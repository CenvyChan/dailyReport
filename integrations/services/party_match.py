"""金蝶客商名称 ↔ 系统主数据（简称）的模糊匹配。

系统侧客户/供应商名称多为简称，金蝶侧多为全称，故不能靠精确匹配：
按字符重合 + 子串 + difflib 比率打分，唯一强命中自动挂接，多命中落候选交人工。
纯函数、不依赖 DB，便于单测。
"""

import re
from difflib import SequenceMatcher

# 归一化时剥离的常见企业名后缀/修饰词，让简称与全称的核心词对齐。
_NOISE = [
    "有限责任公司", "股份有限公司", "有限公司", "集团股份", "集团", "公司",
    "厂", "商行", "经营部", "贸易", "科技", "实业", "股份",
]
_PUNCT = re.compile(r"[\s()（）〔〕【】·.,，。、;；:：\-—_/\\]+")

# 打分阈值
THRESHOLD = 0.50   # 低于此分不作为候选
STRONG = 0.95      # 视为强命中（子串/完全一致）
GAP = 0.15         # 第一名领先第二名的分差，够大才允许自动挂接


def normalize(name: str) -> str:
    s = _PUNCT.sub("", name or "")
    for token in _NOISE:
        s = s.replace(token, "")
    return s.strip().lower()


def score(local_name: str, k3_name: str) -> float:
    """local_name 通常是简称，k3_name 通常是全称。返回 0~1。"""
    a, b = normalize(local_name), normalize(k3_name)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.95
    common = sum(1 for ch in set(a) if ch in b)
    overlap = common / len(set(a))
    ratio = SequenceMatcher(None, a, b).ratio()
    return round(max(overlap * 0.9, ratio), 3)


def match_candidates(k3_name: str, locals_):
    """locals_: 可迭代的 (id, name)。返回按分数降序的候选 [{id,name,score}]。"""
    scored = []
    for local_id, local_name in locals_:
        s = score(local_name, k3_name)
        if s >= THRESHOLD:
            scored.append({"id": local_id, "name": local_name, "score": s})
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored


def decide(k3_name: str, locals_):
    """返回 (status, resolved_id, candidates)。

    - AUTO：唯一强命中，或第一名显著领先 → 自动挂接 resolved_id；
    - PENDING：多个候选难分伯仲 → 落全部候选，交人工；
    - UNMATCHED：无候选。
    """
    candidates = match_candidates(k3_name, locals_)
    if not candidates:
        return "UNMATCHED", None, []
    top = candidates[0]
    second = candidates[1]["score"] if len(candidates) > 1 else 0.0
    if top["score"] >= STRONG and (len(candidates) == 1 or top["score"] - second >= GAP):
        return "AUTO", top["id"], candidates
    return "PENDING", None, candidates
