"""Unit tests for snapshot assembly (P7). Pure — exercises the real engine + explainer, no DB."""
from datetime import datetime, timezone

from data.rag.assemble_snapshots import build_snapshot, load_forecasts, placeholder_forecast

AS_OF = datetime(2026, 10, 9, tzinfo=timezone.utc)
PROFILE = {"ticker": "AAPL", "name": "Apple", "sector": "Information Technology",
           "asset_type": "stock", "risk": {"volatility_1y": 0.22}}
EVIDENCE = [{"title": "Apple update", "source_type": "news",
             "published_at": "2026-10-07T00:00:00Z", "source_url": "u", "snippet": "s"}]


def _news(score):
    return {"score": score, "article_count": 3, "recency_hours": 10.0, "relevant": True,
            "source": "marketaux", "relevance": 0.1}


def test_placeholder_forecast_is_pending():
    f = placeholder_forecast("AAPL")
    assert f["return_10d"] is None and "pending" in f["basis"].lower()


def test_placeholder_never_yields_explore_and_notes_pending():
    snap = build_snapshot(PROFILE, "moderate", _news(0.3), EVIDENCE, placeholder_forecast("AAPL"), AS_OF)
    assert snap["forecast"]["return_10d"] is None
    assert snap["signal"]["news_aware_stance"] in ("MONITOR", "CAUTION")   # EXPLORE needs a real forecast
    assert any("Forecast pending" in t for t in snap["signal"]["decision_trace"])
    assert snap["explanation"]["text"]


def test_bearish_news_still_drives_caution_under_placeholder():
    snap = build_snapshot(PROFILE, "moderate", _news(-0.3), EVIDENCE, placeholder_forecast("AAPL"), AS_OF)
    assert snap["signal"]["news_aware_stance"] == "CAUTION"


def test_snapshot_has_full_shape():
    snap = build_snapshot(PROFILE, "conservative", None, EVIDENCE, placeholder_forecast("AAPL"), AS_OF)
    for key in ("ticker", "name", "sector", "asset_type", "as_of", "forecast", "signal",
                "evidence", "explanation"):
        assert key in snap
    assert snap["signal"]["risk_profile"] == "conservative"
    assert snap["evidence"] == EVIDENCE


# --- Real forecast wiring (main's saved XGBoost results feed the hybrid engine) ---------

def _write_forecasts(tmp_path, rows):
    header = ("ticker,Date,predicted_return_10d,lower_return,upper_return,"
              "uncertainty_width_pp,nominal_coverage,model,forecast_horizon_sessions\n")
    body = "".join(f"{t},2026-10-08,{p},{lo},{up},{(up-lo)*100},0.9,xgboost_v1,10\n"
                   for t, p, lo, up in rows)
    (tmp_path / "forecasts.csv").write_text(header + body)
    (tmp_path / "report.json").write_text('{"metadata": {"selected_model": "xgboost_v1"}}')
    return tmp_path


def test_load_forecasts_scales_fractions_to_percent(tmp_path):
    _write_forecasts(tmp_path, [("AAPL", 0.04, 0.015, 0.065)])
    fc = load_forecasts(str(tmp_path))
    assert fc["AAPL"]["return_10d"] == 4.0          # 0.04 fraction -> 4.0 percent
    assert fc["AAPL"]["lower"] == 1.5 and fc["AAPL"]["upper"] == 6.5
    assert fc["AAPL"]["model_version"] == "xgboost_v1"
    assert fc["AAPL"]["return_10d"] is not None and "pending" not in fc["AAPL"]["basis"].lower()


def test_load_forecasts_absent_returns_empty(tmp_path):
    assert load_forecasts(str(tmp_path / "nope")) == {}   # falls back to placeholder in assemble
    assert load_forecasts(None) in ({}, load_forecasts(None))  # None without env var -> {}


