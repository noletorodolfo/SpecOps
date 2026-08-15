#!/usr/bin/env node
// Syntax-only check for a generated .ts/.tsx file, mirroring what
// ast.parse() does for Python: catches malformed code (unbalanced
// braces, invalid tokens, a line the model squashed together) without
// requiring the file's imports to resolve or @types packages to be
// installed — that's what full type-checking would need, and would
// produce false positives for perfectly valid generated code.
import ts from "typescript";
import { readFileSync } from "node:fs";

const path = process.argv[2];
const source = readFileSync(path, "utf8");

const sourceFile = ts.createSourceFile(
  path,
  source,
  ts.ScriptTarget.Latest,
  /* setParentNodes */ true,
  path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS
);

const diagnostics = sourceFile.parseDiagnostics ?? [];

if (diagnostics.length > 0) {
  for (const d of diagnostics) {
    const { line, character } = sourceFile.getLineAndCharacterOfPosition(d.start);
    const message = ts.flattenDiagnosticMessageText(d.messageText, "\n");
    console.error(`${path}:${line + 1}:${character + 1}: ${message}`);
  }
  process.exit(1);
}

process.exit(0);
