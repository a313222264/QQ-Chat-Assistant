"""正向 WebSocket 连接：连接 NapCat、断线自动重连、事件分发、API 调用回包匹配。"""
import asyncio
import json
import uuid

import websockets

from core.logger import get

log = get("connection")


class NapCatConnection:
    def __init__(self, cfg, bot, dispatcher):
        self.cfg = cfg
        self.bot = bot
        self.dispatcher = dispatcher
        self._ws = None
        self._pending: dict[str, asyncio.Future] = {}
        self.connected = asyncio.Event()

    def _ws_url(self) -> str:
        return self.cfg.get("napcat.ws_url", "ws://127.0.0.1:3001")

    def _headers(self) -> dict:
        token = self.cfg.get("napcat.access_token") or ""
        return {"Authorization": f"Bearer {token}"} if token else {}

    async def run(self):
        """主循环：断开后按 3/6/12/30/60 秒退避重连，永远不退出。"""
        backoff = 3
        first = True
        while True:
            try:
                async with websockets.connect(
                    self._ws_url(),
                    additional_headers=self._headers(),
                    max_size=20 * 1024 * 1024,
                    ping_interval=20,
                    ping_timeout=20,
                ) as ws:
                    self._ws = ws
                    self.connected.set()
                    backoff = 3
                    log.info("已连接 NapCat: %s", self._ws_url())
                    # 收包循环必须独立成任务：登录信息、on_start 里的 API 调用
                    # 都要等回包，回包只有收包循环能读，顺序执行会死锁
                    recv_task = asyncio.create_task(self._recv_loop(ws))
                    try:
                        if first:
                            first = False
                            try:
                                info = await self.bot.get_login_info()
                                self.bot.self_id = info.get("user_id")
                                self.bot.nickname = info.get("nickname")
                                log.info(
                                    "机器人账号：%s（%s）", info.get("nickname"), info.get("user_id")
                                )
                            except Exception as e:
                                log.warning("获取登录信息失败（不影响运行）：%s", e)
                        await self.dispatcher.on_start(self.bot)  # 启动/重连后恢复插件状态
                        await recv_task  # 正常运行直到连接关闭
                    finally:
                        if not recv_task.done():
                            recv_task.cancel()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("连接断开：%s，%s 秒后重连…", e.__class__.__name__, backoff)
            finally:
                self.connected.clear()
                self._ws = None
                self._fail_pending("连接断开")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _recv_loop(self, ws):
        async for raw in ws:
            await self._handle_raw(raw)

    # ---------- 收包 ----------

    async def _handle_raw(self, raw: str):
        try:
            data = json.loads(raw)
        except ValueError:
            log.warning("收到非JSON报文：%s", raw[:200])
            return

        echo = data.get("echo")
        if echo and echo in self._pending:
            fut = self._pending.pop(echo)
            if not fut.done():
                fut.set_result(data)
            return

        if "post_type" in data:
            # 事件交给分发器，逐条隔离异常；DEBUG下记录事件便于诊断
            log.debug("收到事件: %s %s", data.get("post_type"),
                      data.get("message_type") or data.get("notice_type") or "")
            asyncio.create_task(self.dispatcher.dispatch(self.bot, data))
        elif data.get("status") == "failed":
            log.warning("API失败报文（无echo匹配）：%s", data.get("message"))

    # ---------- 发API ----------

    async def call_api(self, action: str, params: dict, timeout: float = 30.0):
        if self._ws is None:
            raise RuntimeError("NapCat 未连接")
        echo = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self._pending[echo] = fut
        try:
            await self._ws.send(json.dumps({"action": action, "params": params, "echo": echo}))
            result = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            raise ApiTimeoutError(f"API {action} 超时（{timeout}s）")
        finally:
            self._pending.pop(echo, None)

        if result.get("retcode") not in (0, "0", 1, "1"):
            # retcode=1 是 OneBot 11 的 async 语义，NapCat 同步回包时一般为 0
            wording = result.get("wording") or result.get("message") or "未知错误"
            raise ApiError(f"API {action} 失败: retcode={result.get('retcode')} {wording}")
        return result.get("data")

    def _fail_pending(self, reason: str):
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError(f"API调用失败：{reason}"))
        self._pending.clear()


class ApiTimeoutError(RuntimeError):
    pass
