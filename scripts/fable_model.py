#!/usr/bin/env python3
"""Fable 选号模型：自适应噪声检验收缩 + 形态分层组合设计（确定性）

由 Claude Fable 5 设计（2026-06，接替 Opus 4.8 版 opus_model.py），与
Opus 的"固定强度 Dirichlet 后验 + 信息熵形态打分"、Codex 的"位置/共现/转移枚举"
三代方法论互不重叠，互为对照。

一句话解释（给非统计用户）：
  第一层先做"噪声检验"：用卡方统计量比较每个号码的出现次数偏离与纯随机下的理论
  噪声水平——若偏离没超出噪声（几乎总是如此），就把频率重度收缩回均匀分布，只保留
  温和的残差排序作为确定性"个性"。收缩力度由数据自己决定（James-Stein 思想），
  不像固定先验那样预设立场，也不偏向任何号段。
  第二层不给单注打分选"最优前五"，而是做"形态分层设计"：从历史学出
  （奇数个数 × 和值三分位）的联合分布，把 5 注按最大余额法分配到历史最常见的形态层，
  每层内选收缩得分最高的组合——5 注合在一起构成历史形态分布的一个"分层代表团"，
  这是组合集（portfolio）层面的设计，区别于另两套的逐注打分。

算法全程不含任何随机数，同输入永得同输出。第一层的噪声检验本身就是诚实声明：
模型每次运行都先确认"冷热不超出随机噪声"，它只是历史分布的结构化偏好，
不改变开奖随机性，也不提高任何一注的中奖概率。
"""
import json
import math
import re
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).parent.parent

# 收缩系数上限：即使数据与纯噪声完全一致也保留 10% 的经验残差，
# 避免得分完全退化为均匀（那样排序将失去数据个性，只剩号码大小）。
SHRINK_CAP = 0.9

# 形态层联合分布的拉普拉斯平滑量。
STRATA_SMOOTH = 1.0

# 与 opus_model 同构的契约结构（backtest.py / backfill_full.py 直接 cfg = GAMES[game]）。
GAMES = {
    "ssq": {
        "zoneA": {"label": "红球", "pick": 6, "range": 33},
        "zoneB": {"label": "蓝球", "pick": 1, "range": 16},
        "pickA": 6, "rangeA": 33, "pickB": 1, "rangeB": 16, "poolA": 16, "poolB": 5,
    },
    "dlt": {
        "zoneA": {"label": "前区", "pick": 5, "range": 35},
        "zoneB": {"label": "后区", "pick": 2, "range": 12},
        "pickA": 5, "rangeA": 35, "pickB": 2, "rangeB": 12, "poolA": 16, "poolB": 6,
    },
}


def load_draws(full=False):
    if full:
        text = (ROOT / "data" / "draws_full.js").read_text(encoding="utf-8")
        m = re.search(r"window\.LOTTO_FULL\s*=\s*(\{.*\});?\s*$", text, re.S)
    else:
        text = (ROOT / "data" / "draws.js").read_text(encoding="utf-8")
        m = re.search(r"window\.LOTTO_DATA\s*=\s*(\{.*\});?\s*$", text, re.S)
    return json.loads(m.group(1))


def shrunken_scores(draws, zone, rng, pick):
    """每个号码的自适应收缩得分（James-Stein 思想，目标为均匀分布）。

    噪声基准：每期从 rng 个号里取 pick 个（不放回），单号每期出现概率 p=pick/rng，
    N 期后计数方差 ≈ N·p(1-p)，全体号码的期望卡方 E[χ²] = rng·N·p(1-p)。
    实际 χ²_obs = Σ(count - N·p)²。收缩系数 λ = min(SHRINK_CAP, E[χ²]/χ²_obs)：
    观测离散 ≤ 噪声水平 → λ 触顶、重度收缩（数据没有超出随机的信息）；
    观测离散异常大 → λ 变小、多信数据（历史上从未发生，这正是检验的意义）。
    """
    count = {n: 0 for n in range(1, rng + 1)}
    for d in draws:
        for n in d[zone]:
            count[n] += 1
    n_draws = len(draws)
    p = pick / rng
    expect = n_draws * p
    chi2_obs = sum((count[n] - expect) ** 2 for n in count)
    chi2_noise = rng * n_draws * p * (1 - p)
    lam = min(SHRINK_CAP, chi2_noise / chi2_obs) if chi2_obs > 0 else SHRINK_CAP

    total = n_draws * pick
    uniform = 1.0 / rng
    out = {}
    for n in range(1, rng + 1):
        freq = count[n] / total if total else uniform
        out[n] = uniform + (1.0 - lam) * (freq - uniform)
    return out, lam


