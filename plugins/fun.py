"""趣味包：今日运势、签到积分、小游戏（石头剪刀布/猜数字/成语接龙）、每日一题。

命令：
    签到                  每日签到+5分（连签加成），回复附今日运势
    运势 [@某人]           查看今日运势（按日期+QQ确定，当天固定）
    积分 / 积分排行        查询
    石头 / 剪刀 / 布       石头剪刀布（赢了+2分）
    猜数字 [范围] / <数字>  群级猜数字游戏（猜中+3分）
    成语接龙 / 接龙结束     LLM接龙（接对+1分）
    出题 / 答案是 xxx      每日一题（剑网3/三角洲轮换，答对+10分）
"""
import hashlib
import json
import random
import re
import time
from datetime import date

from core import segments
from core.ai_completion import chat_once_sync
from core.logger import get

log = get("fun")

FORTUNE_LEVELS = ["大吉", "中吉", "小吉", "平", "小凶", "末吉"]
YI_POOL = ["搬砖", "氪金", "抽卡", "开荒", "水群", "睡大觉", "点外卖", "看攻略", "上分", "下副本", "买外观", "收金"]
JI_POOL = ["氪金", "抽卡", "单排", "熬夜", "跟人对线", "吃辣", "剁手", "开团", "跳车", "炸鱼"]
COLORS = ["中国红", "原谅绿", "土豪金", "深海蓝", "基佬紫", "象牙白", "玄学风", "活泼橙"]

_rps_state = {}       # 无需状态：即时对局
_guess_state = {}     # group_id -> {"target", "low", "high", "tries", "started_by"}
_idiom_state = {}     # group_id -> {"idiom", "chain", "starter"}
_quiz_state = {}      # group_id -> {"q", "a", "topic"}


# ---------------- 运势 ----------------

