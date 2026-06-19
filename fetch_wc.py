#!/usr/bin/env python3
"""世界杯赛程+比分抓取 → 跑确定性模型 → 写 data/wc_matches.js

数据源（均为国际站，海外/机房出口可达，绕开对中国大陆服务器的拦截）：
  赛程 + 实时比分：ESPN site API（soccer/fifa.world scoreboard）
  球队实力 Elo   ：eloratings.net World.tsv（World Football Elo，国家队）
  队名 → 代码    ：eloratings.net en.teams.tsv（自动匹配 ESPN displayName，
                   绕开 Scotland=SQ、Türkiye=TR 这类非 ISO 代码坑）

闭环（仿预测台账）：开赛前按当时 Elo 锁定预测；开赛后用真实比分对照打分。
模型零随机、确定性，同输入同输出——这是「预测可对照、不可事后改」的根基。

用法：
  python3 fetch_wc.py            # 拉今天（机器本地日期）的赛事
  python3 fetch_wc.py 20260619   # 指定某天
  python3 fetch_wc.py 20260611-20260620  # 日期区间（已结束的做对照，未来的做预测）
"""
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "scripts"))
import wc_model

OUT = Path(__file__).parent / "data" / "wc_matches.js"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
HOST_NATIONS = {"US", "CA", "MX"}  # 2026 主办国

# ESPN displayName（规范化后）→ eloratings code 的特例覆盖（自动匹配兜底）
OVERRIDE = {
    "united states": "US", "usa": "US",
    "turkiye": "TR", "turkey": "TR",
    "south korea": "KR", "korea republic": "KR",
    "ir iran": "IR", "iran": "IR",
    "czechia": "CZ", "czech republic": "CZ",
    "cote divoire": "CI", "ivory coast": "CI",
    "cape verde": "CV", "curacao": "CW",
    "bosnia and herzegovina": "BA", "bosniaherzegovina": "BA",
    "congo dr": "CD", "dr congo": "CD", "democratic republic of congo": "CD",
    "republic of ireland": "IE",
}

# 2026 世界杯参赛队中文名（按 eloratings 代码）；未列出的回落 ESPN 英文名
ZH_NAMES = {
    "US": "美国", "CA": "加拿大", "MX": "墨西哥",
    "AR": "阿根廷", "BR": "巴西", "UY": "乌拉圭", "CO": "哥伦比亚",
    "EC": "厄瓜多尔", "PY": "巴拉圭",
    "ES": "西班牙", "FR": "法国", "EN": "英格兰", "PT": "葡萄牙",
    "DE": "德国", "NL": "荷兰", "BE": "比利时", "HR": "克罗地亚",
    "CH": "瑞士", "AT": "奥地利", "NO": "挪威", "SE": "瑞典",
    "SQ": "苏格兰", "CZ": "捷克", "IT": "意大利",
    "MA": "摩洛哥", "SN": "塞内加尔", "CI": "科特迪瓦", "DZ": "阿尔及利亚",
    "EG": "埃及", "TN": "突尼斯", "GH": "加纳", "CV": "佛得角", "ZA": "南非",
    "JP": "日本", "KR": "韩国", "IR": "伊朗", "SA": "沙特阿拉伯",
    "QA": "卡塔尔", "IQ": "伊拉克", "JO": "约旦", "UZ": "乌兹别克斯坦",
    "AU": "澳大利亚", "NZ": "新西兰",
    "TR": "土耳其", "HT": "海地", "PA": "巴拿马", "CW": "库拉索",
    "BA": "波黑", "CD": "刚果(金)",
}


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "ignore")


