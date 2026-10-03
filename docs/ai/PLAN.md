# AI work plan

## Authorized work and stop point

Collection, preparation and shared-data migration are complete. On 2026-10-03
the user authorized the independent data-readiness gate. Audit existing sources
and snapshots, record reproducible evidence and consolidate readiness decisions.
Stop after the gate report and required-fix list. Model training, learned PCA/LDA
fitting, retrieval indexes, RAG generation, rule-engine changes, application
integration, commits, pushes and deployment are not authorized by this gate.

Use `data/asset_universe.csv`: 80 stocks, 10 ETFs, and VIX for context; preserve
the existing forecast eligibility flags. Work in this worktree, with no more
than three concurrent subagents. The lead orchestrator integrates shared files.

## Assignments

| Role | Owned implementation | Outcome |
| --- | --- | --- |
| Market data | market preparation script, feature-builder interface, associated tests | Audit committed data; write price-only and macro candidate features with provenance |
| SEC filings | SEC collector and associated tests | Issuer mapping, filing metadata/documents, coverage, resumable collection |
| Market news | News collector and associated tests | Alpaca news, optional Alpha Vantage sentiment, coverage, quota ledger |
| Preparation (after collection) | text preparation and associated tests | Normalized sections/chunks and dated sentiment aggregates |
| Orchestrator | shared collection utilities, docs, agent setup, integration | Stable contracts, safe configuration, implementation checks, handoff |

Evaluation is authorized for the data gate. Forecasting, discovery/rules, RAG,
backend AI integration and frontend AI integration require later authorization.

## Shared contracts

- Artifacts live under ignored `data/artifacts/`; baseline Parquet files stay unchanged.
- CLI collectors load exported environment variables and optional `data/.env`.
  Never print secret values, request headers, or credential-bearing URLs.
- Source records use stable `document_id`, `source_type` (`sec` or `news`),
  `provider`, `tickers`, `published_at`, `available_at`, `fetched_at`, `source_url`,
  `title`, `text`, and `content_hash` fields. Dates are UTC ISO 8601 timestamps.
- SEC records additionally retain CIK, accession, form, report period and
  acceptance timestamp. News retains provider ID, updated timestamp, content
  availability and provider sentiment without blending it with local sentiment.
- Collectors export `documents.jsonl` and `coverage.json` in their output directory.
  Raw responses/documents remain private local artifacts. Coverage distinguishes
  collected, no-results, unavailable, failed, and not-applicable outcomes.
- Preparation consumes these exported documents, keeps citations and source
  identity, and does not claim missing source data has been collected.
- Recent text is for current research context. Backfilled/revised text is not
  automatically eligible for historical forecasting.

## Sequence and current status

1. Agent setup and shared contracts: complete; ten reusable roles, three-agent cap.
2. Parallel market, SEC, and news collection: complete for this collection scope;
   658 SEC filings collected across all 80 stock issuers.
3. Preparation using available real artifacts: complete for market and combined
   SEC/news text, including cached SEC text cleanup.
4. Implementation checks: 33 offline tests pass; serialized chunk offsets and
   finite sentiment outputs checked across the refreshed corpus. User handoff is the current stop point.
5. Independent data gate: **completed 2026-10-03; conditional readiness**.
   See [DATA_GATE.md](DATA_GATE.md) for use-specific decisions and required fixes.

SEC identification and Alpaca/Alpha Vantage credentials are configured in ignored
`data/.env`. EDGAR collection succeeded using the supplied `SEC_USER_AGENT`. The credential file was removed from Git staging and stays local.

## Execution handoff (2026-10-02)

- Market candidates: 110,229 rows across 87 eligible assets, 109,359 labels and
  870 unlabeled rows; source prices end 2026-09-18. Price-only output matches the
  committed baseline. Macro candidate adds four fields; historical vintage
  provenance is unverified, with 3,045 missing CPI YoY values and 14 missing RSI
  values. Source artifacts were preserved.
- Alpaca: pilot succeeded, then all 30 requested collection windows completed;
  3,745 matched records, covering all 90 stocks/ETFs.
- Alpha Vantage: 1,035 supplementary records from seven requests. Six daily
  responses hit the result cap and are explicitly partial; the newest partial
  day completed. The local global quota ledger records seven calls.
- Text preparation: 5,168 normalized documents (4,510 news and 658 SEC),
  173,292 chunks, 7,222 article/ticker associations, 4,523 local sentiment
  estimates, and 2,699 ambiguous associations
  left unscored. There are 90 current aggregate rows; 88 have local sentiment
  and two remain unavailable. Twenty-nine scored inputs required token truncation.
- SEC: 658 filings across all 80 stock issuers (151 10-K, 303 10-Q, 181 8-K,
  four 20-F, two Canadian 40-F, and 17 6-K). The other 11 assets are explicitly
  not applicable. Pilot collected 44 filings across five issuers. Hidden XBRL
  metadata was removed through versioned normalization of cached HTML; visible
  facts, source URLs, acceptance times, and original fetch timestamps remain.
- Model weights/tokenizers are pinned and cached locally. A repeat preparation
  run uses the cache, including already computed sentiment. No forecast model,
  vector index, rule changes, or application integration were produced.

These are implementation results, not an independent readiness decision.
Market and current news snapshots have different dates; no historical text join
has been performed. This collection handoff predates the now-completed data gate.

### Stop point

The original collection/preparation stop point was reached. The user subsequently
authorized storage migration and then the independent data gate. Stop after the
gate report; downstream implementation remains a separate phase.

