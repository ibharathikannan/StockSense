"""Grounded 'Why?' explanation generation (P5).

Produces the cited explanation that accompanies a research signal. It is **template-first**:
the explanation is assembled deterministically from the rule engine's `decision_trace` plus
the retrieved Evidence, so it is guaranteed grounded, cited, and free of invented financial
claims. An optional local LLM (Ollama) can rephrase the *same grounded facts* more fluently,
but its output must pass a guardrail validator or we fall back to the template.

Boundaries (docs/ai/DATA_GATE.md): cite sources or abstain; never issue buy/sell advice;
no specific financial figures; the forecast is a development-fold estimate; Marketaux
sentiment and any MONITOR* override are experimental. RAG explains the signal — it never
changes it.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Advice language the explanation must never contain (we are a research guide, not a broker).
BANNED_PATTERNS = [
    r"\bstrong buy\b", r"\bbuy now\b", r"\bsell now\b", r"\byou should (buy|sell)\b",
    r"\b(guaranteed|surefire|can'?t lose|risk[- ]free)\b", r"\bbuy more\b", r"\bdump\b",
]

STANDING_CAVEATS = [
    "This 10-day forecast is a development-fold estimate, not a guaranteed prediction.",
    "Signals guide research priority (Explore / Monitor / Caution), not trading decisions.",
    "News sentiment comes from a third-party provider and is experimental.",
]

STANCE_LEAD = {
    "EXPLORE": "Explore — worth a closer look",
    "MONITOR": "Monitor — keep on your radar",
    "CAUTION": "Caution — higher risk, research carefully",
}


def _citation(evidence_item: dict) -> dict:
    return {
        "title": evidence_item.get("title", ""),
        "source_type": evidence_item.get("source_type", ""),
        "published_at": evidence_item.get("published_at"),
        "source_url": evidence_item.get("source_url", ""),
    }


def _compose_template(stance: str, trace: list[str], evidence: list[dict], ticker: str,
                      provisional: bool) -> str:
    lines = [f"{STANCE_LEAD.get(stance, stance)} for {ticker}."]
    if trace:
        lines.append("Why this signal:")
        lines.extend(f"- {t}" for t in trace)
    if provisional:
        lines.append("- Note: recent news changed this from the forecast-only stance; "
                     "treat it as experimental/provisional pending validation.")
    if evidence:
        lines.append("Supporting evidence:")
        for i, ev in enumerate(evidence, 1):
            src = ev.get("source_type", "source")
            date = (ev.get("published_at") or "")[:10]
            title = ev.get("title") or "(untitled)"
            lines.append(f"[{i}] {title} — {src}{', ' + date if date else ''}")
            if ev.get("snippet"):
                lines.append(f"    “{ev['snippet']}”")
    else:
        lines.append(f"No recent news or filing evidence was found for {ticker}; this "
                     f"explanation reflects the deterministic signal only.")
    return "\n".join(lines)


def validate_explanation(text: str, evidence: list[dict]) -> list[str]:
    """Return a list of guardrail violations (empty means the text is acceptable)."""
    violations = []
    lowered = text.lower()
    for pattern in BANNED_PATTERNS:
        if re.search(pattern, lowered):
            violations.append(f"contains advice language matching /{pattern}/")
    # Dollar figures must be traceable to the evidence snippets (no invented numbers).
    evidence_blob = " ".join((e.get("snippet", "") + " " + e.get("title", "")) for e in evidence)
    for amount in re.findall(r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:billion|million|bn|m|k)?", text, re.I):
        if amount.strip() not in evidence_blob:
            violations.append(f"cites a financial figure not present in evidence: {amount.strip()}")
    return violations


def _ollama_polish(prompt: str, model: str) -> Optional[str]:
    """Best-effort fluency pass. Returns None if Ollama is unavailable or errors."""
    try:
        import ollama
    except ImportError:
        return None
    try:
        response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}],
                               options={"temperature": 0.2})
        return (response.get("message") or {}).get("content")
    except Exception:
        return None


def _llm_prompt(grounded: str) -> str:
    return (
        "Rewrite the following stock-research note so it reads as clear, plain English for a "
        "beginner investor. Rules you MUST follow: keep every fact and every bracketed citation "
        "[n] exactly as given; do not add any numbers, prices, or financial figures that are not "
        "already present; never give buy/sell advice; do not change the Explore/Monitor/Caution "
        "stance. Only rephrase.\n\n" + grounded
    )


def explain(signal: dict[str, Any], evidence: list[dict], ticker: str, *,
            use_llm: bool = False, ollama_model: str = "llama3.2") -> dict[str, Any]:
    """Build the grounded, cited Explanation for a signal.

    `abstained` means no external evidence was found — the deterministic signal reasoning is
    still explained, but no news/filing claims are made. Returns the Explanation shape used by
    the snapshot (text, citations, abstained, caveats).
    """
    stance = signal.get("news_aware_stance") or signal.get("baseline_stance")
    trace = list(signal.get("decision_trace") or [])
    provisional = bool(signal.get("provisional"))
    abstained = not evidence

    grounded = _compose_template(stance, trace, evidence, ticker, provisional)
    text = grounded
    if use_llm and evidence is not None:
        polished = _ollama_polish(_llm_prompt(grounded), ollama_model)
        if polished and not validate_explanation(polished, evidence):
            text = polished  # accept the fluent version only if it passes the guardrail

    caveats = list(STANDING_CAVEATS)
    if provisional:
        caveats.append("This news-driven change of stance is experimental and not yet "
                       "validated against historical performance.")

    return {
        "text": text,
        "citations": [_citation(e) for e in evidence],
        "abstained": abstained,
        "caveats": caveats,
    }
