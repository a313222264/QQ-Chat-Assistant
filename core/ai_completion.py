"""AI 底层通用调用：创建客户端、简单对话、搜索结果总结。

ai_chat 的工具循环、game_data 的总结、proactive_chat 的生成 都走这里创建的客户端，
避免相互 import。
"""
import asyncio
import re

_client_cache = {}


def get_client(cfg):
    """按 (base_url, api_key) 缓存 OpenAI 兼容客户端。"""
    api_key = cfg.get("ai.api_key", "") or ""
    base_url = cfg.get("ai.base_url", "https://api.minimaxi.com/v1")
    key = (base_url, api_key)
    if key not in _client_cache:
        from openai import OpenAI

        _client_cache[key] = OpenAI(api_key=api_key or "EMPTY", base_url=base_url)
    return _client_cache[key]


def strip_think(text: str) -> str:
    """剥掉模型输出里的思考内容。"""
    if not text:
        return ""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def model_name(cfg) -> str:
    return cfg.get("ai.model", "MiniMax-M3")


def chat_once_sync(cfg, messages: list, max_tokens: int = None, temperature: float = None) -> str:
    """单轮同步对话（不含工具循环），返回剥掉思考标签的文本。"""
    resp = get_client(cfg).chat.completions.create(
        model=model_name(cfg),
        messages=messages,
        max_tokens=max_tokens or int(cfg.get("ai.max_tokens", 2000)),
        temperature=temperature if temperature is not None else float(cfg.get("ai.temperature", 0.8)),
    )
    return strip_think(resp.choices[0].message.content or "")


async def summarize_search(cfg, query: str, results: list) -> str:
    """基于搜索结果整理回答：强制引用来源编号和链接。"""
    from core import websearch

    results_text = websearch.format_results(query, results)
    messages = [
        {
            "role": "system",
            "content": (
                "你是数据整理助手。只依据用户提供的搜索结果回答问题，"
                "不要编造数据。回答末尾必须用「来源：」列出所引用结果的编号和链接。"
                "如果搜索结果不足以回答，明确说明信息不足。用简洁的中文，不要markdown。"
            ),
        },
        {"role": "user", "content": f"问题：{query}\n\n搜索结果：\n{results_text}"},
    ]
    try:
        answer = await asyncio.to_thread(chat_once_sync, cfg, messages)
    except Exception as e:
        return f"AI整理失败（{e.__class__.__name__}），原始搜索结果：\n" + websearch.format_results(query, results)[:800]
    if not answer:
        return "AI没有给出有效回答，请稍后再试。"
    return answer[:1200]
