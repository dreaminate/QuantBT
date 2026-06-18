# 04 · 人在环审批门 + 决策疲劳设计

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 A

## 1. 一句话定位

人在环（HITL）审批门的**工程能力今天是成熟的**——OpenAI Agents SDK / LangGraph / Temporal 三套主流框架都能把一次 Agent 运行**挂起数天再恢复**（前提是开发者自己接上持久化存储）；但**审批门的有效性是不成熟的**：跨域证据（临床用药警报、司法裁决）一致显示人会把审批门退化成橡皮图章，自动化偏误真实存在。本环节的可达目标因此不是"加了门就安全"，而是**双通道分流（探索类轻量可逆 / 确证类重门可挂数天）+ 反自动化偏误设计 + 把审批延迟本身当作一类新风险来对冲**——并且必须清醒：决定橡皮图章会不会发生的是**审批人的激励与后果暴露**，不是门是否存在。

## 2. 前沿 SOTA 与代表系统

| 系统 / 范式 | 它提供什么 | 对本设计的意义 | 链接 |
|---|---|---|---|
| **OpenAI Agents SDK — HITL（needsApproval / RunState）** | 工具上挂 `needsApproval`（布尔或异步函数）即可在工具调用前暂停运行；`RunState` 是持久化的暂停/恢复边界，存模型响应、已生成项、**审批状态**；经 `state.toJSON()` / `RunState.fromString()` 序列化，可把运行存盘后晚些恢复；人类用 `state.approve()` / `state.reject()` 决策，再把 state 传回 `runner.run()`。`{ alwaysApprove }` / `{ alwaysReject }` 的粘性决策也随序列化存活。 | "门=一个可序列化的运行快照"这一范式最干净的现成实现，天然契合本仓库"先生成—后批准"。**但"恢复数天后"是合理推断而非文档原话**（见第 7 节）。 | https://openai.github.io/openai-agents-js/guides/human-in-the-loop/ |
| **LangGraph — `interrupt()` + checkpointer** | 在节点内调用 `interrupt()`，"LangGraph 用持久层保存图状态并**无限期等待**直到你恢复执行"；恢复需同一 thread ID + 生产级持久 checkpointer（数据库支撑）。 | 直接给出"可挂数天"的官方机制；**但其文档明确警告：恢复时整个节点从头重跑，`interrupt` 之前的副作用会再执行一次，因此必须幂等**——这正是交易场景的雷区（见第 5/7 节）。 | https://docs.langchain.com/oss/python/langgraph/interrupts |
| **Temporal — 持久工作流 HITL** | `workflow.wait_condition()` 让 Worker 交还任务、零算力空转；durable timer 服务端落库、跨 Worker 重启/部署/迁移存活；SLA 到期自动升级到备用审批人；Activity 带幂等键；每个动作（Signal / Activity / timer 触发）全程审计。 | 多日挂起的最强方案——官方称"五秒还是五个月机制一致"；一次带提醒的审批约产 40–80 事件，远低于 51,200 事件上限。是"超时默认动作 + SLA 升级"的现成模板。 | https://temporal.io/blog/human-in-the-loop-approvals |
| **OWASP Top 10 for Agentic Applications（2025–2026）** | 把"过度自主"列为根本风险；对不可逆 / 财务 / 改状态动作要求人在环；审批配 dry-run / 预览；审批门**专门映射到高影响动作**而非每一步。 | 给出"门该挂在哪"的标准答案——少而重，而非多而滥（门越多越橡皮图章，见第 3 节）。 | https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications/ |
| **"审批提示不等于授权"（行业立场文）** | 论证 Agent 弹出的审批提示是 UX 确认、不是 authorization；真正的控制是凭据 / 权限 / 后果边界。 | 提醒本设计：把安全寄托在"人会认真看那个弹窗"上是虚假安全感；门要配真实的权限 / 限额闸门。 | https://blakecrosley.com/blog/ai-agent-approval-prompts-not-authorization |

## 3. 关键论文（每条带 URL）

