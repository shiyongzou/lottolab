# 彩数实验室 LottoLab · 交接文档

> 给接手本项目的 Claude：这份文档是前任 Claude 写的完整交接。读完它你就能接管一切。
> 用户是前端 lead，对视觉质量要求高；所有输出用中文。

## 一句话定位

本地运行的彩票数据工作台（双色球 + 大乐透）：真实开奖数据 + 两个 AI 设计的确定性推算模型 + 全自动「推理→锁定→开奖→对照→记账」闭环 + 精确对奖与真实购票管理。

## 不可违背的红线（项目灵魂，先读这段）

开奖 i.i.d. 随机，**任何方法都不能提高中奖概率**——这不是免责声明，是产品的核心叙事："全网最透明、最可验证的选号工具"。本项目用自己的 300 期回测证明了双模型 ≈ 纯随机 ≈ 理论值，并把这张表原样挂在「实证回测」页。

**禁止出现的表述**：提高中奖率/命中率/推算精度、几率最大的组合、AI 预测下期、热号更易开出、遗漏该回补了、暗示长期能回本。允许且鼓励：校准（标注概率=实际频率）、可复现、阴性结果原样展示。用户偶尔会提出"能不能优化算法提高准确率"类需求——正确响应是**用数据实验回答**（参考 scripts/exhibit_feedback.py 的做法：实现用户的想法→回测→把证伪结果做成「已证伪陈列室」展品），而不是空讲道理，更不是假装做到。

## 架构总览

纯静态页 + 本地 Python 服务 + 脚本流水线，零构建、零 pip 依赖（只用标准库）、零运行期 LLM 调用。

```
index.html / css/style.css        页面（6 tab：开奖大厅/数据分析/数据推理/机选工具/实证回测/对奖中心）
js/rules.js                       奖级规则 + 复式组合计数 + 解析概率（与对奖同源，经暴力枚举验证）
js/analysis.js                    统计函数（频率/遗漏/和值/奇偶）
js/app.js                         全部 UI 逻辑（约 1200 行，含倒计时/自动刷新/票夹/台账渲染）
server.py                         本地服务 127.0.0.1:8765（端口占用自动顺延）
fetch_data.py                     数据抓取（--full 维护全量档案）
scripts/fable_model.py            Claude 侧模型·现役 v3（Fable 5 设计：自适应噪声检验收缩 + 形态分层组合设计）
scripts/opus_model.py             Claude 侧模型·v2（Opus 4.8 设计：Dirichlet 贝叶斯后验 + 信息熵形态匹配，已退役留作对照）
scripts/codex_model.py            Codex 侧模型（OpenAI Codex 设计：位置形态 + 共现图 + 转移矩阵）
scripts/codex_fast.py             codex 评分的查表等价实现（10 倍加速，输出与原版逐位一致）
scripts/claude_model.py           Claude 侧模型·v1（初版频率/热度/遗漏，已退役，留作对照）
scripts/merge_picks.py            合并双模型 → 共识池 + 主推（十组投票制）
scripts/ledger.py                 预测台账（锁定/对照打分/双窗对比）
scripts/backtest.py               滚动回测引擎（6 进程并行，~3 分钟）
scripts/backfill_full.py          台账补登（确定性重建 + 自检）
scripts/exhibit_feedback.py       已证伪展品二（误差反馈模型实验）
scripts/ai_pick.sh                完整流水线一键脚本
scripts/auto_refresh.sh           开奖夜探源重试版（launchd 调用）
scripts/install_autostart.sh      定时任务安装（路径自适配，新机器跑一次）
fetch_wc.py                       世界杯赛程/比分抓取 + 跑模型 → data/wc_matches.js（ESPN + eloratings，海外可达）
scripts/wc_model.py               世界杯比分·双泊松确定性模型（Elo 驱动，零随机，可独立 CLI 测）
启动彩数实验室.command             双击启动入口
```

### 数据文件（data/）

