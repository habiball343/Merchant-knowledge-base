from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from app.pipeline import stage
from app.prompts import HYDE_SYSTEM, HYDE_USER
from app.query.fusion import rrf_fuse
from app.query.state import QueryContext, QueryState


@stage("vector_search", "混合检索")
async def vector_search(state: QueryState, runtime: Runtime[QueryContext]) -> dict:
    """用问题本身检索：语义向量找意思相近的片段，BM25 找字面命中的片段（型号、参数、专有名词）。"""
    context = runtime.context
    query = state["rewritten_query"]
    dense = await context["embeddings"].embed_one(query)
    hits = await context["vector_store"].hybrid_search(
        query, dense, state["products"], context["settings"].retrieval_top_k)
    return {"vector_hits": hits, "_detail": f"{len(hits)} 条"}


@stage("hyde_search", "HyDE 检索")
async def hyde_search(state: QueryState, runtime: Runtime[QueryContext]) -> dict:
    """HyDE（Hypothetical Document Embeddings）：先让模型写一段"假想的手册原文"，再用它去检索。

    问题通常很短，而资料是成段的陈述；假想答案在措辞和长度上更接近真正的资料，
    用它的向量去找，能补上问题向量够不着的片段。假想内容本身不会进入答案。
    """
    context = runtime.context
    query = state["rewritten_query"]
    products = "、".join(state["products"])
    try:
        reply = await context["llm"].ainvoke([
            SystemMessage(content=HYDE_SYSTEM.format(products=products)),
            HumanMessage(content=HYDE_USER.format(products=products, query=query)),
        ])
        hypothetical = str(reply.content).strip()
    except Exception as exc:
        return {"hyde_hits": [], "_skipped": f"假想文档生成失败（{type(exc).__name__}）"}
    if not hypothetical:
        return {"hyde_hits": [], "_skipped": "模型没有返回内容"}

    dense = await context["embeddings"].embed_one(f"{query}\n{hypothetical}")
    hits = await context["vector_store"].hybrid_search(
        query, dense, state["products"], context["settings"].retrieval_top_k)
    return {"hyde_hits": hits, "_detail": f"{len(hits)} 条"}


@stage("web_search", "联网搜索")
async def web_search(state: QueryState, runtime: Runtime[QueryContext]) -> dict:
    searcher = runtime.context["web_search"]
    if searcher is None:
        return {"web_hits": [], "_skipped": "未启用"}
    hits = await searcher.search(state["rewritten_query"])
    return {"web_hits": hits, "_detail": f"{len(hits)} 条"}


@stage("fuse", "融合排序")
async def fuse(state: QueryState, runtime: Runtime[QueryContext]) -> dict:
    """用 RRF 合并两路知识库检索的结果。联网结果没有可比的名次，留到重排序阶段一起打分。"""
    settings = runtime.context["settings"]
    fused = rrf_fuse(
        {"vector": state.get("vector_hits") or [], "hyde": state.get("hyde_hits") or []},
        k=settings.rrf_k, top_k=settings.fused_top_k)
    return {"fused": fused, "_detail": f"{len(fused)} 条候选"}
