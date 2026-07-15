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
- **六字段**:1 Local checkout=slice/model-switch-crossvendor(本地领先 origin 2:S5-piece1 credential_pool/factory
  认 subscription_cli scaffold + dev 记账,未 push);2 Remote=origin/main @ ae2e61b1..4a5f882b(S1-S3b 全 land);
  3 Local tests=后端全量 **6444 passed/13 skipped/0 failed**(4a5f882b,真汇总行);S5-piece1 隔离 4 passed;
  4 CI=**✅ 4a5f882b run 29413489103 success(S1-S3b 完整,后端+前端+build)** + 88c30703 success——flaky 训练
  超时彻底恢复,整个 model-switch 后端 CI 验证绿;5 Production=Unqueried;6 User acceptance=Unverified。
- **audit 基线四项**(不变):61 files / 20,339 lines / 26,209,663 bytes / sha `1c1788b0bbe2`。
  (本特性改动全在 app/backend/dev,不跑数据管线,基线按构造不变。)
- **断点**:**当前战役=Claudian 式「每对话跨厂商切模型」(卡 db95c0c6,in_progress)**。蓝图 + 参考实现见 findings。
  **✅ S1 目录 · ✅ S2 hard-pin routing · ✅ S3a gateway pin 注入 · ✅ S3b(持久化+pin 穿生产链+selection API)**
  ——**后端跨厂商切模型端到端功能可用 + CI 绿**(用户 PATCH `/api/agent/chat/{tid}/llm-selection` 手选→驱动那条对话生产 agent,
  对话中途切下条消息即生效)。各切片经 skeptic 对抗验证(S1 假绿灯/S2 3MEDIUM/S3a CRITICAL 泄漏/S3b MEDIUM,全修+变异门)。
  **S4=已证成**(dual 门 3 层+skeptic 亲验+强测试+conversation 层集成测试组合覆盖,无新代码)。
  **K3 约束确认+待拍板(用户已知悉·非阻塞)**:订阅模型跑不了带工具 agentic 对话(厂商 CLI 拒工具,生产 role 传 tool schema)——
  订阅只能无工具场景(dual-model 审查已可用/纯聊天);API-key 线全场景可切(已可用)。订阅进带工具对话=需受治理 tool bridge(大·ToS 灰)
  或纯聊天模式(中),默认保持现状。**S5 订阅接生产 gateway 暂缓**(避免建误导性成品);S5-piece1 scaffold 本地留存(无害·任一方案都要)。
  **下一步 S7 前端切换器**:让 API-key 每对话切+中途切对普通用户可视化可用(北极星:能用)。前端 vite/react,chat 页
  Mode2ChatPage.tsx/AgentWorkbenchPage.tsx。S6 内嵌登录中继(订阅 auth 用,优先级降)。ultracode:每片落码后对抗验证。

