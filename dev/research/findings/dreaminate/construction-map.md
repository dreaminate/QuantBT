# 全量落地施工图 v2 · duet 三方并集定稿（2026-06-29 · 评估锚点 main=540b2d56）

> **三方并集**：中心 Claude ‖ deep-opus（6 探针逐节核 540b2d56 真代码 + 实跑 141+48 测试 + perf harness）‖ codex（gpt-5.5 xhigh），中心亲手裁决定稿、唯一写入。
> **诚实边界**：本地代码 proof + 局部实跑；非 CI、非线上、非用户验收；全量 pytest 未叠跑（守 memory）。**旧 v1 图（下方）§7/§9/§14/§15 四处已被真代码推翻，以本 v2 为准。**
> **结构源**：本 v2 = 结构源；逐节真实度 = 本表 + 当前代码；实时前沿 = dev/state/dreaminate/state.md 顶部块。

## ★ 头号结论：证据脊柱「三重失效」· 第一张多米诺是 PRODUCER（不是 enforce 翻转）
门套件 §6/§9/§10×2/§13/§16/§17 共 7 门已注册 gate_registry、接进 promote.py、490+ 测试过——**但 promote 从未被真治理/enforce**，三层叠加每层独立致命：
- (a) **advisory**：producer 出厂全红（`mark_green` 零非测试调用）·enforce 永不触发（`ide/promote.py:200` 两真调用方 `main.py:21172`+`agent/business_tools.py:300` 都不传 producer_status）。
- (b) **空过**：门「节缺省→ok=True」+ **无 producer 把 typed 记录写进 manifest**（`promote_assembler.py:77-80` 真路径 honest-absent）→ 即便翻 enforce 也空过。
- (c) **路径孤岛**：唯一真 promote 是 IDE 沙箱 + agent 回测·approval-gate/paper-desk 真晋级根本不走门链。
→ 真闭合**第一张多米诺 = PRODUCER**（从真研究 run 把 §6/§9/§10/§13/§16/§17+RDP typed 记录写进 run.json）→ 标绿 → 翻 enforce → 并所有 promote 路径。这是「机械齐备 + 测试齐备」与「真·enforced 研究到晋级」之间唯一结构鸿沟。

## 一、逐节 §0-§17 真实度（540b2d56 真代码核验）
| 节 | 裁定 | 真状态（承重 file:line） | 关键 gap |
|---|---|---|---|
| §0 北极星 | key_gap | install/真回测/单 LLM turn 真·无单条 stranger 端到端全链·full_product 诚实 False(goal_coverage.py:277) | 无可走的「配数据/LLM→QRO→跑→判证据→导RDP→ladder」流 |
| §1 对象 | genuine_partial | QRO/Graph/Compiler store 已建·覆盖校验只查结构存在不解析真对象(goal_coverage.py:11) | cited ref 解析真 QRO/Graph 横切未接 |
| §2 多台 | genuine_partial | canvas projection/mutation 已建·DeskHandoff 仅库无 REST·canonical_command_ref 可选 | 跨台 handoff REST + canvas 强制 canonical command |
| §3 生命周期 | genuine_partial | asset_lifecycle 校验器真·ingestion 写时 enforce·退役/缺 state 拒未挂全 registry 写路径 | 跨 registry lifecycle 门(factor/model/signal/strategy 写点) |
| §4 数据接入 | genuine_partial | **真 data pull 真**(Tushare/Binance/Stooq·keyring→token 桥 main.py:636)·keystore 真 | OAuth/device=KRG·health reactive·revoke 校验拒非自动扫·GE ingest 不跑 |
| §5 RAG | genuine_partial | 4 registry 写自动 sync(权限+source/version main.py:1045)·best-effort 吞异常 | embedding=local-hash(KRG)·广义检索类型未覆盖 |
| §6 文档/数学 | genuine_partial | doc parser 真 no-network sandbox·§6 门委托 spine_gate 8 子句真拒残缺强标签 | 门 advisory+节缺省 ok=True+**无 producer 写数学链** |
| §7 Agent Shell | key_gap | **LLM Gateway 真 path+deny-by-default 真**(main.py:1205→NoLLMConfigured→503)·单 role turn 真 | **AgentOrchestrator 零生产调用方**(orchestrator.py:299)·多 role DAG 仅库 |
| §8 治理脊柱 | genuine_partial | gateway secret-scan/admissibility/seal inline enforce 可达·deny-by-default·honest-N/approval/replay 真 | **LLMCallRecord 不落账**(record_sink=None main.py:1239)·promote 门 advisory 空过 |
| §9 边界 | genuine_partial(强) | **3/5 bar 真 enforce 422**(模型体入因子库/守门指标入 fitness/孤儿信号) | StrategyBookContract 无生产构造方→short-intent/math-binding 库超前不可达 |
| §10 方法学 | genuine_partial | 计算器全真测过(DSR/PSR/MinTRL/CSCV-PBO/conformal/N_eff)·overfit_gate 对噪声真返红 | verdict-阻断 advisory·cost-cap research-hole·control-plane caps 零真调用方 |
| §11 数据层/标的 | genuine_partial | InstrumentSpec 单一源(C-S11)·TypedInstrumentSpec 逐类构造门真 | PIT enforce 4 层 fail-closed 但 LATENT(无端点 thread registry)·逐类数学 DECLARED-only KRG |
| §12 执行边界 | genuine_partial | ladder-jump 真 enforce 422·OrderGuard 唯一入口真·A股 live 封死·Binance adapter 真 | 真下单 materialize 刻意 disabled(KRG)·monitor IC observation=None(live KRG·interim 未接) |
| §13 信任层 | genuine_partial | trust_layer(2253 行)真+测·每 acceptance 映真 violation code | 门 advisory 且真 run no-op(无 producer)·require_trustworthy 零 release 调用方 |
| §14 平台 M1-M21 | key_gap | platform_coverage:317 真用 SA-1 resolver fail-closed | **main.py 从不 wire resolver**(_DEFAULT_RESOLVER 恒 None)→拒一切 honest-absent·无 relevance 证书 |
| §15 模型治理 | **genuine_full** | **真 fail-closed enforce 在写/晋级/serving**(缺 Dossier/challenger/recert/外来 pickle→拒)·pickle 默认 block 实证(runner.py:60)·serving 真(422+invocation record) | 自训 passport 硬编 MEDIUM tier·serving 主进程无 trust=(残余)·无 A-B 路由 |
| §16 工程标准 | genuine_partial | 校验器全真·真 benchmark harness 实跑 3 测/2 KRG | 门 advisory+节缺省 ok=True+producer 未接 CI |
| §17 交付/RDP | genuine_partial | rdp_gate 4 门真能拒(manifest/血统/残余/可追溯) | 门 advisory+节缺省 ok=True·4 producer 真路径 honest-absent·真 runner 全 None·require_rdp=False |

**旧 v1 推翻更正**：①§7 LLM Gateway 已 land（旧图「实例化 0 次」陈旧）·orchestrator-wire 未 land ②§9 已 3×422 真 enforce（非「无消费方」）③§15 genuine_full·pickle 默认 True 实证 ④§14 是 resolver=None 拒一切（非接受 synthetic·方向相反）。

## 二、距「真实可运行研究」三大结构 gap
- **GAP-1【最关键】证据脊柱三重失效**（见头号结论）→ 第一张多米诺 = PRODUCER。
- **GAP-2 无单条 stranger 端到端研究流**：真件孤岛（真 data pull/真回测/真单 LLM turn/真因子台/真模型治理都真），未连成 Quant Intent→QRO→Graph→Compiler→Run→Evidence→Promote→RDP→ladder→Monitor·Agent-native Chat/Canvas→QRO 非 live 默认（前端 P0=mock）·多 role orchestrator 仅库。
- **GAP-3 大量 fail-closed 最后一公里未接真生产调用点**（头号假绿面）：§14 resolver 未 wire·confirmatory-PIT registry 未 thread·§10 control-plane caps 零调用方·goal_coverage 不 import ref_resolution·LLMCallRecord 不落账·§9 StrategyBook 无生产构造方。

