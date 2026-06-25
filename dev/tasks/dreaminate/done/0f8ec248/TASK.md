---
uuid: 0f8ec24886fd4288b840ba844c87e5f7
title: 信号层规范组合器 compose_signal_pipeline——不可绕过的安全门顺序（不假信号）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: signals
source: audit-finding
source_ref: 方法学消费侧 correctness 审计（workflow wm8x329vn）#6 发现（teeth_gap）
depends_on: []
---

# 信号层规范组合器 compose_signal_pipeline

## Scope [必填]
信号层四个 transform（`fuse_signals`/`apply_regime_gating`/`confidence_threshold_filter`/`conformal_abstain_gate`）
各自单测齐全、各自导出，但**无规范组合器**强制按序全跑——审计 #6 指出任意调用方可只挑 `fuse_signals` 就直发方向信号、
跳过 regime 关停 / 低置信打平 / conformal 区间跨阈弃权（= 对噪声下单 = 假信号）。本卡加**唯一安全路径**
`compose_signal_pipeline`，并修 `core.py __all__` 漏导出 `conformal_abstain_gate`（包 __init__ 已导、core 自身漏）。

## 数学/顺序先行（为何顺序无关于最终结果·为何仍固定规范序）[必填]
- **规范序**：fuse → regime gating → confidence filter → conformal abstain。
- **各门只降级不升级**：下游每个门只在其条件成立时把信号设为 `direction=flat, magnitude=0`，**绝不**把 flat 升回方向。
- **顺序无关于最终结果（可证）**：三个下游门的触发条件分别作用于**稳定输入列**（regime / confidence / 原始 score），
  非依赖中间 direction（regime gating 虽读 direction，但 flat 恒 ∈ 任何 regime 的 allowed 集 → 已 flat 的不会被改回）；
  故 `direction=flat ⟺ (regime 禁原方向) ∨ (confidence<min) ∨ (|score−thr|≤q̂)`，`magnitude=0` 同理 ⟺ 任一触发——
  与施加顺序无关。固定规范序仅为审计/留痕清晰。**对抗测试 `compose==手工逐步` 钉死语义等价**。
- **conformal 用原始 score**：弃权判 `|score−threshold|≤q̂` 必须用原始 score（与阈值同量纲），绝不用 sigmoid 后的 confidence
  （已失真）——沿用 `conformal_abstain_gate` 既有契约（缺 score_col → raise）。

## 治理（护栏·correctness / 不替用户拍板）[必填]
- **修 correctness（不假信号）非新设硬门**：组合器是**提供**安全路径，不改任何单门语义、不强加阈值。
- **松紧=用户方法学**：`min_confidence`/`conformal_band`(q̂ 来源/α)/`regime_rules` 全是参数，默认向后兼容
  （`conformal_band=0` → 不弃权；`regimes=None` → 跳过 regime gating，无数据不臆造）。
- **扩展不替换**：additive 新函数 + 补 __all__ 导出，四个底层 transform 一字未改。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/signals/core.py | +`compose_signal_pipeline`；__all__ 补 compose + conformal_abstain_gate（漏导出） | additive |
| app/backend/app/signals/__init__.py | 导出 compose_signal_pipeline | additive |
| app/backend/tests/test_signal_pipeline.py | 新建 5 测试 | 新增 |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **全安全门施加**：bear 下 long→flat、short 保留、带内弱信号→弃权 flat（abstained=True/mag=0）→ MUT-1（丢 abstain 步）/MUT-2（丢 regime 步）→ 红 ✓
2. **compose==手工逐步**：组合器与手工 fuse→regime→confidence→abstain 逐位等价（不偷改语义）。
3. **向后兼容**：conformal_band=0 → 全 abstained=False；regimes=None → 跳过 regime gating。
4. **导出面**：compose + conformal_abstain_gate 在 app.signals 与 core.__all__。

## 验收一句话 [必填]
信号层有了不可绕过的规范组合器（fuse→regime→confidence→conformal abstain·任一门触发即 flat/mag=0·顺序无关结果已证），
任何模型分→可交易信号的路径都应走它而非自拼 transform；默认向后兼容不替拍；MUT-1/2 双变异抓；全量后端 1640 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-SIGNAL-COMPOSE）
- **审计驱动**：correctness 审计 workflow（wm8x329vn）#6——四 transform 无规范组合器，可只跑 fuse 跳过安全门=假信号；
  且 `conformal_abstain_gate` 在 core.py __all__ 漏导出（包 __init__ 已导）。
- **数学/顺序先行**：证「各门只降级 + 作用于稳定输入列 + flat 吸收态 ⇒ 最终 direction/magnitude 与施加顺序无关」，
  组合器固定规范序仅为审计清晰；`compose==手工逐步` 测试钉死语义等价。
- **实现（additive）**：`compose_signal_pipeline`（fuse→regime[可选]→confidence→abstain·参数默认向后兼容）+ 补两处 __all__。
- **对抗 + 变异**：5 测试。MUT-1（丢 conformal_abstain 步）→ 弃权/等价/无 abstained 列 3 测红；MUT-2（丢 regime gating 步）→
  bear 下 long 未 flat 红；均定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：组合器 5 + 既有信号/conformal 测试 passed；**全量后端 1640 passed / 13 skipped / 0 failed / 133s**（基线 1635，净 +5）。
  （首/次跑机器负载高，已知 flaky `test_effect_ledger_concurrent_same_key` 本 session 复发 2 次触 120s 兜底——隔离 1.09s 绿、
  改动只碰 signals 不碰 DAG/ledger，证非回归；复跑机器转闲 133s 全绿。该 flaky 是 memory 记录的并发硬化残余，非本切片范畴。）
- **follow-on**：92a2182f 信号层 abstain UI（呈现 abstained 信号）+ 生产路径（回测/交付端点）改用本组合器——池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
