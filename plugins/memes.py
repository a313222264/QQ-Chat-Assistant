"""表情包插件：本地图库（主）+ QQ收藏表情（补充）。

本地图库：data/memes/ 下的图片，文件名（不含扩展名）即关键词，支持子文件夹分类。
    表情包            —— 随机发一张
    表情包 关键词      —— 按文件名模糊匹配
    表情包列表         —— 列出可用关键词（最多30个）
    收藏表情          —— 发一张机器人小号收藏的QQ表情（需NapCat支持，尽力而为）
    刷新表情包         —— (管理员) 重建本地图库索引

AI 工具：send_meme(keyword) —— ai_chat 的工具循环里调用，按语境自主发表情包。
"""
import random
from pathlib import Path

from core import segments
from core.logger import get
from core.tools import register_tool

log = get("memes")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MEME_TYPES = ("表情包", "发表情包", "来张表情包")


def _meme_dir(cfg) -> Path:
    d = Path(cfg.get("plugins.memes.dir", "data/memes"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def build_index(cfg) -> list:
    """扫描本地图库 -> [{keyword, path}]，每次调用即重建（图库小，开销可忽略）。"""
    root = _meme_dir(cfg)
    out = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            out.append({"keyword": p.stem, "path": p})
    return out


def find_memes(cfg, keyword: str) -> list:
    """按关键词模糊匹配（文件名包含即算命中）。"""
    index = build_index(cfg)
    if not keyword:
        return index
    kw = keyword.strip().lower()
    return [m for m in index if kw in m["keyword"].lower()]


async def send_meme_file(bot, event: dict, path: Path, reply: bool = False):
    segs = []
    if reply:
        segs.append(segments.reply(event.get("message_id")))
    segs.append(segments.image(str(path.resolve())))
    return await bot.send_segments(event, segs)


# ---------------- 消息命令 ----------------

async def on_message(bot, event) -> bool:
    if not bot.cfg.get("plugins.memes.enabled", True):
        return False
    text = segments.plain_text(event)
    if not text:
        return False

    for prefix in MEME_TYPES:
        if text == prefix:
            memes = build_index(bot.cfg)
            if not memes:
                await bot.send_text(event, "图库还是空的，往 data/memes 文件夹放些图片（文件名当关键词）吧~")
                return True
            await send_meme_file(bot, event, random.choice(memes)["path"])
            return True
        if text.startswith(prefix + " "):
            kw = text[len(prefix) + 1:].strip()
            memes = find_memes(bot.cfg, kw)
            if not memes:
                await bot.send_text(event, f"没有匹配「{kw}」的表情包，试试 表情包列表")
                return True
            await send_meme_file(bot, event, random.choice(memes)["path"])
            return True

    if text == "表情包列表":
        memes = build_index(bot.cfg)
        if not memes:
            await bot.send_text(event, "图库是空的，把图片放进 data/memes 文件夹即可")
        else:
            kws = [m["keyword"] for m in memes[:30]]
            await bot.send_text(event, f"🎭 共{len(memes)}张：\n" + "、".join(kws))
        return True

    if text == "刷新表情包":
        n = len(build_index(bot.cfg))
        await bot.send_text(event, f"✅ 已重建表情包索引，当前 {n} 张")
        return True

    if text == "收藏表情":
        await _send_collected_face(bot, event)
        return True

    return False


async def _send_collected_face(bot, event):
    """发小号收藏的QQ表情（NapCat fetch_custom_face，尽力而为）。"""
    try:
        faces = await bot.call_action("fetch_custom_face", count=10)
        items = faces if isinstance(faces, list) else []
        if not items:
            await bot.send_text(event, "小号的收藏表情列表是空的")
            return
        pick = random.choice(items)
        file_id = pick.get("emoji_id") or pick.get("file_id") or pick.get("id") if isinstance(pick, dict) else pick
        await bot.send_segments(event, [segments.image(str(file_id))])
    except Exception as e:
        log.warning("获取收藏表情失败: %s", e)
        await bot.send_text(event, f"读取收藏表情失败（{e.__class__.__name__}），NapCat 可能不支持此接口")


# ---------------- AI 工具 ----------------

@register_tool(
    "send_meme",
    "发送一张表情包图片。当聊天氛围适合斗图、用户要求发表情包、或想活跃气氛时使用。",
    {
        "type": "object",
        "properties": {
            "keyword": {
                "type": "string",
                "description": "表情包关键词（匹配图片文件名），留空则随机发一张",
            }
        },
    },
)
async def _tool_send_meme(bot, args, ctx):
    event = ctx.get("event") or {}
    memes = find_memes(bot.cfg, args.get("keyword", ""))
    if not memes:
        n = len(build_index(bot.cfg))
        return f"没有匹配「{args.get('keyword','')}」的表情包。" + (
            f"图库共{n}张，可用部分关键词：{'、'.join(m['keyword'] for m in build_index(bot.cfg)[:15])}" if n else "图库是空的（data/memes 文件夹没有图片）"
        )
    pick = random.choice(memes)
    await send_meme_file(bot, event, pick["path"])
    return f"已发送表情包「{pick['keyword']}」"
