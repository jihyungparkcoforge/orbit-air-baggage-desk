"""feature/deadlines-and-escalation: strict overdue rule, escalation sweep, history, rollback."""

import sqlite3
from datetime import datetime, timedelta

import pytest

import claims

FILED_AT = datetime(2026, 11, 2, 9, 0)
GOLD_DEADLINE = FILED_AT + timedelta(hours=4)  # 13:00
ONE_MINUTE = timedelta(minutes=1)
EARLY = FILED_AT + timedelta(hours=1)  # before any deadline


def file_one(conn, tier="gold"):
    return claims.file_claim(
        conn, "Fatima Zahra", "OA730", "damaged", tier, by="desk", now=FILED_AT
    )


def status_of(conn, claim_id):
    return claims.get_claim(conn, claim_id).status


def test_one_minute_before_the_deadline_is_not_overdue():
    assert claims.is_overdue(GOLD_DEADLINE, GOLD_DEADLINE - ONE_MINUTE) is False


def test_exactly_at_the_deadline_is_not_overdue():
    assert claims.is_overdue(GOLD_DEADLINE, GOLD_DEADLINE) is False


def test_one_minute_after_the_deadline_is_overdue():
    assert claims.is_overdue(GOLD_DEADLINE, GOLD_DEADLINE + ONE_MINUTE) is True


@pytest.mark.parametrize("tier, hours", [("gold", 4), ("silver", 24), ("standard", 72)])
def test_deadline_edge_for_every_tier(conn, tier, hours):
    deadline = claims.get_claim(conn, file_one(conn, tier)).deadline
    assert deadline == FILED_AT + timedelta(hours=hours)

    assert claims.is_overdue(deadline, deadline - ONE_MINUTE) is False
    assert claims.is_overdue(deadline, deadline) is False
    assert claims.is_overdue(deadline, deadline + ONE_MINUTE) is True


def test_sweep_escalates_overdue_open_and_assigned_claims(conn):
    open_id = file_one(conn)
    assigned_id = file_one(conn)
    claims.assign_claim(conn, assigned_id, "Priya Nair", by="supervisor", now=EARLY)

    escalated = claims.escalate_overdue(conn, by="system", now=GOLD_DEADLINE + ONE_MINUTE)

    assert escalated == [open_id, assigned_id]
    assert status_of(conn, open_id) == "escalated"
    assert status_of(conn, assigned_id) == "escalated"


def test_sweep_exactly_at_the_deadline_escalates_nothing(conn):
    claim_id = file_one(conn)

    assert claims.escalate_overdue(conn, by="system", now=GOLD_DEADLINE) == []
    assert status_of(conn, claim_id) == "open"


def test_sweep_only_touches_claims_past_their_own_deadline(conn):
    gold = file_one(conn, "gold")
    silver = file_one(conn, "silver")
    standard = file_one(conn, "standard")

    one_day_and_a_minute = FILED_AT + timedelta(hours=24) + ONE_MINUTE
    assert claims.escalate_overdue(conn, by="system", now=one_day_and_a_minute) == [gold, silver]
    assert status_of(conn, standard) == "open"


def test_sweep_leaves_resolved_closed_and_escalated_claims_alone(conn):
    resolved = file_one(conn)
    claims.assign_claim(conn, resolved, "Priya Nair", by="supervisor", now=EARLY)
    claims.resolve_claim(conn, resolved, by="Priya Nair", now=EARLY)

    closed = file_one(conn)
    claims.assign_claim(conn, closed, "Priya Nair", by="supervisor", now=EARLY)
    claims.resolve_claim(conn, closed, by="Priya Nair", now=EARLY)
    claims.close_claim(conn, closed, by="supervisor", now=EARLY)

    escalated = file_one(conn)
    claims.change_status(
        conn, escalated, "escalated", by="supervisor", now=GOLD_DEADLINE + ONE_MINUTE
    )

    five_days_later = FILED_AT + timedelta(days=5)
    assert claims.escalate_overdue(conn, by="system", now=five_days_later) == []
    assert status_of(conn, resolved) == "resolved"
    assert status_of(conn, closed) == "closed"
    assert status_of(conn, escalated) == "escalated"
    assert len(claims.get_history(conn, escalated)) == 2


@pytest.mark.parametrize("assign_first", [False, True])
def test_escalating_a_claim_that_is_not_overdue_is_rejected(conn, assign_first):
    claim_id = file_one(conn)
    if assign_first:
        claims.assign_claim(conn, claim_id, "Priya Nair", by="supervisor", now=EARLY)
    status_before = status_of(conn, claim_id)
    history_before = claims.get_history(conn, claim_id)

    with pytest.raises(claims.ClaimError, match="overdue"):
        claims.change_status(conn, claim_id, "escalated", by="supervisor", now=GOLD_DEADLINE)

    assert status_of(conn, claim_id) == status_before
    assert claims.get_history(conn, claim_id) == history_before


def test_escalation_writes_a_history_entry_for_each_claim(conn):
    open_id = file_one(conn)
    assigned_id = file_one(conn)
    claims.assign_claim(conn, assigned_id, "Priya Nair", by="supervisor", now=EARLY)
    now = GOLD_DEADLINE + ONE_MINUTE

    claims.escalate_overdue(conn, by="system", now=now)

    last_open = claims.get_history(conn, open_id)[-1]
    last_assigned = claims.get_history(conn, assigned_id)[-1]
    assert (last_open.old_status, last_open.new_status, last_open.changed_by) == (
        "open",
        "escalated",
        "system",
    )
    assert last_open.changed_at == now
    assert (last_assigned.old_status, last_assigned.new_status, last_assigned.changed_by) == (
        "assigned",
        "escalated",
        "system",
    )
    assert last_assigned.changed_at == now


def test_sweep_with_no_claims_returns_an_empty_list(conn):
    assert claims.escalate_overdue(conn, by="system", now=FILED_AT) == []


def test_failed_history_write_rolls_back_the_whole_sweep(conn, break_history):
    first = file_one(conn)
    second = file_one(conn)
    break_history()

    with pytest.raises(sqlite3.Error):
        claims.escalate_overdue(conn, by="system", now=GOLD_DEADLINE + ONE_MINUTE)

    assert status_of(conn, first) == "open"
    assert status_of(conn, second) == "open"
    assert len(claims.get_history(conn, first)) == 1
    assert len(claims.get_history(conn, second)) == 1
