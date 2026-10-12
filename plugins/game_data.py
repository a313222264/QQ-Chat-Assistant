"""游戏数据查询插件：剑网3（jx3api 官方社区API）+ 三角洲行动（网页检索）。

命令：
    剑网3 活动              —— 今日活动日历（大战/战场/矿车/周常，免token）
    剑网3 开服 [区服]        —— 大区开服状态（免token）
    剑网3 公告              —— 最新维护公告（免token）
    剑网3 骚话              —— 随机骚话（免token）
    剑网3 金价 [区服]        —— 金价行情（需要 config 里配 jx3_token，jx3api.com 注册）
    三角洲 关键词            —— 网页实时检索 + AI整理（注明来源和时间）

AI 工具：query_jx3(action, server) / web_search(query)
准确性约定：AI回答数据类问题必须只基于工具返回结果，并标注数据时间和来源。
"""
import asyncio
import json
import time
from datetime import datetime

import httpx

from core import segments, websearch
from core.logger import get
from core.tools import register_tool

log = get("game_data")

JX3_BASE = "https://www.jx3api.com"

STATUS_TEXT = {0: "未开服", 1: "已开服"}


async def _jx3_get(cfg, path: str, params: dict = {}) -> dict:
    """请求 jx3api，返回 data 字段；失败抛异常。"""
    token = cfg.get("plugins.game_data.jx3_token", "") or ""
    if token:
        params = {**params, "token": token}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(JX3_BASE + path, params=params)
    d = r.json()
    if d.get("code") != 200:
        raise RuntimeError(d.get("msg") or f"接口返回 code={d.get('code')}")
    return d.get("data")


