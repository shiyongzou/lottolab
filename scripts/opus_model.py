#!/usr/bin/env python3
"""Opus 选号模型：贝叶斯 Dirichlet 后验 + 信息熵形态似然（确定性）

由 Claude Opus 4.8 亲自设计，与 Fable 的频率/热度/遗漏模型、Codex 的位置/共现/转移模型
三者方法论互不重叠，互为对照。

一句话解释（给非统计用户）：
  先用"贝叶斯小样本修正"给每个号码估一个被信任的出现概率——观测次数多就更信数据，
  观测少就往一个温和的先验拉回，避免被 150 期里的偶然冷热带偏；
  再用"信息熵形态匹配"评估整注号码的形态（奇偶、和值区间、跨度、尾数分散）
  和历史开奖的整体长相有多像，越不令人意外（信息量越低）得分越高。

两层都来自概率论里的成熟工具（Dirichlet 共轭后验 + 交叉熵/惊异度），
与另两套模型的统计量完全不同。算法全程不含任何随机数，同输入永得同输出。
它只是对历史分布的结构化偏好，不改变开奖随机性。
"""
import json
import math
import re
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).parent.parent

# Dirichlet 先验的等效样本量：相当于额外注入 PRIOR_STRENGTH 期"按先验分布"的虚拟观测。
# 取适中值，使后验在小样本下被先验温和拉回，大样本下基本回归数据本身。
PRIOR_STRENGTH = 12.0

# 形态似然里给每个特征的拉普拉斯平滑量，避免历史从未出现的桶得到 log(0)。
SHAPE_SMOOTH = 1.0

