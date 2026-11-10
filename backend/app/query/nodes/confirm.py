import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from app.logging import logger
from app.pipeline import stage
from app.prompts import PRODUCT_EXTRACT_SYSTEM, PRODUCT_EXTRACT_USER
from app.query.products import align_products, mentions_in_text
from app.query.state import QueryContext, QueryState

_HISTORY_TEXT_LIMIT = 300


@stage("confirm_product", "确认商品")
async def confirm_product(state: QueryState, runtime: Runtime[QueryContext]) -> dict:
    """弄清用户问的是哪个商品，并把问题改写成不依赖上下文的完整问题。

    "它怎么换电池？"这样的追问，单独拿去检索什么也查不到；
    结合历史对话补全成"ZG-12 数字万用表怎么换电池"之后才有意义。
    """
    context = runtime.context
    settings = context["settings"]
    question = state["question"]

    history = await context["history_store"].recent(state["session_id"], settings.history_messages)
    catalog = await context["vector_store"].list_products()
    if not catalog:
        return {"history": history, "options": [],
                "clarification": "知识库里还没有资料。请先在“知识库”页面导入商品手册，再来提问。",
                "_detail": "知识库为空"}

    extracted = await _extract(context["llm"], question, history, catalog)
    mentions = extracted["item_names"] or mentions_in_text(question, catalog)
    rewritten = extracted["rewritten_query"] or question

    if mentions:
        vectors = await context["embeddings"].embed(mentions)
        matches = {
            mention: await context["vector_store"].search_products(vector, limit=settings.product_max_options)
            for mention, vector in zip(mentions, vectors)
        }
        alignment = align_products(mentions, catalog, matches, settings.product_confirm_score,
                                   settings.product_option_score, settings.product_max_options)
        confirmed, options = alignment.confirmed, alignment.options
    else:
        # 问题里没提商品：沿用上一轮确认的商品；只有一个商品的知识库不需要确认
        confirmed = [name for name in _last_products(history) if name in catalog]
        if not confirmed and len(catalog) == 1:
            confirmed = list(catalog)
        options = []

    if confirmed:
        runtime.stream_writer({"type": "products", "items": confirmed, "rewritten_query": rewritten})
        return {"history": history, "products": confirmed, "rewritten_query": rewritten,
                "_detail": "、".join(confirmed)}
    if options:
        return {"history": history, "options": options, "clarification": "您问的是下面哪一款？",
                "_detail": f"{len(options)} 个候选"}
    return {"history": history, "options": catalog[:settings.product_max_options],
            "clarification": "我没能确定您问的是哪个商品。目前知识库里有这些商品的资料，请告诉我是哪一款：",
            "_detail": "未识别"}


async def _extract(llm, question: str, history: list[dict[str, Any]], catalog: list[str]) -> dict[str, Any]:
    """让模型提取商品叫法并改写问题。模型不可用或输出无法解析时返回空结果，由字面匹配兜底。"""
    empty = {"item_names": [], "rewritten_query": ""}
    prompt = PRODUCT_EXTRACT_USER.format(
        catalog="\n".join(f"- {name}" for name in catalog[:50]),
        history=format_history(history) or "（无）",
        query=question,
    )
    try:
        reply = await llm.ainvoke([SystemMessage(content=PRODUCT_EXTRACT_SYSTEM), HumanMessage(content=prompt)])
        data = parse_json_object(str(reply.content))
    except Exception as exc:
        logger.warning("商品提取失败，改用字面匹配：{}: {}", type(exc).__name__, exc)
        return empty
    names = data.get("item_names")
    rewritten = data.get("rewritten_query")
    return {
        "item_names": list(dict.fromkeys(
            name.strip() for name in names if isinstance(name, str) and name.strip())) if isinstance(names, list) else [],
        "rewritten_query": rewritten.strip() if isinstance(rewritten, str) else "",
    }


def parse_json_object(text: str) -> dict[str, Any]:
    """从模型输出中取出 JSON 对象，容忍代码块包裹和前后多余的文字。"""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except ValueError:
        match = re.search(r"\{.*\}", cleaned, re.S)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("模型输出不是 JSON 对象")
    return data


def format_history(history: list[dict[str, Any]]) -> str:
    labels = {"user": "用户", "assistant": "助手"}
    lines = [
        f"{labels[message['role']]}：{str(message.get('text', ''))[:_HISTORY_TEXT_LIMIT]}"
        for message in history
        if message.get("role") in labels and message.get("text")
    ]
    return "\n".join(lines)


def _last_products(history: list[dict[str, Any]]) -> list[str]:
    for message in reversed(history):
        if message.get("products"):
            return list(message["products"])
    return []
