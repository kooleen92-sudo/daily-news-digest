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
import json
import logging
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
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


@dataclass(frozen=True)
class FeedSpec:
    url: str
    min_score: float = 2.0
    category: str = "财经/中国"
    max_items: int = 20


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


# ---------------------------------------------------------------------------
# Whitelist, Blacklist & Multi-tiered Relevance Scoring Engine
# ---------------------------------------------------------------------------

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
    "货币政策", "量化宽松", "通胀", "通货膨胀", "通货紧缩", "经济衰退",
    "失业率", "非农", "非农就业", "国债收益率", "美债", "主权债务", "债务违约",
    "财政赤字", "赤字", "贸易逆差", "贸易战", "制裁", "去美元化", "房贷利率", "贴息",
    "存款准备金率", "评级", "信用评级"
]

TIER3_MARKET_KEYWORDS = [
    # Markets & Commodities
    "wall street", "s&p 500", "nasdaq", "dow jones", "nikkei", "ftse", "dax",
    "stock market", "bond market", "crude oil", "oil", "brent", "wti", "opec",
    "gold", "gold price", "silver", "copper", "dollar index", "dxy", "dollar", "forex", "fx",
    # Tech chips & AI infra
    "semiconductor", "chip export", "chipmaker", "asml", "tsmc", "nvidia", "ai chip",
    "gpu", "data center", "artificial intelligence", "generative ai", "large language model",
    # Chinese terms
    "华尔街", "美股", "标普500", "标普", "纳斯达克", "纳指", "道琼斯", "日经指数", "日经",
    "股市", "债市", "原油", "石油", "布伦特", "欧佩克", "黄金", "白银",
    "铜价", "大宗商品", "美元指数", "美元", "外汇", "汇率", "半导体", "芯片", "光刻机",
    "台积电", "英伟达", "算力", "数据中心", "人工智能", "大模型", "生成式ai", "ai"
]

TIER4_BUSINESS_KEYWORDS = [
    "economy", "economic", "market", "markets", "trade", "investment", "investor", "capital",
    "earnings", "revenue", "profit", "ipo", "bank", "banking", "finance", "financial",
    "stock", "stocks", "bond", "bonds", "asset management", "hedge fund", "private equity",
    "merger", "acquisition",
    "经济", "市场", "贸易", "投资", "投资者", "资本", "财报", "营收", "利润", "净利润",
    "上市", "挂牌", "银行", "金融", "资产管理", "对冲基金", "私募", "并购", "重组", "回购"
]


def _compile_keyword_matcher(keywords: list[str]) -> tuple[list[str], re.Pattern | None]:
    """
    Split keywords into Chinese substrings and precompiled boundary-aware English regex.
    Deduplicates and optimizes matching speed.
    """
    seen = set()
    chinese_list: list[str] = []
    english_list: list[str] = []

    for kw in keywords:
        cleaned = kw.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        if any("\u4e00" <= ch <= "\u9fff" for ch in cleaned):
            chinese_list.append(cleaned)
        else:
            english_list.append(cleaned)

    # Sort longer keywords first for regex alternation
    english_list.sort(key=len, reverse=True)
    regex_pattern = None
    if english_list:
        sub_pattern = "|".join(re.escape(k) for k in english_list)
        regex_pattern = re.compile(rf"(?<![a-z0-9])(?:{sub_pattern})(?![a-z0-9])", re.IGNORECASE)

    return chinese_list, regex_pattern


# Merge custom keywords from config/topics.yaml if configured
_custom_kw = getattr(config, "topics_config", {}).get("custom_keywords", {})
_extra_t1 = _custom_kw.get("tier1_china", []) if isinstance(_custom_kw, dict) else []
_extra_t2 = _custom_kw.get("tier2_macro", []) if isinstance(_custom_kw, dict) else []
_extra_t3 = _custom_kw.get("tier3_markets", []) if isinstance(_custom_kw, dict) else []

