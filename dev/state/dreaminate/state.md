# STATE · dreaminate 现状（对照 GOAL 的 gap · 重生型）

> 现状 gap,对照 `../GOAL.md` 终态量。**🟡 未验证 ≠ ✅ 已验证** —— 只有挂得出可指认证据(file:line / 测试名 passed / 带口径的指标)的才标 ✅,空泛即假绿灯。
> 重生型:land 后整篇重写为当前快照;会话叙事进 `log/`,续接现场进 `frontier.md`,都别堆在这。
> 本版 2026-07-14 整篇重写(蒸馏此前 2026-06 全部追加块——原文在 git 历史 `git log dev/state/dreaminate/state.md`)。

## 进行中
- **🧭 module-convergence 扫描结论(2026-07-15 · 用户令「收敛具体模块直到 GOAL 全收口」后 Plan 独立扫)**:剩 3 个 🟡 模块**全撞用户门/外部依赖**,无 decision-free 干净本地切片。逐一(据 file:line 核实):
  - **§8 Governed Compiler**:治理主干已建全(governed_compiler.py 5 命门);唯一「未做」=neural-graph codegen(training/codegen.py:239 仅支持线性链子集·分支/机制嵌套留后续)=**方法学重**(branch/merge 语义=设计空间无单一正解),且属 build 台 feature-completeness 非 correctness 治理。→**方法学待拍板**。
  - **§4 Settings/LLM Gateway**:registry/keystore/routing/gateway 已建;残余 OAuth/device-code/全 connector(GOAL §4:610)=**外部阻塞**(需真 IdP 端点+浏览器同意+真凭据·踩 OAuth/明文 secret 边界)。→**external-blocked**。
  - **§13/§17 RDP**:机制**已建全且已接进两条真 promote 路**(approval/gate.py:179·paper/desk.py:1001);末公里卡两处:①in-code scope 决策 `D-SCOPE-CONSERVATIVE`(aggregator.py:31·是否 require_rdp=True 强制)②**不可伪造真链证据**(gate1/gate3 需诚实 reproducibility_command+unverified_residual·真 LLMCallRecord 部分待用户凭据·自动填=honesty 门拒的假绿灯)。→**scope-gated + evidence-gated**。
  - **推荐 unblock(=最接近可做·最高杠杆)**:§17 RDP **advisory-first**——用户绿灯保守版(用现有 aggregate_rdp 组装本链 RDP·挂 promote manifest·require_rdp 保持 False/producer 仍 advisory·residual/repro 诚实手写)即成干净加性可逆切片;骨架+3 对抗测试见 Plan 扫描(promote_assembler.py:1005 honest-empty seam·section17_rdp_gate.py:34)。**仍需用户 scope 绿灯 + 真链证据(凭据)**。
  - **→ ③ 模块轴**:三门全待用户拍(§8 方法学 / §4 external / §17 scope+evidence)。报 decision-ready brief 等用户挑;§17 advisory-first 若绿灯即执行(跨厂商 duet)。
- **✅ 系统级凭据 repr 泄露收口已 land(de002c86 · 2026-07-15 · 数据泄露红线 defense-in-depth)**。
  起源:loop ③ 期间选最高杠杆非用户门 correctness→深度红线审计(**A股永不实盘 判 HOLDS**:8 层 choke-point,
  单一 classify 源+OrderGuard+copy_trade 硬 crypto+7 处 execution_boundary 精确集+IMMUTABLE a_share_live 不可豁免+无 env bypass)。
  审计逮裸 @dataclass/Pydantic 的 secret 字段经默认 repr/str/%s/traceback 明文泄露。**跨厂商 codex 3 轮收敛**:
  ①系统性 scope(逮第 3 处 WSStreamerState + 越出 3 处)②P1 stale-generation(create_listen_key 轮换后老连接 error 携旧 key,
  只打码当前 key 漏)③**SOUND to land**。**修 10 类**:dataclass→field(repr=False)(TokenClient.token·ReleaseCandidate
  .gateway_secret/known_secrets·NodeExecutionContext.token·LLMProviderRecord/LLMGatewayCallRequest.plaintext_credential)·
  Pydantic→Field(repr=False)(CapabilityToken.sig·_AuthSpec.static_value→GenericRESTConfig)·WSStreamerState 打码 listen_key
  字段+`_redact`(历史∪当前 key)封 6 处 error 串 capture 点。原则:**accidental(repr/str/log/traceback)必闭;functional
  序列化(to_dict/model_dump 供签名/持久化/传输)是显式边界保真**。对抗测试 8→23(+12 系统 +3 P1,变异牙口全 red-then-revert)。
  builder=Claude(deep-opus+我 P1 补丁)/verifier=codex(GPT) 跨厂商 SOUND。**后端全量 6511 passed/13 skipped/0 failed(分块实跑规避环境 kill)**。
  残余(如实登记非阻塞·模块未接线原型):64-key 历史上界(>65 轮换后最旧 key 漏·现生命周期不可达)·asdict 面 tripwire-gated·真 generation rotation 待实现时重估。
  证据/全弧见 [[redline-audit-ashare-credential-repr-crossvendor-20260715]]。
- 卡 9c5e6975 已 done(2026-07-15):切片② dual-model **真跨厂商调用收口**——订阅账号 auth+
  onboarding 全做(陌生用户从零)、dual_model_review 接订阅、真跑 independent=True 逮 builder
  夸大。切片③ CI ✅、on_event 迁移 ✅、bundle 拆分 ✅ 均已 land。/loop 15m 自主循环运行中;
  下一步转用户可感知面(队列见 frontier)。

