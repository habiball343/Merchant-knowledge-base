"""应用配置。

所有配置项都可以通过项目根目录的 ``.env`` 或环境变量设置（变量名即字段名的大写形式），
源码中不存放任何密钥。
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # ---- 服务 ----
    app_host: str = "127.0.0.1"
    app_port: int = 18100
    data_dir: Path = PROJECT_ROOT / "data"          # 上传的原始文件、解析产物和图片
    max_upload_mb: int = 50

    # ---- 大模型（OpenAI 兼容协议）----
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-flash"
    llm_temperature: float = 0.1
    vision_model: str = ""                           # 留空则不为图片生成说明文字
    vision_requests_per_minute: int = 30

    # ---- 向量模型（OpenAI 兼容的 /embeddings 接口，默认指向本地 TEI）----
    embedding_base_url: str = ""
    embedding_host: str = "127.0.0.1"
    embedding_port: int = 18181
    embedding_api_key: str = ""
    embedding_model: str = "bge-large-zh-v1.5"
    embedding_dim: int = 1024
    embedding_batch_size: int = 16

    # ---- 重排序模型（TEI 的 /rerank 接口）----
    rerank_base_url: str = ""
    rerank_host: str = "127.0.0.1"
    rerank_port: int = 18182

    # ---- Milvus ----
    milvus_host: str = "127.0.0.1"
    milvus_port: int = 19630
    chunks_collection: str = "kb_chunks"
    products_collection: str = "kb_products"

    # ---- MongoDB ----
    mongo_host: str = "127.0.0.1"
    mongo_port: int = 27117
    mongo_user: str = "zhiku"
    mongo_password: str = ""
    mongo_db: str = "zhiku"

    # ---- 导入 ----
    pdf_parser: Literal["auto", "mineru", "pymupdf"] = "auto"
    mineru_command: str = "mineru"
    chunk_max_chars: int = 480                       # 向量模型最多 512 个 token，一个汉字约一个 token
    chunk_min_chars: int = 120
    product_context_chars: int = 2500                # 识别商品名时提供给模型的正文长度

    # ---- 检索与生成 ----
    retrieval_top_k: int = 10
    rrf_k: int = 60
    fused_top_k: int = 12
    rerank_max_top_k: int = 6
    rerank_min_top_k: int = 2
    rerank_gap_ratio: float = 0.5                    # 相邻两条的相对分差超过该值即视为"断崖"
    rerank_gap_abs: float = 0.3
    rerank_min_score: float = 0.02                   # 低于该分数的资料视为不相关
    product_confirm_score: float = 0.70              # 商品名向量相似度达到该值且没有相近的对手时，直接确认
    product_option_score: float = 0.60               # 达到该值但不足以确认时，作为候选请用户选择
    product_max_options: int = 5
    history_messages: int = 8
    max_context_chars: int = 6000

    # ---- 联网搜索（MCP，可选）----
    web_search_mcp_url: str = ""
    web_search_api_key: str = ""                     # 留空时使用 LLM_API_KEY
    web_search_tool: str = "bailian_web_search"
    web_search_count: int = 3
    web_search_timeout: float = 15.0

    @property
    def embedding_url(self) -> str:
        return (self.embedding_base_url or f"http://{self.embedding_host}:{self.embedding_port}/v1").rstrip("/")

    @property
    def rerank_url(self) -> str:
        return (self.rerank_base_url or f"http://{self.rerank_host}:{self.rerank_port}").rstrip("/")

    @property
    def milvus_uri(self) -> str:
        return f"http://{self.milvus_host}:{self.milvus_port}"

    @property
    def mongo_uri(self) -> str:
        if not self.mongo_password:
            return f"mongodb://{self.mongo_host}:{self.mongo_port}"
        return (f"mongodb://{quote_plus(self.mongo_user)}:{quote_plus(self.mongo_password)}"
                f"@{self.mongo_host}:{self.mongo_port}")

    @property
    def web_search_enabled(self) -> bool:
        return bool(self.web_search_mcp_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
