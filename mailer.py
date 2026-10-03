# -*- coding: utf-8 -*-
"""
Email builder and SMTP sender.
Renders responsive HTML emails and sends via SMTP (SSL/TLS).
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import markdown

from config import config

log = logging.getLogger("daily-news")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
    line-height: 1.68;
    color: #24292e;
    background-color: #f6f8fa;
    margin: 0;
    padding: 20px 10px;
  }}
  .container {{
    max-width: 820px;
    margin: 0 auto;
    background: #ffffff;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 4px 18px rgba(0,0,0,0.06);
    border: 1px solid #e1e4e8;
  }}
  .header {{
    background: linear-gradient(135deg, #1f2937 0%, #111827 100%);
    color: #ffffff;
    padding: 30px 25px;
    text-align: left;
    border-bottom: 3px solid #3b82f6;
  }}
  .header h1 {{
    margin: 0 0 10px 0;
    font-size: 24px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }}
  .header .meta {{
    font-size: 13px;
    color: #9ca3af;
  }}
  .sources-bar {{
    background: #f8fafc;
    padding: 12px 25px;
    border-bottom: 1px solid #e2e8f0;
    font-size: 13px;
    color: #475569;
  }}
  .badge {{
    display: inline-block;
    padding: 3px 8px;
    margin-right: 6px;
    margin-bottom: 4px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 600;
  }}
  .badge-bloomberg {{ background: #fff1e5; color: #b45309; border: 1px solid #fcd34d; }}
  .badge-reuters {{ background: #fee2e2; color: #b91c1c; border: 1px solid #fca5a5; }}
  .badge-wsj {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #93c5fd; }}
  .badge-ft {{ background: #fdf2f8; color: #be185d; border: 1px solid #fbcfe8; }}
  .badge-zaobao {{ background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }}
  .badge-nikkei {{ background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }}
  .badge-economist {{ background: #fff7ed; color: #c2410c; border: 1px solid #fed7aa; }}

  .content {{
    padding: 30px 28px;
    font-size: 15px;
  }}
  .content h2 {{
    color: #0f172a;
    font-size: 20px;
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 8px;
    margin-top: 35px;
    margin-bottom: 18px;
  }}
  .content h3 {{
    color: #1e293b;
    font-size: 17px;
    margin-top: 24px;
    margin-bottom: 12px;
  }}
  .content p {{
    margin: 10px 0;
  }}
  .content blockquote {{
    margin: 12px 0;
    padding: 12px 18px;
    background: #f8fafc;
    border-left: 4px solid #3b82f6;
    color: #475569;
    border-radius: 0 6px 6px 0;
  }}
  .content ul, .content ol {{
    padding-left: 22px;
    margin: 10px 0;
  }}
  .content li {{
    margin-bottom: 8px;
  }}
  .content a {{
    color: #2563eb;
    text-decoration: none;
    font-weight: 500;
  }}
  .content a:hover {{
    text-decoration: underline;
  }}
  .content table {{
    width: 100%;
    border-collapse: collapse;
    margin: 20px 0;
    font-size: 14px;
  }}
  .content table th {{
    background: #f1f5f9;
    color: #1e293b;
    font-weight: 600;
    text-align: left;
    padding: 10px 14px;
    border: 1px solid #cbd5e1;
  }}
  .content table td {{
    padding: 10px 14px;
    border: 1px solid #e2e8f0;
    vertical-align: top;
  }}
  .content table tr:nth-child(even) {{
    background: #f8fafc;
  }}
  .footer {{
    background: #f8fafc;
    border-top: 1px solid #e2e8f0;
    padding: 20px 25px;
    text-align: center;
    font-size: 12px;
    color: #64748b;
  }}
  .footer a {{
    color: #64748b;
  }}
  .warning-box {{
    background: #fffbeb;
    border: 1px solid #fde68a;
    color: #92400e;
    padding: 10px 15px;
    border-radius: 6px;
    font-size: 13px;
    margin-top: 15px;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>每日财经与中国宏观深度简报</h1>
    <div class="meta">报告日期：{date_str} | 生成时间：{time_str} ({timezone})</div>
  </div>
  <div class="sources-bar">
    <strong>关注媒体：</strong>
    <span class="badge badge-bloomberg">彭博社 Bloomberg</span>
    <span class="badge badge-reuters">路透社 Reuters</span>
    <span class="badge badge-wsj">华尔街日报 WSJ</span>
    <span class="badge badge-ft">金融时报 FT</span>
    <span class="badge badge-zaobao">联合早报 Zaobao</span>
    <span class="badge badge-nikkei">日经中文网 Nikkei</span>
    <span class="badge badge-economist">经济学人 Economist</span>
  </div>
  <div class="content">
    {body_html}
    {warnings_html}
  </div>
  <div class="footer">
    <p>📱 <strong>手机阅读体验提示</strong>：邮件附件中已附带<strong>高清长图（PNG）</strong>，手机端可长按保存至相册并转发分享。</p>
    <p>本简报由定时任务自动聚合分析海外权威外媒财经与中国要闻生成，仅供参考，请点击原文链接核实详细报道。</p>
  </div>
</div>
</body>
</html>
"""


