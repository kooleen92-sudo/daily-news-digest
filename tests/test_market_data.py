# -*- coding: utf-8 -*-
"""Unit tests for real-time market data snapshot engine."""

from market_data import MarketQuote, render_market_table, format_market_context_for_prompt


def test_render_market_table_trend_badges():
    quotes = [
        MarketQuote(symbol="sh000001", name="上证指数", price=3842.19, change=11.74, change_pct=0.31, category="A股基准"),
        MarketQuote(symbol="hkHSI", name="恒生指数", price=24130.50, change=-150.06, change_pct=-0.62, category="港股核心"),
        MarketQuote(symbol="flat", name="平盘资产", price=100.0, change=0.0, change_pct=0.0, category="货币基金"),
    ]

    table_md = render_market_table(quotes)

    assert "### 📈 全球核心资产与宏观行情快照" in table_md
    assert "上证指数" in table_md
    assert "+0.31% 🟢" in table_md
    assert "-0.62% 🔴" in table_md
    assert "0.00% ⚪" in table_md
    assert "3,842.19" in table_md


def test_format_market_context_for_prompt():
    quotes = [
        MarketQuote(symbol="sh000001", name="上证指数", price=3842.19, change=11.74, change_pct=0.31, category="A股基准"),
    ]
    prompt_ctx = format_market_context_for_prompt(quotes)
    assert "上证指数" in prompt_ctx
    assert "+0.31%" in prompt_ctx

    empty_ctx = format_market_context_for_prompt([])
    assert "未获取" in empty_ctx
