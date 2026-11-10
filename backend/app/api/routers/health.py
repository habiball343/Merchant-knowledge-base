"""健康检查：逐项探测依赖的服务。只返回是否就绪，不暴露地址、密钥或原始异常。"""
import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import get_container
from app.container import Container

APP_ID = "merchant-knowledge-base"

router = APIRouter(prefix="/api")


async def collect_health(container: Container) -> dict:
    settings = container.settings
    milvus, mongo, embedding, reranker = await asyncio.gather(
        container.vector_store.healthy(), container.mongo_healthy(),
        container.embeddings.healthy(), container.reranker.healthy())
    services = {
        "milvus": {"ok": milvus},
        "mongodb": {"ok": mongo},
        "embedding": {"ok": embedding},
        "reranker": {"ok": reranker},
    }
    return {
        "app": APP_ID,
        # 重排序模型不可用时问答会自动降级，所以不计入"是否就绪"
        "ready": milvus and mongo and embedding,
        "services": services,
        "model": settings.llm_model,
        "model_key_configured": container.llm_configured,
        "vision_enabled": container.captioner is not None,
        "web_search_enabled": container.web_search is not None,
    }


@router.get("/health")
async def health(container: Container = Depends(get_container)) -> JSONResponse:
    data = await collect_health(container)
    return JSONResponse(data, status_code=200 if data["ready"] else 503)
