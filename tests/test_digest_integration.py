# -*- coding: utf-8 -*-
"""End-to-end orchestration checks for delivery and history ordering."""

from types import SimpleNamespace

import pytest

import main


def _patch_digest_dependencies(monkeypatch, tmp_path, *, send_email, maintenance=None):
    statuses = []
    pushed = []
    if maintenance is None:
        maintenance = []
    output_dir = tmp_path / "output"
    logs_dir = tmp_path / "logs"
    config = SimpleNamespace(
        digest_timezone="Asia/Shanghai",
        fetch_timeout=1,
        lookback_hours=24,
        max_items_per_source=2,
        output_retention_days=7,
        recipient_list=["reader@example.com"],
        validate=lambda: [],
        get_configured_providers=lambda: [],
    )

    monkeypatch.setattr(main, "config", config)
    monkeypatch.setattr(main, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(main, "LOGS_DIR", logs_dir)
    monkeypatch.setattr(main, "save_run_status", statuses.append)
    monkeypatch.setattr(main, "fetch_market_snapshot", lambda timeout: [])
    monkeypatch.setattr(main, "collect_all_sources", lambda **kwargs: ({"wire": [object()]}, []))
    monkeypatch.setattr(main, "filter_cross_day_duplicates", lambda articles: (articles, 0))
    monkeypatch.setattr(main, "enrich_top_articles", lambda articles, top_n: 0)
    monkeypatch.setattr(main, "analyze_news", lambda articles, errors, market_quotes=None: "# Report")
    monkeypatch.setattr(main, "validate_report_integrity", lambda report: (True, []))
    monkeypatch.setattr(main, "render_html_document", lambda report, errors: "<html><title>Report</title></html>")

    def generate_image(html_file, image_file):
        image_file.write_bytes(b"png")
        return str(image_file)

    monkeypatch.setattr(main, "generate_digest_image", generate_image)
    monkeypatch.setattr(main, "archive_daily_digest", lambda *args, **kwargs: maintenance.append("archive"))
    monkeypatch.setattr(main, "generate_archive_portal", lambda: maintenance.append("portal"))
    monkeypatch.setattr(main, "generate_rss_feed", lambda: maintenance.append("rss"))
    monkeypatch.setattr(main, "clean_old_outputs", lambda retention_days: maintenance.append("clean"))
    monkeypatch.setattr(main, "send_digest_email", send_email)
    monkeypatch.setattr(main, "dispatch_webhooks", lambda title, report: {})
    monkeypatch.setattr(main, "record_pushed_articles", lambda articles, is_dry_run: pushed.append(is_dry_run))
    return statuses, pushed


def test_delivery_failure_does_not_record_history_and_fails_run(tmp_path, monkeypatch):
    def failing_email(*args, **kwargs):
        raise OSError("smtp unavailable")

    statuses, pushed = _patch_digest_dependencies(monkeypatch, tmp_path, send_email=failing_email)

    with pytest.raises(RuntimeError, match="Digest delivery failed"):
        main.execute_digest(dry_run=False)

    assert pushed == []
    assert statuses[-1]["overall_status"] == "DELIVERY_FAILED"
    assert statuses[-1]["delivery_failure_reason"]


def test_successful_delivery_records_history_after_send(tmp_path, monkeypatch):
    send_order = []

    def successful_email(*args, **kwargs):
        send_order.append("email")

    statuses, pushed = _patch_digest_dependencies(monkeypatch, tmp_path, send_email=successful_email)
    monkeypatch.setattr(main, "record_pushed_articles", lambda articles, is_dry_run: (send_order.append("history"), pushed.append(is_dry_run)))

    main.execute_digest(dry_run=False)

    assert statuses[-1]["overall_status"] == "SUCCESS"
    assert pushed == [False]
    assert send_order == ["email", "history"]


def test_no_news_run_still_delivers(tmp_path, monkeypatch):
    sent = []

    def successful_email(*args, **kwargs):
        sent.append("email")

    statuses, pushed = _patch_digest_dependencies(monkeypatch, tmp_path, send_email=successful_email)
    monkeypatch.setattr(main, "collect_all_sources", lambda **kwargs: ({}, []))
    monkeypatch.setattr(
        main,
        "analyze_news",
        lambda articles, errors, market_quotes=None: "## 📭 今日暂无有效新闻\n\n各数据源本时段均无更新。",
    )
    monkeypatch.setattr(main, "validate_report_integrity", lambda report: (False, ["报告长度过短"]))

    main.execute_digest(dry_run=False)

    assert sent == ["email"]
    assert statuses[-1]["overall_status"] == "SUCCESS"
    assert pushed == [False]


def test_invalid_report_with_articles_still_fails(tmp_path, monkeypatch):
    statuses, pushed = _patch_digest_dependencies(monkeypatch, tmp_path, send_email=lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "validate_report_integrity", lambda report: (False, ["missing modules"]))

    with pytest.raises(ValueError, match="Report integrity validation failed"):
        main.execute_digest(dry_run=False)

    assert statuses[-1]["overall_status"] == "FAILED"
    assert pushed == []


def test_dry_run_generates_preview_without_archive_or_delivery(tmp_path, monkeypatch):
    sent = []
    maintenance = []
    statuses, pushed = _patch_digest_dependencies(
        monkeypatch,
        tmp_path,
        send_email=lambda *args, **kwargs: sent.append("email"),
        maintenance=maintenance,
    )

    main.execute_digest(dry_run=True)

    assert statuses[-1]["overall_status"] == "SUCCESS_DRY_RUN"
    assert maintenance == []
    assert sent == []
    assert pushed == []


def test_regular_run_archives_cleans_then_rebuilds_portal_and_rss(tmp_path, monkeypatch):
    maintenance = []
    statuses, pushed = _patch_digest_dependencies(
        monkeypatch,
        tmp_path,
        send_email=lambda *args, **kwargs: None,
        maintenance=maintenance,
    )

    main.execute_digest(dry_run=False)

    assert statuses[-1]["overall_status"] == "SUCCESS"
    assert maintenance == ["archive", "clean", "portal", "rss"]
