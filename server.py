#!/usr/bin/env python3
"""本地控制台：静态页 + 刷新接口

GET  /api/ping    探活（页面据此显示「更新数据」按钮）
GET  /api/status  流水线状态 {running, ok, log}
POST /api/refresh 启动流水线：fetch_data → claude_model → codex_model → merge_picks
"""
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).parent
WALLET = ROOT / "data" / "wallet.json"
BASE_PORT = 8765

STATE = {"running": False, "ok": None, "log": [], "task": None}
STATE_LOCK = threading.Lock()

PIPELINES = {
    "refresh": [
        ("拉取最新开奖数据", ["fetch_data.py"], 180),
        ("更新全量档案", ["fetch_data.py", "--full"], 180),
        ("Claude(Fable 5) 模型推算（150期窗口）", ["scripts/fable_model.py"], 180),
        ("Claude(Fable 5) 模型推算（全量窗口）", ["scripts/fable_model.py", "full"], 180),
        ("Codex 模型推算（150期窗口）", ["scripts/codex_model.py"], 180),
        ("Codex 模型推算（全量窗口）", ["scripts/codex_model.py", "full"], 180),
        ("合并双脑共识", ["scripts/merge_picks.py"], 180),
        ("更新预测台账", ["scripts/ledger.py"], 180),
    ],
    "backtest": [
        ("更新全量档案", ["fetch_data.py", "--full"], 180),
        ("滚动回测 300 期（约 2-3 分钟）", ["scripts/backtest.py", "300", "6"], 600),
    ],
    "wc": [
        ("世界杯赛程+比分+预测对照", ["fetch_wc.py"], 120),
        ("推送预测到 Telegram", ["scripts/wc_notify.py"], 60),
    ],
}


def run_pipeline(task):
    try:
        _run_pipeline(task)
    finally:
        STATE["running"] = False


def _run_pipeline(task):
    STATE["log"] = []
    STATE["ok"] = None
    STATE["task"] = task
    for name, script, step_timeout in PIPELINES[task]:
        STATE["log"].append(f"▶ {name}…")
        try:
            p = subprocess.run(
                [sys.executable, *script],
                cwd=ROOT, capture_output=True, text=True, timeout=step_timeout,
            )
        except subprocess.TimeoutExpired:
            STATE["log"].append(f"✗ {name} 超时")
            STATE["ok"] = False
            STATE["running"] = False
            return
        if p.returncode != 0:
            err = (p.stderr or p.stdout or "").strip()
            STATE["log"].append(f"✗ {name} 失败：{err[-400:]}")
            STATE["ok"] = False
            STATE["running"] = False
            return
        for line in (p.stdout or "").strip().splitlines()[-4:]:
            STATE["log"].append(f"  {line}")
        STATE["log"].append(f"✓ {name} 完成")
    STATE["log"].append("全部完成，页面即将刷新")
    STATE["ok"] = True
    STATE["running"] = False


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/ping":
            return self._json({"pong": True})
        if self.path == "/api/status":
            return self._json({"running": STATE["running"], "ok": STATE["ok"], "log": STATE["log"], "task": STATE["task"]})
        if self.path == "/api/wallet":
            try:
                return self._json(json.loads(WALLET.read_text()) if WALLET.exists() else [])
            except json.JSONDecodeError:
                return self._json([])
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/wallet":
            try:
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                data = json.loads(body)
                if not isinstance(data, list):
                    raise ValueError
            except (ValueError, json.JSONDecodeError):
                return self._json({"ok": False}, 400)
            tmp = WALLET.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False))
            os.replace(tmp, WALLET)
            return self._json({"ok": True})
        task = {"/api/refresh": "refresh", "/api/backtest": "backtest", "/api/wc": "wc"}.get(self.path)
        if task:
            with STATE_LOCK:
                if STATE["running"]:
                    return self._json({"started": False, "reason": "已有任务在运行"})
                STATE["running"] = True
            threading.Thread(target=run_pipeline, args=(task,), daemon=True).start()
            return self._json({"started": True})
        self.send_error(404)

    def end_headers(self):
        if self.path.startswith(("/data/", "/js/", "/css/")) or self.path == "/":
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *args):
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else BASE_PORT
    server = None
    for p in range(port, port + 10):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            continue
    if server is None:
        print(f"端口 {port}~{port + 9} 均被占用，请指定端口：python3 server.py 9000")
        sys.exit(1)
    url = f"http://127.0.0.1:{port}/"
    print(f"彩数实验室运行中：{url}（Ctrl+C 退出）")
    if not os.environ.get("LOTTOLAB_NO_BROWSER"):
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已退出")


if __name__ == "__main__":
    main()
