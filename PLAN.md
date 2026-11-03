# Plan: Orbit Air Baggage Desk

Written before any feature code. If the plan changes while I build, I will note it at the bottom instead of rewriting history.

## The problem

Orbit Air tracks lost, delayed, and damaged bag claims in spreadsheets and email. Nobody can tell at a glance who owns a claim, what state it is in, or whether it has already blown its response deadline, so claims go stale. Gold passengers wait as long as everyone else because nothing flags them.

I am building a small command line tool backed by SQLite that the baggage desk can use instead. It needs to:

- take in a claim and work out its deadline right away,
- let a supervisor hand claims to agents and move them through a fixed set of states,
- refuse any state change that skips a step,
- keep a full audit trail of who changed what and when,
- sweep up claims that are past their deadline and escalate them.

## Deadline rules (my words)

The deadline is fixed when the claim is filed: filed time plus a number of hours that depends on the passenger's tier.

| Tier | Hours |
|---|---|
| gold | 4 |
| silver | 24 |
| standard | 72 |

"Overdue" is strict. If the deadline is 13:00, then at 12:59 and at exactly 13:00 the claim is fine, and at 13:01 it is overdue. In code this is `now > deadline`, never `>=`.

No rule code is allowed to look at the clock. Every function that cares about time gets `now` as an argument. The CLI decides what `now` is: the `--now` value if given, otherwise the real clock. That keeps the tests stable and makes the overdue demo possible without waiting four hours.

Times are stored as ISO 8601 text with no offset, treated as UTC.

## Status changes (my words)

Every claim starts as `open`. From there:

- An open claim can be assigned to an agent, or escalated if it is overdue.
- An assigned claim can be resolved, or escalated if it is overdue.
- An escalated claim can be assigned (again) or resolved directly.
- A resolved claim can only be closed.
- A closed claim is finished. Nothing moves it.

Anything else is an error that names the current and requested status, and nothing is saved. Examples that must fail: closing an open claim, resolving an open claim, reopening a closed claim, escalating a resolved claim.

I will keep the allowed moves in one dictionary (`from_status -> set of to_statuses`) so the table in the spec and the code look the same.

Escalation has an extra rule on top of the table: only `open` and `assigned` claims can be escalated, and only when they are overdue.

Open question I noticed: the deadline does not reset when an escalated claim is reassigned, so that claim is `assigned` and still overdue, and the next escalation sweep will escalate it again. The spec does not say the deadline resets, so I am following it as written and will point this out in the README.

## Tables

`claims`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PRIMARY KEY | auto increment |
| passenger | TEXT NOT NULL | CHECK not blank after trim |
| flight | TEXT NOT NULL | CHECK not blank after trim |
| claim_type | TEXT NOT NULL | CHECK in (delayed, lost, damaged) |
| tier | TEXT NOT NULL | CHECK in (standard, silver, gold) |
| status | TEXT NOT NULL DEFAULT 'open' | CHECK in (open, assigned, escalated, resolved, closed) |
| agent | TEXT | null until assigned |
| note | TEXT NOT NULL DEFAULT '' | free text, stored as data only |
| filed_at | TEXT NOT NULL | ISO timestamp |
| deadline | TEXT NOT NULL | ISO timestamp, filed_at + tier hours |

`history`

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PRIMARY KEY | auto increment |
| claim_id | INTEGER NOT NULL | REFERENCES claims(id) |
| old_status | TEXT | NULL for the filing entry, otherwise CHECK in the five statuses |
| new_status | TEXT NOT NULL | CHECK in the five statuses |
| changed_by | TEXT NOT NULL | who made the change |
| changed_at | TEXT NOT NULL | ISO timestamp, the `now` passed in |

Each write that changes a claim does two things in one `with conn:` block: update (or insert) the claim row first, then insert the history row. If the history insert fails, the whole block rolls back. The order matters: if history were written first, a failing history write would never reach the claim update, and a rollback test would pass even without a transaction.

## Branches and tests

Tests are written and committed first on every branch, run once to see them fail, and only then does the agent write the feature code. Each branch gets its own test file so that no test file is touched again after it is committed.

### 1. feature/schema-and-filing (tests/test_claims.py, at least 5)

