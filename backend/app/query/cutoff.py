"""断崖截断：根据重排序分数的落差，动态决定给模型多少条资料。

固定取前 N 条有两个问题：相关资料只有 2 条时，后面几条是噪声；相关资料很多时又可能不够。
重排序后的分数通常会在"相关"与"不相关"之间出现一次明显的下跌，在那里截断即可。
"""
from typing import Any


def cliff_cutoff(documents: list[dict[str, Any]], min_k: int, max_k: int, gap_ratio: float, gap_abs: float,
                 min_score: float = 0.0) -> list[dict[str, Any]]:
    """documents 需已按 score 降序排列。

    - 分数低于 min_score 的一律丢弃（全部低于时返回空列表，表示没有相关资料）；
    - 找到第一处"断崖"——相邻分差达到 gap_abs，或相对分差达到 gap_ratio——在那里截断；
    - 结果至少 min_k 条、至多 max_k 条。断崖出现在 min_k 之前时保留 min_k 条，不再往后多取。
    """
    relevant = [doc for doc in documents if doc.get("score") is None or doc["score"] >= min_score]
    if not relevant:
        return []
    upper = min(max_k, len(relevant))
    lower = min(max(min_k, 1), upper)
    cut = upper
    for index in range(upper - 1):
        current, following = relevant[index].get("score"), relevant[index + 1].get("score")
        if current is None or following is None:
            continue
        gap = current - following
        if gap >= gap_abs or gap / (abs(current) + 1e-6) >= gap_ratio:
            cut = max(index + 1, lower)
            break
    return relevant[:cut]
