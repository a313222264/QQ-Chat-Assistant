"""管理员命令与帮助。链路第 1 位：命中命令即终止，避免被 AI 等后续插件响应。

命令一览（<必填> [可选]）：
    所有人：帮助
    超级用户：状态 / 开启插件 x / 关闭插件 x / 插件列表 / 广播 群号 文本 / 重载配置 / 设置人设 x
    群内管理员（含超级用户）：禁言 @xx 分钟数 / 踢人 @xx / 全员禁言 开|关 / 精华 / 公告 文本 / 撤回
"""
import asyncio
import time

from core import permission
from core.logger import get

log = get("admin")

HELP_TEXT = """📖 命令帮助
【AI聊天】私聊直接说；群里@我/叫我名字；引用我的消息可直接追问
【游戏趣味】签到 / 运势 [@某人] / 积分排行 / 石头·剪刀·布 / 猜数字 / 成语接龙 / 出题·答案是X
【消息存档】查记录 关键词 [条数] / 群统计 / 导出记录 / 日报 / 周报
【订阅推送】订阅 关键词 / 退订 关键词 / 我的订阅
【提醒】提醒我 30分钟后 喝水 / 提醒我 明天9点 开会 / 提醒我 每天8:30 打卡 / 查看提醒 / 取消提醒 编号
【待办】添加待办 内容 / 看待办 / 完成待办 编号
【记账】记账 事项 金额 / 查账 今日|本月
【生活】天气 [城市]（不带=自动定位+AI总结） / 设置城市 城市名
【游戏数据】剑网3 活动/开服/公告/金价 [区服] / 三角洲 关键词
【媒体】总结 网页链接 / 吐槽（带图或引用图片）
【语音】说 一句话（TTS点播）
【表情包】表情包 [关键词] / 表情包列表 / 刷新表情包 / 收藏表情
【群管理(管理员)】禁言 @某人 分钟 / 踢人 @某人 / 全员禁言 开|关 / 设精华(引用消息) / 公告 内容 / 撤回(引用消息)
【管理(超级用户)】状态 / 插件列表 / 开启插件 x / 关闭插件 x / 设置人设 内容 / 广播 群号 内容 / 重载配置 / 清空对话"""

STATUS_TEXT = """📊 机器人状态
账号: {self_id}
连接: {conn}
已运行: {uptime}
消息存档: {msg_count} 条
插件: {plugins}"""


def _plain(event):
    from core import segments
    return segments.plain_text(event)


async def on_message(bot, event) -> bool:
    text = _plain(event)
    if not text:
        return False

    # ---- 所有人 ----
    if text in ("帮助", "菜单", "help", "指令"):
        await bot.send_text(event, HELP_TEXT)
        return True

    # ---- 超级用户命令 ----
    if permission.is_superuser(bot.cfg, event.get("user_id")):
        if await _handle_superuser(bot, event, text):
            return True

    # ---- 群管理员命令 ----
    if event.get("message_type") == "group" and permission.is_admin(bot.cfg, event):
        if await _handle_group_admin(bot, event, text):
            return True

    return False


