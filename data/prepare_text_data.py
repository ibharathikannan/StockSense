#!/usr/bin/env python3
"""Prepare collected evidence and current sentiment; no retrieval or training."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
from importlib.metadata import version
import math
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

if __package__:
    from .collection_common import atomic_write_json, read_jsonl, stable_hash, utc_now, write_jsonl
    from .collect_sec_filings import normalize_filing
else:
    from collection_common import atomic_write_json, read_jsonl, stable_hash, utc_now, write_jsonl
    from collect_sec_filings import normalize_filing


DATA_DIR = Path(__file__).resolve().parent
FINBERT = "ProsusAI/finbert"
FINBERT_REVISION = "4556d13015211d73dccd3fdd39d39232506f3e43"
TOKENIZER = "sentence-transformers/all-MiniLM-L6-v2"
TOKENIZER_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
CHUNK_TOKENS = 220
OVERLAP_TOKENS = 32


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Evidence timestamps must include a timezone")
    return result.astimezone(timezone.utc)


def canonical_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Evidence requires an HTTP(S) source URL")
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def normalize_documents(records: list[dict], universe: dict[str, dict], as_of: datetime) -> tuple[list[dict], list[dict]]:
    """Select the newest known revision per source article, then dedupe syndication URLs."""
    latest: dict[tuple, dict] = {}
    rejected: list[dict] = []
    for source in records:
        identity = source.get("document_id", "unknown")
        try:
            published = timestamp(source["published_at"])
            available = timestamp(source["available_at"])
            fetched = timestamp(source["fetched_at"])
            if available < published or fetched < available:
                raise ValueError("Inconsistent evidence timestamps")
            if available > as_of:
                rejected.append({"document_id": identity, "reason": "not_available_at_cutoff"})
                continue
            tickers = sorted(set(source["tickers"]) & universe.keys())
            if not tickers:
                raise ValueError("No universe ticker association")
            url = canonical_url(source["source_url"])
            # SEC collector already exports normalized text. Parse HTML news only.
            body = source.get("text") or ""
            if source["source_type"] == "news":
                body = normalize_filing(body)
                body = "\n".join(filter(None, [source.get("title", "").strip(), body.strip()]))
            body = "\n".join(" ".join(line.split()) for line in body.splitlines() if line.strip())
            if not body:
                raise ValueError("Empty evidence text")
            doc = {**source, "tickers": tickers, "text": body, "canonical_url": url,
                   "source_content_hash": source.get("content_hash"), "content_hash": stable_hash(body),
                   "source_document_ids": [identity]}
            revision_key = (source["provider"], source.get("provider_id") or identity)
            old = latest.get(revision_key)
            revision_time = timestamp(source.get("updated_at") or source["available_at"])
            if revision_time > as_of:
                rejected.append({"document_id": identity, "reason": "revision_after_cutoff"})
                continue
            if old is None or revision_time > timestamp(old.get("updated_at") or old["available_at"]):
                latest[revision_key] = doc
        except (KeyError, TypeError, ValueError):
            rejected.append({"document_id": identity, "reason": "invalid_source_record"})
    deduped: dict[tuple, dict] = {}
    for doc in latest.values():
        # Keep different SEC filings; cross-provider news copies share a URL.
        key = (doc["source_type"], doc["canonical_url"])
        previous = deduped.get(key)
        if previous is None:
            deduped[key] = doc
            continue
        chosen = max([previous, doc], key=lambda r: (bool(r.get("content_available")), len(r["text"])))
        merged = {**chosen, "tickers": sorted(set(previous["tickers"]) | set(doc["tickers"])),
                  "source_document_ids": sorted(set(previous["source_document_ids"]) | set(doc["source_document_ids"])),
                  "provider_sentiment": {**(previous.get("provider_sentiment") or {}), **(doc.get("provider_sentiment") or {})}}
        # Merged evidence is available only after every included source was known.
        merged["available_at"] = max(previous["available_at"], doc["available_at"], key=timestamp)
        merged["fetched_at"] = max(previous["fetched_at"], doc["fetched_at"], key=timestamp)
        deduped[key] = merged
    return sorted(deduped.values(), key=lambda r: r["document_id"]), rejected


def sections(text: str) -> list[tuple[str, int, int]]:
    matches = list(re.finditer(r"(?im)^(?:part\s+[ivx]+[. \t]*)?item\s+\d+[a-z]?[. :\t-]*[^\n]{0,120}$", text))
    boundaries = [(0, "Document")]
    for match in matches:
        if match.start() > boundaries[-1][0]:
            boundaries.append((match.start(), match.group(0).strip()))
    return [(name, start, boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text))
            for i, (start, name) in enumerate(boundaries)]


def chunk_documents(documents: list[dict], tokenizer) -> list[dict]:
    chunks = []
    for doc in documents:
        for section, section_start, section_end in sections(doc["text"]):
            part = doc["text"][section_start:section_end]
            offsets = tokenizer(part, add_special_tokens=False, truncation=False,
                                return_offsets_mapping=True, verbose=False)["offset_mapping"]
            for start in range(0, len(offsets), CHUNK_TOKENS - OVERLAP_TOKENS):
                stop = min(start + CHUNK_TOKENS, len(offsets))
                left = section_start + offsets[start][0]
                right = section_start + offsets[stop - 1][1]
                chunks.append({
                    "chunk_id": stable_hash(f"{doc['document_id']}:{doc['content_hash']}:{left}:{right}"),
                    "document_id": doc["document_id"], "source_document_ids": doc["source_document_ids"],
                    "tickers": doc["tickers"], "source_type": doc["source_type"],
                    "source_url": doc["source_url"], "published_at": doc["published_at"],
                    "available_at": doc["available_at"], "section": section,
                    "start_char": left, "end_char": right, "token_count": stop - start,
                    "text": doc["text"][left:right],
                })
                if stop == len(offsets):
                    break
    return chunks


def company_pattern(ticker: str, name: str) -> re.Pattern:
    short = re.sub(r"(?i)^the\s+", "", name)
    short = re.sub(r"(?i)[,\s]+(?:incorporated|inc\.?|corporation|corp\.?|company|co\.?|plc|ltd\.?)(?:[,\s].*)?$", "", short).strip()
    names = [name, short] if len(short) >= 4 else [name]
    company = "|".join(re.escape(n) for n in set(names) if len(n) >= 4)
    ticker_text = re.escape(ticker)
    # Short symbols such as A and ON are common words; require explicit notation.
    symbol = rf"(?:\${ticker_text}\b|\({ticker_text}\)|(?:NASDAQ|NYSE):\s*{ticker_text}\b)"
    if len(ticker) >= 3:
        symbol += rf"|(?<![A-Za-z0-9]){ticker_text}(?![A-Za-z0-9])"
    company_expression = rf"(?i:\b(?:{company})\b)|" if company else ""
    return re.compile(company_expression + rf"(?:{symbol})")


def sentiment_inputs(documents: list[dict], universe: dict[str, dict]) -> list[dict]:
    patterns = {t: company_pattern(t, row["name"]) for t, row in universe.items()}
    inputs = []
    for doc in documents:
        if doc["source_type"] != "news":
            continue
        sentences = re.split(r"(?<=[.!?])\s+|\n+", doc["text"])
        for ticker in doc["tickers"]:
            attributed = [sentence for sentence in sentences if patterns[ticker].search(sentence)
                          and not any(patterns[other].search(sentence) for other in doc["tickers"] if other != ticker)]
            text = " ".join(attributed)
            inputs.append({"document_id": doc["document_id"], "ticker": ticker,
                           "published_at": doc["published_at"], "available_at": doc["available_at"],
                           "source_url": doc["source_url"], "text": text,
                           "status": "pending" if text else "unavailable_ambiguous_attribution"})
    return inputs


def score_finbert(inputs: list[dict], cache_dir: Path, output_dir: Path, download: bool) -> list[dict]:
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    cache_path = output_dir / "sentiment_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    tokenizer = AutoTokenizer.from_pretrained(FINBERT, revision=FINBERT_REVISION,
                                              cache_dir=cache_dir, local_files_only=not download, trust_remote_code=False)
    missing: dict[str, str] = {}
    for row in inputs:
        if row["status"] == "pending":
            key = stable_hash(FINBERT_REVISION + row["text"])
            if key not in cache:
                missing[key] = row["text"]
    if missing:
        torch.set_num_threads(4)
        model = AutoModelForSequenceClassification.from_pretrained(
            FINBERT, revision=FINBERT_REVISION, cache_dir=cache_dir,
            local_files_only=not download, trust_remote_code=False,
        )
        device = "mps" if torch.backends.mps.is_available() else "cpu"
        model.to(device).eval()
        labels = {i: name.lower() for i, name in model.config.id2label.items()}
        if set(labels.values()) != {"positive", "negative", "neutral"}:
            raise ValueError("Unexpected sentiment model labels")
        entries = list(missing.items())
        for offset in range(0, len(entries), 16):
            batch = entries[offset:offset + 16]
            texts = [text for _, text in batch]
            lengths = [len(ids) for ids in tokenizer(texts, truncation=False, verbose=False)["input_ids"]]
            encoded = tokenizer(texts, return_tensors="pt", padding=True, truncation=True, max_length=512).to(device)
            with torch.inference_mode():
                probabilities = model(**encoded).logits.softmax(dim=-1).cpu().tolist()
            for (key, _), values, length in zip(batch, probabilities, lengths):
                scores = {labels[i]: float(value) for i, value in enumerate(values)}
                cache[key] = {"score": scores["positive"] - scores["negative"], "probabilities": scores,
                              "input_truncated": length > 512, "input_tokens": length}
            atomic_write_json(cache_path, cache)
            if offset % 256 == 0:
                print(f"Sentiment inputs scored: {min(offset + 16, len(entries))}/{len(entries)}", flush=True)
    results = []
    for row in inputs:
        result = {k: v for k, v in row.items() if k != "text"}
        if row["status"] == "pending":
            result.update(cache[stable_hash(FINBERT_REVISION + row["text"])])
            result.update(status="scored", model=FINBERT, model_revision=FINBERT_REVISION,
                          input_hash=stable_hash(row["text"]))
        results.append(result)
    return results


def aggregate_sentiment(documents: list[dict], scored: list[dict], universe: dict[str, dict], as_of: datetime) -> list[dict]:
    lookup = {(row["document_id"], row["ticker"]): row for row in scored}
    result = []
    for ticker in sorted(universe):
        recent = [doc for doc in documents if doc["source_type"] == "news" and ticker in doc["tickers"]
                  and as_of - timedelta(days=7) <= timestamp(doc["published_at"]) <= as_of
                  and timestamp(doc["available_at"]) <= as_of]
        local, provider = [], []
        for doc in recent:
            age_days = (as_of - timestamp(doc["published_at"])).total_seconds() / 86400
            weight = math.exp(-math.log(2) * age_days / 2)
            score = lookup.get((doc["document_id"], ticker), {})
            if score.get("status") == "scored":
                local.append((score["score"], weight))
            av = (doc.get("provider_sentiment") or {}).get(ticker, {}).get("score")
            try:
                if av is not None and math.isfinite(float(av)) and -1 <= float(av) <= 1:
                    provider.append((float(av), weight))
            except (TypeError, ValueError):
                pass
        mean = lambda rows: sum(value * weight for value, weight in rows) / sum(weight for _, weight in rows) if rows else None
        result.append({"ticker": ticker, "as_of": as_of.isoformat().replace("+00:00", "Z"),
                       "articles_7d": len(recent), "local_scored_articles_7d": len(local),
                       "local_sentiment_7d": mean(local), "alpha_vantage_sentiment_7d": mean(provider),
                       "sentiment_status": "available" if local else "unavailable",
                       "latest_publication": max((doc["published_at"] for doc in recent), default=None),
                       "lookback_days": 7, "decay_half_life_days": 2,
                       "historical_training_eligible": False})
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--news-dir", type=Path, default=DATA_DIR / "artifacts" / "news")
    parser.add_argument("--sec-dir", type=Path, default=DATA_DIR / "artifacts" / "sec")
    parser.add_argument("--output-dir", type=Path, default=DATA_DIR / "artifacts" / "prepared")
    parser.add_argument("--as-of", default=None, help="Timezone-aware evidence availability cutoff")
    parser.add_argument("--download-models", action="store_true", help="Allow required public pretrained weights/tokenizers to download")
    parser.add_argument("--sentiment", choices=["finbert", "none"], default="finbert")
    args = parser.parse_args()
    as_of = timestamp(args.as_of or utc_now())
    with (DATA_DIR / "asset_universe.csv").open() as stream:
        universe = {r["ticker"]: r for r in csv.DictReader(stream) if r["asset_type"] != "index"}
    records, source_status = [], {}
    for name, directory in [("news", args.news_dir), ("sec", args.sec_dir)]:
        path = directory / "documents.jsonl"
        incoming = read_jsonl(path)
        records.extend(incoming)
        coverage = directory / "coverage.json"
        source_status[name] = {"path": str(path), "records": len(incoming),
                               "status": "present" if incoming else "unavailable",
                               "sha256": stable_hash(path.read_text()) if path.exists() else None,
                               "coverage": json.loads(coverage.read_text()) if coverage.exists() else None}
    documents, rejected = normalize_documents(records, universe, as_of)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = DATA_DIR / ".cache" / "huggingface"
    chunks, scored = [], []
    if documents:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(TOKENIZER, revision=TOKENIZER_REVISION, cache_dir=cache_dir,
                                                  local_files_only=not args.download_models, trust_remote_code=False)
        chunks = chunk_documents(documents, tokenizer)
        inputs = sentiment_inputs(documents, universe)
        if args.sentiment == "finbert" and any(row["status"] == "pending" for row in inputs):
            scored = score_finbert(inputs, cache_dir, args.output_dir, args.download_models)
        else:
            scored = [{**{k: v for k, v in row.items() if k != "text"},
                       "status": "not_run" if row["status"] == "pending" else row["status"]} for row in inputs]
    for filename, values in [("documents.jsonl", documents), ("chunks.jsonl", chunks), ("sentiment.jsonl", scored),
                              ("sentiment_aggregates.jsonl", aggregate_sentiment(documents, scored, universe, as_of))]:
        write_jsonl(args.output_dir / filename, values)
    manifest = {
        "purpose": "Preparation only; independent data gate not run", "as_of": as_of.isoformat(),
        "sources": source_status, "documents": len(documents), "chunks": len(chunks),
        "rejected": rejected, "sentiment_inputs": len(scored), "sentiment_scored": sum(r["status"] == "scored" for r in scored),
        "tokenizer": TOKENIZER, "tokenizer_revision": TOKENIZER_REVISION,
        "chunk_tokens": CHUNK_TOKENS, "overlap_tokens": OVERLAP_TOKENS,
        "sentiment_mode": args.sentiment, "sentiment_model": FINBERT, "sentiment_revision": FINBERT_REVISION,
        "packages": {name: version(name) for name in ["transformers", "torch", "numpy"]} if documents else {},
        "citation_offsets": "Character offsets into prepared documents.jsonl normalized text",
        "notes": ["No embeddings, retrieval index, forecast model, or rule changes were produced.",
                  "Sentiment is a pretrained model estimate, not independently validated financial ground truth.",
                  "Current source snapshots must not be backfilled into historical training rows."]}
    atomic_write_json(args.output_dir / "manifest.json", manifest)
    print(f"Prepared {len(documents)} documents, {len(chunks)} chunks, {manifest['sentiment_scored']} sentiment inputs.")


if __name__ == "__main__":
    main()
