# LOG · 执行台滚动日志

> 每个 session/Goal Loop 一条，最新在上。只记**做了什么 + 结果 + 下一步**，详情进 `tasks/done/<id>/`。

<!-- 格式·防跑偏 | 追加型：最新追加到本注释下方第一位。每条照此：
## <日期> · <标题>
- 建/改了什么 + 命门  - 验收：<对抗测试 + 变异 + 全量数字>  - 下一步：<…> -->

## 2026-06-26 · §8 治理脊柱门 advisory 接进 agent orchestrator Review（卡 a8f3c1d2 · D-GOV-ADVISORY）

- **实现**：新增 `agent/orchestrator/governance_advisory.py`，把已建 `GovernanceSpineGate.evaluate(SpineEvidence)` 接进 orchestrator Review 形态；`AgentOrchestrator` 新增 `advise_governance`，包导出同步。判定零重写，全委派 §8 门；事件 / `to_dict()` 只投 clause id、bool、计数，不投 evidence surface、`verdict_text`、`violation` 文本，secret 不回显。advisory-first：违反只 flag + `VerifierChallengeRaised`，不阻断 `plan/dispatch/replay/repair`；若底层 future `SecretLeakError` 硬停，本层只投 `INV_SECRET_PLAINTEXT` 后 re-raise。
- **验收**：新增对抗测试 14 passed；相邻回归 `test_trust_orchestrator_advisory` 17 passed、`test_governance_spine` 30 passed、`test_agent_orchestrator` 47 passed。MUT：临时洗白 `flagged=False` -> 目标测试 1 failed；恢复后新增测试 14 passed。后端全量 `2706 passed / 13 skipped / 0 failed / 117.30s`。
- **下一步**：free-text -> `SpineEvidence`/`TrustContext` 上游映射仍未做；`advise_trust/advise_governance/evaluate_run_releasable` 接 main.py 真 agent/promote 端点仍是中心串行 follow-on；硬 enforce 晋级需先评估证据输入完整度。

## 2026-06-25 · CPCV q05→gate 最后一公里——promote 真实路径读 emit cpcv 透传 gate（卡 f1bd08f2 · D-CPCV-PROMOTE）

- **缘起**：autonomous-loop（ultracode）。correctness 审计 workflow（wm8x329vn）#8（高假绿灯）：done 卡 89e7be1e 让 gate 接受 cpcv，但生产 promote 路径 `promote.py:_run_overfit_gate` 调 `evaluate_overfit_gate` 时从不传 cpcv → gate 恒 cpcv=None，cpcv_conservative 在真实晋级路径永远触发不了（我自己 cpcv→gate 工作的最后一公里断线）。
- **实现（additive）**：`_run_overfit_gate` 读 `result.get("cpcv_distribution")`（退 meta 内·须 dict status=ok）+ `meta.cpcv_policy`（默认 report_only·非法值回落·守不替方法学拍板）→ 透传 evaluate_overfit_gate。verdict.to_dict() 经 asdict 含 cpcv → run.json gate_verdict 携带。缺则 None（不编造·向后兼容逐位不变）。
- **验收**：test_gate_wiring +3（T-GW-7：emit 带 cpcv→verdict.cpcv 非空 fragile=True+policy 真读 / 不带→None / 非法 policy 回落 report_only 不降级）。MUT（promote 丢透传）→ 透传+非法回落 2 测试红、缺则 None 测试仍绿（精准）；定点反向 edit 后还原。**全量后端 1626 passed / 13 skipped / 0 failed / 149s**（基线 1623，净 +3）。
- **CPCV 全链端到端贯通**：库→消费(regression+二分类)→train_model opt-in→result.json→eval 端点→UI 卡→gate(run/gate_runner)→**promote 真实路径**。剩 861182e6 ③（cv_scheme UI 选项+双轨 report+Sharpe/DSR 转换=用户方法学）池卡留。
- **下一步**：分支续 land-ready，commit+push 自动；候选下一切片见审计残余（attribution provider / 信号组合器 / 监控绩效轴 554cdcf2）+ 池卡。

## 2026-06-25 · 监控调度 driver 接线——补缺失生产 tick loop 让 weekly cron 真 fire（卡 698a3c60 · D-MONITOR-DRIVER）

- **缘起 + 选片**：autonomous-loop（ultracode on）。先跑只读 correctness 审计 workflow（wm8x329vn·7 方法学域并行+对抗证伪·24 agent·全程 graphify+Read 不跑 pytest，不违「套件不叠跑」红线），排出 16 真缺口；取 #1（lev 8·不卡用户·最清晰假绿灯）。
- **缺口（端到端假绿灯）**：`main._start_production_monitor_scheduler` 注册 weekly DAG（cron 0 9 * * 1）+ log「已启动」，但 `Scheduler.tick()` 是轮询式（engine.py:302 docstring「调用方 loop 里 every N s 调 tick」）、生产**无 driver** → cron 永不到点 fire、退役闭环空转。端到端测试靠手动 tick+拨表 2000 年强制到期绕过 cron 门+绕过「谁 tick」，运维误以为周一自动退役实则 scheduler 静止。
- **活性先行**：注册的 cron 必有驱动器使其 scheduled_at≤now 时 fire；轮询器不被周期调用=cron 形同虚设。weekly op 是 kind=pure（不触券商/资金、只改 registry+PROV）→ driver 让它 fire 不涉动钱；A1 退役只接绩效/成本轴红线不碰。
- **实现（additive·daemon 线程）**：`_monitor_driver_loop`（`_MONITOR_DRIVER_STOP.wait(interval)` 周期 tick·异常吞续跑·读全局句柄）+ `_start_monitor_driver`（幂等·env QUANTBT_MONITOR_DRIVER 可关·TICK_SECONDS 周期）+ `stop_monitor_driver`；startup 接 driver、新增 shutdown 停。daemon+默认 60s ⇒ 秒级测试永不误触发。**护栏=不替用户拍「是否自动跑」**（env 可关）、修复 correctness 活性假绿灯非新设门。
- **验收**：`test_monitor_driver` 4 测试。MUT-1（driver 不 tick）→ 真-tick 测试超时红；MUT-2（startup 不接 driver）→ 接线测试红；双变异定点反向 edit 后还原。**全量后端 1623 passed / 13 skipped / 0 failed / 180s**（基线 1619，净 +4）。
- **诚实残余 → follow-on 卡 554cdcf2**：绩效轴真退役还差 ① 4 个 drift 检测器接 run_weekly_monitor_pass 的 perf_drift（审计 #3·lev 7）② per-factor IC 真源 ③ 观测落盘。driver 只解「scheduler 静止」这层。
- **审计其余高分发现（留池/已覆盖，供后续选片）**：#2 attribution 无 per-factor 收益 provider（lev 7·物化纯工程、选因子集=用户）；#4 信号弃权门 q̂ 不自动喂（lev 6·用户方法学）；#5 gate.color 无执行牙（lev 5·=用户「放行不设卡」哲学、非 bug）；#6 无规范信号组合器；#7 capacity 未接 sizing（无 sizing 层）；#8 cpcv→promote 真实路径残口（promote_ide_run 调 gate 时 cpcv=None）。被证伪：DSR/Bootstrap-CI 每支恒活、PBO 单策略恒 None（矩阵<10 列·三角退化双证据+yellow 天花板）。
- **下一步**：分支续 land-ready，commit+push 自动；候选下一切片见审计残余 + 池卡。

## 2026-06-25 · CPCV 路径稳健性 q05 接进 overfit gate（report-only 默认 / cpcv_conservative opt-in · 卡 89e7be1e · D-CPCV-GATE）

- **缘起**：autonomous-loop。池卡 861182e6 ② 残项「q05 接 promote/overfit gate」——CPCV per-path 分布此前只到 UI（done 876a0c11·report-only），未接 gate。
- **数学先行**：q05=路径分布 5% 分位=保守端；q05<无技能基线（r2:0/auc:0.5）=部分路径无优于随机=过拟合脆弱信号。取**保守分位非均值**（守「均值掩盖差路径」）。q05 是 PBO/DSR/Bootstrap-CI 多证据三角外的**第四类弱证据**（路径一致性≠跨策略过拟合 PBO，绝不喂 cscv_pbo）→ 最多 advisory 降一档（守 R2 单支不承重），**绝不硬 red、绝不升级**（路径稳≠策略好，不洗假绿灯）。
- **实现（additive·两层）**：① `overfit_gate.py` GateVerdict +`cpcv` 字段、run_overfit_gate +`cpcv_distribution`/`cpcv_policy`（report_only 默认/cpcv_conservative）+ 降级逻辑（仅 fragile∧green→yellow）+ verdict_phrasing/reason 三分支注；② `gate_runner.evaluate_overfit_gate` 透传两参数（**promote 生产路径接通**）。默认 None/report_only → 行为逐位不变（守不替方法学拍板）。缺/status≠ok→cpcv=None（未算≠已算）。
- **验收**：单元 `test_overfit_gate_cpcv` 6 + `test_gate_wiring` 透传 2（T-GW-6）。**变异（牙坐实）**：MUT-A（report_only 也降级）/MUT-B（降级成 red）/MUT-C（gate_runner 丢转发）三变异全抓——定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。green 可达走组合层 A2 allow_pbo_absent_green。**全量后端 1619 passed / 13 skipped / 0 failed / 183s**（基线 1611，净 +8）。
- **下一步**：861182e6 ③剩（cv_scheme UI 选项 + 双轨 report 不自动判赢 + Sharpe/DSR prediction→收益转换，用户方法学）池卡留；分支续 land-ready，commit+push 自动。

## 2026-06-25 · conformal 校准区间接进 model_eval——第二个价值闭环（卡 d4a324ae · D-CONFORMAL-MODELEVAL）

- **缘起**：autonomous-loop。继续合拢价值闭环——选最大未接数学件 conformal（R23）接进模型台。
- **实现（additive）**：`model_eval.conformal_prediction_band`——回归 OOS 残差按**时间序**切 calib(前半)/test(后半，leak-free)→ 复用 `split_conformal_interval` 算带 q̂ → 在 test 上报**真留出覆盖率**（非循环自证）；`training_job_eval` 加 `conformal_interval` 字段（additive，不破 charts/metrics）。命门实证：留出覆盖 α=0.1→0.901/α=0.05→0.948（跨 100 seed 匹配总体 k/(m+1)）。
- **两轮独立复核全闭环（同型门牙缺口第三轮，措辞/判别路径）**：
  - ① **Stop-hook codex 顾问 P2**：黑名单 `task=="classification"` 漏 **lambdarank(排序)** → 对排序 job 残差发假校准信号 → 改**白名单** `task!="regression"`（regression-only，classification/lambdarank/未知→None）。
  - ② **多透镜评审 2 confirmed medium**：(a) 覆盖测试措辞「经验均值≥1−α=达标」=**假绿灯**——80-seed 均值 0.8986<0.90 靠 -0.01 slack 过；conformal 保证的是**总体**覆盖 k/(m+1)≈0.9005≥nominal，**经验均值是带噪估计可略低**，称「达标」违 §3 → 改**统计一致性断言**（|均值−k/(m+1)|≤几个 MC 标准误，核 k/(m+1)≥1−α 总体保证，去「达标」绿灯措辞）。(b) **核心命门「非循环·非自证」零牙**——种 test→calib 循环自证 bug（`np.mean(|calib|<=q)`、恒≈0.905）7 测全过=纸糊门（**正是用户在 worktree 种的 `# INJECTED BUG: self-validate on calib`**）→ 加 **σ1/σ3 非循环 sentinel**（calib σ1/test σ3 真留出覆盖 0.36<<0.9，循环自证会≈0.9 被抓）。low 修：.1% 显示去进位掩盖（89.6%≠「90%达标」）/test 非有限掩码披露/抽样噪声 caveat/__all__ 导出。
  - **第三轮坐实同型盲区**（dsr sr_benchmark / banned-words / 此处循环自证）：我的测试一再"断言 happy-path 数字、不区分正确机制 vs 似真错误机制"。现都补成真有牙 sentinel。
- **验证**：`test_model_eval_conformal.py` 9 + model_eval 6 回归 passed；**全量后端 1564 passed / 13 skipped / 0 failed**，基线 1554 未破。
- **交付**：本轮 loop「commit 不擅自 push」→ 本地 commit、未 push。land main 待授权。下一步：继续合拢价值闭环或续方法学。

## 2026-06-25 · 冷启动 MinTRL 接进 run /overfit 投影——首个价值闭环合拢（卡 b1e4efdf · D-COLDSTART-WIRE）

- **缘起**：autonomous-loop。CEO 透镜连续 6 切片指「数学对、未接到用户」（7 张 P2 接线卡累积）→ 本轮转向**合拢价值闭环**。评估各 P2：CPCV→gate 难（CPCV 需按折 fit-predict、gate 只见最终 returns）、lifecycle→退役是方法学拍板、cold-start→UI 是前端 + RunDetailPage 冻结 → 选**最低风险**：MinTRL 接 /overfit（R27 明言冷启动呈现层、不动治理闸门）。
- **实现（additive·扩展不替换）**：`run_verdict._cold_start_evidence`（MinTRL 判证据充分性 4 状态：ok+短→证据不足/N<3 或 σ≈0→DSR 不适用/负 edge→never_significant）；`project_overfit` 加 `cold_start` 字段，**不动 gate.color/is_promotion_candidate/三态裁决**（R27 呈现层不动治理）。axis="track_record_length" 与过拟合门样本充分性轴区分。JSON-safe（inf/nan→null）。
- **对抗测试**：`test_run_verdict_cold_start.py` 9（短不渲染达标/N=1 DSR 不适用/never_significant/措辞守门/JSON-safe/集成）+ run_verdict_card 14 回归不破。
- **两轮独立复核全闭环（措辞守门是焦点）**：
  - ① **用户在 run_verdict.py 种 banned-words mutation**（sufficient 分支 note 塞「可信，已排除过拟合」）——测我的 R7 措辞守门。已撤回正确。教训同 dsr 那次：**让测试显式行权判别路径** → 强化禁词测试**显式覆盖全 4 状态分支（含 ok_sufficient 高危分支）+ 覆盖断言 + sentinel**，那条 mutation 落 ok_sufficient 分支必被抓。
  - ② **多透镜评审 confirmed（governance medium + correctness low）**：**我的禁词集 `("可信","安全","排除过拟合","通过")` 是 R7 红线不完整子集**——漏 **保证/可复现/组织独立**（姊妹测试 test_run_verdict_card 用完整 6 词；cold_start note 手拼绕过 `_verdict_note` 单一措辞源 → 此测试是唯一守门 → 子集=纸糊门，未来「保证显著」之类会溜）。→ 补全 R7 红线全集 + **加生产 runtime 防御守门**（`_BANNED_VERDICT_WORDS`，红线词出现即退安全兜底、生产期绝不输出禁词、不只靠测试）+ 单一源对齐测试（生产集 ⊇ 红线、测试集==生产集不漂）+ insufficient 分 n<3/σ≈0 措辞 + dsr_applicable 口径修。
- **验证**：**全量后端 1555 passed / 13 skipped / 0 failed**，基线 1547 未破。
- **交付**：上轮授权 push 的 6 切片已在 origin；本轮 loop 回「commit 不擅自 push」→ 本切片仅本地 commit、未 push。land main 待授权。下一步：继续合拢价值闭环或续方法学。

## 2026-06-25 · R27 冷启动 MinTRL（最小业绩期长度）+ PSR 反解命门 + 用户 mutation 抓门牙缺口（卡 6acbb499 · D-MINTRL-R27）

- **缘起**：autonomous-loop 下一切片。MinTRL 未建、R27=确认「冷启动 N=1 剔 DSR、用 PSR/MinTRL + 显式证据不足」→ 自取（扩展已建 PSR、低风险、直击「能信」+ 降门槛：诚实告诉新用户"业绩期太短、还需 N 期"）。
- **数学先行 + 并行思考**：落 `findings/dreaminate/mintrl-cold-start.md`（MinTRL=PSR 反解推导）；codex(xhigh) 确认是 PSR 精确反解 + 边界。
- **实现（扩展不替换）**：`dsr.py` 加 MinTRLResult + minimum_track_record_length，denom² 与 PSR 同项同钳 → **n=MinTRL 时 PSR≡confidence**（实证 8.88e-16 机器精度）。SR≤SR*→+∞、n<3/N=1→insufficient（R27 不假装算出）、冷启动 sufficient=n≥⌈MinTRL⌉。
- **对抗测试 + 命门**：`test_mintrl_cold_start.py` **10 passed** + 方法学不变量 **+2**（PSR↔MinTRL 反解 8.88e-16 / 单调边界）。
- **两轮独立复核抓到 2 类同型「门牙缺口」全补（这轮的核心收获）**：
  - ① **用户在 dsr.py 种 mutation `delta = sr_pp  # dropped sr_benchmark`**（RULES §2「种已知坏门必抓」）——精准戳中我盲区：**所有 MinTRL 测试都用 sr_benchmark=0**，此时 `sr_pp−0≡sr_pp`，mutation 完全隐形，**71 测全绿漏网**。诚实承认门牙缺口 → 补 sr_benchmark≠0 交叉校验（含正/负基准）→ 带 mutation 实测 **RED（max|Δz|=2.08≫1e-9）**、还原正确代码后绿 → 门有牙确认。
  - ② **多透镜评审 1 confirmed medium**：`test_mintrl_cold_start_sufficiency_verdict` 在 seed=5 落 status='never_significant'（负 edge）→ 核心 `assert not sufficient` 被 `if status==ok` 跳过 → 评审注入「`>=` 翻 `<=`」回归 71 测仍全绿、ok+short 的 sufficient 语义零覆盖。→ 改**确定性构造**（sr_pp=0.05 短→证据不足 / sr_pp=0.3 长→达标）+ **无条件 assert** 钉死两路。
  - **两条同属「测试过运气/未行权判别路径」**（与 §3 随机游走单种子、§5 NaN 同源教训）。低优：ceil 测试改纯矩确定性（去单种子重采样噪声）。
- **验收**：**全量后端 1547 passed / 13 skipped / 0 failed**，基线 1534 未破。mint **P2 卡 31289338**（冷启动 gate/UI 接 MinTRL：DSR=N/A + PSR + "需 N 期"渐进披露，R25/R27 呈现层）。
- **下一步**：land main 待用户授权；进下一切片（倾向开始合拢价值闭环/接 P2，已累计 7 张接线卡）。

## 2026-06-24 · R18 平方根市场冲击 回测成本项（size-aware）+ 容量交叉校验命门（卡 7179ba36 · D-SQRT-IMPACT-R18）

- **缘起**：autonomous-loop 下一切片。审计发现回测成本 `BacktestCostModel` slippage 是平 bps 常数、随单量不变 → 大单成本系统性低估、大资金回测过优（接近「未复权价喂回测」级 P&L 失真）→ 自取（这次外科、直接接进真回测非孤岛）。
- **数学先行**：落 `findings/dreaminate/sqrt-impact-backtest-cost.md`（平方根冲击律 Y·σ·(Q/ADV)^δ + 理论 Kyle-λ/propagator 凹增 + 容量交叉校验命门）。
- **实现（扩展不替换 + 向后兼容）**：`execution/impact.py` 单一公式源（δ=0.5 锁定 R18，与 §3 容量 strategy_capacity **同 sqrt-impact 物理**）；`BacktestCostModel` 加 impact_coef 默认 **0=关 → 冲击项恒 0、现有回测字节不变**；启用须 volume 列估 ADV、否则 init raise。
- **对抗测试 + 命门层**：`test_sqrt_impact_cost.py` **14 passed**（√标度/向后兼容字节不变/大单惩罚/无 volume raise/无效 ADV fail-fast/日内日 ADV/前视 warning/显式无泄露入口）+ 方法学不变量 **+3**（√标度精确/Y·σ 线性/**容量 C 处冲击==毛 alpha 交叉校验**）。
- **两轮独立复核全闭环**：① **Stop-hook codex 顾问 2 条 P2**——无效 ADV（volume 全 0/null/NaN）静默当 0 冲击=假绿灯（→成交时 fail-fast raise）/ 日内 1m·1h 数据 vol.mean 是每 bar 量非日 ADV、高估 √bars/日（→ts 为 datetime 时按日聚合 volume→真日 ADV）；② **多透镜评审 1 confirmed HIGH**——ADV/σ **全样本估计（含未来 bar）→ 启用 impact 的回测有前视泄露**（实测早期成交参与率被未来高量稀释 50x→冲击低估 ~7x），**命中 RULES.project §17 look-ahead 红线字面**，但评审精准裁定**非 stop-work、是 §7 拍板项**（理由：impact_coef 默认 0=关，active/默认路径无前视、字节不变；finding+docstring 已诚实标注「样本内估计未做滚动无泄露」+ P2 scope → 非 §3 假绿灯）。**按用户护栏「风险决策标清用户自负即放行、别把缓解当不交付硬条件」处置**：① default-off 路径前视红线守住 ② opt-in 自估路径 emit **代码级响亮 warning**（残余文档→代码可见、标用户自负）③ 提供**显式点位无泄露 ADV/σ 入口**（绕开自估、不触发 warning）④ mint **P2 卡 0f696e56**（滚动无泄露自估根治）。数学核心经 correctness/governance/CEO/eng 4 透镜独立复跑全真、对抗测试有真牙。
- **验收**：**全量后端 1534 passed / 0 真失败**（1 条预存异步 flake `test_eval_endpoint_after_training` 在 354s 重载全量下排队超时报 queued、**单独重跑 1 passed**、与本切片 execution 改动完全无关），基线 1518 未破、**默认关字节不变验证**。mint P2: 0f696e56(无泄露自估) + e2afc5c2(三档成本预设接 sqrt-impact + 成交报告成本归因拆字段)。
- **下一步**：land main 待用户授权；进下一切片。

## 2026-06-24 · §3 因子机构级生命周期度量（衰减/容量/因子族/拥挤）+ 命门（卡 b12de4f5 · D-LIFECYCLE-§3）

- **缘起**：autonomous-loop 下一切片。M11 确认「toy 五态机 / 机构级（衰减/拥挤/容量/因子族）未做」→ 自取 GOAL §3 度量层 4 件。
- **数学先行 + 并行思考**：落 `findings/dreaminate/factor-lifecycle-institutional.md`（AR(1) 半衰期 / sqrt-impact 容量闭式推导 / 因子族相关聚类 / 拥挤定性 + 命门）；codex(xhigh) 复核——加固 **ρ 绝不 clip** / **容量 τ³ 标度** / corr-vs-距离阈钉清 / 拥挤结构隔离。
- **实现（扩展不替换）**：`lifecycle_metrics.py`（lifecycle.py toy 五态机不动）；**n_eff 抽 `_cluster_labels` 单一聚类口径源**（因子族与 honest-N 同源、cross-check 守不漂）。**命门**：①半衰期绝不 clip ρ（ρ≥1→no_decay/ρ≤0→reversal/ρ̂>0.95 近单位根或 CI 跨0/1→unstable，机器门绝不对随机游走发 ok）②容量 δ=0.5 锁定不暴露入参（R18）、α≤0→no_edge、cost(C)≈α 自检、Y 占位诚实告警③因子族 n_families==n_eff.point 交叉校验 + 阈值不可调（防放水）④拥挤 CrowdingAdvisory 结构无任何减仓/动作字段（GOAL §3 禁自动减仓，R19）、missing≠crowding 0。
- **对抗测试 + 命门层**：`test_factor_lifecycle_metrics.py` **25 passed** + 方法学不变量 **+6**（半衰期解析点 ρ=0.5→h=1 / ρ 不 clip sentinel / 容量精确标度 + 净 alpha=0 自检 / 因子族==n_eff 交叉校验 / 拥挤无动作字段机器钉死）。
- **两轮独立复核全闭环（共 7 真问题）**：① **Stop-hook codex 顾问 3 条 P2**——零拥挤 falsy 陷阱（`0.0 or nan` 把有效零相关当 missing→修成 none）/ IC 跨 NaN 缺口拼接（先 arr[isfinite] 压扁 stitch→改原轴建对只丢跨缺口对）/ 因子族阈值 override 放水口（→锁定不暴露）；② **多透镜评审 4 confirmed**——随机游走 ρ=1 ~28% 种子假绿灯 + 测试单种子脆弱（→ρ̂>0.95 local-to-unity 降级 unstable，ρ=1 'ok' 占比降<10%、ρ=0.9 合法仍 100% ok；测试改多种子 sweep）/ 容量 δ 可改离 R18 锁定 0.5（自检循环抓不到→锁定不暴露）/ 容量 Y 占位无诚实告警（→告警）/ 拥挤等级阈值 override 放水（→锁定）+ 越界相关脏值（→insufficient）。数学核心经 correctness/governance/CEO/eng **4 透镜独立复跑全真**、对抗测试有真牙。low 清理：DRY 单一源 / 死 import·Literal / 4 dataclass to_dict / __init__ 导出。
- **验收**：**全量后端 1518 passed / 13 skipped / 0 failed**（实跑 223s，机器负载偏慢但 `--timeout=120` 单测超时无触发=未卡，非 hang），基线 1487 未破。mint **P2 卡 aa13c3b0**（度量接 lifecycle 退役/sizing/组合独立性生产路径）。
- **下一步**：land main 待用户授权；进下一切片。

## 2026-06-24 · R4 CPCV（Combinatorial Purged CV）多路径回测 + 组合学/防泄露命门（卡 41ea6e35 · D-CPCV-R4）

- **缘起**：autonomous-loop 下一切片。确认 GOAL §4「CPCV 双轨 walk-forward（R4）」中 CPCV 多路径**未建**（`models/purged_cv.py` 只有单路径 purged k-fold；pbo.py 的 cscv_pbo 是 PBO 用对称 CV ≠ CPCV 路径生成）→ 自取扩展。数学最密 + correctness-critical（防泄露 + 多路径分布喂已建 PBO/DSR 命门）。
- **数学先行 + 并行思考**：落 `findings/dreaminate/cpcv.md`（φ=C(N−1,k−1)=k·C(N,k)/N 双计数证明 + golden path_matrix N=4,k=2 + 命门）；codex(xhigh) 复核——确认 φ 恒等/路径重建算法，加固三处：**purge 必须逐 test group 段判**（非全局 min..max，否则误删非连续 test group 中间合法 train）、**PBO 路径≠策略红线**（单策略 φ 路径绝不冒充策略数）、embargo 语义（AFML test 后 vs purged_kfold 两侧）。
- **实现（扩展不替换）**：`models/cpcv.py` 复用 purged_cv 的 t1-overlap purge 口径；C(N,k) 爆炸预检 raise **绝不静默采样**（否则 φ 公式失效）；多路径 Sharpe 分布给保守分位 q05/min。**命门钉死**：①φ 路径≠φ 策略（不产 PBO，测试守）②饿死/未覆盖路径记 NaN 剔除 + n_paths_dropped 可见、**绝不伪造 0.0 污染保守分位**③insufficient dict 形状对称④R4=B「真实市场未确立」`CPCV_REALWORLD_SUPERIORITY_ESTABLISHED=False` 常量机器钉死（双轨不自动判赢）。
- **对抗测试 + 命门层**：`test_cpcv.py` **22 passed**（golden path_matrix / 覆盖来源==path_matrix / purge sentinel / embargo AFML 单侧 / 饿死路径不假 0 / PBO 红线 / 爆炸 / 边界）+ 方法学不变量 **+4**（φ 恒等 N=3..12 / occurrence 双射 / 覆盖来源 / 逐段 purge sentinel）。
- **多透镜评审（autoplan 等价 4 透镜 + 对抗复核，14 agents）**：数学核心经 correctness/governance/CEO/eng **独立复跑全真**、对抗测试有真牙（sentinel 证伪变体确变红）。修 9 confirmed：**medium 命门后门（饿死路径默认 Sharpe 静默假 0.0 污染 q05/min）** + insufficient dict 形状不对称 + 路径覆盖测试缺来源区分牙 + embargo 单侧方向零测试 + low 清理（build_path_matrix 爆炸护栏/负 embargo 拒/死 import/per_combo 长度校验/__init__ 再导出/caveat 机器钉死/文档「生成器→list」）。
- **实证亮点**：φ 恒等全对（N=3..12）；golden path_matrix 精确匹配 codex；**purge 0 泄露 vs 不 purge 120**；饿死路径记 NaN 不污染 min（修后正收益策略 min>0）。
- **验收**：**全量后端 1487 passed / 13 skipped / 0 failed**，基线 1478 未破。mint **P2 卡 861182e6**（接 promote/overfit gate + cv_scheme 双轨 report，应 CEO「价值闭环未合拢——CPCV 纯孤岛」）。
- **下一步**：land main 待用户授权；进下一切片。

## 2026-06-24 · R23 不确定性预测区间（split conformal/CQR/ACI）+ abstain + 覆盖定理命门（卡 69e1cb16 · D-CONFORMAL-R23）

- **缘起**：autonomous-loop 下一切片。确认 GOAL §4「conformal/CQR/ACI 区间 + abstain（R23）」**完全未实现**（eval/ 无不确定性模块），最高杠杆 + 数学最密 + 直击「能信」（诚实不确定性而非假自信）+ 非凭据门 → 自取。
- **数学先行 + 并行思考**：落 `findings/dreaminate/conformal-intervals.md`（split conformal/CQR/ACI 公式 + 覆盖定理 + 可证伪不变量 + R23 不锁 α 治理）；codex(xhigh) 独立复核，**修正三处**：ACI 长程界应 (max{α₁,1−α₁}+γ)/(Tγ) 非 (α₁+γ)/(Tγ)；CQR Q̂ 可负（合法收窄）+ 端点交叉 abstain 绝不交换；手写秩分位（非 np.quantile 默认插值）。
- **实现（扩展不替换）**：新建 `eval/conformal.py`——**模型无关**（接残差/分位预测、不接模型本体，合信号契约解耦）；秩 k=⌈(n+1)(1−α)⌉ 含 +1 校正、k>n→abstain（n<⌈1/α⌉−1）；ACI raw α_t 递推 + clipped-level 工程变体。**命门钉死**：①不锁 α（R23·全调用方传参、内部不硬编，仅 docstring/gamma 出现 0.x 字面量）②abstain 三态不假绿灯 + `__post_init__` 构造期拒矛盾态 + **非 1D 输入亦 abstain**（防畸形数组区间逃网）③exchangeability 诚实披露、ACI 工程变体实测收敛不空引论文界。
- **对抗测试 + 命门**：`test_conformal_intervals.py` **25 passed**（abstain/CQR符号/Q̂可负/端点交叉/ACI方向/漂移长程覆盖/非1D/构造期拒态）+ 方法学不变量 **+9**（分布无关覆盖 ≥1−α、**+1 校正 sentinel 门有牙**、ACI 漂移长程覆盖收敛、单调嵌套、CQR 覆盖、ACI 递推恒等、不锁 α）。
- **实证亮点**：split 覆盖 normal/重尾t/偏态/异方差**全≈0.90 分布无关**；**ACI 漂移下长程覆盖 0.901 vs 固定 split 0.542**（漂移崩）；CQR oracle 过窄→Q̂>0 放大、过宽→Q̂<0 收窄。
- **多透镜评审（autoplan 等价 4 透镜 + 对抗复核）**：confirmed_real 空——数学经 CEO/governance **独立数值复验**全真（覆盖落理论带、abstain 阈跨 α 精确含非整 α、CQR validity 不依赖分位质量、四命门达标）。correctness 透镜点出 1 条 medium：**非 1D 输入绕过 abstain 网产畸形数组区间** → 已修（1D 守门）+ 低优清理全做（CQR max_width 对称旋钮 / `__post_init__` 拒矛盾态 / `to_dict` / 披露面收窄到已实现 / `_min_calib_for` 单一源 / docstring 措辞）。
- **验收**：**全量后端 1460 passed / 13 skipped / 0 failed**，基线 1453 未破。mint **P2 卡 92a2182f**（消费侧接线：模型台/信号层预测附校准区间 + abstain UI 渐进披露，应 CEO「未接线另一半当 live 债追」）。
- **下一步**：land main 待用户授权（不擅自 push/land）；进下一切片。

## 2026-06-24 · §5 生产期漂移检测器（rolling-PSR/CUSUM/Page-Hinkley/PSI）+ 理论不变量命门（卡 d718d5c5 · D-DRIFT-§5）

- **缘起**：autonomous-loop（用户授权自主迭代，北极星#1 数学贯穿/#2 理论先证明/#4 监管对齐命门）。所有卡 done、pool 空 → 自取 state.md 点名的「新生残余：§5 漂移检测器」。现有 monitor 只有粗粒度成本漂移阈值，缺 GOAL §5 的统计漂移检测器。
- **数学先行 + 并行双脑**：落 `findings/dreaminate/drift-detectors.md`（4 检测器公式+推导+治理 voice）；deep-opus‖codex 三脑独立复核——**deep-opus 实证抓到教科书 Page-Hinkley 全局 running-mean 的 √t 假告警致命陷阱**（平稳噪声 FPR→1）→ 改 frozen-baseline 变体 + 配 sentinel 证明弃用对（单脑会照教科书埋雷）。
- **实现（扩展不替换 + 命门钉死）**：`dsr.py` +`probabilistic_sharpe_ratio`（与已变异验证的 DSR V-path 互为 1e-12 交叉校验锚，实测偏差 0.0）；新建 `monitor/drift.py`（4 检测器 + 三态 ok/breach/insufficient_evidence + 绩效轴/特征轴**类型隔离**）；`monitor_tick` additive `perf_drift`。**三层钉死**：①rolling-PSR 签名不暴露 n_trials/var_sr_hat（杜绝 DSR 通缩走私进 live 退役，违 M-AUTHORITY/GOAL §5）②PSI=FeatureDriftDiagnosis 无 breach/无 to_lifecycle_observation/类型层喂不进 monitor_tick + 运行期 axis 防伪 ③CUSUM/PH 冻结基准（绝不用监控窗自身均值，温水煮青蛙）。
- **多透镜评审（autoplan 等价：correctness/governance/CEO/eng 并行 + 对抗复核）抓真 bug 全修**：**5 条 confirmed——4 条 NaN 静默假绿灯（high，正中本模块自钉「不假绿灯」命门：喂数缺口插 NaN→NaN<floor 恒 False 绕过守门→主告警读绿=对真钱致命静默）** + 1 条 CEO 阈值代价诚实披露（PSR_FLOOR=0.90 偏激进，已标注）。修法：`_all_finite` 守门 4 检测器全判 insufficient + 对抗测试钉死；eng 4 清理（死常量→_SIGMA_FLOOR、冗余 re-export、饱和值/全零 docstring）全做。
- **验收**：`test_drift_detectors.py` **31 passed**（温水煮青蛙/方向/PH sentinel/PSI 范畴红线/NaN 假绿灯）+ `test_methodology_invariants.py` **19→38 passed**（+19 理论不变量：PSR↔DSR 恒等含中段判别力、PSI 对称/非负/置换、CUSUM 平移/尺度等变 + sentinel 门有牙、PH FPR 受控）。**全量后端 1426 passed / 13 skipped / 0 failed（167s），基线 1357 未破**。
- **诚实残余（非假绿）**：冻结基准 μ0/σ0 跨重启持久化依赖上游观测管道（建议 mint 后续卡）；PSR 自相关高估有效 n（docstring 披露）；阈值标定属用户方法学旋钮（代价已诚实标）。
- **下一步**：land main 待用户授权（不擅自 commit/push）；进下一切片。

## 2026-06-24 · 交付门收尾波「全量落地 web」全完成（4 P2 卡清零 + glossary 27 + rag 回归修 + land main）

- **缘起**：用户 /autoplan「全量落地 web」→ 3 问全选推荐档（全量范围 / 授权 land delivery-slice / 凭据门码路+文档待验收）。理解 workflow 摸清：项目 ~95% 已绿，真缺口=整波 32 commit 未 land main + 5 张卡（e1a98c41 已做未归档 + 4 待做）。worktree `deliver-final`（基 delivery-slice）。
- **4 张 P2 卡（deep-opus 各实现，leader 复核真绿 + 变异自检）**：ba59fb7b 组合 promote 生产端点 record=True 真记 honest-N（`4082d5d`，+8 测）/ de764e1c 监控生产调度 strict scheduler+观测管道（`b871c92`，+10 测，范畴红线钉死 monitor_tick 不接 verdict，§5 漂移检测器诚实标残余未投机造桩）/ 64717fe6 paper 真 BTC 样本回放 entry_price 反推防 P&L 失真（`45b0f19`，+7 测）/ a367bfc8 testnet 真喂码路 fail-open 留痕 key 不进 LLM（`2fd185f`，+20 测，真连接待用户 key）+ e1a98c41 vision bug 落档（ac72b81 此前已修）。
- **glossary 27 词条**：workflow 27 写手并行→6 批对抗验文献真实性→修 6 处（2 critical：var_cvar VaR 公式杂散负号、funding_rate 杜撰文献换真 arXiv:2310.11771）（`2ea71b7`）。validate_glossary PASS count=30。
- **回归自查（不假绿）**：glossary 补全改了 RAG 检索结果→test_retrieve_glossary_hit 转红（base 0 failed=我引入）。二分定位坐实（glossary 还原 base→测试转绿），修 rag 加别名整体点名 boost（`d39d606`）+ 钉回归门；未让卡2 的「预存」误判蒙混。
- **验收**：**全量后端 1357 passed / 13 skipped / 0 failed（实跑 189s）**+ 前端 **vitest 280 + tsc 0 + build 绿**（delivery-slice worktree 验，前端源同 deliver-final）+ validate PASS。
- **下一步**：land delivery-slice（含本波收尾）→ main（用户授权）。凭据门 §9 尾项码路+文档就绪待用户验收；新生残余建议 mint 卡（生产周度 IC 重算、§5 漂移检测器、观测持久化）。

## 2026-06-23 · code-review 修复批（交付门波 land 后 xhigh 审出 15 缺陷全修）· 6 worker 并行 + land main

- **缘起**：交付门波 land main 后跑 workflow code-review(xhigh)：50 候选→26 验证→**15 报告**。讽刺的是「修 §3 假绿灯」的波自己留了新假绿灯 + 默认路径断 + leader relabel 偷懒。用户「全部要修」。
- **7 单元（文件 disjoint）6 worker 并行各 PR**：FU1 main.py 注册诚实化（#10·**§5 治理**：H3 market 派生不默认 equity_cn 伪造 600519 / H4 注册失败显 error 非静默 200 / M3 二次注册 reconcile / M6 relabel 漏 3 注释 / M7 prime 惰性化；worker 自身 code-review 还抓出 A股 spot 误判成 crypto 绕 live-forbidden 并修）/ FU2 synth 诚实化（#7·M1 组装输入落 metadata+诚实 note 不静默丢 / M8 LLM market 校验）/ FU3 裁决卡 null（#8·H2 pbo/dsr null→N/A 不假绿）/ FU4 Agent 台 live（#9·H1-fe LIVE 无 run_id 不退 mock 绿、显诚实态 / M5 不丢上下文）/ FU5 paper desk 并发（#11·M4 prime 前 stop scheduler join 防 equity_log 撕裂 / perf mtm_count）/ FU6+7（#6·M2 goal_id 纳 benchmark/cost/window 防撞覆盖 / 删 paperApi 死 export）。
- **leader 整合**：6 PR merge（文件 disjoint，仅 FU1/FU5 共改 test_paper_desk_api 冲突→两组回归测试都留）。
- **§5 治理终审**：A股恒拒 live（attempt_live_order 对 equity_cn 恒 AShareLiveForbidden）、INV-5、止模拟盘、market 派生不伪造标的——全不破，且更准。
- **验收**：**全量后端 1311 passed / 13 skipped**（基线 1292 + ~19 新回归种坏门）+ 前端 **280 passed + tsc/build 绿** + e2e/治理测试全过。每 finding 配回归测试（修前红/修后绿对照验证）。
- **下一步**：land main（用户授权全修+land）。
## 2026-06-27 · Agent/API/IDE QRO producer compiler coverage（4056a87f）

- **取前沿**：StrategyGoal、IDE save/run/promote/AI complete 已写业务 QRO/Graph，但未自动进入 Governed Compiler / GOAL entrypoint coverage。新卡把这些高频入口从 QRO/Graph 推到 compiler IR/pass/coverage。
- **runtime/API**：新增 `_compile_entrypoint_qro`；Agent Shell `strategy_goal.create` 与 direct `POST /api/strategy_goals` 改走 `_create_strategy_goal_with_compiler_coverage`；IDE save/run/promote/AI complete QRO helper 写 Graph 后自动生成 compiler refs 和 entrypoint coverage refs。
- **坏门**：direct API coverage 绑定 `api:strategy_goals`；Agent Shell coverage 绑定 `agent_shell:strategy_goal.create`；IDE coverage 绑定 `ide:strategy.save` / `ide:strategy.run` / `ide:run.promote` / `ide:ai_complete`；compiler audit 不复制 prompt/code/description/stdout/stderr/result/LLM output/secret。
- **测试**：`test_ds2_strategy_goal_persist.py` + `test_agent_runtime_research_graph.py` + `test_strategy_console_s2.py` **58 passed / 2 warnings**；`compileall app/backend/app` **PASS**。
- **落档**：新增 done 卡 `4056a87f`。边界：这是 Agent/API/IDE 已有 QRO producer 的 compiler coverage 自动化，不是完整 compiler、全入口 producer、CI、线上或用户验收。

## 2026-06-27 · Compiler artifact Mathematical Spine hard reference gate（0b3f6a91）

- **取前沿**：`ecc6b957` 已有 MathematicalSpineChain registry/API，`41b7c9e2` 已让 compiler artifact 写 entrypoint coverage；artifact manifest 仍未强制引用已登记 Mathematical Spine chain。新卡补 artifact-level hard ref gate。
- **runtime/API**：`CompilerArtifactRecord` 新增 `mathematical_spine_chain_refs`；`POST /api/research-os/compiler/artifacts` 解析/summary/response 暴露该字段，写 artifact 前确认每个 chain ref 已在 `MATHEMATICAL_SPINE_CHAIN_REGISTRY` 登记。
- **对抗门**：缺 `mathematical_spine_chain_refs` 被 compiler validator 拒绝；unknown chain ref 422 且不写 artifact、不新增 coverage；artifact replay/summary/coverage lifecycle refs 保留 chain ref。
- **测试**：`tests/test_governed_compiler.py` **20 passed / 2 warnings**；goal/compiler scoped **33 passed / 2 warnings**；goal/compiler/spine/methodology/trust adjacent **72 passed / 2 warnings**。
- **落档**：新增 done 卡 `0b3f6a91`。边界：这是 compiler artifact 对 Mathematical Spine chain 的硬引用门，不是所有 producer 自动写 chain、完整 compiler/codegen、CI、线上或用户验收。

## 2026-06-27 · Compiler artifact entrypoint coverage producer（41b7c9e2）

- **取前沿**：`173405ef` 已让 `compile_qro` 和 direct compiler pass 写 entrypoint coverage；compiler artifact endpoint 仍只写 artifact audit。新卡把 artifact manifest 成功路径接到 refs-only entrypoint coverage。
- **runtime/API**：新增 `_goal_entrypoint_coverage_from_compiler_artifact()`；`POST /api/research-os/compiler/artifacts` 现在先验证 artifact 和 coverage candidate，再写 artifact JSONL 与 coverage JSONL，响应返回 `entrypoint_coverage_ref`。
- **对抗门**：artifact coverage 绑定已记录 IR/pass、QRO refs、Research Graph command refs、evidence/validation/permission/replay refs；fake codegen/executable artifact claim 不新增 artifact coverage；历史 silent mock IR 进入 artifact endpoint 时 422，且不写 artifact/coverage partial record。
- **测试**：goal/compiler scoped **32 passed / 2 warnings**；goal/compiler/spine/methodology/trust adjacent **71 passed / 2 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `41b7c9e2`。边界：这是 artifact manifest coverage producer，不是 executable compiler、strategy code generator、scheduler wiring、CI、线上或用户验收。

## 2026-06-27 · Weekly monitor execution reconciliation action producer wiring（a91b0c63）

- **取前沿**：`d4c9a2f0` 已有 refs-only reconciliation action producer API；§12 仍缺接入现有 production weekly monitor tick。新 mint `a91b0c63` 把 producer 接到 monitor endpoint 和 DAG result recorder。
- **runtime/API**：抽出 `_run_pending_execution_reconciliation_actions()`；`/api/monitor/weekly_tick` 和 `_record_weekly_monitor_qro_from_scheduler()` 在记录 monitor QRO 后触发 action producer，响应/任务结果带 `execution_reconciliation_action_producer` 摘要。
- **坏门**：pending reconciliation 首次 tick 创建 action；重复 tick 幂等 skip；测试把 execution registries patch 到 tmp_path，避免写真实 `DATA_ROOT`。
- **测试**：monitor+execution scoped **33 passed / 2 warnings**；execution/monitor/portfolio/factor/realtime safety adjacent scoped **80 passed / 2 warnings**；expanded Research OS/coverage/standards/security scoped **147 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 165）。
- **落档**：新增 done 卡 `a91b0c63`。边界：这是本地 weekly monitor tick / DAG result_recorder 接线，不是 order emission、live trading、broker connector、venue API 连通、自动 remediation 或线上长期 scheduler 运行证明。

## 2026-06-27 · Execution reconciliation action producer API（d4c9a2f0）

- **取前沿**：`6e4a9b21` 已有 reconciliation action record/API/QRO；§12 仍缺把 pending reconciliations 批量转 action 的 producer。新 mint `d4c9a2f0` 补 refs-only action producer API。
- **runtime/API**：新增 `/api/research-os/execution/reconciliation_actions/run_pending`，扫描 `EXECUTION_RECONCILIATIONS` 中 `action_required=true` 的记录，按状态映射默认 action kind，写 `DATA_ROOT/audit/execution_reconciliation_actions.jsonl` + `QROType.EXECUTION_POLICY`。
- **坏门**：`needs_reconcile` -> `request_missing_reconcile`；terminal conflict / venue mismatch -> `escalate_manual_review`；其他 pending -> `investigate`；已有 open/acknowledged action 按 `(reconciliation_ref, action_kind)` 幂等 skip。
- **测试**：`test_execution_boundary_contract.py` **26 passed / 2 warnings**；execution/portfolio/factor/realtime safety adjacent scoped **73 passed / 2 warnings**；expanded Research OS/coverage/standards/security scoped **140 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 164）。
- **落档**：新增 done 卡 `d4c9a2f0`。边界：这是 API-triggered reconciliation action producer，不是 order emission、live trading、broker connector、venue API 连通、自动 remediation 或部署级长期 scheduler。

## 2026-06-27 · Execution reconciliation action QRO API（6e4a9b21）

- **取前沿**：`0c4d71a9` 已能批量产 reconciliation records/QRO；§12 仍缺把 `action_required=true` 对账结果进入治理动作队列。新 mint `6e4a9b21` 补 refs-only reconciliation action record/API/QRO。
- **runtime/API**：新增 `ExecutionReconciliationActionRecord`、`PersistentExecutionReconciliationActionRegistry`、`/api/research-os/execution/reconciliation_actions` record/summary API；成功路径写 `DATA_ROOT/audit/execution_reconciliation_actions.jsonl` 和 `QROType.EXECUTION_POLICY`。
- **坏门**：只有 action_required reconciliation 可创建 action；`reconciled/action_required=false` 创建 action 会 422 且不写 JSONL/Graph；`halt_runtime` 必须有 `halt_plan_ref`，`waive_with_evidence` 必须有 `waiver_ref`。
- **测试**：`test_execution_boundary_contract.py` **25 passed / 2 warnings**；execution/portfolio/factor/realtime safety adjacent scoped **72 passed / 2 warnings**；expanded Research OS/coverage/standards/security scoped **139 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 163）。
- **落档**：新增 done 卡 `6e4a9b21`。边界：这是 execution reconciliation action record/API/QRO，不是 order emission、live trading、broker connector、venue API 连通、自动 remediation 或部署级长期 scheduler。

## 2026-06-27 · Execution reconciliation batch worker API（0c4d71a9）

- **取前沿**：`4a7d2e90` 已有单笔 reconciliation record/API/QRO；§12 仍缺批量处理已记录 venue events 的 pending worker。新 mint `0c4d71a9` 补 refs-only batch worker API。
- **runtime/API**：新增 `/api/research-os/execution/reconciliations/run_pending`，按 `(order_intent_ref, runtime_promotion_ref, venue_order_ref)` 分组扫描 `EXECUTION_VENUE_EVENTS`，生成 `ExecutionReconciliationRecord` 并写 `DATA_ROOT/audit/execution_reconciliations.jsonl` + `QROType.EXECUTION_POLICY`。
- **坏门**：只处理已落库 refs；unknown upstream 组 skip；重复 run 按 event refs 幂等 skip；响应固定 `record_only=true`、`api_place_order_called=false`、`api_venue_call_called=false`。
- **测试**：`test_execution_boundary_contract.py` **23 passed / 2 warnings**；execution/portfolio/factor/realtime safety adjacent scoped **70 passed / 2 warnings**；expanded Research OS/coverage/standards/security scoped **137 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 162）。
- **落档**：新增 done 卡 `0c4d71a9`。边界：这是 execution reconciliation batch worker/API/QRO，不是 order emission、live trading、broker connector、venue API 连通或部署级长期 scheduler。

## 2026-06-27 · Execution reconciliation worker QRO API（4a7d2e90）

- **取前沿**：`3b6e9c12` 已有 venue event audit/QRO，但缺把 fill/ack/reconciled 事件汇总成 execution reconciliation 状态的 worker。新 mint `4a7d2e90` 补 refs-only reconciliation worker/API。
- **runtime/API**：新增 `ExecutionReconciliationRecord`、`PersistentExecutionReconciliationRegistry`、`reconcile_execution_venue_events()`、`/api/research-os/execution/reconciliations` record/summary API；成功路径写 `DATA_ROOT/audit/execution_reconciliations.jsonl` 和 `QROType.EXECUTION_POLICY`。
- **坏门**：filled + reconciled -> `reconciled/action_required=false`；filled 但缺 reconciled -> `needs_reconcile/action_required=true`，不假绿；unknown order intent/runtime promotion 422 且不写 JSONL/Graph。
- **测试**：`test_execution_boundary_contract.py` **22 passed / 2 warnings**；execution/portfolio/factor/realtime safety adjacent scoped **69 passed / 2 warnings**；expanded Research OS/coverage/standards/security scoped **136 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 161）。
- **落档**：新增 done 卡 `4a7d2e90`。边界：这是 execution reconciliation record/API/QRO，不是 order emission、live trading、broker connector、venue API 连通或后台调度循环。

## 2026-06-27 · Execution venue event audit QRO API（3b6e9c12）

- **取前沿**：`0d9a6e42` 已让 runtime promotion 写 registry/QRO；§12 仍缺 venue ack/fill/reconcile 证据面。新 mint `3b6e9c12` 补 refs-only venue event audit，不在 main 新增 `place_order`。
- **runtime/API**：新增 `ExecutionVenueEventRecord`、`PersistentExecutionVenueEventRegistry`、`/api/research-os/execution/venue_events` record/summary API；成功路径写 `DATA_ROOT/audit/execution_venue_events.jsonl` 和 `QROType.EXECUTION_POLICY`。
- **坏门**：fill event 缺 fill/quantity/price refs 422；unknown order intent/runtime promotion refs 422；payload 带 raw_event/raw_ack/raw_fill/raw_execution_report/filled_qty/fill_price/commission/raw_order 等 raw material 422；失败不写 JSONL/Graph。
- **测试**：`test_execution_boundary_contract.py` **19 passed / 2 warnings**；execution/portfolio/factor/realtime safety adjacent scoped **66 passed / 2 warnings**；expanded Research OS/coverage/standards/security scoped **133 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 160）。
- **落档**：新增 done 卡 `3b6e9c12`。边界：这是 venue event audit record/API/QRO，不是 order emission、live trading、broker connector、venue API 连通或 fill reconciliation worker。

## 2026-06-27 · Runtime promotion registry QRO API（0d9a6e42）

- **取前沿**：`8f2d4b0c` 已让 order intent 成功路径写 ExecutionPolicy QRO；§12 runtime promotion 仍只有纯 validator，没有可 replay 的 record/API。新 mint `0d9a6e42` 补 runtime promotion append-only registry + QRO write-through。
- **runtime/API**：新增 `RuntimePromotionRecord`、`PersistentRuntimePromotionRegistry`、`/api/research-os/execution/runtime_promotions` record/summary API；成功路径写 `DATA_ROOT/audit/runtime_promotions.jsonl` 和 `QROType.EXECUTION_POLICY`。
- **坏门**：live ladder jump、A股 live、缺 approval/permission/OrderGuard/idempotency/audit/kill-switch/SecretRef/responsibility refs、silent mock profile、waiver execution invariant 均沿用 `validate_runtime_promotion()` fail-closed；失败不写 JSONL、不写 Graph。
- **测试**：`test_execution_boundary_contract.py` **15 passed / 2 warnings**；execution/portfolio/factor/realtime safety adjacent scoped **62 passed / 2 warnings**；expanded Research OS/coverage/standards/security scoped **129 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 159）。
- **落档**：新增 done 卡 `0d9a6e42`。边界：这是 runtime promotion record/API/QRO，不是 order emission、live trading、broker connector、venue ack/fill/reconcile 或资金执行。

## 2026-06-27 · Execution order intent QRO write-through（8f2d4b0c）

- **取前沿**：`5e1d0a77` 已有 typed order intent registry/API，但成功路径尚未写入 QRO/Research Graph。新 mint `8f2d4b0c` 把 order intent 成功记录同步成 `QROType.EXECUTION_POLICY` 和 `upsert_qro` command。
- **Graph 接线**：`/api/research-os/execution/order_intents` 成功后返回 `qro_id` / `research_graph_command_id`；QRO 带 market/universe/horizon/frequency/lineage/implementation_hash，output contract 保留 execution/risk/venue/permission/guard/audit/kill-switch/SecretRef/responsibility refs 和 `place_order_called=false`。
- **坏门**：raw quantity/price/notional/secret/raw_order 仍在写入前 422；QRO output contract 不复制 raw order material。
- **测试**：`test_execution_boundary_contract.py` **12 passed / 2 warnings**；execution/portfolio/factor/realtime safety adjacent scoped **59 passed / 2 warnings**；expanded Research OS/coverage/standards/security scoped **126 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 158）。
- **落档**：新增 done 卡 `8f2d4b0c`。边界：这是 order intent QRO write-through，不是 order emission、live trading、broker connector、venue ack/fill 或资金执行。

## 2026-06-27 · StrategyConsole Research Graph Ghost and Auto intent ref write-back（aa74a817）

- **取前沿**：`3a17e940` 已有 connect-intent ref/hash 写回；Ghost/Auto 在真实 projection 下仍只有“不改图”提示。新 mint `aa74a817`（review_status=1）把 Ghost/Auto 记录进 QRO intent 账。
- **前端接线**：StrategyConsole 真实 projection 下，Ghost accept 写 `output_contract.canvas_ghost_ref/hash`，Auto send 写 `output_contract.canvas_auto_ref/hash`；两条路径都只发 ref/hash、canonical/audit/evidence refs，成功后重拉 projection，不应用本地 mock patch。
- **后端验收**：补 Ghost/Auto patch-intent asset mutation 测试，确认 QRO version 递增、evidence refs 记录、projection audit 不泄露 ghost/auto ref/hash。
- **验收**：StrategyConsole scoped → 1 file / 36 passed；Research Graph scoped → 18 passed / 2 warnings；Graph/Compiler/StrategyConsole/standards adjacent scoped → 69 passed / 2 warnings；frontend full → 26 files / 299 passed；frontend build → `tsc && vite build` PASS（既有 chunk size warning）。
- **边界**：这是 Ghost/Auto intent ref/hash write-back，不是真实 patch application、完整 agent patch lifecycle、完整 graph database、完整 compiler pass、CI 或线上部署证明。

## 2026-06-27 · StrategyConsole Research Graph connect intent ref write-back（3a17e940）

- **取前沿**：`fbab2819` 已有 delete-intent ref/hash 写回；GraphCanvas 自由建边仍未接 canonical QRO。新 mint `3a17e940`（review_status=1）只做 connect-intent ref/hash 写回，不声称真实新增 Graph edge。
- **前端接线**：StrategyConsole 真实 projection 下 `onConnect` 改成输出端口→输入端口两步 intent；调用 `/api/research-os/graph/canvas_asset_mutations` 写 `output_contract.canvas_connect_ref/hash`，只发 ref/hash、canonical/audit/evidence refs，成功后重拉 projection。
- **后端验收**：补 `canvas_connect_ref/hash` asset mutation 测试，确认 QRO version +1、evidence refs 记录、projection audit 不泄露 connect ref/hash。
- **验收**：StrategyConsole scoped → 1 file / 34 passed；Research Graph scoped → 17 passed / 2 warnings；Graph/Compiler/StrategyConsole/standards adjacent scoped → 68 passed / 2 warnings；frontend full → 26 files / 297 passed；frontend build → `tsc && vite build` PASS（既有 chunk size warning）。
- **边界**：这是 connect-intent ref/hash write-back，不是真实 Graph edge 创建、完整连线预览、Ghost/Auto 写回、完整 graph database、完整 compiler pass、CI 或线上部署证明。

## 2026-06-27 · StrategyConsole Research Graph delete intent ref write-back（fbab2819）

- **取前沿**：`a63af9d7` 已有 QRO-node parameter ref/hash 写回；GraphCanvas 删除仍未接 canonical QRO。新 mint `fbab2819`（review_status=1）只做 delete-intent ref/hash 写回，不声称真实删除 QRO/Graph 拓扑。
- **前端接线**：StrategyConsole 真实 projection 下，QRO 节点 Delete/Backspace 调用 `/api/research-os/graph/canvas_asset_mutations` 写 `output_contract.canvas_delete_ref/hash`；edge inspector 增加 `记录删除`，同样只发 ref/hash、canonical/audit/evidence refs，成功后重拉 projection。
- **后端验收**：补 `canvas_delete_ref/hash` asset mutation 测试，确认 QRO version +1、evidence refs 记录、projection audit 不泄露 delete ref/hash。
- **验收**：StrategyConsole scoped → 1 file / 33 passed；Research Graph scoped → 16 passed / 2 warnings；Graph/Compiler/StrategyConsole/standards adjacent scoped → 67 passed / 2 warnings；frontend full → 26 files / 296 passed；frontend build → `tsc && vite build` PASS（既有 chunk size warning）。
- **边界**：这是 delete-intent ref/hash write-back，不是真实 QRO tombstone、Graph 拓扑删除、自由建边、Ghost/Auto 写回、完整 graph database、完整 compiler pass、CI 或线上部署证明。

## 2026-06-27 · StrategyConsole Research Graph parameter ref write-back（a63af9d7）

- **取前沿**：`ddec60c2` 已有 projection edge relation ref/hash 写回；GraphCanvas parameter/Ghost/Auto 仍是画布真实性残余。新 mint `a63af9d7`（review_status=1）只做 QRO-node parameter ref/hash 写回。
- **前端接线**：StrategyConsole 真实 QRO 节点 inspector 增加 `记录参数` action；调用 `/api/research-os/graph/canvas_asset_mutations` 写 `output_contract.canvas_param_ref/hash`，带 canonical/audit/evidence refs，成功后重拉 `/api/research-os/graph/canvas_projection`。
- **后端验收**：补 `canvas_param_ref/hash` asset mutation 测试，确认 QRO version +1、evidence refs 记录、projection audit 不泄露 parameter ref/hash。
- **验收**：StrategyConsole scoped → 1 file / 31 passed；Research Graph scoped → 15 passed / 2 warnings；Graph/Compiler/StrategyConsole/standards adjacent scoped → 66 passed / 2 warnings；frontend full → 26 files / 294 passed；frontend build → `tsc && vite build` PASS（既有 chunk size warning）。
- **边界**：这是 QRO-node parameter ref/hash write-back，不是自由参数编辑、Ghost/Auto 写回、删除、自由建边、完整 graph database、完整 compiler pass、CI 或线上部署证明。

## 2026-06-27 · StrategyConsole QRO node drag canonical layout hash（74632fdf）

- **取前沿**：`93f4027d` 已有 QRO-node inspector canonical edit；GraphCanvas 手势仍未写回。新 mint `74632fdf`（review_status=1）把真实 Research Graph QRO 节点拖拽接到 `canvas_asset_mutations`。
- **前端手势接线**：StrategyConsole 在 Research Graph projection active 时，只允许 QRO 节点 head drag 进入写回；drag end 计算 `hash_canvas_layout_*`，POST `output_contract.canvas_layout_hash` / `operation=set_hash`，再重拉 `/canvas_projection`。command 节点、非 QRO 节点、删除、连线、参数、Ghost、Auto 仍走只读门。
- **后端验收**：补 `set_hash` asset mutation 测试，不带 `value_ref` 也能 upsert 同一 QRO v+1，projection audit 不泄露 hash raw value。
- **验收**：Graph/Desk scoped → 15 passed / 2 warnings；Graph/Desk/Compiler/StrategyConsole scoped → 59 passed / 2 warnings；StrategyConsole frontend scoped → 2 files / 41 passed；frontend build → `tsc && vite build` PASS（既有 chunk size warning）；frontend full → 26 files / 287 tests passed；backend full → 1560 passed / 13 skipped / 283 warnings。
- **边界**：这是 QRO 节点布局 digest 写回，不是精确坐标 server replay、完整 GraphCanvas 手势 write-back、完整 graph database 或 strategy codegen。

## 2026-06-27 · Research Graph canonical canvas asset mutation executor（93f4027d）

- **取前沿**：`af535207`/`ef1f3f61` 已有只读 GraphCanvas projection，`8a0a6102` 已有 mutation audit command，但 StrategyConsole 还不能把真实 QRO 节点编辑写回 canonical asset。新 mint `93f4027d`（review_status=1）补第一条 QRO-node executor。
- **后端执行器**：新增 `execute_canvas_asset_mutation()` 与 `POST /api/research-os/graph/canvas_asset_mutations`；endpoint 要求登录用户，先写 `record_canvas_mutation`，再 `upsert_qro` 同一 QRO 新版本，只允许 `_ref/_hash` 合同字段或 evidence/math ref，拒绝未知 QRO、target type mismatch、live QRO 和 raw value。
- **前端接线**：StrategyConsole 真实 QRO 节点 inspector 增加 `记录编辑` action，调用执行型 endpoint 后重拉 `/canvas_projection`；测试断言 POST 不带 `raw_value`。
- **验收**：Research Graph/Desk/Compiler/StrategyConsole backend scoped → 58 passed / 2 warnings；StrategyConsole frontend scoped → 2 files / 41 passed；frontend build → `tsc && vite build` PASS（既有 chunk size warning）；backend full → 1559 passed / 13 skipped / 283 warnings。
- **边界**：这不是所有 GraphCanvas 手势可写、完整 graph database、strategy codegen、或所有 desk/API/scheduler edit path 全接线。

## 2026-06-27 · Governed model artifact loader guard（051144a8）

- **取前沿**：§15 要求 external pickle blocked、producer-run + hash binding、torch weights_only；现有 `training.lib.load_model()` 直接 `pickle.load`，DL 分支 `torch.load(..., weights_only=False)`。新 mint `051144a8`（review_status=1）补本地 loader guard。
- **Loader guard**：`.pkl` / `.joblib` 加载前必须有同目录 `validation_dossier.json`，且 dossier `artifact_hash` 必须等于当前文件 sha256，symlink serialized artifact 拒绝；`.pt` checkpoint 改为 `torch.load(..., weights_only=True)`。
- **验收**：loader/training/backtest/DL scoped → 49 passed / 2 warnings；training/model-desk/backtest/governance scoped → 118 passed / 2 warnings；compileall success；backend full → 1557 passed / 13 skipped / 283 warnings。
- **边界**：这是本地训练产物 loader guard，不是独立 sandbox 进程、远程 artifact store、runtime auto-promotion 或 live model serving 安全证明。

## 2026-06-27 · TrainingRun produces governed ModelPassport（fb378e42）

- **取前沿**：`08ce677e` 已要求模型晋级必须引用 passport，但训练成功路径还不会自动生产 ValidationDossier / ModelPassport。新 mint `fb378e42`（review_status=1）把结构化训练成功产物接进 §15 governance metadata。
- **Training producer**：`TrainingJob` 新增 `model_version`、`model_passport_ref`、`validation_dossier_ref`；`TrainingRequest` 新增 `dataset_id`；训练产物文件存在时计算 artifact sha256，写 `validation_dossier.json`，记录 `ModelGovernancePassport`，再把 passport/dossier refs 写入 `ModelVersion`。
- **Backend API**：`POST /api/training/jobs` 透传 `dataset_id`，训练完成后的 job response 暴露 `model_passport_ref` / `validation_dossier_ref`，避免训练台产出无治理模型。
- **验收**：training/model-governance/experiments scoped → 43 passed / 2 warnings；training/model-desk/backtest bridge scoped → 91 passed / 2 warnings；compileall success；backend full → 1555 passed / 13 skipped / 283 warnings。
- **边界**：这不是 artifact loader/inference 安全加载实现、sandbox execution、runtime auto-promotion 或 live model serving；审批门仍控制 stage flip，自由代码无 artifact 不注册幽灵模型版本。

## 2026-06-27 · Model Registry promotion requires governed model passport（08ce677e）

- **取前沿**：`6a9e7626` 已能记录 ModelPassport，但旧 `MODEL_REGISTRY.promote()` 仍可开 staging/production gate 而不认识 passport。新 mint `08ce677e`（review_status=1）把 §15 ModelPassport 接进旧模型晋级路径。
- **Model Registry gate**：`ModelVersion` 增加 `model_passport_ref` / `validation_dossier_ref`；`ModelRegistry.promote()` 对 staging/production fail-closed 校验已登记 passport，并要求 passport 的 `model_version_ref` 匹配当前 `model_id` + `version`。
- **Backend API**：`MODEL_REGISTRY` 注入 `MODEL_GOVERNANCE_REGISTRY`；`POST /api/models/{model_id}/promote` 透传 `model_passport_ref`；通过后把 `model_passport_ref` 与 `validation_dossier_ref` 写入 approval gate evidence。
- **验收**：`tests/test_model_governance.py` → 17 passed / 2 warnings；Model governance / approval / Model Desk / experiments / hypothesis scoped → 75 passed / 2 warnings；compileall success；backend full → 1554 passed / 13 skipped / 283 warnings。
- **边界**：这不是训练执行、TrainingRun→Passport 自动生产、artifact loader、runtime auto-promotion 或训练台全链路接线；审批门仍控制实际 stage flip。

## 2026-06-27 · Research OS model governance passport registry API（6a9e7626）

- **取前沿**：§15 已有 promotion validator，但 ModelPassport 还不能作为 Research OS metadata 持久化、replay 或通过 API 查看。新 mint `6a9e7626`（review_status=1）补 ModelPassport registry/API，不替换旧 `MODEL_REGISTRY`。
- **ModelPassport registry**：新增 `PersistentModelGovernanceRegistry`，append-only JSONL 记录通过 `validate_model_promotion` 的 `ModelGovernancePassport`；malformed history fail-closed；invalid passport 不写 partial file。
- **Backend API**：新增 `POST /api/research-os/model_governance/passports` 和 `GET /api/research-os/model_governance/summary`。summary 只返回 passport metadata 和 artifact refs，不加载模型 artifact，不触发 runtime promotion。
- **验收**：`tests/test_model_governance.py` → 12 passed / 2 warnings；§15 adjacent scoped → 52 passed / 2 warnings；compileall success；backend full → 1549 passed / 13 skipped / 283 warnings。
- **边界**：这不是训练执行、旧 Model Registry 替换、artifact loader、runtime promotion、训练台接线或模型晋级端点全入口强制治理。

## 2026-06-27 · Research OS settings LLM provider registry API（73e78014）

- **取前沿**：§4 的 Settings / LLM Provider / SecretRef 还只有 contract validator 和旧 `/api/llm/configure` keystore 路径；新 mint `73e78014`（review_status=1）补 Research OS metadata registry，不保存明文 secret。
- **Settings registry**：新增 `PersistentOnboardingRegistry`，append-only JSONL 记录 SecretRef metadata、LLMProvider metadata、LLMCredentialPool 和 ModelRoutingPolicy；provider/pool/policy 必须引用已登记上游 refs，malformed history fail-closed。
- **Backend API**：新增 `/api/research-os/settings/secret_refs`、`llm_providers`、`credential_pools`、`routing_policies` 和 `summary`。API 统一扫描 payload，发现 `sk-*`、`api_key`、password、OAuth token 等明文 credential material 即 422，不写 partial。
- **验收**：`tests/test_onboarding_gateway.py` → 13 passed / 2 warnings；§4 adjacent scoped → 64 passed / 2 warnings；compileall success；backend full → 1544 passed / 13 skipped / 283 warnings。
- **边界**：这不是真实 secret value storage、provider adapter、Gateway runtime enforcement、Settings UI、connection test wizard 或 full connector integration。

## 2026-06-27 · Governed Compiler artifact manifest audit layer（11470900）

- **取前沿**：§1/§8 的 compiler output artifact 仍只有 IR/pass，没有可持久化的 compiler artifact manifest。新 mint `11470900`（review_status=1）补非可执行 manifest 审计层，不声称 codegen。
- **Compiler artifact**：新增 `CompilerArtifactRecord` 与 `compiler_artifact_recorded` JSONL event。artifact 必须绑定已记录 IR/pass、Research Graph command、canonical command、run plan、environment lock、permission、output contract、manifest hash、evidence 和 validation refs；store 拒绝悬空 IR/pass 引用。
- **Backend API**：新增 `POST /api/research-os/compiler/artifacts`，`GET /api/research-os/compiler/summary` 返回 `artifact_total` 和 artifact summaries。validator 拒绝 `strategy_source` / `executable_strategy`、`executable=true`、embedded source code、raw LLM output、plaintext secret 和 silent mock fallback。
- **验收**：`tests/test_governed_compiler.py` → 16 passed / 2 warnings；Graph/Desk/Compiler/entrypoint scoped → 80 passed / 2 warnings；compileall success；backend full → 1539 passed / 13 skipped / 283 warnings。
- **边界**：这是非可执行 compiler artifact manifest 审计层；不是完整 compiler pass implementation、策略代码生成、scheduler wiring 或 production compiler service。

## 2026-06-27 · Research Graph governed canvas mutation command（8a0a6102）

- **取前沿**：§2 的 writable canvas mutation engine 仍未闭合；新 mint `8a0a6102`（review_status=1）先补 canonical mutation audit/write-back command，不声称完整可写画布。
- **Graph command**：新增 `CanvasMutationRecord` 与 `record_canvas_mutation` command type；`PersistentResearchGraphStore` 可持久化并 replay mutation command，且 mutation audit 不进入 QRO projection index。
- **Backend API**：新增 `POST /api/research-os/graph/canvas_mutations`。API 要求 `canonical_command_ref`、`audit_ref`、`value_ref` 或 `value_hash`，拒绝 `value/raw_value/raw_payload/payload`，并复用 `validate_canvas_mutation` 阻止 strategy desk 写 Factor `formula.*`。
- **验收**：Research Graph persistence → 6 passed / 2 warnings；Graph/Desk/Compiler/entrypoint scoped → 75 passed / 2 warnings；compileall success；backend full → 1534 passed / 13 skipped / 283 warnings。
- **边界**：这不是完整 writable canvas mutation engine、frontend edit wiring、canonical asset mutation executor、完整 graph database、full compiler implementation 或 strategy codegen。

## 2026-06-27 · Research Graph canvas projection frontend data flow（ef1f3f61）

- **取前沿**：§2 仍有 frontend GraphCanvas 数据流 gap；新 mint `ef1f3f61`（review_status=1）把 StrategyConsole 画布接到后端只读 Research Graph projection，不声称可写 mutation engine。
- **Frontend data flow**：`strategy/api.ts` 新增 `fetchResearchGraphCanvasProjection`；`StrategyConsolePage` mount 后请求 `/api/research-os/graph/canvas_projection?limit=24`，成功且非空时用真实 `nodes`/`edges` 替换 mock graph，并显示 `Research Graph` source/banner；失败、空投影或响应格式错时保留 mock fallback 并明示来源。
- **只读门**：真实 projection active 时启用 `canvasReadOnly`，拖拽、连线、删除、参数编辑、Ghost patch、Auto patch 均不改图；UI 不渲染后端额外 raw 字段。
- **验收**：StrategyConsole scoped → 2 files / 39 passed；frontend full → 26 files / 285 passed；frontend build → `tsc && vite build` PASS（保留既有 chunk size warning）。
- **边界**：这不是 canvas mutation engine、canonical command 写回、完整 graph database、完整 compiler pass implementation 或 strategy codegen。

## 2026-06-27 · Research Graph read-only canvas projection API（af535207）

- **取前沿**：§2 仍有 canvas projection engine gap；新 mint `af535207`（review_status=1）做只读 Graph→GraphCanvas projection，不声称 canvas mutation engine 或前端接线。
- **Canvas read model**：新增 `GET /api/research-os/graph/canvas_projection`，复用 QRO projection index filters，把每条 QRO projection 派生成 locked command node + locked QRO node，并以 command→QRO edge 连接。QRO type 映射到现有 GraphCanvas `NodeCat`，status axes 映射到 `NodeState`。
- **对抗测试**：覆盖 filter 后 shape、locked read-only、edge port wiring、position/running 映射、raw prompt/output contract 不泄露。
- **验收**：`tests/test_research_graph_persistence.py` → 3 passed / 2 warnings；Graph/Desk/Compiler/entrypoint scoped → 72 passed / 2 warnings；compileall success；backend full → 1531 passed / 13 skipped / 283 warnings。
- **边界**：这不是 canvas mutation engine、前端 GraphCanvas 数据接线、完整 graph database 或 production graph query service。

## 2026-06-27 · Governed Compiler compile QRO pass API（9d175460）

- **取前沿**：§1/§7/§8/§14/§16 仍有 compiler pass implementation gap；新 mint `9d175460`（review_status=1）做第一条从 Research Graph QRO 派生 governed Compiler IR/pass 的 deterministic API。
- **Compiler pass**：新增 `POST /api/research-os/compiler/compile_qro`。endpoint 从 `RESEARCH_GRAPH_STORE.commands()` 查已存在 `upsert_qro`，要求 `validation_refs`、`environment_lock_ref`、permission/evidence refs，派生 `CompilerIRRecord` + `CompilerPassRecord`，先 validate 两个 record，再写 `PersistentCompilerIRStore`。
- **对抗测试**：成功路径钉住 qro id、graph command id、canonical command ref、validation refs、environment lock、tool record refs；未知 QRO 422 不写 store；QRO/command 无 evidence refs 422 不写 partial。
- **验收**：`tests/test_governed_compiler.py` → 11 passed / 2 warnings；entrypoint/Graph/Compiler scoped → 66 passed / 2 warnings；compileall success；backend full → 1531 passed / 13 skipped / 283 warnings。
- **边界**：这不是完整 compiler pass implementation、策略代码生成、canvas mutation engine、scheduler wiring 或 production compiler service。

## 2026-06-27 · Research Graph QRO projection index API（7ba4a8b9）

- **取前沿**：§1/§2/§7/§8/§14/§16 仍有 projection index gap；新 mint `7ba4a8b9`（review_status=1）做 QRO projection read model，不声称完整 graph database。
- **Graph read model**：新增 `ResearchGraphProjectionRecord`。`ResearchGraphStore.apply(upsert_qro)` 写 QRO 时派生 projection index；`PersistentResearchGraphStore` replay command log 后自动重建。索引可按 QRO type、owner、market、universe、definition/evidence/runtime status 和 lineage token 过滤。
- **Backend API**：新增 `GET /api/research-os/graph/projection_index`，只读返回 QRO identity、status axes、lineage、refs、contract keys/hash 和 command ref；不返回 raw input/output contracts、prompt、strategy ref 或 tool payload。
- **验收**：Graph/Spine/Agent/Compiler scoped → 27 passed / 2 warnings；entrypoint/Graph/Compiler scoped → 63 passed / 2 warnings；compileall success；backend full → 1528 passed / 13 skipped / 283 warnings。
- **边界**：这不是完整 graph database、canvas mutation/projection engine、全入口 compiler wiring、完整 compiler pass implementation 或 production graph query service。

## 2026-06-27 · Document Intelligence safe local directory sync API（c4f3ac02）

- **取前沿**：§5/§6 仍缺显式安全目录级 ingestion；新 mint `c4f3ac02`（review_status=1）做本地目录同步 API，不声称全域自动资产库同步。
- **Backend API**：新增 `POST /api/research-os/documents/sync_local_directory`。调用方必须给 `asset_ref`、rights 和显式 `base_path`；后端只在 `project` 或 `data` root 下解析 `.md/.markdown/.txt/.rst/.pdf`，拒绝路径逃逸、hidden/sensitive 路径、symlink 和 plaintext secret。endpoint 先全量 prepare，再写 Document store/RAG index，失败不留 partial records；unsupported 文件进入 `skipped_paths`。
- **对抗测试**：新增目录同步成功/RAG retrieval、secret-bearing file fail-closed、hidden/sensitive path fail-closed 三个测试，钉住 atomicity 与权限边界。
- **验收**：`tests/test_document_intelligence_parser_rag.py` → 21 passed / 7 warnings；Document/RAG adjacent scoped → 45 passed / 7 warnings；compileall success；backend full → 1527 passed / 13 skipped / 283 warnings。
- **边界**：这不是 HTML crawler、跨 registry/provider/scheduler 的真实资产库全域自动同步、dense embedding/vector DB、完整 graph database 或表格/版面理解。

## 2026-06-27 · Document Intelligence scanned PDF OCR fallback（200435a6）

- **取前沿**：§6 仍有 scanned PDF OCR extraction gap；新 mint `200435a6`（review_status=1）做本机 tesseract fallback，不声称 OCR 质量或表格/版面理解。
- **Backend parser**：PDF parser 仍优先 PyMuPDF layout text blocks；当 PDF 无可抽取文本时，渲染临时 PNG 并调用 `tesseract stdout`，生成 `local_pdf_tesseract_ocr_no_network_v1` EvidenceSpan/RAG blocks，metadata 标 `layout_kind=pdf_ocr_page`，response 仍不返回 raw text。
- **对抗测试**：新增 image-only scanned PDF test，stub OCR 输出，断言 parser id、layout_kind、RAG hit、no raw text；既有 text PDF test 继续钉住 PyMuPDF layout parser。
- **验收**：`tests/test_document_intelligence_parser_rag.py` → 18 passed / 7 warnings；本机 tesseract smoke 可调用但 `PDF` 识别为 `POF`，只证明管线可调用；Document/RAG adjacent scoped → 42 passed / 7 warnings；compileall success；backend full → 1524 passed / 13 skipped / 283 warnings。
- **边界**：这不是 OCR 质量保证、表格/版面理解、联网 OCR 服务、真实资产库自动扫描/全库同步、dense embedding/vector DB 或完整 graph database。

## 2026-06-27 · Document Intelligence parser upload API and workbench UI（b1514408）

- **取前沿**：§6 的 parser 上传 UI 仍缺；新 mint `b1514408`（review_status=1）做受限 upload，不放开 raw document preview。
- **Backend API**：新增 `POST /api/research-os/documents/parse_upload`。上传只允许 text/Markdown/PDF/HTML 后缀，先 filename/size guard，再写 `DATA_ROOT/document_uploads/` 隔离区，随后复用 no-network parser、license rights、HTML URL allowlist、RAG permission 和 plaintext secret guard；缺 rights / secret-bearing body / bad filename 均 fail-closed，且本次隔离文件会清理。
- **Frontend UI**：`ResearchRAGPanel` 新增 Parser upload 表单；`authFetch` 对 FormData 不再强制 JSON content-type，避免破坏 multipart boundary。
- **验收**：`tests/test_document_intelligence_parser_rag.py` → 17 passed / 7 warnings；Document/RAG adjacent scoped → 41 passed / 7 warnings；frontend related scoped → 4 files / 53 tests passed；frontend full → 26 files / 281 tests passed；frontend build → tsc + vite PASS（chunk size warning）；backend full → 1523 passed / 13 skipped / 283 warnings。
- **边界**：这不是 OCR/scanned PDF extraction、联网 crawler、真实资产库自动扫描/全库同步、dense embedding/vector DB 或 raw document preview。

## 2026-06-27 · Document Intelligence frontend source summary browser（7a6fe037）

- **取前沿**：§6 的 SourceDocument 浏览 UI 仍缺；新 mint `7a6fe037`（review_status=1）只做只读摘要浏览，不做 parser 上传。
- **前端 UI**：`ResearchRAGPanel` 增加 `Document evidence` 区块，点击 `Load` 调用 `/api/research-os/documents/summary`，展示 sources/spans/claims 计数、`source_ref`、`parser_sandbox_ref`、`mime_magic_check_ref`，不展示 raw document payload。
- **测试修复**：`RDPExportPanel.test.tsx` 等待 detail controls ready 后再读 source map/run id/download 按钮，修复前端全量并发下的异步 race。
- **验收**：agent-workbench/RAG/RDP scoped → 3 files / 50 tests passed；`cd app/frontend && npm test -- --run` → 25 files / 278 tests passed；`cd app/frontend && npm run build` → tsc + vite build PASS（保留既有 chunk size warning）。
- **边界**：这不是 parser 上传 UI、OCR/scanned PDF extraction、真实资产库自动扫描/全库同步或 dense embedding/vector DB。

## 2026-06-27 · Document Intelligence layout-aware PDF text parser metadata（229e195d）

- **取前沿**：§6 的 PDF parser 仍缺 layout-aware evidence block；本机有 PyMuPDF，缺 pytesseract，所以新 mint `229e195d`（review_status=1）只做 layout-aware text blocks，不声称 OCR。
- **parser/API/RAG**：`parse_local_document` 的 PDF 分支优先使用 `local_pdf_pymupdf_layout_no_network_v1`，按 PyMuPDF text blocks 产生 EvidenceSpan，block metadata 增 `layout_bbox`、`layout_block_index`、`layout_kind=pdf_text_block`；pypdf 只作为 PyMuPDF 库缺失回退。RAG metadata 和 parse_local response 都带 layout refs，但仍不返回 raw text。
- **对抗测试**：扩展 `test_parse_local_pdf_records_page_anchored_spans_and_rag_context`，断言 parser sandbox id、layout bbox/block index/kind、no raw text；既有 parser tests 继续覆盖 fake PDF、path escape、secret-bearing body、batch atomic 等 fail-closed。
- **验收**：`cd app/backend && python -m pytest tests/test_document_intelligence_parser_rag.py -q` → 13 passed / 7 warnings；§5/§6 adjacent scoped → 37 passed / 7 warnings；`cd app/backend && python -m pytest -q` → 1519 passed / 13 skipped / 283 warnings。
- **边界**：这不是 OCR/scanned PDF extraction、external PDF service、parser 上传 UI、真实资产库自动扫描/全库同步或完整 graph database。

## 2026-06-27 · Research Asset RAG frontend candidate-context search UI（edf31a24）

- **取前沿**：§5/§6 仍有前端 RAG UI gap；新 mint `edf31a24`（review_status=1）承接研究执行台只读查询面，不碰 active `review_status:0` 卡。
- **前端 UI**：新增 `ResearchRAGPanel` 并挂入 agent-workbench 产物工作区 `RAG` tab。用户必须显式输入 `query`、`desk`、`visible_asset_refs`、`permission_tags`、`top_k`；UI 支持 lexical 与 deterministic sparse-vector search，分别调用 `/api/research-os/rag/retrieve` 和 `/api/research-os/rag/vector_search`。结果展示 source/version/asset/projection/score/context_role/evidence_label/applicability/snippet，命中只标 `candidate_context`，不包装成 verdict/proof。
- **对抗测试**：新增 `ResearchRAGPanel.test.tsx`，覆盖无 visible assets 不请求后端、sparse-vector payload 必含显式权限范围、lexical endpoint + top_k clamp、后端 422 显错且不伪造命中。
- **验收**：`cd app/frontend && npm test -- --run src/pages/workshop/agent-workbench/ResearchRAGPanel.test.tsx src/pages/workshop/agent-workbench/RDPExportPanel.test.tsx` → 9 passed；`cd app/frontend && npm test -- --run src/pages/workshop/agent-workbench/agentWorkbench.test.tsx` → 40 passed；`cd app/frontend && npm test -- --run` → 25 files / 277 tests passed；`cd app/frontend && npm run build` → tsc + vite build PASS（保留既有 chunk size warning）。
- **边界**：这不是 dense embedding/vector DB、OCR/layout-aware PDF parser、parser 上传 UI、真实资产库自动扫描/全库同步或完整 graph database。

## 2026-06-26 · RDP local package publish registry/API/UI

- **本机 publish registry**：新增 `RDPPackagePublishRecord` / `RDPLocalPackagePublisher` / `PersistentRDPPackagePublishStore`。publish 必须先通过 `RDPPackageArchiveExporter.export()`；通过后将 zip 复制到 `DATA_ROOT/rdp_packages/_published/<package_id>/`，写 `publication.json` 和 append-only `DATA_ROOT/audit/rdp_package_publishes.jsonl`。
- **Backend API + UI**：新增 `POST /api/research-os/rdp/manifests/{package_id}/publish` 和 `GET /api/research-os/rdp/publications`；`RDPExportPanel` 增加 `Publish local`，前端固定发 `{channel:"local_registry"}`，不接受外部 URL/对象存储目标。
- **对抗测试**：新增 `tests/test_research_os_rdp_publish.py`，覆盖 local publish + replay、tampered archive、缺 source bundle、external channel、API publish/list、unknown manifest 404；前端 RDP 面板测试覆盖 publish body 和 publish_hash 展示。
- **验收**：`cd app/backend && python -m pytest tests/test_research_os_rdp_publish.py -q` → 6 passed / 2 warnings；RDP package group → 53 passed / 2 warnings；Research OS scoped group → 185 passed / 2 warnings；`cd app/frontend && npm test -- RDPExportPanel.test.tsx` → 5 passed；`cd app/frontend && npm test -- agentWorkbench.test.tsx` → 40 passed；`cd app/frontend && npm run build` → tsc + vite build PASS（chunk size warning）；`cd app/backend && python -m pytest -q` → 1499 passed / 13 skipped / 278 warnings。
- **边界**：这不是公网/对象存储发布、CI release、生产部署、实盘运行或重新回测；它只补本机 registry publish 和审计记录。

## 2026-06-26 · RDP frontend export UI

- **研究执行台 RDP.zip**：新增 `RDPExportPanel` 并挂入 agent-workbench 产物工作区。面板读取 RDP manifest registry/detail，按后端顺序调用 materialize、bundle_sources、source-run integrity attestation 和 archive 下载；workspace 顶栏在 RDP tab 显示 Backend，不沿用老产物 MOCK 角标。
- **前端 guard**：`source_map` 默认只从 manifest `source_file_refs` 推导安全相对路径；`../`、绝对路径和空 run_id 先在 UI 层拦截，后端 RDP guard 仍是权威；archive 422 显示错误，不伪造下载成功。
- **对抗测试**：新增 `RDPExportPanel.test.tsx`，覆盖空 registry、materialize→bundle→attest→archive 成功路径、archive 422、unsafe source ref 不自动映射、空 run_id 不发 attestation。
- **验收**：`cd app/frontend && npm test -- RDPExportPanel.test.tsx` → 5 passed；`cd app/frontend && npm test -- agentWorkbench.test.tsx` → 40 passed；`cd app/frontend && npm run build` → tsc + vite build PASS（保留 chunk size warning）。
- **边界**：这不是 live package publish、公网/对象存储上传、外部部署、自动 parser/RAG ingestion 或重新运行回测；它只把后端 RDP open package 导出链接到真实前端入口。

## 2026-06-26 · RDP source-to-run integrity attestation/API

- **RDP source-run integrity**：新增 `RDPSourceRunIntegrityRecord` / `PersistentRDPSourceRunIntegrityStore`，把已 materialize 且已完成 source-file bundle 的 RDP package、`RUN_ROOT/<run_id>/run.json`、`strategy.py`、`portfolio.csv` 和 manifest `artifact_hash` 绑定成 append-only 一致性证明。
- **Backend API**：`app/backend/app/main.py` 新增 app-level `RDP_SOURCE_RUN_INTEGRITY_STORE` 和 `POST /api/research-os/rdp/manifests/{package_id}/source_run_integrity_attestations`。接口只收 `run_id` 和可选 `source_file_ref`，从服务端 `RUN_ROOT` 定位运行产物，不接受任意本地路径；unknown package 404，guard 失败 422。
- **对抗测试**：新增 `tests/test_research_os_rdp_source_run_integrity.py`，覆盖 source bundle 缺失、run_id 未声明、`run.json` run_id mismatch、manifest `artifact_hash` mismatch、source bundle 与 run strategy mismatch、run_id path escape、API success 和 unknown package 404。
- **验收**：`cd app/backend && python -m pytest tests/test_research_os_rdp_source_run_integrity.py -q` → 8 passed / 2 warnings；RDP package group → 47 passed / 2 warnings；Research OS scoped group → 177 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1493 passed / 13 skipped / 278 warnings。
- **边界**：这不是前端导出 UI、live package publish、外部部署、重新运行回测或 deployment attestation 替代；它只补 RDP package source bundle 到真实 run artifacts 的本地后端证明链。

## 2026-06-26 · RDP package archive export/API

- **RDP archive export**：新增 `RDPPackageArchiveRecord` / `RDPPackageArchiveExporter`，把已 materialize 且按需完成 source-file bundle 的 RDP open package 导出为 deterministic zip，归档缓存写在 `DATA_ROOT/rdp_packages/_archives/`，不会卷回 package 目录。
- **Backend API**：`app/backend/app/main.py` 新增 app-level `RDP_PACKAGE_ARCHIVE_EXPORTER` 和 `GET /api/research-os/rdp/manifests/{package_id}/archive`。接口返回 `application/zip`，带 archive sha256 / file count headers；unknown package 404，包 guard 失败 422。
- **对抗测试**：新增 `tests/test_research_os_rdp_archive_export.py`，覆盖确定性 zip 重复导出、未物化包、reserved package id、声明 source refs 但缺 source bundle、tampered manifest、symlink escape、API zip 下载和 unknown package 404。
- **验收**：`cd app/backend && python -m pytest tests/test_research_os_rdp_archive_export.py -q` → 8 passed / 2 warnings；RDP package group → 39 passed / 2 warnings；Research OS scoped group → 169 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1485 passed / 13 skipped / 278 warnings。
- **边界**：这不是前端导出 UI、live package publish、外部部署或 source-to-run integrity attestation；它只补本地后端 open package 下载面。

## 2026-06-26 · RDP deployment attestation/API

- **RDP deployment attestation**：新增 `RDPDeploymentAttestationRecord` / `PersistentRDPDeploymentAttestationStore`，对已 materialize 的 RDP package 做只读一致性证明，写 append-only `DATA_ROOT/audit/rdp_deployment_attestations.jsonl`。记录 manifest hash、manifest file sha256、refs sha256、source bundle index sha256、deployment_ref、approval/monitor/rollback/retire refs 和 attestation hash。
- **Backend API**：`app/backend/app/main.py` 新增 app-level `RDP_DEPLOYMENT_ATTESTATION_STORE` 和 `POST /api/research-os/rdp/manifests/{package_id}/deployment_attestations`。接口不 materialize、不 bundle、不发布；调用方必须先准备 package/source bundle，再提交已声明的 `deployment_ref`。
- **对抗测试**：新增 `tests/test_research_os_rdp_deployment_attestation.py`，覆盖 live package attestation + restart replay、缺 source bundle、未声明 deployment_ref、tampered manifest、source bundle package_id mismatch、API success、unknown package 404。
- **验收**：`cd app/backend && python -m pytest tests/test_research_os_rdp_deployment_attestation.py -q` → 7 passed / 2 warnings；RDP package group → 31 passed / 2 warnings；Research OS scoped group → 161 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1477 passed / 13 skipped / 278 warnings。
- **边界**：这不是 frontend export、live package publish、外部部署或 source-to-run integrity attestation；它只证明当前本地 open package 与部署清单一致。

## 2026-06-26 · RDP source-file content bundle/API

- **RDP source bundle**：新增 `RDPSourceFileBundler` / `RDPSourceFileBundleEntry` / `RDPSourceFileBundleRecord`，在已 materialize 的 RDP package 下写 `source_files/` 和 bundle-relative `source_files_index.json`。只复制 `manifest.source_file_refs` 声明的源码文件；`manifest.json` / `refs.json` 仍不嵌 source payload。
- **Backend API**：`app/backend/app/main.py` 新增 app-level `RDP_SOURCE_FILE_BUNDLER` 和 `POST /api/research-os/rdp/manifests/{package_id}/bundle_sources`。API 会先物化 manifest，再按 `source_map` 复制源码；unknown package 404，source guard 失败 422。
- **对抗测试**：新增 `tests/test_research_os_rdp_source_bundle.py`，覆盖正常复制/index、未声明 ref、缺 mapping、`../` 逃逸、绝对路径、明文 secret、超限文件、非 UTF-8 和 API unknown package。复核修正：`source_files_index.json` 不写本机绝对 package path，只保留 bundle-relative path。
- **验收**：`cd app/backend && python -m pytest tests/test_research_os_rdp_source_bundle.py -q` → 8 passed / 2 warnings；RDP package group → 24 passed / 2 warnings；Research OS scoped group → 154 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1470 passed / 13 skipped / 278 warnings。
- **边界**：这不是前端导出、deployment attestation、live package publish，也不是 source-to-run integrity attestation；它只补第一版安全源码内容打包。

## 2026-06-26 · RDP open package materializer

- **RDP materializer**：新增 `RDPOpenPackageMaterializer` / `RDPPackageRecord`，接受已通过 manifest gate 的 `RDPManifest`，在 `DATA_ROOT/rdp_packages/<package_id>/` 写 deterministic `manifest.json` 和 `refs.json`。同一 manifest 反复 materialize 幂等；unsafe package id 拒绝；只保留 `source_file_refs`，不复制 source payload。
- **Backend API**：`app/backend/app/main.py` 新增 app-level `RDP_PACKAGE_MATERIALIZER` 和 `POST /api/research-os/rdp/manifests/{package_id}/materialize`。unknown package 404；invalid manifest/materializer guard 422。
- **对抗测试**：新增 `tests/test_research_os_rdp_materializer.py`，覆盖 manifest/refs 文件输出、source payload 不生成、幂等、路径穿越拒绝、API materialize、unknown package 404。第一次 scoped 跑出 idempotency 比较 bug（写入有换行、比较无换行），已修。
- **验收**：`cd app/backend && python -m pytest tests/test_research_os_rdp.py tests/test_research_os_rdp_persistence.py tests/test_research_os_rdp_materializer.py -q` → 16 passed / 2 warnings；Research OS scoped group → 70 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1462 passed / 13 skipped / 278 warnings。
- **边界**：这不是前端导出、source-file content bundle、deployment attestation 或 live package publish。

## 2026-06-26 · Governed Compiler IR persistent store/API

- **Compiler IR store**：新增 `app/backend/app/research_os/compiler.py`，定义 `CompilerIRRecord`、`CompilerPassRecord`、compiler validators 和 `PersistentCompilerIRStore`。compiler IR/pass audit records 以 append-only JSONL 写到 `DATA_ROOT/audit/compiler_ir.jsonl`，启动 replay，malformed history fail-closed。
- **Backend API**：`app/backend/app/main.py` 新增 app-level `COMPILER_IR_STORE` 和 `POST /api/research-os/compiler/ir`、`POST /api/research-os/compiler/passes`、`GET /api/research-os/compiler/summary`。接口只记录 schema-constrained compiler audit records，不执行真实 compiler pass。
- **对抗测试**：新增 `tests/test_governed_compiler.py`，覆盖 IR 缺 QRO/Research Graph/canonical command/evidence/validation refs；compiler pass direct graph mutation / permission bypass / raw LLM output-as-IR；unknown output IR；restart replay；malformed history；API no-write。
- **验收**：`cd app/backend && python -m pytest tests/test_governed_compiler.py -q` → 8 passed / 2 warnings；Research OS scoped group → 65 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1457 passed / 13 skipped / 278 warnings。
- **边界**：这不是完整 compiler pass 实现、projection index、canvas mutation engine、scheduler 或全入口 compiler wiring。

## 2026-06-26 · RDP persistent package registry/API

- **RDP store**：新增 `PersistentRDPStore`，把通过 `validate_rdp_manifest` 的 `RDPManifest` 以 append-only JSONL 写到 `DATA_ROOT/audit/rdp_manifests.jsonl`，启动 replay，malformed history fail-closed；invalid manifest 和 live runtime 缺 deployment/monitor/rollback/retire refs 均拒绝且不落盘。
- **Backend API**：`app/backend/app/main.py` 新增 app-level `RDP_STORE` 和 `POST /api/research-os/rdp/manifests`、`GET /api/research-os/rdp/manifests`、`GET /api/research-os/rdp/manifests/{package_id}`。列表返回 package summary；详情返回 open manifest dict；不做 source-file payload materialization。
- **对抗测试**：新增 `tests/test_research_os_rdp_persistence.py`，覆盖 restart replay、invalid manifest no-write、live refs guard、malformed history、API create/list/read、source file 仅 refs 不嵌 payload。
- **验收**：`cd app/backend && python -m pytest tests/test_research_os_rdp.py tests/test_research_os_rdp_persistence.py -q` → 11 passed / 2 warnings；Research OS scoped group → 57 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1449 passed / 13 skipped / 278 warnings。
- **边界**：这不是前端导出、source-file bundle、zip/package materialization、deployment attestation 或 live package publish。

## 2026-06-26 · Document Intelligence persistent evidence store/API

- **Document Intelligence store**：新增 `PersistentDocumentIntelligenceStore`，把 `SourceDocumentIntakeRecord`、`EvidenceSpanRecord`、`ExtractedResearchClaim`、`PrivilegedToolUseRequest` 以 append-only JSONL 写到 `DATA_ROOT/audit/document_intelligence.jsonl`，启动 replay，malformed history fail-closed；每次写入复用现有 validator，并补非空 record ref 守门。
- **Backend API**：`app/backend/app/main.py` 新增 app-level `DOCUMENT_INTELLIGENCE_STORE` 和 `/api/research-os/documents/sources`、`/evidence_spans`、`/extracted_claims`、`/tool_requests`、`/summary`。接口只记录 schema-constrained evidence metadata，不接受 raw document payload。
- **对抗测试**：新增 `tests/test_document_intelligence_store.py`，覆盖 safe source + verified span + confirmatory claim + schema-only tool request restart replay；unsafe source 不落盘；unverified span 不得进入 confirmatory claim；direct document payload 不得触发 privileged tool；empty refs 和 malformed history fail-closed。
- **验收**：`cd app/backend && python -m pytest tests/test_document_intelligence_contract.py tests/test_document_intelligence_store.py -q` → 13 passed / 2 warnings；Research OS scoped group → 51 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1443 passed / 13 skipped / 278 warnings。
- **边界**：这不是完整 PDF/web parser pipeline、前端 document 检索 UI、vector search、自动 Research Asset RAG ingestion 或完整 graph database。

## 2026-06-26 · GOAL 0-17 第一主线 runtime contract + Vision reload-merge 修复落档

- **Agent Shell 接线 + Graph 审计读面**：新增 `app/backend/tests/test_agent_runtime_research_graph.py`，扩展 `app/backend/app/agent/agent_runtime.py`，让 `AgentRuntime` 可选注入 `ResearchGraphStore`，每个 user/assistant/tool/system step 通过 `QRORecord` + `ResearchGraphCommand(upsert_qro)` 落图；QRO contracts 只放 content hash / 元数据，避免把原文或 tool payload secret 复制进 Graph。`app/backend/app/main.py` 新增 app-level `RESEARCH_GRAPH_STORE`，`_agent_runtime()` 注入它，`/api/agent/chat`、workbench done event、Mode2 chat metadata 暴露 `qro_ids` / `research_graph_command_ids`；新增 `GET /api/research-os/graph/commands` 只读审计摘要，返回 command/QRO refs、状态轴、lineage 和 allowlist hash 元数据，不返回 prompt/tool payload；`5ac0a71e` / `1668fc7c` done。这是真实 Agent Shell 入口接线和读面，不等于 canvas/API/IDE/scheduler/Settings/connectors/training/execution/CI 全入口已接。
- **StrategyGoal / QuantIntent 业务 QRO**：新增 `QROType.QUANT_INTENT`，扩展 `StrategyGoalStore.create_from_args(..., research_graph=...)`，成功产 `strategy_goal_id` 时写 `QuantIntent` QRO；Agent Shell `strategy_goal.create` 注册点传入同一个 `RESEARCH_GRAPH_STORE`。QRO 只保存 arg hash/arg keys、goal hash、asset_class/objective/horizon/benchmark，不复制自然语言 description 或工具参数值；`59372285` done。这是第一条业务对象接线，不等于 factor/model/signal/strategy 全端点已接。
- **StrategyGoal direct API 接线**：新增 `POST /api/strategy_goals` / `GET /api/strategy_goals` / `GET /api/strategy_goals/{goal_id}`。直接 API 成功创建 StrategyGoal 时复用同一个 `StrategyGoalStore` 和 `RESEARCH_GRAPH_STORE`，以 `entry_source=api` / `actor_source=user_manual` 写 `QuantIntent` QRO；缺槽位返回 422，不落 goal 文件，不加 Graph command；`b32dbcd8` done。这推进 API 入口，不等于 canvas/IDE/scheduler/Settings/training/execution 已接。
- **IDE StrategyBook 入口接线**：`POST /api/ide/strategies` 成功保存策略草稿后写 `QROType.STRATEGY_BOOK`，返回 `qro_id` / `research_graph_command_id`。QRO 只保存 strategy_id/name、asset_class、code_hash、description_hash、content_hash、updated_at_utc；Graph 审计响应不暴露 Python 源码或 description 原文；非法 asset_class 等失败路径不写 Graph command；`b1b48097` done。这只覆盖 IDE strategy save，不等于 IDE run/promote/AI complete 或 compiler pass 已接。
- **IDE BacktestRun 入口接线**：`POST /api/ide/strategies/{name}/run` 完成实际沙箱运行后写 `QROType.BACKTEST_RUN`，返回 `qro_id` / `research_graph_command_id`。QRO 只保存 strategy/run 身份、source hash、status、exit_code、duration、result_key_count 和时间；Graph 审计不暴露 stdout/stderr/result payload/result key names；unknown strategy 404 不写 Graph command；failed/timeout run 写 `evidence=insufficient`，ok run 写 `evidence=exploratory`，均不包装成验证结论；`a2a5b61b` done。这只覆盖 IDE run，不等于 IDE promote/AI complete 或 validation dossier 已接。
- **IDE promoted BacktestRun 入口接线**：`POST /api/ide/runs/{run_id}/promote` 成功创建正式 run artifact 后写 promoted `QROType.BACKTEST_RUN`，返回 `qro_id` / `research_graph_command_id`。QRO 只保存 source/promoted run id、strategy hash、metric_count、gate_verdict_present；Graph 审计不暴露 strategy.py、equity_curve、trades、metrics payload、gate verdict 详情或 record_name；invalid result PromoteError 400 不写 Graph command；`18bb49e7` done。这只覆盖 IDE promote，不等于 IDE AI complete、approval 或 production readiness 已接。
- **IDE LLMCallRecord 入口接线**：`POST /api/ide/ai_complete` 成功 LLM 调用后写 `QROType.LLM_CALL_RECORD`，返回 `qro_id` / `research_graph_command_id`。QRO 只保存 mode、provider、prompt_hash、context_hash、output_hash、output_char_count、market；Graph 审计不暴露 prompt/context/generated code 或 explanation；empty prompt 400 不写 Graph command；`4f4eab2a` done。这只覆盖 IDE AI complete，不等于 Settings/provider adapter/Gateway hard routing、完整 graph database 或其他 LLM 入口已接。
- **Research Graph command/QRO 持久化**：新增 `PersistentResearchGraphStore`，把已接 `ResearchGraphCommand` 以 JSONL 写到 `DATA_ROOT/audit/research_graph_commands.jsonl`，启动时 replay，malformed history fail-closed；`app/backend/app/main.py` 的 `RESEARCH_GRAPH_STORE` 已换成持久化 store；`5bb5d9da` done。这只覆盖当前 command/QRO 持久化，不等于完整 graph database、RAG index、Canvas canonical mutation、Scheduler、Settings/provider adapter、training/execution 或 compiler pass 已接。
- **建/改**：新增 `app/backend/app/research_os/spine.py` / 包入口，建立 QRO 类型、分离状态轴、Research Graph canonical command、Mathematical Spine binding/check、MethodologyChoice/Responsibility 记录和 promotion guard；把 `1d16328c` 自分配并落 done。该工作推进 GOAL §1/§6/§8/§10/§13/§16/§17 的第一条 runtime 契约，但尚未把 chat/canvas/API/IDE/scheduler 全入口接入。
- **Research Asset RAG**：新增 `app/backend/app/research_os/asset_rag.py`，建立 §5 第一版资产级 RAG contract：user/desk/asset/tag 权限过滤、source/version/timestamp/permission/applicability hit 元数据、Agent hit usage 账、SecretRef 明文阻断、user-waived 不得显示强证据；`37729820` done。
- **Research Asset RAG persistent backend**：新增 `PersistentResearchAssetRAGIndex`，把 RAG document 和 Agent usage event 以 JSONL 落 `DATA_ROOT/audit/research_asset_rag.jsonl`，启动 replay，malformed history fail-closed；新增 `POST /api/research-os/rag/documents`、`POST /api/research-os/rag/retrieve`、`GET /api/research-os/rag/agent_usage`。API 默认 document 限当前 user，保持 user/desk/asset/tag 过滤，拒绝 plaintext secret，agent-mode retrieve 记录 source/version/user_id usage，usage 查询只返回当前 user；`3f1dd2de` done。这只覆盖 RAG 持久化 backend seam，不等于前端 RAG UI、Agent Shell 自动调用、Document parser/source ingestion 或 vector search 已接。
- **RDP gate**：新增 `app/backend/app/research_os/rdp.py`，把 §17 Research Delivery Package 的 manifest / DatasetVersion / IngestionSkill / math binding / MethodologyChoice / reproducibility command / artifact hash / 未验证残余 / live 清单做成可执行 validator；`bc412bbd` done。它是后端交付门，不等于前端导出或完整打包器已完成。
- **Onboarding/Gateway**：新增 `app/backend/app/research_os/onboarding_gateway.py`，把 §4 的 SecretRef/IngestionSkill、DataSourceAsset export/share 限制、LLMProvider/Auth、CredentialPool、ModelRoutingPolicy、LLM Gateway call 做成 validator；`c637a97f` done。它是治理合约，不等于 Settings UI、connector 和 provider adapter 全接线已完成。
- **Market Data Contract**：新增 `app/backend/app/research_os/market_data_contract.py`，把 §11 的 DatasetSemantics、InstrumentSpec、MarketCapabilityMatrix、跨币种资本账、期权语义、数据变换数学绑定做成 validator；`11c209b2` done。它是数据/标的合约，不等于所有 connector、strategy builder 或 execution path 已强制接入。
- **Execution Boundary**：新增 `app/backend/app/research_os/execution_boundary.py`，把 §12 的 live ladder、A股 live 边界、OrderGuard/kill switch/SecretRef/idempotency/audit 不可 waiver、HALT/reconcile、drift action、execution math ConsistencyCheck、user risk responsibility 做成 validator；`f8da74ba` done。它是执行边界合约，不等于所有 runtime transition 和 execution endpoint 已接线。
- **Trust Layer**：新增 `app/backend/app/research_os/trust_layer.py`，把 §13 的 strong claim evidence、反谄媚、弱点默认可见、cold-start N=1、functional independence、user autonomy、release gate 做成 validator；`2f4c8e91` done。它是信任层合约，不等于 UI 披露和发版流水线已全部接线。
- **Model Governance**：新增 `app/backend/app/research_os/model_governance.py`，把 §15 的 ModelPassport / artifact manifest / safe loading policy / challenger / recertification 做成 promotion validator；`317bdbd4` done。它是后端晋级闸门，不等于训练台和 Model Registry 全入口已接入。
- **Factor/Signal/Strategy Boundary**：新增 `app/backend/app/research_os/factor_strategy_boundary.py`，把 §9 的 generator/gatekeeper 解耦、模型本体不得进因子库、Signal OOF/purge/embargo/lock/honest-N、StrategyBook short 检查、retired factor、数学 run_config 绑定做成 boundary validator；`12f2d5ad` done。它是合约闸门，不等于所有 factor/model/signal/strategy 端点已强制接入。
- **Desk/Lifecycle/Document/Methodology**：新增 `desk_projection.py` / `asset_lifecycle.py` / `document_intelligence.py` / `methodology_validation.py`，把 §2 多台 projection/DeskHandoff/canonical command、§3 全资产 lifecycle、§6 EvidenceSpan/文档 trust boundary、§10 methodology validation/control plane 做成 validator；`4e7a2c10` / `6b1d3f20` / `9c5e2a6d` / `a7d4f102` done。它们是运行时合约，不等于所有 canvas/registry/parser/validation producer 已接线。
- **Agent OS / M1-M21 / Engineering Standards**：新增 `agent_os.py` / `platform_coverage.py` / `engineering_standards.py`，把 §7 visible event/plan/dispatch/code-change/tool/completion、§14 M1-M21 coverage manifest、§16 no silent mock/data/LLM replay/theory binding/fatal/perf baseline 做成 validator；`b8e1f37a` / `d2f9b604` / `f3a6c8d1` done。它们是合约和覆盖清单，不等于 live dashboard、CI/benchmark/provider/data 全入口已强制接线。
- **GOAL coverage manifest**：新增 `app/backend/app/research_os/goal_coverage.py`，要求 §0–§17 每节都有 contract/test/task/evidence refs，并防止把 contract 覆盖误报成 full product implementation；`0f17c0de` done。它是总覆盖门，不等于真实入口自动接线。
- **Vision 修复落档**：`e1a98c41` 已有代码和测试验证，`_reload_partition_csv(... try_parse_dates=False)` 保持 timestamp 字符串，防止多日同年增量 merge 出 String/Datetime schema crash；任务移入 done。
- **验证发现并修复**：RDP 后第二轮全量在既有 `test_effect_ledger_concurrent_same_key` 卡住，线程在 `EffectLedger.__init__` 的 WAL 初始化处遇到 sqlite `database is locked` 且异常发生在 barrier 前；修 `EffectLedger` 并发 first-open retry，`8d40a946` done。`tests/test_dag_kernel.py::test_effect_ledger_concurrent_same_key -v` → 1 passed；`tests/test_dag_kernel.py -q` → 25 passed。
- **验收**：`cd app/backend && python -m pytest tests/test_research_os_spine.py -v` → 8 passed；`cd app/backend && python -m pytest tests/test_research_os_rdp.py -v` → 5 passed；`cd app/backend && python -m pytest tests/test_research_asset_rag.py -v` → 6 passed；`cd app/backend && python -m pytest tests/test_onboarding_gateway.py -v` → 8 passed；`cd app/backend && python -m pytest tests/test_secrets_loader.py tests/test_llm_providers.py tests/test_onboarding_gateway.py -v` → 21 passed；`cd app/backend && python -m pytest tests/test_market_data_contract.py -v` → 6 passed；`cd app/backend && python -m pytest tests/test_data_contract.py tests/test_universe.py tests/test_paper_desk_api.py tests/test_market_data_contract.py -v` → 61 passed；`cd app/backend && python -m pytest tests/test_execution_boundary_contract.py -v` → 8 passed；`cd app/backend && python -m pytest tests/test_security_gate_adversarial.py tests/test_dag_kernel.py tests/test_paper_desk_api.py tests/test_execution_boundary_contract.py -v` → 82 passed；`cd app/backend && python -m pytest tests/test_model_governance.py -v` → 7 passed；`cd app/backend && python -m pytest tests/test_factor_strategy_boundary.py -v` → 7 passed；`cd app/backend && python -m pytest tests/test_factor_lab_endpoints.py tests/test_factor_strategy_boundary.py -v` → 22 passed；`cd app/backend && python -m pytest tests/test_trust_layer.py -v` → 10 passed；`cd app/backend && python -m pytest tests/test_desk_projection.py tests/test_asset_lifecycle.py -v` → 13 passed；`cd app/backend && python -m pytest tests/test_document_intelligence_contract.py tests/test_methodology_validation.py -v` → 13 passed；`cd app/backend && python -m pytest tests/test_agent_os_contract.py -v` → 8 passed；`cd app/backend && python -m pytest tests/test_platform_coverage.py tests/test_engineering_standards.py -v` → 12 passed；`cd app/backend && python -m pytest tests/test_goal_coverage.py -v` → 5 passed；`cd app/backend && python -m pytest tests/test_research_os_spine.py tests/test_research_os_rdp.py tests/test_research_asset_rag.py tests/test_model_governance.py tests/test_factor_strategy_boundary.py tests/test_onboarding_gateway.py tests/test_market_data_contract.py tests/test_execution_boundary_contract.py tests/test_trust_layer.py tests/test_desk_projection.py tests/test_asset_lifecycle.py tests/test_document_intelligence_contract.py tests/test_methodology_validation.py tests/test_agent_os_contract.py tests/test_platform_coverage.py tests/test_engineering_standards.py tests/test_goal_coverage.py -q` → 116 passed；`cd app/backend && python -m pytest tests/test_agent_runtime_research_graph.py -v` → 6 passed；`cd app/backend && python -m pytest tests/test_ds2_strategy_goal_persist.py tests/test_agent_runtime_research_graph.py -v` → 14 passed；`cd app/backend && python -m pytest tests/test_agent.py tests/test_agent_tool_status.py tests/test_agent_business_tools_a4.py tests/test_agent_permission_tristate.py tests/test_agent_runtime_research_graph.py tests/test_chat_conversations.py tests/test_ds2_strategy_goal_persist.py -q` → 89 passed；`cd app/backend && python -m pytest tests/test_strategy_console_s2.py -q` → 26 passed；`cd app/backend && python -m pytest tests/test_ide_promote.py tests/test_ide.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_research_os_spine.py -q` → 54 passed；`cd app/backend && python -m pytest tests/test_agent.py -v` → 9 passed；`cd app/backend && python -m pytest tests/test_vision_pull_merge.py -v` → 3 passed；`cd app/backend && python -m pytest -q` → 1428 passed / 13 skipped / 278 warnings。
- **补充验收（IDE AI complete 后）**：`cd app/backend && python -m pytest tests/test_strategy_console_s2.py -q` → 28 passed / 2 warnings；`cd app/backend && python -m pytest tests/test_ide_promote.py tests/test_ide.py tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_research_os_spine.py -q` → 54 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1430 passed / 13 skipped / 278 warnings；runtime artifact check 确认 `data/artifacts/experiments`、`data/ide_runs`、`data/artifacts/strategy_goals`、`data/artifacts/llm_fixtures`、`data/verification` 无 git-visible 新变化。
- **补充验收（Graph persistence 后）**：`cd app/backend && python -m pytest tests/test_research_graph_persistence.py -q` → 2 passed；`cd app/backend && python -m pytest tests/test_research_os_spine.py -q` → 8 passed；`cd app/backend && python -m pytest tests/test_agent_runtime_research_graph.py tests/test_ds2_strategy_goal_persist.py tests/test_strategy_console_s2.py tests/test_research_graph_persistence.py -q` → 44 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1432 passed / 13 skipped / 278 warnings。
- **补充验收（RAG persistence 后）**：`cd app/backend && python -m pytest tests/test_research_asset_rag.py tests/test_research_asset_rag_persistence.py -q` → 10 passed / 2 warnings；Research OS contract group → 122 passed / 2 warnings；`cd app/backend && python -m pytest -q` → 1436 passed / 13 skipped / 278 warnings。
- **下一步**：继续把 QRO/Graph/RAG contract 接进真实入口。当前事实状态是 §0–§17 第一版 contract 覆盖已建并有测试，Agent Shell / StrategyGoal API / IDE save / IDE run / IDE promote / IDE AI complete 已接，已接 command/QRO 可跨 store restart 恢复，Research Asset RAG 有 persistent backend seam；其余真实入口强制接线仍需按 TRACE 的下一层逐点推进。

## 2026-06-25 · D-MATH-SPINE 入 GOAL

- **拍板**：用户明确数学贯穿全流程，理论先证明，Agent 降实现门槛，理论到实现一致性是不可绕过的诚实门；方法学松紧和是否走流程由 user 选择，系统给代价、推荐、流程和责任边界。
- **GOAL**：补 Mathematical Spine、TheorySpec、TheoryImplementationBinding、ConsistencyCheck、MethodologyChoiceRecord、ResponsibilityDisclosureRecord；覆盖 data→factor→model→signal→portfolio→execution→backtest→attribution→monitor。
- **账本**：追加 `D-MATH-SPINE`；同步 `research/TRACE.md` 与 `state/dreaminate/state.md`，把数学脊柱标为新 GOAL gap，未写成已实现。

## 2026-06-25 · GOAL 终态扩展 + dev 规则审计

- **GOAL**：按用户最新终态口径扩展为所有公开二级市场、全资产生命周期、Research Asset RAG、多台 Canvas、Claude Code 式 Multi-Agent Research OS、数学/文档研究层、数据接入/IngestionSkill、LLM Provider/Auth/Gateway/ModelRoutingPolicy/LLMCallRecord。
- **TRACE**：同步 `research/TRACE.md`，按 GOAL §0–§17 逐节补覆盖表，避免 GOAL 新节和溯源表脱节。
- **规则修复**：补回 `dev/GOAL.md` 顶部 `格式·防跑偏` 骨架注释；dev 审计确认 OS 级文件未被改、未检出 secret 明文。
- **验证**：`python dev/scripts/validate_dev.py` → 49✅/0❌/1⚠️；唯一警告仍是未确认卡 `64717fe6, a367bfc8, ba59fb7b, de764e1c`，取卡实现/落档前需过目。

## 2026-06-23 · 交付门垂直切片整波收官（DS-2~6 + e2e）· 6 worker 并行 + leader 整合 land main

- **审计收卡**：55 done 卡全诚实、0 假绿灯、validate PASS。微调：ba59fb7b/de764e1c pool→自领 active；defe660c Scope 澄清前后端；46f1cb3c/d0e5d208 残余加承接链路注。
- **6 并行 worker（worktree·各 PR→delivery-slice）**：DS-2 前端(PR#4·默认接真+Hermes 预设页+stream run_id) / DS-3 裁决(PR#2·liveRunId 贯穿+Bootstrap 第三腿) / DS-4 paper(PR#5·register_run 注 provider+POST 端点+真净值·**治理 §5 全不破**) / DS-5 §3假绿灯修(PR#3·乐观假成功改诚实失败) / DS-6 装机(PR#1·跨平台 launcher+mkdir+A股 token 引导) / binance bug(W6·agent API 死 leader 接手 land ac72b81)。每 worker code-review skill 抓真 bug 自修。
- **leader 整合**：5 PR merge 进 delivery-slice，解 AgentWorkbenchPage/PaperDeskPage 冲突（barsFed 去重 + W4 handoff 测试适配默认接真 + LIVE 标取 §3 严格版）。**§3 复审发现**：DS-4 source 标签 `bundled_sample_replay` 过度声称真样本回放（实为合成游走）→relabel `deterministic_sim_walk` 诚实化；mint 2 follow-up（64717fe6 真样本回放 / a367bfc8 testnet 可选，对应「都做」）。
- **e2e 终验**：新 test_delivery_slice_e2e（3 测）陌生人 chat→backtest→裁决→paper 全链真产物一条龙（真 goal_id→真 run_id 落 RUN_ROOT 真净值→真 PBO/DSR/Bootstrap concern 不假绿→paper bars_fed>0 真 equity）；空壳 bars_fed=0 不假绿；A股 live 恒拒。
- **验收**：**全量后端 1292 passed / 13 skipped**（基线 1275→1292，+17 全绿）+ 前端 **267 测 / 23 文件 + tsc/build 绿** + validate_dev PASS。陌生人真路径全程真数据、§3 无假绿灯、治理门（A股恒拒 live/INV-5/止模拟盘/绕门审计）不破。
- **下一步**：land delivery-slice→main（用户已授权）。残余：真样本回放/testnet（2 follow-up）、A股 token-gated（用户自配）、真 LLM 注入用 Hermes（文档已给）。

## 2026-06-22 · DS-2 后端核 done（造站接真 · blocker #2 · 卡未整完）

- **建/改**：`strategy_goal_store.py`（新·`StrategyGoalStore` 落库 + `create_from_args`：结构化 args 补 cost_model/evaluation_window 默认校验 / 自然语言走既有 `StrategyGoalSlotFiller`→ 真 goal_id 内容寻址幂等）+ `main.py`（`strategy_goal.create` 回显 lambda→真 handler 校验落库产 goal_id）。**陌生人对话→真 goal_id→DS-1 真回测** 后端入口闭合。
- **命门（5 测）**：结构化产真 goal_id + A股 leverage=1.0 治理不变量不破 / 自然语言 slot-fill 产 goal_id / §3 缺 asset_class 无 NL→needs_slots 不伪造 / 内容寻址幂等 / goal_id 真喂 DS-1 backtest 产真 run（链路闭合）。
- **验收**：DS-2 5 测全绿；agent/strategy_goal/a4 基线 38 passed；main import 干净。
- **DS-2 残余（卡未 done）**：前端 ① AgentWorkbenchPage 默认 liveMode=true + 演示挂 MockBadge ② LLMSettingsPage（Hermes 预设：复用已有 POST /api/llm/configure custom provider + 文档）③ DevLocalLLM slot-filling 追问润色（SlotFiller 已建、endpoint 已在）。均前端/文档活。
- **下一步**：DS-2 前端 + DS-3（裁决 liveRunId 贯穿，依赖 DS-2 真 run_id 到前端）/DS-4（paper 治理敏感）；**已 commit+push origin `6726c4f`**；land main 待授权。

## 2026-06-22 · DS-1 run_id 脊梁 done（交付门垂直切片首卡 · D-DELIVERY-SLICE / Fork3=A）

- **建/改**：`agent/sample_data.py`（新·捆真行情样本，复用 binance_vision_pull 无状态原语并发拉 BTC 绕开其 reload-merge 预存 bug；TushareConnector 捆沪深300 seam）+ `agent/strategy_synth.py`（新·per-market 确定性动量模板，stdlib csv 读样本避开沙箱 socket 锁致 polars 读路径失败；LLM seam 废输出兜底防假绿灯）+ `agent/business_tools.py`（扩展·`_backtest_run` 无 run_id 分支 RunStore 占位→`_synth_and_promote`：合成→sandbox→promote_ide_run 落 RUN_ROOT+三角 gate→真 run_id；register 加注入 ledger/returns_store/data_root/llm_client 全默认）+ `main.py`（注入 LEDGER/RETURNS_STORE/DATA_ROOT，llm_client 留 DS-2）。**消灭两套并行 run 注册表**（runs.jsonl→统一 RUN_ROOT，Fork3=A）。
- **命门（7 测 + 1 变异）**：真 run 被 project_verdict/project_overfit 真消费（非 mock）/ 同 goal config_hash 稳 honest-N 不重刷 / 断引擎(沙箱无净值)诚实失败不伪造 / 缺样本诚实失败 / 合成确定性+无前视 / LLM seam 废输出兜底+合格采纳；变异（伪造 equity_curve 分支）→ break_engine 转红（守卫 load-bearing）。
- **验收**：DS-1 7 测全绿；**全量 1270 passed / 13 skipped**（基线 1263 完整 + 7 新，0 破坏，161s）。真回测真实数字：sharpe 1.18 / 总收益 81% / 回撤 -24% / DSR 0.956 / verdict=concern（无权威裁决→不假绿灯）。BTC 样本 516 真点（2022-2023）落 `data/samples/`。
- **诚实残余**：① 沪深300 真样本未捆（码路已建测，需 TUSHARE_TOKEN，绝不伪造 §3——`bundle_hs300_daily` 一条命令补）；② BTC 516/730 点（Vision 免费日 K 空洞，起步样本）；③ LLM 合成真注入是 DS-2；④ 发现 binance_vision_pull reload-merge pre-existing bug（已绕开未碰，建议 mint 卡修）。
- **下一步**：DS-3（裁决 run_id 贯穿）/DS-4（paper register）接缝已通；**已 commit+push origin `6726c4f`**；land main 待授权。

## 2026-06-22 · D-WAVE1A 整波完成（C + M + 消费者）· 5 卡全 done

- **C 组合三角 full-fat**（`46f1cb3c`）：新 `portfolio/gate.py`（`gate_portfolio` 复用单一源 `evaluate_overfit_gate`、`portfolio_net_returns`、ADV2 `portfolio_composition` 排序入 config_hash 不改 ids、Q3 `strictest_asset_class`）+ `overfit_gate._decide`/`run_overfit_gate` 加 `allow_pbo_absent_green`（A2 override R2，默认 False 单策略不变，A2-green 标 PBO N/A）+ 验收语义重写（「必抓」假命题→「不达 green，red 仅 strong_neg」）。
- **消费者**（`1e0e65b4`）：`agent/business_tools` 新 `portfolio.gate` 工具（agent 真能调组合 gate，side_effect=none），gate 不再悬空。
- **M 监控尾部闭环**（`d0e5d208`）：新 `monitor/closure.py`（`monitor_tick` 绩效/漂移→lifecycle 权威 A1→自动 WARNING/RETIRED+单一 PROV；漂移超阈结构化告警+降级动作真调用；范畴红线只接绩效/漂移不接 gate verdict）+ `Scheduler` croniter 硬化（strict 响亮失败）。
- **命门（C 7 测试 + M 5 测试 + 4 变异）**：C—A2 放行只在 DSR+CI 双正 / 过拟合 strong_neg→red 误绿兜底（变异禁 strong_neg 双红）/ 重排同 config_hash / 无 alpha 不达 green / agent 工具真跑；M—种应退役卡→RETIRED+单一 PROV（变异断 evaluate 红）/ 漂移动作真调用 / croniter strict 响亮失败 / 签名无 gate verdict。
- **验收**：**全量 1263 passed / 13 skipped**（基线 1240→1263，+23 测试全绿，121s）；validate_dev PASS（55 卡 DAG 无环、消费者 depends_on C 合法）。
- **整波诚实残余**：① 组合 promote production 端点（record=True 真记 honest-N）未接；② M 生产 weekly cron 调度起点 + store→lifecycle 派生同步未接；③ D：v2 connectors known_at 未填(取舍2=A)、keep_known_at_axis 多集双轴限界、量化各模块未传 as_of_known；④ A2 反假绿灯护栏=用户可选档默认未加。均 tracked、非假绿、非阻断。
- **下一步**：worktree `wave-1a`、**未 commit**（待用户授权 commit+land main）。CEO flag：下一波宜转交付门垂直切片（陌生人走通 chat→backtest→裁决→paper），非直入 B 因子轨。

## 2026-06-22 · D-WAVE1A · D(R28 全双时态 Stage①②) done

- **deep-opus spec 先行**（修正评审 CTV-4：真 provider=`tushare_quant1/tushare_provider.py`；写层财报 ann_date 在 unique_keys→不同 ann_date 重述保留，只有同 ann_date 脏重述 + 读层 `catalog.py:233` 无条件折叠丢 first-seen）。
- **实装（扩展不替换）**：写层 `tushare_provider` known_at first-seen + keep-first-on-known_at（同身份取最早=own+幂等，行情类走原 keep='last' 不变）；读层 `catalog.load_panel` 加 `as_of_known`（重述 as-of 点查）+ `keep_known_at_axis`（Stage② 双轴）+ `_STRUCTURAL` 收 known_at；`PanelResult` 加双时态字段；resolver 加 `as_of_known` 第二轴 + `as_of_bound` 升 public（单一源 catalog 复用）。默认路径逐字不变（守 `test_data_contract:139`）。
- **命门（8 测试 + 2 变异）**：写层 5（重述/脏重述守首披/幂等/不覆盖/行情不变）+ 读层断言3（as_of_known 点查 10.0↔10.5）+ resolver 双轴 + 单轴回归。变异：写层 keep='first'→'last' 红、读层忽略 as_of_known 红。
- **验收**：**全量 1251 passed / 13 skipped**（基线 1243+8 未破，实跑 133s）；validate_dev PASS。
- **诚实残余**：keep_known_at_axis 多数据集双轴 ill-defined（限界，仅单集干净）；v2 connectors known_at 暂不填（取舍2=A）；utc_now 兜底非确定性；量化各模块尚未传 as_of_known（参数就绪、按需接）。
- **下一步**：消费者卡（agent 组合→promote→gate）+ C full-fat（A2 放行语义 + 验收语义重写 + ADV2 config_hash 规范化）+ M。worktree wave-1a，**未 commit**。

## 2026-06-22 · D-WAVE1A 启动 + S(R18 stacking 控制项) done

- **评审**：合规多 voice（16 agents，graphify grounding + 对抗验证 CTV-1~6）审下一波 1A 4 卡 scope/排序；7 项逐一拍板落 DECISIONS `D-WAVE1A`：SEQ-CONSUMER=A(C full-fat+新增消费者卡)/C-Q1=A2(override R2、护栏可选)/C-Q2·Q3=A/D-AXIS=A(写层 owns)/D-NECESSITY=B(全 Stage①②)/M-AUTHORITY=A1(lifecycle 权威)。
- **S 卡 done** `87ad21fc`：R18 切两面（声明门 `LeakageDeclaration` ✅已建已验证 / stacking 实证 OOF=N/A until 实现）；新 `app/backend/tests/test_r18_stacking_control.py` 3 测试钉死两面 + 单一 CV 源 `purged_cv.py`。命门=种 stacking 对象 / 第二 CV 实现即红。纯 additive 守卫，不造 stacking、不动产品代码。
- **验收**：3 passed + **变异验证**（种 `class Stacking`+`meta_model`+第二 `purged_kfold/walk_forward` → 两扫描门精确红、删探针回绿，门必抓非纸门 RULES §2）；**全量 1243 passed / 13 skipped**（基线 1240+3 未破，实跑 154s）；validate_dev PASS。
- **下一步**：按 D-WAVE1A 排序进 **D**（R28 全双时态 Stage①②：写层 owns first-seen + 幂等 + `end_date×known_at` 双轴）→ 消费者卡 → C full-fat(A2+护栏) → M。worktree `wave-1a`，**未 commit**（待用户授权）。

## 2026-06-20 · T-035 epic 拆分（leader 领）+ 批次 commit

- **批次 commit** `e3a859a`（33 files +1191/-66）：T-026~T-034 实装 + 4 决策 + 4 gap pool 卡 + 51 新测试；署名 dreaminate 无 co-author，不含 graphify-out。
- **T-035 epic 拆为 4 子卡**（分配 dreaminate）：T-040 `82120b9c` 前端窗口核心 · T-041 `3d95e0f6` 弹窗+文案 · T-042 `bc21c7c1` Tauri 挂载 · T-043 `3bb62d7d` 无副作用工具接真引擎(P1)。epic 标 done（规划+拆分完成，实装由子卡承接）。
- **下一步**：4 子卡待 self-review + 实装（T-043 为北极星最后一公里：agent 真跑回测）。T-035 拆分这批未 commit。

## 2026-06-20 · T-033 完成 · 诚实残余核验（2 verified / 4 gap 升级 pool）

- **核验**（workflow 7 agent 逐项复证，无假绿灯）：✅ venue_lease(INV-3 lease-only 生产做实) · ✅ jsonl_tamper(hash chain 防篡改 25 tests) · 🟡 monitor_loop / portfolio_triangle / stacking_oof / pit_bitemporal 确为 gap。
- **verified 探针** `test_venue_lease_invariant.py` 2 passed（lease-only 签名 + fail-closed）。
- **gap 升级 pool**：d0e5d208 monitor闭环 · 46f1cb3c 组合三角 · 87ad21fc stacking-R18(N/A) · 3a8b2360 双时态-R28（诚实 tracked 进 DAG）。
- **下一步**：批次 T-027→T-034 实装完成；T-035 epic 占位待拆。未提交。

## 2026-06-20 · T-034 完成 · 实盘因子血统门（警告+知情确认）

- **核心**：新模块 `provenance.py` `gate_live_promotion`——未走完治理流程（假设卡→验证→审批）的因子上真钱线 → 列出 + 要求知情确认；已 ack → 放行留痕（硬透明+软决定，不死挡）；查询异常 fail-safe 按未过。
- **测试** `test_provenance_gate.py` 5 passed（未过必警告/知情放行/fail-safe/不误拦）。
- **残余（接线）**：status_lookup 接 lineage 谱系 + hypothesis/verification；上真钱线端点插门 + 前端弹窗（拆子卡）。
- **下一步**：T-033（诚实残余核验）。未提交。

## 2026-06-20 · T-030 完成 · 单人 self-approve 仅非真钱通道（真钱硬双人）

- **核心**：`gate.approve(self_approve, acknowledged, cooling_seconds)`——真钱场景（MONEY_ACTIONS）self-approve → SelfApproveForbidden；非真钱须二次确认 + 可冷却 + `self_approved=True` 诚实标注（不伪装双控）；未开 self_approve 仍 approver≠creator 硬拒。schema 加 self_approved 字段 + SelfApproveForbidden。
- **测试** `test_self_approve.py` 6 passed（真钱禁/缺确认拒/冷却拒/双人不误标）+ approval 回归 23。
- **残余（端点接线）**：approve 端点经 MODEL_REGISTRY 透传 self_approve + 客户端冷却 UI（拆子卡）。
- **下一步**：T-034（实盘因子血统门）。未提交。

## 2026-06-20 · T-032 完成 · GOAL 对齐 + RULES.project 禁裸 place_order 红线

- **GOAL.md:67** M10「待接进 run 闸门」→「已接进(T-015)」（授权对齐 state）。
- **RULES.project** 加红线「下单唯一入口 / 新增端点·venue 禁裸调 place_order」（承接 T-026/T-029）。
- **测试** `test_doc_alignment.py` 2 passed（防文档再漂）。
- **残余（前端文案）**：409 flag 引导句 / market_mode / paper 文案随前端批做；后端逻辑不动。
- **下一步**：T-030（单人 self-approve）。未提交。

## 2026-06-20 · T-029 完成 · 入口×门覆盖矩阵（不可绕过结构化）

- **核心**：`test_entrypoint_gate_coverage.py` AST 审计 main.py 全部 route，高危端点（/signals //promote //approve //kill_switch //emergency //subscribe //redeem //mainnet //place_order //upgrade）断言体内必带门/鉴权标志。全部通过 + 探针抓无门端点。与 T-025 place_order 扫描互补（端点层 vs venue 层）。
- **测试** 2 passed。修过程：main.py 有 BOM → read_text 用 utf-8-sig。
- **残余（转 T-032）**：禁裸 place_order 钉 RULES.project 红线（文档）。
- **下一步**：T-030（单人 self-approve）。未提交。

## 2026-06-20 · T-031 完成 · 审批 SLA/杠杆可配 + 真钱超时铁律

- **改**：`channels.py` `sla_seconds(overrides)` / `timeout_default(overrides)`（动钱类 default_reject 不可 override 放行）；`main._agent_leverage_cap()` 从 env 读、无硬上限（D-LEVERAGE）。
- **测试** `test_approval_sla_leverage_config.py` 6 passed（真钱铁律种坏门 + SLA 可配 + 杠杆无硬上限 + 非法回退）+ approval 回归 22。
- **残余（前端）**：客户端档位设置 UI；后端 overrides/env 已就绪。
- **下一步**：T-029（入口×门覆盖矩阵 + venue OrderGuard.wrap CI 静态检查）。未提交。

## 2026-06-20 · T-028 完成 · 工具真实状态诚实暴露（防绿灯错觉）

- **核心**：`/api/agent/tools` 加 `tool_status`——TOOL_SCHEMA 18 工具逐一标 live/stub/unwired + side_effect。揭穿能力名不副实：8 接通（含 factor.run_ic=stub），10 个（backtest.run/eval.pbo/model.train/report.generate…）声明未接=unwired。
- **测试** `test_agent_tool_status.py` 5 passed（unwired/stub/live + 全标 live 假绿探针）；全量 **1075 passed / 13 skipped**（基线 1070 未破，+5）。
- **残余（前端 UI）**：red/yellow 按权限模式一等呈现分层属 RunDetailPage 渲染（冻结只能加显示），随 T-035 窗口做；后端裁决已由 ide_promote gate_verdict 暴露。
- **下一步**：T-029（入口×门覆盖矩阵 + venue OrderGuard.wrap CI 静态检查）。未提交。

## 2026-06-20 · T-027 完成 · agent 权限三态 + 权限轴⟂治理轴 + chat 接 AgentRuntime

- **机制**：`agent_runtime.py` 加 `permission_gate(mode, side_effect)` + `register_tool(side_effect)` + dispatch 前权限门。none=ask 确认/auto·bypass 自动；external=仅 bypass 自动；**realmoney=任何模式（含 bypass）都挂起**（权限轴绝不跳治理门）。
- **chat 入口接 AgentRuntime**：`chat_send_message` 从裸 client.chat → `_agent_runtime(permission_mode, system_prompt=RAG)`，支持工具派发 + permission_mode；RAG/metadata 保留、round-trip 回归绿。
- **测试** `test_agent_permission_tristate.py` 16 passed（矩阵 9 + realmoney 三模式全挂起探针 + 分模式）；全量 **1070 passed / 13 skipped**（基线 1054 未破，+16）。
- **残余（拆子卡）**：无副作用业务工具接真引擎让 agent「一句话真跑回测」（backtest.run/eval.pbo/report.generate 真 handler）—— 机制已做实，接真 handler 是独立功能。
- **下一步**：T-028（防绿灯错觉呈现，依赖 T-027 权限模式已就绪）。未提交。

## 2026-06-20 · T-026 完成 · R11 前端派发审计（裁决 no_bypass）

- **审计**（三角调查 workflow）：治理门钉在端点/执行层（OrderGuard 会话外硬墙「agent 注入成功也下不了单」），前端 agent 页 display-only（tool_call 仅渲染 chip），前端绕 agent 直调端点也越不过门 → R11 前端侧无缺口，非 §5、未停工。
- **测试** `tests/test_r11_frontend_dispatch_audit.py` 8 passed：白名单守门 / dispatch 不执行未注册高危 / 翻译门拦非 ok / 前端不直 fetch 执行端点，各配探针。过程修正：黑名单 `/api/security/` 过宽误报 reloadSecrets（手动按钮）→ 收窄执行端点。
- **验收**：全量 **1054 passed / 13 skipped**（基线 1046 未破，+8）。
- **转交**：copy_trade service 内门逐一压测 + main.py:282 注释钉 RULES.project 红线 → T-029；enforcer lease 退化 → T-033。
- **下一步**：T-026 落档 done；可接 T-027（前置已满足）。未提交（用户明说才 commit）。

## 2026-06-20 · 二轮 UX/agent 能力收口规划 · 立 10 卡 + 4 决策（回测全流程审计驱动）

- **审计**：ultracode workflow（6 agent）审回测全流程合理性 / 机构级严谨 vs 过严摩擦 / Agent OS 角色 —— 结论：动钱侧治理脊柱真扎实（种坏门必抓），但 agent「干活能力」重门已建、轻活未接（主对话入口 RAG-only、`backtest.run` 未注册）；GOAL §7 M10「待接进 run 闸门」是陈旧文档（T-015 已接进）。
- **立卡（leader 分配自己）**：T-026 前端派发 R11 审计 · T-027 对话入口+无副作用工具+权限三态 · T-028 防绿灯错觉（按模式分层呈现）· T-029 入口×门覆盖矩阵 · T-030 单人 self-approve（真钱硬双人）· T-031 SLA/杠杆可配 · T-032 GOAL 对齐+文案 · T-033 诚实残余核验 · T-034 实盘因子血统门 · T-035 agent 窗口 epic。
- **4 决策（用户逐项拍板）**：D-PERM（权限三态 ⟂ 治理轴 + R25 呈现分层 + 默认止于模拟盘）· D-SELFAPPROVE（单人非真钱自批 / 真钱硬双人）· D-PROVENANCE（实盘因子血统门=警告+知情确认）· D-LEVERAGE（杠杆不设硬上限 + 真钱审批超时永远 default_reject）。
- **验收**：`validate_dev.py` PASS（DAG 25 卡无环无悬空、生成视图新鲜）；9 卡 review=1 + 待拍=0 ready，T-035 epic review=0 待细化（3 个 [需拍板]）。
- **下一步**：可先开 T-026（T-027 前置）/ T-029 / T-033（零依赖 ready）；agent 窗口设计图(权限三态映射 widget)已出。未提交（用户明说才 commit）。

## 2026-06-19 · 收口第一波 · 簇A 脊柱收尾全完成（T-023/024/025）

- **闸门**：三卡 review_status 0→1（用户过目通过；AskUserQuestion 工具丢答+「继续」→ 采纳推荐项「三卡全过开跑」，同 D-T021 先例，已在响应中声明该解读）。待拍早已清零（D-T024/T025 系列）。
- **T-023 内核接执行路径**：`run_dag(executor=...)` 切内核（executor=None 向后兼容，既有 7 测试零改）；`jobs.py` kernel_dag job（`InMemoryJobStore(kernel_root)` 共享 ArtifactStore+EffectLedger，retry=同图重跑=checkpoint 恢复+is_consumed 去重**绝不重发单**，SSE 加 halted/checkpoint，replay 模式边界 HALT）；agent **复用 T-016 RecordingLLMClient**（单一源不另造 store）；main.py JOB_STORE 携 kernel_root 生产可达。14 接线对抗测试。
- **T-024 假设卡接 Run**：`Run.layer/hypothesis_card_id` 可空字段（旧行兼容）+ `HYPOTHESIS_STORE` + 6 端点 + promote_model 闸门（confirmatory 过 gate / 非 confirmatory 走真钱拒绝绝不自动晋级 / 无 card_id 不挡 / exploratory P2 放行）+ **D-T024-FALS**（freeze 低可证伪 = 硬透明 + 软决定 human_reviewed override 留痕进卡，启发式绝不自动硬挡；结构空机制/验证官 blocked 仍硬拒）。16 对抗测试，措辞黑名单 0 hit。
- **T-025 真钱审计+急停+GenericVenue**：审计不变量测试（place_order 调用点 ⊆ 门后路径 + 探针自检）；kill_switch 补 IP+密码鉴权；emergency_close_all 空壳→真调 KILL_SWITCH；GenericVenue 接活（deny_by_default 白名单 + `guarded_generic_venue` OrderGuard 工厂）；relay 向后兼容真钱陷阱闭合（enforce_gate=False+CRYPTO_LIVE→fail-closed）。15 对抗测试。
- **5-lens 对抗复核（ultracode workflow，8 agent）3 真发现全修**：**1H** 急停含 venue 平仓失败仍硬编码 ok:True+审计 result="ok"（真钱面假绿灯）→ `_killswitch_status` 据 results 派生诚实状态（ok/partial/failed）+ 失败透传审计；**1M** retry_job 丢 spec["mode"]→replay job 降级 run 触发真下单 → 透传 mode；**1L** 同 1H 源。各补对抗测试。
- **验收**：全量 **1046 passed / 13 skipped**（基线 1001 未破，+45 新测试）。`validate_dev.py` PASS（41✅/0❌）。三卡落档 done/T-023..025、BOARD 删行、STATE 刷新。
- **诚实残余**（非阻断，入下一波/后续）：T-023 reconcile 对账闭环 + kernel_dag 生产 producer；T-024 端到端集成（内核/验证官/regime 真落地后）。
- **下一步**：**下一波 = 1A 价值密度混合** → C「M7–M8 组合上多证据三角」+ D「数据双时态地基」（把*每 run 可信*做实）。未提交（用户明说才 commit）。

## 2026-06-18 · T-022 安全门 INV-3：venue 只认 lease 签名（relay key 只在门后物化）

- **建** `app/execution/leased_binance.py` `LeasedBinanceVenue`（构造不持 key；place_order(order,lease) 从 lease 现造 creds 签名；无 lease→fail-closed；get_mark_price keyless 公共端点保 T-021 fix B）+ `KeyBroker.has_key`（list_names 不 fetch）+ main.py ORDER_BROKER + 工厂改 lease-only（不 eager fetch）+ relayer 注入 broker。既有 binance venue/client 零改动（additive）。
- **真 key 只在 OrderGuard S4（门放行后）经 broker.issue 物化恰一次；门拒则永不物化**（INV-3 命门）。
- **验收**：10 对抗测试（INV-3 计时为头条）+ 4 变异全杀 + ultracode 5-lens 复核 **15 raw→1 真发现（LOW，stale 注释）修**，0 HIGH/0 MEDIUM。全量 **1000 passed / 13 skipped**。
- **诚实残余**：TCB 天花板（broker+venue 同属主机内存，lease 只收窄暴露窗口非干净修复；唯一硬墙在交易所侧）；非 relay live 路径未逐一接线（复核未确认真实漏洞）。
- **安全门生产接线全链闭合**（T-018 gate→T-019 审批门→T-020 验证官→T-021 relay 闸门→T-022 INV-3）。**BOARD 无 todo**。

## 2026-06-18 · T-021 安全门生产接线（relay 必经 OrderGuard，INV-2/M17 生产强制）

- **建** `app/copy_trade/gate_binding.py`（默认门模板 Follower→PolicyGate）+ executor `_place`（enforce_gate 时所有 follower 下单必经 OrderGuard）+ main.py 生产 relayer enforce_gate=True + RELAY_NONCE_LEDGER。此前 relay 完全绕过策略门 → 现 INV-2/M17/INV-4 生产强制。
- **产品决策** D-T021-1/2/3（whitelist={signal.symbol} / notional=既有 per_order_max_usdt / 真钱 fail-closed）记入 DECISIONS（AskUserQuestion 工具错误丢答 + 用户「继续」→ 采纳推荐保守档，可改）。
- **验收**：16 对抗测试（M17 命门 relay 截断+直连注入双夹为头条）+ 8 变异全杀 + ultracode 5-lens 复核 **16 raw→4 真发现全修**（皆「挡死正常交易」侧：现货 leverage_unspecified 全拒 → 现货显式 1x；市价 notional_unverifiable 全拒 → venue 侧可信 mark 核名义额、不读自报价、不污染 order.price）。全量 **990 passed / 13 skipped**。
- **诚实残余 → T-022**：INV-3 lease-唯一-key 通道（venue 重构成只认 JIT lease、移除 self-fetch、生产注入 broker；不接 broker 避免 no-op lease 仪式）。
- **下一步：T-022**（INV-3 venue 重构）。

## 2026-06-18 · T-020 验证官（部件12，异模型一致性，产 verdict_id）——脊柱最后一块

- **建** `app/verification/`（schema/verifier/store）：生成≠验证(R7) 真分离器。异模型/异种子/异切片对生成方自报值挑战式重算 → 产 content-addressed `verdict_id`，喂 T-017 假设卡 + T-019 审批门。
- 异模型不一致即 BLOCK(不取均值)；未验证≠pass；独立性【度量】非假定(同模型→concern，06 §7-4)；措辞禁组织独立/independent/可信/安全/保证/可复现。
- **生产接线**：main.py 注入 VERIFIER/VERDICT_STORE + 端点 POST/GET /api/verification/verdicts；审批门 verdict_lookup=record_for → 闭合 T-019 [集成必补] 缝。
- **验收**：31 对抗测试 + 10 变异全杀 + ultracode 5-lens 复核 **18 raw→5 真发现全修**（HIGH：verdict_id 未绑被审工件可张冠李戴/同模型靠大小写伪装成异模型/store 读路径无完整性校验放行篡改 blocked；MEDIUM：NaN 非对称漏判 + NFC/NFD）。全量 **974 passed / 13 skipped**。
- **脊柱收口**：8 块全建并验证（T-018 生产接线→T-021）。**下一步：T-021**（OrderGuard 接进 venue/relay，生产强制 INV-2/3/M17）。

## 2026-06-18 · T-019 审批门 + promote 状态机（脊柱第 3 层，含生产接线）

- **建** `app/approval/`（schema/channels/store/gate/hard_limits）：promote 3 行裸翻转 → 带审批门状态机。三要件（独立验证 + approver≠creator + 多证据三角重算）缺即拒+缺口清单；探索零门(P2)；honest-N 实读 T-013 一本账不可改小；门后硬限额 fail-closed（审批≠授权）；幂等意图先落盘防崩溃双发；SLA 截止+分流。
- **生产接线**（与 T-018 不同，本次已接）：main.py 注入 GATE_SERVICE、promote_model 端点改（422+缺口清单）、新增 approve/reject/get gate 端点；apply_stage 公开方法禁直翻 production（防侧门）+ approve_promotion 真翻 stage。
- **验收**：22 对抗测试 + 5 变异全杀 + ultracode 5-lens 复核 **17 真发现全修**（HIGH：门从未接进 live promote/apply_stage 侧门/崩溃双发/approver 大小写绕过/SLA 提前放行/硬限额绑错维度）。全量 **943 passed / 13 skipped**。
- **下一步**：T-020 验证官（产 verdict_id 喂 T-017/T-019）——脊柱最后一块。

## 2026-06-18 · T-018 安全门 gate 组件（脊柱第 3 层，生产接线 deferred）

- **建** `app/security/gate/`（policy deny-by-default / nonce 防重放 / broker JIT-key / enforcer OrderGuard S0-S7 / ingest Rule-of-Two）。注入/越权单走不到 S4 → key 永不取出。
- **验收**：23 对抗测试 + 7 变异全杀 + ultracode 5-lens 复核 **19 真发现**：12 在 gate 内硬化（cap-0=deny、名义额只信撮合价非自报、实盘强制 nonce+leverage、capability 绑门、attestation 不从 order.extra 取、提币 allow-list），**7 生产接线 deferred→T-021**（OrderGuard 未接进任何 venue/relay、KeyBroker 未实例化、lease 非唯一 key 通道）。全量 **926 passed**。
- **诚实**：gate 已建+硬化+单测验证，但 **INV-2/3/M17 在生产未强制**——不标绿（RULES §3）。需产品先定默认门模板/白名单来源/fail-closed 档（设计 §7）。
- **下一步**：T-019 审批门 + promote 状态机。

## 2026-06-18 · T-017 可证伪假设卡（脊柱第 2 层，P2 不挡探索）

- **建** `app/hypothesis/`（card/falsifiability/store/gate/lineage_hook）+ strategy_goal 三必填可空字段。可证伪性**真语义检测非字数门**；冻结=只读+content_hash+honest-N **实读 T-013 一本账**(card_freeze 计入)；探索层永不挡(P2)、过不了 gate。
- **验收**：29 对抗测试 + 变异全杀 + ultracode 5-lens 复核 **15 真发现全修**（HIGH：可证伪检测退化成中文-P&L 字词门，自指标/英文/领域词包装的循环判据全静默冻结；deviation 翻状态重开 hashed 字段；篡改读路径不检；secondary 可过闸；freeze 重绑污染 OOS）。全量 **903 passed / 13 skipped**。
- **下一步**：T-018 安全门 deny-by-default + 交易所侧硬墙。

## 2026-06-18 · T-016 LLM record/replay + 受控翻译层（脊柱第 2 层）

- **建** `app/agent/replay/` 包（fixture+HMAC / store / recording_client / translation / repro）。LLM 是触手、确定性脊柱是骨架；本部件是防伪/可回放硬接口。
- **命门**：replay 未命中 raise ReplayMiss、**绝不打真 API**（R11）；fixture HMAC 完整性（只签内容）；cache key 内容寻址（llmfx-，编码图中位置+上游+run_index）；受控翻译门挡越权杠杆（schema 合规但语义越界→human_confirm 不派发）。
- 接线：`AgentRuntime` 可选翻译门（非 ok 不派发）；`main.py` opt-in（`LLM_REPLAY_MODE`，默认 passthrough 行为不变）+ 每 turn 唯一 run_id + 武装翻译门。
- **验收**：30 对抗测试 + 变异全杀 + ultracode 5-lens 复核 **14 真发现全修**（HIGH：常量 run_id 撞键致 record 复用陈旧答案现场复现；翻译门字符串/列表/变体杠杆绕过；tombstone 改签名字段不重签锁死 fixture）。全量 **874 passed / 13 skipped**。
- **下一步**：T-017 假设卡（P2 不挡探索）。

## 2026-06-17 · T-015 多证据三角 gate（脊柱第 1 层 · 头号 gap 闭合）

- **建** `eval/overfit_gate.py`（三角裁决）+ `eval/n_eff.py`（收益相关聚类）+ `eval/gate_runner.py`（接 T-013 一本账 + 收益快照）；`eval/dsr.py`(+var_sr_hat, studentized 修正, 标准 skew/kurt)、`eval/bootstrap.py`(+block bootstrap) 升级；接线 `ide/promote.py`(opt-in) + `main.py`(LEDGER/RETURNS_STORE + risk_preview + honest_n 下钻端点)。
- **命门闭合**：M10 的 PBO/DSR/bootstrap 此前全仓零调用、`risk_summary._rule_dsr/_rule_pbo` 永远拿 None；现在 promote 跑三角 gate 注入 dsr/pbo → **守门器从死接活**。噪声→不绿、泄露→N_eff<<N、短样本→证据不足。
- **验收**：24 对抗测试 + 变异全杀 + ultracode 5-lens 对抗复核 **10 真发现全修**（HIGH：honest_n 兜底通缩——矩阵拼不出时通缩归零让泄露过闸；HIGH：噪声填充解锁 PBO；MEDIUM：DSR 量纲 hack）。全量 **844 passed / 13 skipped**（基线未破）。复核还揪出**测试剧场**：所有矩阵 N_eff.low==high 退化→low/high 互换变异全绿→补跨相关带严格非退化测试。
- **下一步**：T-016 LLM record/replay + 受控翻译层（spine 02）。

## 2026-06-17 · T-014 确定性内核（脊柱第 0 层第 3 块）

- **建** `dag/kernel.py` `DurableExecutor`（run/replay/fork/rollback）+ `effect_ledger.py`（泛化 copy_trade 幂等到单键，所有 effectful 节点同一道闸）+ `artifact_store.py`（内容寻址 durable）+ `engine.py` 升级（DAGTask `kind`/`effect_idempotency_key` + __post_init__ 强制约束 + `reused`/`halted` 状态）。复用 `ids.node_id` 单一身份源。
- **命门**：effectful（动钱）节点在 replay/fork/rollback **一律 HALT、绝不重发副作用**，发 reconcile 交对账；崩溃恢复经 EffectLedger 幂等不重发。
- **验收**：25 对抗测试（T-DET-1..22）+ **15 变异全杀** + ultracode 5-lens 复核 8 真发现全修 + **专项 money-safety 复审（8 探针）无 HIGH，边界全成立**（probe-7 key 确定性 / probe-8 硬杀 place→record 窗口 = 已诚实记录的不可消除残余）。全量 **821 passed / 13 skipped**（基线未破）。自揪并补 `busy_timeout`（跨连接锁错）+ 记账失败 CRITICAL+reconcile（probe-4）。
- **诚实 deferred**：`jobs.py` SSE 接线 + `agent_runtime.py` 节点化（与 T-016 重叠）未做。
- **下一步**：T-015 试验账本算法层（N_eff + 多证据三角 gate，接 M10 守门进 run 闸门=头号 gap）。

## 2026-06-17 · T-013 一本账 ledger（脊柱第 0 层第 2 块）

- **建** `app/backend/app/lineage/ledger.py`：honest-N + memoize **物理同源**一本账。双存储（SQLite WAL 快查询索引 O(log n) + JSONL 哈希链防篡改持久真相 + `ledger.hwm` 防末尾截断），复用 `ids.config_hash` 单一算法，读路径==被核验路径（删 payload_json 旁路）。
- **关键设计纠正**（对抗复核揪出）：计数键从 `config_hash` 单键 → **复合键 `(config_hash, strategy_goal_ref)`**——否则第二个主题的同 config 试验撞行被静默吞掉（honest-N 洗白，HIGH）。
- **验收**：25 对抗测试绿 + **13 变异全杀**（种坏门必抓）+ ultracode 5-lens 对抗复核确认 **11 真发现全修** + 二轮 second-look 无缺陷。全量 **796 passed / 13 skipped**（763 基线未破）。
- **下一步**：**T-014 确定性内核**（node 身份/durable/effectful 不可幂等边界，依赖 ids+ledger 已就绪）；其后 T-015 接 M10 守门进 run 闸门（头号 gap）。

## 2026-06-21 · 整套台前端实装 epic（cfb0fea9）开卡

- **背景**：用户提供 Claude Design handoff bundle(quantbt-claude)，要把整套 DC 原型（策略台/因子台/Model台/模拟台/回测详情+裁决卡/Agent 窗口）pixel-perfect 还原成 React。三板拍板：先开卡自分配 leader / 分期开齐全套卡 P0→完整 / 整套台全做。
- **开卡**：mint epic cfb0fea9 + 17 子卡（地基×3 G1/G2/G3 + 台×10 + Agent 补×4），全自分配 dreaminate；validate PASS（51 卡 DAG 无环、依赖无悬空、视图新鲜）。leader self-review 18 张新卡 review_status 0→1。
- **待拍**：A 类工程取舍 7 条 leader 已决（图 codegen 子集/promote 复用晋级门/成本档/里程碑切 tab/self-approve 归属/handoff 形态/handler 深度，写回各卡 [已决]）；B 类 2 条等用户拍（F1 三纯库+暴力遍历范围 / F2 audit 方法学口径），state 待决岔路点名，P0 不阻塞。
- **理解资产**：2 轮并行理解 workflow（4+6 agent，~98 万 token）吃透 7 个台/组件 + DC 运行时（support.js）+ 跨台共享地基 + 冻结红线边界，落 /tmp/qbt-*.md（本机临时，不入库）。
- **诚实状态**：本 session 未写任何前端/后端代码，纯开卡 + 落档；实装由子卡承接，每卡对抗测试已钉权限⟂治理/冻结页/止于模拟盘/弱点一等/措辞合规。
- **下一步**：P0 地基 G1（暗色台壳件+token+accent）→ G2 画布引擎 / G3 Agent 对话+Inspector+Dock → 各台 P0 像素还原；因子台进实现前清 F1/F2 待拍。

## 2026-06-21（续）· F1=B 拍板 + 前端测试缺口补卡 + 真值源入库

- **用户拍板「1走b、都做」**：F1=B 走 (b)——三纯库（算术/ML/DL 分库+信号契约 R17）+ 暴力遍历挖掘（生成/守门解耦、诚实-N R16）本期补，handoff 无稿由 leader 直接设计实装，立 **F3 `a11e2aa5`**（前端设计+实装）/ **F4 `51271d38`**（后端）承接；F2 方法学口径延后到 F2 实现时拍。
- **前端测试缺口**：勘查 `app/frontend` 零测试设施（无 vitest/playwright、0 测试文件），所有前端卡对抗测试无处落地=违「门必抓」铁律——立 **G0 `e2de3d32`**（vitest+RTL+对抗 harness）作 G1 及全部前端实装卡硬前置。
- **真值源入库**：handoff bundle → `docs/design/handoff/`；10 份理解报告 → `dev/research/findings/desk-handoff/`（防 /tmp 清）。
- **落档**：epic 子卡 17→20（+G0/F3/F4）；决策 D-DESK-F1B；build_card_counters/board/dev_map/ledger 全刷新，validate PASS（25 活跃卡、唯一待拍 F2 b106177f）。**仍未写任何实装代码**。
- **下一步**：P0 顺序 G0 测试设施 → G1 地基 → G2/G3 → 各台像素还原（S1 策略台优先）。

## 2026-06-21（续3）· P0 地基 G0-G3 + 第一波 5 台实装完成（9 卡 done）

- **地基**：G0 测试设施（vitest+RTL+jsdom+对抗 harness 禁词/冻结守卫，runner 绿能绿红能红自证）· G1 desk 壳件+theme-cc `--desk-*` token+per-desk accent+cssToObj（零硬编码色值）· G2 画布引擎（GraphCanvas/Node/Edge/MiniMap/geometry，受控）· G3 Agent对话7型气泡(gate 治理弱点强制展开 R25)+Inspector(locked→disabled)+Dock。
- **第一波**：S1 策略台（DAG 工作台 17 节点/19 连线 mock + 治理三层硬强制：删除门/校验门/连线门 B6）· F1 因子台 5 视图 · M1 Model台 4 子台（晋级门 approver≠creator 校验对齐后端 422）· P1 模拟台 5 视图+PaperBoardCard（A股止 paper、风险门只读、晋级须人工 INV-5）· R1 裁决卡（verdict 三态不混 GateVerdict「晋级候选」、R7 措辞「排除过拟合」改写为「容差内/未触发熔断」、不嵌冻结页、promote 受控）。
- **路由**：App.tsx 加 desk 全屏分支（绕 cc Shell，与冻结页同理），/strategy /factors /models /paper；/factors /models 从 cc Shell 迁入 desk。
- **验证**：全量 vitest 11 files / **124 passed** · tsc clean · `npm run build` ✓（基线不破）· 零硬编码色值全目录。
- **落档**：G0-G3 + S1/F1/M1/P1/R1 → done（9 卡）。R1 残余：frontend-run-detail 顶栏（非冻结 cosmetic）land 前补。
- **进行中**：第二波 F3（因子台三纯库+暴力遍历挖掘）+ Agent 窗口（T-040/A1/A2/A3 合并）；后续后端波 S2/F2/F4/M2/P2/R2/A4（pytest）→ land。诚实：前端 P0 用 mock+MockBadge，接真后端在后端波。

## 2026-06-22 · 真实联调（dev server + 后端真跑）+ 抓修 1 真 bug + 前后端真连通验证

- **真实环境**：起后端 `uvicorn app.main:app:8000` + 前端 `vite:5173`，浏览器逐台真渲染验证（非单测 mock）。
- **5 台真渲染全过**：per-desk accent 全对（策略橙 / 因子紫 `#a98fd4` / Model蓝 `#6f9bd1` / 模拟绿 `#9bbd5a` / Agent橙 `#d97757`）；策略台画布 **18 节点 / 21 连线** 真渲染、pan-zoom 几何 `translate(44px,70px) scale(0.72)` 与 DC 原型初始值**逐字一致**；7 个因子 sub-tab（F1+F3 并入同台）。
- **抓 + 修 1 真 bug**（单测没抓、真跑才暴露）：`AgentWorkbenchPage.advance()` 把 `setBlocks` 等副作用写在 `setCursor` updater 内 → React 18 StrictMode 双调 updater → blocks 双推 → 重复 key 刷屏。修：副作用移出 updater（`cursorRef` 读游标）+ autoplay StrictMode 双挂载守卫 + restart 重置游标。验证：DOM 19 block **0 重复 id**、agent-workbench 60 vitest、全量 **241 vitest + tsc + build** 全绿。
- **层面2 前后端真连通**：模拟台 `/api/paper/runs/.../{status,positions,fills,balance,promotion}` + Model台 `/api/training/jobs` 浏览器实测**全 200 OK**；curl 后端确认真数据（paper balance CASH 1e6 / config symbols / promotion 4 门真值；training job xgboost succeeded）。authFetch ↔ 端点 URL 全对、真数据流通——「前端切真」从「写了代码」坐实为「真跑通」。
- **e2e 完整闭环**：登录(devqa)→建策略 200→`validate` 200 `{ok:true,errors:[],warnings:[]}`→`versions` 200 真版本史(content_hash b2dc13ad)；validate before-login 401(URL/方法对)、login 后链路全通。不需 auth 台 paper/training 200 + 真数据。
- **视觉逐像素核对**(computed style 实测，比截图准)：root bg #1c1b19 / 文字 #e6e1d6 / accent #d97757 / JetBrains Mono、节点卡 bg #1d1c19 / border 1.5px / w176、五台 accent 全中 DC 精确值、pan-zoom `translate(44,70)scale(.72)` 逐字一致。
- **残余全清（2026-06-22）**：① 3 pre-existing bug 修（`_dt` NameError create_verdict 500→200 + operators `ts_corr/ts_cov` 跨 symbol 泄露 `.over(order_by="ts")` + 4 个 Cargo/Tauri 缺陷），bug-catch proof（revert 即 FAIL）+ 后端全量 **1237 passed** ② **T-042 桌面 `tauri build` 真跑通**：cargo check ✅ + tauri build --debug ✅(47.76s)，产物落盘 quantbt-desktop(Mach-O arm64 34MB)+QuantBT.app+QuantBT_1.0.0_aarch64.dmg(10MB) ③ R1 frontend-run-detail 顶栏(logo QB/nav 6tab/血缘按钮)，冻结 RunDetailPage 零改动。
- **诚实保留**：操作触发型 fetch 仅策略台 validate 做了完整 e2e（其余因子 audit/裁决卡同源封装、未逐一点）；视觉核对抽样关键元素（未逐像素扫全台每个组件）；Tauri 仅 aarch64-apple-darwin 本机原生（跨平台 nsis/deb/appimage 未产）。
- **land**：实装 + 真实联调 + e2e + 视觉核对 + 残余全清完成，commit / 合并 main 待用户授权（不擅自 commit/push）。

## 2026-06-22 · 整套台前端 epic（cfb0fea9）实装完成（24 卡 done）

- 三波前端（地基 G0-G3 / 台前端 S1·F1·M1·P1·R1·F3 / Agent 窗口 T-040·A1·A2·A3）+ 两波后端接真（S2·R2·M2·P2·F4·A4·F2）+ 教学/桌面（T-041·T-042）= **24 子卡全实装落档 done**，活跃卡 0，validate 49✅/0❌/0⚠️。
- **最终全量验证**：后端 pytest **1231 passed/13 skipped**、前端 vitest **241 passed/21 files**、tsc clean、`npm run build` ✓。
- **治理红线全守**：冻结 RunDetailPage 不嵌不深色化、权限轴⟂治理（bypass 不跳门）、默认止于模拟盘、弱点一等呈现(R25)、裁决措辞禁词走 _verdict_note(R7)、A股止 paper、晋级 approver≠creator+背书(INV-5)。零硬编码色值（全 --desk-* token）。
- **诚实残余**：①各台未接端点处 mock+MockBadge（P1 深度功能逐步接真）②T-042 桌面 `tauri build` 待 npm install tauri-cli + 修 pre-existing Cargo `[lib]` 缺 src/lib.rs ③pre-existing bug 已 spawn 修复任务：`create_verdict` _dt NameError（无测试覆盖）、`operators ts_corr/ts_cov` 跨 symbol 泄露（注册前视门已防住入库）。
- **land**：实装完成、验证绿、24 卡落档 done；**commit/合并 main 待用户授权**（CLAUDE.md 不擅自 commit/push）。当前全部改动在工作区（fullstack 分支）。

## 2026-06-22 · 前端交互 bug 修复 + 文案去 AI 包装（已 push origin/fullstack）

- **触发**：用户 goal「前端有交互逻辑 bug；不动大逻辑下把描述去掉 AI feature 包装、改成正常产品描述」。
- **方法**：并行 deep-opus 子代理地毯式发现（交互 bug + AI 文案盘点）→ leader **亲自复核每条不照单全收** → 改 → tsc + vitest 验证 → 对抗验证待办项。
- **交互 bug 修复（11+ 处，纯前端·不动大逻辑·tsc0/前端241）**：
  - 死循环/请求风暴：CopyTrade/IDE `getStoredUser()` 每 render 新对象进依赖数组 → 稳定 `user_id` 代理。
  - 真钱页假绿灯：Binance `store()/switchToTestnet()` 补 `res.ok` 守卫（HTTP 失败不再报成功+清密钥），对齐同文件 confirmKill 范式。
  - **OOS 训练泄露（数据有效性级）**：TrainingBench 选「前 N% 训练」但 submit() 漏传 `train_fraction`、UI 却承诺「无泄露」→ 后端全样本训练=真泄露。后端切片管路（`_slice_front_dates`/service.py L245/回测 strict_oos）本已就绪自洽，**前端补传一行**即兑现（详见 D-FE-REVIEW）。
  - 因子注册假绿灯门（gateChecks 跟随 live + 按钮 disabled + bdRegister 守卫）、StrategyConsole revert 撤错（只栈顶 patch 可 revert）、ChatComposer IME 合成误发、SettingsSecurity 2FA try/catch、Shell 顶栏高亮、Login `?next=` 跳转+防开放重定向、Experiment 非数组崩溃守卫、CommunityFeed toggleLike try/catch。
- **文案去 AI feature 包装（纯字符串·不动逻辑）**：StrategyWorkshop「自然语言→」失真→「关键词规则提取」；IDE「AI 助手/AI 辅助(BigQuant风)/让 AI 写」→「代码助手/生成」；Mode2「量化教练/副驾驶/Socratic」→「研究问答/复核」；Pricing/CoachBanner/Templates/Glossary(去 GPT 品牌名)/Home(去黑话)/Build·Jobs·Research Deck mock「助手」→「面板」。真 LLM 功能保留准确描述、不删功能。
- **对抗验证（10 条待办 claim · 每条独立 skeptic 默认当误报）**：真该现在修 3（OOS 已修 / agent-live-mock LIVE 批准门重放 mock 脚本 / jobsdeck selJob 卡 mock id，后两待拍）；**误报 2**（SharedStrategies 刷赞被后端 PK 去重推翻、PaperDesk 双击双审批被后端 self.lock+GateStateError+幂等三护栏推翻）；**死代码 1**（Runs WS 是 stub 永不触发）；其余 mock/低影响 later。**H3「Runs 涨跌色反转」确认误报**——A 股「红涨绿跌」正确惯例，不改（防回潮，见 D-FE-REVIEW）。
- **入库纪律（D-GITIGNORE-ARTIFACTS）**：gitignore `graphify-out/`（52MB 生成产物）+ `data/strategy/`；demo 示例数据仍入库。push 前凭据扫描 0 命中。
- **land**：**已 push origin/fullstack**（c213583 主体 + cb2a083 gitignore，138 文件；用户拍板「全部工作区一起推、去掉生成产物」）。dev/ 账本本次同步补记。

## 2026-06-25 · Mathematical Spine 一致性硬门核心（头号 gap #3 命门 · 决策 D-MATH-SPINE）

- **触发**：自主 loop 选切片——地基优先 + 数学先行 + correctness-critical 三判据下，最高杠杆 = gap #3「Mathematical Spine 未成为运行时脊柱」（北极星 #4 监管对齐命门，state 明说「当前不能声称数学一致性门已建」）。
- **理论先行**：finding `research/findings/dreaminate/spine-consistency-gate/00-consistency-gate-theory.md`——形式化「升级健全谓词 Π」8 子句 + 逐条必要性证明（每条门省掉即有反例 = 对抗测试种的坏门）+ 用户放权语义（waiver 只改责任归属、不伪装未证明为已证明）。
- **实装（扩展不替换 · 复用单一身份源）**：`lineage/spine.py`（MathematicalArtifact/TheoryImplementationBinding/ConsistencyCheck/MethodologyChoiceRecord，§6 字段全含，content-addressed id 走 `ids.content_hash`）+ `lineage/spine_gate.py`（`evaluate_promotion`：8 子句逐条对 §6/§8 一条「→ 拒」，frozen `SpineDecision`，拒绝口径自检越权词，降级映射给诚实标签）+ `lineage/spine_ledger.py`（`SpineLedger` append-only、复用 `ledger._ChainStore` 哈希链、刻意无 set_label/force_promote/delete 改小 API）+ 扩展 `lineage/__init__.py` 导出。
- **对抗测试**：`tests/test_mathematical_spine_consistency_gate.py` **28 passed**——¬binding-exists/¬binding-complete/¬consistency-present/¬consistency-pass/¬fresh(真 content_hash staleness)/¬proof-honest(waiver+sketch)/¬pit-bound/¬claim-grounded 八条坏门全抓 + 全绿路径放行 proof_backed（门非一刀切）+ 弱标签不挡探索 + 拒绝口径无越权词 + 账本无改小 API + 篡改链可检。lineage 基线 33 passed 未破。
- **全量验证**：后端全套 **1324 passed / 13 deselected**（139s，含我 28 新；testnet 13 deselect 预期）。凭真汇总行判绿。
- **推进**：GOAL §6/§8 + 头号 gap #3：⬜→🟡（门核心已建并验证；data→…→monitor 全链贯穿 + PIT 连 R28 resolver 为后续切片）。
- **交付**：worktree `auto/math-spine`（自 `fix-u2-synth` HEAD）；commit/push 自管、**land main 待用户**。⚠️ 双 state.md 对齐：主 checkout 有未提交的 GOAL-rebaseline 新版 state.md，land 时并入本进展防漂。

## 2026-06-25 · Spine 全链贯穿第一段——DSR 估计器真实绑定 + 漂移对账门（gap #3 · 依赖 a00b3956）

- **触发**：自主 loop 续推 gap #3——门核心已建（上轮）但未接真数学点，选信任层核心估计器 DSR 为第一个真实绑定（correctness-critical：DSR 实现漂移则整个 promote 信任层失真）。
- **理论先行**：finding `spine-consistency-gate/01`——DSR 数学定义（Bailey-LdP False Strategy Theorem）+ z 公式 + 假设/适用域/失败条件；可证伪主张「impl 偏离定义超容差 → 对账 fail → 门拒」。
- **实装（扩展不替换 · 复用单一身份源）**：`lineage/spine_binder.py`（可复用范式：`code_fingerprint(*fns)` 用 `inspect.getsource` 取整条实现链真源码 + `ids.content_hash` 冻结指纹；`numerical_consistency_check` impl vs 独立 oracle 在 fixtures 对账产 ConsistencyCheck）+ `eval/spine_bindings.py`（DSR proof_backed artifact §6 字段全含 + `dsr_oracle` 走 scipy 矩独立重算 + `build_dsr_binding`/`dsr_consistency_check`/`verify_dsr_consistency` 跑通 artifact→binding→check→门全链）+ 扩展 `lineage/__init__.py` 导出 binder。只 import `eval/dsr.py` 不改其实现。
- **对抗测试**：`tests/test_spine_dsr_binding.py` **10 passed**——独立 oracle 忠实重算(≤1e-6) + 正确 impl 过门 proof_backed(pit-bound+consistency-pass matched) + **命门：种漂移 impl(丢 E[max] 通缩+denom)→oracle 对账 fail→门拒 granted=challenged** + 真源码指纹==content_hash(getsource 链) + 整链入指纹(改 helper 也变,防绕过) + staleness(指纹漂移→fresh 子句拒) + 落账 append-only verify_chain。
- **全量验证**：eval+spine+lineage 组 **94 passed**；全量后端 **1334 passed / 13 deselected**（127s，上切片 1324 + 本 10 DSR，精确吻合 0 破坏）。凭真汇总行判绿。
- **推进**：GOAL §6/§9 + 头号 gap #3「全链贯穿」第一个真数学点（DSR）已绑并验证漂移被门抓。
- **残余（诚实边界）**：`verify_dsr_consistency()` 未接生产 promote 路径（run_verdict/overfit_gate/ide.promote）= 下一切片；oracle 独立性在矩计算层（scipy vs 手算），不判定义本身对错（靠 Verifier/Critic+文献）；factor/model/signal/portfolio/execution/attribution/monitor 其余数学点逐个绑后续。
- **交付**：同 worktree `auto/math-spine`；commit/push 自管、**land main 待用户**。

## 2026-06-25 · Spine 接进生产 promote 路径——overfit gate DSR 一致性核（gap #3 · 依赖 11b0a3ab）

- **触发**：DSR 已绑脊柱但只孤立可证；本切片让脊柱**真正治理生产**——`run_overfit_gate`（信任层 promote 必经门）的红绿全建在 DSR 上，若 DSR 漂离定义则「证据充分」是建在坏估计器上的假绿灯。
- **实装（扩展不替换）**：`eval/overfit_gate.py` 加 `GateVerdict.spine_consistency` 字段（默认 None）+ memoized `dsr_spine_decision()`（懒导入避 eval↔lineage 环）+ `check_spine_consistency=True` 参 + drift→降级 `insufficient_evidence`（复用既有非 promote sink）。DSR 一致（正常）→ color/numbers 不变、不破基线。
- **codex 只读复核 2×P2（均真问题，已修，非误报）**：
  - P2-1「生产 staleness 不可达」：`verify_dsr_consistency()` 原用当前源建 binding+当前 hash → fresh 子句恒匹配。修：加 `DSR_PINNED_FINGERPRINT=77bd7ce66bf157a9` 已审定指纹，生产用 pinned 当 binding 记录 hash、live 当 current → 改 dsr.py 即 live≠pinned → §6「实现改动未刷新 binding→拒」真触发；+ tripwire 测试 `pinned==dsr_code_fingerprint()`（dsr.py 一改即硬失败逼显式重核 + 刷新常量 = 审定动作）。
  - P2-2「DSR 在 spine 核之前被调用」：drift 致 `deflated_sharpe_ratio` 抛错/签名变会先崩 gate（promote 报错而非 fail-closed）。修：spine 核**提到 DSR 调用之前** + try/except 包裹 → 抛错也映射成 fail-closed `insufficient_evidence`（granted=execution_error），不报坏估计器单点数字（NaN）。
- **对抗测试**：`tests/test_spine_gate_wiring.py` **10 passed**——命门(漂移把本会 green 翻成证据无效) + 隔离(漂移是唯一改判因素) + 逃生阀(check_spine_consistency=False) + 只更严不放水(噪声不被改 green) + tripwire(pinned==源) + 生产 staleness 可达(pinned≠live→fresh 拒) + 抛错 fail-closed + 不报坏数字。
- **全量验证**：gate+spine 组 **71 passed**、verdict/promote/gate_runner **88 passed**；全量后端真汇总见下条/本日。凭真汇总行判绿。
- **推进**：GOAL §6/§8 + gap #3：脊柱从「孤立可证」→「真正 gate 生产 promote」（DSR 数值漂移/源 staleness/执行抛错三类都在生产门被挡）。**残余**：只接 DSR 一支，PBO/bootstrap/factor 等逐个补；spine_consistency 未在前端/RDP 展示。
- **交付**：同 worktree `auto/math-spine`；commit/push 自管、**land main 待用户**。
## 2026-06-25 · sqrt-impact 扩张窗 as-of 无泄露根治（done 卡 d9bf88b1 / 池卡 0f696e56 闭）
- **根治前视（look-ahead 红线）**：sqrt-impact 自估 ADV/σ 从全样本（含未来 bar）改**扩张窗 as-of**——replay 每笔成交按 ts 只用 `F_{t⁻}`（datetime 按日聚合「严格早于当日」+ int ts 前缀均量 + σ 扩张 std 只用 r_1..r_{t-1}）；`step` 传 next_ts；终端标量仅 ts=None 回退。warning 转 informational（无前视/扩张窗/warmup 披露）。数学推导补进 finding「扩张窗 as-of 无泄露自估」节。
- **评审三角（deep-opus‖codex 互不知情 + 我裁决）挖出真 critical 并修**：① 初版用全样本 `max(volume)>0` 判 warmup-vs-fail-fast → PROBE H 实测「early bar 逐位相同、仅未来量不同 → 裁决翻转(raise vs warmup)」=残余前视 + 缺流动性伪装 warmup 假绿灯。**修**：warmup 裁决改纯 F_{t⁻} prefix 驱动、剔除全样本信号；未知 ts 改 warmup-披露不回退泄露终端值。② σ 通道测试无牙（原 leak-free 测试只扰量、close 相同）+ ADV 机制未钉死 → 补 σ-价测试 + 非平量机制测试，**MUT-A（σ 全样本）/MUT-B（lag-1）双 mutation 验证真有牙**（旧测漏、新测必抓）。
- **验证**：全量后端 **1571 passed / 13 skipped / 0 failed**（基线 1564，净 +7）；PROBE H 修前(raise vs cost=0)→修后(两面板同 warmup)实证。**教训**：除 mutation 用定点反向 edit，**绝不 `git checkout` 带未提交改动的文件**（本轮误用一次、全切片实现被抹、已重建）。
- **land main 待用户授权**（本轮 loop「commit 不擅自 push」→ 本地 commit、未 push）。

## 2026-06-25 · 成本逐成分诚实归因（done 卡 6e264c59 / e2afc5c2 #1）+ 测试防挂死（commit 443fca9）
- **成本归因（honesty）**：fill 报告 `commission` 字段实装总成本（含 impact）→ 下游 TCA 误读市场冲击为手续费。修 `_cost_breakdown` 逐成分（impact **单列绝不并入 commission**、各成分非负、求和==total），fill 报告 additive 加 `cost_breakdown`、顶层 commission=total 向后兼容（cost_drift 取总实现成本不破），`step` 一次算 breakdown（避免 warmup 计数双增）。MUT-C（impact 并入 commission 成分）验证有牙（commission 虚高被抓）。finding 补「成本逐成分诚实归因」节 + 修 slice-9 误留的「## 复用」重复节。e2afc5c2 #2（三档预设默认 size-aware）=用户方法学决策（需 Y、seam 就绪默认关、不替拍板）。
- **测试套件防挂死（诚实纠错 + 加固）**：排查「测试跑了 7h/9h」发现两个 pytest 进程空挂——根因 `test_dag_kernel::test_effect_ledger_concurrent_same_key`（8 连接争 SQLite 锁）在我**多 full-suite 并行叠跑** + 后台**无 `--timeout`** 下被饿死挂死（单独 5.4s、全量单独 192s 绿=非生产 bug）；后台被 kill 后 harness 误报「exit 0」=假绿、识破未当真。修 pytest.ini 加全局 `timeout=120` + 并发测试 `daemon=True`（commit 443fca9）。**教训记 memory**：全量套件绝不并行叠跑、必带超时、凭真汇总行判绿别凭 exit code。
- **验证**：`test_sqrt_impact_cost.py` 23 + test_dag_kernel 25 passed；**全量单独前台 1574 passed / 13 skipped / 0 failed / 192s**（基线 1571，净 +3）。
- **land main 待用户授权**（本轮 loop「commit 不擅自 push」→ 本地 commit、未 push）。

## 2026-06-25 · IC 持久性半衰期接 lifecycle 状态机（done 卡 1b83a5c5 / aa13c3b0 ①）
- **价值闭环**：`ic_decay_half_life`（slice-4 建、lifecycle 状态机零消费）→ `LifecycleManager.decay_diagnostic`（perf 轴 advisory）+ evaluate() 事件 advisory 注解；硬转移逻辑零改。**关键修正**：它是 IC 持久性（自相关）半衰期 ≠ 现有转移测的 IC 水平衰减——两不同概念，故 advisory 不并入硬转移（避免数学↔实现混淆 + 守 slice-4「unstable 不作硬退役」自律）。
- **命门**：M-AUTHORITY A1（转移只吃 perf 轴 IC 观测、注入 gate verdict 到 extra 不改判，MUT-M 验证有牙）+ 单一源（复用 ic_decay_half_life、多 ρ 区间扫描，MUT-S clip ρ>0.9 验证有牙）+ 诚实 status（随机游走→unstable 绝不 'ok'）。
- **meta 教训应用 + 验证**：单一源测试初版只测 ρ=0.6 一点 → MUT-S 逃逸（「测单点 happy-path 不扫判别区间」盲区）→ 强化为 ρ∈{0.3,0.6,0.9,0.97}+reversal 扫描后必抓。
- **验证**：`test_lifecycle_decay_advisory.py` 5 + test_alpha_lite_and_lifecycle 7 passed；**全量后端 1579 passed / 13 skipped / 0 failed / 180s**（基线 1574，净 +5）。aa13c3b0 ② 容量/拥挤→sizing 留池（方法学决策）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1**（land main 仍仅用户）。

## 2026-06-25 · conformal 接信号层弃权 + 并发测试负载 flaky 根治（done 卡 ee3b8dbd / 92a2182f ①）
- **价值闭环**：`signals.conformal_abstain_gate` 后处理器——预测区间 [score±q̂] 跨决策阈值（|score−thr|≤q̂）→ 方向不可辨 → 弃权（flat/magnitude=0/abstained=True），诚实「不对噪声下单」。q̂ 用 model_eval `conformal_prediction_band` 的 band_half_width（同一 q̂ 命门交叉校验）。量纲正确：缺 score_col raise、绝不用 confidence sigmoid/magnitude clip 失真值代。band≤0 向后兼容。
- **门有牙**：MUT-conf1（≤→< 漏边界）→边界测试抓；MUT-conf2（反转弃权条件）→跨阈值测试抓。
- **附带根治并发测试负载 flaky**：`test_effect_ledger_concurrent_same_key`（8 连接争 SQLite 锁）重负载下各等满 5s busy_timeout 被饿死、撞 pytest.ini 全局 timeout=120 fail（**全局兜底按设计 fail-fast、未再挂 7-9h**）。根因治：`EffectLedger` 加可配 `busy_timeout_ms`（默认 5000=生产不变·additive），测试用 1000 → loser 快速失败、5.4s→1.1s、3/3 稳；不变量 at-most-one 不受影响。套件 271s→164s。
- **CPCV→gate（861182e6）勘察**：判为需独立 Plan（train_model 单路径 OOS→组合多路径重构跨 3 层 + 成本×C(N,k)；**CPCV paths≠cscv_pbo 跨策略矩阵、不可误喂**），scope 已落卡供后续。
- **验证**：`test_conformal_abstain_signal.py` 6 + test_signals 7 + test_dag_kernel 25 passed；**全量后端 1585 passed / 13 skipped / 0 failed / 164s**（基线 1579，净 +6）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1**（land main 仍仅用户）。

## 2026-06-25 · 冷启动 MinTRL 业绩期证据接裁决卡 UI（done 卡 c5960022 / 31289338 UI · 能信）
- **价值闭环（能信·首个前端切片）**：后端 cold_start（卡 b1e4efdf 建于 project_overfit、UI 零呈现）→ `RunVerdictCard` 首类「业绩期」格 `ColdStartStat` + `LiveRunVerdictCard` mapToData 真映射（/overfit cold_start → `coldStartOrNull` 形状校验 → RunVerdictData.coldStart → 渲染）。小白看见「证据不足·需 N 期」而非在短业绩期上信 PBO/DSR。
- **不假绿灯在 UI**：sufficient=false→「证据不足」警示色非绿、sufficient=true→「充分」中性色非绿（够数据≠策略好、质量看 PBO/DSR）、缺省/坏形状→不渲染（不编造达标）。R7：UI 只渲业绩期长度事实、合规措辞走后端 cold_start.note 单一源（harness R7 扫描门覆盖）。
- **门有牙**：MUT-cs（冷启动恒渲成功绿）→ 3 冷启动测试 FAIL（不假绿灯有牙）。
- **worktree 前端验证**：worktree 无 node_modules（git worktree 不带 gitignored）→ symlink 主仓库 app/frontend/node_modules 跑 tsc/vitest/build，验后清理（symlink+dist 不入库）。
- **验证**：tsc 无类型错；`RunVerdictCard.test` 28 + `LiveRunVerdictCard.test` 15 passed；**全前端 288 passed / 23 文件**（基线 280，净 +8）；vite build ✓。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1**（land main 仍仅用户）。

## 2026-06-25 · conformal 校准区间接模型台 UI（done 卡 29258b77 / 92a2182f ② · 能信）
- **价值闭环**：conformal_interval（卡 d4a324ae 建于 model_eval·OOS 真留出覆盖、UI 零呈现）→ `ConformalIntervalCard` 纯组件（--cc-* token）+ TrainingBenchPage openEval 真映射（读 body.conformal_interval → 渲染）。用户看见「±半宽·目标覆盖·留出实测覆盖 + caveat」或「证据不足」。
- **不假绿灯在 UI**：abstained（calib 不足）→「证据不足」警示色、绝不造假区间/假覆盖；单次留出覆盖率**中性色非成功绿**（带噪估计、跨多次取均值方判校准——后端 note 已述）；interval 缺/null→不渲染（不编造）。合规说明走后端 note 单一源、原样渲染。
- **门有牙**：MUT-cf（单次覆盖渲成功绿）→「不假绿灯①」FAIL。
- **验证**：tsc 无错；`ConformalIntervalCard.test` 5 passed；**全前端 293 passed / 24 文件**（基线 288，净 +5）；vite build ✓。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1**（land main 仍仅用户）。

## 2026-06-25 · 因子收益归因建库（done 卡 ff286f80 · 北极星「归因」阶段填缺）
- **填 pipeline 缺口**：grep 实证北极星「归因」阶段无独立模块 → 建 `eval/attribution.py` `factor_return_attribution`。组合实现收益 OLS 时序回归到因子收益、分解各因子贡献（contrib_k=β̂_k·ΣF_k）+ 特异（specific=Tα̂+Σε̂）。数学先行 finding「因子收益归因」。
- **命门加总恒等式有真牙**：Σcontrib+specific≡Σr 逐位；contrib（β̂·ΣF）与 specific（Tα̂+Σε̂）独立公式 → 非构造性 tautology。MUT-attr（contrib 用 mean 代 sum）→ test_attribution 恒等式 + methodology 恒等式 + 已知 β 恢复三测全红。
- **不假绿灯**：T<K+2→insufficient 不出 β；rank<K+1→collinear 不报不可识别 β；近共线→ok+warn（β 不稳）；非有限行剔除披露；低 R² 如实报（收益多由特异驱动≠已归因）。
- **验证**：`test_attribution.py` 8 + `test_methodology_invariants::test_attribution_sum_identity_invariant` 1 passed；**全量后端 1594 passed / 13 skipped / 0 failed / 151s**（基线 1585，净 +9）。消费侧（组合台/归因报告 UI·因子集/口径=用户方法学决策）mint 卡 e4496023。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1**（land main 仍仅用户）。

## 2026-06-25 · BacktestVenue.cost_summary（per-fill 成本归因收口到 run 级·done 卡 7ac5a0fe）
- **收口**：slice 成本归因（卡 6e264c59）只到 per-fill；run_detail_core:150 已读 run 级 manifest.cost_breakdown 但无 producer（恒空）。建 `cost_summary()` 聚合 audit fills → run 级（commission/slippage/stamp_duty/transfer/impact/total + n_fills），impact 单列不淹没在 commission。
- **run 加总恒等式有牙**：total 走「Σ各 fill.total」独立路径（非 Σ成分）→ total==Σ成分有真牙；MUT-cs2（聚合漏 impact）→ 测试崩。无成交→全 0、n_fills=0（不编造）。
- **验证**：`test_sqrt_impact_cost.py` 25 passed（+2 cost_summary）；**全量后端 1596 passed / 13 skipped / 0 failed / 128s**（基线 1594，净 +2）。
- **follow-on**：backtest→manifest 把 venue.cost_summary() 落 manifest.cost_breakdown 的 producer wiring 待接（IDE sandbox 回测是否产 per-fill 待确认）——本卡提供可用聚合 API、wiring 建后续 mint。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1**（land main 仍仅用户）。

## 2026-06-25 · CPCV 作消费产 per-path OOS 指标分布（done 卡 2da39479 / 861182e6 ① · 最深命门件）
- **啃下前 3 轮延后的 CPCV**：经勘察（assemble_cpcv_paths 通用、组合序一致）后落地消费侧 ①。`models/training.py::cpcv_oos_metric_distribution`——φ=C(N-1,k-1) 路径各覆盖全样本一次→每路径模型 OOS r2→分布（mean/std/q05/min/median/max/frac_below_0；q05/路径方差=过拟合脆弱度）。report-only、regression-only。
- **行为不变抽 `_fit_predict_fold`**：从 train_model 主循环抽出（lambdarank group + classification proba 分支原样），train_model 与 CPCV 共用=fit/predict 单一源；31 训练测试 + 全量套件绿（行为保持）。
- **判别器命门有真牙**：强信号→r2 高稳、噪声→r2≈0/负；MUT「预测 test 段内反序(misalign)」→强信号 r2 崩 -0.87→判别器+强信号测试双红（证 assemble_cpcv_paths 路径重组对齐正确，非纸糊）。
- **避方法学纠缠**：用模型自身 r2（非 Sharpe/DSR——后者需 prediction→收益转换=用户方法学决策）→ report-only、非回归 unsupported_task 诚实、不替拍板。
- **验证**：`test_cpcv_oos_distribution.py` 7 + 训练 31 passed；**全量后端 1603 passed / 13 skipped / 0 failed / 124s**（基线 1596，净 +7）。follow-on（861182e6 ②③ q05→gate/Sharpe-DSR/分类排序）池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1**（land main 仍仅用户）。

## 2026-06-25 · 分支 land-readiness 整体评审 + 修 3 发现（done 卡 3d4a872e · 里程碑）
- **里程碑分支级评审**：18 commits（78 文件/+7764）累积未 land → loop 第 4 步「以可上线成品验收」。deep-opus 三角（execution/drift+lifecycle/frontend+infra）+ 自验：安全红线全清（look-ahead σ/ADV as-of 真无泄露、A股 live 全 venue=backtest、M-AUTHORITY 无 gate verdict 参数、动钱未碰）、additive 属实（impact_coef=0 字节相等、无改既有测试）、无结构阻断 → **判定 land-ready**。
- **修 3 发现**：① [high] signals conformal_abstain_gate 文档过claim（q̂「来自 model_eval·同一命门」暗示生产已闭环、实未串接）→ 软化诚实；② [high] backtest_venue cost_summary 文档称「供 run_detail_core 消费」（实另一 schema 无 producer）→ 软化诚实；③ [medium·真牙缝] σ same-bar 边界未钉（现码 p=j-1 正确但 leak-free 测试只扰未来、漏判 p=j 同根前视，评审种 p=j 两不变量仍过）→ 补 `test_asof_sigma_excludes_same_bar_return_boundary_pinned`（扰单根 close[k]、MUT p=j 验证有牙），σ 边界与 ADV 同级钉死。
- **教训**：in-code 文档不得声称代码里不存在的跨件 wiring——即便 dev/state 另有诚实追踪，维护者先读 in-code 文档=不假绿灯雷。
- **验证**：受影响 33 测 + **全量后端 1604 passed / 13 skipped / 0 failed / 123s**（基线 1603，净 +1）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1。判定 land-ready，待用户授权合并 main。**

## 2026-06-25 · ic_decay 诚实 status 精修 no_persistence（done 卡 b762da53 · 清评审 low 残余）
- **诚实 status**：ic_decay_half_life 原 ρ̂≤0 一律 reversal，但 ρ̂≈0 白噪 IC 是无持久性非反转（reversal=anti-persistent 须 ρ 显著<0）。改按 95% CI 上界：ci_hi<0→reversal、CI 含 0→no_persistence（无显著自相关·非反转非持久）。对齐不假绿灯/honest-status（不把噪声弱负 over-claim 成反转）。
- **MUT 验证有牙**：还原「ρ≤0 全 reversal 过claim」→ 弱负（ρ=-0.2 n=45 CI 含 0）测试红。低 ripple（显著负仍 reversal、random walk 不碰、near-constant insufficient、decay_diagnostic advisory 传播不变）。
- **验证**：test_factor_lifecycle_metrics 31 + test_lifecycle_decay_advisory 全 passed；**全量后端 1605 passed / 13 skipped / 0 failed / 124s**（基线 1604，净 +1）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1。分支续 land-ready。**

## 2026-06-25 · CPCV per-path 分布扩二分类 roc_auc（done 卡 c43c6301 · 扩 2da39479）
- **任务扩展**：cpcv_oos_metric_distribution 从 regression-only(r2) additive 扩二分类(roc_auc·重组 proba 路径)。任务白名单：regression→r2(baseline 0)、二分类→roc_auc(baseline 0.5)、多分类/lambdarank/无 predict_proba→unsupported_task 诚实。proba 路径用 assemble_cpcv_paths 重组（与 pred 同机制）。
- **判别器有牙**：MUT「proba misalign」→ 强分类器 auc 崩 0.4999 → 强信号高 auc + 强 vs 噪声判别器双红（证 proba 重组对齐正确）。additive（regression 路径不变 baseline=0.0）、report-only 不接 gate。
- **验证**：`test_cpcv_oos_distribution.py` 11 passed（+4 分类）；**全量后端 1609 passed / 13 skipped / 0 failed / 124s**（基线 1605，净 +4）。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1。分支续 land-ready。**

## 2026-06-25 · CPCV 路径分布 opt-in 集成进 train_model（done 卡 74f93771）
- **集成进训练生命周期**：CPCV 消费函数（done 2da39479/c43c6301）从孤立可调 → opt-in 集成进 train_model（ModelSpec +compute_cpcv 默认关 + cpcv_n_groups/k_test；TrainResult +cpcv_distribution；开启则训练后产分布随 result.json 流到 verdict/UI）。默认关=零行为/成本变更（护栏：不替方法学拍板、开启=用户自负 C(N,k) 拟合）。
- **additive 零回归**：ModelSpec/TrainResult 加 default 字段向后兼容、train_model 默认关分支行为不变；49 训练测试 + 全量套件绿。
- **验证**：`test_cpcv_oos_distribution.py` 12 passed（+1 opt-in：默认关→None、开启→分布·asdict JSON-safe）；**全量后端 1610 passed / 13 skipped / 0 failed / 124s**（基线 1609，净 +1）。follow-on（861182e6 ②）：cpcv_distribution→verdict/UI + q05 接 gate（阈值=用户方法学）池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1。分支续 land-ready。**

## 2026-06-25 · CPCV 路径稳健性分布呈现到模型台 UI（done 卡 876a0c11 · CPCV→用户闭环收尾）
- **闭环收尾**：cpcv_distribution（卡 74f93771）→ training_job_eval 透传 → `CpcvRobustnessCard`（模型台·report-only）。CPCV 全链：库→消费(regression+二分类)→train_model opt-in→result.json→eval→UI。
- **不假绿灯在 UI**：未算/缺→不渲染、status≠ok→不造假分布、q05<无技能基线(r2:0/auc:0.5)→脆弱警示色非绿、q05≥基线中性非绿（路径稳≠策略好）。report-only 不接 gate。
- **worktree 坑（已避污染）**：symlink node_modules 一度成真目录（gitignored·主仓库未污染·已确认 141 项完好）→ rm -rf 安全清理；git status 仅 4 源文件无 node_modules 泄漏。
- **验证**：`CpcvRobustnessCard.test` 5 + `test_model_eval_conformal` 10（+1 cpcv 透传）passed；**全前端 298 / 25 文件 + tsc + build ✓**；**全量后端 1611 passed / 13 skipped / 0 failed**（基线 1610，净 +1）。861182e6 ②剩 q05→gate（阈值=用户方法学）池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支 worktree-autopolish-w1。分支续 land-ready。**

## 2026-06-25 · 同步 main——spine 分支 merge origin/main（用户拍板「同步到 main 后再继续」）

- **触发**：本轮 loop 准备绑 PBO/bootstrap 前，git fetch 发现 `auto/math-spine` 基于的 `fix-u2-synth` **落后 origin/main 47 提交**（用户在 main 并行 loop 推进 CPCV q05/conformal/attribution/MinTRL/drift/lifecycle…，main 全量 1626 passed）；main 的 CPCV q05 改了 `overfit_gate.py`、与我的 spine 接线冲突。HANDOFF「main 有触及你路径的新提交先看 diff 再动手」+ correctness（一致性门须对真·当前代码验，非陈旧快照）→ 停下问用户。
- **用户拍板**：AskUserQuestion「分支对齐」→ **同步到 main 后再继续**。
- **处置**：先备份 `auto/math-spine-prerebase`；rebase 因 dev/ 共享文档在 3 提交各冲突太碎 → 改 **merge origin/main 进分支**（冲突一次解完）。解 5 冲突：`overfit_gate.py`（整合 main CPCV q05 + 我的 spine 接线，GateVerdict `cpcv`+`spine_consistency` 双字段、run_overfit_gate 双套参数共存、早返回 fail-closed 与 CPCV 块并存）；`state.md`/`DEVMAP`/`_NAV` 取 main 权威版（spine 进展 prepend + regenerate）；`log.md` 保双方条目。
- **验证**：merge 后 spine+gate+cpcv **76 passed**；`origin/main 现为 HEAD 祖先`=分支已同步；DSR pinned 指纹对 main 的 dsr.py 仍有效（main 只新增 PSR/MinTRL 函数，未动我指纹的 5 链函数）。**全量后端 1673 passed / 13 deselected / 1 已知并发 flake**（`test_effect_ledger_concurrent_same_key` 负载下 timeout、隔离单跑 1.13s 绿、非回归）。
- **结果**：spine 3 切片（门核心 + DSR 绑定 + 接生产 gate）现建立在 main 真·当前代码上、一致性门对当前估计器验。下一切片绑 PBO/bootstrap 在同步后分支上做。commit/push 自管、**land main 待用户**。

## 2026-06-25 · 信任层三角补齐——PBO+Bootstrap 经脊柱绑定 + 三支接生产 gate（gap #3 · 依赖 4458ff54）

- **触发**：DSR 已接生产 gate 但 gate 红绿建在 DSR/PBO/bootstrap **三支**上，只核一支不够；本切片补齐三角（先 git fetch 确认仍同步 main 无新提交）。
- **理论先行**：finding `spine-consistency-gate/02`——PBO(CSCV)/bootstrap 难做闭式独立 oracle → 用 **property-based 一致性**（从定义推出必要性质）。PBO：范围∈[0,1]/纯噪声≈0.5(CSCV 定理)/真信号低 pbo/pbo↔λ 符号一致。bootstrap：lower≤upper/estimate==sharpe(同源)/可复现/真信号 lower>0/噪声跨0。
- **实装（扩展不替换·复用范式）**：`lineage/spine_binder.py` +`property_consistency_check`（§6 check_type=property，诚实标必要非充分弱于 numerical）；`eval/spine_bindings.py` +PBO/bootstrap proof_backed artifact + 性质集 + binding + verify + pinned 指纹（PBO `8a7179e0db1006b3`/bootstrap `fc9f5c540e5834b8`，实测性质全过：noise_pbo=0.514≈0.5、skill_pbo=0.000、bootstrap 5 性质成立）；`overfit_gate.py` +`pbo_spine_decision`/`bootstrap_spine_decision` + spine 块**泛化成三支循环**（任一不一致/抛错 fail-closed，reason 点名哪支）。
- **对抗测试**：`tests/test_spine_pbo_bootstrap_binding.py` **17 passed**——PBO sign 反转→P4/P5 fail→门拒；bootstrap lower/upper 交换→B1 fail→门拒；tripwire(pinned==源)；staleness(pinned≠live→fresh 拒)；生产 gate 三支全核(spine_consistency 三键)、PBO/bootstrap 任一漂移→fail-closed insufficient_evidence。
- **全量验证**：spine+gate 组 **93 passed**；**全量后端 1691 passed / 13 deselected / 0 failed / 125s**（merge 真基线 1674 + 本 17，未破基线）。凭真汇总行判绿。
- **推进**：GOAL §6/§9 + gap #3：信任层多证据三角**三支全上脊柱**、生产 gate 三支任一漂离定义 fail-closed。**残余**：conformal/attribution/MinTRL/drift（main 新增）等其余数学点逐个绑后续；property 必要非充分（弱于 DSR numerical oracle）。
- **交付**：worktree `auto/math-spine`（已同步 main）；commit/push 自管、**land main 待用户**。

## 2026-06-25 · MinTRL+PSR 经脊柱绑定（交叉校验恒等式）+ 接 run verdict cold_start（gap #3 · 依赖 b85e34cc）

- **触发**：脊柱已治理信任层 promote 门（三角三支）；选下一个有生产消费点 + 干净一致性检查的数学点。attribution 无生产消费点（孤立可证·跳过）；MinTRL/PSR 有**两条精确交叉校验恒等式** + 生产消费点（run verdict cold_start）→ 选它（先 git fetch 确认仍同步）。
- **理论先行**：finding `spine-consistency-gate/03`——M1 n=MinTRL→PSR(SR*)≡confidence（PSR 解析反解，代回 z=zp）；M4 PSR(r,E[max_N over V])≡DSR(r,N,V)（绑回已绑 DSR·V-path 恒等）。
- **实装（扩展不替换·复用范式）**：`eval/spine_bindings.py` +MinTRL/PSR proof_backed artifact + 必要性质集（M1 交叉校验·独立 scipy 矩重算 PSR@n=MinTRL / M2 PSR 范围 / M3 abstain 诚实 / M4 PSR-DSR 互校验·构造 sr_pp≈0.85 N=10 落区间内 0.674 有判别力）+ pinned 指纹 `21d30c6a2b851342` + verify_mintrl_consistency；`run_verdict.py` +memoized `_mintrl_spine_status`（懒导入避环）+ `_cold_start_evidence` 注入 spine_consistency + **漂移 fail-soft**（dsr_applicable=False + 数学一致性失败 note·呈现层不动治理闸门）。
- **对抗测试**：`tests/test_spine_mintrl_binding.py` **12 passed**（含 codex P2 回归 2：正信号误判 never_significant 必抓 / fail-soft note 无 R7 禁词）——种 MinTRL 1.5× 漂移→M1 交叉校验破→门拒；种 PSR +0.1 漂移→M4 互校验破；tripwire；staleness 可达；cold_start 一致→dsr_applicable 不变、漂移→dsr_applicable=False+note。
- **全量验证**：spine 组 **75 passed**、run_verdict/cold_start **35 passed**；**全量后端 1702 passed / 13 deselected / 1 已知并发 flake**（test_effect_ledger_concurrent_same_key 负载 timeout·隔离 1.09s 绿·非回归；1702+flake=1703=基线 1701+P2 回归 2）。凭真汇总行判绿。
- **推进**：GOAL §6/§4 + gap #3：脊柱覆盖从信任层三角扩到 MinTRL/PSR + **第二个生产消费点（run verdict cold_start）**治理。**残余**：conformal/attribution/drift 等其余数学点逐个绑；attribution 待其生产消费侧（卡 e4496023）落地再绑。
- **交付**：worktree `auto/math-spine`（已同步 main）；commit/push 自管、**land main 待用户**。

## 2026-06-25 · Conformal 预测区间经脊柱绑定（覆盖定理）+ 接 model_eval band（gap #3/#7 · 依赖 c86be35e）

- **触发**：脊柱已治理 overfit gate + run verdict cold_start 两消费点；选验证纵深 conformal（覆盖定理可机器证伪 + model_eval band 生产消费点）。先 git fetch 确认仍同步 main。
- **理论先行**：finding `spine-consistency-gate/04`——split conformal 覆盖定理 P(Y∈C)≥1−α（分布无关·有限样本·边际，秩 k=⌈(n+1)(1−α)⌉ 含 +1 校正）。
- **实装（扩展不替换·复用范式）**：`eval/spine_bindings.py` +conformal proof_backed artifact + 覆盖性质（C1 固定 seed N(0,1) 留出 MC 覆盖≥1−α·实测 α=0.1→0.898/0.05→0.956 / C2 abstain 诚实 n<⌈1/α⌉−1 / C3 区间合法）+ pinned `be82f9471f557ab8` + verify_conformal_consistency；`model_eval.py` +memoized `_conformal_spine_status`（懒导入避环）+ `conformal_prediction_band` 注入 spine_consistency + **漂移 fail-soft abstained**（坏 conformal 不给假覆盖的 band·note 避 R7 禁词「可信」）。
- **对抗测试**：`tests/test_spine_conformal_binding.py` **10 passed**（含 codex P2 回归：split 漂移成 [finite,+inf] 经 C3 双端点有限封死）——种区间砍半漂移→欠覆盖→C1 覆盖定理 property 破→门拒；tripwire；staleness 可达；band 一致→正常出、漂移→abstained=True+数学一致性失败 note（断言无禁词「可信」）。
- **全量验证**：spine 组 **58 passed**、model_eval/conformal **62 passed**；**全量后端 1713 passed / 13 deselected / 0 failed**（flake 本次通过；1713=真基线 1712+inf-upper 回归 1）。凭真汇总行判绿。
- **推进**：GOAL §4 + gap #3/#7：脊柱覆盖从信任层三角 + MinTRL 扩到**验证纵深 conformal** + **第三个生产消费点**（model_eval band）。**残余**：cqr/aci/drift/attribution 等其余数学点逐个绑。
- **交付**：worktree `auto/math-spine`（已同步 main）；commit/push 自管、**land main 待用户**。

## 2026-06-26 · 并行 campaign 施工图 + 第一波 pool 卡 + 红线止血（一中心+5并发筹备）

- **触发**：用户拍板转「一中心 + 5 并发 deep-opus」并行开发范式（拆分在本会话外部做完、用户新开会话 loop）。
- **GOAL canonical 修复**：发现真 §0-§17 契约（2076 行）一直只在本地未提交、committed 分支只有 85 行精炼 §0-§9 → commit §0-§17 进 main（beb1b2f·授权 land）。
- **三方研究施工图**：中心 + deep-opus（代码 file:line 核验·36min）+ codex(gpt-5.5·xhigh) 三方独立拆 GOAL→DAG，取并集。落 `dev/research/findings/dreaminate/construction-map.md`（7 LINE + territory + 依赖 + 文件争用 + 波次 + 11 拍板项 + 红线）。
- **致命红线止血（commit 7311c6b·C-MODELGOV-1 第一刀）**：`training/lib.py` 裸 pickle.load + torch.load(weights_only=False)=外来 artifact RCE（§15 做反了）→ RestrictedUnpickler 拦 RCE gadget（os/subprocess/pydoc/marshal…）+ weights_only=True。codex 复核处置（补 gadget·诚实标 blocklist≠safe-pickle·完整门 carded）。对抗测试 8 passed。
- **第一波 pool 卡 mint**：`36f88f6b`(C-MODELGOV-1 完整门) `e01bf12f`(B-PIT-1 回测消费 as_of_known) `0430cd78`(B-VERSION-1 数据写门) `9d593481`(D-RDP-1 RDP schema) `f19c5c19`(A-QRO-1 对象信封地基)；W5=已有 `de764e1c`。各带文件领地 + 对抗验收 + depends_on。validate PASS（DAG 无环）。
- **集成 land**：auto/math-spine（spine 全套 + GOAL + 红线修·9 ahead·origin/main 祖先=ff）land 进 main（用户授权）。fix-u2-synth(47d79a9) 已是 main 祖先无需 land。
- **land 前终验**：全量后端 **1721 passed / 0 failed / 13 deselected**（1713 + 红线 8·flake 本次通过）。
- **74 文件前端 sweep 并入 main（3064fad）**：fix-u2-synth 前端术语 relabel + 文档整波 3-way merge 进 main（68 文件自动合 + `LiveRunVerdictCard.test.tsx` 1 冲突解：保 main 新增 2 对抗测试 pbo:null/dsr 全缺→N/A + 应用 sweep 措辞）。dev/ OS 文件刻意排除（vs main 集成态陈旧）。验证 tsc EXIT=0 + vitest 25 文件/298 测试全过。
- **codex 顾问处置（2 P2）**：① README sync 声称=**误报驳回**（全 dev/ grep「README 同步」0 命中，DECISIONS.md 仅 299 行·codex 引 :317 越界；README「A股+加密」是诚实现状、GOAL「所有公开二级市场」是终态，二者本应不同）。② D-MATH-SPINE 未锚 GOAL=**真问题修**（该决策被 7 done 卡+6 finding+state 引为控制决策，GOAL 9 处 footer 却只引 D-QRO-CANVAS）→ 锚进 GOAL 6 处（来源行 + §0/§6/§8/§10/§17 footer，镜像 D-QRO-CANVAS 锚法·扩展不替换）。**未伪造正式 DECISIONS 记录**（D-QRO-CANVAS/D-MATH-SPINE 均无正式登记体·pre-existing gap·留用户/campaign 形式化，不假「用户拍板」provenance）。validate_dev PASS。
- **下一步**：用户新开会话用新版 loop 提示词（中心+5并发·活的任务池·可新开卡/线）驱动 fleet。

## 2026-06-26 · 第一波 4 线并行整合 land（中心 orchestrator·一中心+5 并发范式首跑）

- **派 4 deep-opus 并行线**（各隔离 worktree·文件领地不交叠）+ 中心轻量集成线：W1 artifact 安全完整门(`36f88f6b`) / W2 PIT 训练接线(`e01bf12f`) / W3 数据写时门(`0430cd78`) / W4 RDP schema(`9d593481`)；逐条 fetch+merge 进集成分支 worktree-center-integ。
- **验收**：批次全量 **1784 passed / 13 skipped / 0 真失败**（基线 1734 collected + 64 新对抗测试；唯一失败 `test_effect_ledger_concurrent_same_key` 隔离单跑 1.12s 绿=已知负载 flake 非回归·4 线零碰 dag/kernel/ledger 并发代码实证）+ validate_dev PASS + 中心亲审 W1 lib.py 安全 diff（红线零裸危险加载·grep 实证）。各线 MUT 种坏门必抓（W1×4 / W2×2 / W3×2 / W4×4 门）。
- **诚实状态**：4 卡核心 seam/机制 ✅+对抗验证齐；全 scope wiring 据实标 🟡（W1 生产激活 / W2 service 全链 / W3 字段+data lineage / W4 接导出器+真 promote）→ mint 4 follow-on P2（`6144bd61`/`6a8752ab`/`ec7a7d9a`/`67b42025`·depends_on 各 canonical）。
- **dev/ reconcile**：最初在旧分支 fix-u2-synth（pool 空）误判 → 用新 uuid 建了重复卡；纠正=删中心自建的 4 重复·canonical pool 卡(`36f88f6b` 等)移 done + 补完成记录·施工图 uuid 对齐 → 无双重记账。
- **land**：4 线整批 land main（用户授权·能回滚兜底）。**下一步**：开 LINE-A 对象脊柱（QRO/Graph/Compiler/Command·最强上游瓶颈·阻塞几乎全部下游）。

## 2026-06-26 · 第二波 4 线并行整合 land（LINE-A 对象脊柱开局 + wave-1 接线激活）

- **派 4 deep-opus 并行线**（隔离 worktree·领地不交叠·避开 main.py 中心独占）：A-QRO-1 QRO 对象信封+状态六轴(`f19c5c19`·头号 gap#1 LINE-A 地基) / W2-service PIT 全链(`6a8752ab`) / W3-fields 数据写门余项(`ec7a7d9a`) / W4-wire RDP 接 promote(`67b42025`)。
- **验收**：批次全量 **1878 passed / 13 skipped / 0 真失败**（基线 1798 + 80 新对抗测试；唯一失败 `test_effect_ledger_concurrent_same_key` 隔离 1.19s 绿=已知负载 flake 非回归·4 线零碰 ledger/dag 并发代码）+ validate_dev PASS。各线 MUT 种坏门必抓（A-QRO×5 含四轴分离 / W2×2 双机制泄露 / W3×2 manifest+缺字段 / W4×6 promote 缺 RDP）。中心补 main.py:1510 入口透传闭合 PIT HTTP→service 全链。
- **诚实状态**：A-QRO-1 信封+六轴+收编结构门 ✅（下游接线 A-QRO-2/axis↔spine 🟡）；W2 PIT 全链 ✅（demo 无 known_at 列·真数据集另卡）；W3 信封/lineage/manifest/secret 守门 ✅；W4 RDP 接 promote 门 ✅（强制档默认关待 D-RDP-2 聚合器）。
- **2 拍板项停报中心（保守默认 land·非阻塞·摆代价待用户拍）**：W3 ①字段提级必备(方法学口径) ②data_pull legacy 回收(越领地·canonical intake 已覆盖)；W4 RDP 强制档常开(待 D-RDP-2)。均方法学松紧/范围·保守默认已 land·用户决定是否调紧。
- **dev/ 整合**：4 张 assigned 卡删(opus done supersede)·done 卡 32-hex uuid 齐·f19c5c19 待拍字面量修。
- **land**：4 线整批 land main（用户授权·能回滚兜底）。推进 GOAL §1/§11/§17。**下一步**：第三波 A-GRAPH-1 ResearchGraph IR(LINE-A 续) / LINE-A-AGENT LLM Gateway(另一最强瓶颈) / A-QRO-2 / D-RDP-2。

## 2026-06-26 · W1 artifact 信任门生产激活·enforce 默认开兑现 §15（第三波先派单线·GOAL-锚定）

- **派 1 deep-opus**（`6144bd61`·wave3/w1-artifact-activate）：producer 全接 register（models/training.py pickle / models/dl/trainer.py torch.save）+ service 组合消费侧 enforce + safetensors 入依赖 + artifact_trust 门语义零改。
- **GOAL-锚定关键**：用户三次强调锚定 GOAL → 读 §15「external pickle **blocked by default**」=enforce 默认开是**终态**（opus 标 profile 松紧·但 GOAL 已决·非松紧旋钮·中心按 §15 不回退、不问用户）。修正了我此前误用「不要管太宽」想保 opt-in。
- **验收**：全量 **1887 passed / 13 skipped / 0 failed / 131s**（基线 1892+8·enforce 默认开**零破基线**=producer 全接证·flake 未触发）+ validate PASS·8 测 MUT-1（register 落错店）/MUT-2（强 enforce=False）双抓。
- **子系统**：artifact 信任门 🟡→✅（§15 兑现：机制+生产激活+enforce 默认开+全量验证齐）。
- **诚实残余**：① 自由代码子进程路（submit_code）enforce 未覆盖（领地外·结构化 spec 路已 enforce）② safetensors 输出保留 .pt（须连带改 backtest auto-find+M12 跨领地）③ 全局策略未翻。
- **land**：单线 land main（用户授权）。**下一步**：第三波主力 A-GRAPH-1 + LLM Gateway（GOAL-first prep·读 §1/§2/§7）。

## 2026-06-26 · 第三波 3 线并行整合 land（ResearchGraph IR + LLM Gateway + confirmatory-PIT 门·GOAL-first）

- **派 3 deep-opus 主力**（各 GOAL-first·先读对应节·领地不交叠）：A-GRAPH-1 Research Graph IR(`76a611d3`·§1/§2·阻塞 Compiler/各台) / LLM Gateway(`640b66a0`·§7·LINE-A-AGENT 开局) / confirmatory-PIT 门(`25247eb4`·§16)。
- **验收**：批次全量 **1997 passed / 13 skipped / 0 failed / 125s**（基线 1900+109 新对抗测试全绿·flake 未触发·confirmatory enforce 默认开+portfolio additive 零破基线）+ validate PASS。MUT 钉死：A-GRAPH×6(单一源/typed contract/写隔离…) / LLM Gateway×6(绕过/secret 进账·进 prompt/缺字段/静默降质/凭据越权) / confirmatory×MUT(翻 advisory→11 failed)。
- **GOAL-锚定成效**：3 条线**全无停工拍板**——A-GRAPH infra 写台切分锚 §2/§1(A-QRO-1 precedent 可逆)、LLM Gateway 锚 D-LLM-ROUTING+D-DELIVERY-SLICE、confirmatory 锚 §11/§16/§6+R28。GOAL 已决直接建。
- **子系统**：Research Graph IR ✅(地基)·LLM Gateway ✅(核+路由+凭据池+调用账·secret 不进 LLM/日志/导出双扫)·confirmatory-PIT 库层门 ✅。
- **诚实残余**：A-COMPILER/A-CMD(§1 链续)·Agent Orchestrator+12 role+23 事件(§7)·Gateway 接 main.py/AgentRuntime·confirmatory 端点激活(待上游注册一致)。
- **land**：3 线整批 land main（用户授权）。推进 GOAL §1/§7/§16。**下一步**：A-COMPILER/A-CMD·Agent Orchestrator·A-QRO-2/D-RDP-2。

## 2026-06-26 · 第四波 3 线并行整合 land（CanonicalCommand + Agent Orchestrator + RDP 聚合器·GOAL-first）

- **派 3 deep-opus 主力**（各 GOAL-first·领地不交叠 command/ ‖ agent/orchestrator/ ‖ delivery/）：A-CMD CanonicalCommand(`8abde88e`·§1/§2) / Agent Orchestrator(`437e94bd`·§7) / D-RDP-2 RDP 聚合器(`0781bb13`·§17)。
- **验收**：批次全量 **2125 passed / 13 skipped / 0 failed / 125s**（基线 2010+128 新对抗测试全绿·flake 未触发·collect 2138 精确吻合）+ validate PASS。MUT 钉死：A-CMD×12(绕过通道/actor 四类/目标台/内容寻址/payload) / Agent Orchestrator×6(绕过 DAG/Gateway/Verifier 独立性/Agent 替拍方法学/完成门/可见性) / D-RDP-2×3(缺真 DatasetVersion 门拒/真血统不编造/secret 扫描)。
- **GOAL-锚定成效**：3 线**全无停工拍板**——A-CMD actor 面表锚 §2/§0(可逆)、Agent Orchestrator **24 事件按 GOAL §7 实列**(opus 信 GOAL 而非我卡面写错的 23·GOAL-FIRST 完美生效)、D-RDP-2 锚 D-SCOPE-CONSERVATIVE(没擅自常开 require_rdp)。
- **里程碑**：**QRO→ResearchGraph→CanonicalCommand 三段对象脊柱通** + **LINE-A-AGENT(LLM Gateway+Orchestrator)通** + **§17 RDP 真血统聚合通**。role agent 不读 key·role 节点 kind=pure 不动钱·实盘 key 不进 RDP。
- **诚实残余**：A-COMPILER(消费命令→Run→Verdict·完成 §1 链)·Orchestrator/Gateway 接 main.py+前端·record/replay store·RDP 端到端常开(待用户)·命名对象 typed 化。
- **land**：3 线整批 land main（用户授权）。推进 GOAL §1/§2/§7/§17。**下一步**：A-COMPILER(完成 QRO→Graph→Command→Compiler→Run→Verdict 整脊柱)·A-QRO-2·各残余接线。

## 2026-06-26 · 第五波 3 线并行整合 land·🏛 LINE-A 整脊柱贯通 capstone（GOAL-first）

- **派 3 deep-opus**（各 GOAL-first·领地不交叠 compiler/ ‖ training/ ‖ monitor/）：A-COMPILER Governed Compiler(`26c795c1`·§1 capstone) / W1 子进程 enforce(`ccb4f333`·§15) / drift→monitor(`554cdcf2`·绩效轴闭环)。
- **验收**：批次全量 **2177 passed / 13 skipped / 0 failed / 135s**（基线 2138+52 新对抗测试全绿·flake 未触发·collect 2190 精确吻合）+ validate PASS。MUT 钉死：A-COMPILER×4 命门(命令未经 compiler 落 run/run 无内核身份/verdict 绕 verifier/promotion 绕 approval) / W1 子进程×2(外来 .pkl 子进程拒) / drift→monitor×2(断接线 perf 不触发/观测落盘重启) + 范畴红线钉死(PSI/gate/dsr 经类型层拒入)。
- **🏛 里程碑：QRO→Graph→Command→Compiler→Run→Verdict 整脊柱贯通**——A-COMPILER 收编 dag/kernel(确定性内核·独立 re-derive 身份不绕)+verifier+三角门(evidence verdict 不伪造绑本 run)+approval(approver≠creator) 零改重造，GOAL §1 范式链 Quant Intent→QRO→Research Graph→Governed Compiler→Deterministic Run→Evidence Verdict→Promotion 完整成型。
- **GOAL-锚定成效**：3 线全无停工拍板（A-COMPILER 两边界 docstring 钉·drift 阈值=用户文献默认·W1 沿用已拍开关）。
- **诚实残余**：接 Agent OS(Gateway/Orchestrator/Compiler)进 main.py+各台 Canvas 触发编译(领地外·中心做)·evidence 抽取适配·监控真实数据源待 data 管道·W1 领地外消费点·confirmatory 端点激活。
- **land**：3 线整批 land main（用户授权）。推进 GOAL §1/§5/§15。**下一步**：中心接 Agent OS 进 main.py·A-QRO-2·老 P2·各残余接线。

## 2026-06-26 · 第六波 3 线并行整合 land（A-QRO-2 语义切分 + 归因消费 + 成本 opt-in 桥·GOAL-first）

- **派 3 deep-opus**（各 GOAL-first·领地不交叠 qro/ ‖ eval+frontend ‖ execution/）：A-QRO-2 模型↔Factor 切分(`872af176`·§1/§9) / 归因消费(`e4496023`·§0/§13) / 成本字段拆(`e2afc5c2`·§10)。
- **验收**：批次全量 **2272 passed / 13 skipped / 0 failed / 135s**（基线 2190+95 新对抗测试全绿·flake 未触发·collect 2285 精确吻合）+ validate PASS。MUT 钉死：A-QRO-2×3 门(30 failed 精确归因) / 归因×(abstain 不渲绿/低 R² 不标已归因/加总恒等式/R7 措辞/冻结页) / 成本×MUT-A/B(impact 不并入 commission/不静默吞 opt-in)。前端真验(归因 vitest 17+tsc 0)。
- **GOAL-锚定成效**：A-QRO-2 复用单一源(零第二黑名单·钉死 QRO==mining)·归因因子集口径=用户原样回显·成本字段拆 opus grep 实证②早已 done 没重做·只建①opt-in 桥。
- **2 拍板项停报中心(保守默认 land·非阻塞·摆代价待用户)**：成本三档预设是否默认翻 size-aware(须先可信 Y 标定+无泄露管线否则没校准冲击当默认=另一种不诚实)·归因因子集/口径(原样回显·用户那摊)。
- **诚实残余/中心补**：归因 main.py 薄路由+前端 FactorAttributionCard 挂载·成本三档预设生产 run 管线消费(producer wiring)·Agent OS 接 main.py·A-QRO-2 admit_signal/strategy 正路径 builder。
- **land**：3 线整批 land main（用户授权）。推进 GOAL §1/§9/§0/§10。**下一步**：中心接 Agent OS+归因路由进 main.py·老 P2 剩·各残余。

## 2026-06-26 · 第七波 4 线并行整合 land（发版门禁 + Document 安全栈 + 方法学控制面 + Forecast/StrategyBook·GOAL-first）

- **派 4 deep-opus**（各 GOAL-first·全新 greenfield territory 不交叠 release_gate/ ‖ documents/ ‖ methodology/ ‖ strategy/）：发版门禁(`785c79c6`·§16) / Document 摄入安全栈(`66195b71`·§6) / 方法学控制面 6 档(`e62a8933`·§10) / Forecast+StrategyBook typed(`61053f3d`·§9)。
- **验收**：批次全量 **2447 passed / 13 skipped / 0 failed / 233s**（基线 2285+175 新对抗测试全绿·flake 未触发·collect 2460 精确吻合）+ validate PASS。MUT 钉死：发版门禁(silent mock/template 标生产/缺 binding/缺 MCR/伪造封印各→拒·3 MUT) / Document(伪装扩展名/SSRF 16 种/联网解析器/zip bomb/隔离真生效) / 方法学(放宽后仍显强证据→拒 15 红/未记录 tradeoffs→拒) / Forecast(未绑 Signal Contract→拒/A股 short 硬拒 R13)。
- **GOAL-锚定成效**：4 线全无停工拍板·全靠锚 GOAL+已决决策自决。复用单一源纪律：发版门禁委派已建门不重造·方法学复用 spine.MethodologyChoiceRecord(is 断言)·Forecast 复用 signal_contract/strategy_goal.Constraints·Document 复用 ids.content_hash。
- **安全里程碑**：Document 外来文档攻击面(quarantine/sandbox/no-network/SSRF/zip bomb)与 artifact RCE 同级防护立死·发版门禁 no silent mock+no template false success 硬拒。
- **2 拍板项停报中心(保守默认 land·非阻塞·摆代价待用户)**：PDF/OOXML 解析库选型(Document 立沙箱+stub)·方法学 standard 档是否 cap(GOAL §10 放宽语义·已 GOAL-consistent)。
- **诚实残余/中心补**：发版门禁/方法学接 main.py 真 promote+RDP·Document EvidenceSpan 抽取+真解析库·Forecast runtime 执行接线·InstrumentSpec 本体·归因 main.py 路由·Agent OS 接 main.py。
- **land**：4 线整批 land main（用户授权）。推进 GOAL §16/§6/§10/§9。**下一步**：LINE-G 执行监控/runtime profile/governance 收口/各接线。

## 2026-06-26 · 第八波 4 线并行整合 land（InstrumentSpec + EvidenceSpan + 信任层硬约束门 + governance 收口门·GOAL-first）

- **派 4 deep-opus**（各 GOAL-first·greenfield 非交叠 instruments/ ‖ documents/扩 ‖ trust/ ‖ governance/）：InstrumentSpec(`0850cc54`·§11) / Document EvidenceSpan(`2bac27d3`·§6) / 信任层硬约束门(`0d7c9511`·§13) / governance 收口门(`d904b8d9`·§8)。
- **验收**：批次全量 **2615 passed / 13 skipped / 0 failed / 113s**（基线 2460+168 新对抗测试全绿·flake 未触发·collect 2628 精确吻合）+ validate PASS。MUT 钉死：InstrumentSpec(期权缺 expiry/A股 live 恒拒/跨币种缺 base currency) / EvidenceSpan(缺追溯/未标未验证/span-support 抗伪造/真实 MUT 8 例) / 信任层(waiver 绕 safety→拒命门/反谄媚/弱点隐藏/伪造强标签) / governance(七条硬不变量各违反→拒)。
- **GOAL-锚定成效**：4 线全无停工拍板·复用单一源(InstrumentSpec 复用 classify A股硬墙·信任层复用 spine.MCR·governance 收编已建零重写 ENFORCEMENT_BINDINGS 实证·EvidenceSpan 独立链账不污染 honest-N)。补缺口:ResponsibilityDisclosureRecord(rdp.py 早有 string-ref 无类)。
- **安全里程碑**:waiver 绝不可绕 secret/OrderGuard/kill switch/no-silent-mock(§13 命门 fail-closed)·governance §8 七条硬不变量统一核查·A股 live 恒拒(InstrumentSpec)。
- **2 拍板项停报中心(已 GOAL-anchored 自决)**:ExtractionRun 落账归属(独立链账·延续 intake 先例)·信任层 waiver-safety 硬 raise(§13 命门+release_gate 先例)。
- **诚实残余/中心补**:各门接 main.py 真 promote(发版门禁/方法学/信任层/governance/confirmatory)·真 PDF 库选型·AssetClass 双枚举收敛·归因 main.py 路由·Agent OS 接 main.py。
- **进程**:push 门控 validate PASS(上波教训应用)。**land**:4 线整批 land main(用户授权)。推进 GOAL §11/§6/§13/§8。**下一步**:各门接真 promote·LINE-G 执行监控·归因路由。

## 2026-06-26 · 第九波 · 1 opus 线 + 中心 drift-guard land（收敛进入"最后一公里生产接线"阶段）
- **派发**：1 deep-opus 线（D 卡 aa13c3b0·因子度量接生产路径剩余 ②③④·后台·独立 worktree）。**未满载 5 线——诚实判断**：读 pool 4 张"消费侧接线"卡发现核心工程价值闭环大都已在前几波关闭（done 卡内联状态注），残余多是用户方法学(B CPCV cv_scheme 双轨 report)/前端 UI(C conformal abstain 呈现)/live(C ACI)味道，盲派 opus 工程线不对；只 D 卡有清晰孤立后端残余。
- **Line D（因子度量→生产路径·§3/§9）**：`wave9/factor-metrics-wiring`(3543aeb)·8 文件·`portfolio/capacity_sizing.py`(容量→sizing 上限·硬上限仅 ok∧真Y∧proposed>cap·占位只示意·运行期逐槽拒 CrowdingAdvisory)+`independence.py`(独立 bet 计数·复用锁定 n_eff·剔零权恒等)+`factor_advisory.py`(只读呈现·crowding 无动作字段)·扩展 closure(只读附证·M-AUTHORITY)+business_tools(portfolio.gate 非禁区路径)·14 对抗测+MUT 三门(placeholder/剔零权/类型隔离·in-place Edit 非 checkout)。**未触禁区**(main.py/instruments/signals/eval.model_eval/training/run_verdict 全未碰)。
- **中心 drift-guard（AssetClass 双枚举单一源·§11）**：勘察发现 wave-8 作者已写死设计——广 instruments.spec.AssetClass(§0 全目录 19 值) ⊇ 窄 strategy_goal.AssetClass(4 值·成本派发)·"token 兼容超集·扩展不替换不改既有窄枚举"。"收敛"真残余=把注释声明钉成机器可证不变量。`tests/test_asset_class_single_source.py`(子集不变量·MUT 加越界 token→转红)·纯 additive 零源码改。下游回填广目录=作者刻意 deferred 大 ripple·留 follow-on(不管太宽·守扩展不替换)。
- **验收**：批次全量 **2632 passed / 13 skipped / 0 failed / 122s**（基线 2628 + D 14 + AssetClass 3·collect 2645 精确吻合·flake 未触发·凭真汇总行非 exit code）+ validate PASS。
- **GOAL-锚定+不建空壳成效（重要）**：勘察否决两个原计划中心活——①归因 main.py 薄路由：`build_factor_attribution_report` 全仓无消费方且 run 无 per-run 因子收益矩阵源·硬接 GET=永远 available:False 空壳；②各门接 promote：release_gate 等需 ReleaseCandidate 全字段输入管线·硬接=空壳/改测试态。按"不建空壳/不假绿灯/不要管太宽"**本波不强接**·诚实记为"需真输入管线的中心串行大活·非一行薄路由"。
- **收敛阶段判断（诚实·非进度焦虑）**：29+ 线建完对象脊柱 + 各门 building blocks·可并行纯 greenfield 基本耗尽·剩余收敛 = "接 main.py/orchestrator 真生产路径"为主(需输入管线·中心串行·部分需用户方法学决策)·波次自然从"5 opus 扇出"收窄为"中心精细串行 + 少量孤立后端残余 opus"。这是收敛的真实形态·不为满载而满载。
- **诚实残余/follow-on**：production sizing 端点硬强制接 main.py(optimize_portfolio 零调用方)·factor advisory UI surface·各门接 promote 真晋级(需 ReleaseCandidate 输入管线)·归因数据源管线(per-run 因子矩阵)·no_edge 生产 sizing 政策(用户方法学待拍·摆代价非阻塞)。
- **进程**：push 门控 validate PASS(应用上波教训)。**land**：D 线 + AssetClass guard 整批 land main(用户授权·回滚兜底)。推进 GOAL §3/§9/§11。**下一步**：production sizing/factor advisory 接 main.py·各门接 promote(需输入管线)·LINE-G 执行监控·归因数据源管线。

## 2026-06-26 · 第十波 · 1 opus 线 land（各门接 promote 的输入管线第一块·自动循环·不等用户）
- **派发**：1 deep-opus 线（卡 f2a9c4e1·promote 证据组装器·后台·独立 worktree）。用户明确"别等我继续·loop 自动循环"→改为自维持：每波 ≥1 后台 opus 线·完成通知即自动 fetch+merge+全量+validate+land+派下一波。
- **Line（promote 证据组装器·§16/§0）**：`wave10/promote-assembler`(682da76)·新建 `release_gate/promote_assembler.py`(run.json→ReleaseCandidate 诚实映射·三入口·只组装输入判定全委派 evaluate_release·缺证据留 None 不编造·执行块缺/非法 mode fail-closed raise)+28 对抗测·**MUT 两门三态**(占位 checksum/空壳 binding)·未触禁区(main.py/ide.promote/release_gate 内部/approval 全未碰)。**意义**：已建 evaluate_release 八门聚合此前无生产调用方·now 有诚实组装器喂它=各门接 promote 的前置输入管线。
- **★ opus 暴露 §16 致命真实未闭合处（高价值发现·KNOWN_RUN_GAPS）**：ide/promote.py 写的 run.json 不带执行诚实标识/dataset checksum/LLMCallRecord/**injection 状态**；尤其 business_tools._synth_and_promote 的 assembly_injected=False 只进返回 dict 不进 run.json → 组装器无从核「声称注入但实为模板基线」（§16 致命「未注入却声称已采用」）。**这精确指明第十一波中心活**：先把 injection 状态写进 run.json（最高优先·§16 致命），组装器才能映射 MODE_TEMPLATE 经 R4 硬拒。
- **验收**：批次全量 **2660 passed / 13 skipped / 0 failed / 118s**（基线 2645 + 28·collect 2673 精确吻合·flake 未触发·凭真汇总行）+ validate PASS。
- **GOAL-锚定+不建空壳**：组装器缺证据绝不编造（缺即标缺·MUT 两门证非纸门）·复用 evaluate_release 零重写判定·单一身份源 ids.content_hash 不另造。工程取舍 ratify：assembly_inputs 在 ReleaseCandidate(禁改)无字段→AssembledRelease 包装(不静默丢·不碰 ReleaseCandidate)。
- **收敛策略（自动循环·诚实）**：进"接 main.py 真生产路径"阶段·把大活拆「opus 建孤立输入管线 lib + 中心串行接 main.py」两步——本波 opus 建组装器（孤立可测·不碰禁区）·十一波中心串行接 promote + 补 run.json 证据落账。
- **进程**：push 门控 validate PASS。codex 复核抓 wave10 卡 status「doing」非法（已修 in_progress）+ 视图过期（已重建）·体现 push-validate 门控价值。**land**：opus 线 land main（用户授权·回滚兜底）。推进 GOAL §16/§0。**下一步（十一波·中心串行）**：① 补 run.json injection 状态/执行诚实/dataset 身份落账（injection 最高优先·§16 致命）② evaluate_run_releasable advisory-first 接 promote 端点 ③ 继续各门接 promote/LINE-G(§12)。

## 2026-06-26 · 第十一波 · 1 opus 线 land（§16 致命「未注入却声称已采用」数据层闭合·自动循环）
- **Line（promote 执行诚实·§16 致命·依赖第十波组装器）**：`wave11/promote-execution-honesty`(8110f99)·+73/-0 纯 additive opt-in 向后兼容。ide/promote.py promote_ide_run 加 opt-in execution_blocks 透传 + business_tools._synth_and_promote 把执行诚实(未注入/模板基线)映射成 {mode:template,result_grade:production} 落进 run.json → 组装器→R4+R5 标签无关硬拒。10 对抗测+MUT 三态(未注入→MODE_TEMPLATE→改 MODE_LIVE 冒充→2 failed→复原)·未触禁区(main.py/release_gate 内部/组装器内部/approval 未碰)。
- **意义**：第十波组装器能读 run.json execution_blocks 判 §16，但 producer 不写=门平凡过。本波 producer 补上→**§16 致命「未注入资产却声称已采用/模板基线冒充生产」在数据生产层闭合**(agent synth 路径)。producer↔consumer 键对齐(mode/result_grade/mock_marked/live_source_ref)。
- **验收**：批次全量 **2670 passed / 13 skipped / 0 failed / 116s**（基线 2673 + 10·collect 2683 精确吻合·flake 未触发·凭真汇总行）+ validate PASS。定向回归 164 passed。
- **GOAL-锚定+不建空壳**：未注入绝不写 live 冒充(MUT 证致命门有牙)·复用 mock_honesty mode/grade 单一源·判定全委派 evaluate_release 零重写·向后兼容(不传块既有全绿)。
- **★ 中心第十二波接端点须知**：template 块固定 result_grade=production→R4+R5 标签无关触发→组装器接 promote 端点后，带组装入参但 DS-1 真注入前的 synth run 会被发版门硬拒(任何标签)=§16 正解(模板冒充不可发版)·接线预期此拒·DS-1 真注入时喂 assembly_injected=True+真 source 自然过门。
- **诚实残余/follow-on**：IDE 沙箱直接 promote 路径 execution_blocks 未填(参数就位·端点未填)·dataset_versions+checksum/LLMCallRecord 仍不带 run.json(KNOWN_RUN_GAPS)。
- **进程**：push 门控 validate PASS。**land**：opus 线 land main(用户授权·回滚兜底)。推进 GOAL §16/§0。**下一步（十二波·中心串行+并行 opus 保活）**：① 中心 evaluate_run_releasable advisory-first 接 promote 端点(main.py 专属) ② 并行孤立 opus：dataset_version/LLMCallRecord 落 run.json·或 IDE 直接 promote 执行诚实·或 LINE-G(§12)。

## 2026-06-26 · 第十二波 · 中心串行 land（§16 发版门 advisory-first 接进 promote 路径·自动循环）
- **中心串行（main.py/promote 专属·无 opus·我自己做）**：把第十波 evaluate_run_releasable 接进 promote_ide_run——§16 发版门真在 promote 路径上跑。`ide/promote.py` 写 run.json 前防御式 advisory：evaluate_run_releasable(manifest)→release_verdict 落 run.json·try/except 兜底(异常落 available:False·绝不破 promote)·默认开·+1 文件 additive。新测试 test_promote_release_advisory.py(5 例)。
- **advisory-first 核心不变量**：模板基线冒充→§16 裁 ok=False(mock 诚实门 R4/R5)且记录·但 promote **仍成功落盘**(只记录绝不 reject 晋级·守不预先削弱方法学也不破基线)。MUT 三态：advisory 改洗白(恒 ok=True 不真跑门)→模板基线测试转红→复原。
- **链条闭合**：§16 八门聚合 release gate(七波)→组装器 run→ReleaseCandidate(十波)→执行诚实落账(十一波)→advisory 接 promote(本波)。**至此已建 §16 发版门从「无生产调用方的孤岛」变成「每个 promoted run 携带可追溯 release_verdict」**——推进 §0 可上线(发版门真跑生产路径)。
- **验收**：全量批次 **2675 passed / 13 skipped / 0 failed / 116s**（基线 2683 + 5·collect 2688 精确吻合·flake 未触发·凭真汇总行）+ validate PASS。**改 promote_ide_run(众多 promote 测试共用)零回归** = advisory 真 additive 非破坏。
- **GOAL-锚定+不建空壳**：advisory 只记录不 reject(不预先削弱·不破基线)·防御式不破 promote·复用 evaluate_release 零重写·MUT 证门有牙·异常落诚实标不假绿灯。
- **诚实残余/follow-on**：enforce(硬卡晋级)=后续显式决策(需先补 dataset/LLM/IDE 直接 promote 证据否则误拒合法 run·摆代价待定)·dataset_versions+checksum/LLMCallRecord/IDE 直接 promote execution_blocks 续补(KNOWN_RUN_GAPS)·main.py GET release_check 只读端点暴露给前端。
- **进程**：push 门控 validate PASS。**land**：中心串行 land main(用户授权·回滚兜底)。推进 GOAL §16/§0。**下一步（自动循环）**：派孤立 opus 续补 run.json 证据(dataset/LLM/IDE 路径)保活循环 + 中心评估 GET release_check 端点/enforce 时机。

## 2026-06-26 · 第十三波 · 1 opus 线 land（§13 信任层接 agent orchestrator advisory）+ 会话交接
- **Line（§13 信任层接 orchestrator·§13/§7）**：`wave13/trust-orchestrator-advisory`(970e255)·+586/-2 additive。攻入点=orchestrator Review 形态新增 advise_trust(ctx:TrustContext)→TrustAdvisory·新建 trust_advisory.py(判定零重写全委派 app.trust.evaluate_trust)。未触禁区(main.py/trust 内部/release_gate/governance/GovernedToolDispatcher 全未碰)。
- **advisory-first + ★ 命门不降级（关键正确处理·已入 experience 思路）**：软门(诚实/反谄媚/弱点披露/责任/用户自主)只 flag+投影 VerifierChallengeRaised·不阻断 orchestrator 主流程；§13 命门(secret/OrderGuard/kill switch/no-silent-mock 被 waiver 绕)=fail-closed 硬墙·evaluate_trust raise SafetyWaiverError·本层不吞(吞=降级削弱命门)·投不变量名(不回显 target 文本免泄 secret)后原样 re-raise。
- **验收**：批次全量 **2692 passed / 13 skipped / 0 failed / 118s**（基线 2675 + 17·collect 2705·flake 未触发·凭真汇总行）+ validate PASS。opus scoped+回归 157 passed(含 4 对抗+MUT 三态)。
- **诚实残余/follow-on**：free-text→TrustContext 映射(不自动抽姿态·避脆弱启发式越权重判·上游另卡)·接 main.py 真 agent 端点·§8 governance 接 orchestrator(平行另卡)。
- **进程**：push 门控 validate PASS。**land**：opus 线 land main。推进 GOAL §13/§7。
- **━━ 会话交接 ━━**：用户开新会话接续编排·本会话止于第十三波·**不派十四波**(新会话从 state 顶部块就绪前沿起步)。已存：dev/experience 两条工程经验(land 913af35)·项目 memory feedback_central_orchestrator_autoloop(协作模式+接续)·更新版编排提示词(给用户)。下一波候选见 state 顶部块(§8 governance 接 orchestrator / free-text→TrustContext / 接 main.py 端点 / §16 enforce 时机 / LINE-G §12 / §10 消费侧 / AssetClass 回填)。
## 2026-06-26 · Document Intelligence local parser-to-RAG ingestion（79b5e526）

- **取前沿**：active 四卡仍为 `review_status:0`，未实现；按 GOAL/state/TRACE 的 §5/§6 明确 gap 新 mint `79b5e526`（review_status=1）承接 Document source ingestion。
- **runtime**：`parse_local_text_document` 新增本地 no-network UTF-8 text/Markdown parser；拒绝 absolute/`..`/symlink/隐藏敏感路径/unsupported suffix/empty/oversized/NUL/non-UTF8；产 `SourceDocumentIntakeRecord` + verified `EvidenceSpanRecord`。
- **API/RAG**：新增 `POST /api/research-os/documents/parse_local`，先构造 RAG candidate-context 文档并过 secret guard，再写 Document store + Research Asset RAG index；secret-bearing body 422 时不留 partial Document JSONL。
- **测试**：新增 `tests/test_document_intelligence_parser_rag.py` 5 测；parser+Document/RAG scoped **16 passed / 2 warnings**，§5/§6 adjacent **28 passed / 2 warnings**，Research OS scoped **188 passed / 2 warnings**，后端全量 **1504 passed / 13 skipped / 278 warnings**。
- **落档**：`79b5e526` moved done；更新 `state/dreaminate/state.md` 与 `research/TRACE.md`。边界仍诚实：这只是 local text/Markdown ingestion，不是 PDF/web parser、前端 document search UI、vector search 或 Agent Shell 自动检索。

## 2026-06-26 · Research Asset RAG sparse vector search backend（6f5cad5c）

- **取前沿**：§5 仍有 `vector search` gap；新 mint `6f5cad5c`（review_status=1）承接后端第一版 sparse-vector search seam。
- **runtime/API**：`ResearchAssetRAGIndex.vector_search` 使用 deterministic sparse token-vector cosine over existing RAG documents；复用 projection filter、`_visible()` 权限门、`AssetRAGHit` candidate-context 形态；新增 `POST /api/research-os/rag/vector_search`，agent actor 复用 `AgentRAGUsage` source/version ledger。
- **测试**：扩 `tests/test_research_asset_rag_persistence.py`，覆盖排序、unauthorized desk denied、candidate_context 不变和 agent usage；RAG scoped **11 passed / 2 warnings**，§5/§6 adjacent **29 passed / 2 warnings**，Research OS scoped **189 passed / 2 warnings**，后端全量 **1505 passed / 13 skipped / 278 warnings**。
- **落档**：`6f5cad5c` moved done；更新 `state/dreaminate/state.md` 与 `research/TRACE.md`。边界仍诚实：这不是 dense embedding、外部 embedding provider、vector DB、frontend search UI 或 Agent Shell 自动检索。

## 2026-06-26 · Document Intelligence local PDF text parser ingestion（038d2c8b）

- **取前沿**：§6 仍有 PDF parser gap；本波先做 local PDF text extraction，不做 OCR、layout verification、web parser 或前端 UI。
- **runtime/API**：`parse_local_document` 统一 text/Markdown/PDF；PDF path 要求 `%PDF-` magic，使用本地 `pypdf` no-network extraction，拒绝 encrypted PDF、page 超限和无文本 PDF；`parse_local` API 继续写 Document store + ResearchRAG candidate context，不返回 raw extracted text。
- **测试**：`tests/test_document_intelligence_parser_rag.py` 增 generated-PDF success + fake-PDF magic fail-closed；parser scoped **7 passed / 2 warnings**，§5/§6 adjacent **31 passed / 2 warnings**，Research OS scoped **191 passed / 2 warnings**，后端全量 **1507 passed / 13 skipped / 278 warnings**。
- **落档**：`038d2c8b` moved done；更新 `state/dreaminate/state.md` 与 `research/TRACE.md`。边界仍诚实：这不是 OCR、layout-aware PDF parser、web parser、frontend document UI、dense embedding 或外部 PDF service。

## 2026-06-26 · Agent Shell automatic Research Asset RAG retrieval（d1b14723）

- **取前沿**：active 四卡仍为 `review_status:0`，未实现；§5/§6/§7 的明确 gap 是 Agent Shell 自动 RAG。新 mint `d1b14723`（review_status=1）承接 `/api/agent/chat` 主入口。
- **runtime/API**：`AgentRuntime` 新增 optional RAG context provider；`/api/agent/chat` 在 current user + `visible_asset_refs` 存在时按 user/desk/asset/tag permission 走 Research Asset RAG lexical/vector search，写 `AgentRAGUsage`，把 `rag:<source>@<version>:<asset>` 与 `rag_usage:<id>` 写入 QRO/ResearchGraphCommand evidence refs。无 current user 或无 visible assets 时不猜权限、不检索。
- **测试**：`tests/test_agent_runtime_research_graph.py` 增 authorized auto retrieval + unauthorized desk denied；AgentRuntime scoped **8 passed / 2 warnings**，RAG+Agent scoped **19 passed / 2 warnings**，Agent scoped **77 passed / 2 warnings**，Research OS scoped **199 passed / 2 warnings**，后端全量 **1509 passed / 13 skipped / 278 warnings**。
- **落档**：`d1b14723` moved done；更新 `state/dreaminate/state.md` 与 `research/TRACE.md`。边界仍诚实：只覆盖 `/api/agent/chat`，不等于 workbench stream、legacy Mode2 chat、前端 RAG UI、web/OCR parser、dense embedding/vector DB 或全资产批量 ingestion。

## 2026-06-26 · Agent workbench stream Research Asset RAG retrieval（29a283af）

- **取前沿**：`d1b14723` 只覆盖 `/api/agent/chat`；§7 workbench stream 仍未接 RAG。新 mint `29a283af`（review_status=1）承接 `/api/agent/workbench/stream`。
- **runtime/API**：workbench SSE endpoint 新增 `desk`、`visible_asset_refs`、`permission_tags`、`projections`、`rag_search`、`rag_top_k` query params；只有显式 `visible_asset_refs` + current user 时才复用 `_agent_shell_rag_context_provider`。RAG refs 通过 AgentRuntime system step 投影为 `say` frame，done frame 增 `rag_hits`/`rag_usage_ids`。
- **测试**：`tests/test_agent_business_tools_a4.py` 增 authorized workbench RAG SSE；workbench scoped **23 passed / 2 warnings**，RAG+Agent scoped **42 passed / 2 warnings**，Research OS scoped **222 passed / 2 warnings**，后端全量 **1510 passed / 13 skipped / 278 warnings**。
- **落档**：`29a283af` moved done；更新 `state/dreaminate/state.md` 与 `research/TRACE.md`。边界仍诚实：不等于 legacy Mode2 chat、前端 RAG UI、web/OCR parser、dense embedding/vector DB 或全资产批量 ingestion。

## 2026-06-27 · legacy Mode2 chat thread Research Asset RAG retrieval（199d3c00）

- **取前沿**：active 四卡仍为 `review_status:0`，未实现；§5/§6/§7 的明确 gap 是 legacy Mode2 chat 自动 RAG。新 mint `199d3c00`（review_status=1）承接旧 thread chat non-stream + stream 两入口。
- **runtime/API**：`POST /api/agent/chat/{thread_id}/message` 复用 `_agent_shell_rag_context_provider`；只有 current user + 显式 `visible_asset_refs` 时才检索，旧 glossary RAG 保留。metadata 新增 `research_asset_rag_hits` / `research_asset_rag_usage_ids`，non-stream 通过 AgentRuntime 把 `rag:<source>@<version>:<asset>` 和 `rag_usage:<id>` 写入 Research Graph evidence refs。`GET /api/agent/chat/{thread_id}/stream` 新增 `desk`、`visible_asset_refs`、`permission_tags`、`projections`、`rag_search`、`rag_top_k` query params；命中时注入 Mode2 prompt、发 `event: research_rag`，assistant metadata 记录命中与 usage。
- **测试**：`tests/test_chat_conversations.py` 增 legacy non-stream authorized RAG、no-visible-assets 不检索、stream RAG SSE/metadata 三测；legacy chat scoped **25 passed / 2 warnings**，RAG+Agent legacy scoped **67 passed / 2 warnings**，后端全量 **1513 passed / 13 skipped / 278 warnings**。
- **落档**：`199d3c00` moved done；更新 `state/dreaminate/state.md` 与 `research/TRACE.md`。边界仍诚实：不等于前端 RAG UI、web/OCR parser、dense embedding/vector DB、全资产批量 ingestion、完整 graph database 或所有 agent 入口贯通。

## 2026-06-27 · Document Intelligence HTML/web snapshot parser-to-RAG ingestion（f27c07fb）

- **取前沿**：§6 仍有 web parser gap；按 GOAL Source intake 的 `URL allowlist` + `no network parser` 约束，新 mint `f27c07fb`（review_status=1）承接本地 HTML/web snapshot parser，不做联网抓取。
- **runtime/API**：`parse_local_document` 新增 `.html/.htm` 分支；调用方必须传 `source_url` 与 `allowed_url_hosts`。parser 只允许 https 且 host 命中 allowlist，拒绝 URL userinfo 和 path/query 中的 token/api_key/password/secret 等凭据；本地 UTF-8 snapshot 不联网、不执行脚本，跳过 script/style/noscript/svg/canvas/template，只把 visible text 切 EvidenceSpan。`POST /api/research-os/documents/parse_local` 透传 `source_url`/`allowed_url_hosts`，response 和 RAG metadata 带 source_url，但不返回 raw text。
- **测试**：`tests/test_document_intelligence_parser_rag.py` 增 HTML snapshot success、host 不在 allowlist、tokenized URL fail-closed 三测；parser scoped **10 passed / 2 warnings**，§5/§6 adjacent scoped **90 passed / 2 warnings**，后端全量 **1516 passed / 13 skipped / 278 warnings**。
- **落档**：`f27c07fb` moved done；更新 `state/dreaminate/state.md` 与 `research/TRACE.md`。边界仍诚实：这是 no-network web snapshot parser，不是 live URL fetch/crawler；仍未覆盖 OCR/layout-aware PDF parser、前端 RAG UI、dense embedding/vector DB、全资产批量 ingestion 或完整 graph database。

## 2026-06-27 · Document Intelligence explicit batch parser-to-RAG ingestion（3f7b39d1）

- **取前沿**：§5/§6 仍有批量 ingestion gap；新 mint `3f7b39d1`（review_status=1）承接显式 item list batch，不做自动扫目录或真实资产库全量同步。
- **runtime/API**：新增 `POST /api/research-os/documents/parse_local_batch`；每个 item 复用单文档 text/Markdown/PDF/HTML snapshot parser、rights、URL allowlist、RAG permission 和 secret guard。endpoint 先 parse/build 全部 `AssetRAGDocument`，再统一写 `DOCUMENT_INTELLIGENCE_STORE` 与 `RESEARCH_ASSET_RAG_INDEX`；任一 item 失败时全批 422 且不写 partial；同批重复 `source_path/source_url` 422。
- **测试**：`tests/test_document_intelligence_parser_rag.py` 增 mixed markdown+HTML batch success、bad second item atomic no partial、duplicate source path fail-closed 三测；parser scoped **13 passed / 2 warnings**，§5/§6 adjacent scoped **93 passed / 2 warnings**，后端全量 **1519 passed / 13 skipped / 278 warnings**。
- **落档**：`3f7b39d1` moved done；更新 `state/dreaminate/state.md` 与 `research/TRACE.md`。边界仍诚实：这是显式 item list batch，不是自动扫描真实资产库或全库同步；仍未覆盖 OCR/layout-aware PDF parser、前端 RAG UI、dense embedding/vector DB 或完整 graph database。

## 2026-06-27 · Settings-managed LLM Gateway runtime enforcement（de77a28c）

- **取前沿**：active board / pool 为空，但 GOAL §4/§7/§8/§16 和 state/TRACE 仍有 Settings/Secrets/LLM Gateway runtime enforcement 缺口；新 mint `de77a28c` 落档 done，承接 LLM configure/test/runtime seam，不覆盖完整 Settings UI/OAuth/provider adapter。
- **runtime/API**：`app.agent.llm_providers` 新增 `make_settings_managed_llm_client`，真实 provider 解析只认 `SecureKeystore` + `PersistentOnboardingRegistry`；`/api/llm/configure` 继续把明文 key 写 keystore，同时写 SecretRef/LLMProvider/CredentialPool/RoutingPolicy metadata；`/api/llm/status` 展示 settings-managed 状态；`/api/llm/test` 和 `_current_agent_llm` 改走 Gateway resolver。
- **坏门**：env key 不能让 role-agent 绕过 Settings；revoked/missing SecretRef 会 fail-closed；配置响应/status/metadata 不回显明文 key。
- **测试**：LLM/Settings scoped **29 passed / 2 warnings**；runtime adjacent scoped **132 passed / 2 warnings**；`cd app/backend && python -m compileall -q app` -> PASS；后端全量 **1585 passed / 13 skipped / 283 warnings**。
- **落档**：新增 done 卡 `de77a28c`；更新 `dev/research/TRACE.md`、`dev/state/dreaminate/state.md`；`python dev/scripts/validate_dev.py` -> **49 ✅ / 0 ❌ / 0 ⚠️ PASS**。边界：未验证外部 LLM 实网连通，不等于完整 Settings UI、OAuth/device-code/account auth、所有 provider/connector adapter、生产 keystore backend 选择或完整 connection wizard。

## 2026-06-27 · Settings-managed LLM connection wizard UI（21d99c19）

- **取前沿**：`de77a28c` 后端 Gateway resolver 已接，但 `/settings/llm` 仍看不到 Settings refs，也不能在配置页内完成保存后测试连接；新 mint `21d99c19` 落档 done。
- **runtime/UI**：`LLMSettingsPage` provider 卡显示 Gateway managed / auth status / SecretRef / Pool / Policy，并新增同页 `/api/llm/test` 按钮；configure 成功回执只显示 `SecretRef` 和 Settings metadata，不回显 key、不宣称已连通。`SettingsSecurityPage` 的 LLM Providers 面板改用 `authFetch` 和同一 refs/status 字段。
- **坏门**：前端 refs 状态不泄露 API key；configure 成功不写“已连通”；connection test 成功/失败按后端返回显示，失败不报成功。
- **测试**：LLM Settings UI scoped **1 file / 9 tests passed**；前端全量 **26 files / 292 tests passed**；frontend build **tsc + vite PASS**（保留既有 chunk size warning）。
- **落档**：新增 done 卡 `21d99c19`；更新 `dev/research/TRACE.md`、`dev/state/dreaminate/state.md`。边界：这不是完整 Settings UI、OAuth/device-code/account auth、所有 provider/connector adapter、生产 keystore backend 选择、CI/线上部署或外部 LLM 实网连通证明。

## 2026-06-27 · StrategyConsole Research Graph edge relation write-back（ddec60c2）

- **取前沿**：state/TRACE 仍把 GraphCanvas 连线、删除、参数/Ghost/Auto 写回列为画布真实性残余；新 mint `ddec60c2` 先闭合真实 projection edge relation ref/hash 写回，不做自由建边或删除。
- **runtime/UI**：选中真实 Research Graph projection edge 后，Inspector 显示 edge relation 面板；点击“记录连线”调用 `/api/research-os/graph/canvas_asset_mutations` 写 `output_contract.canvas_edge_ref/hash`，带 canonical/audit/evidence refs，成功后重拉 projection。
- **坏门**：前端请求 body 不含 edge `from`/`to` raw payload，也不含 `raw_value`；后端 projection audit 不泄露 `canvas_edge_ref/hash` 值。
- **测试**：StrategyConsole scoped **1 file / 30 tests passed**；Research Graph scoped **14 passed / 2 warnings**；Graph/Compiler/StrategyConsole/standards adjacent scoped **65 passed / 2 warnings**；前端全量 **26 files / 293 tests passed**；frontend build **tsc + vite PASS**。
- **落档**：新增 done 卡 `ddec60c2`；更新 `dev/research/TRACE.md`、`dev/state/dreaminate/state.md`。边界：这不是自由建边、删除、参数/Ghost/Auto 写回、完整 graph database、CI 或线上部署证明。

## 2026-06-27 · Research Graph first-class QRO-to-QRO edge creation（87ec505c）

- **取前沿**：`3a17e940` 只做 connect-intent ref/hash，`aa74a817` 闭合 Ghost/Auto intent；state/TRACE 仍把真实 Graph edge creation 列为画布真实性缺口。新 mint `87ec505c` 做第一版 first-class QRO-to-QRO edge，不做 tombstone、patch application 或完整 graph DB。
- **runtime/API**：新增 `ResearchGraphEdgeRecord` + `record_graph_edge` command schema，`PersistentResearchGraphStore` 可 JSONL replay；新增 `POST /api/research-os/graph/edges`，要求 canonical/audit/evidence refs，拒绝 raw value、未知 QRO、same-QRO edge 和 live QRO topology edit。
- **projection/UI**：`/api/research-os/graph/canvas_projection` 会把当前可见 QRO 两端的 edge 渲染为 `canvas_edge:graph:*`；StrategyConsole 真实 projection 两步连接改为 QRO-to-QRO edge creation，不再把 command-node→QRO 内部投影边伪装成用户 Graph edge。
- **坏门**：前端 edge create 请求 body 不含 `canvas_node:*`、`port` 或 raw endpoint object；projection 不泄露 QRO input/output contract 原值。
- **测试**：Research Graph scoped **20 passed / 2 warnings**；Graph/ResearchOS/Agent/Compiler/StrategyConsole adjacent scoped **142 passed / 2 warnings**；StrategyConsole scoped **1 file / 36 tests passed**；前端全量 **26 files / 299 tests passed**；frontend build **tsc + vite PASS**。
- **落档**：新增 done 卡 `87ec505c`。边界：这是 first-class QRO-to-QRO edge creation，不是真实 Graph deletion、Ghost/Auto patch application、完整 graph database、完整 compiler pass、CI 或线上部署证明。

## 2026-06-27 · Research Graph edge tombstone deletion（f509953e）

- **取前沿**：`87ec505c` 已有 first-class QRO-to-QRO edge creation；删除仍停在 `canvas_delete_ref/hash` intent。新 mint `f509953e` 做 append-only edge tombstone，不做 QRO node tombstone 或完整 graph deletion。
- **runtime/API**：新增 `ResearchGraphEdgeDeletionRecord` + `delete_graph_edge` command schema；`ResearchGraphStore.graph_edges()` 默认过滤 tombstoned edge，`include_deleted=True` 保留历史；新增 `POST /api/research-os/graph/edge_deletions`，要求 canonical/audit/evidence refs，拒绝 raw value、未知 edge 和 live QRO topology edit。
- **projection/UI**：`canvas_projection` 不再显示 tombstoned `canvas_edge:graph:*`；StrategyConsole 选中真实 graph edge 后 Delete/Inspector 删除走 tombstone endpoint。旧 command→QRO projection edge 仍走 delete-intent ref/hash write-back，不混淆。
- **坏门**：前端 deletion body 只提交 `edge_ref` 和 canonical/audit/evidence refs，不提交 `canvas_node:*`、`port`、`from`/`to` raw endpoint object。
- **测试**：Research Graph scoped **22 passed / 2 warnings**；Graph/ResearchOS/Agent/Compiler/StrategyConsole adjacent scoped **144 passed / 2 warnings**；StrategyConsole scoped **1 file / 37 tests passed**；前端全量 **26 files / 300 tests passed**；frontend build **tsc + vite PASS**。
- **落档**：新增 done 卡 `f509953e`。边界：这是 first-class edge tombstone deletion，不是 QRO node tombstone、Graph node deletion、Ghost/Auto patch application、完整 graph database、完整 compiler pass、CI 或线上部署证明。

## 2026-06-27 · Research Graph QRO node tombstone deletion（7070feed）

- **取前沿**：`f509953e` 已有 first-class edge tombstone；QRO node 删除仍停在 `canvas_delete_ref/hash` intent。新 mint `7070feed` 做 append-only QRO tombstone，不做 restore、Ghost/Auto patch application 或完整 graph DB。
- **runtime/API**：新增 `QROTombstoneRecord` + `tombstone_qro` command schema；`ResearchGraphStore.qro()` / `projection_index()` 默认过滤 tombstoned QRO，`include_tombstoned=True` 保留历史；`graph_edges()` 默认过滤 tombstoned QRO 相关 active edge，`include_deleted=True` 保留历史 edge。新增 `POST /api/research-os/graph/qro_tombstones`，要求 canonical/audit/evidence refs，拒绝 raw value、未知 QRO 和 live QRO tombstone。
- **projection/UI**：`canvas_projection` 不再显示 tombstoned `canvas_node:qro:*` 或其相关 active `canvas_edge:graph:*`；StrategyConsole 选中真实 QRO node 后 Delete/Inspector 删除走 tombstone endpoint。旧 command→QRO projection edge 仍走 delete-intent ref/hash write-back，不混淆。
- **坏门**：前端 QRO tombstone 请求 body 不含 `canvas_node:*`、params 或 raw node object；projection 不泄露 QRO input/output contract 原值。
- **测试**：Research Graph scoped **24 passed / 2 warnings**；Graph/ResearchOS/Agent/Compiler/StrategyConsole adjacent scoped **146 passed / 2 warnings**；StrategyConsole scoped **1 file / 37 tests passed**；前端全量 **26 files / 300 tests passed**；frontend build **tsc + vite PASS**（仍有既有 chunk size warning）。
- **落档**：新增 done 卡 `7070feed`。边界：这是 QRO node tombstone，不是 restore command、完整 graph database、Ghost/Auto patch application、完整 compiler pass、CI 或线上部署证明。

## 2026-06-27 · Research Graph Ghost/Auto patch application（1af10281）

- **取前沿**：`aa74a817` 只做 Ghost/Auto intent ref/hash，`7070feed` 已补 QRO node tombstone；Ghost/Auto 仍缺真实 Graph application。新 mint `1af10281` 做 `apply_graph_patch` + patch QRO + graph edge，不做 operation-level raw patch replay、revert 或完整 agent patch lifecycle。
- **runtime/API**：新增 `GraphPatchApplicationRecord` + `apply_graph_patch` command schema；新增 `POST /api/research-os/graph/patch_applications`，要求 target QRO、patch kind/ref/hash、canonical/audit/evidence refs，拒绝 raw `ops`/`diff`/`node`/`edge`/`params`/`payload`/`raw_value`、未知 target 和 live target。成功后写 `apply_graph_patch`、patch QRO `upsert_qro`、`record_graph_edge` 三条 command。
- **projection/UI**：StrategyConsole Ghost accept / Auto send 改为调用 patch application endpoint，成功后重拉 projection；`canvas_projection` 显示 `GraphPatchApplication` QRO 和 `canvas_edge:graph:*`，但不显示 raw proposal ops、DrawdownGuard raw node 或 patch hash。
- **坏门**：前端 patch request body 只提交 target QRO、patch kind/ref/hash 和 refs，不提交 `ops`、`varcvar`、`DrawdownGuard` 或 raw node object。
- **测试**：Research Graph scoped **26 passed / 2 warnings**；Graph/ResearchOS/Agent/Compiler/StrategyConsole adjacent scoped **148 passed / 2 warnings**；StrategyConsole scoped **1 file / 37 tests passed**；前端全量 **26 files / 300 tests passed**；frontend build **tsc + vite PASS**（仍有既有 chunk size warning）。
- **落档**：新增 done 卡 `1af10281`。边界：这是 GraphPatchApplication QRO + edge，不是 operation-level raw patch replay、patch revert、完整 agent patch lifecycle、完整 graph database、完整 compiler pass、CI 或线上部署证明。

## 2026-06-27 · Research Graph canvas parameter value save（9a6db34e）

- **取前沿**：`a63af9d7` 只做 QRO-node parameter ref/hash intent，`1af10281` 已补 Ghost/Auto patch application；自由参数值仍未保存。新 mint `9a6db34e` 做 `set_canvas_parameter` value-level record + QRO ref/hash，不做完整参数 schema 或 secret 参数存储。
- **runtime/API**：新增 `CanvasParameterValueRecord` + `set_canvas_parameter` command schema；新增 `POST /api/research-os/graph/canvas_parameter_values`，要求 target QRO、target asset type、param key/value、canonical/audit/evidence refs，拒绝 raw wrapper fields、secret-like value、未知 target 和 live target。成功后写 `set_canvas_parameter` 与 QRO `upsert_qro` 两条 command。
- **projection/UI**：StrategyConsole Inspector 新增参数名/参数值输入；“记录参数”走 value-level endpoint，成功后重拉 projection。QRO output contract 只保存 `canvas_param_value_ref/hash` 和 `canvas_param_key`，projection 不泄露具体参数值。
- **坏门**：前端 parameter request body 不提交 `node.params` 整包、`raw_value` 或 context payload；后端 projection 不含 `45%/w`、parameter_ref 或 value_hash。
- **测试**：Research Graph scoped **28 passed / 2 warnings**；Graph/ResearchOS/Agent/Compiler/StrategyConsole adjacent scoped **150 passed / 2 warnings**；StrategyConsole scoped **1 file / 37 tests passed**；前端全量 **26 files / 300 tests passed**；frontend build **tsc + vite PASS**（仍有既有 chunk size warning）。
- **落档**：新增 done 卡 `9a6db34e`。边界：这是参数值 record + QRO ref/hash，不是完整参数 schema/类型系统、secret 参数存储、所有节点/边布局、完整 graph database、完整 compiler pass、CI 或线上部署证明。

## 2026-06-27 · Monitor weekly scheduler tick writes Observable QRO（10b23996）

- **取前沿**：GOAL §0 明写 Chat / Canvas / API / IDE / Scheduler 都要能产生 QRO；Agent/API/IDE/Canvas 已有多片，weekly monitor scheduler 仍只返回业务结果。新 mint `10b23996` 先闭合 production weekly monitor tick 的 scheduler-origin Graph 写入，不做所有 scheduler/API/execution 入口。
- **runtime/API**：`MonitorRuntime` 增加 `result_recorder` hook；DAG op 成功后把 `WeeklyMonitorResult` 交给 recorder。`main.py` 新增 weekly monitor QRO helper，写 `QROType.OBSERVABLE`、`EntrySource.SCHEDULER`，只保存 result hash、计数和 scheduler refs，不复制 cost drift report、factor observation 或 actions payload。
- **endpoint/DAG**：`/api/monitor/weekly_tick` 成功响应新增 `qro_id` / `research_graph_command_id` / `research_graph_result_hash`；startup monitor runtime 绑定同一 recorder，DAG scheduler op 成功也会返回 Graph refs。
- **坏门**：gate verdict/DSR/PBO 作为 observation 输入仍 422，且不写 Graph；audit summary 不泄露 factor id、cost report 或 actions 详情。
- **测试**：monitor scoped **6 passed / 2 warnings**；monitor/Graph/Agent/entrypoint adjacent scoped **49 passed / 2 warnings**；monitor/Graph/Agent/entrypoint/Research OS/coverage/standards expanded scoped **74 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 146）。
- **落档**：新增 done 卡 `10b23996`。边界：这是 weekly monitor scheduler tick 的 QRO 写入，不是所有 scheduler/API/execution 入口贯通、完整 runtime promotion、CI/线上 scheduler 证明或 live broker 连通证明。

## 2026-06-27 · Training success writes Model QRO（a2f46b22）

- **取前沿**：训练台成功路径已有 ModelRegistry version、ModelPassport 和 ValidationDossier refs，但不会写 QRO/Research Graph。新 mint `a2f46b22` 闭合“训练成功产模型版本 → Model QRO”，不把 queued/failed/free-code no-artifact job 伪装成模型资产。
- **runtime/API**：`TrainingJob` 增加 `qro_id` / `research_graph_command_id`；`TrainingService` 增加 `result_recorder`，只在 job `succeeded` 且 `model_version` 已登记后调用。`main.py` 新增 `_record_training_job_qro`，写 `QROType.MODEL` / `EntrySource.API`。
- **审计边界**：QRO 只保存 job/model/version/passport/dossier/run refs、request hash、metrics hash 和计数；不复制 metrics 明细、artifact_dir、artifact_path 或模型二进制路径。轮询 `GET /api/training/jobs/{job_id}` 可看到 QRO refs。
- **坏门**：训练仍必须先完成现有 ModelPassport/ValidationDossier/ModelRegistry version 路径；无模型版本成功 job 不写 Model QRO。
- **测试**：新增单测 **1 passed / 2 warnings**；training/model governance/Graph adjacent scoped **99 passed / 2 warnings**；training+monitor+Research OS/coverage/standards expanded scoped **135 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 147）。
- **落档**：新增 done 卡 `a2f46b22`。边界：这是训练成功 Model QRO 写入，不是 Model Registry promotion QRO、runtime serving、完整 compiler/codegen、sandbox artifact inspection process、live model promotion 或所有模型相关 API 入口贯通。

## 2026-06-27 · Training success compiler coverage（54b60744）

- **取前沿**：`a2f46b22` 已让训练成功产模型版本路径写 Model QRO，但训练入口仍未自动生成 compiler IR/pass 和 entrypoint coverage。新卡把训练成功 QRO 接到同一条 Governed Compiler coverage 路径。
- **runtime/API**：`_record_training_job_qro` 写 Research Graph 后调用 `_compile_training_job_qro`，返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`；`TrainingJob` snapshot 与 job detail API 透传这些 refs。
- **refs contract**：compiler 记录绑定 ModelVersion、ModelPassport、ValidationDossier、training job、request hash、metrics hash、permission、environment lock 和 deterministic run plan refs；不复制 metrics 明细、artifact_dir、artifact_path 或模型二进制路径。
- **对抗门**：测试断言 IR/pass/coverage 绑定同一 QRO + Graph command，`entry_source=api`、`actor_source=agent`、permission=`training.job:service`，且 compiled text 不含 `r2` 或 artifact path。
- **测试**：`tests/test_training_api.py` **10 passed / 2 warnings**。
- **落档**：新增 done 卡 `54b60744`。边界：这是训练成功入口的 compiler/coverage producer，不是 Model Registry promotion coverage、完整 compiler codegen、runtime auto-promotion、live model serving、CI、线上训练集群或用户验收。

## 2026-06-27 · Model Registry promotion writes Model QRO（6c3d8f21）

- **取前沿**：`a2f46b22` 已把训练成功产模型版本路径写入 Model QRO，但 Model Registry promotion 仍只写 approval gate / ModelVersion store。新 mint `6c3d8f21` 闭合 promotion request + approval 两个成功路径的 Model QRO。
- **runtime/API**：`/api/models/{model_id}/promote` 成功返回 pending gate 时写 `Model` QRO，并返回 `qro_id` / `research_graph_command_id`；`/api/models/{model_id}/gates/{gate_id}/approve` 成功真翻 stage 后写第二条审批 `Model` QRO。
- **审计边界**：promotion request QRO 只保存 ModelVersion/ApprovalGate/ModelPassport/ValidationDossier refs 与 `evidence_hash`；approval QRO 只保存 `reason_hash` / `risk_restated_hash` / `side_effect_ref`。不复制 DSR/PBO/champion raw evidence、审批理由正文、metrics 明细或 artifact path。
- **坏门**：pending gate 不标成 approval；approval 不标成 live serving readiness、safe loading approval 或执行许可；现有 ModelPassport / ValidationDossier / approval gate 门不改弱。
- **测试**：`test_model_governance.py` **19 passed / 2 warnings**；training/model governance/Graph/entrypoint/Research OS/coverage/standards adjacent scoped **126 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 148）。
- **落档**：新增 done 卡 `6c3d8f21`。边界：这是 Model Registry promotion 成功开门和成功审批 QRO，不是 rejected gate QRO、runtime serving、独立 sandbox artifact inspection process、remote artifact store、runtime auto-promotion、live model serving 或所有模型相关 API 入口贯通。

## 2026-06-27 · Rejected Model Registry promotion writes Model QRO（e4f2a1c9）

- **取前沿**：`6c3d8f21` 已覆盖 pending gate 和 approve success；rejected promotion gate 仍只由 endpoint 422 + approval store 体现。新 mint `e4f2a1c9` 闭合 rejected gate QRO。
- **runtime/API**：`POST /api/models/{model_id}/promote` 遇 `GateRejection` 仍返回 422，但 detail 带 `qro_id` / `research_graph_command_id`；后端查回 stored gate 写 rejected `Model` QRO。
- **审计边界**：QRO 输出 `gap_count` / `gaps_hash` / `verdict_hash` / `evidence_hash`，不复制缺口正文、verdict 文案、DSR/PBO/champion raw evidence、metrics 明细或 artifact path。
- **坏门**：三角证据不同向仍 422；rejected QRO 不标成 pending/approved；现有 ModelPassport / ValidationDossier / approval gate 门不改弱。
- **测试**：`test_model_governance.py` **20 passed / 2 warnings**；training/model governance/Graph/entrypoint/Research OS/coverage/standards adjacent scoped **127 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 149）。
- **落档**：新增 done 卡 `e4f2a1c9`。边界：这是 rejected promotion gate QRO，不是 runtime serving、独立 sandbox artifact inspection process、remote artifact store、runtime auto-promotion、live model serving 或所有模型相关 API 入口贯通。

## 2026-06-27 · Model Registry promotion compiler coverage（ee8040b9）

- **取前沿**：`6c3d8f21` / `e4f2a1c9` 已让 promotion pending、approval success 和 rejected gate 写 Model QRO，但 promotion API 仍未自动生成 compiler IR/pass 和 entrypoint coverage。新卡把三条 Model Registry QRO 接到 compiler coverage。
- **runtime/API**：新增 `_compile_model_registry_qro`，`_record_model_promotion_request_qro` 与 `_record_model_promotion_approval_qro` 写 Graph 后返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
- **refs contract**：compiler 记录绑定 ModelVersion、ModelPassport、ValidationDossier、approval gate、request hash、permission、environment lock 和 deterministic run plan refs；pending/rejected coverage entrypoint 是 `api:models.promote`，approval coverage entrypoint 是 `api:models.gates.approve`。
- **对抗门**：测试覆盖 pending、rejected、approved 三条路径；compiled text 不含 DSR/PBO/champion raw evidence、中文 gap/verdict、approval reason 或 risk restatement 正文。
- **测试**：`test_model_governance.py` **31 passed / 2 warnings**。
- **落档**：新增 done 卡 `ee8040b9`。边界：这是 Model Registry promotion 的 compiler/coverage producer，不是完整 compiler codegen、runtime auto-promotion、live model serving、CI、线上或用户验收。

## 2026-06-27 · Model governance monitoring and recertification records（f6d7a3b8）

- **取前沿**：§15 仍把 `MonitoringProfile` / `RecertificationRecord` 写成 GOAL 对象，但 runtime 只有 passport、dossier、promotion gate 和 promotion QRO。新 mint `f6d7a3b8` 承接模型监控配置与再认证事件的 first-class record 层。
- **runtime/API**：新增 `ModelMonitoringProfile` 与 `ModelRecertificationRecord`；`PersistentModelGovernanceRegistry` 支持 append-only event 写入、replay 和查询。新增 `/api/research-os/model_governance/monitoring_profiles` 与 `/api/research-os/model_governance/recertification_records`，summary 返回 profile/record totals 和 refs。
- **坏门**：monitoring profile 必须引用匹配的 ModelPassport/ModelVersion，必须有 metrics/schedule/alert policy；recertification record 的 trigger 必须由 passport 声明，decision 只能是 `accepted` / `rejected` / `waived`。
- **测试**：`test_model_governance.py` **23 passed / 2 warnings**；training/model governance/Graph/entrypoint/Research OS/coverage/standards adjacent scoped **130 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 150）。
- **落档**：新增 done 卡 `f6d7a3b8`。边界：这是 monitoring/recertification registry/API/summary，不是 runtime serving、独立 sandbox artifact inspection process、remote artifact store、runtime auto-promotion、live model serving 或外部监控系统接线。

## 2026-06-27 · Model artifact sandbox inspection process（0e5c2a9d）

- **取前沿**：§15 Artifact 安全仍有 `sandboxed load / inspect` 缺口；旧 loader 只验证 validation dossier/hash，`.pkl/.joblib` 仍会在主进程最终反序列化。新 mint `0e5c2a9d` 承接本地子进程 inspection + loader 双绑定 + governance artifact inspection record。
- **runtime**：新增 `training.artifact_inspection_worker` 子进程 worker 和 wrapper；训练成功登记 model version 前写 `artifact_inspection.json`，validation dossier 写 `artifact_inspection_ref`，ModelPassport artifact 的 `sandbox_inspection_ref` 绑定同一 ref。pickle/joblib inspection 只做 metadata-only scan，不反序列化。
- **治理/API**：新增 `ModelArtifactInspectionRecord`；registry 可 append-only replay，要求 passport/version/artifact/hash/inspection_ref 匹配；新增 `/api/research-os/model_governance/artifact_inspections` 和 summary 字段。
- **坏门**：`.pkl/.joblib` loader 缺 `artifact_inspection.json`、path/hash/ref 不一致、非 subprocess isolation、inspection 反序列化过 pickle/joblib，都会拒绝加载。
- **测试**：`test_model_governance.py` **28 passed / 2 warnings**；`test_training_service.py` **15 passed**；training/model governance/Graph/entrypoint/Research OS/coverage/standards adjacent scoped **136 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 151）。
- **落档**：新增 done 卡 `0e5c2a9d`。边界：这是本地子进程 inspection 和 governance record，不是容器级/内核级 sandbox、remote artifact store、runtime auto-promotion、live model serving 或外部监控系统接线。

## 2026-06-27 · Governed model prediction serving seam（0f6a1d2e）

- **取前沿**：`0e5c2a9d` 后 artifact inspection 已可执行/记录；§15 runtime serving 仍缺受控调用边界。新 mint `0f6a1d2e` 先做 staging/production 本地 prediction seam，不做 live broker serving。
- **runtime/API**：新增 `/api/models/{model_id}/versions/{version}/predict`。入口要求 ModelVersion stage 是 `staging` 或 `production`，且有 recorded ModelPassport、accepted artifact inspection、matching MonitoringProfile；rows 限 200，feature cols 必须存在。
- **治理**：新增 `ModelServingInvocationRecord`，调用后写 request_hash、prediction_hash、row_count、feature refs、artifact_inspection_ref、monitoring_profile_ref；summary 不写 raw rows 或 raw predictions。
- **坏门**：dev stage 422；缺 passport / artifact inspection / monitoring profile 422；模型加载失败按 422 fail-closed。
- **测试**：`test_model_governance.py` **30 passed / 2 warnings**；training/model governance/Graph/entrypoint/Research OS/coverage/standards adjacent scoped **138 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 152）。
- **落档**：新增 done 卡 `0f6a1d2e`。边界：这是受控本地 prediction serving seam 和治理记录，不是 live broker serving、runtime auto-promotion、remote artifact store、外部监控系统回路或生产部署。

## 2026-06-27 · Model prediction emits typed signal contract（4c0d9e1f）

- **取前沿**：`0f6a1d2e` 已能受控本地预测，但模型输出仍只是 prediction 数组；§9 要求 forecast/signal contract 带时间、单位、方向、置信度、过期等语义。新 mint `4c0d9e1f` 承接 model prediction → typed SignalContract 接线。
- **runtime/API**：`/api/models/{model_id}/versions/{version}/predict` 新增可选 `signal_contract`。payload 必须给 OOF/purge/embargo、train/test lock、honest-N、forecast time、horizon、unit、direction semantics、confidence、expiry refs；通过 `validate_signal_protocol` 后才登记 `SIGNAL_CONTRACTS` 并返回 `signal_ref`。
- **boundary**：`SignalProtocolRecord` 新增 typed forecast/signal semantics 字段，并在模型信号 validator 中强制检查。
- **坏门**：缺 typed refs 时 422，且不写 serving invocation；模型本体仍不能直接进因子库。
- **测试**：`test_factor_strategy_boundary.py` **8 passed**；`test_model_governance.py` **31 passed / 2 warnings**；training/model governance/factor boundary/Graph/entrypoint/Research OS/coverage/standards adjacent scoped **147 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 153）。
- **落档**：新增 done 卡 `4c0d9e1f`。边界：这是模型预测到 SignalContract 的可选 typed 接线，不是 signal alpha 证明、自动组合、order emission、live trading 或持久化 SignalContractRegistry。

## 2026-06-27 · Persistent signal contract registry（c8e2f4a0）

- **取前沿**：`4c0d9e1f` 已把 model prediction 可选接到 SignalContract，但 registry 仍是进程内存。新 mint `c8e2f4a0` 承接 SignalContract JSONL 持久化。
- **runtime**：`SignalContractRegistry` 新增可选 `path`；有 path 时 startup replay，register 成功后 append JSONL。坏 schema/缺 payload fail-fast。
- **app 接线**：主 app `SIGNAL_CONTRACTS` 改为 `DATA_ROOT/audit/signal_contracts.jsonl` backed，覆盖 `/api/factors/signal_contracts` 和 `/api/models/{model_id}/versions/{version}/predict` 的登记路径。
- **坏门**：范畴门、model_ref 本体回指门、OOF/purge/embargo 泄露声明门不放松。
- **测试**：`test_factor_lab_endpoints.py` **16 passed / 2 warnings**；factor boundary + model governance scoped **39 passed / 2 warnings**；expanded adjacent scoped **163 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 154）。
- **落档**：新增 done 卡 `c8e2f4a0`。边界：这是 SignalContract 持久化，不是 signal alpha proof、自动组合、order emission、live trading 或外部 registry。

## 2026-06-27 · Signal performance validation registry（b7c6d8a9）

- **取前沿**：`c8e2f4a0` 后 SignalContract 已可重放，但策略/组合消费 signal 仍缺 performance validation 记录门。新 mint `b7c6d8a9` 承接 signal validation registry/API 和 StrategyBook accepted-validation gate。
- **runtime**：新增 `SignalPerformanceValidationRecord`、`PersistentSignalValidationRegistry` 和 `validate_signal_performance_validation`；validation 要求 signal_ref、dataset/window/methodology/metric/performance/leakage/evidence refs，verdict 限定 accepted/rejected/challenged。
- **app 接线**：主 app 新增 `SIGNAL_VALIDATIONS = DATA_ROOT/audit/signal_validations.jsonl`，新增 `/api/research-os/signal_validations` record/summary API；record 先确认 SignalContract 存在，summary 不返回 raw predictions/raw returns。
- **StrategyBook gate**：`validate_strategy_book(..., require_signal_validation=True)` 要求每个 `signal_ref` 绑定 accepted validation ref；缺失或 rejected validation 会拒。
- **测试**：`test_factor_strategy_boundary.py` **12 passed**；`test_factor_lab_endpoints.py` **18 passed / 2 warnings**；factor/model/portfolio adjacent scoped **66 passed / 2 warnings**；expanded Research OS/coverage/standards scoped **93 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 155）。
- **落档**：新增 done 卡 `b7c6d8a9`。边界：这是 signal performance validation record/gate，不是 signal alpha proof、自动组合、order emission、live trading 或外部 signal registry。

## 2026-06-27 · Portfolio promote signal validation gate（2c9f4e11）

- **取前沿**：`b7c6d8a9` 已有 SignalPerformanceValidationRecord，但 portfolio production promote 入口尚未消费该门。新 mint `2c9f4e11` 把组合 promote 的 signal_refs 接到 accepted validation refs。
- **runtime/API**：`/api/portfolios/{portfolio_id}/promote` 新增可选 `signal_refs` / `signal_validation_refs`；只要声明 signal，就必须有 matching accepted validation，且 signal_ref 必须存在于 SignalContract registry。
- **坏门**：缺 validation、unknown validation、validation 指向非本组合 signal set、rejected validation 都在 `gate_portfolio` 前 422，不消耗 honest-N。
- **测试**：`test_portfolio_promote_api.py` **8 passed / 2 warnings**；factor/model/portfolio adjacent scoped **69 passed / 2 warnings**；expanded Research OS/coverage/standards scoped **96 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 156）。
- **落档**：新增 done 卡 `2c9f4e11`。边界：这是 portfolio promote signal validation gate，不是 signal alpha proof、自动组合、order emission、live trading 或外部 signal registry。

## 2026-06-27 · Execution order intent registry API（5e1d0a77）

- **取前沿**：`2c9f4e11` 已把 portfolio promote 接到 signal validation gate；§9/§12 仍缺 portfolio/signal→order 的 typed intent contract。新 mint `5e1d0a77` 补 order intent audit object，不接真钱下单。
- **runtime**：新增 `ExecutionOrderIntentRecord`、`PersistentExecutionOrderIntentRegistry` 和 `validate_execution_order_intent`；testnet/live intent 要求 venue、permission、OrderGuard、idempotency、audit、kill-switch、SecretRef、responsibility refs，A股 live intent 拒。
- **app 接线**：主 app 新增 `EXECUTION_ORDER_INTENTS = DATA_ROOT/audit/execution_order_intents.jsonl`，新增 `/api/research-os/execution/order_intents` record/summary API。API 拒 raw `quantity`/`price`/`notional`/`secret`/`raw_order`，成功返回 `place_order_called=false`。
- **测试**：`test_execution_boundary_contract.py` **12 passed / 2 warnings**；execution/portfolio/factor/realtime safety adjacent scoped **59 passed / 2 warnings**；expanded Research OS/coverage/standards/security scoped **126 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 157）。
- **落档**：新增 done 卡 `5e1d0a77`。边界：这是 typed order intent record/API，不是 order emission、live trading、broker connector 或资金执行。

## 2026-06-27 · Guarded execution order submission seam（23f80fa8）

- **取前沿**：`5e1d0a77` / `8f2d4b0c` 已有 typed order intent + QRO，`0d9a6e42` 已有 runtime promotion，后续 venue event/reconciliation/monitor action 已可记录 refs；但 order intent 到受控提交边界仍缺一个明确 seam。新 mint `23f80fa8` 做 guarded order submission record/API/QRO，不接真实交易所。
- **runtime/API**：新增 `ExecutionOrderSubmissionRecord`、`PersistentExecutionOrderSubmissionRegistry`、`validate_execution_order_submission`；主 app 新增 `EXECUTION_ORDER_SUBMISSIONS`、disabled default submitter、`POST /api/research-os/execution/order_submissions` 与 summary。API 先拒 raw order/secret 字段，再确认 recorded order intent/runtime promotion，校验 permission、OrderGuard、idempotency、SecretRef、responsibility refs 与上游一致。
- **submitter seam**：默认 `EXECUTION_ORDER_SUBMITTER` disabled，`submit_enabled=true` 且未注入 submitter 会 fail-closed。测试注入 fake `submit_guarded_order` 只证明 seam 可被调用；API 自身仍返回 `api_place_order_called=false`，不新增裸 `place_order`。
- **审计边界**：成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command，output contract 只保存 refs、submitter_called、ack_ref、venue_order_ref 和 status，不保存 raw order、quantity、price、raw venue payload 或明文 secret。
- **测试**：execution boundary scoped **31 passed / 2 warnings**；realmoney audit scoped **18 passed / 2 warnings**；entrypoint gate scoped **2 passed**；monitor+execution+realmoney scoped **58 passed / 2 warnings**；expanded Research OS/monitor/model/signal/execution/security scoped **163 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 166）。
- **落档**：新增 done 卡 `23f80fa8`。边界：这是 guarded submitter seam 和 fake submitter 注入证明，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector 或资金执行。

## 2026-06-27 · Execution order materialization registry API（709450a4）

- **取前沿**：`23f80fa8` 已有 guarded submission seam，但 `submit_enabled=true` 仍缺前置 order materialization hash/ref 门。新 mint `709450a4` 把 order intent + runtime promotion 先落成 refs-only materialization，再允许 submitter seam。
- **runtime/API**：新增 `ExecutionOrderMaterializationRecord`、`PersistentExecutionOrderMaterializationRegistry`、`validate_execution_order_materialization`；主 app 新增 `EXECUTION_ORDER_MATERIALIZATIONS`、disabled default materializer、`POST /api/research-os/execution/order_materializations` 与 summary。API 拒 raw order/secret 字段，确认 recorded order intent/runtime promotion，校验 permission、OrderGuard、idempotency、SecretRef、responsibility refs 与上游一致。
- **materializer seam**：默认 `EXECUTION_ORDER_MATERIALIZER` disabled；只有显式注入 `materialize_order` 才会产出 `order_schema_ref`、`order_payload_hash`、sizing/price/risk/market refs。materializer result 若报告 `api_place_order_called` 或 `api_venue_call_called` 会被拒。
- **submission gate**：`ExecutionOrderSubmissionRecord` 增加 `order_materialization_ref`；`submit_enabled=true` 必须引用 recorded 且 `materialized` 的 materialization，否则 422，submitter 不调用；submitter result 若带 raw order/quantity/price 或自报 direct `place_order` 也会 422。
- **审计边界**：成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command，output contract 只保存 refs/hash/materializer_called/status，不保存 raw order、quantity、price、raw venue payload 或明文 secret。
- **测试**：execution boundary scoped **38 passed / 2 warnings**；realmoney audit scoped **18 passed / 2 warnings**；entrypoint gate scoped **2 passed**；expanded Research OS/monitor/model/signal/execution/security scoped **170 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 167）。
- **落档**：新增 done 卡 `709450a4`。边界：这是 refs-only materialization 和 fake materializer/submitter seam 证明，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native payload 生成或资金执行。

## 2026-06-27 · Execution venue capability readiness gate（98d6bf4a）

- **取前沿**：`709450a4` 已要求 `submit_enabled=true` 先引用 materialized order payload hash/ref；但 submitter seam 仍缺“当前 guarded venue/submitter/runtime 安全能力 ready”的 refs-only 证明。新 mint `98d6bf4a` 补 venue capability readiness gate。
- **runtime/API**：新增 `ExecutionVenueCapabilityRecord`、`PersistentExecutionVenueCapabilityRegistry`、`validate_execution_venue_capability`；主 app 新增 `EXECUTION_VENUE_CAPABILITIES`、`POST /api/research-os/execution/venue_capabilities` 与 summary。成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command。
- **submission gate**：`ExecutionOrderSubmissionRecord` 增加 `venue_capability_ref`；`submit_enabled=true` 必须同时引用 `materialized` 的 `order_materialization_ref` 和 `ready/can_submit_orders=true` 的 `venue_capability_ref`。capability 非 ready、缺 credential/IP allowlist/withdrawal disabled/HMAC/health/rate-limit/kill-switch/SecretRef/responsibility refs，或 venue/submitter/runtime/guard refs 与 order intent/runtime promotion/submission 不一致，都会 422 且不调用 submitter。
- **审计边界**：capability/API/QRO/summary 只存 refs/status，不存 raw order、quantity、price、raw venue payload 或明文 secret；新增路径不产生裸 `place_order` 或 venue API 调用。
- **测试**：execution boundary scoped **44 passed / 2 warnings**；realmoney audit scoped **18 passed / 2 warnings**；entrypoint gate scoped **2 passed**；expanded Research OS/monitor/model/signal/execution/security scoped **176 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 168）。
- **落档**：新增 done 卡 `98d6bf4a`。边界：这是 refs-only venue capability readiness 和 fake submitter seam 证明，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native payload 生成或资金执行。

## 2026-06-27 · Execution venue safety attestation backing registry（4393d50a）

- **取前沿**：`98d6bf4a` 已要求 ready capability 提供安全 refs，但这些 refs 仍可被裸字符串假填。新 mint `4393d50a` 把 credential/IP allowlist/withdrawal disabled/HMAC/health/rate-limit/sandbox refs 落成独立 append-only safety attestation。
- **runtime/API**：新增 `ExecutionVenueSafetyAttestationRecord`、`PersistentExecutionVenueSafetyAttestationRegistry`、`validate_execution_venue_safety_attestation`；主 app 新增 `EXECUTION_VENUE_SAFETY_ATTESTATIONS`、`POST /api/research-os/execution/venue_safety_attestations` 与 summary。成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command。
- **capability gate**：`ExecutionVenueCapabilityRecord` 增加 `venue_safety_attestation_ref`；`capability_status=ready` 必须引用 safety attestation ref。capability API 会解析 recorded attestation，并要求 `attestation_status=accepted` 且 venue/runtime/permission/OrderGuard/idempotency/credential/IP allowlist/withdrawal disabled/HMAC/health/rate-limit/kill-switch/SecretRef/responsibility refs 与 capability 匹配。
- **审计边界**：attestation/API/QRO/summary 只存 refs/status，不存 raw order、quantity、price、raw venue payload 或明文 secret；新增路径不产生裸 `place_order` 或 venue API 调用。
- **测试**：execution boundary scoped **49 passed / 2 warnings**；realmoney audit scoped **18 passed / 2 warnings**；entrypoint gate scoped **2 passed**；expanded Research OS/monitor/model/signal/execution/security scoped **181 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 169）。
- **落档**：新增 done 卡 `4393d50a`。边界：这是 refs-only safety attestation backing，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native payload 生成或资金执行。

## 2026-06-27 · Execution submit request envelope registry（9ca19020）

- **取前沿**：`4393d50a` 已让 ready venue capability 必须引用 accepted safety attestation；但 `ExecutionOrderSubmissionRecord.submit_request_ref` 仍只是裸字段。新 mint `9ca19020` 把 submit request 本身落成 refs-only append-only envelope。
- **runtime/API**：新增 `ExecutionSubmitRequestRecord`、`PersistentExecutionSubmitRequestRegistry`、`validate_execution_submit_request`；主 app 新增 `EXECUTION_SUBMIT_REQUESTS`、`POST /api/research-os/execution/submit_requests` 与 summary。成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command。
- **submission gate**：`submit_enabled=true` 的 order submission 现在必须引用 recorded 且 `ready` 的 submit request。submit request 绑定 order intent、runtime promotion、materialized order payload hash、ready venue capability、guarded venue、submitter、runtime、permission、OrderGuard、idempotency、audit、kill-switch、SecretRef、responsibility refs；submission API 会解析并校验这些 refs 与上游和 submission 一致，未通过则 422 且不调用 submitter。
- **审计边界**：submit request/API/QRO/summary 只存 refs/hash/status，不存 raw order、quantity、price、notional、raw venue payload 或明文 secret；新增路径不产生裸 `place_order` 或 venue API 调用。默认 submitter 仍 disabled。
- **测试**：execution boundary scoped **54 passed / 2 warnings**；realm-money + entrypoint scoped **20 passed / 2 warnings**；expanded Research OS/monitor/model/signal/execution/security scoped **186 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 170）。
- **落档**：新增 done 卡 `9ca19020`。边界：这是 refs-only submit request envelope，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native payload 生成或资金执行。

## 2026-06-27 · Execution venue connectivity check registry（ac0ad93d）

- **取前沿**：`4393d50a` 已让 ready venue capability 必须引用 accepted safety attestation，但 safety attestation 仍可直接人工填 credential/IP/HMAC/health/rate-limit refs。新 mint `ac0ad93d` 把这些 refs 先落成可重放的 connectivity check。
- **runtime/API**：新增 `ExecutionVenueConnectivityCheckRecord`、`PersistentExecutionVenueConnectivityCheckRegistry`、`validate_execution_venue_connectivity_check`；主 app 新增 `EXECUTION_VENUE_CONNECTIVITY_CHECKS`、`POST /api/research-os/execution/venue_connectivity_checks` 与 summary。成功路径写 `QROType.EXECUTION_POLICY` / `upsert_qro` command。
- **attestation gate**：`attestation_status=accepted` 的 venue safety attestation 现在必须引用 recorded 且 `accepted` 的 `venue_connectivity_check_ref`；API 会解析 connectivity check，并要求 venue/runtime/permission/OrderGuard/idempotency/credential/IP allowlist/withdrawal disabled/HMAC/health/rate-limit/sandbox/kill-switch/SecretRef/responsibility refs 与 attestation、order intent、runtime promotion 一致。
- **审计边界**：connectivity check/API/QRO/summary 只存 refs/hash/status，不存 raw order、quantity、price、notional、raw venue payload 或明文 secret；新增路径不产生裸 `place_order` 或 venue API 调用。
- **测试**：execution boundary scoped **59 passed / 2 warnings**；realm-money + entrypoint scoped **20 passed / 2 warnings**；expanded Research OS/monitor/model/signal/execution/security scoped **191 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 171）。
- **落档**：新增 done 卡 `ac0ad93d`。边界：这是 refs-only connectivity check registry，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native payload 生成或资金执行。

## 2026-06-27 · Execution venue connectivity checker seam（8d15d10c）

- **取前沿**：`ac0ad93d` 已把 connectivity check 落成 append-only record/API/QRO，但成功路径仍靠手动提交 record。新 mint `8d15d10c` 补注入式 checker seam。
- **runtime/API**：新增 disabled `EXECUTION_VENUE_CONNECTIVITY_CHECKER` adapter；`POST /api/research-os/execution/venue_connectivity_checks/run` 读取 recorded order intent + runtime promotion 后调用 checker。默认 disabled 会 422 且不写 connectivity JSONL/QRO。
- **checker gate**：fake checker 成功路径把 checker result 归一成 `ExecutionVenueConnectivityCheckRecord`，写 connectivity registry 和 ExecutionPolicy QRO；checker result 继续拒 raw order、raw venue payload、quantity、price、notional、secret，也拒自报 direct `place_order` 或 venue API call。
- **审计边界**：run endpoint 响应 `checker_called=true` 只证明注入 seam 被调用，不证明真实 Binance testnet key 连通；新增路径不产生裸 `place_order` 或 venue API 调用。
- **测试**：execution boundary scoped **63 passed / 2 warnings**；realm-money + entrypoint scoped **20 passed / 2 warnings**；expanded Research OS/monitor/model/signal/execution/security scoped **195 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 172）。
- **落档**：新增 done 卡 `8d15d10c`。边界：这是 refs-only checker seam，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native payload 生成或资金执行。

## 2026-06-27 · Execution submit request builder seam（7ace6793）

- **取前沿**：`9ca19020` 已把 submit request envelope 落成 append-only registry/API/QRO，但成功路径仍靠手工提交 refs。新 mint `7ace6793` 补 submit request builder seam。
- **runtime/API**：新增 disabled `EXECUTION_SUBMIT_REQUEST_BUILDER` adapter；`POST /api/research-os/execution/submit_requests/run` 读取 recorded order materialization + ready venue capability，并解析对应 order intent/runtime promotion 后调用 builder。默认 disabled 会 422 且不写 submit request JSONL/QRO。
- **builder gate**：fake builder 成功路径把 builder result 归一成 `ExecutionSubmitRequestRecord`，写 submit request registry 和 ExecutionPolicy QRO；builder result 继续拒 raw order、raw venue payload、quantity、price、notional、secret，也拒自报 direct `place_order` 或 venue API call。
- **审计边界**：run endpoint 响应 `builder_called=true` 只证明注入 seam 被调用，不证明真实 venue-native payload builder 或真实 Binance testnet key 连通；新增路径不产生裸 `place_order` 或 venue API 调用。
- **测试**：execution boundary scoped **67 passed / 2 warnings**；realm-money + entrypoint scoped **20 passed / 2 warnings**；expanded Research OS/monitor/model/signal/execution/security scoped **199 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 173）。
- **落档**：新增 done 卡 `7ace6793`。边界：这是 refs-only submit request builder seam，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector、venue-native raw payload 生成或资金执行。

## 2026-06-27 · Execution guarded submission runner seam（951b443b）

- **取前沿**：`7ace6793` 已让 submit request 可由 builder seam 生成，但 submission 仍需手工 POST 完整 refs。新 mint `951b443b` 补 submit_request-only runner。
- **runtime/API**：新增 `POST /api/research-os/execution/order_submissions/run`；只接 `submit_request_ref`，解析 recorded submit request、order intent、runtime promotion、materialization、venue capability 后构造 `ExecutionOrderSubmissionRecord`。默认 `EXECUTION_ORDER_SUBMITTER` disabled 会 422 且不写 submission JSONL/QRO。
- **submitter gate**：fake submitter 成功路径写 submission registry 和 ExecutionPolicy QRO；runner 继续拒 raw order、raw venue payload、quantity、price、notional、secret，也拒自报 direct `place_order` 或 direct venue API call。
- **审计边界**：runner endpoint 响应 `submitter_called=true` 只证明注入 seam 被调用，不证明真实 Binance testnet key 连通、真实 venue API 连通或资金执行。
- **测试**：execution boundary scoped **71 passed / 2 warnings**；realm-money + entrypoint scoped **20 passed / 2 warnings**；expanded Research OS/monitor/model/signal/execution/security scoped **203 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 174）。
- **落档**：新增 done 卡 `951b443b`。边界：这是 refs-only guarded submission runner seam，不是真实 Binance testnet key 连通、真实 venue API 连通、live trading、broker connector 或资金执行。

## 2026-06-27 · Execution venue event ingester seam（6613a3fa）

- **取前沿**：`951b443b` 已能从 ready submit request 进入 guarded submission runner，但 venue ack/fill event 仍需手工 POST。新 mint `6613a3fa` 补 submission→venue event ingester seam。
- **runtime/API**：新增 disabled `EXECUTION_VENUE_EVENT_INGESTER` adapter；`POST /api/research-os/execution/venue_events/run` 只接 `submission_ref`，解析 recorded submission、order intent、runtime promotion 后调用 ingester。默认 disabled 会 422 且不写 venue event JSONL/QRO。
- **ingester gate**：fake ingester 成功路径把 ingester result 归一成 `ExecutionVenueEventRecord`，写 venue event registry 和 ExecutionPolicy QRO；ingester result 继续拒 raw order、raw venue payload、quantity、price、notional、secret，也拒自报 direct `place_order` 或 direct venue API call；fill event 缺 fill/quantity/price refs 会被 validator 拒绝。
- **审计边界**：run endpoint 响应 `ingester_called=true` 只证明注入 seam 被调用，不证明真实 Binance testnet ack/fill ingest、真实 venue API 连通或资金执行。
- **测试**：execution boundary scoped **76 passed / 2 warnings**；realm-money + entrypoint scoped **20 passed / 2 warnings**；expanded Research OS/monitor/model/signal/execution/security scoped **208 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 175）。
- **落档**：新增 done 卡 `6613a3fa`。边界：这是 refs-only venue event ingester seam，不是真实 Binance testnet ack/fill ingest、真实 venue API 连通、live trading、broker connector 或资金执行。

## 2026-06-27 · Market data asset registry and QRO write-through（24baede1）

- **取前沿**：§11 已有 `market_data_contract.py` validator，能挡无 PIT confirmatory、跨币种资本账缺失、期权 terms 缺失、live capability 缺 permission、A股 live 和数据变换数学绑定缺失；但 DatasetSemantics、InstrumentSpec、MarketCapabilityMatrix 还没有作为 Research OS 资产写入 append-only registry/API/QRO。
- **runtime/API**：新增 `PersistentMarketDataRegistry`、record parsers 和 `to_dict`；主 app 新增 `MARKET_DATA_REGISTRY`、`POST /api/research-os/market_data/datasets`、`POST /api/research-os/market_data/instruments`、`POST /api/research-os/market_data/capability_matrices`、`GET /api/research-os/market_data/summary`。
- **QRO 接线**：DatasetSemantics 成功写 `QROType.DATASET`；InstrumentSpec 映射到当前已有 `QROType.DATA_SOURCE_ASSET`，QRO known_limits 明确当前没有专门 InstrumentSpec QRO type；MarketCapabilityMatrix 成功写 `QROType.MARKET_CAPABILITY_MATRIX`。output contract 均标明 `raw_data_stored=false`、`connector_called=false`，capability 额外标明 `venue_called=false`。
- **对抗门**：confirmatory dataset 缺 known_at/effective_at/PIT、option InstrumentSpec 缺 expiry/strike/multiplier/settlement、live MarketCapabilityMatrix 缺 live permission、malformed history、raw rows/payload、plaintext secret 均 fail-closed；坏输入不写 registry，不写 Graph。
- **测试**：`tests/test_market_data_contract.py` **12 passed / 2 warnings**；market data/onboarding/Graph/entrypoint adjacent scoped **63 passed / 2 warnings**；expanded Research OS/entrypoint/execution/model/RDP/compiler scoped **234 passed / 2 warnings**；`compileall app/backend/app` **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️**（DAG 176）。
- **落档**：新增 done 卡 `24baede1`。边界：这是 §11 refs-only metadata registry/API/QRO，不是真实 data connector、行情下载、全资产自动同步、strategy builder 接线、execution path 接线、live provider permission proof 或真实 venue permission check。

## 2026-06-27 · Market data use gate registry and QRO write-through（e2907891）

- **取前沿**：`24baede1` 已把 DatasetSemantics、InstrumentSpec、MarketCapabilityMatrix 落成 registry/API/QRO，但下游仍可把裸 refs 拼成 MarketDataUseRequest。新卡补 refs-only use gate，要求使用方引用已登记 §11 资产后再进入 MarketDataUse validator。
- **runtime/API**：新增 `MarketDataUseValidationRecord`、parser、validator 和 `PersistentMarketDataRegistry.record_use_validation` event；主 app 新增 `POST /api/research-os/market_data/use_requests`，成功通过后写 use validation registry 和 Research Graph QRO；summary 增加 `use_validations` / `use_validation_total`。
- **QRO 接线**：use validation QRO 使用当前已有 `QROType.MARKET_CAPABILITY_MATRIX` 承载 capability-bound use gate；output contract 只存 refs 和 gate 状态，标明 `raw_data_stored=false`、`connector_called=false`、`strategy_builder_called=false`、`venue_called=false`。
- **对抗门**：use request 引用未登记 dataset/instrument/capability、cross-currency 缺 base_currency/fx_conversion_ref、live use 引用 live=false matrix、raw rows/payload/secret 均 422；坏输入不写 use validation，不写 Graph command。
- **测试**：`tests/test_market_data_contract.py` **17 passed / 2 warnings**；expanded Research OS/entrypoint/execution/model/RDP/compiler scoped **239 passed / 2 warnings**；`compileall app/backend/app` **PASS**。
- **落档**：新增 done 卡 `e2907891`。边界：这是 refs-only MarketDataUse gate，不是 strategy builder 接线、execution order intent 强制引用、真实 connector、行情下载、live provider permission proof、真实 venue permission check 或全资产自动同步。

## 2026-06-27 · Execution order intent requires MarketDataUse validation（0f977f03）

- **取前沿**：`e2907891` 已把 MarketDataUse gate 落成 registry/API/QRO，但 `ExecutionOrderIntent` 仍可绕过它进入 paper/testnet/live 意图记录。新卡补 §11→§12 的 refs-only downlink。
- **runtime/API**：`ExecutionOrderIntentRecord` 新增 `market_data_use_validation_ref`；validator 对 paper/testnet/live 强制要求该 ref；`POST /api/research-os/execution/order_intents` 写入前调用 `MARKET_DATA_REGISTRY.use_validation(ref)` 并要求 `accepted=true`。
- **QRO 接线**：ExecutionPolicy QRO 的 evidence refs、lineage、implementation hash、input contract、output contract 和 summary 均包含 `market_data_use_validation_ref`；仍不保存 raw data rows、raw order、quantity、price、notional 或 secret。
- **对抗门**：缺 `market_data_use_validation_ref`、unknown ref 或未 accepted ref 均 422；坏输入不写 order intent JSONL，不写 Research Graph command。
- **测试**：`tests/test_execution_boundary_contract.py` **78 passed / 2 warnings**；market-data/execution/Graph/entrypoint/model/compiler/RDP adjacent scoped **228 passed / 2 warnings**；`compileall app/backend/app` **PASS**。
- **落档**：新增 done 卡 `0f977f03`。边界：这是 execution order intent 对 accepted MarketDataUse validation 的 refs-only 强制引用，不是 strategy builder 接线、StrategyBook/portfolio promote 全入口强制引用、真实 connector、行情下载、live provider permission proof、真实 venue permission check 或全资产自动同步。

## 2026-06-27 · StrategyBook requires MarketDataUse validation（2cee6b45）

- **取前沿**：`e2907891` 已把 MarketDataUse gate 落成 registry/API/QRO，`0f977f03` 已把它强制接到 ExecutionOrderIntent；但 StrategyBook 仍可只引用 factor/signal/leg，不引用数据使用验证。新卡补 §11→§9 的 runtime validator gate。
- **runtime**：`StrategyBookContract` 新增 `market_data_use_validation_refs`；`validate_strategy_book` 新增 `market_data_use_validations` 与 `require_market_data_use_validation`。开启 hard gate 后，每个 leg instrument 必须被 accepted `MarketDataUseValidationRecord.instrument_refs` 覆盖。
- **对抗门**：缺 ref、unknown ref、未 accepted ref、validation 自身 violation、instrument 不覆盖均 fail-closed；错误码覆盖 `missing_market_data_use_validation_record`、`market_data_use_not_accepted`、`market_data_use_has_violations`、`missing_market_data_use_validation`。
- **测试**：`tests/test_factor_strategy_boundary.py` **16 passed**；market-data/factor-lab/portfolio/model adjacent scoped **90 passed / 2 warnings**。
- **落档**：新增 done 卡 `2cee6b45`。边界：这是 StrategyBook runtime validator 的 MarketDataUse hard gate，不是 portfolio promote API 接线、IDE strategy save/run 接线、strategy builder 全入口接线、真实 connector、行情下载或 live provider permission proof。

## 2026-06-27 · Portfolio promote requires MarketDataUse validation（0a0dc8c5）

- **取前沿**：`ba59fb7b` 已把 portfolio production promote 接成 `record=True` 一本账，`2c9f4e11` 已接 signal validation gate，`e2907891` 已有 MarketDataUse gate；但 promote 仍只校验 `dataset_version` 字符串和收益序列结构。新卡把 accepted MarketDataUse validation 接到 promote 前置门。
- **runtime/API**：`/api/portfolios/{portfolio_id}/promote` 新增 `market_data_use_validation_refs` hard gate；每个 portfolio symbol 必须被 accepted `MarketDataUseValidationRecord.instrument_refs` 覆盖。gate 在 `gate_portfolio` 与 honest-N 消耗前执行。
- **对抗门**：缺 ref、unknown ref、未 accepted ref、validation 带 violation、symbol 不覆盖均 422；坏输入不增加 honest-N，不写 portfolio gate record。
- **测试**：`tests/test_portfolio_promote_api.py` **12 passed / 2 warnings**；market-data/factor/portfolio/model/Graph/entrypoint adjacent scoped **124 passed / 2 warnings**。
- **落档**：新增 done 卡 `0a0dc8c5`。边界：这是 portfolio production promote 的 refs-only MarketDataUse hard gate，不是 strategy builder 全入口接线、IDE strategy save/run 接线、真实 connector、行情下载、live provider permission proof、真实 venue permission check 或 order emission。

## 2026-06-27 · IDE strategy save requires MarketDataUse validation（06b1f745）

- **取前沿**：`e2907891` 已把 MarketDataUse gate 落成 registry/API/QRO，且 `0f977f03` / `2cee6b45` / `0a0dc8c5` 已把它分别接到 order intent、StrategyBook validator、portfolio promote；但 `POST /api/ide/strategies` 仍可保存策略草稿并写 StrategyBook QRO，却不引用 accepted MarketDataUse validation。新卡闭合 IDE save 入口。
- **runtime/API**：`ide_save_strategy` 在 `IDEService.save_strategy` 前解析 `market_data_use_validation_refs`，要求 list、非空、每个 ref resolve 到 accepted/no-violation `MarketDataUseValidationRecord`。缺 ref、unknown ref、未 accepted ref、带 violation ref 均 422，且不保存 strategy、不写 Research Graph command。
- **QRO/审计**：`_record_ide_strategy_qro` 的 input/output contract、lineage 和 implementation hash 绑定 `market_data_use_validation_refs`；Graph audit allowlist 暴露 refs 字段，但仍不复制 raw strategy code 或 description。
- **前端**：IDE 页面新增 MarketDataUse refs 输入，保存 payload 带 refs；`run()` 自动保存失败时停止，不再继续调用 run endpoint；新策略首次 run 使用 save 返回的策略名，避免 React state 尚未同步导致 run 打旧 name。
- **测试**：`tests/test_strategy_console_s2.py` **32 passed / 2 warnings**；market-data/IDE/portfolio/Graph/Agent adjacent scoped **97 passed / 2 warnings**；`compileall app/backend/app` **PASS**；frontend build **tsc + vite PASS**（保留既有 chunk size warning）。
- **落档**：新增 done 卡 `06b1f745`。边界：这是 IDE strategy save 的 refs-only MarketDataUse hard gate；IDE run gate 后续由 `84b1d0c6` 补齐；本卡不是 strategy builder 全入口接线、真实 connector、行情下载、live provider permission proof、真实 venue permission check 或 order emission。

## 2026-06-27 · IDE strategy run requires MarketDataUse validation（84b1d0c6）

- **取前沿**：`06b1f745` 已让 IDE save 在保存策略和写 StrategyBook QRO 前强制 accepted MarketDataUse refs，但 run 入口仍可能绕过数据使用证明。新卡闭合 `POST /api/ide/strategies/{name}/run` 的 sandbox 前门。
- **runtime/API**：`IDEService` 持久化策略级 `market_data_use_validation_refs`，旧 SQLite 库自动补列，fork 继承 parent refs；run payload 可显式传 refs，未传时继承 saved strategy refs。
- **run gate**：`ide_run_strategy` 在 `IDEService.run_strategy` 前校验 refs，要求 list、非空、每个 ref resolve 到 accepted/no-violation `MarketDataUseValidationRecord`。缺 ref、unknown ref、未 accepted ref 或 violation ref 均 422，且不生成 `i_runs`、不写 Research Graph command。
- **QRO/审计**：BacktestRun QRO input/output contract、lineage、implementation hash 和 audit summary 绑定 `market_data_use_validation_refs`；Graph audit summary 仍不暴露 stdout、stderr、result payload 或 raw source。
- **前端**：IDE `run()` payload 带 MarketDataUse refs。
- **测试**：`tests/test_strategy_console_s2.py` **36 passed / 2 warnings**；`tests/test_ide.py` **23 passed**；market-data/IDE/portfolio/Graph/Agent adjacent scoped **124 passed / 2 warnings**；`compileall app/backend/app` **PASS**；frontend build **tsc + vite PASS**（保留既有 chunk size warning）。
- **落档**：新增 done 卡 `84b1d0c6`。边界：这是 IDE strategy run 的 refs-only MarketDataUse hard gate，不是 strategy builder 全入口接线、真实 connector、行情下载、live provider permission proof、真实 venue permission check、order emission 或 sandbox code 对真实数据行消费的强证明。

## 2026-06-27 · Agent strategy synthesis requires MarketDataUse validation（4b6f55dc）

- **取前沿**：IDE save/run 已接 MarketDataUse gate，但 Agent `backtest.run` 的 `_synth_and_promote` 仍可从 StrategyGoal/组装意图合成策略、读样本、跑 sandbox 并 promote 成 run。新卡把 §11 数据使用门接到这个 strategy synthesis 前门。
- **runtime/tool**：`_synth_and_promote` 开头解析 `market_data_use_validation_refs`，要求 list/string、非空、每个 ref resolve 到 accepted/no-violation `MarketDataUseValidationRecord`；`_agent_runtime` 注册 business tools 时注入 `MARKET_DATA_REGISTRY`；`backtest.run` tool schema 声明 refs 必填。
- **no-write gate**：缺 ref、unknown ref、未 accepted ref 或 violation ref 均返回 error/no_write，且早于 LLM/code synthesis、sample read、sandbox run 和 promote；缺 refs 测试证明 LLM `complete()` 未被调用，坏 refs 不创建 `artifacts/experiments`。
- **兼容边界**：正向 DS-1/DS-2/delivery 路径补 accepted refs；成功响应返回 `market_data_use_validation_refs`；旧 `run.json["assembly_inputs"]` shape 不变，不把 MarketDataUse refs 塞进 assembly metadata。
- **测试**：DS-1/DS-2/delivery focused **26 passed / 2 warnings**；Agent/tool focused **38 passed / 2 warnings**；Agent/DS/Chat adjacent **97 passed / 2 warnings**；market-data/IDE/portfolio/execution adjacent **143 passed / 2 warnings**；`compileall app/backend/app` **PASS**。
- **落档**：新增 done 卡 `4b6f55dc`。边界：这是 Agent `backtest.run` strategy synthesis 的 refs-only MarketDataUse hard gate，不是真实 connector、行情下载、live provider permission proof、真实 venue permission check、order emission、完整 strategy code generator、自动组合注入或 sandbox code 对真实数据行消费的强证明。

## 2026-06-27 · IDE AI complete requires MarketDataUse validation（b7c35c82）

- **取前沿**：IDE save/run 和 Agent `backtest.run` strategy synthesis 已接 MarketDataUse gate，但 IDE AI complete 仍可在保存/运行前调用 LLM 生成、解释或修复策略代码。新卡闭合 IDE strategy codegen 的 LLM 前门。
- **runtime/API**：`ide_ai_complete` 在 prompt 非空后、LLM 调用前复用 IDE MarketDataUse refs validator；缺 ref、unknown ref、未 accepted ref 或 violation ref 均 422，不调用 LLM。
- **QRO/审计**：LLMCallRecord QRO input/output contract、lineage、implementation hash、assumptions/known_limits 记录 `market_data_use_validation_refs`；仍不复制 prompt、context code 或 generated output。
- **前端**：IDE AI complete payload 带同一组 MarketDataUse refs。
- **对抗门**：缺 refs 与 violation refs 测试证明 fake LLM 不被调用，Research Graph command 数不增加；成功路径返回 refs，QRO 记录 refs且不泄露 prompt/context/output。
- **测试**：`tests/test_strategy_console_s2.py` **38 passed / 2 warnings**；IDE/market-data/portfolio/execution adjacent **168 passed / 2 warnings**；Agent/DS/Chat adjacent **97 passed / 2 warnings**；`compileall app/backend/app` **PASS**；frontend build **tsc + vite PASS**（保留既有 chunk size warning）。
- **落档**：新增 done 卡 `b7c35c82`。边界：这是 IDE AI complete strategy codegen 的 refs-only MarketDataUse hard gate，不是真实 connector、行情下载、live provider permission proof、真实 venue permission check、order emission、完整 strategy code generator 验证、自动组合注入或 sandbox code 对真实数据行消费的强证明。

## 2026-06-27 · IDE promote requires MarketDataUse validation（d6c4a2b8）

- **取前沿**：IDE save/run/AI complete 和 Agent strategy synthesis 已接 MarketDataUse gate，但 IDE promote 仍可只凭 ok sandbox run 和 result shape 写正式 Run。新 mint `d6c4a2b8` 补 sandbox run -> formal Run 的 MarketDataUse 前门。
- **runtime/API**：`i_runs` 新增 `market_data_use_validation_refs`，旧 SQLite 库自动补列；`IDEService.run_strategy()` 默认继承 saved strategy refs，也可显式传 refs。`POST /api/ide/runs/{run_id}/promote` 在读取 result、调用 `promote_ide_run()`、写 QRO/Graph 前校验 refs。
- **promote gate**：缺 refs、unknown ref、未 accepted ref 或 violation ref 均 422；对抗测试证明不会创建 promoted run 目录，也不会写 Research Graph command。
- **QRO/前端**：promoted BacktestRun QRO input/output contract、lineage、implementation hash 和 assumptions 记录 refs；IDE 页面 promote payload 优先发送 active run refs，兼容旧 run 时使用当前输入框 refs。
- **测试**：IDE scoped **66 passed / 2 warnings**；market-data/portfolio/execution/delivery/DS adjacent **133 passed / 2 warnings**；`compileall app/backend/app` **PASS**；frontend build **tsc + vite PASS**（保留既有 chunk size warning）。
- **落档**：新增 done 卡 `d6c4a2b8`。边界：这是 IDE promote 的 refs-only MarketDataUse hard gate，不是真实 connector、行情下载、live provider permission proof、真实 venue permission check、order emission、完整 strategy code generator 验证、自动组合注入或 sandbox code 对真实数据行消费的强证明。

## 2026-06-27 · Settings-managed Data Connector checks（aa10b25c）

- **取前沿**：`73e78014` 已有 Settings/LLM Provider metadata registry/API，但 DataSourceAsset、IngestionSkill 和 data connector connection test 还没有持久化 Settings 入口。新卡补 §4 Data Onboarding 的第一条 refs-only connector check seam。
- **runtime/API**：`PersistentOnboardingRegistry` 新增 DataSourceAsset、IngestionSkill、DataConnectorConnectionCheck 三类 append-only event 和 replay；主 app 新增 `/api/research-os/settings/data_sources`、`/ingestion_skills`、`/data_connector_checks`，summary 返回对应 totals 和 sanitized records。
- **connector seam**：新增 `DATA_CONNECTOR_CONNECTION_CHECKER`，默认 disabled；API 会记录 `ok=false/status=disabled/health_status=disabled` 的诚实失败，不声称真实 provider 连通。调用 checker 前先验证 skill/source/SecretRef 已登记且 SecretRef 未 revoked。
- **对抗门**：plaintext Settings payload、checker result 含明文 secret、revoked SecretRef、source/secret refs 不匹配均 422；坏输入不写 ConnectorCheck，revoked SecretRef 路径证明 checker 不被调用。
- **前端**：Settings 安全页新增 Data Connectors panel，读取 `/api/research-os/settings/summary`，展示 source/skill/check refs，并按 `skill_id` 调用 `/api/research-os/settings/data_connector_checks`；页面不显示 raw key。
- **测试**：`tests/test_onboarding_gateway.py` **20 passed / 2 warnings**；LLM/Settings scoped **36 passed / 2 warnings**；onboarding/LLM/market-data/spine adjacent **61 passed / 2 warnings**；targeted compileall **PASS**；frontend scoped **2 files / 10 tests passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `aa10b25c`。边界：这是 Settings-managed connector metadata + refs-only connection-check seam，不是真实 connector adapter、真实 secret value storage、OAuth/device-code/account auth、行情下载、schema scanner、DatasetVersion 写入、全资产自动同步、live provider permission proof 或 sandbox code 对真实数据行消费的强证明。

## 2026-06-27 · IngestionSkill updates require DatasetVersion binding（addd2e4e）

- **取前沿**：`aa10b25c` 已让 Settings 登记 DataSourceAsset/IngestionSkill/ConnectorCheck，但数据更新仍没有 append-only update registry/API，也未把更新记录绑定到真实 DatasetVersion/checksum/time axes。新卡补 §3/§4/§11 的 DataUpdate audit seam。
- **runtime/API**：`IngestionSkillUpdateRecord` 新增 source_ref、secret_ref、known_at_ref、effective_at_ref、freshness/schema/row_count/evidence refs；新增 `PersistentAssetLifecycleRegistry` 和 `POST /api/research-os/settings/ingestion_skill_updates`。
- **update gate**：endpoint 写入前确认 Settings IngestionSkill 存在、skill version/source 匹配、SecretRef 属于 skill 且未 revoked、`dataset_version_ref` 对应 `DatasetRegistry` 真实 version、checksum 匹配、row_count 匹配。
- **对抗门**：缺 source/SecretRef/DatasetVersion/checksum/lineage/quality/known_at/effective_at、unknown DatasetVersion、checksum mismatch 均 fail-closed；坏输入不写 lifecycle update。
- **前端**：Settings 安全页 Data Connectors panel 增加 update count、latest DatasetVersion、quality verdict、known_at/effective_at refs 展示。
- **测试**：`tests/test_asset_lifecycle.py` **8 passed**；asset/onboarding scoped **31 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine adjacent **72 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `addd2e4e`。边界：这是已有 DatasetVersion 的 refs/checksum 绑定和 ingestion update audit，不是真实 connector adapter、schema scanner、字段映射、PIT/bitemporal 自动生成、DatasetVersion 文件生成、全资产自动同步、live provider permission proof 或 raw data consumption proof。

## 2026-06-27 · Settings IngestionSkill runner produces DatasetVersion files（e6f2b8a4）

- **取前沿**：`aa10b25c` 已有 Settings connector check，`addd2e4e` 已能把 update 绑定已有 DatasetVersion，但还没有受控 producer 把 connector 结果写成 DatasetVersion 文件。新卡补 §4→§11→§3 的第一条 runner seam。
- **runtime/API**：新增 `DATA_CONNECTOR_INGESTION_RUNNER`，默认 disabled；新增 `POST /api/research-os/settings/ingestion_skill_runs`。endpoint 要求 active IngestionSkill、active SecretRef 和 ok DataConnectorConnectionCheck，runner 返回 `FetchResult` 后重新校验 row_count/checksum/secret，原子写本地 parquet，登记 `DatasetRegistry`，并自动写 `IngestionSkillUpdateRecord`。
- **dataset file**：成功路径写 `DATA_ROOT/datasets/ingestion/<dataset_id>/<sha12>.parquet`，DatasetVersion metadata 带 source、skill、connector_check、schema_probe、permission、PIT refs；响应只返回 refs/hash/path/row_count/update_ref，不返回 raw rows。
- **对抗门**：缺 ok connector check 不调用 runner；默认 disabled runner 不写；checksum mismatch 不写；frame 含明文 secret 不写。
- **前端**：Settings 安全页 Data Connectors panel 新增 `Run update`，使用最新 ok `connector_check_ref` 调 `/api/research-os/settings/ingestion_skill_runs`，展示 DatasetVersion ref、row_count 和 update_ref。
- **测试**：`tests/test_onboarding_gateway.py` **28 passed / 2 warnings**；asset/onboarding scoped **36 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **87 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `e6f2b8a4`。边界：这是注入式 runner seam + 本地 DatasetVersion 文件生成 + update audit，不是内置真实 connector adapter、真实行情下载、字段映射 wizard、PIT/bitemporal 自动推导、全资产自动同步、live provider permission proof、生产 scheduler 或外部 provider 实网连通证明。

## 2026-06-27 · Settings ingestion schema probe registry and drift gate（2d7a91c3）

- **取前沿**：`e6f2b8a4` 已让 runner 生成 DatasetVersion 文件，但 schema_probe 仍是裸 ref，没有可 replay schema scanner 记录和 drift gate。新卡补 §4/§11 schema scanner。
- **runtime/registry**：新增 `DataConnectorSchemaProbeRecord`、`validate_data_connector_schema_probe()` 和 `data_connector_schema_probe_recorded` event；`PersistentOnboardingRegistry` 可 record/replay/access/list schema probes。
- **run gate**：ingestion run 计算 columns/dtypes 的 `schema_signature_hash`，绑定 skill/source/ok connector check/DatasetVersion。首次 schema 为 `none`，相同 schema 为 `unchanged`；schema 变化时若缺 `schema_drift_event_ref` 或 `downstream_impact_refs`，在写 parquet 前 422，不写 DatasetVersion/schema probe/update。
- **前端**：Settings 安全页 Data Connectors panel 显示 schema probe count、latest probe ref、drift status、columns count。
- **测试**：`tests/test_onboarding_gateway.py` **30 passed / 2 warnings**；asset/onboarding scoped **38 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **89 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `2d7a91c3`。边界：这是可 replay schema scanner record + drift gate，不是自动字段映射、语义类型推断、PIT/bitemporal 自动生成、真实 connector adapter、全资产自动同步、生产 scheduler 或外部 provider 实网连通证明。

## 2026-06-27 · Settings data connector field mapping registry and UI（b7d0708b）

- **取前沿**：`2d7a91c3` 已让 schema probe/drift gate 可 replay，但 schema 后的字段映射仍是裸 ref/旧 field catalog 辅助能力。新卡补 GOAL §2/§4/§11 的 Settings-managed field mapping record。
- **runtime/registry**：新增 `DataConnectorFieldMappingRecord`、`data_connector_field_mapping_hash()`、`validate_data_connector_field_mapping()` 和 `data_connector_field_mapping_recorded` event；`PersistentOnboardingRegistry` 可 JSONL replay/access/list field mappings。
- **API/UI**：新增 `POST /api/research-os/settings/data_connector_field_mappings`，绑定 recorded IngestionSkill/DataSourceAsset/SchemaProbe，缺 schema_probe_ref 时取该 skill 最新 probe；summary 返回 field mapping total/list。Settings 安全页 Data Connectors panel 显示 latest mapping，并可基于 schema probe 常见列名记录一版 mapping。
- **对抗门**：未知 source column、未覆盖 observed columns、缺/未知/未映射 event_time、secret-like 字段、schema probe/scope mismatch、mapping_hash mismatch 均 fail-closed；API 坏输入不写 partial field mapping。
- **测试**：`tests/test_onboarding_gateway.py` **32 passed / 2 warnings**；asset/onboarding scoped **40 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **91 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `b7d0708b`。边界：这是可 replay Settings field mapping record/API/UI，不是完整字段映射 wizard、语义类型推断、PIT/bitemporal 自动生成、真实 connector adapter、全资产自动同步、生产 scheduler、live provider permission proof 或 confirmatory validation data-semantics proof。

## 2026-06-27 · Settings PIT bitemporal rule registry and UI（22682f6a）

- **取前沿**：`b7d0708b` 已让 schema probe 后的字段映射可 replay，但 `pit_bitemporal_rules_ref` 仍只是 IngestionSkill 上的裸字符串。新卡补 GOAL §4/§11 的 Settings-managed PIT/bitemporal rule record。
- **runtime/registry**：新增 `DataConnectorPITBitemporalRuleRecord`、`data_connector_pit_bitemporal_rule_hash()`、`validate_data_connector_pit_bitemporal_rule()` 和 `data_connector_pit_bitemporal_rule_recorded` event；`PersistentOnboardingRegistry` 可 JSONL replay/access/list PIT/bitemporal rules。
- **API/UI**：新增 `POST /api/research-os/settings/pit_bitemporal_rules`，绑定 recorded IngestionSkill/DataSourceAsset/FieldMapping/SchemaProbe；缺 field_mapping_ref 时取该 skill 最新 mapping。summary 返回 PIT rule total/list。Settings 安全页 Data Connectors panel 显示 latest rule，并可从 field mapping 生成一版 PIT-safe rule payload。
- **对抗门**：rule_ref 不匹配 skill、event_time 不在 schema 或不等于 field mapping axis、`current_snapshot/full_history/latest` 等非 PIT-safe as-of policy、缺 field mapping/schema probe evidence、rule_hash mismatch 均 fail-closed；API 坏输入不写 partial PIT rule。
- **测试**：`tests/test_onboarding_gateway.py` **33 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **92 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `22682f6a`。边界：这是可 replay Settings PIT/bitemporal rule record/API/UI，不是完整 PIT 推导 wizard、语义类型推断、真实 connector adapter、全资产自动同步、生产 scheduler、live provider permission proof 或 confirmatory validation proof；当时不含 DatasetSemantics 生成，已由 `6886f4e4` 补齐第一条 Settings 自动登记路径。

## 2026-06-27 · Settings DatasetSemantics generation from ingestion update and PIT rule（6886f4e4）

- **取前沿**：`22682f6a` 已把 PIT/bitemporal rule 做成可 replay record，但 Settings ingestion run 产出的 DatasetVersion / update 还没有自动闭合到 §11 `DatasetSemanticsRecord` 和 Dataset QRO。新卡补 Settings 链路从 update + PIT rule 到 MarketData registry 的第一条生成路径。
- **runtime/API**：新增 `POST /api/research-os/settings/dataset_semantics`，读取 recorded IngestionSkill、DataSourceAsset、IngestionSkillUpdate、DatasetVersion、PIT/bitemporal rule，校验 skill/source/update/DatasetVersion/checksum/PIT rule 匹配后组装 `DatasetSemanticsRecord`，默认以 `confirmatory_validation` 写 `MARKET_DATA_REGISTRY.record_dataset(...)`。
- **QRO/summary**：endpoint 复用 `_record_market_data_dataset_qro()` 写 Dataset QRO/Research Graph command；响应明确 `raw_data_stored=false`、`connector_called=false`。Settings summary 增加 `market_data_dataset_total` 和 `market_data_datasets`，Settings 安全页 Data Connectors panel 显示 latest DatasetSemantics，并在 latest update + PIT rule 存在时可触发登记。
- **对抗门**：缺 recorded PIT rule、坏 update_ref、DatasetVersion 不存在或 checksum mismatch 均 422；坏输入不写 MarketData registry，不写 Research Graph command。
- **测试**：`tests/test_onboarding_gateway.py` **33 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **92 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `6886f4e4`。边界：这是 Settings 链路到 refs-only DatasetSemantics + Dataset QRO 的闭合，不是 InstrumentSpec/Capability/MarketDataUseValidation 自动生成，不是实际策略消费数据行证明，不是真实 connector adapter、全资产自动同步、生产 scheduler、CI、线上或用户验收。

## 2026-06-27 · Settings InstrumentSpec and CapabilityMatrix generation from DatasetSemantics（ebaaefd1）

- **取前沿**：`6886f4e4` 已让 Settings ingestion update + PIT rule 生成 DatasetSemantics/QRO，但 §11 下游 MarketDataUse gate 仍需要 InstrumentSpec 和 MarketCapabilityMatrix。新卡补 Settings 链路从 DatasetSemantics 到标的/能力 metadata 的生成路径。
- **runtime/API**：新增 `POST /api/research-os/settings/instrument_specs`，读取 recorded IngestionSkill、DataSourceAsset、DatasetSemantics 和 PIT rule，生成 `InstrumentSpec` 并写 `MARKET_DATA_REGISTRY.record_instrument()`；新增 `POST /api/research-os/settings/capability_matrices`，从 recorded DatasetSemantics + InstrumentSpec 生成默认 research/backtest/paper capability，live/testnet 默认 false。
- **QRO/summary/UI**：两个 endpoint 均复用现有 market-data QRO 写入函数；响应明确 `raw_data_stored=false`、`connector_called=false`、`venue_called=false`。Settings summary 增加 `market_data_instrument_total` / `market_data_instruments` 和 `market_data_capability_matrix_total` / `market_data_capability_matrices`；Settings 安全页显示 latest instrument/capability 并提供 Instrument / Capability 按钮。
- **对抗门**：缺 recorded DatasetSemantics 时 InstrumentSpec 422，不写 instrument/QRO；A股/`cn_equity` live capability 仍由现有 validator 422，不写 capability/QRO。
- **测试**：`tests/test_onboarding_gateway.py` **33 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **92 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `ebaaefd1`。边界：这是 Settings 链路到 refs-only InstrumentSpec + CapabilityMatrix + QRO 的闭合，不是 MarketDataUseValidation 自动生成，不是实际策略消费数据行证明，不是真实 connector adapter、全资产自动同步、生产 scheduler、CI、线上或用户验收。

## 2026-06-27 · Settings MarketDataUseValidation generation from onboarding refs（e65a6e96）

- **取前沿**：`ebaaefd1` 已让 Settings 链路生成 DatasetSemantics、InstrumentSpec 和 CapabilityMatrix，但 IDE/Agent/portfolio/execution 下游强制引用的是 accepted MarketDataUseValidation ref。新卡补 Settings 链路到下游数据使用 gate 的 refs-only validation。
- **runtime/API**：新增 `POST /api/research-os/settings/market_data_use_validations`，从 recorded DatasetSemantics、InstrumentSpec、CapabilityMatrix 构造 `MarketDataUseRequest`，复用 `validate_market_data_use()`，成功后写 `MARKET_DATA_REGISTRY.record_use_validation()`。
- **QRO/summary/UI**：endpoint 复用 `_record_market_data_use_validation_qro()`；响应明确 `raw_data_stored=false`、`connector_called=false`、`strategy_builder_called=false`、`venue_called=false`。Settings summary 增加 `market_data_use_validation_total` / `market_data_use_validations`；Settings 安全页显示 latest validation 并提供 MarketDataUse 按钮。
- **对抗门**：缺 recorded CapabilityMatrix 时 422，不写 validation/QRO；验证仍经过 DatasetSemantics、InstrumentSpec 和 CapabilityMatrix validators。
- **测试**：`tests/test_onboarding_gateway.py` **33 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **92 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `e65a6e96`。边界：这是 Settings 链路到 refs-only accepted MarketDataUseValidation + QRO 的闭合，不是下游自动注入，不是实际策略消费数据行证明，不是真实 connector adapter、全资产自动同步、生产 scheduler、CI、线上或用户验收。

## 2026-06-27 · Settings SecretValue storage for SecretRef-backed connectors（4b7e2c19）

- **取前沿**：`e65a6e96` 已把 Settings Data Connector 链路闭合到 accepted MarketDataUseValidation，但 §4/§16 仍把 “SecretRef metadata 不等于真实 secret value backend” 留为缺口。新卡补 Settings-managed Data Connector secret value storage。
- **runtime/API**：新增 `POST /api/research-os/settings/secret_values`，这是 Settings 下唯一允许接收 plaintext credential 的 SecretValue 入口；endpoint 先构造并验证 SecretRef metadata，再写 `SecureKeystore`，并把 metadata `access_audit` 绑定到 `keystore:<name>`。
- **summary/gate**：SecretRef summary 返回 `keystore_refs`、`secret_value_stored`、`keystore_backend`，不返回 value 或 note。Data Connector check/run 在 SecretRef metadata 声明 keystore ref 时先确认 value 存在；缺 value 时 422 且不调用 checker/runner。
- **前端**：Settings 安全页 Data Connectors panel 显示 per-SecretRef stored/missing 状态、backend/ref，并提供 password 输入与 Store value 按钮；成功回执只显示 keystore ref/backend。
- **对抗门**：revoked SecretRef 不能写 value；metadata-only endpoint 仍拒绝 plaintext payload；declared keystore missing 会在 checker 前 fail-closed；fake checker 可通过 keystore ref 自行 fetch value，但 response/summary/UI 不回显 value。
- **测试**：`tests/test_onboarding_gateway.py` **37 passed / 2 warnings**；asset/onboarding/LLM/market-data/spine/data_quality adjacent **96 passed / 2 warnings**；targeted compileall **PASS**；Settings frontend scoped **1 file / 1 test passed**；frontend full **27 files / 301 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `4b7e2c19`。边界：这是 Settings-managed secret value storage + declared keystore presence gate，不是 OAuth/device-code/account auth、生产 keyring/HSM 选择、真实 connector adapter、外部 provider 实网连通、CI、线上或用户验收。

## 2026-06-27 · Settings registry-backed data connector adapter（adf0c2a4）

- **取前沿**：`4b7e2c19` 已让 Settings SecretRef value 进入 `SecureKeystore`，但 Settings Data Connector check/run 默认仍需要外部注入 fake/disabled runner。新卡补 GOAL §4/§11 的第一条内置 connector registry adapter。
- **runtime/API**：新增 Settings connector-name 推断、keystore-backed Tushare connector 实例化、`FetchRequest` 构造、`SettingsRegistryDataConnectorConnectionChecker` 和 `SettingsRegistryDataConnectorIngestionRunner`，并设为默认 `DATA_CONNECTOR_CONNECTION_CHECKER` / `DATA_CONNECTOR_INGESTION_RUNNER`。
- **connector path**：Tushare adapter 从 SecretRef declared keystore value 读取 token 后实例化 `TushareConnector(token=...)`；connection check 调 connector `health_check()`，ingestion run 调 connector `fetch()`，再复用现有 `FetchResult` row_count/checksum/plaintext-frame gate、DatasetVersion parquet writer、schema probe 和 IngestionSkillUpdate 管线。
- **对抗门**：fake Tushare SDK 测试确认 adapter 使用 Settings keystore token，不读 env 绕过 Settings；check/run response 不回显 token；declared keystore 缺 value、revoked SecretRef、bad runner result 仍由既有 gate fail-closed。
- **测试**：`tests/test_onboarding_gateway.py` **39 passed / 2 warnings**；connectors + asset/onboarding/LLM/market-data/spine/data_quality adjacent **110 passed / 2 warnings**；targeted compileall **PASS**。
- **落档**：新增 done 卡 `adf0c2a4`。边界：这是内置 connector registry adapter seam 和 fake SDK 证明，不是外部 Tushare/Binance 实网连通、完整 connector/provider adapter 覆盖、OAuth/device-code/account auth、生产 keyring/HSM 选择、CI、线上或用户验收。

## 2026-06-27 · Settings Binance public connector adapter coverage（a6dcb50f）

- **取前沿**：`adf0c2a4` 已证明 Tushare SecretRef-backed adapter；§4/§11 仍缺 no-auth public connector path。新卡覆盖 Binance public REST connector，不让空 SecretRef 被误判成普通缺 credential，也不把 fake method 测试说成实网连通。
- **runtime/API**：新增 `ingestion_skill_allows_no_secret_connector()`，只有 `auth_mode=none/no_auth/public`、无 `auth_ref`、无 `secret_refs` 时允许 no-auth connector check。Settings connector resolver 对 `binance_rest_spot` / `binance_rest_usdm` 显式构造 `BinanceRESTConnector`。
- **run/update**：no-auth ingestion run 继续要求 ok DataConnectorConnectionCheck；runner 调 connector `fetch()` 产 `FetchResult`，复用 DatasetVersion/schema probe/IngestionSkillUpdate gate；update 写 `secret:none:<connector_name>` 作为审计占位。
- **对抗门**：fake Binance connector method 测试确认 check 调 `health_check()`、run 调 `fetch()`、secret_refs 为空时仅显式 no-auth skill 可通过、DatasetVersion/update 被写入、响应不回显 secret 字段。
- **测试**：`tests/test_onboarding_gateway.py` **41 passed / 2 warnings**；connectors + asset/onboarding/LLM/market-data/spine/data_quality adjacent **112 passed / 2 warnings**；targeted compileall **PASS**。
- **落档**：新增 done 卡 `a6dcb50f`。边界：这是 Binance public connector no-auth seam 和 fake method proof，不是真实 Binance REST 实网连通、真实 Binance testnet key、venue permission proof、完整 provider adapter catalog、CI、线上或用户验收。

## 2026-06-27 · Settings data connector one-shot onboarding run（ce49ca21）

- **取前沿**：`e65a6e96` 已让 Settings 链路逐步闭合到 accepted MarketDataUseValidation；`4b7e2c19` / `adf0c2a4` / `a6dcb50f` 已补 SecretValue、Tushare adapter 和 Binance public no-auth adapter。新卡把散端点收成后端 one-shot onboarding run。
- **runtime/API**：新增 `POST /api/research-os/settings/data_connector_onboarding_runs`，按 step 串联 connection check、ingestion run、field mapping、PIT/bitemporal rule、DatasetSemantics、InstrumentSpec、CapabilityMatrix 和 MarketDataUseValidation。每步复用现有 endpoint/validator，不新增第二套验证路径。
- **field mapping**：未显式传 mapping 时，只对常见 event_time/symbol/OHLCV/amount/market/interval 字段做 conservative inference，其余 observed columns 进入 `unmapped_columns`，并标记 `mapping_method=agent_suggested`。
- **对抗门**：成功路径产 accepted MarketDataUseValidation；坏 mapping 在 `field_mapping` step 返回 `failed_step` + `completed_steps`，已发生 check/run 保留为审计事实，但不写 field mapping、PIT rule、DatasetSemantics、InstrumentSpec、CapabilityMatrix、MarketDataUseValidation 或 Graph command。
- **测试**：`tests/test_onboarding_gateway.py` **43 passed / 2 warnings**；connectors + asset/onboarding/LLM/market-data/spine/data_quality adjacent **114 passed / 2 warnings**；targeted compileall **PASS**；`validate_dev` **49 ✅ / 0 ❌ / 0 ⚠️ PASS**。
- **落档**：新增 done 卡 `ce49ca21`。边界：这是后端 one-shot onboarding seam 和 fake checker/runner proof，不是真实 provider 实网连通、完整 Settings wizard、下游 strategy auto-injection、venue execution、CI、线上或用户验收。

## 2026-06-27 · Settings Data Connector one-shot onboarding UI（8ba1997f）

- **取前沿**：`ce49ca21` 已有后端 one-shot onboarding seam，但 Settings 安全页仍需要 user 逐步点击 check/run/mapping/PIT/semantics/instrument/capability/use；同时 `secret_refs=[]` 的 public no-auth connector 会被前端误禁用测试和 run update。
- **前端 UI**：Settings Security 的 Data Connectors panel 新增 `Run onboarding` 动作，调用 `/api/research-os/settings/data_connector_onboarding_runs`；成功显示 `run_ref`、`market_data_use_validation_ref` 和 completed step count；失败显示 `failed_step`、`completed_steps` 和 sanitized error。
- **no-auth 修正**：`测试连接` / `Run update` 不再因为 `secret_refs=[]` 被前端禁用，no-auth/public 与 SecretRef gate 交给后端 validator 和 connector resolver 裁决。
- **对抗门**：测试覆盖 one-shot 成功调用、422 failed_step 展示、public no-auth connector 按钮启用、SecretValue 不回显。
- **测试**：`SettingsSecurityPage.test.tsx` **1 file / 2 tests passed**；frontend full **27 files / 302 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `8ba1997f`。边界：这是 Settings Data Connector one-shot UI seam，不是真实 provider 实网连通、完整字段映射/PIT wizard、下游 strategy auto-injection、venue execution、CI、线上或用户验收。

## 2026-06-27 · Settings editable Data Connector field mapping and PIT wizard（f11f8c4c）

- **取前沿**：`8ba1997f` 暴露了 one-shot onboarding，但 `Record mapping` / `PIT rules` 仍由前端硬推断默认 payload。新卡补 GOAL §4/§11 的可编辑字段映射/PIT wizard seam。
- **前端 UI**：Data Connectors panel 基于 schema probe columns 渲染 canonical role select，用户可指定 `event_time`、`instrument_id`、OHLCV/amount/market/interval 等 canonical roles；ignored columns 进入 `unmapped_columns`。
- **time/PIT controls**：新增 `event_time_column`、`known_at_column`、`effective_at_column`、`symbol_column` selectors；PIT rule 可编辑 event/known/effective columns、known/effective policies、as-of policy、restatement policy 和 timezone。
- **对抗门**：提交仍调用既有 `/data_connector_field_mappings` 与 `/pit_bitemporal_rules` endpoint，不复制后端 validator；unsafe `current_snapshot` 等 policy 由后端 422，UI 显示失败原因。
- **测试**：`SettingsSecurityPage.test.tsx` **1 file / 3 tests passed**；frontend full **27 files / 303 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `f11f8c4c`。边界：这是 Settings editable field mapping/PIT UI seam，不是真实 provider 实网连通、完整 provider catalog、生产 scheduler、下游 strategy auto-injection、CI、线上或用户验收。

## 2026-06-27 · Settings Generic REST connector YAML adapter（0fca8ad6）

- **取前沿**：`adf0c2a4` / `a6dcb50f` 已覆盖 Tushare 和 Binance hardcoded adapters，`f11f8c4c` 已补 editable mapping/PIT UI，但 GOAL §4/§11 仍缺可扩展 provider adapter。新卡把已有 `GenericRESTConnector` 接入 Settings resolver。
- **runtime/API**：`_settings_connector_for_skill()` 支持 `connector_name=generic_rest` / `generic_rest_yaml` / `generic_rest_config`；从 `IngestionSkill.connector_config` 或 request override 读取 `generic_rest_yaml` / `connector_yaml` / `generic_rest_config` / `connector_config`，构造 `GenericRESTConnector`，并拒绝 `auth.static_value`。
- **check/run**：Generic REST adapter 使用 YAML 内的 `connector_name` 作为 capability/source/audit 名称；Settings checker 调 `health_check()`，runner 调 `fetch()`，随后复用 DatasetVersion parquet writer、schema probe 和 IngestionSkillUpdate 管线。无 SecretRef 时仍要求 `auth_mode=none` 等既有 no-auth gate。
- **对抗门**：缺 YAML/config 不假绿，按现有 checker 契约记录 `status=failed` / `ok=false` 的 audited check；mocked Generic REST check/run 证明实例来自 per-skill YAML，不走全局 singleton；response 不回显 `api_key`、`sk-live` 或 `static_value`。
- **测试**：`tests/test_onboarding_gateway.py` **45 passed / 2 warnings**；connectors + asset/onboarding/LLM/market-data/spine/data_quality adjacent **116 passed / 2 warnings**；targeted compileall **PASS**。
- **落档**：新增 done 卡 `0fca8ad6`。边界：这是 Generic REST YAML adapter seam 和 fake method proof，不是真实外网 provider 连通、完整 provider catalog、OAuth/device-code/account auth、生产 scheduler、下游 strategy auto-injection、CI、线上或用户验收。

## 2026-06-27 · Settings Generic REST connector draft UI（8c774e19）

- **取前沿**：`0fca8ad6` 已有后端 Generic REST YAML adapter，但 Settings UI 仍只能操作已有 summary 里的 skill/source。新卡补 Generic REST source/skill draft 表单，不新增后端 bypass。
- **前端 UI**：Data Connectors panel 新增 Generic REST YAML draft，用户可填写 source ref/url、skill id、dataset/schema/PIT refs、symbol/market/interval/start/end 和 YAML；提交先写 `/api/research-os/settings/data_sources`，再写 `/api/research-os/settings/ingestion_skills`。
- **payload contract**：IngestionSkill 固定 `source_type=generic_rest_api`、`connector_config.connector_name=generic_rest`、`auth_mode=none`、`generic_rest_yaml=<textarea>`、`secret_refs=[]`，后续 test/run/onboarding 仍由既有 Settings 后端 gates 执行。
- **对抗门**：测试确认登记动作只调用 DataSource/IngestionSkill endpoints，不触发 connection check/run 假绿；第二步失败时 UI 显示失败并保留 source recorded 事实；UI 不接收 SecretValue。
- **测试**：`SettingsSecurityPage.test.tsx` **1 file / 4 tests passed**；frontend full **27 files / 304 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `8c774e19`。边界：这是 Settings Generic REST metadata draft UI，不是真实 provider 实网连通、完整 provider marketplace、OAuth/device-code/account auth、生产 scheduler、下游 strategy auto-injection、CI、线上或用户验收。

## 2026-06-27 · Methodology validation depth registry and API（b6bf792c）

- **取前沿**：§10 已有 `ValidationMethodologyRecord`，但状态仍把 CPCV + walk-forward 双轨、conformal/abstain、TCA、feature-level leakage probes、fault injection 与 recovery drill 列为验证纵深缺口。新卡补 first-class validation-depth runtime record，不伪造外部计算已执行。
- **runtime/API**：新增 `ValidationDepthRecord`、`validate_validation_depth()`、`PersistentValidationDepthRegistry`；`POST /api/research-os/methodology/validation_depth_records` 写 JSONL append-only event，`GET /api/research-os/methodology/summary` 返回 refs/verdict 摘要。
- **对抗门**：strong label 缺 CPCV+walk-forward、conformal、abstain、feature leakage probe 会拒绝；paper/testnet/live/production 缺 TCA/cost、fault injection、recovery drill 会拒绝；non-passing verdict、silent mock fallback、user-waived strong overclaim 会拒绝；API 失败不写 partial JSONL。
- **测试**：`tests/test_methodology_validation.py` **13 passed / 2 warnings**；methodology/spine/trust/goal/compiler adjacent **52 passed / 2 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `b6bf792c`。边界：这是 validation-depth 证据 refs registry/API，不是 CPCV/conformal/TCA 计算器、真实 broker/venue fault drill、production scheduler、完整 validation dossier UI、CI、线上或用户验收。

## 2026-06-27 · Trust release gate registry for RDP publish（e9c58149）

- **取前沿**：§13 `TrustReleaseGateRecord` 已有 contract，但 RDP local publish 可不带 release gate。新卡把 trust release gate 接到 RDP publish 流水线。
- **runtime/API**：新增 `PersistentTrustReleaseGateRegistry`、`trust_release_gate_record_from_dict()`、`POST /api/research-os/trust/release_gates` 和 `GET /api/research-os/trust/summary`。
- **RDP publish gate**：`RDPPackagePublishRecord` 新增 `trust_release_ref`；`/api/research-os/rdp/manifests/{package_id}/publish` 在 export/publish 前要求 payload `trust_release_ref` 已登记，缺 ref 或 unknown ref 422 且不写 publish record。旧 publish JSONL 无该字段仍可 replay。
- **前端 UI**：`RDPExportPanel` local publish 增加 `trust_release_ref` 输入，空 ref 前端阻断，不打后端；成功 publication 显示 gate ref。
- **对抗门**：release gate 缺任一 §13 检查 ref 不写 JSONL；RDP publish 缺/未知 trust gate 不写 publication；成功 publish 和 publications summary 回显 `trust_release_ref`。
- **测试**：`tests/test_trust_layer.py` + `tests/test_research_os_rdp_publish.py` **20 passed / 2 warnings**；trust/RDP adjacent **47 passed / 2 warnings**；`python -m compileall -q app/backend/app` PASS；`RDPExportPanel.test.tsx` **1 file / 6 tests passed**；RDP/agent-workbench frontend scoped **2 files / 46 tests passed**；frontend build PASS（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `e9c58149`。边界：这是 RDP local publish 的 trust gate ref 接线和既有 publish UI 的入参同步，不是完整 release gate 管理 UI、专家工作流、自动压力测试生成器、外部 object-store publish、CI、线上或用户验收。

## 2026-06-27 · Mathematical Spine full-chain registry and API（ecc6b957）

- **取前沿**：`TheoryImplementationBinding` / `ConsistencyCheck` 已建，但状态仍写明 Mathematical Spine 未贯穿 data→factor→model→signal→portfolio→execution→backtest→attribution→monitor。新卡补 full-chain refs registry/API。
- **runtime/API**：新增 `MathematicalSpineChainRecord`、`validate_mathematical_spine_chain()`、`PersistentMathematicalSpineChainRegistry`；`POST /api/research-os/spine/mathematical_chains` 写 JSONL append-only event，summary 返回全链 refs。
- **对抗门**：缺 data/factor/model/forecast/signal/strategy/portfolio/risk/execution/backtest/attribution/monitor 任一关键 ref、缺 theory/consistency/evidence/validation refs、consistency 非 checked/accepted 或 silent mock fallback 均拒绝；API 用 current user 覆盖 payload `recorded_by`。
- **测试**：`tests/test_research_os_spine.py` **13 passed / 2 warnings**；spine/methodology/trust/goal/compiler/factor/execution adjacent **154 passed / 2 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `ecc6b957`。边界：这是 full-chain Mathematical Spine refs record/API，不是所有生产者自动写入、完整 compiler pass、strategy code generator、完整 graph database、前端 inspector UI、CI、线上或用户验收。

## 2026-06-27 · GOAL entrypoint spine coverage registry and API（173405ef）

- **取前沿**：§0/§1/§7/§8 已有 QRO/Graph/Compiler 多个入口接线，但状态仍写明全入口单一路径未闭合。新卡补 entrypoint coverage refs registry/API，用来证明某个入口是否已走 QRO -> Graph -> Compiler -> Evidence/Validation。
- **runtime/API**：新增 `GoalEntrypointCoverageRecord`、`validate_goal_entrypoint_coverage()`、`validate_goal_entrypoint_coverage_manifest()`、`PersistentGoalEntrypointCoverageRegistry`；`POST /api/research-os/goal/entrypoint_coverage_records` 写 JSONL append-only event，summary 返回 present/missing entry sources；`POST /api/research-os/compiler/compile_qro` 和 `POST /api/research-os/compiler/passes` 成功记录 IR/pass 后自动写 entrypoint coverage 并返回 `entrypoint_coverage_ref`。
- **对抗门**：缺 QRO、Research Graph command、Compiler IR/pass、evidence、validation、permission、replay refs 均拒绝；unknown EntrySource/GOAL section、silent mock fallback、raw payload persisted 均拒绝；all-entrypoints-wired claim 缺 Chat/Canvas/API/IDE/Scheduler/Agent Shell 任一入口会 fail；unknown QRO、缺 evidence 或 silent mock coverage 的 `compile_qro` 失败路径不写 compiler/coverage partial record；silent mock IR 的 direct pass coverage 失败路径不写 pass/coverage partial record。
- **测试**：`tests/test_goal_coverage.py` **13 passed / 2 warnings**；goal/compiler scoped **31 passed / 2 warnings**；goal/compiler/spine/methodology/trust adjacent **70 passed / 2 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `173405ef`。边界：这是 entrypoint coverage 证据 refs registry/API，不是所有入口 producer 自动接线、完整 compiler implementation、strategy code generator、CI、线上或用户验收。

## 2026-06-27 · RDP manifest upstream compiler coverage and math spine gate（31870f62）

- **取前沿**：`173405ef` / `41b7c9e2` / `0b3f6a91` 已把 compiler artifact 绑定到 entrypoint coverage 和 Mathematical Spine chain；`e9c58149` 已把 RDP publish 绑定 trust release gate。新卡补 RDP manifest 本体的 upstream refs 硬门。
- **runtime/API**：`RDPManifest` 新增 `compiler_artifact_refs`、`mathematical_spine_chain_refs`、`goal_entrypoint_coverage_refs`；RDP record/materialize/bundle/deployment attestation/archive/source-run integrity/publish 入口在继续前校验三类 refs 已登记，并要求 coverage lifecycle refs 覆盖 compiler artifact 和 chain refs。
- **open package**：materialized `refs.json` 打包三类 upstream refs，交付包可审计其 compiler artifact、Mathematical Spine chain 和 entrypoint coverage 来源。
- **对抗门**：缺三类 refs 的 manifest 被 validator 拒绝；未登记 compiler artifact 422 且不写 RDP manifest；replay/detail/materialized refs 保留三类 refs。
- **测试**：RDP scoped **56 passed / 2 warnings**；goal/compiler/trust/RDP adjacent **102 passed / 2 warnings**。
- **落档**：新增 done 卡 `31870f62`。边界：这是 RDP manifest 的上游 refs gate，不是所有 GOAL 入口闭合、完整 compiler pass/strategy codegen、外部 publish、CI、线上或用户验收。

## 2026-06-27 · RDP publish source-run and live deployment attestation gate（d14e2309）

- **取前沿**：RDP 已有 source-run integrity、deployment attestation、trust release gate 和 upstream refs gate，但 local publish 仍只要求 trust gate + archive。新卡把已有 attestation 记录接到 publish 终端动作。
- **runtime/API**：`/api/research-os/rdp/manifests/{package_id}/publish` 在 archive export 后、copy publish 前检查 source-run integrity；manifest 有 `source_file_refs` 时，matching manifest hash + artifact hash 的 integrity records 必须覆盖 `run_refs`。`target_runtime=live` 时还要求 deployment attestation 覆盖 `deployment_refs`。
- **前端 UI**：`RDPExportPanel` 在有 source refs 且未完成 source-run integrity 时阻断 local publish 请求，先让用户完成 attest。
- **对抗门**：source bundle + trust gate 都存在但 source-run integrity 缺失时 422 且不写 publication；成功 publish 先登记 integrity；external channel 仍被 local-only gate 拒绝。
- **测试**：`tests/test_research_os_rdp_publish.py` **8 passed / 2 warnings**；`RDPExportPanel.test.tsx` **1 file / 7 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `d14e2309`。边界：这是 publish 终端 attestation gate，不是外部 object-store publish、live deployment runner、真实 broker/provider attestation、CI、线上或用户验收。

## 2026-06-27 · Weekly monitor scheduler compiler coverage（d6bbdb2e）

- **取前沿**：`10b23996` 已让 weekly monitor scheduler tick 写 Observable QRO，但 state 仍把 scheduler 的 QRO→Compiler wiring 列为缺口。新卡让同一路径自动生成 compiler IR/pass 和 scheduler entrypoint coverage。
- **runtime/API**：`_record_weekly_monitor_qro` 写 Research Graph 后调用 `_compile_weekly_monitor_qro`，复用 `_compile_qro_payload`、compiler store 和 coverage registry，返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
- **refs contract**：compiler 记录绑定 scheduler DAG/op、QRO ref、Research Graph command ref、result hash validation ref、permission ref、environment lock ref 和 deterministic run plan ref，不复制 factor id、cost drift report、actions 或 raw monitor payload。
- **对抗门**：非法 `factor_observations` 带 DSR/PBO/gate verdict 时仍在 monitor 输入校验阶段 422，不写 Graph、compiler IR 或 coverage partial；DAG path 断言 actor_source 为 `scheduled_agent`。
- **测试**：`tests/test_monitor_production.py` **7 passed / 2 warnings**。
- **落档**：新增 done 卡 `d6bbdb2e`。边界：这是 weekly monitor scheduler 的 compiler/coverage producer，不是所有 scheduler 入口、完整 compiler implementation、CI、线上 cron 证明、真实 deployment monitor 或 live broker 连通证明。

## 2026-06-27 · Settings market data use/onboarding compiler coverage（5d93d82e）

- **取前沿**：`e65a6e96` 已让 Settings 生成 accepted `MarketDataUseValidationRecord` 与 MarketDataUse QRO；`ce49ca21` / `8ba1997f` 已让 Data Connector one-shot onboarding 串起 Settings 数据接入链路。新卡把 direct MarketDataUse 和 one-shot onboarding 的最终 QRO 接到 Governed Compiler 与 GOAL entrypoint coverage。
- **runtime/API**：`_record_market_data_use_validation_qro` 写 Research Graph 后自动调用 `_compile_market_data_use_validation_qro`，返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。`/api/research-os/settings/data_connector_onboarding_runs` 成功后再为 one-shot 入口生成单独 coverage，并把 `compiler_coverage` 写入 `completed_steps`。
- **refs contract**：direct coverage entrypoint 是 `api:research_os.settings.market_data_use_validations`；one-shot coverage entrypoint 是 `api:research_os.settings.data_connector_onboarding_runs`。两者都绑定最终 MarketDataUse QRO、Research Graph command、Dataset/Instrument/Capability/MarketDataUse validation refs、permission/env/run-plan refs，不复制 raw rows、instrument symbol、plaintext secret、strategy builder payload 或 venue payload。
- **测试**：`tests/test_onboarding_gateway.py` **45 passed / 2 warnings**；asset/onboarding/market-data/goal/compiler adjacent **103 passed / 2 warnings**；`SettingsSecurityPage.test.tsx` **1 file / 4 tests passed**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `5d93d82e`。边界：这是 Settings data onboarding 的 compiler/coverage producer，不是真实 provider 实网连通、完整 provider catalog、下游 strategy auto-injection、venue execution、CI、线上或用户验收。

## 2026-06-27 · Execution QRO producers compiler coverage（093ee78e）

- **取前沿**：execution ladder 已有 order intent、runtime promotion、materialization、connectivity、safety、capability、submit request、submission、venue event、reconciliation、action 的 ExecutionPolicy QRO/ResearchGraph write-through，但这些 API 成功路径还没有进入 governed compiler/entrypoint coverage spine。
- **runtime/API**：新增 `_compile_execution_boundary_qro`，11 类 execution QRO producer 写 Graph 后自动生成 compiler IR/pass 和 entrypoint coverage refs，并随 HTTP response 返回。
- **refs contract**：coverage entrypoint 保持真实 API 名称，例如 `api:research_os.execution.order_submissions`；compiler IR/pass 绑定 QRO、Research Graph command、validation/evidence/permission/env/run-plan refs，不复制 raw order、raw event 或 secret material。
- **对抗门**：17 条 execution 成功路径断言 response refs、store 回查、entrypoint_ref、`direct_graph_mutation=false`、`bypassed_permission=false`、`raw_payload_persisted=false`；拒绝路径继续由原 no-write tests 覆盖。
- **测试**：`tests/test_execution_boundary_contract.py` **78 passed / 2 warnings**；`tests/test_governed_compiler.py` + `tests/test_goal_coverage.py` + `tests/test_monitor_production.py` **40 passed / 2 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `093ee78e`。边界：这是 execution refs-only compiler/coverage producer，不是真实 venue connector、真实下单、资金执行、线上长期 scheduler、CI 或用户验收。

## 2026-06-27 · Market data contract QRO producers compiler coverage（ed548b5c）

- **取前沿**：DatasetSemantics、InstrumentSpec、MarketCapabilityMatrix 已写 market-data registry、QRO 和 Research Graph；MarketDataUseValidation / one-shot onboarding 已有 compiler coverage。剩余缺口是前置 market-data objects 没有 entrypoint-level compiler coverage。
- **runtime/API**：新增 `_compile_market_data_contract_qro`；direct `/api/research-os/market_data/datasets|instruments|capability_matrices` 成功后返回 compiler IR/pass/coverage refs；Settings `dataset_semantics|instrument_specs|capability_matrices` 传入 settings-specific entrypoint。
- **refs contract**：direct entrypoint 和 Settings entrypoint 分开记录，compiler IR/pass 绑定 QRO、Research Graph command、validation/evidence/permission/env/run-plan refs，不复制 raw rows/raw payload/secret。
- **对抗门**：测试确认 direct entrypoint 不误写成 Settings，Settings entrypoint 不误写成 direct；coverage store 可回查同一 QRO/Graph command。
- **测试**：`tests/test_market_data_contract.py` + `tests/test_onboarding_gateway.py` **62 passed / 2 warnings**；market-data/onboarding/goal/compiler/execution adjacent **173 passed / 2 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `ed548b5c`。边界：这是 market-data contract refs-only compiler coverage，不是真实 provider 实网连通、全资产自动同步、下游 strategy auto-injection、venue permission proof、CI 或用户验收。

## 2026-06-27 · Signal/portfolio QRO producers compiler coverage（a00ed3d6）

- **取前沿**：SignalContract、SignalPerformanceValidation 和 portfolio production promote gate 已有 registry/gate/honest-N 约束，但成功路径还没有统一写 QRO→Graph→Compiler→Coverage。
- **runtime/API**：新增 `_record_signal_contract_qro`、`_record_signal_validation_qro`、`_record_portfolio_promote_qro`；`POST /api/factors/signal_contracts`、`POST /api/research-os/signal_validations`、`POST /api/portfolios/{portfolio_id}/promote` 成功后返回 QRO/Graph/compiler/coverage refs。
- **refs contract**：coverage entrypoint 分别是 `api:factors.signal_contracts`、`api:research_os.signal_validations`、`api:portfolios.promote`；compiler IR/pass 绑定 QRO、Research Graph command、validation/evidence/permission/env/run-plan refs。
- **对抗门**：测试确认 SignalContract 不把模型本体路径写入 Graph/Compiler；SignalValidation 不保存 raw predictions/raw returns；PortfolioPolicy QRO 不保存 `asset_returns` 或收益数列明细，honest-N/gate 语义保持不变。
- **测试**：`tests/test_factor_lab_endpoints.py` + `tests/test_portfolio_promote_api.py` **30 passed / 2 warnings**；factor/portfolio/goal/compiler/market-data/execution adjacent **174 passed / 2 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `a00ed3d6`。边界：这是 signal/portfolio refs-only compiler coverage，不是 signal alpha proof、自动组合构建、stage flip、真实下单、CI、线上或用户验收。

## 2026-06-27 · Factor registration compiler coverage（67a5e97c）

- **取前沿**：`POST /api/factors` 已有编译、前视、重名三检查和 FactorRegistry 初始 `NEW` 写入，但成功路径还没有 Factor QRO、Research Graph command 或 entrypoint compiler coverage。
- **runtime/API**：新增 `_record_factor_qro`；因子注册成功后写 Factor QRO，并随响应返回 `qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。
- **refs contract**：coverage entrypoint 是 `api:factors`；QRO/Compiler 记录 formula hash、params hash、gate summary、Factor refs、permission/env/run-plan refs，不保存公式原文。
- **对抗门**：测试确认 Factor QRO 类型、coverage store 回查、compiler safety flags 和 `raw_payload_persisted=false`；公式原文不进入 Graph/Compiler；原失败路径仍由注册三门阻断。
- **测试**：`tests/test_factor_desk_f2.py` **28 passed / 2 warnings**；factor/portfolio/goal/compiler/market-data/execution adjacent **202 passed / 2 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `67a5e97c`。边界：这是 Factor registration refs-only compiler coverage，不是 alpha validation、strategy codegen、portfolio construction、runtime promotion、CI、线上或用户验收。

## 2026-06-27 · Factor audit ValidationDossier compiler coverage（b9c3dc4b）

- **取前沿**：`67a5e97c` 已把 factor registration 接到 Factor QRO/Graph/Compiler/Coverage，但 `POST /api/factors/{factor_id}/audit` 仍只返回多证据三角报告，没有把报告作为 ValidationDossier producer 写入统一链路。
- **runtime/API**：新增 `_record_factor_audit_qro`；因子 audit 成功后写 `QROType.VALIDATION_DOSSIER`，并随响应返回 `validation_dossier_ref`、`qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。audit endpoint 现在通过 `require_user_dependency` 记录 actor。
- **refs contract**：coverage entrypoint 是 `api:factors.audit`；QRO/Compiler 只保存 formula hash、report hash、threshold hash、check summary hash、verdict 和 refs，不保存公式原文、raw return panel、raw audit payload 或 secret marker。
- **对抗门**：成功路径断言 ValidationDossier QRO、coverage store 回查、compiler safety flags 和 `raw_payload_persisted=false`；invalid tier 422 后 Graph/Compiler/Coverage 记录数不变。
- **测试**：`tests/test_factor_desk_f2.py` **29 passed / 2 warnings**；factor/portfolio/goal/compiler/market-data/execution adjacent **203 passed / 2 warnings**；后端全量 **1802 passed / 13 skipped / 283 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `b9c3dc4b`。边界：这是 Factor audit refs-only ValidationDossier compiler coverage，不是 alpha approval、strategy promotion、portfolio construction、runtime permission、CI、线上或用户验收。

## 2026-06-27 · Factor layered BacktestRun compiler coverage（84c728cb）

- **取前沿**：factor registration 和 factor audit 已进入 QRO/Graph/Compiler/Coverage，但 `POST /api/factors/{factor_id}/layered_backtest` 仍只返回分层诊断报告，没有作为 BacktestRun producer 写入统一链路。
- **runtime/API**：新增 `_record_factor_layered_backtest_qro`；分层回测成功后写 `QROType.BACKTEST_RUN`，并随响应返回 `backtest_run_ref`、`qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。layered endpoint 现在通过 `require_user_dependency` 记录 actor。
- **refs contract**：coverage entrypoint 是 `api:factors.layered_backtest`；QRO/Compiler 只保存 formula hash、report hash、quantile/sample summary 和 refs，不保存公式原文、bucket mean returns、long-short spread、raw returns 或 secret marker。
- **对抗门**：成功路径断言 BacktestRun QRO、coverage store 回查、compiler safety flags 和 `raw_payload_persisted=false`；`n_quantiles < 2` 422 后 Graph/Compiler/Coverage 记录数不变。
- **测试**：`tests/test_factor_desk_f2.py` **30 passed / 2 warnings**；factor/portfolio/goal/compiler/market-data/execution adjacent **204 passed / 2 warnings**；后端全量 **1803 passed / 13 skipped / 283 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `84c728cb`。边界：这是 Factor layered refs-only BacktestRun compiler coverage，不是 alpha approval、cost-aware strategy performance、portfolio promotion、runtime permission、CI、线上或用户验收。

## 2026-06-27 · Factor preview ValidationDossier compiler coverage（ae5237ad）

- **取前沿**：factor registration、audit 和 layered backtest 已进入 QRO/Graph/Compiler/Coverage，但 `POST /api/factors/validate` 的 build desk 即时预览仍只返回 HTTP 结果，没有作为 preview ValidationDossier producer 写入统一链路。
- **runtime/API**：新增 `_record_factor_preview_validation_qro`；`factors_validate` 的 ok、compile reject、lookahead reject 200 返回路径写 `QROType.VALIDATION_DOSSIER`，并随响应返回 `validation_dossier_ref`、`qro_id`、`research_graph_command_id`、`compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。validate endpoint 现在通过 `require_user_dependency` 记录 actor。
- **refs contract**：coverage entrypoint 是 `api:factors.validate`；QRO/Compiler 只保存 formula hash、result hash、reason hash、IC summary hash、stage/valid summary 和 refs，不保存公式原文、IC 数值、return panel 或 secret marker。
- **对抗门**：成功预览、编译拒绝、前视拒绝三条路径均断言 ValidationDossier QRO、coverage store 回查、compiler safety flags 和 `raw_payload_persisted=false`；拒绝预览只写 rejected dossier，不注册因子也不升级为 alpha proof。
- **测试**：`tests/test_factor_desk_f2.py` **31 passed / 2 warnings**；factor/portfolio/goal/compiler/market-data/execution adjacent **205 passed / 2 warnings**；后端全量 **1804 passed / 13 skipped / 283 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `ae5237ad`。边界：这是 Factor preview refs-only ValidationDossier compiler coverage，不是 factor registration、alpha approval、strategy promotion、runtime permission、CI、线上或用户验收。

## 2026-06-27 · Model Governance runtime record compiler coverage（aeb7832a）

- **取前沿**：Model Registry promotion 已进入 QRO/Graph/Compiler/Coverage，但 monitoring profile、recertification record、artifact inspection 和 serving invocation 仍只停在 registry 或 prediction response。
- **runtime/API**：新增 `_record_model_monitoring_profile_qro`、`_record_model_recertification_qro`、`_record_model_artifact_inspection_qro`、`_record_model_serving_invocation_qro`；三个 `/api/research-os/model_governance/*` POST 和 `/api/models/{model_id}/versions/{version}/predict` 成功后返回 QRO/Graph/compiler/coverage refs。
- **refs contract**：coverage entrypoints 分别是 `api:research_os.model_governance.monitoring_profiles`、`api:research_os.model_governance.recertification_records`、`api:research_os.model_governance.artifact_inspections`、`api:models.predict`；compiler/coverage 绑定 ModelVersion、ModelPassport、inspection/profile/recertification/serving refs、permission/env/run-plan refs，不复制 raw evidence、loader limitation text、feature rows、prediction values 或 artifact path。
- **对抗门**：测试确认四条成功路径的 QRO type、permission ref、entrypoint_ref、compiler safety flags 和 `raw_payload_persisted=false`；未声明 recertification trigger 的 422 仍不写 Graph/Compiler/Coverage partial record。
- **测试**：`tests/test_model_governance.py` **31 passed / 2 warnings**；model/training/goal/compiler/spine adjacent **102 passed / 2 warnings**；后端全量 **1804 passed / 13 skipped / 283 warnings**；`python -m compileall -q app/backend/app` PASS。
- **落档**：新增 done 卡 `aeb7832a`。边界：这是 refs-only Model Governance runtime record compiler coverage，不是真实外部 serving、runtime auto-promotion、artifact sandbox execution、portfolio/order/execution permission、CI、线上或用户验收。

## 2026-06-27 · Training MarketDataUse/PIT hard gate（03dcb87d）

- **取前沿**：Settings/MarketDataUse 已能生成 accepted refs，训练成功路径已有 Model QRO、Governed Compiler 和 entrypoint coverage，但 `/api/training/jobs` 仍允许只凭 `dataset_id` 提交，未把 estimator 与 data timing/PIT refs 绑定成硬门。
- **runtime/API**：`training_submit` 现在要求 `market_data_use_validation_refs` 是非空 list；每个 ref 必须 resolve 到 accepted/no-violation `MarketDataUseValidationRecord`，且至少一个 ref 的 `dataset_refs` 覆盖训练 `dataset_id`。缺 ref、unknown、未 accepted、violation、dataset mismatch 均 422 且不创建 job。
- **refs contract**：`TrainingRequest`、ValidationDossier、training Model QRO input/output contract、QRO lineage、Compiler IR validation refs 和 GOAL entrypoint coverage 绑定同一组 refs；QRO/Compiler 仍只保存 refs/hash/count，不复制 metrics 明细、artifact path、artifact dir 或模型二进制路径。
- **前端**：训练台新增 MarketDataUse refs 输入，按空白/逗号拆分去重后随 `/api/training/jobs` payload 下发；无 refs 时禁用提交。
- **测试**：training focused **70 passed / 2 warnings**；model/market-data/goal/compiler adjacent **145 passed / 2 warnings**；后端全量 **1805 passed / 13 skipped / 283 warnings**；frontend scoped **25 passed**；frontend full **28 files / 307 tests passed**；frontend build **PASS**；`compileall app/backend/app` PASS。
- **落档**：新增 done 卡 `03dcb87d`。边界：这是训练入口的 refs-only MarketDataUse/PIT hard gate，不是真实 provider 实网连通、所有 backtest/report/data consumer 全域 PIT 闭合、线上训练集群、runtime auto-promotion、CI 或用户验收。

## 2026-06-27 · Training job backtest MarketDataUse + BacktestRun coverage（2b9b76fb）

- **取前沿**：`03dcb87d` 已让训练提交绑定 MarketDataUse/PIT refs，但训练后的 `/api/training/jobs/{job_id}/backtest` 仍可换 dataset 做跨集 OOS，未校验回测 dataset refs，也没有 BacktestRun QRO/Compiler/Coverage。
- **runtime/API**：`training_job_backtest` 现在用训练 job request refs 作为同集 fallback；如果 payload 换 `dataset_id`，refs 必须覆盖 backtest dataset。只拿训练 dataset refs 去回测另一个 dataset 会 422，不创建 BacktestRun QRO。
- **QRO/Compiler**：新增 `_record_training_job_backtest_qro`，成功回测写 `QROType.BACKTEST_RUN`、Research Graph command、compiler IR/pass 和 `api:training.jobs.backtest` coverage。QRO/Compiler 只保存 refs/hash/count，不保存 raw `metrics`、`equity_curve`、`artifact_dir`、`artifact_path` 或模型二进制路径。
- **前端**：训练台评价面板新增 backtest MarketDataUse refs 输入，跨集回测时可显式传 refs；payload 按空白/逗号拆分去重。
- **测试**：backtest/training focused **29 passed / 2 warnings**；training/model/market-data/goal/compiler adjacent **138 passed / 2 warnings**；后端全量 **1805 passed / 13 skipped / 283 warnings**；frontend scoped **26 passed**；frontend full **28 files / 308 tests passed**；frontend build **PASS**；`compileall app/backend/app` PASS。
- **落档**：新增 done 卡 `2b9b76fb`。边界：这是训练 job 回测入口的 refs-only MarketDataUse/PIT hard gate + BacktestRun compiler coverage，不是所有回测/report consumer 全域 PIT 闭合、alpha proof、promotion approval、真实 provider 实网连通、线上训练/回测集群、CI 或用户验收。

## 2026-06-27 · Factor layered backtest MarketDataUse/PIT hard gate（48f70fa3）

- **取前沿**：`84c728cb` 已把 `POST /api/factors/{factor_id}/layered_backtest` 接成 BacktestRun QRO/Graph/Compiler/Coverage，但该入口仍可在没有 MarketDataUse/PIT refs 的情况下产分层回测证据，属于“其他回测入口”缺口。
- **runtime/API**：新增 `_factor_layered_market_data_use_validation_refs`；endpoint 在调用 `layered_backtest(...)` 前要求 `market_data_use_validation_refs` 非空 list，每个 ref 必须 resolve 到 accepted/no-violation 记录，use_context 必须是 backtest 或 confirmatory_validation；引用的 DatasetSemantics 必须有 `known_at_ref`、`effective_at_ref`、`pit_bitemporal_rules_ref`，CapabilityMatrix 必须允许 backtest，Instrument/Capability asset_class 必须覆盖请求 market。
- **refs contract**：`_record_factor_layered_backtest_qro` 把 deduped refs 写入 BacktestRun QRO input/output、evidence refs、lineage 和 Compiler IR validation refs；QRO/Compiler 仍只保存 formula hash、report hash、quantile/sample summary、refs 和 hashes，不保存公式原文、bucket mean returns、long-short spread 或 raw returns。
- **对抗门**：测试覆盖缺 refs、unknown refs、未 accepted/带 violation 历史脏账、market mismatch、PIT timing 缺失、invalid quantiles 失败路径均不写 Graph/Compiler/Coverage partial record；成功路径可从 QRO/IR 回查 refs。
- **测试**：`tests/test_factor_desk_f2.py` **35 passed / 2 warnings**；factor/portfolio/goal/compiler/market-data/execution adjacent **155 passed / 2 warnings**；后端全量 **1809 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS。
- **落档**：新增 done 卡 `48f70fa3`。边界：这是 factor layered backtest 入口的 refs-only MarketDataUse/PIT hard gate，不是正式报告全域 gate、所有 backtest/report consumer 全域 PIT 闭合、alpha approval、strategy promotion、CI、线上或用户验收。

## 2026-06-27 · RDP formal package MarketDataUse/PIT gate（5ba64e4f）

- **取前沿**：RDP manifest gate 已要求 data_refs、DatasetVersion、reproducibility command、run、honest-N、known limits、compiler/spine/coverage refs 等字段，但没有一等 `market_data_use_validation_refs`，正式交付包可引用 dataset/run 而不强制绑定 event/known/effective time 证据。
- **runtime/API**：`RDPManifest` 新增 `market_data_use_validation_refs`，`validate_rdp_manifest` 要求非空；`_rdp_manifest_from_payload` 接收该字段，summary/detail 回显；`_validate_rdp_manifest_registered_refs` 回查 MarketData registry，要求 refs 已记录、accepted、无 violation、use_context 为 backtest/confirmatory_validation，DatasetSemantics 有 `known_at_ref` / `effective_at_ref` / `pit_bitemporal_rules_ref`，且覆盖 manifest 的 `dataset:*` data_refs。
- **package contract**：open `manifest.json` 和 `refs.json` 都输出 `market_data_use_validation_refs`；package id hash 纳入该字段，refs 变化会得到不同 package identity。
- **前端**：RDP export panel detail 显示 MarketDataUse refs，不把正式包的数据使用证据藏在后端 JSON。
- **对抗门**：测试覆盖缺 refs 的 pure manifest rejection、unknown ref API 422 no-write、data_ref mismatch API 422 no-write，以及 RDP materialize/bundle/archive/publish 仍复用同一 runtime validator。
- **测试**：RDP focused **60 passed / 2 warnings**；RDP/market-data/goal/compiler adjacent **168 passed / 2 warnings**；后端全量 **1812 passed / 13 skipped / 283 warnings**；RDP frontend scoped **1 file / 7 tests passed**；frontend full **28 files / 308 tests passed**；frontend build **PASS**；`compileall app/backend/app` PASS。
- **落档**：新增 done 卡 `5ba64e4f`。边界：这是 RDP 正式交付包的 refs-only MarketDataUse/PIT gate，不是外部 publish、对象存储/CI release、完整 release gate UI、所有非 RDP 报告入口、真实 provider 实网连通、CI 或线上验收。

## 2026-06-27 · Agent report.generate MarketDataUse/PIT gate（8f9d53ac）

- **取前沿**：RDP formal package 已接 MarketDataUse/PIT gate，但 Agent Shell 的 `report.generate` 仍可只凭 `run_id` 生成 markdown 报告，属于非 RDP 报告入口缺口。
- **runtime/schema**：`report.generate` tool schema 现在要求 `run_id` + `market_data_use_validation_refs`；handler 在调用 `project_verdict` / `project_overfit` / `project_cost_sensitivity` 前回查 MarketData registry，要求 refs 已记录、accepted、无 violation、use_context 为 backtest/confirmatory_validation，且 DatasetSemantics 有 `known_at_ref` / `effective_at_ref` / `pit_bitemporal_rules_ref`。
- **report contract**：坏 refs 返回 `no_write=true`，不投影报告；成功报告返回体与 markdown 都显示 MarketDataUse refs。报告仍只是 Agent markdown，不升级成 RDP package 或 persisted artifact。
- **对抗门**：测试覆盖缺 refs、unknown、rejected、violation、wrong use_context、DatasetSemantics timing 缺失均不调用报告投影；成功路径断言 refs 出现在 markdown 和返回体。
- **测试**：Agent report focused **37 passed / 2 warnings**；Agent/DS1/delivery/legacy chat adjacent **51 passed / 2 warnings**；Agent/MarketData/Goal adjacent **118 passed / 2 warnings**；后端全量 **1820 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `8f9d53ac`。边界：这是 Agent markdown report 的 refs-only MarketDataUse/PIT gate，不是 RDP formal package、report artifact persistence、所有非 RDP 报告入口、CI、线上或用户验收。

## 2026-06-27 · Factor audit MarketDataUse/PIT gate（713803ca）

- **取前沿**：`b9c3dc4b` 已把 `POST /api/factors/{factor_id}/audit` 接成 ValidationDossier QRO/Graph/Compiler/Coverage，但该报告/验证材料仍可在没有 MarketDataUse/PIT refs 的情况下生成。
- **runtime/API**：抽出 `_factor_market_data_use_validation_refs` 供 factor audit 与 layered backtest 共享；audit endpoint 在运行 `run_factor_audit(...)` 前要求 `market_data_use_validation_refs` 非空 list，每个 ref 必须 resolve 到 accepted/no-violation 记录，use_context 必须是 backtest 或 confirmatory_validation；引用的 DatasetSemantics 必须有 `known_at_ref`、`effective_at_ref`、`pit_bitemporal_rules_ref`，CapabilityMatrix 必须允许 backtest，Instrument/Capability asset_class 必须覆盖请求 market。
- **refs contract**：`_record_factor_audit_qro` 把 deduped refs 写入 ValidationDossier QRO input/output、evidence refs、lineage 和 Compiler IR validation refs；QRO/Compiler 仍只保存 formula hash、report hash、threshold/check summary hash、verdict 和 refs，不保存公式原文、raw return panel 或 raw audit payload。
- **对抗门**：测试覆盖缺 refs、unknown、未 accepted、带 violation、market mismatch、PIT timing 缺失、invalid tier 均不写 Graph/Compiler/Coverage partial record；成功路径可从 QRO/IR 回查 refs。
- **测试**：`tests/test_factor_desk_f2.py` **39 passed / 2 warnings**；factor/portfolio/goal/compiler/market-data/execution adjacent **197 passed / 2 warnings**；后端全量 **1824 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `713803ca`。边界：这是 factor audit ValidationDossier 的 refs-only MarketDataUse/PIT gate，不是 alpha approval、strategy promotion、portfolio construction、CI、线上或用户验收。

## 2026-06-27 · Factor preview and IC MarketDataUse/PIT gate（659eb22d）

- **取前沿**：factor audit/layered 已接 MarketDataUse/PIT gate，但 factor preview valid path、IC report 和 IC decay report 仍可直接读 panel，属于因子数据 consumer/report 旁路。
- **runtime/API**：新增 `_factor_preview_market_data_use_validation_refs`；`POST /api/factors/validate` 只在 compile/lookahead 通过、即将计算 IC 前要求 refs，compile/lookahead rejected preview 不读行情所以保持可无 refs；`GET /api/factors/{factor_id}/ic` 和 `/ic_decay` 通过 query `market_data_use_validation_refs` 接同一 gate。
- **refs contract**：Preview ValidationDossier QRO input/output、evidence refs、lineage 和 Compiler IR validation refs 写入 deduped refs；IC/decay report 返回体回显 refs。QRO/Compiler 仍只保存 refs/hash/count，不复制公式原文、raw IC、return panel 或 raw data。
- **对抗门**：测试覆盖 valid preview 缺 refs 422 且不写 Graph/Compiler/Coverage partial record，IC/decay 缺 refs 422 且不写新增 partial record，compile/lookahead rejected preview 仍不要求 refs。
- **测试**：`tests/test_factor_desk_f2.py` **41 passed / 2 warnings**；factor/portfolio/goal/compiler/market-data/execution adjacent **199 passed / 2 warnings**；后端全量 **1826 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `659eb22d`。边界：这是 factor preview/IC report 的 refs-only MarketDataUse/PIT gate，不是 alpha approval、factor registration、strategy promotion、CI、线上或用户验收。

## 2026-06-27 · Factor correlation MarketDataUse/PIT gate（f2722491）

- **取前沿**：preview valid IC、IC/IC decay、audit 和 layered backtest 已接 MarketDataUse/PIT gate，但 `GET /api/factors/correlation` 仍可直接读 panel 并生成 matrix，属于因子报告/数据 consumer 旁路。
- **runtime/API**：`factors_correlation` query 增加 `market_data_use_validation_refs`，在 pair selection 和 `correlation_matrix(...)` 前调用 `_factor_market_data_use_validation_refs`；refs 必须已记录、accepted、无 violation，use_context 必须是 backtest/confirmatory_validation，且 DatasetSemantics timing refs、Instrument/Capability market coverage 和 Capability backtest permission 通过。
- **report contract**：成功响应回显 deduped refs；失败路径 422，不写 Graph/Compiler/Coverage partial record。该 endpoint 仍只是 correlation report，不升级为 alpha approval 或 strategy promotion。
- **对抗门**：测试覆盖缺 refs fail-closed 和成功路径 refs 回显。
- **测试**：`tests/test_factor_desk_f2.py` **42 passed / 2 warnings**；factor/portfolio/goal/compiler/market-data/execution adjacent **200 passed / 2 warnings**；后端全量 **1827 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `f2722491`。边界：这是 factor correlation report 的 refs-only MarketDataUse/PIT gate，不是 alpha approval、strategy promotion、portfolio construction、CI、线上或用户验收。

## 2026-06-27 · Direct run report MarketDataUse/PIT gate（b7651d50）

- **取前沿**：Agent `report.generate` 已接 MarketDataUse/PIT gate，但 direct RunVerdictCard HTTP endpoints 仍可绕过 Agent tool schema，直接按 `run_id` 投影 verdict / overfit / cost / monthly heatmap。
- **runtime/API**：新增 `_run_report_market_data_use_validation_refs`；`GET /api/runs/{run_id}/verdict`、`/overfit`、`/cost-sensitivity`、`/monthly-heatmap` 都要求 query `market_data_use_validation_refs`。endpoint 先从 run manifest 取 market，再在调用 projector 前要求 refs 已记录、accepted、无 violation，use_context 为 backtest/confirmatory_validation，且 DatasetSemantics timing refs、Instrument/Capability market coverage 和 Capability backtest permission 通过。
- **report contract**：成功响应回显 deduped refs；缺 refs 422 且不调用任何 report projector。missing run 仍保持 404。
- **对抗门**：测试 monkeypatch 四个 projector，确认缺 refs 时无调用；成功路径断言 refs 回显。
- **测试**：`tests/test_run_verdict_card.py` **16 passed / 2 warnings**；run-report/Agent/DS/Goal/MarketData/Execution adjacent **179 passed / 2 warnings**；后端全量 **1828 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `b7651d50`。边界：这是 direct run report 的 refs-only MarketDataUse/PIT gate，不是 RDP formal package、alpha approval、strategy promotion、CI、线上或用户验收。

## 2026-06-27 · Agent backtest.run existing-run MarketDataUse/PIT gate（73209378）

- **取前沿**：`backtest.run` 无 run_id 的 strategy synthesis 分支已强制 MarketDataUse refs，direct run report endpoints 也已加门；但 `backtest.run` 传已有 `run_id` 时仍直接投影 verdict/overfit 摘要，绕过 handler 实际 refs 校验。
- **runtime/tool**：existing-run branch 在 `project_verdict` / `project_overfit` 前调用 `_market_data_use_validation_refs(..., operation="backtest.run existing run projection", require_dataset_timing=True, allowed_use_contexts=(backtest, confirmatory_validation))`。
- **summary contract**：成功响应回显 refs；缺 refs 返回 `no_write=true`，不调用 projector。新合成回测主路径仍由 `_synth_and_promote` 原有 gate 负责。
- **对抗门**：测试 monkeypatch projector，确认缺 refs 不投影；成功 path 只调用 verdict/overfit 并回显 refs。
- **测试**：`tests/test_agent_business_tools_a4.py` **33 passed / 2 warnings**；Agent/DS/run-report/Goal/MarketData/Execution adjacent **181 passed / 2 warnings**；`tests/test_model_governance.py` **31 passed / 2 warnings**（修正 raw-payload 泄漏断言用裸 `"1.5"` 误撞时间戳的测试误报；runtime 未变）；后端全量 **1830 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `73209378`。边界：这是 Agent existing-run summary 的 refs-only MarketDataUse/PIT gate，不是新回测、RDP formal package、strategy promotion、CI、线上或用户验收。

## 2026-06-27 · Agent backtest.run synthesis PIT timing gate（499980c8）

- **取前沿**：`4b6f55dc` 已让 Agent `backtest.run` synthesis 分支要求 accepted/no-violation MarketDataUse refs，但没有要求 DatasetSemantics timing refs；这是实际回测入口，不能停在 refs-only accepted 状态。
- **runtime/tool**：`_synth_and_promote` 调 `_market_data_use_validation_refs` 时开启 `require_dataset_timing=True`，并限制 use_context 为 `strategy_builder_backtest` / `backtest` / `confirmatory_validation`。
- **gate contract**：缺 refs、unknown/rejected/violation refs、缺 DatasetSemantics timing refs 都在 LLM/codegen/sample/sandbox/promote 前 no-write；成功路径仍返回 refs。
- **测试替身**：DS-1、DS-2 和 delivery slice fake registry 补 `dataset()` timing refs；delivery slice 与 DS2 fake use_context 同步为正式 `backtest`。
- **测试**：`tests/test_ds1_run_id_spine.py` **16 passed**；`tests/test_ds2_strategy_goal_persist.py` **8 passed / 2 warnings**；Agent/DS/Chat/run-report/Goal/MarketData adjacent **145 passed / 2 warnings**；后端全量 **1831 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `499980c8`。边界：这是 Agent strategy synthesis 的 refs-only PIT gate，不是完整 strategy assembly injection、真实 provider 实网连通、CI、线上或用户验收。

## 2026-06-27 · Research Asset RAG local dense vector index（5f8d8f7c）

- **取前沿**：TRACE §5 仍把 `dense embedding/vector DB` 列为待实现；已有 `/api/research-os/rag/vector_search` 是 token-count sparse cosine，不能冒充 dense embedding 或 vector DB。
- **runtime/API**：`ResearchAssetRAGIndex` 新增 `AssetRAGDenseVector`、`local_hash_dense_v1` deterministic dense embedding、`dense_vector_search` 和 `dense_vectors()`；`PersistentResearchAssetRAGIndex` 在 document add 后追加 `dense_embedding_indexed` JSONL 事件，replay 时恢复 dense vectors，旧 document-only 历史仍可补建内存 vector。
- **Agent/API contract**：新增 `POST /api/research-os/rag/dense_vector_search`，返回 `embedding_model_ref`、hits 和 agent usage ids；Agent Shell `rag_search=dense` 走同一 dense index。权限过滤、candidate-context 角色、plaintext secret guard 和 Agent source/version usage 账本不变。
- **测试**：RAG focused **12 passed / 2 warnings**；RAG/Document/Agent adjacent **99 passed / 7 warnings**；后端全量 **1832 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `5f8d8f7c`。边界：这是本地 deterministic dense vector index，不是语义 embedding 模型、外部 embedding provider、生产级 vector DB、跨 registry/provider/scheduler 自动同步、CI、线上或用户验收。

## 2026-06-27 · Methodology CPCV/conformal/TCA calculators（d3983386）

- **取前沿**：`b6bf792c` 已有 ValidationDepthRecord refs gate，但 CPCV/conformal/TCA 仍只能手填 refs，没有 producer。
- **runtime/API**：新增 `CPCVCalculatorRecord`、`ConformalCalculatorRecord`、`TCACalculatorRecord` 与 `PersistentMethodologyCalculatorRegistry`；新增 `/api/research-os/methodology/cpcv`、`/conformal`、`/tca`。成功路径计算 refs/hash/摘要并写 `methodology_calculators.jsonl`；summary 返回 calculator totals 与摘要。
- **honesty contract**：计算使用 raw fold/calibration/gross-return arrays，但 JSONL 不保存这些 raw arrays，只保存 sample/count/mean/threshold/cost summary 和 `source_hash`；silent mock、短 fold、短 calibration、非法 alpha、缺 cost refs、负成本均 no-write。
- **测试**：methodology focused **16 passed / 2 warnings**；methodology/goal/compiler/spine/trust/RDP adjacent **82 passed / 2 warnings**；后端全量 **1835 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `d3983386`。边界：这是本地 calculator producer，不是完整 CPCV path enumeration、walk-forward scheduler、真实 broker/venue fault drill、完整 validation dossier UI、CI、线上或用户验收。

## 2026-06-27 · RDP trust release gate management UI（1058c62d）

- **取前沿**：`e9c58149` 已让 RDP local publish 必须引用已登记 trust gate，但 RDP export desk 仍只能手填 `trust_release_ref`，用户不能在同一发布面查看、创建或选择 gate。
- **前端 UI/API**：`RDPExportPanel` 启动读取 `/api/research-os/trust/summary`，展示 release gate 总数和 gate refs；新增七字段 Record gate 表单，提交 `{ release_gate }` 到 `/api/research-os/trust/release_gates`；已有 gate 可点击 Use 填入 publish `trust_release_ref`。
- **对抗门**：缺任一 required ref 时前端显示错误且不调用 release gate 后端；创建成功后刷新 summary 并填入返回的 `release_ref`；既有 materialize/bundle/attest/archive/publish 流程保持，publish 仍要求非空 `trust_release_ref` 和 source-run integrity。
- **测试**：`RDPExportPanel.test.tsx` **10 passed**；frontend full **28 files / 311 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `1058c62d`。边界：这是本地 release gate 记录/选择 UI，不是自动压力测试生成器、专家工作流、外部 release、CI release、线上发布或用户验收。

## 2026-06-27 · Methodology validation dossier UI（33a8a56e）

- **取前沿**：`b6bf792c` 已有 ValidationDepthRecord registry/API，`d3983386` 已有 CPCV/conformal/TCA calculator producers，但研究执行台仍没有 §10 方法学验证操作面。
- **前端 UI/API**：新增 `MethodologyValidationPanel`；Agent Workbench 增加 `Methodology` tab 并标记 Backend。面板读取 `/api/research-os/methodology/summary`，展示 validation-depth 与 CPCV/conformal/TCA calculator 摘要；可提交 `/cpcv`、`/conformal`、`/tca` calculator inputs，也可提交 `{ validation_depth: ... }` 写 ValidationDepthRecord refs/verdict/责任边界。
- **对抗门**：CPCV 缺 fold values 时前端阻断且不打后端；calculator summary 不展示 raw fold/calibration/gross-return series；ValidationDepthRecord payload 强制 `silent_mock_fallback_used=false` 并按后端 schema 包装。
- **测试**：`MethodologyValidationPanel.test.tsx` **4 passed**；agent-workbench/RAG/RDP/methodology scoped **4 files / 61 tests passed**；frontend full **29 files / 315 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `33a8a56e`。边界：这是现有方法学 backend records 的 UI，不是真实 broker/venue fault drill、fault/recovery runner、monitor/promotion 自动 producer、CI 或线上验收。

## 2026-06-27 · Methodology runtime drill producer API and UI（d3efc139）

- **取前沿**：ValidationDepthRecord 已要求 fault injection / recovery drill refs，Methodology UI 也可手填 refs，但没有 producer 生成这些 refs。
- **runtime/API**：新增 `RuntimeDrillRecord`、`validate_runtime_drill()`、`record_runtime_drill()` 和 `PersistentMethodologyRuntimeDrillRegistry`；新增 `/api/research-os/methodology/runtime_drills`，summary 返回 `runtime_drill_total` 和 `runtime_drills` 摘要。
- **前端 UI**：Methodology tab 新增 Runtime drills 表单；提交成功后刷新 summary，并把返回的 `fault_injection_ref` / `recovery_drill_ref` 回填到 ValidationDepthRecord draft。
- **对抗门**：`drill_mode` 只允许 simulation/paper/testnet；live/production/unknown mode、guard mismatch、silent mock fallback 都拒绝且 no-write；summary 不暴露 raw log / traceback。
- **测试**：methodology focused **19 passed / 2 warnings**；methodology/goal/compiler/spine/trust/RDP adjacent **85 passed / 2 warnings**；后端全量 **1838 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`MethodologyValidationPanel.test.tsx` **5 passed**；agent-workbench/RAG/RDP/methodology scoped **4 files / 62 tests passed**；frontend full **29 files / 316 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `d3efc139`。边界：这是 safe-mode producer，不是真实 broker/venue API、venue-native fault injection、真钱/实盘故障演练、CI 或线上验收。

## 2026-06-27 · Trust release check producer API and RDP UI（a8e03245）

- **取前沿**：RDP export desk 已能查看/创建 Trust Release Gate，但 gate 所需六类检查 refs 仍只能手填，缺受控 producer 生成 `check_ref`。
- **runtime/API**：新增 `TrustReleaseCheckRecord`、`validate_trust_release_check()`、`record_trust_release_check()` 与 `PersistentTrustReleaseCheckRegistry`；新增 `/api/research-os/trust/release_checks`，summary 返回 `release_check_total` 与 `release_checks`。
- **前端 UI**：RDP export desk 新增 release checks 列表和 Record check 表单；提交成功后刷新 trust summary，并把返回的 `check_ref` 回填到对应 release gate draft 字段。
- **对抗门**：unknown `check_kind`、expected/observed behavior mismatch、缺 evidence/validation refs、silent mock fallback 均拒绝且 no-write；前端缺 required refs 时不调用 release check 后端。
- **测试**：trust focused **16 passed / 2 warnings**；RDP publish focused **8 passed / 2 warnings**；trust/RDP adjacent **24 passed / 2 warnings**；后端全量 **1841 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`RDPExportPanel.test.tsx` **12 passed**；agent-workbench/RAG/RDP/methodology scoped **4 files / 64 tests passed**；frontend full **29 files / 318 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `a8e03245`。边界：这是 refs producer 和本地 UI，不是真实外部专家工作流、自动压力测试 runner、CI release、线上或用户验收。

## 2026-06-27 · Trust disclosure registry API and workbench UI（4c8e476b）

- **取前沿**：TrustLayer 已有 trust claim、functional independence、user autonomy validators，但这些 disclosure 只能在测试里存在，没有 runtime registry/API/UI。
- **runtime/API**：新增 `PersistentTrustDisclosureRegistry`，同一 JSONL 记录 `trust_claim_recorded`、`functional_independence_disclosure_recorded`、`user_autonomy_recorded`；新增 `/api/research-os/trust/claims`、`/independence_disclosures`、`/user_autonomy`，并把三类 totals/records 接入 trust summary。
- **前端 UI**：Agent Workbench 新增 `Trust` tab；`TrustDisclosurePanel` 展示三类 disclosure summary，并能记录 trust claim、independence disclosure 和 user autonomy。
- **对抗门**：strong claim 缺 evidence refs、虚假 organizational independence、agent made final choice 均 fail-closed；前端 strong claim 缺 evidence refs 不打后端。
- **测试**：trust focused **19 passed / 2 warnings**；trust/RDP/coverage adjacent **40 passed / 2 warnings**；后端全量 **1844 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`TrustDisclosurePanel.test.tsx` **2 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 66 tests passed**；frontend full **30 files / 320 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）。
- **落档**：新增 done 卡 `4c8e476b`。边界：这是 disclosure runtime surface 和本地 UI，不是真实外部专家工作流、组织流程系统、CI release、线上或用户验收。

## 2026-06-27 · Trust release check suite producer API and RDP UI（bab2b148）

- **取前沿**：单条 release check producer 已存在，但 release gate 仍靠逐条手填六类 check refs；这不等于自动压力测试 runner，也不能伪装外部专家或 CI release。
- **runtime/API**：新增 `record_trust_release_check_suite()`，要求 anti-flattery、multi-turn、expert veto、weakness collapse、mock honesty、cold-start honesty 六类 check 全覆盖且无重复；每条 check 复用单条 validator，最后生成 matching `TrustReleaseGateRecord`。新增 `/api/research-os/trust/release_check_suites`，成功时写 6 checks + 1 gate。
- **前端 UI**：RDP export desk 新增 release check suite JSON array 表单；提交成功后刷新 trust summary、填 `trust_release_ref`，并把 returned release gate 写回 gate draft。
- **对抗门**：suite 缺 kind、重复 kind、坏 JSON、silent mock、behavior mismatch 或缺 refs 均 fail-closed；后端缺项/重复项测试断言 check/gate registry 不写 partial record。
- **测试**：trust focused **22 passed / 2 warnings**；trust/RDP/coverage adjacent **43 passed / 2 warnings**；后端全量 **1847 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`RDPExportPanel.test.tsx` **14 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 68 tests passed**；frontend full **30 files / 322 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `bab2b148`。边界：这是本地 refs-only suite producer，不是真实外部专家工作流、自动 agent 压力测试 runner、CI release、线上或用户验收。

## 2026-06-27 · External expert review registry API and Trust UI（a952f63e）

- **取前沿**：Trust release gate/check/suite 已能记录本地 release refs，但还没有独立的 external expert review evidence surface。不能把 agent critic 或本地用户判断伪装成外部专家。
- **runtime/API**：新增 `ExternalExpertReviewRecord`、`validate_external_expert_review()`、`record_external_expert_review()` 和 `external_expert_review_from_dict()`；`PersistentTrustDisclosureRegistry` 新增 `external_expert_review_recorded` event replay。新增 `/api/research-os/trust/expert_reviews`，summary 返回 `expert_review_total` 与 `expert_reviews`。
- **前端 UI**：Trust tab 新增 expert review summary 和 Record expert review 表单，提交 release/reviewer/independence/artifact/protocol/verdict/evidence/veto/signature refs。
- **对抗门**：agent/system/self/generic user reviewer、approved 缺 signed attestation、vetoed/needs_revision 缺 reason、缺 evidence refs、silent mock fallback 均拒绝；前端 approved 缺 signed attestation 不打后端。
- **测试**：trust focused **24 passed / 2 warnings**；trust/RDP/coverage adjacent **45 passed / 2 warnings**；后端全量 **1849 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`TrustDisclosurePanel.test.tsx` **3 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 69 tests passed**；frontend full **30 files / 323 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️）；`git diff --check` PASS。
- **落档**：新增 done 卡 `a952f63e`。边界：这是 external expert review evidence record，不是真实外部专家账号体系、电子签平台、组织审批流、CI release、线上或用户验收。

## 2026-06-27 · Trust pressure runner producer API and RDP UI（f94d20a0）

- **取前沿**：release check suite 已能一次生成 six checks + one gate，但仍要求人工提交 suite；TRACE §13/§17 的自动 agent 压力测试 runner 缺口还没被 runtime record 覆盖。不能把本地 refs-only suite 伪装成 CI、真实 autonomous agent 或外部专家流程。
- **runtime/API**：新增 `TrustPressureRunRecord`、`validate_trust_pressure_run()`、`record_trust_pressure_run()`、`trust_pressure_run_record_from_dict()` 和 `PersistentTrustPressureRunRegistry`；新增 `/api/research-os/trust/pressure_runs`，成功时复用 suite producer 写 6 checks + 1 gate，再写 1 条 pressure run record；trust summary 返回 `pressure_run_total` 与 `pressure_runs`。
- **前端 UI**：RDP export desk 新增 pressure runs summary/list 和 scenarios JSON 表单；提交成功后刷新 trust summary，填 `trust_release_ref`，并把 returned release gate 写回 gate draft。
- **对抗门**：runner mode 只允许 `local_deterministic` / `test_harness`；六类 scenario 必须全覆盖且无重复；expected/observed behavior mismatch、outcome flags、缺 runner/scenario evidence refs、缺 validation refs、silent mock 或失败 scenario 均 fail-closed；失败路径不写 check/gate/run partial record。
- **测试**：trust focused **30 passed / 2 warnings**；trust/RDP/coverage adjacent **51 passed / 2 warnings**；后端全量 **1855 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`RDPExportPanel.test.tsx` **16 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 71 tests passed**；frontend full **30 files / 325 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️；244 cards）；`git diff --check` PASS。
- **落档**：新增 done 卡 `f94d20a0`。边界：这是本地 deterministic/test harness pressure runner record，不是真实 autonomous agent 长程执行、CI release、外部专家审批、线上发布或用户验收。

## 2026-06-27 · Trust release approval workflow registry API and RDP UI（acd267d1）

- **取前沿**：Trust pressure run 和 external expert review 已能分别登记，但还没有把 release gate + pressure run + expert review 合成为一条 release approval evidence record。当前不能把本地 record 说成 CI、外部组织流程或线上发布。
- **runtime/API**：新增 `TrustReleaseApprovalRecord`、`validate_trust_release_approval()`、`record_trust_release_approval()`、`trust_release_approval_record_from_dict()` 和 `PersistentTrustReleaseApprovalRegistry`；新增 `/api/research-os/trust/release_approvals`，summary 返回 `release_approval_total` 与 `release_approvals`。
- **前端 UI**：RDP export desk 新增 release approval summary/list、expert review ref list 和 Record approval 表单；可提交 release gate、pressure run、expert review、artifact、protocol、evidence、signature、blocker refs。
- **对抗门**：API 从现有 registries 查 gate/pressure/expert；unknown ref、release mismatch、pressure run gate mismatch、approved 缺签名、approved 带 residual blocker、needs_revision/blocked 缺 blocker、approved 引用非 approved expert review、silent mock 均 fail-closed；失败不写 approval record。
- **测试**：trust focused **36 passed / 2 warnings**；trust/RDP/coverage adjacent **57 passed / 2 warnings**；后端全量 **1861 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`RDPExportPanel.test.tsx` **18 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 73 tests passed**；frontend full **30 files / 327 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️；245 cards）；`git diff --check` PASS。
- **落档**：新增 done 卡 `acd267d1`。边界：这是本地 release approval evidence record，不是 RDP publish hard gate 已升级、CI release、外部组织审批流、线上发布或用户验收。

## 2026-06-27 · RDP local publish requires trust release approval ref（44ca5ea7）

- **取前沿**：release approval record 已存在，但 RDP local publish 仍只要求 `trust_release_ref`，approval 证据没有约束发布动作。
- **runtime/API**：`RDPPackagePublishRecord` 新增 `trust_release_approval_ref`，新 publish hash 纳入该 ref；`RDPLocalPackagePublisher.publish()` 缺 approval ref 拒绝；旧 publication JSONL 缺字段仍可 replay。RDP publish API 要求 `trust_release_approval_ref` 已登记、release 匹配且 verdict=approved。
- **前端 UI**：RDP export desk publish 表单新增 `trust_release_approval_ref`；approval create/use 成功回填 publish approval ref；publish response/results 回显 approval ref。
- **对抗门**：缺 approval ref、unknown approval ref、approval release mismatch、non-approved approval 均 422 且不写 publication；source bundle、source-run integrity、external channel 等既有 publish 坏门仍按原错误触发。
- **测试**：RDP publish focused **8 passed / 2 warnings**；trust/RDP/coverage adjacent **57 passed / 2 warnings**；后端全量 **1861 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`RDPExportPanel.test.tsx` **19 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 74 tests passed**；frontend full **30 files / 328 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️；246 cards）；`git diff --check` PASS。
- **落档**：新增 done 卡 `44ca5ea7`。边界：这是 local publish hard gate，不是外部 object store publish、CI release、live deployment runner、线上发布或用户验收。

## 2026-06-27 · RDP external publish attestation proof（770982f3）

- **取前沿**：RDP local publish 已被 trust release approval hard gate 约束，但 §13/§17 仍没有 external publish/release proof 记录面；不能把 `channel` 改成外部 URL 直接绕过 local publish hard gate。
- **runtime/API**：新增 `RDPExternalPublicationProofRecord` 与 `PersistentRDPExternalPublicationProofStore`；新增 `/api/research-os/rdp/manifests/{package_id}/external_publications`，必须引用已存在 local publication hash，并重新校验 trust release gate、approved release approval、archive hash 和 secret-free external pointer。record 只保存 external URI digest、immutable pointer ref、destination allowlist ref、local publish hash、archive hash、release/approval refs 与 evidence refs，不保存 raw external URI。
- **前端 UI**：RDP export desk 新增 external publication proof 表单；必须先有 local publication 结果，否则前端阻断且不打后端；结果区回显 `external_proof_hash`、`external_uri_digest` 和 immutable pointer ref。
- **对抗门**：缺 local publication hash、unknown local publish hash、archive hash mismatch、unknown approval、secret-bearing external URI 均 422 且不写 proof；`/publish` 仍只支持 `local_registry`。
- **测试**：RDP publish/external proof focused **11 passed / 2 warnings**；trust/RDP/coverage adjacent **60 passed / 2 warnings**；后端全量 **1864 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`RDPExportPanel.test.tsx` **20 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 75 tests passed**；frontend full **30 files / 329 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️；247 cards）；assigned-vs-done duplicate check 无输出；`git diff --check` PASS。
- **落档**：新增 done 卡 `770982f3`。边界：这是 refs-only external publication proof，不是真实 object-store 上传、CI release、live deployment runner、线上发布、线上可用性证明或用户验收。

## 2026-06-28 · External expert identity and signed attestation verification（4143d1cc）

- **取前沿**：`a952f63e` 已能记录 external expert review refs，`acd267d1` release approval 也能引用 expert review，但 `signed_attestation_ref` 仍只是字符串；不能把“有 ref”说成“detached signature 已验证”。
- **runtime/API**：新增 `ExternalReviewerIdentityRecord`、`ExternalExpertSignatureRecord` 与 `PersistentExternalExpertSignatureRegistry`。identity 记录 Ed25519 public key、public key fingerprint、identity provider ref、independence/evidence refs；signature record 绑定已登记 `ExternalExpertReviewRecord`，对 canonical payload 验证 detached Ed25519 signature 后写 `verified_signature_ref` / `verification_hash`。
- **后端接口**：新增 `/api/research-os/trust/expert_identities` 与 `/api/research-os/trust/expert_signatures`；trust summary 增加 `expert_identity_total`、`expert_identities`、`expert_signature_total`、`expert_signatures`，只回显 refs/fingerprint/hash，不回显 private key、raw payload 或 `signature_b64`。
- **前端 UI**：Trust tab 新增 expert identity 和 expert signature verification 表单；缺 required field 时前端阻断，不打后端。
- **对抗门**：agent/system/self/user reviewer、invalid public key、signature reviewer mismatch、bad signature、secret/private-key marker 均 fail-closed；坏 signature 不写 partial record。
- **测试**：trust/RDP/goal adjacent **63 passed / 2 warnings**；后端全量 **1867 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`TrustDisclosurePanel.test.tsx` **4 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 76 tests passed**；frontend full **30 files / 330 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️；248 cards）；assigned-vs-done duplicate check 无输出；`git diff --check` PASS。
- **落档**：新增 done 卡 `4143d1cc`。边界：这是本地 external reviewer identity registry 与 detached Ed25519 signature verification，不是外部身份平台、KYC、SSO、电子签 SaaS、组织审批流、CI、线上发布或用户验收。

## 2026-06-28 · RDP CI release attestation proof（b793f3a7）

- **取前沿**：`770982f3` 已能登记 refs-only external publication proof，但 §17 仍没有 CI release attestation 记录面；不能把外部 proof 或本地 publish 说成 CI workflow/test release 已证明。
- **runtime/API**：新增 `RDPCIReleaseAttestationRecord` 与 `PersistentRDPCIReleaseAttestationStore`；新增 `/api/research-os/rdp/manifests/{package_id}/ci_release_attestations`。endpoint 先查已登记 local publication、external proof、trust release gate 和 approved release approval，再写 CI attestation record。
- **honesty contract**：record 只保存 CI system/workflow/run/commit refs、artifact digest、test report refs/hash、build log digest、required check refs、evidence refs 和 `attestation_hash`；不保存 raw CI log、raw artifact payload、secret 或 token。`ci_status != passed`、failed/skipped/missing checks、archive mismatch、approval mismatch、secret-bearing refs 均 422 且不写 partial record。
- **前端 UI**：RDP export desk 新增 CI release attestation 表单；必须先有 local publication 和 external publication proof，否则前端阻断，不打后端。
- **测试**：RDP publish/CI focused **14 passed / 2 warnings**；trust/RDP/goal adjacent **66 passed / 2 warnings**；后端全量 **1870 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`RDPExportPanel.test.tsx` **21 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 77 tests passed**；frontend full **30 files / 331 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）。
- **落档**：新增 done 卡 `b793f3a7`。边界：这是 refs/hash-only CI release attestation，不是真实 CI provider adapter、GitHub Actions/GitLab/CircleCI 凭据接入、外部 workflow 触发、deployment runner、线上健康检查、线上发布或用户验收。

## 2026-06-28 · RDP CI release runner seam（6ec698e4）

- **取前沿**：`b793f3a7` 已有 refs/hash-only CI release attestation record，但 §17 仍缺 CI provider adapter / external workflow trigger 的 fail-closed 接缝；不能把手工 attestation 当成 runner 已跑。
- **runtime/API**：新增 configurable `RDP_CI_RELEASE_RUNNER`，默认 `None`；新增 `/api/research-os/rdp/manifests/{package_id}/ci_release_attestations/run`。endpoint 先查真实 manifest、local publication、external proof、trust release gate 和 approved release approval，再把 refs/hash-only request 交给 runner；runner 成功结果复用 `PersistentRDPCIReleaseAttestationStore.record_attestation()` 写同一类 CI attestation。
- **honesty contract**：未配置 runner 422 且不写记录；runner result 只允许 refs/hash/status/check/evidence 字段，`raw_ci_log`、raw artifact payload、stdout/stderr、token/secret key、plaintext secret、非标量 ref payload、failed/skipped/missing checks 均 fail-closed。
- **前端 UI**：RDP export desk 新增 `Run CI` 按钮；手工 `Record CI attestation` 仍要求完整 CI refs/hash，`Run CI` 只要求 runner request 所需 refs，允许 `ci_run_ref`、artifact digest、test report、build log digest 先为空，由 runner result 产出。
- **测试**：RDP publish/CI focused **20 passed / 2 warnings**；trust/RDP/goal adjacent **72 passed / 2 warnings**；后端全量 **1876 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`RDPExportPanel.test.tsx` **22 passed**；agent-workbench/RAG/RDP/methodology/trust scoped **5 files / 77 tests passed**；frontend full **30 files / 332 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️；250 cards）；assigned-vs-done duplicate check 无输出；`git diff --check` PASS。
- **落档**：新增 done 卡 `6ec698e4`。边界：这是本地 configurable runner seam 和 fake-runner 验证，不是真实 GitHub Actions/GitLab/CircleCI credential adapter、真实外部 workflow execution、object-store uploader、deployment runner、线上发布、线上健康检查或用户验收。

## 2026-06-28 · Settings Stooq public market-data connector（76898af4）

- **取前沿**：§4/§11 已有 Tushare token、Binance public 和 Generic REST YAML adapter，但 TRACE 仍保留“更多真实 connector/provider adapter 覆盖”；Stooq public daily CSV 是一个 no-auth、read-only、非执行路径的安全切入点。
- **runtime/API**：新增 `StooqConnector`，实现 describe、health check 和 daily OHLCV CSV fetch；注册到 connector registry；Settings connector inference 可识别 `stooq`，继续使用现有 `SettingsRegistryDataConnectorConnectionChecker` / `SettingsRegistryDataConnectorIngestionRunner`，不新增并行 Settings API。
- **对抗门**：只支持 daily interval，非 daily interval 拒绝；Settings check/run 不需要 secret，`secret_refs=[]`，IngestionSkillUpdate 使用 `secret:none:stooq` 占位；测试钉住不回显 plaintext token/API key。
- **测试**：onboarding focused **48 passed / 2 warnings**；onboarding/asset-lifecycle/market-data/goal adjacent **86 passed / 2 warnings**；后端全量 **1879 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️；251 cards）；assigned-vs-done duplicate check 无输出；`git diff --check` PASS。
- **落档**：新增 done 卡 `76898af4`。边界：这是 Stooq public daily CSV no-auth connector 和 Settings registry-backed check/run 接线，不是全资产自动同步、scheduler crawling、商业授权自动判断、live venue permission check、下游自动注入、生产 health monitor、线上验收或用户验收。

## 2026-06-28 · Settings Stooq public connector preset UI（29a670fe）

- **取前沿**：`76898af4` 已接 Stooq no-auth connector 后端，但 Settings 用户仍要手工构造 DataSourceAsset/IngestionSkill metadata；§4 完整 Settings/connection wizard 仍缺具体 no-auth preset。
- **前端 UI**：`/settings/security` Data Connectors panel 新增 Stooq public daily bars 表单，可登记 source_ref、skill_id、symbol、output dataset、schema mapping、PIT ref、source URL、rate limit、start/end；提交只走既有 `data_sources` 和 `ingestion_skills` endpoints。
- **对抗门**：payload 固定 `connector_name=stooq`、`auth_mode=none`、`source_type=public_csv`、`secret_refs=[]`；登记动作不触发 `data_connector_checks` 或 `ingestion_skill_runs`，不提供 secret 表单，也不回显 api_key/token/sk-live。
- **测试**：`SettingsSecurityPage.test.tsx` **1 file / 5 tests passed**；frontend full **30 files / 333 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `29a670fe`。边界：这是 no-auth public provider metadata preset UI，不是真实连接测试、ingestion run、scheduler crawling、商业授权自动判断、全资产同步、生产 health monitor、线上验收或用户验收。

## 2026-06-28 · Settings Binance public connector preset UI（224e9865）

- **取前沿**：`a6dcb50f` 已接 Binance public no-auth backend adapter，Settings summary 也能渲染 existing Binance skill，但用户仍要手工登记 DataSourceAsset/IngestionSkill metadata；本卡补 Spot/USDM public REST preset。
- **前端 UI**：`/settings/security` Data Connectors panel 新增 Binance public REST 表单，可登记 source_ref、skill_id、symbol、market、interval、output dataset、schema mapping、PIT ref、source URL、rate limit、start/end；提交只走既有 `data_sources` 和 `ingestion_skills` endpoints。
- **对抗门**：Spot/USDM market 映射到 `binance_rest_spot` / `binance_rest_usdm`；payload 固定 `auth_mode=none`、`source_type=public_api`、`secret_refs=[]`；登记动作不触发 `data_connector_checks` 或 `ingestion_skill_runs`，不提供 secret 表单，也不回显 api_key/token/sk-live。
- **测试**：`SettingsSecurityPage.test.tsx` **1 file / 6 tests passed**；frontend full **30 files / 334 tests passed**；frontend build **PASS**（保留既有 chunk-size warning）。
- **落档**：新增 done 卡 `224e9865`。边界：这是 Binance public provider metadata preset UI，不是真实 Binance REST 实网连通、ingestion run、testnet/live trading、scheduler crawling、生产 health monitor、线上验收或用户验收。

## 2026-06-28 · RDP external publication uploader seam（9ea22292）

- **取前沿**：`770982f3` 已有手工 refs-only external publication proof，`6ec698e4` 已有 CI release runner seam；§17 仍缺 object-store publication uploader 的受控接缝。不能把手工 proof 当成 uploader 已运行，也不能接真实 cloud SDK/credential 越过 Secrets/CI/账号治理。
- **runtime/API**：新增 configurable `RDP_EXTERNAL_PUBLICATION_UPLOADER`，默认 `None`；新增 `/api/research-os/rdp/manifests/{package_id}/external_publications/run`。endpoint 先查真实 manifest、local publication、trust release gate、approved release approval 和 archive hash，再把 refs/hash-only request 交给 uploader；成功结果复用 `PersistentRDPExternalPublicationProofStore.record_proof_from_digest()` 写同一类 external proof。
- **honesty contract**：未配置 uploader 422 且不写记录；uploader request 不含 raw external URI、published archive path、raw artifact 或 secret；uploader result 只允许 external channel、external URI digest、immutable pointer ref、destination allowlist ref、publication status 和 evidence refs，raw URI、stdout/stderr、token/secret、plaintext secret、非标量 ref payload 和非 `published` status 均 fail-closed。
- **前端 UI**：RDP export desk 新增 `Run external publish` 按钮；手工 `Record external proof` 仍要求 raw external URI 并由后端只保存 digest，runner path 不提交 `external_uri`。
- **测试**：RDP publish/uploader focused **26 passed / 2 warnings**；trust/RDP/goal adjacent **78 passed / 2 warnings**；后端全量 **1885 passed / 13 skipped / 283 warnings**；`compileall app/backend/app` PASS；`RDPExportPanel.test.tsx` **24 passed**；frontend full **30 files / 336 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）；`validate_dev` PASS（49 ✅ / 0 ❌ / 0 ⚠️；254 cards）；assigned-vs-done duplicate check 无输出；`git diff --check` PASS。
- **落档**：新增 done 卡 `9ea22292`。边界：这是本地 configurable uploader seam 和 fake-uploader 验证，不是真实 S3/GCS/R2 credential adapter、云端实际上传、CI release、deployment runner、线上发布、线上健康检查或用户验收。

## 2026-06-28 · RDP deployment runner seam（bf94fd9d）

- **取前沿**：`d5f0ff41` 已有手工 deployment attestation record，`d14e2309` 已让 live publish 要求 deployment attestation 覆盖 `deployment_refs`，但 §17 仍缺 deployment runner 接缝。不能把手工 attestation 当成部署动作已执行，也不能直接接真实 Vercel/Fly/Kubernetes/SSH 凭据越过 Secrets、CI 和线上变更治理。
- **runtime/API**：新增 configurable `RDP_DEPLOYMENT_RUNNER`，默认 `None`；新增 `/api/research-os/rdp/manifests/{package_id}/deployment_attestations/run`。endpoint 先查真实 manifest 和声明的 deployment ref，再把 refs/hash-only request 交给 runner；成功结果复用 `PersistentRDPDeploymentAttestationStore.record_attestation()` 写同一类 deployment attestation。
- **record 兼容**：`RDPDeploymentAttestationRecord` 增加 `deployment_event_ref`、`deployment_artifact_digest` 和 `evidence_refs`；无新增字段的 v1 记录保持原 hash/replay payload，新 runner 记录写 v2 attestation。
- **honesty contract**：未配置 runner 422 且不写记录；runner request 不含 raw deployment payload、本地 package path、kubeconfig、SSH key、token、stdout/stderr 或 secret；runner result 只允许 deployment ref/status、deployment event/artifact digest、monitor/rollback/retire/evidence refs，raw manifest/package payload、stdout/stderr、token/secret、plaintext secret、非标量 ref payload 和非 `deployed` status 均 fail-closed。
- **测试**：`compileall app/backend/app` PASS；RDP deployment focused **14 passed / 2 warnings**；RDP/goal adjacent **98 passed / 2 warnings**；后端全量 **1892 passed / 13 skipped / 283 warnings**。
- **落档**：新增 done 卡 `bf94fd9d`。边界：这是本地 configurable deployment runner seam 和 fake-runner 验证，不是真实 Vercel/Fly/Render/Kubernetes/SSH credential adapter、production rollout、线上健康检查、rollback 执行、线上发布或用户验收。

## 2026-06-28 · RDP deployment health and rollback proof registry（378bb0b9）

- **取前沿**：`bf94fd9d` 已能把 configurable deployment runner result 写成 deployment attestation，但 GOAL §17 的 `Deployment / monitor / rollback / retire 清单` 仍没有 post-deploy health/rollback proof 记录面。不能把 deployment attestation 说成线上健康检查或 rollback 已证明。
- **runtime/API**：新增 `RDPDeploymentHealthCheckRecord` 与 `PersistentRDPDeploymentHealthCheckStore`，JSONL append-only/replay；新增 `/api/research-os/rdp/manifests/{package_id}/deployment_health_checks`。endpoint 先查 manifest 和已登记 deployment attestation，再写 refs/hash-only health/rollback proof。
- **honesty contract**：record 只保存 `deployment_attestation_hash`、health refs、monitor refs、rollback plan/readiness/drill refs、retire plan ref、evidence refs 和 proof hash；不保存 raw health response、raw log、provider payload、token 或 secret。
- **对抗门**：缺/unknown deployment attestation hash、hash 不属于 package、deployment ref mismatch、`health_status != healthy`、缺 health/monitor/rollback/retire/evidence refs、raw response/log/provider payload、token/secret 或 plaintext secret 均 422，且不写 partial record。
- **测试**：`compileall app/backend/app` PASS；RDP deployment focused **22 passed / 2 warnings**；RDP/goal adjacent **106 passed / 2 warnings**；后端全量 **1900 passed / 13 skipped / 283 warnings**。
- **落档**：新增 done 卡 `378bb0b9`。边界：这是本地 refs/hash-only deployment health/rollback proof registry，不是真实 provider health API、prod traffic probe、real canary、rollback execution、production rollout、线上发布或用户验收。

## 2026-06-28 · RDP deployment proof UI wiring（60c601d2）

- **取前沿**：`bf94fd9d` 和 `378bb0b9` 已有 backend API，但 RDP export desk 还不能操作 deployment attestation、runner 和 post-deploy health/rollback proof。
- **前端 UI**：`RDPExportPanel` 新增 deployment proof 区，包含 `Record deployment`、`Run deployment` 和 `Record health proof`；结果面显示 deployment attestation hash、deployment event/artifact digest、deployment health proof hash、health status、rollback drill ref 和 retire plan ref。
- **对抗门**：runner payload 只提交 `deployment_ref` 和 `source_bundle_required`；不提交 raw deployment payload、本地 package path、kubeconfig、SSH key、token 或 secret。health proof 缺 deployment attestation、health refs、monitor refs、rollback/retire/evidence refs 时前端阻断，不打后端。
- **测试**：`RDPExportPanel.test.tsx` **1 file / 26 tests passed**；frontend full **30 files / 338 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）。
- **落档**：新增 done 卡 `60c601d2`。边界：这是 RDP export desk 的本地 UI 接线，不是真实 deployment provider、真实线上健康检查、real canary、rollback execution、production rollout、线上发布或用户验收。

## 2026-06-28 · Settings LLM provider health snapshot registry（2cd2ed24）

- **取前沿**：GOAL §4 要求 Settings 监控 provider health 与 quota status。现有 `LLMProviderRecord` 只有当前字段，`/api/llm/test` 是临时测试，没有可 replay 的 provider health/quota snapshot 账本。
- **runtime/API**：新增 `LLMProviderHealthSnapshotRecord`、`validate_llm_provider_health_snapshot()` 和 `PersistentOnboardingRegistry.record_llm_provider_health_snapshot()`；新增 `/api/research-os/settings/llm_provider_health_snapshots`，settings summary 回显 `llm_provider_health_snapshot_total` 与 snapshot 列表。
- **对抗门**：snapshot 必须绑定已登记 LLMProvider 和 provider.auth_refs 里的 Settings SecretRef；revoked auth ref、unknown provider、bad health/quota status、负 latency、raw response/prompt/output/provider payload、token/secret 或 plaintext secret 均 fail-closed。
- **honesty contract**：record 只保存 snapshot/provider/auth refs、health/quota status、latency、response hash、capability/evidence refs 和 snapshot hash；服务端重算 hash，不保存 raw provider response、prompt、output、token 或 secret。
- **测试**：`compileall app/backend/app` PASS；onboarding focused **51 passed / 2 warnings**；LLM/onboarding/market-data/goal/compiler adjacent **154 passed / 2 warnings**；后端全量 **1903 passed / 13 skipped / 283 warnings**。
- **落档**：新增 done 卡 `2cd2ed24`。边界：这是本地 provider health/quota snapshot 账本，不是真实 provider polling scheduler、OAuth/device-code/account auth、生产 keyring/HSM、外部 billing/quota API、CI 或线上监控。

## 2026-06-28 · Settings LLM provider health snapshot UI（a5dc9306）

- **取前沿**：`2cd2ed24` 已有 provider health/quota snapshot registry/API，但 `/settings/llm` 只能配置和测试 provider，不能把 health/quota 证据写回 Settings 账本。
- **前端 UI**：`LLMSettingsPage` 读取 `/api/research-os/settings/summary` 的 `llm_providers` / `llm_provider_health_snapshots`；新增 Provider health snapshot 面板，基于已登记 provider/auth_ref 提交 snapshot。
- **对抗门**：缺 Settings provider/auth_ref 时前端禁用并阻断提交；成功 payload 只含 status/quota/latency/checker/response_hash/capability_refs/evidence_refs/error_code，不提交 raw response、prompt/output、token、secret 或 API key；后端 422 时显示失败，不假装记录成功。
- **测试**：`LLMSettingsPage.test.tsx` **1 file / 12 tests passed**；frontend full **30 files / 341 tests passed**；frontend build **PASS**（保留既有 Vite chunk-size warning）。
- **落档**：新增 done 卡 `a5dc9306`。边界：这是本地 Settings wizard UI 接线，不是真实 provider polling scheduler、OAuth/device-code/account auth、外部 billing/quota API、生产 keystore backend、CI 或线上监控。

## 2026-06-28 · GOAL §0-§17 runtime gap matrix

- **启动复核**：当前分支 `fix-u2-synth`，HEAD `5d55de3`，`origin/main` `70bacab`，`HEAD...origin/main = 0 167`；工作区有大量既有脏改，未切分支/未 reset/未 commit。
- **证据读取**：已读 `/Users/wzy/.codex/AGENTS.md`、项目 `CLAUDE.md`、`dev/exec/HANDOFF.md`、`dev/.identity`、`dev/TEAM.md`、`dev/GOAL.md`、`dev/RULES.md`、`dev/RULES.project.md`、`dev/decisions/_NAV.md`、`dev/decisions/dreaminate/DECISIONS.md`、`dev/experience/dreaminate/experience.md`；`dev/research/findings/dreaminate/construction-map.md` 不存在。
- **矩阵结论**：新增 finding `dev/research/findings/dreaminate/goal-0-17-gap-matrix-2026-06-28.md`。本地 `goal_entrypoint_coverage.jsonl` 有 **577 rows**，但全是 `entry_source=api` 且只覆盖 `§0/§1/§7/§8`，`claims_full_product_entrypoint=0`；full §0-§17 和 all-entrypoints 仍是缺口。
- **落任务**：新增 active 卡 `2b1706f1`、`6bbfa5ac`、`9112dbc6`、`124d7c3a`、`564ccd82`、`7f4823d4`，分别覆盖 full section manifest、chat/agent_shell、canvas、IDE、scheduler、M1-M21 real platform manifest。
- **验证**：`python -m pytest app/backend/tests/test_funnel_hooks.py::test_register_emits_user_registered -q` **1 passed / 2 warnings**；`validate_dev` 在新增矩阵前为 **49 ✅ / 0 ❌ / 0 ⚠️**。新增卡后需重新 build board/dev-map/validate。
- **边界**：这是矩阵和任务路由，不是 §0-§17 完成证明；未做 CI、线上、真实 provider、用户验收。

## 2026-06-28 · GOAL §0-§17 full section coverage manifest hard gate（2b1706f1）

- **取前沿**：`validate_goal_coverage_manifest` 已能拒绝 contract-only full claim，但没有持久化 section coverage 账本，也无法回查 `entrypoint_wiring_refs` 是否真实存在。
- **runtime/API**：新增 `PersistentGoalSectionCoverageRegistry` 与 `goal_section_coverage_record_from_dict()`；新增 `/api/research-os/goal/section_coverage_records` 与 `/api/research-os/goal/section_coverage/summary`。
- **对抗门**：section record 必须有 contract/test/task/evidence refs；`full_entrypoint_wired=true` 必须有 `entrypoint_wiring_refs`；每个 wiring ref 必须能从 `PersistentGoalEntrypointCoverageRegistry` 回查，且 entrypoint record 必须覆盖同一 GOAL section。unknown ref、section mismatch、contract-only full claim 均 fail-closed。
- **测试**：`compileall app/backend/app` PASS；goal focused **17 passed / 2 warnings**；goal/platform/compiler/spine adjacent **55 passed / 2 warnings**；后端全量 **1907 passed / 13 skipped / 283 warnings**。
- **落档**：新增 done 卡 `2b1706f1`。边界：这是 full section coverage manifest 硬门，不是 chat/canvas/IDE/scheduler/agent_shell producer 本身，也不是 §0-§17 完成证明。

## 2026-06-28 · Chat / Agent Shell GOAL entrypoint coverage producer（6bbfa5ac）

- **取前沿**：GOAL gap matrix 显示 `goal_entrypoint_coverage.jsonl` 当前只证明 `entry_source=api`；chat / agent_shell 成功入口虽有 QRO/Graph command，但没有 Compiler IR/pass 与 GOAL entrypoint coverage。
- **runtime/API**：`AgentTurn` 增加 `compiler_ir_refs`、`compiler_pass_refs`、`entrypoint_coverage_refs`；新增 AgentRuntime turn coverage helper，把成功 turn 的 QRO/Research Graph command 编译成 Governed Compiler IR/pass 并写 GOAL entrypoint coverage。`/api/agent/chat`、workbench SSE、legacy non-stream chat 写 `entry_source=agent_shell|chat`；legacy stream 未经过 AgentRuntime，只创建 hash-only chat QRO 并写 `entry_source=chat` coverage。
- **对抗门**：缺 QRO/Graph refs 会 fail-closed 且不写 partial；silent mock fallback 被 coverage validator 拒绝且不写 compiler/coverage；coverage/IR/pass/QRO 只保存 refs/hash/count/status，不保存 raw user prompt、assistant text、tool payload、token 或 secret。
- **测试**：`compileall app/backend/app app/backend/tests/test_agent_runtime_research_graph.py app/backend/tests/test_chat_conversations.py` PASS；agent/chat focused **36 passed / 2 warnings**；goal/agent/chat/spine adjacent **66 passed / 2 warnings**；后端全量 **1910 passed / 13 skipped / 283 warnings**。
- **落档**：新增 done 卡 `6bbfa5ac`。边界：这是 chat / agent_shell entrypoint coverage producer，不是 canvas、IDE、scheduler producer；仍只覆盖 GOAL `§0/§1/§7/§8` entrypoint wiring，不是 §0-§17 full product implementation proof、CI、线上或用户验收。

## 2026-06-28 · Scheduler GOAL entrypoint coverage producer（564ccd82）

- **取前沿**：矩阵拆卡时 `entry_source=scheduler` 没有进入本地 audit 实证。复核代码后确认 weekly tick producer 已存在，不应重复造第二套 scheduler coverage。
- **runtime/API**：`_record_weekly_monitor_qro()` 记录 `QROType.OBSERVABLE` 和 `ResearchGraphCommand(source=EntrySource.SCHEDULER)`；`_compile_weekly_monitor_qro()` 记录 Governed Compiler IR/pass，并写 `entry_source=scheduler`、`entrypoint_ref=scheduler:monitor.weekly_tick` 的 GOAL entrypoint coverage。manual `/api/monitor/weekly_tick` 和 scheduled DAG result recorder 复用同一路径。
- **对抗门**：坏 observation / gate verdict observation 在写 QRO/Compiler/Coverage 前 422；QRO/IR/pass/coverage 只保存 refs/hash/count/status，不保存 raw factor id、cost drift report、action payload 或 secret。
- **测试**：`compileall app/backend/app/monitor app/backend/app/main.py` PASS；scheduler/goal focused **24 passed / 2 warnings**；后端全量 **1910 passed / 13 skipped / 283 warnings**。
- **落档**：新增 done 卡 `564ccd82`。边界：这是 weekly tick / scheduled producer 的核验落档，不是部署级长期 scheduler 运行证明、canvas、IDE、chat/agent_shell producer，也不是 §0-§17 full product implementation proof。

## 2026-06-28 · IDE GOAL entrypoint coverage producer（124d7c3a）

- **取前沿**：代码里已存在 IDE save/run/promote/AI complete 的 QRO→Compiler→Coverage producer，但 `test_ide.py` 只测 service/sandbox，没有 API-level coverage registry 断言。
- **runtime/API**：IDE save/run/promote/AI complete 成功路径分别写 `ide:strategy.save`、`ide:strategy.run`、`ide:run.promote`、`ide:ai_complete` 的 QRO、Research Graph command、Compiler IR/pass 和 GOAL entrypoint coverage，`entry_source=ide`。
- **对抗门**：unknown MarketDataUse ref 在写 QRO/Compiler/Coverage 前 422；QRO/IR/pass/coverage 只保存 refs/hash/count/status，不保存 raw strategy code、description、LLM prompt、editor context、LLM output、token 或 secret。
- **测试**：`compileall app/backend/tests/test_ide.py app/backend/app/main.py` PASS；IDE/goal focused **43 passed / 2 warnings**。
- **落档**：新增 done 卡 `124d7c3a`。边界：这是 IDE producer 和测试补强，不是 canvas、scheduler、chat/agent_shell producer，也不是 §0-§17 full product implementation proof。

## 2026-06-28 · Canvas GOAL entrypoint coverage producer（9112dbc6）

- **取前沿**：Canvas 已有 canonical Graph command 与 QRO update 路径，但 canonical canvas 操作没有统一写 Governed Compiler IR/pass 与 GOAL entrypoint coverage。
- **runtime/API**：新增 `_record_canvas_goal_entrypoint_coverage()`；`canvas_asset_mutations`、`canvas_layouts`、`canvas_parameter_values`、`patch_applications` 成功路径返回 `compiler_ir_ref`、`compiler_pass_ref`、`entrypoint_coverage_ref`。entrypoints 分别是 `canvas:asset_mutation`、`canvas:layout`、`canvas:parameter_value`、`canvas:graph_patch_application`。
- **旧入口边界**：旧 audit-only `/api/research-os/graph/canvas_mutations` 继续只写 canonical mutation command，不伪造 QRO 或 coverage。
- **对抗门**：raw canvas payload 在写账前 422；QRO/IR/pass/coverage 只保存 refs/hash/count/status，不保存 raw value、layout projection、patch body、token 或 secret。
- **测试**：`compileall app/backend/app/main.py app/backend/tests/test_research_graph_persistence.py` PASS；canvas/goal focused **45 passed / 2 warnings**；canvas/spine/strategy-console adjacent **83 passed / 2 warnings**。
- **落档**：新增 done 卡 `9112dbc6`。边界：这是 canonical canvas QRO update/layout/parameter/patch producer，不是 §0-§17 full product implementation proof、CI、线上或用户验收。

## 2026-06-28 · M1-M21 real platform coverage manifest registry（7f4823d4）

- **取前沿**：`validate_platform_coverage()` 只能证明 M1-M21 结构齐，不区分 synthetic/test fixture refs，也没有可 replay 的 manifest registry/API。
- **runtime/API**：新增 `PersistentPlatformCoverageRegistry`、dict materializer、real-manifest validator 和 JSONL append-only replay；新增 `/api/research-os/platform/coverage_manifest` 与 `/api/research-os/platform/coverage_summary`，summary 按 M1-M21 顺序输出 rows。
- **对抗门**：common refs 必须是 registry/audit-shaped QRO、Research Graph、lifecycle、governance、RAG、Mathematical Spine refs；evidence/specific refs 拒绝 synthetic、fixture、test-only、`:001` 占位；M14 必须有 LLM gateway、routing policy、credential pool、theory binding；M21 必须有 mock label 和 asset category。非对象 records 422，不静默跳过。
- **测试**：`compileall app/backend/app/research_os/platform_coverage.py app/backend/app/research_os/__init__.py app/backend/app/main.py app/backend/tests/test_platform_coverage.py` PASS；platform focused **11 passed / 2 warnings**；platform+goal coverage **28 passed / 2 warnings**；后端全量 **1918 passed / 13 skipped / 283 warnings**。
- **落档**：新增 done 卡 `7f4823d4`。边界：这是本地 platform coverage manifest registry/API，不是 CI、线上、真实 provider、生产 audit 数据已全量登记或用户验收。

## 2026-06-28 · GOAL §0-§17 local integration proof

- **任务状态**：本轮拆出的 GOAL §0-§17 follow-up 卡 `2b1706f1`、`6bbfa5ac`、`564ccd82`、`124d7c3a`、`9112dbc6`、`7f4823d4` 均在 `dev/tasks/dreaminate/done/`；dreaminate active 任务检查无输出。
- **dev 校验**：`build_board.py`、`build_dev_map.py` 已刷新；`validate_dev.py` **49 ✅ / 0 ❌ / 0 ⚠️**（265 卡）。
- **全量验证**：后端全量 **1918 passed / 13 skipped / 283 warnings**；前端 `npm run test:run` **30 files / 341 tests passed**；前端 `npm run build` PASS（保留 Vite chunk-size warning）；`git diff --check` 无输出。
- **边界**：这是本地 runtime/dev/test proof；未 commit、未 push、未跑 CI、未部署线上，生产 audit 数据是否全量登记和用户验收均未声明。
