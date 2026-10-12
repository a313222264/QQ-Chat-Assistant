"""自主聊天插件：让机器人像普通群员一样，看群里聊什么然后自然插话。

工作方式（低频试跑默认参数）：
    每 30~180 分钟随机触发一次 -> 检查群里最近2小时聊天记录 ->
    不足5条跳过（群里没人聊就不硬聊）-> 让AI以群员身份生成一句自然的话 ->
    AI返回[SKIP]就不发 -> 发送纯文本（无@、无markdown、口语化）

防呆设计：
    深夜静默（默认23:00-08:00）；每天每群上限（默认5条）；
    机器人自己刚说过话就不插（防自嗨）；连续SKIP自动拉长间隔。
"""
import random
import time
from datetime import datetime

from core import ai_completion
from core.logger import get

log = get("proactive_chat")

_daily: dict = {}          # (group_id, date) -> 次数
_skip_streak: dict = {}    # group_id -> 连续SKIP次数
_chat_started: dict = {}   # group_id -> True（本次会话已插入过话）

PROACTIVE_PROMPT = """你是QQ群「{group}」里的一个普通群员，网名"东小0"。性格随和、有点幽默，熟悉游戏和日常话题。
下面是这个群最近的聊天记录。请以普通群员的身份，自然地接一句话，要求：
1. 像真人随手打字：口语化、简短（一般不超过30个字）、可以不用标点结尾、可以用网络用语
2. 紧跟当前话题接话/吐槽/提问，不要自我介绍，不要说"作为AI"，不要提"聊天记录"
3. 只输出这一句话本身，不要任何解释、引号或格式
4. 如果最近聊的内容你实在接不上话，或者没有值得说的，只输出：[SKIP]

最近聊天记录：
{history}"""


def _in_quiet_hours(now: datetime, quiet) -> bool:
    """quiet=[23,8] 表示 23:00-08:00 不说话。"""
    if not quiet or len(quiet) < 2:
        return False
    start, end = int(quiet[0]), int(quiet[1])
    h = now.hour
    if start <= end:
        return start <= h < end
    return h >= start or h < end  # 跨午夜


def _daily_count(group_id) -> int:
    return _daily.get((group_id, time.strftime("%Y-%m-%d")), 0)


def _bump_daily(group_id):
    key = (group_id, time.strftime("%Y-%m-%d"))
    _daily[key] = _daily.get(key, 0) + 1


def _schedule_next(bot):
    """按配置的随机间隔安排下一次触发。"""
    if bot.scheduler is None:
        return
    cfg = bot.cfg
    lo = int(cfg.get("plugins.proactive_chat.min_gap_minutes", 30))
    hi = int(cfg.get("plugins.proactive_chat.max_gap_minutes", 180))
    skip_bonus = min(_skip_streak.get("__total__", 0), 5) * lo  # 连续SKIP则拉长间隔
    delay = random.randint(lo, hi) + skip_bonus
    from datetime import timedelta

    bot.scheduler.add_job(_tick, "date", run_date=datetime.now() + timedelta(minutes=delay),
                          args=[bot], id="proactive_tick", replace_existing=True)
    log.info("自主聊天下次触发：%s 分钟后", delay)


async def on_start(bot):
    if not bot.cfg.get("plugins.proactive_chat.enabled", True):
        return
    _schedule_next(bot)


def _build_history_text(rows, self_id) -> str:
    lines = []
    for r in rows:
        name = r["sender_name"] or str(r["user_id"])
        prefix = "你" if str(r["user_id"]) == str(self_id) else name
        text = (r["text"] or "")[:80]
        if text:
            lines.append(f"{prefix}：{text}")
    return "\n".join(lines)


