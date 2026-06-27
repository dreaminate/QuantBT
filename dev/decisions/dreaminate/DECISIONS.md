# 机构级 Agent OS · R1–R29 决策记录（二轮建设基线）

Status: 用户 2026-06-16 读完 36 份研究 dossier 后逐条拍板 · 本文件是二轮"研究→可落地设计→接线"的基线
依据：`docs/institutional-agent-os/research/01..36-*.md`（每条 dossier 的 §7 对抗核查为准）

> **导航**：§0 产品哲学（统御所有决策）→ §1–§8 按主题分类的 R1–R29 + P 管太宽放松项 → `## D-XXXX` 专项决策（append-only，按日期、锁定不改既往）。
> **查法**：按主题看 §；查某条 grep `R<编号>` 或 `D-<名>`（如 `D-T024`）；最新决策看文件末尾。（只描述结构与查法，不枚举每条——枚举=会漂。）

<!-- 格式·防跑偏 | 追加型(append-only,锁定不改既往)：新决策追加到末尾。每条照此：
## D-XXXX · <标题>（<日期> 拍板）  - **决策**：<选了什么>  - **依据**：<研究/讨论>  - **状态**：confirmed -->

---

## 0. 产品哲学（用户原则，统御所有决策）

**处处必须最专业最严谨，绝不因"单用户 / 低频"砍任何治理动作；用户有困难就派 agent 辅助，而不是降低标准。** 闸门对所有人完全一致、最严。

### 0.1 关键分界：严谨 vs 管太宽

- **研究侧旋钮**（用户在自己的策略 / 自己的钱上调的东西：α、门槛档、重调次数、要不要填假设卡才探索）→ **不锁、不禁**。只做：① honest-N 透明计数（调几次都算进去、门槛随之抬高）② 显示通缩后真相 ③ 防呆挡离谱值。然后用户自己决定。
- **执行侧 / 不可逆 / 外部可见边界**（实盘下单、动钱、加杠杆、提币、A股 paper-only、密钥、留出集触碰留痕）→ **硬锁**，防灾难。
- 分界线一句话：**"不让你藏试验"（诚信底线，硬）≠ "不让你跑试验"（研究自由，放）。**

### 0.2 元发现（读 dossier 的方法）

第一遍前沿研究系统性夸大/张冠李戴/杜撰精度，全靠**对抗核查（§7）逐条揪出反转**——这本身验证了环节12（验证官：生成方与验证方硬分离、异模型、有权 block）的架构。**读这批 dossier 先读 §7，标题与 §5 乐观推荐按 §7 打折。**

### 0.3 R7↔R28/R29 的化解（单用户怎么"全建机器又不表演"）

全套机构机器照建（R28/R29）；"生成≠验证"的真分离靠**独立验证官 agent（异模型/异种子/异数据切片，环节12）**——它是单用户场景的"第二双眼睛"。唯一要诚实：别宣称"组织独立验证"，说"异模型独立挑战 agent"。

---

## 1. 统计地基与方法学

- **R1 = C** · honest-N：探索自由，**晋级到可下注结论时强制显式提交试验账本**（与 R8 是同一本账）。依据：§14/15/23——N 在 agent 自搜索下近乎不可数（鸡生蛋循环），C 是"agent 出工程"与"honest-N"唯一不互斥解。
- **R2 = B** · 多证据三角（DSR/PBO/bootstrap CI 同向才放行）+ 通缩区间；红绿灯**必须一键下钻**暴露有效N/试验聚类/适用域空洞。依据：§13/23/33——单点红绿灯本身是"解释剧场/伪精确"。
- **R3 = B（v2 按 0.1 放松，见 P1）** · `t>3` 不硬编，做"谨慎/标准/宽松"三档。~~预注册锁定~~ → **可自由切换，切换计入 honest-N 并显示门槛抬高，不强制锁定**。依据：§05/11/14/15/23/27——Chen 证 t-hurdle 弱识别（90%CI 横跨 0–3.0），无共识。
- **R4 = B** · CPCV 作"更强默认"与 walk-forward 双轨；DL 退化 WF+少数折。依据：§14/16/23/24/27/28——CPCV 仅合成(Heston)环境占优，真实市场未确立。
- **R5 = B** · 守门器（DSR/PBO/honest-N）自身模型风险对用户明示。依据：§23/24——SR11-7 要求"对验证模型做验证"。

## 2. 监管与治理定位

- **R6 = B** · 改锚 **NIST AI RMF + 自建治理**，"有效挑战"借概念**不宣称合规**。依据：§03/11/12/22/24/25——SR11-7 已被 SR26-2 取代，且 SR26-2 明确把 generative/agentic AI 划出范围。
- **R7 = B** · 真强制只在交易所侧硬边界；左侧证据治理**诚实承认非组织独立**，分离靠独立验证 agent（见 0.3）。依据：§07/12/22/32/33——单用户 approver≠creator 是表演。
- **R8 = B** · 双通道审批：探索轻量 / 确证（上实盘、动钱、加杠杆、删历史）重门可挂数天。依据：§04/06——93% 权限弹窗被点同意，门会退化橡皮图章。

## 3. 安全与自治边界

- **R9 = C** · 按"资产类别×是否实盘×可逆性"分级威胁模型：A股 paper 放宽、加密实盘严格（禁会话内摄入不可信内容，新闻/RAG 进无工具子 agent 只回传结构化结果 + 回传值做合理性区间检测）。依据：§06——Rule of Two 与中低频"吃新闻+持币+下单"天然冲突。
- **R10 = 确认** · 密钥不进 LLM（后端 key broker 短时凭证）、API key 关提币+IP白名单、下单 HMAC 防重放、**护栏接所有执行路径含中继/桥**（M17 教训）。依据：§06/21。
- **R11 = B** · 重放读已落盘工件、不重跑 LLM；时间敏感部分自托管钉版本。依据：§02——托管 API temp=0 也不保证逐位可复现。
- **R12 = B** · 留出集隔离降级为"约定 + 防篡改证据 + 一次性消费(触碰留痕)"，诚实标注防自欺非防恶意。依据：§01-design/07——本地开放落盘无真访问控制边界。

## 4. 资产 / 市场范围

- **R13 = B** · A股**禁空头侧、纯多头弱腿**，不外推美股多空 alpha。依据：§30——A股做空近乎不可行（融券池小/T+1/涨跌停），而 PEAD/新闻 alpha 集中在空头腿。
- **R14 = B** · A股统计门本地化（涨跌停→成交概率、停牌按有效交易日折算 embargo、样本不足判"证据不足"）。依据：§15/19/36——T+1/涨跌停破坏 DSR/PSR 平稳假设。
- **R15 = B** · 加密拥挤护栏数据不足 → 只定性警示、禁自动减仓。依据：§27——加密缺做空兴趣/机构持仓数据 + wash-trading 污染。
- **R16 = B（v2 按 0.1 放松，见 P3）** · 加密短样本：~~禁用 DSR 单点裁决~~ → **照常显示 DSR 但醒目标注"短样本失真、不可作单点裁决"**（show+caveat 非 hide）。依据：§15/23——加密短样本+幸存者偏差使偏度峰度修正失效。