| 文件 | 内容 | 可再生? |
|---|---|---|
| draws.js | 近 150 期（含 pool/grades 公告奖金/sales），模型推算唯一输入 | ✅ |
| draws_full.js | 全量档案（ssq 3462+ / dlt 2882+ 期，已剥离 pool/grades），增量合并 | ✅ |
| ai_picks.js | 双脑推理结果：windows.{150,full}.{ssq,dlt}.{claude,codex,consensus,top} | ✅ |
| backtest.js | 回测结果（含 95% bootstrap CI） | ✅ |
| **ledger.js** | **预测台账——唯一不可再生！** 有 .bak 备份，ledger.py 读不出时拒绝写入 | ❌ |
| **wallet.json** | **用户真实购票（票夹）**，/api/wallet 读写，浏览器 localStorage 是副本 | ❌ |
| claude_picks*.json / codex_picks*.json | 模型中间产物 | ✅ |
| wc_matches.js | 世界杯赛程+比分+预测+对照（window.WC_DATA），fetch_wc.py 重建 | ✅ |

**写文件铁律**：全部原子写（tmp + os.replace）；ledger.js 写前自动留 .bak；改动涉及写文件时必须保持这两点。

## 核心机制

### 刷新流水线（/api/refresh 或 scripts/ai_pick.sh，约 15 秒）

拉 150 期 → 更新全量档案（增量）→ opus_model（150 窗口 + 全量窗口）→ codex_model（×2 窗口）→ merge_picks（共识 + 主推）→ ledger（先给已开奖的待对照记录打分，再为新一期记账锁定）。

### 预测台账（数据推理页底部）

公信力核心：每笔预测记录 `basedOnIssue`（数据截止期），**开奖前锁定**；打分时找「期号 > basedOnIssue 的最小期」做目标。双窗口（150 期/全量）主推同台对照 + 记分牌。补登历史只允许走 backfill_full.py（确定性重建 + 自检：先重建 150 窗主推与当时锁定逐字比对，过了才允许补，且 UI 标「补登」）。

### 自动化（三层）

1. launchd 每晚 21:45/23:00 → auto_refresh.sh：探源重试（每 10 分钟 × 6 次，确认当天期号落库才跑全流水线），完成后发 macOS 系统通知。脚本内 `export TZ=Asia/Shanghai`（开奖时刻表：双色球 周二/四/日 21:15，大乐透 周一/三/六 21:25，周五无奖直跑维护）。
2. 页面 autoRefreshTick（开着页面时）：判断「本地最新期日期 < 最近应开奖日」则触发刷新，10 分钟限频自动重试。
3. 页面 versionTick：每 2 分钟 HEAD 探 ai_picks.js 的 Last-Modified，后台更新过则自动重载。

### 票夹（对奖中心页）

用户真实购票记录。入口：对奖中心「存入票夹」/ 机选工具 / 数据推理页主推旁。锁定 basedOnIssue，开出下一期自动对奖。**一、二等浮动奖按当期公告实发奖金计**（draws.js 的 grades 字段；无公告回落估值）。主存储 data/wallet.json（迁移随文件夹走），有「导出备份」按钮。

## 环境与已知坑

