#!/usr/bin/env python3
"""已证伪陈列室 · 展品二：误差反馈自适应模型

实现"根据最近开奖结果优化算法"的直觉版本，并用滚动回测检验它是否真的会变准：
  - 开出的号码加权（追热修正）
  - 选了没中的号码降权（惩罚错误）
  - 权重逐期向中性衰减（防爆炸）
完全确定性（零随机数），每一期都在"吸取上一期的教训"。
若该思路有效，命中率应随期数上升并超过理论期望；实测结果见输出。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent

SPECS = {"ssq": ("a", 33, 6, "b", 16, 1), "dlt": ("a", 35, 5, "b", 12, 2)}


def load_full():
    text = (ROOT / "data" / "draws_full.js").read_text()
    return json.loads(re.search(r"window\.LOTTO_FULL\s*=\s*(\{.*\});?\s*$", text, re.S).group(1))


def pick_top(weights, count):
    return sorted(sorted(weights, key=lambda n: (-weights[n], n))[:count])


def run(game, draws, n_periods):
    fa, amax, an, fb, bmax, bn = SPECS[game]
    wa = {n: 1.0 for n in range(1, amax + 1)}
    wb = {n: 1.0 for n in range(1, bmax + 1)}
    seq = list(reversed(draws[: n_periods]))
    hits_a = 0
    half1, half2 = 0, 0
    for idx, d in enumerate(seq):
        pa = pick_top(wa, an)
        pb = pick_top(wb, bn)
        h = len(set(pa) & set(d[fa]))
        hits_a += h
        if idx < len(seq) // 2:
            half1 += h
        else:
            half2 += h
        for n, w in list(wa.items()):
            if n in d[fa]:
                wa[n] = w * 1.2
            elif n in pa:
                wa[n] = w * 0.85
            wa[n] = 1 + (wa[n] - 1) * 0.98
        for n, w in list(wb.items()):
            if n in d[fb]:
                wb[n] = w * 1.2
            elif n in pb:
                wb[n] = w * 0.85
            wb[n] = 1 + (wb[n] - 1) * 0.98
    n = len(seq)
    theory = an * an / amax
    print(f"[{game}] 误差反馈模型回测 {n} 期：平均命中 {hits_a / n:.3f} 个/注（理论期望 {theory:.3f}）")
    print(f"[{game}] 前半段 {half1 / (n // 2):.3f} vs 后半段 {half2 / (n - n // 2):.3f} ——若'吸取教训'有效，后半段应显著更高")
    return hits_a / n, theory


def main():
    n_periods = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    full = load_full()
    for game in ("ssq", "dlt"):
        run(game, full[game], n_periods)


if __name__ == "__main__":
    main()
