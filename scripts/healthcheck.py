"""机器人健康检查小工具（桌面启动器 v2 与诊断共用，venv python 运行）。

用法：
    python healthcheck.py status           只读健康检查：登录信息+在线状态，exit 0=正常
    python healthcheck.py sendtest         向推送群发一条🔧自检消息验证发送通道，exit 0=成功
    python healthcheck.py login [qr路径]   登录WebUI拿凭证存NapCat/_cred.txt；
                                           未登录且给了qr路径时生成二维码PNG；输出 loginPhase 行
"""
import asyncio
import hashlib
import json
import sys
import uuid
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
WS_URL = "ws://127.0.0.1:3001"
WEBUI = "http://127.0.0.1:6099"
WEBUI_TOKEN = "f56a526c77f8"
CRED_FILE = ROOT / "NapCat" / "_cred.txt"
SELFCHECK_TEXT = "🔧 自检：发送通道正常，机器人在线"


def load_config() -> dict:
    import yaml

    cfg_path = ROOT / "config.yaml"
    if cfg_path.exists():
        return yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return {}


def _ws_call(ws, action: str, params: dict):
    async def go():
        import websockets

        async with websockets.connect(WS_URL, max_size=20 * 1024 * 1024) as w:
            echo = uuid.uuid4().hex
            await w.send(json.dumps({"action": action, "params": params, "echo": echo}))
            while True:
                d = json.loads(await asyncio.wait_for(w.recv(), 15))
                if d.get("echo") == echo:
                    return d
    return asyncio.run(go())


def cmd_status() -> int:
    try:
        login = _ws_call(None, "get_login_info", {})
        st = _ws_call(None, "get_status", {})
    except Exception as e:
        print(f"STATUS 连接失败: {e.__class__.__name__}")
        return 1
    print(json.dumps({
        "login_ok": login.get("retcode") == 0,
        "nickname": (login.get("data") or {}).get("nickname"),
        "online": (st.get("data") or {}).get("online"),
    }, ensure_ascii=False))
    return 0 if login.get("retcode") == 0 else 1


def _push_group() -> int:
    cfg = load_config()
    groups = (cfg.get("plugins", {}).get("digest", {}).get("push_groups")
              or cfg.get("plugins", {}).get("proactive_chat", {}).get("groups")
              or [])
    return int(groups[0]) if groups else 0


def cmd_sendtest() -> int:
    gid = _push_group()
    if not gid:
        print("SENDTEST 未配置推送群(plugins.digest.push_groups / proactive_chat.groups)")
        return 2
    try:
        d = _ws_call(None, "send_group_msg", {
            "group_id": gid,
            "message": [{"type": "text", "data": {"text": SELFCHECK_TEXT}}],
        })
    except Exception as e:
        print(f"SENDTEST 失败: {e.__class__.__name__}")
        return 2
    print(f"SENDTEST status={d.get('status')} retcode={d.get('retcode')} "
          f"msg={(d.get('wording') or d.get('message') or '')[:80]}")
    return 0 if d.get("retcode") in (0, "0") else 2


def cmd_login(qr_path: str) -> int:
    import urllib.request

    h = hashlib.sha256((WEBUI_TOKEN + ".napcat").encode()).hexdigest()
    req = urllib.request.Request(
        WEBUI + "/api/auth/login",
        data=json.dumps({"hash": h, "totpCode": ""}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        cred = json.loads(urllib.request.urlopen(req, timeout=10).read())["data"]["Credential"]
    except Exception as e:
        print(f"LOGIN WebUI登录失败: {e.__class__.__name__}")
        return 1
    CRED_FILE.write_text(cred, encoding="utf-8")

    req2 = urllib.request.Request(
        WEBUI + "/api/QQLogin/CheckLoginStatus", data=b"{}",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + cred},
    )
    try:
        st = json.loads(urllib.request.urlopen(req2, timeout=10).read()).get("data", {})
    except Exception as e:
        print(f"LOGIN 状态查询失败: {e.__class__.__name__}")
        return 1

    phase = st.get("loginPhase", "")
    print(f"LOGIN isLogin={st.get('isLogin')} phase={phase}")
    if not st.get("isLogin") and qr_path:
        qr = st.get("qrcodeurl", "")
        if qr:
            import qrcode

            Path(qr_path).parent.mkdir(parents=True, exist_ok=True)
            qrcode.make(qr).save(qr_path)
            print(f"LOGIN QR已生成: {qr_path}")
    return 0


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        sys.exit(cmd_status())
    elif cmd == "sendtest":
        sys.exit(cmd_sendtest())
    elif cmd == "login":
        sys.exit(cmd_login(sys.argv[2] if len(sys.argv) > 2 else ""))
    else:
        print("用法: status | sendtest | login [qr路径]")
        sys.exit(1)