### 顶部刷新块（本轮值 · 每轮覆写）
- **✅ Claude-Code 内嵌 agent M4a「orchestrator + SSE 映射 core」已过四门·待 land main(分支 `agent-m4-orchestrator-sse-20260716`·从 main b0eed5f0·产品 commit ec506137·用户 2 次拍板「claudecode 式 agent/epic fork-2 可直接做」)**。
  - **建**：`app/agent/backends/events.py`（BackendEvent 联合 + `backend_events_to_sse` 映现有 SSE 词汇 say/tool_start/tool_end/done/error·纯函数）+ `scripted_backend.py`（回放定序·无 subprocess·ready 开关）+ `session_orchestrator.py`（preflight not-ready→**诚实 error 不 fallback**·backend.run()→SSE·cross-process 写→`refresh_store()`）。复用 workbench_stream.sse_format。route 留 M4b。
  - **对抗测试 17·5 变异有牙**（去 not-ready 门/去 refresh hook/去 terminal 强制/去 except/去 liveness cap→红·字节还原）。
  - **🔴 跨厂商 codex 复审 2 轮 UNSOUND→修（诚实边界价值）**：R1 逮 ①**terminal 未强制**（多 Done/Done 后尾随帧漏）②**异常逃逸**（preflight/run/refresh raise 无 honest error 直崩 500）→ 修：首 done/error 终止+丢尾随、全程 try/except→honest error+done。R2 逮 ③BaseException seam 与 `except Exception` 契约不一致 ④**无 liveness 边界**（无限流永不终止）→ 修：seam 收 `Exception`（BaseException 控制流信号正确传播）、`max_events` cap（超限 honest error+done·无限流实测不挂）。**R3 复审中**（b9saalcwv）。
  - **四门全绿**：①后端全量分块 **6834 passed/13 skipped/0 failed**（5 chunk:1451+1536+1517+1416+914·signal timeout·真汇总行·codex done 后干净跑无叠跑）+ 前端 430 passed + build✓ + compileall✓；②validate_dev PASS✓；③评审门=**跨厂商 codex 3 轮 R3 SOUND**；④data/audit 基线无异常。diff-check CLEAN·GOAL 零 diff。
  - **六字段**：1 Local=分支 ec506137（+dev commit 待提）；2 Remote=待 push；3 Tests=后端 6834 passed/0 failed+前端 430；4 CI=Unqueried；5 Prod=Unqueried；6 User acceptance=Unverified。
  - **NEXT**：dev/ commit（state+finding）→ ff main+push→gh 查 CI。M4a land 后 M4b（main.py 新路由 `GET /api/agent/session/stream` + claude stream-json→BackendEvent parser）。
- **✅ Claude-Code 内嵌 agent M3「claude 后端 spawn 契约·L-C 红线」已 LAND main(分支 agent-m3-claude-backend-spawn-20260716·从 main 2ef0bb9a·产品 a2c69ba1+dev b0eed5f0·CI in_progress run 29496890528·跨厂商 codex floor 3 轮 R3 FLOOR-HOLD)**。
  - **建**：新 `app/backend/app/agent/backends/{__init__,base,claude_backend}.py`（纯 builder·不 spawn）——`build_agent_argv`（stream-json+`--strict-mcp-config`+canvas MCP 工具+`--permission-mode`）、`build_spawn_env`（**L-C 红线**·显式 allowlist·无 QUANTBT_MASTER_KEY/venue secret）、`build_mcp_config`、`preflight`（复用 provider_auth_report）。`PermissionTier` 用户可配（放权）。
  - **🔴 跨厂商 codex floor 3 轮·逮真红线破口（这正是强制复审的价值）**：R1 FLOOR-HOLE 逮 **prompt argv 注入**（claude 2.1.210 把 `--mcp-config=/evil.json` 当真 flag 解析·绕 strict-mcp 注入恶意 venue-tool MCP server）+ preflight 假绿（API key 冒充 ready）+ 外来 mcp__ + NODE_OPTIONS。→ 修：prompt 移出 argv 走 **stdin**、model dash-guard、preflight=cli_installed AND subscription_authed、去 NODE_OPTIONS/NODE_PATH、strip 外来 mcp__。R2 FLOOR-HOLE 逮 **comma-smuggling**（`"Bash,mcp__evil__x"` 单元素绕 per-element filter）。→ 修：先 comma-split·再 drop 含 `mcp__` 任意位置 token（**同时挡 comma+space smuggling**·paren spec `Bash(git *)` 存活）。**R3 复审中**（bff2atedk）。
  - **对抗测试 15**（`test_agent_backend_spawn_contract.py`）：env allowlist（master/venue/opaque/NODE_OPTIONS 排除）、strict-mcp、外来 mcp__ strip、comma+space smuggling、prompt 不在 argv、model dash reject、preflight 诚实。**7 变异全有牙**（copy-all env / 去 strict-mcp / 去 mcp__ strip / 去 node-var 排除 / 去 model-guard / preflight 信 generic / per-element filter）·均字节还原。
  - **四门全绿**：①后端全量分块 **6817 passed/13 skipped/0 failed**（5 chunk:1507+1525+1391+972+1422·各 gtimeout+`--timeout=120`·**凭真汇总行判绿**·chunk 1 的 rc=1 已查明=`--timeout-method=thread` 令进程多线程→forking 测试触 fork-warning 的伪退出码·单跑 rc=0·signal 法干净）+ 前端 test:run **430 passed** + build✓ + compileall✓；②validate_dev PASS✓；③评审门=**跨厂商 codex floor 3 轮 R3 FLOOR-HOLD**；④data/audit 基线无异常（不碰 data/）。diff-check CLEAN·GOAL 零 diff。
  - **六字段**：1 Local=分支 a2c69ba1（+dev commit 待提）；2 Remote=待 push；3 Tests=后端 6817 passed/0 failed+前端 430 passed（真汇总行·分块带 timeout）；4 CI=Unqueried（push 后 gh 查）；5 Prod=Unqueried；6 User acceptance=Unverified。
  - **NEXT**：dev/ commit（finding+state）→ ff main+push→gh 查 CI。M3 land 后 **M4**（orchestrator 驱动外部 CLI agent 跑循环+新 SSE 路由·backend.run()→BackendEvent→现有 SSE 词汇·写后 RESEARCH_GRAPH_STORE.refresh() 跨进程写可见）。L-D（CANVAS store 级 OFFLINE 不变量）属 M5。
