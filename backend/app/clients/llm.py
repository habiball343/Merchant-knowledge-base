"""大模型客户端：对话模型与视觉模型，均通过 OpenAI 兼容协议接入。"""
import base64

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.config import Settings


def build_chat_model(settings: Settings, model: str | None = None, temperature: float | None = None) -> ChatOpenAI:
    return ChatOpenAI(
        model=model or settings.llm_model,
        api_key=settings.llm_api_key or "not-configured",
        base_url=settings.llm_base_url,
        temperature=settings.llm_temperature if temperature is None else temperature,
        timeout=90,
        max_retries=1,
    )


class VisionCaptioner:
    """用视觉模型为资料中的图片写一句说明。

    说明文字会写进图片的 alt 文本，随正文一起被切片和检索——这样"接线图""按键示意图"
    这类只存在于图片里的信息也能被问到。
    """

    def __init__(self, model: ChatOpenAI):
        self._model = model

    async def caption(self, image: bytes, mime_type: str, document_title: str, context: str) -> str:
        data_url = f"data:{mime_type};base64,{base64.b64encode(image).decode('ascii')}"
        prompt = (
            "任务：为产品资料中的一张图片写一个简短的中文说明。\n"
            f"所属资料：《{document_title}》\n"
            f"图片附近的正文：\n{context or '（无）'}\n\n"
            "请结合图片内容和上面的正文，用一句话概括这张图片展示了什么（不超过 40 个字）。"
            "只输出说明本身，不要以“图片”“这张图”开头，不要加引号或句号。"
        )
        reply = await self._model.ainvoke([HumanMessage(content=[
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ])])
        return str(reply.content).strip()
