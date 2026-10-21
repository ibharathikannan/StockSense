import asyncio
import datetime as dt

from app.services.research import ResearchService

UTC = dt.timezone.utc
ROW = {
    "ticker": "AAPL", "name": "Apple Inc.", "sector": "Information Technology", "asset_type": "stock",
    "as_of": dt.date(2026, 10, 21), "baseline_stance": "MONITOR", "news_aware_stance": "MONITOR",
    "provisional": False, "risk_profile": "moderate", "forecast": {},
    "signal_detail": {"decision_trace": ["Mixed signals."], "news_signal": {"score": None}},
    "evidence": [], "explanation": {"text": ""},
}
AV = {
    "as_of": "2026-10-02T08:59:39Z", "ticker": "AAPL", "articles_7d": 92, "lookback_days": 7,
    "sentiment_status": "available", "latest_publication": "2026-10-02T02:13:50Z",
    "alpha_vantage_sentiment_7d": 0.058, "local_sentiment_7d": -0.087,
}
ARTICLES = [
    {"document_id": "news:marketaux:1", "title": "Apple beats estimates", "source_url": "https://x/1",
     "published_at": dt.datetime(2026, 10, 20, tzinfo=UTC), "text": "Shares rose.",
     "provider_sentiment": {"AAPL": {"score": 0.4}}},
    {"document_id": "news:alpaca:2", "title": None, "source_url": "https://x/2",
     "published_at": dt.datetime(2026, 9, 23, tzinfo=UTC),
     "text": "Apple headline\n<p>Body &amp; more</p>", "provider_sentiment": None},
]


class Recs:
    async def get(self, ticker, risk_profile):
        return dict(ROW)


class News:
    def __init__(self, articles=(), scores=(), av=None):
        self.articles, self.scores, self.av = list(articles), list(scores), av

    async def latest_articles(self, ticker, limit):
        return self.articles[:limit]

    async def marketaux_scores(self, ticker):
        return self.scores

    async def alpha_vantage_aggregate(self, ticker):
        return self.av


def detail(news):
    return asyncio.run(ResearchService(Recs(), news).get_detail("AAPL", {"risk_level": "moderate"}))


def scored(day, score):
    return {"published_at": dt.datetime(2026, 10, day, tzinfo=UTC), "score": score}


def test_detail_shows_most_recent_stored_news_with_marketaux_sentiment():
    snap = detail(News(articles=ARTICLES))
    assert [e.title for e in snap.recent_news] == ["Apple beats estimates", "Apple headline"]
    assert snap.recent_news[0].sentiment == 0.4
    assert snap.recent_news[1].snippet == "Body & more" and snap.recent_news[1].sentiment is None


def test_latest_sentiment_is_the_newer_provider_score_averaged_over_seven_days():
    snap = detail(News(scores=[scored(20, 0.4), scored(18, 0.2), scored(5, -0.9)], av=AV))
    assert snap.news_sentiment.source == "marketaux"
    assert snap.news_sentiment.article_count == 2
    assert abs(snap.news_sentiment.score - 0.3) < 1e-9
    assert snap.signal.news_signal.score is None            # display-only: the signal is unchanged
    assert snap.signal.news_aware_stance == "MONITOR"


def test_falls_back_to_alpha_vantage_until_marketaux_scores_exist():
    snap = detail(News(av=AV))
    assert snap.news_sentiment.source == "alpha_vantage" and snap.news_sentiment.score == 0.058
    assert snap.news_sentiment.as_of.date() == dt.date(2026, 10, 2)


def test_nothing_scored_shows_no_sentiment():
    assert detail(News(av={**AV, "alpha_vantage_sentiment_7d": None})).news_sentiment is None
    assert detail(News(av={**AV, "sentiment_status": "unavailable"})).news_sentiment is None
    assert detail(News()).news_sentiment is None


def test_retired_missing_news_lines_are_dropped_from_stored_traces():
    row = {**ROW, "signal_detail": {"decision_trace": [
        "Mixed signals.",
        "Sentiment is unavailable. News coverage gap means no sentiment evidence was used.",
        "News-aware check abstained to the forecast-only stance: no eligible provider news coverage.",
    ]}}

    class OldRecs:
        async def get(self, ticker, risk_profile):
            return row

    snap = asyncio.run(ResearchService(OldRecs(), News()).get_detail("AAPL", {"risk_level": "moderate"}))
    assert snap.signal.decision_trace == ["Mixed signals."]
