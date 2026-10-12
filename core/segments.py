"""OneBot 11 消息段辅助：构造与解析。

消息段格式：{"type": "text", "data": {"text": "..."}}
"""
from typing import Optional


# ---------- 构造 ----------

def text(t: str) -> dict:
    return {"type": "text", "data": {"text": t}}


def at(qq) -> dict:
    return {"type": "at", "data": {"qq": str(qq)}}


def reply(message_id) -> dict:
    return {"type": "reply", "data": {"id": str(message_id)}}


def image(file_or_url: str) -> dict:
    return {"type": "image", "data": {"file": file_or_url}}


def face(face_id: int) -> dict:
    return {"type": "face", "data": {"id": str(face_id)}}


# ---------- 解析 ----------

def segs(event: dict) -> list:
    """事件里的消息段列表（NapCat 统一给数组；个别情况给字符串则报文原样）。"""
    m = event.get("message")
    if isinstance(m, list):
        return m
    return []


def plain_text(event: dict) -> str:
    """只取 text 段拼接（命令解析用，不含 @/图片等）。"""
    parts = []
    for s in segs(event):
        if s.get("type") == "text":
            parts.append(s.get("data", {}).get("text", ""))
    return "".join(parts).strip()


def readable_text(event: dict) -> str:
    """人类可读的完整消息文本，用于存档与展示：@→@某人，图片→[图片] 等。"""
    parts = []
    for s in segs(event):
        t = s.get("type")
        d = s.get("data", {}) or {}
        if t == "text":
            parts.append(d.get("text", ""))
        elif t == "at":
            parts.append(f"@{d.get('qq')}")
        elif t == "image":
            parts.append("[图片]")
        elif t == "face":
            parts.append(f"[表情{d.get('id', '')}]")
        elif t == "record":
            parts.append("[语音]")
        elif t == "video":
            parts.append("[视频]")
        elif t == "reply":
            parts.append(f"[回复{d.get('id', '')}]")
        elif t == "json":
            parts.append("[卡片]")
        elif t == "forward":
            parts.append("[合并转发]")
        elif t == "file":
            parts.append("[文件]")
    return "".join(parts).strip()


def at_targets(event: dict, exclude_self=None) -> list:
    """消息中 @ 的QQ号列表（可排除机器人自己）。"""
    out = []
    for s in segs(event):
        if s.get("type") == "at":
            qq = str(s.get("data", {}).get("qq", ""))
            if qq and qq != "all" and str(exclude_self) != qq:
                out.append(qq)
    return out


def is_at_bot(event: dict, self_id) -> bool:
    for s in segs(event):
        if s.get("type") == "at" and str(s.get("data", {}).get("qq")) == str(self_id):
            return True
    return False


def replied_message_id(event: dict) -> Optional[str]:
    """如果消息引用回复了某条消息，返回那条消息的 id。"""
    for s in segs(event):
        if s.get("type") == "reply":
            return str(s.get("data", {}).get("id", "")) or None
    return None


def replied_user_id(event: dict):
    """引用回复的对象QQ号（NapCat 会带在 reply 段的 qq 字段）。"""
    for s in segs(event):
        if s.get("type") == "reply":
            return str(s.get("data", {}).get("qq", "")) or None
    return None


def images(event: dict) -> list:
    """消息里的图片（url 或 file 字段）。"""
    out = []
    for s in segs(event):
        if s.get("type") == "image":
            d = s.get("data", {}) or {}
            out.append(d.get("url") or d.get("file") or "")
    return [u for u in out if u]
