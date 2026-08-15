# Architecture

## Components

| Component | Responsibility | Location |
|---|---|---|
| CLI (Python) | Orchestrates prompts, writes artifacts, drives the state machine | `src/cli/` |
| Adapters | One `send_prompt(prompt_text, context)` interface, four backends (mock, Hugging Face, OpenAI, Ollama) | `src/adapters/` |
| Prompt builder | Loads governance rules, pulls RAG excerpts, assembles the final prompt, hashes it for audit | `src/core/prompt_builder.py` |
| State machine | Persists each feature's current stage; gates `apply` behind `review` | `src/core/state_machine.py` |
| RAG | Your own operational notes, embedded with `sentence-transformers`, indexed with FAISS | `rags/`, `src/rags/retrieve.py` |
| Validators | terraform validate, kubeval, pytest, jest — run locally and in CI | `tools/validators.sh` |
| Logger | Append-only JSON audit log of every phase's decision | `src/core/logger.py`, `logs/specops.log` |
| Neovim plugin | `:SpecOps*` commands, patch preview, explicit confirm before apply | `nvim/lua/specops/` |

## Pipeline state machine

```
SPEC_DRAFT → PLAN_DRAFT → WORK_DRAFT → REVIEW_PATCH → APPLY_PENDING → APPLIED
```

- `brainstorm` writes a spec and sets the feature's stage to `SPEC_DRAFT`.
- `plan` writes a plan and advances to `PLAN_DRAFT`.
- `work` generates a patch, then immediately runs `git apply --check` against it. A malformed diff (mock placeholder, truncated model output, hallucinated hunk) resets the stage to `WORK_DRAFT` right there instead of only failing later at apply time. `git apply --check` only validates diff *mechanics*, though — it has no idea whether the resulting file is valid code. New `.py` files get an `ast.parse` check, new `.ts`/`.tsx` files get a syntax-only check via the TypeScript compiler's parser (`tools/ts_syntax_check.mjs`, needs `npm install` once). Either failing also resets to `WORK_DRAFT`. Only once the patch is both a valid diff and its new files parse does the stage advance to `REVIEW_PATCH`.
- `review` runs `tools/validators.sh`. Passing moves the stage to `APPLY_PENDING`; failing resets it to `WORK_DRAFT`.
- `apply` refuses to run unless the stage is exactly `APPLY_PENDING`. It asks for an explicit `yes`, checks out a new `feat/<feature>` branch, applies the patch, and commits.

State is persisted per feature in `state/<feature>.json`, so this survives across CLI invocations and Neovim sessions.

## Governance and prompt building

`governance.yml` declares, per profile and phase, which frameworks apply and what system instructions the model should follow:

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

Each note in `rags/<framework>/*.md` lives under a directory that maps to a framework identifier declared in `governance.yml` (e.g. `rags/terraform/` ↔ `TERRAFORM`). `retrieve_topk(frameworks, query, k)` first filters candidates to the frameworks relevant to the current phase, then ranks by embedding similarity within that subset. `rags/patterns/` is the one exception — cross-cutting notes there are always eligible regardless of phase.

This matters once the note count grows past a handful: without the filter, a spec-phase prompt could easily surface a Terraform note just because it scored well on raw cosine similarity, polluting a business-requirements answer with infrastructure jargon it never asked for.

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
