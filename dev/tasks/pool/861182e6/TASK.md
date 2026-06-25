---
uuid: 861182e6f90a4219bd6a94553514172e
title: CPCV 接 promote/overfit gate + cv_scheme 双轨 report（价值闭环）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: eval-methodology
source: goal-gap
source_ref: 卡 41ea6e35（CPCV 库）完成后的消费侧残余；CEO 评审「价值闭环未合拢——CPCV 纯孤岛」
depends_on: [41ea6e357df24045ad4427f85afc1a7a]
---

# CPCV 接 promote/overfit gate + cv_scheme 双轨 report

> **状态（2026-06-25）**：**① cpcv 作 cv_scheme 产 per-path OOS 指标分布（report-only）✅ done**（done 卡 2da39479·`cpcv_oos_metric_distribution`：φ 路径各覆盖全样本一次→每路径模型 OOS r2→mean/std/q05/min/median/max/frac_below_0；复用 train_model 抽出的 `_fit_predict_fold`[行为不变]+cpcv.py splits/assemble；判别器命门 MUT「预测 misalign」验证有牙）；**二分类 roc_auc·proba 路径重组 ✅ done**（done 卡 c43c6301，多分类/lambdarank→unsupported_task 诚实）；**分布→UI 呈现 ✅ done**（done 卡 876a0c11·`CpcvRobustnessCard`·report-only·q05<基线警示非绿）。**② q05 接 promote/overfit gate ✅ done**（done 卡 89e7be1e·D-CPCV-GATE：q05<无技能基线=过拟合脆弱信号接进 `run_overfit_gate` + `gate_runner.evaluate_overfit_gate`；**默认 report_only 绝不改裁决·守不替方法学拍板**，`cpcv_conservative` 用户 opt-in 才 green→yellow advisory；**绝不硬 red/不升级**[q05=多证据三角外弱证据·守 R2 单支不承重·CPCV 路径≠cscv_pbo 跨策略红线]；MUT-A/B/C 三变异全抓）。**②最后一公里 ✅ done**（done 卡 f1bd08f2·D-CPCV-PROMOTE：`promote_ide_run._run_overfit_gate` 此前调 gate 时恒 cpcv=None=死接线[审计 #8 高假绿灯]→ 改读 emit `cpcv_distribution`+`cpcv_policy` 透传，缺则 None 不编造、非法 policy 回落 report_only；CPCV 全链端到端贯通至生产晋级路径）。**剩 follow-on（③·用户方法学）**：cv_scheme UI 选项（cpcv/dual_cpcv_wf 用户选）+ 双轨 report（CPCV⟂WF 并陈不自动判赢·R4=B）+ Sharpe/DSR 口径 prediction→收益转换（用户方法学）。
>
> **scope 勘察（2026-06-25·autonomous-loop 摸过、判为「需独立 Plan、不宜单轮塞」）**：`train_model`（models/training.py:174）现为**单路径 OOS**——`_make_splits` 按 cv_scheme 分派 purged_kfold/walk_forward，逐 fold 把 test 预测 concatenate 成一条 OOS 序列。CPCV 要**组合式多路径重构**：cpcv_splits(C(N,k) 组合)→每组合 fit→assemble_cpcv_paths→cpcv_metric_distribution（路径 Sharpe 分布）。即改动跨 **3 层**（① train_model 核心循环产 per-path 指标 + 结果 schema 加 path 分布字段；② verdict/gate 消费保守分位；③ 训练成本×C(N,k)）。**关键 correctness 警示**：CPCV 路径 ≠ cscv_pbo 的「跨策略矩阵」——绝不可把 CPCV paths 直接喂 `cscv_pbo`（语义误用：路径一致性≠跨策略过拟合）；正确用法是路径分布的保守分位喂 PSR/DSR + 脆弱度（路径方差）报告。建议拆：先「① cpcv 作 cv_scheme 产 path 分布诊断（report_only）」一卡，再「② 保守分位接 gate（用户选 gate_policy）」一卡。

## Scope [必填]
R4 CPCV 库（`models/cpcv.py`）已建并验证（φ 多路径分布 + 保守分位 + 防泄露 + 命门），但**纯孤岛**——
未注册为 cv_scheme、未接 promote/overfit gate、无双轨 report。本卡合拢价值闭环：
① 训练/回测台 `cv_scheme` 增 cpcv / dual_cpcv_wf 选项（用户选，**不替拍**）；
② CPCV 多路径分布的**保守分位（q05/min DSR）**接进 promote/overfit gate（gate_policy: report_only / cpcv_conservative）；
③ 双轨 report：CPCV（路径稳健性）⟂ walk-forward（部署形态）并陈，**分歧时不自动判赢**（R4=B caveat 入呈现）。

## 上下文 / 动机 [按需]
卡 41ea6e35 把 CPCV 数学/命门立住（φ 恒等、逐段 purge、PBO 路径≠策略红线、饿死路径不假 0、R4 caveat 机器钉死），
但 CEO 评审指出价值闭环只走机制层：无消费侧 → 用户用不到。接 gate 时须守住「保守分位、不压单点、双轨不自动判赢」。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| app/models/cpcv.py | 已建 | 复用，不改 |
| app/models/training.py / 回测台 | cv_scheme 选项 | 增 cpcv / dual_cpcv_wf（用户选） |
| app/eval/overfit_gate.py / gate_runner | 保守分位喂 gate | q05/min DSR；single-strategy 仍不产 PBO |
| 前端裁决卡（RunDetail 冻结不动） | 双轨 report 呈现 | CPCV ⟂ WF 并陈 + R4 caveat 弱点一等呈现 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. CPCV 接 gate 后单策略仍不产 PBO（路径数≠策略数红线在生产路径也守住）。
2. gate 取保守分位（q05/min），种「均值好但 q05 崩」→ gate 仍拦（不被漂亮单点蒙混）。
3. 双轨分歧（CPCV 过 / WF 不过）→ report 并陈、不自动判 CPCV 赢（R4=B）。
4. preprocessing 在每折内 fit（CPCV 只隔离索引）——种折外 fit scaler → 泄露门必抓。

## 验收一句话 [必填]
CPCV 多路径保守分位真接进 promote/overfit gate + cv_scheme 双轨 report 诚实并陈（不自动判赢、保守分位、单策略不产 PBO），不破基线与现有闸门。
