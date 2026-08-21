const path = require("node:path");

/** @type {import('jest').Config} */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  testMatch: ["**/*.test.ts", "**/*.spec.ts"],
  // node_modules/.venv/rags/.specops all get scanned by default without
  // this — a project mixes generated TS features into its own tree, so
  // keep Jest scoped to real test files.
  testPathIgnorePatterns: ["/node_modules/", "/.venv/", "/.specops/"],
  // tsconfig.json sets isolatedModules: true — transpile-only, no full
  // type-checking. We already have a dedicated syntax-only gate
  // (tools/ts_syntax_check.mjs) in cmd_work; ts-jest's default
  // type-checking is stricter than that on purpose and would block on
  // things the tsc syntax check correctly lets through.
  //
  // Resolved via __dirname (this file's own location, i.e. the engine),
  // not cwd — validators.sh invokes this with --rootDir pointing at
  // whatever project is being reviewed, which won't have its own
  // tsconfig.json.
  transform: {
    "^.+\\.tsx?$": ["ts-jest", { tsconfig: path.join(__dirname, "tsconfig.json") }],
  },
};
