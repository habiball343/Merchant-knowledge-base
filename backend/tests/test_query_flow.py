"""问答流程：用替身模型和内存存储驱动真实的 LangGraph 图。"""
import pytest

from app.query.graph import query_graph
from app.query.nodes.answer import NO_SOURCES_ANSWER, format_sources
from app.query.nodes.confirm import parse_json_object
from app.services.ingest_service import IngestService
from tests.fakes import FakeContainer, FakeReranker, FakeWebSearch, ScriptedLLM

MULTIMETER = """# ZG-12 数字万用表使用手册

## 测量直流电压

将旋钮转到直流电压档，红表笔接正极，黑表笔接负极，读取屏幕上的数值。若显示 OL，说明超出量程，请换用更高的量程后重新测量。测量高于 36V 的电压时，手指不要越过表笔的护指环，也不要在潮湿的环境中操作。测量结束后先取下红表笔，再取下黑表笔，最后把旋钮转回 OFF 位置，以免误触其他档位损坏仪表。

## 更换电池

屏幕出现电池符号时需要更换电池。拧开后盖的两颗螺丝，取出旧的 9V 电池，按正负极方向装入新电池后装回后盖。更换电池前必须先把表笔从被测电路上取下，并把旋钮转到 OFF 位置。长期不使用时请取出电池，以免漏液腐蚀电路板。废旧电池请按当地的规定分类回收，不要随生活垃圾丢弃。
"""

AIR_FRYER = """# ZG-3000 空气炸锅使用手册

## 首次使用

首次使用前请取出炸篮内的所有包装材料，用温水和洗洁精清洗炸篮和炸锅，擦干后空烧十分钟去除异味。空烧时可能会有少量白烟，属于正常现象，请保持厨房通风。空烧结束后等待机器冷却再开始烹饪。机器四周请留出至少十厘米的空间，不要紧贴墙面或者放在橱柜里使用。

## 清洁保养

每次使用后请等待机器完全冷却，再取出炸篮清洗。炸篮表面有不粘涂层，请使用软海绵，不要用钢丝球或者金属铲刮擦。机身外壳用拧干的湿布擦拭即可，不要把整机浸入水中，也不要放进洗碗机。发热管上的油渍可以在冷却后用软毛刷轻轻刷掉，每月清理一次即可。
"""


async def knowledge_base(tmp_path, llm=None, **kwargs) -> FakeContainer:
    """导入两份手册，得到一个有两个商品的知识库。"""
    container = FakeContainer(tmp_path, llm=llm or ScriptedLLM(), **kwargs)
    service = IngestService(container)
    await service.submit("ZG-12使用手册.md", MULTIMETER.encode("utf-8"), product="ZG-12 数字万用表")
    await service.submit("ZG-3000使用手册.md", AIR_FRYER.encode("utf-8"), product="ZG-3000 空气炸锅")
    await service.wait_idle()
    container.vector_store.searches.clear()
    container.embeddings.calls.clear()
    return container


async def ask(container, question, session_id="s1"):
    events, final = [], {}
    async for mode, chunk in query_graph.astream(
            {"session_id": session_id, "question": question},
            context=container.query_context(), stream_mode=["custom", "values"]):
        if mode == "custom":
            events.append(chunk)
        else:
            final = chunk
    return events, final


def stages(events, status="done"):
    return [event["node"] for event in events if event["type"] == "stage" and event["status"] == status]


