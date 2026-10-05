# -*- coding: utf-8 -*-
"""
Configuration management for Daily News & Impact Digest.
Reads settings from environment variables and .env file.
"""

from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

if ENV_PATH.exists():
    load_dotenv(ENV_PATH)
else:
    load_dotenv()


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

    # Dedicated Gemini Settings (Priority 1)
    gemini_api_key: str = ""
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-3.8-flash"

    # Dedicated DeepSeek Settings (Priority 2 / Fallback)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_model: str = "deepseek-chat"

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

    def get_configured_providers(self) -> list[dict[str, Any]]:
        """Return configured LLM providers in priority order."""
        providers = []
        # Tier 1: Gemini
        if self.gemini_api_key:
            providers.append({
                "name": "Google Gemini",
                "api_key": self.gemini_api_key,
                "base_url": self.gemini_base_url,
                "model": self.gemini_model,
                "candidates": [self.gemini_model, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"],
            })
        # Tier 2: DeepSeek
        if self.deepseek_api_key:
            providers.append({
                "name": "DeepSeek",
                "api_key": self.deepseek_api_key,
                "base_url": self.deepseek_base_url,
                "model": self.deepseek_model,
                "candidates": [self.deepseek_model, "deepseek-chat"],
            })
        # Tier 3: Standard / Generic OpenAI compatible provider
        # Active if openai_api_key is set and not identical to gemini or deepseek keys
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

    @classmethod
    def load(cls) -> "AppConfig":
        def get_bool(key: str, default: bool) -> bool:
            val = os.getenv(key, "").strip().lower()
            if not val:
                return default
            return val in {"1", "true", "yes", "on"}

        smtp_port = int(os.getenv("SMTP_PORT", "465"))
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
            openai_model if "gemini" in openai_model.lower() else "gemini-2.5-flash"
        )

        # Dedicated DeepSeek configuration
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not deepseek_key and "deepseek" in openai_base_lower:
            deepseek_key = openai_key

        deepseek_base = os.getenv("DEEPSEEK_BASE_URL", "").strip() or (
            openai_base if "deepseek" in openai_base_lower else "https://api.deepseek.com/v1"
        )
        deepseek_model = os.getenv("DEEPSEEK_MODEL", "").strip() or (
            openai_model if "deepseek" in openai_model.lower() else "deepseek-chat"
        )

        return cls(
            digest_time=os.getenv("DIGEST_TIME", "08:00").strip(),
            digest_timezone=os.getenv("DIGEST_TIMEZONE", "Asia/Shanghai").strip(),
            lookback_hours=int(os.getenv("LOOKBACK_HOURS", "24")),
            max_items_per_source=int(os.getenv("MAX_ITEMS_PER_SOURCE", "5")),
            fetch_timeout=float(os.getenv("FETCH_TIMEOUT", "15.0")),
            dedupe_similarity=float(os.getenv("DEDUPE_SIMILARITY", "0.85")),
            output_retention_days=int(os.getenv("OUTPUT_RETENTION_DAYS", "7")),
            compress_image=get_bool("COMPRESS_IMAGE", True),
            openai_api_key=openai_key,
            openai_base_url=openai_base,
            llm_model=openai_model or "gpt-4o-mini",
            llm_timeout=float(os.getenv("LLM_TIMEOUT", "90.0")),
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
        )


config = AppConfig.load()

