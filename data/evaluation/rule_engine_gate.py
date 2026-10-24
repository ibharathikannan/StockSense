#!/usr/bin/env python3
"""Independent, read-only evaluation of the rule engine; never touches data or the network.

Run from any directory:  python data/evaluation/rule_engine_gate.py

Measures the three rule-engine criteria in the report's success table:
  * Rule accuracy: the engine's stance is compared with an independent restatement of
    the written rules over an exhaustive grid of boundary inputs for all five risk profiles.
  * Rule consistency: random inputs are evaluated repeatedly and the full outputs compared.
  * Decision trace completeness: every output carries its required fields, a stated
    reason for its outcome, only known reason codes, and no buy/sell wording.

Only the base engine (backend/app/rule_engine/rule_based_engine.py) is evaluated; the news
and fundamentals layer in hybrid_engine.py is not covered. The reference below is written
from the same specification as the engine, so this shows conformance and consistency, not
that the signals predict returns. Writes one JSON file under data/artifacts/evaluation/.
Exit code 0 when every check passes, 1 when any check fails.
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.rule_engine.rule_based_engine import (  # noqa: E402
    RULES_VERSION,
    VOLATILITY_LIMITS,
    evaluate_stock_stance,
)

OUTPUT = ROOT / "data" / "artifacts" / "evaluation" / "rule_engine_gate.json"
REQUIRED_FIELDS = ("stance", "decision_trace", "reason_codes", "inputs",
                   "thresholds", "rules_version", "disclaimer")
KNOWN_CODES = {
    "UNKNOWN_PROFILE", "SENTIMENT_MISSING", "NEGATIVE_FORECAST", "VOLATILITY_EXCEEDS_LIMIT",
    "BEARISH_SENTIMENT", "INTERVAL_MISSING", "INTERVAL_TOO_WIDE", "INTERVAL_INCLUDES_LOSS",
    "SECTOR_CONCENTRATION", "EXPLORE_CONFLUENCE", "RETURN_BELOW_THRESHOLD", "SENTIMENT_NEUTRAL",
}
CAUTION_CODES = {"NEGATIVE_FORECAST", "VOLATILITY_EXCEEDS_LIMIT", "BEARISH_SENTIMENT"}
BANNED = re.compile(r"\b(buy|sell|hold|short)\b", re.I)


def reference_stance(ret, vol, sentiment, width, profile, lower, sector):
    """The written rules, restated independently of the engine's code."""
    limit = VOLATILITY_LIMITS[profile]
    if ret < 0 or vol > limit or (sentiment is not None and sentiment <= -0.15):
        return "CAUTION"
    uncertain = width is None or width > 6.0 or (lower is not None and lower < 0 and ret >= 0)
    concentrated = sector is not None and sector > 0.30
    if ret >= 2.0 and sentiment is not None and sentiment >= 0.15 and not uncertain and not concentrated:
        return "EXPLORE"
    return "MONITOR"


def grid():
    for profile, limit in VOLATILITY_LIMITS.items():
        vols = sorted({0.0, round(limit - 0.001, 4), limit, round(limit + 0.001, 4), 0.9})
        for case in itertools.product(
            [-5.0, -0.1, 0.0, 1.99, 2.0, 5.0], vols,
            [None, -1.0, -0.15, -0.14, 0.0, 0.14, 0.15, 1.0],
            [None, 0.0, 6.0, 6.1, 24.0], [None, -1.0, 0.5], [None, 0.30, 0.31],
        ):
            ret, vol, sentiment, width, lower, sector = case
            yield ret, vol, sentiment, width, profile, lower, sector


def call(ret, vol, sentiment, width, profile, lower, sector):
    return evaluate_stock_stance(
        forecast_return=ret, volatility=vol, sentiment_score=sentiment,
        prediction_interval_width=width, user_risk_profile=profile,
        forecast_lower_bound=lower, sector_weight=sector)


def accuracy_and_trace():
    total = mismatches = fields = reasons = codes = wording = 0
    stances = Counter()
    for case in grid():
        out = call(*case)
        total += 1
        stances[out["stance"]] += 1
        mismatches += out["stance"] != reference_stance(*case)
        trace, found = out["decision_trace"], set(out["reason_codes"])
        fields += all(key in out for key in REQUIRED_FIELDS)
        if out["stance"] == "CAUTION":
            reasons += bool(found & CAUTION_CODES) and len(trace) >= 1
        elif out["stance"] == "EXPLORE":
            reasons += "EXPLORE_CONFLUENCE" in found and len(trace) >= 4
        else:
            reasons += len(trace) >= 1
        codes += found <= KNOWN_CODES
        wording += not any(BANNED.search(line) for line in trace)
    return {"cases": total, "stance_mismatches": mismatches, "stances_in_grid": dict(stances),
            "fields_present": fields, "reason_for_outcome": reasons,
            "known_reason_codes": codes, "no_buy_sell_wording": wording}


def consistency(inputs=2000, repeats=20, seed=7):
    rng = random.Random(seed)
    profiles = list(VOLATILITY_LIMITS)
    differences = 0
    for _ in range(inputs):
        case = (round(rng.uniform(-8, 8), 2), round(rng.uniform(0, 0.8), 3),
                rng.choice([None, round(rng.uniform(-1, 1), 2)]),
                rng.choice([None, round(rng.uniform(0, 30), 1)]), rng.choice(profiles),
                rng.choice([None, round(rng.uniform(-10, 5), 1)]),
                rng.choice([None, round(rng.uniform(0, 1), 2)]))
        first = json.dumps(call(*case), sort_keys=True)
        differences += sum(json.dumps(call(*case), sort_keys=True) != first for _ in range(repeats - 1))
    return {"inputs": inputs, "evaluations": inputs * repeats, "differences": differences}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=OUTPUT, help="JSON evidence path")
    args = parser.parse_args()

    result = {"rules_version": RULES_VERSION, "accuracy_and_trace": accuracy_and_trace(),
              "consistency": consistency()}
    a, c = result["accuracy_and_trace"], result["consistency"]
    ok = (a["stance_mismatches"] == 0 and c["differences"] == 0 and
          all(a[key] == a["cases"] for key in
              ("fields_present", "reason_for_outcome", "known_reason_codes", "no_buy_sell_wording")))
    result["all_checks_pass"] = ok
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"Rules version {RULES_VERSION}")
    print(f"Rule accuracy: {a['cases'] - a['stance_mismatches']}/{a['cases']} stances match the reference")
    print(f"Rule consistency: {c['differences']} differences in {c['evaluations']} evaluations")
    print(f"Trace completeness (of {a['cases']}): fields {a['fields_present']}, reason for outcome "
          f"{a['reason_for_outcome']}, known codes {a['known_reason_codes']}, "
          f"no buy/sell wording {a['no_buy_sell_wording']}")
    print("ALL CHECKS PASS" if ok else "CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
