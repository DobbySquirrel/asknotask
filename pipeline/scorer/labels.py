"""软标签。模拟器选了一个下标就是 one-hot。金标 SQL 同时支持至少两个选项就是 multi。弃权是 others。"""
from __future__ import annotations


def distribute(m: int, sim_index: int | None, gold_set: list[int]) -> tuple[list[float], str]:
    if m < 1:
        return [], "others"
    gold = [i for i in gold_set if 0 <= i < m]
    if sim_index is None:
        return [1.0 / m] * m, "others"
    if len(gold) >= 2:
        share = 1.0 / len(gold)
        return [share if i in gold else 0.0 for i in range(m)], "multi"
    target = [0.0] * m
    if 0 <= sim_index < m:
        target[sim_index] = 1.0
        return target, "onehot"
    return [1.0 / m] * m, "others"
