# LOG · 执行台滚动日志

> 每个 session/Goal Loop 一条，最新在上。只记**做了什么 + 结果 + 下一步**，详情进 `tasks/done/<id>/`。

<!-- 格式·防跑偏 | 追加型：最新追加到本注释下方第一位。每条照此：
## <日期> · <标题>
- 建/改了什么 + 命门  - 验收：<对抗测试 + 变异 + 全量数字>  - 下一步：<…> -->

## 2026-07-15-1043 dual-model binding(卡 8be0e547)跨厂商 skeptic 判 NOT SOUND—未 land 已 revert
- deep-opus 实现+我同厂商复审判 sound,但 codex 跨厂商 skeptic 逮 4×P1:digest 哈希 messages 非实发 payload(label actually_submitted 越界)·订阅 opt-in 后 _assert_submission_bound 必崩(burn 额度才炸)·submitted_prompt_digest 加 v3 必填废旧 seal/旧 journal 读不了·identity_basis 未持久化下游仍裸 independent:true
- 同厂商复审不足以守诚实边界——本次现场证(被审对象就是独立性机制,独立审查抓出自己越界)。收紧诚实 scope+findings 见 [[dual-model-binding-crossvendor-findings-20260715]];卡保持 pool/todo,重做须跨厂商复验。main 干净

## 2026-07-15-0908 补 F1 producer 侧 factors_all_finite 建门——非有限 adj_factor 双拦已闭
- research_quality_report 补 factors_all_finite(镜 bars_all_finite is_finite);NaN/±inf factor(polars 里既非 null 又非<=0)令 quality_verdict≠pass、不注册。承接 §11 PIT skeptic F1(读侧 0c926235 已拦,建侧原只 <=0 漏非有限)
- 对抗测试 test_factors_all_finite_caught(NaN+inf 反例)+变异门(门恒 True→red-then-revert);data_onboarding 32 passed+后端全量 6475 passed/0 failed。防御纵深:读侧+建侧双拦

## 2026-07-15-0842 §11 PIT 复权读侧接线 land——真实 HS300 后复权 hfq panel(fail-closed)
- panel_source.py:market ashare_hs300 registry present→raw×adj_factor 四价列同乘(volume raw)·缺因子/非正/非有限(NaN±inf,F1)/dup 全 fail-closed raise;absent→逐字节合成兜底零行为变更;registry 单一源=paths.DATA_ROOT(=main.py:734,D-11-DATA-ROOT=b 无双源漂移)
- §16 隔离:研究/回测 env≠perf harness(物理隔离)·perf_baseline_claim=False·拒 forbidden_confirmatory cohort;PIT:hfq PIT-safe·诚实标 no_per_row_factor_vintage 不冒充 bitemporal
- 验证:12 对抗测试+后端 6474 passed/0 failed+前端 build 绿;hfq 方向(×→÷)与非有限(is_finite)变异门均 red-then-revert;byte-identity 双证。deep-opus clean-context 实现+独立 skeptic 判 §16 sound(逮 F1 已修)
- Inference(未拍板默认可翻案):D-11-MARKET-KEY=B(新 ashare_hs300 key)·D-11-VOLUME-ADJ=raw·D-11-DATA-ROOT=b(据新证=main.py 已有 paths.DATA_ROOT 单一源,翻我先前 <repo>/data 默认)
- follow-up(非 §16,登记非阻塞):读时 manifest hash 复验(F3)、producer hs300_pipeline factors_all_finite 建侧门(现只 <=0 无 finite 检查)

## 2026-07-15-0709 S6 订阅账号 in-app 登录中继 + K4 token 泄漏面收口 + §3 假绿灯修复(跨厂商切模型伞卡 db95c0c6)
- 后端 begin_subscription_login/_spawn_detached_login(DEVNULL 三流·不 wait·固定 argv,后端不碰 token)+2 端点(机器级 admin gated)+前端订阅登录面板(状态卡/一键登录/终端降级)
- K4:全仓弃 claude setup-token(打长效 token 到 stdout)→ claude auth login --claudeai(存 keychain);清 scripts/llm_auth.py+docstring+错误串+quickstart,login_cmd 单一源防漂
- §3 假绿灯:subscription_authed 按 authMethod=claude.ai/firstParty/subscriptionType 正信号闸,console(--console 按量计费)不再冒充订阅(deep-opus skeptic 逮·变异确认)
- 验证:后端 6462 passed/0 failed·前端 430 passed·build 绿;skeptic 判 token 边界 sound,5 findings(假绿灯/K4/echo/DoS/vacuous 测试)全修+变异门。真浏览器登录端到端 Unverified(用户本人按)
- 残余:K3(订阅带工具对话跑不了,待拍板 tool bridge/纯聊天/保持现状)、S5(订阅接生产 gateway,K3 所限)

