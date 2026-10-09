# -*- coding: utf-8 -*-
"""Unit tests for multi-channel notification dispatcher."""

from unittest.mock import patch, MagicMock
from notifier import dispatch_webhooks, send_wecom_webhook, send_feishu_webhook


def test_dispatch_webhooks_without_env(monkeypatch):
    monkeypatch.delenv("WECOM_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("FEISHU_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DINGTALK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SERVERCHAN_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    results = dispatch_webhooks("Title", "Content")
    assert results == {}


@patch("requests.post")
def test_send_wecom_webhook_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
    mock_post.return_value = mock_resp

    ok = send_wecom_webhook("https://qyapi.weixin.qq.com/webhook/test", "Test Title", "Markdown body")
    assert ok is True
    assert mock_post.called
