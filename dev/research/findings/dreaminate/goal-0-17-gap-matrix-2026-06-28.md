# FINDING · GOAL §0-§17 runtime gap matrix（2026-06-28）

- **蒸馏自**:`dev/GOAL.md` §0-§17、`dev/research/TRACE.md`、`data/audit/goal_entrypoint_coverage.jsonl`、`app/backend/app/research_os/goal_coverage.py`、`app/backend/tests/test_goal_coverage.py`、本轮启动 objective。
- **证据强度**:中。GOAL 原文、validator contract 和本地 audit JSONL 已实读；完整代码全路径未逐行审完，矩阵只作为当前攻入图，不作为最终完成证明。
- **适用域**:当前 checkout `fix-u2-synth`，HEAD `5d55de3`，`origin/main` `70bacab`，本地工作区很脏且落后 `origin/main` 167；不能据此声明 CI、线上或用户验收。

## 核心主张（可证伪）[必填]
如果 QuantBT 要声称 `dev/GOAL.md` §0-§17 全实现，则必须让 section manifest 在 `claims_full_product_implementation=True` 下通过，并让 entrypoint coverage manifest 在 `claims_all_entrypoints_wired=True` 下覆盖 `chat/canvas/api/ide/scheduler/agent_shell`；当前本地 audit 只证明 `api` 覆盖 `§0/§1/§7/§8`，所以全实现声明必须继续拒绝。

## 当前硬证据
- `python dev/scripts/validate_dev.py`：**49 ✅ / 0 ❌ / 0 ⚠️**，259 卡。
- `python -m pytest app/backend/tests/test_funnel_hooks.py::test_register_emits_user_registered -q`：**1 passed / 2 warnings**，objective 里提到的 funnel 红点当前未复现。
- `data/audit/goal_entrypoint_coverage.jsonl`：577 rows；`entry_source = api` only；`goal_sections = §0/§1/§7/§8` only；`claims_full_product_entrypoint = 0`。
- `app/backend/tests/test_goal_coverage.py`：contract validator 已明确 full product / all entrypoints claim 的拒绝条件。
- `dev/research/findings/dreaminate/construction-map.md`：路径不存在，未读到该文件；不能引用它作证据。

## GOAL §0-§17 gap matrix

