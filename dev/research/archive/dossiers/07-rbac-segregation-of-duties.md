# 07 · 单机本地优先下的 RBAC / 职责分离

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 A

## 1. 一句话定位

在单台、属主完全可控的机器上（开放的 DuckDB / Parquet、属主拥有管理员与物理访问权限），RBAC / 职责分离（SoD）在**安全意义上不可技术性强制**——属主本人就在可信计算基（TCB）之内，任何"角色墙"对属主而言都是策略 / 体验框架、而非控制点，可通过直接改库或改代码绕过；因此本环节的可达目标不是"防篡改（tamper-prevention）"，而是**"防篡改证据（tamper-EVIDENCE）" + 生成职能与验证职能的结构性分离**，而这恰好就是监管真正要求的东西（SR 11-7 的"有效挑战，以行为与结果论之"）。

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 它提供什么 | 对本设计的意义 | 链接 |
|---|---|---|---|
| **SLSA Source Track（L1–L3）** | 关于"技术性强制 vs. 仅声明"最干净的现有模型：高等级要求声明的控制（分支保护、签名复核、状态检查）被"对每次提交持续强制并出具证明"，配合 in-toto / VSA 的密码学来源证明。两方复核是凌驾于等级之上的独立策略层。 | 是"强制分离"长什么样的概念模板——**但其强制力前提是存在一个开发者无法编辑的托管信任域（平台）**，纯本地机器恰恰缺这个域。 | https://slsa.dev/spec/v1.0/levels |
| **Git 签名提交 + 受保护分支 / 强制复核（GitHub / GitLab）** | 四眼原则对"工件变更"的主流技术实现：签名绑定作者身份；分支保护机械性地阻止自合并与未复核合并。 | 强制力**驻留在服务器而非开发者笔记本**——正是单机本地优先设计必须正视的信任域依赖。 | https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification |
| **Maker-checker / 四眼工作流引擎**（核心银行系统、SAP、Devolutions RDM、Flagsmith 特性开关） | 生产级 SoD：制单人（maker）创建、复核人（checker）授权，系统拒绝同一身份兼任并记录配对。 | 我们"先生成—后批准"门的范式模板——**但有文献记录其会退化为橡皮图章 / 审批疲劳**，除非复核被强制为实质性并轮岗。 | https://en.wikipedia.org/wiki/Maker-checker |
| **防篡改追加写审计账本**（hash-chaining / Merkle；如 HARDLOG；以及 QLDB 式设计【见第 7 节降权】） | 在属主可控机器上对"防止"的现实替代品：密码学哈希链让对生命周期记录的任何回溯性编辑变得**可检测**，尽管拥有完整权限的本地属主仍能重写状态。 | "能改系统的人不应能悄悄改那些改动的记录"——作为证据可达，作为硬墙不可达（无外部锚定时）。 | https://www.microsoft.com/en-us/research/wp-content/uploads/2022/04/hardlog-sp22.pdf |
| **能力本位安全 / POLA**（对象能力模型、macaroons） | RBAC/ACL 的替代物，用于约束自主 Agent：不可伪造的令牌按资源授予最小权限，从结构上规避"混淆代理（confused deputy）"问题。 | 替用户行事的 Agent 是教科书级混淆代理；按资源的能力比粗粒度 RBAC 角色更适合给 Agent 的工具 / 出口权限做闸门——**但"结构性消除"是夸大，见第 7 节**。 | https://en.wikipedia.org/wiki/Capability-based_security |

## 3. 关键论文（每条带 URL）

