# QuantBT 用户手册

> 这份手册按 `QuantBT-GOAL.md` §4 模块组织，每节告诉你「这个模块在 UI / API / 文件
> 上对应什么」。读完你能用 QuantBT 跑出第一个端到端策略 + 看懂所有产物。

---

## 0. 5 分钟搞清"它是什么"

QuantBT 是一个面向 A股（仅 paper trading）+ 加密（Binance 现货/USDM 永续，含实盘）
的全栈量化软件。三层视角：

1. **数据 + 因子**：5 内置 connector + 30 内置 alpha_lite + DIY YAML connector
2. **策略**：表达式因子 → ML 模型 (LGBM + Purged k-fold) → 信号融合 → 组合优化
3. **执行 + 审计**：BacktestVenue / PaperVenue / BinanceSpot/UM Futures + 风控 + Kill Switch

每个 run 自动产出 `data/artifacts/experiments/{run_id}/` 标准目录（report.md /
portfolio.csv / metrics.json …），可以被 RunDetailPage 一键加载。

---

## 1. 装

参见 [installer-guide.md](installer-guide.md)。最快路径：
```bash
docker compose up -d
# http://127.0.0.1:5173
```

---

## 2. 配 secrets

参见 [secrets-guide.md](secrets-guide.md)。最少配置：填 `~/.quantbt/secrets.yaml`
里的 `llm.anthropic.api_key`（或 custom + base_url + model）就能让 Agent 工作台跑。
更多：Tushare token / Binance testnet key。

---

## 3. UI 总览

顶栏有两个区：

### 回测研究
- `/runs` 回测列表（带 search / filter / sort）
- `/runs/{id}` 回测详情（**冻结，仅排版/显示逻辑/加字段允许修改**）
- `/compare` 多 run 对比
- `/data` 数据中心（拉数 / preview / 数据集 catalog）

### 工坊
- `/workshop` 策略工坊：自然语言 → StrategyGoal slot-fill
- `/agent` Agent 工作台：跟 LLM 对话；可看 provider 状态 + 一键测试
- `/factors` 因子市场：30 alpha_lite + 用户表达式因子，按 lifecycle_state 分组
- `/trading` Binance 交易台：keystore + testnet/mainnet 顶部色块 + 二次确认 + Kill Switch
- `/experiments` 实验追踪：experiments + runs + lineage

---

## 4. 模块速查（对齐 §QuantBT-GOAL.md §4）

| 模块 | 后端入口 | 文件 | API |
|---|---|---|---|
| M1 StrategyGoal | `app.strategy_goal.StrategyGoal` | `strategy_goal.py` | `POST /api/agent/slot_fill` |
| M3a connectors | `app.connectors.registry` | `connectors/` | `GET /api/connectors` |
| M3b dataset_version | `app.data_quality` | `data_quality.py` | `GET /api/datasets` `/api/data/freshness` |
| M4 因子 | `app.factor_factory` | `factor_factory/` | `GET /api/factors` `/api/factors/operators` |
| M4b alpha_lite | `register_alpha_lite()` | `factor_factory/alpha_lite.py` | 自动注册 30 个 |
| M5 标签 | `app.labels` | `labels/` | （后端逻辑层，无单独 REST） |
| M6 模型 | `app.models.train_model` | `models/` | （后端逻辑层） |
| M7 信号融合 | `app.signals.fuse_signals` | `signals/` | （后端逻辑层） |
| M8 组合 | `app.portfolio.optimize_portfolio` | `portfolio/` | （后端逻辑层） |
| M9.1 执行抽象 | `app.execution.{BacktestVenue,PaperVenue,GenericTradingVenue}` | `execution/` | – |
| M9.3 Binance 实盘 | `BinanceSpotVenue` / `BinanceUMFuturesVenue` + `BinanceUserDataStream` | `execution/binance_*.py` | `POST /api/security/keystore` `POST /api/security/network` |
| M10 评估 | `app.eval.{cscv_pbo,deflated_sharpe_ratio,bootstrap_sharpe_ci,brinson_attribution}` | `eval/` | （写进 run.metrics） |
| M11 因子生命周期 | `LifecycleManager` | `factor_factory/lifecycle.py` | – |
| M12 实验追踪 | `ExperimentStore` `RunStore` `ModelRegistry` | `experiments/` | `GET /api/experiments` `/runs` `/models` |
| M13 DAG | `app.dag.run_dag` | `dag/` | – |
| M14 Agent | `AgentRuntime` + `make_llm_client` | `agent/` | `POST /api/agent/chat` `/api/llm/*` |
| Paper 调度 | `app.paper.PaperScheduler` | `paper/scheduler.py` | – |
| 安全 keystore | `SecureKeystore` + `secrets_loader` | `security/` | `GET /api/security/secrets` `/api/security/reload_secrets` |
| 风控 | `RiskMonitor` + `KillSwitch` | `risk/` | `GET /api/risk/alerts` `POST /api/risk/kill_switch` |
| 监控 | `cost_drift.compute_weekly_cost_drift` | `monitor/` | `scripts/weekly_cost_drift.py` CLI |
| 可观测性 | `init_error_reporting` | `observability/` | `GET /api/observability/errors` |
| 数据导出 | `data_export.export_tar_gz_stream` | `data_export.py` | `GET /api/data/export` |
| SSE 进度 | `JobStore.stream_job` | `jobs.py` | `GET /api/jobs/{id}/stream` |

---

## 5. 端到端 demo（最佳学习路径）

跑两个 deterministic demo（不需要任何 key）：

```bash
python examples/run_a_share_ml_demo.py
python examples/run_crypto_perp_demo.py
```

产物：
- `data/artifacts/experiments/a_share_ml_demo/`
- `data/artifacts/experiments/crypto_perp_demo/`

打开 http://127.0.0.1:5173/runs 立即能看到。

---

## 6. 关键命令速查

```bash
# 跑全套测试
python -m pytest app/backend/tests -q

# 启动后端
cd app/backend && python -m uvicorn app.main:app --port 8000

# 启动前端
cd app/frontend && npm run dev

# 启动 paper 调度器（cron 风格）
python -m app.paper.scheduler --strategy demo --symbols BTCUSDT,ETHUSDT --market crypto

# 跑成本偏差周报
python scripts/weekly_cost_drift.py --audit-log data/audit/audit.jsonl --asset crypto_perp

# secrets 热加载
curl -X POST http://127.0.0.1:8000/api/security/reload_secrets

# 一键导出"我的所有数据"
curl http://127.0.0.1:8000/api/data/export -o my-quantbt-export.tar.gz
```

---

## 7. 三条硬约束（GOAL §M15 / §12 / §M9.3）

1. **`frontend-run-detail/src/pages/RunDetailPage.tsx` 冻结**：仅排版/显示逻辑/加字段
2. **A股不接券商**：禁止 `import vnpy/easytrader/ths_trader` 等
3. **Binance API key 必须 keyring 加密 + 启动时校验无 withdraw 权限**

---

## 8. 故障定位

`GET /api/observability/errors` 看最近 10 条未捕获异常；本地落 `data/audit/errors.jsonl`。
Sentry 启用时同时上报。