| GOAL | 原文验收点压缩 | 已有 runtime/API/UI/audit/test refs | 缺失 runtime | 缺失测试 | 缺失 audit/evidence refs | full_entrypoint_wired | 需新卡 | 文件领地 | 验收命令 |
|---|---|---|---|---|---|---|---|---|---|
| §0 北极星 | 所有入口能从 Chat/Canvas/API/IDE/Scheduler 产 QRO，完整 research-to-execution lifecycle 可追证据 | `goal_coverage.py`、`goal_entrypoint_coverage.jsonl`、大量 API QRO/compiler coverage；RDP/Settings/Execution 局部链路 | full product coverage manifest producer；非 API 入口 coverage producer；full lifecycle closure | full claim acceptance + mutation tests | 非 API entry_source；§2-§17 section refs | 否 | `2b1706f1` + entrypoint tasks | `research_os/goal_coverage.py`、`main.py`、entry producers | `pytest test_goal_coverage.py`; coverage summary all false→true |
| §1 统一对象模型 | Quant Intent→QRO→Graph→Compiler→Evidence/Runtime，状态轴分离 | QRO/Graph/Compiler stores、API coverage records | 所有正式入口统一强制；full section manifest wiring | non-API entry bad refs fail-closed | chat/canvas/ide/scheduler/agent_shell refs | 否 | `2b1706f1`、`6bbfa5ac`、`9112dbc6`、`124d7c3a`、`564ccd82` | `spine.py`、`compiler.py`、entry APIs | all entrypoint validator |
| §2 多台工作系统 | 各台 Canvas 是同一 Research Graph typed projection；user/agent 手动改动落 canonical command | canvas projection/mutation/QRO-node edit/layout cards；StrategyConsole UI tests | canvas entry_source coverage record；其他 desk endpoint 写回覆盖 | canvas mutation coverage test | `entry_source=canvas`、desk-specific evidence refs | 否 | `9112dbc6` | canvas mutation/projection APIs + StrategyConsole tests | canvas mutation test writes coverage |
| §3 生命周期与资产库 | Research/Data/Factor/Model/Signal/Strategy/Policy/Provider/Math 全生命周期 | 多 registry/API 已建；asset lifecycle and onboarding tests | all registry write paths forced lifecycle refs；section manifest aggregation | registry missing lifecycle ref mutation tests | lifecycle_refs per asset class in coverage | 否 | `2b1706f1` | registry modules, lifecycle store | section manifest full flag rejects until lifecycle refs |
| §4 Data Onboarding / Settings / Skill | Settings/Secrets/DataSource/IngestionSkill/LLMProvider/Auth/Gateway/health/quota | onboarding registry, connector runners, LLM provider configure/test, `2cd2ed24`, `a5dc9306` UI | OAuth/device-code/account auth；true polling scheduler；external billing/quota API；production keystore backend | provider polling fail-closed; auth method tests | ProviderHealth scheduled records; quota evidence refs | 否 | later §4 provider task | `onboarding_gateway.py`, LLM settings, scheduler | onboarding + LLM + scheduler tests |
| §5 Research Asset RAG | RAG 服务 user/Agent，权限、source/version、usage refs | RAG persistent index/query/usage; document parser; Agent/Workbench/Mode2 usage; RAG UI | cross registry/provider/scheduler automatic asset sync; external embedding provider; production vector DB | sync producer tests; embedding provider fail-closed | all-asset sync evidence refs | 否 | later §5 sync task | RAG index, document parser, scheduler | RAG/document/agent tests |
| §6 Research / Document / Math | document evidence, parser sandbox, Mathematical Spine, TheoryImplementationBinding | Document store/parser/upload/OCR; MathematicalSpineChain; method choices; artifact math ref gates | table/layout quality layer; all producers auto-write full math chain | producer missing math-chain tests | full-chain refs for every formal run/report | 否 | later §6 math producer task | document_intelligence, spine, RDP | document + spine + RDP tests |
| §7 Agent Shell / Multi-Agent OS | visible workflow, role agents, LLM Gateway, DAG/compiler, agent code diff/test/rollback | AgentRuntime Graph QRO; agent_shell source in code; RAG usage; workbench events | `entry_source=agent_shell` coverage records in persisted goal coverage; multi-role dispatch/full compiler | agent_shell coverage test; verifier independence tests | agent_shell QRO/Graph/Compiler/Evidence coverage refs | 否 | `6bbfa5ac` | `agent_runtime.py`, agent endpoints, coverage registry | agent runtime test writes coverage |
| §8 治理脊柱 | canonical command, permission, replay, LLMCallRecord, no secret, no silent mock | Graph/Compiler/coverage validators; Settings secret/LLM tests; execution no-silent-mock paths | all entrypoint claim; formal section manifest | all-entrypoint negative tests | chat/canvas/ide/scheduler/agent_shell refs | 否 | `2b1706f1` + entrypoint tasks | goal coverage + entry producers | `claims_all_entrypoints_wired=True` passes |
| §9 因子/模型/信号/策略边界 | 三纯库、Signal Contract、StrategyBook、多策略组合、math binding | factor/model/signal/strategy tests; Signal/Model registries; many API coverage refs | true venue-backed order emission remains out; full strategy codegen validation | strategy codegen bad gate tests | StrategyBook promotion RDP/evidence refs across entries | 否 | later §9 strategy task | factor/model/strategy modules | factor/model/strategy/coverage tests |
| §10 方法学与验证 | PBO/DSR/CPCV/bootstrap/conformal/TCA/fault drill, user choice ledger | methodology calculators, runtime drill, UI | real broker/venue fault drill; venue-native fault injection; more dossier/monitor/promotion producers | broker drill seam tests | real venue drill refs | 否 | later §10 fault drill task | methodology modules | methodology + execution tests |
| §11 数据层与标的接入 | InstrumentSpec, PIT/bitemporal, options/futures/bonds/FX/commodity semantics | MarketData contracts, Settings semantics/instrument/capability/use gate, connectors | richer asset class adapters; option/futures/bond/FX/commodity full semantics | asset-class semantic bad refs | per asset class evidence refs | 否 | later §11 asset-class task | market_data/onboarding connectors | market-data tests |
| §12 执行边界 | paper/testnet/live ladder, OrderGuard, A股 no-live, monitor/retire | execution intent/promotion/materialization/connectivity/safety/submit envelope; A股 live guards | real broker/venue adapter remains; actual order emission under guarded seam | real adapter disabled/fail-closed tests | venue ack/fill/reconcile worker refs | 否 | later §12 venue task | execution modules | execution + realmoney tests |
| §13 信任层 | appropriate reliance, release gates, pressure/expert/reviewer signatures, no overclaim | trust release gates, pressure, external expert identity/signature, RDP approval UI | external org workflow/KYC/SSO absent; user waiver display full sweep | waiver display tests | external workflow evidence refs | 否 | later §13 trust workflow task | trust/RDP UI | trust + RDP tests |
| §14 M1-M21 平台 | Every M row has QRO/Graph/lifecycle/governance/RAG/math refs and specifics | pure validator `test_platform_coverage.py` accepts synthetic complete manifest | persistent platform coverage registry/API/materializer from real refs | real manifest missing row tests | M1-M21 real refs | 否 | `7f4823d4` | `platform_coverage.py`, summary API | platform coverage persists real manifest |
| §15 模型治理 | model registry/passport/recertification/artifact safety/serving | model governance records, artifact inspection, model serving invocation coverage | external sandbox execution/serving hardening; full recert producer chain | unsafe load / recert trigger tests | model monitoring/evidence refs | 否 | later §15 task | model_governance, training | model governance tests |
| §16 工程标准 | no silent mock, dataset_version/checksum, WAL/JSONL, replay, performance baselines | engineering standards tests, many anti-raw/secret validators, dev validate | performance baselines not continuously proved; full no-silent-mock sweep | perf tests; no-silent-mock scan tests | benchmark evidence refs | 否 | later §16 benchmark task | tests/engineering, benchmark scripts | engineering + perf smoke |
| §17 交付标准 | RDP open package with manifest, sources, RDP refs, CI/release/deploy/monitor/rollback/retire | RDP registry/materializer/source bundle/archive/publish/CI/deployment/health UI | real object-store/CI/deployment provider adapters; online health/canary | provider adapter fail-closed tests | real CI/deploy/canary refs | 否 | later §17 provider task | RDP stores/UI/runners | RDP focused + frontend tests |

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| `app/backend/app/research_os/goal_coverage.py` | `validate_goal_coverage_manifest`, `validate_goal_entrypoint_coverage_manifest` | full-product / all-entrypoints hard contract 已在，下一步要接真实 producer/materializer |
| `app/backend/app/main.py` | `/api/research-os/goal/entrypoint_coverage_records`, `/summary` | 当前 summary 能看 missing sources；需要非 API producer 写入 |
| `data/audit/goal_entrypoint_coverage.jsonl` | local audit | 577 rows 全是 API，且只覆盖 §0/§1/§7/§8 |
| `app/backend/tests/test_goal_coverage.py` | validator tests | 已有负例；需要真实 entry producer integration tests |
| `app/backend/tests/test_platform_coverage.py` | platform validator tests | 只有 synthetic manifest；需要真实 registry/API/materializer |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. 只提供 contract refs，却声明 `claims_full_product_implementation=True` → `goal_section_not_full_entrypoint_wired` 必抓。
2. 只提供 `entry_source=api`，却声明 `claims_all_entrypoints_wired=True` → `goal_entrypoint_source_missing` 必抓。
3. 非 API entrypoint 写 coverage 时缺 QRO/Graph/Compiler/Evidence/Permission/Replay 任一 ref → 不写 partial record。
4. coverage record 带 `silent_mock_fallback_used=true` 或 `raw_payload_persisted=true` → fail-closed。
5. M1-M21 platform manifest 缺任一 common ref 或专项 ref → fail-closed，不允许 synthetic-only proof 当真实 proof。

