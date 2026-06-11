#!/usr/bin/env python3
"""Codex 选号模型：位置形态分布 + 号码共现图 + 相邻期转移矩阵

本脚本由 OpenAI Codex (codex-cli) 独立设计编写，与 Claude 的模型(claude_model.py)互为对照。
确定性算法，不使用随机数；它只是历史分布的结构化偏好，不改变开奖随机性。
"""
import itertools
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path


def load_data(root: Path, full: bool = False) -> dict:
    name = "draws_full.js" if full else "draws.js"
    var = "LOTTO_FULL" if full else "LOTTO_DATA"
    text = (root / "data" / name).read_text(encoding="utf-8")
    match = re.search(r"window\." + var + r"\s*=\s*(\{.*\})\s*;\s*$", text, re.S)
    if not match:
        raise ValueError(f"data/{name} does not contain window.{var} JSON")
    return json.loads(match.group(1))


def build_side(draws, field, maxnum, pickn):
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

        gaps = [nums[0] - 1]
        gaps += [nums[i + 1] - nums[i] for i in range(len(nums) - 1)]
        gaps += [maxnum - nums[-1]]
        for i, gap in enumerate(gaps):
            gap_counts[i][gap] += 1

        span_counts[nums[-1] - nums[0]] += 1

        for pair in itertools.combinations(nums, 2):
            pair_counts[pair] += 1

    chronological = list(reversed(draws))
    for prev_draw, next_draw in zip(chronological, chronological[1:]):
        for source in prev_draw[field]:
            for target in next_draw[field]:
                delta = target - source
                global_shift[delta] += 1
                specific_shift[source][delta] += 1

    latest = draws[0][field]

    def score(nums):
        nums = tuple(nums)
        total = 0.0

        for i, n in enumerate(nums):
            bucket = 0.0
            for offset, weight in ((0, 3.0), (-1, 1.0), (1, 1.0)):
                x = n + offset
                if 1 <= x <= maxnum:
                    bucket += weight * (pos_counts[i][x] + 1)
            total += math.log(bucket)

        gaps = [nums[0] - 1]
        gaps += [nums[i + 1] - nums[i] for i in range(len(nums) - 1)]
        gaps += [maxnum - nums[-1]]

        for i, gap in enumerate(gaps):
            bucket = 0.0
            for offset, weight in ((0, 3.0), (-1, 1.0), (1, 1.0)):
                g = gap + offset
                if g >= 0:
                    bucket += weight * (gap_counts[i][g] + 1)
            total += 0.85 * math.log(bucket)

        span = nums[-1] - nums[0]
        total += 0.7 * math.log(
            sum(
                (span_counts[span + offset] + 1) * weight
                for offset, weight in ((0, 3.0), (-1, 1.0), (1, 1.0))
                if span + offset >= 0
            )
        )

        total += 0.42 * sum(
            math.log(pair_counts[tuple(sorted(pair))] + 1)
            for pair in itertools.combinations(nums, 2)
        )

        for n in nums:
            best = 0.0
            for source in latest:
                delta = n - source
                best = max(
                    best,
                    2.0 * (specific_shift[source][delta] + 1)
                    + 0.35 * (global_shift[delta] + 1),
                )
            total += 0.55 * math.log(best)

        odd = sum(n % 2 for n in nums)
        low = sum(n <= maxnum // 2 for n in nums)
        adjacent = sum(1 for a, b in zip(nums, nums[1:]) if b - a == 1)
        total += -0.28 * abs(odd - pickn / 2)
        total += -0.20 * abs(low - pickn / 2)
        total += -0.18 * max(0, adjacent - 1)

        return total

    combos = [(score(nums), nums) for nums in itertools.combinations(range(1, maxnum + 1), pickn)]
    combos.sort(key=lambda item: (-item[0], item[1]))
    return combos


def pick_tickets(main_rank, back_rank, main_n, count=5):
    tickets = []
    used = []
    main_pool = [nums for _, nums in main_rank[:300]]
    back_pool = [nums for _, nums in back_rank[:80]]

    for main in main_pool:
        for back in back_pool:
            if any(main == used_main and back == used_back for used_main, used_back in used):
                continue
            if any(len(set(main) & set(used_main)) > max(1, main_n - 3) for used_main, _ in used):
                continue
            tickets.append({"a": list(main), "b": list(back)})
            used.append((main, back))
            break
        if len(tickets) == count:
            return tickets

    for main in main_pool:
        for back in back_pool:
            if not any(main == used_main and back == used_back for used_main, used_back in used):
                tickets.append({"a": list(main), "b": list(back)})
                used.append((main, back))
                if len(tickets) == count:
                    return tickets

    return tickets


def validate(result):
    specs = {
        "ssq": (33, 6, 16, 1),
        "dlt": (35, 5, 12, 2),
    }
    for game, (amax, an, bmax, bn) in specs.items():
        tickets = result[game]["tickets"]
        if len(tickets) != 5:
            raise ValueError(f"{game} must contain 5 tickets")
        seen = set()
        for ticket in tickets:
            a = ticket["a"]
            b = ticket["b"]
            if len(a) != an or sorted(a) != a or len(set(a)) != an or not all(1 <= x <= amax for x in a):
                raise ValueError(f"invalid {game} front/main numbers: {ticket}")
            if len(b) != bn or sorted(b) != b or len(set(b)) != bn or not all(1 <= x <= bmax for x in b):
                raise ValueError(f"invalid {game} back/blue numbers: {ticket}")
            key = (tuple(a), tuple(b))
            if key in seen:
                raise ValueError(f"duplicate {game} ticket: {ticket}")
            seen.add(key)


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    # 查表版与 build_side 输出排名一致（误差<1e-13），全枚举 24s→2s，原函数保留作算法审计基准
    from codex_fast import build_side_fast

    full = "full" in sys.argv
    root = Path(__file__).parent.parent
    data = load_data(root, full=full)

    ssq_main = build_side_fast(data["ssq"], "a", 33, 6, topk=300)
    ssq_blue = build_side_fast(data["ssq"], "b", 16, 1, topk=80)
    dlt_main = build_side_fast(data["dlt"], "a", 35, 5, topk=300)
    dlt_back = build_side_fast(data["dlt"], "b", 12, 2, topk=80)

    result = {
        "provider": "codex",
        "ssq": {
            "tickets": pick_tickets(ssq_main, ssq_blue, 6),
            "note": "采用位置形态分布、号码共现图和相邻期开奖转移矩阵进行确定性评分，不使用随机数，不改变开奖随机性",
        },
        "dlt": {
            "tickets": pick_tickets(dlt_main, dlt_back, 5),
            "note": "采用位置形态分布、号码共现图和相邻期开奖转移矩阵进行确定性评分，不使用随机数，不改变开奖随机性",
        },
    }

    if full:
        for key in ("ssq", "dlt"):
            result[key]["note"] = f"基于全量 {len(data[key])} 期：" + result[key]["note"]

    validate(result)
    output = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    name = "codex_picks_full.json" if full else "codex_picks.json"
    (root / "data" / name).write_text(output + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
