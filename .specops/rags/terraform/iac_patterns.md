# Terraform IaC Patterns (summary)
- State is the source of truth, not the code: always run `terraform plan` and read the diff before apply, even for changes that "should" be no-ops.
- Module boundaries should match ownership boundaries — a module per bounded_context (network, compute, data) keeps blast radius contained and makes `terraform validate` failures easy to attribute.
- Use remote state with locking (S3+DynamoDB, or Terraform Cloud) for anything beyond a solo experiment; local state plus concurrent applies is how state files get corrupted.
- Practical note: `terraform validate` only checks syntax/internal consistency, not whether the plan matches intent — SpecOps' review gate should treat a clean validate as necessary, not sufficient.