async def _handle_superuser(bot, event, text) -> bool:
    if text == "状态":
        uptime = "未知"
        if bot.started_at:
            secs = int(time.time() - bot.started_at)
            uptime = f"{secs // 3600}小时{(secs % 3600) // 60}分钟"
        await bot.send_text(
            event,
            STATUS_TEXT.format(
                self_id=bot.self_id or "未知",
                conn="已连接" if bot.conn and bot.conn.connected.is_set() else "未连接",
                uptime=uptime,
                msg_count=bot.db.message_count(),
                plugins=", ".join(bot.dispatcher.enabled_names()),
            ),
        )
        return True

    if text == "插件列表":
        lines = []
        for name, entry in bot.dispatcher.plugins.items():
            lines.append(f"{'✅' if entry['enabled'] else '⛔'} {name}")
        await bot.send_text(event, "🔌 插件列表\n" + "\n".join(lines))
        return True

    if text.startswith("开启插件 "):
        name = text[len("开启插件 "):].strip()
        ok = bot.dispatcher.set_enabled(name, True)
        await bot.send_text(event, f"插件 {name} 已开启" if ok else f"没有叫 {name} 的插件")
        return True

    if text.startswith("关闭插件 "):
        name = text[len("关闭插件 "):].strip()
        if name == "admin":
            await bot.send_text(event, "admin 插件不允许关闭")
            return True
        ok = bot.dispatcher.set_enabled(name, False)
        await bot.send_text(event, f"插件 {name} 已关闭" if ok else f"没有叫 {name} 的插件")
        return True

    if text.startswith("广播 "):
        rest = text[len("广播 "):].strip()
        parts = rest.split(maxsplit=1)
        if len(parts) == 2 and parts[0].isdigit():
            group_id = int(parts[0])
            await bot.send_group_msg(group_id, [{"type": "text", "data": {"text": parts[1]}}])
            await bot.send_text(event, f"已广播到群 {group_id}")
        else:
            await bot.send_text(event, "格式：广播 群号 内容")
        return True

    if text == "重载配置":
        ok = bot.cfg.reload()
        await bot.send_text(event, "✅ 配置已重载" if ok else "❌ 配置文件读取失败")
        return True

    if text.startswith("设置人设 "):
        persona = text[len("设置人设 "):].strip()
        bot.db.kv_set("ai_persona", persona)
        await bot.send_text(event, "✅ AI人设已更新")
        return True

    if text == "查看人设":
        persona = bot.db.kv_get("ai_persona") or bot.cfg.get("ai.system_prompt", "")
        await bot.send_text(event, f"当前AI人设：\n{persona}")
        return True

    return False


async def _handle_group_admin(bot, event, text) -> bool:
    group_id = event["group_id"]
    from core import segments

    targets = segments.at_targets(event, exclude_self=bot.self_id)

    if text.startswith("禁言 ") and targets:
        # 禁言 @某人 分钟数
        parts = text.split()
        minutes = 10
        for p in parts:
            if p.isdigit():
                minutes = int(p)
                break
        try:
            if minutes == 0:
                await bot.set_group_ban(group_id, targets[0], 0)
                await bot.send_text(event, f"已解除 {targets[0]} 的禁言", reply_to=True)
            else:
                await bot.set_group_ban(group_id, targets[0], minutes * 60)
                await bot.send_text(event, f"已将 {targets[0]} 禁言 {minutes} 分钟", reply_to=True)
        except Exception as e:
            await bot.send_text(event, f"禁言失败：{e}")
        return True

    if text.startswith("踢人 ") and targets:
        try:
            await bot.set_group_kick(group_id, targets[0])
            await bot.send_text(event, f"已将 {targets[0]} 移出群聊", reply_to=True)
        except Exception as e:
            await bot.send_text(event, f"踢人失败：{e}")
        return True

    if text.startswith("全员禁言 "):
        arg = text[len("全员禁言 "):].strip()
        enable = arg in ("开", "开", "开启", "on", "1")
        await bot.set_group_whole_ban(group_id, enable)
        await bot.send_text(event, "已开启全员禁言" if enable else "已解除全员禁言")
        return True

    if text in ("设精华", "设置精华"):
        reply_id = segments.replied_message_id(event)
        if not reply_id:
            await bot.send_text(event, "请引用要设为精华的消息后发送 设精华")
            return True
        try:
            await bot.set_essence_msg(reply_id)
            await bot.send_text(event, "已加入精华消息", reply_to=True)
        except Exception as e:
            await bot.send_text(event, f"设置精华失败：{e}")
        return True

    if text.startswith("公告 "):
        content = text[len("公告 "):].strip()
        try:
            await bot.send_group_notice(group_id, content)
            await bot.send_text(event, "群公告已发布")
        except Exception as e:
            await bot.send_text(event, f"发布公告失败：{e}")
        return True

    if text == "撤回":
        reply_id = segments.replied_message_id(event)
        if not reply_id:
            await bot.send_text(event, "请引用要撤回的消息后发送 撤回")
            return True
        try:
            await bot.delete_msg(reply_id)
        except Exception as e:
            await bot.send_text(event, f"撤回失败：{e}")
        return True

    return False
