# -*- coding: utf-8 -*-
"""
News collector for the 7 targeted media outlets:
1. 彭博社 (Bloomberg)
2. 路透社 (Reuters)
3. 华尔街日报 (The Wall Street Journal / WSJ)
4. 金融时报 (Financial Times / FT)
5. 联合早报 (Lianhe Zaobao)
6. 日经中文网 (Nikkei Chinese / Nikkei Asia)
7. 经济学人 (The Economist)

Focusing on:
- Financial & Macroeconomic news (财经消息)
- Mainland China news & policies (关于中国大陆的消息)
"""

from __future__ import annotations

import calendar
import difflib
import html
import logging
import re
import urllib.parse
import urllib.request
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, List, Set, Tuple
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import feedparser

log = logging.getLogger("daily-news")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 DailyNewsDigest/1.0"
)

# SSL context that allows standard requests
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


@dataclass
class NewsArticle:
    source: str          # 媒体名称，如 "彭博社"、"路透社"、"华尔街日报"、"金融时报"、"联合早报"
    title: str           # 新闻标题
    url: str             # 原文链接
    summary: str         # 摘要或导语
    published_at: datetime  # UTC 时间
    category: str = "财经/中国"  # 分类标签
    language: str = "zh"    # zh or en


def clean_text(raw_text: str, max_length: int = 1000) -> str:
    """Strip HTML tags and normalize whitespace."""
    if not raw_text:
        return ""
    soup = BeautifulSoup(raw_text, "html.parser")
    text = soup.get_text(separator=" ")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


def http_get(url: str, timeout: float = 12.0, extra_headers: dict[str, str] | None = None) -> bytes:
    """Send HTTP GET request with standard browser headers."""
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/rss+xml,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as response:
        return response.read()


def parse_feed_datetime(entry: Any) -> datetime:
    """Extract entry publish time in UTC."""
    for field_name in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field_name)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return datetime.now(timezone.utc)


def is_relevant_china_or_finance(title: str, summary: str) -> bool:
    """
    Check if the article pertains to Finance / Economy OR China mainland.
    For targeted feeds (like Bloomberg Markets or WSJ Markets), most are finance,
    but we filter out pure lifestyle/sports/entertainment if any.
    """
    text = (title + " " + summary).lower()
    
    # Financial keywords
    finance_keywords = [
        "market", "stock", "bond", "yield", "rate", "fed", "central bank", "inflation",
        "economy", "economic", "gdp", "trade", "dollar", "yuan", "cnh", "oil", "gold",
        "bank", "invest", "ai", "chip", "semiconductor", "earnings", "tariff", "debt",
        "财经", "经济", "股市", "股票", "债券", "收益率", "央行", "通胀", "降息", "加息",
        "外汇", "汇率", "人民币", "美元", "黄金", "原油", "银行", "投资", "芯片", "半导体",
        "财报", "关税", "贸易", "债务", "资产", "消费", "出口", "房地产", "楼市"
    ]
    
    # China keywords
    china_keywords = [
        "china", "chinese", "beijing", "shanghai", "pboc", "xi jinping", "taiwan",
        "hong kong", "yuan", "cnh", "csi 300", "hang seng", "bilibili", "tencent",
        "alibaba", "byd", "deepseek", "huawei", "smic",
        "中国", "大陆", "北京", "上海", "央行", "习", "台海", "香港", "恒生",
        "离岸", "中概", "阿里巴巴", "腾讯", "比亚迪", "华为", "中芯"
    ]
    
    for kw in china_keywords:
        if kw in text:
            return True
            
    for kw in finance_keywords:
        if kw in text:
            return True

    return False