## 三、新 codemap 卡（闭哪节·可证伪·领地·依赖·分类）
### STREAM-1 PRODUCER 层 + ENFORCE 激活（GAP-1·最高杠杆·第一波 PARALLEL-SAFE）
- **NC-S17-RDP-PRODUCER**(§17·SHARED-ANCESTOR)：真 run→完整 RDP typed 记录写 run.json·标 s17_rdp 绿翻 enforce。可证伪:缺 repro-command 晋级拒·honest-absent 不误拒。领地:delivery/rdp_gate.py+promote_assembler.py+ide/promote.py。PARALLEL-SAFE(producer)→CENTER-SERIAL(翻)。
- **NC-S6-MATHCHAIN-PRODUCER**(§6)：theory-backed 自动写 TheorySpec→Binding→ConsistencyCheck 进 run/RDP·标 s6_mathchain 绿。可证伪:强标签缺 ConsistencyCheck 拒。领地:research_os/spine.py+promote_assembler.py。
- **NC-S10-COST/CTRL-PRODUCER**(§10)：写 cost/TCA+tier/effective_label·接 validate_validation_methodology+control_plane.constrain_promotion 进真 verdict 路径(今零调用方)·修 cost research-hole(按 claim_label 非 target_env)·标 s10_cost/s10_controlplane 绿。领地:methodology_validation.py+control_plane.py+eval/+promote_assembler.py。
- **NC-S13-TRUST-PRODUCER**(§13)：写 section13_trust·接 require_trustworthy 进真 release·标 s13_trust 绿。领地:trust_layer.py+promote_assembler.py。
- **NC-S16-ENGSTD-PRODUCER**(§16)：写工程证据进 manifest·标 s16 绿·接 CI。领地:engineering_standards.py+promote_assembler.py+CI。
- **NC-DATAQUALITY-INGEST-ENFORCE**(§4/§16·PARALLEL-SAFE+轻 main.py)：connector ingest 跑 ≥5 GE 测试+require_provenance·known_at/secret_ref 绑不可变 DatasetVersion。可证伪:违声明数据测试的表隔离非冒充 clean。领地:main.py:9520 ingest+data_quality.py+connectors/base.py。
- **NC-S13-WAIVER-SWEEP**(§13·PARALLEL-SAFE 前端)：每面诚实显 waiver 不渲染 proof-backed。
### STREAM-2 ENFORCE 翻 + 最后一公里（CENTER-SERIAL）
- **NC-PRODUCER-FLIP-LEDGER**(横切·SHARED-ANCESTOR)：真 ProducerStatusLedger 接 ide/promote.py 两真调用方·只标 wiring 测试过的 producer 绿。可证伪:标 wiring 红的 producer 绿→enforcement_policy 结构 fail-closed 拒(:114)。领地:ide/promote.py+agent/business_tools.py+gate_registry.py。依赖:各 producer。
- **NC-PROMOTE-PATH-UNIFY**(§17/§8)：approval-gate+paper-desk 真晋级并进同一门链。领地:approval/+paper/+ide/promote.py+main.py。
- **NC-PIT-REGISTRY-WIRE**(§11)：真 promote/gate 端点 thread registry+CONFIRMATORY·confirmatory-PIT 门真触发。可证伪:confirmatory 带未注册 dataset_version 拒。领地:main.py:21864+ide/promote.py+portfolio/gate.py+jobs.py。
- **NC-INSTRUMENT-RESOLVER-WIRE**(§11)：parse_instrument_spec 接 strategy_book/onboarding·逐类语义门可达。可证伪:期权策略缺 strike 拒。领地:strategy/strategy_book.py+market_data_contract.py+main.py。
- **NC-S14-RESOLVER-WIRE**(§14)：RealRefResolver wire 进 main.py platform_coverage(今 None 拒一切)。可证伪:真 ref backed·synthetic not-backed。领地:main.py:16519+platform_coverage.py。依赖 SA-1。
- **NC-LLMCALLRECORD-PERSIST**(§8/§17)：record_sink 落 LLMCallRecord 进 durable ledger·补 tool_schema_hash/cost。可证伪:agent turn→LLMCallRecord 带 cost·缺 cost 拒。领地:llm/gateway.py+llm/call_record.py+main.py+ledger。
- **NC-S14-RELEVANCE-CERT**(§14·PARALLEL-SAFE 库)：行↔ref 语义相关性证书。
### STREAM-3 Agent-native OS（GAP-2·CENTER-SERIAL）
- **NC-ORCHESTRATOR-WIRE**(§7·最强上游)：真 agent 端点实例化 AgentOrchestrator·多 role DAG 派发·投 24 事件经 gateway。可证伪:研究 turn 经 DAG·绕 DAG 拒·verifier 共 builder 上下文 flag 独立性。领地:agent/orchestrator/+main.py agent 端点。注:advise_trust/advise_governance 已 advisory 接·勿重做。
- **NC-AGENTCODECHANGE-GATE**(§7/§8)：AgentCodeChange⇒diff+test+rollback enforce。依赖 NC-ORCHESTRATOR-WIRE。
### STREAM-4 覆盖完整性 + 真研究 promote（GAP-2/3·CENTER-SERIAL）
- **NC-REAL-RESEARCH-PROMOTE**(§0/§1/§17·关键)：建真研究 run(QRO/Graph/Compiler/Evidence+RDP)→promote 路径(非 IDE 沙箱)·天然携 §6/§9/§10 记录。可证伪:promote run.json 带真 DatasetVersion+LLMCallRecord+ConsistencyCheck ref。领地:main.py 研究端点+compiler.py+promote_assembler.py。依赖多 producer。
- **NC-S0-COVERAGE-RESOLVER-WIRE**(§0/§1)：goal_coverage 接 ref_resolution·cited ref 解析真对象·停硬编 4 节。可证伪:cite 不存在 qro_id 拒·full_product 全节真接才 True。领地:goal_coverage.py+main.py。
- **NC-S9-STRATEGYBOOK-PATH**(§9)：建 StrategyBookContract 生产构造方·math-binding 可达·翻 §9 release 门。领地:strategy/+factor_strategy_boundary.py+main.py+promote_assembler.py。
- **NC-S3-LIFECYCLE-GATE**(§3·advisory-first 用户裁定)：退役/缺 state 门挂全 registry 写路径(advisory 起·Factor.evidence_refs from_dict 兜底)。领地:factor_factory/registry.py+main.py。
- **NC-S2-HANDOFF/CANVAS**(§2)：DeskHandoff REST+canvas mutation 强制 canonical command。领地:desk_projection.py+main.py。
### STREAM-5 前端/装/用/信（PARALLEL-SAFE·RunDetailPage 冻结·新页）
- **NC-AGENT-UI-LIVE-DEFAULT**(§2/§7)：agent-workbench 默认走 agentLive.ts SSE 非 mock。领地:frontend agent-workbench。
- **NC-DESK-LIVE-WIRE**(§14)：honest-mock 台接真端点。
- **NC-STRANGER-SMOKE-E2E**(§0·末波)：全栈 stranger smoke(净机→装→QRO→跑→导 RDP)。可证伪:断 RDP 导出红·跳 paper 直 live 红。
### STREAM-6 KNOWN_RUN_GAP 诚实 seam（不闭·保持诚实）
C-S4-PROVIDER-AUTH(OAuth/device §4)·C-S4-HEALTH-POLL(§4)·C-S5-EMBEDDING(§5)·C-S11-ASSETCLASS-MATH(Greeks/IV/duration §11)·C-S12-VENUE+真下单(§12·A股禁·用户按键)·**C-S12-MONITOR-IC-INTERIM(§12·可建·helper monitor/production.py:174 未接默认)**·C-S17-REAL-RUNNERS(CI/部署/canary §17·main.py:448 全 None)·C-S13-ORG-INDEPENDENCE(§13)。§10 池卡 MinTRL/CPCV/CONFORMAL(pool 31289338/861182e6/92a2182f)。

## 四、波次 + 争用图
- **第一波 PRODUCER 建**(PARALLEL-SAFE·5 线零热文件):NC-S17/S6/S10/S13/S16-PRODUCER + NC-DATAQUALITY-INGEST。前端 NC-S13-WAIVER-SWEEP 机动。
- **第二波 ENFORCE 翻 + 最后一公里**(CENTER-SERIAL 一次一张·promote_assembler+ide/promote.py+main.py):NC-PRODUCER-FLIP-LEDGER→各翻 enforce→NC-PROMOTE-PATH-UNIFY→NC-PIT-REGISTRY-WIRE→NC-INSTRUMENT-RESOLVER-WIRE→NC-S14-RESOLVER-WIRE→NC-LLMCALLRECORD-PERSIST。并发非热:NC-S14-RELEVANCE-CERT(库)‖前端 live。
- **第三波 Agent OS**(CENTER-SERIAL):NC-ORCHESTRATOR-WIRE→NC-AGENTCODECHANGE-GATE。并发前端 NC-AGENT-UI-LIVE-DEFAULT。
- **第四波 真研究 promote + 覆盖**:NC-REAL-RESEARCH-PROMOTE→NC-S0-COVERAGE-RESOLVER-WIRE→NC-S9-STRATEGYBOOK-PATH→NC-S3-LIFECYCLE-GATE→NC-S2-HANDOFF/CANVAS。
- **第五波 总闸 + 诚实 seam**:NC-STRANGER-SMOKE-E2E ‖ C-S0-DELIVERY-TOTALGATE ‖ STREAM-6 各 seam(含 C-S12-MONITOR-IC-INTERIM)‖ §10 池卡。

