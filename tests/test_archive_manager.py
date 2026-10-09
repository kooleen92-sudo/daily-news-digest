# -*- coding: utf-8 -*-
"""Integration tests for archive manager, static HTML portal, and RSS feed."""

from archive_manager import archive_daily_digest, generate_archive_portal, generate_rss_feed


def test_archive_daily_digest(tmp_path, monkeypatch):
    monkeypatch.setattr("archive_manager.ARCHIVE_DIR", tmp_path / "archive")
    dest = archive_daily_digest("# Report", "<html>Report</html>", date_tag="20261008")
    assert dest.exists()
    assert (dest / "digest_20261008.md").exists()
    assert (dest / "digest_20261008.html").exists()


def test_archive_copies_image_and_portal_uses_nested_relative_links(tmp_path, monkeypatch):
    archive_dir = tmp_path / "archive"
    output_dir = tmp_path / "output"
    monkeypatch.setattr("archive_manager.ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr("archive_manager.OUTPUT_DIR", output_dir)
    output_dir.mkdir()

    image = tmp_path / "digest.png"
    image.write_bytes(b"png")
    archive_daily_digest("# Old", "<title>Old</title>", date_tag="20261007", image_path=str(image))
    (archive_dir / "2026" / "10" / "digest_20261007.md").write_text("# Old", encoding="utf-8")

    portal = generate_archive_portal()
    portal_text = portal.read_text(encoding="utf-8")
    assert "../archive/2026/10/digest_20261007.html" in portal_text
    assert "../archive/2026/10/digest_20261007.png" in portal_text
    assert "../archive/2026/10/digest_20261007.md" in portal_text
    assert (archive_dir / "2026" / "10" / "digest_20261007.png").read_bytes() == b"png"


def test_portal_omits_missing_sidecar_links_and_rss_keeps_archived_reports(tmp_path, monkeypatch):
    archive_dir = tmp_path / "archive"
    output_dir = tmp_path / "output"
    monkeypatch.setattr("archive_manager.ARCHIVE_DIR", archive_dir)
    monkeypatch.setattr("archive_manager.OUTPUT_DIR", output_dir)
    output_dir.mkdir()

    old_dir = archive_dir / "2025" / "01"
    old_dir.mkdir(parents=True)
    old_html = old_dir / "digest_20250102.html"
    old_html.write_text("<title>Archived</title>", encoding="utf-8")

    portal_text = generate_archive_portal().read_text(encoding="utf-8")
    assert "../archive/2025/01/digest_20250102.html" in portal_text
    assert "digest_20250102.png" not in portal_text
    assert "digest_20250102.md" not in portal_text

    rss_text = generate_rss_feed().read_text(encoding="utf-8")
    assert "<link>../archive/2025/01/digest_20250102.html</link>" in rss_text
    assert "20250102" in rss_text


def test_generate_archive_portal_and_rss(tmp_path, monkeypatch):
    monkeypatch.setattr("archive_manager.OUTPUT_DIR", tmp_path / "output")
    monkeypatch.setattr("archive_manager.ARCHIVE_DIR", tmp_path / "archive")

    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "digest_20261008.html").write_text("<title>Test Digest</title>", encoding="utf-8")
    (out_dir / "digest_20261008.md").write_text("# Digest", encoding="utf-8")

    portal = generate_archive_portal()
    assert portal.exists()
    assert "Test Digest" in portal.read_text(encoding="utf-8")

    rss = generate_rss_feed()
    assert rss.exists()
    assert "<rss version=\"2.0\">" in rss.read_text(encoding="utf-8")
    assert "20261008" in rss.read_text(encoding="utf-8")
