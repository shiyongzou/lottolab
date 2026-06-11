const GAMES = {
  ssq: {
    name: '双色球',
    zoneA: { label: '红球', pick: 6, range: 33 },
    zoneB: { label: '蓝球', pick: 1, range: 16 },
    price: 2,
    tierCond: {
      1: '6+1', 2: '6+0', 3: '5+1',
      4: '5+0 / 4+1', 5: '4+0 / 3+1', 6: '2+1 / 1+1 / 0+1',
    },
    fixed: { 3: 3000, 4: 200, 5: 10, 6: 5 },
    floatDefault: { 1: 5000000, 2: 150000 },
  },
  dlt: {
    name: '大乐透',
    zoneA: { label: '前区', pick: 5, range: 35 },
    zoneB: { label: '后区', pick: 2, range: 12 },
    price: 2,
    addPrice: 1,
    tierCond: {
      1: '5+2', 2: '5+1', 3: '5+0', 4: '4+2', 5: '4+1',
      6: '3+2', 7: '4+0', 8: '3+1 / 2+2', 9: '3+0 / 1+2 / 2+1 / 0+2',
    },
    fixed: { 3: 10000, 4: 3000, 5: 300, 6: 200, 7: 100, 8: 15, 9: 5 },
    floatDefault: { 1: 8000000, 2: 150000 },
  },
};

const TIER_NAMES = ['', '一等奖', '二等奖', '三等奖', '四等奖', '五等奖', '六等奖', '七等奖', '八等奖', '九等奖'];

const combCache = new Map();
function comb(n, k) {
  if (k < 0 || k > n) return 0;
  k = Math.min(k, n - k);
  const key = n + ',' + k;
  if (combCache.has(key)) return combCache.get(key);
  let r = 1;
  for (let i = 1; i <= k; i++) r = (r * (n - k + i)) / i;
  r = Math.round(r);
  combCache.set(key, r);
  return r;
}

function tierOf(gameKey, hitA, hitB) {
  if (gameKey === 'ssq') {
    if (hitA === 6) return hitB ? 1 : 2;
    if (hitA === 5 && hitB) return 3;
    if (hitA === 5 || (hitA === 4 && hitB)) return 4;
    if (hitA === 4 || (hitA === 3 && hitB)) return 5;
    if (hitB) return 6;
    return 0;
  }
  const map = {
    '5-2': 1, '5-1': 2, '5-0': 3, '4-2': 4, '4-1': 5, '3-2': 6,
    '4-0': 7, '3-1': 8, '2-2': 8, '3-0': 9, '1-2': 9, '2-1': 9, '0-2': 9,
  };
  return map[hitA + '-' + hitB] || 0;
}

// 复式不展开枚举，按命中数的组合计数公式直接算各奖级注数
function checkBet(gameKey, bet, draw) {
  const g = GAMES[gameKey];
  const hitA = bet.a.filter((n) => draw.a.includes(n)).length;
  const hitB = bet.b.filter((n) => draw.b.includes(n)).length;
  const pa = g.zoneA.pick, pb = g.zoneB.pick;
  const tiers = {};
  for (let i = 0; i <= pa; i++) {
    const waysA = comb(hitA, i) * comb(bet.a.length - hitA, pa - i);
    if (!waysA) continue;
    for (let j = 0; j <= pb; j++) {
      const waysB = comb(hitB, j) * comb(bet.b.length - hitB, pb - j);
      if (!waysB) continue;
      const t = tierOf(gameKey, i, j);
      if (t) tiers[t] = (tiers[t] || 0) + waysA * waysB;
    }
  }
  return { hitA, hitB, tiers };
}

function betCount(gameKey, bet) {
  const g = GAMES[gameKey];
  return comb(bet.a.length, g.zoneA.pick) * comb(bet.b.length, g.zoneB.pick);
}

// 奖级精确概率（解析解，与对奖规则同源）：任何一注的概率都由规则钉死，与选号方法无关
function tierProbs(gameKey) {
  const g = GAMES[gameKey];
  const an = g.zoneA.pick, am = g.zoneA.range;
  const bn = g.zoneB.pick, bm = g.zoneB.range;
  const pa = (k) => (comb(an, k) * comb(am - an, an - k)) / comb(am, an);
  const pb = (j) => (comb(bn, j) * comb(bm - bn, bn - j)) / comb(bm, bn);
  const probs = {};
  for (let i = 0; i <= an; i++) {
    for (let j = 0; j <= bn; j++) {
      const t = tierOf(gameKey, i, j);
      if (t) probs[t] = (probs[t] || 0) + pa(i) * pb(j);
    }
  }
  return probs;
}

function anyPrizeProb(gameKey) {
  return Object.values(tierProbs(gameKey)).reduce((s, p) => s + p, 0);
}

function expectedReturn(gameKey) {
  const g = GAMES[gameKey];
  const probs = tierProbs(gameKey);
  let ev = 0;
  for (const [t, p] of Object.entries(probs)) {
    ev += p * (g.fixed[t] != null ? g.fixed[t] : g.floatDefault[t]);
  }
  return ev;
}

function probText(p) {
  if (p >= 0.001) return (p * 100).toFixed(2) + '%';
  return '1/' + Math.round(1 / p).toLocaleString('zh-CN');
}

function parseBet(gameKey, line) {
  const g = GAMES[gameKey];
  const cleaned = line.replace(/[（(].*?[)）]/g, ' ').trim();
  if (!cleaned) return null;
  let partA, partB;
  const sep = cleaned.match(/[+｜|]/);
  if (sep) {
    const idx = cleaned.indexOf(sep[0]);
    partA = cleaned.slice(0, idx);
    partB = cleaned.slice(idx + 1);
  } else {
    const all = cleaned.match(/\d+/g) || [];
    if (all.length === g.zoneA.pick + g.zoneB.pick) {
      partA = all.slice(0, g.zoneA.pick).join(' ');
      partB = all.slice(g.zoneA.pick).join(' ');
    } else {
      return { error: `无法区分${g.zoneA.label}与${g.zoneB.label}，请用 + 分隔` };
    }
  }
  const a = (partA.match(/\d+/g) || []).map(Number);
  const b = (partB.match(/\d+/g) || []).map(Number);
  if (a.length < g.zoneA.pick) return { error: `${g.zoneA.label}至少 ${g.zoneA.pick} 个号码` };
  if (b.length < g.zoneB.pick) return { error: `${g.zoneB.label}至少 ${g.zoneB.pick} 个号码` };
  if (new Set(a).size !== a.length || new Set(b).size !== b.length) return { error: '号码重复' };
  if (a.some((n) => n < 1 || n > g.zoneA.range)) return { error: `${g.zoneA.label}范围 01-${g.zoneA.range}` };
  if (b.some((n) => n < 1 || n > g.zoneB.range)) return { error: `${g.zoneB.label}范围 01-${g.zoneB.range}` };
  return { a: a.sort((x, y) => x - y), b: b.sort((x, y) => x - y) };
}
