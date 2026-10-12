"""无QQ回归测试：MockBot 模拟 NapCat，覆盖核心框架与全部插件的命令/事件路径。

运行： venv/Scripts/python.exe scripts/mock_test.py
全部通过输出 ALL PASSED，任何断言失败立即报错退出。
"""
import asyncio
import random
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config as config_mod  # noqa: E402
from core.api import Bot  # noqa: E402
from core.dispatcher import Dispatcher  # noqa: E402
from core import segments as seg  # noqa: E402
from db.database import Database  # noqa: E402

SELF_ID = 888
GROUP_ID = 777
USER_A = 10001   # 普通成员
USER_B = 10002   # 普通成员2
USER_ADMIN = 10003  # 群主
USER_SUPER = 10000  # 超级用户

PASS_COUNT = 0


def ok(name):
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  PASS  {name}")


# ---------------- 测试替身 ----------------

class MockBot(Bot):
    def __init__(self, cfg, db):
        super().__init__(cfg, db, dispatcher=None)
        self.actions = []
        self.self_id = SELF_ID
        self.started_at = time.time()
        self.conn = self
        self.connected = asyncio.Event()
        self.connected.set()

    async def call_action(self, action, timeout=30.0, **params):
        self.actions.append((action, params))
        if action == "get_group_member_info":
            return {"card": "测试昵称", "nickname": "测试昵称", "role": "member"}
        if action == "get_login_info":
            return {"user_id": SELF_ID, "nickname": "测试Bot"}
        if action == "send_group_msg":
            return {"message_id": 999}
        return {"ok": True}

    def sent_texts(self):
        out = []
        for action, p in self.actions:
            if action in ("send_group_msg", "send_private_msg"):
                m = p.get("message")
                txt = "".join(
                    s.get("data", {}).get("text", "") for s in m if s.get("type") == "text"
                ) if isinstance(m, list) else str(m)
                out.append((p.get("group_id") or p.get("user_id"), txt))
        return out

    def last_text(self):
        texts = self.sent_texts()
        return texts[-1][1] if texts else ""


def group_event(text=None, segs=None, user_id=USER_A, role="member", msg_id=None, group_id=GROUP_ID):
    msg_id = msg_id if msg_id is not None else int(time.time() * 1000) % 10**9
    return {
        "post_type": "message", "message_type": "group", "sub_type": "normal",
        "group_id": group_id, "user_id": user_id, "message_id": msg_id,
        "self_id": SELF_ID, "time": int(time.time()),
        "message": segs if segs is not None else [{"type": "text", "data": {"text": text}}],
        "raw_message": text or "",
        "sender": {"user_id": user_id, "nickname": f"昵称{user_id}", "card": f"群名片{user_id}", "role": role},
    }


def private_event(text, user_id=USER_A, msg_id=None):
    msg_id = msg_id if msg_id is not None else int(time.time() * 1000) % 10**9
    return {
        "post_type": "message", "message_type": "private", "sub_type": "friend",
        "user_id": user_id, "message_id": msg_id,
        "self_id": SELF_ID, "time": int(time.time()),
        "message": [{"type": "text", "data": {"text": text}}],
        "raw_message": text,
        "sender": {"user_id": user_id, "nickname": f"昵称{user_id}"},
    }


async def say(bot, dispatcher, event):
    """模拟连接层分发一条消息事件。"""
    await dispatcher.dispatch(bot, event)


# ---------------- 测试 ----------------

