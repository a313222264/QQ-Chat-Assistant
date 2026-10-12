"""推送包：群聊日报/周报、剑网3金价播报、关键词订阅推送。

命令：
    日报 / 周报            生成本群昨日日报 / 近7天周报
    订阅 关键词 / 退订 关键词 / 我的订阅
定时任务（config.yaml plugins.digest）：
    digest_time 每天   群聊日报推送到 push_groups
    gold_time   每天   金价播报（对比昨日涨跌）
    sub_time    每天   订阅关键词检索推送（去重，只推新）
"""
import asyncio
import json
import time
from datetime import datetime, timedelta

from core import segments, websearch
from core.ai_completion import chat_once_sync
from core.logger import get

log = get("digest")


def _push_groups(bot) -> list:
    groups = [int(g) for g in (bot.cfg.get("plugins.digest.push_groups", []) or [])]
    if not groups:
        groups = [int(g) for g in (bot.cfg.get("plugins.proactive_chat.groups", []) or [])]
    return groups


# ---------------- 群聊日报 ----------------

def _window_since(kind: str):
    now = datetime.now()
    if kind == "周报":
        return now - timedelta(days=7), "近7天"
    # 日报：昨天0点到现在（凌晨生成时覆盖前一天）
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return start, "昨天以来"


async def build_digest(bot, group_id, kind: str = "日报") -> str:
    since, label = _window_since(kind)
    rows = bot.db.recent_messages("group", group_id, int(since.timestamp()), 300)
    rows = [r for r in rows if r["text"] and r["user_id"] != bot.self_id]
    if len(rows) < 5:
        return f"群聊{kind}：{label}消息不足5条，没什么好总结的~"
    lines = []
    for r in rows[-150:]:
        name = r["sender_name"] or str(r["user_id"])
        t = (r["text"] or "").replace("\n", " ")[:80]
        lines.append(f"{name}：{t}")
    history = "\n".join(lines)
    messages = [
        {"role": "system", "content": (
            "你是群聊日报编辑。根据聊天记录写一份群聊日报，格式："
            "【话题】列2-4个主要话题（每个一句话）；【要点】值得记住的事/约定/决定；"
            "【金句】最有趣的1-2句话（注明谁说的）。总共250字内，用中文，不要markdown。"
        )},
        {"role": "user", "content": f"时间范围：{label}\n\n聊天记录：\n{history}"},
    ]
    try:
        summary = await asyncio.to_thread(chat_once_sync, bot.cfg, messages, 800, 0.5)
    except Exception as e:
        log.exception("日报LLM总结失败")
        return f"群聊{kind}生成失败（{e.__class__.__name__}），请稍后再试。"
    return f"📰 群聊{kind}（{label}）\n\n{summary}"


async def _cmd_digest(bot, event, kind: str):
    text = await build_digest(bot, event["group_id"], kind)
    await bot.send_text(event, text[:1500])


# ---------------- 金价播报 ----------------

async def build_gold_report(bot) -> str:
    from plugins.game_data import _jx3_get

    cfg = bot.cfg
    if not cfg.get("plugins.game_data.jx3_token", ""):
        return ""
    servers = [s for s in (cfg.get("plugins.digest.gold_servers", []) or [])]
    try:
        d = await _jx3_get(cfg, "/trade/demon", {"limit": 12})
    except Exception as e:
        log.warning("金价播报拉取失败: %s", e)
        return ""
    if isinstance(d, dict):
        d = [d]
    rows = []
    for item in d or []:
        name = item.get("server", "")
        if servers and name not in servers:
            continue
        try:
            price = float(item.get("wanbaolou") or 0)
        except ValueError:
            continue
        if price > 0:
            rows.append((item.get("zone", ""), name, price))
    if not rows:
        return ""
    rows = rows[:6]
    last = bot.db.kv_get("gold_last") or {}
    lines = ["💰 剑网3金价早报（万宝楼）"]
    new_last = {}
    for zone, name, price in rows:
        prev = last.get(name)
        if prev:
            pct = (price - prev) / prev * 100
            arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "→")
            delta = f"{arrow}{abs(pct):.1f}%（昨 {prev:g}）"
        else:
            delta = "（首日记录）"
        lines.append(f"· {name}：{price:g} {delta}")
        new_last[name] = price
    bot.db.kv_set("gold_last", new_last)
    lines.append("（数据来源 jx3api，数值为万宝楼金币比价）")
    return "\n".join(lines)


# ---------------- 订阅推送 ----------------

async def _cmd_subscribe(bot, event, keyword: str):
    if not keyword or len(keyword) > 30:
        await bot.send_text(event, "格式：订阅 关键词（30字内）")
        return
    rows = bot.db.query(
        "SELECT id FROM subscriptions WHERE user_id=? AND keyword=?",
        (event.get("user_id"), keyword),
    )
    if rows:
        await bot.send_text(event, f"你已经订阅过「{keyword}」了", reply_to=True, at_user=event.get("user_id"))
        return
    chat_type = "group" if event.get("message_type") == "group" else "private"
    chat_id = event.get("group_id") if chat_type == "group" else event.get("user_id")
    bot.db.execute(
        "INSERT INTO subscriptions (user_id, chat_type, chat_id, keyword, created_ts) VALUES (?,?,?,?,?)",
        (event.get("user_id"), chat_type, chat_id, keyword, int(time.time())),
    )
    await bot.send_text(
        event, f"✅ 已订阅「{keyword}」，每天傍晚帮你盯新消息（退订 关键词 可取消）",
        reply_to=True, at_user=event.get("user_id"),
    )


