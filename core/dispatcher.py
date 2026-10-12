"""事件分发器：按顺序调用已启用插件的处理函数，逐个隔离异常。

插件契约（plugins/ 下的模块）：
    async def on_message(bot, event) -> bool   # 返回 True 表示已处理，终止后续插件
    async def on_notice(bot, event) -> None
    async def on_request(bot, event) -> None
    async def on_start(bot) -> None            # 启动/重连后调用（注册定时任务等）

插件开关：config.yaml 的 plugins.<名字>.enabled，或管理员运行时开关（runtime_state）。
"""
import asyncio
import importlib

from core import config as config_mod
from core.logger import get

log = get("dispatcher")

# 链路顺序：admin 的命令最先匹配（命中即停），存档其次（永不拦截），AI 最后
# proactive_chat 只有 on_start（定时触发），digest 以定时任务为主
PLUGIN_MODULES = [
    "admin", "msg_archive", "group_manage", "memes", "game_data",
    "life_assistant", "media", "fun", "voice", "digest", "ai_chat", "proactive_chat",
]


class Dispatcher:
    def __init__(self, cfg, db):
        self.cfg = cfg
        self.db = db
        self.plugins = {}  # name -> {"module": mod, "enabled": bool}
        self._runtime_state = config_mod.load_runtime_state()

    # ---------- 插件管理 ----------

    def load_plugins(self):
        for name in PLUGIN_MODULES:
            try:
                mod = importlib.import_module(f"plugins.{name}")
            except Exception:
                log.exception("插件 %s 加载失败", name)
                continue
            self.plugins[name] = {"module": mod, "enabled": self.is_enabled(name)}
            log.info("插件已加载: %s (%s)", name, "启用" if self.is_enabled(name) else "停用")

    def is_enabled(self, name: str) -> bool:
        if name in self._runtime_state:
            return bool(self._runtime_state[name])
        return bool(self.cfg.get(f"plugins.{name}.enabled", True))

    def set_enabled(self, name: str, enabled: bool) -> bool:
        if name not in self.plugins:
            return False
        self._runtime_state[name] = enabled
        config_mod.save_runtime_state(self._runtime_state)
        self.plugins[name]["enabled"] = enabled
        return True

    def enabled_names(self) -> list:
        return [n for n in PLUGIN_MODULES if n in self.plugins and self.plugins[n]["enabled"]]

    # ---------- 事件入口 ----------

    async def dispatch(self, bot, event: dict):
        post_type = event.get("post_type")
        try:
            if post_type == "message":
                await self._run_chain(bot, event)
            elif post_type == "notice":
                await self._run_hook(bot, event, "on_notice")
            elif post_type == "request":
                await self._run_hook(bot, event, "on_request")
            elif post_type == "meta_event":
                pass  # 心跳/生命周期，忽略
        except Exception:
            log.exception("分发事件时出错: %s", event.get("post_type"))

    async def _run_chain(self, bot, event: dict):
        for name in PLUGIN_MODULES:
            entry = self.plugins.get(name)
            if not entry or not entry["enabled"]:
                continue
            handler = getattr(entry["module"], "on_message", None)
            if handler is None:
                continue
            try:
                handled = await handler(bot, event)
                if handled:
                    return
            except Exception:
                log.exception("插件 %s 处理消息时出错", name)

    async def _run_hook(self, bot, event: dict, hook_name: str):
        for name in PLUGIN_MODULES:
            entry = self.plugins.get(name)
            if not entry or not entry["enabled"]:
                continue
            handler = getattr(entry["module"], hook_name, None)
            if handler is None:
                continue
            try:
                await handler(bot, event)
            except Exception:
                log.exception("插件 %s 的 %s 出错", name, hook_name)

    async def on_start(self, bot):
        for name in PLUGIN_MODULES:
            entry = self.plugins.get(name)
            if not entry or not entry["enabled"]:
                continue
            handler = getattr(entry["module"], "on_start", None)
            if handler is None:
                continue
            try:
                await handler(bot)
            except Exception:
                log.exception("插件 %s 的 on_start 出错", name)
