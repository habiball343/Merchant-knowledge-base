"""流程测试用的替身：脚本化的模型，内存里的向量库、台账和对话历史。"""
import math
import re
import time
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk

from app.clients.object_store import LocalObjectStore
from app.clients.reranker import RerankError
from app.config import Settings
from app.ingest.state import IngestContext
from app.query.state import QueryContext

DIM = 64


def _tokens(text: str) -> list[str]:
    """汉字逐字、英文数字按词切分——足够让"字面相近的文本向量也相近"。"""
    return re.findall(r"[a-z0-9]+|[一-鿿]", text.lower())


def fake_vector(text: str) -> list[float]:
    vector = [0.0] * DIM
    for token in _tokens(text):
        vector[sum(ord(char) for char in token) % DIM] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def cosine(first: list[float], second: list[float]) -> float:
    return sum(a * b for a, b in zip(first, second))


class FakeEmbeddings:
    dim = DIM

    def __init__(self):
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [fake_vector(text) for text in texts]

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]

    async def healthy(self) -> bool:
        return True


class FakeReranker:
    """按问题与资料的字面重合度打分；available=False 时模拟服务不可用。"""

    def __init__(self, available: bool = True):
        self.available = available
        self.calls: list[tuple[str, list[str]]] = []

    async def score(self, query: str, texts: list[str]) -> list[float]:
        if not self.available:
            raise RerankError("服务不可用")
        self.calls.append((query, list(texts)))
        wanted = set(_tokens(query))
        return [len(wanted & set(_tokens(text))) / (len(wanted) or 1) for text in texts]

    async def healthy(self) -> bool:
        return self.available


