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
    "你是「足球小子」，世界杯预测助手，在 Telegram 和用户中文对话。"
    "下方【预测数据】已含全部场次（北京时间、对阵、最可能比分、🔥大胆剧本、胜平负%、实际比分）。"
    "优先直接用这些数据，简洁口语秒答——别去读文件、别纠结过程。"
    "只有用户明确问实时信息（伤病/阵容/新闻）时才联网查。"
    "诚实：预测是概率不是保证。绝不修改文件、不跑命令。回答简短，适合手机，别超 10 行。"
    "重要：紧扣用户当前这句话回答，有上下文就顺着聊；别答非所问、别堆无关数据。"
)

CHAT_HIST = {}


def build_context(wc):
    rows = []
    for m in wc.get("matches", []):
        if not m.get("pred"):
            continue
        dt = datetime.fromisoformat(m["date"].replace("Z", "+00:00")).astimezone(CN)
        p = m["pred"]
        pr = p["probs"]
        sc = f" 实际{m['score']['home']}-{m['score']['away']}" if m.get("score") else ""
        rows.append(
            f"{dt.strftime('%m-%d %H:%M')} {m['home']['name']}vs{m['away']['name']} "
            f"最可能{p['likely'][0]}-{p['likely'][1]} 大胆{p['boldScore'][0]}-{p['boldScore'][1]} "
            f"胜平负{round(pr['home']*100)}/{round(pr['draw']*100)}/{round(pr['away']*100)}{sc}")
    return "\n".join(rows)


