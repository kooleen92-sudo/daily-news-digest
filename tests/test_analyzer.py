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


def test_report_disclaimer_present():
    from prompts import REPORT_DISCLAIMER
    assert "免责声明与风险提示" in REPORT_DISCLAIMER
    assert "不构成任何实质性买卖建议" in REPORT_DISCLAIMER


def test_cache_date_timezone_aware(tmp_path, monkeypatch):
    from analyzer import save_cached_analysis, get_cached_analysis
    from config import config

    test_hash = "abcdef0123456789"
    test_report = "## 🌟 一、今日宏观核心研判与前瞻\n内容\n## 💡 二、个人投资与大类资产配置实战指南\n内容\n| a | b |\n|---|---|\n## 📊 三、市场与资产影响速查矩阵\n内容\n## 🔍 四、各家外媒精要与深度影响剖析\n内容\n"

    # Point cache dir to tmp_path
    monkeypatch.setattr("analyzer._get_cache_path", lambda: tmp_path / ".cache_digest.json")

    save_cached_analysis(test_hash, test_report)
    loaded = get_cached_analysis(test_hash)
    assert loaded == test_report


def test_validate_report_integrity_accepts_heading_variants():
    from analyzer import validate_report_integrity

    template = """# 今日宏观简报

## 一、今日宏观核心研判与前瞻（Executive Summary）
全球宏观核心研判内容，美联储处于政策观望期。

## 二、个人投资与大类资产配置实战指南（Personal Allocation Blueprint）
个人配置实战指南内容，覆盖 A 股、基金、QDII 与黄金。

| 资产类别 | 稳健型比例 | 进取型比例 |
|---|---|---|
| A股核心资产 | 30% | 45% |

## 三、市场与资产影响速查矩阵（Market Impact Matrix）
| 资产 | 影响倾向 | 逻辑 |
|---|---|---|
| A股 | 🟢利好 | 政策发力 |

## 四、各家外媒精要与深度影响剖析（In-Depth Analysis）
外媒深度分析内容。
""" + ("详细分析文字 " * 150)

    original_headings = (
        "## 一、今日宏观核心研判与前瞻（Executive Summary）",
        "## 二、个人投资与大类资产配置实战指南（Personal Allocation Blueprint）",
        "## 三、市场与资产影响速查矩阵（Market Impact Matrix）",
        "## 四、各家外媒精要与深度影响剖析（In-Depth Analysis）",
    )
    variants = [
        ("### 一、今日宏观核心研判与前瞻", "### 二、个人投资与大类资产配置实战指南",
         "### 三、市场与资产影响速查矩阵", "### 四、各家外媒精要与深度影响剖析"),
        ("# 1. 今日宏观核心研判与前瞻", "# 2. 个人投资与大类资产配置实战指南",
         "# 3. 市场与资产影响速查矩阵", "# 4. 各家外媒精要与深度影响剖析"),
        ("**一、今日宏观核心研判与前瞻**", "**二、个人投资与大类资产配置实战指南**",
         "**三、市场与资产影响速查矩阵**", "**四、各家外媒精要与深度影响剖析**"),
    ]

    for variant in variants:
        report = template
        for old, new in zip(original_headings, variant):
            report = report.replace(old, new)
        is_valid, issues = validate_report_integrity(report)
        assert is_valid, f"标题变体应通过校验: {variant} -> {issues}"


def test_no_news_report_is_deliverable():
    from analyzer import analyze_news
    from prompts import REPORT_DISCLAIMER

    report = analyze_news({}, ["彭博社：未能成功拉取更新"])
    assert "暂无" in report
    assert "彭博社：未能成功拉取更新" in report
    assert REPORT_DISCLAIMER.strip() in report


def _build_valid_report():
    return (
        "# 今日简报\n\n"
        "## 一、今日宏观核心研判与前瞻（Executive Summary）\n" + "宏观研判内容。" * 10 + "\n\n"
        "## 二、个人投资与大类资产配置实战指南（Personal Allocation Blueprint）\n" + "配置指南内容。" * 10 + "\n\n"
        "| 资产类别 | 稳健型 | 进取型 |\n|---|---|---|\n| A股 | 30% | 45% |\n\n"
        "## 三、市场与资产影响速查矩阵（Market Impact Matrix）\n" + "矩阵内容。" * 10 + "\n\n"
        "## 四、各家外媒精要与深度影响剖析（In-Depth Analysis）\n" + "外媒分析内容。" * 150
    )


def _make_fake_openai(monkeypatch, responses):
    """Patch analyzer.OpenAI with a fake client returning queued (content, finish_reason) pairs."""
    import analyzer
    from types import SimpleNamespace

    calls = []

    class _FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            content, finish_reason = responses.pop(0)
            choice = SimpleNamespace(message=SimpleNamespace(content=content), finish_reason=finish_reason)
            return SimpleNamespace(choices=[choice])

    class _FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setattr(analyzer, "OpenAI", _FakeClient)
    return calls


def test_call_llm_provider_skips_blind_retry_on_invalid_format(monkeypatch):
    import analyzer

    valid_report = _build_valid_report()
    responses = [
        ("无结构内容。" * 20, "stop"),
        (valid_report, "stop"),
    ]
    calls = _make_fake_openai(monkeypatch, responses)

    content, err = analyzer._call_llm_provider(
        provider_name="FakeProvider",
        api_key="sk-test",
        base_url="https://example.com/v1",
        candidate_models=["m1", "m2"],
        prompt="prompt",
    )

    assert err is None
    assert content == valid_report
    # m1 不合格后只调用一次（不再盲目重试），m2 调用一次
    assert len(calls) == 2


def test_call_llm_provider_continues_truncated_report(monkeypatch):
    import analyzer

    full_report = _build_valid_report()
    marker = "## 三、市场与资产影响速查矩阵（Market Impact Matrix）"
    head, tail_body = full_report.split(marker, 1)
    partial = head.rstrip("\n")
    tail = marker + tail_body

    responses = [
        (partial, "length"),
        (tail, "stop"),
    ]
    calls = _make_fake_openai(monkeypatch, responses)

    content, err = analyzer._call_llm_provider(
        provider_name="FakeProvider",
        api_key="sk-test",
        base_url="https://example.com/v1",
        candidate_models=["m1"],
        prompt="prompt",
    )

    assert err is None
    assert content == partial + "\n" + tail
    assert len(calls) == 2
    assert calls[1]["messages"][2]["role"] == "assistant"
    assert calls[1]["messages"][2]["content"] == partial
    assert "继续" in calls[1]["messages"][3]["content"]

