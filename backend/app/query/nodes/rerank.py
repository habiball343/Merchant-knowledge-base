import re
from typing import Any

from langgraph.runtime import Runtime

from app.clients.reranker import RerankError
from app.logging import logger
from app.pipeline import stage
from app.query.cutoff import cliff_cutoff
from app.query.state import QueryContext, QueryState

_SNIPPET_CHARS = 160


@stage("rerank", "重排序")
async def rerank(state: QueryState, runtime: Runtime[QueryContext]) -> dict:
    """知识库候选和联网结果放在一起，由交叉编码器逐条打分，再按分数落差截断。"""
    context = runtime.context
    settings = context["settings"]
    candidates = _collect(state)
    if not candidates:
        return {"sources": [], "_detail": "没有候选资料"}

    try:
        scores = await context["reranker"].score(state["rewritten_query"], [doc["content"] for doc in candidates])
        ranked = sorted(({**doc, "score": score} for doc, score in zip(candidates, scores)),
                        key=lambda doc: doc["score"], reverse=True)
        kept = cliff_cutoff(ranked, settings.rerank_min_top_k, settings.rerank_max_top_k,
                            settings.rerank_gap_ratio, settings.rerank_gap_abs, settings.rerank_min_score)
        detail = f"{len(candidates)} 条候选，保留 {len(kept)} 条"
    except RerankError as exc:
        # 重排序模型不可用时退回融合排序的结果，问答仍然可用，只是排序没那么准
        logger.warning("重排序不可用，沿用融合排序：{}", exc)
        kept = [{**doc, "score": None} for doc in candidates[:settings.rerank_max_top_k]]
        detail = f"重排序不可用，沿用融合排序的前 {len(kept)} 条"

    sources = [{**doc, "index": index} for index, doc in enumerate(kept, 1)]
    runtime.stream_writer({"type": "sources", "items": [public_source(doc) for doc in sources]})
    return {"sources": sources, "_detail": detail}


def _collect(state: QueryState) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for hit in state.get("fused") or []:
        if (hit.get("content") or "").strip():
            candidates.append({
                "source": "knowledge",
                "chunk_id": hit.get("chunk_id"),
                "doc_id": hit.get("doc_id"),
                "product": hit.get("product", ""),
                "file_title": hit.get("file_title", ""),
                "title": hit.get("title", ""),
                "parent_title": hit.get("parent_title", ""),
                "url": "",
                "content": hit["content"].strip(),
                "routes": hit.get("routes", []),
            })
    for hit in state.get("web_hits") or []:
        if (hit.get("snippet") or "").strip():
            candidates.append({
                "source": "web",
                "chunk_id": None,
                "doc_id": None,
                "product": "",
                "file_title": "",
                "title": hit.get("title", ""),
                "parent_title": "",
                "url": hit.get("url", ""),
                "content": hit["snippet"].strip(),
                "routes": ["web"],
            })
    return candidates


def public_source(doc: dict[str, Any]) -> dict[str, Any]:
    """发给页面的资料卡片：带正文摘要，不带向量等内部字段。"""
    content = doc["content"]
    snippet = plain_text(content, skip_heading=doc["title"])
    return {
        "index": doc["index"],
        "source": doc["source"],
        "product": doc["product"],
        "file_title": doc["file_title"],
        "title": doc["title"],
        "parent_title": doc["parent_title"],
        "url": doc["url"],
        "doc_id": doc["doc_id"],
        "chunk_id": doc["chunk_id"],
        "score": None if doc.get("score") is None else round(float(doc["score"]), 4),
        "routes": doc.get("routes", []),
        "snippet": snippet[:_SNIPPET_CHARS] + ("…" if len(snippet) > _SNIPPET_CHARS else ""),
        "content": content,
    }


def plain_text(markdown: str, skip_heading: str = "") -> str:
    """把一段 Markdown 压成一行纯文字，用作资料卡片上的摘要（标题、表格、图片的标记都去掉）。"""
    parts: list[str] = []
    for line in markdown.split("\n"):
        line = line.strip()
        if not line or re.fullmatch(r"\|?[\s:|-]+\|?", line) or re.match(r"^(```|~~~)", line):
            continue                                           # 空行、表格的分隔行、代码围栏
        heading = re.match(r"^#{1,6}\s+(.*)$", line)
        if heading:
            text = heading.group(1).strip()
            if text and text not in skip_heading:              # 卡片上已经有标题，不在摘要里重复
                parts.append(f"{text}：")
            continue
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|") if cell.strip()]
            line = "，".join(cells) + "；"
        line = re.sub(r"!\[([^\]]*)\]\([^)]*\)", lambda match: f"（图：{match.group(1)}）" if match.group(1) else "", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", line)
        line = re.sub(r"^([-*+]|>)\s+", "", line)
        line = re.sub(r"[*_`]{1,3}", "", line)
        if line:
            parts.append(line)
    text = re.sub(r"\s+", " ", " ".join(parts))
    return re.sub(r"([：；]) ", r"\1", text).strip()
