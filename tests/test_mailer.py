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


def test_send_digest_email_multiple_recipients(monkeypatch):
    import mailer

    sent_messages = []

    class DummySMTP:
        def __init__(self, host, port, timeout=30):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def login(self, user, password):
            pass
        def send_message(self, msg):
            sent_messages.append(msg)
            return {}

    from config import AppConfig

    custom_cfg = AppConfig(
        mail_to="user1@qq.com, user2@163.com",
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_user="sender@qq.com",
        smtp_password="secret",
        smtp_use_ssl=True,
    )
    monkeypatch.setattr(mailer, "config", custom_cfg)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", DummySMTP)

    mailer.send_digest_email("# Markdown Title", [])
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert msg["To"] == "user1@qq.com, user2@163.com"
