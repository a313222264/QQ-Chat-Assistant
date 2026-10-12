"""个人生活助手：定时提醒、待办清单、记账、天气查询、每日播报。

命令：
    提醒我 30分钟后 喝水 | 提醒我 明天9点 开会 | 提醒我 每天8:30 打卡 | 提醒我 每周一 9:00 例会
    查看提醒 / 取消提醒 编号
    添加待办 内容 / 看待办 / 完成待办 编号
    记账 午饭 25 / 查账 今日|本月
    天气 [城市]        —— 不带城市=常驻城市/自动定位，数据后附AI总结（穿衣/带伞建议）
    设置城市 城市名     —— 设置常驻城市，之后直接发「天气」即可
每日播报在 config.yaml 的 plugins.life_assistant.daily_report 配置。
AI 工具：get_weather(location) —— 聊天中自然语言查询天气。
"""
import asyncio
import re
import time
from datetime import datetime, timedelta

import httpx

from core import segments
from core.ai_completion import chat_once_sync
from core.logger import get
from core.tools import register_tool

log = get("life_assistant")

WMO_CODES = {
    0: "晴", 1: "大致晴", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "小毛雨", 53: "毛雨", 55: "大毛雨", 61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "强冻雨", 71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "强阵雨", 82: "暴雨", 85: "小阵雪", 86: "大阵雪",
    95: "雷雨", 96: "雷雨伴冰雹", 99: "强雷雨伴冰雹",
}

WEEKDAY_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


# ================= 时间解析 =================

def _parse_hhmm(s: str, base: datetime) -> tuple:
    """解析 '9点' '9点半' '9点30分' '9:30' '18时'，返回 (时, 分)。已过当日时间由调用方决定顺延。"""
    s = s.strip()
    m = re.match(r"^(\d{1,2})[点时:：](?:(\d{1,2})分?|半)?$", s)
    if not m:
        return None
    hour, minute = int(m.group(1)), m.group(2)
    minute = int(minute) if minute else (30 if "半" in s else 0)
    return hour, minute


def _apply_period(hour: int, period: str) -> int:
    """按 早上/上午/中午/下午/晚上/凌晨 修正 12 小时制。"""
    if period in ("下午", "晚上", "晚间"):
        if 1 <= hour <= 11:
            return hour + 12
        return hour  # 晚上12点 → 24点按 0 处理由调用方取模
    if period == "中午":
        return hour if hour >= 11 else hour + 12
    return hour  # 早上/上午/凌晨 原样