def strata_dist(draws, zone, pick):
    """历史（奇数个数 × 和值三分位）联合分布与三分位边界（拉普拉斯平滑）。"""
    sums = sorted(sum(d[zone]) for d in draws)
    n = len(sums)
    t1, t2 = sums[n // 3], sums[(2 * n) // 3]

    def tercile(s):
        return 0 if s <= t1 else (1 if s <= t2 else 2)

    cells = {}
    for d in draws:
        nums = d[zone]
        key = (sum(1 for x in nums if x % 2), tercile(sum(nums)))
        cells[key] = cells.get(key, 0) + 1
    n_cells = (pick + 1) * 3
    dist = {}
    for odd in range(pick + 1):
        for tc in range(3):
            c = cells.get((odd, tc), 0)
            dist[(odd, tc)] = (c + STRATA_SMOOTH) / (n + STRATA_SMOOTH * n_cells)
    return dist, tercile


def allocate_quota(dist, total=5):
    """最大余额法把 total 注分配到形态层；并列时取历史占比高、奇数少、和值低的层。"""
    order = sorted(dist, key=lambda k: (-dist[k], k))
    quota = {k: int(total * dist[k]) for k in order}
    assigned = sum(quota.values())
    frac = sorted(order, key=lambda k: (-(total * dist[k] - quota[k]), -dist[k], k))
    for k in frac:
        if assigned >= total:
            break
        quota[k] += 1
        assigned += 1
    return [k for k in order for _ in range(quota[k]) if quota[k] > 0]


def pick_zone_a(draws, cfg):
    pick, rng = cfg["pickA"], cfg["rangeA"]
    scores, _ = shrunken_scores(draws, "a", rng, pick)
    dist, tercile = strata_dist(draws, "a", pick)
    cells = allocate_quota(dist, 5)

    log_s = {n: math.log(scores[n]) for n in scores}
    max_overlap = pick - 2

    def best_in_cell(cell, chosen, pool_size):
        pool = sorted(scores, key=lambda n: (-scores[n], n))[:pool_size]
        best = None
        for combo in combinations(sorted(pool), pick):
            odd = sum(1 for x in combo if x % 2)
            if (odd, tercile(sum(combo))) != cell:
                continue
            if any(len(set(combo) & set(c)) > max_overlap for c in chosen):
                continue
            s = sum(log_s[n] for n in combo)
            if best is None or s > best[0] or (s == best[0] and combo < best[1]):
                best = (s, combo)
        return best[1] if best else None

    chosen = []
    for cell in cells:
        combo = best_in_cell(cell, chosen, cfg["poolA"])
        if combo is None:  # 该形态层在池内无可行组合时扩池重试
            combo = best_in_cell(cell, chosen, cfg["poolA"] + 6)
        if combo is not None:
            chosen.append(combo)
    # 兜底：层内全不可行时按全局得分补足（保持确定性）
    if len(chosen) < 5:
        pool = sorted(scores, key=lambda n: (-scores[n], n))[: cfg["poolA"] + 6]
        ranked = sorted(
            combinations(sorted(pool), pick),
            key=lambda c: (-sum(log_s[n] for n in c), c),
        )
        for combo in ranked:
            if combo in chosen:
                continue
            if all(len(set(combo) & set(c)) <= max_overlap for c in chosen):
                chosen.append(combo)
            if len(chosen) == 5:
                break
    return chosen[:5]


def pick_zone_b(draws, cfg):
    pick, rng = cfg["pickB"], cfg["rangeB"]
    scores, _ = shrunken_scores(draws, "b", rng, pick)
    if pick == 1:
        ranked = sorted(scores, key=lambda n: (-scores[n], n))[:5]
        return [(b,) for b in ranked]
    pool = sorted(scores, key=lambda n: (-scores[n], n))[: cfg["poolB"]]
    log_s = {n: math.log(scores[n]) for n in pool}
    ranked = sorted(
        combinations(sorted(pool), pick),
        key=lambda c: (-sum(log_s[n] for n in c), c),
    )
    return list(ranked[:5])


def pick_game(draws, cfg):
    chosen_a = pick_zone_a(draws, cfg)
    chosen_b = pick_zone_b(draws, cfg)
    return [{"a": list(a), "b": list(b)} for a, b in zip(chosen_a, chosen_b)]


def validate(result):
    specs = {"ssq": (33, 6, 16, 1), "dlt": (35, 5, 12, 2)}
    for game, (amax, an, bmax, bn) in specs.items():
        tickets = result[game]["tickets"]
        if len(tickets) != 5:
            raise ValueError(f"{game} 必须是 5 注")
        seen = set()
        for t in tickets:
            a, b = t["a"], t["b"]
            if len(a) != an or sorted(a) != a or len(set(a)) != an or not all(1 <= x <= amax for x in a):
                raise ValueError(f"{game} 主区号码非法: {t}")
            if len(b) != bn or sorted(b) != b or len(set(b)) != bn or not all(1 <= x <= bmax for x in b):
                raise ValueError(f"{game} 副区号码非法: {t}")
            key = (tuple(a), tuple(b))
            if key in seen:
                raise ValueError(f"{game} 出现重复注: {t}")
            seen.add(key)


def main():
    import sys
    full = "full" in sys.argv
    data = load_draws(full=full)
    result = {"provider": "claude"}
    for key, cfg in GAMES.items():
        draws = data[key]
        n = len(draws)
        _, lam = shrunken_scores(draws, "a", cfg["rangeA"], cfg["pickA"])
        note = (
            f"由 Claude Fable 5 设计：对{'全量' if full else '近'} {n} 期真实开奖，"
            "先做噪声检验式自适应收缩（卡方比较冷热偏离与纯随机噪声，本次收缩系数 "
            f"λ={lam:.2f}，越接近上限 0.9 说明数据越像纯噪声），只保留温和残差排序；"
            "再按历史（奇偶×和值三分位）联合分布做形态分层设计——5 注按最大余额法"
            "分配到最常见的形态层，构成历史形态分布的分层代表团。"
            "全程确定可复现、零随机数；它只是历史分布的结构化偏好，不改变开奖随机性。"
        )
        result[key] = {"tickets": pick_game(draws, cfg), "note": note}
    validate(result)

    out = ROOT / "data" / ("claude_picks_full.json" if full else "claude_picks.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out}")
    for key in GAMES:
        for t in result[key]["tickets"]:
            print(key, t["a"], "+", t["b"])


if __name__ == "__main__":
    main()