Commands completed include `python3 data/prepare_market_data.py`, the Alpaca
one-day pilot and 30-day run, the seven-day Alpha Vantage supplement,
`prepare_text_data.py --download-models`, cached preparation including SEC, the full SEC collection plus Canadian form
completion, and
`.venv-data/bin/python -m pytest -q data/tests`. Backend database tests and
frontend checks were not run because those modules were unchanged.

## Later roles

Forecasting owns baseline/XGBoost/Transformer experiments. Evaluation owns
independent time-series and evidence checks. Discovery/rules owns deterministic
research stances. RAG owns retrieval and Ollama explanations. Backend and
frontend integration own the corresponding product interfaces. None starts
as part of collection/preparation.

## Shared-data direction: Azure PostgreSQL

The user has authorized migration of existing local market datasets and SEC/news
text into their Azure PostgreSQL instance. MongoDB remains the web application's
database.

The authorized migration adds connection configuration, typed numeric tables,
queryable documents/chunks with complete JSONB payloads, immutable snapshots,
original-file archives, resumable imports and verification. It reads existing
artifacts without downloading providers' data or regenerating preparation outputs.
See `data/SHARED_DATA.md` for commands, storage mapping and verification limits.

PostgreSQL is the shared-data storage implementation. Preserve local originals
and committed baselines until verified migration. A successful local implementation
check does not establish that a remote migration occurred; actual import requires
configured credentials.

This migration does not authorize embeddings, pgvector/BM25 indexes, RAG generation,
forecasting, the independent data-readiness gate, web integration or deployment.

### Migration handoff (2026-10-03)

- Created `stocksense_data` on the supplied Azure PostgreSQL instance and imported
  the local inventory under schema `ss_ef82d22e57e68952a418`.
- All 12 queryable tables (662,926 rows) passed complete row/schema verification;
  all 778 archived files passed decompressed size and SHA-256 checks.
- Prices cover 91 tickers from 2020-09-01 through 2026-09-18. All 173,292 prepared
  chunks reference existing prepared documents. Source metadata and local files
  were preserved; credentials remain in ignored local configuration.
- 59 data tests and 12 subtests pass, including real local PostgreSQL integration
  tests and a regression for Azure's different text collation.
- The migration is complete. Embedding generation and RAG remain the next separate
  phase; no models, vector indexes, product integration or deployment were added.

## Forecast preprocessing sequence (future authorized phase)

After the independent data gate and any required fixes, define chronological
training/validation/test folds with controls for overlapping 10-session labels.
Build the preprocessing pipeline before training forecast models. Within each
fold, fit imputation, categorical handling, scaling and optional PCA only on the
training portion; reuse those fitted transforms for validation/test and inference.
Tune component counts using training/validation only, and retain an original-feature
comparison. Persist preprocessing with the corresponding model and dataset version.

Linear discriminant analysis requires class labels and is not directly applicable
to the current continuous-return target. Consider it only for an explicitly defined
classification experiment. Topic-model LDA is a separate text experiment, not a
required numeric forecasting or RAG preparation step. Neither PCA nor LDA is fitted
as a global preprocessing step before temporal splitting. This sequencing note does
not authorize the data gate, learned preprocessing or forecast training.

## Independent data gate (authorized 2026-10-03)

The orchestrator delegates three independent evaluations with exclusive ownership:

| Evaluation | Owned files | Scope |
| --- | --- | --- |
| Numeric | `data/evaluation/numeric_gate.py`, `docs/ai/NUMERIC_GATE.md` | Prices, labels, predictors, temporal leakage, eligibility and macro provenance |
| Text | `data/evaluation/text_gate.py`, `docs/ai/TEXT_GATE.md` | Source coverage, revision/availability, text/chunk integrity, sentiment and sampled evidence quality |
| Shared storage | `docs/ai/STORAGE_GATE.md` | Local snapshot identity, migration contracts, archives and shared-consumer limitations |
| Orchestrator | `docs/ai/DATA_GATE.md`, this plan | Consolidated evidence, use-specific readiness and required actions |

Machine-readable evidence goes under ignored `data/artifacts/evaluation/`.
Input files, provider caches, prepared datasets and the migrated schema are not
modified. No provider downloads, preprocessing fitting, model jobs or index builds
are included. Remote verification is reported separately from local evidence.

Readiness is assigned by intended use rather than a single blanket approval:
PASS means the audited checks support that use; CONDITIONAL means explicit input
restrictions or implementation contracts remain; BLOCKED means the input cannot
support the stated use until identified defects or missing evidence are resolved.
A report must distinguish exhaustive mechanical checks from sampled semantic
review and identify limitations such as current-universe and adjusted-price bias.

### Gate handoff

The independent gate completed with conditional price-only offline forecasting
and bounded narrative RAG readiness. Historical macro/sentiment training,
complete financial/event explanations, validated company sentiment and live
forecast serving remain blocked for their stated uses. Existing corpus mechanics
and shared snapshot counts passed. Required remediation and implementation
contracts are consolidated in [DATA_GATE.md](DATA_GATE.md); individual numeric,
text and storage reports retain evidence and limitations. The text checker exits
1 for a demonstrated malformed-input crash, not stored-corpus corruption.

The current stop point is after this report. Remediation, new collection,
preprocessing/PCA fitting, forecast training, embedding/index generation, RAG,
rule integration and deployment need subsequent authorization.
