#!/usr/bin/env python3
"""彩票实时跟单 · 每次比分更新就规则对照，检测哪些票已断，推进度图到 TG

读 data/wc_tickets.json（结构化票）。规则对照（总进球超了=断；半全场半场步错=断）。
每次比分/状态变化 → 重算每票每腿 status（hit/miss/pending）→ 若有变化推进度图。
进球同时发文字快报。launchd com.lottolab.ticket 每 60 秒。
"""
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
CFG = ROOT / "data" / "tg_config.json"
TJ = ROOT / "data" / "wc_tickets.json"
STATE = ROOT / "data" / "wc_ticket_state.json"
BROWSE = Path.home() / ".claude" / "skills" / "gstack" / "browse" / "dist" / "browse"
SB = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates=20260611-20260719&limit=400"


def load_cfg():
    try:
        return json.loads(CFG.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_tj():
    try:
        return json.loads(TJ.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")


def tg(token, chat, text):
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage", data=data), timeout=15)
    except Exception:
        pass


def send_photo(token, chat, img, cap):
    r = subprocess.run(["curl", "-sS", "--max-time", "40",
                        f"https://api.telegram.org/bot{token}/sendPhoto",
                        "-F", f"chat_id={chat}", "-F", f"photo=@{img}", "-F", f"caption={cap}"],
                       capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout).get("ok", False)
    except json.JSONDecodeError:
        return False


def wpd(a, b):
    return "胜" if a > b else ("负" if a < b else "平")


def evaluate(tj, states):
    out = []
    for tk in tj["tickets"]:
        legs, sts = [], []
        for leg in tk["legs"]:
            e = leg["e"]
            st = states.get(e, {})
            name = tj["events"].get(e, e)
            s, actual = "pending", "—"
            if tk["t"] == "total":
                pickn = int(leg["pick"])
                if st.get("total") is not None:
                    tot = st["total"]
                    actual = f"{tot}球"
                    if st.get("state") == "post":
                        s = "hit" if tot == pickn else "miss"
                    elif tot > pickn:
                        s = "miss"   # 已超，断
                pickstr = f"{pickn}球"
            else:  # 半全场
                pick = str(leg["pick"])
                ph, pf = pick[0], pick[1]
                if st.get("ftres") and st.get("state") == "post":
                    actual = (st.get("htres", "?")) + st["ftres"]
                    s = "hit" if (st.get("htres") == ph and st["ftres"] == pf) else "miss"
                elif st.get("htres"):
                    actual = "半" + st["htres"]
                    if st["htres"] != ph:
                        s = "miss"   # 半场步已错，断
                pickstr = pick
            legs.append({"g": name, "pick": pickstr, "actual": actual, "status": s})
            sts.append(s)
        out.append({"n": tk["n"], "legs": legs,
                    "allHit": all(x == "hit" for x in sts),
                    "alive": not any(x == "miss" for x in sts)})
    return out


def render_and_send(token, chat, tj, states, results, note):
    summary = [{"team": tj["events"][e], "score": st.get("score", ""), "ht": st.get("ht", "")}
               for e, st in states.items() if st.get("score")]
    Path("/tmp/ticket_data.json").write_text(
        json.dumps({"summary": summary, "tickets": results, "note": note}, ensure_ascii=False))
    try:
        subprocess.run(["node", str(ROOT / "scripts" / "gen_ticket_img.js"), "/tmp/ticket_data.json"],
                       cwd=str(ROOT), capture_output=True, timeout=30)
        subprocess.run([str(BROWSE), "viewport", "760x1700", "--scale", "2"], capture_output=True, timeout=20)
        subprocess.run([str(BROWSE), "load-html", "/tmp/ticket.html"], capture_output=True, timeout=30)
        subprocess.run([str(BROWSE), "screenshot", "/tmp/ticket.png"], capture_output=True, timeout=30)
        if Path("/tmp/ticket.png").exists() and send_photo(token, chat, "/tmp/ticket.png", note):
            return True
    except Exception:
        pass
    return False


def main():
    c = load_cfg()
    token, chat = c.get("token"), c.get("chat_id")
    tj = load_tj()
    if not token or not chat or not tj:
        return
    watch = set(tj["events"].keys())
    try:
        data = json.loads(http_get(SB))
    except Exception:
        return
    try:
        prev = json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        prev = {}
    pstates = prev.get("states", {})

    states, msgs = {}, []
    for ev in data.get("events", []):
        eid = ev["id"]
        if eid not in watch:
            continue
        comp = ev["competitions"][0]
        cs = comp["competitors"]
        h = next(x for x in cs if x["homeAway"] == "home")
        a = next(x for x in cs if x["homeAway"] == "away")
        try:
            hs, as_ = int(h.get("score")), int(a.get("score"))
        except (TypeError, ValueError):
            hs = as_ = None
        typ = ev["status"]["type"]
        state = typ["state"]
        detail = (typ.get("detail") or "").lower()
        period = ev["status"].get("period", 0)
        nm = tj["events"][eid]
        pst = pstates.get(eid, {})
        cur = {"state": state}
        if hs is not None:
            cur["score"] = f"{hs}-{as_}"
            cur["total"] = hs + as_
        # 半场记录（首次进半场，score 即半场比分）
        if (("half" in detail) or (period >= 2 and state == "in")) and not pst.get("ht") and hs is not None:
            cur["ht"] = f"{hs}-{as_}"
            cur["htres"] = wpd(hs, as_)
        elif pst.get("ht"):
            cur["ht"] = pst["ht"]
            cur["htres"] = pst["htres"]
        if state == "post" and hs is not None:
            cur["ftres"] = wpd(hs, as_)
            if not cur.get("htres") and pst.get("htres"):
                cur["htres"] = pst["htres"]
        states[eid] = cur
        if state == "in" and cur.get("score") and pst.get("score") and cur["score"] != pst["score"]:
            msgs.append(f"⚽ {nm} 进球！ {cur['score']}  {ev['status'].get('displayClock', '')}")

    for e in watch:
        if e not in states and pstates.get(e):
            states[e] = pstates[e]

    results = evaluate(tj, states)
    prev_results = prev.get("results")
    new_dead = []
    for r in results:
        if not r["alive"]:
            pr = next((p for p in (prev_results or []) if p["n"] == r["n"]), None)
            if pr is None or pr.get("alive", True):
                new_dead.append(r["n"].split("·")[0])

    for m in msgs:
        tg(token, chat, m)

    has_score = any(st.get("score") for st in states.values())
    if has_score and results != prev_results:
        alive = sum(1 for r in results if r["alive"])
        if new_dead:
            note = f"📊 跟单实时 · ⚠ {('、'.join(new_dead))} 已挂（{alive}/{len(results)} 张还活着）"
        else:
            note = f"📊 跟单实时 · {alive}/{len(results)} 张还活着"
        render_and_send(token, chat, tj, states, results, note)

    new = {"states": states, "results": results}
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new, ensure_ascii=False))
    tmp.replace(STATE)


if __name__ == "__main__":
    main()
