---
uuid: 3d4a872e77274bcd8689b147aaeb9f54
title: 分支 land-readiness 整体评审 + 修 3 发现（2 文档过claim + σ 边界牙缝）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: review
source: loop-step4
source_ref: loop 第 4 步「评审打磨·以可上线成品验收」——18 commits 累积里程碑分支级审
depends_on: []
---

# 分支 land-readiness 整体评审 + 修 3 发现

## Scope [必填]
积累 18 commits（78 文件 / +7764）未 land → 按 loop 第 4 步做**分支级 land-readiness 评审**（deep-opus 三角 + 自验·
全量 1603 绿）：集成连贯性 / correctness 缺口 / 测试牙缝 / 安全红线 / 可上线阻断。**判定：land-ready，修 3 项后合并。**

## 评审结论（deep-opus 三角 + 我裁决）
- **安全红线全清**：look-ahead（σ/ADV as-of 真无泄露）、A股 live（全 venue=backtest、无券商网关 import）、M-AUTHORITY（monitor_tick 无 gate verdict 参数、PSI 结构性拒、decay advisory）、动钱/HMAC 未碰。
- **additive 属实**：全量 1603 passed / 0 failed；impact_coef=0 默认与旧 4 成分成本字节相等；前端 +411/−2；无改既有测试。
- **无结构性阻断**。

## 修的 3 发现（本卡交付）
1. **[high] signals/core.py `conformal_abstain_gate` 文档过claim**：称 q̂「来自 model_eval band_half_width·同一 q̂ 命门」暗示生产已闭环，实际生产信号管线未串接（语义兼容有测、wiring 是 follow-on）→ **改文档**：标「设计消费 band_half_width·语义有测、生产 wiring=follow-on（卡 92a2182f ①）、绝不暗示已闭环」。**（不假绿灯：in-code 文档不得声称不存在的接线）**
2. **[high] backtest_venue `cost_summary` 文档过claim**：称「供 run_detail_core 的 cost_breakdown 消费」，但那是另一套 schema(fee/funding/net)、无 producer → **改文档**：标「可用聚合 API·尚未写进 run manifest·run 详情归因 follow-on（IDE sandbox 向量化不产 per-fill）」。
3. **[medium·真牙缝] σ same-bar 边界未钉**：现码 `p=j-1`（排除当根 r_k）**正确**，但 leak-free 测试只扰未来 bar、无法区分 `p=j`（含同根 r_k=same-bar 前视）——评审把 p=j 种进去两不变量仍过 → **补测** `test_asof_sigma_excludes_same_bar_return_boundary_pinned`：扰单根 close[k]→asof[k].σ 不变、asof[k+1].σ 变；MUT「p=j」验证有牙（asof[k].σ 随 close[k] 变→第一断言崩）。σ 通道边界现与 ADV 同级钉死。

## 验收一句话 [必填]
分支 land-readiness 评审（三角+自验·安全红线全清·additive 属实·无结构阻断）+ 修 2 文档过claim（不假绿灯）
+ 补 σ same-bar 边界真牙缝（MUT p=j 验证），全量后端 1604 passed/0 failed；**判定 land-ready，待用户授权合并 main**。

## 完成记录（2026-06-25 · autonomous-loop / D-BRANCH-LANDREVIEW）
- **里程碑分支级评审**：18 commits 经 deep-opus 三角（execution/drift+lifecycle/frontend+infra）+ 我裁决，安全红线全清、additive 属实、无结构阻断 → land-ready。
- **修 3 发现**：2 个 high 是 in-code 文档过claim（声称不存在的跨件 wiring=不假绿灯雷，dev/state 虽另有诚实追踪、但 in-code 文档才是维护者先读）→ 软化为「设计消费·wiring follow-on·绝不暗示闭环」；1 个 medium 是 σ 通道 same-bar 边界真牙缝（现码正确但测试漏判 p=j 同根前视）→ 补边界钉测试、MUT 验证有牙。
- **验证**：受影响 33 测 + **全量后端 1604 passed / 13 skipped / 0 failed / 123s**（基线 1603，净 +1 σ 边界测试）。
- **low 残余（非阻断·已记）**：attribution 加总恒等式单测部分 tautology（已知 β 恢复才是判别器，docstring 可注）、ConformalIntervalCard bare-hex token 不一致、ic_decay ρ̂≈0 标 reversal（宜加 no_persistence 带）——均不阻 land、后续可清。CI 须确认 `npm ci`（worktree 无 node_modules 时 vitest 静默 exit 0）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户·本卡判定 land-ready）。