## 5. 因子轨（三库 + 组合 + 生成）

- **R17 = B** · **DL/ML 本体进模型注册表、输出登记为信号进因子库；三库（算术/ML/DL）保持纯净**。把"三纯库"精确化为"两层 + 信号契约"（锚 Qlib/MLflow/Feast；v3 `backtest_bridge` 输出≈该契约）。依据：§26——把 `.pt` 当因子塞库是范畴错误。
- **R18 = 确认** · 信号层做模型集成（强制 OOF+purge+embargo 防 stacking 泄露）/ 策略层做 meta-allocation；默认组合器等权/HRP，学习型 stacking 须自证增量。依据：§28——forecast-combination puzzle：简单等权常胜。
- **R19** · 暴力遍历=廉价候选生成器；① 生成器/守门器严格解耦 ② 守门指标绝不进生成 fitness（否则验证集泄露）③ 候选先过经济先验+去重 ④ 每条计入 R8 账本。定位"诚实-N 守门人"非"挖矿机"。依据：§23。
- **R20 = C** · **LLM 引导因子生成暂缓**（证据乱+对中文/加密零验证，先做实三纯库）。依据：§29——参数记忆泄露 DSR 抓不到、prompt 约束系统性失效、外部效度未测。
- **R21 = 对** · 因子退役+去重是状态机一等流程；去重用收益序列相关聚类（防换等价公式绕过），阈值二轮定。依据：§27。

## 6. 信号层

- **R22 = 确认** · 新闻/事件/链上/A股基本面（中低频，不碰 HFT）；LLM 情绪配 FinBERT 基线 + 自托管避免外发敏感头条；外部信号默认打选择偏误折扣。**爬虫团队对接口已就绪**：产 `ts×symbol` 宽表 → `register_official_dataset`。依据：§30。
- **R23 = A（v2 按 0.1 放松）** · 知识 agent 给建议 + 合理区间防呆。~~α 一旦裁决即锁定~~ → **不锁 α**（用户自己的事，honest-N 已透明吸收回调，管太宽）。依据：§17 + 用户原则。

## 7. 产品 / 信任 / 冷启动 / 个性化

- **R24 = B** · 信任 UI 北极星 = **恰当依赖**非信任最大化（live 无 per-case ground truth，用代理指标）。依据：§13/33——"更透明=更信任"被证伪、解释抬高过度依赖。
- **R25 = 确认（澄清）** · 闸门对所有人**一套最严**；披露=全证据对所有人可下钻、默认分层只为可读、**弱点风险一律一等呈现绝不淡化**（撤回"证据强时做轻"）。
- **R26 = 确认** · **专业知识优先于用户 wishful thinking**：可证伪经济错觉不迎合可 override，纯主观约束（只做加密/能受30%回撤）仍尊重；证伪话术由用户定性为**非投资建议**（教育性专业知识服务）。依据：§35。
- **R27 = 确认** · 冷启动 N=1 剔除 DSR、用 PSR/MinTRL + 隐性 champion + 显式"证据不足"，标"先验断言未经数据检验"；个性化只动呈现层不动治理。依据：§36——N=1 时 DSR 退化为 PSR、范畴误用。

## 8. 工程比例性（用户 override 为"全量最严"）

- **R28 = A** · **全库双时态 + 企业级谱系**（不分级，用 agent 降用户负担）。代价（用户已接受）：全库 as-of 查询的 compute/延迟、谱系大工程。⚠️ 落地优先解 Tushare `f_ann_date` 脏数据 → 落 first-seen known_at。依据：§03/09（§09 原建议分级，用户 override）。
- **R29 = 全保留** · 不砍任何机构治理动作（高频能用低频也能）。依据：用户原则 override §22/32 的裁剪建议。

---

## P · 管太宽放松项（**已生效** · 用户 2026-06-16 随 R1–R29 拍板,非备选 / 是已决变更 · 统一原则见 0.1）

- **P1**（动 R3 + §15/27/28）：门槛档/聚类口径**不强制预注册锁定** → 可切换 + 计入 honest-N + 显示门槛抬高。
- **P2**（动 §05/08）：**假设卡不挡探索性回测** → 探索自由（标 exploratory），仅晋级 confirmatory 结论时才冻结假设卡（= R1 自然延伸）。
- **P3**（动 R16）：加密短样本**不禁用 DSR**，改 show + caveat。

## D-T021 · 安全门生产接线（relay 默认门模板 + fail 模式）

> 2026-06-18，AskUserQuestion 工具内部错误丢答 + 用户「继续」→ 采纳推荐保守档；皆 deny-by-default 安全方向，可改默认。

- **D-T021-1** follower 生产门 `symbol_whitelist = {signal.symbol}`：跟单作用域=所跟 master 当下交易标的，余皆 deny。
- **D-T021-2** 单笔名义额上限 = `follower.per_order_max_usdt`（**既有字段**，默认 100；≤0 兜底 100，绝不放无限额）——无需新字段/迁移。
- **D-T021-3** fail 模式：**CRYPTO_LIVE 真钱 → fail-closed**（防重放台缺失即拒）；CRYPTO_TESTNET/PAPER → fail-open（假钱不过度工程化、不破坏既有 testnet 基线）。
- 杠杆 = `follower.max_leverage`（None/≤0→1.0 保守）；现货无杠杆 → 显式 1x；turnover = notional×max(max_positions,1)。
- 放宽门走既有 T-019 审批门（单用户 approver≠creator 防自欺 + 审计）。
- 市价单名义额：从 venue 侧 mark（可信）核，绝不读 signal/extra 自报价；取不到 mark → deny-by-default。

---

## 下一步

二轮：挑一簇做"研究→可落地设计 + 代码接线(file:line) + 测试要点"。候选优先级：**A 脊柱/内核**（确定性内核+谱系+假设卡）或 **E 因子轨**（三纯库+信号契约+暴力遍历守门）。

---

## D-CLOSEOUT · 收口计划（2026-06-18 用户拍板）

> 脊柱 8 块全建并验证、安全门生产接线全链闭合（T-012~T-022，已合并 main，全量 1001 测试绿）后进入"收口"。用户读 STATE 全 gap + 本文件后逐条拍板：

- **排序 = 1A 价值密度混合**：第一波 簇A 脊柱收尾 → 第二波 C「M7–M8 组合上多证据三角」+ D「数据双时态地基」（把*每 run 可信*做实）→ B 因子轨 → E 信任层 / F 可上线 交织。
- **范围 = 2B 分两轮**：本轮收口 = 脊柱收尾 + 选定主线核心价值 + 跑通小额实盘；剩余纵深列入下一轮 BOARD。
- **节奏 = 3C 最大自驱**：簇/波次内连续自驱，只在 ①触 RULES §5 红线 ②本文件（R1–R29/S/P/D）未覆盖的新岔路 ③波次完成 才停下找用户。
- **首波交付 = 4B 先看卡再说**：簇A 三张卡（T-023 内核 jobs/agent 接线 · T-024 假设卡↔Run 集成 · T-025 非-relay live 路径审计接门）先写 TASK.md 给用户过目，点头才动代码。
- **实盘交棒（硬）**：mainnet 100U 一周实盘（簇F）由用户**亲自执行**，agent 不动钱/不下真单；agent 备齐 testnet 矩阵/SafeKey/ladder/killswitch/监控并验证绿后交棒按键。
- 簇 A–F 内容映射见 STATE「收口计划」表 + BOARD。

