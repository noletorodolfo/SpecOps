# Security

## Secrets

- Credentials live in `.env` (gitignored) or your shell environment — never in code, `governance.yml`, or `rags/` notes.
- `.env.example` documents which variables each adapter expects, with empty values.
- `src/core/logger.py` masks anything matching `(api_key|secret|token)[:=]\s*[\w-]{8,}` before writing to `logs/specops.log`.
- CI runs a [gitleaks](https://github.com/gitleaks/gitleaks) scan on every push and PR.

## If a secret leaks

1. Revoke/rotate it at the provider immediately — assume it's compromised the moment it hits a chat log, a committed file, or a CI log, even if you delete it right after.
2. If it landed in a commit, treat the commit as permanently tainted (rotating the secret matters far more than scrubbing history — assume anything pushed is unrecoverable).

## Apply gate

`specops apply` will not run unless a feature's state is exactly `APPLY_PENDING`, which only happens after `specops review` passes (`terraform validate`, `kubeval`, `pytest`). There is no flag to skip this from the CLI. `apply` also always asks for an explicit `yes` before touching git.

## Input handling

Feature names are validated against `^[a-zA-Z0-9_-]+$` everywhere they reach a shell command or file path — in the CLI (`validate_feature`) and in the Neovim plugin (mirrored check before the argv-list `vim.fn.system()` call, which never goes through a shell in the first place).

## Reporting

This is currently a private, single-maintainer project — open an issue if you spot something.
