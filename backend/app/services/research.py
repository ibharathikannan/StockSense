from __future__ import annotations

import html
import re
from datetime import timedelta
from typing import Any

from app.repositories.news import NewsRepository
from app.repositories.recommendations import RecommendationsRepository
from app.schemas.recommendations import (
    DiscoveryResponse,
    DiversificationNote,
    Evidence,
    NewsSentiment,
    RecommendationSnapshot,
)
from app.services.discovery import diversification as compute_diversification
from app.services.discovery import interest_targets
from app.services.errors import NotFound

RECENT_NEWS_LIMIT = 3
SENTIMENT_LOOKBACK = timedelta(days=7)
SNIPPET_CHARS = 500
_TAG = re.compile(r"<[^>]+>")


def _article_evidence(row: dict[str, Any], ticker: str) -> Evidence:
    text = re.sub(r"[ \t]+", " ", html.unescape(_TAG.sub(" ", row.get("text") or ""))).strip()
    title = (row.get("title") or "").strip()
    if not title:
        # Older news chunks carry the headline as the first line of the text.
        head, _, rest = text.partition("\n")
        title, text = head.strip()[:160] or "News update", rest.strip() or text
    payload = ((row.get("provider_sentiment") or {}).get(ticker) or {})
    return Evidence(title=title, source_type="news", published_at=row.get("published_at"),
                    source_url=row.get("source_url") or None, snippet=text[:SNIPPET_CHARS],
                    sentiment=payload.get("score"))


class ResearchService:
    """Serves precomputed research snapshots (the RAG "Discover" feature) and layers on the
    request-time, per-user view: the matching discovery set and a diversification note from the
    user's followed assets. The news-aware stance is the operative signal
    (see docs/ai/OPERATIONAL_MODEL.md).

    Distinct from app.services.recommendations.RecommendationService, which is the team's
    content-based suggestion recommender that powers the dashboard.
    """

    def __init__(self, recs: RecommendationsRepository, news: NewsRepository | None = None) -> None:
        self._recs = recs
        self._news = news

    async def get_detail(self, ticker: str, profile: dict[str, Any]) -> RecommendationSnapshot:
        row = await self._recs.get(ticker, profile["risk_level"])
        if not row:
            raise NotFound(f"No recommendation available for '{ticker.strip().upper()}'.")
        snapshot = RecommendationSnapshot.from_row(row)
        if self._news is not None:
            rows = await self._news.latest_articles(snapshot.ticker, RECENT_NEWS_LIMIT)
            snapshot.recent_news = [_article_evidence(r, snapshot.ticker) for r in rows]
            snapshot.news_sentiment = await self._latest_sentiment(snapshot.ticker)
        return snapshot

    async def _latest_sentiment(self, ticker: str) -> NewsSentiment | None:
        """The newer of the Marketaux and Alpha Vantage provider scores. Local FinBERT stays
        evidence-only (docs/ai/SENTIMENT_ATTRIBUTION.md); nothing scored shows nothing."""
        candidates = []
        scores = await self._news.marketaux_scores(ticker)
        if scores:
            newest = scores[0]["published_at"]
            window = [r["score"] for r in scores if r["published_at"] > newest - SENTIMENT_LOOKBACK]
            candidates.append(NewsSentiment(score=sum(window) / len(window), source="marketaux",
                                            as_of=newest, article_count=len(window)))
        agg = await self._news.alpha_vantage_aggregate(ticker)
        if agg and agg.get("sentiment_status") == "available" \
                and agg.get("alpha_vantage_sentiment_7d") is not None:
            candidates.append(NewsSentiment(
                score=agg["alpha_vantage_sentiment_7d"], source="alpha_vantage",
                as_of=agg.get("latest_publication") or agg["as_of"],
                article_count=agg.get("articles_7d") or 0, lookback_days=agg.get("lookback_days") or 7))
        return max(candidates, key=lambda c: c.as_of) if candidates else None

    async def get_discovery(self, profile: dict[str, Any], limit: int = 20) -> DiscoveryResponse:
        sectors, themes = interest_targets(profile.get("interests") or [])
        rows = await self._recs.list_for_profile(profile["risk_level"], list(sectors),
                                                 list(themes), limit)
        candidates = [RecommendationSnapshot.from_row(r) for r in rows]

        followed = profile.get("followed_tickers") or []
        followed_sectors = await self._recs.followed_sectors(followed)
        assets_by_ticker = {t: {"ticker": t, "sector": s} for t, s in followed_sectors.items()}
        cand_dicts = [{"ticker": c.ticker, "sector": c.sector} for c in candidates]
        div = compute_diversification(assets_by_ticker, profile, cand_dicts)

        return DiscoveryResponse(candidates=candidates, diversification=DiversificationNote(**div))
