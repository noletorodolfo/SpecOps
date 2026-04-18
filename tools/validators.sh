#!/usr/bin/env bash
set -e
echo "Running validators..."
terraform validate || exit 1
kubeval --schema-location 'https://raw.githubusercontent.com/instrumenta/kubernetes-json-schema/master' ./k8s/*.yaml || exit 1
pytest -q || exit 1
echo "Validators passed"

