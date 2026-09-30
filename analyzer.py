# -*- coding: utf-8 -*-
"""
AI Financial & Geopolitical News Analyzer.
Synthesizes news articles from Bloomberg, Reuters, WSJ, FT, and Lianhe Zaobao,
and provides deep, professional impact analysis on China's economy, financial markets,
and specific industries.
"""

from __future__ import annotations

import logging
import time
from typing import Any
from openai import OpenAI
from config import config
from collector import NewsArticle

log = logging.getLogger("daily-news")

SYSTEM_PROMPT = """你是一名国际顶级宏观对冲基金的首席策略分析师、资深财经主编与资深私人财富资产配置顾问。
你的任务是根据各大国际权威外媒（彭博社、路透社、华尔街日报、金融时报、联合早报）抓取到的过去24小时财经及中国大陆相关最新消息，撰写一份高水准、严谨专业且极具决策与实操价值的《每日财经与中国宏观深度简报》。

在分析时，请严格遵守以下原则：
1. **客观准确**：严格基于提供的新闻事实，不胡乱编造任何未提及的数据或内幕，区分客观事实与外媒观点。
2. **深度影响分析（核心重点）**：不仅要说明“发生了什么”，必须深入剖析“有什么影响”：
   - **宏观与货币政策**：对中国宏观经济动能、央行货币/财政政策、监管导向的可能传导。
   - **资本市场与汇率**：对A股、港股恒生指数、中概股、离岸人民币（CNH）、中美利差及全球金融资产价格的影响倾向（利好/利空/震荡）。
   - **产业与龙头企业**：对重点产业（如科技/AI/半导体、新能源汽车、房地产、出海贸易、金融）的具体冲击或拉动。
   - **国际地缘与经贸**：外媒报道关注的重点议题、经贸制裁或博弈动向。
3. **个人投资与大类资产配置指引（极高实用价值）**：必须结合当日最新宏观要闻，面向中国个人投资者给出落地的投资操作与资产配置指引，覆盖：
   - **A股股票（沪深主板及双创板）**：主板蓝筹/高股息红利 vs 科技成长板块的操作策略与仓位控制建议。
   - **公募基金（场内ETF与场外基金）**：宽基ETF、行业主题ETF的交易时机，以及场外定投/固收底仓策略。
   - **QDII基金（场内/场外）**：美股核心资产（纳指100/标普500）、全球半导体QDII的配置节奏与溢价风险警示。
   - **黄金与贵金属**：黄金ETF、积存金的逢低布局或避险配置比例。
4. **输出排版格式**：请使用规范清晰的 Markdown 语法，结构化呈现。保留每条新闻的原文链接。
"""

