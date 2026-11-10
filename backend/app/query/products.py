"""商品对齐：把用户口中的商品叫法对应到知识库里的标准商品名。

用户说"ZG12""那个万用表"，知识库里叫"ZG-12 数字万用表"。对齐分两步：
先看字面——叫法是否就是某个商品名或它的一部分；字面对不上再看向量相似度。
结果有三种：确认（可以直接检索）、候选（请用户选）、无法识别。
"""
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Alignment:
    confirmed: list[str] = field(default_factory=list)
    options: list[str] = field(default_factory=list)


def normalize(name: str) -> str:
    """忽略大小写、空白和连接符："ZG 12""zg-12""ZG12" 视为相同。"""
    return re.sub(r"[\s\-_·•/()（）]+", "", name).lower()


def model_tokens(text: str) -> set[str]:
    """文本里的型号：同时含有字母和数字的连续字符，如 "ZG-12" → "zg12"。"""
    tokens = (normalize(token) for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", text))
    return {token for token in tokens if re.search(r"[a-z]", token) and re.search(r"\d", token)}


def mentions_in_text(text: str, catalog: list[str]) -> list[str]:
    """在一句话里直接找出现过的商品：整个商品名，或其中的型号（如 ZG-12）。"""
    haystack = normalize(text)
    asked_models = model_tokens(text)
    return [name for name in catalog if normalize(name) in haystack or model_tokens(name) & asked_models]


def align_products(mentions: list[str], catalog: list[str], matches: dict[str, list[dict[str, Any]]],
                   confirm_score: float = 0.70, option_score: float = 0.60, max_options: int = 5,
                   ambiguity_margin: float = 0.05, outlier_margin: float = 0.15) -> Alignment:
    """mentions：从问题中提取出的商品叫法；matches：每个叫法在商品向量库中的近邻 [{name, score}]。"""
    confirmed: dict[str, float] = {}
    options: list[str] = []

    def add_options(names: list[str]) -> None:
        for name in names:
            if name not in options and name not in confirmed:
                options.append(name)

    for mention in mentions:
        key = normalize(mention)
        if not key:
            continue
        # 1. 字面完全一致
        exact = [name for name in catalog if normalize(name) == key]
        if exact:
            confirmed[exact[0]] = 1.0
            continue
        # 2. 叫法是商品名的一部分（或反过来）：唯一命中直接确认，多个命中交给用户选
        partial = [name for name in catalog if len(key) >= 2 and (key in normalize(name) or normalize(name) in key)]
        if len(partial) == 1:
            confirmed[partial[0]] = 1.0
            continue
        if len(partial) > 1:
            add_options(partial)
            continue
        # 3. 向量相似度。型号只差一个字符的两个商品，名称向量几乎一样（"ZG-13"与"ZG-12"的相似度超过 0.9），
        #    所以叫法里带了型号、而型号对不上时，相似度再高也不直接确认，交给用户选。
        ranked = sorted(matches.get(mention, []), key=lambda item: item["score"], reverse=True)
        strong = [item for item in ranked if item["score"] >= confirm_score]
        if strong:
            rivals = [item for item in strong if strong[0]["score"] - item["score"] <= ambiguity_margin]
            asked_models = model_tokens(mention)
            model_matches = not asked_models or bool(asked_models & model_tokens(strong[0]["name"]))
            if len(rivals) == 1 and model_matches:
                name, score = strong[0]["name"], strong[0]["score"]
                confirmed[name] = max(confirmed.get(name, 0.0), score)
            else:
                add_options([item["name"] for item in rivals])
        else:
            add_options([item["name"] for item in ranked if item["score"] >= option_score][:3])

    # 多个商品同时被确认时，剔除相似度明显偏低的（多半是误判）
    if len(confirmed) > 1:
        best = max(confirmed.values())
        confirmed = {name: score for name, score in confirmed.items() if best - score <= outlier_margin}

    return Alignment(
        confirmed=list(confirmed),
        options=[name for name in options if name not in confirmed][:max_options],
    )