def parse_when(text: str):
    """解析时间描述，返回 (run_at: int|None, cron: str|None, human: str|None)。"""
    text = text.strip()

    # ---- 循环：每天 ----
    m = re.search(r"每\s*天\s*(早上|上午|中午|下午|晚上|晚间|凌晨)?\s*(\d{1,2})[点时:：](?:(\d{1,2})分?|半)?", text)
    if m:
        hh = _apply_period(int(m.group(2)), m.group(1) or "")
        hh %= 24
        mm = int(m.group(3)) if m.group(3) else (30 if "半" in m.group(0) else 0)
        return None, f"daily {hh:02d}:{mm:02d}", f"每天 {hh:02d}:{mm:02d}"

    # ---- 循环：每周X ----
    m = re.search(r"每\s*周\s*([一二三四五六日天])\s*(早上|上午|中午|下午|晚上|晚间|凌晨)?\s*(\d{1,2})[点时:：](?:(\d{1,2})分?|半)?", text)
    if m:
        wd = WEEKDAY_CN[m.group(1)]
        hh = _apply_period(int(m.group(3)), m.group(2) or "") % 24
        mm = int(m.group(4)) if m.group(4) else (30 if "半" in m.group(0) else 0)
        names = "一二三四五六日"
        return None, f"weekly {wd} {hh:02d}:{mm:02d}", f"每周{names[wd]} {hh:02d}:{mm:02d}"

    # ---- 相对：N分钟/小时/天后 ----
    m = re.search(r"(\d+(?:\.\d+)?)\s*(分钟|个小时|小时|半天|天)后", text)
    if m:
        n = float(m.group(1))
        unit = m.group(2)
        seconds = {"分钟": n * 60, "个小时": n * 3600, "小时": n * 3600, "半天": 43200, "天": n * 86400}[unit]
        run_at = time.time() + seconds
        human = f"{m.group(0)}（{datetime.fromtimestamp(int(run_at)).strftime('%m-%d %H:%M')}）"
        return int(run_at), None, human

    # ---- 日期 + 时间 ----
    base = datetime.now()
    day = None
    day_human = ""
    m = re.search(r"(今天|今日|今晚|明天|明晚|后天|大后天)", text)
    if m:
        kw = m.group(1)
        offset = {"今天": 0, "今日": 0, "今晚": 0, "明天": 1, "明晚": 1, "后天": 2, "大后天": 3}[kw]
        day = (base + timedelta(days=offset)).date()
        day_human = kw
    else:
        m = re.search(r"(\d{1,2})月(\d{1,3})[日号]", text)
        if m:
            month, d = int(m.group(1)), int(m.group(2))
            try:
                day = base.replace(month=month, day=d).date()
                if day < base.date():
                    day = day.replace(year=day.year + 1)
                day_human = f"{month}月{d}日"
            except ValueError:
                return None, None, None

    # 时间部分
    m = re.search(r"(早上|上午|中午|下午|晚上|晚间|凌晨)?\s*(\d{1,2})[点时:：](?:(\d{1,2})分?|半)?", text)
    if m:
        hh = int(m.group(2))
        mm = int(m.group(3)) if m.group(3) else (30 if "半" in m.group(0) else 0)
        hh = _apply_period(hh, m.group(1) or "") % 24
        if day is None:
            day = base.date()
            cand = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
            if cand <= base:  # 没说今天明天，时间已过 → 顺延到明天
                cand += timedelta(days=1)
                day_human = "明天"
            run_at = int(cand.timestamp())
            human = f"{day_human or '今天'} {hh:02d}:{mm:02d}"
            return run_at, None, human
        cand = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
        return int(cand.timestamp()), None, f"{day_human} {hh:02d}:{mm:02d}"

    # 只有日期没时间 → 默认当天 9:00
    if day is not None:
        cand = datetime.combine(day, datetime.min.time()).replace(hour=9)
        return int(cand.timestamp()), None, f"{day_human} 09:00（默认上午）"

    return None, None, None


# ================= 插件主体 =================

async def on_message(bot, event) -> bool:
    if not bot.cfg.get("plugins.life_assistant.enabled", True):
        return False
    text = segments.plain_text(event)

    if text.startswith("提醒我 "):
        await _cmd_remind(bot, event, text[len("提醒我 "):].strip())
        return True
    if text == "查看提醒":
        await _cmd_list_reminders(bot, event)
        return True
    if text.startswith("取消提醒 "):
        await _cmd_cancel_reminder(bot, event, text[len("取消提醒 "):].strip())
        return True
    if text.startswith("添加待办 "):
        await _cmd_add_todo(bot, event, text[len("添加待办 "):].strip())
        return True
    if text == "看待办":
        await _cmd_list_todos(bot, event)
        return True
    if text.startswith("完成待办 "):
        await _cmd_done_todo(bot, event, text[len("完成待办 "):].strip())
        return True
    if text.startswith("记账 "):
        await _cmd_ledger_add(bot, event, text[len("记账 "):].strip())
        return True
    if text.startswith("查账"):
        await _cmd_ledger_query(bot, event, text[2:].strip())
        return True
    if text == "天气" or text.startswith("天气 "):
        await _cmd_weather(bot, event, text[3:].strip())
        return True
    if text.startswith("设置城市 "):
        await _cmd_set_city(bot, event, text[len("设置城市 "):].strip())
        return True
    if text == "设置城市":
        await _cmd_set_city(bot, event, "")
        return True
    return False


# ---------- 提醒 ----------

