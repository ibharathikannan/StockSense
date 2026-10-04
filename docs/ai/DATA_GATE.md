# Independent data-readiness gate — 2026-10-03

## Decision

**Gate completed; conditional readiness, not a blanket pass.** The user authorized
this evaluation after collection/preparation and verified migration. Three
independent evaluators reviewed numeric inputs, text evidence and storage. The
orchestrator reviewed their scripts/findings, checked the shared database read-only,
and consolidated this report. No downstream implementation is authorized here.

| Intended use | Verdict | Boundary |
| --- | --- | --- |
| Existing numeric calculations and stored text structure | PASS | Checked formulas, keys, metadata, offsets and source identities; semantic accuracy is separate |
| Price-only historical forecasting on the fixed 87-asset universe | CONDITIONAL | After-close origins, explicit feature allowlist, RSI policy, train-only preprocessing and purged temporal development/holdout folds |
| Historically point-in-time macro comparison | BLOCKED | Historical vintages and actual release times are unverified; revised-data proxy joins cannot establish historical gains |
| Current/live forecasts | BLOCKED | Prices end 2026-09-18; no validated forecast model/service or freshness contract exists |
| Bounded RAG experiments on reviewed narrative evidence | CONDITIONAL | Preserve dates/citations, restrict unsupported financial/event questions and abstain on absent evidence |
| Complete SEC financial/event explanations across the universe | BLOCKED | Relevant linked earnings/financial exhibits were not collected; flattened tables lose financial context |
| Validated company sentiment for forecasts or deterministic rules | BLOCKED | Observed subject-attribution errors and no independently labeled benchmark |
| Recent sentiment as historical 2021–2026 model inputs | BLOCKED | News versions became locally available on 2026-10-02; publication dates do not permit backdated joins |
| Shared snapshot existence and row-count relationships | PASS | Independently checked actual remote counts and parent joins; not a fresh complete byte/value verification |
| Team reproducibility and recovery from PostgreSQL alone | CONDITIONAL | Teammate read-only access, exact export/restore and backup recovery remain unverified |

A conditional verdict specifies a possible next experiment; it is neither a
forecast-performance result nor permission to start training or RAG implementation.
The gate did not perform retrieval/generation accuracy tests because those systems
do not exist yet.

## Evidence

### Numeric

- 135,593 price rows across 91 universe assets; 110,229 feature rows across exactly
  87 forecast-eligible assets, with 109,359 known labels and 870 unlabeled rows.
- Independent recomputation of 34 ticker-level fields on every feature row and
  four SPY/VIX fields found zero mismatches (tolerance 1e-10; maximum absolute
  error 5.11e-15). No duplicate keys or basic invalid price ranges were found.
- Labels use the tenth subsequent observed trading session. Training flags match;
  current unlabeled tails are exactly ten per asset. Same-date features require
  prediction after close and finalized source bars.
- At illustrative annual boundaries, 870 training rows cross into evaluation and
  must be purged by label-end date. The 2024/2025 validation windows also need 870
  tail rows removed so tuning does not consume subsequent held-out outcomes.
- Fourteen missing RSI values are zero-loss windows, not missing source prices.
  Define corrected semantics or a consistent train-only missing-data policy.
- All 5,345 macro vintage-end fields are null; fixed proxy lags and 3,045 missing
  CPI-YoY feature values limit macro use. Current selected universe, adjusted-price
  revisions and unavailable historical delivery times limit generalization/as-of
  claims. A BE return outlier is flagged for source verification, not auto-trimming.

See [NUMERIC_GATE.md](NUMERIC_GATE.md) for formulas, restrictions and split counts.

### Text

- All 5,168 prepared documents and 173,292 chunks passed the implemented identity,
  provenance, metadata, parent and exact-offset checks. An independent cached
  tokenizer sample of 87 chunks found maximum 220 tokens and zero discrepancies;
  full retokenization was not performed.
- All 90 local sentiment aggregates were independently recalculated; 4,523 scored
  associations retain finite estimates and matching attribution inputs, while
  2,699 remain unavailable. This does not establish semantic sentiment accuracy.
- Primary SEC documents omit relevant exhibits: UNP/TMO earnings releases and CCJ
  6-K/40-F incorporated financial materials are concrete examples. Issuer coverage
  does not establish complete financial/event evidence.
- Sampled sentiment errors attribute Morgan Stanley's analyst action on TEO to MS,
  and DELL's movement to NOW through sentence/list segmentation. No corpus-wide
  error-rate estimate can be inferred from the small sample.
