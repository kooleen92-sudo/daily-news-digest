# -*- coding: utf-8 -*-
"""
Configuration management for Daily News & Impact Digest.
Reads settings from environment variables and .env file.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()


# 官方弃用清单: https://ai.google.dev/gemini-api/docs/deprecations
DEPRECATED_GEMINI_MODELS = frozenset({
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3-pro-preview",
    "gemini-3.1-flash-lite-preview",
})

log = logging.getLogger("daily-news")

# 同一次运行内，同一弃用模型只告警一次（get_configured_providers 会被多次调用）
_warned_deprecated_gemini: set[str] = set()


@dataclass(frozen=True)
class AppConfig:
    # Schedule
    digest_time: str = "08:00"
    digest_timezone: str = "Asia/Shanghai"
    lookback_hours: int = 24
    max_items_per_source: int = 5
    fetch_timeout: float = 15.0
    dedupe_similarity: float = 0.85

    # Legacy / General LLM Settings
    openai_api_key: str = ""
    openai_base_url: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 90.0
    llm_max_tokens: int = 8192
    llm_max_tokens_large: int = 16384

    # Dedicated Gemini Settings (Priority 1)
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-3.8-flash"

    # Dedicated DeepSeek Settings (Priority 2 / Fallback)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-v4-pro"

    # Email Settings
    mail_to: str = ""
    mail_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_ssl: bool = True
    smtp_use_tls: bool = False

    # Output & Maintenance Settings
    output_retention_days: int = 7
    compress_image: bool = True

    # Collector Settings
    resolve_google_news: bool = True

    # Externalized Topics & Persona Configuration (from config/topics.yaml)
    topics_config: dict[str, Any] = field(default_factory=dict)


    def deprecated_gemini_model(self) -> str | None:
        """Return the configured Gemini model if it is on the official deprecation list."""
        if self.gemini_model and self.gemini_model.strip().lower() in DEPRECATED_GEMINI_MODELS:
            return self.gemini_model.strip()
        return None

    def get_configured_providers(self) -> list[dict[str, Any]]:
        """Return configured LLM providers in priority order with deduplicated candidates."""
        providers = []

        # Tier 1: Gemini
        if self.gemini_api_key:
            deprecated = self.deprecated_gemini_model()
            if deprecated and deprecated not in _warned_deprecated_gemini:
                _warned_deprecated_gemini.add(deprecated)
                log.warning(
                    "GEMINI_MODEL '%s' 已被 Google 官方弃用，请求可能被自动路由或直接失败；"
                    "建议改用 gemini-3.8-flash。当前仍会优先尝试该模型，失败后自动降级到候选池中的新版模型。",
                    deprecated,
                )
            gemini_candidates = []
            for m in [self.gemini_model, "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.1-pro"]:
                if m and m not in gemini_candidates:
                    gemini_candidates.append(m)
            providers.append({
                "name": "Google Gemini",
                "api_key": self.gemini_api_key,
                "base_url": self.gemini_base_url,
                "model": self.gemini_model,
                "candidates": gemini_candidates,
            })

        # Tier 2: DeepSeek
        if self.deepseek_api_key:
            deepseek_candidates = []
            for m in [self.deepseek_model, "deepseek-chat", "deepseek-v4-pro", "deepseek-flash", "deepseek-reasoner"]:
                if m and m not in deepseek_candidates:
                    deepseek_candidates.append(m)
            providers.append({
                "name": "DeepSeek",
                "api_key": self.deepseek_api_key,
                "base_url": self.deepseek_base_url,
                "model": self.deepseek_model,
                "candidates": deepseek_candidates,
            })

        # Tier 3: Standard / Generic OpenAI compatible provider
        if self.openai_api_key:
            is_dup = (self.openai_api_key == self.gemini_api_key) or (self.openai_api_key == self.deepseek_api_key)
            if not is_dup:
                providers.append({
                    "name": "OpenAI / Compatible",
                    "api_key": self.openai_api_key,
                    "base_url": self.openai_base_url or "https://api.openai.com/v1",
                    "model": self.llm_model,
                    "candidates": [self.llm_model],
                })
        return providers

    def validate(self) -> list[str]:
        """
        Validate application configuration settings (Fail-Fast).
        Returns a list of human-readable error messages. If empty, configuration is valid.
        """
        errors = []
        # Validate DIGEST_TIME format (HH:MM)
        if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", self.digest_time):
            errors.append(f"DIGEST_TIME '{self.digest_time}' 格式不合法，应为 HH:MM (如 '08:00')")

        # Validate DIGEST_TIMEZONE
        try:
            ZoneInfo(self.digest_timezone)
        except Exception:
            errors.append(f"DIGEST_TIMEZONE '{self.digest_timezone}' 无效，应为标准 IANA 时区 (如 'Asia/Shanghai')")

        # Validate numbers
        if self.lookback_hours <= 0:
            errors.append(f"LOOKBACK_HOURS '{self.lookback_hours}' 必须大于 0")
        if self.max_items_per_source <= 0:
            errors.append(f"MAX_ITEMS_PER_SOURCE '{self.max_items_per_source}' 必须大于 0")
        if not (0.0 < self.dedupe_similarity <= 1.0):
            errors.append(f"DEDUPE_SIMILARITY '{self.dedupe_similarity}' 必须在 0.0 到 1.0 之间")
        if self.output_retention_days <= 0:
            errors.append(f"OUTPUT_RETENTION_DAYS '{self.output_retention_days}' 必须大于 0")

        # Validate LLM Providers
        providers = self.get_configured_providers()
        if self.mail_to and not providers:
            errors.append("未检测到任何可用的 AI 模型提供商配置 (请至少配置 GEMINI_API_KEY、DEEPSEEK_API_KEY 或 OPENAI_API_KEY)")

        # Validate Email Settings (if mail_to is specified)
        if self.mail_to:
            recipients = self.recipient_list
            if not recipients:
                errors.append("MAIL_TO 未配置有效收件邮箱")
            for addr in recipients:
                if "@" not in addr:
                    errors.append(f"MAIL_TO '{addr}' 邮箱格式无效")
            if not self.smtp_host:
                errors.append("配置了 MAIL_TO，但未配置 SMTP_HOST")
            if not (1 <= self.smtp_port <= 65535):
                errors.append(f"SMTP_PORT '{self.smtp_port}' 端口超出合法范围 (1~65535)")
            if self.smtp_use_ssl and self.smtp_use_tls:
                errors.append("SMTP_USE_SSL 和 SMTP_USE_TLS 不能同时为 True，请根据端口选择其一 (465 通常为 SSL，587 通常为 TLS)")

        return errors

    @property
    def recipient_list(self) -> list[str]:
        """Return parsed list of recipient email addresses."""
        if not self.mail_to:
            return []
        return [addr.strip() for addr in re.split(r"[,;，；\s]+", self.mail_to) if addr.strip()]


    @classmethod
    def load(cls) -> "AppConfig":
        def get_bool(key: str, default: bool) -> bool:
            val = os.getenv(key, "").strip().lower()
            if not val:
                return default
            return val in {"1", "true", "yes", "on"}

        def get_int(key: str, default: int) -> int:
            try:
                return int(os.getenv(key, str(default)))
            except (TypeError, ValueError):
                return default

        def get_float(key: str, default: float) -> float:
            try:
                return float(os.getenv(key, str(default)))
            except (TypeError, ValueError):
                return default

        smtp_port = get_int("SMTP_PORT", 465)
        default_ssl = (smtp_port == 465)
        default_tls = (smtp_port == 587)

        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        openai_base = os.getenv("OPENAI_BASE_URL", "").strip()
        openai_model = os.getenv("LLM_MODEL", "").strip()
        openai_base_lower = openai_base.lower()

        # Dedicated Gemini configuration
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key and (
            openai_key.startswith("AIza")
            or openai_key.startswith("AQ.")
            or "googleapis.com" in openai_base_lower
        ):
            gemini_key = openai_key

        gemini_base = os.getenv("GEMINI_BASE_URL", "").strip() or (
            openai_base if "googleapis.com" in openai_base_lower else "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        gemini_model = os.getenv("GEMINI_MODEL", "").strip() or (
            openai_model if "gemini" in openai_model.lower() else "gemini-3.8-flash"
        )

        # Dedicated DeepSeek configuration
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not deepseek_key and "deepseek" in openai_base_lower:
            deepseek_key = openai_key

        deepseek_base = os.getenv("DEEPSEEK_BASE_URL", "").strip() or (
            openai_base if "deepseek" in openai_base_lower else "https://api.deepseek.com/v1"
        )
        deepseek_model = os.getenv("DEEPSEEK_MODEL", "").strip() or (
            openai_model if "deepseek" in openai_model.lower() else "deepseek-v4-pro"
        )

        return cls(
            digest_time=os.getenv("DIGEST_TIME", "08:00").strip(),
            digest_timezone=os.getenv("DIGEST_TIMEZONE", "Asia/Shanghai").strip(),
            lookback_hours=get_int("LOOKBACK_HOURS", 24),
            max_items_per_source=get_int("MAX_ITEMS_PER_SOURCE", 5),
            fetch_timeout=get_float("FETCH_TIMEOUT", 15.0),
            dedupe_similarity=get_float("DEDUPE_SIMILARITY", 0.85),
            output_retention_days=get_int("OUTPUT_RETENTION_DAYS", 7),
            compress_image=get_bool("COMPRESS_IMAGE", True),
            resolve_google_news=get_bool("RESOLVE_GOOGLE_NEWS", True),
            openai_api_key=openai_key,
            openai_base_url=openai_base,
            llm_model=openai_model or "gpt-4o-mini",
            llm_timeout=get_float("LLM_TIMEOUT", 90.0),
            llm_max_tokens=get_int("LLM_MAX_TOKENS", 8192),
            llm_max_tokens_large=get_int("LLM_MAX_TOKENS_LARGE", 16384),
            gemini_api_key=gemini_key,
            gemini_base_url=gemini_base,
            gemini_model=gemini_model,
            deepseek_api_key=deepseek_key,
            deepseek_base_url=deepseek_base,
            deepseek_model=deepseek_model,
            mail_to=os.getenv("MAIL_TO", "").strip(),
            mail_from=os.getenv("MAIL_FROM", "").strip() or os.getenv("SMTP_USER", "").strip(),
            smtp_host=os.getenv("SMTP_HOST", "").strip(),
            smtp_port=smtp_port,
            smtp_user=os.getenv("SMTP_USER", "").strip(),
            smtp_password=os.getenv("SMTP_PASSWORD", "").strip(),
            smtp_use_ssl=get_bool("SMTP_USE_SSL", default_ssl),
            smtp_use_tls=get_bool("SMTP_USE_TLS", default_tls),
            topics_config=cls._load_topics_yaml(),
        )

    @classmethod
    def _load_topics_yaml(cls) -> dict[str, Any]:
        """Load externalized topics.yaml if present."""
        topics_file = BASE_DIR / "config" / "topics.yaml"
        if topics_file.exists():
            try:
                import yaml
                data = yaml.safe_load(topics_file.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except Exception:
                pass
        return {}



_cached_config: AppConfig | None = None


def get_config(reload: bool = False) -> AppConfig:
    """Get global cached configuration or reload from environment."""
    global _cached_config
    if _cached_config is None or reload:
        _cached_config = AppConfig.load()
    return _cached_config


config = get_config()
