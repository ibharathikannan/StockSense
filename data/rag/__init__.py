"""RAG / decision-explanation layer (offline batch).

This package produces the evidence and grounded explanations that back the three research
signals (Explore / Monitor / Caution). It is deliberately offline: embeddings, retrieval
and generation run in a batch that writes recommendation snapshots to the application
database, matching the end-of-day / no-live-feeds constraint.

Boundaries this package must respect (from docs/ai/DATA_GATE.md):
- Explanations cite sources or abstain; they never invent reasons.
- No specific financial figures (SEC exhibits uncollected, tables flattened).
- Company sentiment is exploratory and caveated, never presented as fact.
- RAG explains the already-decided signal; it never changes it.
"""
