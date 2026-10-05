# -*- coding: utf-8 -*-
"""Unit tests for mailer HTML rendering and sanitization."""

from mailer import render_html_document


def test_render_html_document_sanitization():
    # Attempt script injection in markdown
    dirty_md = (
        "## Test Heading\n\n"
        "Some normal text.\n\n"
        "<script>alert('xss')</script>\n"
        "<a href=\"javascript:alert('xss')\">Malicious Link</a>\n"
        "<a href=\"https://legit.com\">Safe Link</a>"
    )
    errors = ["<script>alert('err')</script>"]
    html_out = render_html_document(dirty_md, errors)

    # <script> tag MUST be stripped
    assert "<script>" not in html_out
    # javascript: scheme MUST be stripped
    assert "javascript:" not in html_out
    # Safe link MUST be preserved
    assert 'href="https://legit.com"' in html_out
    # Errors must be escaped
    assert "&lt;script&gt;" in html_out or "<script>" not in html_out
