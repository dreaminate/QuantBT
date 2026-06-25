---
uuid: 554cdcf251804a19bfb81dbbebbdf5f1
title: 监控绩效轴真闭环——4 个 drift 检测器接 run_weekly_monitor_pass + per-factor IC 真源 + 观测落盘（审计残余）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: monitor
source: audit-finding
source_ref: 方法学消费侧 correctness 审计（workflow wm8x329vn）#3 发现（lev 7）+ production.py:18-26 诚实残余；done 卡 698a3c60（driver 接线）的下游前置
depends_on: [698a3c60c1af4ea8bc0b038acedcd91b]
---

# 监控绩效轴真闭环——drift 检测器接生产 + IC 真源 + 观测落盘

## Scope [必填]
done 卡 698a3c60 补了 driver（scheduler 真 tick、weekly op 真跑），但绩效轴**在真数据上仍无法退役**——三层残余：
① **4 个统计 drift 检测器零生产调用方**（审计 #3）：`rolling_psr_drift`/`cusum_drift`/`page_hinkley_drift`/
   `population_stability_index`（monitor/drift.py）在生产从未被求值；`monitor_tick` 已接 `perf_drift` 形参
   （closure.py:70/95-111 production-ready），但唯一生产入口 `run_weekly_monitor_pass`（production.py:88-94）调 monitor_tick
   时**只传 drift_pct（成本轴），从不传 perf_drift（绩效轴）** → 绩效轴主告警三件套在生产从未跑。
② **生产无真实周期 per-factor IC 源**（production.py:18-22）：`Factor.ic_summary` 仅注册期写一次，无人按周重算
   → `observation` 恒 None；须建周度 IC 重算管道（`ic_provider` 钩子已留）。
③ **观测不落盘跨重启清空**（production.py:25-26）：`LifecycleManager._observations` 内存级 → WARNING→RETIRED 需连续
   2 周负观测，进程重启则历史清空、退役不触发；须持久化。

## 治理（命门·范畴红线）[必填]
- **M-AUTHORITY=A1 范畴守恒**：drift 检测器喂 `monitor_tick` 的只能是**绩效/成本漂移轴**（IC/PSR/CUSUM/PH/drift_pct），
  **绝不**传 gate verdict/PBO/DSR/overfit（晋级期过拟合闸接成运营退役触发器=范畴错误，违 GOAL §10/§12 + closure.py:14-16 + DECISIONS M-AUTHORITY=A1）。
- **rolling-PSR 不变量**：breach ⇔ PSR(SR*;n,γ3,γ4) < psr_floor，sr_benchmark 固定、**绝不暴露 n_trials**（否则退化为
  DSR=晋级闸）。CUSUM/PH：μ0/σ0 取晋级期 OOS 冻结基准、仅看下降侧、绝不用监控窗自身均值（温水煮青蛙不变量）。
- **方法学松紧=用户**：psr_floor/CUSUM h/PH δ,λ / 确证模式 等阈值是用户方法学决策——摆代价 + 默认值，不替拍。
- **不假绿灯**：无真 IC 源时 observation=None，绝不把注册期陈旧 IC 伪装成「本周观测」。

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 断接线：run_weekly_monitor_pass 不传 perf_drift → 绩效退役不触发（证 perf 轴接线真生效，非套套逻辑）。
2. 范畴红线：监控路径绝不能把任何 gate/pbo/dsr 字段喂进 monitor_tick（机器钉死断言）。
3. rolling-PSR 不暴露 n_trials（种「传 n_trials→退化 DSR」→ 红）。
4. 观测落盘：写 2 周负观测 → 模拟重启（重载 manager）→ 第 2 周仍触发 RETIRED（证持久化真生效）。

## 验收一句话 [必填]
绩效轴 drift 检测器（rolling-PSR/CUSUM/PH）真接 run_weekly_monitor_pass→monitor_tick 的 perf_drift + per-factor IC 真源 + 观测落盘，
使监控在真数据上能真退役（范畴红线守 A1、阈值=用户方法学、不假绿灯），不破基线。

## 完成记录（2026-06-26 · deep-opus 任务线 · 隔离 worktree·基于 origin/main 前五波已 land）

### GOAL-FIRST 契约坐实（动手前先读）
- **GOAL §12 执行边界·Live 监控**（行 1789-1809）：`rolling-PSR / CUSUM / Page-Hinkley / PSI / performance primary alert /
  feature drift root-cause alert`；可证伪验收「feature drift 单独触发交易动作且无绩效/风险证据 → 拒」。
- **GOAL §10 方法学与验证**（行 1605）：「单策略 live 监控搬用 DSR 做主告警 → 拒」；松紧档=用户（strict/standard/loose/...，摆代价记 tradeoffs）。
- **DECISIONS M-AUTHORITY=A1**：监控→降级/退役走 factor lifecycle（registry.LifecycleState）为权威、单发 PROV；
  退役动作矩阵只接绩效/成本漂移信号（IC/drift_pct），绝不接 gate verdict（DSR/PBO 晋级闸）。
