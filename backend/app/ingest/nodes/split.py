from langgraph.runtime import Runtime

from app.ingest.chunking import split_markdown
from app.ingest.state import IngestContext, IngestState
from app.pipeline import stage


@stage("split_document", "切分文档")
async def split_document(state: IngestState, runtime: Runtime[IngestContext]) -> dict:
    settings = runtime.context["settings"]
    chunks = split_markdown(
        state["markdown"], state["file_title"], settings.chunk_max_chars, settings.chunk_min_chars)
    if not chunks:
        raise ValueError("资料中没有可以导入的文字内容")
    doc_id = state["doc_id"]
    return {
        "chunks": [
            {
                "chunk_id": f"{doc_id}-{chunk.seq:04d}",
                "doc_id": doc_id,
                "file_title": state["file_title"],
                "title": chunk.title,
                "parent_title": chunk.parent_title,
                "seq": chunk.seq,
                "content": chunk.content,
            }
            for chunk in chunks
        ],
        "_detail": f"{len(chunks)} 个片段",
    }