**争用图（绝不两张同飞）**:`main.py`(22862 行·全 *-WIRE+producer-flip+orchestrator+LLMCallRecord+PIT+instrument+coverage resolver 碰·硬串)·`ide/promote.py`+`release_gate/promote_assembler.py`(promote 收口枢纽·全 producer-flip+enforce+path-unify·SA-3 给门注册零争用但 producer 写入仍中心串)·`agent/orchestrator/orchestrator.py`(orchestrator+codechange agent 线内串)·`research_os/market_data_contract.py`(instrument-resolver 数据线内串)·`research_os/trust_layer.py`(trust-producer+waiver 排序)·`RunDetailPage.tsx` 冻结(新 UI 走新页)。

## 五、工程取舍待拍板（中心摆代价·不替拍）
1. **真研究 promote 路径**:建独立全链(重·合 GOAL 全生命周期) vs 从 IDE/agent 合成 honest-absent 记录(轻·已选 C-S17-RUNJSON 范式)。效果不等价(前者才满足 GOAL「已晋级=可追溯 RDP」)。建议后者作桥前者作真闭合·**点名用户拍**。
2. **§10 cost-cap research-hole 修法**:按 claim_label 门 cost(闭 GOAL bar·改 research 档行为) vs 维持 target_env。建议改 claim_label·flag 用户(行为变更)。
3. **enforce 翻转时机**:GOAL「拒」要 enforce·早翻(producer 未在全合法路径可靠写记录前)误拒诚实 run(违锁定决策)。SA-2/SA-3 advisory-first+producer-green 对冲·每翻前强制 mutation 三态(honest-absent 过/坏 run 拒/注释接线变红)。
4. **orchestrator 接法**:全多 role DAG(重·北极星·库已测) vs 单 role 增量。建议 DAG。

**风险**:第二波集中改 promote 枢纽·producer 翻绿不严→误拒诚实 run(缓解:每翻前 mutation 三态)。§15 自训 passport 硬编 MEDIUM·高风险 challenger bar 自训路径不触(真残余·建议补卡)。
**假绿灯风险点（状态卡必诚实标）**:①7 门注册≠promote 被 enforce(三重失效)②C-S7 全闭≠Agent OS 可用③ENFORCE_PIT=True≠生效④真 connector≠真数据进治理 run⑤§14 覆盖校验=拒一切 honest-absent⑥goal_coverage 覆盖=只查结构存在。

---
> ↓↓↓ 2026-06-28 v1 施工图（历史保留·v2 已据 540b2d56 真代码更正逐节真实度，§7/§9/§14/§15 四处已推翻·以 v2 为准）↓↓↓

## 全量落地施工图 (2026-06-28 · codemap-first)

> 三方独立思考并集（中心 Claude ‖ deep-opus ‖ codex gpt-5.5·xhigh）+ 4 条代码核验子探针，**中心已接收为项目 codemap**。覆盖 §0-§17 真·闭合全路径（≠ 仅当前收敛）。本节是【全量导航】，实时依据永远是卡原文 + 代码 + dev/state；与下方 2026-06-26 版互补不冲突。
> **诚实边界**：本地代码核验 proof（非 CI / 非线上 / 非用户验收）。下列 4 条方法学决策为**中心转达·驱动本图**（我未独立核到用户原话；如用户更正则刷新本图）。
>
> **▶ Wave 1 producer 收口波 land 进度（2026-06-29·全 advisory-first）**：§13-HARDEN（`trust_layer` 堵 3 gaming 漏洞·闭合 trust_layer 硬化 KNOWN_RUN_GAP）+ §16-GATE（新建 `section16_engineering_standards_gate`·注册 `gate_registry` 共 6 门·advisory）+ §17 **C-S17-RUNJSON-PRODUCERS**（`promote_assembler.assemble_promote_sections` 组装 API·§9/§10/§17 真血统→section 记录·接进 `ide/promote.py`·honest-absent 不误拒）均 land。**C-S15-PICKLE-DEFAULT-ENFORCE 核验为早已做**（提交 1a099191+73bfc4e1·子进程默认 `enforce=True`·下方 line「今 enforce=False」已陈旧）。**★ 标绿激活 §9/§10/§17 enforce 待用户拍板**（破 advisory-first 默认契约 + IDE 路径 honest-absent 激活意义有限 + 真记录源缺口）。详见 `dev/state/dreaminate/state.md` 顶部块。
>
> **▶ Wave 2 就绪节并行波 land 进度（2026-06-29·用户定向「并行推进其它就绪节」）**：**C-S5-RAG-AUTOSYNC**（§5·`asset_rag.py` 4 个 `build_*_rag_document` helper + `main.py` 4 处 autosync hook·权限 owner-scoped 空 owner raise·向后兼容纯加法）+ **C-S15-RECERT-PRODUCER**（§15·新建 `training/schema_drift.py` 消费列 fingerprint + pre-run fail-closed 门·schema 变→block until recert）均 land·全量 3640 passed/0 failed。**C-S3-LIFECYCLE 库核验为已做**（asset_lifecycle.py + factor_factory/lifecycle.py + register_guard.py）·剩 `main.py` 端点强制（`create_factor` 加 `validate_governed_asset` 硬门·**enforce 性质·留下一波 advisory-first 评估**）。新增 KNOWN_RUN_GAP：C-S5 catch-up sync（scheduler 卡）+ C-S15 `monitor/production.py` schema hook（语义不匹配·建议独立 serving 期监控卡）。详见 `state.md` 顶部块。
>
> **▶ C-S7-LLM-GATEWAY-WIRE land（2026-06-29·§7/§8·兑现 no-silent-mock 红线·用户拍板 deny-by-default）**：`agent/llm_providers.py` 去静默 `DevLocalLLM`→`NoLLMConfigured`·`llm/gateway.py` 加 `GatewayBackedLLMClient`+`make_gateway_backed_agent_llm`（复用 LLMGateway 全链·封印 LLMCallRecord·dev_local 三处拒）·`main.py` `_current_agent_llm` 两层治理（Settings 撤销/路由 + gateway 产账）+ 全局 `NoLLMConfigured`→503 handler + 探针哨兵 + record/replay 单层 + chat 端点穿透/明确 deny。**codex 复核修 finding**（chat_send_message/chat_stream 原吞 NoLLMConfigured→改）。全量 3651 passed/0 failed。**§8 no-silent-mock 在 agent LLM 路径真消除**（中心 grep 实证 + 变异三态）。新增 KNOWN_RUN_GAP：Finding2（gateway traceback 窄 secret 向量·pre-existing）·record_sink RDP 落账（暂 None）·Settings 治理深度（registry 进 build_agent_llm_gateway 合一层）。**下一波用 duet 设计 C-S11-INSTRUMENT-MERGE**（flat 升 Pydantic 单一源删 spec.py·atomic 重构）。详见 `state.md` 顶部块。
>
> **▶ 攒批三线 land 进度（2026-06-29·火力全开 3 并行领地零交叠 merge 零冲突）**：**C-S11 Commit1**（§11·`market_data_contract.InstrumentSpec` flat→Pydantic additive·吸收 instruments/spec.py typed 富能力作 Optional·删 orphan spec.py·新 `asset_class.py` 单一源·spec_id property 保 instrument_ref·to_dict 零漂移·main.py 零改·codex 四类 hazard 过）+ **C-S6 §6 数学链门**（新建 `section6_mathchain_gate.py` 委托 `spine_gate.evaluate_promotion` 8 子句·中心串接 gate_registry 共 **7 门**·advisory-first[producer s6_mathchain RED]·codex 修 2 fail-open）+ **C-S7 Gap1**（gateway.py 四条 secret→errors.jsonl 向量结构性全闭·codex 两轮）均 land·全量 3704 passed/0 failed。**C-S15-SERVING 核验为 already_done**（见下方 line 106）。**★ 待用户裁（全 CENTER-SERIAL）**：C-S11 Commit2 fork（values-required/token-tighten/数据迁移）·monitor-schema-hook·C-S7 Gap2/3·C-S3 端点。详见 `state.md` 顶部块。

### ★ 4 条已锁方法学决策（中心转达·已 bake 进对应卡）
1. **enforce 切换时机 = 逐门绿灯即自动 enforce**：每个门的「证据 producer 接线测试」转绿那刻自动从 advisory 翻 enforce；转绿前只 advisory + 记录；**绝不误拒诚实 run**。→ 定义 SA-2、解锁第三波。
2. **§11 instruments = 合并删孤儿**：`instruments/spec.py`（零非测试 importer 的孤儿富类型）**并入** `market_data_contract.InstrumentSpec` 作单一源，**删** `spec.py`。→ 落 C-S11-INSTRUMENT-MERGE。
3. **§15 模型 serving = 在范围内**：建**真** serving 卡（C-S15-SERVING 不再是 KNOWN_RUN_GAP / 桩，是真活）。
4. **§12 监控 IC = paper/backtest 派生 IC 作诚实过渡源**；live 实盘 IC 半边仍 KNOWN_RUN_GAP。→ 落 C-S12-MONITOR-IC。

