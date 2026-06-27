---
uuid: f6d7a3b8a1d24a79b5970c5e8a3f0b16
title: Model governance monitoring and recertification records
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-model-governance
source: goal-gap
source_ref: GOAL §14/§15 Model monitoring profile and recertification records
depends_on: [e4f2a1c9a0c54e0fb624b1dcb8a0c4d7]
completed_at: 2026-06-27
---

# Model governance monitoring and recertification records

## Scope [必填]
把 GOAL §15 的 `MonitoringProfile` 与 `RecertificationRecord` 从文档名词升级为 first-class append-only runtime record：可通过 persistent model governance registry 写入、replay、查询，并通过 backend API 创建和在 summary 中审计。

## 上下文 / 动机 [按需]
`6c3d8f21` / `e4f2a1c9` 已把 Model Registry promotion 成功和拒绝事实写入 Model QRO。模型上线后的监控与再认证仍缺可验证对象。本卡先补治理 record 层，让模型监控配置和再认证事件有确定 id、passport/version 绑定、trigger gate、append-only history 和 API 读面。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/model_governance.py` | 新增 `ModelMonitoringProfile`、`ModelRecertificationRecord`、parser、append-only event replay、registry write/read API 和 passport/trigger gate |
| `app/backend/app/research_os/__init__.py` | 导出 monitoring/recertification 类型与 parser |
| `app/backend/app/main.py` | 新增 monitoring profile / recertification record 创建 endpoint，并扩展 model governance summary |
| `app/backend/tests/test_model_governance.py` | 覆盖 registry replay、API success、未声明 recertification trigger fail-closed |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Monitoring profile 必须引用存在且匹配的 ModelPassport / ModelVersion。
2. Monitoring profile 必须带 metrics、schedule、alert policy；recertification triggers 必须来自 passport 声明。
3. Recertification record 必须引用存在且匹配的 passport，trigger 必须已声明，decision 只能是 `accepted` / `rejected` / `waived`。
4. Registry 重启 replay 后 monitoring profile 与 recertification record 必须仍可查。
5. API summary 必须返回 refs/ids/decision，不复制 artifact 或模型二进制内容。

## 红线 [按需]
- 不允许绕过 ModelPassport / ModelVersion 匹配关系。
- 不允许接受未声明 recertification trigger。
- 不允许把 monitoring profile 或 recertification record 说成 runtime serving 已接。
- 不允许把 raw model artifact、artifact path 或 serving secret 写入 summary。

## 非目标 [按需]
不实现 runtime serving，不实现独立 sandbox artifact inspection process，不实现 remote artifact store，不实现 runtime auto-promotion，不实现 live model serving，不实现外部监控系统接线或自动再训练。

## 验收一句话 [必填]
Model governance registry/API 现在能写入、replay 和审计 `ModelMonitoringProfile` 与 `ModelRecertificationRecord`；未声明 trigger 或 passport/version 不匹配会 fail-closed。

## 完成记录（2026-06-27）
- 新增 first-class `ModelMonitoringProfile` 与 `ModelRecertificationRecord`，id 由内容确定。
- `PersistentModelGovernanceRegistry` 支持 `model_monitoring_profile_recorded` 与 `model_recertification_recorded` event replay。
- 新增 `/api/research-os/model_governance/monitoring_profiles` 与 `/api/research-os/model_governance/recertification_records`，summary 返回 profile/record totals 和 refs。
- 本地验证：
  - `python -m pytest app/backend/tests/test_model_governance.py -q` -> 23 passed / 2 warnings。
  - `python -m pytest app/backend/tests/test_training_api.py app/backend/tests/test_training_service.py app/backend/tests/test_model_governance.py app/backend/tests/test_model_desk_m2.py app/backend/tests/test_research_graph_persistence.py app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_entrypoint_gate_coverage.py app/backend/tests/test_research_os_spine.py app/backend/tests/test_goal_coverage.py app/backend/tests/test_platform_coverage.py app/backend/tests/test_engineering_standards.py -q` -> 130 passed / 2 warnings。
  - `python -m compileall app/backend/app` -> PASS。
  - `python dev/scripts/validate_dev.py` -> 49 ✅ / 0 ❌ / 0 ⚠️；DAG 150 卡。
