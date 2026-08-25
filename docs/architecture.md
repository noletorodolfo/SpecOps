# Architecture

## Components

| Component | Responsibility | Location |
|---|---|---|
| CLI (Python) | Orchestrates prompts, writes artifacts, drives the state machine | `src/cli/` |
| Project discovery | Resolves which project's `.specops/` to operate on (explicit `--project`, or walk up from cwd like git finds `.git/`); `specops project init` scaffolds a new one | `src/core/project.py` |
| Adapters | One `send_prompt(prompt_text, context)` interface, four backends (mock, Hugging Face, OpenAI, Ollama) | `src/adapters/` |
| Prompt builder | Loads governance rules, pulls RAG excerpts, assembles the final prompt, hashes it for audit | `src/core/prompt_builder.py` |
| State machine | Persists each feature's current stage; gates `apply` behind `review` | `src/core/state_machine.py` |
| RAG (notes) | The project's own operational notes, embedded with `sentence-transformers`, indexed with FAISS | `.specops/rags/`, `src/rags/retrieve.py` |
| RAG (code) | Semantic index over the project's own tracked source, so the work phase can find relevant existing files unaided | `.specops/index/`, `src/rags/code_index.py` |
| Validators | terraform validate, kubeval, pytest, jest — run locally and in CI, against whichever project is active | `tools/validators.sh` |
| Logger | Append-only JSON audit log of every phase's decision | `src/core/logger.py`, `.specops/logs/specops.log` |
| Certificate | Human-readable record of what was checked and who approved a change, assembled from the audit log + git after every `apply` | `src/core/certificate.py`, `.specops/certificates/` |
| Neovim plugin | `:SpecOps*` commands, patch preview, explicit confirm before apply | `nvim/lua/specops/` |

## Project mode

SpecOps is installed once as a global engine; every project it operates on gets its own `.specops/` directory holding that project's governance, RAG notes, and working state:

```
some-project/
├── .git/
├── src/
└── .specops/
    ├── governance.yml
    ├── rags/
    ├── specs/
    ├── plans/
    ├── state/
    ├── logs/
    ├── out/
    ├── certificates/
    └── index/
```

`main()` resolves the target project before dispatching any subcommand: `--project <path>` if given, otherwise walk up from the current directory looking for `.specops/` (same algorithm git uses for `.git/`), then `os.chdir()` into it. Every other module (`state_machine`, `logger`, `certificate`, `retrieve`, `prompt_builder`) just uses plain paths relative to cwd (`.specops/state`, `.specops/rags/index.faiss`, etc.) — they don't know or care which project is active, `main()` already made that true by the time they run.

Tooling that belongs to the *engine* rather than the *project* — `tools/validators.sh`, `tools/ts_syntax_check.mjs`, the bundled `jest`/`ts-jest` install — is resolved relative to `specops_cli.py`'s own install location (`ENGINE_ROOT`), not cwd, so review works the same way regardless of which project is active or what that project has installed.

This repo dogfoods itself: `.specops/` here is what this repo's own `specops` commands read and write when run from inside this checkout.

## Pipeline state machine

```
SPEC_DRAFT → PLAN_DRAFT → WORK_DRAFT → REVIEW_PATCH → APPLY_PENDING → APPLIED
```

- `brainstorm` writes a spec and sets the feature's stage to `SPEC_DRAFT`.
- `plan` writes a plan and advances to `PLAN_DRAFT`.
- `work` asks the model for the **complete final content** of each file it creates or changes, then builds the patch itself (see "How the patch is built" below). Files the spec/plan name that already exist on disk are fed back into the prompt, so the model can modify them rather than only create new ones. Several gates run before the stage can advance: a rewrite that dropped most of an existing file is refused, `git apply --check` must pass, and the resulting content must parse — `ast.parse` for `.py`, the TypeScript compiler's parser for `.ts`/`.tsx` (`tools/ts_syntax_check.mjs`, needs `npm install` once). Any failure resets to `WORK_DRAFT`; only a patch that clears all of them reaches `REVIEW_PATCH`.
- `review` runs `tools/validators.sh`. Passing moves the stage to `APPLY_PENDING`; failing resets it to `WORK_DRAFT`.
- `apply` refuses to run unless the stage is exactly `APPLY_PENDING`. It asks for an explicit `yes`, checks out a new `feat/<feature>` branch, applies the patch, and commits.

State is persisted per feature in `.specops/state/<feature>.json`, so this survives across CLI invocations and Neovim sessions.

## How the patch is built

The work phase does **not** ask the model for a unified diff. It asks for each file's complete final content, wrapped in markers:

```
<<<SPECOPS_FILE src/calculator.py>>>
(entire file content, with the change applied)
<<<SPECOPS_END>>>
```

