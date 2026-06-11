#!/bin/bash
# 开奖夜自动刷新：先探数据源，确认当天开奖号已落库再跑全流水线
# 数据源开奖后 10-40 分钟才更新，固定时间跑一次会扑空，所以每 10 分钟重试，最多 6 次
# 开奖时刻表按北京时间，强制 TZ 以免机器时区漂移
export TZ=Asia/Shanghai
cd "$(dirname "$0")/.."
TODAY=$(date +%Y-%m-%d)
DOW=$(date +%w)

notify() {
  osascript -e "display notification \"$1\" with title \"彩数实验室\"" 2>/dev/null || true
}

if [ "$DOW" = "5" ]; then
  ./scripts/ai_pick.sh && notify "今日无开奖，例行数据维护完成"
  exit 0
fi

GOT=""
for i in 1 2 3 4 5 6; do
  python3 fetch_data.py >/dev/null 2>&1
  LATEST=$(python3 -c "
import json, re
d = json.loads(re.search(r'window\.LOTTO_DATA = (.*);', open('data/draws.js').read(), re.S).group(1))
print(max(d['ssq'][0]['date'], d['dlt'][0]['date']))
")
  echo "[$(date '+%H:%M:%S')] 第 $i 次探测，数据源最新开奖日 $LATEST（目标 $TODAY）"
  if [ "$LATEST" = "$TODAY" ]; then
    echo "当天开奖已落库，执行完整流水线"
    GOT=1
    break
  fi
  [ "$i" = "6" ] && break
  sleep 600
done

if ./scripts/ai_pick.sh; then
  if [ -n "$GOT" ]; then
    notify "今晚开奖已入库，双脑已重算，台账已对照"
  else
    notify "重试 6 次未取到今晚开奖（数据源更新慢），已按现有数据维护；23:00 任务会再试"
  fi
else
  notify "自动刷新失败，详见 /tmp/lottolab-cron.log"
fi
