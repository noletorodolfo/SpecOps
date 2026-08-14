# AWS Well-Architected — Reliability & Scalability (summary)
- Pillars relevant to the plan phase: Reliability (recover from failure automatically), Performance Efficiency (scale with demand, not headcount), Operational Excellence (small reversible changes over big ones).
- Pattern: design for failure at the component boundary — timeouts, retries with backoff, circuit breakers — instead of assuming the dependency is always up.
- Pattern: prefer horizontal scaling with stateless compute; push state to managed stores (RDS, DynamoDB, S3) that already handle replication and failover.
- Practical note: define the SLO before picking the architecture — "how much downtime is acceptable" determines whether multi-AZ is enough or multi-region is required, and that decision belongs in the plan artifact, not discovered during an incident.
