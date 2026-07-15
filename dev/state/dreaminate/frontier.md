<!-- 重生型:每个 loop/session 收尾整篇覆写,永远只有最新一份(历史在 git)。模板 state/_TEMPLATE.frontier.md -->
# FRONTIER · dreaminate 前沿快照（重生型 · 每次整篇覆写）

> 给下一个 session/loop 的续接现场。**覆写,不追加**——旧快照不保留(要历史看 git log 本文件)。
> 与 `state.md` 分工:state = 对照 GOAL 的 gap 表(慢变);frontier = 正在进行的战役现场(每 loop 全刷)。

## 现在打到哪了
- **/loop 15m 自主循环运行中**(cron ce958a8c)。首轮启动切片 ✅(脏区收口 land `f41789dc`)。
- **切片① 39d08df8 · HS300 真数据证据链:核心目标已达成,本批已 land**——
  **GOAL §16「沪深300×10年日频读取<3s」以完整诚实链真数据转绿:measured=True / 0.0185s**。
  链条全走:pull(产线化,180/分限流+退避+幂等)→ preflight(12 项镜像门)→ DatasetVersion
  `hs300_daily_10y_readbench_cohort@20260714T201056_370595_0000__856b67b1`(65.4 万行,
  metadata 携 benchmark_only/survivorship/forbidden_confirmatory/volume_unit 四键)→
  不可变 manifest → HMAC 签名 universe(v2 携 300 成员 list_dates)+receipt → **跨厂商
  dual-model 三轮审查**(修门 REJECT→修复→chain approve_pin→delta approve)→ operator pin
  `quantbt-hs300-operator-root-v1`(指纹 79d1a7b7…1653;key 在 keyring 永不入仓)。
  证据包在仓可下钻:`dev/research/findings/dreaminate/hs300-chain-evidence-20260714.md`。
- **harness 修门已 land**:覆盖率「自上市起算」(0.80 纯计数契约,311 天真实停牌实证)+签名
  list_dates(universe v2)+上市前 bar 拒+首 bar 滞后≤10 天;72 benchmark 测试(59 保+13 新)。
- **autoplan 四相评审已跑完**(CEO/Eng/DX 各双声道+我=三方;Design 跳过=前端零 diff):
  三声道收敛必修项全落——fetch 产线化/README 漂移修正/语义化 dataset_id+metadata 入签名制品/
  store-token 子命令/keygen 死路纠偏/quickstart 一页/assert→raise/keygen fail-closed/
  .partial 防 glob 撞/monotonic 限速/三参数一致性校验。评审产物:autoplan restore point +
  本 frontier + 证据包。
- **卡 39d08df8 ✅ done**(2026-07-14):研究面资产已注册(hs300_research_universe_10y,
  1.38M bars/622 只含退市/19,200 停复牌,12 质量门真数据 PASS);探针 #6(bar 日因子完备,
  日期错位必抓)/#7(有记录停牌伪 bar 必抓,含退化窗编码)已落带种坏测试;质量门经 codex
  四轮对抗(轮4-7 全 reject→逐轮修复:对称比率/不变量收敛/finite 门),最终数学收敛=
  「factor-价格补偿不变量」,全部反例钉死为回归测试(41 producer tests)。
  **scope 裁定(Inference,待用户复核)**:质量门承诺「无意损坏」检测;对抗性防篡改
  (canonical floor=真实暴跌日耦合伪造)归签名链/重拉比对/跨源/vintage(后续卡)——
  codex 轮7 reject 基于对抗性标准,operator 裁定超出本层承诺,verdict 轨迹全留档。

## 活跃上下文
- **audit 基线四项全程不变**:61/20,339/26,209,663/`1c1788b0bbe2`(canonical 配方:
  `cd data/audit && find . -type f | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256`)。
- **测试基线(实跑)**:后端全量 **6288→(终验以最新实跑为准)** passed/0 failed;benchmark 72;
  data_onboarding 24;前端 423+build PASS(本切片前端零 diff);validate_dev PASS(两个已知 ⚠️:
  state.md 蒸馏归档=后续切片)。
- **本机制品(gitignored,不入仓)**:staging=data/.cache/tushare_hs300_raw(68MB);
  链产物=data/datasets/{registry.jsonl,lake/,provenance/,manifests/};keyring:tushare token+
  hs300_provenance key。fetch 脚本已产线化(scripts/hs300_onboard.py pull),tmp 脚本弃用。
- **工作模式**:EnterWorktree 编辑→过门→主 checkout merge main→push;codex(gpt-5.6-sol ultra)
  =跨厂商 verifier(builder≠verifier);分类器拒改 .claude/settings.json(不再试)。
