# -*- coding: utf-8 -*-
"""Unit tests for collector, URL normalization, and keyword filtering."""

from datetime import datetime, timezone
from collector import (
    normalize_url,
    _contains_keyword,
    is_relevant_china_or_finance,
    deduplicate_articles,
    NewsArticle,
)


def test_normalize_url_strips_tracking_params():
    url = "https://www.bloomberg.com/news/articles/2026-10-05/fed-rate?utm_source=twitter&utm_medium=social&spm=123"
    cleaned = normalize_url(url)
    assert cleaned == "https://www.bloomberg.com/news/articles/2026-10-05/fed-rate"
    assert "utm_source" not in cleaned
    assert "spm" not in cleaned


def test_keyword_matching_avoids_false_positives():
    # 'rain forecast' should NOT match 'ai'
    assert not _contains_keyword("rain forecast for tomorrow", "ai")
    
    # 'first-rate' or 'crime rate' should NOT match finance
    assert not is_relevant_china_or_finance("First-rate London hospital opens new ward", "Hospital service rating is excellent")
    assert not is_relevant_china_or_finance("City crime rate drops sharply", "Local police reports lower rates of crime")

    # Genuine financial terms MUST match
    assert is_relevant_china_or_finance("Fed announces interest rate decision", "Central bank cuts benchmark rates")
    assert is_relevant_china_or_finance("PBOC injects liquidity into interbank market", "Chinese central bank issues statement")
    assert is_relevant_china_or_finance("Nvidia announces new AI chip for data centers", "Semiconductor stock rallies")


def test_deduplicate_articles():
    now = datetime.now(timezone.utc)
    a1 = NewsArticle(
        source="Bloomberg",
        title="China Economy Expands in Third Quarter",
        url="https://bloomberg.com/article1?utm_source=rss",
        summary="Growth details",
        published_at=now,
    )
    # Duplicate by URL (after normalization)
    a2 = NewsArticle(
        source="Bloomberg",
        title="China Economy Expands in Third Quarter",
        url="https://bloomberg.com/article1",
        summary="Different summary",
        published_at=now,
    )
    # Different article
    a3 = NewsArticle(
        source="Reuters",
        title="Federal Reserve Holds Policy Rates Steady",
        url="https://reuters.com/fed",
        summary="Fed news",
        published_at=now,
    )
    deduped = deduplicate_articles([a1, a2, a3])
    assert len(deduped) == 2
    titles = [a.title for a in deduped]
    assert "China Economy Expands in Third Quarter" in titles
    assert "Federal Reserve Holds Policy Rates Steady" in titles
