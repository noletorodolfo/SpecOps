#!/usr/bin/env bash
set -e
echo "Running validators..."
terraform validate || exit 1
kubeval --schema-location 'https://raw.githubusercontent.com/instrumenta/kubernetes-json-schema/master' ./k8s/*.yaml || exit 1
pytest -q || exit 1

# jest, only when there's actually a TS test file to run — an empty
# testMatch is an error, not a pass, as far as jest is concerned.
if find . -not -path './node_modules/*' -not -path './.venv/*' \( -name '*.test.ts' -o -name '*.spec.ts' \) | grep -q .; then
  echo "Running jest..."
  npx jest || exit 1
fi

echo "Validators passed"

