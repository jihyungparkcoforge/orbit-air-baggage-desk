"""Command line entry point for the baggage desk.

This is the only place that reads the real clock. Every rule lives in claims.py.
"""

import argparse
import sqlite3
import sys
from datetime import UTC, datetime

import claims
import db


def _naive_utc(moment):
    """UTC with no tzinfo and no microseconds, so printed times look like 2026-11-02T09:00:00."""
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.replace(tzinfo=None, microsecond=0)


def _parse_now(text):
    try:
        return _naive_utc(datetime.fromisoformat(text))
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"not an ISO 8601 timestamp: {text!r}") from error


def _cmd_file(conn, args, now):
    claim_id = claims.file_claim(
        conn, args.passenger, args.flight, args.type, args.tier, args.note, by=args.by, now=now
    )
    claim = claims.get_claim(conn, claim_id)
    print(f"Filed claim {claim.id} ({claim.tier}), deadline {claim.deadline.isoformat()}.")


def _cmd_list(conn, args, now):
    found = claims.list_claims(conn, status=args.status, tier=args.tier)
    if not found:
        print("No claims found.")
        return
    print(f"{'ID':>4}  {'PASSENGER':<20}  {'FLIGHT':<7}  {'TYPE':<8}  {'TIER':<8}  "
          f"{'STATUS':<9}  {'AGENT':<16}  DEADLINE")
    for c in found:
        print(f"{c.id:>4}  {c.passenger:<20}  {c.flight:<7}  {c.claim_type:<8}  {c.tier:<8}  "
              f"{c.status:<9}  {c.agent or '-':<16}  {c.deadline.isoformat()}")


def _cmd_assign(conn, args, now):
    claim = claims.assign_claim(conn, args.id, args.agent, by=args.by, now=now)
    print(f"Assigned claim {claim.id} to {claim.agent}.")


def _cmd_resolve(conn, args, now):
    claim = claims.resolve_claim(conn, args.id, by=args.by, now=now)
    print(f"Resolved claim {claim.id}.")


def _cmd_close(conn, args, now):
    claim = claims.close_claim(conn, args.id, by=args.by, now=now)
    print(f"Closed claim {claim.id}.")


def _cmd_escalate(conn, args, now):
    escalated = claims.escalate_overdue(conn, by=args.by, now=now)
    if escalated:
        print(f"Escalated {len(escalated)} claim(s): {', '.join(map(str, escalated))}")
    else:
        print("No overdue claims to escalate.")


def _cmd_history(conn, args, now):
    claim = claims.get_claim(conn, args.id)  # an unknown id is an error, not empty output
    print(f"Claim {claim.id}: {claim.passenger}, {claim.flight}, {claim.claim_type}, "
          f"{claim.tier}, {claim.status}")
    if claim.note:
        print(f"Note: {claim.note}")
    for entry in claims.get_history(conn, claim.id):
        print(f"{entry.changed_at.isoformat()}  {entry.old_status or '-'} -> "
              f"{entry.new_status}  by {entry.changed_by}")


def _cmd_seed(conn, args, now):
    count = claims.seed_claims(conn, args.path, by=args.by, now=now)
    print(f"Loaded {count} claims from {args.path}.")


# STRETCH GOAL 2
def _cmd_report(conn, args, now):
    print(f"Report at {now.isoformat()}")
    print(f"{'TIER':<10}  {'OPEN':>4}  {'OVERDUE':>7}")
    for tier, open_count, overdue in claims.tier_report(conn, now=now):
        print(f"{tier:<10}  {open_count:>4}  {overdue:>7}")


def build_parser():
    parser = argparse.ArgumentParser(prog="main.py", description="Orbit Air baggage claims desk.")
    parser.add_argument("--now", type=_parse_now, metavar="ISO_TIMESTAMP",
                        help="pretend the current time is this (UTC if no offset is given)")
    parser.add_argument("--db", default="baggage_desk.db", metavar="PATH",
                        help="SQLite database file (default: baggage_desk.db)")
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name, handler, help_text, *, by=False):
        sub = commands.add_parser(name, help=help_text)
        sub.set_defaults(handler=handler)
        if by:
            sub.add_argument("--by", default="desk", metavar="NAME",
                             help="who is making the change (default: desk)")
        return sub

    sub = command("file", _cmd_file, "file a new claim", by=True)
    sub.add_argument("passenger")
    sub.add_argument("flight")
    sub.add_argument("type", metavar="type", help=", ".join(claims.CLAIM_TYPES))
    sub.add_argument("tier", help=", ".join(claims.TIERS))
    sub.add_argument("--note", default="")

    sub = command("list", _cmd_list, "list claims")
    sub.add_argument("--status", help=", ".join(claims.STATUSES))
    sub.add_argument("--tier", help=", ".join(claims.TIERS))

    sub = command("assign", _cmd_assign, "assign a claim to an agent", by=True)
    sub.add_argument("id", type=int)
    sub.add_argument("agent")

    sub = command("resolve", _cmd_resolve, "mark a claim resolved", by=True)
    sub.add_argument("id", type=int)

    sub = command("close", _cmd_close, "close a resolved claim", by=True)
    sub.add_argument("id", type=int)

    command("escalate", _cmd_escalate, "escalate every overdue claim", by=True)

    sub = command("history", _cmd_history, "show a claim's status history")
    sub.add_argument("id", type=int)

    sub = command("seed", _cmd_seed, "load claims from a CSV file", by=True)
    sub.add_argument("path")

    command("report", _cmd_report, "open and overdue counts per tier")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    now = args.now if args.now is not None else _naive_utc(datetime.now(UTC))

    conn = None
    try:
        conn = db.connect(args.db)
        db.init_db(conn)
        args.handler(conn, args, now)
    except (claims.ClaimError, sqlite3.Error, OSError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    finally:
        if conn is not None:
            conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
