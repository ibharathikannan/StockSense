import unittest
from app.rule_engine.rule_based_engine import evaluate_stock_stance as ev

# A baseline input that yields EXPLORE for a moderate user
GOOD = dict(forecast_return=3.0, volatility=0.30, sentiment_score=0.4,
            prediction_interval_width=4.0, user_risk_profile="moderate")


def run(**over):
    return ev(**{**GOOD, **over})


class TestStances(unittest.TestCase):
    def test_explore(self):
        self.assertEqual(run()["stance"], "EXPLORE")

    def test_caution_negative_return(self):
        self.assertEqual(run(forecast_return=-0.1)["stance"], "CAUTION")

    def test_zero_return_not_caution(self):
        self.assertEqual(run(forecast_return=0.0)["stance"], "MONITOR")

    def test_return_boundary_2(self):
        self.assertEqual(run(forecast_return=2.0)["stance"], "EXPLORE")
        self.assertEqual(run(forecast_return=1.99)["stance"], "MONITOR")

    def test_volatility_boundary(self):
        self.assertEqual(run(volatility=0.35)["stance"], "EXPLORE")
        self.assertEqual(run(volatility=0.351)["stance"], "CAUTION")

    def test_sentiment_boundaries(self):
        self.assertEqual(run(sentiment_score=-0.15)["stance"], "CAUTION")
        self.assertEqual(run(sentiment_score=-0.14)["stance"], "MONITOR")
        self.assertEqual(run(sentiment_score=0.15)["stance"], "EXPLORE")
        self.assertEqual(run(sentiment_score=0.14)["stance"], "MONITOR")

    def test_interval_boundary(self):
        self.assertEqual(run(prediction_interval_width=6.0)["stance"], "EXPLORE")
        self.assertEqual(run(prediction_interval_width=6.1)["stance"], "MONITOR")

    def test_missing_interval_caps_at_monitor(self):
        r = run(prediction_interval_width=None)
        self.assertEqual(r["stance"], "MONITOR")
        self.assertIn("INTERVAL_MISSING", r["reason_codes"])

    def test_missing_sentiment_cannot_explore(self):
        r = run(sentiment_score=None)
        self.assertEqual(r["stance"], "MONITOR")
        self.assertIn("SENTIMENT_MISSING", r["reason_codes"])

    def test_lower_bound_loss_caps_at_monitor(self):
        r = run(forecast_lower_bound=-0.5)
        self.assertEqual(r["stance"], "MONITOR")
        self.assertIn("INTERVAL_INCLUDES_LOSS", r["reason_codes"])

    def test_concentration_downgrades(self):
        self.assertEqual(run(sector_weight=0.31)["stance"], "MONITOR")
        self.assertEqual(run(sector_weight=0.30)["stance"], "EXPLORE")


class TestProfilesAndTrace(unittest.TestCase):
    def test_profile_normalisation(self):
        self.assertEqual(run(user_risk_profile="Very_Conservative", volatility=0.16)["stance"], "CAUTION")

    def test_unknown_profile_flagged(self):
        r = run(user_risk_profile="foo")
        self.assertIn("UNKNOWN_PROFILE", r["reason_codes"])
        self.assertEqual(r["thresholds"]["max_volatility"], 0.35)

    def test_multiple_caution_reasons(self):
        r = run(forecast_return=-1, volatility=0.9, sentiment_score=-0.5)
        self.assertEqual(r["stance"], "CAUTION")
        for c in ("NEGATIVE_FORECAST", "VOLATILITY_EXCEEDS_LIMIT", "BEARISH_SENTIMENT"):
            self.assertIn(c, r["reason_codes"])

    def test_caution_records_uncertainty(self):
        r = run(forecast_return=-1, prediction_interval_width=9.0)
        self.assertIn("INTERVAL_TOO_WIDE", r["reason_codes"])

    def test_output_fields(self):
        r = run()
        for k in ("decision_trace", "reason_codes", "inputs", "thresholds",
                  "rules_version", "disclaimer"):
            self.assertIn(k, r)


class TestValidation(unittest.TestCase):
    def test_bad_inputs_raise(self):
        for bad in (dict(forecast_return=float("nan")), dict(volatility=-0.1),
                    dict(sentiment_score=1.5), dict(prediction_interval_width=-1),
                    dict(sector_weight=1.2), dict(forecast_return=None)):
            with self.assertRaises(ValueError, msg=str(bad)):
                run(**bad)


if __name__ == "__main__":
    unittest.main()
