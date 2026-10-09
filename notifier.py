# -*- coding: utf-8 -*-
"""
Multi-channel notification dispatcher.
Supports WeCom (企业微信), Feishu (飞书), DingTalk (钉钉), ServerChan (Server酱), and Telegram Bot,
providing resilient multi-channel delivery and automatic failover when SMTP encounters disruptions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
import requests

log = logging.getLogger("daily-news")


def send_wecom_webhook(webhook_url: str, title: str, markdown_text: str) -> bool:
    """Send markdown notification to WeChat Work (企业微信) webhook."""
    try:
        content = f"### {title}\n\n{markdown_text[:3500]}"
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content}
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp_json = resp.json()
        if resp_json.get("errcode") == 0:
            log.info("企业微信 Webhook 推送成功！")
            return True
        log.warning("企业微信 Webhook 返回错误: %s", resp_json)
    except Exception as exc:
        log.warning("企业微信 Webhook 推送失败: %s", exc)
    return False


def send_feishu_webhook(webhook_url: str, title: str, markdown_text: str) -> bool:
    """Send rich notification to Feishu (飞书) bot webhook."""
    try:
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue"
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {"tag": "lark_md", "content": markdown_text[:3500]}
                    }
                ]
            }
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp_json = resp.json()
        if resp_json.get("code") == 0 or resp_json.get("StatusCode") == 0:
            log.info("飞书 Webhook 推送成功！")
            return True
        log.warning("飞书 Webhook 返回错误: %s", resp_json)
    except Exception as exc:
        log.warning("飞书 Webhook 推送失败: %s", exc)
    return False


def send_dingtalk_webhook(webhook_url: str, title: str, markdown_text: str) -> bool:
    """Send markdown notification to DingTalk (钉钉) bot webhook."""
    try:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"### {title}\n\n{markdown_text[:3500]}"
            }
        }
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp_json = resp.json()
        if resp_json.get("errcode") == 0:
            log.info("钉钉 Webhook 推送成功！")
            return True
        log.warning("钉钉 Webhook 返回错误: %s", resp_json)
    except Exception as exc:
        log.warning("钉钉 Webhook 推送失败: %s", exc)
    return False


def send_serverchan_notice(key: str, title: str, markdown_text: str) -> bool:
    """Send notification via ServerChan (Server酱)."""
    try:
        url = f"https://sctapi.ftqq.com/{key.strip()}.send"
        resp = requests.post(url, data={"title": title[:100], "desp": markdown_text[:5000]}, timeout=10)
        resp_json = resp.json()
        if resp_json.get("code") == 0:
            log.info("Server酱推送成功！")
            return True
        log.warning("Server酱返回错误: %s", resp_json)
    except Exception as exc:
        log.warning("Server酱推送失败: %s", exc)
    return False


def send_telegram_notice(bot_token: str, chat_id: str, title: str, markdown_text: str) -> bool:
    """Send notification via Telegram Bot API using resilient HTML mode."""
    import html
    try:
        url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
        safe_title = html.escape(title)
        safe_body = html.escape(markdown_text[:3500])
        payload = {
            "chat_id": chat_id.strip(),
            "text": f"<b>{safe_title}</b>\n\n{safe_body}",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=12)
        if resp.status_code == 200:

            log.info("Telegram Bot 消息推送成功！")
            return True
        log.warning("Telegram Bot 推送失败 (HTTP %d): %s", resp.status_code, resp.text)
    except Exception as exc:
        log.warning("Telegram Bot 推送失败: %s", exc)
    return False


def dispatch_webhooks(title: str, markdown_text: str) -> dict[str, bool]:
    """
    Check environment variables for configured webhook endpoints and dispatch notifications.
    Returns status mapping for each configured provider.
    """
    results: dict[str, bool] = {}

    # 1. WeCom
    wecom_url = os.getenv("WECOM_WEBHOOK_URL", "").strip()
    if wecom_url:
        results["wecom"] = send_wecom_webhook(wecom_url, title, markdown_text)

    # 2. Feishu
    feishu_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if feishu_url:
        results["feishu"] = send_feishu_webhook(feishu_url, title, markdown_text)

    # 3. DingTalk
    dingtalk_url = os.getenv("DINGTALK_WEBHOOK_URL", "").strip()
    if dingtalk_url:
        results["dingtalk"] = send_dingtalk_webhook(dingtalk_url, title, markdown_text)

    # 4. ServerChan
    serverchan_key = os.getenv("SERVERCHAN_KEY", "").strip()
    if serverchan_key:
        results["serverchan"] = send_serverchan_notice(serverchan_key, title, markdown_text)

    # 5. Telegram
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if tg_token and tg_chat_id:
        results["telegram"] = send_telegram_notice(tg_token, tg_chat_id, title, markdown_text)

    return results
