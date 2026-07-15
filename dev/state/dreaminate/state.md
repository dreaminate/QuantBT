# STATE · dreaminate 现状（对照 GOAL 的 gap · 重生型）

> 现状 gap,对照 `../GOAL.md` 终态量。**🟡 未验证 ≠ ✅ 已验证** —— 只有挂得出可指认证据(file:line / 测试名 passed / 带口径的指标)的才标 ✅,空泛即假绿灯。
> 重生型:land 后整篇重写为当前快照;会话叙事进 `log/`,续接现场进 `frontier.md`,都别堆在这。
> 本版 2026-07-14 整篇重写(蒸馏此前 2026-06 全部追加块——原文在 git 历史 `git log dev/state/dreaminate/state.md`)。

## 进行中
- 卡 9c5e6975 已 done(2026-07-15):切片② dual-model **真跨厂商调用收口**——订阅账号 auth+
  onboarding 全做(陌生用户从零)、dual_model_review 接订阅、真跑 independent=True 逮 builder
  夸大。切片③ CI ✅、on_event 迁移 ✅、bundle 拆分 ✅ 均已 land。/loop 15m 自主循环运行中;
  下一步转用户可感知面(队列见 frontier)。

### 顶部刷新块（本轮值 · 每轮覆写）
- **六字段**:1 Local checkout=slice/model-switch-crossvendor @ **918daf7f**(= origin/main,干净;**F3 §11 读侧 manifest 完整性门产品码已 land 于此**);
  2 Remote=**origin/main 同 918daf7f**(F3 产品码 918daf7f + 上游 dev-docs;本 tick 之后另落 dev-docs commit);
  3 Local tests=**后端全量 6487 passed/13 skipped/0 failed**(真汇总行,508s 实跑)+ perf harness 72 passed + 前端 40 files/430 passed + build ✓;
  4 CI=**Unqueried**(F3 918daf7f 刚 push,未 gh 实查;下 tick 查);5 Production=Unqueried;6 User acceptance=**Unverified**。
  本 session 累计 land 进 main:S6 订阅 in-app 登录(656c85eb)·§11 PIT(0c926235)·F1 建侧(a2b6d534)·**F3 读侧完整性门(918daf7f,3 轮跨厂商 SOUND)**。
- **audit 基线四项**(不变):61 files / 20,339 lines / 26,209,663 bytes / sha `1c1788b0bbe2`。(改动全在 app/scripts/docs/dev,基线按构造不变。)
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
  变异确认)。设计 [[pit-adjustment-readside-design-20260715]]。**follow-up(非 §16,登记)**:读时 manifest hash 复验(F3)、
  producer hs300_pipeline factors_all_finite 建门(defense-in-depth,建侧现只 <=0 无 finite 检查)。
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
  **blocking [需拍板]**（alignment doc line47:未批 fork2 前不落任何执行码;且 floor NOT SOUND 未批）:
  ①**fork2 floor 须 v2 硬化**(OS/网络沙箱+纯 projector+env 白名单+owner-cap+封存注册+闭合 schema)再跨厂商复审再请批——
  **P0-1 把范围抬到 OS 级沙箱基建=更大工程,可能本身待拍板(建多少沙箱/薄片是否等沙箱就绪)**;②**A股 live 矛盾请用户拍**:
  `RULES.project.md:11「A股永不实盘」` vs `GOAL.md:1787「未来治理后可 live」`(codex P1-7 发现,我不碰 GOAL/RULES);
  ③新 MCP 依赖(官方 mcp SDK 推 vs FastMCP vs 自建 stdio)+传输(stdio 独立进程 推);④薄片面(只读 canvas_read 推)。
  下一步:请用户拍——A股矛盾澄清 + floor v2 范围(OS 沙箱建多深/薄片等不等沙箱)+ MCP 依赖;拍了再走 v2 硬化设计(跨厂商)→薄片。

## 状态表（确定的才标 ✅,证据必挂）
| 子系统/能力 | 状态 | 证据 |
|---|---|---|
| §16 性能门·HS300 十年读<3s | ✅ | perf_harness measured=True/0.0185s;链=真实 Tushare 65.4万行+签名 receipt/universe+跨厂商 approve_pin+pin(perf_harness.py `quantbt-hs300-operator-root-v1`);证据包 research/findings/dreaminate/hs300-chain-evidence-20260714.md |
| §16 性能门·标准回测<60s / 资产库<1s / RAG 首批<3s | ✅ | perf_harness 三基线 measured PASS(benchmark 套件 72 passed 内) |
| §16 性能门·Run 首屏<2s | ⬜ | 诚实 KNOWN_RUN_GAP(需 Playwright 实测,harness 第二 gap;另卡) |
| §11 数据层·基准面(readbench cohort) | ✅ | DatasetVersion hs300_daily_10y_readbench_cohort@…856b67b1(metadata 四键防误用);preflight 12/12 真数据 PASS |
| §11 数据层·研究面(union 含退市) | ✅ | hs300_research_universe_10y@…332bebc0(1.38M bars/622 只/19,200 停复牌);12 质量门真数据 PASS(含探针 #6 bar日因子完备/#7 停牌伪 bar含退化窗);质量门经 codex 四轮对抗收敛到 factor-价格补偿不变量,scope 裁定见 frontier 待复核 |
| §11 数据接入·Tushare 管线 | ✅ | scripts/hs300_onboard.py 六子命令(store-token/keygen/pull/preflight/build/build-research/bench);限流 180/分+退避+幂等;docs/hs300-quickstart.md;data_onboarding 测试 41 passed(含 codex 全部反例回归) |
| §11 PIT/复权读侧接线 | ✅ | panel_source.py 接真实 HS300 后复权 hfq(market `ashare_hs300`:registry present→raw×adj_factor 四价列同乘·volume raw·缺因子/非正/**非有限**(NaN/±inf,F1)/dup 全 fail-closed raise;absent→逐字节合成兜底,零行为变更)。registry 路径单一源=paths.DATA_ROOT(=main.py:734,D-11-DATA-ROOT=b 无双源漂移)。§16 隔离(≠perf harness·perf_baseline_claim=False·拒 forbidden cohort)。12 对抗测试+变异门(×→÷、is_finite 均 red-then-revert)+byte-identity 双证;后端 6474 passed;deep-opus 实现+独立 skeptic 判 §16 sound;land 0c926235。**F1 双拦已闭**:读侧(0c926235)+ 建侧 research_quality_report `factors_all_finite`(a2b6d534,镜 bars_all_finite;NaN/±inf factor→quality_verdict≠pass·对抗测试+变异门·6475 passed)。**残余(follow-up,非 §16)**:读时 manifest hash 复验(F3) |
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