- **《Supervisory Guidance on Model Risk Management》（SR 11-7 附件），Federal Reserve & OCC，2011-04-04** — 本卷的承重引用，已逐字核对本地副本（`sr117.txt` 第 443–456 行）。原文（译）："验证应有一定程度的独立性……一般而言，验证应由不负责开发或使用、且对模型是否被判定为有效不存利害关系的人员进行……独立性本身不是目的，而是有助于使激励与验证目标对齐。**虽然独立性可由汇报线分离来支撑，但应以行为与结果来判断，因为还有其他确保客观、防止偏见的方式。实务上，部分验证工作或许由模型开发者与使用者来做最为有效；然而至关重要的是，此类验证工作须接受独立方的关键性复核**……"——这是监管者明确许可"无组织架构墙"的情形，以"有效挑战、以结果论之 + 补偿性控制（限额、保守化、文档）"替代不切实际的完全分离。 https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107.htm
- **《Revised Guidance on Model Risk Management》（SR 26-2），Federal Reserve，2026-04-17** — 保留"有效挑战……足够独立以维持客观……组织地位与影响力"，并围绕"潜在利益冲突（如开发组与验证组之间激励错配）"构建角色。对我们至关重要的脚注（已逐字核对 `sr262.txt` 第 215 行）：**脚注 3 把生成式 AI 与 Agentic AI 明确划出适用范围**（"novel and rapidly evolving... not within the scope of this guidance"），并称此类系统的控制须由机构自身风险管理来决定——即**迄今没有监管者为"Agent 自建 + Agent 自验"的流水线背书，这个空白要我们自己填**。 https://www.federalreserve.gov/supervisionreg/srletters/SR2602.pdf
- **《The Probability of Backtest Overfitting》（Bailey, Borwein, López de Prado, Zhu）+《The Deflated Sharpe Ratio》** — 确立了"在量化里为何必须把生成与验证分开"：在众多配置上搜索几乎必然产出一个样本内赢家、而它在 OOS 上跑输（选择偏差 / 研究者自由度）。CSCV 法的 PBO 与 Deflated Sharpe（针对试验次数、偏度、峰度、样本长度做调整）就是该被强制走一遍的"独立验证器"——**且 Agent 不应能调它**（此句强度见第 7 节降权：DSR 的核心输入 N 本身可被博弈）。 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- **《Self-Preference Bias in LLM-as-a-Judge》（arXiv:2410.21819）及后续** — Agent 给自己的输出打分在结构上不成立的直接证据：LLM 评审系统性地偏好自己的生成。**重要再解读（第 7 节）**：原文将此效应归因于**低困惑度 / 熟悉度**（"无论输出是否自生成"），而非身份本身——这部分削弱了"换个模型 / 种子当验证器就能解决"的推论。 https://arxiv.org/abs/2410.21819
- **可信计算基（TCB）—— 引用监视器（reference monitor）概念（综述 / 百科级）** — 诚实的天花板：访问控制只有在"受信任域与不受信任域之边界"上才是真实边界。在属主拥有管理员 / 物理访问权的单用户机器上，属主在 TCB 之内，故同一人控制的两个"角色"之间的 RBAC/SoD 是策略 / 体验、而非强制，可通过改库 / 改代码绕过。 https://en.wikipedia.org/wiki/Trusted_computing_base

## 4. 机构最佳实践 / 标准

- **以"有效挑战"取代"组织架构独立"**：独立性是手段，以行为与结果论之；部分验证可由开发者完成，**前提是随后接受独立方的关键性复核**。这是单操作员设置以"流程 + 补偿性控制"而非"人员墙"满足 SoD 的监管许可。来源：Federal Reserve / OCC SR 11-7（2011）。 https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107.htm
- **三道防线 + 开发与验证间显式的利益冲突映射；严谨度按重要性 / 复杂度分级**（小而简单的业务无须套同等严谨度）。延续到 SR 26-2（2026），后者亦将 Agentic / 生成式 AI 的控制交还给机构自身治理。来源：Federal Reserve SR 26-2（2026）。 https://www.federalreserve.gov/supervisionreg/srletters/SR2602.pdf
- **人手不足时的补偿性控制**：第三方独立对账、对全部交易的强制管理层复核、超阈值双重授权、突击审计、强制休假 / 轮岗、自动异常报告。**明确承认这对"有决心、有知识的内部人"并非万无一失**（残余风险仍在）。来源：ACFE 取向的审计实务（如 Bonadio 补偿性控制指南）。 https://www.bonadio.com/article/addressing-internal-control-gaps-compensating-controls-for-lack-of-segregation-of-duties/
- **NIST AI RMF（GOVERN 职能）**：记录谁有权开发 / 部署 / 监控；按风险等比例构建人类监督；保持决策可追溯，使责任不被稀释——即角色问责可以"可记录、可追溯的治理"形态达成，纵使没有硬技术墙。来源：NIST AI Risk Management Framework 1.0。 https://www.nist.gov/itl/ai-risk-management-framework
- **OWASP Top 10 for Agentic Applications（2026）**：把"过度自主（Excessive Agency / Excessive Autonomy）"视为根本风险；对权限提升、对不可逆 / 财务 / 改状态动作要求人在环；动作级批准配 dry-run / 预览；按工具的最小自主画像；JIT 临时凭证。**把审批门专门映射到高影响动作（即实盘执行），而非每一步**。来源：OWASP Top 10 for Agentic Applications（2025–2026）。 https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications/
- **López de Prado "元策略 / 流水线" 范式**：把研究生命周期切成各工位，其质量被**独立度量与监控**，明确让"策略发现者"不等于"策略验证者"——量化里"生成 / 验证分离"的组织设计化身。来源：M. López de Prado《The 10 Reasons Most Machine Learning Funds Fail》/ Quantitative Meta-Strategies。 https://www.smallake.kr/wp-content/uploads/2018/07/SSRN-id3104816.pdf

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅给方向与原则，不点 file:line、不排实施计划。

