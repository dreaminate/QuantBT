# 策略开发指南

> 从「我有个想法」到「跑出一份 report」的实操路径。

---

## 0. QuantBT 的策略形态

QuantBT 把策略拆成 **可独立组合的 7 层**：

```
StrategyGoal → Universe → Features (factor_factory) → Labels → Model
            → Signals → Portfolio → Execution → Eval / Attribution
```

每一层都可以单独配置或替换；多数策略只改 3-4 层就够。

---

## 1. 5 分钟跑 demo（学习路径）

```bash
python examples/run_a_share_ml_demo.py
python examples/run_crypto_perp_demo.py
```

两份产物在 `data/artifacts/experiments/{a_share_ml_demo,crypto_perp_demo}/`。

打开 demo 脚本 = 看 QuantBT 的标准用法。下面逐步拆解。

---

## 2. 定义 StrategyGoal

```python
from datetime import date
from app.strategy_goal import (
    StrategyGoal, Constraints, EquityCostModel, EvaluationWindow,
)

goal = StrategyGoal(
    name="A股 周频 选股 Top 10%",
    asset_class="equity_cn",
    objective="info_ratio",
    horizon="weekly",
    benchmark="000300.SH",
    constraints=Constraints(
        single_pos_max=0.05,        # 单标的 5%
        turnover_max=0.30,          # 30% 日换手
        max_dd=0.20,                # 回撤 20%
        leverage_max=1.0,           # A股强制 1.0
    ),
    cost_model=EquityCostModel(
        commission_bps=2.5,
        stamp_duty_bps=10,
        slippage_bps=5,
    ),
    evaluation_window=EvaluationWindow(
        backtest_start=date(2020, 1, 1),
        backtest_end=date(2025, 12, 31),
        walk_forward_train_days=252,
        walk_forward_test_days=63,
        embargo_days=5,
    ),
)
```

**一致性硬约束**（StrategyGoal 自动校验）：
- A股 拒绝 `live_crypto` 模式
- A股 `leverage_max` 必须为 1.0
- `crypto_perp` 必须用 `CryptoPerpCostModel`（带 funding_rate_apply=True）

---

## 3. 算因子（用内置 alpha_lite 或自己写表达式）

### 用内置

```python
from app.factor_factory import alpha_lite_specs, evaluate_on_panel

formula = {s.factor_id: s.formula for s in alpha_lite_specs()}["alpha_mom_20d"]
out = evaluate_on_panel(panel, formula, alias="mom20")
```

### 自己写表达式

```python
# rank(ts_pct_change(close, 20))  -- 截面动量排名
out = evaluate_on_panel(panel, "rank(ts_pct_change(close, 20))", alias="rk_mom")
```

44 个算子：
- 时序：`ts_lag` `ts_delta` `ts_pct_change` `ts_sum` `ts_mean` `ts_std` `ts_min` `ts_max` `ts_median` `ts_argmax` `ts_argmin` `ts_rank` `ts_zscore` `ts_skew` `ts_corr` `ts_cov` `ts_decay_linear` `ts_ema`
- 横截面：`cs_rank` (`rank`) / `cs_zscore` (`zscore`) / `cs_demean` / `cs_winsorize` / `cs_quantile`
- 一元：`log` `log1p` `exp` `abs` `sign` `neg` `sqrt` `pow` `clip`
- 二元：`add` `sub` `mul` `div` `max` `min`

**重要约束**：横截面算子（`cs_*` / `rank` / `zscore`）**必须在最外层**。
原因：polars 不支持双层 `.over()` 链；evaluator 检测到 root cs_op 时自动两阶段执行。

### IC 计算

```python
from app.factor_factory import attach_forward_returns, compute_ic_report, compute_ic_decay

panel = attach_forward_returns(panel, [1, 5, 10, 20])
panel = panel.join(out, on=["ts", "symbol"], how="left")
report = compute_ic_report(panel, factor_col="mom20", horizon=5)
print(f"IC={report.ic_mean:.4f} RankIC={report.rank_ic_mean:.4f} IR={report.ic_ir:.4f}")

# 衰减曲线
decay = compute_ic_decay(panel, factor_col="mom20", horizons=[1, 3, 5, 10, 20])
for r in decay:
    print(f"h={r.horizon}: IC={r.ic_mean:.4f}")
```

---

## 4. 标签

| 任务 | 用什么 |
|---|---|
| 回归 forward return | `raw_return_label(panel, horizon=5)` |
| 截面排名（learning-to-rank） | `xs_rank_label(panel, horizon=5)` |
| 超额收益 | `excess_return_label(panel, benchmark_panel, horizon=5)` |
| 三分类（多/空/超时） | `triple_barrier_label(panel, take_profit_sigma=2, stop_loss_sigma=2, max_holding_days=10)` |
| 波动率调整收益 | `vol_adjusted_return_label(panel, horizon=1, vol_window=20)` |
| Meta-labeling（方向 + 是否下单） | `meta_label(triple_barrier_df, base_direction_df)` |

---

## 5. 模型训练（强制 Purged k-fold + Embargo）

