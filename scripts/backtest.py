#!/usr/bin/env python3
"""滚动回测引擎：用全量真实开奖检验两套 AI 模型 vs 纯随机 vs 理论值

协议（无未来函数）：预测第 T 期只使用 T 期之前的 150 期作为窗口。
回报率口径：一、二等奖为浮动奖金，只计中出注数不计金额；
"固定奖回报率"只统计三等及以下固定奖金，对应理论可实现回报率（双色球约 24.3%）。
用法：python3 scripts/backtest.py [回测期数=300] [并行进程=6]
"""
import json
import random
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from math import comb
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fable_model as cm
import codex_model as cx
from codex_fast import build_side_fast

WINDOW = 150
SPECS = {
    "ssq": {"a": ("a", 33, 6), "b": ("b", 16, 1), "fixed": {3: 3000, 4: 200, 5: 10, 6: 5}, "floating": (1, 2)},
    "dlt": {"a": ("a", 35, 5), "b": ("b", 12, 2),
            "fixed": {3: 10000, 4: 3000, 5: 300, 6: 200, 7: 100, 8: 15, 9: 5}, "floating": (1, 2)},
}


def load_full():
    text = (ROOT / "data" / "draws_full.js").read_text()
    m = re.search(r"window\.LOTTO_FULL\s*=\s*(\{.*\});?\s*$", text, re.S)
    return json.loads(m.group(1))


def tier_of(game, ka, kb):
    if game == "ssq":
        if ka == 6:
            return 1 if kb else 2
        if ka == 5 and kb:
            return 3
        if ka == 5 or (ka == 4 and kb):
            return 4
        if ka == 4 or (ka == 3 and kb):
            return 5
        return 6 if kb else 0
    m = {(5, 2): 1, (5, 1): 2, (5, 0): 3, (4, 2): 4, (4, 1): 5, (3, 2): 6,
         (4, 0): 7, (3, 1): 8, (2, 2): 8, (3, 0): 9, (1, 2): 9, (2, 1): 9, (0, 2): 9}
    return m.get((ka, kb), 0)


def codex_job(args):
    game, window = args
    (fa, amax, an) = SPECS[game]["a"]
    (fb, bmax, bn) = SPECS[game]["b"]
    main_rank = build_side_fast(window, fa, amax, an, topk=300)
    back_rank = build_side_fast(window, fb, bmax, bn, topk=80)
    return cx.pick_tickets(main_rank, back_rank, an)


def theory(game):
    (_, amax, an) = SPECS[game]["a"]
    (_, bmax, bn) = SPECS[game]["b"]
    pa = lambda k: comb(an, k) * comb(amax - an, an - k) / comb(amax, an)
    pb = lambda j: comb(bn, j) * comb(bmax - bn, bn - j) / comb(bmax, bn)
    tier_p = {}
    for i in range(an + 1):
        for j in range(bn + 1):
            t = tier_of(game, i, j)
            if t:
                tier_p[t] = tier_p.get(t, 0.0) + pa(i) * pb(j)
    fixed = SPECS[game]["fixed"]
    return {
        "avgHitsA": an * an / amax,
        "hitRateB": bn * bn / bmax,
        "anyPrize": sum(tier_p.values()),
        "returnFixed": sum(tier_p[t] * fixed[t] for t in fixed if t in tier_p) / 2,
        "tierProb": {str(t): tier_p[t] for t in sorted(tier_p)},
    }


def bootstrap_ci(per_period_hits, tickets_per_period, iters=10000, seed=1):
    rng = random.Random(seed)
    n = len(per_period_hits)
    means = []
    for _ in range(iters):
        s = sum(per_period_hits[rng.randrange(n)] for _ in range(n))
        means.append(s / (n * tickets_per_period))
    means.sort()
    return [means[int(iters * 0.025)], means[int(iters * 0.975)]]


