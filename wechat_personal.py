# -*- coding: utf-8 -*-
"""
Windows PC WeChat (微信电脑版) UI automation sender.
Automates sending text and images to personal WeChat groups using Windows native UI & clipboard.
Requires PC WeChat (WeChat.exe) to be running and logged in.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("daily-news")


def is_wechat_running() -> bool:
    """Check if WeChat.exe is currently active in process list."""
    if sys.platform != "win32":
        return False
    try:
        out = subprocess.check_output(
            ["tasklist", "/fi", "IMAGENAME eq WeChat.exe", "/nh"],
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            text=True,
            errors="ignore",
        )
        return "WeChat.exe" in out
    except Exception:
        return False


def send_to_wechat_group(
    group_name: str,
    text: str,
    image_path: Path | str | None = None,
) -> bool:
    """
    Send text and/or image to a personal WeChat group via Windows PC WeChat automation.
    
    Steps:
    1. Activate WeChat window.
    2. Search group name using Ctrl+F and press Enter.
    3. If image_path exists, load into clipboard, paste with Ctrl+V, and press Enter.
    4. Copy text summary into clipboard, paste with Ctrl+V, and press Enter.
    """
    if sys.platform != "win32":
        log.warning("微信电脑版 UI 自动化仅支持 Windows 操作系统")
        return False

    if not is_wechat_running():
        log.warning("未检测到正在运行的微信客户端 (WeChat.exe)，请确保微信已启动并保持登录状态。")
        return False

    group_name = group_name.strip()
    if not group_name:
        log.warning("未配置有效的微信群名称 (WECHAT_PERSONAL_GROUP)")
        return False

    def ps_escape(s: str) -> str:
        return s.replace("'", "''")

    img_resolved = ""
    if image_path:
        p = Path(image_path).resolve()
        if p.exists() and p.is_file():
            img_resolved = str(p)

    ps_code = f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ws = New-Object -ComObject WScript.Shell
$activated = $ws.AppActivate('微信')
if (-not $activated) {{
    $activated = $ws.AppActivate('WeChat')
}}

if (-not $activated) {{
    Write-Error "未能激活微信窗口，请确认微信未被最小化至系统托盘深层或权限受限。"
    exit 2
}}

Start-Sleep -Milliseconds 400

# 1. 唤起搜索并定位群聊 (Ctrl+F)
$ws.SendKeys('^f')
Start-Sleep -Milliseconds 400

[System.Windows.Forms.Clipboard]::SetText('{ps_escape(group_name)}')
$ws.SendKeys('^v')
Start-Sleep -Milliseconds 800

$ws.SendKeys('{{ENTER}}')
Start-Sleep -Milliseconds 600

# 2. 如果存在图片，优先发送长图
$imgPath = '{ps_escape(img_resolved)}'
if ($imgPath -and (Test-Path $imgPath)) {{
    try {{
        $img = [System.Drawing.Image]::FromFile($imgPath)
        [System.Windows.Forms.Clipboard]::SetImage($img)
        $ws.SendKeys('^v')
        Start-Sleep -Milliseconds 600
        $ws.SendKeys('{{ENTER}}')
        Start-Sleep -Milliseconds 800
        $img.Dispose()
    }} catch {{
        Write-Warning "粘贴图片失败: $_"
    }}
}}

# 3. 发送文字摘要
$text = @'
{text[:2000]}
'@

if ($text.Trim()) {{
    [System.Windows.Forms.Clipboard]::SetText($text)
    $ws.SendKeys('^v')
    Start-Sleep -Milliseconds 500
    $ws.SendKeys('{{ENTER}}')
}}

Write-Output "SUCCESS"
"""

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=25,
        )
        if "SUCCESS" in res.stdout:
            log.info("已通过 PC 微信自动化成功发送到微信群 [%s]！", group_name)
            return True
        else:
            log.warning("PC 微信自动化发送未成功: %s %s", res.stdout.strip(), res.stderr.strip())
            return False
    except Exception as exc:
        log.warning("执行 PC 微信自动化脚本异常: %s", exc)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="发送简报文本或长图至指定 Windows 个人微信群")
    parser.add_argument("--group", required=True, help="目标个人微信群完整名称")
    parser.add_argument("--text", default="每日简报测试消息", help="消息文本内容")
    parser.add_argument("--image", default=None, help="图片路径 (可选)")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    success = send_to_wechat_group(args.group, args.text, args.image)
    sys.exit(0 if success else 1)
