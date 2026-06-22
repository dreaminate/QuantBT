---
uuid: f6bb5e8ea620412fa0c3e5a48011b74b
title: DS-1 run_id 脊梁——agent backtest 接真引擎写 RUN_ROOT + run_id 贯穿（Fork3=A）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: agent-backend
source: developer-claude
source_ref: 2026-06-22 D-DELIVERY-SLICE 脊梁 · audit blocker #3 + 统一 run 契约
depends_on: []
---

# DS-1 run_id 脊梁

## Scope [必填]
agent `business_tools._backtest_run` 无 run_id 分支**接真执行引擎**：从 StrategyGoal 合成最小可跑策略 → 复用 IDE promote 落盘契约（`promote.py:53-129` 写 `RUN_ROOT/<id>/run.json + portfolio.csv` 并跑 overfit gate 注入 dsr/pbo/bootstrap）→ 产**真 run_id**。**消灭两套并行 run 注册表**（agent 写 `data/experiments/runs.jsonl` vs 裁决读 `RUN_ROOT/<id>/run.json`，Fork3=A 统一到 RUN_ROOT）。这是切片脊梁：真 run_id 一通，DS-3/DS-4 接缝大半自动合拢。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/agent/business_tools.py | 282-315 _backtest_run 无 run_id 分支 | 接真引擎落 RUN_ROOT（非 RunStore 占位） |
| app/backend/app/ide/promote.py | 53-129 落盘契约 + overfit gate 注入 | 复用，勿另造 |
| app/backend/app/run_verdict.py | project_verdict/project_overfit | run_id 下游消费验证 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. agent backtest.run(goal) → 产 `RUN_ROOT/<id>/run.json + portfolio.csv`（真净值序列，非 status=running 占位）；run_id 可被 `run_verdict.project_verdict/project_overfit` 真消费（非 mock）。断开真引擎接线 → 测试红。
2. 同 goal 重跑 → config_hash 一致、honest-N 不重刷（复用 lineage.ids 单一源）。

## 验收一句话 [必填]
agent 对话路径产真 run（RUN_ROOT 契约、真净值）、run_id 可贯穿裁决/paper；消灭两套注册表；不破基线。