# Precompiled matchers for high-throughput relevance evaluation
_NEG_ZH, _NEG_EN = _compile_keyword_matcher(NEGATIVE_KEYWORDS)
_TIER1_ZH, _TIER1_EN = _compile_keyword_matcher(TIER1_CHINA_KEYWORDS + _extra_t1)
_TIER2_ZH, _TIER2_EN = _compile_keyword_matcher(TIER2_MACRO_KEYWORDS + _extra_t2)
_TIER3_ZH, _TIER3_EN = _compile_keyword_matcher(TIER3_MARKET_KEYWORDS + _extra_t3)
_TIER4_ZH, _TIER4_EN = _compile_keyword_matcher(TIER4_BUSINESS_KEYWORDS)



def _contains_keyword(text: str, keyword: str) -> bool:
    """Match Chinese phrases or complete English words, avoiding substring noise."""
    if any("\u4e00" <= ch <= "\u9fff" for ch in keyword):
        return keyword in text
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def _check_match(text_lower: str, zh_list: list[str], en_pattern: re.Pattern | None) -> bool:
    """Fast check whether text matches any Chinese substring or English regex."""
    if en_pattern and en_pattern.search(text_lower):
        return True
    return any(zh in text_lower for zh in zh_list)


def calculate_relevance_score(title: str, summary: str, source: str = "") -> float:
    """
    Compute structured relevance score for an article.
    High scores indicate strong relevance to Macroeconomics, Financial Markets, or China Mainland.
    Negative scores indicate entertainment, sports, or local human interest noise.
    """
    t = title.lower()
    s = summary.lower()

    score = 0.0

    # Tier 1 (China)
    for k in _TIER1_ZH:
        if k in t:
            score += 6.0
        elif k in s:
            score += 2.5
    if _TIER1_EN:
        for m in _TIER1_EN.finditer(t):
            score += 6.0
        for m in _TIER1_EN.finditer(s):
            score += 2.5

    # Tier 2 (Macroeconomics & Central Banks)
    for k in _TIER2_ZH:
        if k in t:
            score += 4.5
        elif k in s:
            score += 2.0
    if _TIER2_EN:
        for m in _TIER2_EN.finditer(t):
            score += 4.5
        for m in _TIER2_EN.finditer(s):
            score += 2.0

    # Tier 3 (Markets, Commodities, AI Infra)
    for k in _TIER3_ZH:
        if k in t:
            score += 3.0
        elif k in s:
            score += 1.5
    if _TIER3_EN:
        for m in _TIER3_EN.finditer(t):
            score += 3.0
        for m in _TIER3_EN.finditer(s):
            score += 1.5

    # Tier 4 (General Business)
    for k in _TIER4_ZH:
        if k in t:
            score += 1.0
        elif k in s:
            score += 0.5
    if _TIER4_EN:
        for m in _TIER4_EN.finditer(t):
            score += 1.0
        for m in _TIER4_EN.finditer(s):
            score += 0.5

    # Penalize entertainment / sports / crime noise
    if _check_match(t, _NEG_ZH, _NEG_EN):
        score -= 25.0
    elif _check_match(s, _NEG_ZH, _NEG_EN):
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

    for section_url, _ in sections:
        try:
            html_bytes = http_get(section_url, timeout=config.fetch_timeout)
            soup = BeautifulSoup(html_bytes.decode("utf-8", errors="ignore"), "html.parser")

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

                date_match = re.search(r"story(\d{4})(\d{2})(\d{2})-", href)
                if date_match:
                    year, month, day = map(int, date_match.groups())
                    pub_date = datetime(year, month, day, 23, 59, 59, tzinfo=ZoneInfo("Asia/Singapore")).astimezone(timezone.utc)
                else:
                    continue


                if pub_date < cutoff:
                    continue

                score = calculate_relevance_score(title, "", "联合早报")
                if score < 0.5:
                    continue

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

        title_key = "".join(ch for ch in item.title.lower() if ch.isalnum())
        if not title_key:
            continue

        is_dup = False
        for seen in seen_titles:
            if len(title_key) >= 10 and len(seen) >= 10:
                matcher = difflib.SequenceMatcher(None, title_key, seen)
                if matcher.ratio() >= similarity_threshold:
                    # Guard against false deduplication of antonym polarity (e.g. 涨 vs 跌)
                    opposite_pairs = [("涨", "跌"), ("升", "降"), ("增", "减"), ("牛", "熊"), ("利好", "利空")]
                    is_opposite = any(
                        ((pos in title_key and neg in seen) or (neg in title_key and pos in seen))
                        and not (pos in title_key and pos in seen)
                        and not (neg in title_key and neg in seen)
                        for pos, neg in opposite_pairs
                    )
                    if not is_opposite:
                        is_dup = True
                        break

        if is_dup:
            continue

        seen_urls.add(clean_url)
        seen_titles.append(title_key)
        unique_articles.append(item)

    return unique_articles