### A. 现实底座（纠 2026-06-28 gap-matrix 的陈旧点）
- gap-matrix「入口覆盖只有 api·577 行」**已陈旧**：`main.py` 实测六入口 producer 全接（agent_shell L1331 / IDE L1704+ / CHAT L2344 / SCHEDULER L3643 / CANVAS L7654 / api L19514 + monitor/production.py:522）；full-product 守门端点已建且诚实 fail-closed（`main.py:16221` `claims_all_entrypoints_wired=True`、`16265` `claims_full_product_implementation=True`）。
- **解释一切 genuine_partial 的同一模式**：库 + validator **已建已测**；生产接线为 **advisory-first**（接真路径只 flag 不 reject）或 **library-only**（无生产消费方）；**enforce（在真路径拒坏·GOAL「拒」要的）延后**；真外部 provider/venue/data **缺位（诚实 KNOWN_RUN_GAP）**。落地 ≈ **翻 advisory→enforce + 跑真入口 run + 把 ref 对真存储解析**，非 greenfield（greenfield 真耗尽：research_os/ 30+ 大模块·execution_boundary 207K / rdp 99K / trust_layer 90K / onboarding 84K / spine 67K）。
- **两个争用枢纽**：① `main.py` 22717 行 / 370 端点 = 中心串行；② `ide/promote.py` 398 行 = 六门（§9 边界 / §10 成本 / §10 控制面 / §13 信任 / §16 工程 / §17 RDP）共抢的 promote 收口 —— 无共享 seam 就退化成六次串行改。

### C. 分类图例 + 两步法
- **SHARED ANCESTOR**：解锁多张并发卡的前置·中心先建/先串。
- **CENTER-SERIAL**：碰 `main.py` / `ide/promote.py` / `agent/orchestrator/orchestrator.py` 热共享文件·中心一次一张。
- **PARALLEL-SAFE**：独立模块/文件、无热文件争用·可派 deep-opus 并发线。
- **KNOWN_RUN_GAP**：seam 可建 + 可诚实 fail-closed·但真闭合需本环境缺位的真外部源 —— **不闭合·保持诚实**。
- **两步法**（每张 CENTER-SERIAL）：opus 先建孤立 check/lib（PARALLEL-SAFE）→ 注册进 seam → 中心一次性把 seam 串进热文件。

### D. 共享祖先（第零波·先做）
- **SA-1 · 通用真引用解析器**（§0/§1/§8/§14）：把 `platform_coverage.py:validate_platform_capability_real_backing` 六类 resolver 抽成可复用件·对真后端 resolve qro/graph/compiler/evidence/permission/replay/lifecycle/rdp ref·fail-closed·占位 token（含 goal_closure 变体）禁扫。可证伪：引用不存在对象的 coverage 行 → 拒。领地：新 `research_os/ref_resolution.py`（消费方后续：goal_coverage.py / platform_coverage.py / rdp.py）。依赖：无。分类：SHARED ANCESTOR。
- **SA-2 · enforce 切换策略件**（横切·已锁决策 1）：`governance/enforcement_policy.py` 编码「逐门 producer 测试转绿 → 自动 enforce；未绿 → advisory+记录」。可证伪：给 producer 测试为红的门置 enforce=True → 策略自身 fail-closed（无绿 producer 不许翻）。依赖：决策 1（已锁）。分类：SHARED ANCESTOR（**已解锁**）。
- **SA-3 · promote 门链 seam**（§9/§10/§13/§16/§17）：`release_gate/promote_gate_chain.py` 注册式门链·`ide/promote.py` 一次调用；enforce 门拒→promote 拒·advisory 门→落 run.json release_verdict 不阻断。可证伪：注册一个拒模板基线 run 的门 → enforce 时该 run 被拒·advisory 时被记。领地：新 `release_gate/promote_gate_chain.py` + 一次串 `ide/promote.py`（替代六次改）。依赖：SA-2。分类：SHARED ANCESTOR / CENTER-SERIAL。
- **SA-4 · spine/research-graph 占位种子清理**（§6·后续 c）：写 MathematicalSpineChain / research-graph command 带 goal_closure 占位种子 → 写时拒；清运行时 JSONL 旧种子。领地：`research_os/spine.py` 写门 + `graph/research_graph.py` + 数据卫生脚本。依赖：无。分类：PARALLEL-SAFE。

### E. 逐节卡片清单（每卡：可证伪验收 · 文件领地 · 依赖 · 分类）

**§0 北极星**
- **C-S0-COVERAGE-INTEGRITY**（§0/§1/§8）：把 SA-1 解析器接进 `validate_goal_entrypoint_coverage`·cited ref 必须 resolve 到真 QRO/Graph/Compiler/Evidence（今仅查结构存在 = 与 platform-coverage-B 同类假绿）。可证伪：coverage 行 cite 不存在 qro_id → 拒。领地：`research_os/goal_coverage.py` + `main.py` validator 调点。依赖：SA-1。CENTER-SERIAL。
- **C-S0-ENTRYRUNS**（§0/§2/§7/§8）：六入口（重点 canvas/ide/scheduler）真端到端 run 各写真 coverage 行·再按 §0-§17 逐节 seed `GoalSectionCoverageRecord(full_entrypoint_wired=True)` 带可 resolve 的 entrypoint_wiring_refs。可证伪：缺 scheduler 真 run → section 汇总 full_product 仍 False。领地：`app/backend/tests/` 集成 + `main.py` 节覆盖 seeding。依赖：SA-1、C-S0-COVERAGE-INTEGRITY、几乎全部节卡。CENTER-SERIAL（晚）。
- **C-S0-FRONTEND-CLOSURE**（§0/§14·前端·codex 抓的）：修或删悬空 `GoalClosurePanel.tsx`（fake-green A「closure materializer」清档后的前端残件）—— 要么补成诚实面板（如实反映 fail-closed 覆盖·绝不渲染伪全闭合），要么删 panel + 其 test + `OverviewDeskPage.tsx` 接线。可证伪：前端 build/test 无悬空 import 通过；面板绝不显示 fabricated full-closure。领地：`app/frontend/src/pages/overview/GoalClosurePanel.tsx` / `GoalClosurePanel.test.tsx` / `OverviewDeskPage.tsx`。依赖：无。PARALLEL-SAFE。
- **C-S0-DEPLOY-SMOKE**（§0）：可上线 7 条（能装/能用/能产QRO/能走完链/能判证据/能导出RDP/能进 ladder/能监控降级退役）一条可证伪陌生人安装 smoke。可证伪：断 RDP 导出 → smoke 红；跳 paper 直 live → smoke 红。领地：新 `tests/test_deployable_smoke.py` + `scripts/`。依赖：多数卡。PARALLEL-SAFE（末波）。
- **C-S0-DELIVERY-TOTALGATE**（§0/§17）：单一「交付总闸」聚合每节真接线 + 每条可上线条件·fail-closed。可证伪：任一节回退 advisory/未接 → 总闸红。领地：`main.py` 聚合端点 + `research_os/goal_coverage.py`。依赖：近全部。CENTER-SERIAL（末）。

**§2 多台**
- **C-S2-HANDOFF**（§2）：通用跨台 DeskHandoff REST（建/结）写 canonical command + 覆盖；`validate_desk_handoff` enforce（今仅库 `desk_projection.py:DeskHandoffRecord`/`validate_desk_handoff`·**无 REST**·L19695 策略→模拟候选池不算）。可证伪：结 handoff 缺 produced_ref → 拒。领地：`main.py`（新端点）+ `research_os/desk_projection.py`（库已建）。依赖：SA-1。CENTER-SERIAL。
- **C-S2-CANVAS-ENFORCE**（§2）：canvas mutation 的 canonical_command_ref 改**必填**（今实务可选·记录不拒）。可证伪：canvas mutation 缺 canonical command → 拒。领地：`main.py` canvas 端点（L7654/L8247+）+ `research_os/desk_projection.py`。CENTER-SERIAL。

**§3 生命周期**
- **C-S3-LIFECYCLE-GATE**（§3）：强制 registry 写路径挂 lifecycle_state/evidence_refs；真写路径拒退役资产默认引用（今 `asset_lifecycle.py` validator 是 opt-in 松门）。可证伪：注册 production_asset 缺 lifecycle_state → 拒；新 run 默认退役资产 → 拒。领地：`research_os/asset_lifecycle.py` + factor/model/signal/strategy registry 写点 + `main.py` 写端点。CENTER-SERIAL + PARALLEL-SAFE（registry 库）。

