# Contributing to Paradax

Thanks for helping. Paradax has one rule above the others: **the LLM proposes, the system enforces.**
A change that gives a model more freedom needs a check that keeps it honest.

## Principles

1. **Contracts first.** Every agent declares what it reads, what it writes, its output schema and its tools. Do not pass extra context "just in case".
2. **Deterministic where possible.** If a step can be done without an LLM (fetching, parsing, verifying), do it without one.
3. **Nothing applies itself.** New skills or tools proposed by an agent wait for human approval.
4. **Local and private.** No calls to cloud APIs from the core; tests never hit the network or a real model.

## Development

```bash
cd local-agent-os
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

Each agent has its own test file with a fake LLM and fake tools. Add a test next to the code you change.
Tests run in isolation: they get their own database, models file and a temporary git repository for safety snapshots.

## Language

Prompts, comments and server messages are written in Spanish. The interface is translated in
`local-agent-os/static/js/i18n.js` (Spanish source text → English). If you add a visible string, add its English
version there. New code comments may be in English.

## Pull requests

- One topic per pull request, with tests.
- CI runs the test suite on Linux and macOS.
- Keep the README in sync with what the code actually does.

By contributing you agree that your contribution is licensed under the Apache License 2.0.
