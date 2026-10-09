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


def test_source_feed_specs_coverage():
    from collector import SOURCE_FEED_SPECS
    expected_sources = ["彭博社", "路透社", "华尔街日报", "金融时报", "联合早报", "日经中文网", "经济学人"]
    for src in expected_sources:
        assert src in SOURCE_FEED_SPECS, f"Source {src} must be configured in SOURCE_FEED_SPECS"
        assert len(SOURCE_FEED_SPECS[src]) >= 1, f"Source {src} must have at least 1 feed spec"


def test_deduplicate_articles_fuzzy_and_antonym():
    from collector import deduplicate_articles
    now = datetime.now(timezone.utc)

    # 1. Near duplicate should be deduplicated
    a1 = NewsArticle("彭博社", "中国央行今日开展5000亿元买断式逆回购操作", "https://example.com/1", "", now, relevance_score=10.0)
    a2 = NewsArticle("路透社", "中国央行开展5000亿元买断式逆回购操作", "https://example.com/2", "", now, relevance_score=8.0)
    deduped = deduplicate_articles([a1, a2], similarity_threshold=0.85)
    assert len(deduped) == 1
    assert deduped[0].url == "https://example.com/1"

    # 2. Antonym polarity titles should NOT be deduplicated even with high similarity
    a3 = NewsArticle("彭博社", "中国8月工业增加值同比上涨5.3% 超出预期", "https://example.com/3", "", now, relevance_score=10.0)
    a4 = NewsArticle("路透社", "中国8月工业增加值同比下跌5.3% 超出预期", "https://example.com/4", "", now, relevance_score=9.0)
    deduped_opp = deduplicate_articles([a3, a4], similarity_threshold=0.85)
    assert len(deduped_opp) == 2


def test_extract_google_news_article_id():
    from collector import _extract_google_news_article_id

    assert _extract_google_news_article_id("https://news.google.com/rss/articles/CBMiABC?hl=zh-CN&gl=CN") == "CBMiABC"
    assert _extract_google_news_article_id("https://news.google.com/rss/articles/CBMiXYZ") == "CBMiXYZ"
    assert _extract_google_news_article_id("https://www.reuters.com/world/example") is None
    assert _extract_google_news_article_id("") is None


def test_parse_google_news_page():
    from collector import _parse_google_news_page

    html_fragment = '<c-wiz><div data-n-a-sg="SIG123" data-n-a-ts="1712345678">x</div></c-wiz>'
    assert _parse_google_news_page(html_fragment) == ("SIG123", "1712345678")
    assert _parse_google_news_page("<html></html>") == (None, None)
    assert _parse_google_news_page("") == (None, None)


def test_decode_google_news_response():
    from collector import _decode_google_news_response

    sample = (
        ")]}'\n\n"
        '[["wrb.fr","Fbv4je","[[\\"garturlres\\",\\"https://www.reuters.com/world/example\\",null,1]]",null,null,null,"generic"]]'
    )
    assert _decode_google_news_response(sample) == "https://www.reuters.com/world/example"
    assert _decode_google_news_response("garbage without marker") is None
    assert _decode_google_news_response("") is None


def test_resolve_google_news_url_success(monkeypatch):
    import collector

    page_html = '<c-wiz><div data-n-a-sg="SIG123" data-n-a-ts="1712345678"></div></c-wiz>'
    api_text = (
        ")]}'\n\n"
        '[["wrb.fr","Fbv4je","[[\\"garturlres\\",\\"https://www.bloomberg.com/news/articles/x\\"]]",null,null,null,"generic"]]'
    )

    class _Resp:
        def __init__(self, text):
            self.text = text
            self.status_code = 200

    monkeypatch.setattr(collector._SESSION, "get", lambda *args, **kwargs: _Resp(page_html))
    monkeypatch.setattr(collector._SESSION, "post", lambda *args, **kwargs: _Resp(api_text))

    resolved = collector.resolve_google_news_url("https://news.google.com/rss/articles/CBMiABC?hl=zh-CN")
    assert resolved == "https://www.bloomberg.com/news/articles/x"


def test_resolve_google_news_url_fail_safe(monkeypatch):
    import collector

    def raising_get(*args, **kwargs):
        raise RuntimeError("network down")

    monkeypatch.setattr(collector._SESSION, "get", raising_get)
    assert collector.resolve_google_news_url("https://news.google.com/rss/articles/CBMiABC") is None
    assert collector.resolve_google_news_url("https://www.reuters.com/world/example") is None


def test_resolve_google_news_urls_replaces_in_place(monkeypatch):
    import collector
    from collector import NewsArticle

    now = datetime.now(timezone.utc)
    articles = [
        NewsArticle(source="路透社", title="t1", url="https://news.google.com/rss/articles/AAA", summary="", published_at=now),
        NewsArticle(source="路透社", title="t2", url="https://www.reuters.com/direct", summary="", published_at=now),
    ]
    monkeypatch.setattr(collector, "resolve_google_news_url", lambda url, timeout=5.0: "https://www.reuters.com/real-article")

    count = collector.resolve_google_news_urls(articles, max_workers=2, time_budget=5.0)
    assert count == 1
    assert articles[0].url == "https://www.reuters.com/real-article"
    assert articles[1].url == "https://www.reuters.com/direct"


