#!/usr/bin/env python3
"""合并 Claude 与 Codex 两套模型输出（近150期/全量两个窗口），计算共识，写入 data/ai_picks.js"""
import json
import os
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent


def atomic_write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def load_draws():
    text = (ROOT / "data" / "draws.js").read_text()
    m = re.search(r"window\.LOTTO_DATA\s*=\s*(\{.*\});?\s*$", text, re.S)
    return json.loads(m.group(1))


def load_json(name):
    p = ROOT / "data" / name
    return json.loads(p.read_text()) if p.exists() else None


def pool(tickets, zone):
    s = set()
    for t in tickets:
        s.update(t[zone])
    return s


PICKS = {"ssq": (6, 1), "dlt": (5, 2)}


def top_pick(tickets, zone, pick, consensus):
    """十组联合投票：出现次数多者优先，共识号其次，最后小号在前——完全确定性"""
    votes = {}
    for t in tickets:
        for n in t[zone]:
            votes[n] = votes.get(n, 0) + 1
    ranked = sorted(votes, key=lambda n: (-votes[n], 0 if n in consensus else 1, n))
    return sorted(ranked[:pick])


def window_entry(claude, codex):
    out = {}
    for g in ("ssq", "dlt"):
        ca = pool(claude[g]["tickets"], "a") & pool(codex[g]["tickets"], "a")
        cb = pool(claude[g]["tickets"], "b") & pool(codex[g]["tickets"], "b")
        all10 = claude[g]["tickets"] + codex[g]["tickets"]
        pa, pb = PICKS[g]
        out[g] = {
            "claude": claude[g],
            "codex": codex[g],
            "consensus": {"a": sorted(ca), "b": sorted(cb)},
            "top": {"a": top_pick(all10, "a", pa, ca), "b": top_pick(all10, "b", pb, cb)},
        }
    return out


def main():
    draws = load_draws()
    out = {
        "generated": date.today().isoformat(),
        "basedOnIssue": {g: draws[g][0]["issue"] for g in ("ssq", "dlt") if draws.get(g)},
        "windows": {},
    }
    c150 = load_json("claude_picks.json")
    x150 = load_json("codex_picks.json")
    if c150 and x150:
        out["windows"]["150"] = window_entry(c150, x150)
    cfull = load_json("claude_picks_full.json")
    xfull = load_json("codex_picks_full.json")
    if cfull and xfull:
        out["windows"]["full"] = window_entry(cfull, xfull)

    target = ROOT / "data" / "ai_picks.js"
    atomic_write(target, "window.AI_PICKS = " + json.dumps(out, ensure_ascii=False) + ";\n")
    print(f"已写入 {target}（窗口：{'、'.join(out['windows']) or '无'}）")
    for w, entry in out["windows"].items():
        for g in ("ssq", "dlt"):
            print(f"  [{w}] {g} 共识池:", entry[g]["consensus"]["a"], "+", entry[g]["consensus"]["b"])


if __name__ == "__main__":
    main()
