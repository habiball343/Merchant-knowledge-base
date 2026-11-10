import re

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.runtime import Runtime

from app.ingest.state import IngestContext, IngestState
from app.logging import logger
from app.pipeline import stage
from app.prompts import PRODUCT_NAME_SYSTEM, PRODUCT_NAME_USER
from app.query.products import normalize

_MAX_NAME_CHARS = 40


@stage("recognize_product", "识别商品")
async def recognize_product(state: IngestState, runtime: Runtime[IngestContext]) -> dict:
    """确定这份资料属于哪个商品。

    每个片段都会打上商品名，问答时先确认用户问的是哪个商品，再只在它的资料里检索——
    不同型号的手册内容往往高度相似，混在一起检索很容易答错型号。
    """
    context = runtime.context

    if state.get("product_given") and state.get("product"):
        name, source = clean_product_name(state["product"]) or state["file_title"], "上传时指定"
    else:
        name, source = await _ask_model(state, context), "模型识别"
        if not name:
            name, source = state["file_title"], "沿用文件名"

    # 与已有商品对齐：同一商品的多份资料应该归到同一个名字下。
    # 只按字面归并（忽略大小写、空格和连接符）——型号相近的不同商品名称向量几乎一样，不能靠相似度判断。
    if not state.get("product_given"):
        existing = next((item for item in await context["vector_store"].list_products()
                         if normalize(item) == normalize(name)), None)
        if existing and existing != name:
            name, source = existing, "归入已有商品"
    vector = await context["embeddings"].embed_one(name)

    chunks = [{**chunk, "product": name} for chunk in state["chunks"]]
    return {"product": name, "product_vector": vector, "chunks": chunks, "_detail": f"{name}（{source}）"}


async def _ask_model(state: IngestState, context: IngestContext) -> str:
    budget = context["settings"].product_context_chars
    excerpt = "\n\n".join(chunk["content"] for chunk in state["chunks"][:6])[:budget]
    try:
        reply = await context["llm"].ainvoke([
            SystemMessage(content=PRODUCT_NAME_SYSTEM),
            HumanMessage(content=PRODUCT_NAME_USER.format(file_title=state["file_title"], context=excerpt)),
        ])
    except Exception as exc:
        logger.warning("商品名识别失败，沿用文件名：{}: {}", type(exc).__name__, exc)
        return ""
    return clean_product_name(str(reply.content))


def clean_product_name(text: str) -> str:
    """从模型输出中取出商品名：第一行、去掉引号和书名号；无法判断时返回空串。"""
    line = next((item.strip() for item in (text or "").splitlines() if item.strip()), "")
    line = re.sub(r"^(商品名称?|产品名称?)\s*[:：]\s*", "", line)
    line = line.strip("\"'“”‘’「」『』《》`*。.， ")
    # 商品名不会是一句话：过长，或带有句读，说明模型给的是解释而不是名称
    if not line or "UNKNOWN" in line.upper() or len(line) > _MAX_NAME_CHARS or re.search(r"[，。；！？]", line):
        return ""
    return line
