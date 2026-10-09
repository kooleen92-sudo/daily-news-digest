# -*- coding: utf-8 -*-
"""End-to-end orchestration checks for delivery and history ordering."""

from types import SimpleNamespace

import pytest

import main


def _patch_digest_dependencies(monkeypatch, tmp_path, *, send_email):
    statuses = []
    pushed = []
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
    monkeypatch.setattr(main, "archive_daily_digest", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "generate_archive_portal", lambda: None)
    monkeypatch.setattr(main, "generate_rss_feed", lambda: None)
    monkeypatch.setattr(main, "clean_old_outputs", lambda retention_days: None)
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
