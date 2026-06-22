#!/usr/bin/env python3
"""世界杯实时直播提醒 · 轮询 ESPN，进球/开赛/完场推 Telegram

由 launchd 每 60 秒调用（com.lottolab.live.plist）。
无进行中比赛时快速退出（只查不推，轻量）。状态记 data/wc_live_state.json，
靠比分/状态变化触发，不重复推。凭证从 data/tg_config.json 读。
"""
import json
import subprocess
import urllib.parse
import urllib.request
from datetime import date, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
CFG = ROOT / "data" / "tg_config.json"
STATE = ROOT / "data" / "wc_live_state.json"
SB = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
CN = timezone(timedelta(hours=8))

# 今晚及常见参赛队中文名；未列出的回落 ESPN 英文名
ZH = {
    "United States": "美国", "Australia": "澳大利亚", "Scotland": "苏格兰", "Morocco": "摩洛哥",
    "Brazil": "巴西", "Haiti": "海地", "Türkiye": "土耳其", "Turkey": "土耳其", "Paraguay": "巴拉圭",
    "Spain": "西班牙", "Argentina": "阿根廷", "France": "法国", "England": "英格兰",
    "Portugal": "葡萄牙", "Germany": "德国", "Netherlands": "荷兰", "Belgium": "比利时",
    "Mexico": "墨西哥", "Canada": "加拿大", "Japan": "日本", "South Korea": "韩国",
    "Croatia": "克罗地亚", "Uruguay": "乌拉圭", "Colombia": "哥伦比亚", "Switzerland": "瑞士",
}

# 从 wc_matches.js 补全所有参赛队中文名（覆盖全 48 强，避免回落英文）
try:
    _txt = (ROOT / "data" / "wc_matches.js").read_text()
    _d = json.loads(_txt[_txt.index("{"):_txt.rindex("}") + 1])
    for _t in _d.get("teams", {}).values():
        if _t.get("enName") and _t.get("name") and _t["enName"] != _t["name"]:
            ZH.setdefault(_t["enName"], _t["name"])
except Exception:
    pass


def load_cfg():
    try:
        return json.loads(CFG.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore")


def tg(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data),
            timeout=15)
        return True
    except Exception:
        return False


def name(team):
    dn = team.get("displayName") or team.get("shortDisplayName") or "?"
    return ZH.get(dn, team.get("shortDisplayName") or dn)


def main():
    c = load_cfg()
    token, chat_id = c.get("token"), c.get("chat_id")
    if not token or not chat_id:
        return

    # 查今天 + 昨天（跨时区比赛可能算昨天的 UTC 日期）
    days = [date.today().strftime("%Y%m%d"), (date.today() - timedelta(days=1)).strftime("%Y%m%d")]
    events = []
    for d in days:
        try:
            events += json.loads(http_get(f"{SB}?dates={d}&limit=50")).get("events", [])
        except Exception:
            continue
    if not events:
        return

    try:
        state = json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    new = dict(state)
    msgs = []

    for ev in events:
        comp = ev["competitions"][0]
        cs = comp["competitors"]
        h = next(c for c in cs if c["homeAway"] == "home")
        a = next(c for c in cs if c["homeAway"] == "away")
        hn, an = name(h["team"]), name(a["team"])
        st = ev["status"]["type"]["state"]                 # pre / in / post
        hs, as_ = h.get("score"), a.get("score")
        score = f"{hs}-{as_}" if hs not in (None, "") else ""
        clock = ev["status"].get("displayClock", "")
        eid = ev["id"]
        prev = state.get(eid, {})
        pst, psc = prev.get("state"), prev.get("score", "")

        if st == "in" and pst != "in":
            msgs.append(f"🟢 开赛 | {hn} vs {an}")
        elif st == "in" and score and score != psc and psc != "":
            msgs.append(f"⚽ 进球！ {hn} <b>{score}</b> {an}  {clock}")
        elif st == "post" and pst not in (None, "post"):
            msgs.append(f"🏁 完场 | {hn} <b>{score}</b> {an}")

        new[eid] = {"state": st, "score": score}

    for m in msgs:
        # 进球消息用 HTML 加粗
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": m, "parse_mode": "HTML"}).encode()
        try:
            urllib.request.urlopen(
                urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data),
                timeout=15)
        except Exception:
            pass

    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(new))
    tmp.replace(STATE)
    if msgs:
        print(f"[直播] 推送 {len(msgs)} 条")


if __name__ == "__main__":
    main()
