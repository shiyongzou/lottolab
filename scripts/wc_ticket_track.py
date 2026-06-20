#!/usr/bin/env python3
"""彩票跟单 · 监控我买的票涉及的 4 场，半场/进球/完场对照票面推 TG

launchd 每 2 分钟跑（com.lottolab.ticket）。无进行中比赛时快速退出。
半场/完场用 claude 对照票面（懂竞彩玩法）；进球只推比分（快）。
凭证 data/tg_config.json；票面 data/wc_tickets.txt。
"""
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
CFG = ROOT / "data" / "tg_config.json"
TICKETS = ROOT / "data" / "wc_tickets.txt"
STATE = ROOT / "data" / "wc_ticket_state.json"
BROWSE = Path.home() / ".claude" / "skills" / "gstack" / "browse" / "dist" / "browse"
SB = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=20260611-20260719&limit=400"
WATCH_FILE = ROOT / "data" / "wc_ticket_watch.json"


def load_watch():
    """跟单监控的场次（event_id → "队A vs 队B"），由 bot 发图触发时写入"""
    try:
        return json.loads(WATCH_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_cfg():
    try:
        return json.loads(CFG.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")


def tg(token, chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=15)
    except Exception:
        pass


def ask(prompt):
    try:
        r = subprocess.run(["claude", "-p", prompt, "--model", "sonnet"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def send_photo(token, chat, img, caption):
    r = subprocess.run([
        "curl", "-sS", "--max-time", "40",
        f"https://api.telegram.org/bot{token}/sendPhoto",
        "-F", f"chat_id={chat}", "-F", f"photo=@{img}", "-F", f"caption={caption}",
    ], capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout).get("ok", False)
    except json.JSONDecodeError:
        return False


def finalize(token, chat, tickets, results):
    """4场全完场：claude 对照 → 数据 → 渲染对照图 → 发图；失败回落文字"""
    import re
    rsum = "; ".join(f"{nm} {r['score']}(半{r.get('ht', '?')})" for nm, r in results.items())
    prompt = (f"{tickets}\n\n四场最终结果：{rsum}\n"
              "对照每张票每一腿，只输出 JSON（不要别的文字）：\n"
              '{"summary":[{"team":"队A vs 队B","score":"x-y","ht":"a-b"}],'
              '"tickets":[{"n":"票A·总进球·¥20","legs":[{"g":"队A vs 队B","pick":"我选","actual":"实际","hit":true}],"allHit":false,"broken":["断点队名"]}]}\n'
              "总进球=全场总进球；半全场=半场胜平负+全场胜平负（主队赢=胜）。每张票列全4腿。")
    raw = ask(prompt)
    m = re.search(r"\{.*\}", raw, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            dpath = "/tmp/ticket_data.json"
            Path(dpath).write_text(json.dumps(data, ensure_ascii=False))
            subprocess.run(["node", str(ROOT / "scripts" / "gen_ticket_img.js"), dpath],
                           cwd=str(ROOT), capture_output=True, timeout=30)
            subprocess.run([str(BROWSE), "viewport", "760x1600", "--scale", "2"], capture_output=True, timeout=20)
            subprocess.run([str(BROWSE), "load-html", "/tmp/ticket.html"], capture_output=True, timeout=30)
            subprocess.run([str(BROWSE), "screenshot", "/tmp/ticket.png"], capture_output=True, timeout=30)
            if Path("/tmp/ticket.png").exists() and send_photo(token, chat, "/tmp/ticket.png", "🏁 你的票 · 四场全部完场对照"):
                return
        except Exception:
            pass
    tg(token, chat, "🏁 四场全部完场，对照结果：\n" + raw[:1500])


def main():
    c = load_cfg()
    token, chat = c.get("token"), c.get("chat_id")
    WATCH = load_watch()
    if not token or not chat or not WATCH or not TICKETS.exists():
        return
    tickets = TICKETS.read_text()
    try:
        data = json.loads(http_get(SB))
    except Exception:
        return
    try:
        state = json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    new = dict(state)

    for ev in data.get("events", []):
        eid = ev["id"]
        if eid not in WATCH:
            continue
        nm = WATCH[eid]
        comp = ev["competitions"][0]
        cs = comp["competitors"]
        h = next(x for x in cs if x["homeAway"] == "home")
        a = next(x for x in cs if x["homeAway"] == "away")
        hs, as_ = h.get("score"), a.get("score")
        score = f"{hs}-{as_}" if hs not in (None, "") else ""
        typ = ev["status"]["type"]
        st = typ["state"]
        detail = (typ.get("detail") or "").lower()
        period = ev["status"].get("period", 0)
        prev = state.get(eid, {})
        cur = dict(prev)
        cur["state"] = st
        cur["score"] = score

        # 半场结束（首次）
        if (("half" in detail) or (period >= 2 and st == "in")) and not prev.get("ht"):
            cur["ht"] = score
            msg = ask(f"{tickets}\n\n【{nm}】半场结束，半场比分 主队 {score}。"
                      "只对照涉及这场的「半全场胜平负」玩法的半场那一步是否对路（票B/票D），"
                      "其它玩法（总进球）等全场。简洁，只说这一场，2-4行。")
            tg(token, chat, f"⏱️ {nm} · 半场 {score}\n\n{msg}")
        # 进球
        elif st == "in" and score and prev.get("score") and score != prev.get("score"):
            tg(token, chat, f"⚽ {nm} · 进球！当前 {score}  {ev['status'].get('displayClock', '')}")

        # 完场（首次）
        if st == "post" and prev.get("state") != "post":
            ht = prev.get("ht") or cur.get("ht") or "未知"
            msg = ask(f"{tickets}\n\n【{nm}】全场结束，全场比分 主队 {score}（半场 {ht}）。"
                      "对照我这 5 张票里涉及这一场的所有腿（总进球数票A/C/E、半全场票B/D），"
                      "逐张说这一场这一腿中没中。简洁清楚，列出来。")
            tg(token, chat, f"🏁 {nm} · 完场 {score}（半场 {ht}）\n\n{msg}")

        new[eid] = cur

    # 全部场次完场 → 自动生成整票对照图（只发一次）
    if WATCH and all(new.get(e, {}).get("state") == "post" for e in WATCH) and not state.get("_done"):
        results = {nm: {"score": new[e].get("score", ""), "ht": new[e].get("ht", "?")} for e, nm in WATCH.items()}
        finalize(token, chat, tickets, results)
        new["_done"] = True

    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new))
    tmp.replace(STATE)


if __name__ == "__main__":
    main()