async def _tick(bot):
    """定时触发：每个启用群尝试插一次话。"""
    try:
        cfg = bot.cfg
        groups = [int(g) for g in (cfg.get("plugins.proactive_chat.groups", []) or [])]
        if not groups or bot.self_id is None:
            return

        now = datetime.now()
        quiet = cfg.get("plugins.proactive_chat.quiet_hours", [23, 8])
        daily_limit = int(cfg.get("plugins.proactive_chat.daily_limit", 5))
        chance = float(cfg.get("plugins.proactive_chat.chance", 0.6))
        min_msgs = int(cfg.get("plugins.proactive_chat.min_recent_msgs", 5))
        window_h = float(cfg.get("plugins.proactive_chat.history_window_hours", 2))

        if _in_quiet_hours(now, quiet):
            return

        for gid in groups:
            if _daily_count(gid) >= daily_limit:
                continue
            if random.random() > chance:
                continue
            try:
                await _try_chat_in_group(bot, gid, min_msgs, window_h)
            except Exception:
                log.exception("自主聊天群 %s 处理失败", gid)
    finally:
        _schedule_next(bot)


async def _try_chat_in_group(bot, gid: int, min_msgs: int, window_h: float):
    cfg = bot.cfg
    since = time.time() - window_h * 3600
    rows = bot.db.recent_messages("group", gid, since, 30)
    if len(rows) < min_msgs:
        log.info("群%s 最近聊天不足%d条，跳过", gid, min_msgs)
        return

    # 防自嗨：机器人自己最后一条消息距今太近就不插
    last_mine = bot.db.last_message_from("group", gid, bot.self_id)
    if last_mine and time.time() - last_mine["ts"] < int(cfg.get("plugins.proactive_chat.min_gap_minutes", 30)) * 60:
        return
    # 群里最近一条消息太旧（>1小时）也不插
    if time.time() - rows[-1]["ts"] > 3600:
        return

    history = _build_history_text(rows, bot.self_id)
    group_name = f"群{gid}"
    try:
        gl = await bot.call_action("get_group_info", group_id=gid)
        group_name = gl.get("group_name") or group_name
    except Exception:
        pass

    prompt = PROACTIVE_PROMPT.format(group=group_name, history=history)
    messages = [
        {"role": "system", "content": bot.db.kv_get("ai_persona") or cfg.get("ai.system_prompt", "你是友好的聊天助手。")},
        {"role": "user", "content": prompt},
    ]
    try:
        reply = await asyncio_to_thread_completion(cfg, messages)
    except Exception:
        log.exception("自主聊天LLM调用失败")
        return

    if not reply or "[SKIP]" in reply or len(reply) > 100:
        _skip_streak[gid] = _skip_streak.get(gid, 0) + 1
        _skip_streak["__total__"] = _skip_streak.get("__total__", 0) + 1
        log.info("群%s 自主聊天SKIP（%s）", gid, (reply or "空")[:30])
        return

    _skip_streak[gid] = 0
    await bot.send_group_msg(gid, [{"type": "text", "data": {"text": reply[:80]}}])
    _bump_daily(gid)
    # 插话进AI上下文：下次被@聊天时它记得自己说过什么
    from plugins import ai_chat

    hist = ai_chat._contexts.setdefault(f"g:{gid}", [])
    hist.append({"role": "assistant", "content": reply[:80]})
    max_ctx = int(cfg.get("ai.max_context", 12))
    if len(hist) > max_ctx:
        del hist[:-max_ctx]
    # 存档：自主发言也进消息库（防自嗨依赖它）
    bot.db.insert_message(
        {"time": int(time.time()), "message_id": "", "message_type": "group",
         "group_id": gid, "user_id": bot.self_id, "sender": {"card": "", "nickname": "东小0"}},
        reply[:80], "",
    )
    # 10% 概率跟一张表情包
    if random.random() < float(cfg.get("plugins.proactive_chat.meme_chance", 0.1)):
        try:
            from plugins import memes

            index = memes.build_index(cfg)
            if index:
                pick = random.choice(index)
                await bot.send_group_msg(gid, [{"type": "image", "data": {"file": str(pick["path"].resolve())}}])
        except Exception:
            log.exception("自主聊天发表情包失败")


async def asyncio_to_thread_completion(cfg, messages):
    return await asyncio.to_thread(ai_completion.chat_once_sync, cfg, messages, 600)
