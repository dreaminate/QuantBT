---
uuid: 11b0a3abca76427597899e3c2f7814e6
title: Spine 全链贯穿第一段——DSR 估计器经 Mathematical Spine 真实绑定 + 漂移对账门
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: math-spine
source: goal
source_ref: GOAL §6/§9（数学到代码/测试/验证绑定）+ 决策 D-MATH-SPINE + finding spine-consistency-gate/01 + 依赖 a00b3956
depends_on: [a00b39560f5b4fb7b8945141cc307724]
---

# Spine 全链贯穿第一段——DSR 估计器经 Mathematical Spine 真实绑定

## Scope [必填]
把信任层核心估计器 Deflated Sharpe Ratio（`eval/dsr.py`）经脊柱真实绑定：DSR MathematicalArtifact（proof_backed）→ TheoryImplementationBinding（**真源码 `inspect.getsource` 指纹**）→ 数值 ConsistencyCheck（impl vs **独立 scipy oracle** 对账）→ `evaluate_promotion` 门。**做**：证明 DSR 漂离定义→对账 fail→门拒（命门在真代码上工作）+ 改 dsr.py 任一环→指纹变→staleness 门拒 + 可复用 binder 范式。**不做**：把 `verify_dsr_consistency()` 接进生产 promote 路径（run_verdict/overfit_gate/ide.promote）——下一切片。

## 上下文 / 动机 [按需]
gap #3 命门门核心（a00b3956）已建但未接任何真数学点。本切片选 DSR 为第一个真实绑定：DSR 是 promote/信任层的 gate 依据，若实现漂移则整层失真——绑它最 correctness-critical。理论先行 finding `spine-consistency-gate/01`。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/eval/dsr.py` | `deflated_sharpe_ratio` + helper 链 | 被绑定的真实现（只 import 不改）|
| `app/backend/app/lineage/spine_binder.py` | 新增 | 可复用：`code_fingerprint`（真源码指纹）+ `numerical_consistency_check`（impl vs 独立 oracle）|
| `app/backend/app/eval/spine_bindings.py` | 新增 | DSR artifact + scipy oracle + `verify_dsr_consistency()` 全链 |
| `app/backend/app/lineage/__init__.py` | 导出块 | 扩展导出 binder |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 独立 oracle 忠实重算：oracle（scipy 矩）vs 真 impl 在 5 fixtures ≤1e-6。
2. 正确 impl → 一致性 pass + 门 promotable=proof_backed（pit-bound + consistency-pass matched）。
3. **命门**：种漂移 impl（丢 E[max] 通缩 + denom）→ oracle 对账 fail → 门拒、granted=challenged。
4. 真源码指纹：`dsr_code_fingerprint()` == `content_hash(inspect.getsource 链)`；稳定；== binding.code_content_hash。
5. 整条链入指纹：只指纹主函数 ≠ 指纹全链（证明改 helper 也变指纹，防绕过）。
6. staleness：current_code_hash 漂移（≠ binding 记录）→ 门 fresh 子句拒。
7. 落账 append-only + verify_chain 完整。

## 复用 [按需]
`lineage/ids.content_hash`（指纹单一源）· `lineage/spine_gate.evaluate_promotion` · spine 数据模型 · `SpineLedger` · `scipy.stats`（独立 oracle）。

## 红线 [按需]
- 单一身份源：指纹只走 `ids.content_hash`，不另造。
- 诚实：oracle 须真独立（scipy 矩 vs 手算）；门不证明定义本身对错（靠 Verifier/Critic+文献）。
- look-ahead：DSR data_contract 携返回序列 PIT 时间（known_at/effective_at）。

## 非目标 [按需]
- 不接生产 promote 路径（下一切片）。
- 不改 dsr.py 实现（只绑定 + 核对）。
- 全链其余数学点（factor/model/signal/portfolio/...）逐个绑是后续切片。

## 收尾结果（done）
- 实装 `lineage/spine_binder.py`（可复用 binder）+ `eval/spine_bindings.py`（DSR worked example）+ 扩展导出 + 理论 finding 01；新增 `tests/test_spine_dsr_binding.py`。
- 验证：DSR 绑定测试 **10 passed**；eval+spine+lineage 组 **94 passed**（未破基线）；全量后端套件后台验证（真汇总行见 log）。
- 推进 GOAL §6/§9 + 头号 gap #3「全链贯穿」：第一个真数学点（DSR）已绑并验证漂移被门抓；接生产 promote + 其余数学点为后续。