async def _cmd_remind(bot, event, arg: str):
    if not arg:
        await bot.send_text(event, "格式：提醒我 时间 事情\n例：提醒我 30分钟后 喝水")
        return
    run_at, cron, human = parse_when(arg)
    if run_at is None and cron is None:
        await bot.send_text(
            event,
            "没看懂时间，试试这些写法：\n· 30分钟后 / 2小时后\n· 明天9点 / 明天18:30\n· 每天8:30 / 每周一 9:00",
        )
        return

    chat_type = "group" if event.get("message_type") == "group" else "private"
    chat_id = event.get("group_id") if chat_type == "group" else event.get("user_id")
    todo_text = _strip_time_prefix(arg)
    cur = bot.db.execute(
        "INSERT INTO reminders (chat_type, chat_id, user_id, run_at, cron, text, created_ts) "
        "VALUES (?,?,?,?,?,?,?)",
        (chat_type, chat_id, event.get("user_id"), run_at, cron, todo_text, int(time.time())),
    )
    rid = cur.lastrowid
    _schedule_reminder(bot, rid, chat_type, chat_id, event.get("user_id"), run_at, cron, todo_text)
    if cron:
        await bot.send_text(event, f"⏰ 已设置循环提醒 #{rid}：{human}\n内容：{todo_text}")
    else:
        await bot.send_text(event, f"⏰ 已设置提醒 #{rid}：{human}\n内容：{todo_text}")


def _strip_time_prefix(arg: str) -> str:
    """把时间描述从内容里去掉，剩下的事作为提醒内容。"""
    parts = arg.strip()
    m = re.search(
        r"(每\s*周\s*[一二三四五六日天]\s*)?((早上|上午|中午|下午|晚上|晚间|凌晨)?\s*\d{1,2}[点时:：](\d{1,2}分?|半)?)"
        r"|(每\s*天\s*(早上|上午|中午|下午|晚上|晚间|凌晨)?\s*\d{1,2}[点时:：](\d{1,2}分?|半)?)"
        r"|(\d+(?:\.\d+)?\s*(分钟|个小时|小时|半天|天)后)"
        r"|((今天|今日|今晚|明天|明晚|后天|大后天))"
        r"|(\d{1,2}月\d{1,3}[日号])",
        parts,
    )
    if m:
        rest = (parts[:m.start()] + parts[m.end():]).strip()
        return rest or parts
    return parts


async def _cmd_list_reminders(bot, event):
    user_id = event.get("user_id")
    rows = bot.db.query(
        "SELECT * FROM reminders WHERE user_id=? AND done=0 ORDER BY created_ts DESC LIMIT 20",
        (user_id,),
    )
    if not rows:
        await bot.send_text(event, "你还没有进行中的提醒")
        return
    lines = ["⏰ 进行中的提醒："]
    for r in rows:
        if r["cron"]:
            parts = r["cron"].split()
            if parts[0] == "weekly":
                names = "一二三四五六日"
                desc = f"每周{names[int(parts[1])]} {parts[2]}"
            else:
                desc = f"每天 {parts[1]}"
        else:
            desc = datetime.fromtimestamp(r["run_at"]).strftime("%m-%d %H:%M")
        lines.append(f"#{r['id']} [{desc}] {r['text']}")
    await bot.send_text(event, "\n".join(lines))


async def _cmd_cancel_reminder(bot, event, arg: str):
    if not arg.isdigit():
        await bot.send_text(event, "格式：取消提醒 编号（编号从 查看提醒 里看）")
        return
    rid = int(arg)
    rows = bot.db.query("SELECT * FROM reminders WHERE id=? AND user_id=?", (rid, event.get("user_id")))
    if not rows or rows[0]["done"]:
        await bot.send_text(event, f"没有找到你的提醒 #{rid}")
        return
    bot.db.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
    if bot.scheduler:
        try:
            bot.scheduler.remove_job(f"reminder_{rid}")
        except Exception:
            pass
    await bot.send_text(event, f"✅ 提醒 #{rid} 已取消")


def _schedule_reminder(bot, rid, chat_type, chat_id, user_id, run_at, cron, text):
    if bot.scheduler is None:
        return
    try:
        if run_at:
            bot.scheduler.add_job(
                _fire_reminder, "date", run_date=datetime.fromtimestamp(run_at),
                args=[bot, rid, chat_type, chat_id, user_id, text], id=f"reminder_{rid}",
                replace_existing=True,
            )
        elif cron:
            parts = cron.split()
            hh, mm = parts[1].split(":")
            kw = dict(hour=int(hh), minute=int(mm))
            if parts[0] == "weekly":
                kw["day_of_week"] = int(parts[2])
            bot.scheduler.add_job(
                _fire_reminder_loop, "cron",
                args=[bot, rid, chat_type, chat_id, user_id, text, cron],
                id=f"reminder_{rid}", replace_existing=True, **kw,
            )
    except Exception:
        log.exception("注册提醒任务失败 #%s", rid)


