"""WS集成测试：本地起一个模拟 NapCat 的 OneBot 11 服务器，验证真实连接层。

验证点：
    1. 连接成功并自动获取登录信息（get_login_info 回包解析）
    2. 服务器推送事件 -> 分发 -> 消息存档入库
    3. bot.send_group_msg -> WS 请求 -> 模拟服务器回包 -> 拿到 data
    4. 服务器断开后自动重连
运行： venv/Scripts/python.exe scripts/ws_integration_test.py
"""
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import websockets

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config as config_mod  # noqa: E402
from core.api import Bot  # noqa: E402
from core.connection import NapCatConnection  # noqa: E402
from core.dispatcher import Dispatcher  # noqa: E402
from db.database import Database  # noqa: E402

PORT = 30119
SELF_ID = 888
GROUP_ID = 777

server_received = []          # 服务器收到的 action 请求
pushed_event = {
    "post_type": "message", "message_type": "group", "sub_type": "normal",
    "group_id": GROUP_ID, "user_id": 10001, "message_id": 555,
    "self_id": SELF_ID, "time": int(time.time()),
    "message": [{"type": "text", "data": {"text": "集成测试消息ABC"}}],
    "raw_message": "集成测试消息ABC",
    "sender": {"user_id": 10001, "nickname": "测试用户", "card": "测试名片", "role": "member"},
}


def fake_api_response(action: str, params: dict, echo: str) -> dict:
    if action == "get_login_info":
        data = {"user_id": SELF_ID, "nickname": "FakeBot"}
    elif action == "send_group_msg":
        data = {"message_id": 123456}
    elif action == "get_group_member_info":
        data = {"card": "名片", "nickname": "昵称", "role": "member"}
    else:
        data = {"ok": True}
    return {"status": "ok", "retcode": 0, "data": data, "echo": echo}


async def fake_napcat(ws):
    print("  [server] 客户端已连接")
    await asyncio.sleep(0.3)
    await ws.send(json.dumps(pushed_event))  # 推送事件
    try:
        async for raw in ws:
            req = json.loads(raw)
            server_received.append(req)
            resp = fake_api_response(req["action"], req.get("params", {}), req.get("echo", ""))
            await ws.send(json.dumps(resp))
            if req["action"] == "send_group_msg":
                await asyncio.sleep(0.1)
                await ws.close()  # 测试断线重连
                return
    except websockets.ConnectionClosed:
        pass


async def main():
    tmp = Path(tempfile.mkdtemp(prefix="qqbot_ws_"))
    cfg = config_mod.Config({
        "napcat": {"ws_url": f"ws://127.0.0.1:{PORT}", "access_token": "test-token"},
        "admin": {"superusers": [10000], "whitelist_groups": [], "whitelist_friends": []},
        "ai": {"api_key": "", "system_prompt": ""},
        "plugins": {n: {"enabled": True} for n in
                    ["admin", "msg_archive", "group_manage", "life_assistant", "ai_chat"]},
        "log": {"level": "ERROR", "dir": str(tmp / "logs")},
        "data_dir": str(tmp),
    })
    config_mod.current = cfg

    db = Database(str(tmp))
    dispatcher = Dispatcher(cfg, db)
    dispatcher.load_plugins()
    bot = Bot(cfg, db, dispatcher)
    conn = NapCatConnection(cfg, bot, dispatcher)
    bot.conn = conn

    async with websockets.serve(fake_napcat, "127.0.0.1", PORT):
        run_task = asyncio.create_task(conn.run())

        # 1) 等待连接 + 登录信息
        for _ in range(50):
            if bot.self_id == SELF_ID:
                break
            await asyncio.sleep(0.1)
        assert bot.self_id == SELF_ID, f"登录信息未获取: {bot.self_id}"
        print("  PASS  连接成功并获取登录信息")

        # 2) 事件推送 -> 存档
        for _ in range(50):
            if db.message_count() > 0:
                break
            await asyncio.sleep(0.1)
        rows = db.search_messages("group", GROUP_ID, None, "集成测试消息ABC", 5)
        assert rows, "推送事件未入库"
        print("  PASS  事件推送 -> 分发 -> 存档")

        # 3) API调用回包
        result = await bot.send_group_msg(GROUP_ID, [{"type": "text", "data": {"text": "hi"}}])
        assert result.get("message_id") == 123456, result
        assert any(r["action"] == "send_group_msg" for r in server_received)
        print("  PASS  API调用回包匹配")

        # 4) 断线重连
        await asyncio.sleep(1.5)  # 服务器已主动关闭，等重连
        for _ in range(50):
            if conn.connected.is_set():
                break
            await asyncio.sleep(0.1)
        assert conn.connected.is_set(), "断线后未重连"
        print("  PASS  断线自动重连")

        run_task.cancel()
        try:
            await run_task
        except asyncio.CancelledError:
            pass

    print("\nWS集成测试 ALL PASSED ✅")


if __name__ == "__main__":
    asyncio.run(main())
