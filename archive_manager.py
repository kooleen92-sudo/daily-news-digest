# -*- coding: utf-8 -*-
"""
Historical digest archive manager, static HTML portal generator, and RSS 2.0 publisher.
Enables long-term preservation, web browsing, and RSS reader subscriptions.
"""

from __future__ import annotations

import html
import logging
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from config import BASE_DIR, config

log = logging.getLogger("daily-news")

ARCHIVE_DIR = BASE_DIR / "archive"
OUTPUT_DIR = BASE_DIR / "output"


def archive_daily_digest(report_markdown: str, report_html: str, date_tag: str | None = None, image_path: str | None = None) -> Path:
    """
    Archive today's Markdown and HTML reports to archive/YYYY/MM/digest_YYYYMMDD.*.
    """
    tz = ZoneInfo(config.digest_timezone)
    now = datetime.now(tz)
    date_str = date_tag or now.strftime("%Y%m%d")
    year_str = date_str[:4]
    month_str = date_str[4:6]

    dest_dir = ARCHIVE_DIR / year_str / month_str
    dest_dir.mkdir(parents=True, exist_ok=True)

    md_file = dest_dir / f"digest_{date_str}.md"
    html_file = dest_dir / f"digest_{date_str}.html"

    md_file.write_text(report_markdown, encoding="utf-8")
    html_file.write_text(report_html, encoding="utf-8")

    if image_path and Path(image_path).is_file():
        shutil.copy2(image_path, dest_dir / f"digest_{date_str}.png")

    log.info("已永久归档今日简报至: %s", dest_dir)
    return dest_dir


def _digest_html_files() -> list[tuple[str, Path]]:
    """Return ``(date_tag, path)`` pairs for output and permanently archived reports."""
    candidates: list[Path] = []
    if OUTPUT_DIR.exists():
        candidates.extend(path for path in OUTPUT_DIR.glob("digest_*.html") if path.is_file())
    if ARCHIVE_DIR.exists():
        candidates.extend(path for path in ARCHIVE_DIR.rglob("digest_*.html") if path.is_file())

    reports: list[tuple[str, Path]] = []
    for path in candidates:
        match = re.fullmatch(r"digest_(\d{8})\.html", path.name)
        if match:
            reports.append((match.group(1), path))
    return reports


def _output_relative_url(path: Path) -> str:
    """Return a POSIX URL relative to the generated files in ``output/``."""
    try:
        return path.relative_to(OUTPUT_DIR).as_posix()
    except ValueError:
        try:
            archive_relative = path.relative_to(ARCHIVE_DIR)
            return (Path("..") / ARCHIVE_DIR.name / archive_relative).as_posix()
        except ValueError:
            # Keep the helper usable for custom test layouts while retaining POSIX URLs.
            return Path(os.path.relpath(path, OUTPUT_DIR)).as_posix()


