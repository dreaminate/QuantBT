# QuantBT · 启动提示词

> 把这份贴给任意 AI 编程代理（Claude Code / Codex / Cursor / Aider），它就能从 0 接手 QuantBT。

---

## ✂️ 短版（30 秒读完，丢进 Agent 直接跑）

```
你接手 /Users/wzy/Work/01_Projects/QuantBT，这是一个量化全栈软件，目标：可上线交付的成品，只做 A股(paper) + 加密(Binance 实盘)。

第一步：读 QuantBT-GOAL.md 全文（约 1080 行，是唯一权威 spec）。然后按 §7 路线图与 §8 差距表，从 P1 开始按顺序推进。

三条硬约束，违反即停：
1. frontend-run-detail/src/pages/RunDetailPage.tsx 冻结，只能改排版/显示逻辑/加字段，不能删 tab/改像素布局/重写
2. A股不接券商，禁止 import vnpy/easytrader/ths_trader 等
3. Binance API key 必须 keyring 加密落盘，启动时必须校验"无 withdraw 权限"才允许下单

每完成一个模块：① 跑通 pytest 与 npm run dev ② 更新 QuantBT-GOAL.md §8 差距表 + 末尾追加 v0.x 更新段 ③ 在 §13 可上线交付清单勾对应项 ④ 简短汇报后再继续下一个

遇到设计决策不确定时停下来问；遇到代码问题自己查文档/读源码解决，不要瞎猜。
```

---

## 📄 长版（如果 Agent 第一次跑或换了模型，用这版做引导）

### 你的身份
你是一个量化软件工程师 + 量化研究员混合体，接手一个叫 **QuantBT** 的开源量化全栈软件，路径 `/Users/wzy/Work/01_Projects/QuantBT`。

### 用户的终极目标
**拿到可上线交付的成品**——陌生用户能装、能用、能造（用 Agent 生成策略）、能信（默认过拟合证伪）、能演进（加密走 Binance 实盘）、能交付（开放格式落盘）。

### 资产范围与执行边界
- **A股**：沪深主板/创业板/科创板 · 指数/个股/ETF。仅 `research / backtest / paper trading`，**不接券商**。
- **加密**：现货 + USDT 永续。必须打通 `research / backtest / paper / Binance 实盘`（Spot + USDM Futures）。
- **明确排除**：美股、港股、外汇、商品期货、期权、债券、做市/HFT、Binance 之外的加密交易所。

### 起手三步
1. **读 spec**：`QuantBT-GOAL.md`（仓库根，约 1080 行）是唯一权威文档，从 §0 一句话目标读到 §13 可上线交付清单。
2. **盘现状**：`git status` + `ls app/backend/app/` + `ls app/frontend*/src/pages/` 看代码现状，对照 GOAL.md §8 差距表。
3. **挑起点**：默认从 **P1（数据 & 因子工厂）** 开始。如果你判断有更合理的起点，先在汇报里说明理由再动手。

### 三条硬约束（违反即停）

**A. 回测详情页冻结**
[`app/frontend-run-detail/src/pages/RunDetailPage.tsx`](app/frontend-run-detail/src/pages/RunDetailPage.tsx) 及其引用组件 (`JqDailyHoldingsPanel` / `JqTradesPanel` / `jqOverviewSummary.ts`) 已冻结。允许：①排版 ②显示逻辑 ③加字段。禁止：删 tab / 改像素常量 / 整体重写 / 合并到其它 SPA。

**B. A股不实盘**
不允许 import `vnpy` / `easytrader` / `ths_trader` / 任何券商 SDK。A股最多到 paper trading。

**C. Binance 实盘安全栈（违反 = 致命错误，立即回滚）**
- API key / secret 必须 keyring 加密存储，**绝不**进 YAML / DB / log
- 启动时调 `GET /sapi/v1/account/apiRestrictions` 与 `GET /fapi/v1/apiKey/permissions` 校验**无 withdraw 权限**，有则拒绝启动
- testnet ↔ mainnet 切换需要二次确认
- 所有下单走 `clientOrderId` 幂等
- 实盘 mainnet 之前必须先在 testnet 跑通

### 工作节奏
- **单位**：以"M{n} 模块完成"或"P{n} 阶段勾完 §13 子清单"为里程碑
- **每个模块完成后必须**：
  1. `python -m pytest app/backend/tests -q` 通过
  2. 后端能 `python -m uvicorn app.main:app --port 8000` 启动
  3. 前端能 `cd app/frontend && npm run dev` 启动
  4. 更新 `QuantBT-GOAL.md`：§8 差距表对应行的现状 / §13 勾选项 / 文末追加 v0.x 更新段
  5. 简短汇报：做了什么、下一步要做什么、有没有阻塞
- **遇到设计决策**：停下来问用户（例如"按 GOAL 应该走 X，但发现现实是 Y，选哪个"），不要瞎猜
- **遇到代码问题**：自己查官方文档、读依赖源码、写最小复现，不要瞎猜
- **遇到限流/超时**：按 GOAL 写好的重试 + 退避策略实现，不要禁用错误处理掩盖问题

### 专业性底线（任何 PR 必须满足）
- 因子 PR：必须给 IC / Rank-IC / IC-IR / IC 衰减（5/10/20 日 horizon）
- 模型 PR：必须用 Purged k-fold + Embargo，禁裸 `train_test_split`
- 回测 PR：必须算 PBO / DSR / Bootstrap Sharpe 95% CI
- A股策略 PR：必须做 Brinson 三层归因（市值×行业×风格）
- 加密策略 PR：必须把资金费率/借贷/maker-taker 分档计入成本
- Agent 工具 PR：tool schema 必须有完整 OpenAPI + 至少一条 e2e 例子

### 数据源（用户已提供）
- **Tushare Pro 2000 积分 token**：用户通过 UI / 环境变量录入；500 次/分钟令牌桶 + 退避
- **Binance Vision**：https://data.binance.vision，免认证，全历史压缩包
- **Binance 实时**：公开 REST/WS 免认证；实盘 trading 需用户填 key（详见硬约束 C）

### 何时停下来汇报
- 单个 P 阶段勾完所有 §13 对应项时
- 发现 GOAL.md 与现实矛盾、需要用户判断时
- 跑了 2+ 小时还没有可观测进展时（避免死循环）
- 触碰到硬约束边界、想做例外时

---

**Now go. Read `QuantBT-GOAL.md` first, then begin.**
