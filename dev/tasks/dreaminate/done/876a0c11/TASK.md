---
uuid: 876a0c11671f4c539461340b738eb58b
title: CPCV 路径稳健性分布呈现到模型台 UI（能信·report-only·CPCV→用户闭环收尾）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: frontend-trust
source: pool-card
source_ref: 池卡 861182e6 ② 的 UI 呈现部分；done 卡 74f93771（cpcv_distribution 入 TrainResult）的消费侧
depends_on: [74f93771c3bc415a86dac76cbf09bc77]
---

# CPCV 路径稳健性分布呈现到模型台 UI

## Scope [必填]
`cpcv_distribution`（done 卡 74f93771·入 TrainResult/result.json）尚无 UI。本卡呈现到模型台（report-only·能信）：
`training_job_eval` 透传 cpcv_distribution → `CpcvRobustnessCard` 显示路径分布（q05/路径方差=过拟合脆弱度）。
**收尾 CPCV→用户闭环**：库→消费(regression+二分类)→train_model opt-in→result.json→eval 端点→UI 卡。

## 治理（命门·不假绿灯/report-only）[必填]
- **不假绿灯**：dist 缺/null（未开 compute_cpcv）→ 卡不渲染（未算≠已算·不编造）；status≠ok（insufficient/unsupported_task）→ 显状态+reason、绝不渲假分布数字；q05 < 无技能基线（r2:0/auc:0.5）→ **脆弱警示色**（部分路径无优于随机）、q05≥基线也**中性色非绿**（路径稳≠策略好）。
- **report-only**：只呈现、不接 gate、不替方法学拍板（阈值/口径属用户·卡 861182e6 ②剩 q05→gate）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/main.py | training_job_eval +cpcv_distribution 透传 | additive |
| components/charts/CpcvRobustnessCard.tsx | 新建纯组件（--cc-* token） | 新增 |
| pages/models/TrainingBenchPage.tsx | +cpcv state + openEval 读 + EvalCharts 旁渲染 | additive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. ok→渲 q05/mean/min/median/max + note；q05<基线（脆弱）→警示色非绿、q05≥基线→中性非绿（不假绿灯）。
2. status≠ok→状态提示不渲假分布；dist 缺/null→不渲染。
3. 后端透传：result 含 cpcv_distribution→透传、无→None（不编造）。

## 验收一句话 [必填]
CPCV 路径稳健性分布呈现模型台（CpcvRobustnessCard + training_job_eval 透传·report-only·脆弱 q05<基线警示非绿·
未算不渲染），CPCV→用户闭环收尾；tsc + 前端 298 + 后端 1611 passed/0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-CPCV-UI）
- **CPCV→用户闭环收尾**：cpcv_distribution（卡 74f93771）→ training_job_eval 透传 → `CpcvRobustnessCard`（模型台·report-only）。CPCV 全链：库→消费(regression+二分类)→train_model opt-in→result.json→eval→UI。
- **不假绿灯在 UI**：未算/缺→不渲染、status≠ok→不造假分布、q05<无技能基线→脆弱警示色非绿、q05≥基线中性非绿。
- **worktree 前端坑（已避免污染）**：symlink node_modules 时一度成真目录（gitignored、主仓库未污染·已确认 141 项完好）→ rm -rf 安全清理。
- **验证**：`CpcvRobustnessCard.test` 5 + `test_model_eval_conformal` 10（+1 cpcv 透传）passed；**全前端 298 passed / 25 文件 + tsc + build ✓**；**全量后端 1611 passed / 13 skipped / 0 failed**（基线 1610，净 +1）。
- **861182e6 ②剩**：q05 接 promote/overfit gate（阈值=用户方法学）池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户·分支续 land-ready）。