# ---------------------------------------------------------------------------
# Declarative Media Feed Specifications
# ---------------------------------------------------------------------------

SOURCE_FEED_SPECS: dict[str, list[FeedSpec]] = {
    "彭博社": [
        FeedSpec("https://feeds.bloomberg.com/markets/news.rss", min_score=2.0),
        FeedSpec("https://news.google.com/rss/search?q=site:bloomberg.com+(China+OR+Yuan+OR+CSI300+OR+PBOC+OR+Economy)&hl=en-US&gl=US&ceid=US:en", min_score=2.0),
    ],
    "路透社": [
        FeedSpec("https://news.google.com/rss/search?q=site:reuters.com+(China+OR+economy+OR+markets+OR+yuan+OR+PBOC)&hl=en-US&gl=US&ceid=US:en", min_score=2.0),
        FeedSpec("https://news.google.com/rss/search?q=site:reuters.com+(Fed+OR+inflation+OR+Treasury+OR+markets+OR+tariff)&hl=en-US&gl=US&ceid=US:en", min_score=2.0),
    ],
    "华尔街日报": [
        FeedSpec("https://feeds.a.dj.com/rss/RSSMarketsMain.xml", min_score=2.0),
        FeedSpec("https://news.google.com/rss/search?q=site:wsj.com+(China+OR+Trade+OR+Yuan+OR+PBOC+OR+Economy)&hl=en-US&gl=US&ceid=US:en", min_score=2.0),
    ],
    "金融时报": [
        FeedSpec("https://www.ftchinese.com/rss/feed", min_score=2.0),
        FeedSpec("https://www.ft.com/rss/markets", min_score=2.0),
        FeedSpec("https://news.google.com/rss/search?q=site:ftchinese.com+OR+site:ft.com+(China+OR+Yuan+OR+Economy+OR+PBOC)&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", min_score=2.0),
    ],
    "联合早报": [
        FeedSpec("https://news.google.com/rss/search?q=site:zaobao.com.sg+(%E4%B8%AD%E5%9B%BD+OR+%E8%B4%A2%E7%BB%8F)&hl=zh-CN&gl=SG&ceid=SG:zh-Hans", min_score=2.0),
    ],

    "日经中文网": [
        FeedSpec("https://news.google.com/rss/search?q=site:cn.nikkei.com+(%E4%B8%AD%E5%9B%BD+OR+%E7%BB%8F%E6%B5%8E+OR+%E5%8D%8A%E5%AF%BC%E4%BD%93+OR+%E6%97%A5%E5%85%83+OR+%E5%B8%82%E5%9C%BA+OR+%E4%BA%A7%E4%B8%9A)&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", min_score=1.5, category="财经/中国·深度专栏"),
        FeedSpec("https://news.google.com/rss/search?q=site:cn.nikkei.com&hl=zh-CN&gl=CN&ceid=CN:zh-Hans", min_score=1.5, category="财经/中国·深度专栏"),
    ],
    "经济学人": [
        FeedSpec("https://www.economist.com/finance-and-economics/rss.xml", min_score=2.0, category="财经/中国·深度专栏"),
        FeedSpec("https://www.economist.com/china/rss.xml", min_score=2.0, category="财经/中国·深度专栏"),
        FeedSpec("https://news.google.com/rss/search?q=site:economist.com+(China+OR+economy+OR+markets+OR+finance+OR+Fed)&hl=en-US&gl=US&ceid=US:en", min_score=2.0, category="财经/中国·深度专栏"),
    ],
}


