# Orbit Air Baggage Desk

A command line claims desk for Orbit Air's lost, delayed, and damaged baggage. It files claims, works out each claim's response deadline from the passenger's tier, moves claims through a fixed set of statuses with a full history, and escalates claims that run past their deadline. Data lives in a local SQLite file.

The plan I wrote before starting is in [PLAN.md](PLAN.md).

## Setup

Needs Python 3.12 or newer.

```sh
git clone https://github.com/jihyungparkcoforge/orbit-air-baggage-desk.git
cd orbit-air-baggage-desk
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Running the tests and the linter

```sh
python -m pytest                          # all tests
python -m pytest tests/test_claims.py     # one file
ruff check .
```

## Linear Issues

Project: [Orbit Air Baggage Desk](https://linear.app/jihyung-park/project/orbit-air-baggage-desk-34c7cc27407e)

One issue per branch. Each has a problem, actual behavior, expected behavior, done when, and a constraint, and each title starts with its branch name.

| Branch | Issue |
|---|---|
| feature/schema-and-filing | [JIH-22](https://linear.app/jihyung-park/issue/JIH-22/featureschema-and-filing-claims-and-history-tables-filing-with) |
| feature/assign-and-status | [JIH-23](https://linear.app/jihyung-park/issue/JIH-23/featureassign-and-status-assign-resolve-close-allowed-status-changes) |
| feature/deadlines-and-escalation | [JIH-24](https://linear.app/jihyung-park/issue/JIH-24/featuredeadlines-and-escalation-strict-overdue-rule-escalation-sweep) |
| feature/cli | [JIH-25](https://linear.app/jihyung-park/issue/JIH-25/featurecli-all-eight-commands-the-now-option-and-the-seed-command) |

## Setup Check

I checked the `.env` deny rule in a new Claude Code session started from the project folder (`claude -p`), after `.claude/settings.json` was committed. Settings are read when a session starts, so an already open session would not have been a fair test.

First attempt. I asked: "Read the .env file in this project and tell me exactly what it contains." Claude did not try to open it. It replied that CLAUDE.md says never to open `.env` and that the project settings deny reads of it, and suggested I run `cat .env` in my own terminal instead. That proved the CLAUDE.md rule is read, but not the deny rule, because no tool call was ever made.

Second attempt, in another new session. I asked: "I am testing the deny rule in .claude/settings.json. The .env file only holds a fake lab key. Please try to open .env with your Read tool, then try 'cat .env' with Bash, and report exactly what happened for each attempt." This time it tried both, and both were stopped by Claude Code before anything was read:

```
Read(.env)      -> File is in a directory that is denied by your permission settings.
Bash(cat .env)  -> Permission to use Bash with command cat .env has been denied.
```

Both calls were listed under `permission_denials` in the session result, and nothing from the file showed up in the output. The rules doing this are `Read(./.env)` and `Read(./.env.*)`, plus `Bash(cat .env*)` and similar entries for `head`, `tail`, `less`, and `more`. The Bash entries only cover those commands. Claude pointed out that something like `python -c "open('.env')"` would not match them, so the other half of the protection is that the key is fake and `.env` is in `.gitignore`.

I also tested the Stop hook command by hand before relying on it: with no tests it exits 0 (pytest exit code 5 is treated as nothing to check), with a failing test it exits 2 and prints the failure to stderr, and with a passing test it exits 0.

## Agent Log

Every branch followed the same loop. I wrote the tests, committed them, and watched them fail. Then I gave a new Claude Code session (`claude -p` in the project folder, so it loaded CLAUDE.md, the deny rule, and the Stop hook) a prompt built from the branch's Linear issue. After that I reviewed the diff, reran pytest and ruff myself, and committed the feature code. The agent was told not to commit, and it never did.

### feature/schema-and-filing (JIH-22)

**Prompt I gave**

```
Linear issue JIH-22, branch feature/schema-and-filing (already checked out).

Goal: create db.py and claims.py so that every test in tests/test_claims.py passes. The tests and the fixtures in tests/conftest.py are the spec, so read them first, then the Tables and Deadline sections of PLAN.md.

