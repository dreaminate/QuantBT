# QuantBT 5 分钟 Quickstart

## 0. 你将得到什么

- 一个能跑的本地全栈量化软件（FastAPI + Vite + DuckDB/Parquet）
- 内置 30 个 alpha 因子 + 5 个数据 connector + 完整研究执行台
- A股仅 paper trading（不接券商）；加密支持 Binance Spot + USDM Futures 实盘
- 所有产物以 Parquet/CSV/JSON/MD 落盘，可独立审计

> **数据 token-gated · 诚实说明**：**加密自带样本即开即用**（内置 demo run 不配 key 也能看）；
> **A股数据需自配 `TUSHARE_TOKEN`**（见第 2 节）。没 token 不影响加密链路与所有 demo。

---

## 1. 安装（二选一）

### Docker（推荐 · 一行命令）

```bash
git clone <repo> quantbt && cd quantbt
docker compose up -d
# 浏览器打开 http://127.0.0.1:5173
```

### 本地 Python（开发模式）

```bash
cd app/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cd ../frontend
npm install
cd ../..

npm run dev
```

后端 `http://127.0.0.1:8000`、前端 `http://127.0.0.1:5173`。

---

## 2. 三步设置（10 分钟内完成）

1. **填 Tushare token**（A股数据用）
   - 顶部「工坊」→「Binance 交易台」下面那个 keystore 表单也能存 tushare token？不，这里走环境变量更稳：
     ```bash
     export TUSHARE_TOKEN=你的2000积分token
     ```
   - 或在 `docker-compose.yml` 的 `environment` 段加 `TUSHARE_TOKEN`
2. **挂 Binance Vision 数据目录**（加密数据用）
   - 默认 `./data/raw/binance_vision`，第一次拉数会自动建
3. （可选）**填 Binance API key**（实盘用，否则跳过）
   - 在「工坊」→「Binance 交易台」keystore 表单录入 name/api_key/api_secret
   - **必须先关 withdraw 权限**，否则启动会拒绝（见 [Binance 安全指南](binance-security-guide.md)）

---

## 3. 跑示例策略

### 路线 A：用研究执行台结构化想法

打开 `http://127.0.0.1:5173/workbench` → 「研究执行台」，输入：

> 我想做一个 A股 周频 选股策略，回撤 15%，单标的 5%

配置真实 LLM provider 后，研究执行流会：
1. 返回一份建议（IR 目标 / 池子建议 / 数据范围）
2. 触发 `strategy_goal.create` 工具，给你 StrategyGoal JSON
3. 生成候选实现，并按流程继续跑因子 IC → 训模型 → 回测

未配置 provider 时，真实流会明确返回 `NoLLMConfigured`，不会静默落到 DevLocalLLM。
如需查看脚本演示，必须在界面显式选择带 `MOCK` 标识的演示模式。

### 路线 B：直接看现有 demo run

`http://127.0.0.1:5173/runs/quant1-demo` — 看完整的「收益概述」三联图 + Brinson 归因。

---

## 4. 看专业性硬指标

每个 run 都会自动产出（GOAL §6.1 强制）：
- **PBO**（Probability of Backtest Overfitting）— `app.eval.cscv_pbo`
- **DSR**（Deflated Sharpe Ratio）— `app.eval.deflated_sharpe_ratio`
- **Bootstrap Sharpe 95% CI** — `app.eval.bootstrap_sharpe_ci`

A股策略额外加：
- **Brinson 三层归因**（市值×行业×风格）— `app.eval.brinson_attribution`

加密策略额外加：
- **资金费率 + maker/taker 分档** 计入实盘成本

---

## 5. 文件去哪了

- `data/raw/...` 原始行情
- `data/artifacts/experiments/{run_id}/` 回测产物（portfolio / trades / report.md / metrics.json）
- `data/datasets/registry.jsonl` dataset_version 不可变台账
- `data/factors/registry.json` 因子注册表（含 lifecycle_state）
- `data/experiments/{experiments,runs,models}.jsonl` 实验追踪
- `data/audit/` 实盘 audit log（每笔订单 + 信号源 + 决策依据 + 实际成交）
- `~/.quantbt/keystore_index.json` keystore 索引（仅索引；密文走 OS keyring）

---

## 6. 我能 DIY 什么

- **新数据源**：写一份 YAML 喂给 `GenericRESTConnector`，无需写 Python。模板见
  [`app/backend/app/connectors/generic_rest.py`](app/backend/app/connectors/generic_rest.py) 顶部 docstring。
- **新交易接口**：同理，YAML 驱动 `GenericTradingVenue`，文件见
  [`app/backend/app/execution/generic_trading.py`](app/backend/app/execution/generic_trading.py)。
- **新因子**：在「工坊」→ 表达式编辑器（M16 计划）粘入 `rank(ts_corr(close,volume,20))`
  这样的表达式。当前可直接调 `POST /api/factors`（M16 接入后）。
- **新策略 (代码复刻)**：粘 vnpy / backtrader / pandas / qlib 代码到「研究执行台」，
  系统用 AST 改写到 QuantBT 标准模板，产物仍需跑验证链。

---

## 7. 出问题怎么办

| 症状 | 原因 | 解决 |
|---|---|---|
| `TUSHARE_TOKEN 未配置` | env 没设 | 见第 2 节 |
| `BinanceWithdrawPermissionError` | API key 有 withdraw 权限 | 去 Binance 网页关掉 withdraw，重启 |
| `/api/data/freshness` 全是 unknown | 还没拉过数 | 先用 connector 拉一份；或看 `/api/datasets` |
| 回测无报告 | run 失败 | 看 `data/artifacts/experiments/{run_id}/backtest.log` |
| Kill Switch 无反应 | venue 没注册到 `KILL_SWITCH` | 重启服务时把 venue 注入 main.py 的 `KILL_SWITCH` |

更多：见 [Binance 安全指南](binance-security-guide.md) 与 GOAL `QuantBT-GOAL.md` §M9 / §M14。