# 暴露 GAMES：既保留 pick/range 描述（满足契约的 zoneA/zoneB 结构），
# 又附带 pick_game 真正消费的扁平字段（pickA/rangeA/... 与 claude_model.py 同构，
# 保证 backtest.py 里 cfg = GAMES[game] 后能直接用）。
GAMES = {
    "ssq": {
        "zoneA": {"label": "红球", "pick": 6, "range": 33},
        "zoneB": {"label": "蓝球", "pick": 1, "range": 16},
        "pickA": 6, "rangeA": 33, "pickB": 1, "rangeB": 16, "poolA": 14, "poolB": 5,
    },
    "dlt": {
        "zoneA": {"label": "前区", "pick": 5, "range": 35},
        "zoneB": {"label": "后区", "pick": 2, "range": 12},
        "pickA": 5, "rangeA": 35, "pickB": 2, "rangeB": 12, "poolA": 13, "poolB": 6,
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


def posterior_prob(draws, zone, rng, pick):
    """每个号码的贝叶斯后验出现概率。

    模型：每期把 pick 个号码看作从 rng 个类别里的多次抽取，类别计数服从
    Dirichlet-Multinomial。先验不取均匀，而是给"中段号码"略高的先验密度
    （真实球面分布里极端号常被人为冷落，且形态上中段更易组合），
    这一非均匀先验让后验与纯频率统计天然分叉。后验均值 = (count + 先验伪计数) / 总量。
    """
    count = {n: 0 for n in range(1, rng + 1)}
    for d in draws:
        for n in d[zone]:
            count[n] += 1
    total_obs = len(draws) * pick

    # 非均匀先验：以号段中点为中心的钝三角权重，归一化为概率，再乘等效样本量得伪计数。
    mid = (rng + 1) / 2.0
    raw = {n: 1.0 + 0.35 * (1.0 - abs(n - mid) / mid) for n in range(1, rng + 1)}
    raw_sum = sum(raw.values())
    pseudo = {n: PRIOR_STRENGTH * pick * raw[n] / raw_sum for n in range(1, rng + 1)}
    pseudo_total = PRIOR_STRENGTH * pick

    out = {}
    for n in range(1, rng + 1):
        out[n] = (count[n] + pseudo[n]) / (total_obs + pseudo_total)
    return out


def _zone_index(value, edges):
    for i, e in enumerate(edges):
        if value <= e:
            return i
    return len(edges)


def shape_logprob_fns(draws, zone, rng, pick):
    """从历史开奖学出几项整注形态特征的经验分布，返回一个打分函数。

    特征：奇数个数、和值分箱、跨度（最大-最小）分箱、尾数（个位）去重数。
    对候选组合，计算其各特征在历史分布下的对数似然之和——
    即香农"惊异度"的负值：越接近历史常见形态，惊异越小、得分越高。
    这是基于交叉熵的形态匹配，区别于另两套的加减罚项。
    """
    n_draws = len(draws)

    odd_c = {}
    sum_vals = []
    span_c = {}
    tail_c = {}
    for d in draws:
        nums = d[zone]
        odd = sum(1 for x in nums if x % 2)
        odd_c[odd] = odd_c.get(odd, 0) + 1
        sum_vals.append(sum(nums))
        span_c[nums[-1] - nums[0]] = span_c.get(nums[-1] - nums[0], 0) + 1
        tails = len({x % 10 for x in nums})
        tail_c[tails] = tail_c.get(tails, 0) + 1

    # 和值用等宽分箱，箱宽随号池规模自适应。
    smin, smax = min(sum_vals), max(sum_vals)
    nbins = 12
    width = max(1.0, (smax - smin) / nbins)
    sum_c = {}
    for s in sum_vals:
        b = int((s - smin) / width)
        sum_c[b] = sum_c.get(b, 0) + 1

    span_min, span_max = min(span_c), max(span_c)
    span_nb = 10
    span_w = max(1.0, (span_max - span_min) / span_nb)

    def logp(counts, key, n_categories):
        c = counts.get(key, 0)
        return math.log((c + SHAPE_SMOOTH) / (n_draws + SHAPE_SMOOTH * n_categories))

    # 跨度同样分箱平滑，窗口内原始跨度取值稀疏，直接用会过拟合。
    span_bins = {}
    for k, v in span_c.items():
        sb = int((k - span_min) / span_w)
        span_bins[sb] = span_bins.get(sb, 0) + v

    def score(combo):
        odd = sum(1 for x in combo if x % 2)
        sb = int((sum(combo) - smin) / width)
        spb = int((combo[-1] - combo[0] - span_min) / span_w)
        tails = len({x % 10 for x in combo})

        lp = logp(odd_c, odd, pick + 1)
        lp += logp(sum_c, sb, nbins + 4)
        lp += logp(span_bins, spb, span_nb + 4)
        lp += logp(tail_c, tails, pick + 1)
        return lp

    return score


def pick_game(draws, cfg):
    pa = cfg["pickA"]
    ra = cfg["rangeA"]
    pb = cfg["pickB"]
    rb = cfg["rangeB"]

    post_a = posterior_prob(draws, "a", ra, pa)
    post_b = posterior_prob(draws, "b", rb, pb)
    shape_a = shape_logprob_fns(draws, "a", ra, pa)

    # 候选池：后验概率最高的若干号码，避免全枚举。
    pool_a = sorted(post_a, key=lambda n: (-post_a[n], n))[: cfg["poolA"]]

    # 组合分 = 池内号码后验对数概率之和（似然贡献）+ 形态似然权重项。
    # 两者同为对数概率尺度，直接相加即整注的近似对数后验。
    log_post = {n: math.log(post_a[n]) for n in pool_a}
    ranked = []
    for combo in combinations(sorted(pool_a), pa):
        s = sum(log_post[n] for n in combo) + 0.9 * shape_a(combo)
        ranked.append((s, combo))
    ranked.sort(key=lambda x: (-x[0], x[1]))

    # 5 注去冗余：限制两注间主区重叠，保证形态多样。
    max_overlap = pa - 2
    chosen_a = []
    for _, combo in ranked:
        if all(len(set(combo) & set(c)) <= max_overlap for c in chosen_a):
            chosen_a.append(combo)
        if len(chosen_a) == 5:
            break
    while len(chosen_a) < 5:  # 池小时的兜底，放宽重叠约束
        for _, combo in ranked:
            if combo not in chosen_a:
                chosen_a.append(combo)
                break

    if pb == 1:
        ranked_b = sorted(post_b, key=lambda n: (-post_b[n], n))[:5]
        chosen_b = [(b,) for b in ranked_b]
    else:
        pool_b = sorted(post_b, key=lambda n: (-post_b[n], n))[: cfg["poolB"]]
        lp_b = {n: math.log(post_b[n]) for n in pool_b}
        ranked_b = sorted(
            combinations(sorted(pool_b), pb),
            key=lambda c: (-sum(lp_b[n] for n in c), c),
        )
        chosen_b = []
        for c in ranked_b:
            if all(len(set(c) & set(x)) <= pb - 1 for x in chosen_b):
                chosen_b.append(c)
            if len(chosen_b) == 5:
                break
        while len(chosen_b) < 5:
            for c in ranked_b:
                if c not in chosen_b:
                    chosen_b.append(c)
                    break

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
        note = (
            f"由 Claude Opus 4.8 设计：对{'全量' if full else '近'} {n} 期真实开奖，"
            "先用贝叶斯 Dirichlet 后验（带非均匀先验的小样本修正）估每个号码的被信任出现概率，"
            "再用信息熵形态匹配（奇偶/和值/跨度/尾数的历史经验分布做交叉熵打分）评整注形态相似度，"
            "两层都是对数概率尺度相加，在后验最高的候选池内排序取互不雷同的前 5 注。"
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