1. **放弃"属主无法绕过的 RBAC"这个目标，并把它写明。** 在单台属主可控机器上用户在 TCB 内，"批准者不能是创建者"对该用户不可密码学强制。把这条作为**显式书面假设**，而非暗示的安全保证。可达属性是**防篡改证据 + 结构性分离**，按这个口径来设计与对外表述。
2. **以 SR 11-7 的"有效挑战、以结果论之"为统御概念，而非组织架构独立。** 把**职能（生成 vs. 验证）**分成两个独立、命名、各自有记录输出与预注册验收标准的生命周期工位——监管明确允许开发者执行验证工作，只要随后接受独立的关键性复核。我们"流程即信任"的命题字面上就是 SR 11-7 的标准。
3. **让"生成 Agent"与"验证 Agent"在结构上是不同主体。** 回测过拟合（PBO / Deflated Sharpe）与 LLM 自偏好偏差都指向"搜索者不能给自己的赢家盖章"。用不同模型 / 种子 / 留出集（或人类闸门）做验证，并**预注册 OOS 协议与阈值**，使生成方看不到也调不动。验证器的留出数据与验收门，相对某一具体策略应"写一次即定（write-once）"。（注意第 7 节：自偏好机制可能是"低困惑度"而非身份，故两个不同 LLM 可能共享同一盲点——独立性需要被度量，不能假定。）
4. **预注册分离，使之无法被悄悄挪动。** 在生成开始前，把验证协议、OOS 窗口、多重检验预算（试验次数）、通过 / 不通过阈值做哈希链承诺。这里的 SoD = "规则在结果已知之前就已固定"——即便在单机上也作为**证据**可强制，直接对冲研究者自由度滥用。（第 8 节存疑点：本地承诺机制本身也需要在注册时刻向外锚定，否则一样软。）
5. **把每个生命周期事件写入哈希链、追加写账本，并向独立信任域锚定。** 本地哈希链给可检测性；周期性把链头锚定到远程 / 透明日志（或带时间戳的外部回执）是让属主的回溯篡改"可被第三方检测"的最廉价办法。（第 7 节降权：外部锚定只是抬高代价、不是干净的修复；它防不了"选择性不记录"与"锚定前篡改"。）
6. **把唯一的硬墙放在实盘出口，而非研究流程里。** 我们已有的唯一真实独立信任域是 Binance 侧（远程场所 + 密钥托管）。在那里以能力作用域、最小权限、短时效凭证给不可逆 / 财务动作设闸，并以"独立验证证明"作为放行订单的前置条件。A 股到 paper 没有真实资金出口，其"强制"在诚实意义上**仅为证据性**——要说明白。（第 7 节：Binance 这堵墙也被过度信任——API key 在属主机器上，没有 HSM/TPM 或第三方共签则只如本地密钥托管那样强；真正的强制原语是交易所侧的子账户限额 / 交易专用且 IP 白名单的 key / 仓位上限。）
7. **给 Agent 用能力 / POLA 作用域，而非粗粒度 RBAC 角色。** 给它不可伪造、按资源、最小权限的能力（如"读此数据集""写此 run""请求—而非执行—一笔实盘订单"），以**约束**过度自主与提示注入的爆炸半径。（第 7 节：在属主可控盒子上，能力库本身也是属主可改的——这一层逃不出别处已承认的 TCB 天花板。）
8. **把人类审批门设计成抗橡皮图章、抗审批疲劳**——这是四眼原则有记录的失效模式，对非技术用户尤甚。把强制人签字保留给少数高影响、不可逆决策（上实盘、提高风险限额、推翻一次失败的验证）；呈现**决策级摘要**（什么通过、什么失败、残余风险、为何）而非裸的"批准"按钮；强制"带理由的推翻（override-with-reason）"并把它本身记日志。许多低风险步骤应按预注册策略**自动放行**，而非生成同意提示。
9. **把分离规则编码为策略即代码**（如 OPA/Rego），在晋升 / 部署门处求值："无通过独立验证证明（由验证者角色签名）不得晋升""创建者密钥 ≠ 批准者密钥""若试验数超预注册预算或 Deflated Sharpe 不过则阻断上实盘"。可审计、可测试、对复核者可读——同时诚实承认执行它的宿主仍是属主可控的。
10. **把整套控制定位为"执行左侧靠证据治理、唯执行处靠强制治理"。** 这种两层诚实是单用户本地优先 Agentic OS 可辩护的机构立场：它以可追溯、预注册、防篡改的流程满足 SR 11-7 式"有效挑战"预期，而把"真正强制"的主张保留给那唯一存在独立信任域的边界（远程执行 / 托管）。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅示意概念形态，不接线到现有代码。

