---
uuid: c59600222b4d4967b79119c23e702854
title: 冷启动 MinTRL 业绩期证据接进裁决卡 UI（能信·不假绿灯在前端）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: frontend-trust
source: pool-card
source_ref: 池卡 31289338「冷启动 gate/UI 接 MinTRL」的 UI 呈现部分；CEO「数学对、未接到用户」→ 能信层
depends_on: [b1e4efdf30ee441c959346ba4168bd9b]
---

# 冷启动 MinTRL 业绩期证据接进裁决卡 UI

## Scope [必填]
做池卡 **31289338** 的 UI 部分。后端 `project_overfit` 已返 `cold_start`（MinTRL「需 N 期」诚实证据，
卡 b1e4efdf 建），但**裁决卡 UI 零呈现** → 小白在 20 期业绩上看 PBO/DSR 却不知业绩期根本不够。本卡把
cold_start 作首类「业绩期」格接进 `RunVerdictCard` + `LiveRunVerdictCard` 真闭环——**能信 + 不假绿灯在前端**。

## 治理（命门·不假绿灯在 UI / R7 / 真闭环）[必填]
- **不假绿灯在 UI（核心）**：`sufficient=false` → 「证据不足·N=n」**警示色、绝不成功绿**；`sufficient=true` → 「充分」
  **中性色非成功绿**（够数据 ≠ 策略好——质量看 PBO/DSR）；缺省/null → **不渲染该格**（无数据不编造「达标」）。
- **R7 措辞**：UI 只渲染业绩期长度事实陈述（证据不足/充分/需 N 期），不在 UI 重拼信任结论措辞；完整合规说明走后端 cold_start.note 单一源（已过 R7 runtime 守门）。harness R7 扫描门覆盖。
- **真闭环**：`LiveRunVerdictCard` /overfit 响应 → `coldStartOrNull`（形状校验：sufficient:boolean + n_observed:number + status 合法，坏→null 不编造）→ RunVerdictData.coldStart → 卡渲染。
- **轴区分**：track_record_length 轴 ≠ 过拟合门样本充分性轴（type 注释钉，防两「证据不足」混读）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| RunVerdictCard.tsx | +`ColdStartEvidence` type + `coldStart?` 字段 + `ColdStartStat` + gate 行渲染 + MOCK 例 | additive |
| LiveRunVerdictCard.tsx | OverfitResp +`cold_start` + `coldStartOrNull` 校验 + mapToData 映射 | additive·真闭环 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. sufficient=false→「证据不足」警示色**非绿**（MUT-cs 冷启动恒绿→3 测抓）；sufficient=true→「充分」中性**非绿**；never_significant→「任意长度不显著」。
2. 缺省/null→不渲染（不编造达标）；形状坏→coldStartOrNull=null 不渲染。
3. LiveRunVerdictCard：真 /overfit cold_start→渲染「证据不足」；无→不渲染；坏形状→不渲染。
4. note 走后端单一源、不触 R7 禁词（harness 扫描门）。

## 验收一句话 [必填]
冷启动 MinTRL 业绩期证据接进裁决卡（RunVerdictCard + LiveRunVerdictCard 真闭环），不假绿灯在 UI（证据不足非绿/
充分中性非绿/缺数据不编造），MUT-cs 验证恒绿假绿灯有牙；tsc + 前端 288 passed + build 三门全绿、基线不破。

## 完成记录（2026-06-25 · autonomous-loop / D-COLDSTART-UI）
- **价值闭环（能信）**：cold_start（后端 project_overfit 建、UI 零呈现）→ RunVerdictCard `ColdStartStat`（业绩期格）+ LiveRunVerdictCard mapToData 真映射（/overfit cold_start → coldStartOrNull 校验 → 渲染）。小白看见「证据不足·需 N 期」而非在短业绩期上信 PBO/DSR。
- **不假绿灯在 UI**：insufficient 警示色、sufficient 中性色（够数据≠好策略）、缺省/坏形状不渲染。MUT-cs（冷启动恒绿）验证 3 测有牙。
- **worktree 前端验证**：worktree 无 node_modules（git worktree 不带 gitignored）→ symlink 主仓库 node_modules 跑 tsc/vitest/build，验后清理（symlink+dist 不入库）。
- **验证**：tsc 无错；`RunVerdictCard.test` 28 + `LiveRunVerdictCard.test` 15 passed；**全前端 288 passed / 23 文件**（基线 280，净 +8）；vite build ✓。
- **31289338 剩余**：gate 端点侧渐进披露（DSR=N/A + PSR 渐进）若需更细 UI 可续；本卡覆盖裁决卡呈现主路。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
