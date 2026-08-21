# AWS DevOps — Pipeline Patterns (summary)
- Treat the pipeline itself as versioned artifact-producing code: build once, promote the same immutable artifact through environments instead of rebuilding per stage.
- Fail fast, cheap checks first: lint/unit tests before integration tests before deploy — matches SpecOps' own validators.sh ordering (terraform validate, kubeval, pytest).
- Canary or blue/green over big-bang deploys for anything stateful-adjacent; the rollback plan should be as reviewed as the forward plan.
- Practical note: secrets never live in pipeline YAML or env files committed to the repo — pull from a secret manager at deploy time, matching SpecOps' own "secrets via env vars/secret manager, never in RAG" rule.