def fetch_rss_feed(
    source_name: str,
    url: str,
    lookback_hours: int = 24,
    max_items: int = 10,
    force_relevant: bool = False
) -> list[NewsArticle]:
    """Fetch and parse standard RSS feed."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    articles: list[NewsArticle] = []
    
    try:
        content = http_get(url)
        parsed = feedparser.parse(content)
        for entry in parsed.entries:
            title = clean_text(entry.get("title", ""), 250)
            # Remove publisher suffix from Google News RSS titles
            title = re.sub(
                r"\s*[-–|]\s*(日经中文网|The Economist|Bloomberg|Reuters|WSJ|Financial Times|联合早报).*$",
                "",
                title,
                flags=re.IGNORECASE
            ).strip()
            link = str(entry.get("link", "")).strip()
            summary = clean_text(entry.get("summary") or entry.get("description") or "", 800)
            
            if not title or not link:
                continue
                
            pub_date = parse_feed_datetime(entry)
            # If pub_date is older than cutoff, skip (allow slight clock skew)
            if pub_date < (cutoff - timedelta(hours=2)):
                continue
                
            if force_relevant and not is_relevant_china_or_finance(title, summary):
                continue
                
            articles.append(NewsArticle(
                source=source_name,
                title=title,
                url=link,
                summary=summary,
                published_at=pub_date,
                category="财经/中国",
                language="zh" if any("\u4e00" <= ch <= "\u9fff" for ch in title) else "en"
            ))
            
            if len(articles) >= max_items:
                break
                
    except Exception as exc:
        log.warning("Failed to fetch RSS [%s] from %s: %s", source_name, url, exc)
        raise exc

    return articles


def fetch_zaobao_direct(lookback_hours: int = 24, max_items: int = 10) -> list[NewsArticle]:
    """Scrape latest China & Finance news directly from Lianhe Zaobao (zaobao.com.sg)."""
    articles: list[NewsArticle] = []
    seen_links: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    
    sections = [
        ("https://www.zaobao.com.sg/news/china", "联合早报·中国"),
        ("https://www.zaobao.com.sg/finance/china", "联合早报·财经"),
    ]
    
    for section_url, section_name in sections:
        try:
            html_bytes = http_get(section_url)
            soup = BeautifulSoup(html_bytes.decode("utf-8", errors="ignore"), "html.parser")
            
            # Find story links like /news/china/story20260929-9756572
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not re.search(r"/(news/china|finance)/story\d+-\d+", href):
                    continue
                    
                full_url = urllib.parse.urljoin("https://www.zaobao.com.sg", href)
                if full_url in seen_links:
                    continue
                    
                title = clean_text(a.get_text(strip=True), 200)
                if len(title) < 6:
                    continue
                    
                seen_links.add(full_url)
                
                # Extract date from URL slug if available (e.g. story20260929-...)
                date_match = re.search(r"story(\d{4})(\d{2})(\d{2})-", href)
                if date_match:
                    year, month, day = map(int, date_match.groups())
                    pub_date = datetime(year, month, day, 4, 0, tzinfo=timezone.utc)  # estimated
                else:
                    pub_date = datetime.now(timezone.utc)
                    
                # We can fetch snippet from parent card text if available
                card_text = ""
                parent = a.find_parent(["div", "article", "li"])
                if parent:
                    card_text = clean_text(parent.get_text(), 400)
                    if title in card_text:
                        card_text = card_text.replace(title, "").strip()
                
                summary = card_text if card_text else title
                
                articles.append(NewsArticle(
                    source="联合早报",
                    title=title,
                    url=full_url,
                    summary=summary,
                    published_at=pub_date,
                    category="联合早报·中国与财经",
                    language="zh"
                ))
                
                if len(articles) >= max_items:
                    break
        except Exception as e:
            log.warning("Zaobao direct scrape failed for %s: %s", section_url, e)
            
    return articles


def deduplicate_articles(articles: list[NewsArticle], similarity_threshold: float = 0.85) -> list[NewsArticle]:
    """
    Deduplicate articles by exact URL, exact title, and near-duplicate title.
    Preserves unique content across sources.
    """
    unique_articles: list[NewsArticle] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    
    for item in sorted(articles, key=lambda a: a.published_at, reverse=True):
        clean_url = item.url.strip().lower()
        if clean_url in seen_urls:
            continue
            
        # Clean title key (alphanumeric only)
        title_key = "".join(ch for ch in item.title.lower() if ch.isalnum())
        if not title_key:
            continue
            
        # Compare with seen titles
        is_dup = False
        for seen in seen_titles:
            if len(title_key) >= 10 and len(seen) >= 10:
                matcher = difflib.SequenceMatcher(None, title_key, seen)
                if matcher.ratio() >= similarity_threshold:
                    # check opcodes: if replace exists, consider different
                    if all(tag != "replace" for tag, *_ in matcher.get_opcodes()):
                        is_dup = True
                        break
                        
        if is_dup:
            continue
            
        seen_urls.add(clean_url)
        seen_titles.append(title_key)
        unique_articles.append(item)
        
    return unique_articles


def collect_all_sources(lookback_hours: int = 24, max_per_source: int = 6) -> tuple[dict[str, list[NewsArticle]], list[str]]:
    """
    Collect news from all 7 media outlets:
    - 彭博社 (Bloomberg)
    - 路透社 (Reuters)
    - 华尔街日报 (Wall Street Journal / WSJ)
    - 金融时报 (Financial Times / FT)
    - 联合早报 (Lianhe Zaobao)
    - 日经中文网 (Nikkei Chinese / Nikkei Asia)
    - 经济学人 (The Economist)

    Returns:
        (results_by_source, error_messages)
    """
    results: dict[str, list[NewsArticle]] = {
        "彭博社": [],
        "路透社": [],
        "华尔街日报": [],
        "金融时报": [],
        "联合早报": [],
        "日经中文网": [],
        "经济学人": [],
    }
    errors: list[str] = []

    # 1. 彭博社 (Bloomberg)
    bloomberg_items = []
    # Primary: Bloomberg Markets RSS
    try:
        bbg_rss = fetch_rss_feed(
            "彭博社",
            "https://feeds.bloomberg.com/markets/news.rss",
            lookback_hours=lookback_hours,
            max_items=max_per_source
        )
        bloomberg_items.extend(bbg_rss)
    except Exception as e:
        log.warning("Bloomberg official RSS error: %s", e)

    # Secondary: Bloomberg China & Economy via Google News RSS
    try:
        bbg_china = fetch_rss_feed(
            "彭博社",
            "https://news.google.com/rss/search?q=site:bloomberg.com+(China+OR+Yuan+OR+CSI300+OR+PBOC+OR+Economy)&hl=en-US&gl=US&ceid=US:en",
            lookback_hours=lookback_hours,
            max_items=max_per_source,
            force_relevant=True
        )
        bloomberg_items.extend(bbg_china)
    except Exception as e:
        log.warning("Bloomberg China GNews RSS error: %s", e)

    if bloomberg_items:
        results["彭博社"] = deduplicate_articles(bloomberg_items)[:max_per_source]
    else:
        errors.append("彭博社：未能成功拉取更新")

    # 2. 路透社 (Reuters)
    reuters_items = []
    try:
        # Reuters China & Economy
        rt_china = fetch_rss_feed(
            "路透社",
            "https://news.google.com/rss/search?q=site:reuters.com+(China+OR+economy+OR+markets+OR+yuan)&hl=en-US&gl=US&ceid=US:en",
            lookback_hours=lookback_hours,
            max_items=max_per_source,
            force_relevant=True
        )
        reuters_items.extend(rt_china)
    except Exception as e:
        log.warning("Reuters China RSS error: %s", e)

    try:
        # Reuters Business
        rt_biz = fetch_rss_feed(
            "路透社",
            "https://news.google.com/rss/search?q=site:reuters.com+(business+OR+markets)&hl=en-US&gl=US&ceid=US:en",
            lookback_hours=lookback_hours,
            max_items=max_per_source,
            force_relevant=True
        )
        reuters_items.extend(rt_biz)
    except Exception as e:
        log.warning("Reuters Business RSS error: %s", e)

    if reuters_items:
        results["路透社"] = deduplicate_articles(reuters_items)[:max_per_source]
    else:
        errors.append("路透社：未能成功拉取更新")

    # 3. 华尔街日报 (Wall Street Journal / WSJ)
    wsj_items = []
    try:
        wsj_mkt = fetch_rss_feed(
            "华尔街日报",
            "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
            lookback_hours=lookback_hours,
            max_items=max_per_source
        )
        wsj_items.extend(wsj_mkt)
    except Exception as e:
        log.warning("WSJ Markets RSS error: %s", e)

    try:
        wsj_china = fetch_rss_feed(
            "华尔街日报",
            "https://news.google.com/rss/search?q=site:wsj.com+(China+OR+Trade+OR+Yuan)&hl=en-US&gl=US&ceid=US:en",
            lookback_hours=lookback_hours,
            max_items=max_per_source,
            force_relevant=True
        )
        wsj_items.extend(wsj_china)
    except Exception as e:
        log.warning("WSJ China GNews error: %s", e)

    if wsj_items:
        results["华尔街日报"] = deduplicate_articles(wsj_items)[:max_per_source]
    else:
        errors.append("华尔街日报：未能成功拉取更新")

    # 4. 金融时报 (Financial Times / FT)
    ft_items = []
    try:
        # FT Chinese RSS (Official Chinese feed)
        ftc = fetch_rss_feed(
            "金融时报",
            "https://www.ftchinese.com/rss/feed",
            lookback_hours=lookback_hours,
            max_items=max_per_source
        )
        ft_items.extend(ftc)
    except Exception as e:
        log.warning("FT Chinese RSS error: %s", e)

    try:
        # FT Markets Global RSS
        ft_mkt = fetch_rss_feed(
            "金融时报",
            "https://www.ft.com/rss/markets",
            lookback_hours=lookback_hours,
            max_items=max_per_source
        )
        ft_items.extend(ft_mkt)
    except Exception as e:
        log.warning("FT Markets RSS error: %s", e)

    if ft_items:
        results["金融时报"] = deduplicate_articles(ft_items)[:max_per_source]
    else:
        errors.append("金融时报：未能成功拉取更新")

    # 5. 联合早报 (Lianhe Zaobao)
    zaobao_items = []
    # Primary: Direct web scrape from zaobao.com.sg
    try:
        zb_direct = fetch_zaobao_direct(lookback_hours=lookback_hours, max_items=max_per_source)
        zaobao_items.extend(zb_direct)
    except Exception as e:
        log.warning("Zaobao direct scrape error: %s", e)

    # Secondary / Backup: Google News RSS for Zaobao
    if len(zaobao_items) < max_per_source:
        try:
            zb_gnews = fetch_rss_feed(
                "联合早报",
                "https://news.google.com/rss/search?q=site:zaobao.com.sg+(%E4%B8%AD%E5%9B%BD+OR+%E8%B4%A2%E7%BB%8F)&hl=zh-CN&gl=SG&ceid=SG:zh-Hans",
                lookback_hours=lookback_hours,
                max_items=max_per_source,
                force_relevant=True
            )
            zaobao_items.extend(zb_gnews)
        except Exception as e:
            log.warning("Zaobao GNews RSS error: %s", e)

    if zaobao_items:
        results["联合早报"] = deduplicate_articles(zaobao_items)[:max_per_source]
    else:
        errors.append("联合早报：未能成功拉取更新")

    # 6. 日经中文网 (Nikkei Chinese / Nikkei Asia)
    nikkei_items = []
    # 针对节假日/周末及深度专栏，动态放宽回溯窗口至 48 小时，确保稳定拉取
    nikkei_lookback = max(lookback_hours, 48)
    try:
        nikkei_target = fetch_rss_feed(
            "日经中文网",
            "https://news.google.com/rss/search?q=site:cn.nikkei.com+(%E4%B8%AD%E5%9B%BD+OR+%E7%BB%8F%E6%B5%8E+OR+%E5%8D%8A%E5%AF%BC%E4%BD%93+OR+%E6%97%A5%E5%85%83+OR+%E5%B8%82%E5%9C%BA+OR+%E4%BA%A7%E4%B8%9A)&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            lookback_hours=nikkei_lookback,
            max_items=max_per_source,
            force_relevant=False,
        )
        nikkei_items.extend(nikkei_target)
    except Exception as e:
        log.warning("Nikkei targeted GNews RSS error: %s", e)

    if len(nikkei_items) < max_per_source:
        try:
            nikkei_gen = fetch_rss_feed(
                "日经中文网",
                "https://news.google.com/rss/search?q=site:cn.nikkei.com&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
                lookback_hours=nikkei_lookback,
                max_items=max_per_source,
                force_relevant=True,
            )
            nikkei_items.extend(nikkei_gen)
        except Exception as e:
            log.warning("Nikkei general GNews RSS error: %s", e)

    if nikkei_items:
        results["日经中文网"] = deduplicate_articles(nikkei_items)[:max_per_source]
    else:
        errors.append("日经中文网：未能成功拉取更新")

    # 7. 经济学人 (The Economist)
    economist_items = []
    # 经济学人以长周期、深度宏观分析为主，适当放宽回溯时间窗口以锁定高含金量专栏
    econ_lookback = max(lookback_hours, 48)

    # 7.1 官方财经与宏观专栏 RSS
    try:
        econ_fin = fetch_rss_feed(
            "经济学人",
            "https://www.economist.com/finance-and-economics/rss.xml",
            lookback_hours=econ_lookback,
            max_items=max_per_source,
            force_relevant=False,
        )
        economist_items.extend(econ_fin)
    except Exception as e:
        log.warning("The Economist Finance RSS error: %s", e)

    # 7.2 官方中国专栏 RSS
    try:
        econ_china = fetch_rss_feed(
            "经济学人",
            "https://www.economist.com/china/rss.xml",
            lookback_hours=econ_lookback,
            max_items=max_per_source,
            force_relevant=False,
        )
        economist_items.extend(econ_china)
    except Exception as e:
        log.warning("The Economist China RSS error: %s", e)

    # 7.3 Google News 宏观与中国补充流
    if len(economist_items) < max_per_source:
        try:
            econ_gnews = fetch_rss_feed(
                "经济学人",
                "https://news.google.com/rss/search?q=site:economist.com+(China+OR+economy+OR+markets+OR+finance+OR+Fed)&hl=en-US&gl=US&ceid=US:en",
                lookback_hours=econ_lookback,
                max_items=max_per_source,
                force_relevant=True,
            )
            economist_items.extend(econ_gnews)
        except Exception as e:
            log.warning("The Economist GNews RSS error: %s", e)

    if economist_items:
        results["经济学人"] = deduplicate_articles(economist_items)[:max_per_source]
    else:
        errors.append("经济学人：未能成功拉取更新")

    return results, errors