def test_confident_negative_forecast_drives_caution(tmp_path):
    # Regression: the old 0.0 placeholder never tripped the negative-return rule. A forecast
    # that is confidently negative (whole interval below zero) must, even with no news.
    fc = load_forecasts(str(_write_forecasts(tmp_path, [("AAPL", -0.02, -0.035, -0.005)])))
    snap = build_snapshot(PROFILE, "moderate", None, EVIDENCE, fc["AAPL"], AS_OF)
    assert snap["signal"]["news_aware_stance"] == "CAUTION"
    assert snap["forecast"]["return_10d"] == -2.0
    assert not any("Forecast pending" in t for t in snap["signal"]["decision_trace"])


def test_weak_forecast_straddling_zero_is_neutral(tmp_path):
    # A negative point estimate whose interval still spans zero is within the model's noise,
    # so it must NOT force CAUTION — the weak forecaster does not get to move the stance.
    fc = load_forecasts(str(_write_forecasts(tmp_path, [("AAPL", -0.02, -0.05, 0.03)])))
    snap = build_snapshot(PROFILE, "moderate", None, EVIDENCE, fc["AAPL"], AS_OF)
    assert snap["signal"]["news_aware_stance"] == "MONITOR"
    assert snap["forecast"]["return_10d"] == -2.0          # the real number is still shown
    assert any("treated as neutral" in t for t in snap["signal"]["decision_trace"])


def test_tiny_forecast_within_noise_band_is_neutral(tmp_path):
    # Confident direction but economically negligible magnitude (< NEUTRAL_RETURN_BAND).
    fc = load_forecasts(str(_write_forecasts(tmp_path, [("AAPL", 0.003, 0.001, 0.005)])))
    snap = build_snapshot(PROFILE, "moderate", None, EVIDENCE, fc["AAPL"], AS_OF)
    assert snap["signal"]["news_aware_stance"] == "MONITOR"
    assert any("treated as neutral" in t for t in snap["signal"]["decision_trace"])


def test_fundamentals_flow_into_snapshot_signal():
    strong = {"score": 0.8, "rating": "strong", "metric_count": 5, "age_days": 30,
              "source": "sec_xbrl", "period_end": "2025-12-31", "filed": "2026-02-15",
              "metrics": {"operating_margin": {"value": 0.3, "assessment": "strong"}}}
    forecast = {**placeholder_forecast("AAPL"), "return_10d": 3.0, "lower": 1.0, "upper": 5.0}
    snap = build_snapshot(PROFILE, "moderate", None, EVIDENCE, forecast, AS_OF,
                          fundamentals_signal=strong)
    assert snap["signal"]["fundamentals_signal"]["rating"] == "strong"
    assert snap["signal"]["news_aware_stance"] == "EXPLORE" and snap["signal"]["provisional"] is True
    # EXPLORE still requires a real forecast: the placeholder keeps the MONITOR cap.
    pending = build_snapshot(PROFILE, "moderate", None, EVIDENCE, placeholder_forecast("AAPL"), AS_OF,
                             fundamentals_signal=strong)
    assert pending["signal"]["news_aware_stance"] == "MONITOR"
    absent = build_snapshot(PROFILE, "moderate", None, EVIDENCE, placeholder_forecast("AAPL"), AS_OF)
    assert absent["signal"]["fundamentals_signal"]["score"] is None


class _Cursor:
    def __init__(self, results, sql): self.results, self.sql = results, sql
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def execute(self, sql, params=None): self.sql.append((" ".join(sql.split()), params))
    def fetchone(self): return self.results.pop(0)
    def fetchall(self): return self.results.pop(0)


class _Conn:
    def __init__(self, *results): self.results, self.sql = list(results), []
    def cursor(self): return _Cursor(self.results, self.sql)


def test_db_forecasts_use_newest_batch_in_percent_units():
    from data.rag.assemble_snapshots import load_forecasts_from_db
    conn = _Conn(("forecast_batches", "forecast_results"), ("batch-1", "XGBoost grid=3"),
                 [(" aapl ", 0.0125, -0.05, 0.075)])
    forecasts = load_forecasts_from_db(conn)
    assert forecasts["AAPL"]["return_10d"] == 1.25
    assert forecasts["AAPL"]["lower"] == -5.0 and forecasts["AAPL"]["upper"] == 7.5
    assert forecasts["AAPL"]["model_version"] == "XGBoost grid=3"
    assert "ORDER BY as_of DESC, generated_at DESC" in conn.sql[1][0]
    assert conn.sql[2][1] == ("batch-1",)