def _fmt_ts(ts) -> str:
    try:
        return datetime.fromtimestamp(int(ts)).strftime("%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return "未知时间"


# ---------------- 各数据源格式化 ----------------

async def fetch_calendar(cfg) -> str:
    d = await _jx3_get(cfg, "/active/calendar")
    lines = [f"📅 剑网3今日活动（{d.get('date','')} 周{d.get('week','')}）"]
    if d.get("war"):
        lines.append(f"· 大战：{d['war']}")
    if d.get("battle"):
        lines.append(f"· 战场：{d['battle']}")
    if d.get("orecar"):
        lines.append(f"· 矿车：{d['orecar']}")
    if d.get("rescue"):
        lines.append(f"· 救援：{d['rescue']}")
    if d.get("school"):
        lines.append(f"· 门派：{d['school']}")
    if d.get("card"):
        lines.append(f"· 名片副本：{'、'.join(d['card'])}")
    weekly = d.get("weekly") or {}
    if weekly.get("raid"):
        lines.append(f"· 本周团本：{'、'.join(weekly['raid'])}")
    lines.append(f"（数据时间 {datetime.now().strftime('%H:%M')}，来源 jx3api）")
    return "\n".join(lines)


async def fetch_server_check(cfg, server: str = "") -> str:
    d = await _jx3_get(cfg, "/server/status/check")
    now = int(time.time())
    if server:
        hits = [s for s in d if server in (s.get("server") or "") or server in (s.get("zone") or "")]
        if not hits:
            return f"没有找到包含「{server}」的区服。可用区服示例：{'、'.join(s['server'] for s in d[:8])}…"
        lines = [f"🖥 区服「{server}」状态："]
        for s in hits[:8]:
            st = STATUS_TEXT.get(s.get("status"), "未知")
            lines.append(f"· {s['zone']}/{s['server']}：{st}（维护时间 {_fmt_ts(s.get('shuttime'))}）")
        lines.append(f"（数据时间 {datetime.now().strftime('%H:%M')}，来源 jx3api）")
        return "\n".join(lines)
    open_cnt = sum(1 for s in d if s.get("status") == 1)
    lines = [f"🖥 全服状态：共{len(d)}个区服，已开服 {open_cnt} 个（数据时间 {datetime.now().strftime('%H:%M')}）"]
    for s in d[:10]:
        lines.append(f"· {s['zone']}/{s['server']}：{STATUS_TEXT.get(s.get('status'), '未知')}")
    if len(d) > 10:
        lines.append(f"…等共{len(d)}个区服。查单个服：剑网3 开服 区服名")
    return "\n".join(lines)


async def fetch_announce(cfg) -> str:
    d = await _jx3_get(cfg, "/news/announce")
    if not d:
        return "暂无维护公告"
    item = d[0]
    import re
    content = re.sub(r"<[^>]+>", "", item.get("desc", {}).get("content", "") or "")
    content = re.sub(r"\s+", " ", content).strip()[:300]
    return (
        f"📢 官方公告（{item.get('date','')}）\n"
        f"{content}\n"
        f"（来源：剑网3官网公告，jx3api 整理）"
    )


GOLD_CHANNELS = [
    ("wanbaolou", "万宝楼"),
    ("tieba", "贴吧"),
    ("dd373", "DD373"),
    ("uu898", "UU898"),
    ("7881", "7881"),
    ("5173", "5173"),
]


async def fetch_demon(cfg, server: str = "") -> str:
    if not cfg.get("plugins.game_data.jx3_token", ""):
        return (
            "金价行情需要在 jx3api.com 注册令牌（该接口收费）。\n"
            "注册后把 token 填到 config.yaml 的 plugins.game_data.jx3_token，发「重载配置」即可。"
        )
    params = {"limit": 5}
    if server:
        params["server"] = server
    d = await _jx3_get(cfg, "/trade/demon", params)
    if isinstance(d, dict):  # 单服模式返回dict
        d = [d]
    lines = ["💰 剑网3金价行情（各渠道金币比价）："]
    for item in (d or [])[:5]:
        parts = []
        for key, name in GOLD_CHANNELS:
            v = str(item.get(key, "") or "")
            if v and v not in ("000.00", "0.00"):
                parts.append(f"{name}{v}")
        date = item.get("date", "")
        head = f"{item.get('zone','')}/{item.get('server','')}"
        lines.append(f"· {head}（{date}）：{'、'.join(parts) if parts else '暂无数据'}")
    lines.append("（数值为各渠道实时行情，来源 jx3api）")
    return "\n".join(lines)


async def fetch_saohua(cfg) -> str:
    d = await _jx3_get(cfg, "/saohua/random")
    return d.get("text", "…")


# ---------------- 消息命令 ----------------

async def on_message(bot, event) -> bool:
    if not bot.cfg.get("plugins.game_data.enabled", True):
        return False
    text = segments.plain_text(event)

    if text.startswith("剑网3 ") or text.startswith("剑网三 "):
        arg = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        default_server = bot.cfg.get("plugins.game_data.jx3_server", "") or ""
        try:
            if arg.startswith("活动") or arg == "日常":
                await bot.send_text(event, await fetch_calendar(bot.cfg))
            elif arg.startswith("开服"):
                await bot.send_text(event, await fetch_server_check(bot.cfg, arg[len("开服"):].strip() or default_server))
            elif arg.startswith("公告"):
                await bot.send_text(event, await fetch_announce(bot.cfg))
            elif arg.startswith("骚话"):
                await bot.send_text(event, await fetch_saohua(bot.cfg))
            elif arg.startswith("金价"):
                await bot.send_text(event, await fetch_demon(bot.cfg, arg[len("金价"):].strip() or default_server))
            elif arg == "帮助" or not arg:
                await bot.send_text(event, "⚔️ 剑网3查询：\n· 剑网3 活动\n· 剑网3 开服 [区服]\n· 剑网3 公告\n· 剑网3 金价 [区服]\n· 剑网3 骚话")
            else:
                return False
        except Exception as e:
            log.warning("剑网3查询失败: %s", e)
            await bot.send_text(event, f"查询失败：{e}")
        return True

    if text.startswith("三角洲 ") or text.startswith("三角洲行动 "):
        arg = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
        if not arg:
            await bot.send_text(event, "格式：三角洲 关键词（例：三角洲 本赛季曼德尔砖行情）")
            return True
        await bot.send_text(event, "🔍 正在检索三角洲行动的相关信息，稍等…")
        answer = await delta_query(bot, arg)
        await bot.send_text(event, answer)
        return True

    return False


# ---------------- 三角洲：网页检索 + AI 整理 ----------------

async def delta_query(bot, question: str) -> str:
    """搜索三角洲行动相关网页 -> 让AI基于结果整理回答（带来源）。"""
    results = await websearch.bing_search("三角洲行动 " + question, 6)
    if not results:
        return f"网页检索没有返回结果（{question}），可能是网络问题，稍后再试。"
    from core.ai_completion import summarize_search

    return await summarize_search(bot.cfg, f"三角洲行动 {question}", results)


# ---------------- AI 工具 ----------------

@register_tool(
    "query_jx3",
    "查询剑网3官方社区数据。action可选: calendar(今日活动)/check(开服状态,可带server)/announce(维护公告)/demon(金价,需token,可带server)",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["calendar", "check", "announce", "demon"], "description": "查询类型"},
            "server": {"type": "string", "description": "区服名（check/demon 可选）"},
        },
        "required": ["action"],
    },
)
async def _tool_query_jx3(bot, args, ctx):
    action = args.get("action", "")
    server = args.get("server", "") or bot.cfg.get("plugins.game_data.jx3_server", "") or ""
    if action == "calendar":
        return await fetch_calendar(bot.cfg)
    if action == "check":
        return await fetch_server_check(bot.cfg, server)
    if action == "announce":
        return await fetch_announce(bot.cfg)
    if action == "demon":
        return await fetch_demon(bot.cfg, server)
    return f"未知 action: {action}（可选 calendar/check/announce/demon）"


@register_tool(
    "web_search",
    "搜索网页获取实时信息（新闻、行情、版本信息等）。返回带编号的结果列表，回答时必须注明来源编号和链接。",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
        "required": ["query"],
    },
)
async def _tool_web_search(bot, args, ctx):
    query = args.get("query", "")
    results = await websearch.bing_search(query, 6)
    return websearch.format_results(query, results)
