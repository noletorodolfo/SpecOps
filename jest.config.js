/** @type {import('jest').Config} */
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  testMatch: ["**/*.test.ts", "**/*.spec.ts"],
  // node_modules/.venv/rags all get scanned by default without this —
  // this repo mixes generated TS features into the same tree as
  // SpecOps' own Python source, so keep Jest scoped to real test files.
  testPathIgnorePatterns: ["/node_modules/", "/.venv/"],
  // tsconfig.json sets isolatedModules: true — transpile-only, no full
  // type-checking. We already have a dedicated syntax-only gate
  // (tools/ts_syntax_check.mjs) in cmd_work; ts-jest's default
  // type-checking is stricter than that on purpose and would block on
  // things the tsc syntax check correctly lets through.
};
