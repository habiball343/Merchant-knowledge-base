"""检查各项依赖是否就绪：向量库、文档库、向量模型、重排序模型和模型密钥。

    uv run python -m app.scripts.check_environment [--quiet]

只做探测，不调用大模型，也不修改任何数据。必需的依赖有一项不可用时以非零状态退出。
"""
import argparse
import asyncio

from app.config import get_settings
from app.container import Container


async def collect() -> tuple[list[tuple[str, bool | None, str]], bool]:
    """返回 ([(名称, 是否正常, 说明)], 是否就绪)。是否正常为 None 表示可选项。"""
    settings = get_settings()
    container = Container(settings)
    rows: list[tuple[str, bool | None, str]] = []
    try:
        milvus, mongo, embedding, reranker = await asyncio.gather(
            container.vector_store.healthy(), container.mongo_healthy(),
            container.embeddings.healthy(), container.reranker.healthy())

        detail = f"127.0.0.1:{settings.milvus_port}" if settings.milvus_host == "127.0.0.1" else settings.milvus_host
        if milvus:
            await container.vector_store.ensure_collections()
            detail = f"{await container.vector_store.count_chunks()} 个片段，{len(await container.vector_store.list_products())} 款商品"
        rows.append(("向量库 Milvus", milvus, detail if milvus else "连不上，请确认容器已启动"))

        detail = "连不上，请确认容器已启动、MONGO_PASSWORD 与创建数据卷时一致"
        if mongo:
            detail = f"{len(await container.registry.list_documents())} 份文档"
        rows.append(("文档库 MongoDB", mongo, detail))

        detail = "不可用。首次启动要下载模型，可用 docker compose logs embedding 查看进度"
        if embedding:
            detail = f"{settings.embedding_model}，{len(await container.embeddings.embed_one('检查'))} 维"
        rows.append(("向量模型", embedding, detail))

        rows.append(("重排序模型", reranker,
                     "正常" if reranker else "不可用（问答会退回融合排序）。可用 docker compose logs reranker 查看"))
        rows.append(("对话模型", container.llm_configured,
                     settings.llm_model if container.llm_configured else "未填写 LLM_API_KEY"))
        rows.append(("图片说明", None, settings.vision_model or "未启用（VISION_MODEL 为空）"))
        rows.append(("联网搜索", None, "已启用" if settings.web_search_enabled else "未启用（WEB_SEARCH_MCP_URL 为空）"))
        return rows, bool(milvus and mongo and embedding)
    finally:
        await container.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="检查掌柜智库的各项依赖")
    parser.add_argument("--quiet", action="store_true", help="只输出有问题的项目")
    args = parser.parse_args()

    rows, ready = asyncio.run(collect())
    for name, ok, detail in rows:
        if args.quiet and ok is not False:
            continue
        mark = {True: "正常", False: "异常", None: "可选"}[ok]
        print(f"[{mark}] {name}：{detail}")
    if not args.quiet:
        print("依赖服务已就绪。" if ready else "有必需的依赖尚未就绪。")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
