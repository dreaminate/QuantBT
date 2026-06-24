---
uuid: b12de4f59b744065895c4c6bc9f06df7
title: §3 因子机构级生命周期度量（衰减半衰期/容量/因子族/拥挤）+ 命门
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: factor-lifecycle
source: goal-gap
source_ref: GOAL §3「机构级因子生命周期（衰减/拥挤/容量/因子族）」+ 决策 R21/R18/R19
depends_on: []
---

# §3 因子机构级生命周期度量 + 命门

## Scope [必填]
补 M11「toy 五态机 / 机构级未做」缺口：**度量层** 4 件——① 衰减半衰期（AR(1) 持久性）② 容量
（sqrt 市场冲击 δ=0.5）③ 因子族（R21 去重·收益相关聚类）④ 拥挤（定性咨询）。扩展不替换
（`lifecycle.py` toy 五态机不动）；产出喂状态机/sizing。**数学先行**（公式+推导）。

## 治理（命门·correctness/不假绿灯/防放水）[必填]
- **半衰期绝不 clip ρ**：ρ≥1→no_decay、ρ≤0→reversal、CI 跨0/1 或 **ρ̂>0.95 近单位根→unstable**（机器门绝不对随机游走发 ok）。
- **容量**：α≤0→no_edge、τ/σ/ADV=0→invalid（绝不返普通数值）；**δ=0.5 锁定不暴露入参**（R18，否则自检循环失效）；
  Y 省略用占位+**诚实告警**；回代 cost(C)≈α 自检；α 与 τ/σ/ADV 须同周期。
- **因子族**：复用 n_eff 锁定聚类口径（合并|corr|≥0.7），**阈值不暴露入参**（防放水，honest-N 不可手动改小）；
  **n_families==n_eff.point 交叉校验**（绑 honest-N）。
- **拥挤**：定性咨询，`CrowdingAdvisory` **结构无任何减仓/动作字段**（GOAL §3 禁自动减仓，R19）；
  等级阈值锁定不暴露入参；`missing≠crowding 0`（数据不足→insufficient；零相关 0.0 是有效测量→none，非缺失）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/factor_factory/lifecycle_metrics.py | 新建 | ic_decay_half_life + strategy_capacity + factor_families + crowding_advisory + 4 dataclass(to_dict) |
| app/eval/n_eff.py | 抽 `_cluster_labels` 单一聚类口径源（_cluster_count 调它） | 因子族与 honest-N 同一源、防漂 |
| app/factor_factory/__init__.py | 导出 | additive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 半衰期解析点 ρ=0.5→h=1、√0.5→h=2；ρ 不 clip（爆炸→no_decay）；**随机游走多种子 ok 占比<10%**（非单种子侥幸）。
2. 容量 τ³ 标度（τ翻倍→C/8）、α²、ADV¹、σ⁻²、Y⁻²；α≤0→no_edge；τ/σ/ADV=0→invalid；cost(C)≈α；δ/Y 占位告警。
3. 因子族 等价/反相关→1 族、独立→N 族、**==n_eff.point**、NaN corr 不填 0、阈值锁定不可调。
4. 拥挤无动作字段（扫 reduce/haircut/multiplier/action）；数据不足→insufficient 非 none；零相关→none；越界相关→脏值。
5. IC 不跨 NaN 缺口拼接（codex P2）。

## 验收一句话 [必填]
4 件度量数学对齐理论、ρ 不 clip/容量 τ³+δ锁/因子族==n_eff/拥挤无减仓字段命门守门、不放水不假绿灯；全量后端绿、基线不破。

## 完成记录（2026-06-24 · autonomous-loop / D-LIFECYCLE-§3）
- **数学先行 + 并行思考**：落 `findings/dreaminate/factor-lifecycle-institutional.md`；codex(xhigh) 复核——加固 ρ 不 clip / τ³ 标度 / corr-vs-距离阈钉清 / 拥挤结构隔离。
- **实现（扩展不替换）**：`lifecycle_metrics.py`；n_eff 抽 `_cluster_labels` 单一聚类口径源；因子族==n_eff.point 交叉校验。
- **对抗测试 + 命门**：`test_factor_lifecycle_metrics.py` **25 passed** + 方法学不变量 **+6**（半衰期解析点/ρ不clip sentinel/容量精确标度+净alpha=0自检/因子族==n_eff/拥挤无动作字段机器钉死）。
- **两轮独立复核全闭环**：① Stop-hook codex 顾问 **3 条 P2**（零拥挤 falsy 陷阱→none / IC 跨 NaN 缺口拼接→对齐 drop / 因子族阈值放水口→锁定）；② 多透镜评审（autoplan 等价 4 透镜 + 对抗复核，12 agents）**4 confirmed**（随机游走 ρ=1 假绿灯 28%→<10%·ρ̂>0.95 local-to-unity 降级 + 多种子测试 / 容量 δ 可改离 R18→锁定 / 容量 Y 占位无告警→告警 / 拥挤等级阈值放水口→锁定）+ low 清理（DRY 单一源/死 import/死 Literal/to_dict/__init__ 导出/越界相关脏值）。数学核心经 4 透镜独立复跑全真、对抗测试有真牙。
- **验证**：全量后端 **1518 passed / 13 skipped / 0 failed**（223s，机器负载偏慢但 120s 单测超时无触发=未卡），基线 1487 未破。mint **P2 卡 aa13c3b0**（度量接 lifecycle 状态机/sizing 生产路径）。
- **land main 待用户授权**（不擅自 push/land）。