def _fetch_source_declarative(
    source_name: str,
    lookback_hours: int,
    max_per_source: int,
    custom_collector: Callable[[int, int], list[NewsArticle]] | None = None
) -> list[NewsArticle]:
    """Fetch articles for a source using configured FeedSpecs and optional custom collectors."""
    items: list[NewsArticle] = []

    # Optional custom scraper (e.g. Lianhe Zaobao direct web scrape)
    if custom_collector:
        try:
            items.extend(custom_collector(lookback_hours, max_per_source))
        except Exception as e:
            log.warning("[%s] 自定义抓取异常: %s", source_name, e)

    # Standard RSS / GNews feeds
    specs = SOURCE_FEED_SPECS.get(source_name, [])
    for spec in specs:
        try:
            fetched = fetch_rss_feed(
                source_name=source_name,
                url=spec.url,
                lookback_hours=lookback_hours,
                max_items=spec.max_items,
                force_relevant=True,
                min_score=spec.min_score
            )
            for item in fetched:
                item.category = spec.category
            items.extend(fetched)
        except Exception as e:
            log.warning("[%s] Feed 抓取异常 (%s): %s", source_name, spec.url, e)

    # Deduplicate and sort by relevance score
    candidates = deduplicate_articles(items)
    candidates.sort(key=lambda a: (a.relevance_score, a.published_at), reverse=True)
    return candidates[:max_per_source]


GOOGLE_NEWS_BATCHEXECUTE_URL = "https://news.google.com/_/DotsSplashUi/data/batchexecute"


def _extract_google_news_article_id(url: str) -> str | None:
    """Extract the article id from a Google News RSS redirect URL."""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlparse(url.strip())
    except Exception:
        return None
    if "news.google.com" not in parsed.netloc.lower():
        return None
    match = re.search(r"/(?:rss/)?articles/([^/?#]+)", parsed.path)
    if not match:
        return None
    return match.group(1) or None


def _parse_google_news_page(html_text: str) -> tuple[str | None, str | None]:
    """Extract the signature and timestamp tokens from a Google News article page."""
    if not html_text:
        return None, None
    signature_match = re.search(r'data-n-a-sg="([^"]+)"', html_text)
    timestamp_match = re.search(r'data-n-a-ts="([^"]+)"', html_text)
    signature = signature_match.group(1) if signature_match else None
    timestamp = timestamp_match.group(1) if timestamp_match else None
    return signature, timestamp


def _decode_google_news_response(response_text: str) -> str | None:
    """Decode the publisher URL from a Google News batchexecute response."""
    if not response_text:
        return None
    marker_index = response_text.find("garturlres")
    if marker_index == -1:
        return None
    tail = response_text[marker_index:].replace("\\/", "/")
    for match in re.finditer(r'https?://[^\s"\\\]\}]+', tail):
        candidate = match.group(0)
        if "news.google.com" not in candidate:
            return candidate
    return None