---

## D-T024 · exploratory↔confirmatory 判定信号来源（2026-06-19 用户拍板）

> 收口簇A 前置岔路;DECISIONS 此前未覆盖「谁判一个 run 是探索还是可下注确认」。

- **决策 = (a)+(c) 组合**:用户在 `StrategyGoal` 向导里**显式声明 / 晋级** `layer`(exploratory→confirmatory);`execution_mode=paper/live` 仅作**辅助校验**(声明 exploratory 却要走真钱执行 → 告警/拒,**绝不自动晋级** —— 晋级永远是用户的显式动作)。
- **依据**:P2 / R1 —— 探索自由、仅可下注结论才冻结;判定权归用户经济判断,系统不替用户认定「这是可下注的」。
- **落地**:`Run.layer` 字段 + StrategyGoal 声明入口;promote 端点据 `layer` 决定是否触发假设卡闸门(exploratory 跳过 P2)。
- **状态**:confirmed。承接卡:T-024。

## D-T025 · 急停 kill/emergency 的 fail 模式（2026-06-19 用户拍板）

> 收口簇A 前置岔路;D-T021-3 只覆盖 relay **下新单** fail-closed,未覆盖**风险降低**动作(平仓/撤单)的 fail 模式。

- **决策 = (a) 平仓本体 fail-open**:`emergency_close_all` / `kill_switch` 的平仓、撤单等**风险降低**动作**永不被门挡**(门坏也要能救命平仓);护栏放在**「谁能按按钮」** = trigger 端点加人在环 **IP+密码**二次鉴权(复用 `security/mainnet_guards.py`),**不**放在「能不能平仓」。
- **依据**:急停优先级高于策略门;「下新单」(fail-closed 防灾)与「救命平仓」(fail-open 保命)是两个相反方向,分开处理。
- **诚实限界**:fail-open 平仓仍受**交易所侧**可用性约束(本地保证「不被本地门挡」,不保证交易所一定成交)—— 与 I-001 TCB 天花板同源。
- **状态**:confirmed。承接卡:T-025。

## D-T024-OOS · 一次性 OOS 与运营滚动验证集分两套（2026-06-19 用户拍板,闭 I-005）

- **决策 = B1 分两套独立切片**:「晋级确认用的一次性 OOS」(碰一次即出裁决、消费即焚)与上线后「运营滚动验证集」(walk-forward 反复消费近段)**用两套独立数据切片**,文档钉死各自消费口径。
- **依据**:同一切片会被运营滚动消费悄悄破坏「只碰一次」承诺 → 自欺;属诚信底线(不让你藏试验),**不限制任何研究动作**(你想跑什么策略不受影响)。
- **诚实分界**:治理侧硬要求,不碰研究自由。
- **状态**:confirmed。承接卡:T-024。闭合 ISSUES I-005。

## D-T024-FALS · 可证伪启发式 confidence=low = 硬透明 + 软决定（2026-06-19 用户拍板）

> 纠正 T-024 初稿 T1「low→FreezeRejected 硬挡」—— 那是「管太宽」(让会误判的启发式硬挡用户晋级),违反 §0.1 / R26。

- **决策**:晋级 confirmatory 时可证伪性启发式判 `low`(疑似套套逻辑/弱机制)→ **硬透明**(醒目警示 + `needs_human_review=True` + 记进 honest-N 账本 + **绝不渲染成绿/可信**)**+ 软决定**(用户显式 acknowledge/override 后仍可 freeze,override 留痕进卡),**启发式绝不自动硬挡晋级**。
- **依据**:§0.1 研究侧旋钮不锁 + R26 可证伪经济错觉不迎合**可 override**;启发式自身会误判(T1「绝不退化为字数门」),让机器替用户做研究判断=管太宽。
- **保留的硬边界**:(a) **结构空机制**(FalsifiableTriplet 三必填字段空白)仍**硬拒** freeze —— 那是结构完整性、非质量启发式;(b) **验证官**(T-020 异模型对**结论本身**的独立挑战)**有权 block** —— 与措辞启发式两回事,保留。
- **诚实分界**:透明与记账 = 硬(系统锁);晋不晋级 = 软(用户定)。
- **状态**:confirmed。承接卡:T-024。

## D-T025-DIY · GenericTradingVenue 接活做 DIY 策略（2026-06-19 用户拍板）

- **决策 = D2 接活**:`GenericTradingVenue`(审计时未实例化的死代码)**本卡接活**,纳入真钱执行面:实现 **OrderGuard.wrap + deny-by-default 白名单**,与既有 relay/lease 路径同一道门。
- **范围影响**:T-025 从「标死代码 + 加守护测试」升级为「真实现 wrap + 接门」,本卡工作量与对抗测试面增大(generic deny-by-default 从条件项变活测试)。
- **红线(执行侧硬锁)**:接活后任何 `place_order` 必经 OrderGuard、deny-by-default、CRYPTO_LIVE fail-closed —— 与四下单路径同判(M17/INV-2)。
- **状态**:confirmed。承接卡:T-025。

## D-PERM · agent 权限三态 + 权限轴⟂治理轴 + R25 呈现分层（2026-06-20 用户拍板）

> 用户引入 Claude Code 式权限范式（ask/auto/bypass）+ 双画像（小白/researcher），统一原 T-027「哪些动作 agent 自主」与 T-028「red 怎么呈现」为同一条权限轴。

- **决策 = 引入 agent 权限三态**（用户在客户端选）:`ask`（每个有副作用动作停下问）/ `auto`（无副作用自跑、动钱或发外部单才问）/ `bypass`（一路自跑）。
- **权限轴 ⟂ 治理轴（核心不变量）**:权限三态只调「agent 要不要停下问你」,绝不调「治理门要不要执行」。OrderGuard / 审批门 / 过拟合门 / 因子血统门任何模式都执行;`bypass` 只跳过确认 UI、不跳过治理门;真钱命门 bypass 也拦。
- **免门白名单 = 不发外部单的动作**:回测 + Paper（本地模拟、可重置、无外部副作用）→ agent 自主执行;Testnet（假钱但真发交易所、有外部副作用）→ 至少一次轻确认;Live → 重门。
- **默认止于模拟盘（用户 2026-06-20 纠正）**:agent 默认路径永远止于模拟盘,实盘是郑重的显式独立确认,agent 绝不把「直接实盘」作为默认或自动导向（即便 bypass）—— 与 R8 / live ladder「不可跳级」同线。
- **R25 呈现分层（细化非推翻）**:治理一套最严不变、弱点永远可见可下钻、绝不渲染成绿/可信（R25 不淡化保留）;可按权限模式/画像调的只是默认呈现+确认强度（red promote:ask=软确认+标记 / auto·bypass=只标记）。依据 R27「个性化只动呈现层不动治理」。
- **依据**:§0.1（研究侧旋钮不锁 / 执行侧硬锁）+ R8 双通道 + R25/R27。
- **状态**:confirmed。承接卡:T-027 / T-028 / T-035。

