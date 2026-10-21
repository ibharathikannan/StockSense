"""Unit tests for grounded explanation generation (P5). Pure; template path, no LLM."""
from data.rag.explainer import explain, validate_explanation, _compose_template


SIGNAL = {
    "baseline_stance": "EXPLORE", "news_aware_stance": "EXPLORE", "provisional": False,
    "decision_trace": ["Favorable trend: 10-day projected return is strong (+4.0%).",
                       "Risk aligned: volatility (0.18) fits within your Moderate boundary."],
}
EVIDENCE = [
    {"title": "Apple unveils new chip", "source_type": "news",
     "published_at": "2026-10-07T12:00:00Z", "source_url": "https://ex/1",
     "snippet": "Apple announced a new processor today."},
]


def test_explain_includes_trace_and_citations():
    out = explain(SIGNAL, EVIDENCE, "AAPL")
    assert out["abstained"] is False
    assert "Explore" in out["text"] and "Favorable trend" in out["text"]
    assert "[1]" in out["text"] and "Apple unveils new chip" in out["text"]
    assert out["citations"][0]["source_url"] == "https://ex/1"
    assert any("development-fold" in c for c in out["caveats"])


def test_explain_abstains_without_evidence():
    out = explain(SIGNAL, [], "AAPL")
    assert out["abstained"] is True
    assert "No recent news or filing evidence" in out["text"]
    assert out["citations"] == []


def test_provisional_change_is_flagged():
    signal = {**SIGNAL, "news_aware_stance": "CAUTION", "provisional": True,
              "decision_trace": ["News-driven change (experimental): recent sentiment strongly negative."]}
    out = explain(signal, EVIDENCE, "NKE")
    assert "experimental" in out["text"].lower()
    assert any("experimental" in c.lower() for c in out["caveats"])


def test_validator_flags_advice_language():
    assert validate_explanation("This is a strong buy opportunity.", []) != []
    assert validate_explanation("You should sell immediately.", []) != []


def test_validator_flags_untraceable_financial_figure():
    violations = validate_explanation("Revenue hit $5 billion this quarter.", EVIDENCE)
    assert any("financial figure" in v for v in violations)


def test_validator_allows_grounded_figure():
    ev = [{"title": "t", "snippet": "Revenue hit $5 billion this quarter.", "source_type": "news"}]
    assert validate_explanation("The note mentions $5 billion in revenue.", ev) == []


def test_validator_passes_clean_template():
    out = _compose_template("EXPLORE", SIGNAL["decision_trace"], EVIDENCE, "AAPL", False)
    assert validate_explanation(out, EVIDENCE) == []
