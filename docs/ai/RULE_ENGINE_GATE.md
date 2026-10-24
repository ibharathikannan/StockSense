# Rule engine evaluation — 2026-10-24

This evaluation reads only the rule engine source (`backend/app/rule_engine/rule_based_engine.py`,
rules version 1.1.0). It does not read datasets, train models, call providers, or query the
database. It covers the base engine; the news and SEC fundamentals layer in
`hybrid_engine.py` is not evaluated here.

## What is measured

| Measure | Method | Result |
| --- | --- | --- |
| Rule accuracy | Every combination of 6 forecast returns, 5 volatility values around each profile's limit, 8 sentiment values, 5 interval widths, 3 lower bounds and 3 sector weights, for all 5 risk profiles (54,000 cases). The engine's stance is compared with an independent restatement of the written rules. | 54,000 of 54,000 match |
| Rule consistency | 2,000 random inputs (fixed seed), each evaluated 20 times; full outputs compared. | 40,000 evaluations, 0 differences |
| Decision trace completeness | Over the same 54,000 cases: all required fields present; a stated reason for the outcome (a caution code for every CAUTION, the confluence code and at least four trace lines for every EXPLORE, at least one line for MONITOR); only known reason codes; no buy or sell wording in the trace. | 54,000 of 54,000 on each check |

The repository's 17 unit tests in `backend/tests/test_rule_based_engine.py` also pass.

## Reproducible evidence

```bash
python data/evaluation/rule_engine_gate.py
```

Evidence is written to the ignored `data/artifacts/evaluation/rule_engine_gate.json`. The
script exits 0 when every check passes and 1 otherwise. A deliberate change of one
threshold (the strong-return limit from 2.0 to 2.5) was detected: 240 of 54,000 stances
then differed from the reference and the script reported failure.

## Limits of this evidence

- The reference was written from the same specification as the engine, so the result shows
  that the code implements the written rules consistently, not that the rules are right.
- The grid is synthetic. It covers boundaries, not the distribution of real forecasts.
- Nothing here measures whether the stances predict returns, or how stances are distributed
  across the deployed snapshots.

## Finding: interval-width threshold

The engine treats a prediction interval wider than 6.0 percentage points as high
uncertainty, and a flagged result cannot be EXPLORE. In the grid, with every other EXPLORE
condition met, EXPLORE was reached at widths of 0.0 and 6.0 and never at 6.1, 24.0 or when
the interval was missing. The forecasting model's reported intervals are far wider than 6.0
percentage points (mean width 23.96, see `data/FORECASTING.md`), so the base rules alone can rarely produce EXPLORE
on real forecasts. The threshold needs recalibration against the model's interval
distribution before it is relied on.
