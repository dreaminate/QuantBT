# STATE · dreaminate 现状（对照 GOAL 的 gap · 重生型）

> 现状 gap,对照 `../GOAL.md` 终态量。**🟡 未验证 ≠ ✅ 已验证** —— 只有挂得出可指认证据(file:line / 测试名 passed / 带口径的指标)的才标 ✅,空泛即假绿灯。
> 重生型:land 后整篇重写为当前快照;会话叙事进 `log/`,续接现场进 `frontier.md`,都别堆在这。
> 本版 2026-07-14 整篇重写(蒸馏此前 2026-06 全部追加块——原文在 git 历史 `git log dev/state/dreaminate/state.md`)。

## 进行中
- **🧭 module-convergence 扫描结论(2026-07-15 · 用户令「收敛具体模块直到 GOAL 全收口」后 Plan 独立扫)**:剩 3 个 🟡 模块**全撞用户门/外部依赖**,无 decision-free 干净本地切片。逐一(据 file:line 核实):
  - **§8 Governed Compiler**:治理主干已建全(governed_compiler.py 5 命门);唯一「未做」=neural-graph codegen(training/codegen.py:239 仅支持线性链子集·分支/机制嵌套留后续)=**方法学重**(branch/merge 语义=设计空间无单一正解),且属 build 台 feature-completeness 非 correctness 治理。→**方向已拍板**(2026-07-16 用户 b3=[[D-CODEGEN-BRANCH-SESSION]]:codegen 构建走 git 分支/合并·「存为 session」与 session_orchestrator 统一)，具体接线未实装·登记 pending 切片。
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
- **✅ M6b「agent epic 收官·SSE liveness 守卫 + opt-in 真 claude 冒烟」四门全绿·已 land main（产品 a8549fa8·2026-07-16）**：本轮 loop 唤醒本地曾落后 origin **86 commit→`git merge --ff-only` 到 7aa19eed**(recovery·HEAD 为 origin 祖先双证)起，接 M6b 收官 agent epic。**改动(扩展不替换)**：A1 idle+total timeout(reader 线程+bounded queue 抗慢消费者背压·满队列 EOF sentinel 阻塞送达)·A2 orchestrator 显式 close backend.run 确定性 cancel(eager-run 抛错捕获·close 异常不泄 transport)·A2.5 EOF-but-alive bounded `proc.wait(eof_grace 5s)`·A2.6 EOF 无 terminal→honest BackendError(非假 stream_ended)·A3 `_agent_workspace_for_owner` --add-dir owner 路径穿越守(allowlist+resolved containment+symlink 拒)·B4 opt-in 真冒烟经 SSE orchestrator 断言 tool_start/tool_end/done+init.mcp_servers(real-claude oracle sample 验 shape)+store OFFLINE ground-truth·CI 诚实 KNOWN_RUN_GAP skip·`SessionStarted.mcp_servers` additive。
  - **四门**：①最低验证——后端全量 **6931 passed/14 skipped/0 failed**(真汇总行·隔离 DATA_ROOT·带 timeout 非叠跑)+前端 430+build✓+perf 72+compileall✓+git diff--check clean+GOAL 零 diff；②validate_dev PASS；③评审=**跨厂商 codex floor 5 轮**(approver≠creator·GPT-5.6-sol 逮 **3 真 correctness/honesty 洞**〔EOF sentinel 满队列丢弃·A2 双 regression〔eager-run 抛错逃逸+close 异常泄漏〕·EOF-no-terminal 误报 stream_ended 假绿〕+多处 honesty 过强描述→逐条修+RED-then-revert 钉→R5 FLOOR-HOLD·autoplan N/A=纯后端 infra 无产品面·同 M6a 走 floor)；④data/audit——**原 61 文件字节全等(`1c1788b0bbe2`·完整性未破)**，新增 gitignored 运行时 DB `goal_proof_ledger.sqlite`(codex 复审探针 `import app.main` 用非隔离 repo DATA_ROOT 触发·10:27·仅加性无共享历史改写)。**六字段**：1 Local=已 land a8549fa8；2 Remote=待 push(dd5c1800 recovery+a8549fa8 产品+本 dev 提)；3 Tests=后端 6931/0+前端 430；4 CI=Unqueried；5 Prod=Unqueried；6 User=Unverified。
  - **诚实 residual（登记·非阻塞·pre-existing 非 M6b 引入）**：HTTP 断连若 ASGI server 不 close 生成器→显式 close 不触发、idle/total 也不推进(消费者停拉→deadline 检查不执行)→child 若续写被 stdout backpressure 阻塞、否则不受节流(silent/CPU-loop child 无 CPU/进程上界)·靠 GC 回收·L-C/L-D 仍守·非安全边界。→**route-level `request.is_disconnected` 硬化=follow-up**。
