# 06 · Agent 安全模型（注入/越权/投毒/密钥托管）

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 A

## 1. 一句话定位

对一个"能下单的 agent + 实盘 key 在场 + 由非技术用户用对话驱动全生命周期"的机构级 Agent OS，安全必须**前移到脊柱（架构层）**而不能当 P5 的事后过滤——因为提示注入是 LLM 的结构性缺陷（不会像 SQL 注入那样被根治）、模型层防御在自适应攻击下不可单独依赖、且实盘交易所密钥绝不能进入 LLM 上下文。

---

## 2. 前沿 SOTA 与代表系统

### 2.1 CaMeL（Google DeepMind）— Defeating Prompt Injections by Design
- **范式**：用"特权 LLM"只读可信用户意图、生成一段代表任务的 Python 程序，由**定制解释器**执行；"隔离 LLM"处理不可信数据但无工具调用权。控制流/数据流从可信查询里显式抽取，不可信数据无法改变程序流。叠加 capability（能力令牌）在工具调用时强制安全策略、阻断越权数据外流。
- **真实头条指标（已对抗核查纠正）**：在 AgentDojo 上以**可证明安全的方式完成约 77% 的任务**（无防御基线约 84%），即安全-效用差约 7 个百分点。**注意：研究发现稿原写的"缓解 67% 注入"是错记/不存在的数字，已剔除**（详见 §7）。
- **为什么对我们重要**：是"安全前移到架构"的标杆范式，直接适配"人出意图、agent 出工程"的设计。**但 CaMeL 论文 §8.3 自承未根治注入，且需要用户编写并维护安全策略、同样存在反复审批导致的用户疲劳**——这一软肋与本研究用来攻击 human-in-the-loop 的 93% 审批疲劳是同一个，必须正面对待（详见 §7、§8）。
- URL: https://arxiv.org/abs/2503.18813

### 2.2 Meta Agents Rule of Two
- **框架**：在可靠检测注入之前，单个 agent 会话中三个属性——[A] 摄入不可信输入、[B] 访问敏感系统/私有数据、[C] 改状态或对外通信——**最多只能占两个**；三者都要则必须人在环。是 Simon Willison "致命三件套"的更广义版（涵盖状态篡改而非仅外泄）。
- **明确声明**：是 least-privilege 的补充而非替代。
- **对本项目的尖锐含义**：中低频策略天然同时需要摄入行情/新闻/研报（=A）+ 持实盘 key（=B）+ 自动下单（=C），Rule of Two 在本场景几乎**等于给"全自动自治下单"判死刑**——这是个必须诚实面对的两难（详见 §7、§8）。
- URL: https://ai.meta.com/blog/practical-ai-agent-security/

### 2.3 Meta SecAlign（偏好优化的模型层防御）
- **方法**：用含注入输入、安全输出、不安全输出的偏好数据做偏好优化，教模型偏好安全输出；benchmark 上把多种注入成功率压到 **<10%** 且对未见攻击有泛化。Meta SecAlign 是首个内置模型级防御的全开源 LLM。
- **定位**：纵深防御的一环，**非自适应攻击下的银弹**。注意：**不能据此暗示 SecAlign 已被《The Attacker Moves Second》打穿——核验显示该论文点名打破的是 Spotlighting / PromptGuard 等，并不包含 SecAlign**（详见 §7）。
- URL: https://arxiv.org/abs/2507.02735

### 2.4 AgentDojo（NeurIPS 2024 D&B）
- **环境**：评估工具调用 agent 提示注入攻防的动态环境，97 个真实用户任务 + 629 个安全测试，含 banking / slack / travel / workspace 四套件（**banking 套件与我们下单场景同构**）。
- **基线数字**：GPT-4o 良性效用约 69%，受攻击降至约 45%，"Important message"定向攻击成功率约 53%；加二级注入检测器可把攻击成功率降到约 8%（**属静态评估，见 §7**）。
- **用途**：可直接复用的攻防回归基准与 banking 套件。
- URL: https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html

