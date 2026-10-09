# -*- coding: utf-8 -*-
"""
AI Financial & Geopolitical News Analyzer.
Synthesizes news articles from Bloomberg, Reuters, WSJ, FT, Lianhe Zaobao,
Nikkei Chinese, and The Economist, providing deep, professional impact analysis
on China's economy, financial markets, and personal asset allocation.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import openai
from openai import OpenAI
from config import BASE_DIR, config
from collector import NewsArticle
from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, REPORT_DISCLAIMER
from market_data import MarketQuote, format_market_context_for_prompt, render_market_table

log = logging.getLogger("daily-news")



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

    return re.sub(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", replace_link, markdown_content)


def validate_report_integrity(markdown_report: str) -> tuple[bool, list[str]]:
    """
    Validate that the generated markdown report meets structural integrity standards:
    - Contains all 4 required modules (especially Module 2: Personal Allocation Blueprint).
    - Contains the asset allocation table or matrix.
    - Not truncated prematurely.
    - Sufficient substance/length.

    Returns:
        (is_valid: bool, issues: list[str])
    """
    issues = []
    if not markdown_report or len(markdown_report.strip()) < 1000:
        issues.append(f"报告长度过短 (仅 {len(markdown_report.strip()) if markdown_report else 0} 字符)")
        return False, issues

    # Module 1 Check
    has_m1 = bool(re.search(r"##\s*.*一[、\s\.:].*(宏观|研判|Executive Summary)", markdown_report))
    if not has_m1:
        issues.append("缺失【模块一：今日宏观核心研判与前瞻】")

    # Module 2 Check (CRITICAL)
    has_m2 = bool(re.search(r"##\s*.*二[、\s\.:].*(个人投资|资产配置|Personal Allocation)", markdown_report))
    if not has_m2:
        issues.append("缺失【模块二：个人投资与大类资产配置实战指南】")

    # Module 3 Check
    has_m3 = bool(re.search(r"##\s*.*三[、\s\.:].*(市场|资产影响|速查矩阵|Market Impact Matrix)", markdown_report))
    if not has_m3:
        issues.append("缺失【模块三：市场与资产影响速查矩阵】")

    # Module 4 Check
    has_m4 = bool(re.search(r"##\s*.*四[、\s\.:].*(各家外媒|外媒精要|深度影响|In-Depth Analysis)", markdown_report))
    if not has_m4:
        issues.append("缺失【模块四：各家外媒精要与深度影响剖析】")

    # Check for Markdown table presence
    has_table = bool(re.search(r"\|.+\|.+\|\n\|[-:\s|]+\|", markdown_report))
    if not has_table:
        issues.append("缺失资产配置或市场影响速查 Markdown 表格")

    # Truncation check
    stripped = markdown_report.strip()
    if stripped.count("```") % 2 != 0:
        issues.append("报告存在未闭合代码块，疑似被截断")
    if stripped.endswith("##") or stripped.endswith("###") or stripped.endswith("|"):
        issues.append("报告在标题或表格处异常中断，疑似被截断")

    is_valid = len(issues) == 0
    return is_valid, issues


def compute_articles_hash(articles_by_source: dict[str, list[NewsArticle]]) -> str:
    """Calculate MD5 fingerprint of the scraped articles for idempotent caching."""
    hasher = hashlib.md5()
    hasher.update(b"cache-schema-v3")
    for src in sorted(articles_by_source.keys()):
        sorted_articles = sorted(
            articles_by_source[src],
            key=lambda a: (a.url.strip(), a.title.strip(), (a.summary or "").strip(), a.published_at.isoformat()),
        )
        for a in sorted_articles:
            hasher.update(a.source.strip().encode("utf-8"))
            hasher.update(a.url.strip().encode("utf-8"))
            hasher.update(a.title.strip().encode("utf-8"))
            hasher.update((a.summary or "").strip().encode("utf-8"))
            hasher.update(a.published_at.isoformat().encode("utf-8"))
    return hasher.hexdigest()


def _get_cache_path() -> Path:
    cache_dir = BASE_DIR / "output"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / ".cache_digest.json"


def get_cached_analysis(articles_hash: str) -> str | None:
    """Return cached report if hash matches and was created today in target timezone."""
    cache_file = _get_cache_path()
    if not cache_file.exists():
        return None
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        if data.get("hash") == articles_hash:
            cached_date = data.get("created_at", "")[:10]
            tz = ZoneInfo(config.digest_timezone)
            today_str = datetime.now(tz).strftime("%Y-%m-%d")
            if cached_date == today_str and data.get("report"):
                return data["report"]
    except Exception as e:
        log.debug("读取分析缓存异常: %s", e)
    return None


def save_cached_analysis(articles_hash: str, report: str) -> None:
    """Persist generated report to local cache for idempotency."""
    cache_file = _get_cache_path()
    try:
        tz = ZoneInfo(config.digest_timezone)
        cache_data = {
            "hash": articles_hash,
            "created_at": datetime.now(tz).isoformat(),
            "report": report
        }
        fd, temp_path = tempfile.mkstemp(
            prefix=f"{cache_file.name}.",
            suffix=".tmp",
            dir=cache_file.parent,
        )
        temp_file = Path(temp_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(cache_data, fh, ensure_ascii=False, indent=2)
            os.replace(temp_file, cache_file)
        finally:
            if temp_file.exists():
                temp_file.unlink()
    except Exception as e:
        log.debug("写入分析缓存异常: %s", e)


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


def generate_fallback_report(
    articles_by_source: dict[str, list[NewsArticle]],
    errors: list[str],
    market_quotes: list[MarketQuote] | None = None
) -> str:
    """Generate a clean, structured fallback report when LLM is unavailable."""
    lines = []
    if market_quotes:
        lines.append(render_market_table(market_quotes))
        lines.append("")

    lines.extend([
        "## 📌 简报速览（未启用大模型智能分析兜底模式）\n",
        "> 说明：当前未配置 `OPENAI_API_KEY` 或大模型调用超时，以下按来源整理各媒体最新抓取到的财经与中国要闻及原文链接。\n"
    ])


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
    """Execute LLM call across a list of candidate models with typed error handling and exponential retry."""
    if not api_key:
        return None, ValueError(f"{provider_name} API Key 未配置")

    # Normalize base_url
    if base_url and "googleapis.com" in base_url and not base_url.endswith("/openai/"):
        base_url = base_url.rstrip("/") + "/openai/"

    # For Gemini, cap single-call timeout to 60s to avoid hanging CI runners
    call_timeout = 60.0 if (base_url and "googleapis.com" in base_url) else config.llm_timeout

    client_kwargs: dict[str, Any] = {
        "api_key": api_key.strip(),
        "timeout": call_timeout,
        "max_retries": 1,
    }
    if base_url:
        client_kwargs["base_url"] = base_url.strip()

    client = OpenAI(**client_kwargs)
    last_error: Exception | None = None
    best_partial_content: str | None = None

    for cand_model in candidate_models:
        model_name = cand_model.strip()
        for attempt in range(3):
            try:
                log.info("[%s] 正在调用模型: %s (第 %d/3 次尝试)...", provider_name, model_name, attempt + 1)
                max_tokens = 16384 if ("pro" in model_name or "reasoner" in model_name) else 8192
                create_kwargs = {
                    "model": model_name,
                    "temperature": 0.3,
                    "max_tokens": max_tokens,
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
                    content_clean = content.strip()
                    is_valid, _ = validate_report_integrity(content_clean)

                    # 最佳情况：完整生成且通过完整性校验
                    if is_valid and finish_reason != "length":
                        log.info("[%s] 成功生成完整分析报告！模型: %s", provider_name, model_name)
                        return content_clean, None

                    # 触及 token 上限时的容错处理
                    elif finish_reason == "length":
                        if is_valid:
                            log.warning("[%s] 模型 '%s' 输出触及 token 上限，但已完整包含全部核心模块（字数: %d），予以采纳！",
                                        provider_name, model_name, len(content_clean))
                            return content_clean, None

                        if not best_partial_content or len(content_clean) > len(best_partial_content):
                            best_partial_content = content_clean

                        log.warning("[%s] 模型 '%s' 输出触及 token 上限且未完整生成四大核心模块，准备切换下一个候选模型...", provider_name, model_name)
                        break  # 切换到下一个候选模型，避免无谓重试相同被截断的模型

                    elif is_valid:
                        log.info("[%s] 成功生成分析报告！模型: %s", provider_name, model_name)
                        return content_clean, None

            except openai.AuthenticationError as exc:
                log.error("[%s] 鉴权失败 (API Key 无效或未授权): %s", provider_name, exc)
                return None, exc

            except openai.NotFoundError as exc:
                log.warning("[%s] 模型 '%s' 不存在或已被下线 (404): %s", provider_name, model_name, exc)
                last_error = exc
                break  # 立即切换到候选池中的下一个模型

            except openai.APITimeoutError as exc:
                last_error = exc
                log.warning("[%s] 模型 '%s' 调用超时 (已耗时 %.0fs)，快速切换至下一候选模型...", provider_name, model_name, call_timeout)
                break  # 超时表明当前模型节点或网络卡死，不再重复等待，直接切换模型

            except (openai.RateLimitError, openai.APIConnectionError, openai.InternalServerError) as exc:
                last_error = exc
                log.warning("[%s] 模型 '%s' 临时服务异常 (%s): %s", provider_name, model_name, type(exc).__name__, exc)
                if attempt == 0:
                    wait_sec = 2
                    log.info("[%s] 节点繁忙 (503/429)，暂停 %d 秒后重试...", provider_name, wait_sec)
                    time.sleep(wait_sec)
                    continue
                else:
                    log.info("[%s] 模型 '%s' 持续繁忙，立即切换候选池下一模型...", provider_name, model_name)
                    break

            except Exception as exc:
                last_error = exc
                log.warning("[%s] 模型 '%s' 调用异常: %s: %s", provider_name, model_name, type(exc).__name__, exc)
                # Check status code if available
                status_code = getattr(exc, "status_code", None)
                if status_code == 401:
                    log.error("[%s] 鉴权失败 (HTTP 401)，终止该厂商重试。", provider_name)
                    return None, last_error
                if status_code == 404:
                    break

    # 若所有尝试均由于长度原因未完全达标，但保留了高质量长篇生成内容且通过完整性校验，则兜底采纳
    if best_partial_content and len(best_partial_content) > 1000:
        is_valid, _ = validate_report_integrity(best_partial_content)
        if is_valid:
            log.warning("[%s] 所有候选模型调用完毕，兜底采纳保留的高质量分析内容（字数: %d）。",
                        provider_name, len(best_partial_content))
            return best_partial_content, None

    return None, last_error


def analyze_news(
    articles_by_source: dict[str, list[NewsArticle]],
    errors: list[str],
    market_quotes: list[MarketQuote] | None = None
) -> str:
    """
    Generate deep impact analysis with two-tier prioritized architecture:
    1. Priority 1: Google Gemini
    2. Priority 2: DeepSeek
    3. Priority 3: Standard OpenAI compatible provider
    4. Priority 4: Structured news list fallback (if all fail or unconfigured)
    """
    total_articles = sum(len(items) for items in articles_by_source.values())
    if total_articles == 0:
        return "## 暂无新闻\n\n过去 24 小时未抓取到符合条件的财经及中国大陆新闻。"

    market_context = format_market_context_for_prompt(market_quotes) if market_quotes else "（未提供实时行情数据）"
    market_table = render_market_table(market_quotes) if market_quotes else ""

    articles_text = format_articles_for_prompt(articles_by_source)
    prompt = USER_PROMPT_TEMPLATE.format(
        market_context=market_context,
        articles_text=articles_text
    )

    articles_hash = compute_articles_hash(articles_by_source)
    cached_report = get_cached_analysis(articles_hash)
    if cached_report:
        log.info("🎯 命中今日相同新闻集分析缓存 (MD5: %s)，直接复用高质量研报，节省大模型 Token 与耗时。", articles_hash[:8])
        return cached_report

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
            is_valid, issues = validate_report_integrity(content)
            if not is_valid:
                warn_msg = f"{p['name']} 生成内容未通过完整性校验 ({'; '.join(issues)})"
                log.warning("%s。准备切换下一个引擎重新生成完整报告...", warn_msg)
                errors.append(warn_msg)
                continue

            cleaned_content = validate_and_sanitize_links(content, articles_by_source)
            footer_note = f"\n\n---\n*🤖 本期研报由 {p['name']} 智能引擎分析生成*"

            # Position market table cleanly below H1 title if present, otherwise prepend
            if market_table:
                if cleaned_content.startswith("# ") and "\n" in cleaned_content:
                    h1_line, body_rest = cleaned_content.split("\n", 1)
                    body_with_table = h1_line + "\n\n" + market_table + "\n" + body_rest
                else:
                    body_with_table = market_table + "\n\n" + cleaned_content
            else:
                body_with_table = cleaned_content

            final_report = body_with_table + footer_note + "\n" + REPORT_DISCLAIMER
            save_cached_analysis(articles_hash, final_report)
            return final_report

        else:
            warn_msg = f"{p['name']} 尝试失败: {type(err).__name__}: {err}"
            log.warning("%s。准备尝试下一个备用引擎...", warn_msg)
            errors.append(warn_msg)

    # 最终兜底排版（无大模型或全部超时报错）
    log.warning("所有大模型均未配置或调用失败，使用结构化新闻列表兜底排版。")
    return generate_fallback_report(articles_by_source, errors, market_quotes=market_quotes)