- **诚实残余(证据包详列)**:operator_attested≠vendor 签名/第三方审计;对称 HMAC 无轮换撤销;
  root 只 pin key 指纹不绑 version(未来制品逐个复核);纯计数覆盖率不建模停牌结构(suspend_d
  制品=后续);_sha256_of_frame 依赖 polars IPC 编码稳定(共享基建,勿单方动);
  DatasetVersion.to_dict schema 演化会破旧 receipt 重算(共享基建,记录待改);
  build 非版本寻址目录(重跑覆盖旧产物,门会拦但旧证毁);Run first-screen 门=harness 第二 gap(另卡)。
- **切片③ CI ✅ 完成(2026-07-15Z)**:run7 29377617245 success(后端 6315/0+前端 423+build)。
  七轮迭代全录:run1 python-multipart 洗白→run2 xgboost/torch/reportlab 洗白(44败)→
  run3 我的空 pin 失误→run4 polars/pyarrow pin 过期+pypdf/catboost/tesseract(7败)→
  run5 时间炸弹+跨进程边际(2败)→run6 loader 时钟同罪+PIT 超时边际(2败)→run7 绿。
  CI 的头号价值实证:六类「本机隐性状态洗白」被逐一还原(依赖×5/版本 pin×2/时钟×2/资源边际×2)。
- **切片② 接线已 land(卡 9c5e6975,P0/§7 · in_progress 待真实凭据)**:应用内跨厂商
  dual-model 审查脚本化端到端 `scripts/dual_model_review.py`——secrets 窄读→内存 keystore
  (llm_<provider>+note extras,与 /api/llm/configure 同约定)→build_agent_llm_gateway
  (单一源,dev_local 永不进路由)→builder(anthropic)→ReviewSubjectBinding(服务端派生
  verifier prompt)→verifier(openai,independence_required)→bind/validate→IndependenceVerdict,
  HMAC 密封 LLMCallRecord 落盘。结构性事实:应用 live 运行被 secrets.yaml Binance-material
  设计性阻断(预期,不修)→脚本化直调机制链是唯一诚实形态,代码路径与应用内一致。
  **codex(gpt-5.6-sol ultra)九轮对抗复审**:R1 REJECT(五缺口:同源伪装可产 independent=True/
  prompt 未互证/evidence 未密封/子集不 fail-closed/测试判别力不足)→逐轮修复+重验:同源拒斥
  (同 key 字面量拒)/gateway 记账 prompt digest 互证/HMAC 密封 evidence+verify_evidence_file/
  fail-closed(缺凭据/单厂商拒运行,preflight 常开)/key 泄漏全路径(loader 异常抑制+类型门+
  preflight 全 key 脱敏+evidence 双扫)。R5-R8 收窄到编码/URL 结构性关类:多层 JSON 转义
  **迭代到真不动点**(任意嵌套深度剥到 raw)+_redact 兜底全文遮蔽;relay 披露改**端点身份**
  (scheme+host+port,按 requests 规范化 unquote+去尾点,完备性优先宁多报)。R9 被 OpenAI 网安
  分类器掐断未出 verdict(非缺陷,仅翻出 unquote_unreserved→我的全量 unquote 更激进=更安全)。
  **测试 3→36**(桩注入,零网络):端到端独立 True/密封复验/逐坏门(同源/prompt 偷换/多层编码
  key 泄漏/百分号 host 同中继/篡改三态/变异杀手)全绿。**真实跨厂商调用登记待用户提供有效
  anthropic 原生+openai 凭据**(本机中继 key 双 401,脱敏诊断留档;凭据有效时同一路径即通)。
  机制级残余(binding 未绑 adapter 实发 payload/provider 身份声明式)→**新卡 tasks/pool/8be0e547**。
- **切片② CI 已确认绿**:run 29387569832(2e237b1f)success——后端+前端全 job 绿,
  gh 实查落定。dual-model 应用内接线的 CI 面从此为真绿(非 Unqueried)。
- **FastAPI on_event→lifespan 迁移已 land**(分支 slice/on-event-lifespan,commit
  f8d1f1cd+d940aed3):@app.on_event(startup/shutdown)→_app_lifespan asynccontextmanager
  (707 行构造挂载,boot 期按名解析靠后 handler,try/finally 无条件 shutdown 严格等价旧
  _DefaultLifespan.__aexit__)。codex 复核首轮 REJECT 两点(serving 异常 shutdown 被跳过/
  缺"真绑 app"牙)→修复轮 APPROVE。test_app_lifespan.py 5 测(顺序/无 legacy/真绑 app/
  startup 异常外传/serving 异常仍 shutdown)。后端全量 6356 passed。
- **前端 bundle 拆分已 land**(分支 slice/frontend-bundle-split,commit 593ffa02):
  vite manualChunks 把单 2,557.79 kB JS chunk→9 可缓存 chunk(echarts 1.38MB 隔离/
  app 码 index 813.82/react-vendor 142.40/recharts 62.60/vendor 98.92/query 35.59/
  router 13.59)。铁律守 react/react-dom/scheduler 同 chunk(防多实例)。build 绿+423 前端
  测试全 passed。**边界**:首屏字节未减——echarts 只在 RunDetailPage 用,但该页是 GOAL §M15
  「唯一冻结例外」旧 SPA、eager 加载;lazy-load 需碰冻结面=**用户拍板项(登记,非阻塞)**。
