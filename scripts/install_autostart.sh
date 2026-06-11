#!/bin/bash
# 安装/更新开奖夜自动刷新定时任务（路径自动适配当前机器，迁移到新机器后跑一次即可）
# launchd 的 StartCalendarInterval 按本机时钟触发，而开奖时刻表是北京时间——
# 这里把北京 21:45 / 23:00 动态换算成本机时刻再写入 plist，任何时区的机器都自适应
# （此前写死 21:45/23:00 本机时钟，在 UTC+7 机器上 23:00 班 = 北京次日 0 点，
#   auto_refresh.sh 内 TZ=Asia/Shanghai 取到的"今天"错位成次日，兜底班全部扑空）。
set -e
DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.lottolab.autorefresh.plist"

read H1 M1 H2 M2 <<< "$(python3 - <<'PY'
import time
# 本机相对 UTC 的偏移（秒，含夏令时）
off = -time.altzone if time.localtime().tm_isdst else -time.timezone

def conv(bj_h, bj_m):
    total = ((bj_h - 8) * 60 + bj_m + off // 60) % (24 * 60)
    return total // 60, total % 60

a = conv(21, 45)
b = conv(23, 0)
print(a[0], a[1], b[0], b[1])
PY
)"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.lottolab.autorefresh</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${DIR}/scripts/auto_refresh.sh</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>${H1}</integer><key>Minute</key><integer>${M1}</integer></dict>
    <dict><key>Hour</key><integer>${H2}</integer><key>Minute</key><integer>${M2}</integer></dict>
  </array>
  <key>StandardOutPath</key><string>/tmp/lottolab-cron.log</string>
  <key>StandardErrorPath</key><string>/tmp/lottolab-cron.log</string>
</dict>
</plist>
EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
printf "定时任务已安装：北京时间每晚 21:45 / 23:00 自动刷新（本机时钟 %02d:%02d / %02d:%02d，项目路径 %s）\n" "$H1" "$M1" "$H2" "$M2" "$DIR"
echo "auto_refresh.sh 内部统一按北京时间（TZ=Asia/Shanghai）判断开奖日"