async def test_full_pipeline_answers_from_the_confirmed_products_documents(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 数字万用表怎么测量直流电压"})
    container = await knowledge_base(tmp_path, llm=llm)

    events, final = await ask(container, "zg12 怎么测直流电压？")

    running = stages(events, "running")
    assert running[0] == "confirm_product"
    assert set(running[1:4]) == {"vector_search", "hyde_search", "web_search"}
    assert running[4:] == ["fuse", "rerank", "generate_answer"]
    assert final["products"] == ["ZG-12 数字万用表"]
    assert final["rewritten_query"] == "ZG-12 数字万用表怎么测量直流电压"
    # 两路检索都只在确认的商品范围内进行
    assert container.vector_store.searches == [
        {"query": "ZG-12 数字万用表怎么测量直流电压", "products": ["ZG-12 数字万用表"]}] * 2
    # 最相关的片段排在第一，且全部来自万用表的手册
    assert final["sources"][0]["title"] == "测量直流电压" and final["sources"][0]["index"] == 1
    assert {doc["product"] for doc in final["sources"]} == {"ZG-12 数字万用表"}
    assert set(final["sources"][0]["routes"]) == {"vector", "hyde"}
    # 回答逐段推送，拼起来就是完整回答
    deltas = "".join(event["text"] for event in events if event["type"] == "delta")
    assert deltas == final["answer"] == llm.answer
    assert [event["items"] for event in events if event["type"] == "products"] == [["ZG-12 数字万用表"]]
    sources_event = next(event for event in events if event["type"] == "sources")
    assert [item["index"] for item in sources_event["items"]] == [doc["index"] for doc in final["sources"]]
    assert "dense" not in sources_event["items"][0]


async def test_answer_prompt_contains_numbered_sources_products_and_question(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 数字万用表怎么更换电池"})
    container = await knowledge_base(tmp_path, llm=llm)

    await ask(container, "怎么换电池")

    prompt = llm.prompts["answer"][0]
    assert "[1] 来源：ZG-12使用手册｜ZG-12 数字万用表使用手册｜更换电池" in prompt
    assert "取出旧的 9V 电池" in prompt
    assert "【相关商品】\nZG-12 数字万用表" in prompt
    assert "【用户问题】\nZG-12 数字万用表怎么更换电池" in prompt
    assert "ZG-3000" not in prompt


async def test_hyde_embeds_the_question_together_with_the_hypothetical_passage(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 怎么测电压"},
                      hypothetical="假想的手册原文")
    container = await knowledge_base(tmp_path, llm=llm)

    await ask(container, "怎么测电压")

    embedded = [text for call in container.embeddings.calls for text in call]
    assert "ZG-12 怎么测电压\n假想的手册原文" in embedded
    assert "ZG-12" in llm.prompts["hyde"][0] and "ZG-12 怎么测电压" in llm.prompts["hyde"][0]


async def test_follow_up_question_reuses_the_product_from_the_previous_turn(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["ZG-3000"], "rewritten_query": "ZG-3000 空气炸锅第一次用要注意什么"})
    container = await knowledge_base(tmp_path, llm=llm)
    await ask(container, "ZG-3000 第一次用要注意什么")

    llm.extraction = {"item_names": [], "rewritten_query": ""}        # 模型没能从追问里提取出商品
    events, final = await ask(container, "那机身外壳怎么擦拭")

    assert final["products"] == ["ZG-3000 空气炸锅"]
    assert "历史对话" in llm.prompts["extract"][1] and "ZG-3000 第一次用要注意什么" in llm.prompts["extract"][1]
    assert final["sources"][0]["title"] == "清洁保养"
    assert [message["role"] for message in container.history.messages] == ["user", "assistant"] * 2
    assert container.history.messages[-1]["products"] == ["ZG-3000 空气炸锅"]


async def test_unspecified_product_asks_the_user_to_choose_without_searching(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": [], "rewritten_query": "怎么清洁"})
    container = await knowledge_base(tmp_path, llm=llm)

    events, final = await ask(container, "怎么清洁")

    assert stages(events) == ["confirm_product", "respond_directly"]
    assert final["options"] == ["ZG-12 数字万用表", "ZG-3000 空气炸锅"]
    assert "哪" in final["answer"] and final["clarification"] == final["answer"]
    assert container.vector_store.searches == [] and "answer" not in llm.prompts
    options_event = next(event for event in events if event["type"] == "options")
    assert options_event["items"] == final["options"]
    assert container.history.messages[-1]["text"] == final["answer"]


async def test_ambiguous_name_offers_only_the_matching_products(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["万用表"], "rewritten_query": "万用表怎么换电池"})
    container = await knowledge_base(tmp_path, llm=llm)
    await container.vector_store.upsert_product("ZG-20 数字万用表", [0.0] * 64)

    _, final = await ask(container, "万用表怎么换电池")

    assert final["options"] == ["ZG-12 数字万用表", "ZG-20 数字万用表"]
    assert final["answer"] == "您问的是下面哪一款？"


async def test_single_product_knowledge_base_needs_no_confirmation(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": [], "rewritten_query": "怎么更换电池"})
    container = FakeContainer(tmp_path, llm=llm)
    service = IngestService(container)
    await service.submit("ZG-12使用手册.md", MULTIMETER.encode("utf-8"), product="ZG-12 数字万用表")
    await service.wait_idle()

    _, final = await ask(container, "怎么更换电池")

    assert final["products"] == ["ZG-12 数字万用表"] and final["sources"][0]["title"] == "更换电池"


async def test_empty_knowledge_base_says_so(container):
    events, final = await ask(container, "怎么换电池")

    assert "还没有资料" in final["answer"] and final["options"] == []
    assert stages(events) == ["confirm_product", "respond_directly"]


@pytest.mark.parametrize("extraction", ["我觉得用户问的是万用表", RuntimeError("模型超时")])
async def test_model_trouble_during_extraction_falls_back_to_literal_matching(tmp_path, extraction):
    llm = ScriptedLLM()
    if isinstance(extraction, Exception):
        llm.error, llm.fail_kinds = extraction, ("extract",)
    else:
        llm.extraction = extraction
    container = await knowledge_base(tmp_path, llm=llm)

    _, final = await ask(container, "ZG-12 怎么更换电池")

    assert final["products"] == ["ZG-12 数字万用表"]
    assert final["rewritten_query"] == "ZG-12 怎么更换电池"
    assert final["sources"][0]["title"] == "更换电池"


async def test_hyde_failure_is_skipped_and_the_other_route_still_answers(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 怎么更换电池"},
                      error=RuntimeError("模型限流"), fail_kinds=("hyde",))
    container = await knowledge_base(tmp_path, llm=llm)

    events, final = await ask(container, "ZG-12 怎么更换电池")

    skipped = {event["node"]: event["detail"] for event in events if event.get("status") == "skipped"}
    assert "假想文档生成失败" in skipped["hyde_search"] and skipped["web_search"] == "未启用"
    assert final["sources"][0]["routes"] == ["vector"] and final["answer"] == llm.answer


async def test_web_results_are_reranked_together_with_knowledge_base_hits(tmp_path):
    web = FakeWebSearch([{"title": "万用表电池更换指南", "url": "https://example.com/battery",
                          "snippet": "ZG-12 数字万用表更换电池：拧开后盖螺丝，取出 9V 电池。"},
                         {"title": "无关网页", "url": "https://example.com/other", "snippet": ""}])
    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 数字万用表怎么更换电池"})
    container = await knowledge_base(tmp_path, llm=llm, web_search=web)

    _, final = await ask(container, "ZG-12 怎么更换电池")

    assert web.queries == ["ZG-12 数字万用表怎么更换电池"]
    web_sources = [doc for doc in final["sources"] if doc["source"] == "web"]
    assert [doc["url"] for doc in web_sources] == ["https://example.com/battery"]
    assert f"[{web_sources[0]['index']}] 来源：web｜万用表电池更换指南｜https://example.com/battery" in llm.prompts["answer"][0]


async def test_reranker_outage_degrades_to_fused_order(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 怎么更换电池"})
    container = await knowledge_base(tmp_path, llm=llm, reranker=FakeReranker(available=False))

    events, final = await ask(container, "ZG-12 怎么更换电池")

    assert final["sources"] and all(doc["score"] is None for doc in final["sources"])
    rerank_done = next(event for event in events if event.get("node") == "rerank" and event["status"] == "done")
    assert "重排序不可用" in rerank_done["detail"]
    assert final["answer"] == llm.answer


async def test_no_relevant_sources_gives_a_fixed_answer_without_calling_the_model(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 支持蓝牙吗"})
    container = await knowledge_base(tmp_path, llm=llm, rerank_min_score=0.99)

    events, final = await ask(container, "ZG-12 支持蓝牙吗")

    assert final["sources"] == [] and final["answer"] == NO_SOURCES_ANSWER
    assert "answer" not in llm.prompts
    assert "".join(event["text"] for event in events if event["type"] == "delta") == NO_SOURCES_ANSWER


async def test_history_write_failure_does_not_fail_the_answer(tmp_path):
    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 怎么更换电池"})
    container = await knowledge_base(tmp_path, llm=llm)
    container.history.fail_on_append = True

    _, final = await ask(container, "ZG-12 怎么更换电池")

    assert final["answer"] == llm.answer


async def test_answer_generation_failure_propagates(tmp_path):
    class ProviderError(Exception):
        status_code = 402

    llm = ScriptedLLM(extraction={"item_names": ["ZG-12"], "rewritten_query": "ZG-12 怎么更换电池"},
                      error=ProviderError("insufficient balance"), fail_kinds=("answer",))
    container = await knowledge_base(tmp_path, llm=llm)

    with pytest.raises(ProviderError):
        await ask(container, "ZG-12 怎么更换电池")


@pytest.mark.parametrize("text,expected", [
    ('{"item_names": ["A"], "rewritten_query": "q"}', {"item_names": ["A"], "rewritten_query": "q"}),
    ('```json\n{"item_names": []}\n```', {"item_names": []}),
    ('好的，结果如下：{"item_names": ["A"]} 希望有帮助', {"item_names": ["A"]}),
])
def test_parse_json_object_tolerates_wrapping(text, expected):
    assert parse_json_object(text) == expected


def test_parse_json_object_rejects_non_objects():
    with pytest.raises(ValueError):
        parse_json_object("没有 JSON")
    with pytest.raises(ValueError):
        parse_json_object('["A"]')


def test_format_sources_respects_the_character_budget_but_keeps_at_least_one():
    sources = [{"index": index, "source": "knowledge", "file_title": "手册", "parent_title": "", "title": f"第{index}节",
                "url": "", "content": "内容" * 50} for index in range(1, 6)]

    assert format_sources(sources, 250).count("来源：") == 2
    assert format_sources(sources, 10).count("来源：") == 1
    assert format_sources([], 100) == "（无）"
