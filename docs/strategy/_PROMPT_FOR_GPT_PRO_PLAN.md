# 给 GPT Pro 的 QuantBT 战略咨询 briefing（v0.8.3 时点）

把下面整段 prompt 一次性贴到 GPT Pro，让它出一份"超级详细方案"。文末有"必须避免"清单，避免它给套话。

---

## 提示词正文（贴这整段）

你是有 15 年量化产品 + 资管 + 算法交易经验的产品咨询师。你为一个**单人 + AI 协作**的全栈量化项目 **QuantBT** 提供战略和产品建议。我会先把项目方方面面灌给你，然后让你按指定结构输出一份**可执行**的方案——**不是高层愿景，是带数字、对标产品、风险评估、明天就能开干的清单**。

---

### §1. 项目身份卡

**QuantBT** = 单人开发（用户 + Claude Code 协作）的全栈量化平台，目标是把"聚宽/BigQuant 的学习友好"+"QuantConnect 的工程严谨"+"Binance Copy Trading 的实盘闭环"揉成一个**可上线交付**的产品。

- **资产范围**：A股（仅到 paper trading，禁接券商）+ 加密永续/现货（到 Binance 实盘）。两条腿，明确边界。
- **代码规模**：后端 Python ~98 文件、前端 React+TypeScript ~33 文件、总~29k 行，单元/集成测试 261 通过。
- **技术栈**：FastAPI + Uvicorn / Vite + React 18 + TS / sqlite + Polars + DuckDB / LightGBM + sklearn + scipy / echarts / 自写 HMAC Binance client（不用 python-binance）。
- **AI 协作**：所有代码 + 文档 + 测试由 Claude Code (Opus 4.7) 与单人开发者 pair-program 完成，开发周期约 6 个月。

---

### §2. 目标客户 (User Persona)

**P0（核心，必须服务好）· "想毕业的聚宽用户"**：
- 25-40 岁，有 Python 基础（写过 pandas），自学过聚宽/BigQuant 但被它的 in-platform-only 锁得难受
- 想"自己的数据、自己的因子、自己的实盘"，不愿付高额 SaaS 订阅
- 真有几千~几十万本金跑加密，A股是边学边玩
- 想从"抄文章的策略" → "理解原理 → 自己改 → 实盘验证"完整闭环
- 学习焦虑：知道"过拟合"是大问题但不知道怎么真正避免；知道 Sharpe 高不一定真好但不会用 DSR

**P1（次级，想发展）· "想转量化的程序员/数据科学家"**：
- 有强工程背景，但金融知识门槛高
- 关心架构干净度、可读源码、可改造扩展
- 把 QuantBT 当"开源参考实现"+"自己的 sandbox"

**P2（远期）· "想发策略带单的小 V"**：
- 量化经验 1-3 年，跑出几个稳定策略
- 想做"私域带单"小生意（已落地 v0.8.1 copy_trade）
- 不想自己写交易接口/风控
- 单 master 期望带 10-100 个 follower 规模

**明确不服务的人**：
- 完全零编程的小白（让他们去同花顺、雪球）
- 机构量化基金（他们自己有 PM 团队）
- 想"AI 自动赚钱"的伸手党（产品定位是教学+工具，不是黑箱）

---

### §3. 量化方法论选择（学术路线说明）

我们**有意识地**对齐以下三个学术 + 业界路线，反对其他做法：

1. **López de Prado 体系**（《Advances in Financial Machine Learning》2018 / 《Machine Learning for Asset Managers》2020）：
   - 因子建模用 Triple Barrier 标签
   - CV 用 Purged k-fold + Embargo
   - 组合优化用 HRP (2016)
   - 过拟合证伪用 PBO (CSCV) + Deflated Sharpe (Bailey-LdP 2014)
2. **WorldQuant Alpha 体系**（Kakushadze 2016 Alpha101）：
   - 白盒因子表达式 (44 个 ts_/cs_ 算子) + AST 引擎
   - 因子生命周期管理：NEW→QUALIFIED→PROBATION→OBSERVATION→WARNING→RETIRED (参考 aiquantclaw.com)
