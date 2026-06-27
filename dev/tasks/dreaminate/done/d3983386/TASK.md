---
uuid: d3983386340b4fd797850c809356adfe
title: Methodology CPCV conformal and TCA calculators
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-methodology-calculators
source: goal-gap
source_ref: GOAL §10 CPCV/conformal/TCA calculator gap
depends_on: [b6bf792ce773409b812fea2011441d97]
completed_at: 2026-06-27
---

# Methodology CPCV conformal and TCA calculators

## Scope [必填]
为 GOAL §10 增加本地 CPCV、conformal 和 TCA calculator record 层。API 接收数值序列，计算 refs/hash/摘要，并以 append-only JSONL 记录 calculator output。审计记录保存 sample/count/mean/threshold/cost summary 和 `source_hash`，不持久化 raw fold/calibration/gross-return arrays。

## 上下文 / 动机 [按需]
`b6bf792c` 已要求 ValidationDepthRecord 引用 CPCV、walk-forward、conformal、TCA 等 refs，但没有 producer。TRACE §10 仍写着 CPCV/conformal/TCA 计算器待补。该卡补本地 calculator producer，不把 refs-only gate 当成真实计算。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/methodology_validation.py` | 新增 CPCV/Conformal/TCA calculator record、validation、calculate helpers 和 persistent registry |
| `app/backend/app/main.py` | 新增 `/api/research-os/methodology/cpcv`、`/conformal`、`/tca`，summary 返回 calculator totals |
| `app/backend/tests/test_methodology_validation.py` | 覆盖计算结果、raw series 不入记录、registry replay、API summary 和 silent mock no-write |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. CPCV 少于两个 fold 拒绝。
2. Conformal calibration 少于五个观测或 alpha 非法拒绝。
3. TCA 缺 cost_model_refs 或负成本拒绝。
4. silent mock fallback 一律 422/no-write。
5. JSONL 不保存 raw fold/calibration/gross-return arrays，只保存 source hash 和摘要。

## 红线 [按需]
- 不把这些本地计算器说成完整 validation dossier UI。
- 不把简化 CPCV/conformal/TCA 摘要说成覆盖全部统计方法学。
- 不把本地 pytest 说成 CI、线上或用户验收。

## 非目标 [按需]
不实现完整 CPCV path enumeration、walk-forward scheduler、broker/venue fault drill、完整 TCA market simulator、validation dossier UI 或所有生产者自动接线。

## 验收一句话 [必填]
GOAL §10 现在有可 replay 的本地 CPCV/conformal/TCA calculator producers，ValidationDepthRecord 不再只能引用手填 refs。

## 完成记录（2026-06-27）
- 新增 `CPCVCalculatorRecord`、`ConformalCalculatorRecord`、`TCACalculatorRecord` 和 `PersistentMethodologyCalculatorRegistry`。
- 新增 calculator API，成功路径持久化 refs/hash/摘要，失败路径 no-write。
- 本地验证：
  - `python -m pytest app/backend/tests/test_methodology_validation.py -q` -> 16 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_methodology_validation.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp.py -q` -> 82 passed / 2 warnings。
  - `python -m pytest app/backend/tests -q` -> 1835 passed / 13 skipped / 283 warnings。
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️）。
  - `git diff --check` -> PASS。
