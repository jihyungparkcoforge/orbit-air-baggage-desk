#!/usr/bin/env python3
# STRETCH GOAL 1: PreToolUse hook that stops Claude from editing anything in tests/.
"""Claude Code passes the tool call as JSON on stdin. Exit code 2 blocks the call and
sends the message on stderr back to Claude. Any other path is let through (exit 0).

The hook also protects .claude/settings.json, .claude/settings.local.json, and
.claude/hooks/, so it cannot be switched
off by an edit. Paths are compared without regard to letter case, because macOS treats
Tests/ and tests/ as the same folder. If anything goes wrong, the edit is blocked.
"""

import json
import os
import sys
from pathlib import Path

TESTS_REASON = (
    "is in tests/. The tests are the spec. Change the code to make them pass. "
    "If you think a test is wrong, stop and say why."
)
GUARD_REASON = "is part of the hook that guards tests/. Ask the user to change it."
PROTECTED = (
    (("tests",), TESTS_REASON),
    ((".claude", "settings.json"), GUARD_REASON),
    ((".claude", "settings.local.json"), GUARD_REASON),
    ((".claude", "hooks"), GUARD_REASON),
)


def check(event):
    """Return (exit code, message) for one tool call."""
    tool_input = event.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not target:
        return 0, None

    # This file lives in <project>/.claude/hooks/, two levels below the project root.
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    project = project.resolve()
    path = Path(target)
    if not path.is_absolute():
        path = Path(event.get("cwd") or project) / path
    path = path.resolve()

    project_parts = [part.casefold() for part in project.parts]
    path_parts = [part.casefold() for part in path.parts]
    if path_parts[: len(project_parts)] != project_parts:
        return 0, None
    relative = path_parts[len(project_parts):]
    for prefix, reason in PROTECTED:
        if relative[: len(prefix)] == list(prefix):
            return 2, f"Blocked: {target} {reason}"
    return 0, None


try:
    code, message = check(json.load(sys.stdin))
except Exception as error:  # fail closed: a broken guard must not let edits through
    code, message = 2, f"Blocked: the tests/ guard hook failed ({error!r}), so no edit is allowed."
if message:
    print(message, file=sys.stderr)
sys.exit(code)