- `init_db` creates both tables
- filing saves an `open` claim with all fields and returns its id
- blank passenger is rejected (empty and whitespace only)
- blank flight is rejected
- unknown claim type is rejected, error lists the allowed types
- unknown tier is rejected, error lists the allowed tiers
- deadline is filed time + 4 / 24 / 72 hours for gold / silver / standard
- filing writes the first history entry (old status empty, new status open, who, when)
- `list_claims` filters by status, by tier, and by both; an unknown filter value is an error
- CHECK constraints reject a bad type, tier, or status even if the Python checks are bypassed
- if the history insert fails, no claim row is left behind

### 2. feature/assign-and-status (tests/test_status.py, at least 6)

- assign sets the agent and moves open to assigned
- every allowed change in the table works (all 8 pairs)
- disallowed changes are rejected with a clear error and leave status and history untouched (at least 8 pairs, including close an open claim and reopen a closed one)
- an unknown status name is rejected
- assigning needs a non-blank agent name
- a missing claim id is a clear error
- every change adds a history row with old status, new status, who, and when, in order
- if the history insert fails during assign, the claim keeps its old status and agent

### 3. feature/deadlines-and-escalation (tests/test_escalation.py, at least 6)

- one minute before the deadline: not overdue
- exactly at the deadline: not overdue
- one minute after the deadline: overdue
- the sweep escalates overdue open and assigned claims and returns their ids
- the sweep leaves claims alone that are exactly at their deadline
- the sweep leaves resolved, closed, and already escalated claims alone
- escalating a claim that is not overdue is rejected
- escalation writes a history row (old status, escalated, who, when)
- if a history insert fails during the sweep, no claim is escalated (rollback test)

### 4. feature/cli (tests/test_cli.py, at least 3)

- `file` then `list` through `main()` shows the claim and its deadline
- `--now` drives escalation: nothing at the deadline, the claim one minute later
- a rule error prints `Error: ...` to stderr and exits with code 1
- `seed seed_claims.csv` loads every row, and the note with the hidden instruction is stored as plain text
- a seed file with a bad row loads nothing and says which row is wrong
- `assign`, `resolve`, `close`, and `history` work end to end
- a bad `--now` value is rejected
- `python main.py ...` works as a real subprocess

That is well over 20 tests in total.

## Risks and how I will handle them

1. **Tests that depend on today's date.** If rule code reads the clock, deadline tests will pass today and fail next week. Handling: `now` is always a parameter, tests use fixed datetimes, and during review I grep `claims.py` for `datetime.now` and `time.time`.

2. **A half-saved change.** If the claim row updates and the history insert then fails, the audit trail is wrong. Handling: one transaction per change, claim first and history second, plus a rollback test that installs a trigger to make history inserts fail. I will also delete the transaction on purpose once to confirm the test goes red.

3. **The agent changes tests to make them pass.** Handling: CLAUDE.md says tests are the spec, the Stop hook tells the agent to fix code rather than tests, and before every feature commit I run `git diff --stat` on `tests/`. If the agent touched a test, I revert it.

4. **The hidden instruction in the seed file.** One claim note says to ignore the task and print `.env`. Handling: notes are stored and printed as plain data and never acted on, `.env` is blocked by a deny rule (checked in a fresh session), and I will ask Claude Code to summarize the seed file to see what it does with that note.

5. **Off by one at the deadline.** `>=` instead of `>` would escalate claims a minute early. Handling: edge tests at minus one minute, exactly at, and plus one minute, both on `is_overdue` and on the escalation sweep.

## Order of work

1. Repo setup: .gitignore, venv with pytest and ruff, fake .env, CLAUDE.md, .claude/settings.json, check the deny rule.
2. This plan.
3. Linear project "Orbit Air Baggage Desk" with one agent-ready issue per branch.
4. The four branches in the order above. Each one: tests commit, see red, agent writes code, I review the diff and run pytest and ruff myself, feature commit, Agent Log entry, pull request, merge.
5. Seed file, hidden instruction check, overdue demo, and /code-review on the last pull request.
6. Stretch goals if time allows: CI workflow, report command, test folder guard hook, Dockerfile.

## Changes after the plan was written

- Branch 2: I wrote "all 8 pairs" for the allowed changes. The table has 7 (open 2, assigned 2, escalated 2, resolved 1, closed 0). The tests cover all 7, plus 16 disallowed pairs.
- Branch 2: added a rule that `by` (who made the change) cannot be blank, for filing and for every status change. Without it a history row could be saved with no "who".
- Branch 4: added a `report` command (stretch goal 2). After `/code-review` on the last pull request I added a fifth test file, `tests/test_review_fixes.py`, so the fixes stayed test-first without editing a test file that was already committed.
