# Independent text data gate — 2026-10-03

The user authorized this independent gate. This report evaluates existing local
artifacts without recollecting, regenerating, fitting models, or creating indexes.
It is independent of the collectors' implementation reports. Evaluation outputs
under `data/artifacts/evaluation/` are excluded from training and migration input
contracts; they must not be interpreted as a new shared-data snapshot.

## Decision by intended use

| Intended use | Decision | Evidence and boundary |
| --- | --- | --- |
| Existing corpus identity, provenance, chunk parent/offset integrity | Pass on checked snapshot | All 5,168 documents and 173,292 chunks satisfy the checked source hashes, references, metadata and offsets; no stored-corpus integrity violations |
| Bounded current RAG experiments | Conditional | Primary-report narrative is usable as dated evidence, but substantive event/foreign exhibits are missing; retrieval must expose coverage and abstain when evidence is absent |
| Complete SEC financial/event explanations across the universe | Blocked | Primary-document-only collection misses earnings releases and incorporated financial statements; issuer coverage is not evidence-content completeness |
| Company sentiment as a validated forecasting or rule input | Blocked | Concrete attribution failures found; no labeled accuracy benchmark |
| Historical sentiment features for 2021–2026 forecasting | Blocked | All news versions were collected October 2, 2026; publication dates cannot establish historical availability |
| Preparation failure handling | Needs fix | Null `available_at` causes uncaught `AttributeError`; actual existing corpus has no such record |

## Reproduce and preserve evidence

```bash
.venv-data/bin/python data/evaluation/text_gate.py
```

The command writes ignored `data/artifacts/evaluation/text_gate.json`, containing
source file SHA-256 identities, counts, bounded raw-file samples, attribution
traces, failure probes and limitations. It exits **1** for the demonstrated null
input failure, while still saving the complete evidence. Exit 0 would only mean
these implemented integrity/probe checks pass; it would not approve semantic
accuracy, full corpus coverage, retrieval or generation quality.

The source snapshot preparation cutoff is `2026-10-02T08:59:39.194152Z`.
Local scope: 658 SEC primary documents, 3,745 Alpaca source records and 1,035
Alpha Vantage source records. Normalization/revision selection yields 4,510 news
plus 658 SEC prepared documents. Remote storage verification is owned by the
separate storage gate.

## What was checked

- Source IDs, hashes, nonempty universe ticker membership, publication ≤ availability
  ≤ fetch ≤ cutoff and revision availability. Prepared references, merged ticker
  sets and conservative maximum-source availability match originals.
- Unique prepared IDs and canonical URLs, exact text hashes, all chunk IDs,
  parents, text offsets, inherited ticker/date/citation metadata and declared
  1–220 token counts. Every prepared document has a chunk.
- Independently retokenized every 2,000th saved chunk: **87 chunks**, maximum
  **220 tokens**, zero over-bound counts or differences from stored counts. This
  sample uses cached `tokenizers` directly and loads no embedding/sentiment model.
- All 7,222 sentiment associations retain their prepared-document metadata.
  4,523 estimates have finite bounded scores, valid probability sums and expected
  positive-minus-negative values; their reconstructed attribution-input hashes
  match. 2,699 unavailable associations retain null scores. Twenty-nine scored
  inputs are explicitly truncated. All 90 local seven-day aggregates were
  independently recalculated from publication-time decay and available inputs.
- SEC CIK metadata agrees with saved per-ticker coverage. This is an internal
  cross-check, not a fresh authoritative issuer-map verification.
- Unknown-ticker and future-availability synthetic records are rejected. A null
  availability timestamp instead crashes the production normalizer. The gate
  catches and records that failure without modifying the pipeline.

## Evidence-content findings

Twelve deterministic raw HTML samples cover the first/last saved identity of each
form: 10-K, 10-Q, 8-K, 20-F, 40-F and 6-K. All sampled visible inline-XBRL fact
fragments occur in normalized text; no sampled hidden-only fragment longer than
80 characters occurs. Short hidden fragments can coincide with legitimate visible
facts, so absence of all hidden strings is not asserted. These substring checks
support extraction preservation; they do **not** validate table header-to-value
relationships, units, periods or numerical interpretation.