**(a) 预注册承诺（生成开始前固定，结果未知）：**

```yaml
preregistration:                 # 哈希链入账本，理想情况下注册时刻即向外锚定
  strategy_search_id: "ss-2026-0615-A"
  trial_budget: 200              # 多重检验预算（DSR 的 N 输入）
  oos:
    protocol: "walk-forward, train_fraction=0.6, shift=1"
    windows: ["2018-01..2021-12", "2022-01..2024-12"]
    holdout_hash: "blake3:…"     # 验证器留出集，相对本次搜索 write-once
  acceptance_gates:              # 生成方看不到也调不动
    deflated_sharpe_min: 0.0
    pbo_max: 0.5
  committed_at: "2026-06-15T..Z"
  anchor_receipt: "rekor:…"      # 见 §5-4 存疑：本地时钟可控时此锚定才有约束力
```

**(b) 生命周期事件账本（哈希链、追加写、防篡改证据）：**

```
record {
  seq, prev_hash, this_hash      # hash-chain：编辑可检测、不可防止
  event: GENERATED | VALIDATED | PROMOTED | LIVE_ORDER_REQUESTED | ...
  actor: { role: generator|validator|human, key_id }   # 创建者密钥 ≠ 批准者密钥
  refs: { dataset_hash, code_hash, prereg_id }          # §8 缺口：账本只引用、不保证被引对象的完整性
  verdict?: { dsr, pbo, passed }
  ts
}
# 周期性把 head_hash 锚定到远程透明日志 → 第三方可检测回溯篡改
# 已知攻击（§7/§8）：选择性不记录（omission）此机制检测不到
```

**(c) 晋升 / 出口门（策略即代码，概念示意）：**

```rego
# 无通过独立验证证明不得晋升
deny[msg] { input.action == "promote"; not input.attestation.validation.passed
            msg := "missing passing independent-validation attestation" }
# 创建者不得自批
deny[msg] { input.action == "promote"; input.actor.key == input.creator.key
            msg := "creator-key must differ from approver-key" }
# 超预注册试验预算则阻断上实盘
deny[msg] { input.action == "go_live"; input.trial_count > input.prereg.trial_budget
            msg := "trial budget exceeded vs pre-registration" }
```

**(d) 唯一硬墙（实盘出口，仅此处为真强制——且依赖交易所侧原语）：**

