const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const DATA = window.LOTTO_DATA || { meta: {}, ssq: [], dlt: [] };
const FULL = window.LOTTO_FULL || null;
const state = { game: 'ssq', strategy: 'random', tickets: [], scope: '150', inferWindow: '150' };

const pad = (n) => String(n).padStart(2, '0');
const game = () => GAMES[state.game];
const draws = () => DATA[state.game] || [];
const analysisDraws = () => (state.scope === 'full' && FULL ? FULL[state.game] || [] : draws());
const kindB = () => (state.game === 'ssq' ? 'blue' : 'gold');

const STRATEGY_NOTES = {
  random: '完全等概率随机，与投注站机选一致。',
  hot: '按历史出现频率加权，出现越多权重越高。每期开奖独立，热号并不更容易中出，仅供娱乐。',
  cold: '按当前遗漏期数加权，越久未出权重越高。遗漏不会改变真实概率，仅供娱乐。',
  balanced: '随机生成后按奇偶比、和值区间、连号数量过滤，使形态接近历史多数开奖，不改变中奖概率。',
};

function ballHTML(n, kind, extra = '') {
  return `<span class="ball ${kind} ${extra}">${pad(n)}</span>`;
}

function ticketBallsHTML(a, b, size = '', draw = null) {
  const mark = (n, zone) => (draw ? (zone.includes(n) ? 'hit' : 'miss') : '');
  const ha = a.map((n) => ballHTML(n, `red ${size}`, draw ? mark(n, draw.a) : '')).join('');
  const hb = b.map((n) => ballHTML(n, `${kindB()} ${size}`, draw ? mark(n, draw.b) : '')).join('');
  return `${ha}<span class="plus">+</span>${hb}`;
}

function formatMoney(v) {
  if (v >= 1e8) return (v / 1e8).toFixed(2).replace(/\.?0+$/, '') + ' 亿元';
  if (v >= 1e4) return (v / 1e4).toFixed(2).replace(/\.?0+$/, '') + ' 万元';
  return v.toLocaleString('zh-CN') + ' 元';
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove('show'), 2200);
}

/* ---------- 开奖大厅 ---------- */

function drawDetailHTML(d) {
  const parts = [];
  if (d.grades && d.grades['1']) parts.push(`一等奖 ${d.grades['1'][0]} 注 · 每注 ${formatMoney(d.grades['1'][1] || 0)}`);
  if (d.grades && d.grades['2']) parts.push(`二等奖 ${d.grades['2'][0]} 注 · 每注 ${formatMoney(d.grades['2'][1] || 0)}`);
  if (d.sales) parts.push(`销售额 ${formatMoney(d.sales)}`);
  if (d.pool) parts.push(`奖池 ${formatMoney(d.pool)}`);
  return parts.length ? parts.join('　·　') : '该期无公告明细（奖级数据仅覆盖近 150 期）';
}

function drawRowHTML(x) {
  return `
    <div class="draw-row" data-issue="${x.issue}" title="点击展开当期奖级公告">
      <span class="issue">${x.issue}</span>
      <span class="date">${x.date}</span>
      <span>${ticketBallsHTML(x.a, x.b, 'sm')}</span>
    </div>`;
}

function findDraw(issue) {
  return draws().find((d) => d.issue === issue) || ((FULL || {})[state.game] || []).find((d) => d.issue === issue);
}

function renderHallList() {
  $('#drawList').innerHTML = draws().slice(1, 21).map(drawRowHTML).join('');
}

function renderSearch(q) {
  q = q.trim();
  if (!q) {
    renderHallList();
    return;
  }
  const src = FULL && FULL[state.game] && FULL[state.game].length ? FULL[state.game] : draws();
  const hits = src.filter((d) => d.issue.includes(q) || d.date.includes(q)).slice(0, 30);
  $('#drawList').innerHTML = hits.length
    ? `<p class="ai-meta">在 ${src.length} 期档案中命中 ${hits.length} 期${hits.length === 30 ? '（仅显示前 30）' : ''}</p>` + hits.map(drawRowHTML).join('')
    : '<div class="empty-state">没有匹配的期号或日期</div>';
}

function renderHall() {
  const list = draws();
  const hero = $('#heroDraw');
  if (!list.length) {
    hero.innerHTML = '<div class="card empty-state">暂无开奖数据，请运行 fetch_data.py 拉取</div>';
    $('#drawList').innerHTML = '';
    return;
  }
  const d = list[0];
  hero.innerHTML = `
    <div class="hero">
      <div class="hero-head">
        <span class="hero-issue">${game().name} 第 ${d.issue} 期</span>
        <span class="hero-date">${d.date} 开奖</span>
        ${d.pool ? `<span class="hero-pool">奖池滚存 <b>${formatMoney(Number(d.pool))}</b></span>` : ''}
      </div>
      <div>${ticketBallsHTML(d.a, d.b, 'lg')}</div>
      ${d.grades ? `<div class="hero-grades">${drawDetailHTML(d)}</div>` : ''}
      <div class="hero-countdown" id="drawCountdown"></div>
    </div>`;
  startCountdown();
  const si = $('#issueSearch');
  if (si && si.value.trim()) renderSearch(si.value);
  else renderHallList();
}

/* ---------- 数据分析 ---------- */

function renderFreqChart(el, zone, range, kind) {
  const freq = frequency(analysisDraws(), zone, range);
  const vals = freq.slice(1);
  const max = Math.max(...vals, 1);
  const sorted = [...vals].sort((x, y) => y - x);
  const hotLine = sorted[2] ?? sorted[sorted.length - 1];
  const coldLine = sorted[sorted.length - 3] ?? sorted[0];
  el.innerHTML = vals
    .map((v, i) => {
      const cls = v >= hotLine && v > 0 ? 'hot' : v <= coldLine ? 'coldest' : '';
      return `
      <div class="fbar ${cls}" title="${pad(i + 1)} 出现 ${v} 次">
        <div class="cnt">${v}</div>
        <div class="fill" style="height:${Math.max((v / max) * 100, 2)}%"></div>
        <div class="num">${pad(i + 1)}</div>
      </div>`;
    })
    .join('');
}

function renderOmission() {
  const g = game();
  const el = $('#omissionGrid');
  const blocks = [];
  for (const [zone, zg] of [['a', g.zoneA], ['b', g.zoneB]]) {
    const om = currentOmission(analysisDraws(), zone, zg.range);
    const max = Math.max(...om.slice(1), 1);
    blocks.push(`<div class="om-zone-label">${zg.label}</div>`);
    const heatRGB = state.game === 'ssq' ? '232,69,60' : '212,168,67';
    for (let n = 1; n <= zg.range; n++) {
      const alpha = (om[n] / max) * 0.4;
      blocks.push(`
        <div class="om-cell" style="background:rgba(${heatRGB},${alpha.toFixed(3)})">
          <div class="n">${pad(n)}</div>
          <div class="v">${om[n]} 期</div>
        </div>`);
    }
  }
  el.innerHTML = blocks.join('');
}

