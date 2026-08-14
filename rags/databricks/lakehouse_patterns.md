# Lakehouse Patterns (summary)
- Medallion architecture: bronze (raw, as-landed), silver (cleaned, deduplicated, typed), gold (business-level aggregates) — each layer is a checkpoint that lets you replay downstream without re-touching upstream.
- Prefer schema-on-write for silver/gold (enforced via Delta Lake constraints) even though bronze can stay schema-on-read; catching a bad record at silver is far cheaper than debugging a broken dashboard at gold.
- Idempotent writes (MERGE/upsert keyed by a stable id) so a pipeline re-run from a failure doesn't duplicate data — matches the "compensating transactions" note under distributed systems.
- Practical note: partition by a column actually used in downstream filters (usually date), not by whatever is easiest to compute — wrong partitioning silently turns every query into a full scan.
