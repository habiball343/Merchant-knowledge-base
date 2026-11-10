"""导入流程的状态与运行时依赖。"""
from typing import Any, TypedDict

from app.clients.embeddings import EmbeddingClient
from app.clients.object_store import LocalObjectStore
from app.clients.vector_store import VectorStore
from app.config import Settings


class IngestState(TypedDict, total=False):
    doc_id: str
    file_name: str              # 上传时的文件名
    file_title: str             # 不含扩展名
    source_path: str            # 原始文件在本地的路径
    work_dir: str               # 解析过程的工作目录
    kind: str                   # pdf / markdown
    parser: str                 # 实际使用的解析器
    markdown: str
    base_dir: str               # Markdown 中相对路径图片的基准目录
    image_count: int
    chunks: list[dict[str, Any]]
    product: str                # 商品名；上传时指定了就直接使用
    product_given: bool
    product_vector: list[float]


class IngestContext(TypedDict):
    settings: Settings
    llm: Any                    # 对话模型
    captioner: Any | None       # 视觉模型；未配置时为 None
    embeddings: EmbeddingClient
    vector_store: VectorStore
    object_store: LocalObjectStore
