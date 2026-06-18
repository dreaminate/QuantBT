# 机构级 Agent OS · 研究蓝图

> 目标：把 QuantBT 从"功能齐全的量化平台"拔高为 **一个贯穿全程的 Agent OS——让从"什么都不懂的小白"到"不会写代码的经济学者"，都能靠对话把一个模糊念头，走完"世界上最严谨的、资产无关的、中低频"机构级策略研究-到-生产全生命周期。人只出意图与判断，agent 出全部工程；而严谨的流程治理本身，就是非技术用户能信任 agent 产出的唯一支柱。**
>
> 本蓝图由一次研究 workflow 产出：**17 条主线并行检索前沿论文与机构实践 → 17 个独立 agent 对抗式事实核查 → 4 组分组综合 → 总综合 → 完备性复核**，共 **40 个 agent / 270 万 token / 887 次工具调用**。所有诊断均**对照仓库源码逐文件核实**（带 `file:line`）。

## 怎么读这套文档

| 文件 | 内容 |
|---|---|
| **README.md**（本文） | 执行摘要 · 核心论断 · 6 个已验证的洞 · 跨组贯穿主题 |
| [01-agent-os-design.md](01-agent-os-design.md) | Agent OS 架构选择 · 7 个器官 · 记忆模型 · HITL 模型 · 防过拟合护栏 |
| [02-roadmap.md](02-roadmap.md) | P0–P5 分优先级路线图（已吸收完备性复核的重分类与前移项） |
| [03-open-questions-and-risks.md](03-open-questions-and-risks.md) | 完备性复核挖出的 **蓝图自身盲点**：弱论断 / 人群缺口 / 高风险依赖 |
| [04-codex-claude-reconciliation.md](04-codex-claude-reconciliation.md) | Codex 技术架构稿与 Claude 机构级研究包的分歧裁决 · 最终合成方案 · 回写清单 |
| [05-paper-to-strategy-and-model-management.md](05-paper-to-strategy-and-model-management.md) | 论文/文章/研报/模型论文输入 → 策略抽取 → DL/ML 模型卡/护照 → 训练/验证/晋升/监控的 Agent OS 扩展 |
| [06-divergence-deepdive.md](06-divergence-deepdive.md) | 8 处分歧的深挖裁决（独立 workflow，全 holds/high）· 操作级落地 · `⚠️待裁定/待核实`隔离区（配套 04，不取代） |
| [07-codex04-conflict-ledger.md](07-codex04-conflict-ledger.md) | **Codex-04 vs Claude 研究包冲突账本**：22 条按 A/B/C+根因+自相矛盾分组（独立 workflow，代码锚点已核）· 每条带裁断+处理动作（不动 04） |
| [08-llm-factor-generation.md](08-llm-factor-generation.md) | **LLM 方向引导因子生成前沿**（独立 workflow，论文+源码核实）：代表系统表 · 泼冷水证据(记忆/look-ahead 污染) · SOTA 架构 · 对引导式探索 loop 的接线 · 两条必加设计 |
| [99-research-appendix.md](99-research-appendix.md) | 17 流证据：机构标准 · 关键论文(带URL) · SOTA · 差距 · 建议 · 核查裁决 |

---

## 执行摘要

**QuantBT 今天是一箱高质量的零件，还不是一件乐器。**

它已经拥有大部分机构级方法学的**零件**——DSR / PBO(CSCV) / Bootstrap Sharpe CI、Purged k-fold + Embargo、因子五态机、`dev→staging→production` 模型注册表 + run 级 lineage、regime 检测、严格 walk-forward 训练台、L1–L4 渐进披露。但**这些零件没有被装配成一条"不可绕过的脊柱"**，把一个非技术用户从"一个模糊念头"承载到"一个被治理、可问责的实盘策略"。

目标终态是**一条持久的、确定性的治理漏斗**：

```
假设预注册 → 数据 → 因子/标签 → 模型 → 信号 → 组合 → 独立验证 → 审批门 → 资本配置 → 实盘漂移监控 → 衰减/退役
```

——把它渲染成一张**工作流 DAG**，每个节点带持久 checkpoint 与 human-in-the-loop 中断。**Agent 是填满每个节点的手**（拉数/清洗/写因子/训模/验证/接执行），**人只在硬闸门处出意图与经济 go/no-go 判断**。

对目标人群（小白与不懂代码的经济学者）而言，**"流程即信任"**：他们永远读不懂 DSR 代码，所以信任只能来自 **可复现 + 谱系(provenance) + 预注册 + 一个他们能看见在"争论"的独立验证者 + 受众分层的经济学翻译**。

---

## 6 个已验证的洞（完备性复核独立对源码二次确认，全部属实）

| # | 洞 | 源码证据 |
|---|---|---|
| 1 | **agent 自主不在治理导轨内** | `agent_runtime.py` 是单线程 reAct（`max_steps=6`），无 checkpoint / interrupt / 跨 turn 记忆，且**完全不引用** `dag/engine.py`；后者也无 approve/interrupt/checkpoint 原语 |
| 2 | **过拟合体检三件套没有生产调用方** | `eval/dsr.py`、`pbo.py`、`bootstrap.py` 在 `main.py` 的 run 路径上**从不被调用**；`main.py` 只调 `compute_risk_summary()`，而它只是按 key 名读取预先算好的 metric 字符串——GOAL §6.1"每个 run 自动体检"**并未真正接线** |
| 3 | **多重检验记账是空的** | `n_trials` 是用户手填的整数（`tool_schema.py:170`），从不沿谱系自动累加 → 试验数 N 一旦低报，所有多重检验校正归零 |
| 4 | **晋升是无门的裸状态切换** | `ModelRegistry.promote()`（`store.py:232`）+ `/api/models/{id}/promote`（`main.py:405`）是三行状态翻转，无 approver、无独立验证记录、无过拟合证据快照 |
| 5 | **没有可证伪假设层** | `StrategyGoal`（`strategy_goal.py:92`）无 `economic_mechanism` / `falsification_condition` / `stop_rule` 字段，仍是纯参数化 |
| 6 | **严谨度只到"出权重"就停** | 真实回测路径用 top-N 等权 + `shift(1)` + flat-bps 成本（`_cost_for_trade` L187-193 无视已声明的 `impact_model`/订单规模/ADV/funding/borrow），而整个 M8 优化器层**无任何调用方** |

