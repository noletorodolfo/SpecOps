"""Turn full-file model output into a git-applicable patch.

The work phase used to ask the model for a unified diff directly, which
only ever worked for *new* files: an edit diff requires exact line
numbers and byte-identical context lines from the original, which a
model reliably gets wrong. So instead the model emits each file's
complete final content and this module computes the diff with difflib.

That inverts the split of responsibilities in the right direction — the
mechanical part (diff format, line numbers, hunk headers) becomes
deterministic and correct by construction, and the model is left doing
only the semantic part.
"""

import difflib
import os
import re

FILE_BLOCK_RE = re.compile(
    r"^<<<SPECOPS_FILE\s+(?P<path>.+?)\s*>>>\n(?P<body>.*?)(?:\n)?^<<<SPECOPS_END>>>\s*$",
    re.DOTALL | re.MULTILINE,
)

FENCE_RE = re.compile(r"\A```[^\n]*\n(.*)\n```\s*\Z", re.DOTALL)

# A rewrite that loses most of a non-trivial file is almost always the
# model dropping content it didn't bother to repeat, not a deliberate
# refactor. Blocking is the safe default: unlike a bad new file, a bad
# rewrite destroys work that already existed.
SHRINK_MIN_ORIGINAL_LINES = 10
SHRINK_RATIO = 0.5


class PatchGenError(Exception):
    """Raised when model output can't be turned into a safe patch."""


def _strip_fence(text):
    """Models wrap file bodies in markdown fences despite being told not
    to. Strip exactly one wrapping fence, leaving fences that are part of
    the file's real content (e.g. a generated .md) alone."""
    match = FENCE_RE.match(text.strip("\n"))
    if match:
        return match.group(1)
    return text


def parse_file_blocks(text):
    """Extract {path: content} from the work phase's response."""
    files = {}
    for match in FILE_BLOCK_RE.finditer(text):
        path = match.group("path").strip()
        body = _strip_fence(match.group("body"))
        # Normalize to exactly one trailing newline: it sidesteps git's
        # "\ No newline at end of file" marker entirely, which difflib
        # doesn't emit and which previously caused malformed patches.
        files[path] = body.rstrip("\n") + "\n"

    if not files:
        if "diff --git" in text or "--- /dev/null" in text:
            raise PatchGenError(
                "Model returned a unified diff instead of full file contents. "
                "The work phase now expects <<<SPECOPS_FILE path>>> blocks."
            )
        raise PatchGenError(
            "No <<<SPECOPS_FILE path>>> ... <<<SPECOPS_END>>> blocks found in the "
            "model's response."
        )
    return files


def validate_paths(files, project_root):
    """Reject anything that would write outside the project. The model
    chooses these paths, so they're untrusted input — and unlike before,
    a path can now land on an existing file."""
    root = os.path.realpath(project_root)
    for path in files:
        if os.path.isabs(path):
            raise PatchGenError(f"Refusing absolute path from model output: {path}")
        resolved = os.path.realpath(os.path.join(root, path))
        if resolved != root and not resolved.startswith(root + os.sep):
            raise PatchGenError(
                f"Refusing path that escapes the project directory: {path}"
            )


def check_shrinkage(files, project_root):
    """Report files whose rewrite drops most of the original content."""
    warnings = []
    for path, content in files.items():
        full = os.path.join(project_root, path)
        if not os.path.exists(full):
            continue
        with open(full, encoding="utf-8") as f:
            original = f.read()
        original_lines = len(original.splitlines())
        new_lines = len(content.splitlines())
        if (
            original_lines >= SHRINK_MIN_ORIGINAL_LINES
            and new_lines < original_lines * SHRINK_RATIO
        ):
            warnings.append(
                f"{path}: rewrite shrank {original_lines} lines to {new_lines} "
                f"(under {int(SHRINK_RATIO * 100)}% of the original) — the model "
                f"likely dropped content instead of rewriting it"
            )
    return warnings


def build_patch(files, project_root):
    """Build a single git-applicable patch from {path: final_content}.

    Reads each target's current content from disk (empty for a new file)
    and diffs against the model's version, so hunk headers and context
    lines are computed rather than trusted.
    """
    parts = []
    for path in sorted(files):
        new_content = files[path]
        full = os.path.join(project_root, path)
        is_new = not os.path.exists(full)

        if is_new:
            original = ""
        else:
            with open(full, encoding="utf-8") as f:
                original = f.read()

        if original == new_content:
            continue  # nothing to do for this file

        original_lines = original.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff_body = list(
            difflib.unified_diff(
                original_lines,
                new_lines,
                fromfile="/dev/null" if is_new else f"a/{path}",
                tofile=f"b/{path}",
                n=3,
            )
        )
        if not diff_body:
            continue

        header = [f"diff --git a/{path} b/{path}\n"]
        if is_new:
            header.append("new file mode 100644\n")
        parts.extend(header)
        parts.extend(diff_body)

    if not parts:
        raise PatchGenError(
            "The model's output is identical to what's already on disk — nothing to apply."
        )

    patch = "".join(parts)
    if not patch.endswith("\n"):
        patch += "\n"
    return patch


def paths_in_patch(patch_text):
    """Every file path a patch touches, read from its '+++ b/<path>' lines."""
    return [
        m.group(1).strip()
        for m in re.finditer(r"^\+\+\+ b/(.+)$", patch_text, re.MULTILINE)
    ]