**§4 数据接入 / Provider**
- **C-S4-PROVIDER-AUTH**（§4）：OAuth / device-code / CLI 凭据导入 / 企业网关 真流程（今仅 API key + keystore 真·keyring/fernet/memory 实证）。可证伪：device-code 未完成 consent → fail-closed（无静默兜底）。领地：`research_os/onboarding_gateway.py` + `agent/llm_providers.py` + `security/keystore.py` + 新 auth 流模块。PARALLEL-SAFE。**KNOWN_RUN_GAP**（真 provider consent/凭据缺）。
- **C-S4-PROVIDER-HEALTH-POLL**（§4）：真 provider health/quota 轮询调度（今仅 reactive·无调度器）。领地：新调度 + `llm/gateway.py` + monitor。PARALLEL-SAFE。**KNOWN_RUN_GAP**（真 provider API）。
- **C-S4-SECRET-REVOKE-CASCADE**（§4）：SecretRef 撤销 → 依赖 IngestionSkill 自动降级/暂停/隔离·enforce。可证伪：撤 secret 后跑依赖 skill → fail-closed/隔离·落审计。领地：`research_os/onboarding_gateway.py` + `main.py` skill-run 端点。CENTER-SERIAL。

**§5 RAG**
- **C-S5-RAG-AUTOSYNC**（§5）：跨 registry 写时自动 sync producer 索引全资产类（今手动/逐端点 .add()）。可证伪：建 factor → RAG 可检带 source/version·权限隔离·越权不返。领地：`research_os/asset_rag.py` + 调度 + registry 写 hook。PARALLEL-SAFE + 轻 main.py hook。
- **C-S5-RAG-EMBEDDING**（§5）：真外部 embedding + 向量库 seam·诚实 fail-closed；local-hash 留诚实默认。领地：`research_os/asset_rag.py` + `llm/`。PARALLEL-SAFE。**KNOWN_RUN_GAP**（外部 embedding/向量库缺·GOAL 未强制·local 诚实基线可接受）。

**§6 研究/文档/数学**
- **C-S6-MATHCHAIN-AUTOWRITE**（§6/§8）：正式 producer 自动写全数学链（TheorySpec→Binding→ConsistencyCheck）ref 进覆盖/RDP；声 theory-backed 缺 ConsistencyCheck → 拒。领地：`research_os/spine.py` 消费方 + promote（经 SA-3）。依赖：SA-3。PARALLEL-SAFE（库）→ CENTER-SERIAL（链）。
- （占位种子清理见 SA-4。）

**§7/§8 Agent Shell + 治理脊柱 —— 最强上游瓶颈**
- **C-S7-LLM-GATEWAY-WIRE**（§7/§8/§16）：agent LLM 调用走 LLM Gateway·杀 `make_settings_managed_llm_client` 旁路 + 静默 DevLocalLLM 兜底（`llm/gateway.py` 等已建·`LLMGateway` 在 main.py 实例化 **0 次**·agent 直连 Settings client = 活的 §8 `AgentLLMCall⇒Gateway` + `ProductionResult⇒no silent mock` 违反）。可证伪：生产 profile 下 agent turn 无 provider → fail-closed（无静默 mock）；LLMCallRecord 带 provider/model/auth_ref/routing_policy/replay_state。领地：`llm/gateway.py`（库）+ `agent/llm_client.py` + `agent/agent_runtime.py` + `main.py` agent 端点（L1185-1195, L1327）。依赖：无。CENTER-SERIAL。**最先开。**
- **C-S7-ORCHESTRATOR-WIRE**（§7）：真 agent 端点实例化 `AgentOrchestrator`·多 role 经治理 DAG 派发·投 23 可见事件。可证伪：orchestrator 绕 DAG 派发 → 拒；verifier 共 builder 上下文无独立性记录 → flag。领地：`agent/orchestrator/orchestrator.py` + `main.py`。依赖：C-S7-LLM-GATEWAY-WIRE。CENTER-SERIAL。
- **C-S7-AGENTCODECHANGE-GATE**（§7/§8）：AgentCodeChange ⇒ diff+test+rollback 在真改码端点 enforce。可证伪：agent 改码缺 test result → 留 draft/拒。领地：`ide/` + `agent/orchestrator/plan.py` + `main.py`。依赖：C-S7-ORCHESTRATOR-WIRE。CENTER-SERIAL。
- 注：advise_trust/advise_governance 已接 orchestrator Review 形态（trust_advisory.py / governance_advisory.py）—— **勿重做**·orchestrator 接通后即生效。

**§9 因子/模型/信号/策略边界**
- **C-S9-BOUNDARY-ADVISORY**（§9/§7）—— **在飞·勿重做**（边界 validator advisory 接 orchestrator·本 worktree 暂无 boundary_advisory.py）。
- **C-S9-BOUNDARY-ENFORCE**（§9）：把（库级已 enforce 的）边界 validator 经 SA-3 接进真 promote/建因子/建策略写路径（`factor_strategy_boundary.py` L287-317 拒模型体入因子库·L263-284 拒守门指标入 generator fitness·L569-577 拒退役因子默认采用·**无生产消费方**）。可证伪：真端点把模型体入因子库 → 拒；守门指标入 generator fitness → 拒；退役因子被新策略默认采用 → 拒。领地：`research_os/factor_strategy_boundary.py`（库已建）+ `factor_factory/` + `strategy/` + SA-3。依赖：SA-3、C-S9-BOUNDARY-ADVISORY。PARALLEL-SAFE（check）→ CENTER-SERIAL（链）。

**§10 方法学**
- **C-S10-COST-GATE**（§10）：成本/TCA 缺 → 真 verdict/promote 拦 evidence_sufficient（今 `methodology_validation.py:86-87` 记 cost_model_refs/tca_ref·无门消费）。可证伪：无成本模型却声 evidence_sufficient → 降级/拒。领地：`research_os/methodology_validation.py` + `eval/` verdict + SA-3。依赖：SA-3。PARALLEL-SAFE→CENTER-SERIAL。
- **C-S10-CONTROLPLANE-ENFORCE**（§10）：宽松档（loose/exploratory/...）在真 promote 封 verdict 上限（今 `control_plane.py:72-98` 只封 label·宽松档仍可达 evidence_sufficient·spine_gate 只守 proof_backed/production_ready）。可证伪：loose 档 run 显 evidence_sufficient → 封到 exploratory。领地：`methodology/control_plane.py` + SA-3。依赖：SA-3。PARALLEL-SAFE→CENTER-SERIAL。
- **C-S10-POOL-MINTRL**（§10·池卡 31289338）：冷启动 gate/UI DSR=N/A + PSR + ⌈MinTRL⌉ 渐进披露。领地：`eval/dsr.py`（已建）+ verdict gate + 新前端卡。PARALLEL-SAFE。
- **C-S10-POOL-CPCV**（§10·池卡 861182e6 残③）：cv_scheme UI 选项 + CPCV⟂WF 双轨 report（不自动判赢）。领地：`models/training.py` + `eval/overfit_gate.py` + 前端。PARALLEL-SAFE。
- **C-S10-POOL-CONFORMAL**（§10·池卡 92a2182f 残）：信号层 abstain UI + 时序 ACI。领地：`eval/conformal.py`（已建）+ 信号端点 + 前端。PARALLEL-SAFE。
- **C-S10-FAULTDRILL**（§10）：真券商/venue fault-drill seam。PARALLEL-SAFE seam。**KNOWN_RUN_GAP**（真 venue）。

**§11 数据层 / 标的**
- **C-S11-INSTRUMENT-MERGE**（§11·已锁决策 2）：把孤儿 `instruments/spec.py`（OptionSpec/FutureSpec/BondSpec/FxSpec/CommoditySpec·**零非测试 importer**）**并入** `market_data_contract.InstrumentSpec` 作单一源、**删** spec.py；真研究/数据入口 enforce 逐类必填语义。可证伪：期权策略缺 expiry/strike/multiplier/settlement → 真路径拒；删后无悬空 import、无第二 InstrumentSpec 源。领地：`instruments/` + `research_os/market_data_contract.py` + `data_pull.py` + `main.py` 数据端点。CENTER-SERIAL + PARALLEL-SAFE（库）。
- **C-S11-PIT-ENFORCE**（§11）：真 data-pull 路径 enforce PIT/known_at/effective_at/as-of join（今仅契约校验·data_pull.py 不强制）·confirmatory 拒非 PIT。可证伪：非 PIT 数据进 confirmatory run → 拒。领地：`data_pull.py` + `field_catalog/` + `research_os/market_data_contract.py` + `training/codegen.py`。PARALLEL-SAFE（数据线·与 agent/promote 不交）。
- **C-S11-ASSETCLASS-MATH**（§11）：真逐类数学（Greeks/IV 面、期货 roll/连续合约、债 duration/convexity、FX 取价、商品）。今全 DECLARED_ONLY。领地：`instruments/` + 新 adapter。PARALLEL-SAFE seam。**KNOWN_RUN_GAP**（真逐类市场数据缺）。