```python
from app.models import ModelSpec, train_model

spec = ModelSpec(
    task="regression",            # classification / regression / lambdarank
    model="lgbm",                 # lgbm / sklearn_logreg / sklearn_rf
    feature_cols=["mom20", "vol20", "amount_z"],
    label_col="label",
    cv_scheme="purged_kfold",     # purged_kfold / walk_forward
    n_splits=5,
    embargo_pct=0.02,
)
result = train_model(spec, df)
print(result.oos_metrics)         # {"mse":..., "r2":..., "sharpe_proxy":...}
print(result.feature_importance)
```

**绝不允许**：裸 `train_test_split`。

---

## 6. 信号融合

```python
from app.signals import fuse_signals, apply_regime_gating, confidence_threshold_filter

# 模型预测 score → direction/magnitude/confidence 四元组
signals = fuse_signals(predictions_pl, score_col="score", long_only=True)
# regime gating：bear 时禁止 long
signals = apply_regime_gating(signals, regimes_pl)
# 低置信度直接 flat
signals = confidence_threshold_filter(signals, min_confidence=0.55)
```

---

## 7. 组合优化

```python
from app.portfolio import optimize_portfolio, PortfolioConstraints

res = optimize_portfolio(
    optimizer="hrp",                  # equal_weight / mean_variance / risk_parity / hrp
    expected_returns=mu,              # pd.Series, None for hrp/equal/rp
    covariance=cov,                   # pd.DataFrame
    constraints=PortfolioConstraints(
        single_pos_max=0.10,
        sector_cap=0.30,
        sector_map={"AAA": "tech", ...},
        pair_corr_cap=0.85,           # 强相关二选一
        leverage_max=1.0,
        short_allowed=False,
    ),
)
print(res.weights)
```

---

## 8. 回测

```python
from app.execution import BacktestVenue, BacktestCostModel, Order

cost = BacktestCostModel(commission_bps=2.5, slippage_bps=5, stamp_duty_bps=10)
venue = BacktestVenue(prices=panel, cost_model=cost, cash=1_000_000)

# 每日 generate orders
for ts in trading_days:
    for sym, w in target_weights[ts].items():
        venue.place_order(Order(venue="backtest", symbol=sym, side="buy", quantity=qty, order_type="market"))
    fills = venue.step()
    # 记录 portfolio.csv 行
```

或用 `examples/run_a_share_ml_demo.py::_run_backtest` 作为模板。

---

## 9. 评估（GOAL §6.1 强制三项）

```python
from app.eval import (
    cscv_pbo, deflated_sharpe_ratio, bootstrap_sharpe_ci, brinson_attribution
)

# PBO via CSCV（returns_matrix shape T×N，N 个候选策略）
pbo = cscv_pbo(returns_matrix, s_blocks=8, max_combinations=200)

# Deflated Sharpe Ratio
dsr = deflated_sharpe_ratio(daily_returns, n_trials=30)

# Bootstrap CI
ci = bootstrap_sharpe_ci(daily_returns, n_boot=1000)

# A股策略必须：Brinson 三层归因
brinson = brinson_attribution(portfolio_panel, benchmark_panel, group_col="sector")
print(brinson.total)  # {"allocation":..., "selection":..., "interaction":..., "active_return":...}
```

PBO > 0.5 → 策略大概率是过拟合。DSR < 0.5 → 你的 Sharpe 高大概率是侥幸。

---

## 10. 注册到 ExperimentStore + 标准 run 目录

```python
from app.experiments import ExperimentStore, RunStore
from examples._e2e_common import write_run_artifacts

exp_store = ExperimentStore(Path("data/experiments"))
run_store = RunStore(Path("data/experiments"))

exp = exp_store.create_experiment(name="hs300_lgbm_v3", asset_class="equity_cn")
run = run_store.create_run(experiment_id=exp.experiment_id, inputs={"factor_set": "v3"})
# ... 跑回测 ...
run_store.update_run(run.run_id, metrics={"sharpe": 1.5}, finished=True, status="succeeded")

write_run_artifacts(
    run_id=run.run_id,
    run_meta={...},
    portfolio=portfolio_df,
    trades=trades_df,
    metrics=metrics,
    report_markdown=report_md,
)
```

---

## 11. 研究执行台生成候选策略

进 `/agent` 研究执行台，一句话：「我想做 A股 周频 选股，回撤 20%」。
系统会调 `strategy_goal.create` 工具生成 StrategyGoal 候选，然后串联 factor → label → model → backtest。

支持代码复刻：粘 vnpy / backtrader / pandas / qlib 策略代码，系统用 AST 改写到
QuantBT predict 模板。改写结果是候选实现，必须跑完评估和审批链后才能晋级。

---

## 12. 上线检查清单

| 项 | 检查 |
|---|---|
| 因子层 | IC / Rank-IC / IC-IR / IC 衰减都跑了？ |
| 模型层 | Purged k-fold + Embargo 用了？OOS Sharpe 与 train 偏离 < 50%？ |
| 评估层 | PBO ≤ 0.5？DSR ≥ 0.5？Bootstrap CI 不穿 0？ |
| A股 | Brinson 三层（市值×行业×风格）都做了？ |
| 加密 | 资金费率 / maker-taker / 借贷利率都计了？ |
| 实盘 | testnet 跑通至少一周？mainnet 切换走过二次确认？ |
| 风控 | 三档（单笔 / 日内笔数 / 日内亏损）都设了？Kill Switch 测试过？ |
