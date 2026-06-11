#!/usr/bin/env python3
"""预测台账：每次推算自动记账，开奖后自动对照打分

记录的是 150 期窗口的双脑十组 + 主推一注（推算时刻已锁定，基于 basedOnIssue 之前的数据，
无未来函数）。下次数据刷新时，凡是已开出 basedOnIssue 之后一期的记录自动打分：
主推命中、十组最佳命中、平均命中、中奖注数与奖级。
"""
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "ledger.js"


def load_js(path, var):
    if not path.exists():
        return None
    m = re.search(r"window\." + var + r"\s*=\s*([\[{].*[\]}]);?\s*$", path.read_text(), re.S)
    return json.loads(m.group(1)) if m else None


def atomic_write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


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


def hit(ticket, draw):
    ka = len(set(ticket["a"]) & set(draw["a"]))
    kb = len(set(ticket["b"]) & set(draw["b"]))
    return ka, kb


def score_record(rec, draws):
    base = int(rec["basedOnIssue"])
    later = [d for d in draws if int(d["issue"]) > base]
    if not later:
        return False
    target = min(later, key=lambda d: int(d["issue"]))
    game = rec["game"]
    ka, kb = hit(rec["top"], target)
    tiers = {}
    prized = 0
    best = 0
    total_a = 0
    for t in rec["tickets"]:
        a, b = hit(t, target)
        total_a += a
        best = max(best, a)
        tr = tier_of(game, a, b)
        if tr:
            prized += 1
            tiers[str(tr)] = tiers.get(str(tr), 0) + 1
    # grades = 当期开奖公告里一、二等浮动奖的实发奖金与中奖注数（真实数据，趁还在窗口内固化进台账）
    rec["result"] = {"issue": target["issue"], "date": target["date"], "a": target["a"], "b": target["b"], "grades": target.get("grades")}
    rec["score"] = {
        "topA": ka, "topB": kb, "topTier": tier_of(game, ka, kb),
        "bestA": best, "avgA": round(total_a / len(rec["tickets"]), 2),
        "prized": prized, "tiers": tiers,
    }
    if rec.get("topFull"):
        fa, fb = hit(rec["topFull"], target)
        rec["score"]["fullA"] = fa
        rec["score"]["fullB"] = fb
        rec["score"]["fullTier"] = tier_of(game, fa, fb)
    return True


def main():
    data = load_js(ROOT / "data" / "draws.js", "LOTTO_DATA")
    picks = load_js(ROOT / "data" / "ai_picks.js", "AI_PICKS")
    # 台账是唯一不可再生的数据：文件存在但读不出来时必须拒绝继续，绝不允许静默重建清史
    ledger = load_js(OUT, "LEDGER")
    if OUT.exists() and ledger is None:
        print(f"错误：{OUT} 存在但无法解析，拒绝覆盖。请检查文件或从 ledger.js.bak 恢复")
        sys.exit(1)
    ledger = ledger or []

    # 老记录补登全量窗主推：仅当其数据截止期与当前推理一致时才可信（同一轮流水线产物）
    wfull = picks.get("windows", {}).get("full")
    for rec in ledger:
        if rec.get("topFull") is None and rec.get("result") is None and wfull:
            if picks["basedOnIssue"].get(rec["game"]) == rec["basedOnIssue"] and wfull.get(rec["game"]):
                rec["topFull"] = wfull[rec["game"]]["top"]

    scored = 0
    for rec in ledger:
        if rec.get("result") is None and score_record(rec, data.get(rec["game"], [])):
            scored += 1

    # 回填历史已打分记录的真实奖金：早期台账的 result 没存 grades，趁目标期仍在窗口内补上（幂等）
    backfilled = 0
    for rec in ledger:
        res = rec.get("result")
        if res and not res.get("grades"):
            tgt = next((d for d in data.get(rec["game"], []) if d["issue"] == res["issue"]), None)
            if tgt is not None and tgt.get("grades"):
                res["grades"] = tgt["grades"]
                backfilled += 1

    added = 0
    win = picks.get("windows", {}).get("150")
    if win:
        for game in ("ssq", "dlt"):
            base = picks["basedOnIssue"].get(game)
            if not base or not win.get(game):
                continue
            if any(r["game"] == game and r["basedOnIssue"] == base for r in ledger):
                continue
            entry = win[game]
            tickets = (
                [{"a": t["a"], "b": t["b"], "model": "claude"} for t in entry["claude"]["tickets"]]
                + [{"a": t["a"], "b": t["b"], "model": "codex"} for t in entry["codex"]["tickets"]]
            )
            full_entry = picks.get("windows", {}).get("full", {}).get(game)
            ledger.append({
                "game": game,
                "window": "150",
                "basedOnIssue": base,
                "predictedAt": date.today().isoformat(),
                "top": entry["top"],
                "topFull": full_entry["top"] if full_entry else None,
                "tickets": tickets,
                "result": None,
                "score": None,
            })
            added += 1

    ledger.sort(key=lambda r: (r["game"], -int(r["basedOnIssue"])))
    if OUT.exists():
        shutil.copy2(OUT, OUT.with_suffix(".js.bak"))
    atomic_write(OUT, "window.LEDGER = " + json.dumps(ledger, ensure_ascii=False) + ";\n")
    print(f"台账：补打分 {scored} 条，回填真实奖金 {backfilled} 条，新记账 {added} 条，共 {len(ledger)} 条 → {OUT}")


if __name__ == "__main__":
    main()
