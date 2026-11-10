from langgraph.runtime import Runtime

from app.ingest.state import IngestContext, IngestState
from app.pipeline import stage


def embedding_text(chunk: dict) -> str:
    """送去向量化的文本：商品名 + 上级标题 + 片段正文。

    把商品名和上级标题编码进向量，同一商品、同一章节的片段在语义空间里会靠得更近。
    """
    parts = [chunk["product"]]
    if chunk["parent_title"] and chunk["parent_title"] != chunk["title"]:
        parts.append(chunk["parent_title"])
    parts.append(chunk["content"])
    return "\n".join(parts)


@stage("embed_chunks", "向量化")
async def embed_chunks(state: IngestState, runtime: Runtime[IngestContext]) -> dict:
    chunks = state["chunks"]
    vectors = await runtime.context["embeddings"].embed([embedding_text(chunk) for chunk in chunks])
    return {
        "chunks": [{**chunk, "dense": vector} for chunk, vector in zip(chunks, vectors)],
        "_detail": f"{len(vectors)} 个向量",
    }


@stage("store_chunks", "写入知识库")
async def store_chunks(state: IngestState, runtime: Runtime[IngestContext]) -> dict:
    """写入向量库。先清掉这份文档已有的片段，所以同一文档重复导入不会留下旧数据。"""
    store = runtime.context["vector_store"]
    await store.delete_document(state["doc_id"])
    written = await store.upsert_chunks(state["chunks"])
    await store.upsert_product(state["product"], state["product_vector"])
    return {"_detail": f"{written} 个片段"}
