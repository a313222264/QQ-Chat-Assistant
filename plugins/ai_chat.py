"""AI智能聊天（MiniMax，OpenAI 兼容接口 + 函数调用工具循环）。

触发方式：
    私聊：直接发消息
    群聊：@机器人 + 内容；或引用回复机器人的一条消息继续追问
    任意会话：清空对话 —— 清空当前会话的上下文
人设：管理员用 设置人设 xxx 修改（存数据库，立即生效），默认在 config.yaml。
工具：模型可自主调用 web_search / query_jx3 / send_meme 等注册工具（core/tools.py），
数据类回答强制基于工具结果并注明来源。
防护：单人冷却 / 群每日上限 / 回复长度截断 / API 异常兜底。
"""
import asyncio
import json
import random
import time
from collections import OrderedDict

from core import ai_completion
from core import permission, segments, tools as tools_mod
from core.logger import get

log = get("ai_chat")

MAX_TOOL_ROUNDS = 3

_contexts: OrderedDict = OrderedDict()  # chat_key -> [{"role","content"},...]
_last_call: dict = {}                   # (chat_key, user_id) -> 上次触发时间戳
_group_daily: dict = {}                 # (group_id, date_str) -> 次数
_passive_last: dict = {}                # group_id -> 上次passive触发时间戳
_summaries: dict = {}                   # chat_key -> 对话摘要文本
_pending_sum: dict = {}                 # chat_key -> 待摘要的淘汰消息行
_running_sum: set = set()               # 正在后台摘要的 chat_key

SUMMARY_PROMPT = (
    "你是对话记忆压缩器。把「已有摘要」和「新增对话」合并成一份更新后的摘要。"
    "要求：150字以内；保留关键事实（人名/称呼、提到的事件、约定、正在进行的话题、用户偏好）；"
    "用第三人称白描，不要堆砌对话原文；只输出摘要本身，不要任何解释。"
)


def _maybe_summarize(cfg, chat_key: str):
    """把 pending 的淘汰消息异步合并进摘要（后台执行，不阻塞当前回复）。"""
    if not cfg.get("ai.context_summary.enabled", True):
        _pending_sum.pop(chat_key, None)
        return None
    if not _pending_sum.get(chat_key) or chat_key in _running_sum:
        return None
    _running_sum.add(chat_key)

    async def job():
        try:
            old = _summaries.get(chat_key, "")
            new_msgs = "\n".join(_pending_sum.get(chat_key, []))
            messages = [
                {"role": "system", "content": SUMMARY_PROMPT},
                {"role": "user", "content": f"已有摘要：{old or '（无）'}\n\n新增对话：\n{new_msgs}"},
            ]
            summary = (await asyncio.to_thread(
                ai_completion.chat_once_sync, cfg, messages, 600, 0.3
            ) or "").strip()
            if summary:
                _summaries[chat_key] = summary
                log.info("上下文已摘要 %s（%d字）", chat_key, len(summary))
            _pending_sum[chat_key] = []
        except Exception:
            log.exception("上下文摘要失败 %s（pending保留，下次溢出重试）", chat_key)
        finally:
            _running_sum.discard(chat_key)
            # 摘要期间又积累了新的淘汰消息 → 接着处理
            if _pending_sum.get(chat_key):
                _maybe_summarize(cfg, chat_key)

    return asyncio.create_task(job())


def _name_mentioned(bot, text: str) -> bool:
    """消息文本里叫机器人名字（配置别名或登录昵称），等同@。"""
    names = [str(n) for n in (bot.cfg.get("ai.name_aliases", []) or [])]
    if getattr(bot, "nickname", None):
        names.append(str(bot.nickname))
    t = text.replace(" ", "")
    return any(n and n in t for n in names)


def _passive_triggered(bot, event: dict, text: str) -> bool:
    """普通群消息小概率插嘴：受概率/最短长度/群级冷却三重限制。"""
    p = bot.cfg.get("ai.group_passive", {}) or {}
    if not p.get("enabled", False):
        return False
    if len(text) < int(p.get("min_len", 4)):
        return False
    gap = float(p.get("group_cooldown", 120))
    now = time.time()
    if now - _passive_last.get(event.get("group_id"), 0) < gap:
        return False
    if random.random() >= float(p.get("chance", 0.15)):
        return False
    _passive_last[event.get("group_id")] = now
    return True