- **《Override rate of drug-drug interaction alerts in clinical decision support systems: A brief systematic review and meta-analysis》（Felisberto et al., 2024, Health Informatics Journal）** — 橡皮图章最常被引的量化证据：合并 override = **90%（95%CI 85.6–95.0%, p<0.0001）**，**但 I²=100%**（最大可能异质性），16 篇入选、15 篇进入定量合并。**第 7 节降级**：I²=100% 下这个看似精确的 90% 建立在彼此剧烈不一致的研究上，作为单一真值搬运在统计上近乎无意义；且场景是临床用药警报（高频、低单次后果、警报疲劳极强），跨域外推到金融交易门属不当外推。 https://journals.sagepub.com/doi/10.1177/14604582241263242
- **《Extraneous factors in judicial decisions》（Danziger, Levav & Avnaim-Pesso, 2011, PNAS）** — 决策疲劳最著名的原始证据：一段时段内有利裁决率从约 65% 降到接近 0，归因于"精神耗竭"。**本条 URL 仅指向原始论文，不可用来佐证'统计假象'的批评性结论（见下一条与第 7 节）**。 https://www.pnas.org/doi/10.1073/pnas.1018033108
- **《The irrational hungry judge effect revisited: Simulations reveal that the magnitude of the effect is overestimated》（Glöckner, 2016, Judgment and Decision Making 11(6):601–610）** — 对上一条的批评：用模拟表明"有利裁决耗时更长"等理性因素可解释**大部分**顺序效应，**magnitude 被高估**。**第 7 节降级（关键）**：Glöckner 明说理性因素只能解释"large parts — but admittedly not all aspects"，并明确写道其分析"do not preclude that serial order and mental depletion might have affected the legal judgments"——即**他没有断言这是'统计假象'、更没说效应不存在**；研究 JSON 的"statistical artifact / not cleanly replicated"是把"magnitude 被高估 + 部分混淆"反向夸大成"证伪"。 https://www.cambridge.org/core/journals/judgment-and-decision-making/article/irrational-hungry-judge-effect-revisited-simulations-reveal-that-the-magnitude-of-the-effect-is-overestimated/61CE825D4DC137675BB9CAD04571AE58
- **《The Effects of Decision Fatigue on Judicial Behavior: A Study of Arkansas Traffic Court Outcomes》（Hemrajani & Hobert, 2024, Journal of Law and Courts）** — 与"统计假象"结论**相反**的近期证据：传讯听证中庭审后段撤案概率确有小幅下降（部分支持决策疲劳），但庭审听证不显著——说明**效应方向可能真实、只是小且情境依赖**。 https://www.cambridge.org/core/journals/journal-of-law-and-courts/article/abs/effects-of-decision-fatigue-on-judicial-behavior-a-study-of-arkansas-traffic-court-outcomes/8B7EB8735C10F7730FB402D6F2E80D70
- **自动化偏误系统综述（Goddard et al., 2012, JAMIA 等）** — 自动化偏误（盲信系统建议、对错误建议放行）在临床决策支持中被反复记录；**且综述指出各类缓解手段（强制结构化理由、去默认值等）效果混杂、有时仅边际有效**——这一条用来给第 5 节的反偏误手段"标待验证"，而非当作确定解药（见第 7 节漏点）。 https://academic.oup.com/jamia/article/19/1/121/732254

## 4. 机构最佳实践 / 标准

- **审批门只挂高影响、不可逆、改状态 / 动钱的动作**（实盘下单、划转、加杠杆、删数据），不是每一步；门越多、单门信息密度越低，橡皮图章率越高（DDI meta 把"警报数量"列为 override 的失败因子之一）。来源：OWASP Top 10 for Agentic Applications。 https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications/
- **审批前必须呈现 dry-run / 预览 + 结构化风险陈述**：让审批人看到"这一步会导致什么"（拟下单明细、对组合的影响、触发的限额），而非只给一个"批准/拒绝"按钮。来源：OWASP（动作级批准配 dry-run/预览）。 https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications/
- **超时要有明确默认动作 + SLA 升级路径**：把"挂起等人"做成可配置的 durable timer + 升级到备用审批人 / 到期默认安全动作（如默认拒绝、或对止损类默认放行），而不是无限期阻塞。来源：Temporal HITL（durable timer + SLA 升级）。 https://temporal.io/blog/human-in-the-loop-approvals
- **恢复路径必须幂等到下单 / 划转级别**：凡是"审批前已执行"的副作用，恢复重跑不得重复执行——用业务级幂等键（订单 client_order_id、划转请求 id）守护。来源：LangGraph interrupt 文档（节点 resume 整段重跑、副作用须幂等）。 https://docs.langchain.com/oss/python/langgraph/interrupts
- **审批提示 ≠ 授权**：门后面要有真实的权限 / 限额 / 后果边界做硬闸门，不能把安全完全寄托在"人会认真看弹窗"。来源：AI Agent Approval Prompts Are Not Authorization。 https://blakecrosley.com/blog/ai-agent-approval-prompts-not-authorization

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅给方向与原则，不点 file:line、不排实施计划。

