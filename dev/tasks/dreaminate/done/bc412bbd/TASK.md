---
uuid: bc412bbd06814e499c628197a7e2df2f
title: GOAL §17 Research Delivery Package manifest gate
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: research-os-rdp
source: goal-gap
source_ref: 2026-06-26 /goal implement GOAL §17
depends_on: [1d16328c71914babb772fa899b753c07]
---

# GOAL §17 Research Delivery Package manifest gate

## 完成记录
- 新增 `app/backend/app/research_os/rdp.py`，提供 `RDPManifest`、`manifest_from_qro`、`validate_rdp_manifest` 和开放 JSON 输出。
- 新增 `app/backend/tests/test_research_os_rdp.py`，覆盖 DatasetVersion/repro command、未验证残余、user waiver 责任记录、live deployment/monitor/rollback/retire 清单缺失。
- 验证：`cd app/backend && python -m pytest tests/test_research_os_rdp.py -v` → 5 passed；`cd app/backend && python -m pytest tests/test_research_os_spine.py tests/test_research_os_rdp.py -v` → 13 passed。

## Scope [必填]
给正式 Research Delivery Package 建立后端 manifest 与 validator：研究命题、Research Graph、数据/PIT、DatasetVersion、IngestionSkill、数学定义、TheoryImplementationBinding、ConsistencyCheck、MethodologyChoice、Responsibility、代码/环境/hash/seed、reproducibility command、测试、run、honest-N、成本假设、归因、已知限制、未验证残余、verifier verdict、approval、deployment/monitor/rollback/retire 清单都必须有位置。缺关键字段时拒绝，不允许把一张图或一段代码包装成正式交付。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/research_os/rdp.py | 新模块 | RDPManifest / manifest_from_qro / validate_rdp_manifest |
| app/backend/tests/test_research_os_rdp.py | 新测试 | 缺 DatasetVersion、repro command、未验证残余、waiver 责任记录、live 清单时必须红 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. RDP 缺 DatasetVersion 或 reproducibility command → 拒。
2. RDP 缺未验证残余 → 拒。
3. user waiver 交付缺 MethodologyChoice / Responsibility refs → 拒。
4. live RDP 缺 deployment / monitor / rollback / retire 清单 → 拒。

## 验收一句话 [必填]
RDP 不再只是 GOAL 文字，有可执行 manifest gate；正式交付缺关键证据和复现字段时测试会红。