3. **Bailey & López de Prado 反过拟合体系**：
   - 任何 SR > 1 必须配 DSR / PBO 报告
   - 多次试验偏差必须显式估计

**反对的做法**：
- 不用纯 GridSearch 调参（必走 Walk-forward）
- 不用单一 Sharpe 选策略（必看 DSR + PBO）
- 不写黑盒因子（Alpha 必须能写成表达式）
- 不接 vnpy/easytrader/ths_trader（A股不接券商，避法律风险）

---

### §4. 三个不可动摇的硬约束（产品 DNA）

1. **`RunDetailPage.tsx` 冻结**：回测结果详情页只允许"加字段/调排版/调显示逻辑"三类改动，不许重写、不许删 tab、不许大动像素布局。这是用户对"看回测结果"这个核心体验的稳定性诉求。
2. **A股不接券商**：禁止 import vnpy/easytrader/ths_trader 等任何接 A股实盘的库。A股仅到 paper trading。原因：A股实盘对接法律灰色，避险。
3. **Binance keyring 加密 + 启动校验 + no-withdraw**：API key 必须 keyring + Fernet AES 加密落盘；启动时强制校验"该 key 无 withdraw 权限"才允许下单；mainnet 切换必须二次确认弹窗。
4. **Copy-trade 隔离**：私域带单中 follower 的 API key 永远走 follower 自己 keystore，master 拿不到任何 follower 凭证（已落地 v0.8.1 SignalRelayer）。

---

### §5. 当前技术状态（截至 v0.8.3 · 2026-05-28）

#### 后端模块清单（M1-M18 全部落地）

| 模块 | 状态 | 关键能力 |
|---|---|---|
| M1 StrategyGoal | ✅ | Pydantic schema + 两套预设 + YAML round-trip |
| M2 Universe + Regime | ⚠️ 简版 | 仅静态 symbol_pools，缺动态池 / HMM 状态 |
| M3 数据接入 | ✅ | 5 类内置 connector（Tushare/BinanceVision/BinanceREST/GenericREST YAML DIY/UserUpload）+ dataset_version 不可变 + freshness green/yellow/red + GE-lite 5 类质量规则 |
| M4 因子工厂 | ✅ | 44 个白盒算子 + AST 表达式引擎双阶段 eval + alpha_lite 30 内置因子 + IC/RankIC/IC-IR/IC 衰减 + FactorRegistry 版本化 |
| M5 标签 | ✅ | raw_return / excess_return / xs_rank / triple_barrier / meta_label / vol_adjusted |
| M6 模型 | ✅ | LGBM clf/reg/lambdarank + sklearn baseline + Purged k-fold + Embargo + Walk-forward |
| M7 信号融合 | ✅ | direction/magnitude/confidence/regime 四元组 + Platt/isotonic 校准 |
| M8 组合优化 | ✅ | equal_weight / mean_variance(SLSQP) / risk_parity / **HRP** + 单标的/行业/相关性/杠杆约束 |
| M9 执行风控 | ✅ | BinanceSpot/UMFutures venue (HMAC 自签 + symbol filter quantize + clientOrderId 幂等 + assert_safe_startup) + UserDataStream (WS + 25min listenKey 续期 + reconcile) + GenericTradingVenue (YAML DIY) + RiskMonitor (单笔/日内/集中度) + SecureKeystore (keyring + Fernet AES + memory) + KillSwitch |
| M10 回测归因 | ✅ | PBO (CSCV) + DSR (Bailey-LdP 2014) + Bootstrap Sharpe CI + Brinson 三层归因 |
| M11 因子生命周期 | ✅ | 五态机 + 参数化阈值 + LifecycleManager 事件日志 |
| M12 实验注册表 | ✅ | MLflow-lite + lineage + ModelRegistry (dev→staging→production→archived) |
| M13 任务编排 | ✅ | 百行级 DAG (YAML / 拓扑 / 指数退避重试 / 超时 / SLA / 幂等键 / croniter) |
| M14 Agent | ✅ | LLMClient 抽象 + 4 档 provider (Anthropic/OpenAI/Qwen/OpenAICompatible) + 5xx 重试 + tool_schema 13 工具 + StrategyGoalSlotFiller + CodeReplicator + AgentRuntime ReAct loop |
| M15 前端 | ✅ | Claude Code 风深色 shell + quantpedia 风首页 + 5 个 workshop SPA 页 + RunDetail (jq-* 冻结) + 三联图 dataZoom 防压扁 |
| M16 社区分享 | ✅ v0.8.0 | Auth (PBKDF2 200k + bearer) + Community feed (Square 风 recent/hot/following) + Sharing publish/fork/leaderboard |
| M17 私域带单 | ✅ v0.8.1 | CopyTradeService 5 表 + invite_only + invite_code 旋转 + SignalRelayer follower 自 keystore + 14 endpoint |
| M18 IDE + AI 辅助 | ✅ v0.8.3 | 子进程沙箱 (subprocess + rlimit + socket monkey-patch + isolated python -I + wallclock 30s) + emit_result JSON 协议 + IDEService CRUD + AI write/explain/fix 三模式 + **promote_ide_run** 落 runs/<id> 进 RunDetail pipeline + **build_ai_context** 给 LLM 注入 5 connector / 30 factor / 44 operator / 沙箱规则 / emit_result schema |