## 2026-07-15-0539 跨厂商切模型 S7 前端切换器落 main——API-key 线端到端可用+有 UI
- ModelSwitcher.tsx 挂 Mode2ChatPage active-thread header:原生 select+optgroup+Auto 顶项;GET /api/llm/models(filter authed&&selectable)+GET /llm-selection 回显,选中 PATCH(下条消息即生效,对话中途切);仅 API-key 可路由厂商可切,凭据不经前端,stale pin 兜底显示;前端测试 5,前端全 428 passed+build 绿;S5-piece1 scaffold+K3 记账一并 land 803d0e27
- **特性状态**:S1 目录/S2 路由/S3a-b gateway+pin 穿链/S4 隔离(证成)/S7 前端 全 done——**API-key 每对话切模型+中途切 端到端可用+CI 绿+有 UI(北极星:能用)**。残余:S5 订阅接生产 gateway(K3 待拍板 tool bridge,暂缓)/S6 内嵌登录中继(订阅 auth 用,优先级降)。卡 db95c0c6 主体交付、S5/S6 待拍板,保持 in_progress

## 2026-07-15-0525 K3 约束确认+待拍板:订阅模型跑不了带工具 agentic 对话(厂商 CLI 拒工具)
- 核实:orchestrator 按 role 算 role_tool_schema(_role_filtered_tool_schema,orchestrator.py:454),带工具 role 传非空 schema;订阅 adapter 拒非空 tools(test_tools_rejected)。故订阅模型只能跑无工具场景(dual-model 审查已可用/纯聊天),跑不了带工具生产 agent 对话
- **待拍板(用户已知悉,非阻塞)**:订阅模型进带工具对话=需受治理 tool bridge(工作量大+ToS 更灰,登记等拍板)/或加纯聊天模式(中)。默认保持现状:订阅用于审查、对话切模型走 API-key(全场景已可用)。S5 订阅接生产 gateway 暂缓(避免建误导性「显示可切一切工具就崩」);S5-piece1 credential_pool/factory 认 subscription_cli 已本地 committed(无害 scaffold,任一方案都要)
- 下一步转 S7 前端切换器——让 API-key 每对话切+中途切对普通用户可视化可用(北极星:能用)。用户确认两条线(订阅无工具场景/API-key 全场景)+对话中途可切的理解正确

## 2026-07-15-0456 跨厂商切模型 S3b 全部落 main——后端端到端功能可用(持久化+pin 穿生产链+selection API)
- S3b-1 持久化(ChatService.update/get_llm_selection owner-scoped)+S3b-2/3 3 跳传参(_current_agent_gateway/_dispatch/两端点读传 model_pin,gateway.py 零改动)+GET/PATCH selection 端点(校验 gateway 可路由+owner-scoped)。用户 PATCH 对话手选模型→驱动那条对话生产 agent
- S3b-2/3 skeptic:运行期无安全缺陷(dual 门/跨厂商/越权/假账/stale-pin 6 项亲验绕不过 fail-closed),逮 1 MEDIUM(核心接线零端到端覆盖,pin 静默失效变异存活)——补集成测试+**临时断 model_pin 传参确认测试变红**再还原(证明门有牙)。全量 6444 passed;land ae2e61b1
- 剩余:S4 dual-model 隔离门(独立门已 3 层成立,补 conversation 层免疫测试)、S5 订阅接 gateway、S6 内嵌登录中继、S7 前端。CI flaky 训练超时(test_training_runner 300s CI 慢 runner)间歇性,拟停一轮 push 让最终 head CI 跑完确认

## 2026-07-15-0406 跨厂商切模型 S3b-1 每对话 llm_selection 持久化落 main
- ChatService.update_llm_selection(owner-scoped 原子 metadata read-modify-write,Auto 清 pin)+get_llm_selection(服务端读=K10)+_normalize_llm_selection(半残 pin fail-safe→auto);canonical {mode:auto|pinned,provider,model,auth_kind?,updated_at};对抗测试 6(owner-scoped 跨 owner=not found/每对话隔离);全量 6435 passed;land 5a8fc617
- S3b-2/3 待做:gateway 接线(_current_agent_gateway 加 model_pin→build_agent_llm_gateway default_pin)+selection API 端点+**先核实 ChatService 是否生产 _dispatch_production_agent_turn 真读的对话存储**(已派 Explore 追链,codex 提过 workbench 走不同路径)

