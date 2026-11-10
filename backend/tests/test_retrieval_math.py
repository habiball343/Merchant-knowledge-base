"""融合排序、断崖截断与商品对齐：三个纯函数。"""
import pytest

from app.query.cutoff import cliff_cutoff
from app.query.fusion import rrf_fuse
from app.query.products import align_products, mentions_in_text, model_tokens, normalize


def hits(*ids):
    return [{"chunk_id": chunk_id, "content": f"内容 {chunk_id}"} for chunk_id in ids]


# ---------------------------------------------------------------- RRF

def test_documents_found_by_both_routes_rank_first():
    fused = rrf_fuse({"vector": hits("a", "b", "c"), "hyde": hits("c", "d", "a")}, k=60)

    assert [doc["chunk_id"] for doc in fused[:2]] == ["a", "c"]
    assert fused[0]["rrf_score"] == pytest.approx(1 / 61 + 1 / 63)
    assert fused[0]["routes"] == ["vector", "hyde"]
    assert {doc["chunk_id"]: doc["routes"] for doc in fused}["d"] == ["hyde"]


def test_rrf_respects_top_k_weights_and_ignores_duplicates_and_missing_ids():
    routes = {"vector": hits("a", "a", "b") + [{"content": "没有编号"}], "hyde": hits("b")}

    fused = rrf_fuse(routes, k=60, top_k=1, weights={"hyde": 3.0})

    assert [doc["chunk_id"] for doc in fused] == ["b"]
    assert fused[0]["rrf_score"] == pytest.approx(1 / 62 + 3 / 61)


def test_rrf_of_nothing_is_empty():
    assert rrf_fuse({"vector": [], "hyde": []}) == []


# ---------------------------------------------------------------- 断崖截断

def scored(*scores):
    return [{"index": index, "score": score} for index, score in enumerate(scores)]


def test_cuts_at_the_first_cliff_after_the_minimum():
    kept = cliff_cutoff(scored(0.96, 0.91, 0.88, 0.21, 0.19), min_k=2, max_k=6, gap_ratio=0.5, gap_abs=0.3)
    assert [doc["score"] for doc in kept] == [0.96, 0.91, 0.88]


def test_keeps_the_minimum_even_when_the_cliff_comes_earlier():
    kept = cliff_cutoff(scored(0.95, 0.30, 0.28, 0.27), min_k=2, max_k=6, gap_ratio=0.5, gap_abs=0.3)
    assert len(kept) == 2


def test_without_a_cliff_the_maximum_applies():
    kept = cliff_cutoff(scored(0.9, 0.88, 0.86, 0.84, 0.82, 0.80, 0.78), min_k=2, max_k=4, gap_ratio=0.5, gap_abs=0.3)
    assert len(kept) == 4


def test_relative_gap_catches_cliffs_among_low_scores():
    kept = cliff_cutoff(scored(0.30, 0.28, 0.10, 0.09), min_k=1, max_k=6, gap_ratio=0.5, gap_abs=0.3)
    assert [doc["score"] for doc in kept] == [0.30, 0.28]


def test_irrelevant_documents_are_dropped_entirely():
    assert cliff_cutoff(scored(0.01, 0.005), min_k=2, max_k=6, gap_ratio=0.5, gap_abs=0.3, min_score=0.02) == []
    kept = cliff_cutoff(scored(0.9, 0.01), min_k=2, max_k=6, gap_ratio=0.5, gap_abs=0.3, min_score=0.02)
    assert [doc["score"] for doc in kept] == [0.9]


def test_documents_without_scores_are_kept_in_order():
    kept = cliff_cutoff([{"score": None}] * 5, min_k=2, max_k=3, gap_ratio=0.5, gap_abs=0.3, min_score=0.02)
    assert len(kept) == 3


# ---------------------------------------------------------------- 商品对齐

CATALOG = ["ZG-12 数字万用表", "ZG-20 数字万用表", "ZG-3000 空气炸锅"]


def test_exact_and_partial_names_are_confirmed_without_vectors():
    assert align_products(["zg12数字万用表"], CATALOG, {}).confirmed == ["ZG-12 数字万用表"]
    assert align_products(["ZG-12"], CATALOG, {}).confirmed == ["ZG-12 数字万用表"]
    assert align_products(["空气炸锅"], CATALOG, {}).confirmed == ["ZG-3000 空气炸锅"]


def test_name_shared_by_several_products_becomes_options():
    alignment = align_products(["万用表"], CATALOG, {})

    assert alignment.confirmed == []
    assert alignment.options == ["ZG-12 数字万用表", "ZG-20 数字万用表"]


def test_vector_match_confirms_only_a_clear_winner():
    clear = {"钳形表": [{"name": "ZG-20 钳形万用表", "score": 0.73}, {"name": "ZG-12 数字万用表", "score": 0.45}]}
    assert align_products(["钳形表"], CATALOG, clear).confirmed == ["ZG-20 钳形万用表"]

    tie = {"电压表": [{"name": "ZG-12 数字万用表", "score": 0.86}, {"name": "ZG-20 数字万用表", "score": 0.83}]}
    alignment = align_products(["电压表"], CATALOG, tie)
    assert alignment.confirmed == [] and alignment.options == ["ZG-12 数字万用表", "ZG-20 数字万用表"]


