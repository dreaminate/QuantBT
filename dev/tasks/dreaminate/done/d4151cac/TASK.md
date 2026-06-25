---
uuid: d4151cacf5b94e4aba83f2139c23df6e
title: 生产 HRP 走审计安全版——奇异协方差 fallback ladder 接进 optimize_portfolio（岛→消费·透明降级）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: eval-methodology
source: audit-finding
source_ref: 第二轮 correctness 审计（workflow wnbmpeqiv）#7（optimize_hrp_safe 孤岛·lev 5）
depends_on: []
---

# 生产 HRP 走审计安全版——奇异协方差 fallback ladder 接进生产

## Scope [必填]
经学术审计的 `optimize_hrp_safe`（奇异性检测 + Ledoit-Wolf 收缩 + fallback 阶梯 HRP→hrp_shrunk→risk_parity→equal）
是**孤岛**——仅测试消费；生产 `optimize_portfolio` 的 hrp 分支用裸 `hrp_weights`（无任何防御）。近奇异协方差
（资产多于样本 / 高相关簇，真组合常见）下裸 HRP 距离矩阵退化 → 权重 NaN / 极端集中。本卡把生产 hrp 接进审计安全版。

## 数学先行（为何裸 HRP 在奇异协方差崩 + 阶梯如何兜）[必填]
- **退化机理**：HRP 用 corr→distance=√((1−corr)/2)→linkage 树；corr≈1（共线簇）→ distance≈0 → linkage 树不稳、
  recursive bisection 的 cluster variance ≈0 → 权重 NaN / 极端集中。
- **审计阶梯**：`is_near_singular`（相对判据 min_eig<threshold·max_eig ∨ cond>1e10 ∨ min_eig≤0）检测 → 奇异则
  Ledoit-Wolf 收缩 cov_shrunk=(1−α)Σ+α·tr(Σ)/N·I 正则化（α=0.3）再 HRP；仍奇异 → risk_parity；再不行 → equal_weight。
- **透明**：fallback_used≠"hrp" 时把 `hrp_fallback:{used}` 标进 PortfolioResult.constraint_violations（绝不静默降级·同 MVO 透明原则）。

## 治理（护栏·correctness）[必填]
- 纯 correctness 鲁棒性（消费已审计的安全版·岛→消费），不涉用户方法学（阈值用审计默认）。透明标记非设卡。
- **扩展不替换**：抽 `_safe_hrp_from_cov`（cov-based ladder·behavior-preserving·optimize_hrp_safe 与 optimize_portfolio 共用），
  裸 `hrp_weights` 保留（向后兼容·别处或仍引）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| portfolio/hrp_audit.py | 抽 `_safe_hrp_from_cov(cov,...)`（从 optimize_hrp_safe 的 cov-ladder·行为保持） | additive 重构 |
| portfolio/optimizers.py | optimize_portfolio hrp 分支 → `_safe_hrp_from_cov(cov)`；fallback 标进 violations（n≤1 退等权） | additive |
| app/backend/tests/test_portfolio.py | +2 测试 | additive |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **奇异协方差鲁棒**：完全共线 cov（corr=1·min_eig=0）经 optimize_portfolio('hrp') → 权重全有限 + sum≈1 + 透明标 `hrp_fallback:*` → MUT（退回裸 hrp_weights）→ 无 fallback 标记/不稳 → 红 ✓
2. **非奇异不误标**：_toy_cov（健康）→ fallback_used="hrp"、无 hrp_fallback violation（向后兼容）。
3. **抽取行为保持**：test_academic_audit_v2（optimize_hrp_safe returns-based）+ dispatch 测试仍绿。

## 验收一句话 [必填]
生产 HRP 接进审计安全 fallback ladder（奇异检测+Ledoit-Wolf 收缩+降级·近奇异协方差不再 NaN/极端集中）+ fallback 透明标 violation；
保裸 hrp_weights 与既有测试；MUT 抓；全量后端 1657 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-HRP-SAFE）
- **审计驱动（第二轮 #7·lev 5·岛→消费）**：optimize_hrp_safe 仅测试消费、生产 hrp 用裸 hrp_weights。读 hrp_audit/optimizers 原文复核坐实。
- **实现（抽取+wire）**：抽 `_safe_hrp_from_cov`（cov-ladder·optimize_hrp_safe 算 cov 后调它·行为保持）；optimize_portfolio hrp 分支喂 covariance.values → 安全版 → fallback 透明标 violations；n≤1 退等权。
- **测试纠偏教训**：初版 _singular_cov 用 corr=0.99999 未触发——is_near_singular 是**相对**判据（min_eig<threshold·max_eig），corr=0.99999 的 min_eig/max_eig≈1.3e-6 不够；改用**完全共线**（corr=1·min_eig=0→`min_eig≤0` 必判奇异）才稳定触发。
- **对抗 + 变异**：+2 测试。MUT（hrp 退回裸 hrp_weights）→ 奇异 cov 无 fallback 标记红；定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：portfolio+hrp_audit 43 passed（+2）；**全量后端 1657 passed / 13 skipped / 0 failed / 186s**（基线 1655，净 +2）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
