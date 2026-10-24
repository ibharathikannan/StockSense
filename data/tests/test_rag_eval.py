"""Unit tests for the RAG evaluation metrics (pure; no DB or model)."""
from data.evaluation.rag_eval import (FABRICATED_CLAIM, build_queries, context_relevance,
                                      evaluate_query, faithfulness, precision_at_k, recall_at_k,
                                      snapshot_context, split_claims)
from data.rag.explainer import _compose_template

TRACE = ["Favorable trend: 10-day projected return is strong (+4.0%).",
         "Risk aligned: volatility (0.18) fits within your Moderate boundary."]
EVIDENCE = [{"title": "Apple unveils new chip", "source_type": "news",
             "published_at": "2026-10-07T12:00:00Z", "snippet": "Apple announced a new processor today."}]


def _substring_entail(premises, hypothesis):
    """Fake NLI: a premise entails a hypothesis it contains verbatim."""
    return [1.0 if hypothesis.rstrip(".") in p else 0.0 for p in premises]


def test_precision_divides_by_k_even_when_fewer_results():
    assert precision_at_k(["a", "x", "b"], {"a", "b"}, 3) == 2 / 3
    assert precision_at_k(["a"], {"a"}, 5) == 0.2
    assert precision_at_k([], {"a"}, 1) == 0.0


def test_recall_against_all_relevant_and_none_without_relevant():
    assert recall_at_k(["a", "x"], {"a", "b", "c", "d"}, 2) == 0.25
    assert recall_at_k(["a", "b"], {"a", "b"}, 1) == 0.5
    assert recall_at_k(["a"], set(), 1) is None


def test_context_relevance_is_mean_score_or_none():
    assert context_relevance([0.2, 0.8]) == 0.5
    assert context_relevance([]) is None


def test_evaluate_query_uses_threshold_on_pool_scores():
    scores = {"a": 0.9, "b": 0.6, "c": 0.1, "d": 0.7}
    out = evaluate_query(["a", "c", "b"], scores, ks=(1, 3), threshold=0.5)
    assert out["relevant_in_pool"] == 3
    assert out["precision@1"] == 1.0 and out["precision@3"] == 2 / 3
    assert out["recall@3"] == 2 / 3
    assert abs(out["context_relevance@3"] - (0.9 + 0.1 + 0.6) / 3) < 1e-9


def test_split_claims_skips_template_scaffolding():
    text = _compose_template("EXPLORE", TRACE, EVIDENCE, "AAPL", False)
    claims = split_claims(text)
    assert claims == [TRACE[0], TRACE[1], "Apple announced a new processor today."]


def test_split_claims_skips_abstention_note_and_splits_sentences():
    text = _compose_template("MONITOR", ["Sentiment is unavailable. News coverage gap means no "
                                         "sentiment evidence was used."], [], "AAPL", True)
    assert split_claims(text) == ["Sentiment is unavailable.",
                                  "News coverage gap means no sentiment evidence was used."]


def test_faithfulness_counts_supported_claims_and_control_drops():
    snapshot = {"evidence": EVIDENCE, "signal": {"decision_trace": TRACE}}
    text = _compose_template("EXPLORE", TRACE, EVIDENCE, "AAPL", False)
    passages = snapshot_context(snapshot)

    score, unsupported = faithfulness(split_claims(text), passages, _substring_entail)
    assert score == 1.0 and unsupported == []

    control, unsupported = faithfulness(split_claims(text + "\n" + FABRICATED_CLAIM), passages,
                                        _substring_entail)
    assert control == 0.75 and len(unsupported) == 1


def test_snapshot_context_adds_sentence_level_premises():
    snapshot = {"evidence": [{"title": "Chip news", "snippet": "Apple made a chip.\nSales rose sharply."}],
                "signal": {"decision_trace": ["Sentiment is unavailable. Coverage gap here."]}}
    passages = snapshot_context(snapshot)
    assert "Chip news. Apple made a chip.\nSales rose sharply." in passages
    assert {"Apple made a chip.", "Sales rose sharply.", "Sentiment is unavailable."} <= set(passages)


def test_faithfulness_without_claims_or_context():
    assert faithfulness([], ["p"], _substring_entail) == (None, [])
    assert faithfulness(["A claim here."], [], _substring_entail) == (0.0, ["A claim here."])


def test_build_queries_templates_eligible_tickers_and_known_topicals():
    profiles = [{"ticker": "AAPL", "name": "Apple Inc.", "recommendation_eligible": True},
                {"ticker": "SPY", "name": "SPDR", "recommendation_eligible": False}]
    queries = build_queries(profiles, tickers_limit=5)
    kinds = [(q["ticker"], q["kind"]) for q in queries]
    assert kinds == [("AAPL", "production-news"), ("AAPL", "production-sec"), ("AAPL", "topical")]
    assert queries[0]["query"] == "Apple Inc. latest news and developments"
