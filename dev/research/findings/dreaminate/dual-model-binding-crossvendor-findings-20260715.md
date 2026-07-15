# dual-model binding（卡 8be0e547）跨厂商 skeptic 判 NOT SOUND — findings + 收紧后的诚实 scope

> 2026-07-15。deep-opus 实现 → 我（同厂商）复审判 sound → **codex 跨厂商 skeptic 判 HONESTY BOUNDARY: NOT
> SOUND**（4×P1 + 2×P2，逐条挂 file:line）。**未 land，已 revert**。这正是跨厂商独立审查的价值现场演示：
> 被审对象**就是** dual-model 独立性机制，而独立审查抓出了它自己的越界主张。卡保持 pool/todo，用本篇收紧 spec。

## codex 确认的缺陷（不许 land 的原因）
- **P1#3 · digest 越界（核心不诚实）**：`wire_submission_digest` 哈希的是原始 `messages/tools`，**不是**
  真正 `requests.post(json=payload)` 的 provider-specific payload。messages→payload 编码 bug 会改实发内容但
  digest 不变→门放过，却标 `actually_submitted_local_payload`。**label 越界**（llm_providers.py:112/130/136/213/231）。
- **P1#2 · 订阅模式被打断**：脚本给每次 review opt-in submission binding，但订阅 CLI adapter 不报
  `submitted_request_digest`→`_assert_submission_bound` 在两次**付费 CLI 调用后**拒绝→`--subscription` 恒失败
  （burn 完额度才炸）。破了我先前建的订阅 dual-model review。
- **P1#1 · schema 向后不兼容**：`submitted_prompt_digest` 加进 v3 必填集但没 bump v4→旧 v3 journal 缺字段被
  `_from_dict` 拒；且加空默认也废旧 HMAC seal（seal 覆盖全字段）。旧封存证据读不了。
- **P1#4 · 诚实降级没往下游传**：`identity_basis` 加进 verdict 但**未持久化/未暴露**；durable review payload 只存
  `independent`，API 仍回 `independent:true` + 「独立通过」，订阅文案仍写「真跨厂商独立」——与声明式-only 矛盾。
- **P2#5 · PROVIDER_IDENTITY_BOUNDARY 文档失真**：文里说记录「配置 + 响应 model/system_fingerprint」，但 gateway
  只从 routing profile/credential 记 provider/model，**从不消费**响应字段。attestation-不可行结论本身 HOLDS。
- **P2#6 · 8 测不杀上述不诚实**：gateway 测用配合式 stub 手喂任意 digest（从不抓真 adapter 的 post payload 独立哈希）；
  身份测手构造 label；边界测只查子串。**部分 vacuous**（全量套件绿 ≠ 诚实成立）。
- INFO#7 · 非目标（canonical/GoalProofLedger/routing）HOLDS 未碰。✅

## 收紧后的诚实 scope（下次实现照此，别再越界）
- **Gap① 分两路，label 必须精确**：
  - **HTTP adapter（api-key）**：数字要哈希**真正 post 的 provider payload dict**（post 前一刻算），非 messages。
    要么 (a) 只作**证据记录** `actually_posted_payload`（无服务端预测 expected → 不 fail-closed，诚实标「记录非门」），
    要么 (b) 服务端**复用同一 encoding** 算 expected 才能 fail-closed（引入 adapter→server 编码耦合，取舍待定）。
  - **订阅 CLI（claude -p / codex exec）**：opaque 子进程，**观测不到真实 API payload** → **不 opt-in**、不装能绑；
    最多记「CLI 输入 prompt digest」并**如实**标（非「实发 API payload」）。订阅路径绝不因绑定而 fail-closed 崩。
- **下游传播**：`identity_basis` + `subject_binding_basis` 必须**持久化 + API/capability ledger 暴露**；
  「independent」布尔要限定为 `independent_as_declared`，不给裸 pass。
- **schema v4**：v3/v4 分字段集 + 分 seal payload；配**历史 v3 fixture 测**证旧 journal 仍可读 + seal 仍验。
- **测试要有牙**：抓真 adapter post payload 再变异→门必抓；响应 model 与配置不符→测；订阅无 digest→走弱基线不崩；
  v3 fixture 读；下游 API/ledger 断言限定 label。
- **attestation 结论**（标准 chat API 无客户端可验证 model attestation，只 TEE/机密推理端点有）**HOLDS**，可留；
  但删掉「消费响应字段」的失真句，或真去 persist+cross-check 响应 model/fingerprint/request-id（当弱信号，不升成 attestation）。

## 状态
卡 8be0e547 保持 **pool/todo**（未 land、无脏码进 main）。重做时按本篇收紧 spec + 跨厂商 skeptic 复验（同厂商复审
不足以守诚实边界——本次已证）。
