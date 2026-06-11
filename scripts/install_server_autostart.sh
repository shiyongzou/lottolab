#!/bin/bash
# 安装/更新「彩数实验室常驻服务」开机自启（server.py 后台常驻，路径自动适配本机，迁移后跑一次即可）
# 端口固定 8770（避开桌面控制面板占用的 8765）；后台服务不弹浏览器，登录即起、崩溃自动拉起。
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PY="$(command -v python3)"
PORT=8770
PLIST="$HOME/Library/LaunchAgents/com.lottolab.server.plist"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.lottolab.server</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PY}</string>
    <string>${DIR}/server.py</string>
    <string>${PORT}</string>
  </array>
  <key>WorkingDirectory</key><string>${DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    <key>LOTTOLAB_NO_BROWSER</key><string>1</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/lottolab-server.log</string>
  <key>StandardErrorPath</key><string>/tmp/lottolab-server.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "常驻服务已安装：开机/登录自动启动，崩溃自动拉起"
echo "  访问地址 http://127.0.0.1:${PORT}/"
echo "  项目路径 ${DIR}"
echo "  python   ${PY}"
echo "  日志      tail -f /tmp/lottolab-server.log"
