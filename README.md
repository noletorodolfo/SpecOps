# SpecOps

SpecOps is an AI-assisted engineering workflow with a governance layer built in: **spec → plan → work → review → apply → doc**. The idea is simple — an LLM can draft specs, plans, and patches all day, but nothing gets applied to the repo without passing through automated validators and an explicit human approval gate.

**Why this exists**
Most "AI coding assistant" setups let a model write code and a human eyeball the diff before merging. That's fine until the model starts generating infrastructure changes, and "eyeballing" stops being a real safety net. SpecOps forces every phase through a state machine: a patch can't be applied until it's passed review, and review means real validators (Terraform, Kubernetes manifests, tests) — not just "looks plausible."

**How it works**
- **CLI (Python)** drives the whole pipeline — `specops brainstorm/plan/work/review/apply`.
- **Project mode**: SpecOps is a global engine, installed once. Each project it operates on gets its own `.specops/` directory (governance, RAG notes, state, certificates) — `specops` finds it by walking up from your cwd, the same way git finds `.git/`. SpecOps operates on itself this way too (see `.specops/` in this repo).
- **Governance file** (`.specops/governance.yml`) declares which frameworks and system instructions apply to each phase, per profile — one per project.
- **RAG** pulls from that project's own operational notes (`.specops/rags/`), scoped to the frameworks relevant to the current phase — a spec-phase prompt never sees Terraform notes, and vice versa.
- **Pluggable adapters** (mock, Hugging Face, OpenAI, Ollama) share one interface, selected via `SPECOPS_MODEL`.
- **State machine** tracks each feature's stage (`.specops/state/<feature>.json`) and blocks `apply` until `review` has actually passed.
- **Change Certificate**: every `apply` produces a human-readable record (`.specops/certificates/`) of what model was used, what context it saw, which validators actually ran, and who approved it — assembled from data the pipeline already logs, not a self-report from the model.
- **Neovim plugin** wraps the CLI with `:SpecOps*` commands, including a patch preview and confirmation before anything touches git.
- **CI** runs the same validators on every push/PR, plus a gitleaks secret scan.

## Quick start (Arch Linux)

```bash
# prerequisites
sudo pacman -Syu python neovim git

# set up the environment
git clone <repo-url> SpecOps
cd SpecOps
python -m venv .venv && source .venv/bin/activate
pip install -e .

# needed only if you'll generate TypeScript/TSX (syntax-check tooling)
npm install
```

SpecOps operates on whichever project's `.specops/` it finds — including itself. To try the pipeline against this repo (mock adapter, no API key needed):

```bash
python tools/rag_ingest.py   # index this repo's own RAG notes
specops brainstorm my-feature --notes "short description of what you're building"
specops plan my-feature
specops work my-feature
specops review my-feature
specops apply my-feature
```

To use SpecOps on a *different* project:

```bash
cd ~/some-other-project
specops project init          # creates .specops/ here
specops brainstorm my-feature --notes "..."
# ...same pipeline, applied to this project instead
```

`specops` auto-discovers `.specops/` by walking up from your current directory, the same way git finds `.git/` — run it from anywhere inside an initialized project. Pass `--project <path>` to override that (useful from scripts/CI).

To use a real model instead of the mock adapter, set `SPECOPS_MODEL=huggingface` (or `openai`/`ollama`) and the matching credentials in `.env` — see [docs/usage.md](docs/usage.md).

## Docs

- [docs/usage.md](docs/usage.md) — CLI walkthrough, adapters, environment variables
- [docs/architecture.md](docs/architecture.md) — components, state machine, RAG design
- [docs/DoD.md](docs/DoD.md) — what "done" means for a change here
- [CONTRIBUTING.md](CONTRIBUTING.md) — dev setup, commit conventions, branching
- [SECURITY.md](SECURITY.md) — secrets handling, the apply gate, what to do if something leaks
