"""feature/assign-and-status: assign, resolve, close, allowed changes, history entries."""

import sqlite3
from datetime import datetime, timedelta

import pytest

import claims

FILED_AT = datetime(2026, 11, 2, 9, 0)
# Five days after filing every tier is past its deadline, so escalating is always allowed here.
LATER = FILED_AT + timedelta(days=5)

ALLOWED = [
    ("open", "assigned"),
    ("open", "escalated"),
    ("assigned", "resolved"),
    ("assigned", "escalated"),
    ("escalated", "assigned"),
    ("escalated", "resolved"),
    ("resolved", "closed"),
]

NOT_ALLOWED = [
    ("open", "open"),
    ("open", "resolved"),
    ("open", "closed"),
    ("assigned", "open"),
    ("assigned", "assigned"),
    ("assigned", "closed"),
    ("escalated", "open"),
    ("escalated", "escalated"),
    ("escalated", "closed"),
    ("resolved", "open"),
    ("resolved", "assigned"),
    ("resolved", "escalated"),
    ("closed", "open"),
    ("closed", "assigned"),
    ("closed", "escalated"),
    ("closed", "resolved"),
]

# The moves that take a freshly filed claim to each status.
PATH_TO = {
    "open": [],
    "assigned": ["assigned"],
    "escalated": ["escalated"],
    "resolved": ["assigned", "resolved"],
    "closed": ["assigned", "resolved", "closed"],
}


def file_one(conn):
    return claims.file_claim(
        conn, "Aisha Bello", "OA330", "damaged", "silver", by="desk", now=FILED_AT
    )


def move(conn, claim_id, to):
    agent = "Priya Nair" if to == "assigned" else None
    return claims.change_status(conn, claim_id, to, by="supervisor", now=LATER, agent=agent)


def claim_in(conn, status):
    claim_id = file_one(conn)
    for step in PATH_TO[status]:
        move(conn, claim_id, step)
    assert claims.get_claim(conn, claim_id).status == status
    return claim_id


def test_allowed_changes_table_matches_the_spec():
    assert claims.ALLOWED_CHANGES == {
        "open": {"assigned", "escalated"},
        "assigned": {"resolved", "escalated"},
        "escalated": {"assigned", "resolved"},
        "resolved": {"closed"},
        "closed": set(),
    }


@pytest.mark.parametrize("old, new", ALLOWED)
def test_every_allowed_change_works(conn, old, new):
    claim_id = claim_in(conn, old)

    updated = move(conn, claim_id, new)

    assert updated.status == new
    assert claims.get_claim(conn, claim_id).status == new


@pytest.mark.parametrize("old, new", NOT_ALLOWED)
def test_disallowed_change_is_rejected_and_nothing_is_saved(conn, old, new):
    claim_id = claim_in(conn, old)
    claim_before = claims.get_claim(conn, claim_id)
    history_before = claims.get_history(conn, claim_id)

    with pytest.raises(claims.ClaimError) as error:
        move(conn, claim_id, new)

    assert old in str(error.value)
    assert new in str(error.value)
    assert claims.get_claim(conn, claim_id) == claim_before
    assert claims.get_history(conn, claim_id) == history_before


def test_wrappers_refuse_to_skip_steps(conn):
    claim_id = file_one(conn)

    with pytest.raises(claims.ClaimError, match="from open to closed"):
        claims.close_claim(conn, claim_id, by="supervisor", now=LATER)
    with pytest.raises(claims.ClaimError, match="from open to resolved"):
        claims.resolve_claim(conn, claim_id, by="supervisor", now=LATER)

    assert claims.get_claim(conn, claim_id).status == "open"


def test_assign_sets_the_agent_and_the_status(conn):
    claim_id = file_one(conn)

    updated = claims.assign_claim(conn, claim_id, "Priya Nair", by="supervisor", now=LATER)

    assert updated.status == "assigned"
    assert updated.agent == "Priya Nair"
    assert claims.get_claim(conn, claim_id).agent == "Priya Nair"