def test_a_different_model_number_is_never_confirmed_however_similar_the_name():
    # 真实向量模型给出的相似度："ZG-13 数字万用表" 与 "ZG-12 数字万用表" 高达 0.915
    lookalike = {"ZG-13 数字万用表": [{"name": "ZG-12 数字万用表", "score": 0.915},
                                   {"name": "ZG-20 数字万用表", "score": 0.72}]}
    alignment = align_products(["ZG-13 数字万用表"], CATALOG, lookalike)
    assert alignment.confirmed == [] and alignment.options == ["ZG-12 数字万用表"]

    other_brand = {"XY-9 数字万用表": [{"name": "ZG-12 数字万用表", "score": 0.709}]}
    assert align_products(["XY-9 数字万用表"], CATALOG, other_brand).confirmed == []

    same_model = {"ZG-12 万用表": [{"name": "ZG-12 数字万用表", "score": 0.905}, {"name": "ZG-20 数字万用表", "score": 0.787}]}
    assert align_products(["ZG-12 万用表"], CATALOG, same_model).confirmed == ["ZG-12 数字万用表"]
    assert model_tokens("ZG-12 和 zg3000，容量 4.5 升") == {"zg12", "zg3000"}


def test_weak_vector_matches_become_options_and_very_weak_ones_are_ignored():
    weak = {"电烤锅": [{"name": "ZG-3000 空气炸锅", "score": 0.66}, {"name": "ZG-12 数字万用表", "score": 0.31}]}
    alignment = align_products(["电烤锅"], CATALOG, weak)
    assert alignment.confirmed == [] and alignment.options == ["ZG-3000 空气炸锅"]

    unknown = {"洗衣机": [{"name": "ZG-3000 空气炸锅", "score": 0.42}]}
    alignment = align_products(["洗衣机"], CATALOG, unknown)
    assert alignment.confirmed == [] and alignment.options == []


def test_several_products_can_be_confirmed_but_outliers_are_dropped():
    both = align_products(["ZG-12", "ZG-3000"], CATALOG, {})
    assert both.confirmed == ["ZG-12 数字万用表", "ZG-3000 空气炸锅"]

    matches = {"表": [{"name": "ZG-20 数字万用表", "score": 0.81}]}
    mixed = align_products(["ZG-12", "表"], ["ZG-12 数字万用表", "ZG-20 数字万用表"], {"表": matches["表"]},
                           outlier_margin=0.15)
    # "表" 同时是两个商品名的一部分，走的是候选；确认的只有 ZG-12
    assert mixed.confirmed == ["ZG-12 数字万用表"]


def test_confirmed_products_never_appear_among_options():
    alignment = align_products(["ZG-12", "万用表"], CATALOG, {})
    assert alignment.confirmed == ["ZG-12 数字万用表"]
    assert alignment.options == ["ZG-20 数字万用表"]


def test_mentions_in_text_finds_full_names_and_model_numbers():
    assert mentions_in_text("zg12怎么换电池？", CATALOG) == ["ZG-12 数字万用表"]
    assert mentions_in_text("ZG-3000 空气炸锅 能烤红薯吗", CATALOG) == ["ZG-3000 空气炸锅"]
    assert mentions_in_text("怎么换电池", CATALOG) == []
    assert normalize("ZG - 12（新款）") == "zg12新款"


# ---------------------------------------------------------------- 资料摘要

def test_source_snippet_is_plain_text_without_markdown_markup():
    from app.query.nodes.rerank import plain_text

    markdown = (
        "## 技术参数\n\n| 项目 | 参数 |\n| --- | --- |\n| 显示 | 3¾ 位液晶屏 |\n| 电源 | **9V** 电池 |\n\n"
        "### 保修\n\n- 整机保修 `12` 个月\n- 详见[保修卡](https://example.com/card)\n\n![控制面板示意图](/api/files/a/b.png)\n"
        "```\ncode\n```\n1. 第一步"
    )

    assert plain_text(markdown, skip_heading="技术参数、保修") == (
        "项目，参数；显示，3¾ 位液晶屏；电源，9V 电池；整机保修 12 个月 详见保修卡 （图：控制面板示意图） code 1. 第一步")
    assert plain_text("# 概述\n\n正文", skip_heading="别的标题") == "概述：正文"
    assert plain_text("") == ""


def test_public_source_snippet_is_shortened_and_keeps_full_content():
    from app.query.nodes.rerank import public_source

    content = "## 更换电池\n\n" + "拧开后盖。" * 60
    doc = {"index": 1, "source": "knowledge", "product": "P", "file_title": "F", "title": "更换电池", "parent_title": "",
           "url": "", "doc_id": "d", "chunk_id": "d-0000", "score": 0.91234, "routes": ["vector"], "content": content}

    card = public_source(doc)

    assert card["snippet"].startswith("拧开后盖。") and card["snippet"].endswith("…") and len(card["snippet"]) == 161
    assert card["content"] == content and card["score"] == 0.9123