- **finding drift-detectors.md**：rolling-PSR=主告警、CUSUM/PH=确证（行 68）；μ0/σ0 须晋级期 OOS 冻结基准、跨重启持久化是
  点名的后续残余（行 64/76）——即本卡。

### 实现（扩展不替换 · 复用不另造 · 领地内）
| 文件 | 改动 | 残余 |
|---|---|---|
| `app/backend/app/monitor/production.py` | `run_weekly_monitor_pass` 加 `perf_provider` 形参 + 把 `perf_drift` 接进 `monitor_tick`（仅有真源才喂）；新增 `build_returns_perf_drift_provider`（rolling-PSR 主告警 + CUSUM/PH 确证·`require_confirmation` 旋钮）、`build_ic_provider`（复用 `factor_factory.ic.compute_ic_report`·不另造公式）+ `PerfDriftProvider/ReturnsSource/FrozenBaselineSource` 契约 | ①② |
| `app/backend/app/factor_factory/lifecycle.py` | 新增 `ObservationStore` Protocol + `JsonlObservationStore`（append-only JSONL，复用 registry 的 JSON 落盘范式）；`LifecycleManager.__init__` 加 `store=` keyword + env `QUANTBT_LIFECYCLE_OBS_STORE` 兜底（默认空=纯内存·逐位不破基线）+ 构造时从落盘重建历史；`record_observation` 同步落盘 | ③ |
| `app/backend/app/monitor/__init__.py` | 导出新符号（additive） | — |
| `app/backend/tests/test_monitor_perf_closure.py` | 新建 18 条对抗测试 | — |

- **绝不碰**：main.py（生产单例 `FACTOR_LIFECYCLE = LifecycleManager(FACTOR_REGISTRY)` 不带 store → 落盘改走 env 接通，
  零改 main.py）、eval/overfit_gate（晋级闸范畴红线）、closure.py / drift.py（`perf_drift` 形参 + axis 类型守门是前波§5切片既有，本卡只复用未改）、其他在飞线。

### 接线设计（残余①·为何非套套）
- `perf_provider: (factor_id, version) → PerfDriftSignal | None` 是 4 个绩效轴检测器进生产的**唯一接缝**，与既有 `ic_provider` 同诚实范式：
  无真实周期收益序列 → None（不伪造）。`build_returns_perf_drift_provider` 让三件套在生产真被求值：rolling-PSR=主告警
  （只接固定 sr_benchmark、签名不暴露 n_trials），CUSUM/PH=确证（须 `baseline_source` 提供晋级期 OOS 冻结 μ0/σ0；无则退化纯 PSR）。
- `require_confirmation`（默认 False=PSR 主告警单独触发，对齐 GOAL §12「performance primary alert」+ finding「rolling-PSR 才是主告警」）
  =用户方法学旋钮：True 时 breach 须 PSR 越阈 **且** CUSUM/PH 任一确证（更特异、误报更少）——摆代价不替拍。

### 真测试汇总行（scoped·必带 timeout·凭真汇总行判绿）
- **新对抗文件 `tests/test_monitor_perf_closure.py`：18 passed**（0.77s）。
- **scoped 回归（monitor+lifecycle+factor 全套）：138 passed / 0 failed**（`test_monitor_perf_closure + test_monitor_closure +
  test_drift_detectors + test_monitor_driver + test_cost_drift + test_factor_lifecycle_metrics + test_lifecycle_decay_advisory +
  test_alpha_lite_and_lifecycle + test_factor_desk_f2`，2.84s）。另跑 factor/methodology/model/eval/verdict 7 文件 **182 passed**。
- **基线 collect：2138 → 2156（净 +18，零删除既有测试）**；既有 `test_weekly_pass_passes_no_gate_verdict_to_monitor_tick`
  白名单测试**保持不破**（perf_drift 仅有真源时才入参，无 provider 时 kwargs 不含 perf_drift）。

### 对抗测试（种坏门必抓·MUT 定点反向 edit 验证·绝不 git checkout）
- **MUT-A 断接线**（perf_drift 永不传 → `if ... and False`）：4 测试转红——`test_perf_provider_wired_drives_retire_single_prov`
  / `test_perf_drift_passed_to_tick_only_when_provider_present` / `test_feature_axis_psi_cannot_enter_via_perf_provider`
  （证 PSI 类型守门是经新接缝到达的）/ `test_observation_persists_across_restart_triggers_retire` → Edit 还原。
