# ===== QQ聊天助手 启动器 v2 =====
# 双击进入菜单；支持参数直跑（调试用）：powershell -File start_all.ps1 -Action 1|2|3|4
# [1] 启动/重启（幂等）   [2] 全面修复（杀QQ+重启NapCat+扫码+验证发送）
# [3] 自检诊断             [4] 发送通道测试
param([string]$Action = "")

$ErrorActionPreference = "Continue"
$root = "D:\小编程\qq-assistant"
$napcatDir = Join-Path $root "NapCat\Shell"
$venvPy = Join-Path $root "venv\Scripts\python.exe"
$healthPy = Join-Path $root "scripts\healthcheck.py"
$qrPath = Join-Path $root "NapCat\_login_qr.png"

function Test-Port($port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Test-BotRunning {
    $p = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*qq-assistant*main.py*" }
    return $null -ne $p
}

function Get-BotQQMains {
    # 机器人QQ主进程 = 命令行含 --enable-logging（NapCat拉起的特征）
    # 你自己开的QQ（无此参数）永远不会被匹配到
    return @(Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "--enable-logging" })
}

function Kill-BotQQ {
    # 只杀机器人QQ实例（连同其子进程树），绝不碰你自己开的QQ
    $mains = Get-BotQQMains
    if ($mains.Count -eq 0) { return $true }
    foreach ($m in $mains) {
        taskkill /PID $m.ProcessId /T /F 2>&1 | Out-Null
    }
    Stop-Process -Name NapCatWinBootMain -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 8; $i++) {
        if ((Get-BotQQMains).Count -eq 0) { break }
        Start-Sleep -Milliseconds 800
    }
    if ((Get-BotQQMains).Count -gt 0) {
        Write-Host "  !! 机器人QQ实例未能完全清除，请稍后重试" -ForegroundColor Red
        return $false
    }
    return $true
}

function Start-NapCatIfNeeded {
    if (Test-Port 6099) {
        Write-Host "[NapCat] 已在运行，跳过" -ForegroundColor Gray
        return
    }
    Write-Host "[NapCat] 正在启动（QQ登录窗口将弹出）..."
    Start-Process cmd -ArgumentList "/c", "`"$napcatDir\launcher-user.bat`"" -WorkingDirectory $napcatDir
    for ($i = 0; $i -lt 18; $i++) {
        if (Test-Port 6099) { Write-Host "[NapCat] 已上线(6099)"; return }
        Start-Sleep -Seconds 5
    }
    Write-Host "  !! NapCat 启动超时，请检查 Shell 目录" -ForegroundColor Yellow
}

function Start-BotIfNeeded {
    if (Test-BotRunning) {
        Write-Host "[机器人] 已在运行，跳过" -ForegroundColor Gray
        return
    }
    Write-Host "[机器人] 正在启动..."
    Start-Process -FilePath $venvPy -ArgumentList "main.py" -WorkingDirectory $root
    Start-Sleep -Seconds 4
    if (Test-BotRunning) { Write-Host "[机器人] 已启动" } else { Write-Host "  !! 启动失败，请检查 venv/config.yaml" -ForegroundColor Red }
}

function Wait-Login($maxMinutes) {
    # 用健康脚本轮询登录状态；未登录时每90秒刷新一次二维码并弹出
    $qrShown = $false
    $loops = $maxMinutes * 12
    for ($i = 1; $i -le $loops; $i++) {
        if ($i % 18 -eq 1) {
            $out = & $venvPy $healthPy login $qrPath 2>$null
            if (-not $qrShown) {
                Start-Process $qrPath
                $qrShown = $true
                Write-Host "  >> 二维码已弹出，请用手机上的小号(东小0)扫码登录" -ForegroundColor Yellow
            }
        } else {
            $out = & $venvPy $healthPy login "" 2>$null
        }
        if ($out -match "isLogin=True") { Write-Host "[QQ] 登录成功" -ForegroundColor Green; return $true }
        Start-Sleep -Seconds 5
    }
    Write-Host "  !! 等待扫码超时（$maxMinutes 分钟）" -ForegroundColor Red
    return $false
}

function Invoke-NormalStart {
    Write-Host ""
    Write-Host "======== 启动/重启 ========" -ForegroundColor Cyan
    Start-NapCatIfNeeded
    if (Test-Port 3001) {
        Write-Host "[QQ] OneBot 端口 3001 已就绪" -ForegroundColor Gray
    } else {
        Write-Host "[QQ] 等待登录（最多5分钟，需扫码时二维码会自动弹出）..."
        if (-not (Wait-Login 5)) { Write-Host "  >> 机器人会在你登录后自动重连，可稍后重新运行本启动器" -ForegroundColor Yellow }
    }
    Start-BotIfNeeded
    Write-Host ""
    Write-Host "完成。私聊或群里@东小0 即可对话；停止=关闭 NapCat 和机器人两个黑窗口" -ForegroundColor Green
}

function Invoke-FullRepair {
    Write-Host ""
    Write-Host "======== 全面修复 ========" -ForegroundColor Cyan
    Write-Host "  >> 只重启机器人的QQ实例，不会动你自己开的QQ" -ForegroundColor Yellow
    Write-Host "[1/5] 清除机器人 QQ 实例（解决会话假死/实例叠跑）..."
    if (-not (Kill-BotQQ)) { return }
    for ($i = 0; $i -lt 6; $i++) {
        if (-not (Test-Port 6099) -and -not (Test-Port 3001)) { break }
        Start-Sleep -Seconds 2
    }
    Write-Host "[2/5] 启动 NapCat..."
    Start-NapCatIfNeeded
    Write-Host "[3/5] 检查QQ登录状态..."
    if (Test-Port 3001) {
        Write-Host "  >> 已处于登录状态，无需扫码" -ForegroundColor Gray
    } else {
        Write-Host "  >> 需要扫码登录，二维码稍后弹出，请留意屏幕" -ForegroundColor Yellow
        if (-not (Wait-Login 10)) { return }
    }
    Write-Host "[4/5] 确保机器人运行..."
    Start-BotIfNeeded
    Write-Host "[5/5] 发送通道实测..."
    $sendOut = $null
    for ($i = 0; $i -lt 6; $i++) {
        $sendOut = & $venvPy $healthPy sendtest 2>$null
        if ($sendOut -match "retcode=0") { break }
        Start-Sleep -Seconds 10
    }
    Write-Host ($sendOut -join "`n")
    if ($sendOut -match "retcode=0") {
        Write-Host "  ✅ 发送通道正常，机器人已恢复（群里会看到🔧自检消息）" -ForegroundColor Green
    } else {
        Write-Host "  ❌ 发送通道仍异常" -ForegroundColor Red
        Write-Host "  >> 可能QQ又掉了，重新运行一次[2]，或检查网络后再说"
    }
}

