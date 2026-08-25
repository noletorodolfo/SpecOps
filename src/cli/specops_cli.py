#!/usr/bin/env python3
import argparse
import ast
import os
import re
import subprocess
import sys
import tempfile
from dotenv import load_dotenv

load_dotenv()

from core.prompt_builder import build_prompt
from adapters import get_send_prompt
from core.state_machine import (
    StateMachine,
    SPEC_DRAFT,
    PLAN_DRAFT,
    WORK_DRAFT,
    REVIEW_PATCH,
    APPLY_PENDING,
    APPLIED,
)
from core.logger import audit_log
from core import certificate
from core import patchgen
from core import project as project_mod
from rags import code_index

SM = StateMachine()
FEATURE_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_feature(feature):
    if not FEATURE_RE.match(feature):
        raise SystemExit(
            f"Invalid feature name '{feature}': only letters, digits, '-' and '_' are allowed."
        )
    return feature


def _check_python_syntax(files):
    errors = []
    for path, content in files.items():
        if not path.endswith(".py"):
            continue
        try:
            ast.parse(content)
        except SyntaxError as exc:
            errors.append(f"{path}:{exc.lineno}: {exc.msg}")
    return errors


# The SpecOps engine's own install location (where this file lives), as
# opposed to whatever project it's currently operating on — tools/ (and
# its jest/ts-jest setup) belong to the engine, not to each project.
ENGINE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TS_CHECKER = os.path.join(ENGINE_ROOT, "tools", "ts_syntax_check.mjs")
VALIDATORS_SH = os.path.join(ENGINE_ROOT, "tools", "validators.sh")


def _check_typescript_syntax(files):
    """Same idea as _check_python_syntax, for .ts/.tsx files: syntax only,
    via the TypeScript compiler's parser (tools/ts_syntax_check.mjs) — not
    full type-checking, which would need the file's imports and any
    @types packages (jest, etc.) to actually resolve and would false-flag
    perfectly valid generated code."""
    ts_files = {p: c for p, c in files.items() if p.endswith((".ts", ".tsx"))}
    if not ts_files:
        return []
    if subprocess.run(["node", "--version"], capture_output=True).returncode != 0:
        return []  # node not available in this environment; skip rather than block

    errors = []
    with tempfile.TemporaryDirectory() as tmp:
        for path, content in ts_files.items():
            # Keep the real extension so the checker parses TSX correctly;
            # the rest of the name/path doesn't matter, it's a scratch copy.
            suffix = ".tsx" if path.endswith(".tsx") else ".ts"
            tmp_path = os.path.join(tmp, f"check{suffix}")
            with open(tmp_path, "w") as f:
                f.write(content)
            result = subprocess.run(
                ["node", TS_CHECKER, tmp_path], capture_output=True, text=True
            )
            if result.returncode != 0:
                errors.append(f"{path}: {result.stderr.strip().replace(tmp_path, path)}")
    return errors


def cmd_brainstorm(args):
    feature = validate_feature(args.feature)
    context = {"feature": feature}
    prompt_meta = build_prompt("spec", "default", context, args.notes or "")
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("SPEC", prompt_meta, resp, status=SPEC_DRAFT)
    os.makedirs(".specops/specs", exist_ok=True)
    path = f".specops/specs/{feature}.md"
    with open(path, "w") as f:
        f.write(resp["response_text"])
    SM.advance(feature, SPEC_DRAFT)
    print(f"Wrote {path}")


def cmd_plan(args):
    feature = validate_feature(args.feature)
    spec_path = args.spec or f".specops/specs/{feature}.md"
    spec_content = ""
    if os.path.exists(spec_path):
        with open(spec_path) as f:
            spec_content = f.read()
    context = {"feature": feature, "spec_file": spec_path}
    prompt_meta = build_prompt("plan", "default", context, spec_content)
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("PLAN", prompt_meta, resp, status=PLAN_DRAFT)
    path = f".specops/plans/{feature}/plan.yaml"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(resp["response_text"])
    SM.advance(feature, PLAN_DRAFT)
    print(f"Wrote {path}")


FILE_MENTION_RE = re.compile(r"[\w./-]+\.(?:py|ts|tsx|js|jsx|mjs|json|ya?ml|md|sh|sql)")

# Existing files are fed back to the model so it can rewrite them, but a
# whole repo won't fit in a prompt — cap it and skip anything oversized.
MAX_CONTEXT_FILES = 8
MAX_CONTEXT_BYTES = 60_000

# Code retrieval: how many chunks to pull, and how many to keep as
# read-only excerpts once the ones promoted to full files are removed.
CODE_CHUNKS_K = 10
CODE_EXCERPTS_MAX = 5