def ask_claude(text, wc, chat=None, hist_text=None):
    """自然语言交给本机 claude（预喂数据 + 多轮记忆 + sonnet）"""
    sys = CLAUDE_SYS + "\n\n【预测数据】\n" + build_context(wc)
    prompt = text
    if chat and CHAT_HIST.get(chat):
        recent = "\n".join(f"用户：{q}\n你：{a}" for q, a in CHAT_HIST[chat][-3:])
        prompt = f"【最近对话，供理解上下文，用户可能在追问/用「那/这场」等指代】\n{recent}\n\n【用户现在说】\n{text}"
    try:
        r = subprocess.run(
            ["claude", "-p", prompt, "--append-system-prompt", sys, "--model", "sonnet"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=150)
        ans = (r.stdout or "").strip() or "（没拿到回复，换个说法再问问）"
    except subprocess.TimeoutExpired:
        ans = "（这个有点复杂查得久，稍后再试或问简单点～）"
    except Exception as e:
        ans = f"（出错了：{e}）"
    if chat:
        CHAT_HIST.setdefault(chat, []).append((hist_text or text, ans))
        CHAT_HIST[chat] = CHAT_HIST[chat][-5:]
    return ans


BROWSE = Path.home() / ".claude" / "skills" / "gstack" / "browse" / "dist" / "browse"


def capture_day(month, day):
    """截某天的预测卡片高清图（retina ×2），返回路径或 None"""
    if not BROWSE.exists():
        return None
    label = f"{month}/{day}"
    img = "/tmp/wc_day.png"
    clickwc = "[...document.querySelectorAll('#gameSwitch button')].find(x=>x.dataset.game==='worldcup').click()"
    expand = (clickwc + ";var ds=[...document.querySelectorAll('.wc-day')];"
              "ds.forEach(d=>{var t=d.querySelector('.wc-day-date');"
              "d.open=!!(t&&t.textContent.includes('" + label + "'))});"
              "var t=ds.find(d=>d.open);if(t)t.scrollIntoView({block:'start'});window.scrollBy(0,-15)")

    def b(*a, t=40):
        subprocess.run([str(BROWSE), *a], capture_output=True, timeout=t)
    try:
        b("goto", "http://127.0.0.1:8770/")
        b("wait", "--load")
        b("js", clickwc)
        b("viewport", "1100x2200", "--scale", "2")
        b("js", expand)
        b("screenshot", img, "--viewport")
        return img if Path(img).exists() else None
    except Exception:
        return None


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


def reply_day(token, wc, chat, month, day, title):
    if not day_matches(wc, f"{month:02d}-{day:02d}"):
        send(token, chat, f"{title}：暂无可预测场次（未排期或对阵未定）")
        return
    api(token, "sendChatAction", chat_id=chat, action="upload_photo")
    img = capture_day(month, day)
    cap = f"🏆 {title} · 世界杯预测（最可能 + 🔥大胆剧本）"
    if not (img and send_photo(token, chat, img, cap)):
        send(token, chat, fmt_day(wc, f"{month:02d}-{day:02d}", title))  # 截图失败回落文字


TICKETS_FILE = ROOT / "data" / "wc_tickets.txt"
WATCH_FILE = ROOT / "data" / "wc_ticket_watch.json"
TICKET_STATE = ROOT / "data" / "wc_ticket_state.json"


def setup_track(token, wc, chat, path):
    """用户发票图+「跟单」→ 识别票面+涉及场次 → 写监控列表，开始跟单"""
    prompt = (f"用 Read 工具看这张彩票图 {path}。输出两部分：\n"
              "① 用几行简述每张票的玩法和每场选项；\n"
              "② 最后单独一行，以「场次=」开头，列出票里涉及的所有比赛，"
              "每场格式『中文主队|中文客队』，多场用分号 ; 分隔（用最常见的中文队名）。")
    ans = ask_claude(prompt, wc)
    TICKETS_FILE.write_text(ans)
    watch = {}
    m = re.search(r"场次[=＝](.+)", ans)
    if m:
        for pair in m.group(1).split(";"):
            if "|" not in pair and "｜" not in pair:
                continue
            parts = re.split(r"[|｜]", pair)
            hn, an = parts[0].strip(), parts[1].strip()
            for mt in wc.get("matches", []):
                if not mt.get("pred") or mt.get("score"):
                    continue
                hname, aname = mt["home"]["name"], mt["away"]["name"]
                if (hn in hname or hname in hn) and (an in aname or aname in an):
                    watch[mt["id"]] = f"{hname} vs {aname}"
                    break
    WATCH_FILE.write_text(json.dumps(watch, ensure_ascii=False))
    try:
        TICKET_STATE.unlink()
    except FileNotFoundError:
        pass
    if watch:
        send(token, chat, f"✅ 已开始跟单 {len(watch)} 场：\n" + "\n".join(watch.values())
             + "\n\n半场结束 / 进球 / 完场都会自动推你对照中没中。")
    else:
        send(token, chat, "看了票，但没匹配到可跟单的未开赛场次（可能已开赛或队名没对上）。\n" + ans[-300:])


def get_photo(token, file_id):
    """下载 TG 图片到本地，返回路径"""
    r = api(token, "getFile", file_id=file_id)
    fp = (r.get("result") or {}).get("file_path")
    if not fp:
        return None
    path = "/tmp/wc_in.jpg"
    try:
        urllib.request.urlretrieve(f"https://api.telegram.org/file/bot{token}/{fp}", path)
        return path
    except Exception:
        return None


def handle_photo(token, wc, chat, photos, caption):
    """用户发图 → 下载 → 交给 claude 看图分析"""
    api(token, "sendChatAction", chat_id=chat, action="typing")
    path = get_photo(token, photos[-1]["file_id"])
    if not path:
        send(token, chat, "图片没收到，再发一次试试～")
        return
    if "跟单" in (caption or ""):
        setup_track(token, wc, chat, path)
        return
    prompt = (f"用户在 Telegram 发来一张图片，本地路径：{path}。请用 Read 工具看图再回应。"
              + (f"用户附言：{caption}。" if caption else "")
              + "若是彩票/竞彩票：识别买的场次、玩法(总进球数/胜平负/半全场等)和每场选项；"
              + "再对照下方【预测数据】里标了'实际'比分的真实结果——已结束的逐场说中没中，"
              + "没标实际比分的说明还没开踢、结束后再帮对。用中文简洁口语回答。")
    send(token, chat, ask_claude(prompt, wc, chat, hist_text="[用户发来一张彩票/比赛图片]" + (caption or "")))


def handle(token, wc, chat, text, reply=""):
    t = text.strip()
    now = datetime.now(CN)
    if t in ("/start", "/帮助", "/help"):
        send(token, chat, HELP)
        return
    if t in ("/今天", "/today"):
        reply_day(token, wc, chat, now.month, now.day, "今天")
        return
    if t in ("/明天", "/tomorrow"):
        d = now + timedelta(days=1)
        reply_day(token, wc, chat, d.month, d.day, "明天")
        return
    mt = re.match(r"/day\s+(\d{1,2})-(\d{1,2})", t) or re.match(r"/(\d{1,2})-(\d{1,2})$", t)
    if mt:
        a, bb = int(mt.group(1)), int(mt.group(2))
        reply_day(token, wc, chat, a, bb, f"{a}月{bb}日")
        return
    # 非指令 → 自然语言，交给 Claude 理解（像和这个会话对话一样）
    api(token, "sendChatAction", chat_id=chat, action="typing")
    q = f"（用户正在回复你之前发的这条消息：\n「{reply}」）\n用户现在说：{t}" if reply else t
    send(token, chat, ask_claude(q, wc, chat))


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
            photos = msg.get("photo")
            if photos and chat:
                handle_photo(token, wc, chat, photos, msg.get("caption", ""))
            elif text and chat:
                handle(token, wc, chat, text, reply)
        OFF.write_text(str(offset))


if __name__ == "__main__":
    main()
