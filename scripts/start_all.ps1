# ===== QQ聊天助手 一键启动器 =====
# 逻辑：NapCat没开就启动 -> 等QQ登录(3001端口) -> 机器人没跑就启动
# 重复双击安全：已在运行的部分自动跳过
$ErrorActionPreference = "Continue"
$root = "D:\小编程\qq-assistant"
$napcatDir = Join-Path $root "NapCat\Shell"
$venvPy = Join-Path $root "venv\Scripts\python.exe"

function Test-Port($port) {
    return $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Test-BotRunning {
    $p = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*qq-assistant*main.py*" }
    return $null -ne $p
}

Write-Host ""
Write-Host "======== QQ聊天助手 启动器 ========" -ForegroundColor Cyan

# ---- 1. NapCat ----
if ((Test-Port 6099) -or (Get-Process NapCatWinBootMain -ErrorAction SilentlyContinue)) {
    Write-Host "[1/3] NapCat 已在运行，跳过" -ForegroundColor Gray
} else {
    Write-Host "[1/3] 正在启动 NapCat（QQ登录窗口即将弹出，如需扫码请用小号2531285699扫）..."
    Start-Process cmd -ArgumentList "/c", "`"$napcatDir\launcher-user.bat`"" -WorkingDirectory $napcatDir
    Start-Sleep 5
}

# ---- 2. 等待QQ登录（3001端口） ----
if (Test-Port 3001) {
    Write-Host "[2/3] OneBot 端口 3001 已就绪（QQ已登录）" -ForegroundColor Gray
} else {
    Write-Host "[2/3] 等待QQ登录中（最多3分钟）..."
    Write-Host "      提示：请在弹出的QQ窗口用【小号2531285699】扫码登录" -ForegroundColor Yellow
    $ok = $false
    for ($i = 0; $i -lt 36; $i++) {
        if (Test-Port 3001) { $ok = $true; break }
        Start-Sleep -Seconds 5
    }
    if ($ok) {
        Write-Host "      登录成功，3001 已就绪"
    } else {
        Write-Host "      等待超时：QQ 还没登录。机器人稍后会自动重连，也可登录后重新运行本启动器。" -ForegroundColor Yellow
    }
}

# ---- 3. 机器人 ----
if (Test-BotRunning) {
    Write-Host "[3/3] 机器人已在运行，跳过" -ForegroundColor Gray
} else {
    Write-Host "[3/3] 正在启动机器人..."
    Start-Process -FilePath $venvPy -ArgumentList "main.py" -WorkingDirectory $root
    Start-Sleep 4
    if (Test-BotRunning) {
        Write-Host "      机器人已启动（日志在它的黑窗口里）"
    } else {
        Write-Host "      启动可能失败：请检查 config.yaml 是否存在、venv 是否完好" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "======== 完成 ========" -ForegroundColor Green
Write-Host " 对话方式：私聊【东小0】直接说，或群里 @东小0 + 内容"
Write-Host " 停止方法：关闭 NapCat 和机器人两个黑窗口即可"
Write-Host ""
Write-Host "按任意键关闭本窗口..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
