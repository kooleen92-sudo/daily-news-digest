# -*- coding: utf-8 -*-
"""Unit tests for analyzer, prompt budgeting, and link sanitization."""

from datetime import datetime, timezone
from collector import NewsArticle
from analyzer import format_articles_for_prompt, validate_and_sanitize_links


def test_format_articles_for_prompt_token_budget():
    articles_by_source = {
        "彭博社": [
            NewsArticle(
                source="彭博社",
                title="Test Bloomberg Article",
                url="https://bloomberg.com/test",
                summary="A" * 1000,  # 1000 characters
                published_at=datetime.now(timezone.utc),
            )
        ]
    }
    prompt_text = format_articles_for_prompt(articles_by_source, max_summary_chars=250)
    # Ensure summary is capped to roughly 250 chars with ellipsis
    assert len(prompt_text) < 500
    assert "…" in prompt_text


def test_validate_and_sanitize_links():
    valid_url = "https://bloomberg.com/valid-article"
    fake_url = "https://hallucinated-domain.com/fake-article-12345"

    articles_by_source = {
        "彭博社": [
            NewsArticle(
                source="彭博社",
                title="Valid Bloomberg Article",
                url=valid_url,
                summary="Summary",
                published_at=datetime.now(timezone.utc),
            )
        ]
    }

    markdown_input = (
        f"This is a valid link: [Valid Bloomberg Article]({valid_url})\n"
        f"This is a fake link: [Fake Story]({fake_url})\n"
        f"This is an anchor: [Top](#section-1)"
    )

    sanitized = validate_and_sanitize_links(markdown_input, articles_by_source)
    # Valid url is preserved
    assert f"[{valid_url}]" in sanitized or f"({valid_url})" in sanitized
    # Fake url is sanitized to bold text (not a clickable broken link)
    assert fake_url not in sanitized
    # Anchor is preserved
    assert "(#section-1)" in sanitized


def test_validate_report_integrity():
    from analyzer import validate_report_integrity

    # Complete report
    complete_report = """## 🌟 一、今日宏观核心研判与前瞻（Executive Summary）
这里是核心研判内容，全球宏观经济呈现分化，美联储处于政策观望期。

## 💡 二、个人投资与大类资产配置实战指南（Personal Allocation Blueprint）
这里是详尽的个人配置指南，覆盖 A 股操作、公募基金定投、QDII 资产与黄金避险。

| 资产类别 | 稳健型比例 | 进取型比例 |
|---|---|---|
| A股核心资产 | 30% | 45% |
| QDII 全球 | 20% | 30% |

## 📊 三、市场与资产影响速查矩阵（Market Impact Matrix）
| 资产 | 影响倾向 | 逻辑 |
|---|---|---|
| A股 | 🟢利好 | 政策发力 |

## 🔍 四、各家外媒精要与深度影响剖析（In-Depth Analysis）
彭博社：核心要闻解析内容。
""" + ("详细分析文字 " * 150)

    is_valid, issues = validate_report_integrity(complete_report)
    assert is_valid, f"Expected complete report to pass, but got issues: {issues}"
    assert issues == []

    # Incomplete report: missing Module 2 (Personal Allocation Blueprint)
    missing_m2 = complete_report.replace("## 💡 二、个人投资与大类资产配置实战指南（Personal Allocation Blueprint）", "")
    is_valid, issues = validate_report_integrity(missing_m2)
    assert not is_valid
    assert any("缺失【模块二" in issue for issue in issues)

    # Incomplete report: truncated mid-codeblock
    truncated = complete_report + "\n```python\nsome_unclosed_code = 1"
    is_valid, issues = validate_report_integrity(truncated)
    assert not is_valid
    assert any("截断" in issue for issue in issues)


def test_compute_articles_hash():
    from analyzer import compute_articles_hash
    from collector import NewsArticle

    now = datetime.now(timezone.utc)
    articles_set_1 = {
        "彭博社": [NewsArticle(source="彭博社", title="Title 1", url="https://a.com", summary="S1", published_at=now)],
        "路透社": [NewsArticle(source="路透社", title="Title 2", url="https://b.com", summary="S2", published_at=now)]
    }
    articles_set_2 = {
        "路透社": [NewsArticle(source="路透社", title="Title 2", url="https://b.com", summary="S2", published_at=now)],
        "彭博社": [NewsArticle(source="彭博社", title="Title 1", url="https://a.com", summary="S1", published_at=now)]
    }
    articles_set_diff = {
        "彭博社": [NewsArticle(source="彭博社", title="Different Title", url="https://a.com", summary="S1", published_at=now)]
    }

    # Hash should be deterministic regardless of dictionary iteration order
    hash1 = compute_articles_hash(articles_set_1)
    hash2 = compute_articles_hash(articles_set_2)
    hash3 = compute_articles_hash(articles_set_diff)

    assert hash1 == hash2
    assert hash1 != hash3