- **✅ Claude-Code 内嵌 agent M2「canvas_read 端到端」已 LAND main+CI(分支 `agent-m2-canvas-read-e2e-20260716`·从 main 9eec88b1·产品 commit 7e1dd20f)**。
  - **建**：无钥 `canvas_read` 从只读节点扩到 **nodes+edges 语义投影**——`store.graph_edges()` lineage 关系（from/to/relation_type）限定双端点都在投影(owner 过滤)节点集内 → **owner 过滤透传隔离边**（A 永不见 A↔B / B↔B 边）。shape `{nodes, edges, count, edge_count}`·节点仍语义记录（**非前端像素布局**·refine finding §5「shape==前端契约」为 Inference·可翻案）。
  - **对抗测试 4**（`test_agent_mcp_canvas_read_e2e.py`·e2e·经 `upsert_qro`/`record_graph_edge` 真命令路径播种）：owner A/B 节点隔离、**跨进程 append→read 可见**（另进程 store 写·agent store `refresh()` 见）、边 owner 隔离、边 shape。变异去双端点门→Bob 泄露 A 的边=红→字节还原。M1 floor 测 shape 断言同步更新。
  - **四门全绿**：①后端全量分块 **6802 passed/13 skipped/0 failed**（5 chunk:1517+1395+971+1438+1481·各 gtimeout+`--timeout=120`·真汇总行·perf harness 在 chunk_3 内跑过）+ 前端 test:run **430 passed** + build✓ + compileall✓；②validate_dev PASS✓；③评审门=**跨厂商 codex 复审 SOUND**（probe 验 A-B/A-A/B-B 边隔离·tombstoned 排除·floor 仍 {canvas_read} 无新 import·读侧 byte-identical）；④data/audit 基线无异常（不碰 data/）。diff-check CLEAN·GOAL 零 diff。
  - **六字段**：1 Local=分支 7e1dd20f（+dev commit 待提）；2 Remote=待 push；3 Tests=后端 6802 passed/0 failed+前端 430 passed（真汇总行·分块带 timeout）；4 CI=Unqueried（push 后 gh 查）；5 Prod=Unqueried；6 User acceptance=Unverified。
  - **NEXT**：dev/ commit（finding+state）→ ff main+push→gh 查 CI。M2 land 后 M3（claude 后端 spawn 契约·argv/env builder 纯单测·**L-C spawn env 白名单**在此落·env 无订阅 token 无 master key）。
- **✅ Claude-Code 内嵌 agent M1「无钥地基先立」已 LAND main+CI 绿(origin/main 39c29092·产品 920eeaa5+dev 39c29092·CI success run 29490552427[9eec88b1])**。
  用户 2026-07-16「放权给 user·只提供平台·别太严厉」+「含 canvas 写」+ 火力全开 duet 后，按 finding `[[claude-code-agent-impl-plan-duet-20260716]]` §5 起 M1（红线地基·只读 canvas_read；write 延 M5·先证无钥再上写工具）。
  - **建**：新兄弟包 `app/backend/app/agent_mcp/`（bare `__init__`）+ `server.py`（stdio 官方 mcp SDK 低层 `Server`+`stdio_server`·注册**恰好** `{canvas_read}`·只 import `app.paths`+`app.research_os.spine`）+ `tests/test_agent_mcp_redline_floor.py`（8 测）+ `requirements.txt` 钉 `mcp==1.28.1`。
  - **★ build 时逮 L-B 定位错并修**：finding 原写 `app/agent/mcp/`＝**错**——实测 `import app.agent` 级联载 `app.security.keystore`+`trading_credentials`（`__init__.py:17`→llm_providers）。Python 导子模块必先跑父包 `__init__`·无法 opt-out→server 必须落**兄弟包 `app/agent_mcp/`**（实测 `import app.agent_mcp.server`→**0 danger 模块**）。已回写 finding §3 ★M1 落地校正 + 模块表。
  - **红线 floor 证据（非 prose·经验断言）**：L-A 注册表=={canvas_read}·dispatcher 拒 venue/order 名；L-B **新解释器**子进程 import→danger 模块集==∅。**3 变异全有牙**（加 place_order→L-A 红；注 keystore→L-B 红；解锁构造→race 守卫红）·均字节级还原。
  - **跨厂商 codex floor 2 轮**（builder=Claude·verifier=GPT·approver≠creator）：R1 判 **FLOOR-HOLE**——A/B/read-only 全 HOLD·逮**首次构造 race**（懒构造 `_load_existing` 未持跨进程锁·writer partial-tail 时撕裂 fail-closed 崩）+ read-only 精度（建 audit/+.write.lock 非 graph 变更）。**已修**：构造移进 spine 自身 `_persistent_research_graph_write_lock`（server.py:83-85）+ docstring 精确化。**端到端证**：解锁构造 RAISE ResearchGraphError·修后 blocked 0.70s→count=0 无崩。**R2 判 FLOOR-HOLD**——race 闭、无自死锁（`_RESEARCH_GRAPH_PROCESS_WRITE_LOCK`＝RLock spine.py:107·`_load_existing` 不重取锁）、A/B 仍 HOLD、claim 诚实。
  - **四门全绿**：①最低验证——后端全量**分块** 6798 passed/13 skipped/0 failed（5 chunk:1403+986+1440+1480+1489·各 gtimeout+`--timeout=120`·真汇总行·规避未分块 env 挂死）+ perf harness 72 passed + 前端 test:run 430 passed + build✓（bundle>500kB 是既有 gap 非 M1）+ compileall✓；②validate_dev PASS✓；③评审门=**跨厂商 codex floor 2 轮 FLOOR-HOLD**（内部无钥安全模块·比 autoplan 产品透镜更相关更强的审）；④data/audit 基线无异常（M1 不碰 data/）。diff-check CLEAN·GOAL 零 diff。
  - **六字段**：1 Local=main 39c29092；2 Remote=**origin/main 39c29092（已 push·M1 已 land）**+分支 agent-m1-mcp-nokey-floor-20260716；3 Tests=后端 6798 passed/0 failed/13 skipped+perf 72+前端 430 passed（真汇总行·分块带 timeout）；4 CI=**in_progress**（run 29490458231·下轮 gh 复查）；5 Prod=Unqueried；6 User acceptance=Unverified。
  - **NEXT**：下轮 gh 查 CI 转绿→落定；随即 M2（canvas_read owner-scoped 真投影端到端·跨进程 append 后 read 可见·owner A/B 隔离·shape==前端契约）。L-C/L-D（spawn env 白名单·CANVAS store 级 OFFLINE）属 M3/M5·不 gate M1。
- **✅ §17 RDP coercion 穷尽审计已 LAND main(2026-07-16·用户放行「只要是好的就能 push」)**。origin/main **7fe5271f→b0af451d**(5 commit:6b231bdc R1-R6 系统修 + f0cb449d finding + 04cccb03 record 层 canonical 门 + bc4fff86 适配器层 + b0af451d 落档)·CI in_progress(run 29481615251)。断点(landed·分支 `parked/s17-coercion-failopen-6rounds-20260715` 已 push):
  - **record 构造层**(commit 04cccb03·前轮已 codex SOUND 到 R6)+ **HTTP 适配器层**(commit **bc4fff86**·本轮新)。
  - 本轮做完:main.py **9 个 RDP HTTP 适配器**(deployment_attestation×2·health_check·source_run_integrity·publish·external_publication×2·ci_release_attestation×2)+ 4 choke-point helper 的**直接 HTTP-payload 标量 ref** 全改走 `_rdp_str`(str(dict) 洗白→拒非 str→422);runner-result `str(raw_result.get)` 面**已机械验证 fail-closed**(`_validate_*_field_shapes` 拒 dict/list·SCALAR=ALLOWED−SEQUENCE),非直接 HTTP 面不改。
  - 对抗测试:endpoint 级(health 7 字段+deployment_attestation 真 POST→422+guard 归因)+ helper 级(ci_release+external_publication field builder)。**变异验证**:neuter rollback_readiness_ref→dict 洗白成 **200**(RED)·还原 byte-identical→GREEN。
  - **跨厂商 codex 复验 = round-3 判 COMPLETE**(builder=Claude·verifier=codex GPT xhigh 115k tok·approver≠creator)。R1 被 OpenAI cyber-risk 过滤拦·R2「search main.py」发散 TaskStop·**R3 diff-scoped 收敛**:独立 AST 扫 33300-34760 证①无遗漏标量面②`_rdp_str` 行为保真③residual fail-closed。**独立 AST 法与我 grep self-audit 殊途同归**。
  - push：**用户 2026-07-16 明授权「可以放行·只要是好的就能 push」**(此前 auto-mode classifier 拦 loop 授权·真人放行后清)。此后 loop 内 push 好的已验证切片放行。