### 2.5 HashiCorp Vault 动态密钥 / AI agent identity 模式
- **production 标准**：secrets manager 管凭证生命周期 + 动态短时凭证（几分钟有效的临时 token）+ OAuth2 token exchange 给 agent 自己的 scoped token；下游真实交易所密钥由后端/MCP 服务器侧取用，**绝不进 LLM 上下文**。提供完整审计与用户归因。
- URL: https://developer.hashicorp.com/validated-patterns/vault/ai-agent-identity-with-hashicorp-vault

### 2.6 Anthropic "How we contain Claude"（环境层硬边界范式）
- **三层纵深**：环境层（硬件强制边界）/ 模型层（概率性引导）/ 外部内容层。凭证留在宿主 keychain，guest 只拿 scoped session token。
- **关键实测**：用户对约 **93% 的权限弹窗点同意**（approval fatigue），故不可把安全寄托于人工逐次点头；对**不可逆动作优先用确定性环境边界而非模型层防御**；慎用自研组件，优先成熟 hypervisor / syscall 过滤。
- URL: https://www.anthropic.com/engineering/how-we-contain-claude

---

## 3. 关键论文（每条带 URL）

> 引用卫生说明：本环节已主动剔除可疑的未来日期 arXiv 编号（2602/2603/2604.xxxxx 这类——搜索中曾目睹野生 2602.07398 确属可疑），只保留逐条核验为真、无撤稿的来源。

1. **The Attacker Moves Second: Stronger Adaptive Attacks Bypass Defenses Against LLM Prompt Injection and Jailbreaks**（OpenAI / Anthropic / Google DeepMind 等联合）
   - 发现：对 12 个已发表防御用自适应攻击（梯度/RL/搜索）测试，多数被打到 **>90% 攻击成功率**，500 人人类红队达 **100%**。结论：静态样本评估几乎无用，"训练一个抗注入模型"目前不可依赖——强力支撑"安全须在架构层、不能只靠模型"。
   - ref: arXiv:2510.09023（经 Simon Willison 2025-11-02 综述确证）
   - URL: https://simonwillison.net/2025/Nov/2/new-prompt-injection-papers/

2. **Poisoning attacks on LLMs require a near-constant number of poison samples**（Anthropic × UK AISI Safeguards × Alan Turing Institute）
   - 发现：约 **250 篇投毒文档**即可在 600M/2B/7B/13B 模型植入后门，效果取决于投毒文档的**绝对数量而非占比**（13B 见 20× 干净数据仍同样被攻破）。
   - **对抗核查降权（重要）**：原文只验证了一种**最弱的攻击目标**——遇 `<SUDO>` 触发词就输出乱码的**拒绝服务（DoS）窄后门**，作者明确称这是"不太可能对前沿模型构成显著风险的窄后门"，并白纸黑字标注三重限制：(a) 尚不清楚同样动态是否适用于更复杂行为（如给代码植入后门或绕过护栏，前人已发现这些比 DoS 难得多）；(b) 不清楚趋势在 >13B 能否维持；(c) 该实验是**预训练投毒**，不能直接等同于 RAG 语料/agent 长期记忆/微调投毒。**应降级为：真实但目标受限的下界证据，不能据此断言能在下单 agent 里植入越权/泄密级后门。**
   - ref: arXiv:2510.07192
   - URL: https://arxiv.org/abs/2510.07192

3. **EchoLeak: The First Real-World Zero-Click Prompt Injection Exploit in a Production LLM System**（CVE-2025-32711, CVSS 9.3）
   - 发现：一封无需用户交互的邮件即让 M365 Copilot 读内部文件并外泄到攻击者服务器：绕过 XPIA 注入分类器、用引用式 Markdown 规避链接编辑、滥用自动取图与 Teams 代理 CSP 白名单。首个"被投喂文档/邮件触发→具体数据外泄"的**生产级**证据，证明检测器+链接编辑等点防御会被**链式绕过**。
   - ref: arXiv:2509.10540 / CVE-2025-32711
   - URL: https://arxiv.org/abs/2509.10540

4. **SecAlign: Defending Against Prompt Injection with Preference Optimization**（ACM CCS 2025）
   - 发现：首个把多种注入成功率降到 **<10%** 且对训练外攻击泛化的模型层方法。与《The Attacker Moves Second》并读可见"benchmark 强、自适应攻击下未必"的张力——**定位为纵深防御一环**。
   - ref: arXiv:2410.05451
   - URL: https://arxiv.org/abs/2410.05451

