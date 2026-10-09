# -*- coding: utf-8 -*-
"""Unit tests for multi-day cross-day article deduplication and history tracking."""

import json
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from config import config
from collector import NewsArticle
from seen_history import filter_cross_day_duplicates, record_pushed_articles, load_history


def test_filter_cross_day_duplicates(tmp_path):
    history_file = tmp_path / "seen_history.json"
    now = datetime.now(timezone.utc)
    tz = ZoneInfo(config.digest_timezone)
    yesterday_str = (datetime.now(tz) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Yesterday pushed article
    history_file.write_text(json.dumps({
        yesterday_str: [{
            "source": "彭博社",
            "title": "China Economy Expands in Third Quarter",
            "url": "https://bloomberg.com/china-growth",
            "title_key": "chinaeconomyexpandsinthirdquarter",
            "published_at": now.isoformat()
        }]
    }), encoding="utf-8")

    # Today's articles: one old, one brand new
    today_articles = {
        "彭博社": [
            NewsArticle(
                source="彭博社",
                title="China Economy Expands in Third Quarter",
                url="https://bloomberg.com/china-growth",
                summary="Same story",
                published_at=now,
            ),
            NewsArticle(
                source="彭博社",
                title="PBOC Injects Liquidity via Reverse Repos",
                url="https://bloomberg.com/pboc-repo",
                summary="New monetary action",
                published_at=now,
            ),
        ]
    }

    filtered, removed_count = filter_cross_day_duplicates(today_articles, history_file=history_file)
    assert removed_count == 1
    assert len(filtered["彭博社"]) == 1
    assert filtered["彭博社"][0].title == "PBOC Injects Liquidity via Reverse Repos"


def test_same_day_rerun_does_not_filter(tmp_path):
    history_file = tmp_path / "seen_history.json"
    now = datetime.now(timezone.utc)
    tz = ZoneInfo(config.digest_timezone)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    # Pushed earlier today
    history_file.write_text(json.dumps({
        today_str: [{
            "source": "彭博社",
            "title": "Today Fresh Story",
            "url": "https://bloomberg.com/today-story",
            "title_key": "todayfreshstory",
            "published_at": now.isoformat()
        }]
    }), encoding="utf-8")

    today_articles = {
        "彭博社": [
            NewsArticle(
                source="彭博社",
                title="Today Fresh Story",
                url="https://bloomberg.com/today-story",
                summary="Today fresh story",
                published_at=now,
            ),
        ]
    }

    # Should NOT filter out today's story on same-day re-runs
    filtered, removed_count = filter_cross_day_duplicates(today_articles, history_file=history_file)
    assert removed_count == 0
    assert len(filtered["彭博社"]) == 1


def test_dry_run_does_not_write_history(tmp_path):
    history_file = tmp_path / "seen_history.json"
    now = datetime.now(timezone.utc)
    article = NewsArticle(source="彭博社", title="Test", url="https://a.com", summary="S", published_at=now)

    record_pushed_articles({"彭博社": [article]}, history_file=history_file, is_dry_run=True)
    assert not history_file.exists()
