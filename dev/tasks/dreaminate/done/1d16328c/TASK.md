---
uuid: 1d16328c71914babb772fa899b753c07
title: GOAL 0-17 第一主线——QRO/Research Graph/Mathematical Spine runtime contract
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: research-os-spine
source: goal-gap
source_ref: 2026-06-26 /goal implement GOAL §0-§17
depends_on: []
---

# GOAL 0-17 第一主线——QRO/Research Graph/Mathematical Spine runtime contract

## 完成记录
- 新增 `app/backend/app/research_os/spine.py` 与包入口，定义 QRO 类型、分离状态轴、Research Graph canonical command、Mathematical Spine binding/check、MethodologyChoice/Responsibility 记录和 promotion guard。
- 新增 `app/backend/tests/test_research_os_spine.py`，覆盖绕命令、状态轴假绿灯、user waiver overclaim、缺 TheoryImplementationBinding/ConsistencyCheck、production mock fallback。
- 验证：`cd app/backend && python -m pytest tests/test_research_os_spine.py -v` → 8 passed。

## Scope [必填]
建立第一条可执行 runtime 脊柱：QRO 状态轴、Research Graph canonical command、Mathematical Spine 产物、TheoryImplementationBinding、ConsistencyCheck、MethodologyChoiceRecord、ResponsibilityDisclosureRecord 和 promotion guard。它覆盖 GOAL §1/§6/§8/§10/§13/§16/§17 的共同硬门：正式入口不能绕 Research Graph；理论/实现不一致不能冒充 proof-backed；user waiver 不能包装成强证据；production-ready 不能带 mock fallback。

本卡不是声称 0-17 全部完成，而是给后续 §4 数据接入、§5 RAG、§9 因子轨、§15 模型治理、§17 RDP 打同一运行时契约地基。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/research_os/spine.py | 新模块 | QRO / Research Graph / Mathematical Spine / MethodologyChoice / promotion guard |
| app/backend/tests/test_research_os_spine.py | 新测试 | 对抗测试：绕命令、合轴假绿灯、缺 binding、user waiver overclaim、production mock fallback |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Canvas upsert 缺 QRO payload → 拒。
2. 状态轴必须分开，evidence sufficient 不能把 governance/runtime 一起染绿。
3. user_waived_theory 缺 skipped_steps → 拒；有 waiver 也不能 evidence_sufficient/proof_backed。
4. 声称 theory-backed 但缺 TheoryImplementationBinding / ConsistencyCheck → 拒。
5. production_ready 带 mock/fallback profile → 拒。

## 验收一句话 [必填]
GOAL §1/§6/§8/§16/§17 的第一条 runtime 契约有代码、有对抗测试；后续入口必须复用这套对象和 guard，不再各自维护真相。
