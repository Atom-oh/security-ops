#!/usr/bin/env bash
# PreToolUse (BLOCKING) secret scanner for Write/Edit/MultiEdit.
# Delegates to secret_scan.py so the hook JSON on stdin reaches the scanner. Exits 2 to BLOCK
# a write that contains a likely hardcoded credential in a non-test file.
exec python3 "$(dirname "$0")/secret_scan.py"
