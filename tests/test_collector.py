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


def test_relevance_scoring_penalizes_entertainment_and_noise():
    from collector import calculate_relevance_score

    # Bloomberg Tubi merchandise / streaming noise should be strongly negative
    tubi_score = calculate_relevance_score(
        "Everybody's Business: Tubi's Growth Strategy Includes Edgy Merch",
        "At a time when subscriber growth is slowing for streaming giants like Netflix"
    )
    assert tubi_score < 0, f"Expected negative score for Tubi entertainment news, got {tubi_score}"
    assert not is_relevant_china_or_finance(
        "Everybody's Business: Tubi's Growth Strategy Includes Edgy Merch",
        "At a time when subscriber growth is slowing for streaming giants like Netflix"
    )

    # Tourism festival events should be penalized
    festival_score = calculate_relevance_score(
        "Guided Tour - Chinatown Heritage Centre - SG Chinese Fun Festival 2026",
        "Explore Singapore cultural heritage during the festival"
    )
    assert festival_score < 0

    # Non-economic political essay should fail the minimum relevance threshold
    midterm_score = calculate_relevance_score(
        "特朗普在乎共和党输掉中期选举吗？",
        "美国总统似乎对共和党候选人面对中期选举失败相当淡定"
    )
    assert midterm_score < 2.0


def test_relevance_scoring_rewards_china_and_macro():
    from collector import calculate_relevance_score

    # China property mortgage rate subsidy
    china_policy_score = calculate_relevance_score(
        "中国出台房贷贴息政策",
        "中国政府要为首次购房者提供支持，并下调了一项央行放贷利率，提振经济增长"
    )
    assert china_policy_score >= 10.0

    # DeepSeek / AI tech leadership
    deepseek_score = calculate_relevance_score(
        "US Lead in AI Over China Narrows After DeepSeek Gains, BI Says",
        "Bloomberg Intelligence report highlights technological advances in China"
    )
    assert deepseek_score >= 10.0

    # Sovereign debt credit rating
    debt_score = calculate_relevance_score(
        "德国能否保住AAA最高信用评级?",
        "德国政府财政赤字翻番，主权债务与评级面临考验"
    )
    assert debt_score >= 5.0


def test_relevance_ranking_orders_articles_correctly():
    now = datetime.now(timezone.utc)
    from collector import calculate_relevance_score

    articles = [
        NewsArticle(
            source="彭博社",
            title="Everybody's Business: Tubi's Growth Strategy Includes Edgy Merch",
            url="https://bloomberg.com/tubi",
            summary="Streaming service merchandise",
            published_at=now,
            relevance_score=calculate_relevance_score(
                "Everybody's Business: Tubi's Growth Strategy Includes Edgy Merch",
                "Streaming service merchandise"
            )
        ),
        NewsArticle(
            source="彭博社",
            title="US Lead in AI Over China Narrows After DeepSeek Gains",
            url="https://bloomberg.com/deepseek",
            summary="China AI advances and chip rivalry",
            published_at=now,
            relevance_score=calculate_relevance_score(
                "US Lead in AI Over China Narrows After DeepSeek Gains",
                "China AI advances and chip rivalry"
            )
        ),
        NewsArticle(
            source="彭博社",
            title="Stocks Rise as Oil Drop Offsets Europe Debt Worry",
            url="https://bloomberg.com/stocks",
            summary="Wall Street equities rally as crude oil drops",
            published_at=now,
            relevance_score=calculate_relevance_score(
                "Stocks Rise as Oil Drop Offsets Europe Debt Worry",
                "Wall Street equities rally as crude oil drops"
            )
        )
    ]

    # Filter out score < 2.0 and sort by relevance score descending
    valid_articles = [a for a in articles if a.relevance_score >= 2.0]
    valid_articles.sort(key=lambda a: a.relevance_score, reverse=True)

    assert len(valid_articles) == 2
    assert valid_articles[0].title == "US Lead in AI Over China Narrows After DeepSeek Gains"
    assert valid_articles[1].title == "Stocks Rise as Oil Drop Offsets Europe Debt Worry"