- **双通道分流（探索 vs 确证）**。探索类操作（跑回测、生成因子、超参搜索、纸面/沙盒推演）应是**轻量、可逆、无门或仅事后记录**；确证类操作（把策略推向 paper→实盘、实盘下单、划转、改杠杆）走**重门、可挂数天、强制结构化理由**。注意：双通道"降低橡皮图章率"目前是设计直觉、非实证结论（见第 7 节），应标注为待验证假设，并在上线后用门内停留时长 / override 率自我度量。
- **门只挂在高影响边界，且少而重**。沿用 OWASP 取向：实盘执行 / 动钱 / 加杠杆 / 删历史数据才设门；研究态一律放行。门数越少，每个门越值得审批人认真看，越不容易橡皮图章。
- **反自动化偏误的门内交互**（手段本身待验证、非确定解药）：强制结构化理由（不可空、不可纯套话）、**无默认选项**（不预选"批准"）、**让审批人复述风险**（restate-the-risk，例如手填本次最大潜在亏损 / 影响的组合）、并在门内直接展示 dry-run 预览与触发的限额。这些借鉴司法/临床缓解措施，但要承认其效果混杂、可能诱发新的形式化敷衍。
- **把"审批延迟"显式建模为一类新风险并对冲**。中低频资产无关流程里，把确证类操作挂数天等人，本身可能错过执行窗口、造成滑点、或让止损 / 再平衡被人为延迟而失效。因此每个门要配：超时默认动作（按动作类型区分——止损类倾向"到期默认放行"，加仓/动钱类倾向"到期默认拒绝"）、SLA 升级、以及"延迟成本"的可见提示。这是研究原始结论里完全缺失的方向。
- **恢复语义幂等到交易动作级**。本仓库 MEMORY 记录过 M17 幂等 + 杠杆上限曾被中继绕过的同类雷区；审批门一旦采用"节点 resume 整段重跑"语义（LangGraph 式），就必须保证审批前若已下单/已划转，恢复重跑用幂等键去重，绝不重复下单或重复划转。
- **门后配真实硬闸门**。审批通过不等于解除权限边界——实盘动作仍受限额、杠杆上限、白名单出口约束。把安全分成"人审批（防方向性错误）"与"系统硬限额（防灾难性后果）"两层，不互相替代。
- **门的有效性靠激励而非门本身**。单用户场景下审批人就是属主、对结果有直接金钱责任，激励结构远好于"看第 200 条良性警报的医生"；这是本设计相对临床 90% override 证据的**有利不对称**，应被利用（例如门内显式呈现"这是你自己的钱/客户的钱"的后果暴露），而不是假设属主一定会橡皮图章。

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 仅示意，不接现有代码。

审批门记录的概念 schema：

```text
ApprovalGate {
  gate_id            : uuid
  run_id             : 运行/快照引用（对应 RunState 序列化句柄）
  channel            : "exploratory" | "confirmatory"   # 双通道
  action_kind        : "live_order" | "transfer" | "leverage_change" | "data_delete" | ...
  impact_preview     : { dry_run, affected_portfolio, limits_triggered, est_max_loss }
  idempotency_key    : 业务级键（client_order_id / transfer_request_id）  # 恢复重跑去重
  created_at         : ts
  sla_deadline       : ts                                 # 到期触发默认动作
  on_timeout         : "default_reject" | "default_allow" | "escalate"
  escalate_to        : approver_id | null
  decision           : "pending" | "approved" | "rejected" | "timed_out"
  decision_reason    : text(non_empty, anti_boilerplate)  # 强制结构化理由
  risk_restated      : text | null                        # restate-the-risk 输入
  decided_by         : approver_id | null
  decided_at         : ts | null
}
```

恢复路径的幂等护栏（伪代码，强调"重跑不得重复副作用"）：

