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
你的任务是根据各大国际权威外媒（彭博社、路透社、华尔街日报、金融时报、联合早报、日经中文网、经济学人）抓取到的过去24小时财经及中国大陆相关最新消息，撰写一份高水准、严谨专业且极具决策与实操价值的《每日财经与中国宏观深度简报》。

在分析时，请严格遵守以下原则：
1. **客观准确**：严格基于提供的新闻事实，不胡乱编造任何未提及的数据或内幕，区分客观事实与外媒观点。
2. **个人投资与大类资产配置指引（全篇核心灵魂与重点）**：必须结合当日最新宏观要闻与政策风向，面向中国个人投资者给出落地的投资操作与资产配置指引，覆盖：
   - **A股股票（沪深主板及双创板）**：主板蓝筹/高股息红利 vs 科技成长板块的操作策略与仓位控制建议。
   - **公募基金（场内ETF与场外基金）**：宽基ETF、行业主题ETF的交易时机，以及场外定投/固收底仓策略。
   - **QDII基金（场内/场外）**：美股核心资产（纳指100/标普500）、全球半导体QDII的配置节奏与溢价风险警示。
   - **黄金与贵金属**：黄金ETF、积存金的逢低布局或避险配置比例。
   - **推荐资产配置比例表格**：稳健型 vs 进取型资产分布。
3. **结构完整，杜绝截断**：严格把控各部分篇幅分配，第四模块外媒要闻分析务必精炼有力（每条控制在 80~100 字内），确保所有四大模块 100% 完整输出到底。
4. **输出排版格式**：请使用规范清晰的 Markdown 语法，结构化呈现。保留每条新闻的原文链接。
"""

USER_PROMPT_TEMPLATE = """请基于以下从彭博社、路透社、华尔街日报、金融时报、联合早报、日经中文网、经济学人抓取的最新新闻资讯，撰写今日份的专业宏观分析与个人投资配置报告：

---
{articles_text}
---

请按以下四大模块顺序完整输出报告（全部使用中文，专业、严谨、排版美观）：

## 🌟 一、今日宏观核心研判与前瞻（Executive Summary）
（提炼 3~5 条对宏观格局、资本市场、中国政策走势有决定性影响的核心结论与洞察，直击本质）

## 💡 二、个人投资与大类资产配置实战指南（Personal Allocation Blueprint）
（【核心重点模块】：结合今日宏观政策与外媒动向，面向个人投资者输出切实可行的落地配置建议）：
1. **A股股票操作策略（沪深主板 / 创业板 / 科创板）**：
   - **沪深主板**（高股息红利资产、中字头央企、大金融/周期/消费）：进攻还是防御？建仓与波段节奏。
   - **双创与成长板块**（半导体/自主可控、AI产业链、新能源）：外围地缘与科技博弈下的波段或防御思路。
   - **整体仓位建议**：建议权益仓位控制区间（例如几成仓位）及买卖节奏。
2. **公募基金配置指南（场内ETF & 场外基金）**：
   - **场内 ETF 实操**：宽基（如沪深300 ETF、中证A500 ETF、恒生科技 ETF）与行业主题（红利低波、芯片、医药等）的操作思路。
   - **场外基金策略**：定投频率（加仓/观望）、固收+及纯债基金的安全垫配置比例。
3. **QDII 基金配置指南（场内 / 场外全球资产）**：
   - **美股与全球资产**（纳指100 ETF、标普500 ETF、全球芯片科技 QDII）：配置逻辑、防范场内高溢价风险及定投买入点。
4. **黄金与贵金属资产配置指南（避险抗通胀）**：
   - 黄金 ETF、银行积存金/实物金配置建议；结合美联储降息节奏与地缘冲突，给出配置比例（如 5%~15%）及加仓/定投时机。
5. **推荐资产配置比例速查（稳健型 vs 进取型）**：
   - 用 Markdown 表格列出当前推荐的配置比例（A股核心权益 %、QDII全球多元 %、黄金避险 %、现金与固收纯债 %），并做简要风控提醒。

## 📊 三、市场与资产影响速查矩阵（Market Impact Matrix）
（以 Markdown 表格形式呈现，包含：资产/领域、影响倾向[🟢利好/🔴利空/🟡震荡分化]、核心驱动逻辑及相关媒体）

