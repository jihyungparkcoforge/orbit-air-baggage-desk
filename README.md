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
