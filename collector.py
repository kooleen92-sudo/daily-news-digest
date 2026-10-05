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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, List, Set, Tuple
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from config import config

log = logging.getLogger("daily-news")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 DailyNewsDigest/1.0"
)

# Global requests Session with pooling and exponential backoff
_SESSION = requests.Session()
_RETRY_STRATEGY = Retry(
    total=2,
    backoff_factor=0.5,
    status_forcelist=[500, 502, 503, 504],
    raise_on_status=False
)
_ADAPTER = HTTPAdapter(max_retries=_RETRY_STRATEGY, pool_connections=10, pool_maxsize=20)
_SESSION.mount("https://", _ADAPTER)
_SESSION.mount("http://", _ADAPTER)


@dataclass
class NewsArticle:
    source: str          # 媒体名称，如 "彭博社"、"路透社"、"华尔街日报"、"金融时报"、"联合早报"
    title: str           # 新闻标题
    url: str             # 原文链接
    summary: str         # 摘要或导语
    published_at: datetime  # UTC 时间
    category: str = "财经/中国"  # 分类标签
    language: str = "zh"    # zh or en
    relevance_score: float = 0.0  # 主题契合度得分（宏观财经与中国核心要闻）


def clean_text(raw_text: str, max_length: int = 1000) -> str:
    """Strip HTML tags and normalize whitespace."""
    if not raw_text:
        return ""
    soup = BeautifulSoup(raw_text, "html.parser")
    text = soup.get_text(separator=" ")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


def normalize_url(raw_url: str) -> str:
    """Strip tracking query parameters (UTM, spm, ref, etc.) for accurate deduplication."""
    if not raw_url:
        return ""
    try:
        parsed = urllib.parse.urlparse(raw_url.strip())
        filtered_queries = [
            (k, v) for k, v in urllib.parse.parse_qsl(parsed.query)
            if not (k.startswith("utm_") or k in {"spm", "from", "ref", "source", "feature", "ocid", "ved"})
        ]
        new_query = urllib.parse.urlencode(filtered_queries)
        return urllib.parse.urlunparse(parsed._replace(query=new_query, fragment="")).strip()
    except Exception:
        return raw_url.strip()


def http_get(url: str, timeout: float | None = None, extra_headers: dict[str, str] | None = None) -> bytes:
    """Send HTTP GET request with connection pool, automatic retries and standard headers."""
    timeout = config.fetch_timeout if timeout is None else timeout
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/rss+xml,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if extra_headers:
        headers.update(extra_headers)

    resp = _SESSION.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def parse_feed_datetime(entry: Any) -> datetime | None:
    """Extract entry publish time in UTC, or None when unavailable."""
    for field_name in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field_name)
        if parsed:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def _contains_keyword(text: str, keyword: str) -> bool:
    """Match Chinese phrases or complete English words, avoiding substring noise."""
    if any("\u4e00" <= ch <= "\u9fff" for ch in keyword):
        return keyword in text
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


# ---------------------------------------------------------------------------
# Whitelist, Blacklist & Multi-tiered Relevance Scoring Engine
# ---------------------------------------------------------------------------

# Negative / Noise keywords that should be penalized or eliminated
# Entertainment, pop music, movies, celebrities, TV streaming, sports tournaments, local crime/accidents
NEGATIVE_KEYWORDS = [
    # English entertainment & pop culture
    "tubi", "streaming service", "netflix", "hulu", "disney+", "box office", "hollywood",
    "celebrity", "celebrities", "pop star", "oscar", "oscars", "emmy", "grammy", "grammys",
    "actor", "actress", "film festival", "album release", "concert tour", "ticketmaster",
    "super bowl", "nba", "nfl", "premier league", "champions league", "fifa", "formula 1",
    "poker", "dating app", "tinder", "reality tv", "broadway", "met gala", "disneyland",
    "theme park", "sports betting", "esports", "video game", "gaming console",
    "guided tour", "fun festival", "funfest", "heritage centre", "tourist",
    # English crime / local human interest noise
    "stabbing", "murder trial", "kidnapping", "serial killer", "manslaughter",
    # Chinese entertainment & pop culture
    "娱乐", "八卦", "明星", "票房", "影院", "好莱坞", "演唱会", "奥斯卡", "金球奖",
    "体坛", "英超", "欧冠", "世界杯", "足球赛", "篮球赛", "网球公开赛", "时尚周",
    "时装秀", "真人秀", "脱口秀", "红毯", "迪士尼", "环球影城", "选秀", "追星",
    "导览", "欢乐节", "旅游节", "观光", "游园会",
    # Chinese crime / local accidents
    "持刀伤人", "凶杀案", "绑架案", "车祸身亡", "入室抢劫"
]

