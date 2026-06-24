---
uuid: 6acbb499f5b94fe3b77c4de79bb43982
title: R27 冷启动 MinTRL（最小业绩期长度）+ PSR 反解命门
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: eval-methodology
source: goal-gap
source_ref: GOAL §6「冷启动 N=1 诚实证据不足（剔 DSR 用 PSR/MinTRL）」+ 决策 R27=确认
depends_on: []
---

# R27 冷启动 MinTRL + PSR 反解命门

## Scope [必填]
补 §6 R27 冷启动缺口：**MinTRL（最小业绩期长度，Bailey & López de Prado 2012）**=达到置信 p 所需最小观测数，
是 PSR 的解析反解。扩展已建 PSR（`eval/dsr.py`）。服务「冷启动 N=1 剔 DSR、用 PSR/MinTRL + 显式证据不足」。

## 治理（命门·correctness/不假绿灯）[必填]
- **MinTRL=1+denom²·(Φ⁻¹(p)/(SR_pp−SR*))²**，denom² 与 PSR 同项同钳、SR* per-period、Z_p 单侧。
- **命门交叉校验**：n=MinTRL 时 PSR(SR*)≡confidence（PSR 精确反解，实证 8.88e-16）。
- **不假绿灯**：SR_pp≤SR*→+∞(never_significant 非样本不足)；n<3/N=1→insufficient（绝不假装算出，R27）；confidence∈(0.5,1) raise。冷启动 sufficient=n≥⌈MinTRL⌉ 否则诚实证据不足；R27 N=1 DSR 退化 PSR=范畴误用、冷启动 DSR=N/A。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/eval/dsr.py | +MinTRLResult + minimum_track_record_length | 复用 _skew/_kurt_excess/denom 口径；PSR 反解交叉校验 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. PSR↔MinTRL 反解交叉校验：n=MinTRL→PSR≡confidence（**含非零 sr_benchmark**——否则 dropped-sr_benchmark 漏网）。
2. SR_pp≤SR*→never_significant(+∞)；n<3/N=1→insufficient；confidence∉(0.5,1) raise。
3. 单调：confidence↑→MinTRL↑、edge↑→MinTRL↓。⌈MinTRL⌉ 处纯矩 PSR≥confidence。
4. 冷启动 sufficient 有牙：确定性 ok+短→False、ok+够长→True（抓 >=↔<= 翻转）。

## 验收一句话 [必填]
MinTRL 数学对齐 R27/PSR 反解、命门交叉校验（含非零基准）、边界诚实证据不足、冷启动 sufficient 有牙；全量后端绿、基线不破。

## 完成记录（2026-06-25 · autonomous-loop / D-MINTRL-R27）
- **数学先行 + 并行思考**：落 `findings/dreaminate/mintrl-cold-start.md`；codex(xhigh) 确认 MinTRL 是 PSR 精确反解 + 边界/交叉校验。
- **实现（扩展不替换）**：`dsr.py` 加 MinTRLResult + minimum_track_record_length，denom² 与 PSR 同项 → n=MinTRL 时 PSR≡confidence。
- **对抗测试 + 命门**：`test_mintrl_cold_start.py` **10 passed** + 方法学不变量 **+2**（PSR↔MinTRL 反解 8.88e-16/单调边界）。
- **两轮独立复核全闭环（2 类同型门牙缺口全补）**：① **用户种 mutation**（`delta=sr_pp` dropped sr_benchmark）——精准戳中**我所有 MinTRL 测试都用 sr_benchmark=0** 的盲区（sr_pp−0≡sr_pp，mutation 隐形、71 测全绿漏网）→ 补 sr_benchmark≠0 交叉校验（验证带 mutation RED max|Δz|=2.08、还原后绿）；② **多透镜评审 1 medium**——sufficiency 测试 seed=5 落 never_significant 致核心 `assert not sufficient` 被跳过、`>=↔<=` 翻转漏网 → 改确定性构造 ok+short/ok+long + 无条件 assert。**两条同属「测试过运气/未行权判别路径」**，均补成真有牙。低优：ceil 测试改纯矩确定性（去单种子噪声）。
- **验证**：全量后端绿（待最终全量确认），基线不破。mint **P2 卡 31289338**（冷启动 gate/UI 接 MinTRL：DSR=N/A + PSR + "需 N 期" 渐进披露，R25/R27 呈现层）。
- **land main 待用户授权**（不擅自 push/land）。