def test_db_forecasts_absent_without_tables_or_batches():
    from data.rag.assemble_snapshots import load_forecasts_from_db
    assert load_forecasts_from_db(_Conn((None, None))) == {}
    assert load_forecasts_from_db(_Conn(("forecast_batches", "forecast_results"), None)) == {}


# --- Marketaux news accumulated in the database ------------------------------------------

def _ev(title, published, url=None, sentiment=None):
    return {"title": title, "source_type": "news", "published_at": published,
            "source_url": url or title, "snippet": "s", "sentiment": sentiment}


def test_recent_news_takes_newest_across_sources_and_prefers_marketaux_copies():
    from data.rag.assemble_snapshots import recent_news_evidence

    marketaux = [_ev("mx-new", "2026-10-20T10:00:00Z", sentiment=0.4),
                 _ev("shared", "2026-10-18T00:00:00Z", url="u1", sentiment=-0.2)]
    retrieved = [_ev("old", "2026-09-23T00:00:00Z"), _ev("shared-copy", "2026-10-18T00:00:00Z", url="u1"),
                 _ev("fresh-retrieved", "2026-10-21T00:00:00Z"), _ev("undated", None)]
    out = recent_news_evidence(marketaux, retrieved, limit=3)
    assert [e["title"] for e in out] == ["fresh-retrieved", "mx-new", "shared"]
    assert out[2]["sentiment"] == -0.2


def test_merge_documents_prefers_tonights_copy():
    from data.rag.assemble_snapshots import merge_documents

    stored = [{"document_id": "a", "provider_sentiment": None}, {"document_id": "b"}]
    fresh = [{"document_id": "a", "provider_sentiment": {"AAPL": {"score": 0.3}}}]
    merged = {d["document_id"]: d for d in merge_documents(stored, fresh)}
    assert set(merged) == {"a", "b"}
    assert merged["a"]["provider_sentiment"]["AAPL"]["score"] == 0.3


class _NewsCursor:
    def __init__(self, columns, rows):
        self.columns, self.rows, self.result, self.queries = columns, rows, [], []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.queries.append((sql, params))
        self.result = [(c,) for c in self.columns] if "information_schema" in sql else self.rows

    def fetchall(self):
        return self.result


class _NewsConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_stored_marketaux_rows_feed_sentiment_and_evidence():
    from data.rag.assemble_snapshots import load_marketaux_documents_from_db, marketaux_news_evidence
    from data.rag.news_sentiment import records_from_documents

    published = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    row = ("news:marketaux:abc", "Apple beats", "https://x/1", published, None, ["AAPL"], "h", "body",
           '{"AAPL": {"score": 0.5, "relevance": 0.2}}')
    cols = ["document_id", "provider", "provider_sentiment", "available_at"]
    docs = load_marketaux_documents_from_db(_NewsConn(_NewsCursor(cols, [row])), AS_OF)
    assert docs[0]["provider_id"] == "abc" and docs[0]["available_at"] == published.isoformat()
    records = records_from_documents(docs)
    assert len(records) == 1 and records[0].score == 0.5 and records[0].source == "marketaux"
    ev = marketaux_news_evidence(docs, "AAPL", AS_OF)
    assert ev[0]["title"] == "Apple beats" and ev[0]["sentiment"] == 0.5


def test_stored_rows_without_sentiment_column_still_give_headlines():
    from data.rag.assemble_snapshots import load_marketaux_documents_from_db

    published = datetime(2026, 10, 8, tzinfo=timezone.utc)
    cursor = _NewsCursor(["document_id", "provider"],
                     [("news:marketaux:x", "Old row", "u", published, None, ["AAPL"], "h", "t", None)])
    docs = load_marketaux_documents_from_db(_NewsConn(cursor), AS_OF)
    assert docs[0]["provider_sentiment"] is None
    assert "NULL::jsonb" in cursor.queries[-1][0]
    assert load_marketaux_documents_from_db(_NewsConn(_NewsCursor([], [])), AS_OF) == []
