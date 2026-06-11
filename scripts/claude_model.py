#!/usr/bin/env python3
"""Claude 选号模型：基于真实历史开奖的确定性评分推算

号码分 = 0.45×全期频率 + 0.35×近期热度（指数衰减，半衰期 30 期）+ 0.20×遗漏回补
组合分 = 池内号码分之和 - 奇偶失衡惩罚 - 和值偏离惩罚 - 连号惩罚
同一份数据输入永远得到同一组输出，可复现可审计。
注意：该模型只是对历史分布的结构化偏好，无法改变开奖的随机性。
"""
import json
import math
import re
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).parent.parent
HALF_LIFE = 30

GAMES = {
    "ssq": {"pickA": 6, "rangeA": 33, "pickB": 1, "rangeB": 16, "poolA": 14, "poolB": 5},
    "dlt": {"pickA": 5, "rangeA": 35, "pickB": 2, "rangeB": 12, "poolA": 12, "poolB": 6},
}


def load_draws(full=False):
    if full:
        text = (ROOT / "data" / "draws_full.js").read_text()
        m = re.search(r"window\.LOTTO_FULL\s*=\s*(\{.*\});?\s*$", text, re.S)
    else:
        text = (ROOT / "data" / "draws.js").read_text()
        m = re.search(r"window\.LOTTO_DATA\s*=\s*(\{.*\});?\s*$", text, re.S)
    return json.loads(m.group(1))


def scores(draws, zone, rng, pick):
    freq = {n: 0 for n in range(1, rng + 1)}
    recency = {n: 0.0 for n in range(1, rng + 1)}
    omission = {n: len(draws) for n in range(1, rng + 1)}
    for idx, d in enumerate(draws):
        w = 0.5 ** (idx / HALF_LIFE)
        for n in d[zone]:
            freq[n] += 1
            recency[n] += w
            if omission[n] == len(draws):
                omission[n] = idx
    max_f = max(freq.values()) or 1
    max_r = max(recency.values()) or 1
    expected_gap = rng / pick
    out = {}
    for n in range(1, rng + 1):
        gap_norm = min(omission[n] / expected_gap, 2.0) / 2.0
        out[n] = 0.45 * freq[n] / max_f + 0.35 * recency[n] / max_r + 0.20 * gap_norm
    return out


def shape_penalty(combo, sum_mu, sum_sigma):
    odd = sum(1 for n in combo if n % 2)
    ideal = len(combo) / 2
    cons = sum(1 for i in range(1, len(combo)) if combo[i] - combo[i - 1] == 1)
    p = 0.08 * abs(odd - ideal)
    p += 0.10 * abs(sum(combo) - sum_mu) / max(sum_sigma, 1)
    p += 0.06 * max(0, cons - 1)
    return p


def top_combos(pool, pick, score_map, sum_mu, sum_sigma, want, max_overlap):
    ranked = []
    for combo in combinations(sorted(pool), pick):
        s = sum(score_map[n] for n in combo) - shape_penalty(combo, sum_mu, sum_sigma)
        ranked.append((s, combo))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    chosen = []
    for _, combo in ranked:
        if all(len(set(combo) & set(c)) <= max_overlap for c in chosen):
            chosen.append(combo)
        if len(chosen) == want:
            break
    return chosen


def pick_game(draws, cfg):
    sa = scores(draws, "a", cfg["rangeA"], cfg["pickA"])
    sb = scores(draws, "b", cfg["rangeB"], cfg["pickB"])
    sums = [sum(d["a"]) for d in draws]
    mu = sum(sums) / len(sums)
    sigma = math.sqrt(sum((x - mu) ** 2 for x in sums) / len(sums))

    pool_a = sorted(sa, key=lambda n: -sa[n])[: cfg["poolA"]]
    combos_a = top_combos(pool_a, cfg["pickA"], sa, mu, sigma, 5, cfg["pickA"] - 2)

    if cfg["pickB"] == 1:
        ranked_b = sorted(sb, key=lambda n: -sb[n])[:5]
        combos_b = [(b,) for b in ranked_b]
    else:
        pool_b = sorted(sb, key=lambda n: -sb[n])[: cfg["poolB"]]
        ranked = sorted(
            combinations(sorted(pool_b), 2),
            key=lambda c: (-(sb[c[0]] + sb[c[1]]), c),
        )
        combos_b = []
        for c in ranked:
            if all(len(set(c) & set(x)) <= 1 for x in combos_b):
                combos_b.append(c)
            if len(combos_b) == 5:
                break

    return [{"a": list(a), "b": list(b)} for a, b in zip(combos_a, combos_b)]


def main():
    import sys
    full = "full" in sys.argv
    data = load_draws(full=full)
    result = {"provider": "claude"}
    for key, cfg in GAMES.items():
        draws = data[key]
        result[key] = {
            "tickets": pick_game(draws, cfg),
            "note": (
                f"基于{'全量' if full else '近'} {len(draws)} 期真实开奖：全期频率 45% + 近期热度 35%（半衰期 30 期）"
                "+ 遗漏回补 20% 评出号码分，取高分候选池做全组合形态打分"
                "（奇偶均衡、和值贴近历史均值、压连号），输出互不雷同的前 5 注。"
                "算法确定可复现；它只是历史分布的结构化偏好，不改变开奖随机性。"
            ),
        }
    out = ROOT / "data" / ("claude_picks_full.json" if full else "claude_picks.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"已写入 {out}")
    for key in GAMES:
        for t in result[key]["tickets"]:
            print(key, t["a"], "+", t["b"])


if __name__ == "__main__":
    main()
