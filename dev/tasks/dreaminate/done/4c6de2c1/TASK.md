---
uuid: 4c6de2c19e2646b484a304a056491816
title: risk_summary ok 门加固——仅辅助指标(零核心证据)绝不判可信(修 LIVE 假绿灯)
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: eval-methodology
source: audit-finding
source_ref: 第二轮 correctness 审计（workflow wnbmpeqiv）#4 发现（lev 7·LIVE 假绿灯·§3 不待拍）
depends_on: []
---

# risk_summary ok 门加固——零核心证据绝不判可信

## Scope [必填]
`compute_risk_summary` 的 `trust_level` 聚合存在 **LIVE 假绿灯**（审计 pass2 #4）：当 metrics 仅含**健康的辅助指标**
（turnover/max_drawdown/concentration/ic_ir）而**无任何核心证据**（sharpe/pbo/dsr）时，insufficient 守门不触发
（`has_sharpe and not has_pbo and not has_dsr` 中 has_sharpe=False）、checked 非空、无 flag → 落 **ok「可信」**。
即「只报了换手率/回撤的 run、零收益显著性证据」被宣布可信。consumed：`ide_run_risk_preview`（main.py）把 result.json
任意平铺字段塞 metrics，用户 emit 一个 turnover 就踩到。直接违北极星「证据不足绝不给绿」。

## 数学/不变量先行 [必填]
- **不变量**：`trust_level="ok"`（=可信=green-equivalent）⟹ 至少有一个**核心证据**指标 {sharpe ∨ pbo ∨ dsr} 在场 ∧ 无 high/medium flag。
- **为何**：辅助指标（换手/回撤/集中度）描述的是「交易行为特征」，**与策略是否有真 edge 正交**——它们在合理区间
  ≠ 策略可信。「恰好没踩任一阈值」绝不等同「已验证可信」（把『没证据』静默当成『没问题』= 假绿灯）。
- **保 flag 浮出**：守门放在 flags 分级**之后**——辅助指标**不健康**（如 turnover>3.0 触 `excessive_turnover`）仍照常
  high_risk/caution（真风险信号不被「零核心证据→insufficient」吞掉）；只重定向「健康辅助 + 零核心 + 无 flag」这个真假绿灯。

## 治理（护栏·correctness / 不替用户拍板）[必填]
- **纯 correctness（不假绿灯）非设卡**：risk_summary 是 advisory 呈现层（不阻断晋级/订单·真闸是 evaluate_overfit_gate）；
  修的是「DISPLAY 不假绿灯」——属用户**不可违背**的 correctness 非「方法学松紧」（§3 明令不待拍）。
- **不动 #6**（sharpe+dsr 无 pbo→ok 是否过宽）：与既有测试 `test_gate_brings_risk_summary_alive`（断言注入 dsr 后 ≠insufficient）
  设计意图冲突 → 属「display 宽松度=方法学/UX」留用户拍（池卡留），本切片**不碰**（保 #6 既有语义、零回归）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/eval/risk_summary.py | trust_level 末段 ok 分支拆为「有核心证据→ok / 仅辅助→insufficient_data」 | additive 收紧 |
| app/backend/tests/test_risk_summary.py | +3 测试 | additive |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **仅辅助指标→insufficient**：{turnover}/{max_drawdown}/{concentration}/{ic_ir}/组合 → insufficient_data，绝不 ok → MUT（ok 不要求核心证据）→ 红 ✓
2. **不误伤**：sharpe+pbo+dsr / sharpe+dsr → 仍 ok（向后兼容·保 #6）。
3. **不吞风险**：辅助指标超阈（turnover=50→excessive_turnover）→ 仍 caution/high_risk（flag 浮出）。

## 验收一句话 [必填]
risk_summary 不再把「仅健康辅助指标、零核心收益/反过拟合证据」判为可信（→insufficient_data），保 flag 浮出与 #6 既有语义、
不动 advisory 性质；MUT 抓；全量后端 1643 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-RISKSUMMARY-OK）
- **审计驱动（第二轮·未覆盖子系统）**：correctness 审计 workflow（wnbmpeqiv·数据层/组合/risk_summary/paper/lineage·20 agent）排 14 真缺口，
  取 #4（lev 7·LIVE 假绿灯·§3 不待拍）。读 risk_summary.py:247-279 原文复核坐实。
- **实现（additive 收紧）**：ok 分支拆为 `elif has_sharpe or has_pbo or has_dsr: ok` / `else: insufficient_data`（放 flags 分级后，保不健康辅助触 flag 浮出）。
- **对抗 + 变异**：+3 测试（仅辅助→insufficient·不误伤核心→ok·不吞风险 flag）。MUT（还原 ok 不要求核心证据）→ 仅 turnover→ok 假绿灯复现红；定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：risk_summary 26 passed（+3）；**全量后端 1643 passed / 13 skipped / 0 failed / 161s**（基线 1640，净 +3）；`test_gate_brings_risk_summary_alive` 仍绿（#6 未动）。
- **pass2 其余真缺口 → mint 池卡**：fc79b911（数据层真数据可成交性+复权轴·#1 复权/#2 停牌/涨跌停·**RULES 红线级·真喂 Tushare 前必修**）；
  03b1cf47（组合优化诚实化·#3 risk_parity 实为逆波动命名/#5 MVO 不收敛静默回退 + #6 risk_summary 单支 DSR 对齐三角）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