## 状态表（确定的才标 ✅,证据必挂）
| 子系统/能力 | 状态 | 证据 |
|---|---|---|
| §16 性能门·HS300 十年读<3s | ✅ | perf_harness measured=True/0.0185s;链=真实 Tushare 65.4万行+签名 receipt/universe+跨厂商 approve_pin+pin(perf_harness.py `quantbt-hs300-operator-root-v1`);证据包 research/findings/dreaminate/hs300-chain-evidence-20260714.md |
| §16 性能门·标准回测<60s / 资产库<1s / RAG 首批<3s | ✅ | perf_harness 三基线 measured PASS(benchmark 套件 72 passed 内) |
| §16 性能门·Run 首屏<2s | ⬜ | 诚实 KNOWN_RUN_GAP(需 Playwright 实测,harness 第二 gap;另卡) |
| §11 数据层·基准面(readbench cohort) | ✅ | DatasetVersion hs300_daily_10y_readbench_cohort@…856b67b1(metadata 四键防误用);preflight 12/12 真数据 PASS |
| §11 数据层·研究面(union 含退市) | ✅ | hs300_research_universe_10y@…332bebc0(1.38M bars/622 只/19,200 停复牌);12 质量门真数据 PASS(含探针 #6 bar日因子完备/#7 停牌伪 bar含退化窗);质量门经 codex 四轮对抗收敛到 factor-价格补偿不变量,scope 裁定见 frontier 待复核 |
| §11 数据接入·Tushare 管线 | ✅ | scripts/hs300_onboard.py 六子命令(store-token/keygen/pull/preflight/build/build-research/bench);限流 180/分+退避+幂等;docs/hs300-quickstart.md;data_onboarding 测试 41 passed(含 codex 全部反例回归) |
| §11 PIT/复权读侧接线 | 🟡 | raw+adj_factor 分离已交付;panel_source 唯一复权落点未接(后续卡) |
| §4 跨厂商切模型·S1 模型目录 | ✅ | app/llm/model_catalog.py 唯一 LLM 模型清单源(api-key live 拉/models 加固 stream 上限+禁 redirect+fail-closed、非聊天 selectable=false、订阅 curated supports_tools=false、TTL+single-flight+凭据零触碰)+GET /api/llm/models(订阅探测 60s TTL 缓存);对抗测试 29(deep-opus skeptic 逮 1 假绿灯+6 项全修+回归);后端 6409 passed;land e89964a8+CI success。卡 db95c0c6 |
| §4 跨厂商切模型·S2 hard-pin routing | ✅ | routing.py pin_provider/pin_model 硬约束+resolve 硬 pin 过滤(仅 !independence_required 生效→dual 门物理免疫、pool 不变保 no-mix、pin 无候选→PinnedModelUnavailable 绝不跨厂商 fallback、pin_model tier 优先用登记档);对抗测试 14(skeptic 逮 3 MEDIUM:degraded 判反/fallback 锁死实靠断路器/命门测试弱,全修+补测);gateway 76+全量 6423 passed;land 6a8990e9 |
| §4 跨厂商切模型·S3a gateway pin 注入 | ✅ | LLMGateway(default_pin) 在 complete() 盖章成 hard pin(仅非独立且非 verifier role→dual 门物理免疫叠双层);盖章后 effective_capability 贯穿 _invoke_with_fallback→S2 跨厂商锁死端到端成立(K1:真实主链走 GatewayLLMAdapter);对抗测试 6(skeptic 逮 **CRITICAL 跨厂商泄漏**——盖章在 fallback 蒸发,已修+变异门钉死;+MEDIUM-2 spy 门+LOW-4 role 纵深);全量 6429 passed;land dc940949 |
| §4 跨厂商切模型·S3b 持久化+pin 穿链+端点 | ✅ **端到端可用** | ChatService.update/get_llm_selection(owner-scoped 原子,S3b-1) + `_current_agent_gateway(model_pin)`/`_dispatch(model_pin)`/两端点经 `_thread_model_pin` 服务端读传(S3b-2,gateway.py 零改动) + GET/PATCH `/api/agent/chat/{tid}/llm-selection`(校验 gateway 可路由+owner-scoped,S3b-3);对抗测试 6+8+集成 1(skeptic 判运行期无安全缺陷,逮 MEDIUM 接线零覆盖→补集成测试+**临时断 model_pin 传参确认变红**);全量 6444 passed;land ae2e61b1。用户 PATCH 手选→驱动那条对话生产 agent。**订阅 pin 待 S5**(gateway 未接订阅) |
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
| 订阅账号 LLM auth + onboarding(陌生用户从零) | ✅ | app/agent/subscription_cli_llm.py:ClaudeSubscriptionLLM(anthropic,`claude -p`)+CodexSubscriptionLLM(openai,`codex exec -o`) adapter+auth 检测(`subscription_auth_status`/`provider_auth_report`/`auth_status_all`,存在性检测不读 token);scripts/llm_auth.py 三子命令(status/login/verify);docs/llm-auth-quickstart.md 两法(订阅荐/api key)。test_subscription_cli_llm 16 passed(9 adapter fail-closed+7 onboarding)。两家订阅真调通 pong、model 可切换。诚实边界:订阅账号自动化 ToS 由用户自担(个人本地),token 存 CLI 自身安全存储、本仓不读/不复制/不记录 |
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