- **六字段**:1 Local=main==**b0af451d**;2 Remote=**已 push·§17 已 land main**(origin/main b0af451d);3 Tests=受影响 RDP+§17 **522 passed** + **后端全量分块 6645 passed/0 failed/13 skipped**(5 chunk·真汇总行·各带 1500s timeout)·compileall ✓·validate_dev PASS·diff --check CLEAN·GOAL 零 diff;4 CI=**in_progress**(run 29481615251·待复查);5 Prod=Unqueried;6 User acceptance=Unverified。
- **🔄 IN-PROGRESS 切片 = Trust 释放门同族 coercion 收口**(非用户门·同 §17 class·分支 `trust-coercion-failopen-20260716` 从 main ddadb679·复用已验证 `_rdp_str`)。**已侦查确证 fail-open real+safety-adjacent**：`validate_external_expert_review`(trust_layer.py:568) 对 **reviewer_independence_ref/reviewer_ref/release_ref/artifact_ref/review_protocol_ref** 仅 `_present`(非空)检查→`str({..})` 伪造非空 ref **洗白独立性机制**(核心诚实不变量·dual-model 门守的正是它);唯 `verdict` 有 allowlist{approved/vetoed/needs_revision}=fail-closed。**多 adapter map**(待改·全 `str(raw/payload.get(x) or "")`)：①`_external_expert_review_from_payload`(main.py:32016·5 洗门字段)②`_external_reviewer_identity_from_payload`(review_ref/identity_ref/signature_b64/attestation_ref/verified_signature_ref)③`record_trust_release_check`(release_ref/check_kind/scenario_ref/expected+observed_behavior_ref)④release_check_suite/pressure_run(release_ref/runner_mode)⑤trust_claim/independence_disclosure/user_autonomy/release_gate 走 `*_from_dict`(待查是否同族)。alt caller trust_layer.py:1772(内部·非 HTTP)。
  **✅ inline 适配器层已做+验+commit be3b0d8f**(Trust 分支·未 land)：5 HTTP 适配器(expert_review/expert_signature/release_check/release_check_suite/pressure_run)走 `_rdp_str`/`_rdp_tuple`·对抗测试 +12(test_trust_layer 55 passed)·**变异验** neuter reviewer_independence_ref→dict 洗白成 200(fabricated independence 落盘·RED)→还原 GREEN。
  **✅ from_dict 反序列化层已做+验+commit f0192be4**：审计逮 inline 修的 `source_hash` bypass(main.py 绕 _rdp_str)+ functional_independence/user_autonomy/reviewer_identity/trust_claim 直走 from_dict 的 raw dict-ref 洗白。新 `_req_str`/`_opt_str`·5 deserializer 走之·对抗 +6·变异验(neuter→dict 伪造 dual-model 独立性 attestation 成 200·RED→GREEN)·Trust 全套 153 passed。
  **§17 CI=✅ 绿**(run 29481740197 completed success)。
  **✅ Trust batch 跨厂商 codex round-2 = COMPLETE·已 land main**：round-1 判 INCOMPLETE 逮 ~8 未覆盖同族洗门(release-approval/release-gate/expert-signature/suite checks[*]/pressure-run scenarios[*]/release-check check_ref/deser/persist)→ **round-2 全补**(commit 4a9c1a07·5 deserializer+内联全走 _req_str/_opt_str/_rdp_str·对抗 +13·变异验 neuter approval_ref→DID NOT RAISE=RED)→ **codex round-2 判 COMPLETE**(8 vectors 全 rejected·行为保真·honest path 无破)。序列元素/未 resolve junk-string 仍 documented residual(放权)。**land 全绿门**：后端全量分块 **6676 passed/0 failed/13 skipped**(5 chunk:1182+851+777+3032+834·真汇总行)·compileall ✓·validate_dev PASS·diff-check CLEAN·GOAL 零 diff·跨厂商 codex COMPLETE。
- **🆕 agent epic floor 跨厂商 codex 复审 = FLOOR-HOLE(2 红线洞·已改进设计)**：**P0 动钱红线**——spawn `env=os.environ.copy()`(subscription_cli_llm.py:197/303)带 QUANTBT_MASTER_KEY(解 keystore keystore.py:419)进 agent env·开 Bash 即读 key 达真 venue=我方给的权限→修 L-C spawn env 显式最小白名单+canvas-only token 不可 KeyBroker 兑付。**P1 venue/LIVE 红线**——CANVAS upsert 只默认 OFFLINE 非强制(spine.py:856)·codex 实测 runtime_status=live 成功落→修 L-D store 级 CANVAS 不变量拒 TESTNET/LIVE。codex 证 L-B 无钥 outcome 成立(spine import 不载 venue/key 码)。**改进设计已写 finding §3 L-C/L-D**·**M1 落码前须实现这两修+重 codex 复审 floor**。
  **🔥 火力全开 4 审计流全回(S1-S4·~15 safety-adjacent 不假绿灯洗门)**：Trust 独立性/autonomy·runtime-promotion LIVE 治理 refs·venue-safety M17 refs·verification 双模型身份。深层根因 `_present()` 自身 coerce。**放权-calibrated 修法**=reject-non-str 卫生(不强制 registry-resolution=太严厉)。**动钱 mainnet-auth 洗门已修+commit 1f978729**(standing_authorization_statement 必 str·资金红线·变异验)。
