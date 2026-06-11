#!/bin/bash
# 一键刷新：拉取最新真实开奖 → 双模型（150期窗口 + 全量窗口）→ 合并共识
set -e
cd "$(dirname "$0")/.."
python3 fetch_data.py
python3 fetch_data.py --full
python3 scripts/fable_model.py
python3 scripts/fable_model.py full
python3 scripts/codex_model.py
python3 scripts/codex_model.py full
python3 scripts/merge_picks.py
python3 scripts/ledger.py
echo "完成。刷新浏览器即可在「数据推理」页查看双窗口推算与预测台账。"