def test_resolve_and_close_walk_an_assigned_claim_to_closed(conn):
    claim_id = file_one(conn)
    claims.assign_claim(conn, claim_id, "Priya Nair", by="supervisor", now=LATER)

    assert claims.resolve_claim(conn, claim_id, by="Priya Nair", now=LATER).status == "resolved"
    assert claims.close_claim(conn, claim_id, by="supervisor", now=LATER).status == "closed"
    assert claims.get_claim(conn, claim_id).agent == "Priya Nair"


@pytest.mark.parametrize("agent", ["", "   "])
def test_assign_needs_an_agent_name(conn, agent):
    claim_id = file_one(conn)

    with pytest.raises(claims.ClaimError, match="agent"):
        claims.assign_claim(conn, claim_id, agent, by="supervisor", now=LATER)

    assert claims.get_claim(conn, claim_id).status == "open"


def test_unknown_status_is_rejected(conn):
    claim_id = file_one(conn)

    with pytest.raises(claims.ClaimError, match="archived"):
        claims.change_status(conn, claim_id, "archived", by="supervisor", now=LATER)


def test_changing_a_missing_claim_is_a_clear_error(conn):
    with pytest.raises(claims.ClaimError, match="404"):
        claims.assign_claim(conn, 404, "Priya Nair", by="supervisor", now=LATER)


def test_every_change_adds_a_complete_history_entry_in_order(conn):
    claim_id = file_one(conn)
    at_10, at_11, at_12 = (FILED_AT + timedelta(hours=h) for h in (1, 2, 3))

    claims.assign_claim(conn, claim_id, "Priya Nair", by="supervisor", now=at_10)
    claims.resolve_claim(conn, claim_id, by="Priya Nair", now=at_11)
    claims.close_claim(conn, claim_id, by="supervisor", now=at_12)

    history = claims.get_history(conn, claim_id)
    assert [(e.old_status, e.new_status, e.changed_by, e.changed_at) for e in history] == [
        (None, "open", "desk", FILED_AT),
        ("open", "assigned", "supervisor", at_10),
        ("assigned", "resolved", "Priya Nair", at_11),
        ("resolved", "closed", "supervisor", at_12),
    ]
    assert all(entry.claim_id == claim_id for entry in history)


def test_list_claims_filters_on_the_new_statuses(conn):
    assigned = file_one(conn)
    still_open = file_one(conn)
    claims.assign_claim(conn, assigned, "Priya Nair", by="supervisor", now=LATER)

    assert [c.id for c in claims.list_claims(conn, status="assigned")] == [assigned]
    assert [c.id for c in claims.list_claims(conn, status="open")] == [still_open]


def test_failed_history_write_keeps_the_old_status_and_agent(conn, break_history):
    claim_id = file_one(conn)
    break_history()

    with pytest.raises(sqlite3.Error):
        claims.assign_claim(conn, claim_id, "Priya Nair", by="supervisor", now=LATER)

    claim = claims.get_claim(conn, claim_id)
    assert claim.status == "open"
    assert claim.agent is None
    assert len(claims.get_history(conn, claim_id)) == 1


@pytest.mark.parametrize("who", ["", "   "])
def test_filing_and_changes_must_say_who_made_them(conn, who):
    with pytest.raises(claims.ClaimError, match="by"):
        claims.file_claim(conn, "Aisha Bello", "OA330", "damaged", "silver", by=who, now=FILED_AT)
    assert claims.list_claims(conn) == []

    claim_id = file_one(conn)
    with pytest.raises(claims.ClaimError, match="by"):
        claims.assign_claim(conn, claim_id, "Priya Nair", by=who, now=LATER)
    assert claims.get_claim(conn, claim_id).status == "open"
    assert len(claims.get_history(conn, claim_id)) == 1
