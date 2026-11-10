"""外部服务客户端：向量模型、重排序模型、文件存储、联网搜索。"""
import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.clients.embeddings import EmbeddingClient, EmbeddingError
from app.clients.object_store import LocalObjectStore
from app.clients.reranker import RerankClient, RerankError
from app.clients.web_search import McpWebSearch, parse_search_result
from app.config import Settings


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- 向量模型

async def test_embeddings_are_requested_in_batches_and_returned_in_input_order():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        # 故意乱序返回，客户端应按 index 还原顺序
        data = [{"index": index, "embedding": [float(len(text)), 0.0]} for index, text in enumerate(body["input"])]
        return httpx.Response(200, json={"data": list(reversed(data))})

    client = EmbeddingClient("http://embedding/v1/", "bge", dim=2, batch_size=2, http=mock_client(handler))

    vectors = await client.embed(["a", "bb", "ccc"])

    assert vectors == [[1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]
    assert [body["input"] for body in requests] == [["a", "bb"], ["ccc"]]
    assert requests[0]["model"] == "bge"


async def test_embedding_dimension_mismatch_is_reported_with_the_setting_name():
    client = EmbeddingClient("http://embedding/v1", "bge", dim=1024, http=mock_client(
        lambda request: httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})))

    with pytest.raises(EmbeddingError, match="EMBEDDING_DIM=1024"):
        await client.embed(["a"])


async def test_embedding_service_errors_become_embedding_errors():
    client = EmbeddingClient("http://embedding/v1", "bge", dim=2,
                             http=mock_client(lambda request: httpx.Response(503, text="loading")))

    with pytest.raises(EmbeddingError):
        await client.embed(["a"])
    assert await client.healthy() is False


# ---------------------------------------------------------------- 重排序模型

async def test_rerank_scores_are_aligned_with_the_input_texts_across_batches():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["query"] == "问题" and body["truncate"] is True
        scored = [{"index": index, "score": len(text) / 10} for index, text in enumerate(body["texts"])]
        return httpx.Response(200, json=sorted(scored, key=lambda item: item["score"], reverse=True))

    client = RerankClient("http://rerank/", batch_size=2, http=mock_client(handler))

    assert await client.score("问题", ["a", "bbb", "cc"]) == [0.1, 0.3, 0.2]


async def test_rerank_failure_raises_rerank_error():
    client = RerankClient("http://rerank", http=mock_client(lambda request: httpx.Response(500)))

    with pytest.raises(RerankError):
        await client.score("问题", ["a"])


# ---------------------------------------------------------------- 文件存储

def test_object_store_saves_serves_and_deletes(tmp_path):
    store = LocalObjectStore(tmp_path / "files")

    url = store.save_bytes("doc1/images/图 1.png", b"png")

    assert url == "/api/files/doc1/images/图 1.png"
    assert store.resolve("doc1/images/图 1.png").read_bytes() == b"png"
    store.delete_prefix("doc1")
    assert not (tmp_path / "files" / "doc1").exists()
    store.delete_prefix("doc1")       # 重复删除不报错


@pytest.mark.parametrize("key", ["../outside.txt", "doc/../../outside.txt", "/etc/passwd", "", "doc\\..\\..\\x"])
def test_object_store_rejects_keys_that_escape_the_root(tmp_path, key):
    store = LocalObjectStore(tmp_path / "files")

    with pytest.raises(ValueError):
        store.resolve(key)


# ---------------------------------------------------------------- 配置

def test_settings_derive_service_addresses_and_escape_credentials():
    settings = Settings(_env_file=None, mongo_user="zhi ku", mongo_password="p@ss/word", embedding_port=9001,
                        rerank_base_url="http://rerank.internal:8080/")

    assert settings.mongo_uri == "mongodb://zhi+ku:p%40ss%2Fword@127.0.0.1:27117"
    assert settings.embedding_url == "http://127.0.0.1:9001/v1"
    assert settings.rerank_url == "http://rerank.internal:8080"
    assert settings.web_search_enabled is False
    assert Settings(_env_file=None).mongo_uri == "mongodb://127.0.0.1:27117"


# ---------------------------------------------------------------- 联网搜索

def test_search_results_are_parsed_from_common_shapes():
    bailian = json.dumps({"pages": [{"title": "标题", "url": "https://a", "snippet": " 摘要 "},
                                    {"title": "没有摘要", "url": "https://b", "snippet": ""}]}, ensure_ascii=False)
    generic = json.dumps([{"title": "T", "link": "https://c", "content": "正文"}], ensure_ascii=False)

    assert parse_search_result([bailian, "不是 JSON", generic]) == [
        {"title": "标题", "url": "https://a", "snippet": "摘要"},
        {"title": "T", "url": "https://c", "snippet": "正文"},
    ]


@pytest.fixture
def mcp_search_server():
    """在本机起一个真实的 MCP 服务（SSE 传输），提供一个搜索工具。"""
    from mcp.server.fastmcp import FastMCP

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = FastMCP("search", host="127.0.0.1", port=port)
    seen = []

    @server.tool()
    def bailian_web_search(query: str, count: int = 3) -> str:
        """搜索网页"""
        seen.append({"query": query, "count": count})
        return json.dumps({"pages": [
            {"title": f"关于{query}", "url": "https://example.com/1", "snippet": "第一条结果"},
            {"title": "第二条", "url": "https://example.com/2", "snippet": "第二条结果"},
        ][:count]}, ensure_ascii=False)

    runner = uvicorn.Server(uvicorn.Config(server.sse_app(), host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=runner.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not runner.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/sse", seen
    runner.should_exit = True
    thread.join(timeout=5)


async def test_web_search_calls_the_tool_over_mcp(mcp_search_server):
    url, seen = mcp_search_server

    results = await McpWebSearch(url, api_key="key", count=2).search("万用表怎么换电池")

    assert seen == [{"query": "万用表怎么换电池", "count": 2}]
    assert results == [
        {"title": "关于万用表怎么换电池", "url": "https://example.com/1", "snippet": "第一条结果"},
        {"title": "第二条", "url": "https://example.com/2", "snippet": "第二条结果"},
    ]


async def test_web_search_failures_return_nothing_instead_of_raising(mcp_search_server):
    url, _ = mcp_search_server

    assert await McpWebSearch(url, tool="no_such_tool").search("问题") == []
    assert await McpWebSearch("http://127.0.0.1:9/sse", timeout=2).search("问题") == []
