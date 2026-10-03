# Shared data: Azure PostgreSQL

## Verified migration (2026-10-03)

The current `data/` inventory was imported into Azure server
`stocksensedb.postgres.database.azure.com`, database `stocksense_data`, schema
`ss_ef82d22e57e68952a418`. All 12 queryable tables (662,926 total rows) passed
full row and schema verification against the local sources. All 778 inventoried
files (2,270,855,097 original bytes) were archived and their decompressed hashes
verified. Local originals and committed baselines remain intact.

To query this snapshot with short table names, set the search path in your SQL
session after connecting to `stocksense_data`:

```sql
SET search_path TO ss_ef82d22e57e68952a418;
SELECT "Date", ticker, "Close"
FROM historical_prices
WHERE ticker = 'AAPL'
ORDER BY "Date" DESC
LIMIT 10;
```

The migration driver, configuration and verification commands passed 59 offline
tests plus 12 subtests, including integration tests on a disposable local
PostgreSQL instance. Azure verification also confirmed all chunks have matching
prepared parent documents. Embeddings have not been generated.

## Storage mapping

Upload existing local data directly to PostgreSQL; Git is not part of the upload.
The migration reads local artifacts without redownloading data or rebuilding
features or text. MongoDB continues to serve the web application.

| Local source | PostgreSQL representation | Purpose |
| --- | --- | --- |
| Historical-price and macro Parquet | Typed columns preserving original names | Numeric SQL queries |
| Baseline and candidate feature Parquet | Separate typed tables | Future modeling inputs |
| `asset_universe.csv` | Asset universe table | Ticker metadata and eligibility |
| SEC/news JSONL | Query columns plus complete JSONB payload | Source text, revisions and provenance |
| Prepared documents and chunks | Query columns plus complete JSONB payload | Readable text and cited passages for future RAG |
| Sentiment records and aggregates | Query columns plus complete JSONB payload | Dated estimates; missing values remain missing |
| Original inventoried files | Gzipped BYTEA archive with hashes and paths | Preserve sources for restoration and reprocessing |

Parquet is the canonical numeric import source. Its values become database rows;
PostgreSQL does not need a CSV copy. Redundant CSV convenience copies are excluded.
The asset universe CSV is a distinct source and is imported. Archives include
inventoried HTML, raw responses, Parquet/JSONL, coverage, manifests and asset profiles.
Secrets, model caches and quota ledgers stay local.

Archiving HTML preserves the file, but does not turn HTML bytes into semantic
search. Prepared document and chunk tables provide queryable text. Embedding
model selection, embedding generation, pgvector enablement/indexes, retrieval and
RAG generation are separate work and are not performed by the migration.

## Local setup

From the repository root with the data virtual environment active:

```bash
python3 -m pip install -r data/requirements.txt
python3 -m pip install -r data/requirements-postgres.txt
```

The PostgreSQL driver is optional and separate from collection dependencies.
`data/requirements-storage.txt` and the legacy local LanceDB helpers remain
available, but are not used by the PostgreSQL commands.

Your existing Azure connection uses `sslmode=require`, which is supported for
this migration and does not need a certificate bundle configured by the importer.
Create a dedicated database once using the connection that already works:

```bash
psql "host=stocksensedb.postgres.database.azure.com port=5432 dbname=postgres user=postgres sslmode=require" -W
```

At the `psql` prompt:

```sql
CREATE DATABASE stocksense_data;
```

This is a manual setup step; the importer does not create databases or configure
Azure resources. If the database already exists, use it without recreating it.

Set local libpq variables, either in your shell or in ignored `data/.env`:

```dotenv
PGHOST=stocksensedb.postgres.database.azure.com
PGPORT=5432
PGDATABASE=stocksense_data
PGUSER=postgres
PGSSLMODE=require
PGCONNECT_TIMEOUT=15
```

The commands use the collectors' environment-loading helper. Exported variables
take precedence over values loaded from the optional env file. Use
`--env-file <path>` to select another file. Supply the password through an
interactive `--prompt-password`, local `PGPASSWORD`, or libpq's `.pgpass`; keep
credentials out of source control and command output.

## Inventory, import and verify

Inventory does not connect to PostgreSQL or modify files:

```bash
python3 -m data.shared_data inventory --source-root data
```

When additional raw inputs live in another checkout, pass
`--extra-raw-root <directory>` to inventory, import and verification consistently.
Identical paths are deduplicated only if their contents match; conflicting files
are rejected.

Import the selected inventory, including original-file archives:

```bash
python3 -m data.shared_data postgres-import --source-root data --env-file data/.env --prompt-password
```

Import can resume the same snapshot after interruption. Completed tables and
archive files are tracked separately. Different inventory contents produce a new
snapshot; existing snapshots are not replaced.

For an intentional tables-only upload, add `--skip-archive` to the import command.
The resulting status is reported as tables-only; it does not establish that the
original source files are backed up. Otherwise archives are uploaded by default,
with file contents deduplicated by SHA-256 and original paths retained. Preserve
local originals in either case.

Verify against the same source inventory:

```bash
python3 -m data.shared_data postgres-verify --source-root data --env-file data/.env --prompt-password
```

Verification checks actual database rows and schemas against the local originals,
and checks archived content hashes when archives are included. It reports archive
coverage for tables-only imports. Use unchanged local sources to verify a given
snapshot: editing the selected files changes the inventory identity.

## Querying snapshots

Each immutable dataset snapshot uses a schema named `ss_` followed by the first
20 characters of its manifest hash. Import output identifies the selected schema.
Migration metadata resides under `stocksense_storage`. There is no mutable
latest-data alias: use the schema returned for the snapshot you intend to query.

Numeric columns retain their original Parquet names, including capital letters
and spaces. Quote those names in SQL. For example, replace the schema placeholder
below with the returned snapshot schema:

```sql
SELECT "Date", ticker, "Close", "Volume"
FROM ss_<snapshot_hash_prefix>.historical_prices
WHERE ticker = 'AAPL'
ORDER BY "Date" DESC
LIMIT 10;
```

Text chunks can be selected by ticker for a later embedding job:

```sql
SELECT chunk_id, document_id, section, text, source_url,
       payload->>'start_char' AS start_char,
       payload->>'end_char' AS end_char
FROM ss_<snapshot_hash_prefix>.prepared_chunks
WHERE tickers @> ARRAY['AAPL']
ORDER BY _source_row
LIMIT 10;
```

Tables include `_source_row` metadata for source-row identity. Document tables
retain the full JSONB payload alongside extracted query columns; revisions,
timestamps, collection outcomes, citations and chunk offsets remain available.
Ticker/date and document-ID indexes support common SQL lookups. These are SQL
indexes, not embedding retrieval indexes.

## Completion and limits

Local tests and fixtures can check the importer without cloud credentials. A
successful local check does not mean data has been uploaded to Azure. Remote
import and verification require configured credentials and reachable PostgreSQL.

Retain local files and committed baselines until remote verification succeeds.
Before depending exclusively on the database, separately confirm backups and
restoration and access from the machines that will consume the data. No web
application integration, forecasting, embedding job or cloud deployment is
performed by these commands.
