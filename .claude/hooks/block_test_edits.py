#!/usr/bin/env python3
# STRETCH GOAL 1: PreToolUse hook that stops Claude from editing anything in tests/.
"""Claude Code passes the tool call as JSON on stdin. Exit code 2 blocks the call and
sends the message on stderr back to Claude. Any other path is let through (exit 0)."""

import json
import os
import sys
from pathlib import Path

event = json.load(sys.stdin)
tool_input = event.get("tool_input") or {}
target = tool_input.get("file_path") or tool_input.get("notebook_path")
if not target:
    sys.exit(0)

project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd") or ".").resolve()
tests_dir = project / "tests"
path = Path(target)
if not path.is_absolute():
    path = Path(event.get("cwd") or project) / path
path = path.resolve()

if path == tests_dir or tests_dir in path.parents:
    print(
        f"Blocked: {path.relative_to(project)} is in tests/. The tests are the spec. "
        "Change the code to make them pass. If you think a test is wrong, stop and say why.",
        file=sys.stderr,
    )
    sys.exit(2)
sys.exit(0)