5. **AgentDojo: A Dynamic Environment to Evaluate Prompt Injection Attacks and Defenses for LLM Agents**（NeurIPS 2024 Datasets & Benchmarks）
   - 发现：见 §2.4 的基线数字；给出可直接复用的攻防回归基准与 banking 套件。
   - URL: https://openreview.net/forum?id=m1YYAQjO3w

6. **Prompt injection "may never be fixed" — NCSC 警告**
   - 发现：英国国家网络安全中心明确——提示注入不太可能像 SQL 注入那样被根治，因其源于 LLM 处理信息的固有方式。为"把高危下单动作建在确定性边界上而非寄望模型修好"提供权威背书。
   - **对抗核查降权**：这是**权威机构的观点性/政策性判断，不是可复现的实证结论**，证据等级上不应与实验证据完全并列；且研究发现稿只挂了 Malwarebytes **二手报道** URL，一手出处应是 NCSC 官网（ncsc.gov.uk/news/mistaking-ai-vulnerability...），The Record / CyberScoop / IT Pro 亦有独立报道。该指引为 2025-12 发布、时点较新。
   - ref: NCSC 2025（二手：Malwarebytes）
   - URL: https://www.malwarebytes.com/blog/news/2025/12/prompt-injection-is-a-problem-that-may-never-be-fixed-warns-ncsc

---

## 4. 机构最佳实践 / 标准

- **OWASP Top 10 for LLM Applications 2025**：LLM01 提示注入（连续两届第一）、LLM02 敏感信息泄露、LLM03 供应链、LLM04 数据与模型投毒、LLM05 不当输出处理、LLM06 过度自主（excessive agency，根因之一是 excessive functionality）、LLM07 系统提示泄露。LLM06 官方缓解 = 最小权限 + human-in-the-loop + 输出校验 + 限制自主动作范围。
  - https://genai.owasp.org/llm-top-10/

- **OWASP Agentic AI — Threats and Mitigations**（2025-02，首个 agentic 威胁建模参考）：T1 记忆投毒、T2 工具滥用、权限/身份相关威胁等；核心缓解 = 把 agent 当一等身份给 scoped 权限、所有代码执行沙箱化、认证 agent 间通信、多 agent 工作流装断路器、高影响决策保留人工监督。另有 2025-12 的 OWASP Top 10 for Agentic Applications。
  - https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/

- **NIST AI RMF**（GOVERN/MAP/MEASURE/MANAGE）+ Generative AI Profile（NIST AI 600-1, 2024-07-26，12 风险类、200+ 行动，含 Information Security / Information Integrity）；CSA 正构建 Agentic Profile，补充 agent 自主性、工具使用风险、运行时行为治理、委派链问责。
  - https://www.nist.gov/itl/ai-risk-management-framework

- **Five Eyes 联合 agentic AI 安全指南**（CISA+NSA+澳/加/新/英）：严格最小权限、强身份管理、密码学锚定凭证、明确角色、特权动作用即时（JIT）短时凭证、定期评估与输出校验；并入 zero-trust / defense-in-depth；安全须内建于起点。另有 NSA 2026-05-20 的 MCP 部署指南，点名序列化工具响应可携恶意载荷、跨多 MCP 服务器缺隔离。
  - https://cyberscoop.com/cisa-nsa-five-eyes-guidance-secure-deployment-ai-agents/

- **金融模型风险管理（MRM）**：原 SR 11-7 / OCC 2011-12 已于 2026-04-17 被 **OCC Bulletin 2026-13**（Fed/FDIC/OCC 跨机构联合，亦称 SR 26-2）以更显式的风险分级、原则导向框架取代；ML/算法仍属"模型"，要求按风险分级做独立验证、治理、文档与持续监控。
  - **对抗核查降权**：(1) 研究发现稿给的 URL 指向 `nr-occ-2026-29.html`（新闻稿编号 29），与"Bulletin 2026-13"**编号对不上**，正确公告页应为 `occ.gov/.../bulletin-2026-13.html`；(2) **适用性属外推**——MRM 监管约束的是"受监管银行机构"，本项目是单用户、A股到paper+加密到实盘的个人/小团队系统，把银行级 MRM 当成必须遵循的硬性合规基线是**把适用对象放大**；作为"可借鉴的治理精神"没问题。
  - https://www.occ.treas.gov/news-issuances/news-releases/2026/nr-occ-2026-29.html