function Invoke-Diagnose {
    Write-Host ""
    Write-Host "======== 自检诊断 ========" -ForegroundColor Cyan
    $all = @(Get-CimInstance Win32_Process -Filter "Name='QQ.exe'" -ErrorAction SilentlyContinue)
    $mains = @($all | Where-Object { $_.CommandLine -notmatch "--type=" })
    Write-Host ("QQ进程总数: " + $all.Count)
    $botMains = Get-BotQQMains
    $userMains = @($mains | Where-Object { $_.CommandLine -notmatch "--enable-logging" })
    Write-Host ("机器人QQ实例: " + $botMains.Count + " 套（多于1套=叠跑风险）")
    $botMains | ForEach-Object { Write-Host ("  [机器人] pid=" + $_.ProcessId + " start=" + $_.CreationDate.ToString("HH:mm:ss")) }
    if ($userMains.Count -gt 0) {
        Write-Host ("你自己的QQ实例: " + $userMains.Count + " 套（修复时不受影响）")
    }
    Write-Host ("端口6099: " + (Test-Port 6099) + "   端口3001: " + (Test-Port 3001))
    Write-Host ("机器人进程: " + (Test-BotRunning))
    if (Test-Port 3001) {
        $st = & $venvPy $healthPy status 2>$null
        Write-Host ("健康检查: " + ($st -join " "))
    }
    $logFile = Join-Path $root "logs\bot.log"
    if (Test-Path $logFile) {
        $recent = Get-Content $logFile -Tail 40 -ErrorAction SilentlyContinue | Select-String -Pattern "WARNING|ERROR|出错|失败|死亡" | Select-Object -Last 5
        if ($recent) { Write-Host "最近日志异常:" -ForegroundColor Yellow; $recent | ForEach-Object { Write-Host ("  " + $_.Line) } }
        else { Write-Host "最近日志无异常记录" -ForegroundColor Gray }
    }
    Write-Host ">> 疑似'会话死亡'(能收消息但发不出)时，选[2]全面修复"
}

function Invoke-SendTest {
    Write-Host ""
    Write-Host "======== 发送通道测试 ========" -ForegroundColor Cyan
    $out = & $venvPy $healthPy sendtest 2>$null
    Write-Host ($out -join "`n")
    if ($out -match "retcode=0") { Write-Host "✅ 发送正常" -ForegroundColor Green } else { Write-Host "❌ 发送失败，建议[2]全面修复" -ForegroundColor Red }
}

if ($Action) {
    switch ($Action) {
        "1" { Invoke-NormalStart; exit }
        "2" { Invoke-FullRepair; exit }
        "3" { Invoke-Diagnose; exit }
        "4" { Invoke-SendTest; exit }
    }
}

while ($true) {
    Write-Host ""
    Write-Host "======== QQ聊天助手 启动器 v2 ========" -ForegroundColor Cyan
    Write-Host "  [1] 启动/重启（幂等，缺什么启什么）"
    Write-Host "  [2] 全面修复（会话死亡/多实例叠跑的一键解法，需扫码）"
    Write-Host "  [3] 自检诊断（查QQ实例/端口/进程/日志）"
    Write-Host "  [4] 发送通道测试（向推送群发🔧自检消息）"
    Write-Host "  [q] 退出"
    $sel = Read-Host "选择（回车=[1]）"
    if ([string]::IsNullOrWhiteSpace($sel)) { $sel = "1" }
    switch ($sel) {
        "1" { Invoke-NormalStart }
        "2" { Invoke-FullRepair }
        "3" { Invoke-Diagnose }
        "4" { Invoke-SendTest }
        "q" { exit }
        "Q" { exit }
        default { Write-Host "无效选择" -ForegroundColor Yellow }
    }
}
