# Independent storage and reproducibility gate

Evaluated 2026-10-03 after explicit user authorization for the data gate. This
review owns storage evidence only; it does not approve numerical forecasting
features, text quality, sentiment accuracy, embeddings or retrieval.

## Verdict

**Local snapshot identity and import-adapter readiness: PASS.** The independently
computed source inventory exactly matches the documented migrated snapshot.
Original inputs can be identified reproducibly and decoded without adapter
conversion failures. This establishes fidelity of local selection and accepted
conversion inputs, not a second full database round-trip comparison.

**Shared snapshot existence/counts: PASS, verified read-only by the orchestrator.**
**Team reproducibility and recovery workflow: CONDITIONAL.** Individual teammate
access, automatic local restoration, and backup recovery remain unverified.
These limitations do not prevent local experiments on the pinned snapshot; they
must be resolved before claiming that any teammate can reproduce those inputs
from the database alone.

## Exact local evidence

Read-only hashing of all selected files produced:

- Snapshot ID: `ef82d22e57e68952a4187ef5668498208fe8748522b043151106631b5bde4451`.
- Schema: `ss_ef82d22e57e68952a418`.
- 778 inventoried files, 2,270,855,097 original bytes.
- 12 queryable tables, 662,926 rows after including the asset-universe CSV.
- Extensions: 5 Parquet, 108 JSON, 6 JSONL, 658 HTML, 1 CSV.

| Table | Independently decoded rows |
| --- | ---: |
| asset_universe | 91 |
| historical_prices | 135,593 |
| macro_indicators | 5,345 |
| sec_documents | 658 |
| news_documents | 4,780 |
| prepared_documents | 5,168 |
| prepared_chunks | 173,292 |
| prepared_sentiment | 7,222 |
| prepared_sentiment_aggregates | 90 |
| price_only_features | 110,229 |
| macro_features | 110,229 |
| forecast_features | 110,229 |

Every row passed through the actual `rows_for` import adapter. All 658 SEC
document source URLs map to exactly one inventoried raw HTML file by the
collector's SHA-256 URL filename convention. The news and SEC source hashes in
the preparation manifest match their current JSONL files. The source inventory
contains both collectors' coverage, market/preparation manifests, SEC response
inventories, and asset profiles. Models and quota ledgers are intentionally local.

There are no saved raw news HTTP response files in this snapshot: the news
source is the standardized JSONL and coverage. The archive preserves those exact
files, not every original provider response field that collection omitted.

## Remote evidence and limits

The orchestrator independently connected with read-only transactions to
`stocksense_data` and confirmed the documented snapshot exists with status
`complete` and `archive_requested=true`. Actual `COUNT(*)` for all 12 tables
matches the local counts above; 778 archive references have total original size
2,270,855,097 bytes, and a prepared-chunk/parent-document join finds zero orphans.

This gate did **not** reread every remote value or decompress/hash every archive
blob. `SHARED_DATA.md` documents that complete row/schema and archive-byte
verification previously succeeded during migration. The independent evidence
here confirms existence, counts and relationships; full current fidelity relies
on that documented migration verification until `postgres-verify` is rerun.
This storage evaluator loaded no credentials and opened no network connection.

## Contracts, failure behavior and limitations

- Identity includes file paths, content hashes, sizes and table schemas/counts;
  local absolute paths are not part of the inventory identity. Any selected
  content change selects a new snapshot schema instead of silently replacing it.
- SQL adapters preserve numeric column names, dates and nulls. JSONB retains
  complete source/prepared payload objects alongside extracted query fields.
  JSON formatting/key order is not preserved by JSONB; original-file archives
  preserve bytes. `_source_row` identifies source order.
- Unsupported Arrow types, submicrosecond timestamps, overflowing integers,
  malformed JSON, missing timestamp timezone and PostgreSQL-incompatible NUL
  text are rejected instead of silently coerced. All current selected rows
  satisfy the adapter constraints.
- Imports take an advisory lock, commit each table/archive separately, detect
  changing sources, and track completed work for resume. Verification compares
  actual rows/schema and archives against the same inventory. A tables-only
  import is reported distinctly. Archives preserve paths and SHA-256 identity.
- Snapshot schemas are immutable by importer convention; PostgreSQL does not
  prohibit a privileged user from updating tables. Consumer roles should have
  SELECT privileges only, with schema/snapshot ID pinned in experiment metadata.
- The CLI provides inventory, import and verify, **no export/restore command**.
  Current preparation/feature scripts still read local files rather than shared
  SQL tables. A teammate can query tables manually, but an end-to-end download
  of an exact snapshot into the existing pipeline is not implemented.
- `asset_profiles.json`, coverage and manifests are archived but do not have
  dedicated query tables. Retrieval of them requires archive decoding.
- Preparation manifests retain original machine-specific absolute paths. After
  restoration those paths need relocation; source hashes remain usable.
- A read-only inventory scan cannot certify consistency against concurrent
  source edits. Collection/preparation must be stopped while freezing inputs;
  the importer subsequently rechecks each source file.
- **Audit-output identity hazard:** the production inventory recursively includes
  JSON/JSONL under `data/artifacts/`. New `artifacts/evaluation/` gate reports
  therefore change the snapshot ID despite all 778 original files being
  unchanged. The gate script excludes that subtree when checking the source
  snapshot. Do not interpret an ordinary post-audit inventory mismatch as data
  corruption. A later fix should explicitly exclude evaluation artifacts or
  select a frozen manifest; the importer was not changed during this gate.
- Storage identity proves that experiments consume the same files; it does not
  establish historical availability, complete provider coverage, absence of
  leakage, fair temporal comparisons or correctness of source claims. Those
  are the independent numeric/text gates' responsibilities.

## Required next actions

1. Fix the audit-output inventory boundary before the next import/verify cycle;
   keep the current schema pinned until any new snapshot is explicitly selected.
2. Establish individual read-only team access to the snapshot and confirm it
   from another machine, without sharing administrator credentials.
3. Add an archive export/restore workflow with safe paths, hash verification and
   snapshot selection, or implement approved SQL dataset consumers that preserve
   source schemas and record the snapshot ID. Confirm restored hashes against
   this snapshot before replacing local inputs.
4. Demonstrate backup/restore on a separate target before relying exclusively
   on the hosted database. Keep local originals and committed baselines.
5. Correct stale architecture guidance: the root README, filesystem AGENTS and
   backend implementation use asyncpg/PostgreSQL for application persistence.
   Their shared-data sections, `data/README.md`, `data/SHARED_DATA.md` and
   `docs/ai/PLAN.md` still say MongoDB serves the application. This inconsistency
   also exists in the newly supplied AGENTS instructions. No app changes were
   made by this gate.

## Reproduction and checks

From the repository root, using the existing data virtual environment:

```bash
.venv-data/bin/python -m data.evaluation.storage_gate
.venv-data/bin/python -m pytest -q data/tests/test_shared_data.py data/tests/test_postgres_records.py data/tests/test_postgres_cli.py
```

The first command hashes local files, compares source references and runs all
rows through import adapters; it writes no files and makes no network request.
Optional migration dependencies must already be installed. The second uses
temporary fixtures and mocked connections: **16 tests and 12 subtests passed**,
covering exclusion of secrets/caches/symlinks, conflicting copies, preservation
of source payloads, rejected lossy values and sanitized CLI failure paths.
No backend database suite, live-database test fixture, provider download,
embedding job, model training or retrieval index was run by this evaluator.
