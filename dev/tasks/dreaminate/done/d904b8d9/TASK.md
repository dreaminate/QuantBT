---
uuid: d904b8d998d249728db742a62d12c350
title: 治理脊柱收口门——§8 硬不变量统一核查（CanvasMutation⇒canonical command/SecretPlaintext⇒Settings/AgentDataAccess⇒SecretRef）（§8）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: governance
source: goal
source_ref: GOAL §8 治理脊柱(行 1346-1453·硬不变量:CanvasMutation⇒canonical versioned command·AgentAction⇒scoped permission+tool record+no secret exposure·AgentPlan⇒todo+deps+acceptance gates·AgentCodeChange⇒diff+test+rollback·RoleAgentAction⇒visible event+audit·SecretPlaintext⇒Settings/Secrets only·AgentDataAccess⇒SecretRef only)
depends_on: []
---

# 治理脊柱收口门（§8·硬不变量统一核查·收编已建 enforcement）

## 结论（done）
建成 §8 **治理脊柱硬不变量统一核查门**：新 greenfield 包 `app/backend/app/governance/`，把 GOAL §8 治理脊柱
**七条**硬不变量（agent / canvas / secret / event 一脉）聚合成一道**可证伪的统一核查门**——任一硬不变量违反 → 拒。
**收编只读**各已建 enforcement（A-CMD / Orchestrator 派发闸 / plan 门 / EventProjector / call_record secret 门 /
keystore / credential_pool SecretRef），**绝不重造**；诚实标注「全权收编已 enforce」vs「本门聚合补的真缺口」。
scoped 测试 30 passed；全量 collect-only 2490（基线 ~2460 + 本卡 30·未破基线）。

## 第一步实证：§8 七条硬不变量各被哪已建件 enforce（grep + 读源·非索引）
| # | 硬不变量 | 收编的已建 enforcement | 状态 |
|---|---|---|---|
| ① | CanvasMutation ⇒ canonical versioned command | `command/canonical_command.py` `CommandBus.assert_single_channel`（图命令账 ⊄ 通道账 → ChannelBypassViolation）+ `assert_content_addressed` | **全权已 enforce**（delegated） |
| ② | AgentAction ⇒ scoped permission + tool record + no secret | `agent/orchestrator/governance.py` `GovernedToolDispatcher`：越权/绕 DAG 留 ToolViolation·每派发落 ToolCallRecord | scoped perm + tool record **全权已 enforce**；**no-secret-exposure 是真缺口**（mixed·见下） |
| ③ | AgentPlan ⇒ todo + deps + acceptance gates | `agent/orchestrator/plan.py` `AgentPlan.validate/is_ready`（缺三者/悬空依赖 → 维持 draft·不晋升） | **全权已 enforce**（delegated） |
| ④ | AgentCodeChange ⇒ diff + test + rollback | `agent/orchestrator/plan.py` `AgentCodeChange.__post_init__`（缺三者 → AgentCodeChangeError） | **全权已 enforce**（delegated） |
| ⑤ | RoleAgentAction ⇒ visible event + audit record | `agent/orchestrator/events.py` `EventProjector`（24 可见事件 + `assert_event_clean`）；audit = ToolCallRecord / CommandLedger | 可见事件面**全权已 enforce**；「可见 ∧ 留痕双在」联合判定是**本门聚合 join**（mixed） |
| ⑥ | SecretPlaintext ⇒ Settings/Secrets only | `llm/call_record.py` `assert_no_plaintext_secret` / `scan_messages_for_secret` + `security/keystore.py` `SecureKeystore`（永不落 YAML/DB/日志） | **全权已 enforce**（delegated） |
| ⑦ | AgentDataAccess ⇒ SecretRef only | `llm/credential_pool.py` `SecretRef`（`secretref://provider/name` 受控引用·绝非明文·repr 不泄露） | **结构层已 enforce**（delegated） |

诚实点名：GOAL §8 治理脊柱里还有**数学一脉**（TheoryClaim⇒MathematicalArtifact / TIB⇒ConsistencyCheck /
ImplementationClaim⇒consistency_verdict）由 `lineage/spine_gate.py` 另门 enforce、**approver≠creator** 由
`approval/gate.py`（`ApproverEqualsCreator`）enforce、**LLMCallRecord 必填 / AgentLLMCall⇒Gateway / Verifier 独立性**
由 `llm/gateway.py`+`call_record.py` enforce——**均不在本卡七条内·本门不掺手不重造**（无新公式→不造 MathematicalArtifact）。
命名澄清：本包 `app/governance/`（§8 治理脊柱）与既有 `lineage/spine*`（§6 数学脊柱）是两条不同脊柱，互不冲突。

