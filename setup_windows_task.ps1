# -*- coding: utf-8 -*-
# Windows 计划任务配置脚本：每天早上 08:00 自动执行简报抓取与发送
$ErrorActionPreference = "Stop"

$TaskName = "DailyNewsFinanceDigest8AM"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$BatchFile = Join-Path $ScriptDir "run_digest.bat"

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host " 配置每日早上 08:00 财经与中国宏观简报 Windows 定时任务" -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

if (-not (Test-Path $BatchFile)) {
    Write-Error "找不到批处理入口文件: $BatchFile"
    exit 1
}

# 1. 检查是否存在旧任务，若有先删除
$existingTask = schtasks.exe /query /tn "$TaskName" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "发现已存在的同名任务，正在移除更新..." -ForegroundColor Yellow
    schtasks.exe /delete /tn "$TaskName" /f | Out-Null
}

# 2. 创建新定时任务（每天 08:00 执行）
Write-Host "正在创建 Windows 计划任务: $TaskName ..." -ForegroundColor Green
Write-Host "执行时间: 每天 08:00:00" -ForegroundColor Gray
Write-Host "执行脚本: $BatchFile" -ForegroundColor Gray

# 使用 schtasks.exe 创建开机唤醒/按时运行任务
$createCmd = "schtasks.exe /create /tn `"$TaskName`" /tr `"`"$BatchFile`"`" /sc daily /st 08:00 /f"
Invoke-Expression $createCmd

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n✅ 定时任务创建成功！" -ForegroundColor Green
    Write-Host "任务名称: $TaskName" -ForegroundColor White
    Write-Host "每天 08:00 自动执行抓取分析并发送邮件。" -ForegroundColor White
    Write-Host "`n如需立即测试运行该计划任务，可运行:" -ForegroundColor Cyan
    Write-Host "  schtasks.exe /run /tn `"$TaskName`"" -ForegroundColor Yellow
    Write-Host "`n如需删除此计划任务，可运行同目录下的 remove_windows_task.ps1" -ForegroundColor Gray
} else {
    Write-Host "`n❌ 定时任务创建失败，请以管理员身份运行 PowerShell 后重试。" -ForegroundColor Red
}