async def _fire_reminder(bot, rid, chat_type, chat_id, user_id, text):
    bot.db.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
    segs = [segments.text(f"⏰ 到点提醒：{text}")]
    if chat_type == "group":
        segs.insert(0, segments.at(user_id))
    try:
        await bot.send_to(chat_type, chat_id, segs)
    except Exception:
        log.exception("提醒发送失败 #%s", rid)


async def _fire_reminder_loop(bot, rid, chat_type, chat_id, user_id, text, cron):
    segs = [segments.text(f"⏰ 循环提醒：{text}")]
    if chat_type == "group":
        segs.insert(0, segments.at(user_id))
    try:
        await bot.send_to(chat_type, chat_id, segs)
    except Exception:
        log.exception("循环提醒发送失败 #%s", rid)


def resume_reminders(bot):
    """启动/重连后把未完成提醒重新挂上调度器。"""
    rows = bot.db.query("SELECT * FROM reminders WHERE done=0")
    for r in rows:
        if r["run_at"] and r["run_at"] < time.time():
            continue  # 已过期的一次性提醒不再触发
        _schedule_reminder(
            bot, r["id"], r["chat_type"], r["chat_id"], r["user_id"],
            r["run_at"], r["cron"], r["text"],
        )


# ---------- 待办 ----------

async def _cmd_add_todo(bot, event, content):
    if not content:
        await bot.send_text(event, "格式：添加待办 内容")
        return
    bot.db.execute(
        "INSERT INTO todos (user_id, chat_type, chat_id, content, created_ts) VALUES (?,?,?,?,?)",
        (event.get("user_id"), event.get("message_type"), event.get("group_id") or event.get("user_id"), content, int(time.time())),
    )
    await bot.send_text(event, f"📝 待办已添加：{content}")


async def _cmd_list_todos(bot, event):
    rows = bot.db.query(
        "SELECT * FROM todos WHERE user_id=? AND done=0 ORDER BY created_ts DESC LIMIT 30",
        (event.get("user_id"),),
    )
    if not rows:
        await bot.send_text(event, "没有待办，轻松啦~")
        return
    lines = ["📋 你的待办："] + [f"#{r['id']} {r['content']}" for r in rows]
    await bot.send_text(event, "\n".join(lines))


async def _cmd_done_todo(bot, event, arg):
    if not arg.isdigit():
        await bot.send_text(event, "格式：完成待办 编号")
        return
    cur = bot.db.execute(
        "UPDATE todos SET done=1 WHERE id=? AND user_id=? AND done=0", (int(arg), event.get("user_id"))
    )
    await bot.send_text(event, f"✅ 已完成待办 #{arg}" if cur.rowcount else f"没有找到你的待办 #{arg}")


# ---------- 记账 ----------

async def _cmd_ledger_add(bot, event, arg: str):
    parts = arg.rsplit(maxsplit=1)
    if len(parts) == 2 and re.fullmatch(r"\d+(?:\.\d+)?", parts[1]):
        note, amount = parts[0].strip(), float(parts[1])
    elif re.fullmatch(r"\d+(?:\.\d+)?", arg):
        note, amount = "", float(arg)
    else:
        await bot.send_text(event, "格式：记账 事项 金额（例：记账 午饭 25）")
        return
    bot.db.execute(
        "INSERT INTO ledger (ts, user_id, chat_type, chat_id, category, amount, note) VALUES (?,?,?,?,?,?,?)",
        (int(time.time()), event.get("user_id"), event.get("message_type"),
         event.get("group_id") or event.get("user_id"), "", amount, note),
    )
    await bot.send_text(event, f"💰 已记账：{note or '支出'} {amount:.2f} 元")


