"""One supplemental Fable attempt using immutable reviewed BASE executors."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

DIRECTORY = Path(__file__).resolve().parent
MANIFEST = json.loads((DIRECTORY / "manifest.json").read_text())


def restore(work, engine):
    plan = engine.load_plan(work)
    for name in ("head_sha", "base_sha", "plan_digest"):
        if plan[name] != MANIFEST[name]:
            raise ValueError("Frozen input identity differs")
    if (not plan["input_complete"]
            or plan["diff_sha256"] != MANIFEST["input_sha256"]
            or not all(role["required"] for role in plan["roles"].values())):
        raise ValueError("Frozen source or required scope differs")
    for name, digest in MANIFEST["files"].items():
        source = DIRECTORY / "retained" / name
        raw = source.read_bytes()
        if Path(name).name != name or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Retained evidence checksum differs")
        engine.strict_json(raw.decode("utf-8"))
        (work / "slot" / name).write_bytes(raw)
    for tag in plan["roles"]:
        receipt = engine.strict_json((work / "slot" / f"{tag}-request.json").read_text())
        prompt, payload, expected = engine.request_receipt(
            work, plan, tag, receipt["invocation_nonce"])
        if receipt != expected:
            raise ValueError("Retained receipt differs from frozen inputs")
        result = engine.strict_json((work / "slot" / f"{tag}-result.json").read_text())
        if tag in MANIFEST["retained_valid_roles"] and not result["valid"]:
            raise ValueError("Retained required role is not valid")
        if tag == "kiro-fable" and (result["valid"] or result["failure_codes"] != ["malformed_json"]):
            raise ValueError("Only the recorded nonterminal Fable failure may be resumed")
        (work / "requests").mkdir(exist_ok=True)
        (work / "requests" / f"{tag}.prompt").write_bytes(prompt.encode("utf-8"))
        (work / "requests" / f"{tag}.input").write_bytes(payload.encode("utf-8"))


def export(work, public):
    """Copy only the established public evidence allowlist, never raw logs/input."""
    public.mkdir(parents=True, exist_ok=True)
    for pattern in ("*-result.json", "*-request.json", "*-timing.json",
                    "*-attempts.json", "*-parse-metadata.json"):
        for source in (work / "slot").glob(pattern):
            if not source.is_symlink() and source.is_file():
                json.loads(source.read_text())
                shutil.copyfile(source, public / source.name)
    for name in ("role-plan.json", "role-source.json", "role-summary.json", "live-validation.json"):
        source = work / name
        if source.is_file() and not source.is_symlink():
            json.loads(source.read_text())
            shutil.copyfile(source, public / name)


def main():
    os.umask(0o077)
    source, work, public = map(lambda value: Path(value).resolve(), sys.argv[1:4])
    scripts = source / "scripts/pr-review"
    base = MANIFEST["base_sha"]
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source).decode().strip() != base:
        raise ValueError("Checkout is not the immutable reviewed BASE")
    spec = importlib.util.spec_from_file_location("reviewed_engine", scripts / "role_review.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    environment = dict(os.environ, HEAD_SHA=MANIFEST["head_sha"], BASE_SHA=base,
                       GH_REPO="Atom-oh/security-ops", PANEL_RETRIES="1",
                       PANEL_TIMEOUT="300", KIRO_PREFLIGHT_TIMEOUT="60",
                       GITHUB_ENV=str(work / "validation.env"),
                       GITHUB_OUTPUT=str(work / "validation.outputs"),
                       GITHUB_STEP_SUMMARY=str(work / "validation-summary.md"))
    work.mkdir(parents=True, exist_ok=True)
    public.mkdir(parents=True, exist_ok=True)
    binding = {
        **{key: MANIFEST[key] for key in ("head_sha", "base_sha", "plan_digest", "input_sha256")},
        "validation_commit": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "runner_name": os.environ.get("RUNNER_NAME"),
        "pod_hostname": os.environ.get("HOSTNAME"),
        "kind": "Distributed supplemental readiness; never a native PR gate replacement",
        "retained_valid_roles": MANIFEST["retained_valid_roles"],
        "original_runner": MANIFEST["original_runner"],
        "prior_fable_attempts": MANIFEST["prior_fable_attempts"],
        "prior_supplemental_runs": MANIFEST.get("prior_supplemental_runs", []),
        "prior_operator_history": MANIFEST.get("prior_operator_history", []),
        "new_fable_attempt_limit": 1,
        "role_timeout_seconds": 300,
        "kiro_preflight_timeout_seconds": 60,
        "no_pr_head_code_executed": True,
        "readiness_complete": False,
    }
    code = 2
    try:
        with (work / "preparation-private.log").open("wb") as log:
            subprocess.run(
                [sys.executable, str(scripts / "prepare_roles.py"), "--work", str(work)],
                cwd=source, env=environment, stdout=log, stderr=subprocess.STDOUT,
                timeout=120, check=True)
        restore(work, engine)
        initial = subprocess.run(
            [sys.executable, str(scripts / "role_review.py"), "aggregate", "--work", str(work)],
            cwd=source, env=environment, capture_output=True)
        summary = json.loads((work / "role-summary.json").read_text())
        if initial.returncode != 2 or summary["failure_codes"] != ["malformed_json:kiro-fable"]:
            raise ValueError("Retained coverage has an unexpected failure")
        export(work, public / "before-recovery")
        # The wrapper only observes the record boundary; BASE files stay unchanged.
        code = subprocess.run(
            [sys.executable, str(DIRECTORY / "live_base_driver.py"),
             "--source", str(source), "--work", str(work), "--only", "kiro-fable"],
            cwd=source, env=environment).returncode
        if not (work / "slot/kiro-fable-parse-metadata.json").is_file():
            raise ValueError("Safe parse metadata was not captured")
        if (work / "live-validation.json").exists():
            completed = json.loads((work / "live-validation.json").read_text())
            binding["readiness_complete"] = bool(code == 0 and completed["readiness_complete"])
        for tag in MANIFEST["retained_valid_roles"]:
            for suffix in ("result", "request", "timing"):
                name = f"{tag}-{suffix}.json"
                if hashlib.sha256((work / "slot" / name).read_bytes()).hexdigest() != MANIFEST["files"][name]:
                    raise ValueError("An already validated role changed")
    finally:
        export(work, public)
        binding["driver_exit_code"] = code
        (public / "validation-binding.json").write_text(json.dumps(binding, indent=2) + "\n")
    print(json.dumps({"readiness_complete": binding["readiness_complete"], "driver_exit_code": code}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
