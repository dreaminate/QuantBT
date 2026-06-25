---
uuid: d4a324ae663d440b9099df64b3efe103
title: conformal 校准区间接进 model_eval（价值闭环·OOS 真留出覆盖率）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: eval-methodology
source: goal-gap
source_ref: P2 卡 92a2182f 的后端部分；CEO「数学对、未接到用户」→ 第二个价值闭环（conformal→模型台）
depends_on: []
---

# conformal 校准区间接进 model_eval

## Scope [必填]
把已建 R23 conformal（`eval/conformal.py`）**接进 model_eval**——第二个价值闭环（数学→模型台输出）。
`model_eval.conformal_prediction_band`：回归 OOS 残差按时间序切 calib(前半)/test(后半，leak-free) →
split-conformal 带 q̂ → 在 test 上报**真留出覆盖率**（非循环自证）；`training_job_eval` additive 加
`conformal_interval` 字段（不破 charts/metrics）。

## 治理（命门·不假绿灯/白名单/非循环）[必填]
- **白名单 regression-only**（codex P2）：classification/**lambdarank(排序)**/未知任务 → None（残差校准对 rank 无意义=假信号）。
- **真留出覆盖率非循环**：覆盖算在 test 半（非 calib 自证）；sentinel：calib σ1/test σ3 → 覆盖<<0.9（循环自证会≈0.9 被抓）。
- **不假绿灯**：calib 不足→abstained（band/coverage=None）；覆盖测试断言**经验均值≈总体 k/(m+1)（容 MC 噪声）**、绝不称「均值≥1−α=达标」（sub-nominal 估计≠达标）；note 用 .1% 避免进位掩盖 + 抽样噪声 caveat。
- **R5 披露**：conformal 覆盖依赖 exchangeability，时序非平稳可能偏离（note + 自适应 ACI 指引）；test 非有限点剔除并披露。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/eval/model_eval.py | +conformal_prediction_band + __all__ | 复用 split_conformal_interval；不破 build_eval_charts/summarize |
| app/main.py | training_job_eval 加 conformal_interval 字段 | additive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. **留出覆盖率与总体 k/(m+1) 一致**（多种子 MC，容噪声；非「均值≥1−α 达标」假绿灯）。
2. **非循环 sentinel**：calib σ1/test σ3 → 真覆盖<<0.9（循环自证 bug 会≈0.9 → 抓）；太窄带欠覆盖 sentinel。
3. 白名单：classification/lambdarank/ranking/未知 → None；regression → 出区间。abstain（calib 不足）band/cov=None。
4. training_job_eval additive 含 conformal_interval 不破 charts/metrics。JSON-safe。

## 验收一句话 [必填]
conformal 接 model_eval（OOS split-conformal 带 + 真留出覆盖率 + 白名单 regression + abstain），覆盖测试统计诚实非假绿灯、非循环 sentinel 有牙；全量后端绿、基线不破。

## 完成记录（2026-06-25 · autonomous-loop / D-CONFORMAL-MODELEVAL）
- **价值闭环**：选 conformal→model_eval（最大未接数学件、能信）。`conformal_prediction_band` 时间序 calib/test + 真留出覆盖率；training_job_eval additive。命门实证：留出覆盖 α=0.1→0.901/α=0.05→0.948（跨 100 seed）。
- **两轮独立复核全闭环（同型门牙缺口第三轮）**：① **Stop-hook codex 顾问 P2**：黑名单 `task=="classification"` 漏 lambdarank → 改白名单 `task!="regression"`（regression-only，绝不对排序 job 发假校准）。② **多透镜评审 2 confirmed medium**：(a) 覆盖测试措辞「均值≥1−α=达标」是假绿灯（经验均值 0.8986<0.90 靠 slack 过；conformal 保证总体 k/(m+1)≥1−α、经验是带噪估计）→ 改统计一致性断言（≈k/(m+1) 容 MC 噪声）；(b) **核心命门「非循环」零牙**（种 test→calib 循环自证 bug 7 测全过=纸糊门，正是用户那 mutation）→ 加 σ1/σ3 非循环 sentinel + low（.1% 去进位掩盖/test 非有限掩码/抽样噪声 caveat/__all__）。
- **验证**：`test_model_eval_conformal.py` 9 + model_eval 6 回归 passed；**全量后端 1564 passed / 13 skipped / 0 failed**，基线 1554 未破。
- **land main 待用户授权**（本轮 loop「commit 不擅自 push」→ 本地 commit、未 push）。