## D-SELFAPPROVE · 单人 self-approve 仅非真钱通道（2026-06-20 用户拍板）

> R7「单用户 approver≠creator 是表演」+ 代码自承单人场景护栏价值有限;给单人诚实降级路径,真钱绝不松。

- **决策 = 引入 self-approve,仅限非真钱**（回测/paper/testnet/A股模拟）:强制 cooling-off（二次确认 + 冷却期）+ 审计如实标 `self_approved=true`（绝不伪装双控）。
- **真钱硬双人（执行侧硬锁）**:CRYPTO_LIVE 真钱上线绝对保留 approver≠creator 硬双人,self-approve 永不触及真钱。
- **冷却时长 / 上线模式**:放客户端让用户自设（staging / production 两档）。
- **依据**:§0.1 + R7（诚实承认非组织独立）;self-approve 是「诚实降级」非「绕门」。
- **诚实分界**:非真钱单人降级 = 放;真钱双控 = 硬锁。
- **状态**:confirmed。承接卡:T-030。

## D-PROVENANCE · 实盘因子血统门 = 警告+知情确认（2026-06-20 用户拍板）

- **决策 = 上真钱线前校验因子血统**:逐一检查策略所用每个因子是否走完治理流程（假设卡→独立验证→审批）,只要有一个未过 → 上线前强制弹窗警告（列出未过因子）+ 知情确认后仍可上（用户自己的钱与判断,§0.1）。
- **不硬拦**:知情确认（acknowledge 留痕进审计）非死挡 —— 与 R26 / D-T024-FALS「硬透明 + 软决定」同范式。
- **依据**:用户 2026-06-20 提出;补强真钱保护,与 self-approve（D-SELFAPPROVE）、真钱双人并列。
- **状态**:confirmed。承接卡:T-034。

## D-LEVERAGE · 杠杆不设硬上限 + 真钱审批超时永远 default_reject（2026-06-20 用户拍板）

- **决策 = 杠杆可调、不设硬上限**:`leverage_cap` 从硬编码 3.0 改为用户可配,不钉系统硬上限（用户自己的钱与风险偏好,§0.1 研究/风险侧旋钮不锁,已讲清高杠杆爆仓代价）。
- **门不动**:杠杆放开数值不削弱执行侧不变量 —— 下单仍过 OrderGuard、杠杆仍须显式声明、deny-by-default 不变。
- **真钱审批超时铁律（执行侧硬锁,不可配）**:审批 SLA 时长可配,但涉真钱的审批超时永远 = default_reject,绝不允许配成超时自动放行（无人确认却动钱 = 灾难）。止损/降险类超时 default_allow 保留（救命）。
- **依据**:§0.1 分界（研究/风险偏好放 vs 执行侧硬锁）;用户 2026-06-20 拍板。
- **状态**:confirmed。承接卡:T-031。

## D-DESK-EPIC · Claude Design handoff 整套台前端实装（2026-06-21 用户拍板）

- **决策 = 三板**:① 流程:先开卡走正规流程,leader(dreaminate)自 mint uuid 自分配(不走 pool);② 深度:分期开齐覆盖完整路线的全套卡,P0 像素还原+mock → P1 接已有后端 → P2 补缺端点,做到完整(不停在 P0);③ 范围:整套台全做(策略台/因子台/Model台/模拟台/回测详情+裁决卡/Agent 窗口)。
- **架构 = 治理界面投影**:设计稿治理元素(Live只读/Fork/kill/validate/版本血缘/权限三态/晋级审批门/弱点一等)= GOAL §2 治理脊柱 + §6 信任层 + §7 M15「治理新页面」的 UI 投影;治理逻辑全在已建后端脊柱,台只投影不重造。DC→React 近 1:1(逻辑类→React class / renderVals→buildVM / sc-for→map / sc-if→&& / style-hover→CSS:hover / style="{{}}"→cssToObj)。
- **红线(承接卡对抗测试钉死)**:RunDetailPage 冻结(裁决卡新建旁挂不嵌入、不深色化、交互改写须停下问用户,RULES.project §10 / GOAL §0);权限轴⟂治理轴(bypass 绝不跳门,沿用 T-029 矩阵);默认止于模拟盘;弱点一等呈现(R25);裁决措辞禁可信/安全/排除过拟合(R7,走后端 _verdict_note);A股 live 下单永远拒。
- **卡结构**:epic cfb0fea9 + 17 子卡(地基 G1 d11d1426/G2 b9af7c82/G3 d5ea778c + 策略 S1 be3dc598/S2 9fd4f1a6 + 因子 F1 5e47b82f/F2 b106177f + Model M1 b2682edc/M2 4562d903 + 模拟 P1 9d5405ce/P2 79ebe273 + 回测裁决 R1 d93dc5a0/R2 e069d820 + Agent 补 A1 a75c4beb/A2 ca3ab3ec/A3 d41b167d/A4 b961f08b,关联现有 epic 3f5ed0b8 的 T-040~T-043)。A 类工程取舍 7 条 leader 已决(写回各卡 [已决]);B 类 2 条(F1 范围 / F2 audit 方法学)等用户拍板(state 待决岔路点名)。
- **依据**:用户 2026-06-21 提供 handoff bundle(quantbt-claude)+ 三板拍板;§0.1 分界(范围/方法学=用户判断→等拍;实现细节→leader 决)。
- **状态**:confirmed。承接卡:cfb0fea9(epic)+ 子卡;待拍清零后各自进实现。

## D-DESK-F1B · 因子台 §3 两骨干本期补 + 前端测试设施基建（2026-06-21 用户拍板「1走b、都做」）

- **F1=B 走 (b)**:因子台三纯库(算术/ML/DL 分库 + 信号契约,R17)+ 暴力遍历挖掘(生成/守门解耦、诚实-N,R16)**本期补**,handoff 无稿由 leader 按 GOAL §3 + factor_factory 直接设计实装(不经 Claude Design)。新立 **F3 a11e2aa5**(前端设计+实装)+ **F4 51271d38**(后端信号契约/挖掘守门引擎)承接;F1 仅还原 handoff 5 视图。
- **前端测试设施基建**:勘查发现 app/frontend 零测试设施(无 vitest/playwright、0 测试文件),所有前端卡对抗测试无处落地=违「门必抓」铁律。新立 **G0 e2de3d32**(vitest+RTL+对抗 harness),作 G1 及全部前端实装卡硬前置(G1 depends_on 加 G0)。
- **F2 方法学口径延后(F2=2)**:audit(honest-N 三档阈值 / Newey-West / 降级规则 / 文案经 R7)进 F2 实现时拍;底层 eval 原语(cscv_pbo/dsr/n_eff/bootstrap)已存在可复用,口径未拍不实装。
- **真值源入库**:handoff bundle → `docs/design/handoff/`;10 份理解报告 → `dev/research/findings/desk-handoff/`(防 /tmp 清)。
- **依据**:用户 2026-06-21「1走b、都做」;§0.1 分界(范围/方法学=用户判断、实现细节=leader 决)。
- **状态**:confirmed。epic cfb0fea9 子卡 17→20;唯一剩余待拍 = F2(b106177f)。承接卡:G0 / F3 / F4。