GROUNDING_RULES = (
    "你可以调用工具（web_search网页检索 / query_jx3剑网3数据 / send_meme发表情包）来获取实时信息或发送图片。"
    "回答数据类、行情类、版本类问题时，必须先调用工具获取最新信息，只依据工具返回的内容回答，"
    "并注明数据时间和来源链接；工具查不到或失败时明确说查不到，绝不编造数据。"
    "聊天时像真人群友一样用表情包：当氛围搞笑、吐槽、无语、震惊、难过，或值得斗图回应时，"
    "主动调用 send_meme 发一张贴合情绪的（keyword按情绪挑，图库里有 开心/酸了/委屈/打工人/急了/警告/比心/爱你/偷看/巴掌/帅哥 等，不确定就留空随机）。"
    "不用每句都发，觉得氛围到了就发。"
)


def _chat_key(event) -> str:
    if event.get("message_type") == "group":
        return f"g:{event['group_id']}"
    return f"p:{event['user_id']}"


def _persona(bot) -> str:
    base = bot.db.kv_get("ai_persona") or bot.cfg.get(
        "ai.system_prompt", "你是一个友好的聊天助手，用简洁的中文回答。"
    )
    if bot.cfg.get("ai.tools_enabled", True) and tools_mod.TOOLS:
        return base + "\n" + GROUNDING_RULES
    return base


async def _chat_with_tools(cfg, messages: list, bot=None, ctx: dict = None) -> str:
    """带工具循环的对话：模型自主决定调用工具，最多 MAX_TOOL_ROUNDS 轮。"""
    client = ai_completion.get_client(cfg)
    schemas = tools_mod.openai_schemas() if (bot is not None and cfg.get("ai.tools_enabled", True)) else None

    for round_i in range(MAX_TOOL_ROUNDS + 1):
        kwargs = {
            "model": ai_completion.model_name(cfg),
            "messages": messages,
            "max_tokens": int(cfg.get("ai.max_tokens", 2000)),
            "temperature": float(cfg.get("ai.temperature", 0.8)),
        }
        use_tools = schemas if (schemas and round_i < MAX_TOOL_ROUNDS) else None
        if use_tools:
            kwargs["tools"] = use_tools
        resp = await asyncio.to_thread(client.chat.completions.create, **kwargs)
        msg = resp.choices[0].message
        content = ai_completion.strip_think(msg.content or "")

        if not (use_tools and getattr(msg, "tool_calls", None)):
            return content

        # 记录 assistant 的工具调用请求
        messages.append({
            "role": "assistant",
            "content": content or None,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments or "{}"},
                }
                for tc in msg.tool_calls
            ],
        })
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except ValueError:
                args = {}
            log.info("AI调用工具 %s(%s)", tc.function.name, args)
            result = await tools_mod.execute_tool(tc.function.name, args, bot, ctx or {})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return await asyncio.to_thread(ai_completion.chat_once_sync, cfg, messages)


def _trim_and_queue(cfg, bot, chat_key: str, ctx_hist: list):
    """上下文裁剪到窗口大小；淘汰消息进入摘要队列（而非丢弃）。"""
    max_ctx = int(cfg.get("ai.max_context", 12))
    if len(ctx_hist) <= max_ctx:
        return
    evicted = ctx_hist[:-max_ctx]
    del ctx_hist[:-max_ctx]
    if not cfg.get("ai.context_summary.enabled", True):
        return
    pend = _pending_sum.setdefault(chat_key, [])
    bot_name = getattr(bot, "nickname", None) or "机器人"
    for m in evicted:
        line = m.get("content", "")
        if m.get("role") == "assistant":
            line = f"{bot_name}：{line}"
        pend.append(line)
    del pend[:-60]  # 摘要失败重试的兜底上限
    _maybe_summarize(cfg, chat_key)