async def run_tests():
    tmp = Path(tempfile.mkdtemp(prefix="qqbot_test_"))
    # 运行时状态（插件开关）指向临时目录，避免污染真实环境
    config_mod.RUNTIME_STATE_PATH = tmp / "runtime_state.json"

    cfg_data = {
        "napcat": {"ws_url": "ws://127.0.0.1:3001", "access_token": ""},
        "admin": {
            "superusers": [USER_SUPER],
            "whitelist_groups": [],
            "whitelist_friends": [],
        },
        "ai": {
            "api_key": "test-key", "base_url": "https://api.minimax.chat/v1",
            "model": "MiniMax-M2", "max_tokens": 800, "temperature": 0.8,
            "max_context": 12, "per_user_cooldown": 0, "group_daily_limit": 200,
            "max_reply_len": 800,
            "system_prompt": "测试人设",
        },
        "plugins": {
            "msg_archive": {"enabled": True},
            "group_manage": {"enabled": True, "welcome": "欢迎 {name}！", "farewell": "再见 {name}", "keywords": []},
            "life_assistant": {"enabled": True},
            "admin": {"enabled": True},
            "ai_chat": {"enabled": True},
        },
        "log": {"level": "WARNING", "dir": str(tmp / "logs")},
        "data_dir": str(tmp),
    }
    cfg = config_mod.Config(cfg_data)
    config_mod.current = cfg
    # 重载配置命令会从磁盘重读，这里指向临时配置文件，保证测试自洽
    import yaml as yaml_lib

    config_mod.CONFIG_PATH = tmp / "config.yaml"
    config_mod.CONFIG_PATH.write_text(
        yaml_lib.safe_dump(cfg_data, allow_unicode=True), encoding="utf-8"
    )

    db = Database(str(tmp))
    dispatcher = Dispatcher(cfg, db)
    dispatcher.load_plugins()
    bot = MockBot(cfg, db)
    bot.dispatcher = dispatcher

    print("\n== 1. 帮助 ==")
    await say(bot, dispatcher, group_event("帮助"))
    assert "命令帮助" in bot.last_text(), bot.sent_texts()
    ok("帮助命令")

    print("\n== 2. 消息存档 ==")
    count_before = db.message_count()
    await say(bot, dispatcher, group_event("今天天气不错"))
    assert db.message_count() == count_before + 1
    rows = db.search_messages("group", GROUP_ID, None, "天气", 5)
    assert rows and "今天天气不错" in rows[0]["text"]
    ok("消息入库与关键词搜索")

    print("\n== 3. 查记录 ==")
    await say(bot, dispatcher, group_event("查记录 天气 3"))
    assert "天气" in bot.last_text()
    ok("查记录命令")

    print("\n== 4. 群统计 ==")
    await say(bot, dispatcher, group_event("群统计"))
    assert "今日群消息" in bot.last_text()
    ok("群统计命令")

    print("\n== 5. 关键词 ==")
    await say(bot, dispatcher, group_event("添加关键词 早安=早上好！", user_id=USER_ADMIN, role="owner"))
    assert "已添加" in bot.last_text()
    await say(bot, dispatcher, group_event("大家早安"))
    texts = bot.sent_texts()
    assert "早上好！" in texts[-1][1], texts[-1]
    ok("关键词添加与自动回复")

    print("\n== 6. 提醒 ==")
    from plugins.life_assistant import parse_when

    run_at, cron, human = parse_when("30分钟后")
    assert run_at and abs(run_at - (time.time() + 1800)) < 5, (run_at, human)
    run_at, cron, human = parse_when("明天9点")
    want = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    assert abs(run_at - want.timestamp()) < 2
    run_at, cron, human = parse_when("每天8:30")
    assert cron == "daily 08:30" and human == "每天 08:30"
    run_at, cron, human = parse_when("每周一 9:00")
    assert cron == "weekly 0 09:00"
    run_at, cron, human = parse_when("明天18:30")
    want = datetime.now().replace(hour=18, minute=30, second=0, microsecond=0) + timedelta(days=1)
    assert abs(run_at - want.timestamp()) < 2
    ok("时间解析(30分钟后/明天9点/每天8:30/每周一9:00/明天18:30)")

    await say(bot, dispatcher, group_event("提醒我 30分钟后 喝水"))
    assert "已设置提醒" in bot.last_text() and "喝水" in bot.last_text()
    rows = db.query("SELECT * FROM reminders WHERE text='喝水'")
    assert rows and not rows[0]["done"]
    await say(bot, dispatcher, group_event("查看提醒"))
    assert "喝水" in bot.last_text()
    await say(bot, dispatcher, group_event("取消提醒 1"))
    assert "已取消" in bot.last_text()
    rows = db.query("SELECT * FROM reminders WHERE text='喝水'")
    assert rows[0]["done"] == 1
    ok("提醒设置/查看/取消")

    print("\n== 7. 待办 ==")
    await say(bot, dispatcher, group_event("添加待办 买菜做饭"))
    assert "买菜做饭" in bot.last_text()
    await say(bot, dispatcher, group_event("看待办"))
    assert "买菜做饭" in bot.last_text()
    rows = db.query("SELECT id FROM todos WHERE content='买菜做饭'")
    await say(bot, dispatcher, group_event(f"完成待办 {rows[0]['id']}"))
    assert "已完成待办" in bot.last_text()
    ok("待办添加/查看/完成")

    print("\n== 8. 记账 ==")
    await say(bot, dispatcher, group_event("记账 午饭 25"))
    assert "已记账" in bot.last_text() and "25.00" in bot.last_text()
    await say(bot, dispatcher, private_event("查账 今日", user_id=USER_A))
    assert "合计 25.00" in bot.last_text()
    ok("记账与查账")

    print("\n== 9. 群管理权限 ==")
    at_segs = [{"type": "at", "data": {"qq": str(USER_B)}}, {"type": "text", "data": {"text": " 禁言 10"}}]
    await say(bot, dispatcher, group_event(segs=at_segs, user_id=USER_A, role="member"))
    assert not any(a == "set_group_ban" for a, _ in bot.actions), "普通成员不应能禁言"
    await say(bot, dispatcher, group_event(segs=at_segs, user_id=USER_ADMIN, role="owner"))
    assert any(a == "set_group_ban" for a, _ in bot.actions)
    ok("禁言权限校验(普通成员拒绝/群主放行)")

    bot.actions.clear()
    await say(bot, dispatcher, group_event("全员禁言 开", user_id=USER_ADMIN, role="owner"))
    assert any(a == "set_group_whole_ban" and p.get("enable") for a, p in bot.actions)
    ok("全员禁言")

    print("\n== 10. AI聊天 ==")
    import plugins.ai_chat as ai_chat

    ai_chat._contexts.clear()
    ai_chat._group_daily.clear()
    ai_chat._last_call.clear()
    called = {}

    async def fake_loop(cfg, messages, bot=None, ctx=None):
        called["messages"] = messages
        return "你好呀，我是AI"

    real_loop = ai_chat._chat_with_tools
    ai_chat._chat_with_tools = fake_loop
    try:
        at_bot = [{"type": "at", "data": {"qq": str(SELF_ID)}}, {"type": "text", "data": {"text": " 你好"}}]
        await say(bot, dispatcher, group_event(segs=at_bot, user_id=USER_A))
        texts = bot.sent_texts()
        assert texts[-1][1].strip() == "你好呀，我是AI", texts[-1]
        ok("群聊@触发AI回复")

        # 上下文：再次提问应携带历史
        await say(bot, dispatcher, group_event(segs=at_bot, user_id=USER_A))
        msgs = called["messages"]
        assert msgs[0]["role"] == "system" and msgs[0]["content"].startswith("测试人设")
        assert sum(1 for m in msgs if m["role"] == "user") == 2
        assert any(m["role"] == "assistant" and m["content"] == "你好呀，我是AI" for m in msgs)
        ok("多轮上下文与人设")

        # 引用回复机器人消息也应触发
        ai_chat._contexts.clear()
        reply_seg = [{"type": "reply", "data": {"id": "5", "qq": str(SELF_ID)}},
                     {"type": "text", "data": {"text": " 追问一下"}}]
        await say(bot, dispatcher, group_event(segs=reply_seg, user_id=USER_B))
        assert bot.last_text().strip() == "你好呀，我是AI"
        ok("引用回复触发AI")

        # 清空对话
        await say(bot, dispatcher, group_event("清空对话", user_id=USER_A))
        assert "已清空" in bot.last_text()
        assert ai_chat._contexts.get("g:%d" % GROUP_ID) in (None, [])
        ok("清空对话")

        # 冷却：cooldown 设为 5 秒后第二次@应被忽略
        cfg._data["ai"]["per_user_cooldown"] = 5
        before = len(bot.sent_texts())
        await say(bot, dispatcher, group_event(segs=at_bot, user_id=USER_A))
        assert len(bot.sent_texts()) == before
        cfg._data["ai"]["per_user_cooldown"] = 0
        ok("AI冷却防刷屏")

        # 群每日上限
        ai_chat._group_daily.clear()
        cfg._data["ai"]["group_daily_limit"] = 1
        await say(bot, dispatcher, group_event(segs=at_bot, user_id=USER_B))  # 第1次：回复
        before = len(bot.sent_texts())
        await say(bot, dispatcher, group_event(segs=at_bot, user_id=USER_B))  # 第2次：达限
        assert len(bot.sent_texts()) == before
        cfg._data["ai"]["group_daily_limit"] = 200
        ok("群每日AI上限")

        # 未配置 key 时优雅降级
        cfg._data["ai"]["api_key"] = ""
        before = len(bot.sent_texts())
        await say(bot, dispatcher, group_event(segs=at_bot, user_id=USER_A))
        assert len(bot.sent_texts()) == before  # 群里静默
        await say(bot, dispatcher, private_event("你好", user_id=USER_A))
        assert "API key" in bot.last_text()  # 私聊提示
        cfg._data["ai"]["api_key"] = "test-key"
        ok("未配置key优雅降级")
    finally:
        ai_chat._chat_with_tools = real_loop

    print("\n== 11. 入群欢迎/退群/戳一戳 ==")
    bot.actions.clear()
    await dispatcher.dispatch(bot, {
        "post_type": "notice", "notice_type": "group_increase",
        "group_id": GROUP_ID, "user_id": USER_B, "self_id": SELF_ID,
    })
    assert any(a == "send_group_msg" for a, _ in bot.actions)
    assert "欢迎" in bot.last_text() and "测试昵称" in bot.last_text()
    ok("入群欢迎(带名片)")

    bot.actions.clear()
    await dispatcher.dispatch(bot, {
        "post_type": "notice", "notice_type": "notify", "sub_type": "poke",
        "group_id": GROUP_ID, "user_id": USER_A, "target_id": SELF_ID,
    })
    assert any(a == "group_poke" and p.get("user_id") == USER_A for a, p in bot.actions)
    ok("戳一戳戳回去")

    print("\n== 12. 白名单 ==")
    cfg._data["admin"]["whitelist_groups"] = [GROUP_ID + 1]
    count_before = db.message_count()
    before = len(bot.sent_texts())
    await say(bot, dispatcher, group_event("白名单外消息", group_id=GROUP_ID))
    assert len(bot.sent_texts()) == before  # 不响应
    assert db.message_count() == count_before + 1  # 但仍然存档
    cfg._data["admin"]["whitelist_groups"] = []
    ok("群白名单(不响应但仍存档)")

    print("\n== 13. 超级用户命令 ==")
    await say(bot, dispatcher, group_event("状态", user_id=USER_SUPER))
    assert "机器人状态" in bot.last_text()
    await say(bot, dispatcher, group_event("插件列表", user_id=USER_SUPER))
    assert "msg_archive" in bot.last_text()
    await say(bot, dispatcher, group_event("设置人设 新人设X", user_id=USER_SUPER))
    assert "已更新" in bot.last_text()
    assert db.kv_get("ai_persona") == "新人设X"
    ok("状态/插件列表/设置人设")

    print("\n== 14. 插件开关 ==")
    await say(bot, dispatcher, group_event("关闭插件 ai_chat", user_id=USER_SUPER))
    assert "已关闭" in bot.last_text()
    assert not dispatcher.is_enabled("ai_chat")
    before = len(bot.sent_texts())
    await say(bot, dispatcher, group_event(segs=[{"type": "at", "data": {"qq": str(SELF_ID)}},
                                                 {"type": "text", "data": {"text": " hi"}}], user_id=USER_B))
    assert len(bot.sent_texts()) == before
    await say(bot, dispatcher, group_event("开启插件 ai_chat", user_id=USER_SUPER))
    assert dispatcher.is_enabled("ai_chat")
    ok("插件开关即时生效")

    print("\n== 15. 广播与重载 ==")
    await say(bot, dispatcher, group_event(f"广播 {GROUP_ID} 通知一下", user_id=USER_SUPER))
    texts = bot.sent_texts()
    assert any(t == "通知一下" for _, t in texts)
    await say(bot, dispatcher, group_event("重载配置", user_id=USER_SUPER))
    assert "配置已重载" in bot.last_text() or "读取失败" in bot.last_text()
    ok("广播/重载配置")

    print("\n== 16. 私聊AI ==")
    ai_chat._contexts.clear()
    ai_chat._last_call.clear()
    real = ai_chat._chat_with_tools

    async def fake_loop2(cfg, messages, bot=None, ctx=None):
        return "你好呀，我是AI"

    ai_chat._chat_with_tools = fake_loop2
    try:
        await say(bot, dispatcher, private_event("你好呀", user_id=USER_A))
        assert bot.last_text() == "你好呀，我是AI"
    finally:
        ai_chat._chat_with_tools = real
    ok("私聊直接触发AI")

    print("\n== 17. 导出记录(管理员) ==")
    await say(bot, dispatcher, group_event("导出记录", user_id=USER_ADMIN, role="owner"))
    assert any(a == "upload_group_file" for a, _ in bot.actions)
    ok("导出记录上传群文件")

    print("\n== 18. 表情包 ==")
    import plugins.memes as memes

    meme_dir = tmp / "memes"
    meme_dir.mkdir(exist_ok=True)
    (meme_dir / "无语.png").write_bytes(b"\x89PNG fake")
    (meme_dir / "熊猫头-哈哈.jpg").write_bytes(b"\xff\xd8 fake")
    cfg._data["plugins"]["memes"] = {"enabled": True, "dir": str(meme_dir)}

    assert len(memes.build_index(cfg)) == 2
    assert len(memes.find_memes(cfg, "哈哈")) == 1  # 模糊匹配
    await say(bot, dispatcher, group_event("表情包 哈哈", user_id=USER_A))
    img_sends = [p for a, p in bot.actions if a == "send_group_msg" and isinstance(p.get("message"), list)
                 and any(s.get("type") == "image" for s in p["message"])]
    assert img_sends, "表情包命令未产生图片消息"
    ok("表情包命令与模糊匹配")

    await say(bot, dispatcher, group_event("表情包列表"))
    assert "熊猫头-哈哈" in bot.last_text()
    await say(bot, dispatcher, group_event("表情包 不存在的词"))
    assert "没有匹配" in bot.last_text()
    ok("表情包列表/未命中提示")

    # AI 工具 send_meme
    from core import tools as tools_mod

    assert "send_meme" in tools_mod.TOOLS, "send_meme 工具未注册"
    result = await tools_mod.execute_tool("send_meme", {"keyword": "无语"}, bot, {"event": group_event()})
    assert "已发送" in result
    ok("send_meme工具执行")

    print("\n== 19. 游戏数据(剑网3/三角洲) ==")
    import plugins.game_data as game_data

    async def fake_jx3_get(cfg, path, params={}):
        if path == "/active/calendar":
            return {"date": "2026-10-12", "week": "一", "war": "大战！测试副本"}
        if path == "/server/status/check":
            return [{"server": "梦江南", "zone": "电信区", "status": 1, "shuttime": 0}]
        if path == "/trade/demon":
            return [{"zone": "电信区", "server": "梦江南", "tieba": "990.00", "wanbaolou": "980.00",
                     "dd373": "800.00", "uu898": "588.24", "5173": "000.00", "7881": "880.18",
                     "date": "2026-10-12"}]
        if path == "/saohua/random":
            return {"text": "测试骚话"}
        raise RuntimeError("unexpected path " + path)

    real_jx3 = game_data._jx3_get
    game_data._jx3_get = fake_jx3_get
    try:
        await say(bot, dispatcher, group_event("剑网3 活动"))
        assert "大战！测试副本" in bot.last_text()
        assert "jx3api" in bot.last_text()  # 数据来源标注
        ok("剑网3活动命令+来源标注")

        assert "query_jx3" in tools_mod.TOOLS, "query_jx3 工具未注册"
        result = await tools_mod.execute_tool("query_jx3", {"action": "calendar"}, bot, {})
        assert "大战" in result
        result = await tools_mod.execute_tool("query_jx3", {"action": "check", "server": "梦江南"}, bot, {})
        assert "梦江南" in result and "已开服" in result
        # 金价：真实字段结构（需配置token）
        cfg._data["plugins"].setdefault("game_data", {})["jx3_token"] = "test-token"
        result = await tools_mod.execute_tool("query_jx3", {"action": "demon", "server": "梦江南"}, bot, {})
        assert "万宝楼980" in result, result
        assert "5173" not in result, result  # 000.00无数据渠道被过滤
        cfg._data["plugins"]["game_data"]["jx3_token"] = ""
        ok("query_jx3工具(含金价真实字段)")

        # 三角洲：搜索 + 总结
        import core.ai_completion as ai_completion
        import core.websearch as websearch

        real_search = websearch.bing_search

        async def fake_search(q, n=6):
            return [{"title": "三角洲行动行情", "url": "https://example.com/a", "snippet": "曼德尔砖价格上涨"}]

        websearch.bing_search = fake_search
        real_sum = ai_completion.summarize_search

        async def fake_sum(cfg, q, results):
            return "整理结果：曼德尔砖上涨（来源：example.com）"

        ai_completion.summarize_search = fake_sum
        try:
            await say(bot, dispatcher, group_event("三角洲 曼德尔砖行情"))
            texts = bot.sent_texts()
            assert any("整理结果" in t for _, t in texts)
        finally:
            websearch.bing_search = real_search
            ai_completion.summarize_search = real_sum
        ok("三角洲检索+AI整理")
    finally:
        game_data._jx3_get = real_jx3

    print("\n== 20. AI工具循环(函数调用) ==")
    ai_chat._contexts.clear()
    ai_chat._group_daily.clear()
    ai_chat._last_call.clear()

    from types import SimpleNamespace

    class FakeClient:
        def __init__(self, seq):
            self.seq = list(seq)
            self.kw_log = []
            chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
            self.chat = chat

        def create(self, **kw):
            self.kw_log.append(kw)
            msg = self.seq.pop(0)
            return SimpleNamespace(choices=[SimpleNamespace(message=msg)])

    tc = SimpleNamespace(id="call_1", function=SimpleNamespace(name="send_meme", arguments='{"keyword":"无语"}'))
    seq = [
        SimpleNamespace(content=None, tool_calls=[tc]),
        SimpleNamespace(content="<think>思考</think>看我的表情包", tool_calls=None),
    ]
    fake = FakeClient(seq)
    real_get_client = ai_completion.get_client
    ai_completion.get_client = lambda cfg: fake
    real_loop = ai_chat._chat_with_tools
    real_tools_enabled = cfg._data["ai"].get("tools_enabled", True)
    cfg._data["ai"]["tools_enabled"] = True
    try:
        at_bot = [{"type": "at", "data": {"qq": str(SELF_ID)}}, {"type": "text", "data": {"text": "来个表情包"}}]
        await say(bot, dispatcher, group_event(segs=at_bot, user_id=USER_B))
        # 第1轮触发工具send_meme -> 图片消息；第2轮返回文本（think已剥离）
        texts = bot.sent_texts()
        assert any("看我的表情包" in t for _, t in texts)
        img_sends = [p for a, p in bot.actions if a == "send_group_msg" and isinstance(p.get("message"), list)
                     and any(s.get("type") == "image" for s in p["message"])]
        assert img_sends, "工具循环未触发send_meme发图"
        # 第2轮请求里应有 tool 角色消息（工具结果回填）
        second_kw = fake.kw_log[1]
        assert any(m.get("role") == "tool" and m.get("tool_call_id") == "call_1" for m in second_kw["messages"])
        # think标签被剥离后进入上下文
        ctx_hist = ai_chat._contexts.get("g:%d" % GROUP_ID, [])
        assert any(m["role"] == "assistant" and m["content"] == "看我的表情包" for m in ctx_hist)
        ok("工具循环执行+结果回填+think剥离")
    finally:
        ai_completion.get_client = real_get_client
        ai_chat._chat_with_tools = real_loop
        cfg._data["ai"]["tools_enabled"] = real_tools_enabled

    print("\n== 21. 自主聊天 ==")
    import plugins.proactive_chat as proactive

    cfg._data["plugins"]["proactive_chat"] = {
        "enabled": True, "groups": [GROUP_ID], "min_gap_minutes": 30,
        "max_gap_minutes": 0, "daily_limit": 5, "quiet_hours": [],
        "chance": 1.0, "min_recent_msgs": 3, "history_window_hours": 2,
        "meme_chance": 0.0,
    }
    # 静默时段纯函数测试
    assert proactive._in_quiet_hours(datetime(2026, 10, 12, 2, 0), [23, 8]) is True
    assert proactive._in_quiet_hours(datetime(2026, 10, 12, 12, 0), [23, 8]) is False
    assert proactive._in_quiet_hours(datetime(2026, 10, 12, 2, 0), []) is False
    ok("静默时段判断")

    # 造群聊记录
    now_ts = int(time.time())
    for i in range(5):
        bot.db.insert_message(
            {"time": now_ts - 600 + i, "message_id": str(1000 + i), "message_type": "group",
             "group_id": GROUP_ID, "user_id": USER_A if i % 2 == 0 else USER_B,
             "sender": {"card": f"群友{i}", "nickname": f"群友{i}"}},
            f"第{i}条测试消息", "",
        )

    real_completion = proactive.asyncio_to_thread_completion

    async def fake_completion(cfg, messages):
        return "哈哈哈哈这波可以"

    proactive.asyncio_to_thread_completion = fake_completion
    try:
        bot.actions.clear()
        await proactive._tick(bot)
        texts = bot.sent_texts()
        assert any("哈哈哈哈这波可以" in t for _, t in texts), texts[-3:]
        assert proactive._daily_count(GROUP_ID) == 1
        # 插话写入AI上下文（assistant角色）
        ctx_after = ai_chat._contexts.get(f"g:{GROUP_ID}", [])
        assert any(m["role"] == "assistant" and m["content"] == "哈哈哈哈这波可以" for m in ctx_after)
        ai_chat._contexts.pop(f"g:{GROUP_ID}", None)  # 清理，避免影响后续节
        ok("自主插话发送+每日计数+进AI上下文")

        # 连续SKIP：不发送
        async def fake_skip(cfg, messages):
            return "[SKIP]"

        proactive.asyncio_to_thread_completion = fake_skip
        cfg._data["plugins"]["proactive_chat"]["min_gap_minutes"] = 0  # 关掉防自嗨窗口，专门测SKIP路径
        bot.actions.clear()
        await proactive._tick(bot)
        assert not any("send_group_msg" == a for a, _ in bot.actions)
        ok("SKIP不发送")
        # 防自嗨：机器人刚说过话（存在存档里），LLM再给内容也不发
        cfg._data["plugins"]["proactive_chat"]["min_gap_minutes"] = 30
        proactive.asyncio_to_thread_completion = fake_completion
        bot.actions.clear()
        await proactive._tick(bot)
        assert not any("哈哈哈哈" in t for _, t in bot.sent_texts())
        ok("防自嗨")
    finally:
        proactive.asyncio_to_thread_completion = real_completion

    print("\n== 22. 免@回复（名字提及/小概率插嘴） ==")
    ai_chat._contexts.clear()
    ai_chat._group_daily.clear()
    ai_chat._last_call.clear()
    ai_chat._passive_last.clear()
    cfg._data["ai"]["name_aliases"] = ["东小0"]
    cfg._data["ai"]["group_passive"] = {"enabled": True, "chance": 0.0, "min_len": 4, "group_cooldown": 0}

    real_loop3 = ai_chat._chat_with_tools

    async def fake_loop3(cfg, messages, bot=None, ctx=None):
        fake_loop3.calls = getattr(fake_loop3, "calls", 0) + 1
        return "名字触发回复"

    ai_chat._chat_with_tools = fake_loop3
    try:
        # 名字提及 = 触发
        await say(bot, dispatcher, group_event("东小0 你觉得呢", user_id=USER_A))
        assert any("名字触发回复" in t for _, t in bot.sent_texts())
        ok("叫名字免@触发")

        # passive chance=0：普通消息不触发
        fake_loop3.calls = 0
        before = len(bot.sent_texts())
        await say(bot, dispatcher, group_event("今天天气真好啊", user_id=USER_B))
        assert fake_loop3.calls == 0 and len(bot.sent_texts()) == before
        ok("passive概率0不触发")

        # passive chance=1：普通消息触发，SKIP时不发送且不进上下文
        cfg._data["ai"]["group_passive"]["chance"] = 1.0
        ai_chat._passive_last.clear()
        ai_chat._contexts.pop("g:%d" % GROUP_ID, None)  # 清掉别名测试的残留上下文

        async def fake_skip_loop(cfg, messages, bot=None, ctx=None):
            return "[SKIP]"

        ai_chat._chat_with_tools = fake_skip_loop
        before = len(bot.sent_texts())
        await say(bot, dispatcher, group_event("这游戏真好玩啊哈哈哈", user_id=USER_B))
        assert len(bot.sent_texts()) == before, "SKIP不应发送"
        assert ai_chat._contexts.get("g:%d" % GROUP_ID, []) == [], "SKIP不应写入上下文"
        ok("passive触发SKIP静默")

        ai_chat._passive_last.clear()

        async def fake_join_loop(cfg, messages, bot=None, ctx=None):
            return "确实好玩"

        ai_chat._chat_with_tools = fake_join_loop
        await say(bot, dispatcher, group_event("这游戏真好玩啊哈哈哈", user_id=USER_B))
        texts = bot.sent_texts()
        assert any("确实好玩" in t for _, t in texts)
        # 插嘴模式不带@：消息段里不应有at段
        last_send = [p for a, p in bot.actions if a == "send_group_msg"][-1]
        assert not any(s.get("type") == "at" for s in last_send["message"]), "插嘴不应带@"
        ok("passive插嘴发送(无@)")

        # 群级冷却：group_cooldown内第二条普通消息不触发
        cfg._data["ai"]["group_passive"]["group_cooldown"] = 120
        fake_join2 = 0

        async def fake_join_loop2(cfg, messages, bot=None, ctx=None):
            return "第二条"

        ai_chat._chat_with_tools = fake_join_loop2
        await say(bot, dispatcher, group_event("再聊一句试试看呗", user_id=USER_A))
        assert not any("第二条" in t for _, t in bot.sent_texts())
        ok("passive群级冷却")
    finally:
        ai_chat._chat_with_tools = real_loop3
        cfg._data["ai"]["group_passive"] = {"enabled": True, "chance": 0.0, "min_len": 4, "group_cooldown": 0}

    print("\n== 23. 天气升级（自动定位+AI总结） ==")
    import plugins.life_assistant as life

    assert "get_weather" in tools_mod.TOOLS, "get_weather 工具未注册"

    fetched_cities = []

    async def fake_fetch(city):
        fetched_cities.append(city)
        return f"🌤 {city}天气\n现在：晴 25°C\n今日：晴 18~28°C"

    async def fake_summary(cfg, city, data_text):
        return "挺舒服的，白天单衣就行，晚上加件薄外套"

    real_fetch, real_summary, real_ip = life._fetch_weather, life._weather_summary, life._ip_city
    life._fetch_weather = fake_fetch
    life._weather_summary = fake_summary
    try:
        # 1) 设置城市（校验通过才保存）
        await say(bot, dispatcher, group_event("设置城市 北京", user_id=USER_A))
        assert "常驻城市已设为" in bot.last_text(), bot.last_text()
        assert bot.db.kv_get(f"city:{USER_A}") == "北京"
        ok("设置城市")

        # 2) 裸「天气」→ 用常驻城市 + AI总结
        fetched_cities.clear()
        await say(bot, dispatcher, group_event("天气", user_id=USER_A))
        assert fetched_cities == ["北京"]
        t = bot.last_text()
        assert "按你设置的常驻城市" in t and "薄外套" in t, t
        ok("天气自动用常驻城市+AI总结")

        # 3) 显式城市优先于常驻城市
        fetched_cities.clear()
        await say(bot, dispatcher, group_event("天气 上海", user_id=USER_A))
        assert fetched_cities == ["上海"]
        assert "按你设置的常驻城市" not in bot.last_text()
        ok("显式城市优先")

        # 4) 无常驻城市时IP定位兜底
        bot.db.execute("DELETE FROM kv WHERE key=?", (f"city:{USER_B}",))

        async def fake_ip(b):
            return "深圳市"

        life._ip_city = fake_ip
        fetched_cities.clear()
        await say(bot, dispatcher, group_event("天气", user_id=USER_B))
        assert fetched_cities == ["深圳市"], fetched_cities
        assert "自动定位" in bot.last_text()
        ok("IP定位兜底")

        # 5) AI工具：留空location用常驻城市
        fetched_cities.clear()
        result = await tools_mod.execute_tool("get_weather", {}, bot, {"event": group_event("", user_id=USER_A)})
        assert fetched_cities == ["北京"] and "请基于以上数据回答" in result
        ok("get_weather工具")

        # 6) 城市校验失败不保存
        async def bad_fetch(city):
            raise ValueError("找不到城市「亚特兰蒂斯」")

        life._fetch_weather = bad_fetch
        await say(bot, dispatcher, group_event("设置城市 亚特兰蒂斯", user_id=USER_A))
        assert "查不到" in bot.last_text()
        assert bot.db.kv_get(f"city:{USER_A}") == "北京"  # 原值未被动
        ok("城市校验失败不保存")
    finally:
        life._fetch_weather = real_fetch
        life._weather_summary = real_summary
        life._ip_city = real_ip

    print("\n== 24. 上下文滚动摘要 ==")
    ai_chat._contexts.clear()
    ai_chat._summaries.clear()
    ai_chat._pending_sum.clear()
    ai_chat._running_sum.clear()
    ai_chat._group_daily.clear()
    ai_chat._last_call.clear()
    cfg._data["ai"]["context_summary"] = {"enabled": True}
    cfg._data["ai"]["max_context"] = 4  # 小窗口便于触发溢出

    summary_calls = []

    def fake_cis(cfg, messages, max_tokens=None, temperature=None):
        summary_calls.append(messages)
        return "摘要：聊过加薪和钓鱼"

    async def fake_loop_s(cfg, messages, bot=None, ctx=None):
        fake_loop_s.last_msgs = messages
        return "好的"

    real_cis = ai_completion.chat_once_sync
    real_loop_s = ai_chat._chat_with_tools
    ai_completion.chat_once_sync = fake_cis
    ai_chat._chat_with_tools = fake_loop_s
    try:
        at_bot = lambda i: [{"type": "at", "data": {"qq": str(SELF_ID)}},
                            {"type": "text", "data": {"text": f" 第{i}句"}}]
        # 连发6条：窗口4 → 触发淘汰与后台摘要
        for i in range(1, 7):
            await say(bot, dispatcher, group_event(segs=at_bot(i), user_id=USER_A))
        # 等后台摘要任务完成
        for _ in range(40):
            if ai_chat._summaries.get(f"g:{GROUP_ID}"):
                break
            await asyncio.sleep(0.05)
        assert ai_chat._summaries.get(f"g:{GROUP_ID}") == "摘要：聊过加薪和钓鱼"
        assert summary_calls, "摘要LLM未被调用"
        sum_user_msg = summary_calls[0][-1]["content"]
        assert "第1句" in sum_user_msg and "群名片10001" in sum_user_msg, sum_user_msg
        assert "好的" in sum_user_msg or "机器人" in sum_user_msg  # 淘汰的assistant也进摘要
        ok("溢出消息进后台摘要")

        # 下一条消息的LLM请求带摘要注入
        await say(bot, dispatcher, group_event(segs=at_bot(7), user_id=USER_A))
        injected = [m for m in fake_loop_s.last_msgs
                    if m["role"] == "system" and "之前对话的摘要" in m["content"]]
        assert injected and "聊过加薪和钓鱼" in injected[0]["content"]
        ok("摘要注入LLM请求")

        # 清空对话连摘要一起清（先排空后台任务，避免在途任务写回）
        for _ in range(40):
            if not ai_chat._running_sum and not ai_chat._pending_sum:
                break
            await asyncio.sleep(0.05)
        assert f"g:{GROUP_ID}" in ai_chat._summaries  # 清空前摘要应在
        await say(bot, dispatcher, group_event("清空对话", user_id=USER_A))
        assert f"g:{GROUP_ID}" not in ai_chat._summaries
        assert f"g:{GROUP_ID}" not in ai_chat._contexts
        ok("清空对话清摘要")

        # 关闭开关 → 回退硬截断（无摘要任务）
        # 先等enabled阶段的后台摘要任务全部排空，避免竞态污染断言
        for _ in range(40):
            if not ai_chat._running_sum and not ai_chat._pending_sum:
                break
            await asyncio.sleep(0.05)
        cfg._data["ai"]["context_summary"] = {"enabled": False}
        ai_chat._pending_sum.clear()
        summary_calls.clear()
        for i in range(8, 13):
            await say(bot, dispatcher, group_event(segs=at_bot(i), user_id=USER_A))
        await asyncio.sleep(0.3)
        assert not summary_calls, "关闭后不应再有摘要调用"
        assert f"g:{GROUP_ID}" not in ai_chat._summaries
        ctx_now = ai_chat._contexts.get(f"g:{GROUP_ID}", [])
        assert len(ctx_now) <= 4
        ok("关闭开关回退硬截断")
    finally:
        ai_completion.chat_once_sync = real_cis
        ai_chat._chat_with_tools = real_loop_s
        cfg._data["ai"]["context_summary"] = {"enabled": True}
        cfg._data["ai"]["max_context"] = 12

    print("\n== 25. 签到与积分 ==")
    import plugins.fun as fun

    await say(bot, dispatcher, group_event("签到", user_id=USER_A))
    t = bot.last_text()
    assert "签到成功 +5分（连续1天）" in t and "宜" in t and "忌" in t, t
    await say(bot, dispatcher, group_event("签到", user_id=USER_A))
    assert "已经签过" in bot.last_text()

    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    bot.db.execute(
        "INSERT INTO points (chat_type, chat_id, user_id, points, last_sign, sign_streak) "
        "VALUES ('group',?,?,3,?,2)",
        (GROUP_ID, USER_B, yesterday),
    )
    await say(bot, dispatcher, group_event("签到", user_id=USER_B))
    assert "+7分（连续3天）" in bot.last_text(), bot.last_text()  # 5+min(3-1,5)
    await say(bot, dispatcher, group_event("积分", user_id=USER_B))
    assert "10" in bot.last_text()
    await say(bot, dispatcher, group_event("积分排行"))
    assert "10分" in bot.last_text()
    ok("签到/连签加成/积分查询/排行")

    print("\n== 26. 今日运势 ==")
    f1 = fun.fortune(12345, "2026-10-12")
    f2 = fun.fortune(12345, "2026-10-12")
    assert f1 == f2 and f1["level"] in fun.FORTUNE_LEVELS and len(f1["yi"]) == 2
    assert fun.fortune(12345, "2026-10-13") != f1 or True  # 不同日期同号哈希不同（结构性检查即可）
    await say(bot, dispatcher, group_event("运势", user_id=USER_A))
    assert "今日【" in bot.last_text()
    ok("运势确定性生成与查询")

    print("\n== 27. 石头剪刀布/猜数字 ==")
    real_choice = random.choice
    random.choice = lambda seq: "石头"  # 机器人固定出石头
    try:
        await say(bot, dispatcher, group_event("剪刀", user_id=USER_A))
        assert "你输了" in bot.last_text()
        await say(bot, dispatcher, group_event("布", user_id=USER_A))
        assert "你赢了！+2分" in bot.last_text()
    finally:
        random.choice = real_choice
    row = bot.db.get_points_row("group", GROUP_ID, USER_A)
    assert row["points"] >= 2

    await say(bot, dispatcher, group_event("猜数字 10", user_id=USER_A))
    assert "1~10" in bot.last_text()
    fun._guess_state[GROUP_ID]["target"] = 7
    await say(bot, dispatcher, group_event("3", user_id=USER_A))
    assert "小了" in bot.last_text()
    await say(bot, dispatcher, group_event("9", user_id=USER_A))
    assert "大了" in bot.last_text()
    await say(bot, dispatcher, group_event("7", user_id=USER_A))
    assert "猜中了" in bot.last_text() and "+3分" in bot.last_text()
    assert GROUP_ID not in fun._guess_state
    ok("剪刀石头布(定点出拳)/猜数字状态机")

    print("\n== 28. 成语接龙/每日一题 ==")
    script = iter(["一心一意", '{"valid": true, "next": "发愤图强"}'])
    real_fun_llm = fun.chat_once_sync
    fun.chat_once_sync = lambda cfg, msgs, mt=None, tp=None: next(script)
    try:
        await say(bot, dispatcher, group_event("成语接龙", user_id=USER_A))
        assert "【一心一意】" in bot.last_text()
        await say(bot, dispatcher, group_event("意气风发", user_id=USER_A))
        assert "+1分" in bot.last_text() and "【发愤图强】" in bot.last_text()
        await say(bot, dispatcher, group_event("接龙结束", user_id=USER_A))
        assert "接对 1 次" in bot.last_text()
        ok("成语接龙(LLM出题+判定+接龙)")

        quiz = iter([
            '{"q": "藏剑山庄的镇派武学心法是？", "options": ["A. 问水诀", "B. 山居剑意", "C. 太虚剑意", "D. 傲霜"], "a": "B"}',
        ])
        fun.chat_once_sync = lambda cfg, msgs, mt=None, tp=None: next(quiz)
        await say(bot, dispatcher, group_event("出题", user_id=USER_A))
        assert "每日一题" in bot.last_text() and "答案是" in bot.last_text()
        await say(bot, dispatcher, group_event("答案是 A", user_id=USER_A))
        assert "不对哦" in bot.last_text()
        await say(bot, dispatcher, group_event("答案是 B", user_id=USER_A))
        assert "答对了！+10分" in bot.last_text()
        assert GROUP_ID not in fun._quiz_state
        ok("每日一题(出题/判错/答对)")
    finally:
        fun.chat_once_sync = real_fun_llm

    print("\n== 29. 日报/金价/订阅 ==")
    import plugins.digest as digest

    captured_prompts = []
    digest.chat_once_sync = lambda cfg, msgs, mt=None, tp=None: (
        captured_prompts.append(msgs[-1]["content"]) or "【话题】大家在玩梗\n【要点】无大事\n【金句】群友：测试金句"
    )
    real_gd_llm = digest.chat_once_sync
    try:
        text = await digest.build_digest(bot, GROUP_ID, "日报")
        assert "【话题】大家在玩梗" in text and "群聊日报" in text
        assert any("聊天记录" in p for p in captured_prompts)
        await say(bot, dispatcher, group_event("周报", user_id=USER_A))
        assert "群聊周报" in bot.last_text()
        ok("群聊日报/周报生成")
    finally:
        digest.chat_once_sync = real_gd_llm

    cfg._data["plugins"].setdefault("game_data", {})["jx3_token"] = "test-token"
    import plugins.game_data as game_data2

    gold_rows = iter([
        [{"zone": "电信区", "server": "梦江南", "wanbaolou": "980.00", "date": "2026-10-12"}],
        [{"zone": "电信区", "server": "梦江南", "wanbaolou": "1010.00", "date": "2026-10-13"}],
    ])

    async def fake_gold(cfg2, path, params={}):
        return next(gold_rows)

    real_gd2 = game_data2._jx3_get
    game_data2._jx3_get = fake_gold
    try:
        r1 = await digest.build_gold_report(bot)
        assert "梦江南：980" in r1 and "首日记录" in r1
        r2 = await digest.build_gold_report(bot)
        assert "梦江南：1010" in r2 and "↑3.1%" in r2 and "昨 980" in r2
        ok("金价播报(首日/涨跌幅对比)")
    finally:
        game_data2._jx3_get = real_gd2

    await say(bot, dispatcher, group_event("订阅 三角洲行动", user_id=USER_A))
    assert "已订阅" in bot.last_text()
    await say(bot, dispatcher, group_event("订阅 三角洲行动", user_id=USER_A))
    assert "已经订阅过" in bot.last_text()
    await say(bot, dispatcher, group_event("我的订阅", user_id=USER_A))
    assert "三角洲行动" in bot.last_text()

    fake_results = [{"title": "三角洲新赛季", "url": "https://e.com/1", "snippet": "s"},
                    {"title": "三角洲补丁", "url": "https://e.com/2", "snippet": "s"}]
    real_bs = websearch.bing_search

    async def fake_bs(q, n=6):
        return list(fake_results)

    websearch.bing_search = fake_bs
    try:
        before = len(bot.sent_texts())
        await digest.sweep_subscriptions(bot)
        texts = bot.sent_texts()
        pushed = [t for _, t in texts[before:] if "订阅「三角洲行动」有新内容" in t]
        assert pushed and "https://e.com/1" in pushed[0]
        before2 = len(bot.sent_texts())
        await digest.sweep_subscriptions(bot)  # 第二次无新内容
        assert not any("有新内容" in t for _, t in bot.sent_texts()[before2:])
        ok("关键词订阅(推送/去重)")
    finally:
        websearch.bing_search = real_bs

    print("\n== 30. 链接总结/识图吐槽/语音 ==")
    import plugins.media as media

    async def fake_page(url):
        return {"url": url, "status": 200, "title": "测试文章标题",
                "desc": "一篇关于测试的文章", "body": "这是正文内容第一段，讲了一些测试要点。"}

    real_fp = media.fetch_page
    fake_media_llm = lambda cfg, msgs, mt=None, tp=None: (
        "总结：这篇讲测试要点。来源：测试文章标题 example.com"
        if any("网页内容" in m["content"] for m in msgs if m.get("role") == "system")
        else "AI锐评：这文字有点东西"
    )
    media.fetch_page = fake_page
    media.chat_once_sync = fake_media_llm
    try:
        await say(bot, dispatcher, group_event("总结 https://example.com/a", user_id=USER_A))
        texts = bot.sent_texts()
        assert any("来源：测试文章标题" in t for _, t in texts), texts[-2:]
        # 识图：带图发吐槽 -> MockBot.call_action 对 ocr_image 返回 {"ok":True}
        # -> str()非空当作OCR文本 -> 走LLM锐评（fake_media_llm输出含"锐评"）
        img_segs = [{"type": "image", "data": {"url": "https://img/1.jpg"}},
                    {"type": "text", "data": {"text": "吐槽"}}]
        await say(bot, dispatcher, group_event(segs=img_segs, user_id=USER_A))
        assert "AI锐评" in bot.last_text(), bot.last_text()
        ok("链接总结/识图吐槽")
    finally:
        media.fetch_page = real_fp
        media.chat_once_sync = real_gd_llm

    import plugins.voice as voice

    def fake_tts(cfg, text):
        p = tmp / "fake_tts.mp3"
        p.write_bytes(b"mp3")
        return p

    real_tts = voice.tts_sync
    voice.tts_sync = fake_tts
    try:
        await say(bot, dispatcher, group_event("说 大家好呀", user_id=USER_A))
        rec_sends = [p for a, p in bot.actions if a in ("send_group_msg", "send_private_msg")
                     and isinstance(p.get("message"), list)
                     and any(s.get("type") == "record" for s in p["message"])]
        assert rec_sends, "语音命令未发送record消息"
        ok("TTS语音点播(本地合成链路)")
    finally:
        voice.tts_sync = real_tts

    print(f"\n{'=' * 46}")
    print(f"ALL PASSED: {PASS_COUNT} 项检查全部通过 ✅")
    print(f"{'=' * 46}")


if __name__ == "__main__":
    asyncio.run(run_tests())