**§12 执行边界**
- **C-S12-LADDER-ENFORCE**（§12）：真（Binance）下单路径 enforce paper→testnet→live ladder + OrderGuard 唯一入口（Binance 现货/合约 adapter 真·ladder 定义未在下单点 enforce·order materializer/submitter 刻意 DISABLED/fail-closed）。可证伪：无 paper+审批直 live → 拒；HALT 后自动重发 → 拒；新 venue 在 OrderGuard 外裸调 place_order → 拒。领地：`execution/` + `research_os/execution_boundary.py` + `main.py` 执行端点。CENTER-SERIAL。**红线**：A股永不实盘（RULES.project）。
- **C-S12-MONITOR-IC**（§12·已锁决策 4）：把 **paper/backtest 派生 IC** 接进 `monitor/production.py` 作诚实过渡源·让 graded kill/drift 真算（今 observation=None 诚实）；live 实盘 IC 半边留 gap。可证伪：IC 源出现 drift → graded kill 触发；无源 → 诚实 None（绝不拿陈旧注册期 IC 冒充「本周」）。领地：`monitor/production.py` + IC 馈源（paper/backtest）。PARALLEL-SAFE。**半 KNOWN_RUN_GAP**（live 实盘馈源）。
- **C-S12-VENUE-ADAPTER**（§12）：Binance crypto 外的机构 venue adapter。PARALLEL-SAFE seam。**KNOWN_RUN_GAP**（真 venue·真钱=用户亲按键·A股 live 禁）。

**§13 信任层**
- **C-S13-RELEASE-ENFORCE**（§13）：经 SA-3 把信任发版门（反谄媚施压/专家否决/弱点折叠/mock 诚实/冷启动）接进真 release/promote 决定（今 advisory-only·`require_trustworthy()` 从未在 release 调）。可证伪：谄媚强结论 run → release 拦。领地：`research_os/trust_layer.py` + `release_gate/` + SA-3。依赖：SA-2、SA-3。PARALLEL-SAFE（check）→CENTER-SERIAL。
- **C-S13-WAIVER-DISPLAY-SWEEP**（§13）：每个面（RAG/RDP/UI 卡/汇总）诚实显 user-waiver·绝不把 waived 渲染成 proof-backed/evidence_sufficient。可证伪：waived 资产任一处显 evidence_sufficient → 拒。领地：`research_os/trust_layer.py` + 前端 + `research_os/rdp.py` + `research_os/asset_rag.py`。PARALLEL-SAFE。
- **C-S13-ORG-INDEPENDENCE**（§13）：外部组织 KYC/SSO 流。**KNOWN_RUN_GAP**（无真组织·单人功能独立性诚实·GOAL「组织独立性只在真实组织流程存在时声明」）。

**§14 平台 M1-M21**
- **C-S14-RESOLVER-WIRE**（§14·后续 a）：把真后端 resolver 接进 main.py platform_coverage validate 调用·让生产 full_platform_coverage 解真 ref（今诚实 False·~L399-421 区延后）。可证伪：synthetic-only manifest → False；真 ref → 解。领地：`main.py`（platform 覆盖端点）+ `research_os/platform_coverage.py`。依赖：SA-1。CENTER-SERIAL。
- **C-S14-RELEVANCE-CERT**（§14·后续 b）：矩阵行↔ref **语义相关性证书**（存在≠相关）·真但不相关 ref 不许过。可证伪：M3-数据 行被无关 QRO ref 背书 → 拒。领地：`research_os/platform_coverage.py`（库）+ `main.py`。依赖：C-S14-RESOLVER-WIRE。PARALLEL-SAFE（库）→CENTER-SERIAL。
- **C-S14-MATERIALIZER**（§14）：真平台覆盖 materializer·从真运行时 ref 持久化 manifest。依赖：C-S0-ENTRYRUNS。CENTER-SERIAL。

**§15 模型治理**
- **C-S15-PICKLE-DEFAULT-ENFORCE**（§15）：producer-run+hash binding 接齐后把子进程 `TrustPolicy.enforce` 默认翻 True（外来 pickle 默认 block）。**✅ 已做**（核验：提交 1a099191+73bfc4e1·子进程默认 `enforce=True`·`tests/test_artifact_trust_subprocess_enforce.py` 锁测 6 passed + 变异 2 failed·原「今 enforce=False」已陈旧）。可证伪：子进程默认 profile 加载外来 pickle → block。领地：`training/lib.py` + `training/runner.py`。依赖：artifact_trust producer（已止血）。PARALLEL-SAFE。
- **C-S15-RECERT-PRODUCER**（§15）：recert 触发 producer 接真 drift/schema 事件（今 records-only·手动）。可证伪：模型 dataset schema 变 → 下次 run 前要求 recert。领地：`research_os/model_governance.py` + monitor + drift hook。PARALLEL-SAFE。
- **C-S15-SERVING**（§15·已锁决策 3·**✅ 已做**·核验 2026-06-29：真 model serving 全建已接线[safe load + ModelServingInvocationRecord 落审 + predict 端点 stage/passport/dossier/inspection/monitoring 门 + 测试]·诚实负反馈无产出）：真模型 serving —— 安全加载（safetensors/weights_only·外来 pickle 默认 block）+ producer-run+hash binding + sandboxed load/inspect + ModelServingInvocationRecord 落审 + ModelRoutingPolicy/权限门。可证伪：serving 加载外来 pickle/缺 passport 的模型 → 拒；serving 调用缺 invocation record → 拒。领地：`research_os/model_governance.py` + `training/lib.py`（safe load）+ 新 serving 端点 + `main.py`。依赖：C-S15-PICKLE-DEFAULT-ENFORCE。CENTER-SERIAL。

**§16 工程标准**
- **C-S16-BENCHMARK-HARNESS**（§16）：真 benchmark harness 证 5 基线（沪深300×10y读<3s / 回测<60s / Run首屏<2s / 资产检索<1s / RAG<3s）·可跑/CI·带 evidence_ref（`validate_performance_baseline` 库已建·**仓内无 harness**）。可证伪：回测回归到 >60s → benchmark 红。领地：新 `tests/benchmark/` + `research_os/engineering_standards.py`。PARALLEL-SAFE。
- **C-S16-ENGSTD-WIRE**（§16）：经 SA-3 把 engineering_standards validator（mock 诚实/no-silent-mock 扫/data_update/llm_replay）接进真 CI 门 / promote。可证伪：生产路径静默 mock 兜底 → 扫到·CI 红。领地：`research_os/engineering_standards.py` + CI 脚本 + SA-3。依赖：SA-3。PARALLEL-SAFE（扫器）→CENTER-SERIAL。

**§17 交付 / RDP**
- **C-S17-RUNJSON-PRODUCERS**（§17）：补 4 个 run.json 字段（execution_blocks / dataset_versions / llm_call_records / assembly_injected）·让 RDP enforce 不误拒诚实 run。**先于** C-S17-RDP-PROMOTE-ENFORCE。可证伪：promoted run 带真 DatasetVersion + LLMCallRecord ref；缺 producer → 字段诚实空（非伪造）。领地：`release_gate/promote_assembler.py` + `ide/promote.py` + run.json producer。CENTER-SERIAL。
- **C-S17-RDP-PROMOTE-ENFORCE**（§17）：promote 路径 RDP 默认 enforce·追不到完整 RDP 的晋级被拒·四拒绝门在真 promote 活（经 SA-3·`require_valid_rdp` 翻开）。可证伪：promote 缺 manifest/artifact-hash/repro-command → 拒；缺 DatasetVersion/IngestionSkill ref → 拒；缺未验证残余 → 拒；不可追溯晋级 → 拒。领地：`ide/promote.py` + `delivery/rdp_gate.py` + `release_gate/promote_assembler.py` + SA-3。依赖：SA-2、SA-3、C-S17-RUNJSON-PRODUCERS。CENTER-SERIAL。
- **C-S17-REAL-RUNNERS**（§17）：真 RDP runner（CI 存证 / 部署 provider / 对象存储发布 / 在线 health/canary）·今 `RDP_CI_RELEASE_RUNNER=None` 等三 None·建诚实 fail-closed seam 带显式「unavailable」。领地：`delivery/` runner + `main.py` RDP_*_RUNNER 接线。CENTER-SERIAL seam。**KNOWN_RUN_GAP**（真 CI/部署/对象存储/canary 基建缺）。