- **MUT-B 不落盘**（`record_observation` 跳过 `store.append` → `if ... and False`）：`test_observation_persists_across_restart_triggers_retire`
  + `test_env_var_enables_persistence_without_explicit_store` 转红（证持久化 load-bearing，无落盘则跨重启退役不触发的 bug 复发）→ Edit 还原。
- 范畴红线机器钉死：`test_weekly_pass_with_perf_provider_never_feeds_gate_verdict`（运行时 kwargs ⊆ {observation,drift_pct,drift_threshold,perf_drift}、
  无 verdict/pbo/dsr/gate/overfit）+ `test_feature_axis_psi_cannot_enter_via_perf_provider`（PSI 经 perf_provider → TypeError）。
- n_trials：`test_rolling_psr_runtime_rejects_n_trials_kwarg`（运行期传 n_trials/var_sr_hat → TypeError）+ builder 签名无 DSR 通缩参数。

### 红线合规（逐条）
- **M-AUTHORITY=A1 范畴守恒** ✓：喂 monitor_tick 的只有 observation（周期 IC）/drift_pct（成本）/perf_drift（绩效轴 PerfDriftSignal,axis="performance"）；
  机器钉死无 gate/pbo/dsr/overfit；特征轴 PSI 经类型层（axis!="performance"→TypeError）拒，绝不退役。
- **rolling-PSR 不暴露 n_trials** ✓：检测器 + builder 签名均无 n_trials/var_sr_hat（运行期传即 TypeError）；用 PSR(固定 sr_benchmark)，非 DSR。
- **温水煮青蛙不变量** ✓：CUSUM/PH 走 `baseline_source` 提供的晋级期 OOS 冻结 μ0/σ0，绝不用监控窗自身均值（复用 drift.py 既有冻结基准检测器）。
- **不假绿灯** ✓：无真实周期收益/面板源 → perf_provider/ic_provider 返 None → 不喂、不伪造；observation 恒 None 不拿注册期陈旧 IC 充数。
- **扩展不替换·不破基线** ✓：全 additive（新形参默认 None / 新类 / 新函数 / 新 env 默认关）；既有 85→不破，collect 2138→2156 净 +18。
- **复用不另造** ✓：IC 重算复用 `compute_ic_report`（含 Newey-West HAC t 诚实显著性口径）、漂移复用 drift.py 四检测器、落盘复用 registry 的 JSON 范式。
- **绝不碰 main.py / eval / overfit_gate / 其他在飞线** ✓：落盘经 env 兜底接通生产单例（零改 main.py）。

### 拍板项命中（阈值=用户·已决不问）
- psr_floor / CUSUM h,k / PH δ,λ / `require_confirmation` 确证模式 = 用户方法学旋钮：全部「摆代价 + 给文献默认（psr_floor=0.90、h≈5σ 等）」、
  不替拍（默认 require_confirmation=False 对齐 GOAL §12「performance primary alert」）。**无新岔路**（M-AUTHORITY=A1 范畴、rolling-PSR≠DSR
  均为已决决策，照守；落盘默认关=不替用户拍「是否落盘 + 落哪」，与 698a3c60 的 QUANTBT_MONITOR_DRIVER env 同范式）。

### 诚实残余（🟡 未验证 ≠ ✅ 已验证）
- **生产真实数据源仍是残余（领地外·非本卡可填）**：`perf_provider`/`ic_provider` 的 `returns_source`/`baseline_source`/`panel_source`
  在生产仍无真实接入——真实周期 per-factor 收益序列、晋级期 OOS 冻结基准、周度因子面板（factor_value×forward_return）依赖 data/factor
  评估管道（属其他在飞线/领地外）。本卡交付的是**生产可用的接线 + 重算/落盘机制 + 诚实 None 兜底**，数据源接入宜后续 mint 卡。
  故生产默认仍只成本轴可动；绩效轴一旦真源就绪即接（机制全绿、零改本模块）。
- **观测落盘默认关**：生产启用须运维置 `QUANTBT_LIFECYCLE_OBS_STORE`（默认纯内存=不破基线）。事件日志（PROV）跨重启持久化未做
  （registry 状态 + 观测已持久；事件可由重启后 evaluate 重新单发）——非本卡验收项，留意。
- **per-factor 成本归因仍缺**：`compute_weekly_cost_drift` 产单一全局 drift_pct（698a3c60 既陈）；与本卡正交，未改。
- **CI 全量 + ruff 未在本线跑**：本线只跑 scoped（worktree 无 ruff CLI）；全量回归 + land 由中心负责。

### 交付边界（本线只动 monitor/ + factor lifecycle 观测 + 本 done 卡）
- 未碰 state/log/board/DEVMAP/GOAL/pool/其他卡目录/main.py/eval/overfit_gate；未跑 /skill；只跑 scoped 不跑全量。
- commit + push `wave5/drift-monitor`（省略 co-author）；中心负责整合 + 全量 + land main。