# Tier 1: Mainland China Economy, Policy, Geopolitics & Tech Champions (Title: +6.0, Summary: +2.5)
TIER1_CHINA_KEYWORDS = [
    # Core institutions & leaders
    "china", "chinese", "beijing", "shanghai", "pboc", "xi jinping", "state council",
    "ndrc", "ministry of finance", "ministry of commerce", "miit", "taiwan strait", "taiwan",
    "hong kong", "yuan", "cnh", "rmb", "csi 300", "hang seng", "us-china", "sino-",
    # Chinese tech & corporate champions
    "alibaba", "tencent", "byd", "deepseek", "huawei", "smic", "catl", "shein", "temu",
    "pinduoduo", "pdd", "baidu", "xiaomi", "meituan", "jd.com", "geely", "nio", "xpeng",
    # Chinese terms
    "中国", "大陆", "北京", "上海", "央行", "人民银行", "习近平", "国务院", "发改委",
    "财政部", "商务部", "工信部", "中纪委", "证监会", "银保监会", "台海",
    "两岸", "台湾", "香港", "恒生", "离岸人民币", "在岸人民币", "中概股", "a股", "沪深300",
    "科创板", "阿里巴巴", "腾讯", "比亚迪", "华为", "中芯国际", "宁德时代", "拼多多",
    "百度", "小米", "美团", "京东", "吉利", "蔚来", "小鹏", "外商投资", "外贸", "关税",
    "中方", "中美", "涉华"
]

# Tier 2: Global Macroeconomics, Monetary Policy & Sovereign Debt (Title: +4.5, Summary: +2.0)
TIER2_MACRO_KEYWORDS = [
    # Central banks & monetary policy
    "federal reserve", "fed", "ecb", "bank of japan", "boj", "bank of england",
    "central bank", "interest rate", "rate cut", "rate hike", "monetary policy",
    "quantitative easing", "quantitative tightening", "qt", "liquidity",
    # Macro metrics & crisis
    "inflation", "cpi", "ppi", "pce", "gdp", "recession", "unemployment",
    "nonfarm", "treasury yield", "bond yield", "sovereign debt", "debt ceiling",
    "fiscal deficit", "tariff", "trade war", "sanction", "de-dollarization", "debt",
    # Chinese terms
    "美联储", "欧洲央行", "日本央行", "英国央行", "中央银行", "降息", "加息", "基准利率",
    "货币政策", "量化宽松", "通胀", "通货膨胀", "通货紧缩", "cpi", "ppi", "gdp", "经济衰退",
    "失业率", "非农", "非农就业", "国债收益率", "美债", "主权债务", "债务违约", "债务",
    "财政赤字", "赤字", "贸易逆差", "关税", "贸易战", "制裁", "去美元化", "房贷利率", "贴息",
    "存款准备金率", "评级", "信用评级"
]

