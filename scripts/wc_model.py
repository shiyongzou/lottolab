#!/usr/bin/env python3
"""世界杯比分预测 · 多维确定性融合模型（零随机，同输入同输出）

足球比分不是 i.i.d. 随机——强弱有别、可建模；但单场比分高度不确定，
本模型输出的是「概率分布」，不是结果保证。这与本项目对彩票的立场一脉相承：
诚实、可复现、把不确定性原样摆出来，绝不假装能精准预测某一场。

多维融合（全部为真实数据 + 固定权重，确定性可复现，运行期零 LLM）：
  1. Elo 双泊松：两队 World Football Elo 差（含主办国主场修正）→ 两队预期进球 λ
  2. 市场赔率：博彩 moneyline 去抽水 → 市场隐含胜平负概率；overUnder → 市场预期总进球。
     市场已把伤病、停赛、状态、动机等一切定价进去，是最浓缩的多维信号。
  3. 融合：Elo λ 与「市场反推 λ」按固定权重融合（市场权重 MARKET_W），统一驱动比分分布。
  4. 背离信号：纯 Elo 胜平负 vs 市场胜平负的最大差，用作「模型/市场分歧」提示
     （负责任地替代主观「假球判断」——真正的异常靠数据，不靠臆测）。
没有市场赔率时自动退化为纯 Elo（确定性不变）。
模型确定性是「预测可对照、不可事后改」的根基：禁止引入随机数。
"""
import math

AVG_GOALS = 1.35       # 世界杯场均每队进球
ELO_K = 0.0018         # Elo 差 → λ 斜率（标准校准档，不放大）
HOST_ADV = 70          # 主办国（美/加/墨）主场的 Elo 当量加成
MARKET_W = 0.80        # 市场赔率权重（准确率第一：市场是最强基准，回测 28 场 57% > 纯 Elo 54%）
MARKET_TILT = 0.6      # 市场净胜倾向 → λ 分配的强度
DIV_FLAG = 0.20        # 模型/市场背离超过此值则标记提示（显著分歧 → 该场更难测）
# 「大胆剧本」比分：放大实力差 + 市场进球预期，悬殊场敢报大比分（观赏向，与准确的最可能比分并列展示，确定性）
BOLD_K = 0.0034
BOLD_INFLATE = 1.55    # 调高：势均场也敢报 2-1/2-2，不再缩成 1-1
BOLD_CAP = 6.5         # 大胆比分单队进球 λ 上限，防止悬殊场爆到 8-0
MAX_GOALS = 8          # 概率积分用到的最大进球数
MATRIX_N = 6           # 导出给页面热力图的矩阵尺寸（0..6）


def _clamp(x, lo=0.2, hi=4.5):
    return max(lo, min(hi, x))


def _pois(k, lam):
    return math.exp(-lam) * lam ** k / math.factorial(k)


def expected_lambdas(elo_home, elo_away, host=False):
    """Elo 差 → 两队预期进球 λ。主办国主场加 HOST_ADV 的 Elo 当量。"""
    d = (elo_home + (HOST_ADV if host else 0)) - elo_away
    return _clamp(AVG_GOALS * math.exp(ELO_K * d)), _clamp(AVG_GOALS * math.exp(-ELO_K * d))


def _outcome_probs(lh, la):
    """两队 λ → 胜/平/负 + 双方进球 + 大2.5球概率"""
    home = draw = btts = over25 = 0.0
    for i in range(MAX_GOALS + 1):
        pi = _pois(i, lh)
        for j in range(MAX_GOALS + 1):
            p = pi * _pois(j, la)
            if i > j:
                home += p
            elif i == j:
                draw += p
            if i >= 1 and j >= 1:
                btts += p
            if i + j >= 3:
                over25 += p
    return {"home": home, "draw": draw, "away": max(0.0, 1 - home - draw)}, btts, over25