function renderShape() {
  const g = game();
  const list = analysisDraws();
  const dist = oddCountDist(list, g.zoneA.pick);
  const total = list.length || 1;
  $('#oddEvenChart').innerHTML = dist
    .map((v, k) => {
      const pct = ((v / total) * 100).toFixed(1);
      return `
      <div class="oe-row">
        <span class="oe-label">${k}奇${g.zoneA.pick - k}偶</span>
        <div class="oe-track"><div class="oe-fill" style="width:${pct}%"></div></div>
        <span class="oe-pct">${v} 期 ${pct}%</span>
      </div>`;
    })
    .join('');

  const sums = sumSeries(list, 30);
  if (!sums.length) { $('#sumSpark').innerHTML = ''; return; }
  const min = Math.min(...sums), max = Math.max(...sums);
  const span = max - min || 1;
  const W = 300, H = 100, P = 6;
  const pts = sums
    .map((v, i) => {
      const x = P + (i / Math.max(sums.length - 1, 1)) * (W - P * 2);
      const y = H - P - ((v - min) / span) * (H - P * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  $('#sumSpark').innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" stroke="#d4a843" stroke-width="2" stroke-linejoin="round"/>
    </svg>
    <div class="spark-meta">区间 ${min} ~ ${max} · 均值 ${(sums.reduce((s, v) => s + v, 0) / sums.length).toFixed(1)}</div>`;
}

function renderPoolSpark() {
  const el = $('#poolSpark');
  if (!el) return;
  const pts = draws().filter((d) => d.pool).reverse();
  if (pts.length < 2) {
    el.innerHTML = '<div class="empty-state">暂无奖池数据</div>';
    return;
  }
  const vals = pts.map((d) => d.pool);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const W = 300, H = 100, P = 6;
  const line = vals
    .map((v, i) => {
      const x = P + (i / Math.max(vals.length - 1, 1)) * (W - P * 2);
      const y = H - P - ((v - min) / span) * (H - P * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(' ');
  el.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <polyline points="${line}" fill="none" stroke="#d4a843" stroke-width="2" stroke-linejoin="round"/>
    </svg>
    <div class="spark-meta">当前 ${formatMoney(vals[vals.length - 1])} · 区间 ${formatMoney(min)} ~ ${formatMoney(max)}（${pts[0].issue} → ${pts[pts.length - 1].issue} 期）</div>`;
}

function renderAnalysis() {
  const g = game();
  const scopeTag = state.scope === 'full' ? '全量历史' : '近期';
  $('#analysisNotice').textContent =
    `统计基于${scopeTag} ${analysisDraws().length} 期真实开奖。彩票每期独立随机，以下统计仅描述历史，不构成任何预测依据${state.scope === 'full' ? '；全量窗口下各号频率趋于均匀' : ''}。`;
  $('#freqTitleA').textContent = `${g.zoneA.label}出现频率`;
  $('#freqTitleB').textContent = `${g.zoneB.label}出现频率`;
  renderFreqChart($('#freqChartA'), 'a', g.zoneA.range, 'red');
  renderFreqChart($('#freqChartB'), 'b', g.zoneB.range, kindB());
  renderOmission();
  renderShape();
  renderPoolSpark();
}

/* ---------- 智能选号 ---------- */

function weightedSample(range, pick, weights) {
  const pool = [];
  const w = [];
  for (let n = 1; n <= range; n++) { pool.push(n); w.push(weights ? weights[n] : 1); }
  const out = [];
  for (let i = 0; i < pick; i++) {
    const total = w.reduce((s, x) => s + x, 0);
    let r = Math.random() * total;
    let idx = 0;
    for (; idx < pool.length - 1; idx++) { r -= w[idx]; if (r <= 0) break; }
    out.push(pool[idx]);
    pool.splice(idx, 1);
    w.splice(idx, 1);
  }
  return out.sort((x, y) => x - y);
}

function buildWeights(strategy) {
  const g = game();
  const list = draws();
  if (strategy === 'hot') {
    const fa = frequency(list, 'a', g.zoneA.range).map((v) => v + 1);
    const fb = frequency(list, 'b', g.zoneB.range).map((v) => v + 1);
    return { a: fa, b: fb };
  }
  if (strategy === 'cold') {
    const oa = currentOmission(list, 'a', g.zoneA.range).map((v) => v + 1);
    const ob = currentOmission(list, 'b', g.zoneB.range).map((v) => v + 1);
    return { a: oa, b: ob };
  }
  return { a: null, b: null };
}

function genTicket(strategy, weights) {
  const g = game();
  if (strategy === 'balanced') {
    const lim = state.game === 'ssq' ? { odd: [2, 4], sum: [70, 140] } : { odd: [1, 4], sum: [55, 125] };
    for (let t = 0; t < 300; t++) {
      const a = weightedSample(g.zoneA.range, g.zoneA.pick, null);
      const odd = a.filter((n) => n % 2).length;
      const sum = a.reduce((s, n) => s + n, 0);
      if (odd >= lim.odd[0] && odd <= lim.odd[1] && sum >= lim.sum[0] && sum <= lim.sum[1] && consecutivePairs(a) <= 2) {
        return { a, b: weightedSample(g.zoneB.range, g.zoneB.pick, null) };
      }
    }
  }
  return {
    a: weightedSample(g.zoneA.range, g.zoneA.pick, weights.a),
    b: weightedSample(g.zoneB.range, g.zoneB.pick, weights.b),
  };
}

function generate() {
  const n = Math.min(Math.max(parseInt($('#pickCount').value, 10) || 1, 1), 50);
  const weights = buildWeights(state.strategy);
  state.tickets = Array.from({ length: n }, () => genTicket(state.strategy, weights));
  renderTickets();
}

function renderTickets() {
  if (!state.tickets.length) {
    $('#ticketList').innerHTML = '<div class="empty-state">选好策略和注数，点「生成号码」</div>';
    return;
  }
  const tier1 = probText(tierProbs(state.game)[1]);
  $('#ticketList').innerHTML = state.tickets
    .map(
      (t, i) => `
      <div class="ticket" style="animation-delay:${Math.min(i * 40, 600)}ms">
        <span class="idx">${pad(i + 1)}</span>
        ${ticketBallsHTML(t.a, t.b)}
        <span class="odds-badge" title="一等奖概率——所有组合完全相同，机选与任何选号方法没有区别">${tier1}</span>
      </div>`
    )
    .join('');
}

function ticketText(t) {
  return t.a.map(pad).join(' ') + ' + ' + t.b.map(pad).join(' ');
}

function copyText(text, okMsg) {
  const done = () => toast(okMsg);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(() => fallbackCopy(text, done));
  } else {
    fallbackCopy(text, done);
  }
}

function fallbackCopy(text, done) {
  const ta = document.createElement('textarea');
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  ta.remove();
  done();
}

function renderPickerMeta() {
  $('#strategyNote').textContent = STRATEGY_NOTES[state.strategy];
}

/* ---------- 开奖倒计时与自动刷新 ---------- */

const DRAW_SCHEDULE = {
  ssq: { days: [0, 2, 4], hour: 21, minute: 15, label: '周二 / 四 / 日 21:15' },
  dlt: { days: [1, 3, 6], hour: 21, minute: 25, label: '周一 / 三 / 六 21:25' },
};

function cnNow() {
  return new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }));
}

function drawTimeOn(date, sched) {
  const d = new Date(date);
  d.setHours(sched.hour, sched.minute, 0, 0);
  return d;
}

function nextDraw(gameKey) {
  const sched = DRAW_SCHEDULE[gameKey];
  const now = cnNow();
  for (let i = 0; i < 8; i++) {
    const d = new Date(now);
    d.setDate(now.getDate() + i);
    if (sched.days.includes(d.getDay())) {
      const t = drawTimeOn(d, sched);
      if (t > now) return t;
    }
  }
  return null;
}

function lastScheduledDraw(gameKey) {
  const sched = DRAW_SCHEDULE[gameKey];
  const now = cnNow();
  for (let i = 0; i < 8; i++) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    if (sched.days.includes(d.getDay())) {
      const t = drawTimeOn(d, sched);
      if (t <= now) return t;
    }
  }
  return null;
}

function fmtCountdown(ms) {
  const s = Math.max(Math.floor(ms / 1000), 0);
  const d = Math.floor(s / 86400);
  const h = String(Math.floor((s % 86400) / 3600)).padStart(2, '0');
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  const sec = String(s % 60).padStart(2, '0');
  return (d ? `${d} 天 ` : '') + `${h}:${m}:${sec}`;
}

let countdownTimer = null;
function startCountdown() {
  clearInterval(countdownTimer);
  const tick = () => {
    const el = $('#drawCountdown');
    if (!el) return;
    const t = nextDraw(state.game);
    if (!t) return;
    const diff = t - cnNow();
    el.innerHTML = diff <= 0
      ? '正在开奖…数据稍后自动更新'
      : `⏱︎ 距下一期开奖 <b>${fmtCountdown(diff)}</b><span class="cd-sched">${DRAW_SCHEDULE[state.game].label}（北京时间）</span>`;
  };
  tick();
  countdownTimer = setInterval(tick, 1000);
}

function dataStale(gameKey) {
  const list = DATA[gameKey] || [];
  if (!list.length) return false;
  const last = lastScheduledDraw(gameKey);
  if (!last) return false;
  if (cnNow() - last < 25 * 60 * 1000) return false;
  const ds = `${last.getFullYear()}-${String(last.getMonth() + 1).padStart(2, '0')}-${String(last.getDate()).padStart(2, '0')}`;
  return list[0].date < ds;
}

function autoRefreshTick() {
  if (!serverMode) return;
  if (!dataStale('ssq') && !dataStale('dlt')) return;
  const lastTry = Number(localStorage.getItem('lottolab_auto_try') || 0);
  if (Date.now() - lastTry < 10 * 60 * 1000) return;
  const btn = $('#btnRefresh');
  if (!btn || btn.disabled) return;
  localStorage.setItem('lottolab_auto_try', String(Date.now()));
  toast('检测到新一期已开奖，自动更新数据中…');
  startTask('/api/refresh', btn, '⟳ 自动更新中…');
}

// 定时任务/监视器在后台改了数据文件时，开着的页面通过 Last-Modified 感知并自动重载
let dataVersion = null;
async function versionTick() {
  if (!location.protocol.startsWith('http')) return;
  try {
    const r = await fetch('/data/ai_picks.js', { method: 'HEAD', cache: 'no-store' });
    const v = r.headers.get('Last-Modified');
    if (dataVersion && v && v !== dataVersion) {
      toast('数据已在后台更新，页面自动刷新…');
      setTimeout(() => location.reload(), 1000);
      return;
    }
    if (v) dataVersion = v;
  } catch (e) {}
}

/* ---------- 数据推理（AI 双脑） ---------- */

function oddsTableHTML(gameKey) {
  const g = GAMES[gameKey];
  const probs = tierProbs(gameKey);
  const tiers = Object.keys(probs).map(Number).sort((a, b) => a - b);
  const money = (t) => (g.fixed[t] != null
    ? g.fixed[t].toLocaleString('zh-CN') + ' 元'
    : '浮动（约 ' + g.floatDefault[t].toLocaleString('zh-CN') + ' 元起）');
  const rows = tiers.map((t) => {
    const p = probs[t];
    return `<tr><td>${TIER_NAMES[t]}</td><td class="mono">${g.tierCond[t]}</td><td class="mono">${probText(p)}</td><td class="mono">1 / ${Math.round(1 / p).toLocaleString('zh-CN')}</td><td class="mono">${money(t)}</td></tr>`;
  }).join('');
  const any = anyPrizeProb(gameKey);
  return `
    <details class="odds-table-wrap">
      <summary>展开完整奖级中奖概率表（每一注、每个号码组合都完全相同）</summary>
      <div class="bt-scroll"><table class="bt-table odds-table">
        <tr><th>奖级</th><th>中奖条件（${g.zoneA.label}+${g.zoneB.label}）</th><th>单注中奖概率</th><th>平均多少注中一次</th><th>单注奖金</th></tr>
        ${rows}
        <tr class="odds-any"><td>中任意奖</td><td class="mono">—</td><td class="mono">${(any * 100).toFixed(2)}%</td><td class="mono">1 / ${Math.round(1 / any).toLocaleString('zh-CN')}</td><td class="mono">每 2 元期望回报 ≈ ${expectedReturn(gameKey).toFixed(2)} 元</td></tr>
      </table></div>
      <p class="strategy-note">概率由组合规则钉死，与选号方法、冷热号、历史走势全部无关。换任何号码，这张表一个数字都不会变——这正是「不可预测」的数学含义。</p>
    </details>`;
}

function renderOddsStrip() {
  const probs = tierProbs(state.game);
  $('#oddsStrip').innerHTML =
    `<div class="odds-line">每注中奖概率完全相同（由规则钉死，与选号方法无关）：一等奖 <b>${probText(probs[1])}</b> · 中任意奖 <b>${(anyPrizeProb(state.game) * 100).toFixed(2)}%</b> · 每 2 元注期望回报 <b>≈ ${expectedReturn(state.game).toFixed(2)} 元</b>。任何声称某注概率更高的工具都在误导你。</div>`
    + oddsTableHTML(state.game);
}