```text
on_resume(gate):
    # LangGraph 语义：节点从头重跑，interrupt 前的副作用会再执行
    if gate.decision == "approved":
        if not already_executed(gate.idempotency_key):   # 幂等键查重
            execute_action(gate.action_kind, gate.idempotency_key)
        # else: 已执行过，跳过——绝不重复下单/划转
    elif gate.decision in ("rejected", "timed_out"):
        record_and_halt(gate)
```

超时默认动作按动作类型分流（伪代码）：

```text
on_sla_expire(gate):
    match gate.action_kind:
        "stop_loss" | "risk_reduction"  -> default_allow(gate)   # 延迟即风险
        "add_position" | "transfer" | "leverage_up" -> default_reject(gate)
        _ -> escalate(gate.escalate_to)
```

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下限定词（**过度反向夸大 / 不当外推 / 二手数字 / 引用错配 / 待验证**）原样保留。

- **【高·过度反向夸大】"决策疲劳被 Glöckner 2016 质疑为统计假象 / 65%→0 fatigue likely a statistical artifact, not cleanly replicated" 必须降级。** 核对 Glöckner（2016）原文：他明说效应"magnitude 被高估"，且理性因素（案件排序 / 选择性退出 / 数据截尾）只能解释"large parts — but admittedly not all aspects"，并明确写道其分析"do not preclude that serial order and mental depletion might have affected the legal judgments"。即 **Glöckner 没有断言这是"统计假象"、更没说效应不存在**，他承认可能仍有真实耗竭成分、只是更小。研究 JSON 把"magnitude 被高估 + 部分混淆"升格成"证伪"属反向夸大。此外"65%→0"表述本身不准——原文是整段时段内有利裁决率从约 65% 降到接近 0，不是"耗竭归因部分"。**更关键：2024 Arkansas 交通法庭研究（Hemrajani & Hobert）给了决策疲劳的"部分支持"（情境依赖的小幅下降），方向与"统计假象"相反。**
- **【低·引用错配】原研究把"统计假象"finding 挂在 PNAS 2011 原文 DOI 下属来源标注错误。** pnas.org/doi/10.1073/pnas.1018033108 是 Danziger 等 2011 原始论文（主张效应真实），批评性论断来自 Glöckner 2016。核查者无法据此 URL 验证该 finding。**本 dossier 已拆分：PNAS URL 只挂原始主张，批评 finding 挂 Glöckner 2016 的 Cambridge URL。**
- **【中·二手数字/异质性被隐瞒】"橡皮图章被证实（CDS 约 90%）"数字真实但被当作干净结论。** 核对 Felisberto 等（2024）：pooled override = 90%（95%CI 85.6–95.0%, p<0.0001）**但 I²=100%**——这是最大可能异质性，合并点估计在统计上近乎无意义，"90%"建立在 16 篇彼此剧烈不一致的研究上，**不能当作稳定真值搬运**；原研究 JSON 既没标 I²、也没标研究数。
- **【中·不当外推/不可跨域搬运】用 DDI 90% 给"金融交易 agent 审批门也会被橡皮图章"背书属跨域外推。** 该 90% 来自临床用药警报（高频、低单次后果、警报疲劳极强、大量为已知良性组合）；交易审批门频次低得多、单次金钱后果高、审批人有直接经济动机。**结论方向（自动化偏误真实存在）站得住，但用 90% 这个具体数字给金融门背书不稳。**
- **【低·轻微夸大"开箱即用"】"审批门可挂数天已成熟 / heavy gate suspendable for days" 应弱化。** 三框架都是"使能（enable）"数天挂起，而非框架本身保证持久化：OpenAI 提供 `RunState` 序列化、LangGraph `interrupt` 文档明写"waits indefinitely"但前提是"同一 thread ID + 生产级持久 checkpointer"、Temporal 用 durable timer。**能否真挂数天取决于开发者自己接的持久化存储；OpenAI 文档并未给出"days later"的官方时长保证（合理推断而非原话）。** 表述应为"可被设计成挂数天"而非"已成熟地挂数天"。
- **【待验证】"探索 vs 确证两条通道"映射缺乏经验依据。** 这是合理设计直觉，但无任何实证证明"双通道分流"确实降低橡皮图章率或决策疲劳；它在 design_directions 里被列得像结论，**实为未验证假设，已在第 5 节明确标注待验证**。
- **【待验证】反自动化偏误手段（强制理由 / 无默认 / restate-the-risk）本身缺乏疗效证据。** 自动化偏误系统综述指出 mitigator 效果混杂、有时仅边际有效，甚至可能诱发新的形式化敷衍（写理由也能套话）。**不应当作确定有效的解药。**

