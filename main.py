# -*- coding: utf-8 -*-
"""
Main entry point for Daily News Digest & Impact Analysis.
Target media:
1. 彭博社 (Bloomberg)
2. 路透社 (Reuters)
3. 华尔街日报 (Wall Street Journal / WSJ)
4. 金融时报 (Financial Times / FT)
5. 联合早报 (Lianhe Zaobao)
6. 日经中文网 (Nikkei Chinese / Nikkei Asia)
7. 经济学人 (The Economist)

Usage:
  python main.py --dry-run        # Extract, analyze, and save preview to output/ without sending email
  python main.py --run-now        # Extract, analyze, and immediately send to email
  python main.py --schedule       # Run as a background daemon scheduled daily at 08:00 AM
  python main.py --test-sources   # Check connectivity and articles count for each of the 7 sources
  python main.py --test-mail      # Test SMTP settings by sending a quick test email
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import schedule

# Ensure Windows terminal handles UTF-8 gracefully
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from config import config
from collector import collect_all_sources
from analyzer import analyze_news
from mailer import send_digest_email, render_html_document, test_smtp_connection
from image_generator import generate_digest_image

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
LOGS_DIR = Path(__file__).resolve().parent / "logs"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger("daily-news")


def execute_digest(*, dry_run: bool = False) -> None:
    """Execute a complete news collection, analysis, and delivery cycle."""
    log.info("========== 开始执行每日财经与中国宏观简报任务 ==========")
    started_at = time.perf_counter()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 抓取七大权威外媒
    log.info("正在抓取七大外媒（彭博社、路透社、华尔街日报、金融时报、联合早报、日经中文网、经济学人）过去 %d 小时新闻...", config.lookback_hours)
    articles_by_source, errors = collect_all_sources(
        lookback_hours=config.lookback_hours,
        max_per_source=config.max_items_per_source
    )
    
    total_articles = sum(len(v) for v in articles_by_source.values())
    log.info("抓取完成！共获取 %d 篇有效报道：", total_articles)
    for src, items in articles_by_source.items():
        log.info("  * %s: %d 篇", src, len(items))
    if errors:
        log.warning("抓取遇到以下告警: %s", "；".join(errors))

    # 2. 深度分析与影响剖析
    log.info("正在生成财经与中国宏观深度分析报告...")
    report_markdown = analyze_news(articles_by_source, errors)

    # 3. 本地存储预览备份与高清长图生成
    now = datetime.now(ZoneInfo(config.digest_timezone))
    date_tag = now.strftime("%Y%m%d")
    md_file = OUTPUT_DIR / f"digest_{date_tag}.md"
    html_file = OUTPUT_DIR / f"digest_{date_tag}.html"
    img_file = OUTPUT_DIR / f"digest_{date_tag}.png"
    
    html_content = render_html_document(report_markdown, errors)
    md_file.write_text(report_markdown, encoding="utf-8")
    html_file.write_text(html_content, encoding="utf-8")

    # 渲染高清长图 (2x Retina 高清分辨率)
    long_image_path = generate_digest_image(html_file, img_file)

    log.info("已生成本地文件：\n  - Markdown: %s\n  - HTML: %s\n  - Long Image: %s",
             md_file, html_file, long_image_path or "(未生成)")

    # 4. 邮件发送
    if dry_run:
        log.info("[Dry Run 模式] 本次执行仅生成预览与长图，不发送邮件。")
        log.info("报告字数：%d，耗时：%.1f 秒", len(report_markdown), time.perf_counter() - started_at)
        return

    log.info("正在向目标邮箱 [%s] 发送简报邮件（含高清长图附件）...", config.mail_to)
    try:
        send_digest_email(report_markdown, errors, image_path=long_image_path)
        log.info("========== 简报任务成功完成！总耗时: %.1f 秒 ==========", time.perf_counter() - started_at)
    except Exception as exc:
        log.error("邮件发送失败: %s: %s", type(exc).__name__, exc)
        raise exc


def run_scheduler() -> None:
    """Run built-in scheduler daemon."""
    target_time = config.digest_time  # e.g. "08:00"
    log.info("启动定时任务守护进程...")
    log.info("每天早晨 %s (%s) 准时执行抓取与邮件推送任务", target_time, config.digest_timezone)
    log.info("收件人: %s | 大模型: %s", config.mail_to or "(未设置)", config.llm_model)
    log.info("按 Ctrl + C 可终止守护进程。\n")

    def job():
        try:
            execute_digest(dry_run=False)
        except Exception:
            log.exception("定时任务执行异常")

    # Schedule daily job
    schedule.every().day.at(target_time).do(job)

    while True:
        schedule.run_pending()
        time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="每日财经与中国宏观外媒新闻抓取、总结与影响分析服务")
    parser.add_argument("--run-now", action="store_true", help="立即执行抓取、总结并发起邮件发送")
    parser.add_argument("--dry-run", action="store_true", help="立即执行抓取和总结，生成本地 HTML/MD 预览，不发邮件")
    parser.add_argument("--schedule", action="store_true", help="以常驻进程模式启动内置定时任务调度器（默认每天08:00）")
    parser.add_argument("--test-sources", action="store_true", help="仅测试七大外媒的数据源连接与抓取能力")
    parser.add_argument("--test-mail", action="store_true", help="测试 SMTP 邮件连接并发送一封测试邮件")

    args = parser.parse_args()

    if args.test_sources:
        log.info("正在测试七大权威外媒连接...")
        articles_by_source, errors = collect_all_sources(lookback_hours=24, max_per_source=3)
        print("\n" + "="*50)
        print("七大权威外媒连接测试结果：")
        print("="*50)
        for src, items in articles_by_source.items():
            status = "✅ 正常" if items else "❌ 暂无条目"
            print(f"[{src}] {status} - 抓取到 {len(items)} 条新闻：")
            for idx, a in enumerate(items, 1):
                print(f"   {idx}. {a.title} ({a.published_at.strftime('%Y-%m-%d %H:%M')})")
                print(f"      链接: {a.url}")
        if errors:
            print("\n告警信息：")
            for err in errors:
                print(f" - {err}")
        print("="*50 + "\n")
        return

    if args.test_mail:
        log.info("正在测试 SMTP 邮箱连接...")
        if test_smtp_connection():
            log.info("SMTP 验证成功！正在向 %s 发送测试邮件...", config.mail_to)
            test_content = (
                "## 这是一个测试邮件\n\n"
                "您的每日财经与中国深度简报服务邮件配置已生效！\n\n"
                "- 目标关注媒体：彭博社、路透社、华尔街日报、金融时报、联合早报、日经中文网、经济学人\n"
                f"- 定时时间：每天早晨 {config.digest_time} ({config.digest_timezone})\n"
            )
            try:
                send_digest_email(test_content, [])
                log.info("测试邮件发送成功！请检查您的邮箱（包括垃圾邮件箱）。")
            except Exception as e:
                log.error("测试邮件发送失败: %s", e)
        else:
            log.error("SMTP 连接失败，请检查 .env 中的 SMTP 账号密码与服务器配置。")
        return

    if args.dry_run:
        execute_digest(dry_run=True)
        return

    if args.run_now:
        execute_digest(dry_run=False)
        return

    if args.schedule:
        run_scheduler()
        return

    # If no argument passed, show help
    parser.print_help()


if __name__ == "__main__":
    main()