USER_PROMPT_TEMPLATE = """请基于以下从彭博社、路透社、华尔街日报、金融时报、联合早报抓取的最新新闻资讯，撰写今日份的专业分析与个人投资配置报告：

---
{articles_text}
---

请按以下四大模块输出报告（全部使用中文，专业、凝练且具实操指引）：

## 🌟 一、今日核心研判与前瞻（Executive Summary）
（提炼 3~5 条对宏观格局、资本市场、中国政策走势有决定性影响的核心结论与洞察，要害明确，直击本质）

## 📊 二、市场与资产影响速查矩阵（Market Impact Matrix）
（以 Markdown 表格形式呈现，包含：资产/领域、影响倾向[🟢利好/🔴利空/🟡震荡分化]、核心驱动逻辑及相关媒体）

## 🔍 三、各家外媒精要与深度影响剖析（In-Depth Analysis）
（按媒体分类：彭博社、路透社、华尔街日报、金融时报、联合早报。针对每家媒体的关键要闻，逐条提供）：
- **[新闻标题]**（附原文链接）
  - 📰 **核心事实**：用1-2句精炼说明关键事件与数据。
  - 💡 **影响分析**：深入分析对中国宏观/政策、金融市场（股市/汇率/债券）或产业企业的具体传导机制与影响。

## 💡 四、个人投资与大类资产配置操作指引（Personal Allocation Blueprint）
（结合今日全球宏观及政策信号，面向个人投资者给出可落地的实战配置建议）：
1. **A股股票操作策略（沪深主板 / 创业板 / 科创板）**：
   - **沪深主板**（高股息红利资产、中字头央企、大金融/周期/消费）：当前进攻还是防御？估值与建仓节奏。
   - **双创与成长板块**（半导体/自主可控、AI产业链、新能源）：外围地缘与科技博弈下的波段或防御思路。
   - **整体仓位建议**：建议权益仓位控制区间（例如几成仓位）及买卖节奏。
2. **公募基金配置指南（场内ETF & 场外基金）**：
   - **场内 ETF 实操**：宽基（如沪深300 ETF、中证A500 ETF、恒生科技 ETF）与行业主题（红利低波、芯片、医药等）的操作思路。
   - **场外基金策略**：定投频率（是否加仓/观望）、固收+及纯债基金的安全垫配置比例。
3. **QDII 基金配置指南（场内 / 场外全球资产）**：
   - **美股与全球资产**（纳指100 ETF、标普500 ETF、全球芯片科技 QDII）：配置逻辑、防范场内高溢价风险及定投买入点。
4. **黄金与贵金属资产配置指南（避险抗通胀）**：
   - 黄金 ETF、银行积存金/实物金的配置逻辑；结合美联储利率路径与地缘局势，当前是逢低加仓、分批定投还是持金观望？推荐在个人总盘子中的配置比例（如 5%~15%）。
5. **推荐资产配置比例速查（稳健型 vs 进取型）**：
   - 用 Markdown 表格列出当前环境下推荐的配置比例（如：A股核心权益 %、QDII全球多元 %、黄金避险 %、现金与固收纯债 %），并做简要风控提醒。

【篇幅与完整性要求】：
请合理把控全文字数，第三部分针对各媒体要闻剖析要求语言干练、重点突出（每条分析精炼有力），务必确保第四部分【个人投资与大类资产配置操作指引】的所有 5 个要点（A股主板与双创、公募场内场外基金、QDII、黄金配置、配置比例表格）全部完整输出到底，绝不截断。

请直接输出高质量 Markdown 内容。"""



def format_articles_for_prompt(articles_by_source: dict[str, list[NewsArticle]]) -> str:
    """Format structured articles into a prompt context."""
    blocks = []
    item_index = 1
    
    for source_name, items in articles_by_source.items():
        if not items:
            continue
        blocks.append(f"### 【{source_name}】（共 {len(items)} 条）")
        for a in items:
            pub_str = a.published_at.strftime("%Y-%m-%d %H:%M UTC")
            blocks.append(
                f"[{item_index}] 来源：{a.source}\n"
                f"标题：{a.title}\n"
                f"发布时间：{pub_str}\n"
                f"链接：{a.url}\n"
                f"摘要/导语：{a.summary or '（无摘要，参见标题）'}\n"
            )
            item_index += 1
            
    return "\n".join(blocks)


def generate_fallback_report(articles_by_source: dict[str, list[NewsArticle]], errors: list[str]) -> str:
    """Generate a clean, structured fallback report when LLM is unavailable."""
    lines = [
        "## 📌 简报速览（未启用大模型智能分析兜底模式）\n",
        "> 说明：当前未配置 `OPENAI_API_KEY` 或大模型调用超时，以下按来源整理各媒体最新抓取到的财经与中国要闻及原文链接。\n"
    ]

    total_count = sum(len(items) for items in articles_by_source.values())
    lines.append(f"共汇总 **{total_count}** 条最新资讯，请点击对应标题阅读原文。\n")

    for source_name, items in articles_by_source.items():
        lines.append(f"### 📰 {source_name}（{len(items)} 条）")
        if not items:
            lines.append("- *(该源本时段暂无抓取到的新内容)*\n")
            continue
            
        for a in items:
            pub_time = a.published_at.strftime("%m-%d %H:%M")
            lines.append(f"- **[{a.title}]({a.url})**  `{pub_time}`")
            if a.summary and a.summary != a.title:
                snippet = a.summary[:200] + ("…" if len(a.summary) > 200 else "")
                lines.append(f"  > {snippet}")
        lines.append("")

    return "\n".join(lines)


