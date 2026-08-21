# Architecture Decision Records (format)
- Minimal structure: Title, Status (proposed/accepted/superseded), Context (the forces at play, not the solution), Decision (what was chosen, stated as a sentence), Consequences (what gets easier, what gets harder).
- One decision per ADR — if you're listing multiple unrelated choices, split it; a single ADR should be readable in under two minutes.
- Never delete a superseded ADR: mark it "Superseded by ADR-00XX" and keep it — the history of *why we changed our mind* is the actual value, not just the current state.
- Practical note: an ADR is written when a decision is genuinely reversible-but-costly-to-reverse (framework choice, data model, deploy topology) — trivial or free-to-reverse choices don't need one.
