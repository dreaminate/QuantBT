# LOG · 执行台滚动日志

> 每个 session/Goal Loop 一条，最新在上。只记**做了什么 + 结果 + 下一步**，详情进 `tasks/done/<id>/`。

<!-- 格式·防跑偏 | 追加型：最新追加到本注释下方第一位。每条照此：
## <日期> · <标题>
- 建/改了什么 + 命门  - 验收：<对抗测试 + 变异 + 全量数字>  - 下一步：<…> -->

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