#### 前端 SPA 页清单（共 12 页 + 1 冻结）

`/` HomePage（quantpedia 卡片网格） · `/runs` RunsPage · `/runs/:id` **RunDetailPage 冻结** · `/compare` ComparePage · `/data` DataPage · `/strategies` StrategyIndexPage · `/workshop` StrategyWorkshop · `/agent` AgentChat · `/factors` FactorMarket · `/trading` BinanceTrading（mainnet 二次确认）· `/experiments` ExperimentTracking · `/ide` **IDEPage**（v0.8.2-3 新）· `/community` CommunityFeed · `/square` SharedStrategies · `/copy-trade` **CopyTrade**（v0.8.1）· `/u/:username` UserProfile · `/login` Auth

#### 数据库

- `data/community.db` · 共享 sqlite（auth users + community c_* + sharing s_* + copy_trade ct_* 共 13 表）
- `data/ide_strategies.db` · IDE 策略文件 + run 记录 (i_strategies + i_runs)
- `data/artifacts/experiments/<run_id>/` · 每个回测 run 目录（run.json + portfolio.csv + trades.csv + strategy.py + backtest.log + report.md + series/）
- `data/factors/registry.json` · 因子版本注册表
- `data/keystore_index.json` · 加密 keystore 索引

#### 测试基线

- 261 单元 + 集成测试全过
- tsc 0 错
- vite build 1335 modules ✓
- pytest 含真 LLM 端到端验证（Anthropic + Qwen + OpenAICompatible 全过）+ Binance HMAC 签名校验 + Sandbox 网络/subprocess/os.system 拦截校验 + Copy-trade 6 种状态 dispatch + IDE promote 真落 runs/ 端到端

#### 还没做的（GOAL §13 剩 3 项需用户实测的）

- task 34（已完成）：Tushare 真数据 A股 ML demo
- task 35（已完成）：真 LLM 多轮 agent 端到端
- task 36（待办）：Binance testnet 全订单类型 e2e 实测（需要用户上 testnet key）
- mainnet 100USDT 一周实盘（极其谨慎，必须用户决定）

---

### §6. 已规划的路线图

#### v0.8.4-v0.8.6 · Mode 2 教学型 agent（已与用户对齐）