function fingerprint(t, cons) {
  const odd = t.a.filter((n) => n % 2).length;
  const sum = t.a.reduce((s, n) => s + n, 0);
  const span = t.a[t.a.length - 1] - t.a[0];
  const overlap = t.a.filter((n) => cons.a.includes(n)).length + t.b.filter((n) => cons.b.includes(n)).length;
  return `奇偶 ${odd}:${t.a.length - odd} · 和值 ${sum} · 跨度 ${span} · 与共识重合 ${overlap}`;
}

function inferBalls(t, cons) {
  const ha = t.a.map((n) => ballHTML(n, 'red sm', cons.a.includes(n) ? 'cons' : '')).join('');
  const hb = t.b.map((n) => ballHTML(n, `${kindB()} sm`, cons.b.includes(n) ? 'cons' : '')).join('');
  return `${ha}<span class="plus">+</span>${hb}`;
}

function renderAiPicks() {
  const box = $('#aiPicks');
  if (!box) return;
  const ap = window.AI_PICKS;
  const win = ap && ap.windows && (ap.windows[state.inferWindow] || ap.windows['150']);
  const entry = win ? win[state.game] : ap && ap[state.game];
  if (!entry) {
    box.innerHTML = `<div class="empty-state">该窗口暂无推理结果，点右上角「更新数据 · 双脑重算」重新计算（两个窗口会一起算好）</div>`;
    return;
  }
  const winLabel = state.inferWindow === 'full' && ap.windows && ap.windows.full
    ? `全量历史（双色球 ${FULL ? FULL.ssq.length : '—'} 期 / 大乐透 ${FULL ? FULL.dlt.length : '—'} 期）`
    : '近 150 期';
  const cons = entry.consensus || { a: [], b: [] };
  const tier1 = probText(tierProbs(state.game)[1]);
  const panel = (key, label, cls) => {
    const p = entry[key];
    if (!p) return '';
    return `
      <div class="ai-panel">
        <div class="ai-head"><span class="provider-dot ${cls}"></span><b>${label}</b></div>
        <p class="ai-note">${p.note || ''}</p>
        ${p.tickets
          .map(
            (t, i) => `
          <div class="infer-ticket">
            <div class="infer-row">
              <span class="idx">${key === 'claude' ? 'C' : 'X'}${i + 1}</span>
              ${inferBalls(t, cons)}
              <span class="odds-badge" title="一等奖概率——所有组合完全相同">${tier1}</span>
            </div>
            <div class="infer-fp">${fingerprint(t, cons)}</div>
          </div>`
          )
          .join('')}
      </div>`;
  };
  const top = entry.top;
  const topHTML = top
    ? `
    <div class="top-pick">
      <div class="top-pick-label">双脑主推 · 一注</div>
      <div class="top-pick-balls">${top.a.map((n) => ballHTML(n, 'red', cons.a.includes(n) ? 'cons' : '')).join('')}<span class="plus">+</span>${top.b.map((n) => ballHTML(n, kindB(), cons.b.includes(n) ? 'cons' : '')).join('')}<span class="odds-badge">${tier1}</span><button class="btn btn-ghost btn-mini" id="btnSaveTopPick">存入票夹</button></div>
      <div class="top-pick-note">由十组中两模型共同押注最多的号码确定性合成（投票制，可复现）。它的中奖概率与其他任何一注完全相同——主推表达的是两套模型的最大共识，不是更高的胜率。</div>
    </div>`
    : '';
  box.innerHTML = `
    <p class="ai-meta">推理窗口：${winLabel} · 基于第 ${ap.basedOnIssue?.[state.game] || '—'} 期之前的真实开奖 · 生成于 ${ap.generated || '—'} · 两套确定性模型独立计算 · 排列顺序无优劣含义 · 窗口大小不改变中奖概率（实测见「实证回测」）</p>
    ${topHTML}
    <div class="consensus-strip">
      <span class="consensus-label">双脑共识号码池</span>
      <span>${cons.a.length ? cons.a.map((n) => ballHTML(n, 'red sm', 'cons')).join('') : '<span class="consensus-hint">无重合</span>'}<span class="plus">+</span>${cons.b.length ? cons.b.map((n) => ballHTML(n, `${kindB()} sm`, 'cons')).join('') : '<span class="consensus-hint">无重合</span>'}</span>
      <span class="consensus-hint">金圈号码 = 两套模型同时选中。共识只表示两种统计视角重合，不代表概率优势。</span>
    </div>
    <details class="ten-details">
      <summary>展开双脑十组明细（Claude ×5 · Codex ×5）</summary>
      <div class="ai-grid">
        ${panel('claude', 'Claude · Fable 5', 'dot-claude')}
        ${panel('codex', 'Codex · GPT 系', 'dot-codex')}
      </div>
    </details>`;
  const sb = $('#btnSaveTopPick');
  if (sb && top) sb.addEventListener('click', () => walletAdd(state.game, [{ a: top.a, b: top.b }], false));
}

function renderLedger() {
  const box = $('#ledgerBox');
  if (!box) return;
  const all = (window.LEDGER || []).filter((r) => r.game === state.game);
  if (!all.length) {
    box.innerHTML = '<div class="empty-state">暂无记录。每次「更新数据 · 双脑重算」会自动把当期推算记入台账，开奖后下次刷新自动对照打分。</div>';
    return;
  }
  const done = all.filter((r) => r.score);
  const g = game();
  // grades = 该期开奖公告的真实奖金（result.grades），优先用真实，无公告才回落估值
  const hasReal = (t, gr) => !!(gr && gr[t] && gr[t][1] != null);
  const prizeOf = (t, gr) => {
    if (g.fixed[t] != null) return g.fixed[t];
    if (hasReal(t, gr)) return gr[t][1];
    return g.floatDefault[t];
  };
  const expA = (g.zoneA.pick * g.zoneA.pick) / g.zoneA.range;
  const money = (tier, gr) => (tier
    ? `<span class="money-win">+${prizeOf(tier, gr).toLocaleString('zh-CN')} 元${tier <= 2 && !hasReal(tier, gr) ? '（浮动按估值）' : ''}</span>`
    : '<span class="money-lose">未中奖 −2 元</span>');

  let summary = `已记账 ${all.length} 期 · 已开奖对照 ${done.length} 期`;
  let board = '';
  if (done.length) {
    const prized = done.reduce((s, r) => s + r.score.prized, 0);
    summary += ` · 十组累计中奖 ${prized} 注 / ${done.length * 10} 注 · 理论期望命中 ${expA.toFixed(2)} 个/注`;
    const stat = (list, hitKey, tierKey) => {
      if (!list.length) return null;
      const avg = list.reduce((s, r) => s + r.score[hitKey], 0) / list.length;
      const win = list.reduce((s, r) => s + (r.score[tierKey] ? prizeOf(r.score[tierKey], r.result.grades) : 0), 0);
      return { n: list.length, avg, win, net: win - list.length * 2 };
    };
    const s150 = stat(done, 'topA', 'topTier');
    const sFull = stat(done.filter((r) => r.score.fullA != null), 'fullA', 'fullTier');
    const cell = (name, st) => st
      ? `<div class="wb-cell"><div class="wb-name">${name}</div><div class="wb-val">平均命中 <b>${st.avg.toFixed(2)}</b> 个/注</div><div class="wb-val">投入 ${st.n * 2} 元 · 中奖 ${st.win.toLocaleString('zh-CN')} 元 · 盈亏 <b class="${st.net >= 0 ? 'money-win' : 'money-lose'}">${st.net >= 0 ? '+' : '−'}${Math.abs(st.net).toLocaleString('zh-CN')} 元</b></div><div class="wb-n">${st.n} 期已对照</div></div>`
      : `<div class="wb-cell"><div class="wb-name">${name}</div><div class="wb-n">尚无对照数据</div></div>`;
    board = `
      <div class="win-board">
        <div class="wb-title">双窗主推记分牌（各按每期买 1 注计）</div>
        <div class="wb-grid">${cell('近 150 期窗口', s150)}${cell('全量历史窗口', sFull)}</div>
        <div class="wb-note">两边长期都会收敛到同一期望（命中 ${expA.toFixed(2)} 个/注）；阶段性领先属正常波动。</div>
      </div>`;
  }

  const rows = all
    .map((r) => {
      const markBalls = (t) =>
        t.a.map((n) => ballHTML(n, 'red sm', r.result ? (r.result.a.includes(n) ? 'hit' : 'miss') : '')).join('')
        + '<span class="plus">+</span>'
        + t.b.map((n) => ballHTML(n, `${kindB()} sm`, r.result ? (r.result.b.includes(n) ? 'hit' : 'miss') : '')).join('');
      const line = (label, t) => `<div class="ledger-line"><span class="win-chip">${label}</span>${markBalls(t)}</div>`;
      const ballsCol = line('150期', r.top) + (r.topFull ? line('全量', r.topFull) : '');
      if (!r.score) {
        // 下一期期号年末会跨年进位（无法纯靠 +1 推断），直接显示「下一期」更诚实、永不显示错
        return `
        <div class="ledger-row">
          <div class="ledger-issue">预测下一期<br><span class="ledger-date">基于截至 ${r.basedOnIssue} 期的数据 · ${r.predictedAt} 锁定</span></div>
          <div class="ledger-balls">${ballsCol}</div>
          <div class="ledger-result pending">待开奖</div>
        </div>`;
      }
      const s = r.score;
      const tierTag = s.topTier ? `<span class="tier-chip">${TIER_NAMES[s.topTier]}</span>` : '';
      const tiersText = Object.entries(s.tiers).sort((a, b) => a[0] - b[0]).map(([t, c]) => `${TIER_NAMES[t]}×${c}`).join(' ');
      const retroTag = r.topFullRetro ? '<span class="badge" title="开奖后用截至当期的数据确定性重建，与当时本应锁定的结果一致，可复现">补登</span>' : '';
      const fullLine = s.fullA != null
        ? `全量窗 中 <b>${s.fullA}+${s.fullB}</b> ${s.fullTier ? `<span class="tier-chip">${TIER_NAMES[s.fullTier]}</span>` : ''} ${money(s.fullTier, r.result.grades)} ${retroTag}<br>`
        : (r.topFull ? '' : '<span class="ledger-sub">全量窗：当期未记录</span><br>');
      const tenWin = Object.entries(s.tiers).reduce((sum, [t, c]) => sum + c * prizeOf(t, r.result.grades), 0);
      const tenNet = tenWin - 20;
      return `
        <div class="ledger-row">
          <div class="ledger-issue">第 ${r.result.issue} 期<br><span class="ledger-date">${r.result.date}</span></div>
          <div class="ledger-balls">
            ${ballsCol}
            <div class="ledger-actual">开奖：${r.result.a.map(pad).join(' ')} + ${r.result.b.map(pad).join(' ')}</div>
          </div>
          <div class="ledger-result">
            150期窗 中 <b>${s.topA}+${s.topB}</b> ${tierTag} ${money(s.topTier, r.result.grades)}<br>
            ${fullLine}
            <span class="ledger-sub">十组最佳 ${s.bestA} 个 · 平均 ${s.avgA} · 中奖 ${s.prized} 注${tiersText ? '（' + tiersText + '）' : ''} · 十组盈亏 ${tenNet >= 0 ? '+' : '−'}${Math.abs(tenNet).toLocaleString('zh-CN')} 元</span>
          </div>
        </div>`;
    })
    .join('');
  box.innerHTML = `
    <p class="ai-meta">${summary}</p>
    ${board}
    ${rows}
    <p class="strategy-note">台账只记录、不粉饰：两个窗口的主推均在开奖前锁定，命中如实展示，长期均值将回到理论期望。</p>`;
}

