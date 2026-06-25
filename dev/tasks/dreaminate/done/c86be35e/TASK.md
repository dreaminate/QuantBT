---
uuid: c86be35ee275495298f8da08a43e01a8
title: MinTRL+PSR 经脊柱绑定（交叉校验恒等式）+ 接 run verdict cold_start
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: math-spine
source: goal
source_ref: GOAL §6/§4 + 决策 D-MATH-SPINE + finding spine-consistency-gate/03 + 依赖 b85e34cc
depends_on: [b85e34cca681472b9d45cfc052653875]
---

# MinTRL+PSR 经脊柱绑定 + 接 run verdict cold_start

## Scope [必填]
把 MinTRL（最小业绩期长度）+ PSR（probabilistic Sharpe ratio，main 新增于 dsr.py）经脊柱绑定，并接进生产消费点 `run_verdict._cold_start_evidence`（R27 冷启动证据，进 RunVerdictCard）。**做**：MinTRL/PSR artifact + 两条精确交叉校验恒等式（M1 n=MinTRL→PSR≡confidence；M4 PSR(r,E[max_N])≡DSR(r,N)，绑回已绑 DSR）+ pinned 指纹 + tripwire + 接 cold_start（漂移→dsr_applicable=False+note·呈现层 fail-soft）。**不做**：conformal/attribution/drift（后续）；不动治理闸门（cold_start 是呈现层）。

## 上下文 / 动机 [按需]
脊柱已治理信任层 promote 门（三角三支）；run verdict 的 cold_start 是另一生产消费点、建在 MinTRL/PSR 上。MinTRL/PSR 有两条精确解析恒等式（强于纯统计 property）——绑它 correctness-critical 且 wire 真治理。理论先行 finding 03。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/eval/dsr.py` | `probabilistic_sharpe_ratio`/`minimum_track_record_length`/`_skew`/`_kurt_excess` | 被绑定实现（只 import）|
| `app/backend/app/eval/spine_bindings.py` | 扩展 | MinTRL artifact + 交叉校验性质 + pinned `21d30c6a2b851342` + verify_mintrl_consistency |
| `app/backend/app/run_verdict.py` | `_mintrl_spine_status`(新) + `_cold_start_evidence` | 注入 spine_consistency + 漂移 fail-soft |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. M1 交叉校验：PSR(n=MinTRL)≡confidence（实证 0.95/0.99/0.90 精确）；种 MinTRL 1.5× 漂移 → M1 fail → 门拒。
2. M4 PSR-DSR 互校验：PSR(r,E[max])==DSR(r,N)（区间内 0.674 有判别力）；种 PSR +0.1 漂移 → M4 fail。
3. abstain 诚实：n<3→insufficient、SR≤SR*→never_significant。
4. tripwire：pinned==源指纹（改 dsr.py PSR/MinTRL 链即硬失败）。
5. staleness：pinned≠live→fresh 拒。
6. 生产 wire：cold_start 含 spine_consistency.mintrl；一致→dsr_applicable 不变；漂移→dsr_applicable=False+数学一致性失败 note。

## 复用 [按需]
`lineage/spine_binder.property_consistency_check` · `spine_gate.evaluate_promotion` · 已绑 DSR（M4 互校验）· DSR/PBO/bootstrap 切片范式（pinned+tripwire+fail-soft）· scipy 矩（M1 独立重算）。

## 红线 [按需]
- 诚实：M1/M4 精确恒等式，但不证明定义本身对（靠文献+Verifier）。
- cold_start 呈现层 fail-soft（标 dsr_applicable=False+note），不动治理闸门（promote 门是 run_overfit_gate）。
- 不破基线：MinTRL/PSR 一致时 cold_start 逐位不变（dsr_applicable=status==ok 不变）。

## 非目标 [按需]
- 不绑 conformal/attribution/drift（后续）。
- 不改 dsr.py PSR/MinTRL 实现。
- cold_start fail-soft 非阻断 promote（呈现层）。

## 收尾结果（done）
- `eval/spine_bindings.py` +MinTRL/PSR proof_backed artifact + 交叉校验性质（M1/M2/M3/M4）+ pinned + verify；`run_verdict.py` +`_mintrl_spine_status` + cold_start 注入 spine_consistency + fail-soft；新增 `tests/test_spine_mintrl_binding.py`。
- **codex 只读复核 2×P2 处置（均真问题，已修）**：
  - P2-1「M1 false-negative」→ 正信号 fixture `status != ok` 原静默 `continue` 跳过 M1，漂移成 never_significant 的坏 MinTRL 仅靠 M2/M3/M4 蒙混过关。修：把正信号 fixture 的 `status==ok` 本身作一条性质（误判即 fail）+ 回归测试 `_never_sig_mintrl` 漂移必抓。
  - P2-2「R7 禁词绕过」→ cold_start fail-soft note 设在 `_BANNED_VERDICT_WORDS` 守门之后（绕过）且含「不可信」substring 命中禁词「可信」。修：note 改「判据无效」避禁词 + 守门移到最终 note 之后（defense-in-depth）+ 回归测试断言 note 无任一禁词。
- 验证：MinTRL 绑定 **12 passed**（含 P2 回归 2 条）；spine 组 **49 passed**、run_verdict/cold_start **36 passed**（未破基线）；全量后端套件后台验证（真汇总行见 log）。
- 推进 GOAL §6/§4 + gap #3：脊柱覆盖从信任层三角扩到 MinTRL/PSR + 第二个生产消费点（run verdict cold_start）治理。接 conformal/attribution/drift 为后续。
