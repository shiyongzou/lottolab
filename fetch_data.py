#!/usr/bin/env python3
"""拉取双色球/大乐透真实开奖数据，写入 data/draws.js

数据源优先级：
  双色球：福彩官网 API → 500.com 行情页
  大乐透：体彩官网 API → 500.com 行情页
境外出口 IP 会被官方接口拦截（403/567），此时自动落到 500.com。
"""
import json
import os
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).parent / "data" / "draws.js"


def atomic_write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)
COUNT = 150
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def http_get(url, referer=None, timeout=15):
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="ignore")


def td_texts(row_html):
    row_html = re.sub(r"<!--.*?-->", "", row_html, flags=re.S)
    cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)
    return [re.sub(r"<[^>]+>|&nbsp;|\s", "", c) for c in cells]


def to_int(s):
    s = (s or "").replace(",", "")
    return int(s) if s.isdigit() else None


def grades_from(t, i):
    """t[i..i+3] = 一等注数/一等奖金/二等注数/二等奖金（公告实发，浮动奖真值）"""
    g = {}
    if to_int(t[i]) is not None:
        g["1"] = [to_int(t[i]), to_int(t[i + 1])]
    if to_int(t[i + 2]) is not None:
        g["2"] = [to_int(t[i + 2]), to_int(t[i + 3])]
    return g or None


def fetch_ssq_cwl():
    url = (
        "http://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
        f"?name=ssq&issueCount={COUNT}"
    )
    data = json.loads(http_get(url, referer="http://www.cwl.gov.cn/ygkj/wqkjgg/ssq/"))
    out = []
    for r in data["result"]:
        out.append({
            "issue": r["code"],
            "date": r["date"][:10],
            "a": sorted(int(x) for x in r["red"].split(",")),
            "b": [int(r["blue"])],
            "pool": int(r["poolmoney"]) if r.get("poolmoney") else None,
        })
    return out, "中国福彩网"


def fetch_ssq_500():
    html = http_get(f"https://datachart.500.com/ssq/history/newinc/history.php?limit={COUNT}&sort=0")
    rows = re.findall(r'<tr class="t_tr1">.*?</tr>', html, re.S)
    out = []
    for row in rows:
        t = td_texts(row)
        t = [x for x in t if x != ""]
        if len(t) < 15 or not re.match(r"^\d{5}$", t[0]):
            continue
        out.append({
            "issue": "20" + t[0],
            "date": t[-1],
            "a": sorted(int(x) for x in t[1:7]),
            "b": [int(t[7])],
            "pool": to_int(t[8]),
            "grades": grades_from(t, 9),
            "sales": to_int(t[13]),
        })
    return out, "500.com 行情站"


def fetch_dlt_sporttery():
    url = (
        "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
        f"?gameNo=85&provinceId=0&pageSize={COUNT}&isVerify=1&pageNo=1"
    )
    data = json.loads(http_get(url))
    out = []
    for it in data["value"]["list"]:
        nums = it["lotteryDrawResult"].split()
        pool = it.get("poolBalanceAfterdraw", "")
        pool_clean = str(pool).replace(",", "")
        out.append({
            "issue": it["lotteryDrawNum"],
            "date": it["lotteryDrawTime"][:10],
            "a": sorted(int(x) for x in nums[:5]),
            "b": sorted(int(x) for x in nums[5:]),
            "pool": int(float(pool_clean)) if pool_clean.replace(".", "").isdigit() else None,
        })
    return out, "中国体彩网"


def fetch_dlt_500():
    html = http_get(f"https://datachart.500.com/dlt/history/newinc/history.php?limit={COUNT}&sort=0")
    rows = re.findall(r'<tr class="t_tr1">.*?</tr>', html, re.S)
    out = []
    for row in rows:
        t = td_texts(row)
        t = [x for x in t if x != ""]
        if len(t) < 14 or not re.match(r"^\d{5}$", t[0]):
            continue
        out.append({
            "issue": t[0],
            "date": t[-1],
            "a": sorted(int(x) for x in t[1:6]),
            "b": sorted(int(x) for x in t[6:8]),
            "pool": to_int(t[8]),
            "grades": grades_from(t, 9),
            "sales": to_int(t[13]),
        })
    return out, "500.com 行情站"


# GitHub 行情镜像（海外/机房出口可达，绕过对中国大陆服务器的 SNI 重置）
# 该仓库每日更新近百期；缺奖级 grades（票夹一二等浮动奖回落估值）。
XLOTTERY_BASE = "https://raw.githubusercontent.com/wssaidong/x-lottery/main/data"


def _xl_money(s):
    s = str(s or "").replace(",", "")
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def fetch_ssq_xlottery():
    data = json.loads(http_get(f"{XLOTTERY_BASE}/ssq_recent_100.json"))
    out = []
    for r in data:
        reds = [int(r[f"红球号码{i}"]) for i in range(1, 7)]
        out.append({
            "issue": "20" + r["期号"],            # 源给 5 位，规范化成 7 位
            "date": r["开奖日期"],
            "a": sorted(reds),
            "b": [int(r["蓝球号码1"])],
            "pool": _xl_money(r.get("奖池余额")),
            "sales": _xl_money(r.get("总销售额")),
        })
    out.sort(key=lambda d: d["issue"], reverse=True)
    return out, "x-lottery(GitHub)"