- **v0.8.4 知识库 + Glossary API**：30 条核心量化术语 markdown 词条（YAML frontmatter + 四段 L1-L4），后端 `/api/glossary` `/api/glossary/{term}` endpoint。词条由用户用 GPT Pro 按预定 prompt 生成，Claude 接入 + 校验脚本。
- **v0.8.5 字段 ⓘ 化**：RunDetail metrics 卡片每个字段加 ⓘ 按钮（在 §M15 "加字段/显示逻辑" 允许范围内），点击弹 popover 显示 glossary L1/L2，"查看更多"展开 L3/L4。IDE result_keys chip 同款。
- **v0.8.6 多轮 Socratic chat + 主动建议**：
  - `conversations` 表持久化对话 (sqlite)
  - `/api/chat/stream` SSE 端点
  - IDE 右侧 AI 面板改 mode toggle（执行 mode / 深度 mode）
  - 跑完 run 自动在 RunOutput 顶部浮一句温和建议（"你这次 SR 1.2 但 PBO 0.68，想深入看看吗？"）
  - 系统 prompt 自动 inject glossary 关键条目
  - 多轮 chat 走 RAG: 用户问 X → 检索 top-k glossary 词条 → 注入上下文 → LLM 回答

#### 未规划的（你可以推荐）

- 数据集"参考实现"（业内常用的策略复现：BTC 季度持有 / 50ETF 月轮动 / 加密永续套利）
- 真接入 Binance testnet 的 e2e demo
- 移动端 / 通知（带单实时 push）
- 多人协作（团队 master + 多 follower 私域）
- 监控面板（user retention / strategy run count 等）
- 教学路径系统（"新手→因子→标签→模型→组合→实盘"7 步引导）
- 沙箱里允许预装 talib / numpy-financial / pandas-ta（现在没装）
- 数据导出（让用户带走自己跑的全部 runs/）

---

### §7. 资源约束

- **团队**：1 人主开发 + Claude Code AI 协作。无设计师、无 PM、无 QA。
- **时间**：用户每天可投入 2-6 小时（不稳定，工作日少周末多）
- **预算**：基础设施 = 自己 mac mini 本地跑；LLM API 月开销 ~$50（Anthropic 为主）；不打算融资
- **目标上线时间**：6 个月内出 v1.0（即 2026 年 11 月）

---

### §8. 我希望你 GPT Pro 输出的"超级详细方案"——用以下结构

**不要泛泛而谈。每节给出 (a) 具体行动条目 (b) 度量指标 (c) 风险 (d) 备选方案。**

#### A. 商业模式 & 产品定位

- 当前对标产品矩阵（聚宽 / BigQuant / QuantConnect / vnpy / Numerai / 米筐）逐家对比：他们的优劣 + QuantBT 应该学/避什么
- QuantBT 的"独特价值主张"用一句话写出来，且能在 5 秒内被聚宽用户理解
- 建议的 3 种商业模式（开源免费 / 个人订阅 / 带单 GMV 分成）的可行性评分 1-10 + 你最推荐哪种 + 为什么
- 若收费，定价档位建议（具体数字）

#### B. 目标客户细分 + 关键场景

- P0/P1/P2 的"一周典型使用流"具体到每天点哪几个页面、跑几个回测、看什么报表
- 每类用户的最大流失点 + 对策
- P0 用户从 "听说 QuantBT" → "注册" → "首次跑出回测" → "首次发帖/分享" → "首次实盘" 五个 funnel 阶段的关键阻碍 + 干预措施

#### C. 12 周产品路线图（带优先级评分 P0-P4）

- 列出未来 12 周（v0.8.4 ~ v0.9.x）每周的发版主题
- 每周给出：能交付的 user-facing 改动 + 后端基建 + 文档 + 测试基线变化
- 用 RICE 框架打分（Reach / Impact / Confidence / Effort），高分先做

#### D. Mode 2 教学型 agent 的详细 UX 方案

- v0.8.6 多轮 chat 的具体交互：进入入口、对话 thread 持久化 IA、Socratic 风格的 prompt 模板（写出完整 system prompt 例子）
- 词条 RAG 的检索策略（向量 vs 关键词 vs hybrid，预计 token 消耗，回答延迟预算 < 3s）
- "主动建议"具体规则：哪些 metrics 越过哪些阈值时浮出什么文案。给出 5-10 条具体规则（带阈值数字）。
- 防 hallucination 的硬约束：什么情况下 agent 必须拒答 "我不确定"
- 用户体验心理学：怎么营造 "Bloomberg Terminal 深不可测" 的感觉但又不烦人