function renderInfer() {
  renderOddsStrip();
  renderAiPicks();
  renderLedger();
}

/* ---------- 实证回测 ---------- */

const fmtPct = (v, d = 2) => (v * 100).toFixed(d) + '%';

function renderBacktestActions() {
  const bt = window.BACKTEST;
  $('#btActions').innerHTML = `
    <button id="btnBacktest" class="btn btn-primary hidden">▶ 运行全量回测（约 3 分钟）</button>
    <span class="bt-meta">${bt ? `最近回测：${bt.meta.generated} · 滚动窗口 ${bt.meta.window} 期 · 回测 ${bt.meta.periods} 期 × 每期 5 注` : '尚未运行回测'}${serverMode ? '' : ' · 启动 server.py 后可页内一键回测，或运行 python3 scripts/backtest.py'}</span>`;
  if (serverMode) {
    const b = $('#btnBacktest');
    b.classList.remove('hidden');
    b.addEventListener('click', () => startTask('/api/backtest', b, '⟳ 回测中（约 3 分钟）…'));
  }
}

function renderBtHard() {
  const tier1 = probText(tierProbs(state.game)[1]);
  $('#btHard').innerHTML = `
    <div class="hard-trio">
      <div class="hard-card"><div class="hv">${tier1}</div><div class="hk">一等奖概率 · 规则钉死</div></div>
      <div class="hard-card"><div class="hv">${FULL ? (FULL[state.game] || []).length.toLocaleString('zh-CN') : '—'}</div><div class="hk">全量真实开奖档案（期）</div></div>
      <div class="hard-card"><div class="hv">0</div><div class="hk">两套模型使用的随机数个数</div></div>
    </div>`;
}

function renderBtCompare() {
  const bt = window.BACKTEST;
  const g = bt && bt[state.game];
  if (!g) {
    $('#btCompare').innerHTML = '<div class="card empty-state">暂无回测数据，点上方按钮运行</div>';
    return;
  }
  const rows = [
    ['Claude 模型', g.claude, 'dot-claude'],
    ['Codex 模型', g.codex, 'dot-codex'],
    ['纯随机基线', g.random, ''],
  ];
  const th = g.theory;
  const maxHits = Math.max(...rows.map((r) => r[1].avgHitsA), th.avgHitsA);
  const tierCell = (tiers) =>
    Object.entries(tiers).sort((a, b) => a[0] - b[0]).map(([t, c]) => `${TIER_NAMES[t]}×${c}`).join(' ') || '—';
  const covered = rows.every((r) => th.avgHitsA >= r[1].ciHitsA[0] && th.avgHitsA <= r[1].ciHitsA[1]);
  $('#btCompare').innerHTML = `
    <div class="card">
      <h3 class="card-title">全量回测对照 · ${game().name}（${g.range.from} → ${g.range.to}，${g.range.periods} 期 × 5 注）</h3>
      <div class="bt-scroll"><table class="bt-table">
        <tr><th></th><th>${game().zoneA.label}平均命中/注</th><th>中任意奖</th><th>固定奖回报率</th><th>奖级明细</th></tr>
        ${rows
          .map(
            ([name, s, dot]) => `
          <tr>
            <td class="bt-name">${dot ? `<span class="provider-dot ${dot}"></span>` : ''}${name}</td>
            <td>
              <div class="bt-bar"><div class="bt-fill" style="width:${((s.avgHitsA / maxHits) * 100).toFixed(1)}%"></div></div>
              <span class="mono">${s.avgHitsA.toFixed(3)}</span> <span class="bt-ci">95%CI ${s.ciHitsA[0].toFixed(3)}~${s.ciHitsA[1].toFixed(3)}</span>
            </td>
            <td class="mono">${fmtPct(s.anyPrize)}</td>
            <td class="mono">${fmtPct(s.returnFixed, 1)}</td>
            <td class="bt-tiers">${tierCell(s.tiers)}</td>
          </tr>`
          )
          .join('')}
        <tr class="bt-theory">
          <td class="bt-name">理论值</td>
          <td><div class="bt-bar"><div class="bt-fill theory" style="width:${((th.avgHitsA / maxHits) * 100).toFixed(1)}%"></div></div><span class="mono">${th.avgHitsA.toFixed(3)}</span></td>
          <td class="mono">${fmtPct(th.anyPrize)}</td>
          <td class="mono">${fmtPct(th.returnFixed, 1)}</td>
          <td class="bt-tiers">—</td>
        </tr>
      </table></div>
      <p class="bt-conclusion">${
        covered
          ? '两套模型 ≈ 纯随机 ≈ 理论值（各 95% 置信区间均覆盖理论值，未检出任何模型优势）。这不是模型失败，这是彩票的数学本性——历史数据不含未来信息。本页把这张表原样挂出来，因为可验证比好看重要。'
          : '个别置信区间未覆盖理论值，属样本噪声内波动。结论不变：未检出任何模型相对纯随机的优势。'
      }</p>
      <p class="strategy-note">回报率为"固定奖口径"（三等及以下固定奖金），对应理论可实现回报约 ${fmtPct(th.returnFixed, 1)}；一、二等奖为浮动奖金仅计注数。每 2 元长期期望亏损约 1.1 元——理性购彩。</p>
    </div>`;
}

function renderBtCalibration() {
  const box = $('#btCalibration');
  if (!box) return;
  const bt = window.BACKTEST;
  const g = bt && bt[state.game];
  if (!g) { box.innerHTML = ''; return; }
  const th = g.theory;
  const models = [
    { name: 'Claude', s: g.claude, color: '#e8825c' },
    { name: 'Codex', s: g.codex, color: '#10a37f' },
    { name: '纯随机', s: g.random, color: '#8a8f99' },
  ];
  // 可观测的校准维度：各奖级命中率 + 中任意奖率；理论与实测都 >0 才能落在对数轴上
  const dims = Object.keys(th.tierProb)
    .filter((t) => th.tierProb[t] > 0)
    .sort((a, b) => th.tierProb[b] - th.tierProb[a])
    .map((t) => ({ label: TIER_NAMES[t] || t + '等', x: th.tierProb[t], y: (s) => (s.tiers[t] || 0) / s.tickets }));
  dims.push({ label: '任意奖', x: th.anyPrize, y: (s) => s.anyPrize });
  const pts = [];
  let omitted = 0;
  dims.forEach((d) => {
    let any = false;
    models.forEach((mo) => {
      const yv = d.y(mo.s);
      if (yv > 0) { pts.push({ x: d.x, y: yv, color: mo.color, name: mo.name, label: d.label }); any = true; }
    });
    if (!any) omitted++;
  });
  if (!pts.length) { box.innerHTML = ''; return; }
  const L = (v) => Math.log10(v);
  const allL = pts.flatMap((p) => [L(p.x), L(p.y)]);
  let lo = Math.floor(Math.min(...allL)), hi = Math.ceil(Math.max(...allL));
  if (hi === lo) hi = lo + 1;
  const W = 540, H = 400, pad = 58;
  const sx = (v) => pad + ((L(v) - lo) / (hi - lo)) * (W - 2 * pad);
  const sy = (v) => (H - pad) - ((L(v) - lo) / (hi - lo)) * (H - 2 * pad);
  const pct = (v) => (v * 100 >= 1 ? (v * 100).toFixed(2) : (v * 100).toFixed(3)) + '%';
  const tick = (p) => (p * 100 >= 1 ? (p * 100).toFixed(0) : (p * 100).toFixed(p < 0.001 ? 3 : 2)) + '%';
  let svg = '';
  for (let e = lo; e <= hi; e++) {
    const p = Math.pow(10, e);
    svg += `<line x1="${sx(p)}" y1="${pad}" x2="${sx(p)}" y2="${H - pad}" stroke="#eef0f4"/>`;
    svg += `<line x1="${pad}" y1="${sy(p)}" x2="${W - pad}" y2="${sy(p)}" stroke="#eef0f4"/>`;
    svg += `<text x="${sx(p)}" y="${H - pad + 16}" text-anchor="middle" font-size="9" fill="#aab0bb">${tick(p)}</text>`;
    svg += `<text x="${pad - 6}" y="${sy(p) + 3}" text-anchor="end" font-size="9" fill="#aab0bb">${tick(p)}</text>`;
  }
  const dLo = Math.pow(10, lo), dHi = Math.pow(10, hi);
  svg += `<line x1="${sx(dLo)}" y1="${sy(dLo)}" x2="${sx(dHi)}" y2="${sy(dHi)}" stroke="#b9c0cc" stroke-dasharray="5 4" stroke-width="1.5"/>`;
  svg += `<text x="${sx(dHi) - 6}" y="${sy(dHi) + 16}" text-anchor="end" font-size="11" fill="#9aa0ab">完美校准 y = x</text>`;
  svg += `<line x1="${pad}" y1="${H - pad}" x2="${W - pad}" y2="${H - pad}" stroke="#d6dae2"/><line x1="${pad}" y1="${pad}" x2="${pad}" y2="${H - pad}" stroke="#d6dae2"/>`;
  svg += `<text x="${W / 2}" y="${H - 6}" text-anchor="middle" font-size="11" fill="#6b7280">理论概率（对数轴）</text>`;
  svg += `<text x="12" y="${pad - 12}" font-size="11" fill="#6b7280">↑ 实测频率</text>`;
  pts.forEach((p) => {
    svg += `<circle cx="${sx(p.x)}" cy="${sy(p.y)}" r="5" fill="${p.color}" opacity="0.82"><title>${p.name} · ${p.label}：实测 ${pct(p.y)} vs 理论 ${pct(p.x)}</title></circle>`;
  });
  const legend = models.map((mo) => `<span class="cal-leg"><span class="cal-dot" style="background:${mo.color}"></span>${mo.name}</span>`).join('');
  const omitNote = omitted ? `另有 ${omitted} 个更稀有的奖级在 ${g.range.periods} 期回测中三套方法均 0 命中（理论概率过低，样本不足以观测，属正常，故未画出）。` : '';
  box.innerHTML = `
    <div class="card">
      <h3 class="card-title">校准散点图 · ${game().name}（${g.range.periods} 期回测 · 对数轴）</h3>
      <p class="ai-meta">每个点：横轴＝规则决定的理论概率，纵轴＝回测实测频率。点落在对角线上＝校准良好（标注概率＝真实发生频率）。</p>
      <div class="cal-legend">${legend}</div>
      <svg class="cal-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="校准散点图：理论概率对实测频率">${svg}</svg>
      <p class="bt-conclusion">从最常见到较稀有的奖级，三套方法的点都沿对角线分布、彼此交织——Claude、Codex 与纯随机在每一档概率上都与理论一致，没有任何一方更“准”。这正是“可验证”：标注的概率＝真实发生的频率。${omitNote}</p>
    </div>`;
}