`src/core/patchgen.py` parses those blocks, reads each target's current content from disk, and computes the diff with `difflib` — so hunk headers, line numbers and context lines are *calculated*, never trusted.

This is what makes editing existing files possible at all. A model asked to write an edit diff directly has to reproduce byte-exact context lines and correct line offsets from a file it may not have seen; it reliably gets that wrong, which is why the work phase was new-files-only before. Inverting it puts the mechanical part on deterministic tooling and leaves the model doing only the semantic part.

Two safeguards come with that inversion, because a rewrite can destroy existing work where a new file could not:

- **Path validation** — the model chooses these paths, so absolute paths and anything resolving outside the project are refused.
- **Shrink guard** — if a rewritten file loses more than half its lines (and had at least 10 to begin with), the patch is refused. That pattern is almost always the model silently omitting content it didn't bother to repeat, not a deliberate refactor.

Regressions in code the change *didn't* touch are caught later, by `review` running the project's full test suite.

## Governance and prompt building

`.specops/governance.yml` declares, per profile and phase, which frameworks apply and what system instructions the model should follow:

```yaml
profiles:
  default:
    spec:
      frameworks: [TOGAF, DDD]
      system_instructions: "Structure requirements into domains, bounded_contexts and business_capabilities."
    work:
      frameworks: [CKA, TERRAFORM, AWS_DEVOPS]
      system_instructions: "Produce deployable, observable, testable artifacts."
```

`build_prompt(phase, profile, context, feature_notes)` reads that config, retrieves the top-k RAG excerpts for the phase's frameworks, assembles `SYSTEM + RAG_EXCERPTS + USER` into one prompt, and returns it along with a SHA-256 hash and the list of RAG sources used — everything an adapter and the audit log need.

## RAG: scoped by phase, not just similarity

Each note in `.specops/rags/<framework>/*.md` lives under a directory that maps to a framework identifier declared in `.specops/governance.yml` (e.g. `.specops/rags/terraform/` ↔ `TERRAFORM`). `retrieve_topk(frameworks, query, k)` first filters candidates to the frameworks relevant to the current phase, then ranks by embedding similarity within that subset. `.specops/rags/patterns/` is the one exception — cross-cutting notes there are always eligible regardless of phase.

This matters once the note count grows past a handful: without the filter, a spec-phase prompt could easily surface a Terraform note just because it scored well on raw cosine similarity, polluting a business-requirements answer with infrastructure jargon it never asked for.

## Code retrieval: finding relevant files unaided

`specops index` embeds the project's own source into a **separate** FAISS index at `.specops/index/`. Kept separate from the notes deliberately: notes are curated guidance that governance scopes by phase, code is raw project material, and mixing them would let a stray source file outrank the guidance a phase is supposed to follow.

File selection comes from `git ls-files`, which already honours `.gitignore` and skips untracked junk — reimplementing that filter by hand would only approximate it. Vendored/generated paths (`node_modules`, lockfiles, `dist`), unknown extensions and oversized files are dropped, and `.specops/` itself is excluded so SpecOps' own generated specs never come back as "code". Files are chunked into overlapping 60-line windows tagged with their real line ranges.

The work phase then feeds retrieval results in at **two tiers**, which is the part that matters for safety:

- **Full files** — the highest-ranked paths, included whole (within the same byte budget as `--file`). Only these are eligible to be rewritten.
- **Read-only excerpts** — everything else retrieval surfaced, shown as partial snippets so the model can follow existing conventions.

A model that only saw an excerpt cannot safely rewrite that file: whatever it didn't see would be silently deleted. So that isn't left to prompt wording — `work` refuses outright if the model emits a file block for a path that exists on disk but wasn't provided in full, and tells you to re-run with `--file <path>`.

Retrieval is inert until `specops index` has been run, so a project that never indexes behaves exactly as before.

## Adapters

All four adapters implement the same contract:

```python
def send_prompt(prompt_text: str, context: dict) -> dict:
    """Returns: {response_text, prompt_hash, rag_sources, model}"""
```

`adapters.get_send_prompt()` picks the implementation based on `SPECOPS_MODEL` (`mock` by default, or `huggingface`/`hf`, `openai`, `ollama`). OpenAI and Ollama talk to their plain REST APIs via `httpx` — no extra SDKs. Hugging Face uses `huggingface_hub.InferenceClient` against Inference Providers.

## Security notes

- Secrets live in `.env` (gitignored), never in RAG notes or committed code.
- `logger.py` masks anything that looks like a token/secret/api_key before writing to the audit log.
- CI runs a gitleaks scan on every push and PR.
- Feature names are validated against `^[a-zA-Z0-9_-]+$` everywhere they touch a shell command or file path, in both the CLI and the Neovim plugin, to avoid injection through a crafted feature name.
