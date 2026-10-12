"""媒体包：链接总结、识图吐槽。

命令：
    总结 https://xxx      抓取网页 -> AI 三句话总结（带来源）
    吐槽                  带图发，或引用一条图片消息 -> OCR取文字 -> AI 毒舌点评
"""
import asyncio
import re

import httpx

from core import segments
from core.ai_completion import chat_once_sync
from core.logger import get

log = get("media")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

FALLBACK_ROASTS = [
    "这张图有功底，我一时半会看不出来哪好，但肯定有它的道理",
    "图是好图，就是有点考验我的想象力",
    "我盯着看了半天，感觉它想表达的东西已经超出了我的理解范围",
]


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


async def fetch_page(url: str) -> dict:
    """尽力抓网页：标题 + og描述 + 正文前段。JS渲染页只能拿元信息。"""
    async with httpx.AsyncClient(timeout=15, follow_redirects=True,
                                 headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"}) as c:
        r = await c.get(url)
    html = r.text
    title_m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    og_m = re.search(r'<meta[^>]+(?:property|name)="(?:og:description|description)"[^>]+content="([^"]*)"', html, re.I)
    if not og_m:
        og_m = re.search(r'<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="(?:og:description|description)"', html, re.I)
    body = _strip_html(html)[:2500]
    return {
        "url": url,
        "status": r.status_code,
        "title": (title_m.group(1).strip() if title_m else ""),
        "desc": (og_m.group(1).strip() if og_m else ""),
        "body": body,
    }


async def summarize_link(bot, url: str) -> str:
    try:
        page = await fetch_page(url)
    except Exception as e:
        return f"抓取失败：{e.__class__.__name__}（链接可能需要登录或是JS渲染页）"
    if page["status"] != 200:
        return f"网页返回状态码 {page['status']}，拿不到内容"
    material = f"标题：{page['title'] or '（无）'}\n描述：{page['desc'] or '（无）'}\n正文节选：{page['body'] or '（无，可能是纯JS渲染页面）'}"
    messages = [
        {"role": "system", "content": (
            "根据网页内容用中文总结：3句话以内说清这页讲什么、关键信息；"
            "如果正文为空只有标题/描述，就基于标题描述总结并注明'仅能获取到页面简介'。"
            "末尾单独一行输出：来源：<标题> <域名>。不要markdown。"
        )},
        {"role": "user", "content": material},
    ]
    try:
        summary = await asyncio.to_thread(chat_once_sync, bot.cfg, messages, 500, 0.4)
    except Exception as e:
        return f"AI总结失败（{e.__class__.__name__}）\n标题：{page['title']}\n简介：{page['desc'][:150]}"
    return summary[:900] or "总结为空，这页可能没抓到正文"


async def roast_image(bot, event) -> str:
    """识图吐槽：OCR文字 -> AI毒舌。纯画面图给趣味兜底。"""
    urls = segments.images(event)
    if not urls:
        # 引用了一条消息：去取那条消息里的图
        reply_id = None
        for s in segments.segs(event):
            if s.get("type") == "reply":
                reply_id = str(s.get("data", {}).get("id", "")) or None
        if not reply_id:
            return "要吐槽请直接带图发「吐槽」，或引用一条图片消息发「吐槽」"
        try:
            msg = await bot.get_msg(reply_id)
            segs = msg.get("message") if isinstance(msg.get("message"), list) else []
            for s in segs:
                if s.get("type") == "image":
                    d = s.get("data", {}) or {}
                    u = d.get("url") or d.get("file") or ""
                    if u:
                        urls.append(u)
        except Exception:
            pass
    if not urls:
        return "那条消息里没有图片，引用一条带图的试试"

    ocr_text = ""
    try:
        result = await bot.call_action("ocr_image", image=urls[0])
        # NapCat 返回 [{"text": "..."}] 或拼好的字符串
        if isinstance(result, list):
            ocr_text = " ".join(str(x.get("text", "")) for x in result if isinstance(x, dict))
        else:
            ocr_text = str(result or "")
        ocr_text = ocr_text.strip()[:400]
    except Exception as e:
        log.info("OCR失败/不支持: %s", e)

    if not ocr_text:
        import random
        return ("👀 这张图我没识别出文字（目前只能读图里的字，还看不懂纯画面）\n"
                f"AI锐评：{random.choice(FALLBACK_ROASTS)}")

    messages = [
        {"role": "system", "content": (
            "你看了一张图，图里识别出的文字如下。用中文对这张图进行友好的毒舌点评："
            "2-3句，幽默但不伤人，可以玩梗；点明图里文字内容在说什么。不要markdown。"
        )},
        {"role": "user", "content": f"图里的文字：\n{ocr_text}"},
    ]
    try:
        roast = await asyncio.to_thread(chat_once_sync, bot.cfg, messages, 400, 0.9)
    except Exception as e:
        return f"吐槽生成失败（{e.__class__.__name__}），图里的字是：{ocr_text[:100]}"
    return roast[:400] or "这张图我词穷了，但气氛到位了"


async def on_message(bot, event) -> bool:
    if not bot.cfg.get("plugins.media.enabled", True):
        return False
    text = segments.plain_text(event)
    if not text:
        return False

    if text.startswith("总结 http") or text.startswith("总结 https"):
        url = text[len("总结 "):].strip().split()[0]
        await bot.send_text(event, "📄 正在读取页面…")
        await bot.send_text(event, await summarize_link(bot, url))
        return True

    if text == "吐槽" or text.startswith("吐槽 "):
        await bot.send_text(event, await roast_image(bot, event), reply_to=True)
        return True

    return False
