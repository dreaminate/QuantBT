---
uuid: a8f3c1d29e7b4f0c8a1d3e6b2f9c5d04
title: §8 治理脊柱门 advisory 接进 agent orchestrator Review 路径（D-GOV-ADVISORY·孪生 §13·LINE-§8）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: governance
source: goal-gap
source_ref: GOAL §8 治理脊柱硬不变量（行 1346 起）+ §7（行 1119）；第八波 GovernanceSpineGate（卡 d904b8d9·spine_invariants.py）建好但全 app 零消费方=孤岛，与第十三波 §13 trust 接 orchestrator（卡 e4f1a2b3）完全平行的「门→orchestrator advisory」缺口
depends_on: [d904b8d998d249728db742a62d12c350, e4f1a2b3c5d64e7f8a9b0c1d2e3f4a5b]
---

# §8 治理脊柱门 advisory 接进 agent orchestrator Review 路径（D-GOV-ADVISORY）

## Scope [必填]
第八波建的 §8 `GovernanceSpineGate`（`app/governance/spine_invariants.py`·7 条 clause 统一核查门·`evaluate(SpineEvidence)→SpineVerdict`）此前**全 app 零消费方=孤岛**——agent 产出/计划/代码变更没经 §8 治理脊柱核查。本卡把它**advisory-first 接进 orchestrator 的 Review 形态**，与第十三波 §13 `advise_trust`（卡 e4f1a2b3·`trust_advisory.py`）**完全平行的孪生范式**：
① 新建 `app/agent/orchestrator/governance_advisory.py`（镜像 trust_advisory.py）：`GovernanceAdvisory` 结构化结果 + 委派 `GovernanceSpineGate.evaluate`（判定零重写）+ 可见事件投影；
② orchestrator.py Review 形态加 `advise_governance(ctx)→GovernanceAdvisory`（紧挨 advise_trust·additive 扩展不替换）；
③ **advisory-first**：软门违反只 flagged + 投影事件、**绝不阻断** orchestrator 主流程；命门（secret/safety clause）照门真实行为接（若 raise 则不吞·原样 re-raise·投不变量名）。

## 上下文 / 动机 [按需]
卡 d904b8d9 把 §8 治理脊柱七条硬不变量立成统一核查门，但 CEO/收敛评审同 §13 同病：门建好无生产消费者。第十三波已用 advisory-first 把 §13 trust 接进 orchestrator（不阻断主流程·命门硬守·只投不变量名不回显 target），本卡照同一已验证范式接 §8。GOAL §8 是写死契约（硬不变量·非方法学松紧），直接建不问。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| app/governance/spine_invariants.py | 已建 | 复用 GovernanceSpineGate.evaluate，不改门内部 |
| app/agent/orchestrator/governance_advisory.py | 新建 | 镜像 trust_advisory.py·委派门·投影·advisory-first |
| app/agent/orchestrator/orchestrator.py | advise_trust 旁 | 加 advise_governance(ctx)→GovernanceAdvisory（additive） |
| app/agent/orchestrator/events.py | 复用 | VerifierChallengeRaised/FailureDetected 投影 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 违反某 clause 的 evidence（agent_plan 违反 / code_change 无 test_ref / role_action 越权）→ advise_governance 必 flagged=True + 投对应事件，**但 orchestrator 主流程不被阻断**（advisory 核心）。
2. 合法 evidence → flagged=False、不误伤正路径。
3. secret clause：带在册明文 secret 的 surface → 门裁违反 + **接线层投影/返回不含 secret 原文**（红线：key 不进日志/导出·投影载荷 grep 无 secret 子串）。
4. 命门（若 evaluate 对某 clause raise）→ 本层不吞 + re-raise + 投不变量名（不降级硬墙成 advisory）。
5. MUT 三态（in-place Edit·非 git checkout）：advisory 改洗白（恒 allowed=True 不真跑门）→ 违反测试转红（证门有牙非桩）→ 手工复原 → 全绿。

## 验收一句话 [必填]
§8 治理脊柱门真接进 orchestrator Review 路径（advisory-first·软门只标记不阻断·命门硬守不降级·secret 不回显），判定零重写全委派 GovernanceSpineGate，不破基线与现有闸门。

## 完成纪要（done · 第十四波 · 中心整合）
**攻入点**：orchestrator 的 Review 形态新增 `advise_governance(evidence: SpineEvidence) -> GovernanceAdvisory`，与第十三波 `advise_trust` 平行。

**交付**：
- 新增 `app/backend/app/agent/orchestrator/governance_advisory.py`：`run_governance_advisory` 全权委派 `GovernanceSpineGate.evaluate`，只负责 advisory 标记和事件投影。
- 扩展 `app/backend/app/agent/orchestrator/orchestrator.py`：新增 `AgentOrchestrator.advise_governance`，不改 `plan / dispatch / replay / repair` 主流程。
- 扩展 `app/backend/app/agent/orchestrator/__init__.py`：导出 `GovernanceAdvisory / GOVERNANCE_ADVISORY_SOURCE / run_governance_advisory / summarize_governance_for_event`。
- 新增 `app/backend/tests/test_governance_orchestrator_advisory.py`：14 条对抗测试。

**advisory-first 纪律**：
- §8 七条硬不变量违反只 `flagged=True` + 投影 `VerifierChallengeRaised`，不阻断 orchestrator 主流程。
- 判定零重写：不重写 clause 逻辑，全部委派已建 `GovernanceSpineGate.evaluate`。
- secret 不回显：事件和 `to_dict()` 只暴露 clause id、bool、计数；不投 evidence surface、`verdict_text`、`violation` 文本。
- defense-in-depth：若底层未来以 `SecretLeakError` 硬停，本层投 `FailureDetected` 且只投 `INV_SECRET_PLAINTEXT` 后原样 re-raise，不吞成 advisory。

**scoped 验证（中心实跑）**：
- `python -m pytest tests/test_governance_orchestrator_advisory.py -q --timeout=120` -> 14 passed。
- `python -m pytest tests/test_trust_orchestrator_advisory.py -q --timeout=120` -> 17 passed。
- `python -m pytest tests/test_governance_spine.py -q --timeout=120` -> 30 passed。
- `python -m pytest tests/test_agent_orchestrator.py -q --timeout=120` -> 47 passed。
- MUT 三态：临时把 `run_governance_advisory` 返回值改为 `flagged=False` -> `test_advisory_flags_plan_missing_acceptance_gates` 红（1 failed），恢复 `flagged=not verdict.allowed` -> 新增测试 14 passed。
- 后端全量：`python -m pytest -q --timeout=120` -> 2706 passed, 13 skipped, 284 warnings in 117.30s。

**诚实残余 / follow-on**：
- free-text -> `SpineEvidence` 映射未做；本层只吃调用方显式构造的结构化 evidence。
- 接 main.py 真 agent / promote 端点未做；本卡只把 §8 门接进 Review 形态。
- 硬 enforce 晋级未做；当前仍是 advisory-first，后续须等输入证据完整后单独评估。
