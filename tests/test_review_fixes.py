"""Fixes for the /code-review findings on the feature/cli pull request (PR #4)."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

import claims
import main

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".claude" / "hooks" / "block_test_edits.py"
FILED_AT = datetime(2026, 11, 2, 9, 0)
HEADER = "passenger,flight,type,tier,note\n"


def write_csv(tmp_path, text):
    path = tmp_path / "claims.csv"
    path.write_text(text)
    return path


def run_cli(db_path, capsys, *args, now="2026-11-02T09:00:00"):
    code = main.main(["--db", str(db_path), "--now", now, *args])
    out, err = capsys.readouterr()
    return code, out, err


# claims.py


def test_bad_input_to_file_claim_leaves_the_callers_pending_work_alone(conn):
    claim_id = claims.file_claim(
        conn, "Maria Gonzalez", "OA101", "lost", "gold", by="desk", now=FILED_AT
    )
    conn.execute("UPDATE claims SET note = 'pending' WHERE id = ?", (claim_id,))  # not committed

    with pytest.raises(claims.ClaimError):
        claims.file_claim(
            conn, "Kenji Watanabe", "OA215", "delayed", "platinum", by="desk", now=FILED_AT
        )

    assert claims.get_claim(conn, claim_id).note == "pending"


def test_seed_row_numbers_match_the_file_when_it_has_blank_lines(conn, tmp_path):
    path = write_csv(
        tmp_path,
        HEADER + "Maria Gonzalez,OA101,lost,gold,ok\n\nKenji Watanabe,OA215,delayed,platinum,x\n",
    )

    with pytest.raises(claims.ClaimError, match="row 4"):
        claims.seed_claims(conn, path, by="desk", now=FILED_AT)


def test_seed_checks_by_once_and_does_not_blame_a_row(conn, tmp_path):
    header_only = write_csv(tmp_path, HEADER)

    with pytest.raises(claims.ClaimError, match="by") as error:
        claims.seed_claims(conn, header_only, by=" ", now=FILED_AT)
    assert "row" not in str(error.value)

    with pytest.raises(claims.ClaimError, match="by") as error:
        claims.seed_claims(conn, ROOT / "seed_claims.csv", by=" ", now=FILED_AT)
    assert "row" not in str(error.value)
    assert claims.list_claims(conn) == []


def test_seed_accepts_spaces_around_header_names_and_values(conn, tmp_path):
    path = write_csv(
        tmp_path, "passenger, flight, type, tier, note\nMaria Gonzalez, OA101, lost, gold, Red\n"
    )

    assert claims.seed_claims(conn, path, by="desk", now=FILED_AT) == 1
    [claim] = claims.list_claims(conn)
    assert (claim.flight, claim.claim_type, claim.tier) == ("OA101", "lost", "gold")


def test_seed_rejects_a_row_with_fewer_fields_than_the_header(conn, tmp_path):
    path = write_csv(tmp_path, HEADER + "Maria Gonzalez,OA101,lost,gold\n")

    with pytest.raises(claims.ClaimError, match="row 2.*fewer fields"):
        claims.seed_claims(conn, path, by="desk", now=FILED_AT)
    assert claims.list_claims(conn) == []


# main.py


def test_now_that_cannot_be_converted_to_utc_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        main.main(["--db", str(tmp_path / "x.db"), "--now", "0001-01-01T00:00:00+05:00", "list"])

    assert exit_info.value.code == 2


def test_deadline_past_the_last_supported_date_is_a_clean_error(tmp_path, capsys):
    code, _, err = run_cli(
        tmp_path / "x.db", capsys, "file", "Maria Gonzalez", "OA101", "lost", "gold",
        now="9999-12-31T22:00:00",
    )

    assert code == 1
    assert err.startswith("Error:")


def test_control_characters_from_claim_data_are_not_printed_raw(tmp_path, capsys):
    db_path = tmp_path / "x.db"
    run_cli(
        db_path, capsys, "file", "Maria\x1b[31m Gonzalez", "OA101", "lost", "gold",
        "--note", "Bag torn\x1b[2J\x1b]52;c;ZXZpbA==\x07",
    )

    _, history_out, _ = run_cli(db_path, capsys, "history", "1")
    _, list_out, _ = run_cli(db_path, capsys, "list")

    for out in (history_out, list_out):
        assert "\x1b" not in out
        assert "\x07" not in out
        assert "Maria" in out
    assert "Bag torn" in history_out


# .claude/hooks/block_test_edits.py


def run_hook(payload, *, project_env=True, cwd=ROOT):
    env = {key: value for key, value in os.environ.items() if key != "CLAUDE_PROJECT_DIR"}
    if project_env:
        env["CLAUDE_PROJECT_DIR"] = str(ROOT)
    return subprocess.run(
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True,
        env=env, cwd=cwd,
    )


def edit(path, cwd=ROOT):
    payload = {"tool_name": "Edit", "cwd": str(cwd), "tool_input": {"file_path": str(path)}}
    return json.dumps(payload)


def test_hook_blocks_the_tests_folder_in_any_letter_case():
    assert run_hook(edit(ROOT / "Tests" / "test_cli.py")).returncode == 2


def test_hook_blocks_when_it_cannot_read_its_input():
    assert run_hook("not json").returncode == 2


def test_hook_finds_the_project_without_claude_project_dir():
    target = ROOT / "tests" / "test_cli.py"
    result = run_hook(edit(target, cwd=ROOT / "tests"), project_env=False, cwd=ROOT / "tests")

    assert result.returncode == 2


def test_hook_protects_its_own_script_and_the_settings_file():
    assert run_hook(edit(ROOT / ".claude" / "settings.json")).returncode == 2
    assert run_hook(edit(HOOK)).returncode == 2


def test_hook_still_allows_normal_code_edits():
    assert run_hook(edit(ROOT / "claims.py")).returncode == 0
