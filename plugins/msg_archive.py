"""消息存档备份：全量存 SQLite，提供查询/统计/导出。链路第 2 位，永不拦截后续插件。

命令：
    查记录 关键词 [条数]   —— 当前会话内按关键词搜（私聊=搜该好友消息）
    查记录 [条数]          —— 当前会话最新N条（默认10）
    群统计                 —— 今日发言排行（群聊）
    导出记录               —— (管理员) 导出当前群最近2000条为txt并上传到群文件
"""
import csv
import io
import time
from datetime import datetime, timedelta
from pathlib import Path

from core import permission, segments
from core.logger import get

log = get("msg_archive")


async def on_message(bot, event) -> bool:
    # 1) 全量存档（群聊+私聊；群临时会话等也存，字段尽量全）
    try:
        bot.db.insert_message(event, segments.readable_text(event), event.get("raw_message") or "")
    except Exception:
        log.exception("消息存档失败")

    # 2) 查询命令
    text = segments.plain_text(event)
    if text.startswith("查记录"):
        await _cmd_search(bot, event, text)
        return True
    if text in ("群统计", "发言统计") and event.get("message_type") == "group":
        await _cmd_stats(bot, event)
        return True
    if text == "导出记录" and event.get("message_type") == "group":
        if permission.is_admin(bot.cfg, event):
            await _cmd_export(bot, event)
        else:
            await bot.send_text(event, "导出记录仅限管理员使用")
        return True
    return False


async def _cmd_search(bot, event, text: str):
    arg = text[len("查记录"):].strip()
    keyword, limit = "", 10
    parts = arg.split()
    if parts and parts[-1].isdigit():
        limit = max(1, min(int(parts[-1]), 50))
        parts = parts[:-1]
    keyword = " ".join(parts)

    chat_type = event.get("message_type", "group")
    rows = bot.db.search_messages(
        chat_type, event.get("group_id"), event.get("user_id"), keyword, limit
    )
    if not rows:
        await bot.send_text(event, "没有找到匹配的记录")
        return

    title = f"🔎 搜索「{keyword}」" if keyword else "🕐 最新消息"
    lines = [title]
    for r in rows:
        t = datetime.fromtimestamp(r["ts"]).strftime("%m-%d %H:%M")
        name = r["sender_name"] or str(r["user_id"])
        content = r["text"][:60]
        lines.append(f"{t} {name}: {content}")
    await bot.send_text(event, "\n".join(lines))


async def _cmd_stats(bot, event):
    today_start = int(
        datetime.combine(datetime.now().date(), datetime.min.time()).timestamp()
    )
    rows = bot.db.chat_stats("group", event.get("group_id"), today_start)
    if not rows:
        await bot.send_text(event, "今天还没有消息记录")
        return
    total = sum(r["cnt"] for r in rows)
    lines = [f"📊 今日群消息共 {total} 条，排行："]
    for i, r in enumerate(rows, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
        lines.append(f"{medal} {r['sender_name'] or r['user_id']}: {r['cnt']}条")
    await bot.send_text(event, "\n".join(lines))


async def _cmd_export(bot, event):
    rows = bot.db.export_messages("group", event.get("group_id"), 2000)
    if not rows:
        await bot.send_text(event, "该群还没有存档记录")
        return
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["时间", "发送者", "QQ", "内容"])
    for r in rows:
        t = datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S")
        writer.writerow([t, r["sender_name"], r["user_id"], r["text"]])
    # BOM 头保证 Excel 打开不乱码
    data = "\ufeff" + buf.getvalue()

    export_dir = Path("data/exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    fname = f"群{event['group_id']}记录_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    path = export_dir / fname
    path.write_text(data, encoding="utf-8")

    try:
        await bot.upload_group_file(event["group_id"], str(path.resolve()), fname)
        await bot.send_text(event, f"已导出 {len(rows)} 条记录到群文件：{fname}")
    except Exception as e:
        log.exception("上传群文件失败")
        await bot.send_text(event, f"导出成功但上传群文件失败：{e}\n文件在服务器: {path.resolve()}")
