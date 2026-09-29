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

    # LLM Settings
    openai_api_key: str = ""
    openai_base_url: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 90.0

    # Email Settings
    mail_to: str = ""
    mail_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_ssl: bool = True
    smtp_use_tls: bool = False

    @classmethod
    def load(cls) -> "AppConfig":
        def get_bool(key: str, default: bool) -> bool:
            val = os.getenv(key, "").strip().lower()
            if not val:
                return default
            return val in {"1", "true", "yes", "on"}

        smtp_port = int(os.getenv("SMTP_PORT", "465"))
        # Default SSL for port 465, TLS for 587
        default_ssl = (smtp_port == 465)
        default_tls = (smtp_port == 587)

        return cls(
            digest_time=os.getenv("DIGEST_TIME", "08:00").strip(),
            digest_timezone=os.getenv("DIGEST_TIMEZONE", "Asia/Shanghai").strip(),
            lookback_hours=int(os.getenv("LOOKBACK_HOURS", "24")),
            max_items_per_source=int(os.getenv("MAX_ITEMS_PER_SOURCE", "5")),
            fetch_timeout=float(os.getenv("FETCH_TIMEOUT", "15.0")),
            dedupe_similarity=float(os.getenv("DEDUPE_SIMILARITY", "0.85")),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "gpt-4o-mini").strip(),
            llm_timeout=float(os.getenv("LLM_TIMEOUT", "90.0")),
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
