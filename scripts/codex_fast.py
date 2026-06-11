"""codex_model.build_side 的查表等价改写

原版 score() 对每个组合重复做 Counter 查询与 log，全枚举 C(33,6)=110 万组合耗时 ~20s。
六个评分项（位置/间隔/跨度/号对/转移/形态）都只依赖单号或号对，先预计算成 O(maxnum²)
查表后组合层退化为纯加法，提速约 10 倍。与原版 top-300 排名完全一致（分数误差 <1e-13），
由 scripts/codex_model.py 与 scripts/backtest.py 共用。
"""
import itertools
import math
from collections import Counter, defaultdict

W3 = ((0, 3.0), (-1, 1.0), (1, 1.0))


def build_tables(draws, field, maxnum, pickn):
    pos_counts = [Counter() for _ in range(pickn)]
    gap_counts = [Counter() for _ in range(pickn + 1)]
    span_counts = Counter()
    pair_counts = Counter()
    specific_shift = defaultdict(Counter)
    global_shift = Counter()
    for draw in draws:
        nums = draw[field]
        for i, n in enumerate(nums):
            pos_counts[i][n] += 1
        gaps = [nums[0] - 1] + [nums[i + 1] - nums[i] for i in range(len(nums) - 1)] + [maxnum - nums[-1]]
        for i, gap in enumerate(gaps):
            gap_counts[i][gap] += 1
        span_counts[nums[-1] - nums[0]] += 1
        for pair in itertools.combinations(nums, 2):
            pair_counts[pair] += 1
    chrono = list(reversed(draws))
    for prev, nxt in zip(chrono, chrono[1:]):
        for s in prev[field]:
            for t in nxt[field]:
                d = t - s
                global_shift[d] += 1
                specific_shift[s][d] += 1
    latest = draws[0][field]

    log = math.log
    pos_t = [[0.0] * (maxnum + 1) for _ in range(pickn)]
    for i in range(pickn):
        pc = pos_counts[i]
        for n in range(1, maxnum + 1):
            pos_t[i][n] = log(sum(w * (pc[n + o] + 1) for o, w in W3 if 1 <= n + o <= maxnum))
    gap_t = [[0.0] * (maxnum + 2) for _ in range(pickn + 1)]
    for i in range(pickn + 1):
        gc = gap_counts[i]
        for g in range(0, maxnum + 1):
            gap_t[i][g] = 0.85 * log(sum(w * (gc[g + o] + 1) for o, w in W3 if g + o >= 0))
    span_t = [0.7 * math.log(sum((span_counts[s + o] + 1) * w for o, w in W3 if s + o >= 0))
              for s in range(0, maxnum + 1)]
    pair_t = [[0.0] * (maxnum + 1) for _ in range(maxnum + 1)]
    for a in range(1, maxnum + 1):
        for b in range(a + 1, maxnum + 1):
            pair_t[a][b] = 0.42 * log(pair_counts[(a, b)] + 1)
    shift_t = [0.0] * (maxnum + 1)
    for n in range(1, maxnum + 1):
        best = max(2.0 * (specific_shift[s][n - s] + 1) + 0.35 * (global_shift[n - s] + 1) for s in latest)
        shift_t[n] = 0.55 * log(best)
    return pos_t, gap_t, span_t, pair_t, shift_t


def build_side_fast(draws, field, maxnum, pickn, topk=None):
    pos_t, gap_t, span_t, pair_t, shift_t = build_tables(draws, field, maxnum, pickn)
    odd_t = [n % 2 for n in range(maxnum + 1)]
    low_t = [1 if n <= maxnum // 2 else 0 for n in range(maxnum + 1)]
    half = pickn / 2
    combos = []
    ap = combos.append
    if pickn == 6:
        p0, p1, p2, p3, p4, p5 = pos_t
        g0, g1, g2, g3, g4, g5, g6 = gap_t
        for nums in itertools.combinations(range(1, maxnum + 1), 6):
            a, b, c, d, e, f = nums
            total = (p0[a] + p1[b] + p2[c] + p3[d] + p4[e] + p5[f]
                + g0[a - 1] + g1[b - a] + g2[c - b] + g3[d - c] + g4[e - d] + g5[f - e] + g6[maxnum - f]
                + span_t[f - a]
                + pair_t[a][b] + pair_t[a][c] + pair_t[a][d] + pair_t[a][e] + pair_t[a][f]
                + pair_t[b][c] + pair_t[b][d] + pair_t[b][e] + pair_t[b][f]
                + pair_t[c][d] + pair_t[c][e] + pair_t[c][f]
                + pair_t[d][e] + pair_t[d][f] + pair_t[e][f]
                + shift_t[a] + shift_t[b] + shift_t[c] + shift_t[d] + shift_t[e] + shift_t[f])
            odd = odd_t[a] + odd_t[b] + odd_t[c] + odd_t[d] + odd_t[e] + odd_t[f]
            low = low_t[a] + low_t[b] + low_t[c] + low_t[d] + low_t[e] + low_t[f]
            adj = (b - a == 1) + (c - b == 1) + (d - c == 1) + (e - d == 1) + (f - e == 1)
            total += -0.28 * abs(odd - half) - 0.20 * abs(low - half) - (0.18 * (adj - 1) if adj > 1 else 0.0)
            ap((total, nums))
    elif pickn == 5:
        p0, p1, p2, p3, p4 = pos_t
        g0, g1, g2, g3, g4, g5 = gap_t
        for nums in itertools.combinations(range(1, maxnum + 1), 5):
            a, b, c, d, e = nums
            total = (p0[a] + p1[b] + p2[c] + p3[d] + p4[e]
                + g0[a - 1] + g1[b - a] + g2[c - b] + g3[d - c] + g4[e - d] + g5[maxnum - e]
                + span_t[e - a]
                + pair_t[a][b] + pair_t[a][c] + pair_t[a][d] + pair_t[a][e]
                + pair_t[b][c] + pair_t[b][d] + pair_t[b][e]
                + pair_t[c][d] + pair_t[c][e] + pair_t[d][e]
                + shift_t[a] + shift_t[b] + shift_t[c] + shift_t[d] + shift_t[e])
            odd = odd_t[a] + odd_t[b] + odd_t[c] + odd_t[d] + odd_t[e]
            low = low_t[a] + low_t[b] + low_t[c] + low_t[d] + low_t[e]
            adj = (b - a == 1) + (c - b == 1) + (d - c == 1) + (e - d == 1)
            total += -0.28 * abs(odd - half) - 0.20 * abs(low - half) - (0.18 * (adj - 1) if adj > 1 else 0.0)
            ap((total, nums))
    else:
        for nums in itertools.combinations(range(1, maxnum + 1), pickn):
            total = sum(pos_t[i][n] for i, n in enumerate(nums))
            gaps = [nums[0] - 1] + [nums[i + 1] - nums[i] for i in range(len(nums) - 1)] + [maxnum - nums[-1]]
            total += sum(gap_t[i][g] for i, g in enumerate(gaps))
            total += span_t[nums[-1] - nums[0]]
            total += sum(pair_t[x][y] for x, y in itertools.combinations(nums, 2))
            total += sum(shift_t[n] for n in nums)
            odd = sum(n % 2 for n in nums)
            low = sum(1 for n in nums if n <= maxnum // 2)
            adj = sum(1 for x, y in zip(nums, nums[1:]) if y - x == 1)
            total += -0.28 * abs(odd - half) - 0.20 * abs(low - half) - 0.18 * max(0, adj - 1)
            ap((total, nums))
    combos.sort(key=lambda it: (-it[0], it[1]))
    return combos[:topk] if topk else combos
