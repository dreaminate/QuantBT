---
uuid: d9bf88b16fa24755860d338f1ab5c36b
title: sqrt-impact 自估 ADV/σ 扩张窗 as-of 无泄露（根治回测前视泄露）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: execution-cost
source: pool-card
source_ref: 池卡 0f696e56（卡 7179ba36 sqrt-impact 评审 HIGH 前视残余）；RULES.project look-ahead 红线
depends_on: [7179ba36278e4091a8e29b4d58336525]
---

# sqrt-impact 自估 ADV/σ 扩张窗 as-of 无泄露

## Scope [必填]
关闭池卡 **0f696e56**。卡 7179ba36 的 sqrt-impact 自估 ADV/σ 用**全样本**（含未来 bar）→ 启用 impact 的
回测有**前视泄露**（早期成交参与率被未来流动性稀释、成本偏乐观），原处置=default-off + 响亮 warning +
显式无泄露入口。本卡**根治**：自估改**扩张窗 as-of**——replay 每笔成交按其 ts 只用严格早于 ts 的历史
`F_{t⁻}` 估 ADV/σ，消除前视、令自估路径也能安全启用。

## 数学先行（finding「扩张窗 as-of 无泄露自估」节）
ADV_{t⁻}=mean(严格早于 t 所在日的已完成日量)；σ_{t⁻}=std(于 <t 实现的 close 收益, ddof=1, bar t 只用
r_1..r_{t-1})。无泄露性证：每个被求和项于 <t 实现 ⇒ 估计量 F_{t⁻}-可测 ⇒ 成交冲击不依赖 ≥t 数据 ∎。
判别性命门：追加任意未来 bar 不得改早期成交冲击（全样本会变=泄露，as-of 不变=leak-free 的牙）。

## 治理（命门·不假绿灯/无泄露）[必填]
- **warmup 裁决纯由 F_{t⁻} 驱动**（评审 PROBE H 修正）：prior 不足（首日/<2 收益/零量 prefix）→ 该笔不计
  冲击但**计数+披露**（`_impact_warmup_fills` + 一次性 warning），**绝不**用全样本 `max(volume)>0` 判
  warmup-vs-charge（否则早期成交的 skip/charge 离散决策被未来 bar 翻转=残余前视 + 缺流动性成交伪装 warmup
  静默放过=假绿灯）。「全样本无量」硬 fail-fast 仅留 ts=None 终端路径（序列末无未来⇒非泄露）。
- **未知 ts**（不在 as-of map）→ warmup-披露，**绝不回退泄露的终端全样本标量**。
- **终端标量**（ts=None）仅作汇总/直接调用回退（序列末无未来⇒非泄露）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/execution/backtest_venue.py | `_precompute_impact_stats`/+`_build_asof_impact`/+`_impact_inputs`/+`_note_impact_warmup`/`_cost_for_trade`(+ts)/`step`(传 next_ts) | 自估改扩张窗 as-of；终端标量留 ts=None 回退 |
| app/execution/impact.py | 复用 `square_root_impact_fraction` | 不改 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. **leak-free 未来不变量**（量通道）：早期 bar 相同、仅未来量×100 → 早期成交冲击逐位相等（MUT-A/全样本估计→红）。
2. **σ 通道 leak-free**（评审牙缝补强）：量相同、仅未来**价**×mult → 早期成交逐位相等（as-of ADV+全样本 σ 的似真错实现→红，MUT-A 验证有牙）。
3. **ADV 机制钉死**（评审牙缝补强）：非平早期量 → as-of ADV==精确前缀均值（lag-1/前一日 的似真错→红，MUT-B 验证有牙）。
4. **PROBE H 回归**：zero-vol prefix 早期成交的 warmup 裁决三档未来量同一结果（残余前视→红/raise）。
5. warmup 不足→不计冲击+计数+披露（c0=0/count++、c5>0）；全样本无量 ts=None→fail-fast（不静默 0）；replay 集成走 as-of。
6. methodology_invariants 命门：F_{t⁻}-可测 property（同时扰未来价+量，40 seed，ADV+σ 双通道）。

## 验收一句话 [必填]
sqrt-impact 自估改扩张窗 as-of 无泄露（每笔成交只用 F_{t⁻}），消除回测前视泄露、自估路径安全可启用；
warmup 裁决纯 F_{t⁻} 驱动（不被未来翻转）+ 计数披露非假绿灯；leak-free/σ通道/机制三测经 mutation 验证有牙；全量后端绿、基线不破。

## 完成记录（2026-06-25 · autonomous-loop / D-SQRTIMPACT-LEAKFREE）
- **根治前视**：选 P2 0f696e56（correctness floor 里唯一遗留 look-ahead 残余）。`_build_asof_impact` 扩张窗 as-of
  （datetime 按日聚合「严格早于当日」+ int ts 前缀均量 + σ 扩张 std 只用 r_1..r_{t-1}）；`step` 传 next_ts → replay 每笔成交无泄露；终端标量仅 ts=None 回退。warning 从「前视泄露」转 informational（扩张窗/无前视/warmup 披露）。
- **评审三角（deep-opus + codex 互不知情 + 我裁决）挖出真 critical 并修**：① 我初版用全样本 `max(volume)>0` 判 warmup-vs-fail-fast → 评审 PROBE H 实测「early bar 逐位相同、仅未来量不同 → 裁决翻转(raise vs warmup)」=残余前视 + 缺流动性伪装 warmup 静默放过(假绿灯)。**修**：warmup 裁决改纯 F_{t⁻} prefix 驱动、剔除全样本信号；未知 ts 改 warmup-披露不回退泄露终端值。② 评审挖出 σ 通道测试无牙（原 leak-free 测试只扰量、close 相同）+ ADV 机制未钉死（平量下扩张均值/lag-1 不可分）→ **补** σ-价测试 + 非平量机制测试，**经 MUT-A（σ 全样本）/MUT-B（lag-1）双 mutation 验证真有牙**（旧测试确实漏、新测试必抓）。
- **验证**：`test_sqrt_impact_cost.py` 20 + methodology leak-free 不变量 1 passed；**全量后端 1571 passed / 13 skipped / 0 failed**（基线 1564 未破，净 +7 测试）；PROBE H 修前(raise vs cost=0)→修后(两面板同 warmup·cost=0)实证。
- **land main 待用户授权**（本轮 loop「commit 不擅自 push」→ 本地 commit、未 push）。
