# SpecOps Roadmap

Prioritized plan for evolving SpecOps from an MVP into a production-grade AI engineering governance tool. Estimates are rough engineering hours and assume one developer working with an AI coding assistant.

Priority order: (1) things that make the governance guarantees real, (2) things that make the pipeline usable day to day, (3) things that widen adoption.

## P0 — Make the guarantees enforceable (~50h)

| Item | Why | Est. |
|---|---|---|
| Automatic coverage gate in `review` (DoD already requires it) | The DoD says "minimum coverage bar" but nothing enforces it | 8h |
| Secret scan (gitleaks) as a pre-`apply` gate, not only in CI | A patch with a leaked key should never reach a branch | 6h |
| Path policy per profile: allowed/forbidden paths and max files touched per change | Bounds the blast radius of a bad patch | 10h |
| Prompt-injection hardening for repo content entering the context | Files in the target repo are untrusted input | 12h |
| End-to-end integration tests of the full pipeline (mock + one real adapter) | Today's tests are unit-level | 14h |

## P1 — Robust adapters and real-model quality (~60h)

| Item | Why | Est. |
|---|---|---|
| Retry with backoff, timeouts, streaming in all adapters | Current adapters are thin wrappers | 10h |
| Anthropic/Claude adapter | Missing first-class provider | 6h |
| Token and cost accounting per phase, written to the log and certificate | Makes runs auditable and comparable | 8h |
| Evaluation harness: golden set of specs → measure patch pass rate per model/prompt | Choose models and prompts with data, not impressions | 24h |
| Structured-output validation for spec/plan phases (schema-checked) | Fails early on malformed plans | 12h |

## P2 — Better retrieval (~45h)

| Item | Why | Est. |
|---|---|---|
| RAG evaluation set (hit@k, groundedness) and committed reports | Retrieval quality is currently unmeasured | 14h |
| AST-aware chunking in `code_index` | Function-level chunks retrieve better than line windows | 12h |
| Incremental indexing (only changed files) | The index is currently rebuilt in full | 10h |
| Hybrid BM25 + vector search, optional re-ranking | Compare against baseline using the eval set | 9h |

## P3 — Validators and review depth (~50h)

| Item | Why | Est. |
|---|---|---|
| Validators for Dockerfile, SQL migrations, OpenAPI, Helm, GitHub Actions | Governance only covers what it validates | 20h |
| SAST in review (semgrep, bandit) | Catch insecure generated code | 8h |
| Mutation testing option for generated tests | Passing tests are weak evidence on their own | 14h |
| Multi-feature state with conflict detection between pending patches | Several features in flight is the normal case | 8h |

## P4 — Certificates and audit trail (~40h)

| Item | Why | Est. |
|---|---|---|
| Signed Change Certificates (sigstore or local keys) + `specops verify` | Today certificates are readable but not tamper-evident | 16h |
| Hash-chained audit log | Detect edits to history | 8h |
| `specops revert <feature>` driven by the certificate | Safe rollback | 8h |
| Dual-control approval for infrastructure changes | Two-person rule for high-risk paths | 8h |

## P5 — Integrations and adoption (~65h)

| Item | Why | Est. |
|---|---|---|
| GitHub PR integration: open PR with certificate attached, status check | Fits into real team workflows | 16h |
| MCP server exposing the pipeline to other agents | Lets agents like Claude Code use the governance gates | 14h |
| Terminal or web UI for reviewing patches and certificates | Better than raw diffs | 16h |
| VS Code extension (parity with the Neovim plugin) | Wider editor reach | 12h |
| PyPI packaging, multi-version CI, versioned docs | Installable by others | 7h |

## Total

About 310 hours across all priorities. P0 and P1 together (~110h) deliver the biggest gain in trustworthiness and are the recommended starting point.

## Definition of done for each item

Follows `docs/DoD.md`: formatted and linted, unit tests, validators passing, docs updated, patch reviewed and approved by a human, execution log with `prompt_hash` and `rag_sources`.
