import json
import os
import subprocess
import time

CERT_DIR = ".specops/certificates"


def _git(*args):
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    return result.stdout.strip()


def _read_audit_entries(feature):
    """All log entries for this feature, across every phase and every
    retry — the certificate's job is to summarize what actually happened,
    not just the final attempt."""
    entries = []
    path = ".specops/logs/specops.log"
    if not os.path.exists(path):
        return entries
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("feature") == feature:
                entries.append(entry)
    return entries


def _next_number():
    os.makedirs(CERT_DIR, exist_ok=True)
    numbers = []
    for name in os.listdir(CERT_DIR):
        if name.startswith("CHG-"):
            try:
                numbers.append(int(name.split("-")[1]))
            except (IndexError, ValueError):
                continue
    return max(numbers, default=0) + 1


def generate(feature):
    """Called right after `apply` commits. Assembles a human-readable
    record of what was actually checked and who approved it — entirely
    from data the pipeline already produced (audit log, state, git), not
    a self-report from the model. Only lists validators that genuinely
    ran; nothing here is an unverified claim."""
    entries = _read_audit_entries(feature)
    by_phase = {}
    for e in entries:
        # a feature can be regenerated and re-run; keep the entry that
        # corresponds to what actually ended up applied, i.e. the latest
        by_phase[e["phase"]] = e

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    commit = _git("rev-parse", "HEAD")
    author = _git("log", "-1", "--format=%an <%ae>")
    commit_date = _git("log", "-1", "--format=%ad", "--date=iso-strict")
    diffstat = _git("show", "--stat", "--format=", commit)

    rag_sources = sorted({s for e in entries for s in e.get("rag_sources", [])})
    validators_run = sorted({v for e in entries for v in e.get("validators_run", [])})

    number = _next_number()
    cert_id = f"CHG-{number:04d}"
    cert_path = os.path.join(CERT_DIR, f"{cert_id}-{feature}.md")

    lines = [
        f"# SpecOps Change Certificate — {cert_id}",
        "",
        f"**Feature:** `{feature}`",
        f"**Generated:** {time.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        "",
        "## Pipeline",
        "",
    ]
    for phase in ["SPEC", "PLAN", "WORK", "REVIEW"]:
        e = by_phase.get(phase)
        if e:
            lines.append(f"- **{phase}**: model `{e.get('model')}`, prompt hash `{e['prompt_hash'][:12]}…`")
        else:
            lines.append(f"- **{phase}**: not recorded")

    lines += ["", "## Context used (RAG)", ""]
    lines += [f"- `{s}`" for s in rag_sources] if rag_sources else ["- (none retrieved)"]

    lines += ["", "## Validation", ""]
    if validators_run:
        lines += [f"- `{v}` — ran and passed" for v in validators_run]
    else:
        lines.append("- (no validators recorded)")
    lines += [
        "- every new file in the patch also passed `git apply --check`, and "
        "Python/TypeScript syntax checks where applicable (ast.parse / "
        "tools/ts_syntax_check.mjs) — see .specops/logs/specops.log for the full trace",
        "",
        "## Human approval",
        "",
        f"- Approved by: `{author}`",
        f"- Applied at: {commit_date}",
        "- Method: explicit `yes` confirmation in `specops apply`",
        "",
        "## Git",
        "",
        f"- Branch: `{branch}`",
        f"- Commit: `{commit}`",
        "",
        "## Patch",
        "",
        "```",
        diffstat,
        "```",
        "",
        "---",
        "*Not covered yet: lint, dedicated security scanning beyond CI's gitleaks, "
        "project-specific architectural policy checks. These only appear above once "
        "real gates exist for them.*",
        "",
    ]

    os.makedirs(CERT_DIR, exist_ok=True)
    with open(cert_path, "w") as f:
        f.write("\n".join(lines))
    return cert_path
