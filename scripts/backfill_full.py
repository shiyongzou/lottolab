#!/usr/bin/env python3
"""补登历史台账缺失的全量窗主推（确定性重建）

模型零随机数：用截至 basedOnIssue 的存档数据重跑，结果与"当时本应锁定的预测"完全一致。
自检：先用同样方法重建 150 期窗主推，必须与台账中当时真实锁定的逐字相同，证明重建可信，
然后才写入全量窗结果。补登记录带 topFullRetro 标记，页面如实展示。
"""
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fable_model as fb
import opus_model as om
import codex_model as cx
from codex_fast import build_side_fast
from merge_picks import PICKS, pool, top_pick
from ledger import hit, tier_of, atomic_write

# Claude 侧模型按代际排列：自检时逐代尝试，谁能逐字复现"当时锁定的150期主推"，
# 就说明该记录锁定于谁的时代，补登也用谁——保证跨模型升级后历史仍可确定性重建。
CLAUDE_GENS = [("Fable 5", fb), ("Opus 4.8", om)]

SPECS = {"ssq": (("a", 33, 6), ("b", 16, 1)), "dlt": (("a", 35, 5), ("b", 12, 2))}


def load_js(path, var):
    m = re.search(r"window\." + var + r"\s*=\s*([\[{].*[\]}]);?\s*$", path.read_text(), re.S)
    return json.loads(m.group(1))


def dual_top(game, draws, model=fb):
    cfg = model.GAMES[game]
    claude_t = model.pick_game(draws, cfg)
    (fa, amax, an), (fb, bmax, bn) = SPECS[game]
    main_rank = build_side_fast(draws, fa, amax, an, topk=300)
    back_rank = build_side_fast(draws, fb, bmax, bn, topk=80)
    codex_t = cx.pick_tickets(main_rank, back_rank, an)
    all10 = claude_t + codex_t
    ca = pool(claude_t, "a") & pool(codex_t, "a")
    cb = pool(claude_t, "b") & pool(codex_t, "b")
    pa, pb = PICKS[game]
    return {"a": top_pick(all10, "a", pa, ca), "b": top_pick(all10, "b", pb, cb)}


def main():
    full = load_js(ROOT / "data" / "draws_full.js", "LOTTO_FULL")
    ledger_path = ROOT / "data" / "ledger.js"
    ledger = load_js(ledger_path, "LEDGER")

    changed = 0
    for rec in ledger:
        if rec.get("topFull") is not None or rec.get("result") is None:
            continue
        game = rec["game"]
        base = int(rec["basedOnIssue"])
        upto = [d for d in full[game] if int(d["issue"]) <= base]

        gen = None
        for gen_name, model in CLAUDE_GENS:
            if dual_top(game, upto[:150], model) == rec["top"]:
                gen = (gen_name, model)
                break
        if gen is None:
            print(f"[{game} {base}] 自检失败：各代模型重建的150期主推均 ≠ 当时锁定 {rec['top']}，拒绝补登")
            continue
        print(f"[{game} {base}] 自检通过：{gen[0]} 代 150期主推重建与当时锁定逐字一致")

        rec["topFull"] = dual_top(game, upto, gen[1])
        rec["topFullRetro"] = True
        fa, fb = hit(rec["topFull"], rec["result"])
        rec["score"]["fullA"] = fa
        rec["score"]["fullB"] = fb
        rec["score"]["fullTier"] = tier_of(game, fa, fb)
        tf = " ".join(f"{n:02d}" for n in rec["topFull"]["a"]) + " + " + " ".join(f"{n:02d}" for n in rec["topFull"]["b"])
        print(f"[{game} {base}] 补登全量主推 [{tf}] → 对 {rec['result']['issue']} 期命中 {fa}+{fb}")
        changed += 1

    if changed:
        # 台账不可再生：写前留 .bak，再原子写（与 ledger.py 同一铁律）
        if ledger_path.exists():
            shutil.copy2(ledger_path, ledger_path.with_suffix(".js.bak"))
        atomic_write(ledger_path, "window.LEDGER = " + json.dumps(ledger, ensure_ascii=False) + ";\n")
        print(f"已补登 {changed} 条 → {ledger_path}")
    else:
        print("没有需要补登的记录")


if __name__ == "__main__":
    main()
