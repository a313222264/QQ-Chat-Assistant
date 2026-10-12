"""QQ机器人看门狗：计划任务每5分钟运行一次，自动检测并自愈常见故障。

判定与动作（只动机器人QQ实例，即命令行含 --enable-logging 的主进程，绝不碰你自己的QQ）：
    1. 机器人QQ进程没了       -> 重新拉起 NapCat（快速登录一般自动恢复）
    2. 发送失败标记是新鲜的   -> 判定会话假死：只杀机器人QQ实例 -> 重启 NapCat
    3. 其他情况               -> 记录正常，不动作

日志：logs/watchdog.log。用 pythonw 运行（无窗口）。
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHELL = ROOT / "NapCat" / "Shell"
FLAG = ROOT / "data" / "send_fail.flag"
LOG = ROOT / "logs" / "watchdog.log"
FLAG_FRESH_SECONDS = 20 * 60  # 20分钟内的发送失败标记视为有效证据


def log(msg: str):
    line = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    try:
        print(line)
    except Exception:
        pass  # pythonw 下无 stdout


def bot_qq_mains() -> list:
    """机器人QQ主进程（--enable-logging），不含你自己开的QQ。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='QQ.exe'\" -ErrorAction SilentlyContinue | "
             "Where-Object { $_.CommandLine -match '--enable-logging' } | "
             "ForEach-Object { $_.ProcessId }"],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return [int(x) for x in out.split() if x.isdigit()]
    except Exception:
        return []


def kill_bot_qq(pids: list):
    for pid in pids:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, timeout=30)
    subprocess.run(["taskkill", "/IM", "NapCatWinBootMain.exe", "/F"],
                   capture_output=True, timeout=30)


def start_napcat():
    """最小化启动 NapCat（黑色控制台缩到任务栏，不抢屏幕）。"""
    subprocess.Popen(
        ["cmd", "/c", "start", "/min", "", "launcher-user.bat"],
        cwd=str(SHELL),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def health_checks(fix_send: bool) -> None:
    """通用检查：机器人QQ缺失则拉起；fix_send=True 时再用发送实测判定假死并修复。"""
    pids = bot_qq_mains()
    if not pids:
        log("机器人QQ进程缺失 -> 重新拉起 NapCat")
        start_napcat()
        return

    if fix_send:
        # 主动实测发送通道（唤醒场景：睡眠可能把会话变僵尸，读接口看不出来）
        try:
            out = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "healthcheck.py"), "sendtest"],
                capture_output=True, text=True, timeout=90,
            ).stdout
        except Exception as e:
            log(f"唤醒自检发送实测失败: {e.__class__.__name__}")
            return
        if "retcode=0" in out:
            log("唤醒自检：发送通道正常")
            return
        log(f"唤醒自检：发送通道异常({out.strip()[:80]}) -> 只杀机器人QQ实例并重启")
        kill_bot_qq(pids)
        time.sleep(3)
        start_napcat()
        log("NapCat 已重启（如快速登录失效，请在QQ窗口扫码）")
        return

    # 常规模式：只看发送失败标记（不打扰群）
    try:
        flag_ts = float(FLAG.read_text(encoding="utf-8").strip())
        fresh = time.time() - flag_ts < FLAG_FRESH_SECONDS
    except (ValueError, OSError):
        fresh = False

    if fresh:
        log("检测到新鲜的发送失败标记 -> 判定会话假死，只杀机器人QQ实例并重启")
        kill_bot_qq(pids)
        time.sleep(3)
        try:
            FLAG.unlink()
        except OSError:
            pass
        start_napcat()
        log("NapCat 已重启（如快速登录失效，请在QQ窗口/弹出的二维码扫码）")
        return

    log("一切正常")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "normal"

    if mode == "resume":
        # 系统唤醒事件触发：等网络和QQ先自己重连1分钟，再带发送实测的检查
        time.sleep(60)
        log("系统唤醒 -> 执行唤醒自检")
        health_checks(fix_send=True)
        return

    # 常规定时巡检
    health_checks(fix_send=False)


if __name__ == "__main__":
    main()