- **交易所原生 key 护栏**：Binance API key 默认关提币；开提币权限硬性要求至少一个 IP 白名单；无 IP 限制的 key 90 天/30 天不活跃自动删除。提币地址白名单 + 新地址 24h 锁（Crypto.com / Coinbase Intl）。机构托管用 MPC/multisig + HSM + 目的地白名单/金额/时间规则的可编程审批。
  - https://developers.binance.com/docs/wallet/account/api-key-permission

- **Anthropic "How we contain Claude"**（见 §2.6）：三层纵深 + 93% 审批疲劳实测 + 不可逆动作优先确定性边界。
  - https://www.anthropic.com/engineering/how-we-contain-claude

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅给概念级方向，不点 file:line、不排实施计划。

1. **把"致命三件套 / Rule of Two"设成脊柱级不变量**。能下单的会话（持实盘 key = 敏感系统 + 能下单 = 改状态/对外）默认**禁止摄入不可信内容**（行情新闻、被投喂文档、RAG、agent 长期记忆）。需要这些数据时，放进**无工具权限的"隔离/分析"子 agent**，只回传结构化、受类型约束的结果，不让其改变下单控制流——这正是 CaMeL 范式，也最契合"人出意图、agent 出工程"。**诚实警示**：结构化回传**不是银弹**——隔离 agent 回传的数值字段（如被投喂新闻诱导回传一个偏高的信号分）仍可能被语义投毒，从而**合法地**改变下单决策。这是 data-flow 层防不住的"决策值污染"，对量化下单比控制流注入更致命（详见 §7、§8）。

2. **下单走确定性策略门而非模型自觉**。把限额、标的白名单、杠杆上限、最大回撤、单日换手、提币默认禁止等写成**会话外的确定性规则引擎（deny-by-default）**，agent 只能在门内行动；不可逆/超阈动作触发人在环或二人复核。**接线教训**：护栏必须接在**所有执行路径**（含中继/桥）——参照本项目 GOAL §8 跟单中继漂移（M17 幂等+杠杆上限曾被中继绕过），不能被某条路径绕过。

3. **密钥永不进 LLM**。实盘交易所密钥由后端 key broker（Vault/HSM）在 LLM 上下文之外保管，agent 只拿 **scoped、短时、JIT** 凭证；真实签名在后端完成。叠加交易所原生护栏：API key 关提币、IP 白名单、（若涉链上）提币地址白名单 + 新地址冷静期。

4. **下单请求做密码学完整性**。后端对每笔订单用 HMAC-SHA256 签**规范化串（method+path+timestamp+body）+ 时间窗 + nonce 去重**防重放，全程 TLS。

5. **把安全证据做成非技术用户能看懂的"信任面板"**。每次下单前用自然语言展示：本次命中哪条策略门、用的哪个 scoped 凭证、数据源是否可信、是否触发人工复核——让小白用户的信任建立在**可见的确定性规则**上而非对模型的盲信。

6. **按"资产类别 × 是否实盘 × 动作可逆性"做分级威胁模型**（对抗核查补漏）。A股 paper 阶段**没有实盘 key、没有真实资金外流路径**，致命三件套里"敏感系统"强度远低于加密实盘；不应把两者安全等级一刀拉平（会在 paper 阶段过度工程化、又在加密实盘上稀释注意力）。这与"按风险分级"的 MRM 精神一致。

7. **补齐交易所下单侧（非提币侧）经济护栏作为最后一道纵深**（对抗核查补漏）：先小额试单 + 人工确认大额、订单生命周期内的撤单窗口、交易所侧的下单速率限制 / 持仓上限 / 最大订单名义额 / strategy stop / 自动平仓断路器。目标是"即使注入成功下了单，单次最大损失也被夹住"。

8. **数据摄入与记忆按不可信处理**：训练/微调语料、RAG 文档、agent 长期记忆做来源校验、隔离与可信度阈值；外部行情/新闻源标注可信度并与下单决策路径隔离。