## D-F2-AUDIT · 因子 alpha 审查方法学口径（2026-06-21 用户拍板「全采纳，数值可调」）

- **决策（全采纳推荐）**:(a) honest-N 三档(谨慎/标准/宽松,R3):标准档=DSR 诚实 N_eff 通缩后 t>3、谨慎加严/宽松放松,用文献默认(Bailey-López de Prado DSR);(b) IC 显著性纳 Newey-West 自相关调整;(c) verdict 降级:全达标 consistent / 任一不达标 concern / 多个严重 blocked(对齐 R2 多证据三角,绝不单点);(d) 文案走 verifier._verdict_note,禁 R7 词,模板「证据[一致/存疑/不一致]+适用域+未验证项 N」。
- **数值可调（§0.1 研究侧旋钮）**:三档阈值 / N_eff 区间用户可配、不锁;调整计入 honest-N(门槛随之抬高)+ 显示通缩后真相 + 防呆挡离谱值。不硬编死值(与 R3 三档可切换同范式)。
- **依据**:用户 2026-06-21;GOAL §4 + R2/R3 + §0.1 分界(研究侧旋钮放、不锁)。
- **状态**:confirmed。承接卡:F2 b106177f(待拍清零,可进实现)。

## D-NAV-UNIFY · 导航收口:三 tab 合一 + 总览台 + 旧页搬台/退役（2026-06-22 用户拍板「a+b,必须诚实做完」）

