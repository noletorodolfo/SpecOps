#!/usr/bin/env bash
set -e
echo "Running validators..."

# terraform validate, only if there's actual IaC to check
if find . -maxdepth 3 -not -path './node_modules/*' -not -path './.venv/*' -name '*.tf' | grep -q .; then
  echo "Running terraform validate..."
  terraform validate || exit 1
fi

# kubeval, only if there are k8s manifests
if ls k8s/*.yaml 1>/dev/null 2>&1; then
  echo "Running kubeval..."
  kubeval --schema-location 'https://raw.githubusercontent.com/instrumenta/kubernetes-json-schema/master' ./k8s/*.yaml || exit 1
fi

# pytest, only if there's actual Python test code to run — a project with
# no Python in it at all shouldn't fail review because pytest found nothing
if find . -maxdepth 4 -not -path './node_modules/*' -not -path './.venv/*' \( -name 'test_*.py' -o -name '*_test.py' \) | grep -q .; then
  echo "Running pytest..."
  pytest -q || exit 1
fi

# jest, only when there's actually a TS test file to run — an empty
# testMatch is an error, not a pass, as far as jest is concerned. Uses the
# SpecOps engine's own jest/ts-jest install and config (isolatedModules,
# syntax-only — see jest.config.js) rather than requiring the project
# being reviewed to have its own test runner set up.
if find . -not -path './node_modules/*' -not -path './.venv/*' \( -name '*.test.ts' -o -name '*.spec.ts' \) | grep -q .; then
  echo "Running jest..."
  engine="${SPECOPS_ENGINE_ROOT:-.}"
  npx --prefix "$engine" jest --config "$engine/jest.config.js" --rootDir "$PWD" || exit 1
fi

echo "Validators passed"
