# T-018 · 安全门 deny-by-default + 交易所侧硬墙（gate 组件）

- **状态**：✅ done（gate 组件）· **🟡 生产接线 deferred → T-021**（诚实：不假绿灯，见下）
- **review_status**：1（用户 2026-06-19 确认） · **来源**：spine 06 + R6/R7/R9/R10/R11/R12 + M17 · **依赖**：T-014
- **优先级**：P1

## 做了什么

新建 `app/security/gate/`（policy/nonce/broker/enforcer/ingest）—— 脊柱里唯一「动真钱/不可逆」硬墙的
5 不变量组件，复用 `ids.content_hash`：
- `policy.py`：`PolicyGate`（frozen、agent 不可写）+ `evaluate` **deny-by-default**：空白名单=全拒、
  提币/划转 allow-list 外全拒、杠杆/名义上限。`TrustTier` + `classify`（A股永远 paper）。
- `nonce.py`：`NonceLedger`（sqlite UNIQUE 防重放 + busy_timeout）。
- `broker.py`：`CapabilityToken`（**结构上无 key 字段**）+ `KeyBroker`（JIT lease，唯一 fetch 真 key 处）。
- `enforcer.py`：`OrderGuard` S0-S7 状态机（任一前置失败 → 不进 S4 → key 永不取出）。
- `ingest.py`：Rule-of-Two 摄入隔离 + 决策值投毒检测 + 验证官 attestation（诚实非组织独立 R7）。

## 验收（23 对抗测试 + 7 变异全杀 + 5-lens 复核 19 真发现）

`tests/test_security_gate_adversarial.py` → **23 passed**；全量 **926 passed / 13 skipped**（基线未破）。
变异：deny-by-default / 注入取不到 key / 重放 / cap-0=deny / 名义额不信自报 / 实盘强制 nonce / capability 绑门 → 全杀。

## 5-lens 对抗复核：19 真发现 → 12 在 gate 内修，7 接线项 deferred

**已修（gate 内硬化）**：
- #6/#17 cap 默认 0 在实盘=「无限制」allow-by-default → 改 0=deny（notional_cap_unset/turnover_cap_unset）。
- #7/#5 名义额信 attacker 自报 `extra.notional_usdt` → 非 PAPER 只信撮合价 `order.price`，不可核则拒。
- #8 实盘未声明 leverage 跳过 cap（venue 用账户默认最高 125x）→ leverage_unspecified 违规。
- #4/#12/#16 无 nonce 单在实盘静默可重放 → CRYPTO_LIVE 强制 nonce+ledger，缺即 fail-closed。
- #15 attestation 从 attacker 可控 `order.extra` 取（注入单自报已授权）→ 改可信调用方显式入参 + action 取自 capability。
- #3 broker.issue 忽略 capability.gate_ref（旧/松门 cap 取本门 key）→ 加 gate_hash 绑定校验。
- #10 提币仅精确匹配 'withdraw' → allow-list（提币/划转/transfer 全拒）。
- #2(部分) lease 从未交给 venue（no-op 仪式）→ enforcer `_submit` 把 lease 作为 key 通道传入（venue 不支持则退化）。
- low-note 运行时措辞自检（不只测试）。

**deferred → T-021（生产接线，需 §7 产品决策 + 实盘基线风险）**：
- #1/#11/#13 OrderGuard 接进所有 venue 工厂 + KeyBroker 实例化 + relay 路径走 broker（M17 命门的真落地）。
- #2(完整) venue 重构为【只认 lease 签名】、移除各自 keystore 句柄。
- #14 集中冻结门注册表（按 account×tier 解析同一门，禁 per-path 分歧）。
- #18/#19 生产 wrap 断言 + T15 幂等 lease/T16 崩溃不重发/T18 阶梯对账集成测试。
- **为何 deferred**：full deny-by-default 绑定需产品定「默认门模板 + 每 follower 白名单来源 + 放宽二人复核 +
  fail-open/closed 档位」（设计 §7 open Q#2/#3，**落地前必答**），且重构 venue 签名触实盘交易基线（763+ 测试）。
  **诚实：gate 已建+硬化+单测验证，但 INV-2/INV-3/M17 在生产【未强制】——不标绿。**

## 下一步：T-019 审批门 + promote 改带审批门状态机。