def atomic_write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def norm(s):
    # 去掉变音符号（Türkiye→turkiye、Côte d'Ivoire→cote divoire），保证跨源队名能对上
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().strip()
    s = re.sub(r"[.'`’-]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def load_elo():
    """eloratings World.tsv → {code: elo}"""
    elo = {}
    for line in http_get("https://www.eloratings.net/World.tsv").split("\n"):
        p = line.split("\t")
        if len(p) >= 4 and p[3].lstrip("-−").isdigit():
            elo[p[2]] = int(p[3].replace("−", "-"))
    return elo


def load_name2code():
    """eloratings en.teams.tsv（每行 CODE<tab>主名<tab>别名...）→ {规范化名: code}"""
    name2code = {}
    for line in http_get("https://www.eloratings.net/en.teams.tsv").split("\n"):
        cells = line.split("\t")
        if len(cells) >= 2 and re.match(r"^[A-Z]{2}", cells[0]):
            code = cells[0]
            for nm in cells[1:]:
                if nm:
                    name2code[norm(nm)] = code
    return name2code


def resolve(display, name2code, elo):
    """ESPN displayName → eloratings code（OVERRIDE 优先，再自动匹配）"""
    n = norm(display)
    code = OVERRIDE.get(n) or name2code.get(n) or name2code.get(n.replace("the ", ""))
    return code if code and code in elo else None


def team_obj(competitor, name2code, elo):
    t = competitor["team"]
    display = t.get("displayName") or t.get("name")
    code = resolve(display, name2code, elo)
    return {
        "code": code,
        "abbr": t.get("abbreviation"),
        "name": ZH_NAMES.get(code, display),
        "enName": display,
        "elo": elo.get(code) if code else None,
    }, competitor


def parse_score(competitor):
    s = competitor.get("score")
    if s is None or s == "":
        return None
    try:
        return int(s)
    except (ValueError, TypeError):
        return None


WC_FULL_RANGE = "20260611-20260719"  # 2026 世界杯完整赛程（美/加/墨，104 场）


def expand_dates(arg):
    # 默认拉完整赛程；可传具体日期 YYYYMMDD 或区间 YYYYMMDD-YYYYMMDD，或 today
    if arg in (None, "all", "full"):
        return WC_FULL_RANGE
    if arg == "today":
        return date.today().strftime("%Y%m%d")
    return arg


def build_match(ev, name2code, elo):
    comp = ev["competitions"][0]
    cs = comp["competitors"]
    home_c = next(c for c in cs if c["homeAway"] == "home")
    away_c = next(c for c in cs if c["homeAway"] == "away")
    home, home_c = team_obj(home_c, name2code, elo)
    away, away_c = team_obj(away_c, name2code, elo)

    status = ev["status"]["type"]["name"]  # STATUS_SCHEDULED / STATUS_FINAL / ...
    is_final = ev["status"]["type"].get("completed", False)
    group = None
    for note in comp.get("notes", []):
        if note.get("headline"):
            group = note["headline"]
            break

    match = {
        "id": ev["id"],
        "date": ev["date"],
        "group": group,
        "home": home,
        "away": away,
        "host": home["code"] in HOST_NATIONS,
        "status": "final" if is_final else "scheduled",
        "score": None,
        "pred": None,
        "result": None,
    }

    # 实力数据齐全才预测；否则诚实留空（不硬编、不瞎猜）
    if home["elo"] and away["elo"]:
        match["pred"] = wc_model.predict(home["elo"], away["elo"], match["host"])
        match["predLockElo"] = {"home": home["elo"], "away": away["elo"]}

    # 比分：开赛后填真实结果
    sh, sa = parse_score(home_c), parse_score(away_c)
    if sh is not None and sa is not None and (is_final or ev["status"]["type"]["state"] == "in"):
        match["score"] = {"home": sh, "away": sa}
        if match["pred"]:
            pred_outcome = wc_model.argmax_outcome(match["pred"]["probs"])
            real_outcome = wc_model.outcome(sh, sa)
            match["result"] = {
                "exactHit": [sh, sa] == match["pred"]["likely"],
                "outcomeHit": pred_outcome == real_outcome,
                "outcomePred": pred_outcome,
                "outcomeReal": real_outcome,
                "final": is_final,
            }
    return match


def main():
    dates = expand_dates(sys.argv[1] if len(sys.argv) > 1 else None)
    elo = load_elo()
    name2code = load_name2code()

    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard?dates={dates}&limit=400"
    data = json.loads(http_get(url))
    events = data.get("events", [])
    if not events:
        print(f"[世界杯] {dates} 无赛事，保留原数据")
        return

    matches = [build_match(ev, name2code, elo) for ev in events]
    matches.sort(key=lambda m: m["date"])

    teams = {}
    for m in matches:
        for side in ("home", "away"):
            t = m[side]
            if t["code"]:
                teams[t["code"]] = {"name": t["name"], "enName": t["enName"], "elo": t["elo"]}

    payload = {
        "meta": {
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "dates": dates,
            "source": "赛程/比分:ESPN · 实力:World Football Elo(eloratings.net)",
            "model": "双泊松确定性模型（Elo 驱动，零随机）",
        },
        "teams": teams,
        "matches": matches,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(OUT, "window.WC_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n")

    ok = sum(1 for m in matches if m["pred"])
    miss = [m["home"]["enName"] + " vs " + m["away"]["enName"] for m in matches if not m["pred"]]
    print(f"[世界杯] {dates}: {len(matches)} 场，预测 {ok} 场 → {OUT}")
    for m in matches:
        if m["pred"]:
            lk = m["pred"]["likely"]
            pr = m["pred"]["probs"]
            sc = f' 实际 {m["score"]["home"]}-{m["score"]["away"]}' if m["score"] else ""
            print(f"   {m['home']['name']}({m['home']['elo']}) vs {m['away']['name']}({m['away']['elo']})"
                  f"  最可能 {lk[0]}-{lk[1]}  胜平负 {pr['home']*100:.0f}/{pr['draw']*100:.0f}/{pr['away']*100:.0f}{sc}")
    if miss:
        print("   ⚠ 缺实力数据未预测:", "; ".join(miss))


if __name__ == "__main__":
    main()