## 领地（greenfield·只新增·扩展不替换）
- 新 `app/backend/app/governance/__init__.py`（包·re-export）
- 新 `app/backend/app/governance/spine_invariants.py`（七条统一核查门 + 收编登记 `ENFORCEMENT_BINDINGS` + 七条纯核查函数 + `GovernanceSpineGate`）
- 新 `app/backend/tests/test_governance_spine.py`（30 条对抗测试）
- **收编只读·零改动**：command/canonical_command、agent/orchestrator/{governance,plan,events}、llm/{call_record,credential_pool}、security/keystore。**未碰** main.py、被收编模块内部、其他在飞线。

## 可证伪验收（种坏门必抓·§8·MUT 全在测试内造坏 evidence·绝不 git checkout）
1. ✅ CanvasMutation 绕命令通道直写图（未落 canonical command）→ 拒（`test_canvas_mutation_bypass_rejected`·收编 assert_single_channel·MUT 放过即红）。
2. ✅ AgentAction 越权派发（scoped permission 破）→ 拒（`test_agent_action_unpermitted_tool_rejected`）；暴露面夹带在册明文 secret → 拒（`test_agent_action_secret_in_exposed_payload_rejected`）。
3. ✅ AgentPlan 缺 acceptance gates（维持 draft）→ 拒（`test_agent_plan_missing_gates_rejected`）；AgentCodeChange 缺 rollback → 拒（`test_agent_code_change_missing_rollback_rejected`）。
4. ✅ SecretPlaintext 进 dict/LLMCallRecord 导出面 → 拒（`test_secret_plaintext_leak_*`）；AgentDataAccess 持明文 key / 偷渡 secret → 拒（`test_agent_data_access_plaintext_key_rejected` / `_secret_smuggled_in_payload_rejected`）。
5. ✅ 七条全齐 → 放行（`test_unified_all_invariants_present_allows`·正路径不误伤）；任一违反 → allowed=False + 点名 clause（`test_unified_any_violation_rejects_and_names_clause` / `_multiple_violations_all_reported`）。

## 测试汇总（scoped·带 timeout·凭真汇总行判绿）
- `python3 -m pytest app/backend/tests/test_governance_spine.py -q --timeout=120` → **30 passed in 0.18s**。
- 全量 `--collect-only` → **2490 tests collected**（基线 ~2460 + 本卡 30·collection 无 error·未破基线）。
- import 期自检通过：`ENFORCEMENT_BINDINGS` 恰好覆盖七条 + `CLAUSES==7`（漏标/重标即 fail-fast）。

## 红线合规（逐条）
- secret 明文只在 Settings/Secrets：✅ 本门只**逐字比对在册明文**、绝不回显/落账（拒绝文案含 `len=` 不含 secret 本身·两条 MUT 显式断言 `SECRET not in violation`）。收编 call_record + keystore，未自造 secret 后端。
- AgentDataAccess 只 SecretRef：✅ `_is_secretref` round-trip 对齐单一源 `credential_pool.SecretRef.ref`，不另立 scheme。
- 复用已建门不另造：✅ 七条全收编已建 enforcement·零重写（CanvasMutation 调 A-CMD 对账探针、AgentCodeChange 过 plan 构造门、SecretPlaintext 调 call_record 扫描门…）。
- 扩展不替换：✅ 仅新增 greenfield 包 + 测试·改动既有文件 0。
- 诚实标已 enforce vs 补缺口：✅ `ENFORCEMENT_BINDINGS` 机器可读标注 delegated/mixed；mixed 两条（②no-secret 暴露面、⑤可见∧留痕 join）即本门**唯二聚合补的缺口**，绝不冒充新建已有的。
- 先读 GOAL §8 再动手：✅。无致命错误触发（未削弱任一安全不变量·secret 明文未出 Settings）。

## 拍板项命中
无。本卡为 greenfield 收编聚合，无工程取舍待定、无与既有决策冲突的岔路（命名与 `lineage/spine*` 经核不冲突·见上）。

## 诚实残余（限界 vs 残余分清）
- **诚实限界**（设计极限·不会再改）：① 本门是**聚合核查**——按调用方提供的 evidence 判七条是否被违反，**不**自己拦截每个动作（拦截是各已建件本分·本门收编其判定）。② secret 扫描沿用「在册明文逐字匹配」口径，不识别未在册高熵串。③ ⑦ 只校验引用**形态**是 SecretRef，不核验引用真能解出 keystore 记录。
- **本门聚合补的真缺口**（mixed·已落地）：② AgentAction 暴露面 no-secret——派发闸只记工具名不扫 arg 值、事件投影只投 args_keys 不投值，故工具入参/结果里的明文 secret 现有链路无人扫；本门用单一源 `scan_messages_for_secret` 补扫。⑤ 「可见事件 ∧ audit record 双在」的联合判定——单一已建件各管一半，本门把两半并起来核。
- **诚实残余**（后续活·非本卡）：把本门接进 orchestrator 实际调用点（让每个治理动作路由过统一门）是接线卡，不在本卡 greenfield 领地；本卡交付「可证伪的聚合门 + 收编登记 + 补缺口」，接线由中心/后续卡定。