class FakeVectorStore:
    def __init__(self):
        self.chunks: dict[str, dict[str, Any]] = {}
        self.products: dict[str, list[float]] = {}
        self.searches: list[dict[str, Any]] = []

    async def ensure_collections(self) -> None:
        pass

    async def healthy(self) -> bool:
        return True

    async def upsert_chunks(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self.chunks[row["chunk_id"]] = dict(row)
        return len(rows)

    async def delete_document(self, doc_id: str) -> None:
        self.chunks = {key: row for key, row in self.chunks.items() if row["doc_id"] != doc_id}

    async def count_chunks(self, doc_id: str | None = None) -> int:
        return sum(1 for row in self.chunks.values() if doc_id is None or row["doc_id"] == doc_id)

    async def hybrid_search(self, query_text: str, dense: list[float], products: list[str], limit: int):
        self.searches.append({"query": query_text, "products": list(products)})
        wanted = set(_tokens(query_text))
        scored = []
        for row in self.chunks.values():
            if products and row["product"] not in products:
                continue
            keyword = len(wanted & set(_tokens(row["content"]))) / (len(wanted) or 1)
            scored.append((cosine(dense, row["dense"]) + keyword, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{**{key: value for key, value in row.items() if key != "dense"}, "score": score}
                for score, row in scored[:limit]]

    async def upsert_product(self, name: str, dense: list[float]) -> None:
        self.products[name] = dense

    async def delete_product(self, name: str) -> None:
        self.products.pop(name, None)

    async def search_products(self, dense: list[float], limit: int = 5):
        ranked = sorted(((cosine(dense, vector), name) for name, vector in self.products.items()), reverse=True)
        return [{"name": name, "score": score} for score, name in ranked[:limit]]

    async def list_products(self) -> list[str]:
        return sorted(self.products)


class FakeHistory:
    def __init__(self):
        self.messages: list[dict[str, Any]] = []
        self.fail_on_append = False

    async def ensure_indexes(self) -> None:
        pass

    async def append(self, session_id: str, role: str, text: str, **extra: Any) -> None:
        if self.fail_on_append:
            raise RuntimeError("数据库不可用")
        self.messages.append({"session_id": session_id, "role": role, "text": text, "ts": time.time(), **extra})

    async def recent(self, session_id: str, limit: int = 8):
        return [message for message in self.messages if message["session_id"] == session_id][-limit:]

    async def clear(self, session_id: str) -> int:
        before = len(self.messages)
        self.messages = [message for message in self.messages if message["session_id"] != session_id]
        return before - len(self.messages)


class FakeRegistry:
    def __init__(self):
        self.documents: dict[str, dict[str, Any]] = {}

    async def create(self, document: dict[str, Any]) -> None:
        now = time.time()
        self.documents[document["doc_id"]] = {**document, "created_at": now, "updated_at": now}

    async def update(self, doc_id: str, **fields: Any) -> None:
        self.documents[doc_id].update(fields, updated_at=time.time())

    async def push_step(self, doc_id: str, step: dict[str, Any]) -> None:
        self.documents[doc_id].setdefault("steps", []).append(step)

    async def get(self, doc_id: str):
        document = self.documents.get(doc_id)
        return dict(document) if document else None

    async def list_documents(self):
        return sorted((dict(item) for item in self.documents.values()), key=lambda item: item["created_at"], reverse=True)

    async def delete(self, doc_id: str) -> None:
        self.documents.pop(doc_id, None)

    async def find_completed_by_file_name(self, file_name: str, exclude_doc_id: str):
        return [dict(item) for item in self.documents.values()
                if item["file_name"] == file_name and item["status"] == "completed" and item["doc_id"] != exclude_doc_id]

    async def count_by_product(self, product: str) -> int:
        return sum(1 for item in self.documents.values() if item.get("product") == product and item["status"] == "completed")

    async def fail_interrupted(self) -> int:
        return 0


class ScriptedLLM:
    """按提示词的种类返回预设的回答，并记录收到的提示词。"""

    def __init__(self, product_name: str = "ZG-12 数字万用表", extraction: dict | str | None = None,
                 hypothetical: str = "将旋钮转到直流电压档，红表笔接正极，黑表笔接负极，读取屏幕数值。",
                 answer: str = "先把旋钮转到直流电压档，再接好表笔读数 [1]。",
                 error: Exception | None = None, fail_kinds: tuple[str, ...] = ()):
        self.product_name = product_name
        self.extraction = extraction
        self.hypothetical = hypothetical
        self.answer = answer
        self.error = error
        self.fail_kinds = fail_kinds
        self.prompts: dict[str, list[str]] = {}

    @staticmethod
    def _kind(text: str) -> str:
        if "请判断下面这份资料对应的商品名称" in text:
            return "product_name"
        if "找出用户正在询问的商品" in text:
            return "extract"
        if "写一段产品手册中可能出现的原文" in text:
            return "hyde"
        return "answer"

    def _record(self, messages) -> str:
        text = "\n".join(str(message.content) for message in messages)
        kind = self._kind(text)
        self.prompts.setdefault(kind, []).append(text)
        if self.error is not None and (not self.fail_kinds or kind in self.fail_kinds):
            raise self.error
        return kind

    async def ainvoke(self, messages):
        kind = self._record(messages)
        if kind == "product_name":
            return AIMessage(content=self.product_name)
        if kind == "extract":
            if isinstance(self.extraction, str):
                return AIMessage(content=self.extraction)
            import json
            return AIMessage(content=json.dumps(
                self.extraction or {"item_names": [], "rewritten_query": ""}, ensure_ascii=False))
        if kind == "hyde":
            return AIMessage(content=self.hypothetical)
        return AIMessage(content=self.answer)

    async def astream(self, messages):
        self._record(messages)
        for start in range(0, len(self.answer), 6):
            yield AIMessageChunk(content=self.answer[start:start + 6])


class FakeCaptioner:
    def __init__(self, caption: str = "表笔接线示意图", error: Exception | None = None):
        self.caption_text = caption
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def caption(self, image: bytes, mime_type: str, document_title: str, context: str) -> str:
        self.calls.append({"size": len(image), "mime_type": mime_type, "title": document_title, "context": context})
        if self.error:
            raise self.error
        return self.caption_text


class FakeWebSearch:
    def __init__(self, results: list[dict[str, str]] | None = None):
        self.results = results or []
        self.queries: list[str] = []

    async def search(self, query: str):
        self.queries.append(query)
        return list(self.results)


class FakeContainer:
    """与真实 Container 同样的接口，全部由替身组成。"""

    def __init__(self, tmp_path: Path, llm: ScriptedLLM | None = None, captioner=None, web_search=None,
                 reranker: FakeReranker | None = None, llm_api_key: str = "test-key", **overrides: Any):
        self.settings = Settings(_env_file=None, data_dir=tmp_path / "data", llm_api_key=llm_api_key,
                                 pdf_parser="pymupdf", vision_requests_per_minute=1000, **overrides)
        self.llm = llm or ScriptedLLM()
        self.captioner = captioner
        self.embeddings = FakeEmbeddings()
        self.reranker = reranker or FakeReranker()
        self.vector_store = FakeVectorStore()
        self.object_store = LocalObjectStore(self.settings.data_dir / "files")
        self.registry = FakeRegistry()
        self.history = FakeHistory()
        self.web_search = web_search

    @property
    def llm_configured(self) -> bool:
        return bool(self.settings.llm_api_key)

    async def mongo_healthy(self) -> bool:
        return True

    def ingest_context(self) -> IngestContext:
        return IngestContext(settings=self.settings, llm=self.llm, captioner=self.captioner,
                             embeddings=self.embeddings, vector_store=self.vector_store,
                             object_store=self.object_store)

    def query_context(self) -> QueryContext:
        return QueryContext(settings=self.settings, llm=self.llm, embeddings=self.embeddings,
                            reranker=self.reranker, vector_store=self.vector_store,
                            history_store=self.history, web_search=self.web_search)