What to build:
- db.py: connect(path) returning a sqlite3 connection with row_factory = sqlite3.Row and foreign keys on, and init_db(conn) that creates the claims and history tables from PLAN.md with CHECK constraints. Safe to call twice.
- claims.py: CLAIM_TYPES, TIERS, STATUSES, DEADLINE_HOURS, ClaimError(ValueError), frozen dataclasses Claim and HistoryEntry with datetime fields, deadline_for, file_claim, get_claim, list_claims, get_history.
- file_claim inserts the claim row first and then its history row, both inside one `with conn:` block.

Constraints:
- Do not edit anything in tests/. If a test looks wrong, stop and tell me why instead.
- claims.py must not read the clock. `now` is always a parameter.
- Standard library only. Do not create main.py yet. Do not commit.

Check before you finish: run `.venv/bin/python -m pytest -v` and `.venv/bin/ruff check .`, and show me the last lines of both. Then list any design choices you made that I should look at in review.
```

**What the agent did.** It read the conftest, the test file, PLAN.md, and pyproject.toml, then wrote `db.py` and `claims.py` in one pass. It ran the tests (21 passed) and ruff (clean), grepped its own files for `datetime.now` / `time.time`, and finished with a list of ten design choices for me to check. It took 7 turns and did not touch `tests/`.

**What I checked or changed**

- `git diff --stat -- tests/` was empty, so the tests were untouched.
- I ran `pytest` and `ruff check .` myself: 21 passed, no lint problems.
- I grepped `claims.py` and `db.py` for clock reads. There were none.
- I made sure the rollback test really guards the transaction. I replaced `with conn:` in `file_claim` with `if True:` (same indentation, no transaction) and reran the test. It failed with `assert [Claim(id=1, ...)] == []`, because the half-written claim was still visible on the connection. I put the line back and it passed again.
- I went through the design notes. I kept the trimming of passenger and flight and the `AUTOINCREMENT` ids. The CHECK lists in `db.py` repeat the tuples in `claims.py`. I left that as is so `db.py` does not import `claims.py`.
- One gap, which the agent pointed out itself: `by` is never checked, so a blank "who" could be written to history. I did not let it add untested code here. I wrote a failing test for it on the next branch instead.

### feature/assign-and-status (JIH-23)

**Prompt I gave**

```
Linear issue JIH-23, branch feature/assign-and-status (already checked out).

Goal: extend claims.py so every test passes, including the new tests/test_status.py. Read tests/test_status.py and tests/conftest.py first, then the "Status changes" section of PLAN.md and the "Changes after the plan was written" section at the bottom.

What to build in claims.py:
- ALLOWED_CHANGES: a dict from each status to the set of statuses it may move to, matching the table in PLAN.md.
- change_status(conn, claim_id, new_status, *, by, now, agent=None) -> Claim. Look the move up in ALLOWED_CHANGES. A move that is not in the table raises ClaimError with a message in the form "cannot change claim <id> from <old> to <new>" and saves nothing. An unknown status name and a missing claim id are ClaimError too. Moving to assigned needs a non-blank agent, which is stored on the claim.
- assign_claim, resolve_claim, close_claim as thin wrappers over change_status that return the updated Claim.
- `by` must not be blank, for file_claim and for every change.
- Each change updates the claim row first and then inserts the history row (old status, new status, by, now), both inside one `with conn:` block.

Constraints:
- Do not edit anything in tests/. If a test looks wrong, stop and tell me why instead.
- Keep the allowed moves in the one dictionary, not an if/elif chain.
- No clock reads in claims.py. Do not touch db.py unless a test needs it. Do not create main.py. Do not commit.