#### E. 用户粘性最高 ROI 的 5 个杠杆点

- 列出**你推荐的 5 个具体功能**，按"建议优先级 1-5"排序
- 每个功能：(1) 解决什么粘性问题 (2) 实现复杂度 1-5 (3) 预期 7 日留存提升幅度估算 (4) 风险
- 至少 2 个要是**社交向**（社区/分享/带单杠杆）
- 至少 1 个要是**学习路径**（gamification/进度条/成就系统）

#### F. 对标竞品的差异化漏洞 + 我们应该堵的

- 一份"用户为什么离开聚宽来我们 / 又为什么可能从我们走"的清单
- 对每个差异化漏洞给出 "我们填它需要多少工作量 + 拿到多少用户"

#### G. 关键技术债 + 风险

- 当前 261 测试覆盖率主观估计有哪些盲区
- §3 学术路线 vs 实际代码可能不一致的地方（你要 audit 出来）
- 沙箱（v0.8.2-3）的"非 hardened" 实际能挡住多少类攻击 / 哪些扛不住
- sqlite 单文件未来到多少用户就要换 Postgres 的预警线
- 任何你担心的 single point of failure

#### H. 运营 + 监控 + 转化数据

- 上线后必须埋的 10 个核心 metric（具体到事件名）
- 哪个 metric 是"产品健康度北极星"
- "用户首次跑回测耗时分布" 这种 funnel 应该怎么搭

#### I. 团队 / 资源 minimum viable

- 单人 + AI 协作模式还能撑多少功能复杂度？
- 哪个时点必须招第一个全职合伙人 / 外包谁
- AI 协作工作流（用户用 Claude Code）的提效空间还有哪些
- 是否值得做内容/社区运营（自己写文章 vs 让 AI 写 vs 不写）

#### J. **明天就开干的 7 days 清单**

- 给一份 7 天 day-by-day 任务清单
- 每天最多 3 件事，每件标注预计 (1-4 小时)
- 7 天结束后用户应该达到什么 user-facing milestone

---

### §9. 必须避免的废话

不要给以下任何东西：
- "**充分利用 AI 的力量赋能用户**" 这类话
- "**未来可期**" / "**前景广阔**" / "**机遇与挑战并存**"
- 没有具体数字的建议（"提升用户体验"是废话；"把首次回测时间从 N 分钟降到 < 90 秒"是有用建议）
- 不带对标产品名的建议（说"做得更好"没用，要说"参考 Numerai 的 X 机制"）
- 推荐我"做大数据 AI" / "区块链化" / "Web3"（脱离量化主题的扯淡）
- 套话式 risk assessment（"市场风险、运营风险、技术风险"三件套）

---

### §10. 输出格式

用 markdown，按 §8 的 A-J 顺序，每节带 (a)(b)(c)(d) 四个子项。**最少 4000 中文字**，最多 15000 字。表格能用就用表格。不许大段散文。结尾给一个 TL;DR 用 5-10 条 bullet 收束你最强信号。

---

## 我（用户）的使用流程

1. 复制本文件 [docs/strategy/_PROMPT_FOR_GPT_PRO_PLAN.md](docs/strategy/_PROMPT_FOR_GPT_PRO_PLAN.md) 整段
2. 贴到 GPT Pro 开新对话
3. 它会出一份 A-J 结构化方案，**最少 4000 字**
4. 把它的输出存为 `docs/strategy/gpt_pro_plan_<日期>.md`
5. 我（Claude）拿到这份方案后，把 §J "7 days 清单" 和 §C "12 周路线图" 转成具体 commits 排进 v0.8.4+ 的实施流
6. 同时 audit 它的 §G 技术债清单，看哪些需要立即修