Manual inspection of the same samples found retained business narratives in the
long annual/quarterly reports and lost context when tables are flattened. For
financial numbers, later retrieval must retain table/period/unit structure or
link to the source rather than infer meaning from adjacent tokens.

The material collection gap is **linked exhibits**:

- UNP `0000100885-26-000249` and TMO `0000097745-26-000138` 8-K primary documents
  point to earnings-release Exhibit 99.1, which is not a collected document.
- CCJ `0001193125-26-295796` 6-K contains only 972 normalized characters and
  references a July 2 press release in Exhibit 99.1. Seven of seventeen 6-K
  primary documents are shorter than 2,000 characters; length is a warning
  signal, not by itself proof of absent financial evidence.
- The two CCJ 40-F primaries are about 21,850 characters and incorporate annual
  information/financial materials through exhibits; collecting the 40-F cover
  is not equivalent to collecting its full annual financial evidence.

Collector inspection confirms it fetches the selected primary document only;
prepared records have no exhibit ingestion relation. Before claiming complete
financial/event coverage, ingest relevant financial/earnings/MD&A exhibits with
parent-accession links, provenance, acceptance and content-availability dates,
format-specific extraction and explicit failed/missing statuses. Exclude cover-only
passages from substantive-answer evidence until linked materials are available.

## Duplication and retrieval noise

There are **6 excess exact duplicate documents** under different retained
identities and **5,369 excess exact duplicate chunks** (3.10% of saved chunks).
This is exact text duplication only; near duplication across reporting periods
was not measured. Retain original provenance, but collapse identical evidence
within a retrieval response so repeated passages do not create apparent consensus.

Marker counts: 25,230 chunks mention a table of contents, 2,263 mention the SEC
cover heading, and 791 contain the signatures boilerplate phrase. These markers
are overlapping flags, not proven boilerplate-only chunk counts. 20,044 chunks
fall under generic `Document` section labels. Later retrieval evaluation should
measure noise and introduce section/boilerplate handling where it improves
answer evidence; indiscriminate removal could delete relevant content.

## Sentiment suitability and limitations

Source availability is conservatively October 2, 2026 even when news publication
begins September 2. This correctly prevents backfilled text from being treated as
historically known. No price-window historical join is approved. Alpha Vantage
has six explicitly partial windows; provider ticker tags do not establish sentiment
subject identity or corpus completeness.

A seed-17 sample of twelve scored attribution traces plus two targeted examples
found material subject errors. In Alpha Vantage document
`d827b2c86109b224557c92be59aec66c9cb736c524ddb2cc3fe76b52beb1065e:4a65c80e1bb6`,
MS sentiment is assigned from discussion of Morgan Stanley upgrading Telecom
Argentina. The broker is mentioned, but the stock under assessment is TEO.
For Alpaca `61611969:69242336d72e`, NOW attribution includes DELL's price move
followed by ServiceNow's company name because abbreviation/sentence boundaries
split the original list incorrectly. The heuristic excludes other *tagged*
companies only, so untagged-company mentions can survive too.

Fix subject-versus-analyst attribution and financial abbreviation/list sentence
segmentation. Establish a labeled, ticker-stratified benchmark covering short
headlines, full news, summaries, multi-company lists, analysts and ETFs. Calibrate
failure/abstention rules before sentiment drives stances or forecasting. The small
sample supports concrete defects, **not** a corpus-wide error-rate estimate.
Finite scores and matching input hashes do not validate semantic correctness.

Keep source/provider sentiment separate from local estimates. Unscored means
unavailable, not neutral. Current exploratory aggregates can be displayed only
with their sampling/coverage qualifications and original timestamps. Retrieval
and generated-citation faithfulness remain unevaluated because no retrieval or
generation system exists yet.
