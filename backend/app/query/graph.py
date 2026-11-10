"""问答流程（LangGraph）。

    确认商品 ─┬─（需要澄清）─ 回复
              │
              ├─ 混合检索 ──┐
              ├─ HyDE 检索 ─┼─ 融合排序 ─ 重排序 ─ 生成回答
              └─ 联网搜索 ──┘
"""
from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.query.nodes.answer import generate_answer, respond_directly
from app.query.nodes.confirm import confirm_product
from app.query.nodes.rerank import rerank
from app.query.nodes.retrieve import fuse, hyde_search, vector_search, web_search
from app.query.state import QueryContext, QueryState

_RETRIEVERS = ["vector_search", "hyde_search", "web_search"]


def route_after_confirm(state: QueryState):
    """商品没确认就不检索；确认了则三路检索并行出发。"""
    return "respond_directly" if state.get("clarification") else _RETRIEVERS


def build_query_graph():
    graph = StateGraph(state_schema=QueryState, context_schema=QueryContext)
    graph.add_node("confirm_product", confirm_product)
    graph.add_node("respond_directly", respond_directly)
    graph.add_node("vector_search", vector_search)
    graph.add_node("hyde_search", hyde_search)
    graph.add_node("web_search", web_search)
    graph.add_node("fuse", fuse)
    graph.add_node("rerank", rerank)
    graph.add_node("generate_answer", generate_answer)

    graph.add_edge(START, "confirm_product")
    graph.add_conditional_edges("confirm_product", route_after_confirm, ["respond_directly", *_RETRIEVERS])
    graph.add_edge(_RETRIEVERS, "fuse")          # 三路全部完成后汇合
    graph.add_edge("fuse", "rerank")
    graph.add_edge("rerank", "generate_answer")
    graph.add_edge("respond_directly", END)
    graph.add_edge("generate_answer", END)
    return graph.compile()


query_graph = build_query_graph()