# Tier 3: Major Financial Markets, Strategic Commodities & Tech Supply Chains (Title: +3.0, Summary: +1.5)
TIER3_MARKET_KEYWORDS = [
    # Markets & Commodities
    "wall street", "s&p 500", "nasdaq", "dow jones", "nikkei", "ftse", "dax",
    "stock market", "bond market", "crude oil", "oil", "brent", "wti", "opec",
    "gold", "gold price", "silver", "copper", "dollar index", "dxy", "dollar", "forex", "fx",
    # Tech chips & AI infra
    "semiconductor", "chip export", "chipmaker", "asml", "tsmc", "nvidia", "ai chip", "ai",
    "gpu", "data center", "artificial intelligence", "generative ai", "large language model",
    # Chinese terms
    "华尔街", "美股", "标普500", "标普", "纳斯达克", "纳指", "道琼斯", "日经指数", "日经",
    "股市", "债市", "原油", "石油", "布伦特", "wti", "欧佩克", "opec", "黄金", "白银",
    "铜价", "大宗商品", "美元指数", "美元", "外汇", "汇率", "半导体", "芯片", "光刻机",
    "台积电", "英伟达", "算力", "数据中心", "人工智能", "大模型", "生成式ai", "ai"
]

# Tier 4: General Business, Finance & Corporate Actions (Title: +1.0, Summary: +0.5)
TIER4_BUSINESS_KEYWORDS = [
    "economy", "economic", "market", "markets", "trade", "investment", "investor", "capital",
    "earnings", "revenue", "profit", "ipo", "bank", "banking", "finance", "financial",
    "stock", "stocks", "bond", "bonds", "asset management", "hedge fund", "private equity",
    "merger", "acquisition",
    "经济", "市场", "贸易", "投资", "投资者", "资本", "财报", "营收", "利润", "净利润",
    "ipo", "上市", "挂牌", "银行", "金融", "资产管理", "对冲基金", "私募", "并购", "重组", "回购"
]


def calculate_relevance_score(title: str, summary: str, source: str = "") -> float:
    """
    Compute structured relevance score for an article.
    High scores indicate strong relevance to Macroeconomics, Financial Markets, or China Mainland.
    Negative scores indicate entertainment, sports, or local human interest noise.
    """
    t = title.lower()
    s = summary.lower()

    neg_in_title = any(_contains_keyword(t, k) for k in NEGATIVE_KEYWORDS)
    neg_in_summary = any(_contains_keyword(s, k) for k in NEGATIVE_KEYWORDS)

    score = 0.0

    # Tier 1 (China)
    for k in TIER1_CHINA_KEYWORDS:
        if _contains_keyword(t, k):
            score += 6.0
        elif _contains_keyword(s, k):
            score += 2.5

    # Tier 2 (Macroeconomics & Central Banks)
    for k in TIER2_MACRO_KEYWORDS:
        if _contains_keyword(t, k):
            score += 4.5
        elif _contains_keyword(s, k):
            score += 2.0

    # Tier 3 (Markets, Commodities, AI Infra)
    for k in TIER3_MARKET_KEYWORDS:
        if _contains_keyword(t, k):
            score += 3.0
        elif _contains_keyword(s, k):
            score += 1.5

    # Tier 4 (General Business)
    for k in TIER4_BUSINESS_KEYWORDS:
        if _contains_keyword(t, k):
            score += 1.0
        elif _contains_keyword(s, k):
            score += 0.5

    # Penalize entertainment / sports / crime noise
    if neg_in_title:
        score -= 25.0
    elif neg_in_summary:
        score -= 15.0

    return round(score, 2)


def is_relevant_china_or_finance(title: str, summary: str, min_score: float = 2.0) -> bool:
    """Check if the article satisfies the minimum relevance threshold."""
    return calculate_relevance_score(title, summary) >= min_score