- **✅ agent M6a「红线总断言 + canvas_create_node」已 land main（产品 6d0683f0·收尾 7aa19eed）**：四门全绿·跨厂商 codex floor 2 轮(R1 逮 3 test-rigor 洞→R2 HOLD)·detail 归 log/git。**M6b 收官后 agent epic(M1→M6b)整条闭环——NEXT=金融数学 kernel P0(北极星①「数学贯穿」最大缺口)**。
- **本 session 已 land main（前序·完整 narrative 归 log/git 历史）**：§17 RDP coercion(b0af451d)·Trust coercion(4a9c1a07)·§11 PIT 读侧(0c926235)·F1 建侧 finite(a2b6d534)·F3 读侧 manifest(918daf7f)·S6 订阅 in-app 登录·内嵌 agent M1(39c29092)/M2(7e1dd20f)/M3(a2c69ba1·prompt-injection)/M4a(ec506137)/M5a/M5b(1a1c6f0d)/M4b(bd2ac7ee)/M6a(6d0683f0)/**M6b(a8549fa8·本轮)**——每 milestone 跨厂商 codex floor 复审（防自欺价值·M3/M4b/M6a/M6b 各逮真洞）。
- **仍开·待拍板/外部依赖（非阻塞 loop）**：①**A股 live 治理矛盾**（RULES.project.md:11「永不实盘」vs GOAL.md「治理后可」·须用户澄清 claim 边界·我不碰 GOAL/RULES）②**claim 诚实边界**（放权·ambient 显式代价）③**卡 8be0e547 dual-model binding 加固**（跨厂商 NOT SOUND·用户已授权重启）④dual-model 真调用（待用户凭据）⑤§16 Run 首屏门（KNOWN_RUN_GAP 非 fail）⑥§17 RDP advisory-first（真证据待凭据）⑦b3=[[D-CODEGEN-BRANCH-SESSION]]（方向已拍·未实装）⑧**M6b route-level HTTP 断连硬化**（`request.is_disconnected` polling·非阻塞 follow-up）⑨**工作区 2 fib `.ipynb` 无记录删除在 `stash@{0}`**（待用户复核删/留）⑩**data/audit spurious `goal_proof_ledger.sqlite`**（codex 探针 import app.main 污染·gitignored·待用户定夺删/留；此后 codex 复审跑 import app.main 须带隔离 BACKTEST_DATA_ROOT）。
- **audit 基线**（本轮值·来源已查明）：**canonical 稳定基线（排除可变运行时 DB `goal_proof_ledger/`）= 61 files / 20,339 lines / 26,209,663 bytes / `1c1788b0bbe2` 全程字节不变（完整性未破）**；含 goal_proof_ledger 运行时产物的全目录 manifest=63 / 20,522 / 26,332,544 / `4403e432`（可变·不作稳定基线）。下轮 fixed-opening 用「排除 goal_proof_ledger」配方核 61 完整性。

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
| 前端 bundle 拆分 | ✅ | vite manualChunks:单 2,557.79 kB JS→9 可缓存 chunk(echarts 1.38MB/index 813/react-vendor 142/…);build 绿+423 前端测试 passed(commit 593ffa02)。边界:首屏字节未减(echarts 随 §M15 冻结页 eager)。**lazy-load 已定方向**(2026-07-16 b5①=[[D-B5-AUTO-RULINGS]]:echarts 走动态 import 懒加载·待实装接首屏切片) |

## 下一步
- 切片② 真跨厂商已收口(订阅路径)、on_event 已迁移、CI/bundle 已 land → 转**用户可感知面**:
  Run 首屏门(harness 第二 gap,需 Playwright 实测)→ pool 三张 eval 卡 → 卡 8be0e547 机制层
  加固(binding 绑 adapter 实发,蓝图已落)→ 90+ worktree 盘点(只列清单等拍板)。
- 待拍板(非阻塞,已登记):用户贴的「金融数学主干架构设计」文档 A/B/C(默认 C=继续 loop);
  订阅账号自动化 ToS 归用户自担(已在 docs/state 诚实标注)。
- 详单与残余见 frontier.md;战略提示(转用户可感知面)已记。