def fetch_dlt_xlottery():
    data = json.loads(http_get(f"{XLOTTERY_BASE}/dlt_recent_100.json"))
    out = []
    for r in data:
        fronts = [int(r[f"前区号码{i}"]) for i in range(1, 6)]
        backs = [int(r[f"后区号码{i}"]) for i in range(1, 3)]
        out.append({
            "issue": r["期号"],                   # dlt 本就是 5 位
            "date": r["开奖日期"],
            "a": sorted(fronts),
            "b": sorted(backs),
            "pool": _xl_money(r.get("奖池余额")),
            "sales": _xl_money(r.get("总销售额")),
        })
    out.sort(key=lambda d: d["issue"], reverse=True)
    return out, "x-lottery(GitHub)"


def try_sources(name, sources):
    for fn in sources:
        try:
            data, src = fn()
            if data:
                print(f"[{name}] {src} 获取 {len(data)} 期，最新 {data[0]['issue']} ({data[0]['date']})")
                return data, src
        except Exception as e:
            print(f"[{name}] {fn.__name__} 失败：{e}")
    return None, None


def merge_recent(old_list, fresh_list, count):
    """增量合并近 N 期：旧期保留（字段完整，含 grades），新期补充，降序截最新 count 期。
    新源（如 x-lottery）只给百来期且缺 grades，整体替换会让 draws.js 缩水/丢奖级，
    故按期号合并——已有的期不被新源覆盖，只补开奖后新增的期。"""
    merged = {d["issue"]: d for d in old_list}
    for d in fresh_list or []:
        if d["issue"] not in merged:
            merged[d["issue"]] = d
    ordered = sorted(merged.values(), key=lambda d: d["issue"], reverse=True)
    return ordered[:count]


FULL_OUT = Path(__file__).parent / "data" / "draws_full.js"


def update_full():
    """全量档案：首次全量拉取（双色球3462+期/大乐透2881+期），之后按期号增量合并"""
    global COUNT
    old = {"ssq": [], "dlt": []}
    if FULL_OUT.exists():
        m = re.search(r"window\.LOTTO_FULL\s*=\s*(\{.*\});?\s*$", FULL_OUT.read_text(), re.S)
        if m:
            try:
                old = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
    saved_count = COUNT
    fresh_by_game = {}
    try:
        for key, sources in (("ssq", [fetch_ssq_xlottery, fetch_ssq_500, fetch_ssq_cwl]), ("dlt", [fetch_dlt_xlottery, fetch_dlt_500, fetch_dlt_sporttery])):
            COUNT = 300 if old.get(key) else 99999
            fresh_by_game[key], _ = try_sources(f"{key}(全量档案)", sources)
    finally:
        COUNT = saved_count
    ssq, dlt = fresh_by_game["ssq"], fresh_by_game["dlt"]
    payload = {"meta": {"generated": date.today().isoformat()}}
    for key, fresh in (("ssq", ssq), ("dlt", dlt)):
        merged = {d["issue"]: d for d in old.get(key, [])}
        for d in fresh or []:
            merged[d["issue"]] = d
        payload[key] = sorted(merged.values(), key=lambda d: d["issue"], reverse=True)
        for d in payload[key]:
            for f in ("pool", "grades", "sales"):
                d.pop(f, None)
        print(f"[全量档案] {key} 共 {len(payload[key])} 期")
    if not payload["ssq"] and not payload["dlt"]:
        print("全量档案更新失败，保留旧档案")
        sys.exit(1)
    atomic_write(FULL_OUT, "window.LOTTO_FULL = " + json.dumps(payload, ensure_ascii=False) + ";\n")
    print(f"已写入 {FULL_OUT}")


def main():
    if "--full" in sys.argv:
        update_full()
        return
    ssq, ssq_src = try_sources("双色球", [fetch_ssq_xlottery, fetch_ssq_cwl, fetch_ssq_500])
    dlt, dlt_src = try_sources("大乐透", [fetch_dlt_xlottery, fetch_dlt_sporttery, fetch_dlt_500])
    if not ssq and not dlt:
        print("全部数据源失败，保留原有数据文件。若官方接口 403/567，多为境外出口 IP 被拦。")
        sys.exit(1)

    old = {}
    if OUT.exists():
        m = re.search(r"window\.LOTTO_DATA\s*=\s*(\{.*\});?\s*$", OUT.read_text(), re.S)
        if m:
            try:
                old = json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

    payload = {
        "meta": {
            "generated": date.today().isoformat(),
            "sample": False,
            "source": f"双色球:{ssq_src or '沿用旧数据'} / 大乐透:{dlt_src or '沿用旧数据'}",
        },
        "ssq": merge_recent(old.get("ssq", []), ssq, COUNT),
        "dlt": merge_recent(old.get("dlt", []), dlt, COUNT),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(OUT, "window.LOTTO_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n")
    print(f"已写入 {OUT}")


if __name__ == "__main__":
    main()