- **决策 = 三板**:① 顶栏 Research/Workshop/Models 三 tab **合并为单一 Workshop**(落地总览台);② **新增「总览台」**(/overview,第 6 个全屏台)聚合查看类页(回测列表/对比分析/数据中心 + 策略索引作回测列表的卡片视图,去重);③ 旧分散页「能用的搬进对应台」当子标签、死/被取代的退役。台切换器 6 个:总览/策略/因子/Model/模拟/Agent(**Agent台正名**,原伪装成策略台 current)。
- **搬迁映射**:策略工坊/IDE/策略模板→策略台子标签(需求录入/代码IDE/模板起步);实验追踪+训练台→Model台子标签(实验谱系/训练台);Mode2教练→Agent台子标签(量化教练);Binance交易台→模拟台·实盘接入。**退役**:旧 Agent 对话页(/agent,被 Agent工作台 /agent-workbench 超集取代,LLM 连接测试面板迁安全设置页)、因子市场(死文件,无路由无引用)。**训练台改为内嵌不删**(零功能回退;与作业台均调 /api/training/jobs,重叠为已知、可后续去重)。
- **红线遵守**:旧路由全部【重定向】到新台落点(防外链 404);`/runs/:runId` 冻结详情页 RunDetailPage 一字未动(GOAL §M15 / RULES.project §10);R11 前端 display-only 审计仍过(agent 页只 /api/agent/*,删 AgentChatPage 后 Mode2 仍守门);权限/治理逻辑未动,只改导航投影。
- **依据**:用户 2026-06-22「a+b,必须诚实做完」;前端导航三层重叠(顶栏 tab × 旧侧栏页 × 全屏台)收口。
- **状态**:confirmed。验证:tsc 0 / 前端 241 测试 / 后端 R11 8 测试 / 6 台浏览器实证 + fresh server 零 console 报错。未 commit(待用户明示)。

## D-KILLSWITCH-IP · 急停/紧急平仓 IP 白名单改服务端派生（2026-06-22 用户拍板「都做」）

- **决策 = source_ip 服务端派生**:`/api/risk/kill_switch` 与 `/api/security/mainnet/emergency_close_all` 的 IP 白名单校验,source_ip 从【请求连接】(`request.client.host`,新增 `_client_ip` 助手)派生,**不再从 body 取**——body 可伪造则白名单形同虚设(攻击者填一个已加白值即过)。**强化**(非削弱)执行侧不变量(§0.1 执行侧硬锁)。
- **代理注意**:默认【不信任】X-Forwarded-For(可伪造);若部署在反向代理后须在受信代理层处理 XFF 并相应配 trusted_ips(已写代码注释)。`password_verified` 仍走前端 /api/auth/login 真校验(既有契约,未动)。
- **前端**:急停 modal 去掉手填 IP 框(服务端派生,前端无需也无法填)、不再 body 传 source_ip、文案改「按真实连接 IP 校验,不可伪造」。
- **二次鉴权升级(同源,2026-06-22「升级」)**:**废除自证 bool `password_verified`**——新增后端 `_verify_second_factor` + `AuthService.verify_password(user_id, pwd)`(PBKDF2,纯校验不发 token),动钱端点(kill_switch / emergency_close_all)改为服务端【真校验】账户密码 **或** 2FA TOTP(至少一个过)。前端急停 modal 直接传明文密码(同源)、删去 /api/auth/login 预校验旁路;settings 紧急平仓的 totp_code 现也被服务端真校验(原后端只读 password_verified、totp_code 被忽略=隐性失效,顺带修)。body 里的 `password_verified` 字段彻底失效。per-order guard(mainnet_guards.check)的 password_verified 是服务端内部调用、无前端旁路,本次不动。
- **依据**:用户 2026-06-22「都做」+「升级」;修 killswitch 内嵌时发现的既有后端弱点(source_ip 取 body + password_verified 自证 bool);D-T025 急停 fail 模式基线之上的加固。

## D-FE-REVIEW · 前端交互审查修复 + AI 文案去包装的关键判断（2026-06-22）

- **OOS 训练泄露修复（数据有效性级·撞「不假绿灯」红线）**:TrainingBench 选「前 N% 训练·留后段严格 OOS」时 UI 明文承诺「无泄露」,但 submit() 提交体漏传 `train_fraction` → 后端 `request.train_fraction=None` → service.py L245 跳过 `_slice_front_dates` → 全样本(含被保留 OOS 段)训练、回测 strict_oos 永不触发。后端无泄露管路本已就绪自洽,**前端补传 `train_fraction` 一行即兑现承诺**(不动后端/不动大逻辑)。
- **H3「Runs 收益涨跌色反转」= 误报,不改(防回潮)**:审查子代理断言「收益正用红=涨跌色反转 bug」,对抗验证排除——A 股「红涨绿跌」正确惯例:`--danger=#e74c3c`(红)/`--success=#27ae60`(绿)、相邻最大回撤格也用绿,整表自洽。照「修」反而破坏 A 股惯例。**典型审计陷阱:框架(语义色=好坏)被细节(A股惯例+回撤格)推翻(RULES §6)。** 再有人提「修涨跌色」一律驳回。
- **对抗验证收敛「别管太宽」**:10 条待办 claim 逐条独立 skeptic 默认当误报核实 → 真该现在修仅 3(OOS 已修 / agent-live-mock LIVE 批准门重放 mock 违 LIVE 不假绿灯 / jobsdeck selJob 卡 mock id),**误报 2**(SharedStrategies 刷赞被后端 PK 去重、PaperDesk 双击双审批被后端 self.lock+GateStateError+幂等三护栏推翻)、**死代码 1**(Runs WS stub 永不触发)、其余 mock/低影响 later。**区分「管宽」(塞低价值未核实项=错)与「管对」(撞红线/数据有效性,哪怕一条也修)**——上一轮列 20+ 项有 scope 膨胀,验证后真正要紧只 OOS 一条。
- **文案去 AI feature 包装**:把「AI 驱动/教练/副驾驶/Socratic/AI 助手/竞品对标」hype 改成中性专业描述(说清功能实际做什么),真 LLM 功能(IDE 代码助手/Mode2 对话)保留准确标签,**不删功能/不动交互**;唯一真失真是 StrategyWorkshop「自然语言→」(后端实为关键词规则提取)。
- **依据**:用户 goal「前端有交互逻辑 bug + 不动大逻辑下文案去 AI feature」;H3 复核遵 RULES §6(审计框架可被细节推翻)+§3(不假绿灯)。
- **状态**:confirmed。前端这批 + OOS 已修并 push origin/fullstack;**agent-live-mock / jobsdeck-mockid 待用户拍板再修**;其余 later。tsc 0 / 前端 241 passed。

## D-GITIGNORE-ARTIFACTS · 本地生成产物不入库（2026-06-22 用户拍板「graphify 产物不入库，data 也是」）

- **决策**:`.gitignore` 追加 `graphify-out/`(知识图谱本地产物,52MB/含 11MB graph.json,每人本地 `graphify update` 重建)+ `data/strategy/`(策略候选运行产物)。**不入库**。
- **不一刀切 data/**:现有 `.gitignore` 已逐项精细忽略 data 运行产物(market/datasets/db/training_runs/...),同时**有意保留 30 个 demo 示例数据入库**(`data/artifacts/experiments/*_demo/`、`data/_symbol_pools/example_*`)——故只补 `data/strategy/`(当前唯一未跟踪 data 产物),不加宽泛 `data/`(会与既有精细规则冲突、误伤 demo 样例)。
- **依据**:用户 2026-06-22 push 范围确认时拍板;push 前发现 `git add -A` 会把 52MB graphify-out 永久焊进 git 历史(不可逆)、停下报告 → 用户选「去掉生成产物再全推」。push 前凭据扫描 0 命中(无密钥入库)。
- **状态**:confirmed。已 push origin/fullstack(cb2a083 gitignore + c213583 主体,138 文件)。
- **状态**:confirmed。验证:后端全量 **1240 passed**(含 3 条加固/升级回归:`..._body_source_ip_cannot_spoof_whitelist` IP 防伪造、`..._rejects_wrong_password` 错密码 403、`..._self_attested_bool_no_longer_bypasses` 自证 bool 不再放行);前端 tsc 0 / paper 17 测试 / modal 浏览器实证只剩密码框、空密码禁用确认键、零 console 报错。承接:D-T025 同源。

## D-WAVE1A · 下一波 1A「把每 run 可信做实」scope/排序 + 7 项拍板（2026-06-22 用户逐项拍板）

> 承 D-CLOSEOUT 排序(第二波 C+D)。本波在 pool 4 卡上做多 voice 合规评审(16 agents)后，用户逐项拍板。节奏沿 D-CLOSEOUT 3C 最大自驱。

- **本波 scope**：S(R18 诚实标注) + D(R28 全双时态 Stage①②) + M(监控尾部闭环) + C(组合三角 full-fat) + **新增组合消费者卡**(agent 产组合调 `optimize_portfolio` + 走 promote 流注入 gate_runner)。B 因子轨 / E 信任层 / F 可上线 留后续。
- **排序**：S 先(XS·零依赖·诚实修正) → 拍板批次 → D(携本波唯一现在就生效的安全不变量) → 消费者卡 → C(land 在消费者后) → M。4 卡 build-order 无硬 import 依赖、可并行(`depends_on:[]` 评审 CTV-1 确认)，真成本在跨卡口径拍板。
- **7 项拍板**：
  - **SEQ-CONSUMER = A**：C full-fat 本波落地 + 本波新增组合消费者卡(C land 在消费者后)。评审指 `optimize_portfolio` 当前无产品消费者，用户选本波连消费者一起做。
  - **C-Q1 = A2（override R2）**：组合主题归属用独立命名空间 `portfolio:<id>`(砍 `_theme_matrix` layer 过滤，双 voice 核实冗余)；**且放松组合层红绿灯**——PBO 不可达(N<10)时 `DSR(通缩)+bootstrap 双绿即 green`、醒目标 `PBO N/A`。这是用户**明确 override R2「完整三角才放行」**，依据 §0.1 研究侧旋钮(门槛档不锁、归用户)。**反假绿灯护栏 = 用户的可选档(不强加)**：是否加 honest-N 下限 + 更严 DSR/CI margin 防低 N 误绿由用户定；默认按 A2 直做。(对应 memory: 提供流程不强加选择)
  - **C-Q2 = A**：组合 promote honest-N 独立 +1。诚实限界(写进验收)：同 `strategy_goal_ref` 下组合与重权成分被 `n_eff` 收益相关聚类(corr 0.7)聚同簇→N_eff 低估，仅影响乐观展示端，过闸保守端 `honest_n` 兜底不受影响。
  - **C-Q3 = A**：多市场混合组合取最严 `min_T`(成分 max，含 a_share 则 504)，C 接线侧预解析；达不到落 `insufficient_evidence`(诚实结果)。与 R14 一致。
  - **D-AXIS = A**：`known_at` 由**写层 provider owns first-seen**(keep-first 幂等)、读层只查 `as_of_known`。唯一非纸门归属(first-seen 只在写层可观测)，GOAL §8/R28=A 明令。
  - **D-NECESSITY = B**：本波直接做**全 Stage①②**(全库 per-row 双轴 + as-of 重述查询)，不裁 Stage②(+3–5 dev-days)。R28=A「不分级」终态。
  - **M-AUTHORITY = A1**：监控→降级/退役走 **factor lifecycle (`registry.LifecycleState`) 为权威**(hypothesis `card.status` 作派生视图)、单发 PROV；croniter 升硬依赖/启动响亮失败。范畴硬约束：退役动作矩阵只接绩效/成本漂移信号(IC/drift_pct)，**绝不接 C 的 gate verdict**(DSR/PBO 是晋级期过拟合闸，接成运营退役触发器=范畴错误)。
- **红线实现约束(correctness，非待拍·实现时必处理)**：
  - **[critical] C 验收语义重写**：原「组合层过拟合→gate 必红」在冷启动物理不可达(yellow≠red)且低 honest_n 可能三支 all_agree 误绿。改为「组合层过拟合→三角不达 green(yellow/insufficient/red 之一)」；red 仅 DSR<0.2 / CI 上界≤0 / PBO>0.7 触发；ADV1 探针分 N<10(断言 pbo is None 且 verdict≠green)与 N≥10(seed≥10 同主题曲线，断言 PBO 升+red)两档。
  - **[high] D 写层 owns**：对抗测试三断言——写层 keep-first 真门 + re-backfill 幂等(同 restatement 不推进 known_at) + 读层 `as_of_known` 透传；只测 `load_panel` 会在纸门上假绿。扩展不替换、additive、不破 `tushare_quant1` 既有 `(ts_code,end_date)` dedup。
  - **[high] C ADV2 防作弊洞**：`config_hash` 对成分 list 不排序→`[A,B,C]` vs `[C,B,A]` 不同 hash→honest-N 重复 +1。在 C 调用方把成分集+权重规范成排序后 `(symbol,weight)` 序列(不改 `ids.py` 单一源)；对抗测试断言 equal_weight 重排→同一 config_hash→不重复 +1。绝不靠抑制计数(触 honest-N 不可改小)。
  - **[high] M croniter 硬化**：缺 croniter 则 `Scheduler.tick` 静默不跑→自动退役环 paper-true，须启动响亮失败。
  - **[high] M 单发 PROV**：三条发 PROV 路径(`store.retire:207`/`store.deviate:247`/`lifecycle.evaluate:147`)自动接线须收敛到权威单发，禁双发+状态不一致。
- **依据**：D-CLOSEOUT(排序+3C 最大自驱) + R18 确认(信号层强制 OOF+purge+embargo) + 多 voice 评审(graphify grounding + 对抗验证 CTV-1~6) + 用户 2026-06-22 逐项拍板 + §0.1(研究侧旋钮如门槛松紧不锁、归用户)。
- **状态**：confirmed。承接卡:S `87ad21fc` / D `3a8b2360` / M `d0e5d208` / C `46f1cb3c` + 新 mint 组合消费者卡;stacking 控制项卡 `87ad21fc` 即 S。待拍清零，进实现(worktree `wave-1a`)。已 land main `5cf613a`。

## D-DELIVERY-SLICE · 下一波转「交付门垂直切片」陌生人走通 chat→backtest→裁决→paper（2026-06-22 用户拍板）

> 承上一波 CEO flag（连续两波向内、零移动 §9 交付总闸）。用户拍板下一波**转交付门垂直切片**：让一个陌生人靠对话走通端到端。6-agent audit workflow code-grounded 出 gap 地图后逐项拍板。

- **波向**：北极星 §0「可上线」端到端验证——陌生人（非开发者、不懂内部）对话生成策略→真回测→多证据三角裁决→晋级 paper 跑出净值。
- **audit 核心发现（§3 产品级假绿灯）**：后端真基建全在、红线全干净（真引擎/真裁决投影/治理门 D-PERM·A股恒拒live·INV-5·措辞守门），但**陌生人能点的前端路径全程默认 mock**（Agent台 autoplay 脚本 / 裁决卡 MOCK_AGENT_RUN / 模拟台 mock.ts RUNS），真入口藏在不显眼开关后，且**无一条真 run_id 贯穿四站**。陌生人体验「看起来全绿、实则全程 mock」的演示流 = §3 最警惕的假绿灯。修这条切片 = 修真·假绿灯，高价值。
- **3 fork 拍板**：
  - **Fork1 = C + Hermes auth**：造站「对话生成」对陌生人成立 = 配 key 走真 NL / 无 key 走 slot-filling 追问 + `strategy_goal.create` 真落库。**外加 Codex/Claude-Code 订阅 auth（像 Hermes）**：QuantBT 已有 `OpenAICompatibleLLM` custom provider 支持任意 OpenAI 兼容 base_url → 用户跑 Hermes 等本地 OAuth 代理、QuantBT 指向 `localhost:<port>/v1` 即用其 Claude Code/Codex 订阅额度，**不自实现 OAuth**。scope = onboarding/Settings 引导预设 + 文档（轻活）。**暂不**自 shell-out `claude -p`/`codex` CLI（更重、非「像 Hermes」；用户要无缝再开卡）。
  - **Fork2 = A 闭全 6 blocker**：陌生人真走通端到端到 paper 净值（含 2 个 L：#3 backtest 真引擎接 RUN_ROOT、#6 paper 真 provider 产净值）。切片价值就是端到端真走通，不留半截。
  - **Fork3 = A agent backtest 改写 RUN_ROOT**：消灭两套并行 run 注册表（agent 写 `runs.jsonl` vs 裁决读 `RUN_ROOT/<id>/run.json`），agent `backtest.run` 复用 IDE promote 落盘契约 → 单一注册表、run_id 自然贯穿（§1 单一源）。
- **§3 假绿灯类 = correctness 不待拍**：乐观假成功（晋级失败仍 `setPromoted(true)` / handoff 失败显示「已提交」/ 空壳净值盖「LIVE 已接真」绿标）照修，那是产品不变量非松紧档。
- **依据**：CEO flag（交付门垂直切片）+ delivery-slice-audit workflow（6 agent code-grounded gap 地图）+ 用户 2026-06-22 拍 Fork1=C+Hermes/Fork2=A/Fork3=A + Hermes 机制（本地 OpenAI 兼容 OAuth 代理，QuantBT 已有 custom provider 支持）。
- **状态**：confirmed。承接卡:DS-1 run_id 脊梁 / DS-2 造站接真 / DS-3 裁决接真 / DS-4 paper 接真 / DS-5 §3 假绿灯修 / DS-6 装机收口。脊梁=DS-1（真 run_id 一通四缝大半合拢）。worktree `delivery-slice`。

## D-LLM-ROUTING · LLM 默认路由策略 = 混合自适应（2026-06-26 用户拍板·中心并行 campaign 第三波前置）

> 第三波将建 LINE-A-AGENT LLM Gateway（Gateway/Registry/Routing/CredentialPool/LLMCallRecord）。路由默认值需用户拍。

- **拍板 = 混合自适应**：LLM Gateway 默认路由按任务难度/风险自动选档——硬推理（架构/数学/难调试/不可逆决策）走强模型、机械活（格式化/简单提取/样板）走轻模型。符合北极星「降门槛不降标准」：但凡用必机构级、成本可控。
- **实现约束**：Routing 策略**可配**（用户可后调成质量优先/成本优先）；默认=混合自适应。LLMCallRecord 记每次实际路由的模型+档位（可审计·进 RDP）。**绝不静默降质**到不适配的轻模型（难任务误走轻模型=correctness 风险）。
- **依据**：用户 2026-06-26 拍板（AskUserQuestion·混合自适应推荐档）。
- **状态**：confirmed。承接卡:LLM Gateway 卡（待 mint·LINE-A-AGENT·第三波主力）。

## D-SCOPE-CONSERVATIVE · 不过度强制：数据字段不强制来源、RDP 等聚合器、「不要管太宽」（2026-06-26 用户拍板）

> wave-2 落地 3 个「松紧旋钮」（W3 数据字段强制必备 / W3 data_pull 回收进门 / W4 RDP 强制档常开）。用户拍板**全部保持保守默认、不调紧**。

- **W3 数据字段 = 不强制**：正常字段即可，**不强制带 skill_version/secret_ref 等来源字段**。用户明示「来源标注的是数据来源（哪个数据提供商）这种，本就是普通字段、不该当门」。`require_provenance` 保持 opt-in 默认关。
- **W3 data_pull legacy 回收 = 不做**：canonical intake 写路径已 gated 即可；legacy data_pull 不强制进门（不动 main.py 单例/tushare/perf）。
- **W4 RDP 强制档 = 等聚合器**：`require_rdp` 保持默认关，待 D-RDP-2 聚合器供真血统后再议常开（现在强制=promote 砖死）。
- **总原则 = 不要管太宽**：别把缓解护栏当不交付硬条件、别加用户没要的强制门。只守 correctness（不假绿灯/数学↔实现一致/no silent mock fallback）+ 安全不变量（撞即停）。方法学松紧/范围归用户。（呼应 memory: 提供流程不强加选择）
- **对 W1 enforce 的修正（2026-06-26 读 GOAL §15 后·更正本条初稿）**：GOAL §15 明写「external pickle **blocked by default**」=enforce 默认开是**终态**（安全终态·非松紧档·非「管太宽」）。「不要管太宽」只管**方法学松紧/数据来源字段**，**不覆盖 §15 安全终态**——别把它误用到安全红线上。故 W1（6144bd61）目标=**enforce 默认开兑现 §15**：接全 producer→系统自产 artifact 过门、外来默认拒；中心整合点跑全量验证，全 producer 已接+零误伤+全量绿→**默认开**；若 producer 未接齐会破基线→**过渡** opt-in + 标 producer 接线 gap 待补（非永久 opt-in·终态仍是默认开）。
- **依据**：用户 2026-06-26 拍板（AskUserQuestion·「正常字段就行不要强制带其他来源字段…rdp 等聚合器…不要管太宽」）。
- **状态**：confirmed。
## D-QRO-CANVAS · 终态对象模型/画布/编译器正名（2026-06-25 用户拍板）

> 用户明确收敛终极形态：不是普通全栈量化软件、回测平台、因子平台或 ChatGPT wrapper，而是「用户出想法，用画布构建想法，Agent 代为实现代码与数学/统计验证，anywhere 都是机构级，区别只在权限」的全栈量化顶尖机构级平台。

- **整体正名**：QuantBT 终态定义为 **canvas-native / agent-implemented / governance-first 的 Institutional Quant Research-to-Execution OS**（机构级量化研究到执行操作系统），而不是泛称「AI 量化平台」。
- **核心对象链**：所有因子/model/signal/strategy/组合/风控/执行/监控想法统一进入 `Quant Intent → Typed Quant Research Canvas → Quant Research Object(QRO) → Quant Research Graph IR → Governed Quant Research Compiler → Deterministic Run → Evidence Verdict → Promotion/Approval → Runtime → Monitor/Retire`。
- **QRO 范围**：Factor、Model、Forecast、Signal、PortfolioPolicy、RiskPolicy、ExecutionPolicy、Strategy、ValidationCase、Deployment、MonitorDefinition 都是 QRO 类型；统一 identity/version/typed contract/lineage/evidence/permissions/lifecycle，但不抹平各自量化语义。
- **画布真值**：Typed Canvas 不是白板；它是 canonical Research Graph 的可视化编辑器。Chat / Canvas / API / IDE / scheduler 只能提交同一类版本化命令或读取投影，不能各自维护真相。
- **Agent 权限**：Agent 负责消歧、数学形式化、数据绑定、代码实现、测试、实验、报告、解释和运行辅助；Agent 的输出是 proposal / implementation / evidence artifact，绝不是最终控制权。控制权属于 deterministic kernel / verifier / policy engine / approval / execution guard / ledger。
- **anywhere 机构级**：任何正式入口（chat/canvas/API/IDE/batch/paper/testnet/live/report/monitor）都服从同一套契约、时间语义、证据、权限、血缘、安全、审计和生命周期不变量；production 结果不允许 silent mock fallback 或 template false success。
- **降低门槛不降标准**：初学者与专业用户使用同一 QRO/Graph/验证内核/治理状态机；区别只在界面层级、权限、资本额度、确认步骤和可进入环境。不存在「初学者玩具后端」与「专业真实后端」两套标准。
- **单人诚实边界**：一个人可拥有被高度压缩的机构级流程能力；单人模式只能声称 functional independence（隔离验证路径/不可变证据/二次确认/权限边界），不能伪装 organizational independence。
- **交付物正名**：终态交付是 Research Delivery Package，不是一段代码或一张回测图；包含研究命题、graph、数据/PIT 语义、数学定义、代码/环境/hash/seed、测试、运行、honest-N、verdict、approval、deployment、monitor、rollback、retire。
- **诚实边界**：本决策更新终态契约和后续验收口径，不把当前 active/deferred/partially-integrated 能力描述为已完成；当前 gap 继续由 `state/*/state.md`、board、DEVMAP 对照新 GOAL 陈述。
- **依据**：用户 2026-06-25 终极形态描述 + GPT Pro 概念研究输出 + Codex 对当前 `dev/GOAL.md`/state/board 的 live 对照。
- **状态**：confirmed。承接：本次同步 `GOAL.md` / `research/TRACE.md` / `state` / `README`；后续实现卡按新 GOAL 反推出画布真实管线、QRO registry/contract、compiler passes、mock-profile 化和 production no-silent-fallback 等 gap。

## D-MATH-SPINE · 数学贯穿全流程 + 理论到实现一致性门 + 用户方法学放权（2026-06-25 用户拍板）

> 用户明确：数学不只用于因子、模型、策略前段，而要贯穿数据、因子、模型、信号、组合、执行、回测、归因、监控。方法学松紧、是否走某流程、是否继续推进属于用户选择；系统给代价、推荐和流程，不替用户拍板。

- **数学贯穿**：数据时间语义、因子、标签、模型、信号、组合、执行成本、保证金、回测估计、归因、监控触发、降级和退役都进入 Mathematical Spine；该有数学的地方能产出 `MathematicalArtifact / TheorySpec / TheoryImplementationBinding / ConsistencyCheck`。
- **理论先行**：声称使用某方法、公式、估计器、约束、成本模型、风险度量或监控触发器时，先形成数学定义、假设、推导、适用域、反例和失败条件，再绑定实现。
- **一致性硬门**：理论正确但实现跑偏视为系统错误。任何声称“按理论实现”的代码、配置、数据绑定、run config、监控触发器、执行成本模型，必须通过 `TheoryImplementationBinding` 和 `ConsistencyCheck`；不一致不得冒充 proof-backed / evidence sufficient / production-ready。
- **Agent 职责**：Agent 降低实现门槛，负责理论形式化、代码实现、测试、仿真、数据管线、回测、报告和一致性检查。Verifier / Critic 挑战假设、推导、维度、单位、识别、代码映射、运行配置和监控触发器。
- **用户放权**：`MethodologyChoiceRecord` 记录用户选择 strict / standard / loose / exploratory / custom / user_waived，附带可选路径、推荐、代价、跳过项、责任边界和可达环境。用户选择承担风险后，系统继续交付。
- **边界**：user waiver 不能绕过 secret 隔离、OrderGuard、kill switch、no-silent-mock、A股 live 边界和理论实现一致性诚实标注。user waiver 只能改变研究/方法学松紧与责任归属，不能把未证明内容伪装成已证明内容。
- **依据**：用户 2026-06-25 明确表达“数学贯穿整条流程 / 理论先证明 / agent 降门槛 / 理论实现一致性是命门 / 用户自负其责即可放行”。
- **状态**：confirmed。承接：同步 `GOAL.md` / `research/TRACE.md` / `state` / `log`；后续任务按 Mathematical Spine、Consistency Gate、MethodologyChoice ledger 拆分。
