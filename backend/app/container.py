"""依赖装配：创建并持有各个外部服务的客户端。"""
from pymongo import AsyncMongoClient

from app.clients.embeddings import EmbeddingClient
from app.clients.llm import VisionCaptioner, build_chat_model
from app.clients.mongo import ChatHistory, DocumentRegistry
from app.clients.object_store import LocalObjectStore
from app.clients.reranker import RerankClient
from app.clients.vector_store import VectorStore
from app.clients.web_search import McpWebSearch
from app.config import Settings
from app.ingest.state import IngestContext
from app.logging import logger
from app.query.state import QueryContext


class Container:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = build_chat_model(settings)
        self.captioner = (
            VisionCaptioner(build_chat_model(settings, model=settings.vision_model))
            if settings.vision_model else None)
        self.embeddings = EmbeddingClient(
            settings.embedding_url, settings.embedding_model, settings.embedding_api_key,
            settings.embedding_dim, settings.embedding_batch_size)
        self.reranker = RerankClient(settings.rerank_url)
        self.vector_store = VectorStore(
            settings.milvus_uri, settings.chunks_collection, settings.products_collection, settings.embedding_dim)
        self.object_store = LocalObjectStore(settings.data_dir / "files")
        self._mongo = AsyncMongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)
        self.registry = DocumentRegistry(self._mongo, settings.mongo_db)
        self.history = ChatHistory(self._mongo, settings.mongo_db)
        self.web_search = (
            McpWebSearch(settings.web_search_mcp_url, settings.web_search_api_key or settings.llm_api_key,
                         settings.web_search_tool, settings.web_search_count, settings.web_search_timeout)
            if settings.web_search_enabled else None)

    @property
    def llm_configured(self) -> bool:
        return bool(self.settings.llm_api_key)

    async def startup(self) -> None:
        """准备集合与索引。依赖暂时不可用时只记录警告：服务照常启动，健康检查会如实反映。"""
        try:
            await self.vector_store.ensure_collections()
        except Exception as exc:
            logger.warning("Milvus 暂不可用，稍后请检查服务状态：{}: {}", type(exc).__name__, exc)
        try:
            await self.history.ensure_indexes()
            interrupted = await self.registry.fail_interrupted()
            if interrupted:
                logger.warning("{} 个导入任务在上次运行中被中断，已标记为失败", interrupted)
        except Exception as exc:
            logger.warning("MongoDB 暂不可用，稍后请检查服务状态：{}: {}", type(exc).__name__, exc)

    async def mongo_healthy(self) -> bool:
        try:
            await self._mongo.admin.command("ping")
            return True
        except Exception:
            return False

    async def shutdown(self) -> None:
        await self.embeddings.close()
        await self.reranker.close()
        await self.vector_store.close()
        await self._mongo.close()

    def ingest_context(self) -> IngestContext:
        return IngestContext(
            settings=self.settings, llm=self.llm, captioner=self.captioner, embeddings=self.embeddings,
            vector_store=self.vector_store, object_store=self.object_store)

    def query_context(self) -> QueryContext:
        return QueryContext(
            settings=self.settings, llm=self.llm, embeddings=self.embeddings, reranker=self.reranker,
            vector_store=self.vector_store, history_store=self.history, web_search=self.web_search)
