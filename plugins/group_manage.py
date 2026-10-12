"""群管理：入群欢迎、退群提示、关键词自动回复、戳一戳互动。

关键词存放在数据库 KV（管理员可用命令增删，立即生效）：
    添加关键词 触发词=回复内容
    删除关键词 触发词
    关键词列表
欢迎/退群文案在 config.yaml 的 plugins.group_manage 里配置。
"""
import time

from core import permission, segments
from core.logger import get

log = get("group_manage")


def _load_keywords(bot) -> list:
    kws = bot.db.kv_get("keywords", None)
    if kws is None:
        kws = [
            {"match": k["match"], "reply": k["reply"]}
            for k in (bot.cfg.get("plugins.group_manage.keywords", []) or [])
            if k.get("match") and k.get("reply")
        ]
        bot.db.kv_set("keywords", kws)
    return kws


async def on_message(bot, event) -> bool:
    if event.get("message_type") != "group":
        return False
    if not permission.chat_allowed(bot.cfg, event):
        return False

    text = segments.plain_text(event)

    # 关键词管理命令（管理员）
    if permission.is_admin(bot.cfg, event):
        if text.startswith("添加关键词 "):
            arg = text[len("添加关键词 "):].strip()
            if "=" in arg:
                match, reply = arg.split("=", 1)
                kws = _load_keywords(bot)
                kws = [k for k in kws if k["match"] != match.strip()]
                kws.append({"match": match.strip(), "reply": reply.strip()})
                bot.db.kv_set("keywords", kws)
                await bot.send_text(event, f"✅ 关键词「{match.strip()}」已添加", reply_to=True)
            else:
                await bot.send_text(event, "格式：添加关键词 触发词=回复内容")
            return True
        if text.startswith("删除关键词 "):
            match = text[len("删除关键词 "):].strip()
            kws = _load_keywords(bot)
            new_kws = [k for k in kws if k["match"] != match]
            if len(new_kws) != len(kws):
                bot.db.kv_set("keywords", new_kws)
                await bot.send_text(event, f"✅ 关键词「{match}」已删除")
            else:
                await bot.send_text(event, f"没有「{match}」这个关键词")
            return True
        if text == "关键词列表":
            kws = _load_keywords(bot)
            if kws:
                lines = ["🔑 关键词列表："] + [f"· {k['match']} → {k['reply'][:30]}" for k in kws]
            else:
                lines = ["还没有关键词，用 添加关键词 触发词=回复内容 添加"]
            await bot.send_text(event, "\n".join(lines))
            return True

    # 关键词命中 → 自动回复
    if text:
        lower = text.lower()
        for k in _load_keywords(bot):
            if k.get("match") and k["match"].lower() in lower:
                await bot.send_text(
                    event, k["reply"], reply_to=True, at_user=event.get("user_id")
                )
                return True
    return False


async def on_notice(bot, event):
    notice_type = event.get("notice_type")

    if notice_type == "group_increase":
        if not permission.chat_allowed(bot.cfg, event):
            return
        template = bot.cfg.get(
            "plugins.group_manage.welcome", "欢迎 {name} 加入本群！🎉 请先看群公告，多多交流~"
        )
        user_id = event.get("user_id")
        name = f"QQ {user_id}"
        try:
            info = await bot.get_group_member_info(event["group_id"], user_id)
            name = info.get("card") or info.get("nickname") or name
        except Exception:
            pass
        msg = template.replace("{name}", name).replace("{at}", "")
        await bot.send_group_msg(
            event["group_id"], [segments.at(user_id), segments.text(" " + msg)]
        )

    elif notice_type == "group_decrease":
        if not permission.chat_allowed(bot.cfg, event):
            return
        template = bot.cfg.get("plugins.group_manage.farewell", "{name} 离开了本群，一路顺风~")
        msg = template.replace("{name}", str(event.get("user_id", "")))
        await bot.send_group_msg(event["group_id"], [segments.text(msg)])

    elif notice_type == "notify" and event.get("sub_type") == "poke":
        # 有人戳机器人 → 戳回去（仅限白名单会话）
        target_id = event.get("target_id")
        if str(target_id) != str(bot.self_id):
            return
        if not permission.chat_allowed(bot.cfg, event):
            return
        try:
            if event.get("group_id"):
                await bot.group_poke(event["group_id"], event.get("user_id"))
            else:
                await bot.friend_poke(event.get("user_id"))
        except Exception as e:
            log.warning("戳回去失败：%s", e)
