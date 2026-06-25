---
uuid: 03b1cf47bafc4e8e9bc440a3a8ac3f72
title: 组合优化诚实化 + risk_summary 单支证据对齐三角（命名 theory↔impl / 静默回退 / 单支承重）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: eval-methodology
source: audit-finding
source_ref: 第二轮 correctness 审计（workflow wnbmpeqiv）#3（risk_parity 命名·lev 7）+ #5（MVO 静默回退·lev 6）+ #6（risk_summary 单支 DSR·lev 6）
depends_on: []
---

# 组合优化诚实化 + risk_summary 单支证据对齐

## Scope [必填]
三条「数学↔实现不一致 / 未验证当已验证」缺口（当前生产面 MVO/风险平价暂未真钱消费 → 非今日致命，但接入即变致命，提前补牙）：
① **risk_parity 实为逆波动**（optimizers.py:70）：docstring 自称 risk parity，实际给 1/σ 等权——相关 0.9 两资产实测风险贡献
   RC=0.396/0.396/0.208（A,B 各扛近 2× C），违「风险平价=各标的风险贡献相等」定义。测试 test_risk_parity_inverse_sigma 只断言逆波动序、把错误定义钉死。**与项目 glossary/dossier 定义冲突=真 theory↔impl 不一致**。
② **MVO 不收敛静默回退等权**（optimizers.py:65-67）：`weights = res.x if res.success else w0`——SLSQP 不收敛时无声返回初始等权 w0，
   调用方/`optimize_portfolio` 的 violations 不记录 → 「优化失败」与「真优化出等权」不可区分=未验证当已验证。crypto demo 还 try/except 吞异常叠加掩盖。
③ **risk_summary 单支 DSR 即 ok**（risk_summary.py:251）：sharpe+dsr（无 pbo）→ ok，而权威 overfit_gate（PBO=None→yellow）更严
   → 两源对同一 run 互打脸（preview chip 绿 vs gate_verdict yellow）。**注**：与既有测试 `test_gate_brings_risk_summary_alive`
   设计意图（注入 dsr 后 ≠insufficient）冲突 → 改前须重审「advisory chip 该多严」=**用户方法学/UX 拍板**（done 卡 4c6de2c1 已修 #4 但刻意不动 #6）。

## 数学/不变量先行 [必填]
- **真风险平价（ERC）**：∀i,j w_i·(Σw)_i = w_j·(Σw)_j（边际风险贡献相等）→ RC_i=1/N；逆波动 w∝1/σ 仅 corr=0（Σ 对角）时满足。
- **MVO 解状态**：返回 w 须满足 KKT；res.success=False ⇒ 无最优性保证、不得静默当解。
- **risk_summary↔gate 一致（命门）**：advisory chip 的「可信」不应比权威 gate 对同证据更乐观（PBO 缺→gate 至多 yellow）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| portfolio/optimizers.py:70 | risk_parity | 要么改名 inverse_volatility + 标 ERC 退化特例（最小诚实切片）；要么 SLSQP/Newton 解真 ERC |
| portfolio/optimizers.py:65 | mean_variance | res.success=False 透传 constraint_violations.append('mvo_not_converged') 或 raise |
| eval/risk_summary.py:251 | insufficient 守门 | （用户拍板后）PBO 缺时 ok 降级，对齐多证据三角；须同步重审 test_gate_brings_risk_summary_alive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. risk_parity：相关 0.9 两资产+一独立资产 → RC max-min<1e-3（真 ERC 才过·逆波动红）；或改名后断言 OptimizerKind/docstring 一致。
2. MVO：喂奇异 cov 病态输入 → violations 含 'mvo_not_converged' 或抛出（非静默等权）。
3. risk_summary #6（用户拍板后）：sharpe+dsr 无 pbo → 与 gate 同口径（不比 gate 乐观）。

## 验收一句话 [必填]
组合优化命名/状态诚实（risk_parity 名实一致 + MVO 不收敛不静默当解）+（用户拍板后）risk_summary 不比权威 gate 乐观；不破基线。