def generate_archive_portal() -> Path:
    """
    Generate an elegant, mobile-friendly index.html in output/ listing all generated digests.
    """
    digests: list[dict[str, str]] = []

    seen_dates = set()

    reports = sorted(
        _digest_html_files(),
        key=lambda item: (item[0], item[1].is_relative_to(OUTPUT_DIR)),
        reverse=True,
    )
    for d_str, report_path in reports:
        if d_str in seen_dates:
            continue
        seen_dates.add(d_str)

        formatted_date = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
        report_url = _output_relative_url(report_path)
        markdown_path = report_path.with_suffix(".md")
        image_path = report_path.with_suffix(".png")
        excerpt = "全球七大外媒要闻精萃与个人资产配置实战指南"
        try:
            content = report_path.read_text(encoding="utf-8", errors="ignore")
            title_match = re.search(r"<title>(.*?)</title>", content, flags=re.IGNORECASE | re.DOTALL)
            title_text = title_match.group(1).strip() if title_match else f"每日财经与中国宏观深度简报 ({formatted_date})"
        except Exception:
            title_text = f"每日财经与中国宏观深度简报 ({formatted_date})"

        digests.append({
            "date": formatted_date,
            "title": html.escape(title_text),
            "html_url": report_url,
            "md_url": _output_relative_url(markdown_path) if markdown_path.is_file() else "",
            "png_url": _output_relative_url(image_path) if image_path.is_file() else "",
            "excerpt": excerpt,
        })

    digests.sort(key=lambda x: x["date"], reverse=True)

    items_html = ""
    for item in digests:
        items_html += f"""
        <div class="card">
            <div class="card-date">{item['date']}</div>
            <a class="card-title" href="{item['html_url']}">{item['title']}</a>
            <div class="card-excerpt">{item['excerpt']}</div>
            <div class="card-links">
                <a class="btn" href="{item['html_url']}">在线查阅 HTML</a>
                {f'<a class="btn-secondary" href="{item["png_url"]}">长图海报</a>' if item["png_url"] else ''}
                {f'<a class="btn-secondary" href="{item["md_url"]}">Markdown</a>' if item["md_url"] else ''}
            </div>
        </div>
        """

    portal_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>每日财经与中国宏观深度简报 - 历史归档</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: #f8fafc;
            color: #0f172a;
            margin: 0;
            padding: 30px 15px;
        }}
        .container {{
            max-width: 860px;
            margin: 0 auto;
        }}
        header {{
            background: linear-gradient(135deg, #1e293b, #0f172a);
            color: #ffffff;
            padding: 28px;
            border-radius: 12px;
            margin-bottom: 24px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.06);
        }}
        header h1 {{ margin: 0 0 10px 0; font-size: 24px; }}
        header p {{ margin: 0; color: #94a3b8; font-size: 14px; line-height: 1.5; }}
        .feed-bar {{
            margin-top: 15px;
        }}
        .feed-bar a {{
            color: #38bdf8;
            font-size: 13px;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        .card {{
            background: #ffffff;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 16px;
            border: 1px solid #e2e8f0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.02);
            transition: transform 0.15s ease;
        }}
        .card:hover {{ transform: translateY(-2px); }}
        .card-date {{ font-size: 13px; color: #64748b; font-weight: 600; margin-bottom: 6px; }}
        .card-title {{ font-size: 18px; font-weight: 700; color: #1e3a8a; text-decoration: none; display: block; margin-bottom: 8px; }}
        .card-title:hover {{ text-decoration: underline; }}
        .card-excerpt {{ font-size: 14px; color: #475569; margin-bottom: 14px; line-height: 1.5; }}
        .card-links {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .btn {{
            background: #2563eb;
            color: #ffffff;
            font-size: 13px;
            font-weight: 500;
            padding: 6px 12px;
            border-radius: 6px;
            text-decoration: none;
        }}
        .btn-secondary {{
            background: #f1f5f9;
            color: #334155;
            font-size: 13px;
            padding: 6px 12px;
            border-radius: 6px;
            text-decoration: none;
            border: 1px solid #cbd5e1;
        }}
        .btn:hover {{ background: #1d4ed8; }}
        .btn-secondary:hover {{ background: #e2e8f0; }}
    </style>
</head>
<body>
<div class="container">
    <header>
        <h1>📰 每日财经与中国宏观深度简报</h1>
        <p>聚合彭博社、路透社、华尔街日报、金融时报、联合早报、日经中文网与经济学人，面向个人投资者的宏观研判与资产配置实战指引。</p>
        <div class="feed-bar">
            <a href="feed.xml" target="_blank">📡 订阅 RSS 2.0 Feed</a>
        </div>
    </header>

    <div class="list">
        {items_html if items_html else "<div class='card'><p>暂无历史归档报告</p></div>"}
    </div>
</div>
</body>
</html>
"""
    portal_file = OUTPUT_DIR / "index.html"
    portal_file.write_text(portal_html, encoding="utf-8")
    log.info("已更新历史简报导航门户: %s", portal_file)
    return portal_file


def generate_rss_feed() -> Path:
    """Generate standard RSS 2.0 XML feed in output/feed.xml."""
    tz = ZoneInfo(config.digest_timezone)
    now = datetime.now(tz)

    feed_items = []
    seen_dates = set()
    reports = sorted(
        _digest_html_files(),
        key=lambda item: (item[0], item[1].is_relative_to(OUTPUT_DIR)),
        reverse=True,
    )
    for d_str, report_path in reports:
        if d_str in seen_dates:
            continue
        seen_dates.add(d_str)
        if len(seen_dates) > 15:
            break

        pub_dt = datetime.strptime(d_str, "%Y%m%d").replace(tzinfo=tz)
        pub_rfc822 = pub_dt.strftime("%a, %d %b %Y 08:00:00 +0800")

        # Try to read matching markdown summary
        md_file = report_path.with_suffix(".md")
        description_text = ""
        if md_file.exists():
            description_text = md_file.read_text(encoding="utf-8")[:1500] + "..."
        else:
            description_text = f"每日财经与中国宏观深度简报 ({d_str})"

        feed_items.append(f"""
        <item>
            <title>【每日财经与中国深度简报】{d_str}</title>
            <link>{_output_relative_url(report_path)}</link>
            <guid isPermaLink="false">{d_str}</guid>
            <pubDate>{pub_rfc822}</pubDate>
            <description><![CDATA[{html.escape(description_text)}]]></description>
        </item>
        """)

    feed_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>每日财经与中国宏观深度简报</title>
    <link>https://github.com/</link>
    <description>彭博社、路透社、华尔街日报、金融时报、联合早报、日经中文网、经济学人每日全球财经与中国宏观决策简报</description>
    <language>zh-cn</language>
    <lastBuildDate>{now.strftime("%a, %d %b %Y %H:%M:%S +0800")}</lastBuildDate>
    {"".join(feed_items)}
</channel>
</rss>
"""
    feed_path = OUTPUT_DIR / "feed.xml"
    feed_path.write_text(feed_xml, encoding="utf-8")
    log.info("已生成 RSS 2.0 订阅源: %s", feed_path)
    return feed_path
