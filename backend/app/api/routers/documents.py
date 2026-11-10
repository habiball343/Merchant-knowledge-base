"""文档管理：上传、查看导入进度、删除，以及知识库中的商品列表。"""
from collections import Counter
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import get_container, get_ingest_service
from app.container import Container
from app.services.ingest_service import IngestService, UploadRejected

router = APIRouter(prefix="/api")

_PUBLIC_FIELDS = ["doc_id", "file_name", "file_title", "product", "status", "stage", "progress", "chunk_count",
                  "image_count", "parser", "error", "steps", "created_at", "updated_at"]


def _public(document: dict[str, Any]) -> dict[str, Any]:
    return {field: document.get(field) for field in _PUBLIC_FIELDS}


@router.post("/documents", status_code=202)
async def upload_documents(
    files: list[UploadFile] = File(..., description="PDF 或 Markdown 文件，可一次上传多个"),
    product: str = Form("", description="商品名称；留空则由模型从资料中识别"),
    service: IngestService = Depends(get_ingest_service),
) -> dict:
    """上传资料。文件保存后立即返回，解析、切分、向量化在后台进行，进度通过文档列表查看。"""
    accepted, rejected = [], []
    for upload in files:
        try:
            record = await service.submit(upload.filename or "", await upload.read(), product)
            accepted.append(_public(record))
        except UploadRejected as exc:
            rejected.append({"file_name": upload.filename, "reason": str(exc)})
    if not accepted:
        raise HTTPException(status_code=400, detail={"message": "没有可以导入的文件", "rejected": rejected})
    return {"accepted": accepted, "rejected": rejected}


@router.get("/documents")
async def list_documents(container: Container = Depends(get_container)) -> dict:
    return {"items": [_public(document) for document in await container.registry.list_documents()]}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, container: Container = Depends(get_container)) -> dict:
    document = await container.registry.get(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _public(document)


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, container: Container = Depends(get_container),
                          service: IngestService = Depends(get_ingest_service)) -> dict:
    document = await container.registry.get(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    if document["status"] in ("pending", "processing"):
        raise HTTPException(status_code=409, detail="文档正在导入，请等导入结束后再删除")
    await service.delete(doc_id)
    return {"deleted": doc_id}


@router.get("/products")
async def list_products(container: Container = Depends(get_container)) -> dict:
    """知识库里有哪些商品的资料，每个商品有几份文档。"""
    documents = await container.registry.list_documents()
    counts = Counter(document["product"] for document in documents
                     if document["status"] == "completed" and document.get("product"))
    return {"items": [{"name": name, "documents": count} for name, count in sorted(counts.items())]}


@router.get("/files/{key:path}")
async def get_file(key: str, container: Container = Depends(get_container)) -> FileResponse:
    """资料中的图片、解析后的 Markdown 和上传的原始文件。"""
    try:
        path = container.object_store.resolve(key)
    except ValueError:
        raise HTTPException(status_code=404, detail="文件不存在") from None
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path)
