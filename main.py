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
from logging.handlers import RotatingFileHandler
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
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
from market_data import fetch_market_snapshot, render_market_table
from seen_history import filter_cross_day_duplicates, record_pushed_articles
from article_extractor import enrich_top_articles
from notifier import dispatch_webhooks
from archive_manager import archive_daily_digest, generate_archive_portal, generate_rss_feed

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
LOGS_DIR = Path(__file__).resolve().parent / "logs"


# Setup dual logging: stdout + persistent rotating file handler
LOGS_DIR.mkdir(parents=True, exist_ok=True)
log_file_path = LOGS_DIR / "daily_news.log"
file_handler = RotatingFileHandler(
    log_file_path,
    maxBytes=5 * 1024 * 1024,  # 5MB
    backupCount=3,
    encoding="utf-8"
)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))

logging.basicConfig(
    level=logging.INFO,
    handlers=[stream_handler, file_handler]
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


def _atomic_write_text(path: Path, content: str) -> None:
    """Write UTF-8 text content atomically by writing to a temporary sibling file and replacing the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            delete=False,
            dir=path.parent,
            encoding='utf-8',
            mode='w',
        ) as tmp_file:
            tmp_path = Path(tmp_file.name)
            tmp_file.write(content)
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        raise


def save_run_status(status_data: dict[str, Any]) -> None:
    """Save structured execution status and diagnostics to output/status.json."""
    status_file = OUTPUT_DIR / "status.json"
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(status_file, json.dumps(status_data, ensure_ascii=False, indent=2))
        log.info("已更新运行诊断快照: %s", status_file)
    except Exception as e:
        log.debug("写入状态快照失败: %s", e)


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with given PID is still active."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


class SingleInstanceLock:
    """
    File-based lock with stale-lock detection and automatic recovery.
    Prevents overlapping scheduled/manual runs while recovering gracefully from crashes.
    """
    def __init__(self, lock_file: Path, max_age_seconds: int = 7200):
        self.lock_file = lock_file
        self.max_age_seconds = max_age_seconds
        self.acquired = False

    def _check_and_clean_stale_lock(self) -> bool:
        """Return True if lock file was stale and successfully cleaned."""
        if not self.lock_file.exists():
            return False
        try:
            content = self.lock_file.read_text(encoding="utf-8").strip()
            pid = None
            started_at = None
            for line in content.splitlines():
                if line.startswith("pid="):
                    pid = int(line.split("=", 1)[1].strip())
                elif line.startswith("started_at="):
                    started_at = datetime.fromisoformat(line.split("=", 1)[1].strip())

            now = datetime.now(timezone.utc)
            is_stale = False
            reason = ""

            # Check age
            if started_at:
                age_seconds = (now - started_at).total_seconds()
                if age_seconds > self.max_age_seconds:
                    is_stale = True
                    reason = f"超时 (已存活 {int(age_seconds)} 秒 > {self.max_age_seconds} 秒)"

            # Check pid liveness if not already deemed stale
            if not is_stale and pid:
                if not _is_pid_alive(pid):
                    is_stale = True
                    reason = f"持有锁的进程 (PID: {pid}) 已终止"

            if is_stale:
                log.warning("检测到孤儿锁文件 (%s，原因: %s)，自动回收并继续执行。", self.lock_file.name, reason)
                self.lock_file.unlink(missing_ok=True)
                return True

        except Exception as e:
            log.debug("读取锁文件诊断信息异常: %s", e)

        return False

    def __enter__(self) -> bool:
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)

        for attempt in range(2):
            try:
                with self.lock_file.open('x', encoding='utf-8') as handle:
                    handle.write(f"pid={os.getpid()}\nstarted_at={datetime.now(timezone.utc).isoformat()}\n")
                self.acquired = True
                return True
            except FileExistsError:
                if attempt == 0 and self._check_and_clean_stale_lock():
                    continue  # cleaned stale lock, try acquiring again
                log.warning("检测到已有活跃任务实例正在运行 (锁文件: %s)，终止本次执行以防并发冲突。", self.lock_file.name)
                return False
            except Exception as e:
                log.warning("锁文件创建失败: %s，终止本次执行", e)
                return False
        return False

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

            # 1. 抓取实时宏观与大类资产行情快照
            log.info("正在获取全球大类资产与宏观行情快照（A股基准、恒指、美股大盘、黄金ETF、离岸人民币）...")
            market_quotes = fetch_market_snapshot(timeout=config.fetch_timeout)
            if market_quotes:
                log.info("成功获取 %d 项资产与宏观行情指标", len(market_quotes))
                status_record["market_quotes_count"] = len(market_quotes)

            # 2. 抓取七大权威外媒（并发并行抓取）
            log.info("正在并发抓取七大外媒（彭博社、路透社、华尔街日报、金融时报、联合早报、日经中文网、经济学人）...")
            articles_by_source, errors = collect_all_sources(
                lookback_hours=config.lookback_hours,
                max_per_source=config.max_items_per_source
            )

            # 3. 跨日去重引擎：过滤往期已报道新闻，防止连续多日信息冗余
            articles_by_source, removed_hist = filter_cross_day_duplicates(articles_by_source)
            status_record["cross_day_duplicates_removed"] = removed_hist

            # 4. 深度正文抽取：为高分核心要闻拉取实质性正文，充实分析事实依据
            enriched_count = enrich_top_articles(articles_by_source, top_n=8)
            status_record["enriched_articles_count"] = enriched_count

            total_articles = sum(len(v) for v in articles_by_source.values())
            status_record["sources_scraped"] = {src: len(items) for src, items in articles_by_source.items()}
            status_record["total_articles"] = total_articles
            status_record["scraping_errors"] = list(errors)
            log.info("抓取完成！共获取 %d 篇有效报道：", total_articles)
            for src, items in articles_by_source.items():
                log.info("  * %s: %d 篇", src, len(items))
            if errors:
                log.warning("抓取遇到以下告警: %s", "；".join(errors))

            # 5. 深度分析与影响剖析（结合行情快照与资产配置指引）
            log.info("正在生成财经与中国宏观深度分析报告...")
            report_markdown = analyze_news(articles_by_source, errors, market_quotes=market_quotes)
            is_valid, integrity_issues = validate_report_integrity(report_markdown)
            status_record["report_validation"] = {
                "is_valid": is_valid,
                "issues": integrity_issues,
                "word_count": len(report_markdown),
            }

            is_fallback = ("未启用大模型智能分析兜底模式" in report_markdown)
            is_no_news = status_record.get("total_articles", 0) == 0
            if not is_valid and not dry_run and not is_fallback and not is_no_news:
                issues_summary = "; ".join(integrity_issues) if integrity_issues else "no specific issues reported"
                raise ValueError(f"Report integrity validation failed: {issues_summary}")

            # 6. 本地存储预览备份与高清长图生成
            now = datetime.now(ZoneInfo(config.digest_timezone))
            date_tag = now.strftime("%Y%m%d")
            md_file = OUTPUT_DIR / f"digest_{date_tag}.md"
            html_file = OUTPUT_DIR / f"digest_{date_tag}.html"
            img_file = OUTPUT_DIR / f"digest_{date_tag}.png"

            html_content = render_html_document(report_markdown, errors)
            _atomic_write_text(md_file, report_markdown)
            _atomic_write_text(html_file, html_content)

            # 渲染高清长图 (2x Retina 高清分辨率)
            long_image_path = generate_digest_image(html_file, img_file)
            if long_image_path and Path(long_image_path).exists():
                status_record["image_generated"] = True
                status_record["image_size_kb"] = round(Path(long_image_path).stat().st_size / 1024, 1)

            log.info("已生成本地文件：\n  - Markdown: %s\n  - HTML: %s\n  - Long Image: %s",
                     md_file, html_file, long_image_path or "(未生成)")

            # 7. 永久归档、门户索引更新与 RSS 2.0 订阅源生成（仅正式运行写入，Dry Run 不污染历史归档）
            if not dry_run:
                archive_daily_digest(report_markdown, html_content, date_tag, image_path=long_image_path)

                # 自动维护：先清理过期旧输出，再生成门户索引与 RSS，避免索引引用刚被删除的历史文件
                clean_old_outputs(config.output_retention_days)
                generate_archive_portal()
                generate_rss_feed()

            # 8. 邮件发送与多渠道 Webhook 协同通知（先完成归档与输出，再做投递）
            if dry_run:
                log.info("[Dry Run 模式] 本次执行仅生成预览与长图，不写入历史归档，不发送邮件与通知，也不记录已推送文章库。")
                status_record["overall_status"] = "SUCCESS_DRY_RUN"
                return

            email_success = False
            recipients = config.recipient_list
            if recipients:
                log.info("正在向目标邮箱 [%s] 发送简报邮件（含高清长图附件）...", ", ".join(recipients))
                try:
                    send_digest_email(report_markdown, errors, image_path=long_image_path)
                    email_success = True
                    status_record["email_sent"] = True
                except Exception as mail_err:
                    log.error("邮件发送异常: %s", mail_err)
                    errors.append(f"邮件发送失败: {mail_err}")

            # 9. 多渠道 Webhook 协同推送 (企业微信 / 飞书 / 钉钉 / Server酱 / Telegram / NapCat QQ群 / 微信群)
            digest_title = f"【每日财经与中国宏观深度简报】{now.strftime('%Y-%m-%d')}"
            webhook_results = dispatch_webhooks(digest_title, report_markdown, image_path=long_image_path)
            if webhook_results:
                status_record["webhooks_dispatched"] = webhook_results

            webhook_success = bool(webhook_results) and any(bool(v) for v in webhook_results.values())
            delivery_success = bool(email_success or webhook_success)

            if not delivery_success:
                failure_detail = "所有投递渠道均未成功（邮件: %s；Webhook: %s）" % (
                    "已配置但发送失败" if recipients else "未配置收件人",
                    "已配置但推送失败" if webhook_results else "未配置",
                )
                status_record["overall_status"] = "DELIVERY_FAILED"
                status_record["delivery_failure_reason"] = failure_detail
                log.error("❌ 简报投递失败：%s", failure_detail)
                raise RuntimeError(f"Digest delivery failed: {failure_detail}")

            # 10. 仅在非 dry-run 且至少一个投递渠道成功后，记录已推送文章库以供后续跨日去重
            record_pushed_articles(articles_by_source, is_dry_run=False)
            status_record["overall_status"] = "SUCCESS"

            log.info("========== 简报任务成功完成！总耗时: %.1f 秒 ==========", time.perf_counter() - started_at)


        except Exception as exc:
            # 保留投递失败终态，避免被通用异常处理覆盖
            if status_record["overall_status"] != "DELIVERY_FAILED":
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
    target_recipients = ", ".join(config.recipient_list) if config.recipient_list else (config.mail_to or "(未设置)")
    log.info("收件人: %s | 大模型: %s", target_recipients, config.llm_model)
    log.info("按 Ctrl + C 可终止守护进程。\n")

    def job():
        try:
            execute_digest(dry_run=False)
        except Exception:
            log.exception("定时任务执行异常")

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
        separator = "=" * 50
        log.info("\n%s\n七大权威外媒连接测试结果：\n%s", separator, separator)
        for src, items in articles_by_source.items():
            status = "✅ 正常" if items else "❌ 暂无条目"
            log.info("[%s] %s - 抓取到 %d 条新闻：", src, status, len(items))
            for idx, a in enumerate(items, 1):
                log.info("   %d. %s (%s)", idx, a.title, a.published_at.strftime('%Y-%m-%d %H:%M'))
                log.info("      链接: %s", a.url)
        if errors:
            log.warning("\n告警信息：")
            for err in errors:
                log.warning(" - %s", err)
        log.info("%s\n", separator)
        return

    if args.test_mail:
        log.info("正在测试 SMTP 邮箱连接...")
        if test_smtp_connection():
            target_recipients = ", ".join(config.recipient_list) if config.recipient_list else config.mail_to
            log.info("SMTP 验证成功！正在向 %s 发送测试邮件...", target_recipients)
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

    parser.print_help()


if __name__ == "__main__":
    main()
