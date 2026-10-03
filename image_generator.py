# -*- coding: utf-8 -*-
"""
High-resolution long image generator for Daily News Digest.
Uses Playwright to render the HTML digest into a crisp 2x Retina PNG card.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

log = logging.getLogger("daily-news")


def generate_digest_image(
    html_source: Union[str, Path],
    output_path: Path,
    width: int = 860,
    scale: int = 2
) -> Path | None:
    """
    Render HTML digest into a high-resolution long PNG image.

    Args:
        html_source: HTML string content or Path to an .html file.
        output_path: Target path for the output .png image.
        width: Viewport width in pixels (default: 860).
        scale: Device scale factor for high DPI / Retina rendering (default: 2).

    Returns:
        Path to generated image if successful, None otherwise.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("Playwright 未安装，跳过长图生成。可通过 'pip install playwright && playwright install chromium' 启用。")
        return None

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        log.info("正在使用无头浏览器引擎渲染高清长图 (scale=%dx)...", scale)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(
                viewport={"width": width, "height": 1000},
                device_scale_factor=scale
            )
            page = context.new_page()

            if isinstance(html_source, Path) or (isinstance(html_source, str) and Path(html_source).is_file()):
                page.goto(Path(html_source).resolve().as_uri())
            else:
                page.set_content(str(html_source), wait_until="networkidle")

            page.wait_for_load_state("networkidle")

            # Try to screenshot the main .container card for a clean bordered aesthetic
            container = page.locator(".container")
            if container.count() > 0:
                container.screenshot(path=str(output_path), type="png")
            else:
                page.screenshot(path=str(output_path), full_page=True, type="png")

            browser.close()

        file_size_kb = output_path.stat().st_size / 1024
        log.info("高清长图生成成功！路径: %s (大小: %.1f KB)", output_path, file_size_kb)
        return output_path

    except Exception as exc:
        log.warning("高清长图生成失败（不影响邮件正常发送）: %s: %s", type(exc).__name__, exc)
        return None