def evaluate(game, predictions, targets):
    (fa, _, _) = SPECS[game]["a"]
    (fb, _, _) = SPECS[game]["b"]
    fixed = SPECS[game]["fixed"]
    tiers = {}
    hits_a = 0
    hits_b = 0
    win_fixed = 0
    prized = 0
    per_period = []
    n_tickets = 0
    for tickets, target in zip(predictions, targets):
        ta, tb = set(target[fa]), set(target[fb])
        period_hits = 0
        for t in tickets:
            ka = len(ta & set(t["a"]))
            kb = len(tb & set(t["b"]))
            hits_a += ka
            hits_b += kb
            period_hits += ka
            n_tickets += 1
            tr = tier_of(game, ka, kb)
            if tr:
                prized += 1
                tiers[str(tr)] = tiers.get(str(tr), 0) + 1
                if tr in fixed:
                    win_fixed += fixed[tr]
        per_period.append(period_hits)
    cost = n_tickets * 2
    tpp = n_tickets // len(predictions)
    return {
        "tickets": n_tickets,
        "avgHitsA": hits_a / n_tickets,
        "hitRateB": hits_b / n_tickets,
        "anyPrize": prized / n_tickets,
        "tiers": tiers,
        "cost": cost,
        "winFixed": win_fixed,
        "returnFixed": win_fixed / cost,
        "ciHitsA": bootstrap_ci(per_period, tpp),
    }


def main():
    n_periods = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    full = load_full()
    out = {"meta": {
        "generated": date.today().isoformat(),
        "window": WINDOW,
        "periods": n_periods,
        "ticketsPerPeriod": 5,
        "protocol": "滚动窗口，预测第T期只用T期之前的150期；固定奖口径=三等及以下，浮动奖只计注数",
    }}
    for game in ("ssq", "dlt"):
        draws = full[game]
        n = min(n_periods, len(draws) - WINDOW - 1)
        targets = [draws[i] for i in range(n)]
        windows = [draws[i + 1: i + 1 + WINDOW] for i in range(n)]
        print(f"[{game}] 回测 {n} 期（{targets[-1]['issue']} → {targets[0]['issue']}）")

        cfg = cm.GAMES[game]
        claude_preds = [cm.pick_game(w, cfg) for w in windows]
        print(f"[{game}] Claude 模型完成")

        with ProcessPoolExecutor(max_workers=workers) as ex:
            codex_preds = list(ex.map(codex_job, [(game, w) for w in windows], chunksize=2))
        print(f"[{game}] Codex 模型完成")

        rng = random.Random(2026)
        (_, amax, an) = SPECS[game]["a"]
        (_, bmax, bn) = SPECS[game]["b"]
        random_preds = [
            [{"a": sorted(rng.sample(range(1, amax + 1), an)),
              "b": sorted(rng.sample(range(1, bmax + 1), bn))} for _ in range(5)]
            for _ in range(n)
        ]
        out[game] = {
            "range": {"from": targets[-1]["issue"], "to": targets[0]["issue"], "periods": n},
            "claude": evaluate(game, claude_preds, targets),
            "codex": evaluate(game, codex_preds, targets),
            "random": evaluate(game, random_preds, targets),
            "theory": theory(game),
        }

    target = ROOT / "data" / "backtest.js"
    tmp = target.with_suffix(".js.tmp")
    tmp.write_text("window.BACKTEST = " + json.dumps(out, ensure_ascii=False) + ";\n")
    import os
    os.replace(tmp, target)
    print(f"已写入 {target}")
    for game in ("ssq", "dlt"):
        g = out[game]
        print(f"--- {game} ---")
        for k in ("claude", "codex", "random"):
            s = g[k]
            print(f"  {k:7s} 主区均中 {s['avgHitsA']:.3f}/注 CI{s['ciHitsA'][0]:.3f}~{s['ciHitsA'][1]:.3f} | "
                  f"中奖率 {s['anyPrize']*100:.2f}% | 固定奖回报 {s['returnFixed']*100:.1f}%")
        t = g["theory"]
        print(f"  theory  主区均中 {t['avgHitsA']:.3f}/注 | 中奖率 {t['anyPrize']*100:.2f}% | 固定奖回报 {t['returnFixed']*100:.1f}%")


if __name__ == "__main__":
    main()