async def on_message(bot, event) -> bool:
    cfg = bot.cfg
    if not cfg.get("plugins.ai_chat.enabled", True):
        return False
    if not permission.chat_allowed(cfg, event):
        return False

    is_group = event.get("message_type") == "group"
    self_id = str(bot.self_id or "")

    # 清空对话是低风险命令，无需@也响应
    if segments.plain_text(event) == "清空对话":
        key = _chat_key(event)
        _contexts.pop(key, None)
        _summaries.pop(key, None)
        _pending_sum.pop(key, None)
        await bot.send_text(event, "🧹 已清空当前会话的对话记忆（含摘要）")
        return True

    text = segments.plain_text(event)

    # ---- 触发条件：direct(@/引用/名字提及) / passive(小概率插嘴) ----
    trigger_mode = None
    if not is_group:
        trigger_mode = "direct"
    else:
        replied_uid = segments.replied_user_id(event)
        if segments.is_at_bot(event, self_id) or replied_uid == self_id:
            trigger_mode = "direct"
        elif text and _name_mentioned(bot, text):
            trigger_mode = "direct"  # 消息里叫它名字，等同@
        elif text and _passive_triggered(bot, event, text):
            trigger_mode = "passive"  # 普通消息小概率插嘴
    if trigger_mode is None:
        return False

    if not text:
        return False  # 纯@无内容：忽略

    # ---- 防护 ----
    chat_key = _chat_key(event)
    now = time.time()
    cooldown = float(cfg.get("ai.per_user_cooldown", 5))
    last = _last_call.get((chat_key, event.get("user_id")), 0)
    if now - last < cooldown:
        return True  # 冷却中：静默忽略
    _last_call[(chat_key, event.get("user_id"))] = now

    if is_group:
        limit = int(cfg.get("ai.group_daily_limit", 200))
        today = time.strftime("%Y-%m-%d")
        used = _group_daily.get((event["group_id"], today), 0)
        if used >= limit:
            log.warning("群 %s 今日AI回复已达上限 %s", event["group_id"], limit)
            return True
        _group_daily[(event["group_id"], today)] = used + 1

    # ---- 组装上下文 ----
    ctx_hist = _contexts.setdefault(chat_key, [])
    _contexts.move_to_end(chat_key)
    while len(_contexts) > 200:
        _contexts.popitem(last=False)

    speaker = ""
    if is_group:
        s = event.get("sender") or {}
        speaker = s.get("card") or s.get("nickname") or str(event.get("user_id"))
    n_images = len(segments.images(event))
    content = text if not speaker else f"{speaker}：{text}"
    if n_images:
        content += f"\n（发送了{n_images}张图片）"

    ctx_hist.append({"role": "user", "content": content})
    _trim_and_queue(cfg, bot, chat_key, ctx_hist)

    # ---- 调用 MiniMax（含工具循环）----
    api_key = cfg.get("ai.api_key", "") or ""
    if not api_key:
        ctx_hist.pop()
        log.warning("AI未配置 api_key，跳过回复（config.yaml -> ai.api_key）")
        if not is_group:
            await bot.send_text(event, "AI功能还没有配置 API key，请联系管理员在 config.yaml 填写。")
        return True

    system_prompt = _persona(bot)
    if trigger_mode == "passive":
        # 插嘴模式：给AI留出不说话的退路
        system_prompt += (
            "\n（你这次是被随机抽中在群里插话，不是被点名。"
            "如果这条消息不值得回应、插话会突兀，就只输出 [SKIP] 不说话；"
            "要说话就自然接话，通常别超过40字。）"
        )

    loop_msgs = [{"role": "system", "content": system_prompt}]
    summary = _summaries.get(chat_key)
    if summary:
        loop_msgs.append({"role": "system", "content": f"【之前对话的摘要】{summary}"})
    loop_msgs += ctx_hist
    try:
        reply = await _chat_with_tools(cfg, loop_msgs, bot, {"event": event})
    except Exception as e:
        ctx_hist.pop()
        log.exception("LLM调用失败")
        if not is_group:
            await bot.send_text(event, f"AI暂时开小差了（{e.__class__.__name__}），稍后再试试~")
        return True

    if not reply or "[SKIP]" in reply:
        ctx_hist.pop()  # 不说话：这条消息不进记忆
        return True

    max_len = int(cfg.get("ai.max_reply_len", 800))
    if len(reply) > max_len:
        reply = reply[:max_len] + "…"

    ctx_hist.append({"role": "assistant", "content": reply})
    _trim_and_queue(cfg, bot, chat_key, ctx_hist)

    if is_group and trigger_mode == "passive":
        # 插嘴不带@不引用，像普通群员随口接话
        await bot.send_text(event, reply)
    elif is_group:
        await bot.send_text(event, reply, reply_to=True, at_user=event.get("user_id"))
    else:
        await bot.send_text(event, reply)
    return True
