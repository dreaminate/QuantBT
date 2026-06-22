---
uuid: 9fd4f1a6dde647fa8b96a29ae503d182
title: 策略台后端接线 — validate/版本/策略级fork/Live只读 端点 + 前端接真
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: backend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [be3dc5985ab04acdac8aeb44fb4d8d7f]
---

# 策略台后端接线 — validate/版本/策略级fork/Live只读 端点 + 前端接真

## Scope [必填]
后端 `main.py` 扩 4 个缺失端点（validate 图校验 / 版本历史 / 策略级 fork / Live 只读快照），并把策略台前端 S1 从 mock 切真；**不**新增下单/实盘通路、**不**改 OrderGuard/Final Gate/审批门/血统门本体、**不**碰冻结的 RunDetail。

## 上下文 / 动机 [按需]
前端侦察（`/tmp/qbt-scoutFrontend.md` §5）确认后端「编辑/run/promote/kill/publish/源码」端点齐备，唯 **validate、版本历史、策略级 fork、Live 只读快照** 四项无对应端点 —— 策略台 S1 现以 mock 占位（B9 角标）。本卡补这 4 端点并接真，复用既有端点不重写。关键不变量：① validate 必须把「exec 入边不经 Final Risk Gate」判为 `error`（蓝本 B6，原型 `_validateGraph` 规则②）；② fork/版本的身份口径必须**唯一**走 `app/backend/app/lineage/ids.py`（`content_hash`/`node_id`/`config_hash` 同一 `sha256(...)[:16]` 哈希族，文件首段自述「内容寻址身份的唯一定义源」），禁止第二套 hash；③ 任何端点都不得新开绕过 `OrderGuard.place_order`（`enforcer.py:46`）的下单路径。依赖 S1（be3dc598）提供前端 `StrategyConsolePage` 壳 + api.ts 收口位。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/main.py` | IDE 端点群末尾（`~2342`，紧邻 `@app.delete("/api/ide/strategies/{name}")` 后） | 新增 `@app.post("/api/ide/strategies/{name}/validate")`：调图校验逻辑，规则含「exec 有入边但无一来自 Final Risk Gate → error」「compat=bad → error」「必填 in 未连 → warn」；返回 `{ok, errors[], warnings[]}`，`ok = len(errors)==0` |
| `app/backend/app/main.py` | `@app.get("/api/ide/strategies/{name}")` 旁（`2313`） | 新增 `@app.get("/api/ide/strategies/{name}/versions")`：从 lineage ledger 读该策略身份的历史条目，返回版本列表（version_id 经 `lineage/ids.py`，含 lifecycle/当前标记） |
| `app/backend/app/main.py` | `@app.post("/api/sharing/{share_id}/fork")`（`1776`）为复用范式，新端点放 IDE 群 | 新增 `@app.post("/api/ide/strategies/{name}/fork")`：策略级 fork（≠ 模板 fork `2774`、≠ 分享 fork `1776`）；新草稿的 lineage/version 身份**必须**调 `lineage/ids.py` 锚定父身份，不自造 id |
| `app/backend/app/main.py` | IDE 端点群（`~2367`，`/api/ide/runs/{run_id}` 旁） | 新增 `@app.get("/api/ide/strategies/{name}/live_snapshot")`：Live 只读快照（只读聚合，**无任何写/下单参数**）；A股标的 live 快照不导出可下单态 |
| `app/backend/app/lineage/ids.py` | `node_id()` L83 / `config_hash()` L120 / `content_hash()` L77 | **只调用不改**：fork/版本端点的身份计算复用这些函数（唯一定义源，`HASH_LEN=16` 不变量 L27） |
| `app/backend/app/lineage/ledger.py` | `append()` L228 / `list_entries()` L444 | 版本历史端点读 `list_entries(strategy_goal_ref=...)`；fork 端点 `append` 新草稿谱系条目 |
| `app/backend/app/security/gate/enforcer.py` | `OrderGuard.place_order()` L46 | **只读不改**：确认新端点全不触达下单；live_snapshot 走只读聚合，绝不经此路径以外通道下单 |
| `app/frontend/src/api.ts` | strategy/ide 端点封装区（S1 收口位） | 新增 `validateGraph`/`getStrategyVersions`/`forkStrategy`/`getLiveSnapshot` 封装，走 `authFetch`（带 token） |
| `app/frontend/src/pages/workshop/StrategyConsolePage.tsx` | S1 创建的 mock 数据接入点 | 把校验概览/版本 popover/Fork 草稿/Live 只读态 4 处从 mock 切真调上述 api；接真前保留 🟡 MOCK 角标，接真后撤角标 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「exec 节点有入边但无一来自 Final Risk Gate 的图」提交 validate → 门必把它判为 `error`（`ok==false`），且 error 指向该 exec 节点（蓝本 B6 / 原型 `_validateGraph` 规则②）。**变异要杀的点**：把规则从 `error` 偷降为 `warning`、或把判定改成「只要有任意入边即放行」——必须挂测。
2. 种「fork/版本端点自造一个 hash（绕过 `lineage/ids.py`）」或「身份长度≠16 / 不经 `canonical_json`」→ 门必抓「身份未锚单一定义源」（同一策略两个 id = R8 同一本账裂开，`ids.py` 文件首段红线）。**变异要杀的点**：把 `node_id`/`config_hash` 调用替换成本地 `sha256(...)[:24]` 或 `uuid4()`——必须挂测断言身份逐字节等于 `lineage/ids.py` 产物。
3. 种「validate / live_snapshot / fork 任一端点试图触发下单（构造一条绕过 `OrderGuard.place_order` 的路径，或 live_snapshot 返回可直接下单的 live token/key）」→ 门必抓（下单唯一入口经 OrderGuard，实盘 key 不进响应体）。**变异要杀的点**：给 live_snapshot 加任何写/place 参数、或在响应里回显实盘 key——必须挂测断言这些端点零下单副作用、响应无实盘凭据。
4. 种「A股标的走 live_snapshot 并暴露可下单态」→ 门必拒（A股 live 下单永远拒，PolicyGate/TrustTier `policy.py`）。**变异要杀的点**：A股快照里出现下单按钮所需的 enable 字段——必须挂测。

## 复用 [按需]
- **不重写**：编辑/run/promote（`2520`）、kill（`/api/risk/kill_switch` `1482`，需 IP 白名单+密码二次鉴权）、publish（`/api/sharing/publish` `1716`）、源码（`/api/runs/{id}/source` `2265`）端点直接复用，前端只接线。
- **fork 范式**参考 `sharing_fork`（`1776`）的 try/ValueError→404 写法，但身份必走 `lineage/ids.py`。
- **身份唯一源**：`lineage/ids.py`（`content_hash`/`node_id`/`config_hash`/`fixture_key` 全出此处，禁止第二套）。
- **版本历史后端**：`lineage/ledger.py` `list_entries`/`append`。

## 红线 [按需]
- 权限轴⟂治理轴：本卡新端点绝不为任何 agent 模式（Auto/Bypass）开「跳过 OrderGuard/审批门/过拟合门/血统门」的口子。
- 默认止于模拟盘：live_snapshot 只读，不导向直接实盘；A股 live 下单永远拒。
- 下单唯一入口经 `OrderGuard.place_order`；实盘 key 不进响应体、不进 LLM。
- validate 裁决措辞禁「可信/安全/排除过拟合/保证」（R7）；裁决文案走后端 `_verdict_note`/`PolicyDecision.verdict_text`，不在端点里硬编正向断言。
- 身份口径单一源 `lineage/ids.py`，`HASH_LEN=16` 不变量不动（改它 = 改全脊柱身份，须用户明说）。
- 弱点一等呈现（R25）：validate 的 error/warning 默认展开、不染绿、不折叠藏起。

## 非目标 [按需]
- 不实现真实下单 / 不接实盘交易通路。
- 不改 OrderGuard / Final Risk Gate / 审批门 / 过拟合门 / 血统门本体逻辑。
- 不碰冻结的 `RunDetailPage`（只跳转 `/runs/{单段}`，不嵌入/iframe/复用）。
- 不改 `lineage/ids.py` / `ledger.py` 的身份算法（只调用）。
- 不做前端像素级排版（属 S1/前端实装卡）；本卡前端只「mock→真」切换 + api 封装。

## Open Questions（已决 D/总）[按需]
- [已决] 身份口径唯一走 `lineage/ids.py`，fork/版本端点禁自造 hash（`ids.py` 首段决策 S1/S4 + R8 同一本账）。
- [已决] validate 把「exec 不经 Final Risk Gate」判 `error` 而非 warning（蓝本 B6 不可绕 + 原型 `_validateGraph` 规则②）。
- [已决] live_snapshot 只读、零下单副作用、A股 live 拒（默认止于模拟盘 + A股 live 永远拒）。
- D/总：3/3（占位，主控跑 build_card_counters 重算）。

## 验收一句话 [必填]
种「exec 绕 Final Gate 的坏图 / fork 自造 hash 绕单一身份源 / 端点开绕 OrderGuard 下单路径或 A股 live 暴露可下单态」三类坏，validate/版本/fork/live_snapshot 四端点的门必各自抓出（error 判定 / 身份逐字节锚 `lineage/ids.py` / 零下单副作用 / A股 live 拒），且不破现有 OrderGuard/kill_switch/IDE/lineage 测试基线。