- There are 5,369 excess exact duplicate chunks. Table-of-contents markers appear
  in 25,230 chunks; those are heuristic flags, not proven useless passages.
- A synthetic null availability timestamp crashes preparation with AttributeError.
  Stored inputs contain no such invalid record. Unknown tickers and future
  availability are rejected. The text gate exits 1 for this demonstrated robustness
  defect while preserving complete evidence; this is an expected gate finding.

See [TEXT_GATE.md](TEXT_GATE.md) for source samples and attribution limitations.

### Shared storage

The independently recomputed original source snapshot is
`ef82d22e57e68952a4187ef5668498208fe8748522b043151106631b5bde4451`, schema
`ss_ef82d22e57e68952a418`: 778 files, 2,270,855,097 original bytes, 12 tables and
662,926 rows. All local rows decode through the import adapters. Each SEC document
maps to one archived raw HTML file; preparation source hashes match.

The orchestrator connected to `stocksense_data` with default read-only transactions
and checked the exact snapshot status (`complete`), actual counts for all 12 tables,
778 archive references/total original size, and zero orphan chunks. Complete remote
row-value/schema and decompressed archive-hash verification was documented during
migration; it was not repeated during this gate. Other teammates' access and backup
recovery were not tested.

New gate JSON evidence under `data/artifacts/evaluation/` is currently included by
ordinary migration inventory scans, changing identity even though the original
778 files remain unchanged. The storage gate explicitly excludes evaluation
outputs to compare the original snapshot. Fix the importer boundary before the
next normal import/verify cycle; keep the existing schema pinned.

The archived news sources are standardized JSONL plus coverage, not complete raw
HTTP responses. Exact selected bytes are preserved, but omitted provider fields
cannot be recovered from those archives. Stale architecture statements also mix
MongoDB and PostgreSQL, while current application code uses PostgreSQL; reconcile
those separately without changing runtime behavior during this evaluation.

See [STORAGE_GATE.md](STORAGE_GATE.md) for contracts and verification limits.

## Required actions, in dependency order

1. **Pipeline robustness and snapshot boundary:** reject null/invalid timestamps
   cleanly; exclude evaluation artifacts from source inventory. Add focused
   regressions and demonstrate existing source hashes/schema stay pinned.
2. **Forecast experiment contract:** choose the price-only dataset, freeze hashes,
   establish after-close origins and label-end purges for train and validation,
   and resolve the 14 RSI values consistently. Define train-only imputation,
   encoding, scaling and optional PCA; compare original and PCA features later.
   Keep macro/recent sentiment out of the initial historical experiment.
3. **Evidence completeness:** ingest relevant linked SEC exhibits with parent
   accession, dates, provenance and missing/failed status; preserve table units,
   periods and headers or explicitly restrict numerical financial claims.
   Recheck new evidence before treating it as approved RAG input.
4. **Sentiment quality:** correct subject-versus-analyst attribution and financial
   sentence/list handling, then build a labeled ticker-stratified benchmark and
   abstention policy. Until validated, local/provider sentiment remains exploratory.
5. **Shared consumers:** establish teammate read-only access, versioned export/
   restore or SQL consumers, and a demonstrated recovery path. Preserve originals.
6. **Later enhancements:** obtain genuine macro vintages before point-in-time
   macro comparisons; establish incremental collection/freshness policy; evaluate
   duplicate/boilerplate handling on retrieval quality when retrieval exists.

These actions have different scopes: fixing the timestamp/inventory defects does
not solve missing exhibits, and complete RAG evidence is not required to run a
properly scoped price-only forecast experiment. No source recollection, repairs,
learned transforms or models were performed as part of this gate.

## Reproduction and validation

Run from the repository root in the existing data environment:

```bash
.venv-data/bin/python -m data.evaluation.numeric_gate
.venv-data/bin/python -m data.evaluation.text_gate
.venv-data/bin/python -m data.evaluation.storage_gate
```

Numeric/text commands write ignored evidence JSON under `data/artifacts/evaluation/`.
Storage emits evidence to stdout, excludes audit files, loads no credentials and
opens no connection. The remote read-only check was a separate orchestrator action.

Numeric standalone/module execution agrees. A corrupted-target temporary fixture
was detected and exited 1; missing required inputs exited 2. Text exits 1 for the
null-timestamp failure probe, with zero existing-corpus integrity violations.
Storage adapter/CLI tests passed: 16 tests and 12 subtests. Evaluation scripts
compiled and `git diff --check` passed. Input hashes and the original snapshot
identity remained unchanged. No destructive database suite, provider download,
model inference/training, embedding/index generation, deployment or Git commit
was performed.
