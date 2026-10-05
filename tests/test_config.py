# -*- coding: utf-8 -*-
"""Unit tests for configuration routing and provider detection."""

import os
from config import AppConfig


def test_provider_detection_gemini():
    os.environ["GEMINI_API_KEY"] = "AIzaSyTestKey123"
    os.environ["GEMINI_MODEL"] = "gemini-2.5-flash"
    os.environ["DEEPSEEK_API_KEY"] = ""
    os.environ["OPENAI_API_KEY"] = ""
    cfg = AppConfig.load()
    providers = cfg.get_configured_providers()
    assert len(providers) >= 1
    assert providers[0]["name"] == "Google Gemini"
    assert providers[0]["model"] == "gemini-2.5-flash"


def test_provider_detection_deepseek():
    os.environ["GEMINI_API_KEY"] = ""
    os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek-test-key"
    os.environ["OPENAI_API_KEY"] = ""
    cfg = AppConfig.load()
    providers = cfg.get_configured_providers()
    assert len(providers) == 1
    assert providers[0]["name"] == "DeepSeek"
    assert providers[0]["model"] == "deepseek-chat"


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