> 修复顺序的根判断：**先建脊柱**（确定性 DAG + 持久 HITL + 谱系 + 假设卡 + 诚实-N + 自动接线的过拟合闸门 + 独立验证者），**再把方法学纵深逐步回填到脊柱上**（CPCV、conformal/abstain、live 变点监控、meta-allocation、InstrumentSpec/日历），**最后让每个闸门都讲 L1–L4 经济学**，让非程序员靠判断、而非靠读代码来签 go/no-go。

---

## 跨组贯穿主题（四组共识）

1. **流程即信任是命门**：读不懂代码的用户只能靠 可复现 + 谱系 + 预注册 + 独立验证闸门 + 受众分层经济翻译来 go/no-go；这条信任脊柱目前缺统一技术底座，是第一性缺口。
2. **把 agent 自主收敛进确定性治理导轨**：A 组的编排原则、B 组的治理漏斗、C 组的证伪协议引擎、D 组的可签字经济判断，本质是同一动作——确定性 DAG 作轴，LLM 自主性限定在节点内。
3. **"有零件无装配"是系统性病灶**（已逐文件核实）：DSR/PBO/Bootstrap 无生产调用方、M8 优化器整层无调用方、Ledoit-Wolf 仅作 HRP fallback、Brinson-Fachler 已实现却只在回测态——价值不在再造零件，而在**接线成闸门**。
4. **试验计数 N 必须从"人手填"升级为"系统自动记账"**：低报 N 让所有多重检验校正形同虚设——这是低工程量、最高杠杆的单点。
5. **因果先行 / 可证伪假设是唯一入口闸门**：`StrategyGoal` 抬升为带 `economic_mechanism + falsification_condition + stop_rule` 的预注册假设卡，碰最终验证集前冻结、HARKing 留痕。
6. **独立验证（SR 11-7 有效挑战 / 职责分离）需 agent 原生化**：一个与生成方分离、异模型/异种子/异数据切片、对照预注册计划、有权 block 的 verifier/critic 节点——让非程序员"看见对抗而非看见代码"。
7. **闭环断在上线那一刻**：回测/PBO/DSR/归因都是上线前一次性脚本，缺 live 端用同一把尺子持续打分（minTRL/PSR-live/CUSUM/Page-Hinkley）+ 漂移→降级/退役回路 + 问责链。
8. **资产无关靠声明式接入而非硬分支**：当前 `AssetClass` 是封闭 `Literal`、按 `asset_class` 硬分支、无 `InstrumentSpec`/日历/合约规格——硬约束"加品类=填配置"要求把数据/执行/资产元数据改造为声明式注册表。
9. **渐进披露是信任翻译的最后一公里**：每个统计闸门配 L1 一句话经济叙事（赌哪个风险溢价/何时失效）+ 红黄绿过拟合体检 + 反事实 + go/no-go 卡片；`RunDetailPage` 已冻结，治理/谱系/TCA 叙事必须做新页面。
10. **反谄媚 + 现实检验前移**：现有 coach 偏顺从、`risk_summary` 仅作用于回测之后；需在澄清阶段就温和证伪"让 AI 帮我择时跑赢大盘"。
11. **文献不是代码生成燃料，而是受治理的研究证据源**：用户上传论文、研报、网页、模型文章后，系统必须先经过 `SourceDocument → EvidenceSpan → ExtractedStrategySpec / ExtractedModelClaim → PreRegistration / ModelTypeCard`，再进入训练和验证；外部文本不能直接触发 tool call、训练、模型加载或晋升。
12. **DL/ML 模型管理要从“训练文件”升级为“受管模型资产”**：模型类型卡仍是事实源，新模型默认 `runnable:false`；每次训练必须产 `TrainedModelPassport + ArtifactManifest + ValidationDossier + ApprovalEvents + MonitoringProfile`，并经 gated promotion 取代裸 `ModelRegistry.promote()`。

---

## 重要：用词已按对抗式核查降权

对抗式核查抓出多处夸大并已在综合层纠正——引用时须保留这些限定：

- **"谱系→恰当信任""经济语言→更好决策"是待验证假设**（配反向校准检查），不是定论。
- **DSR 修正是"标度修正"**（False Strategy Theorem 缺横截面 SR 方差项），**不是"修复系统性低估"**——误差符号取决于真实横截面方差。
- **FDR/Romano-Wolf 不"解决"发表偏误**（Chen-Zimmermann：发表偏误下 t-hurdle 不可识别），作辅助证据而非唯一判据。
- **拥挤/动态缩量**的关键实证支柱（arXiv 2512.11913）**已被作者撤稿** → 先做监控告警，不触发自动降级。
- **pod 级 kill/scale 阈值 5%/7.5% 为二手数字** → 做成用户可配置软参数，不硬编码。
- **平方根冲击律有 AQR 争议** → 接线时标注不确定，做敏感性区间。
- **CPCV 仅在合成受控环境"显著优于"walk-forward** → 定位为"更强默认"而非铁律，与 WF 双轨保留。