## 8. 开放问题

- **域内验证缺口**：全部疲劳 / 橡皮图章证据来自司法（假释 / 交通法庭）与临床（用药警报），**没有任何来自金融 / 交易审批门的直接证据**。把这些搬到"AI 交易 agent 人在环"上，至少需要一层域内验证或 explicit caveat——本设计上线后应自我度量门内停留时长、override 率、延迟成本，补这层证据。
- **激励设计 vs 门设计**：决定橡皮图章会不会发生的是审批人的激励与后果暴露，不是门本身。单用户属主对自己/客户资金有直接责任，这是有利不对称；但如何在门内**主动放大后果暴露**（让属主真切感到"这是真金白银"）而不引发疲劳，是开放设计问题。
- **审批延迟的最优默认动作**：止损类"到期默认放行" vs 动钱类"到期默认拒绝"的切分边界在哪？SLA 窗口设多长才能在"防错误"与"防错过执行窗口"之间取得平衡？需要按资产 / 频率 / 动作类型实证标定。
- **样本年代与发表偏误**：DDI override meta 的 16 篇研究年代跨度大，CDSS 调参后警报数已大幅下降，90% 是否仍代表当下系统存疑；且 I²=100% 下原研究未做亚组 / 敏感性分析或发表偏误检验（funnel / Egger）。当下基线值得重新核。
- **反偏误手段的效应量**：强制结构化理由、无默认、restate-the-risk 各自被验证过的效应量是多少？失败模式（套话敷衍）如何检测？需要在本系统上做对照观测。
- **幂等键的覆盖完整性**：交易语义下"审批前已执行"的副作用不止下单——还有划转、改杠杆、改风控参数、写状态。每一类是否都有业务级幂等键守护恢复重跑？这正是本仓库 M17 同类雷区，需逐动作清点。

## 9. 参考文献（URL）

- OpenAI Agents SDK — Human-in-the-loop（needsApproval / RunState / approve / reject / resume）: https://openai.github.io/openai-agents-js/guides/human-in-the-loop/
- LangGraph — interrupt + checkpointer（waits indefinitely / node re-runs / side effects must be idempotent）: https://docs.langchain.com/oss/python/langgraph/interrupts
- Temporal — Human-in-the-loop approvals（durable timer / SLA escalation / idempotency / audit）: https://temporal.io/blog/human-in-the-loop-approvals
- OWASP Top 10 for Agentic Applications（2025–2026）: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications/
- AI Agent Approval Prompts Are Not Authorization: https://blakecrosley.com/blog/ai-agent-approval-prompts-not-authorization
- Felisberto et al. (2024) — DDI alert override meta-analysis（90%, 95%CI 85.6–95.0%, I²=100%, n=16）, Health Informatics Journal: https://journals.sagepub.com/doi/10.1177/14604582241263242
- Danziger, Levav & Avnaim-Pesso (2011) — Extraneous factors in judicial decisions, PNAS（原始主张）: https://www.pnas.org/doi/10.1073/pnas.1018033108
- Glöckner (2016) — The irrational hungry judge effect revisited（magnitude overestimated；不排除真实耗竭）, Judgment and Decision Making: https://www.cambridge.org/core/journals/judgment-and-decision-making/article/irrational-hungry-judge-effect-revisited-simulations-reveal-that-the-magnitude-of-the-effect-is-overestimated/61CE825D4DC137675BB9CAD04571AE58
- Hemrajani & Hobert (2024) — Decision Fatigue on Judicial Behavior: Arkansas Traffic Court（部分支持、情境依赖）, Journal of Law and Courts: https://www.cambridge.org/core/journals/journal-of-law-and-courts/article/abs/effects-of-decision-fatigue-on-judicial-behavior-a-study-of-arkansas-traffic-court-outcomes/8B7EB8735C10F7730FB402D6F2E80D70
- Goddard et al. (2012) — Automation bias: a systematic review, JAMIA（缓解手段效果混杂）: https://academic.oup.com/jamia/article/19/1/121/732254
