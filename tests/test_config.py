# -*- coding: utf-8 -*-
"""Unit tests for configuration routing and provider detection."""

import os
from config import AppConfig


def test_provider_detection_gemini():
    os.environ["GEMINI_API_KEY"] = "AIzaSyTestKey123"
    os.environ["GEMINI_MODEL"] = ""
    os.environ["DEEPSEEK_API_KEY"] = ""
    os.environ["OPENAI_API_KEY"] = ""
    cfg = AppConfig.load()
    providers = cfg.get_configured_providers()
    assert len(providers) >= 1
    assert providers[0]["name"] == "Google Gemini"
    assert providers[0]["model"] in {"gemini-3.5-flash", "gemini-3.8-flash"}
    assert "gemini-3.5-flash" in providers[0]["candidates"]
    assert "gemini-3.8-flash" in providers[0]["candidates"]


def test_provider_detection_deepseek():
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek-test-key"
    os.environ["OPENAI_API_KEY"] = ""
    cfg = AppConfig.load()
    providers = cfg.get_configured_providers()
    assert len(providers) == 1
    assert providers[0]["name"] == "DeepSeek"
    assert providers[0]["model"] in {"deepseek-chat", "deepseek-v4-pro"}


def test_provider_detection_openai_compatible():
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["DEEPSEEK_API_KEY"] = ""
    os.environ["OPENAI_API_KEY"] = "sk-proj-openai-key"
    os.environ["OPENAI_BASE_URL"] = "https://api.openai.com/v1"
    os.environ["LLM_MODEL"] = "gpt-4o-mini"
    cfg = AppConfig.load()
    providers = cfg.get_configured_providers()
    assert len(providers) == 1
    assert providers[0]["name"] == "OpenAI / Compatible"
    assert providers[0]["model"] == "gpt-4o-mini"
    assert "openai.com" in providers[0]["base_url"]


def test_config_validation():
    # Valid configuration
    valid_cfg = AppConfig(
        digest_time="07:35",
        digest_timezone="Asia/Shanghai",
        lookback_hours=24,
        max_items_per_source=5,
        dedupe_similarity=0.85,
        output_retention_days=7,
        gemini_api_key="AIzaSyValidKey",
        mail_to="user@example.com",
        smtp_host="smtp.qq.com",
        smtp_port=465,
        smtp_use_ssl=True,
        smtp_use_tls=False
    )
    assert valid_cfg.validate() == []

    # Invalid configuration (bad time, bad timezone, port out of range, SSL/TLS conflict, no API keys)
    invalid_cfg = AppConfig(
        digest_time="25:99",
        digest_timezone="Mars/Olympus",
        lookback_hours=-1,
        max_items_per_source=0,
        dedupe_similarity=1.5,
        output_retention_days=0,
        gemini_api_key="",
        deepseek_api_key="",
        openai_api_key="",
        mail_to="not-an-email",
        smtp_host="",
        smtp_port=99999,
        smtp_use_ssl=True,
        smtp_use_tls=True
    )
    errors = invalid_cfg.validate()
    assert len(errors) >= 7
    assert any("DIGEST_TIME" in e for e in errors)
    assert any("DIGEST_TIMEZONE" in e for e in errors)
    assert any("MAIL_TO" in e for e in errors)
    assert any("SMTP_PORT" in e for e in errors)
    assert any("SMTP_USE_SSL 和 SMTP_USE_TLS" in e for e in errors)
    assert any("未检测到任何可用的 AI 模型提供商配置" in e for e in errors)


def test_get_config_reload():
    from config import get_config
    cfg1 = get_config()
    cfg2 = get_config(reload=True)
    assert cfg1.digest_time == cfg2.digest_time

