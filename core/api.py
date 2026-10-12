"""OneBot 11 API 封装（Bot 对象）。

所有与 NapCat 的交互都通过 bot.call_action(action, **params)，
常用 API 在此封装成方法，插件直接调用。
"""
import asyncio
import uuid

from core import segments as seg


class ApiError(Exception):
    """NapCat 返回 status=failed 时抛出。"""


class Bot:
    def __init__(self, cfg, db, dispatcher=None):
        self.cfg = cfg
        self.db = db
        self.dispatcher = dispatcher
        self.conn = None          # NapCatConnection，main.py 里赋值
        self.scheduler = None     # APScheduler，main.py 里赋值
        self.started_at = None
        self.self_id = None       # 登录的QQ号，连接后填充

    # ---------- 底层 ----------

    async def call_action(self, action: str, timeout: float = 30.0, **params):
        """调用 OneBot API，返回 data 字段。"""
        if self.conn is None:
            raise ApiError("连接未初始化")
        return await self.conn.call_api(action, params, timeout)

    # ---------- 发消息 ----------

    async def send_private_msg(self, user_id, message) -> dict:
        return await self.call_action("send_private_msg", user_id=int(user_id), message=message)

    async def send_group_msg(self, group_id, message) -> dict:
        return await self.call_action("send_group_msg", group_id=int(group_id), message=message)

    async def send_text(self, event: dict, text: str, reply_to: bool = False, at_user=None) -> dict:
        """按事件来源（群/私聊）回复文本。reply_to=True 时引用原消息，群聊附带 @发送者。"""
        segs = []
        if reply_to:
            segs.append(seg.reply(event.get("message_id")))
        if at_user is not None and event.get("message_type") == "group":
            segs.append(seg.at(at_user))
            segs.append(seg.text(" "))
        segs.append(seg.text(text))
        if event.get("message_type") == "group":
            return await self.send_group_msg(event["group_id"], segs)
        return await self.send_private_msg(event["user_id"], segs)

    async def send_segments(self, event: dict, segs: list) -> dict:
        if event.get("message_type") == "group":
            return await self.send_group_msg(event["group_id"], segs)
        return await self.send_private_msg(event["user_id"], segs)

    async def send_to(self, chat_type: str, chat_id: int, segs) -> dict:
        """主动推送：chat_type = 'group' / 'private'。"""
        if chat_type == "group":
            return await self.send_group_msg(chat_id, segs)
        return await self.send_private_msg(chat_id, segs)

    async def send_group_forward(self, group_id, nodes: list) -> dict:
        """合并转发。nodes: [(sender_name, text), ...]"""
        payload = [
            {
                "type": "node",
                "data": {
                    "uin": str(self.self_id or ""),
                    "name": name,
                    "content": [seg.text(t)],
                },
            }
            for name, t in nodes
        ]
        return await self.call_action("send_group_forward_msg", group_id=int(group_id), messages=payload)

    # ---------- 消息操作 ----------

    async def delete_msg(self, message_id) -> dict:
        return await self.call_action("delete_msg", message_id=int(message_id))

    async def set_msg_emoji_like(self, message_id, emoji_id: str) -> dict:
        return await self.call_action("set_msg_emoji_like", message_id=int(message_id), emoji_id=str(emoji_id))

    # ---------- 群管理 ----------

    async def set_group_ban(self, group_id, user_id, duration: int) -> dict:
        return await self.call_action(
            "set_group_ban", group_id=int(group_id), user_id=int(user_id), duration=int(duration)
        )

    async def set_group_whole_ban(self, group_id, enable: bool) -> dict:
        return await self.call_action("set_group_whole_ban", group_id=int(group_id), enable=bool(enable))

    async def set_group_kick(self, group_id, user_id, reject_add_request: bool = False) -> dict:
        return await self.call_action(
            "set_group_kick", group_id=int(group_id), user_id=int(user_id),
            reject_add_request=bool(reject_add_request),
        )

    async def set_essence_msg(self, message_id) -> dict:
        return await self.call_action("set_essence_msg", message_id=int(message_id))

    async def send_group_notice(self, group_id, content: str) -> dict:
        return await self.call_action("_send_group_notice", group_id=int(group_id), content=content)

    async def set_group_card(self, group_id, user_id, card: str) -> dict:
        return await self.call_action(
            "set_group_card", group_id=int(group_id), user_id=int(user_id), card=card
        )

    async def get_group_member_info(self, group_id, user_id) -> dict:
        return await self.call_action("get_group_member_info", group_id=int(group_id), user_id=int(user_id), no_cache=True)

    async def group_poke(self, group_id, user_id) -> dict:
        return await self.call_action("group_poke", group_id=int(group_id), user_id=int(user_id))

    async def friend_poke(self, user_id) -> dict:
        return await self.call_action("friend_poke", user_id=int(user_id))

    # ---------- 文件 ----------

    async def upload_group_file(self, group_id, file_path: str, name: str) -> dict:
        return await self.call_action(
            "upload_group_file", group_id=int(group_id), file=file_path, name=name
        )

    async def upload_private_file(self, user_id, file_path: str, name: str) -> dict:
        return await self.call_action(
            "upload_private_file", user_id=int(user_id), file=file_path, name=name
        )

    # ---------- 查询 ----------

    async def get_login_info(self) -> dict:
        return await self.call_action("get_login_info")

    async def get_status(self) -> dict:
        """当前账号在线状态（健康巡检用）。"""
        return await self.call_action("get_status")

    async def get_friend_list(self) -> list:
        return await self.call_action("get_friend_list")

    async def get_group_list(self) -> list:
        return await self.call_action("get_group_list")

    async def get_group_member_list(self, group_id) -> list:
        return await self.call_action("get_group_member_list", group_id=int(group_id))

    async def get_image(self, file_name: str) -> dict:
        return await self.call_action("get_image", file=file_name)

    async def get_msg(self, message_id) -> dict:
        return await self.call_action("get_msg", message_id=int(message_id))