## 实现设计（grounded · 2026-06-22 build 前锁定）
**架构（复用、零新引擎）**：QuantBT 无后端「spec→equity_curve」引擎，equity_curve 永远由沙箱用户 Python 产。故 DS-1 链路 = StrategyGoal → **合成最小策略 Python** → `ide.sandbox.run_user_strategy(code, work_root, extra_env={DATA_DIR})`（沙箱跑出 `emit_result(equity_curve)`）→ `ide.promote.promote_ide_run(result, strategy_code, ledger)` 落 `RUN_ROOT/<id>/run.json+portfolio.csv` + 跑三角 gate → 真 run_id。复用沙箱引擎 + promote 契约两者；`_backtest_run` 无 run_id 分支从「RunStore 占位」改为此链（Fork3=A 统一到 RUN_ROOT，消灭 runs.jsonl 那套）。
**合成器（接 Fork1=C）**：有 LLM（key/Hermes custom provider）→ agent 真生成策略 Python（真·能造对话生成）；无 LLM → 按市场套**模板策略**（确定性兜底，如 20 日动量）。两条都产读 `DATA_DIR` 样本的可跑 Python。
**数据（用户选 C：两份都捆，gitignore 例外样本）**：① BTC 日频经 `binance_vision_pull`（公开·逐日 zip·零 token）；② 沪深300 经 Tushare（`TUSHARE_TOKEN` 环境变量 / 内置默认 token 兜底）。落 `DATA_ROOT=data/`，沙箱经 `extra_env={DATA_DIR}` 读。**现有 demo（experiments/*_demo）是 run 输出非原始行情、喂不动回测——已核实，故须新捆原始 OHLCV**。
**build 步骤**：(1) 拉+捆 BTC Vision + 沪深300 Tushare 样本（网络重，~365 BTC zip + Tushare API）；(2) 写 per-market 策略合成器（模板 + LLM 路径）；(3) `_backtest_run` 无 run_id 分支接 synth→sandbox→promote；(4) 对抗测试（agent backtest 产真 RUN_ROOT run + run_id 可被 project_verdict 消费；断真引擎接线→红；同 goal config_hash 一致不重刷 N）+ 全量。
**诚实残余/限界**：样本数据是「演示/起步样本」非全市场；真用户应配自己数据源（onboarding 引导）。

## 完成记录（2026-06-22 · 实跑为准）
**建了什么**（复用单一源、零新引擎）：
- `app/backend/app/agent/sample_data.py`（新）：真行情样本定位 + 捆绑器。BTC 复用 binance_vision_pull 下载/解析【无状态原语】并发拉（绕开其 reload-merge 预存 bug）；沪深300 复用 TushareConnector.index_daily（需 TUSHARE_TOKEN）。落 `data/samples/<market>/`（未被 .gitignore、可入库）。
- `app/backend/app/agent/strategy_synth.py`（新）：per-market 确定性动量模板（**stdlib csv 读样本**——沙箱锁 socket/asyncio 致 polars 读路径走 fsspec 被拦）+ LLM seam（不含 emit_result/DATA_DIR 的输出判废兜底模板，防假绿灯）。同 goal+market+lookback → 同码 → 同 config_hash。
- `app/backend/app/agent/business_tools.py`（扩展）：`_backtest_run` 无 run_id 分支从 RunStore 占位改 `_synth_and_promote`：合成→`ide.sandbox.run_user_strategy(DATA_DIR)`→`ide.promote.promote_ide_run` 落 RUN_ROOT + 三角 gate → 真 run_id；register_business_tools 加注入 ledger/returns_store/data_root/llm_client（全默认值、扩展不替换）。
- `app/backend/app/main.py`（扩展）：注入 LEDGER/RETURNS_STORE/DATA_ROOT（llm_client 暂不注入 → 走模板兜底，DS-2 注入真 LLM）。
- `app/backend/tests/test_ds1_run_id_spine.py`（新·7 测）：真 run 被 project_verdict/project_overfit 消费 / config_hash 稳 honest-N 不重刷 / 断引擎诚实失败 / 缺样本诚实失败 / 合成确定性+无前视 / LLM seam 废输出兜底+合格采纳。

**验证（实跑）**：DS-1 7 测全绿；变异（伪造 equity_curve 分支）→ break_engine 测试转红（守卫 load-bearing，§2 种坏门必抓）；全量 **1270 passed / 13 skipped**（基线 1263 完整 + 7 新，0 破坏）。真回测真实数字：sharpe 1.18 / 总收益 81% / 回撤 -24% / DSR 0.956 / verdict=concern（无权威裁决→不假绿灯）。

**接缝**：run_id 落 RUN_ROOT 单一注册表，DS-3（裁决贯穿）/DS-4（paper register）可直接消费。

**诚实残余**（非半成品、明确边界）：
1. **沪深300 真样本未捆**：stocks_cn 码路（合成器模板 + 缺样本诚实失败）已建并测，但真 cn 数据需 TUSHARE_TOKEN（env 未配、内置默认 token=0、绝不伪造 §3）。一条命令补：设 TUSHARE_TOKEN 后跑 `sample_data.bundle_hs300_daily(start,end)`。
2. **BTC 样本 516/730 点**：Binance Vision 免费日 K 源有日期空洞（214 天缺），516 真点足够回测+gate；非全市场（起步样本限界）。
3. **LLM 合成路**：seam 建并单测（废输出兜底），但 _backtest_run 暂不注入真 LLM（走确定性模板）——真 LLM 注入是 DS-2「造站接真」职责（卡本身的设计分工）。
4. **发现 pre-existing bug**（非本卡引入、未改）：`binance_vision_pull.pull_vision_klines_date_range` 多日同年 reload-merge 时 `try_parse_dates=True` 把 timestamp 读成 Datetime 与新 String 列 concat 报 SchemaError（已绕开、未碰该函数）。建议后续 mint 卡修。