def resolve_google_news_url(url: str, timeout: float = 5.0) -> str | None:
    """Resolve a Google News RSS redirect URL to the publisher's real URL (fail-safe)."""
    try:
        article_id = _extract_google_news_article_id(url)
        if not article_id:
            return None

        page_response = _SESSION.get(
            f"https://news.google.com/rss/articles/{article_id}",
            headers={"User-Agent": DEFAULT_USER_AGENT},
            timeout=timeout,
        )
        if page_response.status_code != 200:
            return None

        signature, timestamp = _parse_google_news_page(page_response.text)
        if not signature or not timestamp:
            return None

        inner_payload = (
            '["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,'
            'null,null,null,null,null,0,1],"X","X",1,[1,1,1],1,1,null,0,0,null,0],'
            f'"{article_id}",{timestamp},"{signature}"]'
        )
        form_data = [("f.req", json.dumps([[["Fbv4je", inner_payload, None, "generic"]]]))]
        api_response = _SESSION.post(
            GOOGLE_NEWS_BATCHEXECUTE_URL,
            data=form_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "User-Agent": DEFAULT_USER_AGENT,
            },
            timeout=timeout,
        )
        if api_response.status_code != 200:
            return None

        decoded = _decode_google_news_response(api_response.text)
        if decoded and decoded.startswith("http") and "news.google.com" not in decoded:
            return decoded
        return None
    except Exception as exc:
        log.debug("Google News 链接解析失败 [%s]: %s", url, exc)
        return None


def resolve_google_news_urls(
    articles: list[NewsArticle],
    max_workers: int = 6,
    time_budget: float = 20.0,
) -> int:
    """Resolve Google News redirect URLs to publisher URLs in-place (bounded by a time budget)."""
    targets = [article for article in articles if _extract_google_news_article_id(article.url)]
    if not targets:
        return 0

    resolved_count = 0
    executor = ThreadPoolExecutor(max_workers=max_workers)
    try:
        future_to_article = {executor.submit(resolve_google_news_url, article.url): article for article in targets}
        try:
            for future in as_completed(future_to_article, timeout=time_budget):
                article = future_to_article[future]
                try:
                    real_url = future.result()
                except Exception:
                    real_url = None
                if real_url and "news.google.com" not in real_url:
                    article.url = real_url
                    resolved_count += 1
        except TimeoutError:
            log.debug("Google News 链接解析超出 %.0f 秒时间预算，未完成部分保留原链接。", time_budget)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    if resolved_count:
        log.info("已将 %d/%d 条 Google News 跳转链接解析为发布方原文链接。", resolved_count, len(targets))
    return resolved_count


def collect_all_sources(lookback_hours: int = 24, max_per_source: int = 6) -> tuple[dict[str, list[NewsArticle]], list[str]]:
    """
    Collect news from all 7 media outlets in parallel using ThreadPoolExecutor.

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

    collectors = {
        "彭博社": lambda: _fetch_source_declarative("彭博社", lookback_hours, max_per_source),
        "路透社": lambda: _fetch_source_declarative("路透社", lookback_hours, max_per_source),
        "华尔街日报": lambda: _fetch_source_declarative("华尔街日报", lookback_hours, max_per_source),
        "金融时报": lambda: _fetch_source_declarative("金融时报", lookback_hours, max_per_source),
        "联合早报": lambda: _fetch_source_declarative("联合早报", lookback_hours, max_per_source, custom_collector=fetch_zaobao_direct),
        "日经中文网": lambda: _fetch_source_declarative("日经中文网", lookback_hours, max_per_source),
        "经济学人": lambda: _fetch_source_declarative("经济学人", lookback_hours, max_per_source),
    }

    with ThreadPoolExecutor(max_workers=len(collectors)) as executor:
        future_to_src = {executor.submit(func): src for src, func in collectors.items()}
        for future in as_completed(future_to_src):
            src = future_to_src[future]
            try:
                raw_items = future.result()
                if raw_items:
                    results[src] = raw_items
                else:
                    errors.append(f"{src}：未能成功拉取更新")
            except Exception as e:
                log.warning("抓取源 [%s] 异常: %s", src, e)
                errors.append(f"{src}：抓取异常 ({type(e).__name__})")

    if config.resolve_google_news:
        all_articles = [article for items in results.values() for article in items]
        resolve_google_news_urls(all_articles)

    return results, errors