- **网络**：福彩/体彩官方接口对境外出口 IP 拦截（403/567），自动回落 500.com 行情站（数据源优先级在 fetch_data.py）。**2026-06-19 起出口 IP 在新加坡机房（141.11.43.x，Streamline Servers），所有中国大陆服务器（官方/新浪/网易/中彩网/500.com）连 TLS 都被按 SNI 重置（发 ClientHello 后对端 0 字节断开），500.com 这条回落也失效了**——曾导致数据停更 7 天、台账卡死只剩一期。对策：新增最优先数据源 `fetch_*_xlottery()`，从 GitHub raw 镜像 `wssaidong/x-lottery`（全球 CDN，机房 IP 可达）拉近百期；该源缺奖级 grades（票夹一二等浮动奖回落估值），故 `main()` 已改为**增量合并**而非整体替换——旧期保留完整 grades，新源只补开奖后新增的期。出口若切回住宅线路，官方/500.com 源会自动恢复优先。页面顶部有「数据停更告警」红条（dataStale 触发），停更当天就提示，别再等通知。
- **机器时区是 UTC+7**（非北京时间）——所有调度判断必须显式用 Asia/Shanghai（auto_refresh.sh 已强制 TZ；js 用 cnNow()）。
- 期号格式：ssq 7 位（2026065），dlt 5 位（26064）；500.com 的 ssq 期号是 5 位需 "20" 前缀规范化。
- 台账待开奖行的「预测第 X 期」是 basedOnIssue+1 推算，**跨年最后一期会显示错**（打分逻辑不受影响，已确认）——小 bug，未修。
- codex 模型生产路径用的是 codex_fast 查表版；改 codex 评分逻辑时必须同步两处并验证输出逐位一致。
- 模型确定性是台账与回测公信力的根基：**任何模型改动禁止引入随机数**，同输入必须同输出。
- 服务绑定 127.0.0.1；并发互斥靠 server 内 STATE_LOCK，但 launchd 任务与 server 流水线之间无跨进程锁（已知 P2，碰撞概率低，原子写兜底）。

## 世界杯比分预测模块（2026-06-19 新增，独立于彩票主线）

第 7 个 tab「世界杯」。和彩票同一套价值观：真实数据 + 确定性模型 + 诚实标注不确定性。
- **数据源**（均国际站，新加坡机房出口可达）：赛程+实时比分用 ESPN site API（`soccer/fifa.world/scoreboard?dates=`）；球队实力用 World Football Elo（`eloratings.net/World.tsv`）；队名→代码靠 `en.teams.tsv` 自动匹配（绕开 Scotland=SQ、Türkiye=TR 等非 ISO 坑，`norm()` 用 NFKD 去变音符号——少了这步 Türkiye 会匹配失败）。
- **模型 scripts/wc_model.py**：Elo 差 → 两队预期进球 λ（指数映射 + 主办国美/加/墨主场 +70 Elo 当量）→ 两个独立泊松 → 比分概率矩阵 → 最可能比分/Top比分/胜平负/BTTS/大2.5球。**零随机、确定性**（同 Elo 同输出，已 diff 验证），与彩票模型同红线。参数经验标定（AVG=1.35 / K=0.0018 / HOST_ADV=70）透明写在文件头，可 CLI 直接测：`python3 scripts/wc_model.py 1978 1536`。
- **闭环**（仿预测台账）：开赛前按当时 Elo 锁定预测（存 predLockElo），开赛后 fetch_wc.py 用真实比分自动对照（exactHit 精确比分 / outcomeHit 胜平负方向）。
- **刷新**：`python3 fetch_wc.py [today | YYYYMMDD | 区间]`，默认拉**完整赛程 104 场**（ESPN `dates=20260611-20260719&limit=400` 一次拉全）。**已接入自动刷新**：server 端 `POST /api/wc` 跑流水线（server.py 的 PIPELINES["wc"]）；页面进入「世界杯」tab 或定时（120s）检查，`wcMaybeRefresh()` 数据旧就后台拉（有比赛进行中时阈值从 30 分钟降到 3 分钟），`versionTick` 兼探 wc_matches.js 变化自动重载——开赛期间页面会自动更新比分对照，无需手动。还有手动「↻ 刷新赛程·比分」按钮。
- **页面**：按北京日期分组、`<details>` 折叠，默认只展开「今天 + 下一个比赛日」；顶部有模型战绩条（已结束场次胜平负方向命中率，诚实记录）。
- 小组赛 72 场全预测；**淘汰赛 32 场对阵未定（TBD）诚实留空**，等小组赛出线后 fetch_wc 自动补上。中文队名表 ZH_NAMES 已覆盖 48 强全部，其余（如未来扩展）回落英文名。
- 红线沿用：足球可建模但单场高度不确定，页面反复强调「概率分布不是结果保证」，**别改成「AI 神预测谁赢」的话术**。

