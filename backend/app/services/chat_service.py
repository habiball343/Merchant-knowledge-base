"""问答服务：驱动问答流程，把进度、资料和回答整理成一串事件。"""
import uuid
from typing import Any, AsyncIterator

from app.logging import logger
from app.query.graph import query_graph
from app.query.nodes.rerank import public_source

# 模型服务的常见失败，翻译成使用者能直接处理的提示
_LLM_ERROR_MESSAGES = {
    401: "模型密钥无效，请检查 .env 中的 LLM_API_KEY。",
    402: "模型账户余额不足，请充值后重新提问。",
    429: "模型服务限流，请稍后再试。",
}


def describe_failure(exc: Exception) -> str:
    """把问答过程中的异常翻译成给使用者看的一句话。"""
    status = getattr(exc, "status_code", None)
    if status in _LLM_ERROR_MESSAGES:
        return _LLM_ERROR_MESSAGES[status]
    name = type(exc).__name__
    if "Timeout" in name:
        return "模型服务响应超时，请稍后再试。"
    if "Connection" in name:
        return "连不上模型服务。请检查网络，以及 .env 中的 LLM_BASE_URL 是否正确。"
    return "问答失败。请检查服务状态，详细原因见后端日志。"


class ChatService:
    def __init__(self, container):
        self._container = container

    async def stream(self, question: str, session_id: str | None = None) -> AsyncIterator[dict[str, Any]]:
        """逐条产出事件：session → 若干 stage / products / sources / delta → final 或 error。"""
        session_id = session_id or uuid.uuid4().hex
        yield {"type": "session", "session_id": session_id}
        if not self._container.llm_configured:
            yield {"type": "error", "message": "尚未配置模型密钥。请在 .env 中设置 LLM_API_KEY 后重启服务。"}
            return

        final: dict[str, Any] = {}
        try:
            async for mode, chunk in query_graph.astream(
                    {"session_id": session_id, "question": question},
                    context=self._container.query_context(), stream_mode=["custom", "values"]):
                if mode == "custom":
                    yield chunk
                else:
                    final = chunk
        except Exception as exc:
            # 第三方的原始报错可能带有地址和密钥片段，只写日志，不返回给页面
            logger.exception("问答失败：{} (status={})", type(exc).__name__, getattr(exc, "status_code", None))
            yield {"type": "error", "message": describe_failure(exc)}
            return

        clarifying = bool(final.get("clarification"))
        yield {
            "type": "final",
            "session_id": session_id,
            "answer": final.get("answer", ""),
            "products": final.get("products") or [],
            "rewritten_query": final.get("rewritten_query", ""),
            "sources": [public_source(doc) for doc in final.get("sources") or []],
            "options": (final.get("options") or []) if clarifying else [],
            "needs_clarification": clarifying,
        }

    async def ask(self, question: str, session_id: str | None = None) -> dict[str, Any]:
        """非流式调用：等流程跑完，只返回最终结果。"""
        result: dict[str, Any] = {}
        async for event in self.stream(question, session_id):
            if event["type"] == "session":
                result["session_id"] = event["session_id"]
            elif event["type"] in ("final", "error"):
                result.update(event)
        return result
