#!/usr/bin/env python3
"""世界杯预测 · Telegram 推送

把「未来 LEAD_DAYS 天内开赛、且已可预测」的场次预测推到 TG。
- 只推有 pred 的场次（双方实力数据齐全）；淘汰赛 TBD/无球队信息的**不推**，
  等对阵定了、能预测了，下次刷新时再自动推（增量）。
- 已推过的场次记在 data/wc_notified.json，不重复骚扰。
- 凭证从 data/tg_config.json 读（{"token","chat_id"}），该文件不提交 git。

由 fetch_wc 之后调用（server PIPELINES["wc"] 末步），每次有新分析就推。
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
CFG = ROOT / "data" / "tg_config.json"
WC = ROOT / "data" / "wc_matches.js"
SENT = ROOT / "data" / "wc_notified.json"
LEAD_DAYS = 2  # 提前几天推

CN = timezone(timedelta(hours=8))


def load_cfg():
    try:
        return json.loads(CFG.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_wc():
    try:
        m = re.search(r"window\.WC_DATA\s*=\s*(\{.*\});?\s*$", WC.read_text(), re.S)
        return json.loads(m.group(1)) if m else {"matches": []}
    except FileNotFoundError:
        return {"matches": []}


def tg_send(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true",
    }).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
        return json.loads(r.read())


def fmt_match(m):
    p, h, a = m["pred"], m["home"], m["away"]
    lk = p["likely"]
    dt = datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(CN)
    pr = p["probs"]
    lines = [
        f"<b>⚽ {h['name']} vs {a['name']}</b>",
        f"🕐 {dt.strftime('%m-%d %H:%M')} 北京" + (f" · {m['group']}" if m.get("group") else ""),
        f"📊 最可能比分 <b>{lk[0]}-{lk[1]}</b>",
        f"胜/平/负 {round(pr['home']*100)}/{round(pr['draw']*100)}/{round(pr['away']*100)}%",
    ]
    if p.get("marketProbs"):
        e, k = p["eloProbs"], p["marketProbs"]
        lines.append(f"<i>Elo {round(e['home']*100)}/{round(e['draw']*100)}/{round(e['away']*100)} · "
                     f"市场 {round(k['home']*100)}/{round(k['draw']*100)}/{round(k['away']*100)}</i>")
    if p.get("divergenceFlag"):
        lines.append(f"⚠️ 模型与市场分歧 {round(p['divergence']*100)}%，该场更难测")
    top = "  ".join(f"{i}-{j} {round(pr2*100)}%" for i, j, pr2 in p["topScores"][:3])
    lines.append(f"Top比分 {top}")
    return "\n".join(lines)


def main():
    cfg = load_cfg()
    token, chat_id = cfg.get("token"), cfg.get("chat_id")
    if not token or not chat_id:
        print("[TG] 缺 token/chat_id（data/tg_config.json），跳过推送")
        return

    wc = load_wc()
    try:
        sent = set(json.loads(SENT.read_text()))
    except (FileNotFoundError, json.JSONDecodeError):
        sent = set()

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=LEAD_DAYS)
    todo = []
    for m in wc.get("matches", []):
        if not m.get("pred"):
            continue                      # 无球队信息/TBD：不推，等可预测了再推
        if m.get("score"):
            continue                      # 已开赛/结束：不推预测
        dt = datetime.fromisoformat(m["date"].replace("Z", "+00:00"))
        if not (now <= dt <= horizon):
            continue                      # 只推未来 LEAD_DAYS 天
        if m["id"] in sent:
            continue                      # 已推过：增量去重
        todo.append(m)

    if not todo:
        print("[TG] 无新的可推送场次")
        return

    todo.sort(key=lambda m: m["date"])
    header = (f"🏆 <b>世界杯比分预测 · 未来{LEAD_DAYS}天 {len(todo)} 场</b>\n"
              f"<i>融合模型：Elo × 市场赔率，确定性。概率分布不是结果保证，理性参考。</i>")
    text = header + "\n\n" + "\n\n".join(fmt_match(m) for m in todo)

    resp = tg_send(token, chat_id, text)
    if resp.get("ok"):
        sent |= {m["id"] for m in todo}
        tmp = SENT.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(sorted(sent)))
        tmp.replace(SENT)
        print(f"[TG] 已推送 {len(todo)} 场预测")
    else:
        print("[TG] 推送失败:", resp)


if __name__ == "__main__":
    main()
