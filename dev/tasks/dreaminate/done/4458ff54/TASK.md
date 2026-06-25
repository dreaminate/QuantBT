---
uuid: 4458ff54dabe40fe98b45e60491790bb
title: Spine 接进生产 promote 路径——overfit gate DSR 一致性核（漂移→降级 insufficient）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: math-spine
source: goal
source_ref: GOAL §6（监控/执行触发器称数学依据缺 ConsistencyCheck→拒）+ §8 + 决策 D-MATH-SPINE + 依赖 11b0a3ab
depends_on: [11b0a3abca76427597899e3c2f7814e6]
---

# Spine 接进生产 promote 路径——overfit gate DSR 一致性核

## Scope [必填]
把 `verify_dsr_consistency()` 接进信任层生产门 `eval/overfit_gate.run_overfit_gate`（promote 必经）：gate 算红绿时核 DSR 实现↔定义一致（memoized）。**做**：DSR 漂移/binding 过期（脊柱门拒）→ gate 降级到 `insufficient_evidence`（复用既有非 promote sink）、记 `spine_consistency`、诚实标 math-inconsistency。**不做**：绑 PBO/bootstrap（下一切片）；不改 DSR/gate 既有裁决逻辑（DSR 一致时 color 不变）。

## 上下文 / 动机 [按需]
DSR 已绑脊柱（11b0a3ab）但只孤立可证。本切片让脊柱**真正治理生产**：`run_overfit_gate` 的红绿全建在 DSR 上，若 DSR 漂离定义则「证据充分」是建在坏估计器上的假绿灯。GOAL §6「守门器称数学依据缺一致性→拒」。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/eval/overfit_gate.py` | `GateVerdict` | +`spine_consistency` 字段（默认 None）|
| `app/backend/app/eval/overfit_gate.py` | 新 `dsr_spine_decision()` | memoized + 懒导入避免 eval↔lineage 环 |
| `app/backend/app/eval/overfit_gate.py` | `run_overfit_gate` | +`check_spine_consistency=True` 参 + drift→降级逻辑（正常路径不变）|

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. DSR 一致（正常）→ 记 spine_consistency promotable=True、color 不变（不破基线）。
2. **命门**：monkeypatch DSR 漂移裁定 → 本会 green 的数据降级到 insufficient_evidence、reason 标「数学一致性失败/不得 promote」。
3. 隔离：先证无漂移时 green，再证漂移是唯一改判因素。
4. 逃生阀 check_spine_consistency=False → 跳过、color 不变（向后兼容）。
5. 脊柱只更严不放水：本就非 green 的噪声不被改成 green。

## 复用 [按需]
`eval/spine_bindings.verify_dsr_consistency`（全链）· `lineage/spine_gate` · 既有 `run_overfit_gate` 裁决逻辑（只扩展）。

## 红线 [按需]
- 诚实：drift→证据无效，绝不静默放行（no silent；假绿灯反噬自身）。
- 不破基线：DSR 一致时 color/numbers/reason 全不变（默认开但正常路径无副作用）。
- 单一身份源：复用脊柱门，不另造一致性判定。

## 非目标 [按需]
- 不绑 PBO/bootstrap（下一切片）。
- 不改 DSR 实现或 gate 三角裁决阈值。

## 收尾结果（done）
- 扩展 `eval/overfit_gate.py`：+`spine_consistency` 字段 + memoized `dsr_spine_decision()` + `check_spine_consistency` 参 + drift→降级；新增 `tests/test_spine_gate_wiring.py`。
- **codex 只读复核 2×P2 处置（均真问题，已修）**：
  - P2-1「生产 staleness 不可达」→ 加 `DSR_PINNED_FINGERPRINT` 已审定指纹常量，生产用 pinned 当 binding 记录 hash、live 当 current → 改 dsr.py 即 live≠pinned → §6 fresh 子句真触发；+ tripwire 测试（pinned==源指纹，dsr.py 一改即硬失败逼显式重核/刷新）。
  - P2-2「DSR 在 spine 核之前被调用，drift 致抛错会先崩 gate」→ spine 核**提到 DSR 调用之前** + try/except：抛错也 fail-closed `insufficient_evidence`（granted=execution_error），不报 DSR 单点数字（NaN）。
- 验证：gate wiring **10 passed**（含 P2 修 4 条：tripwire/pinned-stale 可达/抛错 fail-closed/不报坏数字）；gate+spine 组 **71 passed**；verdict/promote/gate_runner **88 passed**（未破基线）；全量后端套件后台验证（真汇总行见 log）。
- 推进 GOAL §6/§8 + gap #3：脊柱从「孤立可证」→「真正 gate 生产 promote」（DSR 数值漂移 + 源 staleness + 执行抛错三类都在生产门被挡）。接 PBO/bootstrap + 其余数学点为后续。