def american_to_prob(ml):
    """美式赔率 moneyline → 隐含概率（未去抽水）"""
    if ml is None:
        return None
    ml = float(ml)
    return (100 / (ml + 100)) if ml > 0 else ((-ml) / ((-ml) + 100))


def market_probs(home_ml, draw_ml, away_ml):
    """三路 moneyline → 去抽水归一化的胜平负概率"""
    ph, pd, pa = american_to_prob(home_ml), american_to_prob(draw_ml), american_to_prob(away_ml)
    if None in (ph, pd, pa):
        return None
    s = ph + pd + pa
    if s <= 0:
        return None
    return {"home": ph / s, "draw": pd / s, "away": pa / s}


def predict(elo_home, elo_away, host=False, market=None, over_under=None, top_n=6):
    """多维融合预测。market 为 market_probs() 的输出（或 None），over_under 为市场预期总进球。"""
    lh, la = expected_lambdas(elo_home, elo_away, host)
    elo_pr, _, _ = _outcome_probs(lh, la)        # 纯 Elo 胜平负，用于背离信号

    source = "elo"
    if market and over_under:
        tilt = market["home"] - market["away"]
        lmh = over_under / 2 * (1 + tilt * MARKET_TILT)
        lma = over_under / 2 * (1 - tilt * MARKET_TILT)
        lh = _clamp((1 - MARKET_W) * lh + MARKET_W * lmh)
        la = _clamp((1 - MARKET_W) * la + MARKET_W * lma)
        source = "elo+market"

    cells = [(i, j, _pois(i, lh) * _pois(j, la)) for i in range(MAX_GOALS + 1) for j in range(MAX_GOALS + 1)]
    cells.sort(key=lambda c: -c[2])
    probs, btts, over25 = _outcome_probs(lh, la)

    out = {
        "lambdaHome": round(lh, 3),
        "lambdaAway": round(la, 3),
        "topScores": [[i, j, round(p, 4)] for i, j, p in cells[:top_n]],
        "likely": [cells[0][0], cells[0][1]],
        "boldScore": bold_score(elo_home, elo_away, host, over_under),
        "expScore": [round(lh, 2), round(la, 2)],
        "probs": {k: round(v, 4) for k, v in probs.items()},
        "btts": round(btts, 4),
        "over25": round(over25, 4),
        "source": source,
        "matrix": [[round(_pois(i, lh) * _pois(j, la), 4) for j in range(MATRIX_N + 1)]
                   for i in range(MATRIX_N + 1)],
    }
    if market:
        div = max(abs(elo_pr[k] - market[k]) for k in ("home", "draw", "away"))
        out["eloProbs"] = {k: round(v, 4) for k, v in elo_pr.items()}
        out["marketProbs"] = {k: round(v, 4) for k, v in market.items()}
        out["divergence"] = round(div, 4)
        out["divergenceFlag"] = div >= DIV_FLAG
        if over_under is not None:
            out["overUnder"] = over_under
    return out


def bold_score(elo_home, elo_away, host=False, over_under=None):
    """大胆剧本比分：市场进球预期(overUnder)定总量 + 放大的实力差定分配 + 悬殊加成。
    悬殊场敢报大比分(如 6-0)，低进球场偏小(可能 0-0/1-0)。确定性，仅观赏参考。"""
    d = (elo_home + (HOST_ADV if host else 0)) - elo_away
    total = (over_under or 2.6) * BOLD_INFLATE + abs(d) / 300.0
    tilt = math.tanh(BOLD_K * d)
    lh = min(BOLD_CAP, max(0.4, total / 2 * (1 + tilt)))
    la = min(BOLD_CAP, max(0.4, total / 2 * (1 - tilt)))
    bi = max(range(MAX_GOALS + 1), key=lambda i: _pois(i, lh))
    bj = max(range(MAX_GOALS + 1), key=lambda j: _pois(j, la))
    return [bi, bj]


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