## 2026-07-15-0342 跨厂商切模型 S3a gateway 构造期 pin 注入落 main(K1)——含对抗验证逮到的 CRITICAL 跨厂商泄漏修复
- LLMGateway(default_pin=(provider,model)) 在 complete() 盖章成 hard pin,仅非独立且非 verifier role 生效(dual 门物理免疫);解决 codex K1(真实主链走 GatewayLLMAdapter,pin 须 gateway 层注入)
- S3a skeptic 逮 CRITICAL-1:盖章只写 complete() 局部 req,但 _invoke_with_fallback 重取原始 capability→fallback 时 pin 蒸发→静默跨厂商泄漏(跑通复现:default_pin=anthropic 首刺失败→prompt 静默送 openai)。修:effective_capability 穿进 _invoke_with_fallback,record 仍读原始保诚实;补变异门(此前零覆盖 leak 绿着 ship)+LOW-4 role 纵深+MEDIUM-2 spy 门
- 全量 6429 passed;land dc940949。**pin 现在真到 gateway 但生产装配点 main.py _current_agent_gateway 尚未传 default_pin**(诚实残余,机制半接线)——S3b 接:对话持久化 metadata.llm_selection+selection API+_current_agent_gateway(model_pin)。skeptic 前向:verifier 请求必带 independence_required=True

## 2026-07-15-0307 跨厂商切模型 S2 hard-pin routing 落 main + 参考实现研究
- routing.py RoleCapabilityRequest 加 pin_provider/pin_model,resolve 硬 pin 过滤仅 independence_required==False 生效(dual 门物理免疫)、pool 不变保 no-mix、pin 厂商无候选→PinnedModelUnavailable 绝不跨厂商 fallback
- S2 skeptic 逮 3 MEDIUM(命门稳固无绕过;M1 pin 丢弃登记 tier 致 degraded 判反+可绕 strict_degrade、M2 pin_model fallback 锁死实际靠 health 断路器隐性兜底非声称的 signature、M3 命门测试不够强)全修+补真测试;S2 测 14+gateway 76 无回归;全量 6423 passed;land 6a8990e9
- 用户指定参考 Claudian/Hermes/OpenClaw 源码(全 MIT/Apache)已调研落 finding:sk-ant-oat 直连 400 真因=缺 CLI 指纹层,但指纹签名绕过=计费规避 ToS 红线只学不落地;S6 内嵌登录采 Hermes session-relay+OpenClaw VPS-aware 贴码;直连高阶开关登记待拍板

## 2026-07-15-0232 跨厂商切模型 S1 模型目录落 main——GET /api/llm/models + 对抗验证加固
- model_catalog.py 唯一 LLM 模型清单源:api-key live 拉/models(加固 stream 上限+禁 redirect+fail-closed)、非聊天模型 selectable=false、订阅 curated(supports_tools=false)、TTL 缓存+single-flight+凭据零触碰;GET /api/llm/models 端点(订阅探测 60s TTL 缓存防 DoS)
- deep-opus skeptic 对抗验证逮到 7 项(1 must-fix 假绿灯:上游挂掉时缓存命中把 curated_fallback 谎报 live 撞§3)全修+回归钉死;后端全量 6409 passed;land e89964a8,CI run 29404840965 in_progress
- 参考 Claudian/Hermes/OpenClaw 源码的研究 agent 进行中,结果将融进 S2~S7(尤其 S6 内嵌登录中继);duet 蓝图 findings/dreaminate/model-switch-crossvendor-design-20260715.md

## 2026-07-15-0046 切片② dual-model 真跨厂商调用跑通(订阅路径)——卡 9c5e6975 done
- 订阅账号 auth+onboarding 做全(subscription_cli_llm.py adapter+llm_auth.py onboarding+docs;陌生用户从零 status/login/verify)——两家订阅 CLI 真调通 pong,model 可切换
- dual_model_review.py 接订阅(--subscription):builder=anthropic claude-sonnet-4-5/verifier=openai gpt-5.6-sol 真跑 independent=True,verifier 独立重算 IC=0.996834 逮 builder 夸大,evidence 密封;绕过 api-key/中继 401 blocker,真跨厂商比中继强
- CLI 子进程路径(非 HTTP token 重放):CLI 自理 OAuth/刷新/签名,受支持(为 CI/脚本设计)、ToS 灰度低。机制级残余(卡 8be0e547)不变

