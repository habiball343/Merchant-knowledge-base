"""文档导入服务：接收上传的文件，在后台跑导入流程，并把进度记到文档台账里。"""
import asyncio
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from app.clients.embeddings import EmbeddingError
from app.ingest.graph import STAGE_PROGRESS, ingest_graph
from app.ingest.nodes.load import SUPPORTED_SUFFIXES
from app.ingest.parsers import PdfParseError
from app.logging import logger


class UploadRejected(ValueError):
    """上传的文件不符合要求，原因可以直接展示给使用者。"""


class IngestService:
    def __init__(self, container):
        self._container = container
        self._tasks: set[asyncio.Task] = set()
        # 解析和向量化都很吃 CPU，一次只处理一份文档，其余排队
        self._queue = asyncio.Semaphore(1)

    async def submit(self, file_name: str, data: bytes, product: str = "") -> dict[str, Any]:
        settings = self._container.settings
        file_name = Path(file_name or "").name
        suffix = Path(file_name).suffix.lower()
        if suffix not in SUPPORTED_SUFFIXES:
            raise UploadRejected(f"不支持的文件类型：{file_name or '未命名文件'}。目前支持 PDF 和 Markdown。")
        if not data:
            raise UploadRejected(f"{file_name} 是空文件。")
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            raise UploadRejected(f"{file_name} 超过了 {settings.max_upload_mb} MB 的大小限制。")

        doc_id = uuid.uuid4().hex[:12]
        store = self._container.object_store
        source_key = f"{doc_id}/source/{_safe_name(file_name)}"
        store.save_bytes(source_key, data)

        product = product.strip()
        record = {
            "doc_id": doc_id,
            "file_name": file_name,
            "file_title": Path(file_name).stem,
            "product": product,
            "status": "pending",
            "stage": "排队中",
            "progress": 0,
            "chunk_count": 0,
            "image_count": 0,
            "parser": "",
            "error": "",
            "steps": [],
        }
        await self._container.registry.create(record)

        task = asyncio.create_task(self._run(doc_id, file_name, store.resolve(source_key), product))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return record

    async def _run(self, doc_id: str, file_name: str, source_path: Path, product: str) -> None:
        registry = self._container.registry
        work_dir = self._container.settings.data_dir / "work" / doc_id
        async with self._queue:
            try:
                work_dir.mkdir(parents=True, exist_ok=True)
                await registry.update(doc_id, status="processing", stage="开始处理", progress=1)
                state = {
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "file_title": Path(file_name).stem,
                    "source_path": str(source_path),
                    "work_dir": str(work_dir),
                    "product": product,
                    "product_given": bool(product),
                }
                final: dict[str, Any] = {}
                async for mode, chunk in ingest_graph.astream(
                        state, context=self._container.ingest_context(), stream_mode=["custom", "values"]):
                    if mode == "values":
                        final = chunk
                    elif chunk.get("type") == "stage":
                        await self._record_stage(doc_id, chunk)

                await registry.update(
                    doc_id, status="completed", stage="完成", progress=100, product=final["product"],
                    chunk_count=len(final["chunks"]), image_count=final.get("image_count", 0),
                    parser=final.get("parser", ""), error="")
                await self._replace_previous(doc_id, file_name)
                logger.info("文档 {} 导入完成：{} 个片段，商品「{}」", file_name, len(final["chunks"]), final["product"])
            except Exception as exc:
                logger.exception("文档 {} 导入失败", file_name)
                await self._discard_partial(doc_id)
                await registry.update(doc_id, status="failed", error=_describe(exc))
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)

    async def _record_stage(self, doc_id: str, event: dict[str, Any]) -> None:
        registry = self._container.registry
        if event["status"] == "running":
            await registry.update(doc_id, stage=event["label"], progress=STAGE_PROGRESS.get(event["node"], 0))
        elif event["status"] in ("done", "skipped"):
            await registry.push_step(doc_id, {
                "label": event["label"], "status": event["status"],
                "detail": event.get("detail", ""), "elapsed_ms": event.get("elapsed_ms"),
            })

    async def _replace_previous(self, doc_id: str, file_name: str) -> None:
        """同名文件重新上传视为更新：新版本入库成功后，再移除旧版本。"""
        for old in await self._container.registry.find_completed_by_file_name(file_name, exclude_doc_id=doc_id):
            await self.delete(old["doc_id"])

    async def _discard_partial(self, doc_id: str) -> None:
        try:
            await self._container.vector_store.delete_document(doc_id)
        except Exception:
            pass  # 向量库本身不可用时没有可清理的内容

    async def delete(self, doc_id: str) -> bool:
        registry = self._container.registry
        document = await registry.get(doc_id)
        if document is None:
            return False
        await self._container.vector_store.delete_document(doc_id)
        self._container.object_store.delete_prefix(doc_id)
        await registry.delete(doc_id)
        product = document.get("product")
        if product and await registry.count_by_product(product) == 0:
            await self._container.vector_store.delete_product(product)
        return True

    async def wait_idle(self) -> None:
        """等待所有后台导入任务结束（测试和优雅停机时使用）。"""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


def _safe_name(file_name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", file_name, flags=re.UNICODE) or "upload"


def _describe(exc: Exception) -> str:
    """面向使用者的失败原因：已知的失败给出具体原因，未知异常只给类型，细节留在日志里。"""
    if isinstance(exc, (ValueError, FileNotFoundError, PdfParseError, EmbeddingError)):
        return str(exc)
    return f"导入过程中出现意外错误（{type(exc).__name__}），详情见后端日志。"
