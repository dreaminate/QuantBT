# QuantBT · A股 + 加密的机构级量化研究到执行 OS

> Typed Research Canvas · Quant Research Object · 因子工厂 · ML/DL 模型 · 信号契约 ·
> HRP/组合 · Backtest/Paper/Testnet/受限 Binance live · Research Execution Plane —
> 一个仓库一行命令跑通。所有正式产物以开放格式落盘，进入证据、血缘、审批与审计链。

终态 spec：[`dev/GOAL.md`](dev/GOAL.md)（canvas-native / agent-implemented / governance-first 的 Research-to-Execution OS 契约）· 完整**开发 OS** 见 [`dev/`](dev/)（四台：目标/任务/研究/执行 + 决策账本 [`dev/DECISIONS.md`](dev/DECISIONS.md) append-only + 机构级治理脊柱）

---

## 架构总览

终态主链是 `Quant Intent → Typed Canvas → QRO → Research Graph → Governed Compiler → Deterministic Run → Evidence Verdict → Promotion/Approval → Runtime → Monitor/Retire`。用户提出因子/model/signal/strategy 等研究意图，画布将其结构化；研究执行层生成数学定义、候选代码和验证计划，确定性内核、验证器、策略门、审批和账本负责控制与记录。

从数据接入到执行的流水线由**同一套 REST + tool API** 驱动；回测/晋级阶段强制做 **PBO / DSR / Bootstrap** 过拟合体检（证据门）；**A股**最多到 research/backtest/paper（不接券商、不实盘），**加密**可走到 testnet 与受限 Binance live。

整条流程被一条**不可绕过的机构级治理脊柱**贯穿：确定性 DAG 内核（动钱副作用设不可幂等边界，绝不重发单）+ honest-N 一本账 + 多证据三角守门 + 安全门 / 审批门 / 异模型验证官 + typed canvas/graph 命令源——把"零件"接成不可绕过的闸门。设计与决策见 [`dev/`](dev/) 开发 OS。

<p align="center">
  <img src="docs/images/architecture.svg" alt="QuantBT 全流程架构：数据接入 → 特征/因子 → 模型训练 → 信号融合 → 组合优化 → 回测+过拟合体检 → 执行；A股到 Paper、加密到 Binance 实盘" width="760">
</p>

---

## 5 分钟 quickstart（macOS / Linux）

```bash
git clone <repo> quantbt && cd quantbt

# 1. 装依赖
cd app/backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd ../frontend && npm install && cd ../..

# 2. （可选）填 secrets
mkdir -p ~/.quantbt
cp deploy/secrets.yaml.example ~/.quantbt/secrets.yaml && chmod 600 ~/.quantbt/secrets.yaml
# 编辑 ~/.quantbt/secrets.yaml 填 tushare token / LLM key 等

# 3. 启动服务（前端 :5173 后端 :8000）
#    npm run dev 会占用当前终端前台跑前端（后端在后台）；不是后台命令，别等它返回。
npm run dev          # macOS / Linux / Windows 同一条命令

# 4. 另开一个终端 / 直接在浏览器打开（服务起来后）
open http://localhost:5173/   # Linux 用 xdg-open，Windows 用 start
```

> **数据是 token-gated 的，诚实说明**：**加密自带样本即开即用**（仓库内置 `crypto_perp_demo`
> 等 demo run，不配任何 key 也能直接看）。**A股需自配 `TUSHARE_TOKEN`**（拉 A股/港股/美股/
> 指数/基金/债券数据用）——把 token 填进 `~/.quantbt/secrets.yaml` 的 `tushare.token`，或
> `export TUSHARE_TOKEN=你的token`。没配 token 不影响加密链路与所有 demo。

## docker compose 一行命令

```bash
docker compose up -d
# http://127.0.0.1:5173
```

详见 [`docs/installer-guide.md`](docs/installer-guide.md)。

---

## 上线最后一公里（demo→生产：需你提供的凭据 / 真金）

> demo 与加密研究/回测链路**零凭据即开即用**。下面 4 项是 §9 交付总闸里**代码与文档已就绪、只等你插凭据/真金验收**的部分——这几项软件无法替你验（要真账号/真金/真 key），但码路与对抗测试已绿，**插上一跑即真**。

