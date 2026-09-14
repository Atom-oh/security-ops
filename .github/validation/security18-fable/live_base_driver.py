"""Collect live role evidence with reviewed BASE executors and prepared data."""

import argparse
import base64
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, required=True)
parser.add_argument("--work", type=Path, required=True)
parser.add_argument("--only", choices=("kiro-fable",))
args = parser.parse_args()
source, work = args.source.resolve(), args.work.resolve()
scripts = source / "scripts/pr-review"
plan = json.loads((work / "role-plan.json").read_text())
base, head = plan["base_sha"], plan["head_sha"]
assert subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=source, text=True
).strip() == base
for revision in (base, head):
    subprocess.run(["git", "cat-file", "-e", revision + "^{commit}"],
                   cwd=source, check=True)
context = subprocess.check_output(["git", "show", base + ":CLAUDE.md"], cwd=source)
assert (work / "project-context.md").read_bytes() == context
paths = subprocess.check_output([
    "git", "diff", "--no-renames", "--name-only", "-z",
    plan["provenance"]["merge_base_sha"], head, "--",
], cwd=source).decode().split("\0")
assert set(filter(None, paths)) == set(plan["paths"])
spec = importlib.util.spec_from_file_location("validated_role_engine", scripts / "role_review.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)
engine.load_plan(work)
assert plan["input_complete"]
assert set(plan["roles"]) == {"codex", "claude-self", "kiro-fable", "kiro-sol"}
assert all(role["required"] for role in plan["roles"].values())
tags = (args.only,) if args.only else ("codex", "kiro-fable", "kiro-sol", "claude-self")
if args.only:
    previous = json.loads((work / "slot" / f"{args.only}-result.json").read_text())
    assert not previous["valid"] and previous["failure_codes"] == ["malformed_json"]
    for tag in plan["roles"]:
        receipt = json.loads((work / "slot" / f"{tag}-request.json").read_text())
        prompt, data, expected = engine.request_receipt(
            work, plan, tag, receipt["invocation_nonce"]
        )
        assert receipt == expected
        assert (work / "requests" / f"{tag}.prompt").read_text() == prompt
        assert (work / "requests" / f"{tag}.input").read_text() == data
        if tag != args.only:
            assert json.loads((work / "slot" / f"{tag}-result.json").read_text())["valid"]
assert os.environ.get("KIRO_API_KEY")
assert os.environ.get("AWS_CONTAINER_CREDENTIALS_FULL_URI")
assert os.environ.get("AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE")
assert (Path.home() / ".codex/config.toml").is_file()

# These public settings match the reviewed BASE workflow. Credentials remain in
# their existing delivery channels; no values are printed or copied into inputs.
environment = dict(os.environ)
environment.update(
    CLAUDE_CODE_USE_BEDROCK="1", AWS_REGION="us-east-1",
    AWS_DEFAULT_REGION="us-east-1", PANEL_TIMEOUT="300",
    GITHUB_ENV=str(work / "validation.env"),
    GITHUB_OUTPUT=str(work / "validation.outputs"),
    GITHUB_STEP_SUMMARY=str(work / "validation-step-summary.md"),
)
children, handles = {}, []
libc = ctypes.CDLL(None, use_errno=True)
events = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
assert events >= 0
assert libc.inotify_add_watch(events, os.fsencode(work / "slot"), 0x8 | 0x80 | 0x100 | 0x200) >= 0
receipt_writes = {tag: 0 for tag in tags}
accounting_exact = True

def emit_file(tag, suffix):
    file = work / "slot" / f"{tag}{suffix}"
    if file.is_file():
        encoded = base64.b64encode(file.read_bytes()).decode()
        print(f"FILE\t{file.relative_to(work)}\t{encoded}", flush=True)

def capture_events():
    global accounting_exact
    try:
        data = os.read(events, 65536)
    except BlockingIOError:
        return
    offset = 0
    while offset < len(data):
        _, mask, _, size = struct.unpack_from("iIII", data, offset)
        name = data[offset + 16:offset + 16 + size].split(b"\0", 1)[0].decode()
        offset += 16 + size
        if mask & 0x4000:
            accounting_exact = False
        for tag in tags:
            if mask & (0x8 | 0x80) and name == f"{tag}-request.json":
                receipt_writes[tag] += 1
                emit_file(tag, "-request.json")
                emit_file(tag, "-attempts.json")
                print("ACCOUNTING\t" + json.dumps({
                    "tag": tag, "receipt_writes": receipt_writes[tag],
                    "issued_review_requests": max(0, receipt_writes[tag] - 1),
                    "event_stream_complete": accounting_exact,
                }), flush=True)

try:
    for tag in tags:
        handle = (work / f"validation-{tag}.log").open("w")
        handles.append(handle)
        children[tag] = subprocess.Popen([
            sys.executable, str(Path(__file__).with_name("record_diagnostic.py")),
            "--source", str(source),
            "--work", str(work), "--tag", tag,
        ], cwd=source, env=environment, stdout=handle, stderr=subprocess.STDOUT)
        print(f"{tag}: launched reviewed BASE executor", flush=True)
    exits = {}
    while len(exits) < len(children):
        capture_events()
        for tag, child in children.items():
            if tag in exits or child.poll() is None:
                continue
            exits[tag] = child.returncode
            print(f"{tag}: executor exit {exits[tag]}", flush=True)
            result_file = work / "slot" / f"{tag}-result.json"
            if result_file.exists():
                result = json.loads(result_file.read_text())
                print(json.dumps({"tag": tag, "valid": result["valid"],
                                  "failure_codes": result["failure_codes"]}), flush=True)
                for suffix in ("-result.json", "-timing.json", "-request.json",
                               "-attempts.json", "-parse-metadata.json"):
                    emit_file(tag, suffix)
        if len(exits) < len(children):
            time.sleep(0.1)
finally:
    capture_events()
    os.close(events)
    for handle in handles:
        handle.close()

aggregate = subprocess.run([
    sys.executable, str(scripts / "role_review.py"), "aggregate", "--work", str(work),
], cwd=source, env=environment)
assert aggregate.returncode in (0, 2)
summary = json.loads((work / "role-summary.json").read_text())
results = {
    tag: json.loads((work / "slot" / f"{tag}-result.json").read_text())
    for tag in plan["roles"]
}
evidence = {
    "head_sha": head, "base_sha": base,
    "engine_sha256": hashlib.sha256((scripts / "role_review.py").read_bytes()).hexdigest(),
    "diff_bytes": (work / "role-diff.txt").stat().st_size,
    "context_bytes": len(context), "context_is_exact_base": True,
    "paths": plan["paths"], "executor_exits": exits, "aggregate_mode": summary["mode"],
    "roles": {tag: {
        "valid": value["valid"], "model": value.get("model"),
        "failure_codes": value["failure_codes"],
        "request_digest": value.get("request_digest"),
    } for tag, value in results.items()},
    "no_head_code_executed": True,
    "limits": {
        "role_timeout": 300,
        "role_attempts": int(environment.get("PANEL_RETRIES", "2")),
        "kiro_preflight_timeout": int(environment.get("KIRO_PREFLIGHT_TIMEOUT", "60")),
    },
    "selected_roles": list(tags),
    "new_receipt_writes": receipt_writes,
    "new_review_invocations": {tag: max(0, count - 1) for tag, count in receipt_writes.items()},
    "new_invocation_count_exact": accounting_exact,
}
ready = (aggregate.returncode == 0
         and summary["mode"] in ("deterministic", "review")
         and all(code == 0 for code in exits.values())
         and accounting_exact
         and all(1 <= count - 1 <= int(environment.get("PANEL_RETRIES", "2"))
                 for count in receipt_writes.values())
         and all(value["valid"] for value in results.values()))
evidence["readiness_complete"] = ready
(work / "live-validation.json").write_text(json.dumps(evidence, indent=2) + "\n")
print(json.dumps(evidence, indent=2), flush=True)
# This is readiness evidence, not a replacement for the native PR review gate.
raise SystemExit(0 if ready else 2)