9. **纵深防御分层、但高危动作只信确定性层**：模型层（SecAlign 式抗注入基座）、检测器、输入/输出防火墙可作外圈降噪，但因自适应攻击可破，**绝不让它们成为唯一闸门**；不可逆下单的最终把关交给环境/规则的硬边界。

10. **持续对抗式评测进 CI，但要诚实标注其有效性边界**（对抗核查补漏）：用 AgentDojo（banking 套件）做回归是有价值的下界检查，**但单用户项目根本无法复现论文级强度的自适应红队（梯度/RL/搜索/500 人 + 2 万美元奖金级）**。因此"跑了 AgentDojo 就放行下单权限"会制造**虚假安全感**——这本身就是"高危动作只信确定性硬边界、不依赖任何模型层/检测器评测分数"的更强理由。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 以下为示意草图，用于表达概念边界，**不是接线到现有代码**。

### 6.1 CaMeL 式控制流/数据流分离（会话拓扑草图）

```
用户意图(可信) ──► 特权LLM(无不可信数据) ──► 生成"任务程序" ──► 定制解释器执行
                                                          │
                       ┌──────────────────────────────────┤ 工具调用经能力令牌校验
                       ▼                                   ▼
            隔离LLM(处理新闻/RAG/文档)            确定性策略门(deny-by-default)
            · 无工具权限                          · 限额/白名单/杠杆上限/提币禁止
            · 仅回传受类型约束的结构化结果         · 命中即放行,超阈→人在环
            · 回传值仍标"不可信来源"              · 接在所有执行路径(含中继/桥)
                       │                                   │
                       └────► [语义投毒风险] 结构化数值仍可能被污染 ◄──┘
                              ⇒ 对回传的决策值做合理性区间/异常检测,不盲信
```

### 6.2 下单动作的能力令牌 / 策略门 schema 草图

```yaml
order_capability:            # agent 持有的是"能力令牌",不是密钥
  asset_class: crypto        # crypto | a_share
  mode: live                 # live | paper   (paper: 不可逆等级降一档)
  scoped_token_ref: "vault://lease/abc123"   # 短时JIT, 真实key在后端
  policy_gate:               # 会话外确定性规则, deny-by-default
    symbol_whitelist: [BTCUSDT, ETHUSDT]
    max_notional_per_order: 500
    max_leverage: 3
    daily_turnover_cap: 0.5
    max_drawdown_halt: 0.15
    withdraw: deny           # 提币永远默认禁止
  irreversibility: high      # high→触发人在环/二人复核 + 小额试单
  data_provenance:           # 决策所依赖的数据来源可信度
    - {source: official_market, trust: high}
    - {source: ingested_news, trust: untrusted}   # 进入隔离子agent
```

### 6.3 后端下单签名（防重放）草图

```
canonical = method + "\n" + path + "\n" + timestamp + "\n" + sha256(body)
signature = HMAC_SHA256(secret_in_backend_only, canonical)   # secret 永不进LLM
# 校验侧: |now - timestamp| <= window(如30s)  AND  nonce 未被用过(去重表)  AND  全程TLS
```

### 6.4 信任面板（下单前对非技术用户展示）草图