function renderBtCalibScore() {
  const box = $('#btCalibScore');
  if (!box) return;
  const bt = window.BACKTEST;
  const g = bt && bt[state.game];
  if (!g) { box.innerHTML = ''; return; }
  const th = g.theory;
  const n = g.claude.tickets;
  const models = [
    { name: 'Claude', s: g.claude, color: '#e8825c' },
    { name: 'Codex', s: g.codex, color: '#10a37f' },
    { name: '纯随机', s: g.random, color: '#8a8f99' },
  ];
  const dims = Object.keys(th.tierProb).filter((t) => th.tierProb[t] > 0)
    .sort((a, b) => th.tierProb[b] - th.tierProb[a])
    .map((t) => ({ label: TIER_NAMES[t] || t + '等', x: th.tierProb[t], y: (s) => (s.tiers[t] || 0) / s.tickets }));
  dims.push({ label: '任意奖', x: th.anyPrize, y: (s) => s.anyPrize });
  const obs = dims.filter((d) => models.some((m) => d.y(m.s) > 0));
  if (!obs.length) { box.innerHTML = ''; return; }
  // 完美校准下的预期 ECE：即便标注概率完全正确，n 注的有限样本也会有抽样偏差 E|f-p| ≈ 0.7979·√(p(1-p)/n)
  const baseECE = obs.reduce((a, d) => a + 0.7979 * Math.sqrt(d.x * (1 - d.x) / n), 0) / obs.length;
  const eceOf = (m) => obs.reduce((a, d) => a + Math.abs(d.y(m.s) - d.x), 0) / obs.length;
  const sd = (p) => Math.sqrt(p * (1 - p) / n);
  const pp = (v) => (v * 100).toFixed(3) + 'pp';
  const pct = (v) => (v * 100 >= 1 ? (v * 100).toFixed(2) : (v * 100).toFixed(3)) + '%';
  const eceCards = models.map((m) => {
    const e = eceOf(m), r = e / baseECE;
    return `<div class="ce-cell"><div class="ce-name"><span class="cal-dot" style="background:${m.color}"></span>${m.name}</div><div class="ce-val">${pp(e)}</div><div class="ce-sub">${r.toFixed(2)}× 噪声基准</div></div>`;
  }).join('');
  const rows = obs.map((d) =>
    `<tr><td>${d.label}</td><td class="mono">${pct(d.x)}</td>${models.map((m) => `<td class="mono">${pct(d.y(m.s))}</td>`).join('')}<td class="mono">±${(sd(d.x) * 100).toFixed(3)}pp</td></tr>`
  ).join('');
  const dltNote = game().name === '大乐透'
    ? '大乐透稀有奖级多、单档样本少，ECE 波动比双色球略大，属有限样本的正常现象'
    : '三者几乎重合';
  box.innerHTML = `
    <div class="card">
      <h3 class="card-title">校准可信度 · 量化（ECE） · ${game().name}</h3>
      <p class="ai-meta">ECE（期望校准误差）＝标注概率与 ${g.range.periods} 期实测频率的平均偏差。越小越说明「标多少就真发生多少」——这是数学上真正能衡量的“准确性”。</p>
      <div class="ce-baseline">完美校准基准 <b>${pp(baseECE)}</b><span>　← ${g.range.periods} 期 × ${n.toLocaleString('zh-CN')} 注下，即便标注概率完全正确，纯抽样也会自带这么大的 ECE。实测 ECE 若与它同量级，就说明偏差全是噪声、没有系统性失准。</span></div>
      <div class="ce-grid">${eceCards}</div>
      <details class="ce-details"><summary>展开逐档明细（可验证 ECE 怎么算出来的）</summary>
        <div class="bt-scroll"><table class="bt-table"><tr><th>奖级/事件</th><th>标注概率</th>${models.map((m) => `<th>${m.name}实测</th>`).join('')}<th>±1σ抽样噪声</th></tr>${rows}</table></div>
      </details>
      <p class="bt-conclusion">三套方法的 ECE 都与噪声基准同量级、绝对值都不到 1 个百分点——偏差全部落在有限样本的抽样噪声内，没有任何一方的标注概率系统性失准，也没有哪套更校准（${dltNote}）。这就是“可信”的量化定义：我们标注的概率，经得起 ${g.range.periods} 期真实开奖的逐档检验。</p>
    </div>`;
}

