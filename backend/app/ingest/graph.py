"""文档导入流程（LangGraph）。

    检查文件 ─┬─ 解析 PDF ──────┬─ 处理图片 ─ 切分文档 ─ 识别商品 ─ 向量化 ─ 写入知识库
              └─ 读取 Markdown ─┘
"""
from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.ingest.nodes.images import process_images
from app.ingest.nodes.load import check_file, parse_pdf, read_markdown
from app.ingest.nodes.product import recognize_product
from app.ingest.nodes.split import split_document
from app.ingest.nodes.store import embed_chunks, store_chunks
from app.ingest.state import IngestContext, IngestState

# 各阶段开始时的大致进度，用于页面上的进度条
STAGE_PROGRESS = {
    "check_file": 2,
    "parse_pdf": 5,
    "read_markdown": 5,
    "process_images": 35,
    "split_document": 55,
    "recognize_product": 60,
    "embed_chunks": 70,
    "store_chunks": 92,
}


def build_ingest_graph():
    graph = StateGraph(state_schema=IngestState, context_schema=IngestContext)
    graph.add_node("check_file", check_file)
    graph.add_node("parse_pdf", parse_pdf)
    graph.add_node("read_markdown", read_markdown)
    graph.add_node("process_images", process_images)
    graph.add_node("split_document", split_document)
    graph.add_node("recognize_product", recognize_product)
    graph.add_node("embed_chunks", embed_chunks)
    graph.add_node("store_chunks", store_chunks)

    graph.add_edge(START, "check_file")
    graph.add_conditional_edges(
        "check_file",
        lambda state: "parse_pdf" if state["kind"] == "pdf" else "read_markdown",
        {"parse_pdf": "parse_pdf", "read_markdown": "read_markdown"},
    )
    graph.add_edge("parse_pdf", "process_images")
    graph.add_edge("read_markdown", "process_images")
    graph.add_edge("process_images", "split_document")
    graph.add_edge("split_document", "recognize_product")
    graph.add_edge("recognize_product", "embed_chunks")
    graph.add_edge("embed_chunks", "store_chunks")
    graph.add_edge("store_chunks", END)
    return graph.compile()


ingest_graph = build_ingest_graph()