```
本次操作: 市价买入 BTCUSDT 0.01 (名义额 ≈ $430)
✓ 命中策略门: 在标的白名单 / 名义额 < $500 上限 / 杠杆 1x ≤ 3x
✓ 使用凭证: 后端短时凭证 lease/abc123 (你和我都看不到真实API key)
⚠ 数据来源: 信号部分依赖外部新闻(标记为不可信), 已经隔离分析, 仅作参考
✓ 无需人工复核 (未触发不可逆/超阈条件)
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下**原样保留对抗核查的降权词**（夸大 / 错记 / 争议 / 二手 / 不可外推 / 暗示未经证实等）。

### 7.1 被降权的具体声明

- **【medium · 错记数字】CaMeL "缓解 67% 注入"**：这是**二手/错记数字**，CaMeL 论文与 Willison 综述都**没有**这个数。真实头条是"在 AgentDojo 上以可证明安全方式**完成约 77% 的任务**（基线约 84%）"——这是"带安全保证完成的任务比例"，**不是"拦下的注入比例"**，研究把两个不同口径混为一谈。更关键：CaMeL §8.3 **自承未根治注入**，并明确列出"需用户编写并维护安全策略""反复审批导致用户疲劳（reflexively approve）"——与本研究用 93% 审批疲劳攻击 human-in-the-loop 是**同一个软肋**，而把 CaMeL 当脊柱范式却回避了这一内在张力。

- **【medium · 未证实暗示】把 SecAlign "<10%" 与 "12 防御被打到 >90%" 并置**：属**过度外推 + 暗示同集合**。已核验《The Attacker Moves Second》(arXiv:2510.09023) 点名打破的是 Spotlighting、Prompt Sandwich、Circuit Breaker、PromptGuard 等，**没有证据显示 SecAlign 就是被打到 >90% 的那 12 个之一**，且该论文主打 jailbreak/越狱场景。结论方向（模型层防御不可单独依赖）成立，但"SecAlign 已被自适应攻击打穿"这个具体暗示**未被引用证据支持**。

- **【medium · 外推过度，隐藏限定】"250 篇投毒文档威胁全链路"**：原文 (arXiv:2510.07192) 只验证了**最弱的 DoS 窄后门**，作者亲口标注**四重限定**：仅 DoS、窄后门、≤13B、**预训练**投毒；并白纸黑字写下"尚不清楚同样动态是否适用于更复杂行为（给代码植入后门/绕过护栏，已知比 DoS 难得多）""不清楚 >13B 能否维持"。研究把它放大成"威胁我们训练/微调/RAG/记忆全链路、与占比无关"，**丢掉了四重限定**。应降级为：**真实但目标受限的下界证据**，不能据此断言能在下单 agent 里植入越权/泄密级后门。

- **【low · 二手数字 + 争议归因】3Commas 2022 案例（44 人 / $14.8M）**：1480 万 / 44 人来自 **ZachXBT 单方核实**，且他本人说这只是能核实的人数、实际更多——是"至少"的**下界估计而非确数**。更重要：3Commas 起初**公开否认是泄露源、归因部分受害于钓鱼（phishing）**，CEO 后来才承认存在数据泄露；究竟多少损失由"集中托管拖库"直接造成、多少由钓鱼造成，**从未被独立厘清**。研究把全部 1480 万一刀切归因为"集中托管点被拖库"，**抹掉了厂方曾归因钓鱼的争议**。教训（密钥集中点是高价值目标→必须 broker 化 + 关提币）仍成立，但因果归因被简化了。

- **【low · 引用链错配 + 适用性外推】OCC Bulletin 2026-13**：事实成立（2026-04-17 联合发布、取代 SR 11-7 等，已核验），但 URL 指向 `nr-occ-2026-29.html` 与 "Bulletin 2026-13" **编号对不上**；且 MRM 约束的是**受监管银行机构**，把银行级 MRM 当成单用户/小团队系统的**硬性合规要求属外推**，作为"可借鉴治理精神"才妥当。

- **【low · 二手来源 + 证据等级拔高】NCSC "不会像 SQL 注入被根治"**：论断成立且有一手出处（NCSC 官网），但研究只挂 **Malwarebytes 二手博客**而非一手页面，引用层级偏弱；且该指引是 **2025-12 发布（时点较新）**，属**权威机构观点/政策性表态而非可复现实验结论**，研究把它与实验证据并列为"已被强证据确证的三条事实"之一，在**证据等级上略有拔高**。

### 7.2 陷阱（pitfalls，原样保留）

- **把安全当 P5 事后过滤**：提示注入是结构性缺陷（NCSC：不会像 SQL 注入被根治），检测器/输出过滤会被**链式绕过**（EchoLeak 同时绕过 XPIA 分类器、链接编辑、CSP 白名单）。能下单 + 持实盘 key 的 agent 必须在架构层（控制流/数据流分离 + 确定性策略门）前移防御。
- **迷信 benchmark 数字**：AgentDojo "加检测器降到 8%"、SecAlign "<10%" 都是**静态评估**；《The Attacker Moves Second》用自适应攻击把多数防御打到 >90%、人类红队 100%。**绝不能据 benchmark 通过率就放行真实下单权限**。
- **让 LLM 直接持有/看到交易所原始密钥或把密钥放进 prompt/可读文件**：一次注入即可外泄（致命三件套）。3Commas 教训 = 密钥集中托管点本身是高价值目标，必须 broker 化 + 关提币 + IP/地址白名单。
- **依赖人工逐次审批做安全闸门**：Anthropic 实测约 **93% 权限弹窗被点同意**，审批越多越不走心（approval fatigue）。高危/不可逆下单不能靠"弹个框"，要靠确定性规则（限额/白名单/冷静期/二人复核）+ 仅对真正异常升级到人。
- **只防直接注入、忽视 indirect/ingested-document 注入**：中低频策略会摄入行情新闻、研报、被投喂文档、RAG 语料——这些都是不可信内容通道，正是 indirect injection 主战场。摄入即视为不可信，绝不让其与下单权限同处一会话（违反 Rule of Two）。
- **忽视数据/记忆投毒**：见 §7.1 第 3 条降权后的边界。agent 长期记忆/向量库也可被投毒（OWASP T1）；自训模型、微调语料、RAG 与记忆都需来源校验、隔离与可信度阈值。
- **MCP/工具层 confused deputy 与 token passthrough**：MCP 服务器把客户端 token 不验证直接透传给下游 API，会让其以超出用户权限行事（CVE-2025-49596 未认证 MCP Inspector RCE，CVSS 9.4）。多 MCP 服务器间须做权限隔离与 scoped token。
- **Rule of Two 不是万能**：Ken Huang 等指出它不覆盖全部 agentic 风险（如多 agent 共谋、记忆投毒），且 Meta 自承"三者都需要时"要靠人工监督；应与最小权限、确定性策略门、审计**一起用**，而非单点依赖。
- **HMAC 签名缺时间戳/nonce 校验或不记录已用签名**：被截获的合法下单请求可在数小时后**重放**。下单签名必须含规范化串（method+path+timestamp+body）+ 短时间窗 + nonce 去重 + 全程 TLS。

---

## 8. 开放问题

1. **可用性 vs 安全的成本被严重低估**：CaMeL 范式（特权 LLM + 隔离 LLM + 定制解释器 + 能力令牌 + 用户维护策略）与确定性策略门，对"单用户、非技术、对话驱动全生命周期"的系统是**巨大的工程与认知负担**。CaMeL §8.3 自承需要用户编写并维护安全策略、且同样有审批疲劳。**研究既用 93% 审批疲劳否定 human-in-the-loop，又把同样依赖用户配置/审批的 CaMeL 抬成脊柱范式，却没正面回答："非技术用户凭什么能正确编写并维护这些会话外确定性规则？"** 这是该范式落地本项目最大的现实裂缝，被"信任面板"一笔带过——需要专门设计"规则由谁来出、默认安全模板 + 渐进式收紧"的落地路径。

2. **Rule of Two 对本项目可能直接判死刑而未被点破**：中低频策略的核心价值恰恰来自摄入行情/新闻/研报（=A）+ 持实盘 key（=B）+ 自动下单（=C），**三者天然同时需要**。按 Rule of Two 这必须"人在环"，而研究又论证人在环因审批疲劳不可靠——**两条主结论在本场景互相挤压**，逻辑上指向"要么放弃自动下单的自治、要么接受 Rule of Two 被违反"。研究只给了"把分析放进无工具子 agent 回传结构化结果"的理想化解法，未诚实面对这个两难。**需要明确：本项目对"全自动自治下单"的边界到底设在哪？**

3. **CaMeL 的结构化回传防控制流、防不住决策值的语义投毒**：隔离 LLM 处理不可信数据后回传的结构化字段，本身可能携带被注入操纵的数值（如被投喂新闻诱导回传偏高信号分），从而**合法地**改变下单决策。这是 data-flow 层防不住的"语义投毒"，对量化下单**比控制流注入更致命**。需要补充：对回传决策值做合理性区间/异常检测/多源交叉验证，而非把 CaMeL 当终点。

4. **对抗式评测的有效性边界与本项目可达性**：真正的自适应攻击需要梯度/RL/搜索/500 人红队 + 2 万美元奖金级算力人力，**单用户项目根本无法复现**。"跑了 AgentDojo 就放行下单权限"反而可能制造虚假安全感。需要明确：对小团队，可达的对抗评测强度远不足以验证防御——这本身就是"高危动作只信确定性硬边界、不依赖任何模型评测分数"的更强理由。

5. **可逆性与结算/撤单这一关键金融控制面完全没碰**（见 §5 第 7 条补漏）：加密下单基本不可逆，但仍可通过小额试单、撤单窗口、交易所侧限速/持仓上限/strategy stop 把单次注入的最大损失夹住。需把交易所原生**下单侧（非提币侧）**护栏纳入纵深。

6. **A股 paper 阶段威胁建模偏弱**：paper 阶段没有实盘 key、没有真实资金外流路径，"敏感系统"强度远低于加密实盘。需要按"资产类别 × 是否实盘 × 动作可逆性"分级，避免 paper 过度工程化 + 加密实盘稀释注意力。

7. **供应链 / 依赖与模型权重来源风险未展开**：本项目大量依赖第三方（Tushare 数据、Binance SDK、开源基座/微调权重、MCP 服务器、pip 依赖）。OWASP LLM03 被列名却没落到具体动作——尤其**下载的预训练/开源权重本身可能已被 250-文档式预训练投毒**（正是该论文场景），而项目**无法重训验证**。这对"用开源 SecAlign/基座模型"的建议是直接反作用力，需要自洽处理（如：权重来源签名/哈希校验、优先可信来源、对关键决策不单独依赖单一模型）。

---

## 9. 参考文献（URL）

**SOTA / 系统**
- CaMeL（Google DeepMind）: https://arxiv.org/abs/2503.18813
- Meta Agents Rule of Two: https://ai.meta.com/blog/practical-ai-agent-security/
- Meta SecAlign（开源安全基座）: https://arxiv.org/abs/2507.02735
- AgentDojo（论文）: https://proceedings.neurips.cc/paper_files/paper/2024/hash/97091a5177d8dc64b1da8bf3e1f6fb54-Abstract-Datasets_and_Benchmarks_Track.html
- AgentDojo（OpenReview）: https://openreview.net/forum?id=m1YYAQjO3w
- AgentDojo（开源代码）: https://github.com/ethz-spylab/agentdojo
- HashiCorp Vault — AI agent identity: https://developer.hashicorp.com/validated-patterns/vault/ai-agent-identity-with-hashicorp-vault
- Anthropic "How we contain Claude": https://www.anthropic.com/engineering/how-we-contain-claude

**关键论文 / 证据**
- The Attacker Moves Second（经 Willison 综述，arXiv:2510.09023）: https://simonwillison.net/2025/Nov/2/new-prompt-injection-papers/
- 250-文档投毒（arXiv:2510.07192）: https://arxiv.org/abs/2510.07192
- EchoLeak（arXiv:2509.10540 / CVE-2025-32711）: https://arxiv.org/abs/2509.10540
- SecAlign（arXiv:2410.05451, CCS 2025）: https://arxiv.org/abs/2410.05451
- NCSC "may never be fixed"（二手：Malwarebytes）: https://www.malwarebytes.com/blog/news/2025/12/prompt-injection-is-a-problem-that-may-never-be-fixed-warns-ncsc

**机构标准 / 实践**
- OWASP LLM Top 10: https://genai.owasp.org/llm-top-10/
- OWASP Agentic AI — Threats and Mitigations: https://genai.owasp.org/resource/agentic-ai-threats-and-mitigations/
- OWASP GenAI Security Project（总入口）: https://genai.owasp.org/
- NIST AI RMF: https://www.nist.gov/itl/ai-risk-management-framework
- CISA / NSA / Five Eyes agentic 指南（经 CyberScoop）: https://cyberscoop.com/cisa-nsa-five-eyes-guidance-secure-deployment-ai-agents/
- OCC Bulletin 2026-13 / SR 26-2（注意编号核对，见 §7）: https://www.occ.treas.gov/news-issuances/news-releases/2026/nr-occ-2026-29.html
- Binance API key 权限文档: https://developers.binance.com/docs/wallet/account/api-key-permission