def _collect_existing_files(texts, explicit_paths=(), extra_paths=()):
    """Find files the work phase should be able to modify, in full.

    Priority order, because the byte budget is finite: files the caller
    named with --file, then files the spec/plan mention by name, then
    anything else offered (in practice, what code retrieval surfaced).
    A model can't rewrite a file it has never seen, so only files included
    here in full are eligible to be rewritten at all.
    """
    candidates = []
    for path in explicit_paths:
        if path and path not in candidates:
            candidates.append(path)
    for text in texts:
        for match in FILE_MENTION_RE.finditer(text or ""):
            path = match.group(0).lstrip("./")
            if path not in candidates:
                candidates.append(path)
    for path in extra_paths:
        if path and path not in candidates:
            candidates.append(path)

    collected = {}
    total = 0
    for path in candidates:
        if len(collected) >= MAX_CONTEXT_FILES:
            break
        if path.startswith(".specops/") or not os.path.isfile(path):
            continue
        size = os.path.getsize(path)
        if size > MAX_CONTEXT_BYTES or total + size > MAX_CONTEXT_BYTES:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                collected[path] = f.read()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable; not something to rewrite anyway
        total += size
    return collected


def cmd_work(args):
    feature = validate_feature(args.feature)
    plan_path = args.plan or f".specops/plans/{feature}/plan.yaml"
    plan_content = ""
    if os.path.exists(plan_path):
        with open(plan_path) as f:
            plan_content = f.read()

    spec_path = f".specops/specs/{feature}.md"
    spec_content = ""
    if os.path.exists(spec_path):
        with open(spec_path) as f:
            spec_content = f.read()

    project_root = os.getcwd()

    # Semantic retrieval over the project's own code, so the work phase can
    # find relevant existing files even when the plan never names them.
    # Silently inactive until `specops index` has been run.
    retrieved = []
    if code_index.is_indexed(project_root):
        query = f"{feature}\n{spec_content[:1500]}\n{plan_content[:1500]}"
        retrieved = code_index.retrieve_code(query, k=CODE_CHUNKS_K, root=project_root)

    retrieved_paths = []
    for chunk in retrieved:
        if chunk["path"] not in retrieved_paths:
            retrieved_paths.append(chunk["path"])

    existing = _collect_existing_files(
        [plan_content, spec_content], args.file or [], retrieved_paths
    )

    # Anything retrieval surfaced that didn't fit the full-content budget
    # is still useful as reference — "this is how the project does X" —
    # but only as an excerpt, and excerpts are explicitly not rewritable.
    excerpts = [c for c in retrieved if c["path"] not in existing][:CODE_EXCERPTS_MAX]

    sections = [plan_content]
    if existing:
        blocks = [
            f"<<<SPECOPS_FILE {path}>>>\n{content.rstrip(chr(10))}\n<<<SPECOPS_END>>>"
            for path, content in existing.items()
        ]
        sections.append(
            "EXISTING FILES (current content on disk — reproduce in full, with your "
            "changes applied, for any you modify):\n\n" + "\n\n".join(blocks)
        )
        print(f"Context: {len(existing)} full file(s) — {', '.join(existing)}")
    if excerpts:
        blocks = [
            f"--- {c['path']} (lines {c['start_line']}-{c['end_line']}) ---\n{c['text']}"
            for c in excerpts
        ]
        sections.append(
            "RELATED CODE (read-only excerpts, shown so you can follow this "
            "project's existing conventions — these are PARTIAL files, so never "
            "output a SPECOPS_FILE block for any of them):\n\n" + "\n\n".join(blocks)
        )
        print(
            f"Context: {len(excerpts)} code excerpt(s) — "
            f"{', '.join(sorted({c['path'] for c in excerpts}))}"
        )

    notes = "\n\n".join(sections)
    context = {"feature": feature, "plan_file": plan_path}
    prompt_meta = build_prompt("work", "default", context, notes)
    resp = get_send_prompt()(prompt_meta["prompt_text"], {"meta": prompt_meta})
    audit_log("WORK", prompt_meta, resp, status=WORK_DRAFT)
    os.makedirs(".specops/out", exist_ok=True)
    patch_path = f".specops/out/{feature}.patch"

    def fail(headline, details=()):
        SM.advance(feature, WORK_DRAFT)
        print(headline)
        for line in details:
            print(f"  {line}")
        print("State: WORK_DRAFT. Fix the prompt/model output and re-run 'specops work'.")
        raise SystemExit(1)

    # The model returns each file's full final content; the diff itself is
    # computed here rather than trusted, so hunk headers and context lines
    # are correct by construction.
    try:
        files = patchgen.parse_file_blocks(resp["response_text"])
        patchgen.validate_paths(files, project_root)
    except patchgen.PatchGenError as exc:
        fail(f"Could not build a patch from the model's output: {exc}")

    # A file the model never saw in full cannot be safely rewritten: what
    # it emits would be reconstructed from an excerpt (or from nothing),
    # and everything it didn't see would be silently deleted. Retrieval
    # makes this reachable — it puts partial files in the prompt — so it
    # has to be a hard gate, not a prompt-level request.
    blind_rewrites = [
        path
        for path in files
        if path not in existing and os.path.exists(os.path.join(project_root, path))
    ]
    if blind_rewrites:
        fail(
            "Refusing to rewrite file(s) the model was not shown in full:",
            [
                f"{path} — re-run with: specops work {feature} --file {path}"
                for path in sorted(blind_rewrites)
            ],
        )

    try:
        patch = patchgen.build_patch(files, project_root)
    except patchgen.PatchGenError as exc:
        fail(f"Could not build a patch from the model's output: {exc}")

    # Rewriting an existing file can destroy work, unlike creating a new
    # one — so a rewrite that drops most of the original is refused rather
    # than silently applied.
    shrink = patchgen.check_shrinkage(files, project_root)
    if shrink:
        fail("Refusing a rewrite that appears to have dropped content:", shrink)

    with open(patch_path, "w") as f:
        f.write(patch)

    check = subprocess.run(
        ["git", "apply", "--check", patch_path], capture_output=True, text=True
    )
    if check.returncode != 0:
        fail(
            f"Generated patch does not apply cleanly: {patch_path}",
            [check.stderr.strip()],
        )

    # A file can be a perfectly valid diff and still be broken code, so the
    # resulting content gets parsed too. This is exact now: `files` holds
    # each file's final content, not a reconstruction from diff hunks.
    syntax_errors = _check_python_syntax(files) + _check_typescript_syntax(files)
    if syntax_errors:
        fail(f"Generated file(s) failed a syntax check: {patch_path}", syntax_errors)

    # A patch was generated and is structurally valid, but not yet reviewed:
    # it must pass 'specops review' before it becomes eligible for apply.
    SM.advance(feature, REVIEW_PATCH)
    created = [p for p in files if not os.path.exists(os.path.join(project_root, p))]
    modified = [p for p in files if p not in created]
    print(f"Patch generated: {patch_path}")
    if created:
        print(f"  creates: {', '.join(sorted(created))}")
    if modified:
        print(f"  modifies: {', '.join(sorted(modified))}")
    print("State: REVIEW_PATCH. Run 'specops review <feature>' before apply.")


