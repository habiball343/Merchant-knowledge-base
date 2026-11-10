from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from app.logging import logger
from app.pipeline import stage
from app.prompts import ANSWER_SYSTEM, ANSWER_USER
from app.query.nodes.confirm import format_history
from app.query.nodes.rerank import public_source
from app.query.state import QueryContext, QueryState

NO_SOURCES_ANSWER = "现有资料中没有找到与这个问题相关的内容。可以换一种问法，或者先导入相关的资料。"
GENERATION_FAILED_ANSWER = "生成回答时出错了，请稍后再试。"


@stage("respond_directly", "回复")
async def respond_directly(state: QueryState, runtime: Runtime[QueryContext]) -> dict:
    """不需要检索的情况（请用户澄清商品、知识库为空）：直接回复提示语。"""
    answer = state["clarification"]
    runtime.stream_writer({"type": "options", "message": answer, "items": state.get("options") or []})
    await _save_turn(runtime.context["history_store"], state, answer, products=[], sources=[])
    return {"answer": answer}


@stage("generate_answer", "生成回答")
async def generate_answer(state: QueryState, runtime: Runtime[QueryContext]) -> dict:
    """把筛选后的资料交给模型作答，逐字推送给页面。没有相关资料时直接说明，不让模型硬编。"""
    context = runtime.context
    sources = state.get("sources") or []
    if not sources:
        answer = NO_SOURCES_ANSWER
        runtime.stream_writer({"type": "delta", "text": answer})
    else:
        prompt = build_answer_prompt(state, context["settings"].max_context_chars)
        answer = ""
        try:
            async for chunk in context["llm"].astream(
                    [SystemMessage(content=ANSWER_SYSTEM), HumanMessage(content=prompt)]):
                text = chunk.content if isinstance(chunk.content, str) else ""
                if text:
                    answer += text
                    runtime.stream_writer({"type": "delta", "text": text})
        except Exception as exc:
            logger.error("回答生成失败：{}: {}", type(exc).__name__, exc)
            if not answer:
                raise
        answer = answer.strip() or GENERATION_FAILED_ANSWER

    await _save_turn(context["history_store"], state, answer, products=state.get("products") or [],
                     sources=[public_source(doc) for doc in sources])
    return {"answer": answer, "_detail": f"{len(answer)} 字"}


def build_answer_prompt(state: QueryState, max_context_chars: int) -> str:
    return ANSWER_USER.format(
        products="、".join(state.get("products") or []) or "（未指定）",
        context=format_sources(state.get("sources") or [], max_context_chars),
        history=format_history(state.get("history") or []) or "（无）",
        question=state.get("rewritten_query") or state["question"],
    )


def format_sources(sources: list[dict[str, Any]], max_chars: int) -> str:
    """按编号排版参考资料，超出字符预算的部分不再放入。"""
    blocks: list[str] = []
    used = 0
    for doc in sources:
        if doc["source"] == "web":
            origin = f"web｜{doc['title']}｜{doc['url']}"
        else:
            origin = "｜".join(part for part in (doc["file_title"], doc["parent_title"], doc["title"]) if part)
        block = f"[{doc['index']}] 来源：{origin}\n{doc['content']}"
        if blocks and used + len(block) > max_chars:
            break
        blocks.append(block)
        used += len(block) + 2
    return "\n\n".join(blocks) or "（无）"


async def _save_turn(history_store, state: QueryState, answer: str, products: list[str],
                     sources: list[dict[str, Any]]) -> None:
    """写入对话历史。历史只是辅助，写失败不应该让这次问答失败。"""
    try:
        await history_store.append(state["session_id"], "user", state["question"],
                                   rewritten_query=state.get("rewritten_query", ""), products=products)
        await history_store.append(state["session_id"], "assistant", answer, products=products, sources=sources)
    except Exception as exc:
        logger.warning("对话历史写入失败：{}: {}", type(exc).__name__, exc)
