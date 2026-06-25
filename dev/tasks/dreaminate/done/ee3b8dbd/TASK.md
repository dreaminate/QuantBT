---
uuid: ee3b8dbd60fc4435af8dc87e1db50b5a
title: conformal 校准区间接进信号层弃权（消费侧·不对噪声下单）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: signals-methodology
source: pool-card
source_ref: 池卡 92a2182f「conformal 区间消费侧接线——信号层 + abstain」的信号层部分
depends_on: []
---

# conformal 校准区间接进信号层弃权

## Scope [必填]
做池卡 **92a2182f** 的「信号层 + abstain」部分。`signals/core.py` 的 `fuse_signals` 把 score→direction
（sign(score−threshold)），confidence 只是 score 的 sigmoid（**非**覆盖保证）。本卡加 `conformal_abstain_gate`
后处理器：用 conformal 残差区间半宽 q̂ 判预测区间是否跨决策阈值 → 跨则**弃权**（不对噪声下单）。

## 数学先行（split-conformal 消费侧）
q̂=conformal_band 是模型残差 (1−α) 预测区间半宽（来自 `model_eval.conformal_prediction_band` 的
`band_half_width`，同一 q̂ 命门）→ 真值 ∈ [score−q̂, score+q̂] 覆盖≥1−α。当 |score−threshold|≤q̂ 该区间
**含阈值** → 1−α 置信下无法判定真值落阈值哪侧 → 方向是噪声、**弃权**（flat/magnitude=0/abstained=True）。

## 治理（命门·不假绿灯/向后兼容）[必填]
- **诚实弃权**：区间跨阈值=方向不可辨 → flat，绝不对噪声 score 发可交易方向（假信号）。
- **量纲正确**：弃权判定必须用**原始 score**（与阈值同量纲），缺 score_col → raise（绝不用 confidence/magnitude 的 sigmoid/clip 失真值代）。
- **向后兼容**：band≤0 → 不弃权（abstained 全 False）；abstained 列 additive；未调用此门=原信号行为。
- **命门交叉校验**：弃权 band == model_eval conformal band_half_width（同一 q̂）。

## 附带·测试套件可靠性根治（effect_ledger busy_timeout 可配）
排查上轮挂死余波：`test_effect_ledger_concurrent_same_key`（8 连接争 SQLite 锁）负载下各等满 5s busy_timeout
被饿死、撞全局 timeout=120 fail（**全局兜底按设计 fail-fast、未再挂 7-9h**）。根治：`EffectLedger` 加可配
`busy_timeout_ms`（默认 5000=生产不变·additive），测试用 1000 让 loser 快速失败 → 该测从 5.4s→1.1s、3/3 稳；
不变量 at-most-one 不受影响（只改 loser 是 OperationalError/IntegrityError）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/signals/core.py | +`conformal_abstain_gate` | 后处理器（同 regime/confidence_filter 风格）additive |
| app/signals/__init__.py | +导出 | additive |
| app/dag/effect_ledger.py | `EffectLedger.__init__` +`busy_timeout_ms`(默认 5000) | additive·生产不变 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 跨阈值弃权 vs 整侧保留（MUT-conf2 反转弃权→抓）；边界 |score−thr|==q̂ 弃权（MUT-conf1 ≤→< 漏边界→抓）。
2. band 单调；band≤0 向后兼容（direction 同 fuse）；缺 score_col → raise（不静默/不用 confidence 代）。
3. 命门交叉校验：弃权 band == conformal_prediction_band 的 band_half_width。

## 验收一句话 [必填]
conformal 区间接进信号层弃权（区间跨阈值→flat·诚实不对噪声下单·量纲正确·向后兼容·与 model_eval band 同 q̂ 命门），
MUT-conf1/2 双 mutation 验证边界与反转有牙；附带根治并发测试负载 flaky（busy_timeout 可配）；全量 1585 passed/0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-CONFORMAL-SIGNAL-ABSTAIN）
- **价值闭环**：conformal（slice-8 建于 model_eval）→ 信号层 `conformal_abstain_gate`（区间跨阈值→弃权）；命门交叉校验绑 model_eval band_half_width 同 q̂。
- **附带根治**：effect_ledger busy_timeout 可配 → 并发测试负载 flaky 修（5.4s→1.1s 稳）；全量套件 271s→164s。
- **验证**：`test_conformal_abstain_signal.py` 6 + test_signals 7 + test_dag_kernel 25 passed；MUT-conf1/conf2 双 mutation 验证有牙；**全量后端 1585 passed / 13 skipped / 0 failed / 164s**（基线 1579，净 +6）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