def fortune(qq, day: str) -> dict:
    """确定性运势：同一天同一个人结果不变。"""
    seed = hashlib.md5(f"{qq}|{day}".encode()).hexdigest()
    rng = random.Random(seed)
    level = FORTUNE_LEVELS[min(int(seed[:2], 16) * len(FORTUNE_LEVELS) // 256, len(FORTUNE_LEVELS) - 1)]
    return {
        "level": level,
        "yi": rng.sample(YI_POOL, 2),
        "ji": rng.sample(JI_POOL, 2),
        "num": rng.randint(1, 99),
        "color": rng.choice(COLORS),
    }


def _fortune_text(qq, name: str) -> str:
    f = fortune(qq, date.today().isoformat())
    return (
        f"🔮 {name} 今日【{f['level']}】\n"
        f"宜：{'、'.join(f['yi'])}\n"
        f"忌：{'、'.join(f['ji'])}\n"
        f"幸运数字 {f['num']} · 幸运色 {f['color']}"
    )


# ---------------- LLM 小工具 ----------------

async def _llm(cfg, prompt: str, max_tokens=400) -> str:
    import asyncio

    return await asyncio.to_thread(
        chat_once_sync, cfg,
        [{"role": "system", "content": "你是群聊游戏主持人，严格按要求输出，不要多余解释。"},
         {"role": "user", "content": prompt}],
        max_tokens, 0.7,
    )


def _parse_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


# ---------------- 消息入口 ----------------

async def on_message(bot, event) -> bool:
    if not bot.cfg.get("plugins.fun.enabled", True):
        return False
    if event.get("message_type") != "group":  # 趣味功能仅在群聊
        return False
    text = segments.plain_text(event)
    if not text:
        return False

    gid = event["group_id"]
    uid = event.get("user_id")
    today = date.today().isoformat()

    # ---- 签到 ----
    if text in ("签到", "打卡"):
        first, streak, gained = bot.db.do_sign("group", gid, uid, today)
        if not first:
            await bot.send_text(event, "今天已经签过啦，明天再来~", reply_to=True, at_user=uid)
            return True
        name = (event.get("sender") or {}).get("card") or (event.get("sender") or {}).get("nickname") or str(uid)
        await bot.send_text(
            event,
            f"✅ {name} 签到成功 +{gained}分（连续{streak}天）\n" + _fortune_text(uid, name),
            reply_to=True, at_user=uid,
        )
        return True

    # ---- 运势 ----
    if text == "运势" or text.startswith("运势 "):
        targets = segments.at_targets(event, exclude_self=bot.self_id)
        if targets:
            tqq = targets[0]
            try:
                info = await bot.get_group_member_info(gid, tqq)
                tname = info.get("card") or info.get("nickname") or tqq
            except Exception:
                tname = tqq
            await bot.send_text(event, _fortune_text(tqq, tname))
        else:
            name = (event.get("sender") or {}).get("card") or str(uid)
            await bot.send_text(event, _fortune_text(uid, name), reply_to=True, at_user=uid)
        return True

    # ---- 积分 ----
    if text in ("积分", "我的积分"):
        row = bot.db.get_points_row("group", gid, uid)
        await bot.send_text(event, f"你当前积分：{row['points'] if row else 0}", reply_to=True, at_user=uid)
        return True
    if text in ("积分排行", "排行榜"):
        rows = bot.db.points_leaderboard("group", gid)
        if not rows:
            await bot.send_text(event, "还没有人有积分，发「签到」开局~")
            return True
        lines = ["🏆 积分排行："]
        for i, r in enumerate(rows, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            try:
                info = await bot.get_group_member_info(gid, r["user_id"])
                nm = info.get("card") or info.get("nickname") or r["user_id"]
            except Exception:
                nm = r["user_id"]
            lines.append(f"{medal} {nm}：{r['points']}分")
        await bot.send_text(event, "\n".join(lines))
        return True

    # ---- 石头剪刀布 ----
    if text in ("石头", "剪刀", "布", "石头剪刀布"):
        await _play_rps(bot, event, gid, uid, "石头剪刀布" if text == "石头剪刀布" else text)
        return True

    # ---- 猜数字 ----
    if text == "猜数字" or text.startswith("猜数字 "):
        await _guess_start(bot, event, gid, uid, text)
        return True
    if text == "猜数字结束" and gid in _guess_state:
        st = _guess_state.pop(gid)
        await bot.send_text(event, f"答案是 {st['target']}，下次再来~")
        return True
    if re.fullmatch(r"\d{1,3}", text) and gid in _guess_state:
        await _guess_try(bot, event, gid, uid, int(text))
        return True

    # ---- 成语接龙 ----
    if text == "成语接龙":
        await _idiom_start(bot, event, gid, uid)
        return True
    if text == "接龙结束":
        st = _idiom_state.pop(gid, None)
        await bot.send_text(event, f"接龙结束，本轮接对 {st['chain']} 次" if st else "现在没有接龙")
        return True
    if gid in _idiom_state and re.fullmatch(r"[\u4e00-\u9fa5]{4}", text):
        await _idiom_try(bot, event, gid, uid, text)
        return True

    # ---- 每日一题 ----
    if text in ("出题", "每日一题"):
        await _quiz_start(bot, event, gid)
        return True
    if text.startswith("答案是 ") and gid in _quiz_state:
        await _quiz_answer(bot, event, gid, uid, text[len("答案是 "):].strip())
        return True
    if text == "放弃答题" and gid in _quiz_state:
        st = _quiz_state.pop(gid)
        await bot.send_text(event, f"答案是：{st['a']}。下次加油！")
        return True

    return False


# ---------------- 石头剪刀布 ----------------

async def _play_rps(bot, event, gid, uid, user_choice: str):
    if user_choice == "石头剪刀布":
        await bot.send_text(event, "直接出招：石头/剪刀/布", reply_to=True, at_user=uid)
        return
    bot_choice = random.choice(["石头", "剪刀", "布"])
    beats = {"石头": "剪刀", "剪刀": "布", "布": "石头"}
    if user_choice == bot_choice:
        await bot.send_text(event, f"我出{bot_choice}，平局！再来", reply_to=True, at_user=uid)
        return
    if beats[user_choice] == bot_choice:  # 用户赢
        bot.db.add_points("group", gid, uid, 2)
        await bot.send_text(event, f"我出{bot_choice}，你赢了！+2分", reply_to=True, at_user=uid)
        await _meme_for(bot, gid, ["帅哥", "开心"])
    else:
        await bot.send_text(event, f"我出{bot_choice}，你输了~", reply_to=True, at_user=uid)
        await _meme_for(bot, gid, ["打工人", "酸了"])


async def _meme_for(bot, gid, keywords) -> None:
    """游戏结算后按关键词附加一张表情包（图库命中才发）。"""
    try:
        from plugins import memes

        for kw in keywords:
            hits = memes.find_memes(bot.cfg, kw)
            if hits:
                await bot.send_group_msg(
                    gid, [{"type": "image", "data": {"file": str(random.choice(hits)["path"].resolve())}}]
                )
                return
    except Exception:
        log.debug("游戏表情包发送失败", exc_info=True)


# ---------------- 猜数字 ----------------

async def _guess_start(bot, event, gid, uid, text):
    rng_max = 100
    m = re.match(r"猜数字\s+(\d+)", text)
    if m:
        rng_max = max(10, min(int(m.group(1)), 1000))
    _guess_state[gid] = {"target": random.randint(1, rng_max), "low": 1, "high": rng_max,
                         "tries": 0, "started_by": uid}
    await bot.send_text(event, f"🎲 我在想一个 1~{rng_max} 的数字，直接发数字猜（发送「猜数字结束」放弃）", reply_to=True, at_user=uid)


async def _guess_try(bot, event, gid, uid, n: int):
    st = _guess_state[gid]
    st["tries"] += 1
    if n == st["target"]:
        del _guess_state[gid]
        bot.db.add_points("group", gid, uid, 3)
        await bot.send_text(event, f"🎉 猜中了！答案就是 {n}（用了{st['tries']}次）+3分", reply_to=True, at_user=uid)
    elif n < st["target"]:
        st["low"] = max(st["low"], n + 1)
        await bot.send_text(event, f"小了，范围 {st['low']}~{st['high']}", reply_to=True, at_user=uid)
    else:
        st["high"] = min(st["high"], n - 1)
        await bot.send_text(event, f"大了，范围 {st['low']}~{st['high']}", reply_to=True, at_user=uid)


# ---------------- 成语接龙 ----------------

async def _idiom_start(bot, event, gid, uid):
    raw = await _llm(bot.cfg, "出一个常见的四字成语作为接龙开头，只输出成语本身，不要拼音和解释。")
    idiom = re.search(r"[\u4e00-\u9fa5]{4}", raw or "")
    if not idiom:
        await bot.send_text(event, "接龙生成失败，稍后再试")
        return
    word = idiom.group(0)
    _idiom_state[gid] = {"idiom": word, "chain": 0, "starter": uid}
    await bot.send_text(event, f"🐲 成语接龙开始：【{word}】\n用「{word[-1]}」开头的成语接上！接对+1分，发「接龙结束」收官")


async def _idiom_try(bot, event, gid, uid, text: str):
    st = _idiom_state[gid]
    if text[0] != st["idiom"][-1]:
        await bot.send_text(event, f"要以「{st['idiom'][-1]}」开头哦", reply_to=True, at_user=uid)
        return
    raw = await _llm(
        bot.cfg,
        f"判断「{text}」是否是真实存在的四字成语，并接一个以「{text[-1]}」开头的常见成语。"
        f'严格输出JSON：{{"valid": true/false, "next": "成语"}}',
    )
    data = _parse_json(raw) or {}
    if not data.get("valid"):
        await bot.send_text(event, f"「{text}」好像不是成语，换一个~", reply_to=True, at_user=uid)
        return
    bot.db.add_points("group", gid, uid, 1)
    st["chain"] += 1
    nxt = data.get("next") or ""
    if not re.fullmatch(r"[\u4e00-\u9fa5]{4}", nxt or ""):
        await bot.send_text(event, f"✅ +1分！我卡壳了，你赢下本轮（共接对{st['chain']}次）")
        del _idiom_state[gid]
        return
    st["idiom"] = nxt
    await bot.send_text(event, f"✅ +1分！我接：【{nxt}】→ 到你了（{nxt[-1]}）")


# ---------------- 每日一题 ----------------

QUIZ_TOPICS = ["剑网3", "三角洲行动", "游戏常识"]


async def _quiz_start(bot, event, gid):
    topic = QUIZ_TOPICS[date.today().timetuple().tm_yday % len(QUIZ_TOPICS)]
    raw = await _llm(
        bot.cfg,
        f"出一道关于{topic}的选择题（四个选项A-D，答案明确唯一，难度中等）。"
        f'严格输出JSON：{{"q": "题目", "options": ["A. xx", "B. xx", "C. xx", "D. xx"], "a": "正确选项字母"}}',
    )
    data = _parse_json(raw) or {}
    if not data.get("q"):
        await bot.send_text(event, "出题失败，稍后再试")
        return
    _quiz_state[gid] = {"q": data["q"], "a": str(data.get("a", "")).strip().upper()[:1], "topic": topic}
    opts = "\n".join(data.get("options") or [])
    await bot.send_text(event, f"📝 每日一题（{topic}）\n{data['q']}\n{opts}\n\n发「答案是 X」作答，答对+10分，「放弃答题」看答案")


async def _quiz_answer(bot, event, gid, uid, ans: str):
    st = _quiz_state[gid]
    user = ans.strip().upper()[:1]
    if user == st["a"]:
        del _quiz_state[gid]
        bot.db.add_points("group", gid, uid, 10)
        await bot.send_text(event, f"🎉 答对了！+10分", reply_to=True, at_user=uid)
    else:
        await bot.send_text(event, "不对哦，再想想（或「放弃答题」）", reply_to=True, at_user=uid)