## 🔍 四、各家外媒精要与深度影响剖析（In-Depth Analysis）
（按媒体分类：彭博社、路透社、华尔街日报、金融时报、联合早报、日经中文网、经济学人。针对每家媒体，重点精选 1~2 条最具宏观影响力或市场传导效应的核心要闻进行深度剖析，其余新闻已在第三模块矩阵中体现无需赘述展开；每条文字务必精炼，控制在 60~80 字内）：
- **[新闻标题]**（附原文链接）
  - 📰 **核心事实**：用 1 句精炼说明关键事件与数据。
  - 💡 **影响分析**：用 1~2 句深入分析对中国宏观/政策、金融市场或产业企业的具体传导机制。

【输出纪律】：请合理把控全篇文字密度（总字数控制在 3500~5000 字以内），严格按上述一至四的顺序完整输出全部内容，杜绝因冗长而在末尾被截断。"""



def validate_and_sanitize_links(markdown_content: str, articles_by_source: dict[str, list[NewsArticle]]) -> str:
    """Ensure links in generated report match actual scraped articles, suppressing hallucinated links."""
    valid_urls = set()
    title_to_url = {}
    for items in articles_by_source.values():
        for a in items:
            valid_urls.add(a.url.strip())
            title_to_url[a.title.strip()] = a.url.strip()

    def replace_link(match: re.Match) -> str:
        anchor_text = match.group(1).strip()
        url = match.group(2).strip()
        if url in valid_urls or url.startswith("#"):
            return match.group(0)
        # Try matching title
        if anchor_text in title_to_url:
            return f"[{anchor_text}]({title_to_url[anchor_text]})"
        # If url domain is totally fabricated or invalid, fallback to anchor text
        return f"**{anchor_text}**"

    import re
    return re.sub(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", replace_link, markdown_content)


def format_articles_for_prompt(articles_by_source: dict[str, list[NewsArticle]], max_summary_chars: int = 250) -> str:
    """Format structured articles into a prompt context with strict token budget."""
    blocks = []
    item_index = 1
    
    for source_name, items in articles_by_source.items():
        if not items:
            continue
        blocks.append(f"### 【{source_name}】（共 {len(items)} 条）")
        for a in items:
            pub_str = a.published_at.strftime("%Y-%m-%d %H:%M UTC")
            summary_raw = a.summary or "（无摘要，参见标题）"
            if len(summary_raw) > max_summary_chars:
                summary_raw = summary_raw[:max_summary_chars] + "…"
            blocks.append(
                f"[{item_index}] 来源：{a.source}\n"
                f"标题：{a.title}\n"
                f"发布时间：{pub_str}\n"
                f"链接：{a.url}\n"
                f"摘要/导语：{summary_raw}\n"
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


def _call_llm_provider(
    provider_name: str,
    api_key: str,
    base_url: str | None,
    candidate_models: list[str],
    prompt: str,
) -> tuple[str | None, Exception | None]:
    """Execute LLM call across a list of candidate models with exponential retry."""
    if not api_key:
        return None, ValueError(f"{provider_name} API Key 未配置")

    # Normalize base_url
    if base_url and "googleapis.com" in base_url and not base_url.endswith("/openai/"):
        base_url = base_url.rstrip("/") + "/openai/"

    client_kwargs = {
        "api_key": api_key.strip(),
        "timeout": config.llm_timeout,
        "max_retries": 1,
    }
    if base_url:
        client_kwargs["base_url"] = base_url.strip()

    client = OpenAI(**client_kwargs)
    last_error: Exception | None = None

    best_partial_content: str | None = None

    for cand_model in candidate_models:
        clean_model = cand_model.strip().lower().replace(" ", "-")
        for attempt in range(3):
            try:
                log.info("[%s] 正在调用模型: %s (第 %d/3 次尝试)...", provider_name, clean_model, attempt + 1)
                create_kwargs = {
                    "model": clean_model,
                    "temperature": 0.3,
                    "max_tokens": 8192,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                }
                response = client.chat.completions.create(**create_kwargs)
                choice = response.choices[0]
                content = choice.message.content
                finish_reason = getattr(choice, "finish_reason", None)

                if content and len(content.strip()) > 50:
                    has_allocation = ("个人投资" in content or "资产配置" in content)
                    content_clean = content.strip()

                    # 最佳情况：完整生成且包含核心个人资产配置
                    if has_allocation and finish_reason != "length":
                        log.info("[%s] 成功生成完整分析报告（含个人资产配置模块）！模型: %s", provider_name, clean_model)
                        return content_clean, None

                    # 触及 token 上限时的容错处理
                    elif finish_reason == "length":
                        # 若核心模块（宏观研判与个人资产配置）已在前部完整生成且篇幅充实（>1500字），予以正常采纳
                        if has_allocation and len(content_clean) > 1500:
                            log.warning("[%s] 模型 '%s' 输出触及 token 上限，但核心模块（宏观研判与个人资产配置）已完整生成（字数: %d），予以采纳！",
                                        provider_name, clean_model, len(content_clean))
                            return content_clean, None

                        # 保存作为最终备选兜底
                        if not best_partial_content or len(content_clean) > len(best_partial_content):
                            best_partial_content = content_clean

                        log.warning("[%s] 模型 '%s' 输出触及 token 上限且缺少核心模块，准备重试...", provider_name, clean_model)
                        if attempt < 2:
                            continue

                    else:
                        log.info("[%s] 成功生成分析报告！模型: %s", provider_name, clean_model)
                        return content_clean, None
            except Exception as exc:
                last_error = exc
                err_str = str(exc).lower()
                log.warning("[%s] 模型 '%s' 第 %d 次尝试未成功: %s: %s", provider_name, clean_model, attempt + 1, type(exc).__name__, exc)

                # If authentication failed, abort immediately
                if "401" in err_str or "invalid_api_key" in err_str or "unauthenticated" in err_str:
                    log.error("[%s] 鉴权失败，终止该厂商重试。", provider_name)
                    return None, last_error

                # If model is retired or not found, switch immediately to next candidate
                if "404" in err_str or "not found" in err_str or "no longer available" in err_str:
                    break

                # If 503 (high demand) or 429 (rate limit), wait and retry
                if ("503" in err_str or "unavailable" in err_str or "high demand" in err_str or "429" in err_str) and attempt < 2:
                    wait_sec = 4 * (attempt + 1)
                    log.info("[%s] 节点繁忙（503/429），暂停 %d 秒后进行重试...", provider_name, wait_sec)
                    time.sleep(wait_sec)
                    continue

    # 若所有尝试均由于长度原因未完全达标，但保留了高质量长篇生成内容，则兜底采纳
    if best_partial_content and len(best_partial_content) > 1000:
        log.warning("[%s] 所有候选模型调用完毕，兜底采纳保留的高质量分析内容（字数: %d）。",
                    provider_name, len(best_partial_content))
        return best_partial_content, None

    return None, last_error


def analyze_news(articles_by_source: dict[str, list[NewsArticle]], errors: list[str]) -> str:
    """
    Generate deep impact analysis with two-tier prioritized architecture:
    1. Priority 1: Google Gemini (latest pro/flash models)
    2. Priority 2: DeepSeek (failsafe failover if Gemini is overloaded or fails)
    3. Priority 3: Structured news list fallback (if both fail or are unconfigured)
    """
    total_articles = sum(len(items) for items in articles_by_source.values())
    if total_articles == 0:
        return "## 暂无新闻\n\n过去 24 小时未抓取到符合条件的财经及中国大陆新闻。"

    articles_text = format_articles_for_prompt(articles_by_source)
    prompt = USER_PROMPT_TEMPLATE.format(articles_text=articles_text)

    providers = config.get_configured_providers()
    for idx, p in enumerate(providers, 1):
        log.info("【Tier %d】尝试使用 %s 引擎（模型: %s）进行深度分析...", idx, p["name"], p["model"])
        content, err = _call_llm_provider(
            provider_name=p["name"],
            api_key=p["api_key"],
            base_url=p["base_url"],
            candidate_models=p["candidates"],
            prompt=prompt,
        )
        if content:
            footer_note = f"\n\n---\n*🤖 本期研报由 {p['name']} 智能引擎分析生成*"
            cleaned_content = validate_and_sanitize_links(content, articles_by_source)
            return cleaned_content + footer_note
        else:
            warn_msg = f"{p['name']} 尝试失败: {type(err).__name__}: {err}"
            log.warning("%s。准备尝试下一个备用引擎...", warn_msg)
            errors.append(warn_msg)

    # -------------------------------------------------------------
    # Tier 4: 最终兜底排版（无大模型或全部超时报错）
    # -------------------------------------------------------------
    log.warning("所有大模型均未配置或调用失败，使用结构化新闻列表兜底排版。")
    return generate_fallback_report(articles_by_source, errors)



