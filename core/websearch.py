"""网页搜索兜底：必应国内版 HTML 抓取（免key，尽力而为）。

返回 [{title, url, snippet}]。抓取失败返回空列表，调用方据此提示。
以后接入博查等正式搜索API时，在 provider 里扩展即可。
"""
import re
from urllib.parse import quote

import httpx

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


def _clean(s: str) -> str:
    s = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", s).strip()


async def bing_search(query: str, max_results: int = 6) -> list:
    """抓取 cn.bing.com 搜索结果。"""
    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            r = await client.get(
                "https://cn.bing.com/search",
                params={"q": query, "count": max(max_results * 2, 10)},
                headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
            )
        html = r.text
    except Exception:
        return []

    results = []
    # 每个 <li class="b_algo"> 块内：标题链接 + 摘要
    for block in re.findall(r'<li class="b_algo".*?</li>', html, re.S)[: max_results * 3]:
        m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
        if not m:
            continue
        url, title = m.group(1), _clean(m.group(2))
        sm = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
        snippet = _clean(sm.group(1)) if sm else ""
        if title and url.startswith("http"):
            results.append({"title": title, "url": url, "snippet": snippet[:200]})
        if len(results) >= max_results:
            break
    return results


def format_results(query: str, results: list) -> str:
    """把搜索结果格式化为给模型看的文本（含编号，方便模型引用来源）。"""
    if not results:
        return f"搜索「{query}」没有返回任何结果（可能是抓取失败或无结果）。"
    lines = [f"搜索「{query}」的结果："]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}\n    摘要: {r['snippet']}\n    来源: {r['url']}")
    return "\n".join(lines)