## 复用 [按需]
`GoalEntrypointCoverageRecord`、`PersistentGoalEntrypointCoverageRegistry`、`CompilerIRRecord`、`CompilerPassRecord`、`PlatformCapabilityRecord`、现有 QRO/Graph/Compiler helper。

## 未验证残余（诚实）[必填]
没有逐个 entrypoint 证明 Chat/Canvas/IDE/Scheduler/Agent Shell 已经写 coverage；没有证明 §2-§17 都达到 full entrypoint wiring；没有证明 M1-M21 real manifest 来自真实 runtime refs；没有 CI、线上、生产 provider、用户验收。

## → 拆成的任务（mint uuid 入 tasks/pool/）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| 2b1706f1 | full-product section manifest 只在 §0-§17 每节都有真实 entrypoint_wiring_refs 时通过，contract-only claim 必红 | P0 | — |
| 6bbfa5ac | chat / agent_shell 成功入口写 QRO→Graph→Compiler→Evidence coverage；缺任一 ref 不写 partial | P0 | 2b1706f19b714040b93e37b23f82dcf8 |
| 9112dbc6 | canvas mutation/layout/QRO-node edit 写 `entry_source=canvas` coverage；raw canvas payload 和 silent mock 必拒 | P0 | 2b1706f19b714040b93e37b23f82dcf8 |
| 124d7c3a | IDE save/run/promote/AI complete 写 `entry_source=ide` coverage，缺 compiler/evidence refs 必拒 | P0 | 2b1706f19b714040b93e37b23f82dcf8 |
| 564ccd82 | scheduler/weekly tick/producer 写 `entry_source=scheduler` coverage，并让 all-entrypoint summary 不再缺 scheduler | P0 | 2b1706f19b714040b93e37b23f82dcf8 |
| 7f4823d4 | M1-M21 platform coverage 从真实 runtime refs 生成并持久化，synthetic-only manifest 不能当完成证明 | P1 | 2b1706f19b714040b93e37b23f82dcf8 |
