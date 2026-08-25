import os

import pytest

from core import patchgen


def test_parse_file_blocks_extracts_path_and_content():
    text = (
        "<<<SPECOPS_FILE src/greet.py>>>\n"
        "def greet(name):\n"
        "    return name\n"
        "<<<SPECOPS_END>>>\n"
    )
    assert patchgen.parse_file_blocks(text) == {
        "src/greet.py": "def greet(name):\n    return name\n"
    }


def test_parse_file_blocks_handles_multiple_files():
    text = (
        "<<<SPECOPS_FILE a.py>>>\nx = 1\n<<<SPECOPS_END>>>\n"
        "<<<SPECOPS_FILE b.py>>>\ny = 2\n<<<SPECOPS_END>>>\n"
    )
    files = patchgen.parse_file_blocks(text)
    assert files == {"a.py": "x = 1\n", "b.py": "y = 2\n"}


def test_parse_file_blocks_strips_a_wrapping_markdown_fence():
    text = (
        "<<<SPECOPS_FILE a.py>>>\n"
        "```python\n"
        "x = 1\n"
        "```\n"
        "<<<SPECOPS_END>>>\n"
    )
    assert patchgen.parse_file_blocks(text) == {"a.py": "x = 1\n"}


def test_parse_file_blocks_rejects_a_unified_diff_with_a_clear_message():
    diff = "diff --git a/x.py b/x.py\n--- /dev/null\n+++ b/x.py\n@@ -0,0 +1 @@\n+x = 1\n"
    with pytest.raises(patchgen.PatchGenError, match="unified diff"):
        patchgen.parse_file_blocks(diff)


def test_parse_file_blocks_rejects_output_with_no_blocks():
    with pytest.raises(patchgen.PatchGenError, match="No <<<SPECOPS_FILE"):
        patchgen.parse_file_blocks("Sure! Here's the code you asked for.")


def test_build_patch_for_a_new_file_applies_cleanly(tmp_path):
    files = {"new.py": "x = 1\ny = 2\n"}
    patch = patchgen.build_patch(files, str(tmp_path))

    assert "diff --git a/new.py b/new.py" in patch
    assert "new file mode 100644" in patch
    assert "--- /dev/null" in patch
    assert "@@ -0,0 +1,2 @@" in patch
    assert "+x = 1" in patch


def test_build_patch_for_an_edit_uses_real_line_numbers_and_context(tmp_path):
    target = tmp_path / "existing.py"
    target.write_text("line1\nline2\nline3\n")

    files = {"existing.py": "line1\nCHANGED\nline3\n"}
    patch = patchgen.build_patch(files, str(tmp_path))

    assert "new file mode" not in patch  # it's an edit, not a creation
    assert "--- a/existing.py" in patch
    assert "-line2" in patch
    assert "+CHANGED" in patch
    assert " line1" in patch  # context line preserved


def test_build_patch_skips_files_that_are_already_identical(tmp_path):
    (tmp_path / "same.py").write_text("x = 1\n")
    (tmp_path / "diff.py").write_text("old\n")

    patch = patchgen.build_patch(
        {"same.py": "x = 1\n", "diff.py": "new\n"}, str(tmp_path)
    )

    assert "same.py" not in patch
    assert "diff.py" in patch


def test_build_patch_raises_when_nothing_would_change(tmp_path):
    (tmp_path / "same.py").write_text("x = 1\n")
    with pytest.raises(patchgen.PatchGenError, match="identical"):
        patchgen.build_patch({"same.py": "x = 1\n"}, str(tmp_path))


def test_build_patch_output_actually_applies_with_git(tmp_path):
    """The whole point of generating the diff instead of trusting the
    model is that git accepts it — so assert that against real git."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "existing.py").write_text("a\nb\nc\n")

    patch = patchgen.build_patch(
        {"existing.py": "a\nB-CHANGED\nc\n", "brand_new.py": "hello\n"},
        str(tmp_path),
    )
    patch_file = tmp_path / "generated.patch"
    patch_file.write_text(patch)

    result = subprocess.run(
        ["git", "apply", "--check", "generated.patch"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    subprocess.run(["git", "apply", "generated.patch"], cwd=tmp_path, check=True)
    assert (tmp_path / "existing.py").read_text() == "a\nB-CHANGED\nc\n"
    assert (tmp_path / "brand_new.py").read_text() == "hello\n"


def test_validate_paths_rejects_traversal_outside_the_project(tmp_path):
    with pytest.raises(patchgen.PatchGenError, match="escapes the project"):
        patchgen.validate_paths({"../evil.py": "x = 1\n"}, str(tmp_path))


def test_validate_paths_rejects_absolute_paths(tmp_path):
    with pytest.raises(patchgen.PatchGenError, match="absolute path"):
        patchgen.validate_paths({"/etc/passwd": "x\n"}, str(tmp_path))


def test_validate_paths_allows_normal_nested_paths(tmp_path):
    patchgen.validate_paths({"src/deep/mod.py": "x = 1\n"}, str(tmp_path))


def test_check_shrinkage_flags_a_rewrite_that_dropped_content(tmp_path):
    original = "\n".join(f"line{i}" for i in range(30)) + "\n"
    (tmp_path / "big.py").write_text(original)

    warnings = patchgen.check_shrinkage({"big.py": "line0\n"}, str(tmp_path))

    assert len(warnings) == 1
    assert "big.py" in warnings[0]


def test_check_shrinkage_ignores_new_files_and_small_files(tmp_path):
    (tmp_path / "tiny.py").write_text("a\nb\n")
    warnings = patchgen.check_shrinkage(
        {"tiny.py": "a\n", "brand_new.py": ""}, str(tmp_path)
    )
    assert warnings == []


def test_check_shrinkage_allows_a_modest_reduction(tmp_path):
    original = "\n".join(f"line{i}" for i in range(20)) + "\n"
    (tmp_path / "f.py").write_text(original)

    kept = "\n".join(f"line{i}" for i in range(15)) + "\n"
    assert patchgen.check_shrinkage({"f.py": kept}, str(tmp_path)) == []


def test_paths_in_patch_lists_every_touched_file():
    patch = (
        "diff --git a/a.py b/a.py\n--- /dev/null\n+++ b/a.py\n@@ -0,0 +1 @@\n+x\n"
        "diff --git a/b/c.ts b/b/c.ts\n--- a/b/c.ts\n+++ b/b/c.ts\n@@ -1 +1 @@\n-x\n+y\n"
    )
    assert patchgen.paths_in_patch(patch) == ["a.py", "b/c.ts"]
