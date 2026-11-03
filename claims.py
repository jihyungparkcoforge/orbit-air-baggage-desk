"""Claim rules: filing, deadlines, lookups, and history.

No function here reads the clock. Anything that needs the current time takes `now`.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

CLAIM_TYPES = ("delayed", "lost", "damaged")
TIERS = ("standard", "silver", "gold")
STATUSES = ("open", "assigned", "escalated", "resolved", "closed")
DEADLINE_HOURS = {"gold": 4, "silver": 24, "standard": 72}
ALLOWED_CHANGES = {
    "open": {"assigned", "escalated"},
    "assigned": {"resolved", "escalated"},
    "escalated": {"assigned", "resolved"},
    "resolved": {"closed"},
    "closed": set(),
}


class ClaimError(ValueError):
    """A claim request broke a rule. The message is meant for the desk user."""


@dataclass(frozen=True)
class Claim:
    id: int
    passenger: str
    flight: str
    claim_type: str
    tier: str
    status: str
    agent: str | None
    note: str
    filed_at: datetime
    deadline: datetime


@dataclass(frozen=True)
class HistoryEntry:
    id: int
    claim_id: int
    old_status: str | None
    new_status: str
    changed_by: str
    changed_at: datetime


def _as_utc(moment):
    """Drop any offset after converting to UTC, matching how times are stored."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC).replace(tzinfo=None)
    return moment


def _to_text(moment):
    """Store times as ISO 8601 with no offset, in UTC."""
    return _as_utc(moment).isoformat()


def _check_choice(value, allowed, name):
    if value not in allowed:
        raise ClaimError(f"Unknown {name} {value!r}. Allowed: {', '.join(allowed)}.")


def _require_text(value, name):
    if not value or not value.strip():
        raise ClaimError(f"{name} must not be blank.")
    return value.strip()


def deadline_for(tier, filed_at):
    """Filed time plus the response hours for the tier."""
    _check_choice(tier, TIERS, "tier")
    return filed_at + timedelta(hours=DEADLINE_HOURS[tier])


def is_overdue(deadline, now):
    """Strict: exactly at the deadline is not overdue, only after it."""
    return _as_utc(now) > _as_utc(deadline)


def file_claim(conn, passenger, flight, claim_type, tier, note="", *, by, now):
    """Save a new open claim and its first history entry. Returns the new claim id."""
    passenger = _require_text(passenger, "passenger")
    by = _require_text(by, "by")
    flight = _require_text(flight, "flight")
    _check_choice(claim_type, CLAIM_TYPES, "claim type")
    _check_choice(tier, TIERS, "tier")
    filed_at = _to_text(now)
    deadline = _to_text(deadline_for(tier, now))

    with conn:
        cursor = conn.execute(
            "INSERT INTO claims (passenger, flight, claim_type, tier, status, note,"
            " filed_at, deadline) VALUES (?, ?, ?, ?, 'open', ?, ?, ?)",
            (passenger, flight, claim_type, tier, note or "", filed_at, deadline),
        )
        claim_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO history (claim_id, old_status, new_status, changed_by, changed_at)"
            " VALUES (?, NULL, 'open', ?, ?)",
            (claim_id, by, filed_at),
        )
    return claim_id


def _claim_from_row(row):
    return Claim(
        id=row["id"],
        passenger=row["passenger"],
        flight=row["flight"],
        claim_type=row["claim_type"],
        tier=row["tier"],
        status=row["status"],
        agent=row["agent"],
        note=row["note"],
        filed_at=datetime.fromisoformat(row["filed_at"]),
        deadline=datetime.fromisoformat(row["deadline"]),
    )


def get_claim(conn, claim_id):
    row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)).fetchone()
    if row is None:
        raise ClaimError(f"No claim with id {claim_id}.")
    return _claim_from_row(row)