```
release_live_order(order):
  require capability("request_live_order")    # 最小权限、短时效
  require attestation(validation.passed AND prereg.satisfied)
  # 真正的强制不在本地代码，而在交易所侧：
  #   子账户限额 / 交易专用 key+IP 白名单 / 仓位上限（§7 缺口：本研究未提及）
  submit_to_binance(order)
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词**原样保留**。总裁决：**部分维持（PARTIALLY UPHELD）**——中心命题存活，但若干支撑性引用比所呈现的更弱、更陈旧或属虚构。承重的监管内核**真实且经本地副本逐字核对**（SR 11-7 第 443–456 行、SR 26-2 脚注 3 第 215 行），TCB 天花板论证与混淆代理 / 能力框架在教科书层面正确，骨干不坍塌。但需把若干具体机制的置信度从"已确立"**下调为"真实但有争议 / 有条件"**。

**降权（按严重度）：**

- **【high — 虚构引用】** 自偏好"理智检查"论文 **arXiv:2601.22548 并不存在 / 属幻觉**（2601.xxxxx 会是 2026-01 投稿；未找到该论文）。真正的反证工作是 **arXiv:2506.02592《Beyond the Surface: Measuring Self-Preference in LLM Judgments》（EMNLP 2025）** 与 **arXiv:2604.22891《Quantifying and Mitigating Self-Preference Bias of LLM Judges》**。**方向正确、引用错误**——而这条恰是承担"我已核对反证"作用的承重脚注，引一个不存在的 ID 是削弱其他引用可信度的核查失败。
- **【medium — 再解读】** "LLM 自偏好偏差……GPT-4 可量化地偏好自己输出……见诸广泛区间"——主引用 arXiv:2410.21819 真实且确发现 GPT-4 自偏好，**但原文把效应归因于低困惑度 / 熟悉度而非身份本身**（"无论输出是否自生成"）。该机制**部分溶解了 SoD 论证**：换种子 / 换模型的验证器若共享同一低困惑度偏好，未必去除偏差。"见诸广泛区间"是无数字的含糊措辞——发现存在，但其量级及其对"生成器 vs. 验证器分离"的具体相关性，比行文暗示的更弱、更有争议。
- **【medium — 存疑 / 有条件】** "CSCV 的 PBO 与 Deflated Sharpe 是该被强制走一遍的客观独立验证器"——DSR 的修正**关键性地依赖有效独立试验数 N**，而当试验相关（特征重叠）时 N 极难估计（López de Prado 本人为此提出多种聚类启发式）。故把 DSR/PBO 呈现为"干净、不可博弈、生成方调不动的独立验证器"是**夸大**：N 本身是研究者选定、可被博弈的输入，对抗性生成方可把表观试验数压低。真实，但比"搜索者不能给自己的赢家盖章"所暗示的要软。
- **【medium — 夸大】** "用能力 / POLA……结构性消除混淆代理问题……结构性约束"——能力 / 对象能力系统**缓解**混淆代理、确实优于环境权限 ACL（Hardy 1988；Miller《Capability Myths Demolished》），但文献明确该保护"取决于正确实现"且能力并非完整的访问控制方案。"结构性消除 / 结构性约束"把它夸成了保证；在属主可改能力库的属主可控 DuckDB/Parquet 盒子上贴一层能力，会落入与别处正确承认的**同一个属主绕过问题**——能力框架逃不出它别处承认的 TCB 天花板。
- **【low — 陈旧 / 死服务】** "防篡改追加写账本……如 HARDLOG、AWS QLDB 式设计"——**AWS QLDB 已于 2025-07-31 退役**，是死服务；AWS 自荐迁移目标（Aurora PostgreSQL）明确**不保留永久不可变记录**（历史须导出并外部存储）。把"QLDB 式设计"当作当下 SOTA 范例而不注明弃用，是陈旧且对现成本地不可变账本选项的成熟度略有误导。
- **【low — 二手 / 民间传说级证据】** "四眼 / maker-checker 被广泛记录会退化为橡皮图章、审批疲劳、横幅盲视与合谋"——方向性主张可信且符合直觉，但所定位的支撑证据**压倒性地是厂商博客、维基百科与网络安全营销贴，而非针对金融 SoD 四眼退化率的同行评议实证**。设计结论（人签字保留给高影响、强制带理由推翻）站得住，但"广泛记录"暗示了一套这些来源实际并未确立的实证文献；属**行业民间传说级证据**。
- **【low — 版本 / 引用不符】** "SLSA v1.2 Source Track（L1–L3）……最干净的模型"——行文写"v1.2"但所给 URL 是 slsa.dev/spec/**v1.0**/levels；Source Track 及"对可达集中每次提交持续强制并出具证明"的 L3 措辞属较新 / 草案框定，**非链接所指的稳定 v1.0 规范**。概念点（强制力前提是独立托管信任域）正确，但版本标签未经核实，引文被当作既定规范文本呈现而其至多是草案。
- **【low — 夸大】** "Rekor / 远程透明日志是把本地防篡改证据变成属主无法悄悄重写之物的那一个机制"——作为干净修复被**夸大**。外部锚定只证明链头在时刻 T 存在；属主仍可维护一条与已锚内容自洽的平行 / 重生链、可选择**锚定什么（遗漏攻击）**、可停止锚定。它抬高悄悄篡改的代价、为已锚事件增加第三方可检测性，但"无法悄悄重写"过强——它防不了选择性不记录或锚定前篡改，而对 Agentic 流水线而言后者比事后编辑更现实。
- **【low — 标记为优点，非降权目标】** "对单用户 Agentic 量化 OS 的具体应用是我的综合 / 外推，尚无标准认证"——此限定诚实且正确，**列此为优点**。SR 11-7 逐字引用与 SR 26-2 脚注 3 划出范围均已对本地副本核对、准确无误；记此以免裁决被误读为质疑监管内核，该内核站得住。

## 8. 开放问题

- **针对"有决心、有知识的属主"的内部威胁 / 取证文献缺位**：研究倚重"防篡改证据"，却从未正面处理**遗漏攻击**（Agent / 属主干脆从不把不便的事件写进账本）。哈希链与锚定检测的是对**已记录**事件的编辑，而非**从未被记录**的事件。对一个自管其自身仪表化的 Agentic 流水线，选择性不记录是主导攻击，却几乎未被处理。
- **威胁模型混淆了三种不同对手**：(a) 防自己未来自欺 / 过拟合的诚实属主、(b) 粗心属主、(c) 意图蒙骗未来合规 / 审计复核者的恶意属主。"靠证据治理"的几乎全部价值只对 (a) 及"日后会复核的外部方"存在；对没有外部复核者的恶意属主，它就是表演——研究半承认了但从未围绕此构建设计。
- **无成本 / 收益或威胁优先级排序**：防篡改账本的受众是谁？若不存在任何会去验证 Rekor 锚定的外部审计师、监管者或未来投资者，整套锚定装置就**零安全价值、纯仪式**。设计从未指明**谁会去核对证据**——而这恰是决定这一切是否值得建造的问题。
- **账本之下的数据与代码可变性（TOCTOU）**：即便一份完美的"在数据集哈希 H 上以协议 P 通过验证"账本，若属主能重生数据集 H、把底下的 DuckDB/Parquet 换掉、或打补丁让验证器二进制把"协议 P"悄悄改义，也一文不值。研究把账本当作完整性根，却从未处理它**仅引用**的数据与代码本身的完整性。
- **"不同模型 / 种子 / 留出集验证器"忽略跨模型的相关偏差**：2410.21819 的机制（低困惑度偏好）与训练数据重叠意味着两个不同 LLM 可共享**同一盲点**，故"独立验证 Agent"提供的独立性可能远少于组织架构类比所暗示的。如何在模型空间度量 / 保证验证器独立性，未被讨论。
- **预注册的承诺机制在单机上未被检视**："生成前哈希链承诺协议"只有在 (a) 属主无法用回填锚定重生预注册、且 (b) 有人去核对时才约束属主。在本地时钟可控的全本地盒子上，"已预注册"与其它一切一样软，除非在注册时刻即向外锚定——研究把锚定修复用在结果账本上，却没对称地用在预注册本身上。
- **Binance 作为"唯一真实硬墙"被过度信任**：交易所 API key 就在属主盒子上（或属主可控的 keyring 里），故研究称为真正强制的出口边界，只如**本地密钥托管**那样强——而那是研究别处说属主可控的东西。没有真 HSM/TPM 或第三方托管 / 共签，Binance 墙比宣称的弱；场所拒绝畸形订单，但无法强制"此订单已被独立验证"。交易所侧控制（子账户限额、交易专用 / IP 白名单 API key、仓位上限）才是真正的强制原语，却**只字未提**。
- **完全没碰 A 股监管制度**：整个模型风险框架是美国的（SR 11-7 / SR 26-2 / NIST / OWASP）。对 A 股到 paper 这一支，相关治理规范（CSRC / 境内算法交易与程序化交易报告规则）完全缺位，纵使研究自身范围横跨 A 股。把 paper 路径一句"仅为证据性"打发，跳过了"是否有任何境内规则适用"。
- **抗橡皮图章"决策级摘要"的可用性 / 行为经济学证据基础是假定而非引用**："更丰富的摘要能击败审批疲劳"这一主张本身就是一种可设计出的失效模式（更长的摘要可能**加重**疲劳 / 诱发略读即批准）。未引用能判断该门是否真改变行为的人因学文献。
- **硬墙的活性 / 可用性**：若实盘执行要求"以独立验证证明为放行订单前置条件"，那当验证器宕机、锚定服务不可达、或行情正在移动时怎么办？研究从未处理它称为承重的那唯一边界上的 **fail-open vs. fail-closed** 取舍——这对交易系统是真实运营风险。

## 9. 参考文献（URL）

**监管 / 标准**
- SR 11-7《Supervisory Guidance on Model Risk Management》（Fed/OCC, 2011）：https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107.htm （附件 PDF：https://www.federalreserve.gov/supervisionreg/srletters/sr1107a1.pdf ；承重引用经本地 `sr117.txt` 第 443–456 行核对）
- SR 26-2《Revised Guidance on Model Risk Management》（Fed, 2026-04-17）：https://www.federalreserve.gov/supervisionreg/srletters/SR2602.pdf （HTML：https://www.federalreserve.gov/supervisionreg/srletters/SR2602.htm ；脚注 3 经本地 `sr262.txt` 第 215 行核对）
- NIST AI Risk Management Framework 1.0：https://www.nist.gov/itl/ai-risk-management-framework
- OWASP Top 10 for Agentic Applications（2026）：https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications/ （另见 AI Agent Security Cheat Sheet：https://cheatsheetseries.owasp.org/cheatsheets/AI_Agent_Security_Cheat_Sheet.html ）
- 补偿性控制实务（Bonadio）：https://www.bonadio.com/article/addressing-internal-control-gaps-compensating-controls-for-lack-of-segregation-of-duties/

**论文 / 概念**
- Trusted Computing Base（引用监视器）：https://en.wikipedia.org/wiki/Trusted_computing_base
- The Probability of Backtest Overfitting / Deflated Sharpe Ratio：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253 （DSR 概览：https://en.wikipedia.org/wiki/Deflated_Sharpe_ratio ）
- López de Prado《The 10 Reasons Most ML Funds Fail》/ Meta-Strategies：https://www.smallake.kr/wp-content/uploads/2018/07/SSRN-id3104816.pdf
- Self-Preference Bias in LLM-as-a-Judge：https://arxiv.org/abs/2410.21819
- （反证 / 再解读）Beyond the Surface: Measuring Self-Preference in LLM Judgments（EMNLP 2025）：https://arxiv.org/abs/2506.02592 ；Quantifying and Mitigating Self-Preference Bias of LLM Judges：https://arxiv.org/abs/2604.22891
- （**已撤回 / 虚构**）arXiv:2601.22548 —— 不存在，勿引用；以上两篇替代

**SOTA 系统 / 工具**
- SLSA（版本标签存疑，见第 7 节）：https://slsa.dev/spec/v1.0/levels
- Git 提交签名验证（GitHub）：https://docs.github.com/en/authentication/managing-commit-signature-verification/about-commit-signature-verification
- Maker-checker / 四眼原则：https://en.wikipedia.org/wiki/Maker-checker
- HARDLOG（防篡改硬件账本）：https://www.microsoft.com/en-us/research/wp-content/uploads/2022/04/hardlog-sp22.pdf
- AWS QLDB 退役（陈旧参考说明）：https://www.infoq.com/news/2024/07/aws-kill-qldb/
- 能力本位安全 / POLA：https://en.wikipedia.org/wiki/Capability-based_security
- in-toto：https://in-toto.io/ ；Sigstore / cosign：https://www.sigstore.dev/ ；Rekor 透明日志：https://docs.sigstore.dev/logging/overview/
- Open Policy Agent（Rego）：https://www.openpolicyagent.org/
- MLflow Model Registry / 阶段门：https://mlflow.org/docs/latest/model-registry.html
