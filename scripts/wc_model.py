#!/usr/bin/env python3
"""世界杯比分预测 · 双泊松确定性模型（零随机，同输入同输出）

足球比分不是 i.i.d. 随机——强弱有别、可建模；但单场比分高度不确定，
本模型输出的是「概率分布」，不是结果保证。这与本项目对彩票的立场一脉相承：
诚实、可复现、把不确定性原样摆出来，绝不假装能精准预测某一场。

方法（Dixon-Coles 思路的简化版，纯泊松、无随机数）：
  1. 两队 World Football Elo 之差（含主办国主场修正）→ 两队预期进球 λ
  2. λ 驱动两个独立泊松，得到 0..N 比分的联合概率矩阵
  3. 从矩阵导出最可能比分、Top 比分、胜平负、双方进球(BTTS)、大 2.5 球
参数（透明、经验标定，非数据拟合，可在页面复核）：
  AVG_GOALS=1.35  世界杯场均每队进球
  ELO_K=0.0018    Elo 差→λ 的指数斜率（约 300 Elo 差 → λ 比 ≈ 1.7×）
  HOST_ADV=70     主办国（美/加/墨）主场的 Elo 当量加成
模型确定性是「预测可对照、不可事后修改」公信力的根基：禁止引入随机数。
"""
import math

AVG_GOALS = 1.35
ELO_K = 0.0018
HOST_ADV = 70
MAX_GOALS = 8          # 概率积分用到的最大进球数
MATRIX_N = 6           # 导出给页面热力图的矩阵尺寸（0..6）


def _clamp(x, lo=0.2, hi=4.5):
    return max(lo, min(hi, x))


def expected_lambdas(elo_home, elo_away, host=False):
    """Elo 差 → 两队预期进球 λ。主办国主场加 HOST_ADV 的 Elo 当量。"""
    d = (elo_home + (HOST_ADV if host else 0)) - elo_away
    return _clamp(AVG_GOALS * math.exp(ELO_K * d)), _clamp(AVG_GOALS * math.exp(-ELO_K * d))


def _pois(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def predict(elo_home, elo_away, host=False, top_n=6):
    lh, la = expected_lambdas(elo_home, elo_away, host)
    cells = []
    for i in range(MAX_GOALS + 1):
        pi = _pois(i, lh)
        for j in range(MAX_GOALS + 1):
            cells.append((i, j, pi * _pois(j, la)))
    cells.sort(key=lambda c: -c[2])
    p_home = sum(p for i, j, p in cells if i > j)
    p_draw = sum(p for i, j, p in cells if i == j)
    p_away = sum(p for i, j, p in cells if i < j)
    btts = sum(p for i, j, p in cells if i >= 1 and j >= 1)
    over25 = sum(p for i, j, p in cells if i + j >= 3)
    return {
        "lambdaHome": round(lh, 3),
        "lambdaAway": round(la, 3),
        "topScores": [[i, j, round(p, 4)] for i, j, p in cells[:top_n]],
        "likely": [cells[0][0], cells[0][1]],
        "expScore": [round(lh, 2), round(la, 2)],
        "probs": {"home": round(p_home, 4), "draw": round(p_draw, 4), "away": round(p_away, 4)},
        "btts": round(btts, 4),
        "over25": round(over25, 4),
        # 0..MATRIX_N 的比分概率矩阵，供页面画热力图
        "matrix": [[round(_pois(i, lh) * _pois(j, la), 4) for j in range(MATRIX_N + 1)]
                   for i in range(MATRIX_N + 1)],
    }


def outcome(score_home, score_away):
    if score_home > score_away:
        return "home"
    if score_home < score_away:
        return "away"
    return "draw"


def argmax_outcome(probs):
    return max(("home", "draw", "away"), key=lambda k: probs[k])


if __name__ == "__main__":
    import sys
    eh, ea = int(sys.argv[1]), int(sys.argv[2])
    host = len(sys.argv) > 3 and sys.argv[3] == "host"
    p = predict(eh, ea, host)
    print(f"λ {p['lambdaHome']}-{p['lambdaAway']}  最可能 {p['likely'][0]}-{p['likely'][1]}")
    print("Top:", "  ".join(f"{i}-{j} {pr*100:.1f}%" for i, j, pr in p["topScores"]))
    pr = p["probs"]
    print(f"胜平负 {pr['home']*100:.0f}/{pr['draw']*100:.0f}/{pr['away']*100:.0f}  "
          f"BTTS {p['btts']*100:.0f}%  大2.5球 {p['over25']*100:.0f}%")
