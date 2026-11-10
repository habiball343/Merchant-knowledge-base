"""问答流程的状态与运行时依赖。"""
from typing import Any, TypedDict

from app.clients.embeddings import EmbeddingClient
from app.clients.reranker import RerankClient
from app.clients.vector_store import VectorStore
from app.config import Settings


class QueryState(TypedDict, total=False):
    session_id: str
    question: str                          # 用户的原始问题
    history: list[dict[str, Any]]          # 本次会话最近的消息
    rewritten_query: str                   # 补全了商品名和指代的完整问题
    products: list[str]                    # 确认的商品
    clarification: str                     # 需要用户澄清时的提示语（有值则不再检索）
    options: list[str]                     # 澄清时给用户的候选商品
    vector_hits: list[dict[str, Any]]      # 混合检索结果
    hyde_hits: list[dict[str, Any]]        # HyDE 检索结果
    web_hits: list[dict[str, Any]]         # 联网搜索结果
    fused: list[dict[str, Any]]            # RRF 融合后的候选
    sources: list[dict[str, Any]]          # 重排序并截断后，最终提供给模型的资料
    answer: str


class QueryContext(TypedDict):
    settings: Settings
    llm: Any
    embeddings: EmbeddingClient
    reranker: RerankClient
    vector_store: VectorStore
    history_store: Any
    web_search: Any | None                 # 未启用联网搜索时为 None
