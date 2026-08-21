import os
import shutil

SPECOPS_DIR = ".specops"

# Subdirectories that live inside <project>/.specops/. Mirrors what used
# to sit loose at the SpecOps repo root — governance/rags are the
# project's own config, the rest is working state for that project.
DATA_SUBDIRS = [
    "rags",
    "specs",
    "plans",
    "state",
    "logs",
    "out",
    "certificates",
]

DEFAULT_GOVERNANCE = """profiles:
  default:
    spec:
      frameworks: [TOGAF, DDD]
      system_instructions: "Structure requirements into domains, bounded_contexts and business_capabilities. Match the depth to the feature's actual scope — a single trivial function doesn't need a multi-domain breakdown."
    plan:
      frameworks: [KLEPPMANN, AWS_SA_PRO]
      system_instructions: "Prioritize scalability, consistency and fault tolerance — but only to the degree the feature's actual scope warrants. A pure function with no external dependencies needs none of this; reserve these patterns for genuinely distributed or stateful concerns. When in doubt, prefer the simplest design that satisfies the spec over the most resilient one."
    work:
      frameworks: [CKA, TERRAFORM, AWS_DEVOPS]
      system_instructions: "Implement exactly what the spec and plan describe — do not add infrastructure, monitoring, retries, or resilience patterns they didn't ask for, but DO include every file the spec/plan explicitly asked for (e.g. if tests were requested, both the implementation file AND its test file must be present — never emit a test file that imports a module you didn't also create). Output ONLY a valid unified diff (git patch format) — nothing else. No prose before or after, no markdown code fences. Only create new files (new file mode, --- /dev/null, +++ b/<path>) — never edit an existing file. Prefer the fewest files that satisfy the request; two (implementation + its test) is normal, avoid going beyond that unless the plan clearly calls for more. CRITICAL: every single line of every file's content in its hunk body must start with a literal '+' character — this is not optional formatting, a line without a leading '+' makes the whole diff invalid."
    data:
      frameworks: [GOOGLE_ML, DATABRICKS]
      system_instructions: "Turn events into reproducible pipelines, scaled to the actual data volume and reliability needs described in the plan — not every pipeline needs a full medallion architecture."
    doc:
      frameworks: [TOGAF, ADR]
      system_instructions: "Generate ADRs, runbooks and operational diagrams proportional to the decision's actual impact — a one-line config tweak doesn't need a runbook."
"""


def find_project_root(explicit=None, start=None):
    """Resolve which project SpecOps should operate on.

    Same two modes as git looking for .git/: an explicit --project always
    wins; otherwise walk up from `start` (default: cwd) looking for a
    .specops/ directory, so `specops <cmd>` works from anywhere inside an
    initialized project, not just its root.
    """
    if explicit:
        root = os.path.abspath(explicit)
        if not os.path.isdir(os.path.join(root, SPECOPS_DIR)):
            raise SystemExit(
                f"No {SPECOPS_DIR}/ found at '{root}'. "
                f"Run 'specops project init' there first."
            )
        return root

    current = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isdir(os.path.join(current, SPECOPS_DIR)):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    raise SystemExit(
        f"No {SPECOPS_DIR}/ found in '{os.path.abspath(start or os.getcwd())}' "
        f"or any parent directory. Run 'specops project init' to set one up here, "
        f"or pass --project <path>."
    )


def init_project(path):
    """Create the .specops/ skeleton at `path` (default: cwd). Idempotent —
    safe to run again; never overwrites an existing governance.yml or notes."""
    root = os.path.abspath(path)
    specops_dir = os.path.join(root, SPECOPS_DIR)
    already_existed = os.path.isdir(specops_dir)

    os.makedirs(specops_dir, exist_ok=True)
    for sub in DATA_SUBDIRS:
        os.makedirs(os.path.join(specops_dir, sub), exist_ok=True)

    governance_path = os.path.join(specops_dir, "governance.yml")
    if not os.path.exists(governance_path):
        with open(governance_path, "w") as f:
            f.write(DEFAULT_GOVERNANCE)

    return specops_dir, already_existed
