# -*- coding: utf-8 -*-
"""
Real-time financial market data collector.
Fetches major macro indicators, A-share indices, global markets, commodities, and currency quotes
to ground AI asset allocation analysis with empirical market data.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo
import requests

log = logging.getLogger("daily-news")

# Target financial market indicators
MARKET_INDICATORS: list[dict[str, str]] = [
    {"symbol": "sh000001", "name": "上证指数", "category": "A股基准"},
    {"symbol": "sh000300", "name": "沪深300", "category": "A股核心资产"},
    {"symbol": "hkHSI", "name": "恒生指数", "category": "港股核心"},

    {"symbol": "hkHSTECH", "name": "恒生科技", "category": "中国科技互联"},
    {"symbol": "usINX", "name": "标普500", "category": "美股大盘"},
    {"symbol": "usIXIC", "name": "纳斯达克", "category": "全球科技成长"},
    {"symbol": "sh518880", "name": "黄金ETF", "category": "避险贵金属"},
    {"symbol": "sh513100", "name": "纳指ETF", "category": "全球科技QDII"},
    {"symbol": "sh513500", "name": "标普500ETF", "category": "全球多元QDII"},
]


@dataclass
class MarketQuote:
    symbol: str
    name: str
    price: float
    change: float
    change_pct: float
    category: str


def fetch_market_snapshot(timeout: float = 6.0) -> list[MarketQuote]:
    """
    Fetch latest market quotes for major indices and assets.
    Returns empty list if network is unavailable or request times out (fail-safe).
    """
    quotes: list[MarketQuote] = []
    symbol_str = ",".join(f"s_{item['symbol']}" for item in MARKET_INDICATORS)
    url = f"https://qt.gtimg.cn/q={symbol_str}"

    meta_by_symbol = {f"s_{item['symbol']}": item for item in MARKET_INDICATORS}

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DailyDigest/1.0"},
            timeout=timeout
        )
        if resp.status_code != 200:
            log.warning("行情接口响应异常 (HTTP %d)", resp.status_code)
            return quotes

        # Format: v_s_sh000001="1~名称~代码~价格~涨跌额~涨跌幅~成交量~成交额~~...";
        lines = resp.text.strip().split(";")
        for line in lines:
            line = line.strip()
            if not line or "=" not in line:
                continue

            var_name, val_str = line.split("=", 1)
            var_name = var_name.strip()
            val_str = val_str.strip(' \t\n\r"')

            if var_name.startswith("v_"):
                var_name = var_name[2:]

            meta = meta_by_symbol.get(var_name)
            if not meta:
                continue

            parts = val_str.split("~")
            if len(parts) >= 6:
                try:
                    price = float(parts[3])
                    change = float(parts[4])
                    change_pct = float(parts[5])
                    quotes.append(MarketQuote(
                        symbol=meta["symbol"],
                        name=meta["name"],
                        price=price,
                        change=change,
                        change_pct=change_pct,
                        category=meta["category"],
                    ))
                except (ValueError, IndexError) as err:
                    log.debug("解析行情字段异常 [%s]: %s", var_name, err)

    except Exception as exc:
        log.warning("获取行情快照失败（不影响主流程）: %s", exc)

    # Fetch USD/CNH forex quote as complementary macro signal
    try:
        forex_url = "http://hq.sinajs.cn/list=fx_susdcnh"
        f_resp = requests.get(
            forex_url,
            headers={"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0 DailyDigest/1.0"},
            timeout=timeout
        )
        if f_resp.status_code == 200 and "hq_str_fx_susdcnh=" in f_resp.text:
            content = f_resp.text.split('="', 1)[1].rstrip('";\n')
            f_parts = content.split(",")
            if len(f_parts) >= 13:
                price = float(f_parts[1])
                change_pct = float(f_parts[10])
                change = float(f_parts[11])
                quotes.append(MarketQuote(
                    symbol="USDCNH",
                    name="离岸人民币",
                    price=price,
                    change=change,
                    change_pct=change_pct,
                    category="汇率风向标",
                ))
    except Exception as exc:
        log.debug("获取离岸人民币汇率跳过: %s", exc)

    return quotes


def _market_snapshot_note(now: datetime | None = None) -> str:
    """Describe snapshot fetch time and A-share/HK session state.

    The digest runs around 08:00 Beijing time, before A-share/HK markets open, so their
    quotes reflect the previous trading day's close rather than live prices.
    """
    current = now or datetime.now(ZoneInfo("Asia/Shanghai"))
    stamp = current.strftime("%Y-%m-%d %H:%M")
    minutes = current.hour * 60 + current.minute
    is_weekday = current.weekday() < 5

    # A股 09:30-11:30 / 13:00-15:00；港股 09:30-12:00 / 13:00-16:00（北京时间）
    a_share_open = is_weekday and ((570 <= minutes < 690) or (780 <= minutes < 900))
    hk_open = is_weekday and ((570 <= minutes < 720) or (780 <= minutes < 960))

    if a_share_open and hk_open:
        session = "A股与港股当前处于交易时段，相关点位为盘中实时行情"
    elif a_share_open:
        session = "A股当前处于交易时段（盘中实时），港股为最近成交价"
    elif hk_open:
        session = "港股当前处于交易时段（盘中实时），A股为最近成交价"
    elif is_weekday and minutes < 570:
        session = "A股与港股尚未开盘（09:30 开盘），相关点位为上一交易日收盘价"
    elif is_weekday and minutes >= 900:
        session = "A股与港股已收盘，相关点位为当日收盘价"
    else:
        session = "A股与港股处于非交易日/休市状态，相关点位为最近一个交易日收盘价"

    return f"*行情快照抓取时间：{stamp}（北京时间）。{session}；美股、黄金与汇率报价为其最近可得的收盘/最新价。*"


def render_market_table(quotes: list[MarketQuote]) -> str:
    """Format market quotes into an elegant Markdown table with trend badges."""
    if not quotes:
        return ""

    lines = [
        "### 📈 全球核心资产与宏观行情快照",
        "| 标的资产 | 最新报价/点位 | 当日涨跌幅 | 资产定位 |",
        "|---|---|---|---|",
    ]

    for q in quotes:
        if q.change_pct > 0.0:
            badge = "🟢"
            pct_str = f"+{q.change_pct:.2f}%"
        elif q.change_pct < 0.0:
            badge = "🔴"
            pct_str = f"{q.change_pct:.2f}%"
        else:
            badge = "⚪"
            pct_str = "0.00%"

        # Format price with commas for large numbers, decimals for ETFs/forex
        if q.price >= 1000:
            price_str = f"{q.price:,.2f}"
        elif q.price >= 1:
            price_str = f"{q.price:.3f}"
        else:
            price_str = f"{q.price:.4f}"

        lines.append(f"| **{q.name}** | `{price_str}` | {pct_str} {badge} | {q.category} |")

    lines.append("")
    lines.append(_market_snapshot_note())
    return "\n".join(lines)


def format_market_context_for_prompt(quotes: list[MarketQuote]) -> str:
    """Format market snapshot into a prompt block for the LLM."""
    if not quotes:
        return "（未获取到行情数据）"

    items = []
    for q in quotes:
        sign = "+" if q.change_pct > 0 else ""
        items.append(f"- {q.name} ({q.category}): 最新价 {q.price}, 涨跌幅 {sign}{q.change_pct:.2f}%")
    items.append("")
    items.append(_market_snapshot_note())
    return "\n".join(items)