def list_claims(conn, status=None, tier=None):
    """All claims in filing order, optionally narrowed by status and/or tier."""
    sql = "SELECT * FROM claims"
    conditions = []
    params = []
    if status is not None:
        _check_choice(status, STATUSES, "status")
        conditions.append("status = ?")
        params.append(status)
    if tier is not None:
        _check_choice(tier, TIERS, "tier")
        conditions.append("tier = ?")
        params.append(tier)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY id"
    return [_claim_from_row(row) for row in conn.execute(sql, params)]


def get_history(conn, claim_id):
    """History entries for one claim, oldest first."""
    rows = conn.execute(
        "SELECT * FROM history WHERE claim_id = ? ORDER BY id", (claim_id,)
    ).fetchall()
    return [
        HistoryEntry(
            id=row["id"],
            claim_id=row["claim_id"],
            old_status=row["old_status"],
            new_status=row["new_status"],
            changed_by=row["changed_by"],
            changed_at=datetime.fromisoformat(row["changed_at"]),
        )
        for row in rows
    ]


def change_status(conn, claim_id, new_status, *, by, now, agent=None):
    """Move a claim to a new status if ALLOWED_CHANGES permits it. Returns the updated claim.

    Moving to assigned needs an agent name, which is stored on the claim.
    Moving to escalated is only allowed once the claim is overdue at `now`.
    """
    _check_choice(new_status, STATUSES, "status")
    by = _require_text(by, "by")
    claim = get_claim(conn, claim_id)
    old_status = claim.status
    if new_status not in ALLOWED_CHANGES[old_status]:
        raise ClaimError(f"cannot change claim {claim_id} from {old_status} to {new_status}")
    if new_status == "escalated" and not is_overdue(claim.deadline, now):
        raise ClaimError(f"cannot escalate claim {claim_id}: it is not overdue")
    if new_status == "assigned":
        agent = _require_text(agent, "agent")
    changed_at = _to_text(now)

    with conn:
        if new_status == "assigned":
            conn.execute(
                "UPDATE claims SET status = ?, agent = ? WHERE id = ?",
                (new_status, agent, claim_id),
            )
        else:
            conn.execute("UPDATE claims SET status = ? WHERE id = ?", (new_status, claim_id))
        conn.execute(
            "INSERT INTO history (claim_id, old_status, new_status, changed_by, changed_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (claim_id, old_status, new_status, by, changed_at),
        )
    return get_claim(conn, claim_id)


def assign_claim(conn, claim_id, agent, *, by, now):
    return change_status(conn, claim_id, "assigned", by=by, now=now, agent=agent)


def resolve_claim(conn, claim_id, *, by, now):
    return change_status(conn, claim_id, "resolved", by=by, now=now)


def close_claim(conn, claim_id, *, by, now):
    return change_status(conn, claim_id, "closed", by=by, now=now)


def escalate_overdue(conn, *, by, now):
    """Escalate every escalatable claim that is overdue at `now`. Returns their ids, ascending.

    All updates and history rows share one transaction, so a failure leaves every claim as it was.
    """
    by = _require_text(by, "by")
    escalatable = [status for status in STATUSES if "escalated" in ALLOWED_CHANGES[status]]
    placeholders = ", ".join("?" for _ in escalatable)
    changed_at = _to_text(now)
    escalated = []

    with conn:
        rows = conn.execute(
            f"SELECT * FROM claims WHERE status IN ({placeholders}) ORDER BY id", escalatable
        ).fetchall()
        for claim in map(_claim_from_row, rows):
            if not is_overdue(claim.deadline, now):
                continue
            conn.execute("UPDATE claims SET status = 'escalated' WHERE id = ?", (claim.id,))
            conn.execute(
                "INSERT INTO history (claim_id, old_status, new_status, changed_by, changed_at)"
                " VALUES (?, ?, 'escalated', ?, ?)",
                (claim.id, claim.status, by, changed_at),
            )
            escalated.append(claim.id)
    return escalated
