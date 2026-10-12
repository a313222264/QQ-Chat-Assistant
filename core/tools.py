"""AI 工具注册表：让模型通过 function calling 自主调用能力（查数据/搜网页/发表情包）。

插件用 @register_tool 注册工具：
    @register_tool("web_search", "搜索网页实时信息", {...json schema...})
    def executor(bot, args, ctx) -> str | Awaitable[str]

ctx 由 ai_chat 在触发时填入：{"event": 事件dict}，工具可用它定位当前会话。
"""
import asyncio
import inspect
from typing import Callable, Optional

TOOLS: dict = {}  # name -> {"description","parameters","executor"}


def register_tool(name: str, description: str, parameters: dict):
    def deco(fn: Callable):
        TOOLS[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "executor": fn,
        }
        return fn
    return deco


def get_tool(name: str) -> Optional[dict]:
    return TOOLS.get(name)


def openai_schemas() -> list:
    """生成 OpenAI tools 参数格式。"""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in TOOLS.values()
    ]


async def execute_tool(name: str, arguments: dict, bot, ctx: dict) -> str:
    """执行工具：同步执行器进线程池，异步执行器直接 await。返回字符串结果。"""
    tool = TOOLS.get(name)
    if tool is None:
        return f"错误：不存在名为 {name} 的工具"
    try:
        result = tool["executor"](bot, arguments, ctx)
        if inspect.isawaitable(result):
            result = await result
        return str(result)[:4000]
    except Exception as e:
        return f"工具 {name} 执行失败: {e.__class__.__name__}: {e}"


def run_async_tool(coro):
    """占位保留：异步工具统一在事件循环内 await（见 execute_tool）。"""
    return asyncio.ensure_future(coro)
