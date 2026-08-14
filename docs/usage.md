# Usage

## The pipeline

```bash
specops brainstorm <feature> --notes "what you're building and why"
specops plan <feature>
specops work <feature>
specops review <feature>
specops apply <feature>
```

Each step writes an artifact and advances the feature's state:

| Command | Writes | New stage |
|---|---|---|
| `brainstorm` | `specs/<feature>.md` | `SPEC_DRAFT` |
| `plan` | `plans/<feature>/plan.yaml` | `PLAN_DRAFT` |
| `work` | `out/<feature>.patch` | `REVIEW_PATCH` (or back to `WORK_DRAFT` if the diff is invalid) |
| `review` | runs `tools/validators.sh` | `APPLY_PENDING` (or back to `WORK_DRAFT` on failure) |
| `apply` | commits the patch on a new `feat/<feature>` branch | `APPLIED` |

`apply` will refuse to run — loudly — if the feature hasn't reached `APPLY_PENDING`. There's no way to skip review from the CLI.

## Choosing a model

By default everything runs against `adapter_mock`, which is enough to exercise the full pipeline (including a syntactically valid patch for the `work` phase) without any credentials. To use a real model:

```bash
export SPECOPS_MODEL=huggingface   # or: openai, ollama
```

| `SPECOPS_MODEL` | Needs | Env vars |
|---|---|---|
| `mock` (default) | nothing | — |
| `huggingface` / `hf` | an HF token | `HF_TOKEN`, optionally `SPECOPS_HF_MODEL` (default `meta-llama/Llama-3.1-8B-Instruct`) |
| `openai` | an OpenAI API key | `OPENAI_API_KEY`, optionally `SPECOPS_OPENAI_MODEL` (default `gpt-4o-mini`) |
| `ollama` | a local Ollama server | `OLLAMA_HOST` (default `http://localhost:11434`), `SPECOPS_OLLAMA_MODEL` (default `llama3.1`) |

Put credentials in `.env` at the repo root (already gitignored) — the CLI loads it automatically on startup.

## RAG notes

Notes live under `rags/<framework>/*.md`, where `<framework>` matches an identifier declared in `governance.yml` (see `src/rags/retrieve.py`'s `FRAMEWORK_DIRS` mapping). Only notes under frameworks relevant to the current phase get retrieved — `rags/patterns/` is the exception and is always eligible.

After adding or editing a note, reindex:

```bash
python tools/rag_ingest.py
```

Only index your own reformulated notes and patterns — never paste in copyrighted or protected text.

## Neovim

```vim
:SpecOpsBrainstorm
:SpecOpsPlan
:SpecOpsWork
:SpecOpsReview
:SpecOpsApply
```

Each command prompts for a feature name, runs the matching CLI command through `.venv/bin/specops`, and opens the output in a scratch buffer. `:SpecOpsApply` shows the patch for review first and asks for an explicit Neovim confirmation before it ever touches git.

## Running validators manually

```bash
bash tools/validators.sh
```

Runs `terraform validate` (if `*.tf` files exist), `kubeval` (if `k8s/*.yaml` files exist), and `pytest`. This is exactly what `specops review` and CI both run — if it passes locally, it'll pass in CI.
