"""掌柜智库后端入口。"""
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routers import chat, documents, health
from app.config import get_settings
from app.container import Container
from app.logging import enable_file_logging
from app.services.chat_service import ChatService
from app.services.ingest_service import IngestService

_FRONTEND_DIST = Path(__file__).resolve().parents[1] / "frontend" / "dist"


def create_app(container: Container | None = None) -> FastAPI:
    """创建应用。测试时可以传入替身容器，不连接任何外部服务。"""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        owned = container is None
        active = container or Container(get_settings())
        app.state.container = active
        app.state.ingest_service = IngestService(active)
        app.state.chat_service = ChatService(active)
        if owned:
            enable_file_logging()
            await active.startup()
        yield
        await app.state.ingest_service.wait_idle()
        if owned:
            await active.shutdown()

    app = FastAPI(title="掌柜智库", description="面向商品资料的检索增强问答（RAG）知识库", lifespan=lifespan)
    app.include_router(documents.router)
    app.include_router(chat.router)
    app.include_router(health.router)
    # 生产形态下由后端同源托管构建好的前端；开发时前端可用 Vite 独立启动
    if _FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True), name="frontend")
    return app


app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(app, host=settings.app_host, port=settings.app_port)
