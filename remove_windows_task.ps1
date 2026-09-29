# -*- coding: utf-8 -*-
# Windows 计划任务删除脚本
$TaskName = "DailyNewsFinanceDigest8AM"

Write-Host "正在删除 Windows 计划任务: $TaskName ..." -ForegroundColor Yellow
schtasks.exe /delete /tn "$TaskName" /f

if ($LASTEXITCODE -eq 0) {
    Write-Host "✅ 计划任务已成功删除！" -ForegroundColor Green
} else {
    Write-Host "⚠️ 未找到该任务或删除失败。" -ForegroundColor Gray
}