def analyze_news(articles_by_source: dict[str, list[NewsArticle]], errors: list[str]) -> str:
    """
    Generate deep impact analysis using OpenAI-compatible LLM.
    Falls back gracefully if LLM is not configured or fails.
    """
    total_articles = sum(len(items) for items in articles_by_source.values())
    if total_articles == 0:
        return "## 暂无新闻\n\n过去 24 小时未抓取到符合条件的财经及中国大陆新闻。"

    if not config.openai_api_key:
        log.info("OPENAI_API_KEY is not configured. Using structured fallback report.")
        return generate_fallback_report(articles_by_source, errors)

    # Clean inputs
    model_name = config.llm_model.strip().lower().replace(" ", "-")
    base_url = config.openai_base_url.strip() if config.openai_base_url else None
    
    # If base_url is google generative language, ensure correct OpenAI endpoint structure
    if base_url and "googleapis.com" in base_url and not base_url.endswith("/openai/"):
        base_url = base_url.rstrip("/") + "/openai/"

    log.info("Requesting LLM analysis via model '%s' (base_url: %s)...", model_name, base_url)
    articles_text = format_articles_for_prompt(articles_by_source)
    prompt = USER_PROMPT_TEMPLATE.format(articles_text=articles_text)

    client_kwargs = {
        "api_key": config.openai_api_key.strip(),
        "timeout": config.llm_timeout,
        "max_retries": 1,
    }
    if base_url:
        client_kwargs["base_url"] = base_url

    client = OpenAI(**client_kwargs)

    # Candidate models to try if the primary model is retired or not found
    candidates = [model_name]
    if "gemini" in model_name:
        for fallback in ["gemini-3.8-flash", "gemini-3.8-flash-lite", "gemini-3.5-flash"]:
            if fallback not in candidates:
                candidates.append(fallback)

    last_error = None
    for cand_model in candidates:
        model_failed = False
        for attempt in range(3):
            try:
                create_kwargs = {
                    "model": cand_model,
                    "temperature": 0.3,
                    "max_tokens": 8192,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                }
                response = client.chat.completions.create(**create_kwargs)
                content = response.choices[0].message.content
                if content and len(content.strip()) > 50:
                    log.info("LLM completion succeeded with model: %s", cand_model)
                    return content.strip()
            except Exception as exc:
                last_error = exc
                err_str = str(exc).lower()
                log.warning("Model '%s' attempt %d failed: %s: %s", cand_model, attempt + 1, type(exc).__name__, exc)
                
                # If authentication failed, abort immediately
                if "401" in err_str or "invalid_api_key" in err_str or "unauthenticated" in err_str:
                    log.error("Authentication failed. Aborting model retries.")
                    model_failed = True
                    break
                    
                # If model not found or retired, stop retrying this model and switch to next
                if "404" in err_str or "not found" in err_str or "no longer available" in err_str:
                    model_failed = True
                    break
                    
                # If server is overloaded (503) or rate limited (429), wait and retry
                if ("503" in err_str or "unavailable" in err_str or "high demand" in err_str or "429" in err_str) and attempt < 2:
                    wait_sec = 4 * (attempt + 1)
                    log.info("Google Gemini server busy (503/429), waiting %d seconds before retry...", wait_sec)
                    time.sleep(wait_sec)
                    continue

        if "401" in str(last_error).lower() or "invalid_api_key" in str(last_error).lower():
            break

    err_msg = f"大模型调用失败: {type(last_error).__name__}: {last_error}"
    log.error("%s. Falling back to structured list.", err_msg)
    errors.append(err_msg)
    return generate_fallback_report(articles_by_source, errors)


