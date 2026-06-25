---
uuid: 5891da4239ac4be08b765c8b1a54b4c7
title: 组合优化诚实化——risk_parity 真 ERC(名实一致) + mean_variance 不收敛透明(非静默回退)
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: eval-methodology
source: audit-finding
source_ref: 第二轮 correctness 审计（workflow wnbmpeqiv）#3（risk_parity 命名 theory↔impl·lev 7）+ #5（MVO 静默回退·lev 6）；池卡 03b1cf47 的 ①②
depends_on: []
---

# 组合优化诚实化——risk_parity 真 ERC + mean_variance 不收敛透明

## Scope [必填]
两条组合优化器「数学↔实现不一致 / 未验证当已验证」缺口（pass2 #3/#5）：
① **risk_parity 实为逆波动**（optimizers.py:70）：OptimizerKind/模块 docstring 称 risk_parity，实际给 w∝1/σ
   ——相关非零时风险贡献**不相等**（A,B 相关 0.9 各扛≈2×C），违 risk parity 定义；测试只断言逆波动序、把错误定义钉死。
② **mean_variance 不收敛静默回退等权**（optimizers.py:66 `res.x if res.success else w0`）：SLSQP 不收敛时无声返回 w0，
   「优化失败」与「真优化出等权」不可区分=未验证当已验证假绿灯。

## 数学先行 [必填]
- **真 ERC**：解 w 使各标的风险贡献 RC_i = w_i·(Σw)_i 相等（归一 RC_i=1/N）。乘性不动点（Maillard-Roncalli-Teïletche 2010）
  暖启 w∝1/σ，迭代 w_i ← w_i·√(target/RC_i) 归一。**关键数值教训**：满步乘性更新**振荡不收敛**（[.333]↔[.256] 反复）→ 必须
  **平方根阻尼**（log 空间半步）才稳定收敛。**对角 Σ → 退化为逆波动 1/σ**（逆波动只是 ERC 零相关特例；相关非零 ERC≠逆波动）。
- **MVO 解状态**：res.success=False ⟹ KKT 未达、w 无最优性保证，不得静默当解 → raise。

## 治理（护栏·correctness / 不替用户拍板）[必填]
- **名实一致是 correctness 非设卡**：用户已选「risk_parity」优化器，让它真做 risk parity（ERC）= 修 theory↔impl 不一致，
  非新增/强加方法学；用户仍可选 equal_weight/mean_variance/hrp。**保 API 字面量不变**（非破坏性）、旧 inverse_sigma 测试仍绿（ERC 对近对角退化）。
- **不收敛透明**：mean_variance raise；optimize_portfolio 捕获 → `mvo_not_converged` violation + 等权回退（主路径非破坏·透明非静默）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| portfolio/optimizers.py | +`PortfolioOptimizationError`；risk_parity→真 ERC（sqrt 阻尼不动点）；mean_variance 不收敛 raise；optimize_portfolio 捕获标 violation+等权回退；docstring 诚实 | additive+行为修正 |
| app/backend/tests/test_portfolio.py | +4 测试 | additive |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **真 ERC**：A,B 相关 0.9+C 独立 → RC 三者相等（max-min<1e-6）、C 权重>A,B；sentinel 逆波动(等权) RC 不均>0.1 → MUT-#3（退回逆波动）→ 红 ✓
2. **对角退化**：对角 Σ → ERC == 1/σ（逆波动是零相关特例）。
3. **MVO 不收敛 raise**：monkeypatch minimize success=False → raise PortfolioOptimizationError → MUT-#5（静默回退）→ 红 ✓
4. **optimize_portfolio 透明标记**：不收敛 → violations 含 'mvo_not_converged' + 仍出权重不崩。

## 验收一句话 [必填]
risk_parity 真做等风险贡献（名实一致·相关非零 RC 相等·对角退化逆波动）+ mean_variance 不收敛透明 raise/标 violation（非静默冒充解）；
保 API 与旧测试；MUT-#3/#5 双变异抓；全量后端 1653 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-PORTFOLIO-HONEST）
- **审计驱动（第二轮 #3/#5）**：risk_parity docstring 自承「简化版 1/σ」却名 risk_parity；mean_variance 静默回退 w0。读 optimizers.py 原文 + test_portfolio 复核坐实。
- **数学先行 + 数值纠偏**：真 ERC 乘性不动点；**自查发现满步振荡不收敛 → 平方根阻尼**（手算轨迹验证 [.333]↔[.256] 振荡 vs sqrt 阻尼 1 步收敛 RC 全 0.333）。
- **实现（additive+行为修正）**：PortfolioOptimizationError；risk_parity→ERC（sqrt 阻尼·对角退化逆波动·非 PSD 回落暖启不崩）；mean_variance 不收敛 raise；optimize_portfolio try/except 标 mvo_not_converged + 等权回退；docstring 诚实。
- **对抗 + 变异**：+4 测试。MUT-#3（退回逆波动）→ ERC RC 不均红、旧 inverse_sigma 仍绿（向后兼容）；MUT-#5（静默回退）→ raise/violation 2 测红；定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：portfolio 13 passed（+4）；**全量后端 1653 passed / 13 skipped / 0 failed / 233s**（基线 1649，净 +4）。
- **03b1cf47 残（#6）**：risk_summary 单支 DSR 即 ok vs 权威 gate（PBO 缺→yellow）——与既有测试 test_gate_brings_risk_summary_alive 意图冲突=display 宽松度=**用户方法学拍板**，池卡留（不替拍）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
