# RAG evaluation

`data/evaluation/rag_eval.py` evaluates the offline RAG layer (`data/rag/retriever.py` →
`data/rag/explainer.py`, assembled by `data/rag/assemble_snapshots.py`). Both evaluations are
read-only and use local cross-encoder judges (no external API). Reports are written to the
ignored `data/artifacts/evaluation/rag/`.

```bash
python -m data.evaluation.rag_eval retrieval --env-file data/.env    # shared DB
python -m data.evaluation.rag_eval generation                        # newest snapshot JSONL
```

## Retrieval: precision@k, recall@k, context relevance

- **Queries (25).** The two production templates from `assemble_snapshots.py` —
  `"{name} latest news and developments"` (news) and `"{name} business risks and financial
  results"` (SEC) — for the first 10 recommendation-eligible tickers, plus 5 topical
  questions (e.g. "NVIDIA data center AI chip demand"). Ticker, `as_of` and source-type
  filters match production.
- **System under test.** The production hybrid path: pgvector top-20 + full-text top-20,
  RRF fusion, content-hash dedup, abstention below similarity 0.30.
- **Relevance labels.** `cross-encoder/ms-marco-MiniLM-L-6-v2` scores every candidate in
  the pool (vector top-20 ∪ keyword top-20); a chunk is relevant when sigmoid(score) ≥ 0.5.
- **Metrics.**
  - precision@k = relevant in top k / k
  - recall@k = relevant in top k / relevant in pool
  - context relevance@k = mean judge score of the top-k contexts actually returned

Recall is a **pooled** estimate (relevant chunks neither arm surfaces are not counted). Many
queries have 10–40 relevant chunks in the pool, so recall@5 is bounded well below 1 by
construction; precision and context relevance are the more meaningful numbers at the small
k production uses (news k=3, SEC k=2).

### Results — 2026-10-24 (as_of = run time, 25 queries, 0 abstained)

| Query kind | n | P@1 | P@3 | P@5 | R@1 | R@3 | R@5 | CR@1 | CR@3 | CR@5 |
|---|---|---|---|---|---|---|---|---|---|---|
| all | 25 | 0.760 | 0.813 | 0.824 | 0.042 | 0.147 | 0.251 | 0.773 | 0.823 | 0.812 |
| production-news | 10 | 0.500 | 0.667 | 0.700 | 0.035 | 0.163 | 0.291 | 0.556 | 0.713 | 0.700 |
| production-sec | 10 | 0.900 | 0.867 | 0.860 | 0.056 | 0.161 | 0.266 | 0.882 | 0.849 | 0.838 |
| topical | 5 | 1.000 | 1.000 | 1.000 | 0.029 | 0.086 | 0.143 | 0.990 | 0.990 | 0.988 |

The generic production news query is the weakest: its top result is judged relevant only half
the time (MRVL SEC and AAPL news had just 2 relevant chunks in the pool). Specific topical
questions retrieve almost perfectly.

## Generation: faithfulness

- **Answer / context.** Each distinct `explanation.text` in the snapshot file (snapshots
  repeat per risk tier) against the passages the explainer was given: evidence title +
  snippet and the signal's `decision_trace`.
- **Claims.** Explanation lines minus template scaffolding (stance headline, section
  headings, `[n] title — source` lines, fixed abstention/provisional notes), split into
  sentences.
- **Judge.** A claim is supported if it appears verbatim in a passage, otherwise if
  `cross-encoder/nli-deberta-v3-small` gives entailment ≥ 0.5 against any passage or any
  single sentence of one (NLI models under-score long multi-sentence premises).
- **Metric.** faithfulness = supported claims / claims.
- **Negative control.** The same explanations with one fabricated claim appended
  ("Revenue rose 40% last quarter after the company accepted a takeover offer.").

### Results — 2026-10-24 (`snapshots-2026-10-21-manual.jsonl`)

| Metric | Value |
|---|---|
| Distinct explanations / claims | 450 / 10,503 |
| Faithfulness (mean) | 1.000 |
| Fully faithful explanations | 1.000 |
| Control: faithfulness with one fabricated claim | 0.958 |
| Control: fabricated claim flagged unsupported | 1.000 |

Faithfulness of 1.0 is expected: the shipped explainer is template-first and quotes the
evidence and trace verbatim (the optional Ollama rewrite was not used for this snapshot).
The control shows the judge flags every invented claim, so the metric would expose an
unfaithful generator such as the LLM rewrite path.

## Limitations

- Labels come from a model judge, not human annotation; thresholds are fixed at 0.5.
- Recall is relative to the judged pool; the query set is small (25) and sector-skewed
  (the first eligible tickers are mostly semiconductors).
- Retrieval results depend on the database contents and `as_of` at run time.
