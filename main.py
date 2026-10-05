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
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
import schedule

# Ensure Windows terminal handles UTF-8 gracefully
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from config import config
from collector import collect_all_sources
from analyzer import analyze_news, validate_report_integrity
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


def clean_old_outputs(retention_days: int = 7) -> None:
    """Retain only recent N days of generated reports in output directory to prevent disk exhaustion."""
    if not OUTPUT_DIR.exists():
        return
    cutoff_time = time.time() - (retention_days * 86400)
    cleaned_count = 0
    reclaimed_bytes = 0
    for f in OUTPUT_DIR.glob("*"):
        if f.is_file() and f.suffix.lower() in {".html", ".md", ".png", ".jpg", ".jpeg"}:
            try:
                mtime = f.stat().st_mtime
                if mtime < cutoff_time:
                    reclaimed_bytes += f.stat().st_size
                    f.unlink()
                    cleaned_count += 1
            except Exception as e:
                log.debug("清理文件失败 %s: %s", f, e)
    if cleaned_count > 0:
        log.info("已自动清理 %d 个超过 %d 天的旧报告文件，释放空间: %.1f MB",
                 cleaned_count, retention_days, reclaimed_bytes / (1024 * 1024))


def save_run_status(status_data: dict[str, Any]) -> None:
    """Save structured execution status and diagnostics to output/status.json."""
    status_file = OUTPUT_DIR / "status.json"
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        status_file.write_text(json.dumps(status_data, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("已更新运行诊断快照: %s", status_file)
    except Exception as e:
        log.debug("写入状态快照失败: %s", e)


class SingleInstanceLock:
    """Simple file-based lock to prevent overlapping scheduled/manual runs."""
    def __init__(self, lock_file: Path):
        self.lock_file = lock_file
        self.acquired = False

    def __enter__(self) -> bool:
        if self.lock_file.exists():
            try:
                age = time.time() - self.lock_file.stat().st_mtime
                if age < 1800:
                    log.warning("检测到已有任务实例正在运行 (锁文件: %s，已存在 %.0f 秒)，终止本次执行以防并发冲突。",
                                self.lock_file.name, age)
                    return False
                else:
                    log.warning("发现超过 30 分钟的残留锁文件，自动重置接管。")
                    self.lock_file.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            self.lock_file.parent.mkdir(parents=True, exist_ok=True)
            self.lock_file.write_text(str(time.time()), encoding="utf-8")
            self.acquired = True
            return True
        except Exception as e:
            log.warning("锁文件创建受阻: %s，继续执行", e)
            return True

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.acquired:
            try:
                self.lock_file.unlink(missing_ok=True)
            except Exception:
                pass


def execute_digest(*, dry_run: bool = False) -> None:
    """Execute a complete news collection, analysis, and delivery cycle."""
    # 0. 启动配置合法性强校验（Fail-Fast 机制）
    cfg_errors = config.validate()
    if cfg_errors:
        for err in cfg_errors:
            log.error("❌ 配置校验错误: %s", err)
        if not dry_run:
            raise ValueError(f"应用启动失败，配置存在以下错误 ({len(cfg_errors)} 项):\n" + "\n".join(f"- {e}" for e in cfg_errors))

    lock = SingleInstanceLock(OUTPUT_DIR.parent / ".daily_digest.lock")
    with lock as ok:
        if not ok:
            return

        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        start_ts = datetime.now(ZoneInfo(config.digest_timezone)).isoformat()
        log.info("========== 开始执行每日财经与中国宏观简报任务 (ID: %s) ==========", run_id)
        started_at = time.perf_counter()
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)

        status_record: dict[str, Any] = {
            "run_id": run_id,
            "started_at": start_ts,
            "dry_run": dry_run,
            "overall_status": "RUNNING",
            "sources_scraped": {},
            "total_articles": 0,
            "scraping_errors": [],
            "report_validation": {},
            "image_generated": False,
            "image_size_kb": None,
            "email_sent": False,
            "duration_seconds": 0.0,
        }

        try:
            # 启动日志：打印当前激活的 AI 引擎与模型链
            providers = config.get_configured_providers()
            p_desc = " -> ".join([f"{p['name']}({p['model']})" for p in providers]) if providers else "无（使用纯列表兜底）"
            log.info("当前有效 AI 分析引擎链: %s", p_desc)
            status_record["configured_providers"] = [p["name"] for p in providers]

            # 1. 抓取七大权威外媒（并发并行抓取）
            log.info("正在并发抓取七大外媒（彭博社、路透社、华尔街日报、金融时报、联合早报、日经中文网、经济学人）...")
            articles_by_source, errors = collect_all_sources(
                lookback_hours=config.lookback_hours,
                max_per_source=config.max_items_per_source
            )
            
            total_articles = sum(len(v) for v in articles_by_source.values())
            status_record["sources_scraped"] = {src: len(items) for src, items in articles_by_source.items()}
            status_record["total_articles"] = total_articles
            status_record["scraping_errors"] = list(errors)
            log.info("抓取完成！共获取 %d 篇有效报道：", total_articles)
            for src, items in articles_by_source.items():
                log.info("  * %s: %d 篇", src, len(items))
            if errors:
                log.warning("抓取遇到以下告警: %s", "；".join(errors))

            # 2. 深度分析与影响剖析
            log.info("正在生成财经与中国宏观深度分析报告...")
            report_markdown = analyze_news(articles_by_source, errors)
            is_valid, integrity_issues = validate_report_integrity(report_markdown)
            status_record["report_validation"] = {
                "is_valid": is_valid,
                "issues": integrity_issues,
                "word_count": len(report_markdown),
            }

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
            if long_image_path and Path(long_image_path).exists():
                status_record["image_generated"] = True
                status_record["image_size_kb"] = round(Path(long_image_path).stat().st_size / 1024, 1)

            log.info("已生成本地文件：\n  - Markdown: %s\n  - HTML: %s\n  - Long Image: %s",
                     md_file, html_file, long_image_path or "(未生成)")

            # 自动维护：清理过期旧输出
            clean_old_outputs(config.output_retention_days)

            # 4. 邮件发送
            if dry_run:
                log.info("[Dry Run 模式] 本次执行仅生成预览与长图，不发送邮件。")
                status_record["overall_status"] = "SUCCESS_DRY_RUN"
                return

            log.info("正在向目标邮箱 [%s] 发送简报邮件（含高清长图附件）...", config.mail_to)
            send_digest_email(report_markdown, errors, image_path=long_image_path)
            status_record["email_sent"] = True
            status_record["overall_status"] = "SUCCESS"
            log.info("========== 简报任务成功完成！总耗时: %.1f 秒 ==========", time.perf_counter() - started_at)

        except Exception as exc:
            status_record["overall_status"] = "FAILED"
            status_record["failure_reason"] = f"{type(exc).__name__}: {exc}"
            log.error("简报任务执行失败: %s: %s", type(exc).__name__, exc)
            raise exc
        finally:
            status_record["completed_at"] = datetime.now(ZoneInfo(config.digest_timezone)).isoformat()
            status_record["duration_seconds"] = round(time.perf_counter() - started_at, 2)
            save_run_status(status_record)


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
    schedule.every().day.at(target_time, tz=config.digest_timezone).do(job)

    while True:
        schedule.run_pending()
        time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(description="每日财经与中国宏观外媒新闻抓取、总结与影响分析服务")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--run-now", action="store_true", help="立即执行抓取、总结并发起邮件发送")
    mode.add_argument("--dry-run", action="store_true", help="立即执行抓取和总结，生成本地 HTML/MD 预览，不发邮件")
    mode.add_argument("--schedule", action="store_true", help="以常驻进程模式启动内置定时任务调度器（默认每天08:00）")
    mode.add_argument("--test-sources", action="store_true", help="仅测试七大外媒的数据源连接与抓取能力")
    mode.add_argument("--test-mail", action="store_true", help="测试 SMTP 邮件连接并发送一封测试邮件")

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