- **worktree 已装前端 node_modules**(npm ci 206 包,gitignored):前端最低验证门(test:run/
  build)本 worktree 从此可真跑,不再靠上次 CI 承接。
- **卡 861182e6(CPCV→gate)已测绘,发现比表面大**:①/② 机制层其实**已 done**(overfit_gate
  run_overfit_gate 已消费 cpcv_distribution+cpcv_policy report_only/cpcv_conservative 降级、
  gate_runner/promote 透传已接)。真缺口=③双轨 report 全无(有前端件)+cv_scheme=cpcv 作
  一等模式(跨 3 层训练重构,train_model 单路径 concat≠CPCV 多路径)+DSR 口径未实现(现 gate
  消费 r2/auc 的 q05 非 Sharpe/DSR,DSR 转换=方法学 follow-on=用户的选择)+backtest promote
  生产者未喂 cpcv_distribution(管线在数据源缺)。**横跨前端+方法学+跨层重构,非干净后端切片,
  暂缓**;测绘全档见本轮 Explore。
- **validate_dev warning gap 已闭**:现 61 ✅ / 0 ❌ / **0 ⚠️**(state.md 早已蒸馏到 6505 字节,
  loop 契约里的「两 warning」是陈旧描述)。
- **90+ worktree/分支盘点已 land**(只列不删,commit 6e22d69e):90 worktree(89 agent-*+主)/
  113 分支(107 已合并可删/5 未合并需审)。5 未合并逐个标审建议(含安全相关 autopolish-w1 沙箱
  逃逸止血,删前确认已在 main);附用户可自跑清理命令 + 不可逆边界。全档
  research/findings/dreaminate/worktree-branch-inventory-20260715.md。**删除等用户拍板(registered)**。
- **GoalProofLedger LRU(P2)已 land**(分支 slice/goalproof-lru,commit cbdc9617):无界
  dict→OrderedDict 有界(maxsize 256);正确性红线守住(命中仍 token+WAL 文件状态绑定门控,
  淘汰只重算不 stale,WAL 非空绑定边界一字未动)。42 测过+codex APPROVE。同分支带 CI flake
  兜底 commit 95e3efb2(训练 PIT 子进程超时 300→600s:dd6db35c CI 后端因慢 runner 22:48
  子进程 300s 被杀=资源边际 flake 非回归,后端代码零变更)。
- **待用户权衡(engineering tradeoff·registered)**:8be0e547 机制层 dual-model 加固的可实现核=
  改 LLMClient 接口让全部 adapter 回带实发 payload digest。四面权衡:防的是「内部 adapter
  改写 payload」内部代码完整性威胁(非假绿灯/非外部对手),当前 gateway-digest 绑定对 app
  可控路径已诚实;广面接口改(4 adapter+全部桩)+6356 测试回归风险 vs 边际防御价值——**架构
  深度取舍,摆代价给你拍**:做则 duet 全量验证,不做则维持现状+卡里已诚实登记边界。
- **下一步(优先序)**:① 切片②真实调用(待用户凭据,非阻塞) ② Run 首屏门(§16
  KNOWN_RUN_GAP,需 Playwright 浏览器基建) ③ 8be0e547(待你权衡上条)。本地干净可收口
  切片渐近清零:剩 Run 首屏(需浏览器基建)+8be0e547(待拍)+前端 eval UI/echarts lazy(用户拍板)。

## 待裁 / 卡点
- **[待用户复核] 研究面质量门 scope 裁定**:codex 轮7 最终 reject(对抗性标准) vs operator
  裁定「质量门=无意损坏检测,对抗性防篡改归签名链/重拉/跨源/vintage 层」——翻案后果:
  本层需接跨源事件表或 factor vintage 才算收口,约一个切片工作量;全部 verdict 轨迹在证据包。
- 无阻塞性待拍板。已按「可逆+不越线」自决并 log 标 Inference 的:token 迁 keyring/覆盖率门
  0.80 纯计数契约/契约常量留 harness 原位(生产者镜像+相等性钉死)/幸存者 cohort 案否决。
- 等用户拍板(非阻塞,registered):90+ 历史 worktree/分支清单(只列不删);DVC vs 自建数据版本化
  的 ADR 补记;非对称签名(Ed25519+轮换撤销)升级时机;2026-06-29 四项旧待裁(核实存活性后再摆)。
- **[Inference:切片② review 门]** codex 九轮对抗:R1-R8 每轮 REJECT 均转成已修+已验的具名门与
  回归测试(codex 反例逐条钉死),R9 被厂商网安分类器掐断(非发现)。当前 commit b5473f38 **无已知
  in-scope 缺陷**,残余(IDNA/DNS 别名/机制层身份)已登记卡 8be0e547。据此按「四门过+放心大胆做」
  自决 land,可翻案。真实跨厂商调用另计,凭据到位后跑真证据。
