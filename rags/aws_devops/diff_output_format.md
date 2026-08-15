# Expected output format for the work phase
- Output raw unified diff text only — no explanation, no markdown code fences (no ```diff blocks), nothing before the first `diff --git` line or after the last `+`/`-`/context line.
- Prefer a new-file diff over editing an existing file: it never depends on matching existing line numbers or content, so it always applies cleanly.
- Exact shape for a new file:

diff --git a/path/to/new_file.py b/path/to/new_file.py
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/path/to/new_file.py
@@ -0,0 +1,3 @@
+line one
+line two
+line three

- The `@@ -0,0 +1,N @@` line's N must equal the number of `+` lines that follow it — a mismatch is the most common reason `git apply` rejects an otherwise reasonable-looking diff.