## 2026-07-14-2330 5 未合并分支全核完:1 救回(autopolish sandbox)+4 可删
- Explore 子代理核查:S13(a400943)/S16(a763)producer 已换位重实现进 promote_assembler.py:_assemble_section13/16(typed dataclass fail-closed)+test_runjson_producers.py 覆盖;prodbuilder=两者 merge 无额外码;wip/uncommitted-closure 是作者自标 fake-green,main 主动加守卫(goal_coverage.py:359/579)拒绝其 goal_closure ref——与 autopolish-w1 正好相反
- destructive 删除留用户/确认无并行 session 在用 worktree 后执行(89 agent worktree 共享 stash 栈,盲删跨 session 损伤风险);盘点 doc 命令用户可自跑

## 2026-07-14-2305 IDE 沙箱逃逸止血 land——盘点捞回从未 land 的 P0 安全加固
- worktree-autopolish-w1@92eade4f(2026-06-25 审计 pass3 #1)从未合并 main,main sandbox.py 仍 5-30 base 版:posix_spawn 族未封/import ctypes 未拒(CDLL RCE 绕 os.system)。按 main 现结构重实现:prelude 封 posix_spawn 族+入口 AST 预检拒 ctypes/cffi 直接 import/__import__
- codex 安全复核逮到 __import__(name=)关键字形式漏网(只查 node.args[0])→补拦位置+关键字两形式;codex 掐于网安分类器但探测尽职。6 对抗测试(种坏可抓)+6363 passed
- 诚实边界:defense-in-depth 非 hardened(importlib/getattr 可绕=声明边界,真隔离 OS 级 P0 卡 5bfb5202),沙箱跑用户自己码防手滑非防对手,非活 P0。盘点证'只列不删'对——其余 4 未合并分支删前需同样逐个核

## 2026-07-14-2239 GoalProofLedger LRU(P2) land + CI 训练 PIT 超时 flake 兜底
- snapshot cache 无界 dict→OrderedDict 有界(maxsize 256,读命中 move_to_end/写后逐最旧);正确性红线守住:命中仍 token+WAL 文件状态绑定独立门控,淘汰只重算不 stale,WAL 非空绑定边界一字未动;42 测(2 新 LRU 对抗)+codex APPROVE
- 同分支 CI flake 兜底:训练 PIT 子进程超时 300→600(dd6db35c CI 后端因慢 runner 22:48 子进程 300s 被杀=资源边际,后端零变更/本地全过/上个 run 绿);120→300→600 逐次实证
- 8be0e547 机制层 dual-model 加固按四面权衡登记待用户拍板:广面 LLMClient 接口改防内部代码完整性威胁 vs 边际价值,架构深度取舍

## 2026-07-14-2209 90+ worktree/分支盘点 land(只列) + validate_dev 0 warning 确认
- 盘点:90 worktree(89 agent-*+主)/113 分支(107 已合并可删/5 未合并需审含安全 autopolish-w1);只列不删=用户拍板,附清理命令+不可逆边界;档 research/findings/dreaminate/worktree-branch-inventory-20260715.md
- validate_dev 现 0 warning(state.md 早已蒸馏 6505 字节,契约陈旧描述);下轮 8be0e547 机制层 dual-model(P1,duet,广面 adapter 接口改)

## 2026-07-14-2150 前端 bundle 拆分 land + 卡 861182e6 测绘
- vite manualChunks:单 2,557.79 kB JS→9 可缓存 chunk(echarts 1.38MB 隔离/index 813/react-vendor 142/…);react 系同 chunk 防多实例;build 绿+423 前端测试 passed(worktree npm ci 装依赖后真跑)
- 边界诚实:首屏字节未减(echarts 只 RunDetailPage 用,该页 §M15 唯一冻结例外、eager);lazy-load 需碰冻结面=用户拍板项,登记非阻塞
- 卡 861182e6(CPCV→gate)Explore 测绘:①/② 机制层已 done(gate 已消费 cpcv_distribution+policy+降级),真缺口=③双轨 report+cv_scheme 一等模式(跨层)+DSR 口径(方法学)+backtest 生产者;横跨前端/方法学/跨层重构,暂缓

## 2026-07-14-2129 FastAPI on_event→lifespan 迁移 land + 切片② CI 确认绿
- main.py @app.on_event(startup/shutdown)→_app_lifespan asynccontextmanager;try/finally 无条件 shutdown 严格等价旧 _DefaultLifespan.__aexit__;startup_event/shutdown_event 保留模块级函数(直调不破)
- codex(gpt-5.6-sol ultra)复核首轮 REJECT 两真缺陷(serving 异常 shutdown 被跳过/缺'真绑 app'牙)→try/finally+2 新测修复→修复轮 APPROVE;test_app_lifespan 5 测
- 后端全量 6356 passed;切片② dual-model CI run 29387569832 gh 实查 success(后端+前端),CI 面转真绿

## 2026-07-14-2050 切片② dual-model 应用内跨厂商接线 land(卡 9c5e6975 in_progress)
- scripts/dual_model_review.py:secrets 窄读→内存 keystore→build_agent_llm_gateway→builder(anthropic)→binding→verifier(openai,indep)→HMAC 密封记录+独立性判定
- codex(gpt-5.6-sol ultra)九轮对抗:R1 五缺口(同源伪装/未互证/未密封/非 fail-closed/判别力)→逐轮修复重验;R5-R8 结构性关类(反转义迭代到真不动点/relay 端点身份 requests 规范化);R9 被厂商网安分类器掐断非缺陷
- 测试 3→36(桩注入零网络)全绿;后端全量 6351 passed;真实跨厂商调用待用户凭据(中继 key 双 401,脱敏留档)
- 机制级残余(binding 绑 adapter 实发/身份可验证)铸新卡 tasks/pool/8be0e547;前端零 diff 门由 CI run 29377617245 承接
- Inference: review 门=九轮对抗全修+回归钉死、R9 厂商分类器掐断非发现、无已知 in-scope 缺陷,按四门过自决 land 可翻案

## 2026-07-14-1717 切片③ CI 完成:run7 29377617245 gh 实查 success(后端 6315/0+前端 423+build);七轮迭代修 11 处本机洗白(依赖5/pin2/时钟2/边际2);CI 字段首次真实转绿

## 2026-07-14-1502 卡 39d08df8 done:研究面资产+探针#6/#7 落地;质量门经 codex 四轮对抗数学收敛到 factor-价格补偿不变量(全反例钉死回归);scope 裁定登记待用户复核(对抗性防篡改归签名链/vintage 层);后端全量以终验行为准

## 2026-07-14-1336 切片① HS300 真数据证据链核心达成并 land:harness 真数据转绿(0.0185s/3s,measured=True);链条全走(pull→preflight→DatasetVersion+manifest→签名 universe/receipt→跨厂商三轮审查[REJECT→修复→approve_pin→delta approve]→operator pin);autoplan 三相三声道评审必修项全落;后端 6298/0 failed;卡余研究面资产+探针#6#7。Inference 自决项(可翻案):0.80 纯计数契约/契约常量留 harness/token 迁 keyring

## 2026-07-14-1228 切片① duet 裁决落定(签真实成员+修门,弃幸存者cohort案与timeline案);拉数完成(137.7万行/622只/68MB);harness 修门 commit e2878c66(66 passed,7 新变异探针);生产者实现+codex 门审并行中

## 2026-07-14-1208 切片① 39d08df8 开工:四路侦察完成;token 迁 keyring(Inference 可翻案)/universe 码 000300.SH 实测可用/覆盖率门不可满足性真数据证明(61 of 300 上市晚于80%线)——修门方案定型;窗口 20160601-20260630;duet 双脑设计评审进行中

## 2026-07-14-1151 loop 首轮启动切片:脏工作区收口 land main(4409738d migration + 3a82b8e6 docx);Atlas 试验产物 .git/info/exclude 本地排除不入仓不延续;audit 基线三项精确吻合,manifest 配方钉 canonical(1c1788b0bbe2)

## 2026-07-14-0926 OS 结构改造 v2 迁移落地(冻结层同步 MDO@81593ab)
- state.md 58 条「上次刷新」堆叠拆出:最新一条进 frontier.md,其余走 git 历史;222KB 待后续蒸馏
- 派生视图 10 个 git rm --cached(DEVMAP/9 个 _NAV/board);dev/.gitignore 接管
- build_card_counters 退役;desk-handoff→findings/_shared/;_areas.md 六域词表起表
- 下一步:state.md 残余 222KB 按重生型蒸馏成 gap 表
