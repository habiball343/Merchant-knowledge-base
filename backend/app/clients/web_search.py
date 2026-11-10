"""联网搜索：通过 MCP（Model Context Protocol）调用外部的搜索工具。

知识库里查不到的问题可以用联网结果兜底。搜索服务只要提供一个 MCP 工具即可接入，
默认按阿里云百炼的 WebSearch 服务配置（工具名 bailian_web_search）。
"""
import asyncio
import json
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamablehttp_client

from app.logging import logger


class McpWebSearch:
    def __init__(self, url: str, api_key: str = "", tool: str = "bailian_web_search", count: int = 3,
                 timeout: float = 15.0):
        self.url = url
        self.tool = tool
        self.count = count
        self.timeout = timeout
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def search(self, query: str) -> list[dict[str, str]]:
        """返回 [{title, url, snippet}]。任何失败都只记录日志并返回空列表，不影响主流程。"""
        try:
            return await asyncio.wait_for(self._search(query), timeout=self.timeout)
        except Exception as exc:  # 外部服务的各种失败都不应中断问答
            logger.warning("联网搜索失败：{}: {}", type(exc).__name__, exc)
            return []

    async def _search(self, query: str) -> list[dict[str, str]]:
        arguments = {"query": query, "count": self.count}
        if self.url.rstrip("/").endswith("/sse"):
            async with sse_client(self.url, headers=self._headers) as (read, write):
                return await self._call(read, write, arguments)
        async with streamablehttp_client(self.url, headers=self._headers) as (read, write, _):
            return await self._call(read, write, arguments)

    async def _call(self, read, write, arguments: dict[str, Any]) -> list[dict[str, str]]:
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(self.tool, arguments)
        if result.isError:
            raise RuntimeError("搜索工具返回了错误")
        return parse_search_result([getattr(item, "text", "") for item in result.content])


def parse_search_result(texts: list[str]) -> list[dict[str, str]]:
    """从工具返回的文本中解析搜索结果，兼容几种常见的字段命名。"""
    pages: list[Any] = []
    for text in texts:
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            continue
        if isinstance(payload, dict):
            for key in ("pages", "results", "items", "data"):
                if isinstance(payload.get(key), list):
                    pages.extend(payload[key])
                    break
        elif isinstance(payload, list):
            pages.extend(payload)

    results = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        snippet = str(page.get("snippet") or page.get("content") or page.get("summary") or "").strip()
        if not snippet:
            continue
        results.append({
            "title": str(page.get("title") or "").strip(),
            "url": str(page.get("url") or page.get("link") or "").strip(),
            "snippet": snippet,
        })
    return results
