# TOGAF ADM (summary)
- ADM is a cycle, not a waterfall: Preliminary -> A (Vision) -> B (Business) -> C (Data/Application) -> D (Technology) -> E (Opportunities) -> F (Migration Planning) -> G (Governance) -> H (Change Management).
- Business Architecture (Phase B) is where domains, capabilities and value streams get named before any tech decision — this maps directly onto SpecOps' spec phase output (domains, bounded_contexts, business_capabilities).
- Practical note: skip phases that don't apply to a small feature, but never skip naming the business capability — it's the anchor that keeps later phases (data, application, technology) traceable back to a reason "why".
- Architecture Requirements Specification is the artifact that should survive into the plan phase; treat it as the contract between spec and plan.