def fetch_rss_feed(
    source_name: str,
    url: str,
    lookback_hours: int = 24,
    max_items: int = 20,
    force_relevant: bool = True,
    min_score: float = 2.0
) -> list[NewsArticle]:
    """Fetch and parse standard RSS feed, scoring and filtering articles by relevance."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    articles: list[NewsArticle] = []
    
    try:
        content = http_get(url, timeout=config.fetch_timeout)
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
            if pub_date is None:
                log.debug("Skipping undated RSS item from %s: %s", source_name, title)
                continue
            # If pub_date is older than cutoff, skip (allow slight clock skew)
            if pub_date < (cutoff - timedelta(hours=2)):
                continue

            score = calculate_relevance_score(title, summary, source_name)
            if force_relevant and score < min_score:
                log.debug("Skipping low relevance item [%.1f < %.1f] from %s: %s", score, min_score, source_name, title)
                continue
                
            articles.append(NewsArticle(
                source=source_name,
                title=title,
                url=link,
                summary=summary,
                published_at=pub_date,
                category="财经/中国",
                language="zh" if any("\u4e00" <= ch <= "\u9fff" for ch in title) else "en",
                relevance_score=score
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
            html_bytes = http_get(section_url, timeout=config.fetch_timeout)
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
                    pub_date = datetime(year, month, day, tzinfo=ZoneInfo("Asia/Singapore")).astimezone(timezone.utc)
                else:
                    # Do not turn an undated page card into a fresh article.
                    continue

                if pub_date < cutoff:
                    continue

                # Calculate relevance score for the article
                score = calculate_relevance_score(title, "", "联合早报")
                if score < 0.5:
                    continue
                    
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
                    language="zh",
                    relevance_score=score
                ))
                
                if len(articles) >= max_items:
                    break
        except Exception as e:
            log.warning("Zaobao direct scrape failed for %s: %s", section_url, e)
            
    return articles


def deduplicate_articles(articles: list[NewsArticle], similarity_threshold: float | None = None) -> list[NewsArticle]:
    """
    Deduplicate articles by exact URL, exact title, and near-duplicate title.
    Prioritizes higher relevance score and more recent publication date.
    """
    if similarity_threshold is None:
        similarity_threshold = config.dedupe_similarity

    unique_articles: list[NewsArticle] = []
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    
    # Sort by relevance_score descending, then published_at descending
    for item in sorted(articles, key=lambda a: (a.relevance_score, a.published_at), reverse=True):
        clean_url = normalize_url(item.url)
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

def _fetch_bloomberg(lookback_hours: int, max_per_source: int) -> list[NewsArticle]:
    items = []
    try:
        items.extend(fetch_rss_feed("彭博社", "https://feeds.bloomberg.com/markets/news.rss", lookback_hours, max_items=20, min_score=2.0))
    except Exception as e:
        log.warning("Bloomberg official RSS error: %s", e)
    try:
        items.extend(fetch_rss_feed(
            "彭博社",
            "https://news.google.com/rss/search?q=site:bloomberg.com+(China+OR+Yuan+OR+CSI300+OR+PBOC+OR+Economy)&hl=en-US&gl=US&ceid=US:en",
            lookback_hours, max_items=20, min_score=2.0
        ))
    except Exception as e:
        log.warning("Bloomberg China GNews RSS error: %s", e)
    candidates = deduplicate_articles(items)
    if not candidates:
        candidates = [item for item in deduplicate_articles(items) if item.relevance_score >= 0.5]
    candidates.sort(key=lambda a: a.relevance_score, reverse=True)
    return candidates[:max_per_source]


def _fetch_reuters(lookback_hours: int, max_per_source: int) -> list[NewsArticle]:
    items = []
    try:
        items.extend(fetch_rss_feed(
            "路透社",
            "https://news.google.com/rss/search?q=site:reuters.com+(China+OR+economy+OR+markets+OR+yuan+OR+PBOC)&hl=en-US&gl=US&ceid=US:en",
            lookback_hours, max_items=20, min_score=2.0
        ))
    except Exception as e:
        log.warning("Reuters China RSS error: %s", e)
    try:
        items.extend(fetch_rss_feed(
            "路透社",
            "https://news.google.com/rss/search?q=site:reuters.com+(Fed+OR+inflation+OR+Treasury+OR+markets+OR+tariff)&hl=en-US&gl=US&ceid=US:en",
            lookback_hours, max_items=20, min_score=2.0
        ))
    except Exception as e:
        log.warning("Reuters Business RSS error: %s", e)
    candidates = deduplicate_articles(items)
    if not candidates:
        candidates = [item for item in deduplicate_articles(items) if item.relevance_score >= 0.5]
    candidates.sort(key=lambda a: a.relevance_score, reverse=True)
    return candidates[:max_per_source]


def _fetch_wsj(lookback_hours: int, max_per_source: int) -> list[NewsArticle]:
    items = []
    try:
        items.extend(fetch_rss_feed("华尔街日报", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", lookback_hours, max_items=20, min_score=2.0))
    except Exception as e:
        log.warning("WSJ Markets RSS error: %s", e)
    try:
        items.extend(fetch_rss_feed(
            "华尔街日报",
            "https://news.google.com/rss/search?q=site:wsj.com+(China+OR+Trade+OR+Yuan+OR+PBOC+OR+Economy)&hl=en-US&gl=US&ceid=US:en",
            lookback_hours, max_items=20, min_score=2.0
        ))
    except Exception as e:
        log.warning("WSJ China GNews error: %s", e)
    candidates = deduplicate_articles(items)
    if not candidates:
        candidates = [item for item in deduplicate_articles(items) if item.relevance_score >= 0.5]
    candidates.sort(key=lambda a: a.relevance_score, reverse=True)
    return candidates[:max_per_source]


def _fetch_ft(lookback_hours: int, max_per_source: int) -> list[NewsArticle]:
    items = []
    try:
        items.extend(fetch_rss_feed("金融时报", "https://www.ftchinese.com/rss/feed", lookback_hours, max_items=20, min_score=2.0))
    except Exception as e:
        log.warning("FT Chinese RSS error: %s", e)
    try:
        items.extend(fetch_rss_feed("金融时报", "https://www.ft.com/rss/markets", lookback_hours, max_items=20, min_score=2.0))
    except Exception as e:
        log.warning("FT Markets RSS error: %s", e)
    try:
        items.extend(fetch_rss_feed(
            "金融时报",
            "https://news.google.com/rss/search?q=site:ftchinese.com+OR+site:ft.com+(China+OR+Yuan+OR+Economy+OR+PBOC)&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            lookback_hours, max_items=20, min_score=2.0
        ))
    except Exception as e:
        log.warning("FT China GNews error: %s", e)
    candidates = deduplicate_articles(items)
    if not candidates:
        candidates = [item for item in deduplicate_articles(items) if item.relevance_score >= 0.5]
    candidates.sort(key=lambda a: a.relevance_score, reverse=True)
    return candidates[:max_per_source]


def _fetch_zaobao(lookback_hours: int, max_per_source: int) -> list[NewsArticle]:
    items = []
    try:
        items.extend(fetch_zaobao_direct(lookback_hours, max_items=20))
    except Exception as e:
        log.warning("Zaobao direct scrape error: %s", e)
    try:
        items.extend(fetch_rss_feed(
            "联合早报",
            "https://news.google.com/rss/search?q=site:zaobao.com.sg/news/china+OR+site:zaobao.com.sg/finance+(%E4%B8%AD%E5%9B%BD+OR+%E8%B4%A2%E7%BB%8F)&hl=zh-CN&gl=SG&ceid=SG:zh-Hans",
            lookback_hours, max_items=20, min_score=2.0
        ))
    except Exception as e:
        log.warning("Zaobao GNews RSS error: %s", e)
    candidates = deduplicate_articles(items)
    if not candidates:
        candidates = [item for item in deduplicate_articles(items) if item.relevance_score >= 0.5]
    candidates.sort(key=lambda a: a.relevance_score, reverse=True)
    return candidates[:max_per_source]


def _fetch_nikkei(lookback_hours: int, max_per_source: int) -> list[NewsArticle]:
    items = []
    lookback = max(lookback_hours, 96)
    try:
        items.extend(fetch_rss_feed(
            "日经中文网",
            "https://news.google.com/rss/search?q=site:cn.nikkei.com+(%E4%B8%AD%E5%9B%BD+OR+%E7%BB%8F%E6%B5%8E+OR+%E5%8D%8A%E5%AF%BC%E4%BD%93+OR+%E6%97%A5%E5%85%83+OR+%E5%B8%82%E5%9C%BA+OR+%E4%BA%A7%E4%B8%9A)&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            lookback, max_items=20, min_score=1.5
        ))
    except Exception as e:
        log.warning("Nikkei targeted GNews RSS error: %s", e)
    if len(items) < max_per_source:
        try:
            items.extend(fetch_rss_feed(
                "日经中文网",
                "https://news.google.com/rss/search?q=site:cn.nikkei.com&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
                lookback, max_items=20, min_score=1.5
            ))
        except Exception as e:
            log.warning("Nikkei general GNews RSS error: %s", e)
    for a in items:
        a.category = "财经/中国·深度专栏"
    candidates = deduplicate_articles(items)
    if not candidates:
        candidates = [item for item in deduplicate_articles(items) if item.relevance_score >= 0.5]
    candidates.sort(key=lambda a: a.relevance_score, reverse=True)
    return candidates[:max_per_source]


def _fetch_economist(lookback_hours: int, max_per_source: int) -> list[NewsArticle]:
    items = []
    lookback = max(lookback_hours, 96)
    try:
        items.extend(fetch_rss_feed("经济学人", "https://www.economist.com/finance-and-economics/rss.xml", lookback, max_items=20, min_score=2.0))
    except Exception as e:
        log.warning("The Economist Finance RSS error: %s", e)
    try:
        items.extend(fetch_rss_feed("经济学人", "https://www.economist.com/china/rss.xml", lookback, max_items=20, min_score=2.0))
    except Exception as e:
        log.warning("The Economist China RSS error: %s", e)
    try:
        items.extend(fetch_rss_feed(
            "经济学人",
            "https://news.google.com/rss/search?q=site:economist.com+(China+OR+economy+OR+markets+OR+finance+OR+Fed)&hl=en-US&gl=US&ceid=US:en",
            lookback, max_items=20, min_score=2.0
        ))
    except Exception as e:
        log.warning("The Economist GNews RSS error: %s", e)
    for a in items:
        a.category = "财经/中国·深度专栏"
    candidates = deduplicate_articles(items)
    if not candidates:
        candidates = [item for item in deduplicate_articles(items) if item.relevance_score >= 0.5]
    candidates.sort(key=lambda a: a.relevance_score, reverse=True)
    return candidates[:max_per_source]


def collect_all_sources(lookback_hours: int = 24, max_per_source: int = 6) -> tuple[dict[str, list[NewsArticle]], list[str]]:
    """
    Collect news from all 7 media outlets in parallel using ThreadPoolExecutor.
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

    collectors = {
        "彭博社": lambda: _fetch_bloomberg(lookback_hours, max_per_source),
        "路透社": lambda: _fetch_reuters(lookback_hours, max_per_source),
        "华尔街日报": lambda: _fetch_wsj(lookback_hours, max_per_source),
        "金融时报": lambda: _fetch_ft(lookback_hours, max_per_source),
        "联合早报": lambda: _fetch_zaobao(lookback_hours, max_per_source),
        "日经中文网": lambda: _fetch_nikkei(lookback_hours, max_per_source),
        "经济学人": lambda: _fetch_economist(lookback_hours, max_per_source),
    }

    # Parallel collection
    with ThreadPoolExecutor(max_workers=len(collectors)) as executor:
        future_to_src = {executor.submit(func): src for src, func in collectors.items()}
        for future in as_completed(future_to_src):
            src = future_to_src[future]
            try:
                raw_items = future.result()
                if raw_items:
                    deduped = deduplicate_articles(raw_items)
                    deduped.sort(key=lambda a: a.relevance_score, reverse=True)
                    results[src] = deduped[:max_per_source]
                else:
                    errors.append(f"{src}：未能成功拉取更新")
            except Exception as e:
                log.warning("抓取源 [%s] 异常: %s", src, e)
                errors.append(f"{src}：抓取异常 ({type(e).__name__})")

    return results, errors

