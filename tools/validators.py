#!/usr/bin/env bash
set -e
echo "Running validators..."

# terraform validate if terraform files exist
if ls *.tf 1> /dev/null 2>&1; then
  echo "Running terraform validate..."
  terraform validate || { echo "terraform validate failed"; exit 1; }
fi

# kubeval if k8s manifests exist
if ls k8s/*.yaml 1> /dev/null 2>&1; then
  echo "Running kubeval..."
  kubeval k8s/*.yaml || { echo "kubeval failed"; exit 1; }
fi

# run pytest if tests exist
if [ -d "tests" ]; then
  echo "Running pytest..."
  pytest -q || { echo "pytest failed"; exit 1; }
fi

echo "Validators passed"