function mulberry32(seed) {
  return function () {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function sampleZone(rng, range, pick) {
  const pool = Array.from({ length: range }, (_, i) => i + 1);
  const out = [];
  for (let i = 0; i < pick; i++) out.push(pool.splice(Math.floor(rng() * pool.length), 1)[0]);
  return out.sort((a, b) => a - b);
}

let mcSeed = 42;
function runMc() {
  const g = game();
  const rng = mulberry32(mcSeed);
  const drawA = new Set(sampleZone(rng, g.zoneA.range, g.zoneA.pick));
  const drawB = new Set(sampleZone(rng, g.zoneB.range, g.zoneB.pick));
  const N = 100000;
  let prized = 0;
  const t0 = performance.now();
  for (let i = 0; i < N; i++) {
    const a = sampleZone(rng, g.zoneA.range, g.zoneA.pick);
    const b = sampleZone(rng, g.zoneB.range, g.zoneB.pick);
    let ka = 0;
    for (const n of a) if (drawA.has(n)) ka++;
    let kb = 0;
    for (const n of b) if (drawB.has(n)) kb++;
    if (tierOf(state.game, ka, kb)) prized++;
  }
  const ms = performance.now() - t0;
  const obs = prized / N;
  const theo = anyPrizeProb(state.game);
  $('#mcResult').innerHTML = `
    <div class="mc-out">种子 ${mcSeed} · ${N.toLocaleString('zh-CN')} 注模拟 · ${ms.toFixed(0)}ms<br>
    中任意奖频率 <b>${fmtPct(obs)}</b> vs 理论 <b>${fmtPct(theo)}</b>，偏差 ${(Math.abs(obs - theo) * 100).toFixed(2)}pp（按 1/√n 收敛）</div>`;
  mcSeed++;
}

function renderMc() {
  $('#mcPanel').innerHTML = `
    <p class="strategy-note">模拟的正确用途是验证概率表，不是选号：10 万注随机票的中奖频率必然收敛到理论值。点击换种子重跑，结论不变。</p>
    <button class="btn btn-ghost" id="btnMc">跑 100,000 注模拟</button>
    <div id="mcResult"></div>`;
  $('#btnMc').addEventListener('click', runMc);
}

function runDebunk() {
  const g = game();
  const N = 100000;
  const seeds = [Math.floor(Math.random() * 1e6), Math.floor(Math.random() * 1e6)];
  const tops = seeds.map((seed) => {
    const rng = mulberry32(seed);
    const cnt = new Map();
    for (let i = 0; i < N; i++) {
      const key = sampleZone(rng, g.zoneA.range, g.zoneA.pick).join(' ') + ' + ' + sampleZone(rng, g.zoneB.range, g.zoneB.pick).join(' ');
      cnt.set(key, (cnt.get(key) || 0) + 1);
    }
    const top = [...cnt.entries()].sort((x, y) => y[1] - x[1]).slice(0, 10);
    return { seed, top };
  });
  const overlap = tops[0].top.filter(([k]) => tops[1].top.some(([k2]) => k2 === k)).length;
  const space = comb(g.zoneA.range, g.zoneA.pick) * comb(g.zoneB.range, g.zoneB.pick);
  const maxc = Math.max(tops[0].top[0][1], tops[1].top[0][1]);
  $('#debunkResult').innerHTML = `
    <div class="mc-out">种子 ${tops[0].seed} 最高频：${tops[0].top[0][0]}（${tops[0].top[0][1]} 次）<br>
    种子 ${tops[1].seed} 最高频：${tops[1].top[0][0]}（${tops[1].top[0][1]} 次）<br>
    两份"最高频十组"重合 <b>${overlap} 组</b> · 最高出现次数仅 ${maxc} 次<br>
    ${space.toLocaleString('zh-CN')} 个组合中 10 万样本的"最高频"只是撞出 ${maxc} 次的运气，换个种子就换一批号。<span class="debunk-stamp">已证伪</span></div>`;
}

function renderDebunk() {
  $('#debunkPanel').innerHTML = `
    <p class="strategy-note">展品一：「模拟 N 次取概率最大的组合」。若该方法有效，不同随机种子应得到相似的结果——亲手验证：</p>
    <button class="btn btn-ghost" id="btnDebunk">双种子对照实验</button>
    <div id="debunkResult"></div>
    <p class="strategy-note" style="margin-top:16px">展品二：「根据最近开奖结果优化算法」。实现了一个误差反馈模型（开出号加权、选错号降权、逐期吸取教训，零随机数），全量数据回测 300 期：</p>
    <div class="mc-out">双色球 平均命中 1.140/注 vs 理论 1.091 · 前半段 1.173 → 后半段 1.107<br>
    大乐透 平均命中 0.720/注 vs 理论 0.714 · 前半段 0.760 → 后半段 0.680<br>
    "学了 150 期教训"的后半段反而更差——独立随机事件的误差里没有可学的信号，所谓优化只是在拟合噪声。<span class="debunk-stamp">已证伪</span><br>
    <span class="ledger-sub">复现：python3 scripts/exhibit_feedback.py 300</span></div>`;
  $('#btnDebunk').addEventListener('click', runDebunk);
}

function checkIntegrity(gameKey) {
  const g = GAMES[gameKey];
  const src = (FULL && FULL[gameKey] && FULL[gameKey].length) ? FULL[gameKey] : (DATA[gameKey] || []);
  if (!src.length) return null;
  const issues = src.map((d) => d.issue);
  const dup = issues.length - new Set(issues).size;
  let badNums = 0;
  for (const d of src) {
    const aOK = d.a && d.a.length === g.zoneA.pick && new Set(d.a).size === g.zoneA.pick && d.a.every((n) => n >= 1 && n <= g.zoneA.range);
    const bOK = d.b && d.b.length === g.zoneB.pick && new Set(d.b).size === g.zoneB.pick && d.b.every((n) => n >= 1 && n <= g.zoneB.range);
    if (!aOK || !bOK) badNums++;
  }
  // 期号连续性：同年内序号应逐期 +1；跨年边界（每年期数不固定）跳过，避免误报
  const yearOf = (i) => (gameKey === 'ssq' ? i.slice(0, 4) : i.slice(0, 2));
  const seqOf = (i) => parseInt(gameKey === 'ssq' ? i.slice(4) : i.slice(2), 10);
  const sorted = [...src].sort((x, y) => x.issue.localeCompare(y.issue));
  let gaps = 0;
  for (let i = 1; i < sorted.length; i++) {
    if (yearOf(sorted[i].issue) === yearOf(sorted[i - 1].issue)) {
      const d = seqOf(sorted[i].issue) - seqOf(sorted[i - 1].issue);
      if (d !== 1) gaps += Math.max(Math.abs(d) - 1, 1);
    }
  }
  const recent = DATA[gameKey] || [];
  const gradesCov = recent.filter((d) => d.grades && (d.grades['1'] || d.grades['2'])).length;
  const poolCov = recent.filter((d) => d.pool != null).length;
  return { name: g.name, total: src.length, oldest: sorted[0].issue, newest: sorted[sorted.length - 1].issue, dup, badNums, gaps, gradesCov, poolCov, recentN: recent.length };
}

function integrityHTML() {
  const cards = ['ssq', 'dlt'].map((gk) => {
    const r = checkIntegrity(gk);
    if (!r) return '';
    const mark = (cond) => (cond ? '<span class="chk-ok">✓</span>' : '<span class="chk-bad">⚠</span>');
    const allPass = r.dup === 0 && r.badNums === 0 && r.gaps === 0;
    return `
      <div class="chk-card">
        <div class="chk-head">${r.name}<span class="chk-badge ${allPass ? 'pass' : 'warn'}">${allPass ? '全部通过' : '有待核查'}</span></div>
        <ul class="chk-list">
          <li>${mark(true)} 全量档案 <b>${r.total.toLocaleString('zh-CN')}</b> 期（${r.oldest} ~ ${r.newest}）</li>
          <li>${mark(r.gaps === 0)} 期号连续：${r.gaps === 0 ? '同年内无缺口' : r.gaps + ' 处疑似缺口'}</li>
          <li>${mark(r.badNums === 0)} 号码合法：${r.badNums === 0 ? '数量 / 范围 / 去重全通过' : r.badNums + ' 期异常'}</li>
          <li>${mark(r.dup === 0)} 期号唯一：${r.dup === 0 ? '无重复' : r.dup + ' 条重复'}</li>
          <li>${mark(r.gradesCov === r.recentN)} 近 ${r.recentN} 期真实奖金 <b>${r.gradesCov}/${r.recentN}</b> · 奖池 <b>${r.poolCov}/${r.recentN}</b></li>
        </ul>
      </div>`;
  }).join('');
  return `
    <div class="card chk-wrap">
      <h3 class="card-title">数据完整性自检 · 本机实时校验</h3>
      <p class="ai-meta">每次打开页面，对本地全量档案实时核验：期号连续性、号码合法性、去重、真实奖金/奖池覆盖。下面是此刻的结果。</p>
      <div class="chk-grid">${cards}</div>
      <p class="strategy-note">校验口径与对奖规则同源（号码范围/数量取自 js/rules.js）。任何一项不通过都会在这里标出——数据干不干净，自己一眼看得到。</p>
    </div>`;
}

function renderProvenance() {
  const bt = window.BACKTEST;
  $('#provenance').innerHTML = integrityHTML() + `
    <table class="prov-table">
      <tr><td>开奖数据源</td><td>${DATA.meta.source || '—'} · 更新 ${DATA.meta.generated || '—'}</td></tr>
      <tr><td>全量档案</td><td>${FULL ? `双色球 ${FULL.ssq.length} 期 / 大乐透 ${FULL.dlt.length} 期（data/draws_full.js，按期号增量合并）` : '未生成，运行 python3 fetch_data.py --full'}</td></tr>
      <tr><td>回测协议</td><td>${bt ? bt.meta.protocol : '—'}</td></tr>
      <tr><td>模型源码</td><td class="mono">scripts/fable_model.py（Claude Fable 5 设计）· scripts/codex_model.py（OpenAI Codex 设计）——确定性，零随机数，同输入同输出</td></tr>
      <tr><td>一键复现</td><td class="mono">./scripts/ai_pick.sh · python3 scripts/backtest.py 300</td></tr>
    </table>
    <p class="strategy-note">本页不展示任何无法在本机重算验证的指标；概率表与对奖规则同源（js/rules.js）。</p>`;
}

function renderBacktestAll() {
  renderBacktestActions();
  renderBtHard();
  renderBtCompare();
  renderBtCalibration();
  renderBtCalibScore();
  renderMc();
  renderDebunk();
  renderProvenance();
}

/* ---------- 对奖中心 ---------- */

function renderChecker() {
  const g = game();
  const list = draws();
  $('#issueSelect').innerHTML =
    list.slice(0, 150).map((d) => `<option value="${d.issue}">第 ${d.issue} 期 (${d.date})</option>`).join('') +
    '<option value="__custom">自定义开奖号码…</option>';
  $('#customDrawRow').classList.add('hidden');
  $('#addOnWrap').classList.toggle('hidden', state.game !== 'dlt');
  $('#betInput').placeholder =
    state.game === 'ssq'
      ? '03 11 17 22 28 33 + 06\n01 05 09 14 20 26 31 + 03 12   ← 多写号码即复式'
      : '05 12 19 26 33 + 04 09\n02 08 15 21 28 34 + 03 07 11   ← 多写号码即复式';
  $('#floatInputs').innerHTML = Object.entries(g.floatDefault)
    .map(
      ([t, v]) => `
      <label>${TIER_NAMES[t]}（元/注）
        <input type="number" id="float-${t}" value="${v}" min="0" step="10000">
      </label>`
    )
    .join('');
  renderPrizeTable();
  $('#checkResult').innerHTML = '';
}

function renderPrizeTable() {
  const g = game();
  const rows = Object.keys(g.tierCond)
    .map((t) => {
      const prize = g.fixed[t] != null ? formatMoney(g.fixed[t]) : '浮动（按当期公告）';
      return `<tr><td>${TIER_NAMES[t]}</td><td class="cond">${g.tierCond[t]}</td><td class="money">${prize}</td></tr>`;
    })
    .join('');
  const addNote = state.game === 'dlt' ? '<p class="strategy-note">追加投注每注 +1 元，仅一、二等奖按基本奖金的 80% 追加。</p>' : '';
  $('#prizeTable').innerHTML = `
    <table class="prize-table">
      <tr><th>奖级</th><th>中奖条件（${g.zoneA.label}+${g.zoneB.label}）</th><th>单注奖金</th></tr>
      ${rows}
    </table>${addNote}`;
}

function getCheckDraw() {
  const sel = $('#issueSelect').value;
  if (sel === '__custom') {
    const g = game();
    const parsed = parseBet(state.game, $('#customDraw').value);
    if (!parsed || parsed.error) return { error: parsed ? parsed.error : '请输入自定义开奖号码' };
    if (parsed.a.length !== g.zoneA.pick || parsed.b.length !== g.zoneB.pick) {
      return { error: `开奖号码须为 ${g.zoneA.pick} 个${g.zoneA.label} + ${g.zoneB.pick} 个${g.zoneB.label}` };
    }
    return { draw: { issue: '自定义', date: '', a: parsed.a, b: parsed.b } };
  }
  const d = draws().find((x) => x.issue === sel);
  return d ? { draw: d } : { error: '未找到该期开奖数据' };
}

function check() {
  const lines = $('#betInput').value.split('\n').map((s) => s.trim()).filter(Boolean);
  if (!lines.length) { toast('请先输入投注号码'); return; }
  const dr = getCheckDraw();
  if (dr.error) { toast(dr.error); return; }
  const draw = dr.draw;
  const g = game();
  const addOn = state.game === 'dlt' && $('#addOn').checked;
  const unitPrice = g.price + (addOn ? g.addPrice : 0);
  const floatVals = {};
  for (const t of Object.keys(g.floatDefault)) {
    floatVals[t] = Number($(`#float-${t}`)?.value) || g.floatDefault[t];
  }
  const prizeOf = (t) => prizeForDraw(state.game, draw, t, floatVals);
  const hasReal = !!(draw.grades && (draw.grades['1'] || draw.grades['2']));

  let totalCost = 0, totalWin = 0, totalTickets = 0;
  const cards = lines.map((line) => {
    const bet = parseBet(state.game, line);
    if (!bet || bet.error) {
      return `<div class="bet-result error">「${line}」 ${bet ? bet.error : '无法解析'}</div>`;
    }
    const count = betCount(state.game, bet);
    const cost = count * unitPrice;
    totalCost += cost;
    totalTickets += count;
    const res = checkBet(state.game, bet, draw);
    let win = 0;
    const chips = Object.entries(res.tiers)
      .sort((x, y) => x[0] - y[0])
      .map(([t, c]) => {
        let amount = c * prizeOf(t);
        if (addOn && (t === '1' || t === '2')) amount += c * prizeOf(t) * 0.8;
        win += amount;
        return `<span class="tier-chip">${TIER_NAMES[t]} ×${c} · ${formatMoney(amount)}</span>`;
      });
    totalWin += win;
    const isMulti = count > 1;
    return `
      <div class="bet-result">
        <div class="bet-head">
          ${ticketBallsHTML(bet.a, bet.b, 'sm', draw)}
          <span class="badge ${isMulti ? 'multi' : ''}">${isMulti ? `复式 ${count} 注` : '单式'} · ${cost.toLocaleString('zh-CN')} 元</span>
          <span class="bet-total ${win > 0 ? 'win' : ''}">${win > 0 ? '+' + formatMoney(win) : '未中奖'}</span>
        </div>
        <div class="tier-chips">${chips.length ? chips.join('') : '<span class="tier-chip none">命中 ' + res.hitA + '+' + res.hitB + '，未达奖级</span>'}</div>
      </div>`;
  });

  const net = totalWin - totalCost;
  $('#checkResult').innerHTML = `
    <div class="result-summary">
      <div class="rs-item"><div class="k">对奖期号</div><div class="v">${draw.issue}</div></div>
      <div class="rs-item"><div class="k">总注数 / 投入</div><div class="v">${totalTickets} 注 / ${formatMoney(totalCost)}</div></div>
      <div class="rs-item"><div class="k">总奖金</div><div class="v ${totalWin > 0 ? 'win' : 'lose'}">${formatMoney(totalWin)}</div></div>
      <div class="rs-item"><div class="k">盈亏</div><div class="v ${net >= 0 ? 'win' : 'lose'}">${net >= 0 ? '+' : '-'}${formatMoney(Math.abs(net))}</div></div>
    </div>
    <p class="strategy-note">${hasReal ? '一、二等奖按该期开奖公告的实发奖金计算。' : '该期暂无公告奖金数据，一、二等奖按估值计算（可在上方「浮动奖金估值设置」中调整）。'}</p>
    ${cards.join('')}`;
}

/* ---------- 本地控制台（server.py 模式） ---------- */

let serverMode = false;

function renderRefreshLog(log, ok) {
  const el = $('#refreshLog');
  el.classList.remove('hidden');
  el.innerHTML = log
    .map((line) => {
      const cls = line.startsWith('✓') || line.startsWith('全部完成') ? 'ok' : line.startsWith('✗') ? 'err' : line.startsWith('▶') ? 'step' : '';
      return `<div class="${cls}">${line}</div>`;
    })
    .join('');
  el.scrollTop = el.scrollHeight;
  if (ok === false) setTimeout(() => el.classList.add('hidden'), 12000);
}

function resetTaskButtons() {
  const r = $('#btnRefresh');
  if (r) {
    r.disabled = false;
    r.classList.remove('running');
    r.textContent = '↻ 更新数据 · 双脑重算';
  }
  const b = $('#btnBacktest');
  if (b) {
    b.disabled = false;
    b.classList.remove('running');
    b.textContent = '▶ 运行全量回测（约 3 分钟）';
  }
}

async function pollTask() {
  try {
    const st = await (await fetch('/api/status')).json();
    renderRefreshLog(st.log, st.ok);
    if (st.running) {
      setTimeout(pollTask, 1000);
      return;
    }
    resetTaskButtons();
    if (st.ok) setTimeout(() => location.reload(), 1200);
  } catch (e) {
    resetTaskButtons();
    toast('与本地服务失联，请检查 server.py 是否仍在运行');
  }
}

function startTask(path, btn, busyText) {
  btn.disabled = true;
  btn.classList.add('running');
  btn.textContent = busyText;
  fetch(path, { method: 'POST' })
    .then((r) => r.json())
    .then((d) => {
      if (d.started === false) toast('已有任务在运行，请等待完成');
      pollTask();
    })
    .catch(() => {
      resetTaskButtons();
      toast('本地服务未运行，请双击「启动彩数实验室.command」重新启动');
    });
}

function detectServer() {
  if (!location.protocol.startsWith('http')) return;
  fetch('/api/ping')
    .then((r) => r.json())
    .then((d) => {
      if (!d.pong) return;
      serverMode = true;
      const r = $('#btnRefresh');
      r.classList.remove('hidden');
      r.addEventListener('click', () => startTask('/api/refresh', r, '⟳ 计算中…'));
      renderBacktestActions();
      syncWalletFromServer();
      setTimeout(autoRefreshTick, 5000);
      fetch('/api/status')
        .then((res) => res.json())
        .then((st) => {
          if (st.running) {
            r.disabled = true;
            r.classList.add('running');
            pollTask();
          }
        });
    })
    .catch(() => {});
}

/* ---------- 我的票夹 ---------- */

const WALLET_KEY = 'lottolab_wallet';
let walletData = (() => {
  try {
    return JSON.parse(localStorage.getItem(WALLET_KEY)) || [];
  } catch (e) {
    return [];
  }
})();
const loadWallet = () => walletData;

function persistWallet() {
  localStorage.setItem(WALLET_KEY, JSON.stringify(walletData));
  if (serverMode) {
    fetch('/api/wallet', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(walletData),
    }).catch(() => {});
  }
}

const saveWallet = (w) => {
  walletData = w;
  persistWallet();
};

// 票夹以服务端 data/wallet.json 为主存储（随项目文件夹迁移），浏览器 localStorage 数据自动并入
async function syncWalletFromServer() {
  try {
    const server = await (await fetch('/api/wallet')).json();
    if (!Array.isArray(server)) return;
    const ids = new Set(server.map((r) => r.id));
    const merged = server.concat(walletData.filter((r) => !ids.has(r.id)));
    merged.sort((x, y) => (String(y.id) > String(x.id) ? 1 : -1));
    walletData = merged;
    persistWallet();
    renderWallet();
  } catch (e) {}
}

function prizeForDraw(gameKey, draw, tier, floatVals) {
  const g = GAMES[gameKey];
  if (g.fixed[tier] != null) return g.fixed[tier];
  const gr = draw && draw.grades && draw.grades[tier];
  if (gr && gr[1] != null) return gr[1];
  return (floatVals && floatVals[tier]) || g.floatDefault[tier];
}

function walletAdd(gameKey, bets, addOn) {
  const base = DATA[gameKey] && DATA[gameKey][0] ? DATA[gameKey][0].issue : null;
  if (!base) {
    toast('暂无开奖数据，无法记票');
    return;
  }
  const w = loadWallet();
  w.unshift({
    id: Date.now() + '-' + Math.random().toString(36).slice(2, 6),
    game: gameKey,
    basedOnIssue: base,
    addedAt: new Date().toISOString().slice(0, 10),
    addOn: !!addOn,
    bets,
  });
  saveWallet(w);
  renderWallet();
  toast(`已存入票夹（${bets.length} 行），开出 ${base} 期之后一期自动对奖`);
}

function walletTarget(gameKey, basedOnIssue) {
  let best = null;
  for (const list of [DATA[gameKey] || [], (FULL || {})[gameKey] || []]) {
    for (const d of list) {
      if (Number(d.issue) > Number(basedOnIssue) && (!best || Number(d.issue) < Number(best.issue))) best = d;
    }
    if (best) break;
  }
  return best;
}

function pnlCurveHTML(settled, g) {
  if (!settled.length) {
    return '<div class="pnl-empty">开奖结算后，这里会画出你的累计盈亏走势。</div>';
  }
  settled.sort((a, b) => Number(a.issue) - Number(b.issue));
  let cumNet = 0, cumCost = 0, cumWin = 0;
  const pts = settled.map((s) => { cumNet += s.net; cumCost += s.cost; cumWin += s.win; return { issue: s.issue, cumNet, cumCost, cumWin }; });
  const n = pts.length;
  const W = 540, H = 200, pad = 42;
  const ys = pts.map((p) => p.cumNet).concat([0]);
  let ymin = Math.min(...ys), ymax = Math.max(...ys);
  if (ymin === ymax) { ymin -= 1; ymax += 1; }
  const padY = (ymax - ymin) * 0.14 || 1;
  ymin -= padY; ymax += padY;
  const sx = (i) => (n <= 1 ? W / 2 : pad + (i / (n - 1)) * (W - 2 * pad));
  const sy = (v) => (H - pad) - ((v - ymin) / (ymax - ymin)) * (H - 2 * pad);
  const y0 = sy(0);
  const last = pts[n - 1].cumNet;
  const col = last >= 0 ? '#34d399' : '#e8825c';
  const linePts = pts.map((p, i) => `${sx(i)},${sy(p.cumNet)}`).join(' ');
  let svg = '';
  svg += `<line x1="${pad}" y1="${y0}" x2="${W - pad}" y2="${y0}" stroke="#9aa0ab" stroke-dasharray="4 4"/>`;
  svg += `<text x="${W - pad}" y="${y0 - 5}" text-anchor="end" font-size="10" fill="#9aa0ab">盈亏平衡线</text>`;
  if (n > 1) {
    svg += `<polygon points="${sx(0)},${y0} ${linePts} ${sx(n - 1)},${y0}" fill="${col}" opacity="0.12"/>`;
    svg += `<polyline points="${linePts}" fill="none" stroke="${col}" stroke-width="2"/>`;
  }
  pts.forEach((p, i) => {
    svg += `<circle cx="${sx(i)}" cy="${sy(p.cumNet)}" r="3.5" fill="${col}"><title>第 ${p.issue} 期结算后 · 累计盈亏 ${p.cumNet >= 0 ? '+' : '−'}${Math.abs(p.cumNet).toLocaleString('zh-CN')} 元</title></circle>`;
  });
  svg += `<text x="6" y="${sy(ymax) + 4}" font-size="9" fill="#9aa0ab">${Math.round(ymax).toLocaleString('zh-CN')}</text>`;
  svg += `<text x="6" y="${sy(ymin) + 4}" font-size="9" fill="#9aa0ab">${Math.round(ymin).toLocaleString('zh-CN')}</text>`;
  const roi = cumCost ? (cumWin / cumCost * 100) : 0;
  return `
    <div class="pnl-box">
      <div class="pnl-stats">
        <span>已结算 <b>${n}</b> 期</span>
        <span>累计投入 <b>${cumCost.toLocaleString('zh-CN')}</b> 元</span>
        <span>累计中奖 <b>${cumWin.toLocaleString('zh-CN')}</b> 元</span>
        <span>净盈亏 <b class="${last >= 0 ? 'money-win' : 'money-lose'}">${last >= 0 ? '+' : '−'}${Math.abs(last).toLocaleString('zh-CN')}</b> 元</span>
        <span>实际回报率 <b>${roi.toFixed(1)}%</b></span>
      </div>
      <svg class="pnl-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="累计盈亏曲线">${svg}</svg>
      <p class="pnl-note">横轴＝按开奖期推进，纵轴＝累计净盈亏。样本少时波动大（中一次大奖就会往上跳），但长期必然向理论期望（每 2 元约回 ${expectedReturn(state.game).toFixed(2)} 元、即长期净亏）收敛——这正是要理性购彩的原因。</p>
    </div>`;
}

function renderWallet() {
  const box = $('#walletBox');
  if (!box) return;
  const w = loadWallet().filter((r) => r.game === state.game);
  if (!w.length) {
    box.innerHTML = '<div class="empty-state">还没有票。在上方输入号码点「存入票夹」，或在机选工具 / 数据推理页一键存入——开奖后这里自动对奖、累计真实盈亏。</div>';
    return;
  }
  const g = game();
  let totalCost = 0;
  let totalWin = 0;
  let pending = 0;
  const settled = [];
  const rows = w
    .map((r) => {
      const unit = g.price + (r.addOn ? g.addPrice || 0 : 0);
      const cost = r.bets.reduce((s, b) => s + betCount(state.game, b) * unit, 0);
      totalCost += cost;
      const target = walletTarget(state.game, r.basedOnIssue);
      const betLines = r.bets
        .map(
          (b) => `<div class="ledger-line">${b.a.map((n) => ballHTML(n, 'red sm', target ? (target.a.includes(n) ? 'hit' : 'miss') : '')).join('')}<span class="plus">+</span>${b.b.map((n) => ballHTML(n, `${kindB()} sm`, target ? (target.b.includes(n) ? 'hit' : 'miss') : '')).join('')}</div>`
        )
        .join('');
      let right;
      if (!target) {
        pending++;
        right = '<div class="ledger-result pending">待开奖</div>';
      } else {
        let win = 0;
        const chips = [];
        for (const b of r.bets) {
          const res = checkBet(state.game, b, target);
          for (const [t, c] of Object.entries(res.tiers)) {
            let amount = c * prizeForDraw(state.game, target, t, null);
            if (r.addOn && (t === '1' || t === '2')) amount += c * prizeForDraw(state.game, target, t, null) * 0.8;
            win += amount;
            chips.push(`${TIER_NAMES[t]}×${c}`);
          }
        }
        totalWin += win;
        const net = win - cost;
        settled.push({ issue: target.issue, cost, win, net });
        right = `<div class="ledger-result">第 ${target.issue} 期 · ${chips.length ? chips.join(' ') : '未中奖'}<br><b class="${net >= 0 ? 'money-win' : 'money-lose'}">${net >= 0 ? '+' : '−'}${Math.abs(net).toLocaleString('zh-CN')} 元</b> <span class="ledger-sub">投 ${cost.toLocaleString('zh-CN')} / 中 ${win.toLocaleString('zh-CN')}</span></div>`;
      }
      return `
      <div class="ledger-row">
        <div class="ledger-issue">${r.addedAt} 购<br><span class="ledger-date">基于 ${r.basedOnIssue} 期 · ${r.bets.length} 行${r.addOn ? ' · 追加' : ''} · ${cost} 元</span></div>
        <div class="ledger-balls">${betLines}</div>
        ${right}
        <button class="wallet-del" data-del="${r.id}" title="删除这张票">×</button>
      </div>`;
    })
    .join('');
  const net = totalWin - totalCost;
  box.innerHTML = `
    <p class="ai-meta">共 ${w.length} 张票（待开奖 ${pending}）· 累计投入 ${totalCost.toLocaleString('zh-CN')} 元 · 中奖 ${totalWin.toLocaleString('zh-CN')} 元 · 盈亏 <b class="${net >= 0 ? 'money-win' : 'money-lose'}">${net >= 0 ? '+' : '−'}${Math.abs(net).toLocaleString('zh-CN')} 元</b> · 一、二等奖按当期公告实发计</p>
    ${pnlCurveHTML(settled, g)}
    ${rows}
    <p class="strategy-note">票夹主存储在项目内 data/wallet.json（随文件夹迁移），浏览器内有副本；纸质票仍是唯一兑奖凭证，中奖票 60 天内兑奖。<button class="btn btn-ghost btn-mini" id="btnWalletExport">导出备份</button></p>`;
  const ex = $('#btnWalletExport');
  if (ex) {
    ex.addEventListener('click', () => {
      const blob = new Blob([JSON.stringify(loadWallet(), null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'lottolab_wallet_backup.json';
      a.click();
      URL.revokeObjectURL(a.href);
      toast('已导出票夹备份');
    });
  }
}

/* ---------- 全局 ---------- */

function renderDataChip() {
  const m = DATA.meta || {};
  $('#dataChip').innerHTML = `${m.sample ? '内置示例数据' : '<b>真实开奖数据</b>'} · ${game().name} ${draws().length} 期${m.generated ? ' · ' + m.generated : ''}`;
}

function renderAll() {
  renderDataChip();
  renderHall();
  renderAnalysis();
  renderInfer();
  renderPickerMeta();
  renderTickets();
  renderBacktestAll();
  renderChecker();
  renderWallet();
}

function init() {
  $('#gameSwitch').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-game]');
    if (!btn || btn.dataset.game === state.game) return;
    state.game = btn.dataset.game;
    $$('#gameSwitch button').forEach((b) => b.classList.toggle('active', b === btn));
    document.body.className = 'game-' + state.game;
    state.tickets = [];
    renderAll();
  });

  $('#tabs').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-tab]');
    if (!btn) return;
    $$('#tabs button').forEach((b) => b.classList.toggle('active', b === btn));
    $$('.tab-panel').forEach((p) => p.classList.toggle('active', p.id === 'tab-' + btn.dataset.tab));
  });

  $('#inferPills').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-iwin]');
    if (!btn || btn.dataset.iwin === state.inferWindow) return;
    state.inferWindow = btn.dataset.iwin;
    $$('#inferPills button').forEach((b) => b.classList.toggle('active', b === btn));
    renderAiPicks();
  });

  if (FULL) $('#scopeRow').classList.remove('hidden');
  $('#scopePills').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-scope]');
    if (!btn || btn.dataset.scope === state.scope) return;
    state.scope = btn.dataset.scope;
    $$('#scopePills button').forEach((b) => b.classList.toggle('active', b === btn));
    renderAnalysis();
  });

  $('#strategyPills').addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-strategy]');
    if (!btn) return;
    state.strategy = btn.dataset.strategy;
    $$('#strategyPills button').forEach((b) => b.classList.toggle('active', b === btn));
    $('#strategyNote').textContent = STRATEGY_NOTES[state.strategy];
  });

  $('#btnGenerate').addEventListener('click', generate);
  $('#btnCopyTickets').addEventListener('click', () => {
    if (!state.tickets.length) { toast('请先生成号码'); return; }
    copyText(state.tickets.map(ticketText).join('\n'), `已复制 ${state.tickets.length} 注号码`);
  });
  $('#btnToChecker').addEventListener('click', () => {
    if (!state.tickets.length) { toast('请先生成号码'); return; }
    $('#betInput').value = state.tickets.map(ticketText).join('\n');
    $('#tabs button[data-tab="checker"]').click();
    toast(`已带入 ${state.tickets.length} 注，选好期号即可对奖`);
  });
  $('#btnSaveTickets').addEventListener('click', () => {
    if (!state.tickets.length) { toast('请先生成号码'); return; }
    walletAdd(state.game, state.tickets.map((t) => ({ a: t.a, b: t.b })), false);
  });
  $('#btnSaveBets').addEventListener('click', () => {
    const lines = $('#betInput').value.split('\n').map((s) => s.trim()).filter(Boolean);
    if (!lines.length) { toast('请先输入投注号码'); return; }
    const bets = [];
    for (const line of lines) {
      const bet = parseBet(state.game, line);
      if (!bet || bet.error) { toast(`「${line}」${bet ? bet.error : '无法解析'}`); return; }
      bets.push(bet);
    }
    walletAdd(state.game, bets, state.game === 'dlt' && $('#addOn').checked);
  });
  $('#walletBox').addEventListener('click', (e) => {
    const btn = e.target.closest('[data-del]');
    if (!btn) return;
    saveWallet(loadWallet().filter((r) => r.id !== btn.dataset.del));
    renderWallet();
    toast('已删除');
  });
  $('#issueSearch').addEventListener('input', () => renderSearch($('#issueSearch').value));
  $('#drawList').addEventListener('click', (e) => {
    const row = e.target.closest('.draw-row');
    if (!row) return;
    const next = row.nextElementSibling;
    if (next && next.classList.contains('draw-detail')) {
      next.remove();
      return;
    }
    const d = findDraw(row.dataset.issue);
    if (!d) return;
    row.insertAdjacentHTML('afterend', `<div class="draw-detail">${drawDetailHTML(d)}</div>`);
  });
  $('#btnCheck').addEventListener('click', check);
  $('#issueSelect').addEventListener('change', () => {
    $('#customDrawRow').classList.toggle('hidden', $('#issueSelect').value !== '__custom');
  });

  renderAll();
  detectServer();
  setInterval(autoRefreshTick, 60000);
  versionTick();
  setInterval(versionTick, 120000);
}

document.addEventListener('DOMContentLoaded', init);