| 要解锁 | 你提供 | 插哪里 | 文档 |
|---|---|---|---|
| A股真数据回测 | `TUSHARE_TOKEN` | `~/.quantbt/secrets.yaml` 的 `tushare.token`，或 `export TUSHARE_TOKEN=` | [secrets-guide](docs/secrets-guide.md) |
| 真 LLM 多轮 Agent | OpenAI / Anthropic / Qwen API key | `secrets.yaml` 对应字段（无 key 自动回退 DevLocalLLM，不假装） | [user-manual](docs/user-manual.md) |
| 加密 testnet 真喂 paper | Binance **testnet** key（名 `binance_testnet`） | `/api/security/keystore`（走 keyring 不入 git；无 key 诚实回退样本回放） | [binance-security-guide §4.5](docs/binance-security-guide.md) |
| 加密小额实盘验证 | Binance **mainnet** key（关提币 + IP 白名单）+ 真金 100 USDT + 一周 | SafeKey wizard → Live Ladder（不可跳级，killswitch 兜底） | [binance-security-guide](docs/binance-security-guide.md) |

> A股**永不实盘**（硬约束）；加密实盘走 backtest→testnet→小额 ladder 不可跳级。详见 [`dev/GOAL.md`](dev/GOAL.md) §5/§9。

---

## 立即看到的产物

- **5 个 demo run** 入仓可在 RunDetail 直接打开：
  - http://localhost:5173/runs/a_share_real_demo （真 Tushare hs300）
  - http://localhost:5173/runs/a_share_ml_demo （合成）
  - http://localhost:5173/runs/crypto_perp_demo （加密永续）
  - http://localhost:5173/runs/quant1-demo
- **30 个内置 alpha_lite 因子** http://localhost:5173/factors
- **研究执行台** 使用真实模型流生成候选研究实现 http://localhost:5173/agent
- **Binance 交易台** http://localhost:5173/trading
- **策略索引（quantpedia 风）** http://localhost:5173/strategies

---

## 三条硬约束（GOAL §M15 / §12 / §M9.3）

1. **`frontend-run-detail/src/pages/RunDetailPage.tsx` 冻结** — 仅排版 / 显示逻辑 / 加字段
2. **A股不接券商** — 禁止 `import vnpy / easytrader / ths_trader` 等
3. **Binance API key keyring 加密 + 启动校验无 withdraw 权限**

---

## 文档

- [`docs/user-manual.md`](docs/user-manual.md) — 功能总览（按 §4 模块）
- [`docs/secrets-guide.md`](docs/secrets-guide.md) — `~/.quantbt/secrets.yaml` 填写指南
- [`docs/installer-guide.md`](docs/installer-guide.md) — 三种安装方式 + 故障定位
- [`docs/binance-security-guide.md`](docs/binance-security-guide.md) — Binance 实盘安全
- [`docs/data-connector-guide.md`](docs/data-connector-guide.md) — DIY 数据源
- [`docs/strategy-dev-guide.md`](docs/strategy-dev-guide.md) — 写一个策略

---

## 仓库形态

- `app/backend/` — FastAPI 业务模块（connectors/factor_factory/labels/models/signals/portfolio/execution/risk/security/eval/experiments/dag/agent/observability/paper/monitor）+ **机构级治理脊柱**（lineage/hypothesis/approval/verification/security.gate — 内核 + 一本账 + 三角 gate + 安全门 + 审批门 + 验证官）
- `app/frontend/` — Vite + React + Claude Code 风 cc-* shell + workshop/desk/typed-canvas 方向 + RunDetailPage（jq-* 冻结）；画布/对话/IDE/报告在终态只做 canonical Research Graph 的投影和命令入口
- `dev/` — **开发 OS**（四台：目标/任务/研究/执行 + 决策本/铁律/问题登记 ISSUES/研究溯源 TRACE + 自检 `validate_dev.py`），见 [`dev/README.md`](dev/README.md)
- `docs/` — 产品手册 + 运行时数据（glossary/model_cards 由 app 运行时读）+ 设计规格 plans/ + 发布说明
- `examples/` — 3 个端到端 demo（A股合成 / 加密永续 / Tushare 真数据）
- `data/artifacts/experiments/{run_id}/` — 标准 run 目录（run.json / portfolio.csv / trades.csv / metrics.json / report.md）
- `deploy/` — docker / PyInstaller spec / secrets 模板
- `.github/workflows/` — CI 自动打 PyInstaller 包

## 跑测试

```bash
python -m pytest app/backend/tests -q
# 1357 passed / 13 skipped（实跑 2026-06-24；数随套件增长，以实跑为准）
```