def render_html_document(body_markdown: str, errors: list[str]) -> str:
    """Convert Markdown body to high quality HTML email."""
    tz = ZoneInfo(config.digest_timezone)
    now = datetime.now(tz)
    date_str = now.strftime("%Y年%m月%d日")
    time_str = now.strftime("%H:%M")

    # Convert Markdown to HTML with table and smartlist support
    body_html = markdown.markdown(
        body_markdown,
        extensions=["tables", "fenced_code", "nl2br", "sane_lists"]
    )

    warnings_html = ""
    if errors:
        warnings_html = f'<div class="warning-box">⚠️ <strong>抓取警告：</strong>{"；".join(errors)}</div>'

    html = HTML_TEMPLATE.format(
        title=f"每日财经与中国宏观深度简报 - {date_str}",
        date_str=date_str,
        time_str=time_str,
        timezone=config.digest_timezone,
        body_html=body_html,
        warnings_html=warnings_html,
    )
    return html


def send_digest_email(body_markdown: str, errors: list[str], image_path: Path | None = None) -> None:
    """Build and send digest email via configured SMTP server."""
    if not config.mail_to:
        raise ValueError("MAIL_TO 未配置，无法发送邮件。请在 .env 中设置 MAIL_TO=收件邮箱")
    if not config.smtp_host or not config.smtp_user:
        raise ValueError("SMTP_HOST 或 SMTP_USER 未配置，无法发送邮件。请在 .env 中设置 SMTP 配置")

    tz = ZoneInfo(config.digest_timezone)
    now = datetime.now(tz)
    date_str = now.strftime("%Y-%m-%d")
    subject = f"【财经与中国深度简报】{date_str} - 全球七大权威媒体精要与资产配置指引"

    html_content = render_html_document(body_markdown, errors)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config.mail_from or config.smtp_user
    message["To"] = config.mail_to
    message["Date"] = format_datetime(now)

    # Plain text fallback
    plain_summary = (
        f"【每日财经与中国宏观深度简报】({date_str})\n\n"
        "请在支持 HTML 格式的邮件客户端中查阅完整图文分析与资产配置指引，"
        "或长按/下载附件中的【高清长图】查看。\n"
    )
    message.set_content(plain_summary)
    # HTML alternative
    message.add_alternative(html_content, subtype="html")

    # Add .png long image attachment if available (only attachment, no .md)
    img_filename = f"finance_china_digest_{date_str}.png"
    if image_path and Path(image_path).exists():
        img_path = Path(image_path)
        try:
            img_bytes = img_path.read_bytes()
            message.add_attachment(
                img_bytes,
                maintype="image",
                subtype="png",
                filename=img_filename
            )
            log.info("已将高清长图 [%s] 添加至邮件附件", img_filename)
        except Exception as e:
            log.warning("添加长图附件失败: %s", e)

    def _do_send(msg: EmailMessage) -> None:
        log.info("Connecting to SMTP server %s:%d (SSL=%s, TLS=%s)...",
                 config.smtp_host, config.smtp_port, config.smtp_use_ssl, config.smtp_use_tls)
        if config.smtp_use_ssl:
            with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=30) as smtp:
                if config.smtp_user and config.smtp_password:
                    smtp.login(config.smtp_user, config.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as smtp:
                if config.smtp_use_tls:
                    smtp.starttls()
                if config.smtp_user and config.smtp_password:
                    smtp.login(config.smtp_user, config.smtp_password)
                smtp.send_message(msg)

    try:
        _do_send(message)
    except smtplib.SMTPDataError as exc:
        err_msg = str(exc)
        if "550" in err_msg or "inappropriate" in err_msg.lower() or "content" in err_msg.lower():
            log.warning("检测到邮件服务商文本内容拦截 (550)，正在自动降级为【精简正文 + 高清长图】模式重发...")
            fallback_msg = EmailMessage()
            fallback_msg["Subject"] = subject
            fallback_msg["From"] = config.mail_from or config.smtp_user
            fallback_msg["To"] = config.mail_to
            fallback_msg["Date"] = format_datetime(now)

            clean_md = (
                f"## 📋 每日财经与中国宏观深度简报 ({date_str})\n\n"
                "> 💡 **查阅提示**：本期完整研报与资产配置建议已渲染为**高清长图（PNG）**附于邮件附件中，请长按或下载附件查看。\n\n"
                f"- 附件已包含：**{img_filename}**（2x 视网膜超清长图）\n"
            )
            clean_html = render_html_document(clean_md, errors)
            fallback_msg.set_content(plain_summary)
            fallback_msg.add_alternative(clean_html, subtype="html")

            if image_path and Path(image_path).exists():
                fallback_msg.add_attachment(
                    Path(image_path).read_bytes(),
                    maintype="image",
                    subtype="png",
                    filename=img_filename
                )
            _do_send(fallback_msg)
            log.info("【精简正文 + 高清长图】模式邮件已成功送达！")
        else:
            raise exc

    log.info("Email successfully sent to %s!", config.mail_to)


def test_smtp_connection() -> bool:
    """Test SMTP connection and credentials without sending a digest."""
    log.info("Testing SMTP connection to %s:%d...", config.smtp_host, config.smtp_port)
    try:
        if config.smtp_use_ssl:
            with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=20) as smtp:
                if config.smtp_user and config.smtp_password:
                    smtp.login(config.smtp_user, config.smtp_password)
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=20) as smtp:
                if config.smtp_use_tls:
                    smtp.starttls()
                if config.smtp_user and config.smtp_password:
                    smtp.login(config.smtp_user, config.smtp_password)
        log.info("SMTP connection and authentication succeeded!")
        return True
    except Exception as e:
        log.error("SMTP test failed: %s: %s", type(e).__name__, e)
        return False