async def _cmd_ledger_query(bot, event, scope: str):
    now = datetime.now()
    if scope.startswith("本月") or "月" in scope:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = "本月"
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        label = "今日"
    rows = bot.db.query(
        "SELECT COALESCE(SUM(amount),0) AS total, COUNT(*) AS cnt FROM ledger "
        "WHERE user_id=? AND ts>=?",
        (event.get("user_id"), int(start.timestamp())),
    )
    total, cnt = rows[0]["total"], rows[0]["cnt"]
    recent = bot.db.query(
        "SELECT note, amount FROM ledger WHERE user_id=? AND ts>=? ORDER BY ts DESC LIMIT 5",
        (event.get("user_id"), int(start.timestamp())),
    )
    lines = [f"💰 {label}记账：共 {cnt} 笔，合计 {total:.2f} 元"]
    if recent:
        lines.append("最近：" + "、".join(f"{r['note'] or '支出'}{r['amount']:.0f}" for r in recent))
    await bot.send_text(event, "\n".join(lines))


# ---------- 天气 ----------

# IP定位源：百度qifu(https免key) -> ip-api(http免key)
# 注意：open-meteo地理编码认"北京"不认"北京市/西城区"，解析时必须清洗后缀
def _clean_city(name: str) -> str:
    return re.sub(r"(市|省|特别行政区|自治区)$", "", (name or "").strip())


def _parse_ipapi(d: dict) -> str:
    city = (d.get("city") or "").strip()
    region = (d.get("regionName") or "").strip()
    # 直辖市的city是区名（如 西城区），用省级名；普通城市优先市名
    pick = region if (not city or city.endswith("区")) else city
    return _clean_city(pick)


IP_SOURCES = [
    ("https://qifu-api.baidubce.com/ip/local/geo/v1/district",
     lambda d: _clean_city((d.get("data") or {}).get("city") or "")),
    ("http://ip-api.com/json/?lang=zh-CN&fields=city,regionName",
     _parse_ipapi),
]


def _city_key(user_id) -> str:
    return f"city:{user_id}"


async def _ip_city(bot) -> str:
    """按机器人所在网络的IP定位城市，结果缓存24小时。"""
    cached = bot.db.kv_get("ip_city_cache")
    if cached and time.time() - int(cached.get("ts", 0)) < 86400 and cached.get("city"):
        return cached["city"]
    for url, parse in IP_SOURCES:
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                r = await client.get(url)
            city = (parse(r.json()) or "").strip()
            if city:
                bot.db.kv_set("ip_city_cache", {"city": city, "ts": int(time.time())})
                return city
        except Exception as e:
            log.debug("IP定位失败 %s: %s", url, e)
    return ""


async def _resolve_city(bot, event: dict, arg: str):
    """城市解析：指定 > 用户常驻城市 > IP定位。返回 (city, how)。"""
    if arg:
        return arg, ""
    saved = bot.db.kv_get(_city_key(event.get("user_id")))
    if saved:
        return saved, f"（按你设置的常驻城市）"
    ip_city = await _ip_city(bot)
    if ip_city:
        return ip_city, "（按网络自动定位，不准可发 设置城市 城市名）"
    return "", ""


async def _weather_summary(cfg, city: str, data_text: str) -> str:
    """AI 一句话总结：重点给穿衣/带伞建议。失败返回空串。"""
    messages = [
        {"role": "system", "content": (
            "根据天气数据用中文口语总结，两句话以内：一句说天气感受，一句给实用建议"
            "（穿衣厚薄/带伞/防晒等）。不要markdown、不要重复原始数字罗列、60字内。"
        )},
        {"role": "user", "content": f"城市：{city}\n数据：\n{data_text}"},
    ]
    try:
        return await asyncio.to_thread(chat_once_sync, cfg, messages, 300, 0.7)
    except Exception as e:
        log.warning("天气AI总结失败: %s", e)
        return ""


async def _cmd_weather(bot, event, city_arg: str):
    city, how = await _resolve_city(bot, event, city_arg)
    if not city:
        await bot.send_text(event, "不知道你在哪个城市~ 发「设置城市 城市名」设置一下，以后直接发「天气」就行")
        return
    try:
        data_text = await _fetch_weather(city)
    except Exception as e:
        log.warning("天气查询失败: %s", e)
        await bot.send_text(event, f"天气查询失败（{city}）：{e.__class__.__name__}")
        return
    summary = await _weather_summary(bot.cfg, city, data_text)
    parts = [data_text]
    if summary:
        parts.append("💬 " + summary)
    if how:
        parts.append(f"📍 {city} {how}")
    await bot.send_text(event, "\n\n".join(parts))