async def _cmd_unsubscribe(bot, event, keyword: str):
    cur = bot.db.execute(
        "DELETE FROM subscriptions WHERE user_id=? AND keyword=?",
        (event.get("user_id"), keyword),
    )
    await bot.send_text(event, f"已退订「{keyword}」" if cur.rowcount else f"你没有订阅过「{keyword}」")


async def _cmd_my_subs(bot, event):
    rows = bot.db.query(
        "SELECT keyword FROM subscriptions WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (event.get("user_id"),),
    )
    if not rows:
        await bot.send_text(event, "还没有订阅，用「订阅 关键词」试试（如：订阅 三角洲 更新）")
    else:
        await bot.send_text(event, "🔔 你的订阅：\n" + "\n".join(f"· {r['keyword']}" for r in rows))


async def sweep_subscriptions(bot):
    """每个关键词检索一次，把新URL推送给所有订阅者（按各自会话）。"""
    kws = bot.db.query(
        "SELECT keyword, COUNT(*) AS cnt FROM subscriptions GROUP BY keyword ORDER BY cnt DESC LIMIT 30"
    )
    for kw_row in kws:
        keyword = kw_row["keyword"]
        results = await websearch.bing_search(keyword, 6)
        if not results:
            continue
        kv_key = f"sub_last:{keyword}"
        old_urls = set(bot.db.kv_get(kv_key) or [])
        fresh = [r for r in results if r["url"] not in old_urls][:3]
        new_urls = [r["url"] for r in results]  # 记录本轮全部，防止旧闻反复推
        bot.db.kv_set(kv_key, new_urls)
        if not fresh:
            continue
        subs = bot.db.query(
            "SELECT DISTINCT chat_type, chat_id FROM subscriptions WHERE keyword=?", (keyword,)
        )
        msg_lines = [f"🔔 订阅「{keyword}」有新内容："] + [
            f"[{i}] {r['title']}\n{r['url']}" for i, r in enumerate(fresh, 1)
        ]
        msg = "\n".join(msg_lines)
        for s in subs:
            try:
                await bot.send_to(s["chat_type"], s["chat_id"], [segments.text(msg)])
            except Exception:
                log.exception("订阅推送失败 %s", s)


# ---------------- 定时注册与消息入口 ----------------

async def on_start(bot):
    cfg = bot.cfg
    if not cfg.get("plugins.digest.enabled", True):
        return
    if bot.scheduler is None:
        return
    groups = _push_groups(bot)

    if groups:
        hh, mm = str(cfg.get("plugins.digest.digest_time", "08:00")).split(":")[:2]
        bot.scheduler.add_job(_job_digest, "cron", hour=int(hh), minute=int(mm),
                              args=[bot], id="digest_daily", replace_existing=True)
        log.info("群聊日报已注册 %s -> %s个群", cfg.get("plugins.digest.digest_time"), len(groups))

    if cfg.get("plugins.digest.gold_enabled", True) and cfg.get("plugins.game_data.jx3_token", ""):
        hh, mm = str(cfg.get("plugins.digest.gold_time", "08:30")).split(":")[:2]
        bot.scheduler.add_job(_job_gold, "cron", hour=int(hh), minute=int(mm),
                              args=[bot], id="gold_daily", replace_existing=True)
        log.info("金价播报已注册 %s", cfg.get("plugins.digest.gold_time"))

    hh, mm = str(cfg.get("plugins.digest.sub_time", "18:00")).split(":")[:2]
    bot.scheduler.add_job(sweep_subscriptions, "cron", hour=int(hh), minute=int(mm),
                          args=[bot], id="sub_sweep", replace_existing=True)


async def _job_digest(bot):
    for gid in _push_groups(bot):
        try:
            text = await build_digest(bot, gid, "日报")
            await bot.send_group_msg(gid, [segments.text(text[:1500])])
        except Exception:
            log.exception("日报推送失败 群%s", gid)


async def _job_gold(bot):
    report = await build_gold_report(bot)
    if report:
        for gid in _push_groups(bot):
            try:
                await bot.send_group_msg(gid, [segments.text(report)])
            except Exception:
                log.exception("金价播报失败 群%s", gid)


async def on_message(bot, event) -> bool:
    if not bot.cfg.get("plugins.digest.enabled", True):
        return False
    if event.get("message_type") != "group":
        return False
    text = segments.plain_text(event)
    if text in ("日报", "群日报"):
        await _cmd_digest(bot, event, "日报")
        return True
    if text in ("周报", "群周报"):
        await _cmd_digest(bot, event, "周报")
        return True
    if text.startswith("订阅 "):
        await _cmd_subscribe(bot, event, text[len("订阅 "):].strip())
        return True
    if text.startswith("退订 "):
        await _cmd_unsubscribe(bot, event, text[len("退订 "):].strip())
        return True
    if text == "我的订阅":
        await _cmd_my_subs(bot, event)
        return True
    return False
