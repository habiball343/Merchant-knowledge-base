"""RRF（Reciprocal Rank Fusion，倒数排名融合）。

不同检索路的分数不可比（余弦相似度、BM25、混合得分的量纲都不一样），
RRF 只看每条结果在各路中的名次：score(d) = Σ 权重 / (k + 名次)。
在多路中都排名靠前的结果得分最高，k 用来压低单路头部结果的优势，通常取 60。
"""
from typing import Any


def rrf_fuse(routes: dict[str, list[dict[str, Any]]], k: int = 60, top_k: int | None = None,
             weights: dict[str, float] | None = None, key: str = "chunk_id") -> list[dict[str, Any]]:
    """融合多路检索结果。返回的每条结果带上 rrf_score 和命中它的路名 routes。"""
    scores: dict[Any, float] = {}
    documents: dict[Any, dict[str, Any]] = {}
    hit_by: dict[Any, list[str]] = {}
    for route, hits in routes.items():
        weight = (weights or {}).get(route, 1.0)
        seen: set[Any] = set()
        rank = 0
        for hit in hits:
            identity = hit.get(key)
            if identity is None or identity in seen:
                continue
            seen.add(identity)
            rank += 1
            scores[identity] = scores.get(identity, 0.0) + weight / (k + rank)
            documents.setdefault(identity, hit)
            hit_by.setdefault(identity, []).append(route)

    ranked = sorted(scores, key=lambda identity: scores[identity], reverse=True)
    if top_k:
        ranked = ranked[:top_k]
    return [{**documents[identity], "rrf_score": scores[identity], "routes": hit_by[identity]} for identity in ranked]
