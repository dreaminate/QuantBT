---
uuid: 92a2182f4abb47afabe757bb0430142f
title: conformal 区间消费侧接线——模型台/信号层预测附校准区间 + abstain UI 呈现
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: eval-methodology
source: goal-gap
source_ref: 卡 69e1cb16（R23 conformal 库）完成后的消费侧残余；CEO 评审「未接线的另一半当 live 债追」
depends_on: [69e1cb16765a4326a11252a1d598574e]
---

# conformal 区间消费侧接线

> **状态（2026-06-25）**：**① 模型台 ✅ done**（done 卡 d4a324ae·`model_eval.conformal_prediction_band` OOS 真留出覆盖）；**① 信号层弃权 ✅ done**（done 卡 ee3b8dbd·`signals.conformal_abstain_gate` 区间跨阈值→弃权、与 model_eval band 同 q̂ 命门）。**② 前端渐进披露区间 + abstain UI 留池**（前端呈现·能信层）；**③ 时序 ACI 在线维覆盖 留池**（live 场景）。

## Scope [必填]
R23 conformal 库（`eval/conformal.py`）已建并验证（分布无关覆盖 + abstain + 不锁 α），但**暂无消费侧**——
预测/信号尚未附校准区间。本卡把它接进价值闭环：
① 模型台/信号层产预测时，用 OOS 残差（`model_eval` 的 `oos_predictions`）建 SplitConformalCalibrator/CQR，
为每个预测附 ConformalInterval（含 abstain 标）；
② 前端**渐进披露**呈现区间 + abstain（信任层 §6：弱点/不确定性一等呈现 R25，绝不淡化；abstain 显「证据不足」非假区间）；
③ 时序/live 场景用 ACI 在线维持长程覆盖。

## 上下文 / 动机 [按需]
卡 69e1cb16 把数学与命门立住（abstain 三态、不锁 α、覆盖定理不变量守门），但 CEO 评审指出价值闭环只走一半：
库为独立件、无消费侧 → 「被误用成假确定性」目前是潜在而非现行风险，但接线前须把 abstain 契约在消费侧也钉死。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| app/eval/conformal.py | 已建 | 复用，不改 |
| app/eval/model_eval.py | `oos_predictions` | 用 OOS 残差建校准器、为预测附区间 |
| 信号/裁决端点 | 预测输出 | additive 附 ConformalInterval.to_dict() |
| 前端（RunDetail 冻结不动，新页/卡） | 区间 + abstain 呈现 | 渐进披露、弱点一等呈现（R25） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 消费侧拿到 abstain 区间 → UI 显「证据不足」、绝不渲染成数值区间（假确定性）。
2. live/时序路径用 ACI、非 split（exchangeability 违反）；种平稳切漂移 → 长程覆盖维持。
3. 校准集与训练集分离（不复用训练残差当校准）→ 否则破坏覆盖保证。

## 验收一句话 [必填]
模型/信号预测在产品路径上附分布无关校准区间 + abstain 诚实呈现（弱点一等、不假确定性），不破现有闸门与基线。