def cmd_review(args):
    feature = validate_feature(args.feature) if args.feature else None
    print("Running review (validators)...")
    # Ensure venv-only tools (e.g. pytest) resolve even when this process was
    # launched via the venv's console-script entrypoint (e.g. from Neovim)
    # without the venv being activated in the caller's shell.
    env = os.environ.copy()
    venv_bin = os.path.dirname(sys.executable)
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    # validators.sh lives in the engine, not the project, and needs to know
    # where to find its own jest/ts-jest install regardless of which
    # project's directory it's actually validating.
    env["SPECOPS_ENGINE_ROOT"] = ENGINE_ROOT
    result = subprocess.run(["bash", VALIDATORS_SH], env=env)
    passed = result.returncode == 0
    if feature:
        state = SM.advance(feature, APPLY_PENDING if passed else WORK_DRAFT)
        prompt_meta = {"prompt_hash": "n/a", "rag_sources": []}
        resp = {"response_text": "", "model": "n/a"}
        audit_log(
            "REVIEW",
            prompt_meta,
            resp,
            validators_run=["tools/validators.sh"],
            status=state["stage"],
            feature=feature,
        )
        if passed:
            print(f"Review passed. State: APPLY_PENDING.")
        else:
            print(f"Review failed. State reset to WORK_DRAFT — fix and re-run work/review.")
    if not passed:
        raise SystemExit(1)


