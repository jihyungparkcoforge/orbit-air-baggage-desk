"""feature/schema-and-filing: tables, filing, validation, deadline by tier, list filters."""

import sqlite3
from datetime import datetime, timedelta

import pytest

import claims
import db

FILED_AT = datetime(2026, 11, 2, 9, 0)


def file_one(conn, **overrides):
    fields = {
        "passenger": "Maria Gonzalez",
        "flight": "OA101",
        "claim_type": "lost",
        "tier": "gold",
        "note": "Black suitcase with a red ribbon",
    }
    fields.update(overrides)
    return claims.file_claim(conn, **fields, by="desk", now=FILED_AT)


def ids(found):
    return [claim.id for claim in found]


def test_init_db_creates_both_tables_and_can_run_twice(conn):
    db.init_db(conn)  # second call must not fail or wipe anything

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"claims", "history"} <= tables


def test_file_claim_saves_an_open_claim_with_every_field(conn):
    claim_id = file_one(conn)

    assert isinstance(claim_id, int)
    claim = claims.get_claim(conn, claim_id)
    assert claim.id == claim_id
    assert claim.passenger == "Maria Gonzalez"
    assert claim.flight == "OA101"
    assert claim.claim_type == "lost"
    assert claim.tier == "gold"
    assert claim.status == "open"
    assert claim.agent is None
    assert claim.note == "Black suitcase with a red ribbon"
    assert claim.filed_at == FILED_AT


def test_note_is_optional(conn):
    claim_id = claims.file_claim(
        conn, "Kenji Watanabe", "OA215", "delayed", "standard", by="desk", now=FILED_AT
    )

    assert claims.get_claim(conn, claim_id).note == ""


@pytest.mark.parametrize("passenger", ["", "   "])
def test_blank_passenger_is_rejected(conn, passenger):
    with pytest.raises(claims.ClaimError, match="passenger"):
        file_one(conn, passenger=passenger)

    assert claims.list_claims(conn) == []


@pytest.mark.parametrize("flight", ["", "   "])
def test_blank_flight_is_rejected(conn, flight):
    with pytest.raises(claims.ClaimError, match="flight"):
        file_one(conn, flight=flight)

    assert claims.list_claims(conn) == []


def test_unknown_claim_type_is_rejected_and_allowed_types_are_listed(conn):
    with pytest.raises(claims.ClaimError, match="type") as error:
        file_one(conn, claim_type="stolen")

    for allowed in ("delayed", "lost", "damaged"):
        assert allowed in str(error.value)
    assert claims.list_claims(conn) == []


def test_unknown_tier_is_rejected_and_allowed_tiers_are_listed(conn):
    with pytest.raises(claims.ClaimError, match="tier") as error:
        file_one(conn, tier="platinum")

    for allowed in ("standard", "silver", "gold"):
        assert allowed in str(error.value)
    assert claims.list_claims(conn) == []


@pytest.mark.parametrize("tier, hours", [("gold", 4), ("silver", 24), ("standard", 72)])
def test_deadline_is_filed_time_plus_tier_hours(conn, tier, hours):
    claim = claims.get_claim(conn, file_one(conn, tier=tier))

    assert claim.deadline == FILED_AT + timedelta(hours=hours)
    assert claims.deadline_for(tier, FILED_AT) == FILED_AT + timedelta(hours=hours)


def test_filing_writes_the_first_history_entry(conn):
    claim_id = file_one(conn)

    history = claims.get_history(conn, claim_id)
    assert len(history) == 1
    entry = history[0]
    assert entry.claim_id == claim_id
    assert entry.old_status is None
    assert entry.new_status == "open"
    assert entry.changed_by == "desk"
    assert entry.changed_at == FILED_AT


def test_list_claims_filters_by_status_and_by_tier(conn):
    gold = file_one(conn, tier="gold")
    silver = file_one(conn, tier="silver")
    standard = file_one(conn, tier="standard")
    # Status changes come on a later branch, so move one claim directly in SQL.
    conn.execute("UPDATE claims SET status = 'resolved' WHERE id = ?", (silver,))

    assert ids(claims.list_claims(conn)) == [gold, silver, standard]
    assert ids(claims.list_claims(conn, status="open")) == [gold, standard]
    assert ids(claims.list_claims(conn, tier="silver")) == [silver]
    assert ids(claims.list_claims(conn, status="open", tier="gold")) == [gold]
    assert claims.list_claims(conn, status="closed") == []


def test_list_claims_rejects_unknown_filter_values(conn):
    with pytest.raises(claims.ClaimError, match="status"):
        claims.list_claims(conn, status="archived")
    with pytest.raises(claims.ClaimError, match="tier"):
        claims.list_claims(conn, tier="platinum")


def test_get_claim_with_unknown_id_is_an_error(conn):
    with pytest.raises(claims.ClaimError, match="999"):
        claims.get_claim(conn, 999)


@pytest.mark.parametrize(
    "column, bad_value",
    [("claim_type", "stolen"), ("tier", "platinum"), ("status", "archived"), ("passenger", "   ")],
)
def test_check_constraints_reject_bad_values_written_straight_to_the_table(conn, column, bad_value):
    row = {
        "passenger": "Maria Gonzalez",
        "flight": "OA101",
        "claim_type": "lost",
        "tier": "gold",
        "status": "open",
        "note": "",
        "filed_at": "2026-11-02T09:00:00",
        "deadline": "2026-11-02T13:00:00",
    }
    row[column] = bad_value

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claims"
            " (passenger, flight, claim_type, tier, status, note, filed_at, deadline)"
            " VALUES (:passenger, :flight, :claim_type, :tier,"
            " :status, :note, :filed_at, :deadline)",
            row,
        )


def test_failed_history_write_leaves_no_claim_behind(conn, break_history):
    break_history()

    with pytest.raises(sqlite3.Error):
        file_one(conn)

    assert claims.list_claims(conn) == []
