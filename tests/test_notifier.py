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


def test_truncate_by_bytes_edge_cases():
    from notifier import _truncate_by_bytes

    long_cn = "中" * 2000
    truncated = _truncate_by_bytes(long_cn, 3000)
    assert len(truncated.encode("utf-8")) <= 3000
    assert truncated.endswith("…")
    assert "\ufffd" not in truncated

    exact = "文" * 100
    assert _truncate_by_bytes(exact, 300) == exact
    assert _truncate_by_bytes(exact, 299) != exact
    assert len(_truncate_by_bytes(exact, 299).encode("utf-8")) <= 299

    mixed = "abc🚀中文" * 100
    mixed_out = _truncate_by_bytes(mixed, 50)
    assert len(mixed_out.encode("utf-8")) <= 50
    assert "\ufffd" not in mixed_out

    assert _truncate_by_bytes("hello", 0) == ""
    assert _truncate_by_bytes("hello", -5) == ""
    assert _truncate_by_bytes("", 100) == ""


@patch("requests.post")
def test_send_wecom_webhook_truncates_to_byte_limit(mock_post):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"errcode": 0, "errmsg": "ok"}
    mock_post.return_value = mock_resp

    ok = send_wecom_webhook("https://qyapi.weixin.qq.com/webhook/test", "超长内容测试", "汉" * 5000)
    assert ok is True
    payload = mock_post.call_args.kwargs["json"]
    content = payload["markdown"]["content"]
    assert len(content.encode("utf-8")) <= 4096
    assert "超长内容测试" in content


@patch("requests.post")
def test_send_telegram_notice_respects_text_limit(mock_post):
    from notifier import send_telegram_notice

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_post.return_value = mock_resp

    ok = send_telegram_notice("token", "chat-id", "标题", "长" * 10000)
    assert ok is True
    payload = mock_post.call_args.kwargs["json"]
    assert len(payload["text"]) <= 4096

    ok = send_telegram_notice("token", "chat-id", "标题", "&" * 6000)
    assert ok is True
    payload = mock_post.call_args.kwargs["json"]
    assert len(payload["text"]) <= 4096
    assert not payload["text"].endswith("&")


def test_dispatch_webhooks_dispatches_all_channels(monkeypatch):
    import notifier

    calls = []

    def make_sender(name):
        def sender(*args):
            calls.append(name)
            return True
        return sender

    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://example.com/wecom")
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.com/feishu")
    monkeypatch.setenv("DINGTALK_WEBHOOK_URL", "https://example.com/dingtalk")
    monkeypatch.setenv("SERVERCHAN_KEY", "sct-test-key")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat-id")

    for channel, attr in (
        ("wecom", "send_wecom_webhook"),
        ("feishu", "send_feishu_webhook"),
        ("dingtalk", "send_dingtalk_webhook"),
        ("serverchan", "send_serverchan_notice"),
        ("telegram", "send_telegram_notice"),
    ):
        monkeypatch.setattr(notifier, attr, make_sender(channel))

    results = dispatch_webhooks("Title", "Content")

    assert results == {
        "wecom": True,
        "feishu": True,
        "dingtalk": True,
        "serverchan": True,
        "telegram": True,
    }
    assert sorted(calls) == sorted(results)


def test_dispatch_webhooks_runs_channels_concurrently(monkeypatch):
    import threading
    import notifier

    barrier = threading.Barrier(2, timeout=5)

    def wait_for_peer(*args):
        barrier.wait()
        return True

    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://example.com/wecom")
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.com/feishu")
    monkeypatch.setattr(notifier, "send_wecom_webhook", wait_for_peer)
    monkeypatch.setattr(notifier, "send_feishu_webhook", wait_for_peer)

    results = dispatch_webhooks("Title", "Content")

    assert results == {"wecom": True, "feishu": True}


def test_dispatch_webhooks_isolates_channel_failure(monkeypatch):
    import notifier

    def failing_sender(*args):
        raise RuntimeError("network down")

    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://example.com/wecom")
    monkeypatch.setenv("FEISHU_WEBHOOK_URL", "https://example.com/feishu")
    monkeypatch.setattr(notifier, "send_wecom_webhook", failing_sender)
    monkeypatch.setattr(notifier, "send_feishu_webhook", lambda *args: True)

    results = dispatch_webhooks("Title", "Content")

    assert results == {"wecom": False, "feishu": True}
