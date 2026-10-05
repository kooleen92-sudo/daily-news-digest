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
    assert "**Fake Story**" in sanitized
    # Anchor is preserved
    assert "(#section-1)" in sanitized