- **🆕 IN-PROGRESS 大方向 = Claude-Code 式内嵌 agent(用户 2026-07-16「放权给 user·只提供平台·别太严厉」+ 火力全开 duet)**：**工程实现图 duet 并集已定稿**(deep-opus 全案 ‖ codex 跨厂商校正[permission-mode 非法值/canvas 非 owner-scoped/MCP import 隔离]‖ 我裁决)→ finding `[[claude-code-agent-impl-plan-duet-20260716]]`。recalibrate：PermissionTier 用户可配·红线 floor 3→2 层结构性(非注册+不 import·**唯 3 硬禁**动钱/venue/A股-live)·薄片 canvas 读+写(QRORecord 强制字段)·stdio 官方 mcp SDK·跨进程 refresh-on-write 写回·M1-M6。**NEXT**：**跨厂商 codex 复审 floor(3→2 层安全相关·命门纪律)→ M1(MCP 无钥地基先立)**。
- **audit 基线四项**(不变):61 files / 20,339 lines / 26,209,663 bytes / sha `1c1788b0bbe2`。(改动全在 app/tests,基线按构造不变。)
- **✅ F3 §11 读侧 manifest 完整性门已 land(918daf7f,3 轮跨厂商 SOUND)**:真实 ashare_hs300 读价【前】拿磁盘字节 re-verify
  注册的不可变 manifest per-file sha256→fail-closed(drift/corruption/误置 防御)。**跨厂商 3 轮收敛**:deep-opus 建→我同厂商
  pre-review 判 sound(**漏**)→codex round1 逮 4 洞(partial/empty-manifest fail-open·deletion→静默合成·overclaim·TOCTOU)→修闭 3/4→
  codex round2 逮 2(split-snapshot manifest race·research_quality_report 越界,**同厂商又漏**)→单快照修(manifest 解析一次,覆盖门+
  verify_manifest_obj sha256 跑同一 DatasetManifest·reads==1 断言+swap 测试·two-read 变异翻红)+ 诚实收窄→**codex round3 判 SOUND to land**。
  land gate 全绿(后端 6487·perf 72·前端 430·validate_dev·audit 基线不变)。设计+3 轮 arc 见
  [[f3-readside-manifest-reverify-crossvendor-20260715]]。**本 session 跨厂商 skeptic 3 轮守住诚实/完整性边界(同厂商 pre-review 两次全漏——再证不足)**。
  残余(如实登记非 fail-open):未签名 manifest 的 co-tamper·size+mtime 保持的原子 swap→需研究面签名 receipt(后续卡)。parked 分支 d2ec4238 已被 918daf7f 取代。
- **§16 Run 首屏门 Explore 侦察结论=infra-blocked(未做)**:Playwright driver + strict validator **已建已测**在
  perf_harness.py(`measure_run_first_screen`:2426·`_playwright_run_first_screen_probe`:2159-2365·validator
  `_RUN_REQUIRED_SERIES` 六键:88/2077),缺的只是 runtime——live 鉴权后端 + seeded run(equity/benchmark 有点+coach)+
  同源 served SPA + Chromium 二进制 + 三 env var。**<2s 门在 2 核 CI 本质 flaky·harness 刻意设计为诚实 KNOWN_RUN_GAP
  不算 fail**(ci.yml:1-4)。一次性 dev receipt 可行(~30min,无新码)但非可复现门+触碰全栈起服务(keystore)——低价值,不强做。
- **本地干净可收口切片已渐近清零(停止条件③临界)**:mechanical gap 全 land(on_event/bundle/validate_dev warn/worktree 盘点/
  GoalProofLedger LRU/IDE 沙箱 P0 止血)+ **F3 完整性门本 tick land(918daf7f)**。**剩全撞真实依赖/用户拍板**:①Run 首屏
  (infra:live 栈+Chromium+flaky·harness 刻意诚实 gap)②卡 8be0e547 dual-model 加固(**registered 工程取舍待用户权衡**:4 adapter+全桩改+
  6356 测试回归 vs 边际防御)③dual-model 真调用(待用户凭据)④Claude-Code agent epic fork-2(**用户命门·本 session 顶级优先**:
  floor OS/网络沙箱 scope + A股 live 治理矛盾 + MCP 依赖)⑤用户裁:worktree 删除/DVC ADR/Ed25519/质量门 scope/echarts lazy。
  真实数据/第二模型(dev codex 已用)/CI 皆已收口非 blocker。**→ F3 land 后仍报 blocker 清单等用户挑高价值方向(尤其 Claude-Code fork-2)。**
