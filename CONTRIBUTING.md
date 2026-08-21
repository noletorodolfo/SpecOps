# Contributing

This is currently a solo project, but the workflow below is meant to hold up even if that changes.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
npm install
python tools/rag_ingest.py
```

Copy `.env.example` to `.env` and fill in whatever adapter credentials you need (see [docs/usage.md](docs/usage.md)). `.env` is gitignored — it should never be committed.

## Before opening a PR

```bash
bash tools/validators.sh
```

This runs the same checks CI runs: `terraform validate` (if any `.tf` files exist), `kubeval` (if any `k8s/*.yaml` files exist), and `pytest`. If it's green locally, it'll be green in CI.

## Commit messages

English, present tense, one logical change per commit. Prefer a short prefix (`fix:`, `feat:`, `docs:`, `ci:`, `chore:`) matching what actually changed — it makes `git log --oneline` skimmable later.

## Branching

Work happens on `feat/<name>` branches off `main`. `specops apply` creates these automatically when it commits a generated patch, but the same convention applies to hand-written changes.

## A note on RAG notes

Anything added under `.specops/rags/` gets embedded and retrieved into future prompts. Only add your own reformulated notes and patterns — never paste in copyrighted or protected text, and never anything containing a secret (see [SECURITY.md](SECURITY.md)).

## Working on SpecOps itself vs. testing project mode

This repo dogfoods SpecOps: its own `.specops/` is what `specops brainstorm/plan/work/review/apply` reads and writes when run from inside this checkout. If you're testing project mode against some *other* directory, use `--project <path>` or `cd` there first — don't point it at this repo unless you actually mean to generate a change here.