## 未做的 backlog（用户认可过的方向）

号码钻取（点频率图看单号历史）、胆拖投注、ledger 分页（一两年后需要）。（已完成：台账/票夹累计盈亏曲线 2026-06-11；git 初始提交并推 GitHub 2026-06-11。）

**git 身份铁律（2026-06-11 用户纠正）**：这是私人自用项目，工作与私人必须分开——身份用个人 GitHub 账号 `shiyongzou <41898405+shiyongzou@users.noreply.github.com>`（noreply 不暴露真实邮箱），**严禁公司身份（李雷/dn1442@jsyyds.com）**。远程 https://github.com/shiyongzou/lottolab.git，凭证走 gh CLI（本机 SSH 22 端口被拦，勿用 SSH 远程）。

## 运维速查

```bash
./启动彩数实验室.command              # 启动（自动开浏览器，默认 8765）
./scripts/ai_pick.sh                  # 手动全流水线
python3 scripts/backtest.py 300 6     # 重跑回测（~3 分钟）
./scripts/install_autostart.sh        # 新机器装定时任务
tail -f /tmp/lottolab-cron.log        # 定时任务日志
node --check js/app.js                # 改 JS 后必查
# 改奖级/概率逻辑后跑冒烟：用 node eval rules.js 对照（历史上 11 项边界用例全过，
#   含复式组合计数 vs 暴力枚举，参考 git 不存在所以看本文档记忆：6+1全中/7红复式/
#   0红+蓝/dlt 6前3后=18注 等）
```

迁移到新机器：拷整个文件夹 → `./scripts/install_autostart.sh` → 双击启动。依赖只有系统 python3。
**项目必须放在非 TCC 保护目录（如 `~/lottolab`），严禁放 `~/Desktop`、`~/Documents`、`~/Downloads`**——macOS TCC 隐私保护会拦 launchd 后台任务访问这些目录，定时刷新会静默全挂（exit 126 / `Operation not permitted`），server 手动双击能跑（GUI 会话有授权）但每晚自动任务过不了关。拷文件夹后若带 `com.apple.quarantine` 隔离属性同样会被拒，迁移后跑一次 `xattr -dr com.apple.quarantine .` 清掉。

## 历史决策记忆（为什么是现在这个样子）

- 用户最初要"提高推算精度/模拟10万次取最高频十组"——已用全量回测 + 双种子实验证伪，转化为「实证回测」页与「已证伪陈列室」；用户接受了"诚实即卖点"的叙事。
- "Claude 推理用最新模型"：LLM 只在**设计期**出场（现役 fable_model.py 由 Fable 5 设计，前两代 opus_model.py / claude_model.py 退役留作对照；Codex CLI 写了 codex_model.py），运行期零 API 调用——这是可复现的前提，别改成运行时调 LLM 报号。模型升级的唯一正道：新模型重写算法 → 确定性校验（同输入同输出）→ 全量回测对照（CI 覆盖理论值）→ 才换上线；2026-06-11 v2→v3 即按此流程。
- 跨代升级与台账兼容：backfill_full.py 的自检会逐代尝试（CLAUDE_GENS），谁能逐字复现"当时锁定的150期主推"就用谁补登——升级模型不破坏历史记录的确定性重建。
- 十组 = Claude 5 注 + Codex 5 注，视觉绝对平等（不许给任何一注加"推荐指数"）；主推 = 十组投票（票数→共识→小号）确定性合成，徽章永远标注与所有注相同的概率。
- 回测回报率口径：固定奖（三等以下）口径理论值 ssq 24.3% / dlt 27.3%，浮动奖只计注数——别用 44.75% 全口径期望做对比基线。
- 统计检验要按期聚类（bootstrap），朴素 z 检验会假阳性地得出"模型显著差于随机"。