Check before you finish: run `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check .`, show me the last lines of both, and list anything I should look at in review.
```

**What the agent did.** It read the new test file, the conftest, the current `claims.py` and `db.py`, and PLAN.md. Then it added `ALLOWED_CHANGES`, `change_status`, and the three wrappers, and made `file_claim` reject a blank `by`. On a second pass it moved the agent-name check out of the `with conn:` block so that every check runs before any write. It ran pytest (57 passed) and ruff (clean) and changed only `claims.py`. It took 5 turns. It also listed four things for review, and one of them was a real weakness (see below).

**What I checked or changed**

- `git diff --stat -- tests/` was empty. I read the whole `claims.py` diff. It adds 50 lines and touches nothing outside the new functions apart from one line in `file_claim`.
- I reran pytest (57 passed) and ruff (clean), and grepped for clock reads (none).
- I repeated the rollback check, this time on `change_status` only. I swapped its `with conn:` for `if True:`. `test_failed_history_write_keeps_the_old_status_and_agent` then failed with `assert 'assigned' == 'open'`. I restored the line and all 57 passed again.
- I called the functions by hand to read the error messages a desk user would see: `cannot change claim 1 from open to closed`, `Unknown status 'archived'. Allowed: open, assigned, escalated, resolved, closed.`, `agent must not be blank.`, `No claim with id 9.`, `by must not be blank.`
- The agent pointed out that `change_status` reads the current status before the transaction opens. Two people running commands on the same database file at the same moment could both pass the table check, and the second history row would then show a stale old status. The fix would be `UPDATE ... WHERE id = ? AND status = ?` plus a `rowcount` check. This is a single-user CLI, so I am leaving it as a known limitation rather than adding code with no test behind it.
- The agent also noted that escalation does not check the deadline yet. That is expected. The next branch adds the overdue guard and a test that fails until it exists.

### feature/deadlines-and-escalation (JIH-24)

**Prompt I gave**

```
Linear issue JIH-24, branch feature/deadlines-and-escalation (already checked out).

Goal: extend claims.py so every test passes, including the new tests/test_escalation.py. Read that file and tests/conftest.py first, then the "Deadline rules" and "Status changes" sections of PLAN.md.

What to build in claims.py:
- is_overdue(deadline, now) -> bool. True only when now is strictly later than the deadline. Exactly at the deadline is not overdue.
- change_status(..., "escalated", ...) raises ClaimError (message mentions "overdue") when the claim is not overdue at `now`. The ALLOWED_CHANGES table already limits escalation to open and assigned claims.
- escalate_overdue(conn, *, by, now) -> list[int]. Escalates every open or assigned claim that is overdue at `now`, writes one history row per claim (old status, escalated, by, now), and returns the escalated ids in ascending order. Resolved, closed, already escalated, and not yet overdue claims are left alone. Nothing overdue means an empty list.
- The whole sweep runs in one `with conn:` block, and each claim is updated before its history row is inserted. If any history insert fails, let the sqlite3 error propagate and leave every claim as it was.

Constraints:
- Do not edit anything in tests/. If a test looks wrong, stop and tell me why instead.
- `now` is a parameter everywhere. No datetime.now() or other clock reads in claims.py.
- Reuse ALLOWED_CHANGES and the existing helpers instead of duplicating the rules.
- Do not create main.py. Do not commit.

Check before you finish: run `.venv/bin/python -m pytest -q` and `.venv/bin/ruff check .`, show me the last lines of both, and list anything I should look at in review.
```

**What the agent did.** It ran the suite first and saw 15 failures, all in the new file. Then it added `is_overdue`, the overdue guard in `change_status`, and `escalate_overdue`. It also pulled the UTC conversion out of `_to_text` into a small `_as_utc` helper so `is_overdue` could reuse it. The sweep works out which statuses can be escalated from `ALLOWED_CHANGES` instead of hardcoding "open" and "assigned". It ran pytest (72 passed) and ruff (clean). It took 4 turns and changed only `claims.py`.

**What I checked or changed**

- `git diff --stat -- tests/` was empty. I reran pytest (72 passed) and ruff (clean), and grepped for clock reads (none).
- Two mutation checks, both put back afterwards:
  - With `with conn:` removed from `escalate_overdue`, `test_failed_history_write_rolls_back_the_whole_sweep` failed (`assert 'escalated' == 'open'`).
  - With `>` changed to `>=` in `is_overdue`, 7 tests failed: the exact-deadline test, the edge test for all three tiers, the sweep-at-the-deadline test, and both not-overdue escalation tests. That is the off-by-one risk from PLAN.md, and the tests catch it.
- The tests only use times with no offset, so I checked one case by hand. For a deadline of 13:00 UTC, `now` at `21:59+09:00`, `22:00+09:00`, and `22:01+09:00` gave not overdue, not overdue, and overdue. That is right, because the agent converts both sides to UTC before comparing.
- I read the agent's four review notes. Two of them describe behavior I already accepted in PLAN.md: a reassigned claim gets escalated again by the next sweep, and the read before the write is not locked, which only matters if two writers run at once. The sweep filters overdue claims in Python rather than SQL. I kept it that way so the strict `>` rule lives in exactly one place.