### F. 波次编排（每波 ≤5 并发线·领地不交叠）
- **第零波·中心串行·共享祖先（+1 并发）**：SA-1 建 ‖ SA-3 seam ‖ SA-4 种子清理（PARALLEL）。SA-2 据已锁决策 1 编码（**不再阻塞**）。
- **第一波·5 线**：① LINE-A-AGENT（SERIAL）C-S7-LLM-GATEWAY-WIRE ② LINE-DATA（PAR）C-S11-PIT-ENFORCE ③ LINE-BOUNDARY（PAR）C-S9-BOUNDARY-ENFORCE check→SA-3 ④ LINE-METHOD（PAR）C-S10-COST-GATE + CONTROLPLANE check→SA-3 ⑤ LINE-ENG（PAR）C-S16-BENCHMARK-HARNESS。（前端 C-S0-FRONTEND-CLOSURE 可作机动并发·零热文件争用。）
- **第二波·5 线**：① C-S7-ORCHESTRATOR-WIRE（SERIAL）② C-S17-RUNJSON-PRODUCERS ③ C-S3-LIFECYCLE-GATE 库 ④ C-S5-RAG-AUTOSYNC ⑤ C-S11-INSTRUMENT-MERGE。
- **第三波·ENFORCE 波（经 SA-3 + main.py·已解锁）**：经 SA-3 一次串 promote.py = C-S17-RDP-PROMOTE-ENFORCE + C-S9-ENFORCE-wire + C-S10 cost/controlplane-wire + C-S13-RELEASE-ENFORCE + C-S16-ENGSTD-WIRE；并发非 promote 的 main.py 串行槽：C-S2-HANDOFF ‖ C-S14-RESOLVER-WIRE ‖ C-S0-COVERAGE-INTEGRITY ‖ C-S2-CANVAS-ENFORCE ‖ C-S4-SECRET-REVOKE-CASCADE（中心排序）。
- **第四波·闭合 + 余 enforce**：C-S0-ENTRYRUNS ‖ C-S14-RELEVANCE-CERT + MATERIALIZER ‖ C-S12-LADDER-ENFORCE + C-S12-MONITOR-IC ‖ C-S15-PICKLE-DEFAULT-ENFORCE + RECERT-PRODUCER + SERVING ‖ C-S13-WAIVER-DISPLAY-SWEEP + C-S7-AGENTCODECHANGE-GATE + C-S6-MATHCHAIN-AUTOWRITE。
- **第五波·总闸 + 诚实桩**：C-S0-DEPLOY-SMOKE ‖ C-S0-DELIVERY-TOTALGATE ‖ C-S17-REAL-RUNNERS（诚实 fail-closed）‖ §10 池卡（MinTRL/CPCV/conformal）‖ 各 KNOWN_RUN_GAP 诚实 seam。

### G. 争用图（中心必协调）
- **`main.py`** —— 全部 CENTER-SERIAL 卡·硬串行（C-S7×2 / C-S2×2 / C-S0-COVERAGE-INTEGRITY / C-S14×2 / C-S4-CASCADE / C-S3 端点 / C-S11 端点 / C-S12-LADDER / C-S0-TOTALGATE / C-S17-REAL-RUNNERS / C-S15-SERVING 端点）·绝不两张同飞。
- **`ide/promote.py`** —— 六门相撞（§9/§10×2/§13/§16/§17）·**靠 SA-3 解**：各线并发建孤立 check（一二波）·中心一次串链（三波）。无 SA-3 = 六次串行改 promote.py。
- **`agent/orchestrator/orchestrator.py`** —— C-S7-ORCHESTRATOR-WIRE / C-S7-AGENTCODECHANGE-GATE + 在飞 C-S9-BOUNDARY-ADVISORY·LINE-A-AGENT 内串。
- **`research_os/spine.py`** —— schema 源（EntrySource/RuntimeStatus）·第零波冻 schema·下游只消费；SA-4 + C-S6 碰它·排序。
- **`research_os/goal_coverage.py` + `platform_coverage.py`** —— 都消费 SA-1·序在 SA-1 后。
- **`research_os/market_data_contract.py`** —— C-S11-PIT-ENFORCE（一波）+ C-S11-INSTRUMENT-MERGE（二波）都碰·同 LINE-DATA owner 内串。
- **前端 `RunDetailPage.tsx`** —— **冻结**（RULES.project）·所有 UI 卡（MinTRL/conformal/CPCV/waiver/GoalClosurePanel）走新页/卡·绝不改冻结页。

### H. KNOWN_RUN_GAP 登记（诚实不闭合·库超前数据·绝不假闭）
| 卡 | 节 | 为何此处不能真闭 |
|---|---|---|
| C-S4-PROVIDER-AUTH / HEALTH-POLL | §4 | 真 OAuth/device consent + provider health/quota API 缺·API-key+keystore 已真 |
| C-S5-RAG-EMBEDDING | §5 | 外部 embedding+向量库缺·local-hash 诚实基线·GOAL 未强制外部 |
| C-S10-FAULTDRILL | §10 | 真券商/venue 故障注入需真 venue |
| C-S11-ASSETCLASS-MATH | §11 | 真逐类市场数据（期权链/FX 价/债券曲线）缺 |
| C-S12-MONITOR-IC（live 半） | §12 | live 实盘逐因子绩效馈源需真钱·paper/backtest IC 为诚实过渡（决策 4） |
| C-S12-VENUE-ADAPTER | §12 | 机构 venue 缺·真钱=用户按键·A股 live 禁 |
| C-S13-ORG-INDEPENDENCE | §13 | 无真组织→只单人功能独立性诚实（合 GOAL） |
| C-S17-REAL-RUNNERS | §17 | 真 CI/部署/对象存储/canary 基建缺·建诚实 fail-closed seam |

> 建真·fail-closed seam（系统对「unavailable」诚实），但所属节**不翻「已全落地」**·保持 genuine_partial + 显式 KNOWN_RUN_GAP（守 GOAL §0 line21 / §16 mock 诚实）。**§15-SERVING 已据决策 3 移出本表为真活。**

### 残余待定（仅这两项·非我拍·其余 GOAL 已决照建）
1. **§5 外部 embedding**：收 local-hash 作诚实生产基线·还是投真外部 embedding provider（成本/凭据）？GOAL 未强制。
2. **「交付总闸」权威 spec 节位**：memory 引「GOAL §9 交付总闸」但 §9 是因子/策略边界·可上线条件在 §0·交付在 §17 —— 建 C-S0-DELIVERY-TOTALGATE 前钉准节位。

---
> ↓↓↓ 以下为 2026-06-26 原施工图（导航总览·保留不动）↓↓↓

# 施工图 · GOAL §0-§17 → task DAG（一中心 + 5 并发 deep-opus）

> 三方独立研究并集（中心 Claude + deep-opus 代码核验 + codex gpt-5.5·xhigh），2026-06-26 建。
> **单一现状源 = 各 pool/dev 卡的 depends_on DAG + dev/state**；本文件是【导航总览】，实时依据永远是卡原文 + 代码。
> 派 opus 前必读：dev/GOAL.md（完整 §0-§17·2076 行·已 canonical on main）+ dev/RULES*。

## 0. 基线真相（代码实证 · 派 fleet 的前置）

- **GOAL canonical**：完整 §0-§17 已 commit 进 main（此前只在本地未提交·已修双源漂移）。
- **集成基线 = main + auto/math-spine**：Mathematical Spine 全套 + 验证纵深件（conformal/cpcv/drift/attribution/impact/lifecycle_metrics）在 `auto/math-spine`（9 ahead·**land 进 main = 一切 spine-dependent 验收的对照基线**）。`fix-u2-synth`(47d79a9) 已是 main 祖先、无需 land。
- **三态成熟度**（贯穿全表，别重复做已 done）：
  - ✅ **已建不变量**：`lineage/ids.py` 单一身份源 + ledger 哈希链/honest-N、`dag/kernel.py` 确定性内核、approval(approver≠creator)、verifier(Independence 度量)、OrderGuard 全 venue + CI 矩阵、SQLite WAL、append-only JSONL、content-addressed、LLM 决策级 replay、provenance 血统门、kill switch(IP+PBKDF2/TOTP)、前端整套台 + 画布引擎 + agent 窗口 epic。
  - 🟡 **auto/math-spine（land 即生效）**：Mathematical Spine + CPCV/conformal/attribution/MinTRL/drift/impact/lifecycle_metrics。
  - 🟥 **greenfield 硬地基**（全仓 0 hit 实证）：QRO/ResearchGraph/GovernedCompiler/CanonicalCommand、LLM Gateway/Registry/Routing/CredentialPool/LLMCallRecord、Document Intelligence 全栈、RDP 开放格式导出、StrategyBook/Forecast 对象、方法学控制面 6 档、发版门禁套件、§11 多资产语义/InstrumentSpec/MarketCapabilityMatrix。

## 1. 七条 LINE（territory + 依赖 + 文件争用）

> 一条 LINE = 内部串行依赖链 + 一块尽量不交叠的文件 territory，分配给一个 deep-opus。中心控并发=文件争用：绝不让两张碰同一文件的卡同时在飞。

