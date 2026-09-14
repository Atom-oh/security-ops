"""Observe safe parse metadata, then forward the reviewed BASE record unchanged."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import re
import runpy
import subprocess
import sys

BASE = "df7fa504471a997a34db93f275865eff78c2c74c"
PARSE_CODES = {
    "malformed_json", "duplicate_json_key", "nonfinite_json",
    "invalid_json_wrapper", "empty_response",
}
JSON_MESSAGES = {
    "Expecting value", "Extra data", "Invalid \\escape",
    "Invalid control character at", "Unterminated string starting at",
    "Expecting property name enclosed in double quotes",
    "Expecting ':' delimiter", "Expecting ',' delimiter",
    "Invalid \\uXXXX escape", "Unexpected UTF-8 BOM (decode using utf-8-sig)",
}


def content_kind(text):
    text = text.lstrip()
    if not text:
        return "empty"
    if text.startswith("```"):
        return "fence"
    first = text[0]
    if first in '{"[':
        return {'{': "object", '[': "array", '"': "string"}[first]
    if first in "-0123456789":
        return "number"
    if text in ("true", "false", "null", "NaN", "Infinity", "-Infinity"):
        return "literal"
    return "prose" if first.isalpha() else "other"


def metadata(raw, engine):
    text = raw.decode("utf-8")
    result = {
        "byte_length": len(raw),
        "parse_response_error": None,
        "json_decode_error": None,
        "first_content_kind": content_kind(
            "\n".join(re.sub(r"^\s*> ?", "", line) for line in text.splitlines()).strip()),
        "ordinary_json_parses": False,
        "ordinary_json_parses_but_strict_rejects": False,
        "normalized_json_available": False,
    }
    strict = engine.strict_json

    def observe(normalized):
        # BASE parse_response supplies its exact post-transport/fence text here.
        result["normalized_json_available"] = True
        result["first_content_kind"] = content_kind(normalized)
        try:
            json.loads(normalized)
            result["ordinary_json_parses"] = True
        except json.JSONDecodeError as error:
            result["json_decode_error"] = {
                "msg": error.msg if error.msg in JSON_MESSAGES else "Other JSON syntax error",
                "line": error.lineno, "column": error.colno, "offset": error.pos,
            }
        except (ValueError, TypeError, RecursionError):
            pass
        try:
            return strict(normalized)
        except engine.Invalid:
            result["ordinary_json_parses_but_strict_rejects"] = result["ordinary_json_parses"]
            raise

    engine.strict_json = observe
    try:
        engine.parse_response(text)
    except engine.Invalid as error:
        result["parse_response_error"] = str(error) if str(error) in PARSE_CODES else "other_parse_error"
    finally:
        engine.strict_json = strict
    return result


def record_wrapper(original, engine_path, work, engine):
    engine_path, work = Path(engine_path).resolve(), Path(work).resolve()

    def run(*args, **kwargs):
        command = args[0] if args else kwargs.get("args")
        try:
            if (isinstance(command, (list, tuple)) and len(command) > 2
                    and command[0] == sys.executable
                    and Path(command[1]).resolve() == engine_path and command[2] == "record"
                    and command[command.index("--tag") + 1] == "kiro-fable"
                    and Path(command[command.index("--work") + 1]).resolve() == work):
                output = Path(command[command.index("--output") + 1])
                if (not output.is_symlink() and output.parent.resolve() == work.parent
                        and output.name.startswith("kiro-fable-response-")):
                    safe = metadata(output.read_bytes(), engine)
                    (work / "slot/kiro-fable-parse-metadata.json").write_text(
                        json.dumps(safe, sort_keys=True) + "\n")
        except Exception:
            # Observation must never replace or suppress the original record.
            # Do not print exception text: it could contain response values.
            pass
        return original(*args, **kwargs)

    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--tag", choices=("kiro-fable",), required=True)
    args = parser.parse_args()
    source, work = args.source.resolve(), args.work.resolve()
    scripts = source / "scripts/pr-review"
    for name in ("role_review.py", "run_role.py"):
        expected = subprocess.check_output(
            ["git", "show", f"{BASE}:scripts/pr-review/{name}"], cwd=source)
        if (scripts / name).read_bytes() != expected:
            raise ValueError("Diagnostic requires unchanged reviewed BASE files")
    spec = importlib.util.spec_from_file_location("parse_metadata_base", scripts / "role_review.py")
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    original = subprocess.run
    subprocess.run = record_wrapper(original, scripts / "role_review.py", work, engine)
    sys.path.insert(0, str(scripts))
    sys.argv = [str(scripts / "run_role.py"), "--work", str(work), "--tag", args.tag]
    try:
        runpy.run_path(str(scripts / "run_role.py"), run_name="__main__")
    finally:
        subprocess.run = original


if __name__ == "__main__":
    main()
