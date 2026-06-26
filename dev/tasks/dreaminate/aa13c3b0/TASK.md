---
uuid: aa13c3b08fec47d1a827b40ddb61f238
title: 因子机构级度量接 lifecycle 状态机/sizing 生产路径
status: doing
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: factor-lifecycle
source: goal-gap
source_ref: 卡 b12de4f5（§3 度量库）完成后的消费侧残余；CEO 评审「度量未接状态机/sizing」
depends_on: [b12de4f59b744065895c4c6bc9f06df7]
---

# 因子机构级度量接 lifecycle 状态机/sizing 生产路径

> **状态（2026-06-25）**：**① 衰减半衰期 → lifecycle 状态机 ✅ done**（done 卡 1b83a5c5·`decay_diagnostic` perf 轴 advisory、unstable/no_decay 不硬退役、M-AUTHORITY 守、MUT-S/MUT-M 验证有牙）。**修正**：`ic_decay_half_life` 是 IC **持久性**（自相关）半衰期、≠ 现有转移测的 IC **水平衰减**——两者不同概念，故 decay 作 **advisory 不并入硬转移**（避免数学↔实现混淆），硬退役阈值是用户方法学决策。
> **② 容量/拥挤 → sizing 生产路径 留池待做**：方法学决策（如何按容量缩仓、Y 占位）+ 需 sizing 生产模块接线。

## Scope [必填]
§3 度量库（`lifecycle_metrics.py`）已建并验证（衰减/容量/因子族/拥挤 + 命门），但**度量层与状态机/sizing 未接**。本卡合拢：
① **衰减半衰期** → 喂 lifecycle 退役判定（半衰期短/status=ok 才作硬退役依据；unstable/no_decay 只告警不硬退役）；
② **容量** → 喂 sizing 上限（AUM 不超容量；Y 占位时只示意不硬卡）；
③ **因子族** → 喂组合层「独立 bet」计数（同族因子不重复计独立性，接 honest-N/组合三角）；
④ **拥挤** → 仅呈现层咨询（绝不接 sizing 自动减仓，结构已隔离）。

## 上下文 / 动机 [按需]
卡 b12de4f5 把 4 件度量的数学/命门立住，但 CEO 评审指出价值闭环停在度量层。接生产路径时须守：退役只用 status=ok 的半衰期（unstable 不硬退役）、容量 Y 占位诚实标、拥挤绝不自动减仓。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| app/factor_factory/lifecycle_metrics.py | 已建 | 复用 |
| app/factor_factory/lifecycle.py | evaluate_transition/状态机 | 半衰期 status=ok 作退役输入之一 |
| app/monitor/closure.py | monitor_tick（绩效轴） | 衰减/容量可作绩效轴附证（非 gate verdict，守 M-AUTHORITY） |
| 组合层 | 独立 bet 计数 | 因子族数接 honest-N/组合三角 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 退役只采 status=ok 的半衰期；种 unstable（随机游走）→ 不触发硬退役（绝不对弱识别发退役）。
2. 容量 Y 占位 → sizing 只示意不硬卡 + 诚实标；真 Y → 硬上限。
3. 拥挤接呈现层 → 绝不进 sizing 减仓路径（类型层守，同 §3 隔离）。
4. 因子族数接组合独立性 → 同族因子不重复计 independent bet。

## 验收一句话 [必填]
4 件度量真接进 lifecycle 退役/sizing/组合独立性生产路径（半衰期 unstable 不硬退役、容量 Y 占位诚实、拥挤绝不自动减仓），不破基线与现有闸门。

## 中心派发指令（第九波·dreaminate·GOAL-first）
**本卡剩余 scope（衰减→lifecycle 已 done·见上方状态注）= ② 容量→sizing 诚实上限 + ③ 因子族→组合独立 bet 计数 + ④ 拥挤仅呈现层咨询（绝不进 sizing 自动减仓）。**

**先读 GOAL 对应节再动手**：`dev/GOAL.md` §3（因子族/度量·行 264 起）+ §9（lifecycle 退役/交付闸·行 1454 起）。容量缩仓/退役阈值的**松紧是用户方法学决策**——系统只做"诚实接线+提供旋钮+按真实状态限制"，**绝不替用户拍方法学**（容量数据缺=Y 占位时只示意+诚实标，绝不编造硬上限；拥挤绝不自动减仓，类型层隔离）。

**领地（只动·扩展不替换）**：`app/backend/app/factor_factory/`（lifecycle.py 状态机入参、lifecycle_metrics.py 复用）+ 组合层独立 bet 计数模块 + sizing 生产路径文件（容量上限附加·additive）+ 新测试。**绝不碰**：`main.py`（中心本波并行在改归因薄路由）、`instruments/`、`signals/`、`eval/model_eval.py`、`models/training.py`、`run_verdict.py`、其它在飞线模块内部。若接线**确实**需要改上述禁区文件，**停下来在完成纪要里报告冲突**（中心下波串行），不要擅自改。

**完成口径（隔离 worktree 内自跑·中心整合）**：
- 数学先行：本卡无新公式（度量公式已在 b12de4f5 立·复用），不强造 MathematicalArtifact；若接线引入新聚合口径（如组合独立性的 effective-N 公式）需落 MathematicalArtifact 并标数学↔实现一致。
- 对抗测试种坏门必抓（按本卡"对抗测试设计"4 条）：unstable 半衰期不硬退役 / 容量 Y 占位只示意 / 拥挤绝不进 sizing / 同族因子不重复计独立 bet。**MUT 用 in-place Edit 改门→测试转红→手工复原→复绿·绝不 git checkout**。
- 只跑 scoped 测试（`cd app/backend && pytest tests/<本卡新测试> -x -q --timeout=300`·真汇总行判绿），**绝不叠跑全量**（中心整合时统一跑全量+land）。
- 自建分支 `wave9/factor-metrics-wiring`（基于 origin/main·801f8c6），push 后回报：分支名、新建/改的文件清单、真测试汇总行、对抗测试逐条、MUT 三态证据、红线合规、任何触禁区冲突。review_status 留 0（权威 review=中心 land）。

**红线**：correctness（不假绿灯 / 数学↔实现一致 / no silent mock）+ 安全不变量（拥挤绝不自动减仓 / 退役只采 status=ok 半衰期 / 容量 Y 占位绝不编造）。撞致命（动钱/不可逆/数据泄露）即停工报告。