| LINE | territory（owner） | 内部串行链 | 阻塞下游 |
|---|---|---|---|
| **LINE-0 集成基线**（中心/leader） | 三流合一 diff · `main.py` 集成窗口 | land auto/math-spine → 全量验证 | 全部（spine 验收对照） |
| **LINE-A 对象脊柱**（gap#1#2·最硬地基） | 新 `qro/` `graph/` `command/` `compiler/` `governance/invariants` + 前端画布投影 | QRO 信封 → ResearchGraph IR → CanonicalCommand → Compiler →（扇出）Canvas/Desk/治理收口 | 几乎全部·收编 ids/kernel/ledger/approval/spine_gate **不重造** |
| **LINE-A-AGENT**（§7§4§8·最强上游瓶颈） | 新 `llm/`(Gateway/Registry/Routing/Pool/CallRecord) + `agent/orchestrator.py` `roles/` | LLM Gateway → Orchestrator → 12 role → 23 事件投影 | D-ENG-3/RDP-2/TRUST-1/DOC-4/ENG-1·收编 replay/keystore |
| **LINE-B 数据PIT脊柱**（gap#6+RAG） | 新 `ingestion/` + `field_catalog/` `universe/` `data_pull.py` `agent/rag.py` | PIT 接线 ‖ DatasetVersion 写门 ‖ IngestionSkill ‖ SecretRef ‖ RAG 升级 | C-METH-2(feature-leak)/RDP-2/B-INST |
| **LINE-C 模型/因子/信号**（gap#5§15§9§10剩余） | `models/` `training/` `signals/` `factor_factory/` `strategy/`(新) `methodology/`(新) `portfolio/` `eval/` | 模型治理 ‖ Forecast→Signal→portfolio typed contract ‖ 因子生命周期接转移 ‖ StrategyBook ‖ 方法学控制面 ‖ spine_gate 接 promote | C-CONTRACT-3/STRAT-3 跨 LINE-G |
| **LINE-E 交付信任**（§17§13§16·北极星总闸） | 新 `delivery/`(RDP) `release_gate/` `runtime/`(profile) `governance/` | RDP schema → 聚合器 → 残余字段 ‖ 发版门禁 ‖ no-silent-mock 中心守卫 ‖ Binding/ConsistencyCheck 门 | 终态交付·汇聚 A/spine/B/C 字段 |
| **LINE-G 执行/文档**（§12§6·安全红线） | `execution/` `risk/` `monitor/production.py` `documents/`(新全栈) `instruments/` | 生产监控调度 → live ladder → graded kill ‖ Document intake 安全栈 → EvidenceSpan → 信任边界 | 跨 B-INST/A Gateway |

**关键文件争用（必排序·写进卡 depends_on）**：`main.py`=中心独占 · `lineage/spine.py`=C0 先定 schema·下游只消费 · `training/codegen.py`=B-PIT(装载入口) 先于 C-CONTRACT(出口) · `eval/overfit_gate.py`=扩展不替换(LINE-0 已落 DSR helper) · `portfolio/gate.py`=冻结不动 · `governance/responsibility.py`/`methodology_choice.py`=LINE-C/E/G 共建单一 schema · `instruments/`=LINE-B owns·LINE-G 消费。

## 2. 波次计划（中心动态补派·活的任务池）

> **前沿实证刷新（2026-06-26 中心 loop）**：① **LINE-0 已完成**——`auto/math-spine` 已 land 进 main（origin/main 严格领先 origin/auto/math-spine 7 提交、spine 分支 0 unique commit），Mathematical Spine 全套 + 验证纵深（cpcv/conformal/drift/attribution/mintrl/impact/lifecycle）已是 main 基线、spine-dependent 验收对照已就位。② **W5 D-EXEC-3（`de764e1c`）已 done**（在 `tasks/dreaminate/done/`）。③ 基线 = origin/main，全量 **1734 tests collected**。

**第一波就绪前沿——已 mint+派发（2026-06-26·4 条 deep-opus 在飞，文件领地不交叠）**：
- **W1 C-MODELGOV-1-full**（uuid `36f88f6b`·分支 `wave1/w1-artifact-trust`）——止血已 done（`training/lib.py` RestrictedUnpickler+weights_only）；完整 producer-run+hash 信任门 + allowlist + safetensors。领地 `training/lib.py`(+新 `training/artifact_trust.py`)。
- **W2 B-PIT-1**（uuid `e01bf12f`·分支 `wave1/w2-pit-wiring`）——`training/codegen.py:25` raw parquet → 消费 `load_panel(as_of_known)`（catalog.py:197 已就绪）堵 look-ahead。领地 `training/codegen.py`。
- **W3 B-VERSION-1**（uuid `0430cd78`·分支 `wave1/w3-dataset-write-gate`）——不可变门已建（`data_hash/dataset_hash.py`），真 gap=接进实际 ingest 写路径强制缺 version/checksum→拒。领地 `data_hash/`+`connectors/base.py`+`data_quality.py`。
- **W4 D-RDP-1**（uuid `9d593481`·分支 `wave1/w4-rdp-schema`）——greenfield `delivery/` RDP schema+manifest+§17 四拒绝门。领地 新 `delivery/`。

**第二波起**（LINE-A 出契约后扇出·当前最强上游瓶颈）：QRO/Graph/Compiler/Command、LLM Gateway/Registry/Routing、Document Intelligence、StrategyBook/Forecast/方法学控制面、RDP 聚合器接 promote、发版门禁。**LINE-A（对象脊柱）是几乎全部下游的依赖**——wave-1 land 后中心宜开 LINE-A 线（greenfield `qro/graph/command/compiler`·收编 ids/kernel/ledger 不重造）。中心每完成一卡从更新后就绪前沿补派，保持 ≤5 满载。

## 3. 「拍板项」绝大多数是 GOAL 已决——读 GOAL 直接建，别当开放决策问用户

> **2026-06-26 用户纠正（多看 GOAL·有答案·不用问·直接做）**：此前把 GOAL §0-§17 已明确写死的终态当成「待拍板」列给用户 = 没好好看 GOAL。**opus 线遇到这些读 GOAL 对应节直接建，绝不问用户。**

**GOAL 已决（照建·不问）**：
1. **多资产范围 = §0(line 13-15)+§11 已决**：面向所有公开二级市场（股/指数/ETF/基金/债/利率/FX/期货/商品/期权/加密现货·永续·期权/宏观/链上/另类/自定义）；IPO/一级/私募/HFT/做市在外。§11 给每类资产语义（期权 expiry/strike/multiplier/settlement、期货 roll、债 duration、FX rollover）+ MarketCapabilityMatrix + 可证伪验收（缺 expiry/strike→拒）。
2. **方法学控制面 6 档 = §10 已决**：strict/standard/loose/exploratory/custom/user_waived 六档命名 + 语义（系统展示代价/证据缺口/适用环境/推荐/责任边界·**user 运行时自选**·记 MethodologyChoiceRecord·按真实状态限制展示·晋级·导出·运行）。**这是系统提供的用户运行时旋钮，不是我问用户的拍板。**
3. **因子退役/去重 = §9/§3+R21 已决**：生命周期七阶段（衰减/拥挤/容量/因子族/相似冗余/退役/跨策略复用）+ 可证伪验收「退役因子被新策略默认采用→拒」；具体数值是 §10 用户可配档。
4. **模型风险分层/materiality = §15 已决**：model_risk_tier/materiality/intended_use/prohibited_use 是必含治理字段；高风险缺 challenger_result→拒、晋级缺 ValidationDossier→拒。
5. **artifact 安全 enforce = §15 已决**：external pickle **blocked by default** + producer-run+hash binding + safe tensors preferred + torch weights_only + sandboxed load。**enforce 默认开是终态**（W1 接全 producer 后默认开·非永久 opt-in；opt-in 仅作 producer 未接齐时的过渡）。
6. **用户方法学自主权 = §10/§13 已决**：系统记录 MethodologyChoiceRecord、user 选松紧/跳过、放宽不得标强证据/生产可上线。生产 profile 松紧同属 §10/§16 用户运行时档（系统提供·不问）。
7. **LLM 默认路由 = D-LLM-ROUTING 已决**（2026-06-26 用户拍·混合自适应·可配）。

**genuine 人类动作项（非设计决策·我无需拍）**：
- **A股 live**：RULES.project「A股永不实盘」**锁死·绝不擅动**（比 GOAL §12「未来治理可开」更严·按更严）。
- **mainnet 100U 一周实盘**：用户**亲自按键**·agent 绝不动钱。

**真·开放（GOAL 留作用户运行时·非我拍）**：方法学松紧档由 user 运行时选（§10）。实现细节（如 PDF 解析库 §6）按能力边界选合理默认·不问。**总则：遇「要不要/松紧/范围」先翻 GOAL §0-§17——基本都已决；GOAL 真没写且是不可逆/动钱才点名用户。**

## 4. 红线守卫（全程·任一违反即停工）

A股不实盘（禁 vnpy/easytrader/ths_trader）· 实盘 key 不进 LLM/RAG/日志/导出 · OrderGuard 唯一下单入口（新 venue/端点禁裸调 place_order）· 杠杆护栏接所有路径含中继桥 · **外来 pickle/torch.load 不安全加载**（已止血·完整门 C-MODELGOV-1）· 单一身份源 `lineage/ids.py` 不另造 · RunDetailPage 冻结 · 生产禁 silent mock fallback · 扩展不替换 · land 仅 leader/admin · 对抗测试种坏门必抓不破基线。

---
> 完整逐节 DAG 表（§0-§17 每节×现状×gap×depends_on×文件领地×可证伪验收）见三方研究记录；pool 卡是其落地单元。中心在 loop 中按就绪前沿动态 mint 后续卡、开新线。
