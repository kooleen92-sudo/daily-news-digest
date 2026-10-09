# -*- coding: utf-8 -*-
"""
Rich article text content extractor.
Fetches and extracts substantive body paragraphs for the highest-ranking articles,
giving the LLM concrete facts, quotes, and statistics rather than sparse headline summaries.
"""

from __future__ import annotations

import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from bs4 import BeautifulSoup
import requests
from collector import NewsArticle, clean_text

log = logging.getLogger("daily-news")

DEFAULT_EXTRACT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36 DailyDigestReader/1.0"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Noisy boilerplate paragraphs to discard
NOISE_PATTERNS = [
    re.compile(r"cookie|subscribe|newsletter|sign in|privacy policy|terms of service|copyright", re.I),
    re.compile(r"版权所有|免责声明|未经授权|点击阅读|下载客户端|关注我们|扫码|广告", re.I),
]


def extract_article_body(url: str, timeout: float = 6.0, max_chars: int = 800) -> str | None:
    """
    Attempt to extract core article paragraphs from a web page.
    Returns None if the page is unreachable or paywalled.
    """
    try:
        resp = requests.get(url, headers=DEFAULT_EXTRACT_HEADERS, timeout=timeout)
        if resp.status_code != 200 or len(resp.content) < 500:
            return None

        # Check content type
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "xml" not in content_type:
            return None

        soup = BeautifulSoup(resp.content.decode("utf-8", errors="ignore"), "html.parser")

        # Strip scripts, styles, iframes, nav, header, footer
        for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "svg"]):
            tag.decompose()

        # Locate core article container if possible
        container = (
            soup.find("article")
            or soup.find("main")
            or soup.find(class_=re.compile(r"article[-_]?(body|content)|story[-_]?(body|text)", re.I))
            or soup.body
        )

        if not container:
            return None

        paragraphs: list[str] = []
        for p in container.find_all("p"):
            text = clean_text(p.get_text(), 600)
            if len(text) < 25:
                continue
            if any(pattern.search(text) for pattern in NOISE_PATTERNS):
                continue
            paragraphs.append(text)
            if sum(len(x) for x in paragraphs) >= max_chars:
                break

        if not paragraphs:
            return None

        joined = "\n".join(paragraphs)
        return joined[:max_chars].strip()

    except Exception as exc:
        log.debug("正文内容提取未成功 [%s]: %s", url, exc)
        return None


def enrich_top_articles(
    articles_by_source: dict[str, list[NewsArticle]],
    top_n: int = 8,
    max_workers: int = 4
) -> int:
    """
    Identify the top N highest-scoring articles across all media sources,
    and fetch rich body snippets to expand their summary context.

    Returns:
        The number of articles successfully enriched.
    """
    # Flatten all articles
    all_articles: list[NewsArticle] = []
    for items in articles_by_source.values():
        all_articles.extend(items)

    if not all_articles:
        return 0

    # Sort by relevance score descending, filtering out unresolvable Google News redirect links
    sorted_candidates = sorted(all_articles, key=lambda a: (a.relevance_score, a.published_at), reverse=True)
    targets = [a for a in sorted_candidates if not a.url.startswith("https://news.google.com/rss")][:top_n]

    enriched_count = 0

    def _fetch_one(article: NewsArticle) -> tuple[NewsArticle, str | None]:
        body = extract_article_body(article.url)
        return article, body

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_fetch_one, art) for art in targets]
        for f in as_completed(futures):
            try:
                art, body = f.result()
                if body and len(body) > len(art.summary or ""):
                    art.summary = body
                    enriched_count += 1
                    log.debug("成功扩充核心要闻正文上下文 [%s]: %s", art.source, art.title)
            except Exception as e:
                log.debug("正文提取线程异常: %s", e)

    if enriched_count > 0:
        log.info("已为 Top %d 篇高分核心要闻成功抓取扩充事实正文，赋能大模型深度剖析。", enriched_count)

    return enriched_count
