#!/usr/bin/env python3
"""世界杯交互 bot · 长轮询监听指令，回复某天预测

指令：/今天  /明天  /day 6-20（月-日）  /帮助
常驻长轮询（launchd KeepAlive）。专属 bot，getUpdates 无人争用。
凭证 data/tg_config.json；预测数据 data/wc_matches.js（实时读，刷新即生效）。
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
OFF = ROOT / "data" / "wc_bot_offset.txt"
CN = timezone(timedelta(hours=8))

HELP = ("⚽ <b>足球小子 · 世界杯预测</b>\n"
        "/今天 — 今天比赛预测\n"
        "/明天 — 明天比赛预测\n"
        "/day 6-20 — 指定日期（月-日）\n"
        "/帮助 — 本说明\n\n"
        "每场给：最可能比分（准）+ 🔥大胆剧本 + 胜平负%")


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


def api(token, method, **params):
    data = urllib.parse.urlencode(params).encode()
    try:
        with urllib.request.urlopen(
                urllib.request.Request(f"https://api.telegram.org/bot{token}/{method}", data=data),
                timeout=40) as r:
            return json.loads(r.read())
    except Exception:
        return {}


def send(token, chat, text):
    api(token, "sendMessage", chat_id=chat, text=text, parse_mode="HTML",
        disable_web_page_preview="true")


def day_matches(wc, daykey):
    out = []
    for m in wc.get("matches", []):
        if not m.get("pred"):
            continue
        dt = datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(CN)
        if dt.strftime("%m-%d") == daykey:
            out.append((dt, m))
    out.sort(key=lambda x: x[0])
    return out


def fmt_day(wc, daykey, title):
    ms = day_matches(wc, daykey)
    if not ms:
        return f"{title}：暂无可预测场次（未排期，或淘汰赛对阵未定）"
    lines = [f"🏆 <b>{title} · {len(ms)} 场</b>"]
    for dt, m in ms:
        p = m["pred"]
        pr = p["probs"]
        bold = f" / 🔥{p['boldScore'][0]}-{p['boldScore'][1]}" if p.get("boldScore") else ""
        score = ""
        if m.get("score"):
            score = f"（实际 {m['score']['home']}-{m['score']['away']}）"
        lines.append(
            f"\n{dt.strftime('%H:%M')} {m['home']['name']} vs {m['away']['name']}{score}\n"
            f"  最可能 {p['likely'][0]}-{p['likely'][1]}{bold} | "
            f"胜平负 {round(pr['home']*100)}/{round(pr['draw']*100)}/{round(pr['away']*100)}")
    return "\n".join(lines)


CLAUDE_SYS = (
    "你是「足球小子」，世界杯预测助手，在 Telegram 上和用户（李雷）中文对话。"
    "当前目录 data/wc_matches.js 是 window.WC_DATA，matches[] 每场含："
    "home/away（name 队名、elo 实力分）、date（UTC 时间）、group、host（是否主办国主场）、"
    "pred.likely（统计最可能比分）、pred.boldScore（🔥大胆剧本比分）、"
    "pred.probs（融合胜/平/负概率）、pred.eloProbs/marketProbs（纯Elo/市场赔率胜平负）、"
    "pred.divergence（模型与市场背离度）、score（实际比分）、result（开赛后对照命中）。"
    "data/wc_matches.js 时间是 UTC，北京时间要 +8 小时。"
    "用简洁口语中文回答用户关于世界杯预测、比赛、球队的任何问题；可以读项目数据、可以联网查实时信息（伤病/新闻等）。"
    "诚实：模型预测是概率不是保证，最可能比分统计上偏小、大胆剧本才敢报大比分。"
    "绝对不要修改任何文件、不要运行构建/部署/git。回答简短，适合手机看，别超过 12 行。"
)


def ask_claude(text):
    """把自然语言消息交给本机 claude CLI 理解并回答（读项目数据、可联网）"""
    try:
        r = subprocess.run(
            ["claude", "-p", text, "--append-system-prompt", CLAUDE_SYS],
            cwd=str(ROOT), capture_output=True, text=True, timeout=180)
        return (r.stdout or "").strip() or "（没拿到回复，换个说法再问问）"
    except subprocess.TimeoutExpired:
        return "（想太久超时了，问题说简单点再试）"
    except Exception as e:
        return f"（出错了：{e}）"


def handle(token, wc, chat, text, reply=""):
    t = text.strip()
    now = datetime.now(CN)
    if t in ("/start", "/帮助", "/help"):
        send(token, chat, HELP)
        return
    if t in ("/今天", "/today"):
        send(token, chat, fmt_day(wc, now.strftime("%m-%d"), "今天"))
        return
    if t in ("/明天", "/tomorrow"):
        d = now + timedelta(days=1)
        send(token, chat, fmt_day(wc, d.strftime("%m-%d"), "明天"))
        return
    mt = re.match(r"/day\s+(\d{1,2})-(\d{1,2})", t) or re.match(r"/(\d{1,2})-(\d{1,2})$", t)
    if mt:
        key = f"{int(mt.group(1)):02d}-{int(mt.group(2)):02d}"
        send(token, chat, fmt_day(wc, key, key))
        return
    # 非指令 → 自然语言，交给 Claude 理解（像和这个会话对话一样）
    api(token, "sendChatAction", chat_id=chat, action="typing")
    q = f"（用户正在回复你之前发的这条消息：\n「{reply}」）\n用户现在说：{t}" if reply else t
    send(token, chat, ask_claude(q))


def main():
    token = load_cfg().get("token")
    if not token:
        return
    try:
        offset = int(OFF.read_text())
    except (FileNotFoundError, ValueError):
        offset = 0
    while True:
        r = api(token, "getUpdates", offset=offset, timeout=30)
        wc = load_wc()
        for u in r.get("result", []):
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            text, chat = msg.get("text", ""), msg.get("chat", {}).get("id")
            reply = (msg.get("reply_to_message") or {}).get("text", "")
            if text and chat:
                handle(token, wc, chat, text, reply)
        OFF.write_text(str(offset))


if __name__ == "__main__":
    main()