def cmd_apply(args):
    feature = validate_feature(args.feature)
    patch_path = f".specops/out/{feature}.patch"
    if not os.path.exists(patch_path):
        print("Patch not found:", patch_path)
        return

    state = SM.load(feature)
    if state.get("stage") != APPLY_PENDING:
        print(
            f"Cannot apply: feature '{feature}' is in stage "
            f"'{state.get('stage', 'UNKNOWN')}', expected APPLY_PENDING. "
            "Run 'specops review <feature>' and ensure it passes first."
        )
        raise SystemExit(1)

    confirm = input(f"Apply patch {patch_path}? Type 'yes' to proceed: ")
    if confirm.strip().lower() != "yes":
        print("Aborted by user.")
        return

    branch = f"feat/{feature}"
    current_branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    if current_branch != branch:
        exists = (
            subprocess.run(["git", "rev-parse", "--verify", branch], capture_output=True).returncode
            == 0
        )
        if exists:
            # A previous apply already used this branch name. Each apply is a
            # fresh attempt against regenerated spec/plan/patch content, so
            # start the branch over from the current commit instead of
            # reusing stale history — reusing it via a plain checkout also
            # fails outright whenever freshly regenerated (untracked) specs
            # or plans collide with what that old branch already tracked.
            subprocess.run(["git", "branch", "-D", branch], check=True)
        subprocess.run(["git", "checkout", "-b", branch], check=True)

    try:
        subprocess.run(["git", "apply", patch_path], check=True)
        with open(patch_path) as f:
            patch_content = f.read()
        # Stage only what this feature actually touches — the patch's own
        # new files plus its spec artifact — never `git add .`. A blanket
        # add would sweep in any unrelated work-in-progress sitting
        # uncommitted elsewhere in the working tree into this feature's
        # commit, silently mixing unrelated changes together. plans/ and
        # out/ are gitignored on purpose (ephemeral working files) and stay
        # that way — only specs/ was ever meant to be part of the record.
        files_to_add = patchgen.paths_in_patch(patch_content)
        spec_path = f".specops/specs/{feature}.md"
        if os.path.exists(spec_path):
            files_to_add.append(spec_path)
        subprocess.run(["git", "add", *files_to_add], check=True)
        subprocess.run(["git", "commit", "-m", "specops: apply patch"], check=True)
    except subprocess.CalledProcessError as exc:
        print(
            f"Apply failed on branch '{branch}': {exc}. "
            "The patch was not applied; fix it (or regenerate with 'specops work') "
            "and re-run review before trying apply again."
        )
        raise SystemExit(1)

    SM.advance(feature, APPLIED)
    print("Patch applied and committed on new branch.")

    # Generated after the commit exists, since it records that commit's own
    # SHA — so it lands in its own small follow-up commit rather than the
    # code-change commit itself.
    cert_path = certificate.generate(feature)
    subprocess.run(["git", "add", cert_path], check=True)
    subprocess.run(
        ["git", "commit", "-m", f"specops: add change certificate for {feature}"],
        check=True,
    )
    print(f"Change certificate: {cert_path}")


def cmd_index(args):
    from rags import code_index

    print("Indexing project code...")
    files, chunks = code_index.build_index(os.getcwd())
    if files == 0:
        print("No indexable source files found — nothing to index.")
        return
    print(f"Indexed {chunks} chunk(s) across {files} file(s).")
    print("The work phase can now find relevant existing code on its own.")


def cmd_project_init(args):
    specops_dir, already_existed = project_mod.init_project(args.path or os.getcwd())
    if already_existed:
        print(f"Already initialized: {specops_dir}")
    else:
        print(f"Initialized {specops_dir}")
        print("Edit governance.yml to match this project, then add notes under rags/.")


def main():
    p = argparse.ArgumentParser(prog="specops")
    p.add_argument(
        "--project",
        default=None,
        help="Path to the project to operate on. Defaults to discovering a "
        ".specops/ directory starting from the current directory and "
        "walking up, the same way git looks for .git/.",
    )
    sub = p.add_subparsers(dest="cmd")
    b = sub.add_parser("brainstorm")
    b.add_argument("feature")
    b.add_argument("--notes")
    pl = sub.add_parser("plan")
    pl.add_argument("feature")
    pl.add_argument("--spec", default="")
    w = sub.add_parser("work")
    w.add_argument("feature")
    w.add_argument("--plan", default="")
    w.add_argument(
        "--file",
        action="append",
        default=[],
        help="Existing file to show the model so it can modify it. Repeatable. "
        "Files named in the spec/plan are picked up automatically; use this to "
        "be explicit.",
    )
    r = sub.add_parser("review")
    r.add_argument("feature", nargs="?")
    a = sub.add_parser("apply")
    a.add_argument("feature")
    sub.add_parser(
        "index",
        help="Build the semantic index over this project's source code, so "
        "the work phase can find relevant existing files on its own.",
    )
    proj = sub.add_parser("project")
    proj_sub = proj.add_subparsers(dest="project_cmd")
    proj_init = proj_sub.add_parser("init")
    proj_init.add_argument("path", nargs="?", default=None)

    args = p.parse_args()

    if args.cmd == "project":
        if args.project_cmd == "init":
            cmd_project_init(args)
        else:
            proj.print_help()
        return

    if args.cmd is None:
        p.print_help()
        return

    root = project_mod.find_project_root(explicit=args.project)
    os.chdir(root)

    if args.cmd == "brainstorm":
        cmd_brainstorm(args)
    elif args.cmd == "plan":
        cmd_plan(args)
    elif args.cmd == "work":
        cmd_work(args)
    elif args.cmd == "review":
        cmd_review(args)
    elif args.cmd == "apply":
        cmd_apply(args)
    elif args.cmd == "index":
        cmd_index(args)


if __name__ == "__main__":
    main()
