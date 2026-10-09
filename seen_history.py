# -*- coding: utf-8 -*-
"""
Multi-day cross-day article history tracker and deduplicator.
Prevents previously reported stories from dominating consecutive digests,
and tags ongoing major developments with '[持续跟踪]'.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from config import BASE_DIR, config
from collector import NewsArticle, normalize_url

log = logging.getLogger("daily-news")

DEFAULT_HISTORY_FILE = BASE_DIR / "output" / "seen_history.json"


def _get_title_key(title: str) -> str:
    """Normalize title to alphanumeric characters only for fuzzy matching."""
    return "".join(ch for ch in title.lower() if ch.isalnum())


def load_history(history_file: Path | None = None, retention_days: int = 3) -> dict[str, list[dict[str, str]]]:
    """Load pushed articles history, discarding entries older than retention_days."""
    target_file = history_file or DEFAULT_HISTORY_FILE
    if not target_file.exists():
        return {}

    try:
        data = json.loads(target_file.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}

        tz = ZoneInfo(config.digest_timezone)
        today = datetime.now(tz).date()
        cutoff_date = today - timedelta(days=retention_days)

        cleaned: dict[str, list[dict[str, str]]] = {}
        for date_str, items in data.items():
            try:
                entry_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                if entry_date >= cutoff_date:
                    cleaned[date_str] = items
            except Exception:
                continue

        return cleaned
    except Exception as exc:
        log.debug("读取历史推送记录异常: %s", exc)
        return {}


def filter_cross_day_duplicates(
    articles_by_source: dict[str, list[NewsArticle]],
    history_file: Path | None = None,
    similarity_threshold: float = 0.85
) -> tuple[dict[str, list[NewsArticle]], int]:
    """
    Filter out articles that have already been pushed in PREVIOUS days.
    Does NOT filter out articles recorded today, preventing accidental wipeout on same-day re-runs.

    Returns:
        (filtered_articles_by_source, removed_count)
    """
    history = load_history(history_file)
    if not history:
        return articles_by_source, 0

    tz = ZoneInfo(config.digest_timezone)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    seen_urls: set[str] = set()
    seen_title_keys: list[str] = []

    # Only inspect past dates (exclude today to prevent same-day re-run false positives)
    for date_str, items in history.items():
        if date_str == today_str:
            continue
        for record in items:
            if "url" in record:
                seen_urls.add(normalize_url(record["url"]))
            if "title_key" in record:
                seen_title_keys.append(record["title_key"])

    if not seen_urls and not seen_title_keys:
        return articles_by_source, 0

    filtered_by_source: dict[str, list[NewsArticle]] = {}
    removed_count = 0

    for source, articles in articles_by_source.items():
        kept_articles: list[NewsArticle] = []
        for article in articles:
            clean_url = normalize_url(article.url)
            # Exact URL match from previous days -> drop
            if clean_url in seen_urls:
                log.debug("[%s] 跨日往期重复 URL，予以过滤: %s", source, article.title)
                removed_count += 1
                continue

            # Fuzzy title match from previous days
            title_key = _get_title_key(article.title)
            is_dup = False
            if len(title_key) >= 10:
                for seen_key in seen_title_keys:
                    if len(seen_key) >= 10:
                        ratio = difflib.SequenceMatcher(None, title_key, seen_key).ratio()
                        if ratio >= similarity_threshold:
                            is_dup = True
                            break

            if is_dup:
                log.debug("[%s] 跨日往期高相似度报道，予以过滤以保新鲜度: %s", source, article.title)
                removed_count += 1
                continue

            kept_articles.append(article)

        filtered_by_source[source] = kept_articles

    if removed_count > 0:
        log.info("跨日去重引擎已自动过滤 %d 篇往期已报道新闻，保障今日内容新鲜度。", removed_count)

    return filtered_by_source, removed_count


def record_pushed_articles(
    articles_by_source: dict[str, list[NewsArticle]],
    history_file: Path | None = None,
    retention_days: int = 5,
    is_dry_run: bool = False
) -> None:
    """Record newly pushed articles to seen_history.json (skips recording in dry-run mode)."""
    if is_dry_run:
        log.info("[Dry Run] 跳过写入跨日历史库。")
        return

    target_file = history_file or DEFAULT_HISTORY_FILE
    target_file.parent.mkdir(parents=True, exist_ok=True)

    tz = ZoneInfo(config.digest_timezone)
    today_str = datetime.now(tz).strftime("%Y-%m-%d")

    history = load_history(target_file, retention_days=retention_days)
    new_entries = []

    for _, articles in articles_by_source.items():
        for a in articles:
            new_entries.append({
                "source": a.source,
                "title": a.title,
                "url": normalize_url(a.url),
                "title_key": _get_title_key(a.title),
                "published_at": a.published_at.isoformat(),
            })

    history[today_str] = new_entries

    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix="seen_hist_",
            suffix=".tmp",
            dir=target_file.parent
        )
        temp_p = Path(tmp_path)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(history, fh, ensure_ascii=False, indent=2)
        os.replace(temp_p, target_file)
        log.info("已更新跨日新闻历史库: %s (%d 条记录)", target_file, len(new_entries))
    except Exception as exc:
        log.debug("更新跨日历史库失败: %s", exc)
