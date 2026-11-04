# -*- coding: utf-8 -*-
"""
Multi-channel notification dispatcher.
Supports WeCom (企业微信), Feishu (飞书), DingTalk (钉钉), ServerChan (Server酱),
Telegram Bot, NapCatQQ / OneBot (QQ群), and Windows PC WeChat personal groups,
providing resilient multi-channel delivery and automatic failover when SMTP encounters disruptions.
"""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
import requests

log = logging.getLogger("daily-news")


def _truncate_by_bytes(text: str, max_bytes: int) -> str:
    """Truncate text so that its UTF-8 byte length stays within max_bytes.

    Multi-byte characters are never split; a trailing ellipsis is appended when truncation occurs.
    """
    if not text or max_bytes <= 0:
        return ""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text

    ellipsis = "…"
    budget = max_bytes - len(ellipsis.encode("utf-8"))
    if budget <= 0:
        return ""

    truncated = raw[:budget]
    while truncated:
        try:
            return truncated.decode("utf-8") + ellipsis
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return ""


def send_wecom_webhook(webhook_url: str, title: str, markdown_text: str) -> bool:
    """Send markdown notification to WeChat Work (企业微信) webhook."""
    try:
        content = _truncate_by_bytes(f"### {title}\n\n{markdown_text}", 4000)
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
                        "text": {"tag": "lark_md", "content": _truncate_by_bytes(markdown_text, 20000)}
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
                "text": _truncate_by_bytes(f"### {title}\n\n{markdown_text}", 18000)
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
        resp = requests.post(url, data={"title": title[:100], "desp": _truncate_by_bytes(markdown_text, 20000)}, timeout=10)
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
        safe_body = html.escape(markdown_text)
        text = f"<b>{safe_title}</b>\n\n{safe_body}"
        if len(text) > 4096:
            text = text[:4096]
            # 去除截断处可能残留的不完整 HTML 实体（如 &amp; 被切成 &am）
            text = re.sub(r"&[a-zA-Z#0-9]*$", "", text)
        payload = {
            "chat_id": chat_id.strip(),
            "text": text,
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


def send_onebot_qq_group(
    api_url: str,
    group_id: int | str,
    title: str,
    markdown_text: str,
    image_path: Path | str | None = None,
    access_token: str = "",
) -> bool:
    """Send digest text and optional rendered long image to a QQ group via OneBot v11 HTTP API (e.g. NapCatQQ)."""
    try:
        url = api_url.rstrip("/")
        if not url.endswith("/send_group_msg"):
            url = f"{url}/send_group_msg"

        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token.strip()}"

        summary_text = _truncate_by_bytes(f"【{title}】\n\n{markdown_text}", 3000)
        messages: list[dict[str, Any]] = [
            {"type": "text", "data": {"text": summary_text}}
        ]

        if image_path:
            img = Path(image_path)
            if img.exists() and img.is_file():
                try:
                    import base64
                    with open(img, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    messages.append({"type": "image", "data": {"file": f"base64://{b64}"}})
                except Exception as img_err:
                    log.warning("读取 QQ 待发送长图失败: %s", img_err)

        payload = {
            "group_id": int(str(group_id).strip()),
            "message": messages,
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp_json = resp.json()
        if resp_json.get("status") == "ok" or resp_json.get("retcode") == 0:
            log.info("QQ 群 (%s) NapCat 消息推送成功！", group_id)
            return True
        log.warning("QQ 群 (%s) NapCat 返回错误: %s", group_id, resp_json)
    except Exception as exc:
        log.warning("QQ 群 (%s) NapCat 推送失败: %s", group_id, exc)
    return False


def send_wechat_personal_notice(
    group_name: str,
    title: str,
    markdown_text: str,
    image_path: Path | str | None = None,
) -> bool:
    """Send digest to a personal WeChat group using Windows PC WeChat UI automation."""
    try:
        from wechat_personal import send_to_wechat_group
        return send_to_wechat_group(group_name, f"【{title}】\n\n{markdown_text}", image_path)
    except Exception as exc:
        log.warning("个人微信群自动化发送失败: %s", exc)
        return False


def dispatch_webhooks(title: str, markdown_text: str, image_path: Path | str | None = None) -> dict[str, bool]:
    """
    Check environment variables for configured webhook endpoints and dispatch notifications.
    All configured channels run concurrently so total latency stays near the slowest single
    channel instead of the sum of every channel. Returns status mapping for each configured
    provider, preserving the channel order.
    """
    tasks: list[tuple[str, Any, tuple[Any, ...]]] = []

    # 1. WeCom
    wecom_url = os.getenv("WECOM_WEBHOOK_URL", "").strip()
    if wecom_url:
        tasks.append(("wecom", send_wecom_webhook, (wecom_url, title, markdown_text)))

    # 2. Feishu
    feishu_url = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if feishu_url:
        tasks.append(("feishu", send_feishu_webhook, (feishu_url, title, markdown_text)))

    # 3. DingTalk
    dingtalk_url = os.getenv("DINGTALK_WEBHOOK_URL", "").strip()
    if dingtalk_url:
        tasks.append(("dingtalk", send_dingtalk_webhook, (dingtalk_url, title, markdown_text)))

    # 4. ServerChan
    serverchan_key = os.getenv("SERVERCHAN_KEY", "").strip()
    if serverchan_key:
        tasks.append(("serverchan", send_serverchan_notice, (serverchan_key, title, markdown_text)))

    # 5. Telegram
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if tg_token and tg_chat_id:
        tasks.append(("telegram", send_telegram_notice, (tg_token, tg_chat_id, title, markdown_text)))

    # 6. OneBot / NapCatQQ (QQ群推送)
    onebot_url = os.getenv("ONEBOT_HTTP_URL", "").strip()
    qq_groups = os.getenv("QQ_GROUP_ID", "").strip()
    onebot_token = os.getenv("ONEBOT_ACCESS_TOKEN", "").strip()
    if onebot_url and qq_groups:
        for gid in re.split(r"[,;，；\s]+", qq_groups):
            gid = gid.strip()
            if gid:
                channel_name = f"qq_group_{gid}"
                tasks.append((channel_name, send_onebot_qq_group, (onebot_url, gid, title, markdown_text, image_path, onebot_token)))

    # 7. PC 微信自动化 (普通个人微信群)
    wechat_group = os.getenv("WECHAT_PERSONAL_GROUP", "").strip()
    if wechat_group:
        tasks.append(("wechat_personal", send_wechat_personal_notice, (wechat_group, title, markdown_text, image_path)))

    if not tasks:
        return {}

    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        futures = {name: pool.submit(sender, *args) for name, sender, args in tasks}
        for name, future in futures.items():
            try:
                results[name] = bool(future.result())
            except Exception as exc:
                log.warning("%s Webhook 推送线程异常: %s", name, exc)
                results[name] = False
    return results
