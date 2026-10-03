"""Independent, read-only corpus checks. No model loading or provider requests."""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import csv
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re
import random
import sys


def rows(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def date(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('naive timestamp')
    return parsed


class RawSample(HTMLParser):
    """Inspect source facts and exhibit links without reusing production normalization."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.facts = []
        self.links = []
        self.fact_depth = 0
        self.hidden_depth = 0
        self.hidden = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('ix:nonfraction', 'ix:nonnumeric'):
            self.fact_depth += 1
        if tag == 'ix:hidden':
            self.hidden_depth += 1
        if tag == 'a' and attrs.get('href'):
            link = attrs['href']
            if re.search(r'(?:ex(?:hibit)?[\-_]?\d|ex99|d\d+dex)', link, re.I):
                self.links.append(link)
    def handle_endtag(self, tag):
        if tag in ('ix:nonfraction', 'ix:nonnumeric'):
            self.fact_depth = max(0, self.fact_depth - 1)
        if tag == 'ix:hidden':
            self.hidden_depth = max(0, self.hidden_depth - 1)
    def handle_data(self, text):
        text = ' '.join(text.split())
        if self.hidden_depth and text:
            self.hidden.append(text)
        elif self.fact_depth and text:
            self.facts.append(text)


def evaluate(root):
    universe = {r['ticker']: r for r in csv.DictReader((root/'asset_universe.csv').open())}
    base = root/'artifacts'
    manifest = json.loads((base/'prepared/manifest.json').read_text())
    cutoff = date(manifest['as_of'])
    sources = {}
    problems = Counter()
    examples = defaultdict(list)
    def fail(kind, identity):
        problems[kind] += 1
        if len(examples[kind]) < 5:
            examples[kind].append(identity)
    source_counts = Counter()
    publication_ranges = defaultdict(list)
    for group in ('sec', 'news'):
        for row in rows(base/group/'documents.jsonl'):
            identity = row['document_id']
            if identity in sources:
                fail('duplicate_source_id', identity)
            sources[identity] = row
            source_counts[row['provider']] += 1
            publication_ranges[group].append(row['published_at'])
            try:
                published, available, fetched = (date(row[k]) for k in ('published_at','available_at','fetched_at'))
                if not published <= available <= fetched <= cutoff:
                    fail('source_timestamp_order', identity)
                if row.get('updated_at') and date(row['updated_at']) > available:
                    fail('revision_not_yet_available', identity)
            except (ValueError,KeyError,TypeError):
                fail('source_timestamp_invalid', identity)
            if digest(row['text']) != row['content_hash']:
                fail('source_content_hash', identity)
            if not row['tickers'] or set(row['tickers']) - universe.keys():
                fail('source_tickers', identity)
    docs = {}
    url_keys = set()
    text_hashes = Counter()
    prepared_counts = Counter()
    for doc in rows(base/'prepared/documents.jsonl'):
        identity = doc['document_id']
        if identity in docs:
            fail('duplicate_prepared_id', identity)
        docs[identity] = doc
        prepared_counts[doc['source_type']] += 1
        text_hashes[digest(doc['text'])] += 1
        key = (doc['source_type'], doc['canonical_url'])
        if key in url_keys:
            fail('duplicate_canonical_url', identity)
        url_keys.add(key)
        refs = doc['source_document_ids']
        if any(ref not in sources for ref in refs):
            fail('unknown_source_reference', identity)
        else:
            if date(doc['available_at']) != max(date(sources[ref]['available_at']) for ref in refs):
                fail('merged_availability', identity)
            expected_tickers = set().union(*(set(sources[ref]['tickers']) for ref in refs))
            if set(doc['tickers']) != expected_tickers:
                fail('merged_tickers', identity)
            if doc['source_content_hash'] != sources[identity]['content_hash']:
                fail('prepared_source_hash', identity)
        if digest(doc['text']) != doc['content_hash']:
            fail('prepared_content_hash', identity)
    chunk_ids = set()
    chunk_counts = Counter()
    exact_chunks = Counter()
    sections = Counter()
    boilerplate = Counter()
    token_samples = []
    for chunk_index, chunk in enumerate(rows(base/'prepared/chunks.jsonl')):
        if chunk_index % 2000 == 0:
            token_samples.append(chunk)
        identity = chunk['chunk_id']
        if identity in chunk_ids:
            fail('duplicate_chunk_id', identity)
        chunk_ids.add(identity)
        doc = docs.get(chunk['document_id'])
        if doc is None:
            fail('chunk_missing_parent', identity)
            continue
        start, end = chunk['start_char'], chunk['end_char']
        if not 0 <= start < end <= len(doc['text']) or doc['text'][start:end] != chunk['text']:
            fail('chunk_offset', identity)
        if identity != digest(f"{doc['document_id']}:{doc['content_hash']}:{start}:{end}"):
            fail('chunk_identity', identity)
        if not 1 <= chunk['token_count'] <= 220:
            fail('declared_token_bound', identity)
        for field in ('tickers','source_document_ids','source_url','available_at','published_at','source_type'):
            if chunk[field] != doc[field]:
                fail('chunk_'+field, identity)
        chunk_counts[chunk['document_id']] += 1
        exact_chunks[digest(chunk['text'])] += 1
        sections[chunk['section']] += 1
        for name, pattern in [('cover',r'SECURITIES AND EXCHANGE COMMISSION'),('toc',r'Table of Contents'),('signatures',r'Pursuant to the requirements of')]:
            if re.search(pattern, chunk['text'],re.I):
                boilerplate[name] += 1
    for identity in docs:
        if not chunk_counts[identity]:
            fail('document_without_chunks', identity)
    token_validation = {'status':'unavailable','sample_stride':2000}
    tokenizer_files = list((root/'.cache/huggingface').glob('models--sentence-transformers--all-MiniLM-L6-v2/snapshots/*/tokenizer.json'))
    if tokenizer_files:
        from tokenizers import Tokenizer
        tokenizer = Tokenizer.from_file(str(tokenizer_files[0]))
        tokenizer.no_truncation()
        tokenizer.no_padding()
        counts = [len(tokenizer.encode(c['text'], add_special_tokens=False).ids) for c in token_samples]
        token_validation = {'status':'sampled','sample_stride':2000,'sample_count':len(counts),
                            'maximum_actual_tokens':max(counts),'actual_over_220':sum(n>220 for n in counts),
                            'stored_count_differences':sum(n!=c['token_count'] for n,c in zip(counts,token_samples)),
                            'over_bound_examples':[{'chunk_id':c['chunk_id'],'actual':n,'stored':c['token_count']} for n,c in zip(counts,token_samples) if n>220][:5]}
    scores = {}
    score_status = Counter()
    truncated = 0
    for row in rows(base/'prepared/sentiment.jsonl'):
        key = (row['document_id'],row['ticker'])
        if key in scores:
            fail('duplicate_sentiment',str(key))
        scores[key] = row
        score_status[row['status']] += 1
        doc = docs.get(key[0])
        if not doc or doc['source_type'] != 'news' or key[1] not in doc['tickers']:
            fail('sentiment_parent', str(key))
            continue
        if any(row[k] != doc[k] for k in ('source_url','published_at','available_at')):
            fail('sentiment_provenance', str(key))
        if row['status'] == 'scored':
            if not math.isfinite(row['score']) or not -1 <= row['score'] <= 1:
                fail('sentiment_score',str(key))
            probabilities = row['probabilities']
            if abs(sum(probabilities.values())-1)>1e-5 or abs(row['score']-(probabilities['positive']-probabilities['negative']))>1e-6:
                fail('sentiment_probabilities',str(key))
            truncated += bool(row.get('input_truncated'))
        elif row.get('score') is not None:
            fail('missing_sentiment_not_null',str(key))
    expected = {(d['document_id'],t) for d in docs.values() if d['source_type']=='news' for t in d['tickers']}
    for key in expected - scores.keys():
        fail('missing_sentiment_association',str(key))
    aggregate_count = 0
    for row in rows(base/'prepared/sentiment_aggregates.jsonl'):
        aggregate_count += 1
        ticker = row['ticker']
        current = [d for d in docs.values() if d['source_type']=='news' and ticker in d['tickers'] and 0 <= (cutoff-date(d['published_at'])).total_seconds() <= 7*86400 and date(d['available_at']) <= cutoff]
        weighted = []
        for doc in current:
            score = scores[(doc['document_id'],ticker)]
            if score['status']=='scored':
                weighted.append((score['score'],math.exp(-math.log(2)*(cutoff-date(doc['published_at'])).total_seconds()/86400/2)))
        mean = sum(v*w for v,w in weighted)/sum(w for _,w in weighted) if weighted else None
        if row['articles_7d'] != len(current) or row['local_scored_articles_7d'] != len(weighted) or (mean is None) != (row['local_sentiment_7d'] is None) or (mean is not None and abs(mean-row['local_sentiment_7d'])>1e-10):
            fail('aggregate_recalculation',ticker)
        if row['sentiment_status'] != ('available' if weighted else 'unavailable') or row['historical_training_eligible'] is not False:
            fail('aggregate_missing_or_historical_state',ticker)
    coverage = json.loads((base/'sec/coverage.json').read_text())
    for doc in docs.values():
        if doc['source_type']=='sec':
            for ticker in doc['tickers']:
                if coverage['tickers'][ticker].get('cik') != doc['cik']:
                    fail('sec_coverage_cik',doc['document_id'])
    sec_docs = [d for d in docs.values() if d['source_type']=='sec']
    samples = []
    for form in ['10-K','10-Q','8-K','20-F','40-F','6-K']:
        choices = sorted((d for d in sec_docs if d['form']==form),key=lambda d:d['document_id'])
        selected = choices[:1] + ([choices[-1]] if len(choices)>1 else [])
        for doc in selected:
            raw_path = base/'sec/raw'/f"{digest(doc['source_url'])}.html"
            if not raw_path.exists():
                fail('raw_sample_missing',doc['document_id'])
                continue
            parser = RawSample()
            parser.feed(raw_path.read_text())
            unique_facts = sorted(set(parser.facts))
            samples.append({'document_id':doc['document_id'],'form':form,'chars':len(doc['text']),'raw_sha256':hashlib.sha256(raw_path.read_bytes()).hexdigest(),'visible_fact_fragments':len(unique_facts),'visible_fact_fragments_present':sum(f in doc['text'] for f in unique_facts),'hidden_fragments':len(set(parser.hidden)),'hidden_only_long_fragments_present':sum(f in doc['text'] for f in set(parser.hidden)-set(parser.facts) if len(f)>80),'exhibit_links':parser.links[:15],'exhibit_link_count':len(set(parser.links))})
    # Reconstruct the production attribution trace for human review, without
    # treating agreement with that heuristic as a semantic accuracy benchmark.
    sys.path.insert(0, str(root.resolve()))
    from prepare_text_data import sentiment_inputs, normalize_documents
    traces = sentiment_inputs(list(docs.values()), universe)
    pending = [r for r in traces if r['status'] == 'pending']
    selected = random.Random(17).sample(pending, min(12, len(pending)))
    selected += [r for r in pending if r['document_id'] in {
        'news:alpha_vantage:d827b2c86109b224557c92be59aec66c9cb736c524ddb2cc3fe76b52beb1065e:4a65c80e1bb6',
        'news:alpaca:61611969:69242336d72e'} and r['ticker'] in {'MS','NOW'}]
    attribution_samples = [{k:r[k] for k in ('document_id','ticker','text')} for r in selected]
    for trace in pending:
        stored = scores.get((trace['document_id'], trace['ticker']))
        if stored and stored['status']=='scored' and stored['input_hash'] != digest(trace['text']):
            fail('sentiment_input_hash', trace['document_id']+':'+trace['ticker'])
    synthetic = {**next(iter(sources.values())), 'document_id':'gate:synthetic'}
    probes = {}
    for name, changes in [('missing_timestamp',{'available_at':None}),
                          ('unknown_ticker',{'tickers':['NOT_IN_UNIVERSE']}),
                          ('future_available',{'available_at':'2099-01-01T00:00:00Z','fetched_at':'2099-01-01T00:00:00Z'})]:
        try:
            accepted, rejected = normalize_documents([{**synthetic, **changes}], universe, cutoff)
            probes[name] = {'rejected_without_crash':not accepted and bool(rejected)}
        except Exception as exc:
            probes[name] = {'rejected_without_crash':False, 'exception':type(exc).__name__}
        if not probes[name]['rejected_without_crash']:
            fail('failure_behavior_'+name, 'gate:synthetic')
    news_cov = json.loads((base/'news/coverage.json').read_text())
    return {'retokenized_chunk_sample':token_validation,'attribution_review_samples':attribution_samples,'failure_behavior_probes':probes,'report_contract':'Evaluation outputs are not training or migration inputs. Original source identities are hashed below; do not import evaluation output as another dataset snapshot.', 'as_of':manifest['as_of'],'source_counts':dict(source_counts),'prepared_counts':dict(prepared_counts),'source_publication_ranges':{k:[min(v),max(v)] for k,v in publication_ranges.items()},'source_integrity_pass':not any(n for k,n in problems.items() if not k.startswith('failure_behavior_')), 'integrity_failure_counts':{k:n for k,n in problems.items() if not k.startswith('failure_behavior_')}, 'robustness_failure_counts':{k:n for k,n in problems.items() if k.startswith('failure_behavior_')},'integrity_failure_examples':dict(examples),'chunks':len(chunk_ids),'exact_duplicate_documents_excess':sum(n-1 for n in text_hashes.values()),'exact_duplicate_chunks_excess':sum(n-1 for n in exact_chunks.values()),'chunks_in_document_section':sections['Document'],'boilerplate_chunk_markers':dict(boilerplate),'sentiment_status':dict(score_status),'sentiment_truncated':truncated,'sentiment_aggregate_rows':aggregate_count,'sec_forms':dict(Counter(d['form'] for d in sec_docs)),'short_event_forms_under_2000_chars':dict(Counter(d['form'] for d in sec_docs if d['form'] in ('6-K','8-K') and len(d['text'])<2000)),'raw_sec_samples':samples,'news_window_status':dict(Counter(w['status'] for w in news_cov['windows'].values())),'source_files_sha256':{str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for path in [base/'sec/documents.jsonl',base/'news/documents.jsonl',base/'prepared/documents.jsonl',base/'prepared/chunks.jsonl',base/'prepared/sentiment.jsonl',base/'prepared/sentiment_aggregates.jsonl']},'limitations':['All declared token counts checked; actual tokenizer bounds tested on deterministic sample only.','Source fact substring checks do not establish table semantics.','No independent labeled sentiment accuracy benchmark.','No retrieval/generation quality evaluation; no embedding model or index.','Local artifacts only; remote migration assessed separately.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root',type=Path,default=Path('data'))
    parser.add_argument('--output',type=Path,default=Path('data/artifacts/evaluation/text_gate.json'))
    args = parser.parse_args()
    result = evaluate(args.data_root)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('raw_sec_samples','source_files_sha256','integrity_failure_examples','attribution_review_samples')},indent=2))
    raise SystemExit(1 if result['integrity_failure_counts'] or result['robustness_failure_counts'] else 0)


if __name__ == '__main__':
    main()