async def _cmd_set_city(bot, event, arg: str):
    uid = event.get("user_id")
    if not arg:
        cur = bot.db.kv_get(_city_key(uid)) or "还没设置"
        await bot.send_text(event, f"格式：设置城市 城市名\n你当前的常驻城市：{cur}")
        return
    # 用真实查询校验城市名，防止存入错别字
    try:
        await _fetch_weather(arg)
    except Exception:
        await bot.send_text(event, f"查不到「{arg}」这个城市，换个写法试试（如：深圳、杭州、成都市）")
        return
    bot.db.kv_set(_city_key(uid), arg)
    await bot.send_text(event, f"✅ 常驻城市已设为「{arg}」，以后直接发「天气」就行")


async def _fetch_weather(city: str) -> str:
    city = _clean_city(city)
    async with httpx.AsyncClient(timeout=10) as client:
        geo = await client.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
        )
        results = (geo.json().get("results") or [])
        if not results:
            raise ValueError(f"找不到城市「{city}」")
        g = results[0]
        w = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": g["latitude"], "longitude": g["longitude"],
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m",
                "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
                "timezone": "auto", "forecast_days": 1,
            },
        )
    d = w.json()
    cur, daily = d["current"], d["daily"]
    code_desc = WMO_CODES.get(int(cur["weather_code"]), "未知")
    today_code = WMO_CODES.get(int(daily["weather_code"][0]), "未知")
    pop = daily.get("precipitation_probability_max", [None])[0]
    pop_txt = f"，降水概率 {pop}%" if pop is not None else ""
    return (
        f"🌤 {g['name']}天气\n"
        f"现在：{code_desc} {cur['temperature_2m']}°C（体感 {cur['apparent_temperature']}°C）\n"
        f"今日：{today_code} {daily['temperature_2m_min'][0]}~{daily['temperature_2m_max'][0]}°C{pop_txt}\n"
        f"湿度 {cur['relative_humidity_2m']}%，风速 {cur['wind_speed_10m']} km/h"
    )


# ---------- AI 工具 ----------

@register_tool(
    "get_weather",
    "查询某个城市的实时天气与今日预报。用户问天气/温度/下不下雨/穿什么时调用。location留空=用户常驻城市或自动定位。",
    {
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "城市名，如 北京/深圳；留空则自动确定"},
        },
    },
)
async def _tool_get_weather(bot, args, ctx):
    event = ctx.get("event") or {}
    city, _ = await _resolve_city(bot, event, (args.get("location") or "").strip())
    if not city:
        return "无法确定城市：让用户发「设置城市 城市名」设置常驻城市，或在问题里带上城市名。"
    try:
        data = await _fetch_weather(city)
    except Exception as e:
        return f"天气查询失败（{city}）：{e.__class__.__name__}，请基于已有知识谨慎回答或告知查询失败。"
    return f"城市：{city}\n{data}（请基于以上数据回答，可给穿衣/带伞建议）"


# ---------- 每日播报 ----------

async def on_start(bot):
    if bot.scheduler is None:
        return
    # 恢复提醒
    resume_reminders(bot)

    report = bot.cfg.get("plugins.life_assistant.daily_report", {}) or {}
    if not report.get("enabled") or not report.get("targets"):
        return
    hh, mm = str(report.get("time", "08:30")).split(":")[:2]
    bot.scheduler.add_job(
        _daily_report, "cron", hour=int(hh), minute=int(mm),
        args=[bot, report], id="daily_report", replace_existing=True,
    )
    log.info("每日播报已注册：%s -> %s 个目标", report.get("time"), len(report["targets"]))


async def _daily_report(bot, report: dict):
    text = str(report.get("content", "早安！新的一天加油！"))
    # 可选拼天气
    for city in (report.get("with_weather") or []):
        try:
            text += "\n\n" + await _fetch_weather(city)
        except Exception as e:
            log.warning("播报天气失败(%s)：%s", city, e)
    for target in report.get("targets", []):
        try:
            await bot.send_to(target.get("type", "group"), int(target.get("id")), [segments.text(text)])
        except Exception:
            log.exception("播报发送失败：%s", target)
