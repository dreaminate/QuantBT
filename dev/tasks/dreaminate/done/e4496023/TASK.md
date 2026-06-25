---
uuid: e4496023a0994583955ef00f00d319a2
title: 因子收益归因接消费侧（组合台/归因报告 + UI 呈现）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: eval-methodology
source: goal-gap
source_ref: done 卡 ff286f80（attribution math 件）的消费侧残余
depends_on: [ff286f80af1546bfaaea9ce0a6feb9b2]
---

# 因子收益归因接消费侧

## Scope [必填]
`eval/attribution.py`（done 卡 ff286f80）已建并验证（加总恒等式命门 + 诚实 abstain），但**纯 math 件、无消费侧**。
本卡合拢价值闭环：
① 组合台/归因报告：接真组合实现收益 + 因子收益矩阵 → `factor_return_attribution` → 各因子贡献 + 特异 + R²；
② 前端呈现：贡献瀑布/堆叠 + R²（因子解释占比）+ abstain（证据不足/共线）诚实呈现（不假绿灯：低 R² 不渲染成「已归因」、insufficient/collinear 显证据不足非假 β）。

## 上下文 / 动机 [按需]
**用户方法学决策（不替拍）**：因子集选哪些（风格/行业/自定义）、收益口径（excess vs raw）、回归窗（全样本 vs 滚动）—— 用户那摊；本件提供机制 + 恒等式守正确，松紧用户定。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| (组合台后端端点) | 取组合收益 + 因子收益 → factor_return_attribution | 新增 |
| (前端归因卡) | 贡献分解 + R² + abstain 呈现（--cc-*/--desk-* 对齐宿主） | 新增 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 端点输出 contrib 加总恒等式不破（绑 math 件命门）。
2. 低 R²/insufficient/collinear → UI 诚实呈现（证据不足非假 β、低解释占比不渲染成「已归因」绿）。

## 验收一句话 [必填]
因子收益归因接组合台 + 归因报告 UI（贡献分解 + R² + abstain 诚实呈现），加总恒等式端到端不破、不假绿灯。

## 完成记录（2026-06-26 · wave6 / deep-opus 隔离 worktree·中心整合 land）
合拢 ff286f80 math 件的消费侧价值闭环（复用 `factor_return_attribution`，**不改 math**）：

**后端（消费报告构建器，扩展不替换·不碰 main.py）**
- 新建 `app/backend/app/eval/attribution_report.py::build_factor_attribution_report`：接组合实现收益 + 用户所选因子收益矩阵 → 调 math → 产 **JSON-safe** 报告（各因子贡献 + 特异 + R² + **消费层加总恒等式自检** `identity.holds/residual` + 诚实 `evidence_state` + **单一源 note**）。nan→None 严格 JSON-safe。
- **不假绿灯**：abstain（insufficient/collinear）→ `evidence_state` 落 abstain 家族、betas 空（不二次编造 β）；低 R²/R² 无定义 → `specific_driven`、**绝不** `factor_explained`；解释占比为拟合度、非策略质量结论。
- **方法学不替拍**：因子集 / 收益口径(excess·raw) / 回归窗(full·rolling) 原样回显；`low_explained_floor` 仅驱动「解释占比低」弱点警示（可覆盖、绝不阻断/伪造）。
- 端点路由（main.py `@app.<method>` 单体·禁区）由**中心补一行薄路由**调本构建器（与 `get_run_attribution_response` 同范式）。

**前端（旁挂独立卡·app/frontend·不碰任一 RunDetailPage）**
- 新建 `app/frontend/src/components/FactorAttributionCard.tsx`：贡献分解（β×Σ因子收益 堆叠/瀑布条·正负分色）+ 特异行 + R² 解释占比 + **加总恒等式 footer（命门可见·渐进披露）** + abstain 警示面板 + note 原样渲染 + 方法学口径回显。data-prop 驱动、`dataSource=mock|live` 诚实角标，镜像 RunVerdictCard 范式。
- **不假绿灯（结构性）**：四态 evidence pill **无一处成功绿 token**（源码扫描守）——可解释只落中性 text-soft（镜像 ColdStartStat「充分」用中性色先例），弱点落 warning；abstain 不渲 β/贡献条；低 R² 标「特异驱动·归因弱」。零裸 hex（全 var(--desk-*)）。

**验证（worktree 隔离·只跑 scoped）**
- 后端 `pytest tests/test_attribution_report.py tests/test_attribution.py` → **17 passed**（9 新报告 + 8 既有 math）。全量 `--collect-only` → **2199 collected**（基线 ~2190·净 +9·collection 干净无 import 错）。
- 前端 `vitest run FactorAttributionCard.test.tsx` → **17 passed**；`tsc --noEmit` → **exit 0**（node_modules 从主仓库 symlink·验后清）。
- **对抗门必抓**：① 命门加总恒等式端到端（30 seed·residual≈0·consume 层独立重算）② 低 R²→specific_driven 绝不 factor_explained（数据层 + UI 层双门）③ abstain 不渲 β/不上绿（insufficient/collinear MUT）④ anti-green 全态扫荡 + 源码无 success token ⑤ note 单一源原样渲染 + R7 措辞门（后端+前端双守）⑥ 不 import 冻结页 + 零裸 hex。

**红线合规**：扩展不替换✓ · 复用 attribution math 不改✓ · 不碰 main.py/两个 RunDetailPage/eval __init__/其他在飞线✓ · 不假绿灯（低 R²/abstain 诚实·无 success-green）✓ · 因子集口径=用户方法学原样回显不替拍✓。

**诚实残余（交中心）**：端点路由须中心在 main.py 补一行（`build_factor_attribution_report` 即用，签名见模块 docstring·组合收益可经现有 `portfolio.gate.portfolio_net_returns` 取、因子矩阵走请求体=用户因子集）；前端卡未挂载进任何页（standalone·中心按 组合台/归因报告台 位置挂载）。