- **断点**:**当前战役=Claudian 式「每对话跨厂商切模型」(卡 db95c0c6,in_progress)**。蓝图 + 参考实现 + S6 记录见 findings。
  **✅ S1 目录 · ✅ S2 路由 · ✅ S3a-b gateway+pin 穿链 · ✅ S4 隔离(证成) · ✅ S6 订阅 in-app 登录 · ✅ S7 前端切换器**
  ——**API-key 每对话切模型端到端可用+有 UI;订阅账号可在应用内登录(设置页『登录订阅账号』→浏览器→轮询转绿,
  终端降级命令兜底)**。各切片经 skeptic 对抗验证(S1 假绿灯/S2 3MEDIUM/S3a CRITICAL 泄漏/S3b MEDIUM/S6 5 findings,全修+变异门)。
  S6 skeptic 判 **token 边界 sound**(后端全程不碰凭据),逮 §3 假绿灯(console 按量计费冒充订阅)已修+变异确认。
  **K3 约束+待拍板(用户已知悉·非阻塞)**:订阅模型跑不了带工具 agentic 对话(厂商 CLI 拒工具)——订阅只无工具场景
  (dual-model 审查/纯聊天);订阅进带工具对话=需 tool bridge(大·ToS 灰)或纯聊天模式(中),默认保持现状。
  **残余(非阻塞)**:S5 订阅接生产 gateway(K3 所限,S5-piece1 scaffold 已 land 无害)。
  **🚩 新大方向(待用户对齐/拍板 · 不建 until pinned)=OpenClaw 式 agent 层**:用户把 K3 掀翻成
  「OpenClaw 式 agent + workspace + skill + 无边画布 + 本地 claude code/codex 作模型供应(两层配置)」。
  反转:不塞工具给纯文本调用,而是**把 claude code/codex 当完整 agent 跑**(自带工具在 workspace 干活),
  我们编排+绑画布。已对齐复述 + 5 岔路(通用/量化专用·**安全命门**·画布=现有 GraphCanvas·本地优先·ToS CLI 驱动)
  见 [[openclaw-agent-epic-alignment-20260715]]。**等用户拍 forks 1-5(尤其 fork2 安全命门)再 duet 设计 + 薄纵切**。
  **✅ §11 PIT 读侧接线已 land 0c926235**(11a+11b+11c 一次落):真实 HS300 后复权 hfq(raw×adj_factor 四价列·
  volume raw·缺因子/非正/**非有限**/dup 全 fail-closed)·absent 逐字节合成兜底·registry 单一源=paths.DATA_ROOT
  (D-11-DATA-ROOT=b)·§16 隔离。deep-opus clean-context 实现 + 独立 skeptic(判 §16 sound,逮 F1 非有限 factor 漏拦已修+
  变异确认)。设计 [[pit-adjustment-readside-design-20260715]]。**follow-up 均已闭(非 §16)**:读时 manifest hash 复验(F3,land 918daf7f·3 轮跨厂商 SOUND)、
  producer hs300_pipeline factors_all_finite 建门(F1 建侧,land a2b6d534,镜 bars_all_finite)。
  **dual-model binding(卡 8be0e547)尝试→跨厂商 skeptic 判 NOT SOUND→已 revert 未 land**:deep-opus 实现 + 我同厂商
  复审判 sound,但 **codex 跨厂商 skeptic 逮 4×P1**(digest 哈希 messages 非实发 payload=label 越界·订阅模式 opt-in 后必崩·
  schema v3 向后不兼容·identity_basis 未下游传播)。**同厂商复审不足以守诚实边界——本次已证**(被审对象就是独立性机制、
  独立审查抓出自己越界)。收紧后诚实 scope + 逐条 findings 见 [[dual-model-binding-crossvendor-findings-20260715]];
  卡保持 pool/todo,重做须跨厂商复验。main 干净无脏码。
  **🚩🔨 当前大活=Claude-Code 式内嵌量化 agent(用户拍 A 已启动)**:**两层架构**——
  ①**服务层(订阅驱动·可插拔 agent 后端)**=`claude`(Claude Code v2.1.210:-p/--mcp-config/--permission-mode/
  --add-dir/stream-json)+`codex`+**`opencode`**(serve/run/mcp/acp;三个本机均已装、都 headless+MCP-capable)抽象成
  单一 AgentBackend 接口,各用自己订阅 auth(S6 登录地基)。②**QuantBT 层(量化专用)**=MCP server(数据/因子/回测/
  **画布**工具,**红线在 MCP 工具层结构性钉死**:动钱/真实 venue/A股实盘/testnet/mainnet 任何权限档都拒)+编排器
  (起后端·解析 stream·驱动 UI+GraphCanvas)+量化 skill+workspace+画布绑定。**造法**=融合 OpenClaw/Hermes(均 MIT,可融,
  落码前 pin commit 复审 license)编排范式,按本仓架构重实现+量化提示词。**K3 经 MCP 化解**。**已拍**:量化专用·权限分级·
  扩 GraphCanvas·A(编排真 agent 后端)·三后端(claude/codex/opencode)。
  **设计已定稿**(deep-opus a6668b18)见 [[claude-code-agent-foundation-design-20260715]]:AgentBackend 抽象(claude/codex/
  opencode·claude 薄片选它·flag 已核)+MCP server(唯一工具 canvas_read 只读读规范图源)+**红线 floor 三层**(L0 架构无钥进程排除
  order/venue 码·L1 危险工具不注册·L2 参数无条件拒无视 tier)+spawn 契约(strict-mcp/allowedTools 排 Bash/无 --dangerously/
  throwaway ws/洗 env)+编排 seam(新 session_orchestrator 映射现有 SSE 词汇·前端不改)+薄片(真订阅 claude→MCP→现有 GraphCanvas)
  +5 对抗测试(红线 bypass/tier 不放宽/L0 无钥/spawn 契约/无静默 fallback)+融合 OpenClaw/Hermes(MIT)。
  **跨厂商 codex 复审判 floor NOT SOUND**(bmywopd2m,3P0+4P1)——**未拿去请用户批**。逐条 + 收紧 v2 要求见
  [[agent-floor-crossvendor-review-20260715]]。核心洞:P0-1 spawn 契约漏 agent 自带 bash 道(user/project/managed 规则可放行→读
  凭据直连 venue,绕过 L0-L2)→**须 OS/网络沙箱**(非 CLI flag 够);P0-2 L0 无钥一旦 canvas_read import main.py 即塌(main 模块级
  import order broker/keystore)→须抽纯 projector 包;P0-3 env os.environ.copy 洗不净→白名单+OS 身份隔离;P1 canvas_read 非 owner-safe/
  L1 非封存/L2 关键词挡不住语义/claim 越界。**第三次跨厂商复审守住命门(同厂商设计+我复审都漏)**。
  **✅ 上述 blocking 已解（2026-07-16 用户 2 次 greenlight fork-2「可直接做」+ 放权 recalibrate）——此段以下为已 SUPERSEDED 历史**：
  - fork-2 floor 从 v1 3层(判 NOT SOUND) → **v2 2层结构性 + L-C/L-D**（放权「minimal not a wall」删逐参数拒门）。M1-M4a **已按 v2 建并 land**，**每 milestone 走跨厂商 codex floor 复审**（M1 FLOOR-HOLD·M3 3轮 R3 FLOOR-HOLD 逮真 prompt-injection 红线破口·M4a 3轮 R3 SOUND）——即 impl-plan §6.4「每落码前跨厂商复审」已在执行。MCP 依赖=官方低层 SDK 钉 mcp==1.28.1；传输=stdio 独立进程；薄片=canvas_read 只读（写 canvas_create_node 延 M5）。均已定/已建。
  - **残余真待拍板（仍开·非 blocking loop）**：①**A股 live 治理矛盾**（`RULES.project.md:11「A股永不实盘」`绝对红线 vs `GOAL.md:1787「未来治理后可 live」`留口·codex P1-7·我不碰 GOAL/RULES）——须用户澄清「永不」还是「治理后可」，决定 floor claim 边界；②**Axis F canvas_create_node 字段门槛**（QRORecord 强制 assumptions/known_limits/failure_modes/validation_plan：agent 全供[GOAL 对齐·门槛高] vs 工具合成占位[门槛低]）——M5 前请用户拍，摆代价不替拍；③**claim 诚实边界**（放权方案A：结构性无钥只证「经 QuantBT MCP dispatch 零执行」，不证「任意 shell 够不到用户自己宿主机凭据」——用户自带 bash+自有 venue 凭据=用户 ambient 风险，须写死当「放权显式代价」）。三项登记等用户挑，不停 loop。

