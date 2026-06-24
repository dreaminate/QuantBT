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
