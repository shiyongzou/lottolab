#!/usr/bin/env python3
"""世界杯预测 · Telegram 高清图推送

每次刷新后，把世界杯预测页截成高清图（retina ×2）发到 TG；
截图不可用时回落为文字推送，保证 launchd 后台不哑火。

- 只在「有未来可预测场次」时推；用预测指纹去重，同一批数据不重复发。
- 没球队信息（TBD）的场次不计入；等对阵定了、能预测了下次再推。
- 凭证从 data/tg_config.json 读（{"token","chat_id"}），不提交 git。

由 fetch_wc 之后调用（server PIPELINES["wc"] 末步）。
"""
import json
import re
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
CFG = ROOT / "data" / "tg_config.json"
WC = ROOT / "data" / "wc_matches.js"
SENT = ROOT / "data" / "wc_photo_sent.txt"
BROWSE = Path.home() / ".claude" / "skills" / "gstack" / "browse" / "dist" / "browse"
PORT = 8770          # launchd 自启 server 端口（com.lottolab.server.plist）
LEAD_DAYS = 2
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


def upcoming(wc):
    """未来 LEAD_DAYS 天内、已可预测、未开赛的场次"""
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=LEAD_DAYS)
    out = []
    for m in wc.get("matches", []):
        if not m.get("pred") or m.get("score"):
            continue
        dt = datetime.fromisoformat(m["date"].replace("Z", "+00:00"))
        if now <= dt <= horizon:
            out.append(m)
    return out


def fingerprint(matches):
    return "|".join(f"{m['id']}:{m['pred']['likely']}:{m['pred'].get('boldScore')}" for m in matches)


def capture_image():
    """用 browse 把世界杯页截成高清图，返回路径或 None"""
    if not BROWSE.exists():
        return None
    img = "/tmp/wc_pred.png"
    base = f"http://127.0.0.1:{PORT}/"
    clickwc = ("[...document.querySelectorAll('#gameSwitch button')]"
               ".find(x=>x.dataset.game==='worldcup').click()")
    scroll = (clickwc + "; var d=[...document.querySelectorAll('.wc-day[open]')].pop();"
              " if(d)d.scrollIntoView({block:'start'}); window.scrollBy(0,-20)")

    def b(*args, t=40):
        return subprocess.run([str(BROWSE), *args], capture_output=True, timeout=t)
    try:
        b("goto", base)
        b("wait", "--load")
        b("js", clickwc)
        b("viewport", "1100x1700", "--scale", "2")
        b("js", scroll)
        b("screenshot", img, "--viewport")
        return img if Path(img).exists() else None
    except Exception:
        return None


def send_photo(token, chat_id, img, caption):
    r = subprocess.run([
        "curl", "-sS", "--max-time", "40",
        f"https://api.telegram.org/bot{token}/sendPhoto",
        "-F", f"chat_id={chat_id}", "-F", f"photo=@{img}", "-F", f"caption={caption}",
    ], capture_output=True, text=True, timeout=60)
    try:
        return json.loads(r.stdout).get("ok", False)
    except json.JSONDecodeError:
        return False


def send_text(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data),
                timeout=20) as r:
            return json.loads(r.read()).get("ok", False)
    except Exception:
        return False


def text_fallback(matches):
    lines = ["🏆 世界杯预测 · 未来比赛"]
    for m in matches:
        p = m["pred"]
        dt = datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(CN)
        bold = f" / 🔥{p['boldScore'][0]}-{p['boldScore'][1]}" if p.get("boldScore") else ""
        lines.append(f"{m['home']['name']} vs {m['away']['name']}（{dt.strftime('%m-%d %H:%M')}）"
                     f" 最可能 {p['likely'][0]}-{p['likely'][1]}{bold}")
    return "\n".join(lines)


def main():
    cfg = load_cfg()
    token, chat_id = cfg.get("token"), cfg.get("chat_id")
    if not token or not chat_id:
        print("[TG] 缺 token/chat_id，跳过推送")
        return

    matches = upcoming(load_wc())
    if not matches:
        print("[TG] 无未来可推送场次")
        return

    fp = fingerprint(matches)
    try:
        if SENT.read_text().strip() == fp:
            print("[TG] 预测未变化，不重复推送")
            return
    except FileNotFoundError:
        pass

    days = sorted({datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(CN).strftime("%m-%d")
                   for m in matches})
    caption = f"🏆 世界杯预测（高清）· {'/'.join(days)} 共 {len(matches)} 场\n最可能比分（准）+ 🔥大胆剧本 | Elo×市场赔率融合"

    img = capture_image()
    ok = send_photo(token, chat_id, img, caption) if img else False
    if not ok:
        ok = send_text(token, chat_id, text_fallback(matches))
        print("[TG] 截图不可用，已回落文字推送" if ok else "[TG] 推送失败")
    else:
        print(f"[TG] 已推送高清预测图（{len(matches)} 场）")

    if ok:
        tmp = SENT.with_suffix(".txt.tmp")
        tmp.write_text(fp)
        tmp.replace(SENT)


if __name__ == "__main__":
    main()