## 状态表（确定的才标 ✅,证据必挂）
| 子系统/能力 | 状态 | 证据 |
|---|---|---|
| §16 性能门·HS300 十年读<3s | ✅ | perf_harness measured=True/0.0185s;链=真实 Tushare 65.4万行+签名 receipt/universe+跨厂商 approve_pin+pin(perf_harness.py `quantbt-hs300-operator-root-v1`);证据包 research/findings/dreaminate/hs300-chain-evidence-20260714.md |
| §16 性能门·标准回测<60s / 资产库<1s / RAG 首批<3s | ✅ | perf_harness 三基线 measured PASS(benchmark 套件 72 passed 内) |
| §16 性能门·Run 首屏<2s | ⬜ | 诚实 KNOWN_RUN_GAP(需 Playwright 实测,harness 第二 gap;另卡) |
| §11 数据层·基准面(readbench cohort) | ✅ | DatasetVersion hs300_daily_10y_readbench_cohort@…856b67b1(metadata 四键防误用);preflight 12/12 真数据 PASS |
| §11 数据层·研究面(union 含退市) | ✅ | hs300_research_universe_10y@…332bebc0(1.38M bars/622 只/19,200 停复牌);12 质量门真数据 PASS(含探针 #6 bar日因子完备/#7 停牌伪 bar含退化窗);质量门经 codex 四轮对抗收敛到 factor-价格补偿不变量,scope 裁定见 frontier 待复核 |
| §11 数据接入·Tushare 管线 | ✅ | scripts/hs300_onboard.py 六子命令(store-token/keygen/pull/preflight/build/build-research/bench);限流 180/分+退避+幂等;docs/hs300-quickstart.md;data_onboarding 测试 41 passed(含 codex 全部反例回归) |
| §11 PIT/复权读侧接线 | ✅ | panel_source.py 接真实 HS300 后复权 hfq(market `ashare_hs300`:registry present→raw×adj_factor 四价列同乘·volume raw·缺因子/非正/**非有限**(NaN/±inf,F1)/dup 全 fail-closed raise;absent→逐字节合成兜底,零行为变更)。registry 路径单一源=paths.DATA_ROOT(=main.py:734,D-11-DATA-ROOT=b 无双源漂移)。§16 隔离(≠perf harness·perf_baseline_claim=False·拒 forbidden cohort)。12 对抗测试+变异门(×→÷、is_finite 均 red-then-revert)+byte-identity 双证;后端 6474 passed;deep-opus 实现+独立 skeptic 判 §16 sound;land 0c926235。**F1 双拦已闭**:读侧(0c926235)+ 建侧 research_quality_report `factors_all_finite`(a2b6d534,镜 bars_all_finite;NaN/±inf factor→quality_verdict≠pass·对抗测试+变异门·6475 passed)。**F3 读时 manifest 完整性门已闭(918daf7f·3 轮跨厂商 SOUND)**:读价前逐字节 re-verify 注册 manifest per-file sha256→fail-closed(drift/corruption 防御)。**残余(如实登记非 fail-open)**:未签名 manifest co-tamper·size+mtime 保持的原子 swap→需研究面签名 receipt(后续卡) |
| §4 跨厂商切模型·S1 模型目录 | ✅ | app/llm/model_catalog.py 唯一 LLM 模型清单源(api-key live 拉/models 加固 stream 上限+禁 redirect+fail-closed、非聊天 selectable=false、订阅 curated supports_tools=false、TTL+single-flight+凭据零触碰)+GET /api/llm/models(订阅探测 60s TTL 缓存);对抗测试 29(deep-opus skeptic 逮 1 假绿灯+6 项全修+回归);后端 6409 passed;land e89964a8+CI success。卡 db95c0c6 |
| §4 跨厂商切模型·S2 hard-pin routing | ✅ | routing.py pin_provider/pin_model 硬约束+resolve 硬 pin 过滤(仅 !independence_required 生效→dual 门物理免疫、pool 不变保 no-mix、pin 无候选→PinnedModelUnavailable 绝不跨厂商 fallback、pin_model tier 优先用登记档);对抗测试 14(skeptic 逮 3 MEDIUM:degraded 判反/fallback 锁死实靠断路器/命门测试弱,全修+补测);gateway 76+全量 6423 passed;land 6a8990e9 |
| §4 跨厂商切模型·S3a gateway pin 注入 | ✅ | LLMGateway(default_pin) 在 complete() 盖章成 hard pin(仅非独立且非 verifier role→dual 门物理免疫叠双层);盖章后 effective_capability 贯穿 _invoke_with_fallback→S2 跨厂商锁死端到端成立(K1:真实主链走 GatewayLLMAdapter);对抗测试 6(skeptic 逮 **CRITICAL 跨厂商泄漏**——盖章在 fallback 蒸发,已修+变异门钉死;+MEDIUM-2 spy 门+LOW-4 role 纵深);全量 6429 passed;land dc940949 |
| §4 跨厂商切模型·S3b 持久化+pin 穿链+端点 | ✅ **端到端可用** | ChatService.update/get_llm_selection(owner-scoped 原子,S3b-1) + `_current_agent_gateway(model_pin)`/`_dispatch(model_pin)`/两端点经 `_thread_model_pin` 服务端读传(S3b-2,gateway.py 零改动) + GET/PATCH `/api/agent/chat/{tid}/llm-selection`(校验 gateway 可路由+owner-scoped,S3b-3);对抗测试 6+8+集成 1(skeptic 判运行期无安全缺陷,逮 MEDIUM 接线零覆盖→补集成测试+**临时断 model_pin 传参确认变红**);全量 6444 passed;land ae2e61b1。用户 PATCH 手选→驱动那条对话生产 agent。**订阅 pin 待 S5**(gateway 未接订阅) |
| §4 跨厂商切模型·S7 前端切换器 | ✅ **有 UI 可用** | ModelSwitcher.tsx 挂 Mode2ChatPage active-thread header(原生 select+optgroup+Auto 顶项);GET /api/llm/models(filter authed&&selectable)+GET /llm-selection 回显,选中 PATCH(下条消息即生效·对话中途切);仅 API-key 可路由厂商可切、凭据不经前端、stale pin 兜底显示;前端测试 5(分组/未 auth 不显/非聊天不可选/回显/PATCH body/auto),前端全 428 passed+build 绿;land 803d0e27。**北极星:普通用户可视化切模型** |
| §6 数学链门(§6 gate) | ✅ | section6_mathchain_gate.py 委托 spine_gate 8 deny 子句;gate_registry 7 门(2026-06-29 land ad7b9d4e,原文 git 历史) |
| §5 Research Asset RAG | ✅ | /api/agent/chat+workbench+legacy Mode2 全接;test_agent_runtime_research_graph 等系列在当日后端全量 6313 passed/0 failed(2026-07-14 实跑)内全绿;建设明细见 git 历史 |
| §6 Document Intelligence | ✅ | text/MD/PDF(PyMuPDF+OCR fallback)/HTML snapshot parser+batch+upload+目录同步;test_document_intelligence_parser_rag 在当日全量 6313 passed(2026-07-14 实跑)内全绿;边界:非联网 crawler/非表格理解 |
| §1/§7 Research Graph+QRO | ✅ | projection/canvas 写回/edge+tombstone+patch/参数值记录全链;test_research_graph_persistence 等系列在当日全量 6313 passed(2026-07-14 实跑)内全绿;边界:非完整 graph database |
| §8 Governed Compiler | 🟡 | compile_qro+IR/pass+artifact manifest 审计层已建;完整 codegen 未做 |
| §15 模型治理 | ✅ | 训练→registry→promotion(pending/rejected/approved QRO)→sandboxed inspection→serving seam+SignalContract(test_model_governance 当时 31 passed 口径,原文 git 历史) |
| §12 执行边界 | ✅ | intent→promotion→venue events→reconciliation→guarded submission/materialization 全 refs-only,A股 live 恒拒;test_execution_boundary_contract 系列在当日全量 6313 passed(2026-07-14 实跑)内全绿;边界:无真实 venue 连通 |
| IDE 沙箱逃逸止血 | ✅ | sandbox.py 补封 posix_spawn 族 + AST 预检拒 ctypes/cffi 直接 import(位置+关键字 __import__)——盘点捞回从未 land 的 P0 加固;defense-in-depth 非 hardened(真隔离=OS 级 P0 卡 5bfb5202);6 对抗测试+6363 passed(commit d7380484+074dfe56);codex 复核逮 kw 形式漏网已补 |
| §4 Settings/LLM Gateway | 🟡 | provider registry+keystore+routing+UI 第一版已建;OAuth/device-code、全 connector 未做;gateway secret 泄漏向量已闭(C-S7 Gap1,2026-06-29) |
| §13/§17 RDP | 🟡 | manifest/store/materialize/publish 已建;本切片链产物未组 RDP(residual) |
| GoalProofLedger snapshot cache | ✅ LRU | 无界 dict→OrderedDict 有界(maxsize 256,读命中 move_to_end/写后逐最旧);命中正确性仍由 token+WAL 文件状态绑定独立门控,淘汰只重算不 stale(WAL 边界一字未动);test_goal_proof_ledger 42 passed(2 新 LRU 对抗)+codex APPROVE(commit cbdc9617) |
| dual-model 独立审查(流程级) | ✅ | builder=claude(anthropic)/verifier=gpt-5.6-sol(openai) 跨厂商;HS300 链三轮 verdict 留档证据包 |
| §7/§8 dual-model 应用内接线(脚本化端到端) | ✅ 真跨厂商跑通 | scripts/dual_model_review.py 两模式:api_key(secrets 窄读→内存 keystore→gateway) + **--subscription**(经厂商官方 CLI,无 key/无中继);test_dual_model_review_script 36 passed(桩注入,零网络)。**真实跨厂商调用已收口(2026-07-15)**:builder=anthropic claude-sonnet-4-5 / verifier=openai gpt-5.6-sol 真跑 independent=True、auth_mode=subscription_cli、claim_scope=cross_vendor_via_official_cli,verifier 独立重算 Pearson IC=0.996834 逮 builder「优秀」夸大、verdict=incorrect,evidence HMAC 密封;绕过此前本机中继 key 双 401 blocker。机制级残余(binding 绑 adapter 实发 request_payload_digest/身份可验证)=卡 8be0e547(蓝图已落 research/findings) |
| 订阅账号 LLM auth + onboarding(陌生用户从零) | ✅ + **in-app 登录(S6)** | adapter(ClaudeSubscriptionLLM/CodexSubscriptionLLM)+auth 检测(`subscription_auth_status`/`provider_auth_report`/`auth_status_all`,不读 token);CLI 三子命令(status/login/verify)+quickstart。**S6 in-app 登录中继(2026-07-15)**:`begin_subscription_login`+`_spawn_detached_login`(stdin/stdout/stderr=DEVNULL·不 wait·固定 argv,后端不碰 token)+端点 GET `/api/llm/providers/auth`·POST `/api/llm/subscription/login/{provider}`(机器级 admin gated)+前端订阅登录面板(状态卡+一键登录+终端降级)。**K4**:全仓弃 `setup-token`(打 token 到 stdout)→`claude auth login --claudeai`(存 keychain)。**§3 假绿灯修复**:console(按量计费)不再冒充「订阅·无按量费」(按 authMethod=claude.ai/firstParty 正信号闸)。test_subscription_cli_llm 21 passed+test_llm_custom_and_api 端点门+前端面板测试;skeptic 判 token 边界 sound、5 findings 全修+变异门。诚实边界:真浏览器登录端到端要用户本人按(我只验状态检测);订阅自动化 ToS 用户自担;token 存 CLI keychain、本仓不读/不复制/不记录 |
| CI(GitHub Actions) | ✅ | .github/workflows/ci.yml 双 job;run 29377617245 gh 实查 success:后端 6315 passed/0 failed(17:18)+前端 423+build;七轮迭代账目在 log/证据包 |
| FastAPI on_event→lifespan 迁移 | ✅ | main.py _app_lifespan asynccontextmanager(try/finally 无条件 shutdown 等价旧 _DefaultLifespan.__aexit__);test_app_lifespan 5 passed;codex 修复轮 APPROVE(commit f8d1f1cd+d940aed3) |
| 前端 bundle 拆分 | ✅ | vite manualChunks:单 2,557.79 kB JS→9 可缓存 chunk(echarts 1.38MB/index 813/react-vendor 142/…);build 绿+423 前端测试 passed(commit 593ffa02)。边界:首屏字节未减(echarts 随 §M15 冻结页 eager),lazy-load=用户拍板 |

## 下一步
- 切片② 真跨厂商已收口(订阅路径)、on_event 已迁移、CI/bundle 已 land → 转**用户可感知面**:
  Run 首屏门(harness 第二 gap,需 Playwright 实测)→ pool 三张 eval 卡 → 卡 8be0e547 机制层
  加固(binding 绑 adapter 实发,蓝图已落)→ 90+ worktree 盘点(只列清单等拍板)。
- 待拍板(非阻塞,已登记):用户贴的「金融数学主干架构设计」文档 A/B/C(默认 C=继续 loop);
  订阅账号自动化 ToS 归用户自担(已在 docs/state 诚实标注)。
- 详单与残余见 frontier.md;战略提示(转用户可感知面)已记。
