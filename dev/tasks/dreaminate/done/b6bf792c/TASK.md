---
uuid: b6bf792ce773409b812fea2011441d97
title: Methodology validation depth registry and API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-methodology-validation
source: goal-gap
source_ref: GOAL §10 methodology validation depth; GOAL §8 governance spine; GOAL §16 no silent mock fallback
depends_on: []
completed_at: 2026-06-27
---

# Methodology validation depth registry and API

## Scope [必填]
新增 GOAL §10 validation-depth runtime record、append-only registry 和 FastAPI 写面，记录 CPCV + walk-forward 双轨、conformal/abstain、TCA/cost、feature-level leakage probe、fault injection 和 recovery drill 的 evidence refs / validation refs，缺项或失败时不能写入 accepted record。

## 上下文 / 动机 [按需]
现有 `ValidationMethodologyRecord` 已能挡短样本强结论、缺 PBO/DSR/bootstrap/honest-N/multiple testing、缺成本模型和 user-waived 强证据包装，但状态文件仍把 CPCV 双轨、conformal/abstain、TCA、feature-level leakage probes、故障注入与恢复演练列为 §10 缺口。本卡补第一条可持久化 record/API，不把外部计算结果伪造成已执行。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/methodology_validation.py` | 新增 `ValidationDepthRecord`、`validate_validation_depth()`、`PersistentValidationDepthRegistry` 和 JSONL replay |
| `app/backend/app/research_os/__init__.py` | 导出 validation-depth record / registry / validator |
| `app/backend/app/main.py` | 新增 `VALIDATION_DEPTH_REGISTRY`、`POST /api/research-os/methodology/validation_depth_records`、`GET /api/research-os/methodology/summary` |
| `app/backend/tests/test_methodology_validation.py` | 覆盖 validator、registry replay、API 成功和失败不落盘 |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档验证深度边界和本地 proof |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. strong/evidence-sufficient record 缺 walk-forward、conformal、abstain、feature leakage probe 时必须拒绝。
2. paper/testnet/live/production record 缺 TCA/cost、fault injection 或 recovery drill refs 时必须拒绝。
3. feature leakage、fault injection 或 recovery drill verdict 非 passing 时必须拒绝。
4. user-waived path 不能标成 proof-backed/evidence-sufficient/production-ready，且必须有 MethodologyChoice / Responsibility refs。
5. silent mock fallback 必须拒绝，API 失败不能写 JSONL partial record。

## 红线 [按需]
- 不声称系统已真实运行 CPCV、conformal、TCA 或故障演练；record 只绑定外部验证产物 refs。
- 不把失败/缺项/user-waived 记录包装成强证据。
- 不新增绕过 validator 的 summary 或写面。

## 非目标 [按需]
不实现 CPCV/conformal/TCA 计算器、不跑真实 broker/venue fault drill、不接 production scheduler、不补完整 validation dossier UI、不做 CI/线上验证。

## 验收一句话 [必填]
方法学验证深度可以作为 append-only 证据记录被 API 写入和 replay，缺 CPCV+walk-forward/conformal/abstain/TCA/leakage/fault/recovery evidence 时 fail-closed。

## 完成记录
- 新增 `ValidationDepthRecord`，显式记录 dual-track validation、conformal/abstain、TCA/cost、feature leakage probe、fault injection、recovery drill、evidence refs 和 validation result refs。
- `validate_validation_depth()` 会拒绝 strong label 缺 dual-track/conformal/abstain/leakage proof、runtime candidate 缺 TCA/cost/fault/recovery proof、非 passing verdict、silent mock fallback、user-waived strong overclaim。
- 新增 `PersistentValidationDepthRegistry`，以 JSONL append-only 方式保存和 replay `validation_depth_recorded` event；无效记录不写文件。
- 新增 `/api/research-os/methodology/validation_depth_records` 和 `/api/research-os/methodology/summary`，写入前先走 validator，summary 只返回 refs/verdict，不返回 raw payload。
- 验证：`pytest app/backend/tests/test_methodology_validation.py -q` → **13 passed / 2 warnings**；`pytest app/backend/tests/test_methodology_validation.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_trust_layer.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_governed_compiler.py -q` → **52 passed / 2 warnings**；`python -m compileall -q app/backend/app` → PASS。
