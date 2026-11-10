"""Milvus 访问层：切片的混合检索（稠密向量 + BM25 全文）与商品名的向量对齐。

两个集合：

- 切片集合：每条是一段资料。``dense`` 是正文的语义向量；``sparse`` 由 Milvus 内置的 BM25
  函数从 ``content`` 自动生成（中文分词），不需要客户端计算稀疏向量。
- 商品集合：每条是一个商品名及其向量，用来把用户口中的叫法对齐到知识库里的标准名称。

pymilvus 的客户端是同步的，这里统一放到线程里执行，避免阻塞事件循环。
"""
import asyncio
import json
import threading
from typing import Any

from pymilvus import AnnSearchRequest, DataType, Function, FunctionType, MilvusClient, RRFRanker

_CHUNK_FIELDS = ["chunk_id", "doc_id", "product", "file_title", "title", "parent_title", "seq", "content"]


def _quote(value: str) -> str:
    """把字符串转成 Milvus 过滤表达式里的字面量（转义引号和反斜杠）。"""
    return json.dumps(value, ensure_ascii=False)


class VectorStore:
    def __init__(self, uri: str, chunks_collection: str, products_collection: str, dim: int):
        self.uri = uri
        self.chunks = chunks_collection
        self.products = products_collection
        self.dim = dim
        self._client: MilvusClient | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 连接与建表

    def _connect(self) -> MilvusClient:
        with self._lock:
            if self._client is None:
                self._client = MilvusClient(uri=self.uri, timeout=10)
            return self._client

    def _ensure_collections(self) -> None:
        client = self._connect()
        if not client.has_collection(self.chunks):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=128)
            schema.add_field("doc_id", DataType.VARCHAR, max_length=64)
            schema.add_field("product", DataType.VARCHAR, max_length=512)
            schema.add_field("file_title", DataType.VARCHAR, max_length=1024)
            schema.add_field("title", DataType.VARCHAR, max_length=2048)
            schema.add_field("parent_title", DataType.VARCHAR, max_length=2048)
            schema.add_field("seq", DataType.INT64)
            schema.add_field("content", DataType.VARCHAR, max_length=32768,
                             enable_analyzer=True, analyzer_params={"type": "chinese"})
            schema.add_field("dense", DataType.FLOAT_VECTOR, dim=self.dim)
            schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
            schema.add_function(Function(
                name="content_bm25", function_type=FunctionType.BM25,
                input_field_names=["content"], output_field_names=["sparse"]))
            index = client.prepare_index_params()
            index.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="COSINE")
            index.add_index(field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25")
            # 知识库规模不大，用强一致性换取"导入完成后立刻可检索"
            client.create_collection(self.chunks, schema=schema, index_params=index, consistency_level="Strong")
        if not client.has_collection(self.products):
            schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field("name", DataType.VARCHAR, is_primary=True, max_length=512)
            schema.add_field("dense", DataType.FLOAT_VECTOR, dim=self.dim)
            index = client.prepare_index_params()
            index.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="COSINE")
            client.create_collection(self.products, schema=schema, index_params=index, consistency_level="Strong")

    async def ensure_collections(self) -> None:
        await asyncio.to_thread(self._ensure_collections)

    async def healthy(self) -> bool:
        try:
            await asyncio.to_thread(lambda: self._connect().has_collection(self.chunks))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._client is not None:
            await asyncio.to_thread(self._client.close)
            self._client = None

    # ------------------------------------------------------------------ 切片

    async def upsert_chunks(self, rows: list[dict[str, Any]]) -> int:
        """写入切片。chunk_id 是确定性的，重复导入会覆盖而不是新增。"""
        def run() -> int:
            client = self._connect()
            total = 0
            for start in range(0, len(rows), 100):
                total += client.upsert(self.chunks, rows[start:start + 100])["upsert_count"]
            return total
        return await asyncio.to_thread(run)

    async def delete_document(self, doc_id: str) -> None:
        await asyncio.to_thread(
            lambda: self._connect().delete(self.chunks, filter=f"doc_id == {_quote(doc_id)}"))

    async def count_chunks(self, doc_id: str | None = None) -> int:
        def run() -> int:
            expr = f"doc_id == {_quote(doc_id)}" if doc_id else ""
            rows = self._connect().query(self.chunks, filter=expr, output_fields=["count(*)"])
            return int(rows[0]["count(*)"]) if rows else 0
        return await asyncio.to_thread(run)

    async def hybrid_search(self, query_text: str, dense: list[float], products: list[str],
                            limit: int) -> list[dict[str, Any]]:
        """在指定商品的资料范围内做混合检索：语义向量一路、BM25 关键词一路，Milvus 内部用 RRF 合并。"""
        def run() -> list[dict[str, Any]]:
            expr = f"product in [{', '.join(_quote(name) for name in products)}]" if products else None
            requests = [
                AnnSearchRequest(data=[dense], anns_field="dense", param={"metric_type": "COSINE"},
                                 limit=limit, expr=expr),
                AnnSearchRequest(data=[query_text], anns_field="sparse", param={"metric_type": "BM25"},
                                 limit=limit, expr=expr),
            ]
            result = self._connect().hybrid_search(
                self.chunks, requests, ranker=RRFRanker(60), limit=limit, output_fields=_CHUNK_FIELDS)
            return [{**hit["entity"], "score": float(hit["distance"])} for hit in (result[0] if result else [])]
        return await asyncio.to_thread(run)

    # ------------------------------------------------------------------ 商品名

    async def upsert_product(self, name: str, dense: list[float]) -> None:
        await asyncio.to_thread(
            lambda: self._connect().upsert(self.products, [{"name": name, "dense": dense}]))

    async def delete_product(self, name: str) -> None:
        await asyncio.to_thread(
            lambda: self._connect().delete(self.products, filter=f"name == {_quote(name)}"))

    async def search_products(self, dense: list[float], limit: int = 5) -> list[dict[str, Any]]:
        """返回与给定向量最接近的商品名及余弦相似度。"""
        def run() -> list[dict[str, Any]]:
            result = self._connect().search(
                self.products, data=[dense], anns_field="dense",
                search_params={"metric_type": "COSINE"}, limit=limit, output_fields=["name"])
            return [{"name": hit["entity"]["name"], "score": float(hit["distance"])}
                    for hit in (result[0] if result else [])]
        return await asyncio.to_thread(run)

    async def list_products(self) -> list[str]:
        def run() -> list[str]:
            rows = self._connect().query(self.products, filter='name != ""', output_fields=["name"], limit=1000)
            return sorted(row["name"] for row in rows)
        return await asyncio.to_thread(run)
