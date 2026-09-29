# -*- coding: utf-8 -*-
"""
AI Financial & Geopolitical News Analyzer.
Synthesizes news articles from Bloomberg, Reuters, WSJ, FT, and Lianhe Zaobao,
and provides deep, professional impact analysis on China's economy, financial markets,
and specific industries.
"""

from __future__ import annotations

import logging
from typing import Any
from openai import OpenAI
from config import config
from collector import NewsArticle

log = logging.getLogger("daily-news")

SYSTEM_PROMPT = """你是一名国际顶级宏观对冲基金的首席策略分析师和资深财经主编。
你的任务是根据各大国际权威外媒（彭博社、路透社、华尔街日报、金融时报、联合早报）抓取到的过去24小时财经及中国大陆相关最新消息，撰写一份高水准、严谨专业且极具决策价值的《每日财经与中国宏观深度简报》。

在分析时，请严格遵守以下原则：
1. **客观准确**：严格基于提供的新闻事实，不胡乱编造任何未提及的数据或内幕，区分客观事实与外媒观点。
2. **深度影响分析（核心重点）**：不仅要说明“发生了什么”，必须深入剖析“有什么影响”：
   - **宏观与货币政策**：对中国宏观经济动能、央行货币/财政政策、监管导向的可能传导。
   - **资本市场与汇率**：对A股、港股恒生指数、中概股、离岸人民币（CNH）、中美利差及全球金融资产价格的影响倾向（利好/利空/震荡）。
   - **产业与龙头企业**：对重点产业（如科技/AI/半导体、新能源汽车、房地产、出海贸易、金融）的具体冲击或拉动。
   - **国际地缘与经贸**：外媒报道关注的重点议题、经贸制裁或博弈动向。
3. **输出排版格式**：请使用规范清晰的 Markdown 语法，结构化呈现。保留每条新闻的原文链接。
"""

USER_PROMPT_TEMPLATE = """请基于以下从彭博社、路透社、华尔街日报、金融时报、联合早报抓取的最新新闻资讯，撰写今日份的专业分析简报：

---
{articles_text}
---

请按以下三大部分输出报告（全部使用中文，专业凝练）：

## 🌟 一、今日核心研判与前瞻（Executive Summary）
（提炼 3~5 条对宏观格局、资本市场、中国政策走势有决定性影响的核心结论与洞察，要害明确，直击本质）

## 📊 二、市场与资产影响速查矩阵（Market Impact Matrix）
（以 Markdown 表格形式呈现，包含：资产/领域、影响倾向[🟢利好/🔴利空/🟡震荡分化]、核心驱动逻辑及相关媒体）

## 🔍 三、各家外媒精要与深度影响剖析（In-Depth Analysis）
（按媒体分类：彭博社、路透社、华尔街日报、金融时报、联合早报。针对每家媒体的关键要闻，逐条提供）：
- **[新闻标题]**（附原文链接）
  - 📰 **核心事实**：用1-2句精炼说明关键事件与数据。
  - 💡 **影响分析**：深入分析对中国宏观/政策、金融市场（股市/汇率/债券）或产业企业的具体传导机制与影响。

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
                log.info("Attempting LLM completion with model: %s (attempt %d/3)", cand_model, attempt + 1)
                response = client.chat.completions.create(
                    model=cand_model,
                    temperature=0.3,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                )
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


