// 读对照数据 JSON（argv[2]）→ 渲染对照图 HTML 到 /tmp/ticket.html
// 数据格式：{ summary:[{team,score,ht}], tickets:[{n,legs:[{g,pick,actual,hit}],allHit,broken:[]}] }
const fs = require("fs");
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

const summary = (data.summary || []).map(v =>
  `<span class="m">${v.team} <b>${v.score}</b>${v.ht ? `<small>半${v.ht}</small>` : ""}</span>`).join("");

const cards = (data.tickets || []).map(tk => {
  const rows = tk.legs.map(l => `<tr class="${l.hit ? 'ok' : 'no'}">
    <td class="g">${l.g}</td><td>${l.pick}</td><td>${l.actual}</td>
    <td class="r">${l.hit ? '✅' : '❌ 错在这'}</td></tr>`).join("");
  const res = tk.allHit ? '✅ 全中！' : '❌ 未中（断在：' + (tk.broken || []).join('、') + '）';
  return `<div class="tk"><div class="th ${tk.allHit ? 'win' : 'lose'}">${tk.n}<span class="res">${res}</span></div>
    <table><tr class="hd"><th>场次</th><th>我选</th><th>实际</th><th>结果</th></tr>${rows}</table></div>`;
}).join("");

const html = `<!doctype html><html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,"PingFang SC",sans-serif}
body{width:720px;background:radial-gradient(circle at 30% 0%,#1e2a1e,#121512 60%);color:#e8e4d4;padding:28px}
.title{font-size:22px;font-weight:800;color:#8fce6f;text-align:center}
.sub{text-align:center;color:#9b9088;font-size:12px;margin:8px 0 6px}
.sums{display:flex;flex-wrap:wrap;justify-content:center;gap:14px;margin-bottom:18px;font-size:12.5px}
.m{color:#c9bfb5}.m b{color:#f0c96a;margin:0 2px}.m small{color:#7a7068;margin-left:3px}
.tk{background:rgba(0,0,0,.3);border:1px solid rgba(255,255,255,.08);border-radius:12px;padding:4px 0 8px;margin-bottom:14px;overflow:hidden}
.th{padding:10px 16px;font-weight:700;font-size:14px;display:flex;justify-content:space-between;align-items:center}
.th.win{background:rgba(143,206,111,.15)}.th.lose{background:rgba(232,69,60,.12)}
.res{font-size:13px}.win .res{color:#8fce6f}.lose .res{color:#f0978f}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:7px 16px;text-align:left}
.hd th{color:#9b9088;font-size:11px;font-weight:600;border-bottom:1px solid rgba(255,255,255,.08)}
tr.ok td{color:#cfe8c0}tr.no td{color:#f0b0aa}
.g{width:42%}.r{text-align:right;font-weight:700}
tr:not(.hd){border-bottom:1px solid rgba(255,255,255,.04)}
.foot{text-align:center;font-size:11px;color:#7a7068;margin-top:12px;line-height:1.6}
</style></head><body>
<div class="title">🏁 跟单对照 · 全部完场</div>
<div class="sub">每张票每场每腿逐一对照，标出错在哪一步</div>
<div class="sums">${summary}</div>
${cards}
<div class="foot">总进球=全场总进球；半全场=半场结果+全场结果。每张票 4 场全中才中奖。</div>
</body></html>`;
fs.writeFileSync("/tmp/ticket.html", html);
console.log("ok");
