# T-021 · 安全门【生产接线】：OrderGuard 接进 relay，强制 INV-2/M17

- **状态**：✅ done（2026-06-18，relay 闸门生产强制）· 🟡 **INV-3 lease-唯一-key 通道 → 残余 T-022**（诚实不标绿）
- **review_status**：1（用户 2026-06-19 确认） · **来源**：spine 06 §4/§7 + INV-2/INV-4/M17 + R9 · **依赖**：T-018（gate 组件）
- **优先级**：P1

## 落地前的产品决策（设计 §7「落地前必答」）

AskUserQuestion 工具内部错误丢答 + 用户「继续」→ 采纳推荐保守档，记为可改默认（见 dev/DECISIONS.md D-T021）：
- **D-T021-1** whitelist = `{signal.symbol}`（跟单作用域=所跟 master 当下标的，余皆 deny）。
- **D-T021-2** notional = `follower.per_order_max_usdt`（**既有字段**默认 100，≤0 兜底 100）——无需新字段/迁移。
- **D-T021-3** fail 模式：**CRYPTO_LIVE 真钱 → fail-closed**（nonce 台缺失即拒）；TESTNET/PAPER → fail-open。
- 放宽门走既有 T-019 审批门（单用户 approver≠creator 防自欺 + 审计）。

## 做了什么

新建 `app/copy_trade/gate_binding.py`（默认门模板：Follower→PolicyGate + tier + nonce 映射）；
relay `executor.py` 加 `_place`：`enforce_gate=True` 时**所有 follower 下单热路径必经 OrderGuard**
（S1 防重放 → S2 deny-by-default 策略门 → S5 提交）。`main.py` 生产 relayer 置 `enforce_gate=True` +
注入 `RELAY_NONCE_LEDGER` → **INV-2/M17 生产强制**（此前 relay 完全绕过策略门）。

- **M17 命门**：master 信号杠杆经 `apply_follower_leverage_cap` 截到 follower cap；**且**直接对门后 venue
  注入超杠杆单 → 门 `max_leverage_exceeded` 拒（relay 路径与直连路径两者都夹，证明门接全）。
- **INV-4 防重放**：确定性 `relay_nonce`，NonceLedger 消费一次；截获 relay 重打 → `replay_rejected`。
- **fail-closed**：真钱档 nonce 台缺失 → `live_deps_unavailable_fail_closed` 拒、venue 永不被调。
- **向后兼容**：`enforce_gate` 默认 False（既有 23 copy_trade 测试 + 763 基线不变）；生产 main.py 置 True。

## 5-lens 对抗复核：16 raw → 4 真发现全修（皆「挡死正常交易」侧，安全方向无泄露）

设计 §7 警告「默认值定错 = 要么挡死要么放水」——复核抓住"挡死"侧：
- **fix A 现货实盘单全拒**（leverage_unspecified）：现货无杠杆 → applied_leverage=None → 实盘门全拒。
  **修**：relay 查 master.asset_class==crypto_spot 时 leverage 显式 1x（满足门「实盘须声明杠杆」且不放真杠杆；
  期货 None 仍拒不变）。
- **fix B 市价实盘单全拒**（notional_unverifiable）：市价单 price=None → 非 PAPER 名义额不可核 → 全拒
  （order_type 默认 market = 规范路径被砖）。**修**：门加可信入参 `ref_price`（additive，T-018 不破）；
  relay 从 **venue 侧 mark**（`get_position().mark_price`）取价核名义额，**绝不读 signal/extra 自报价**（防投毒）；
  不改 order.price（venue 会把 price 发交易所污染市价单）；取不到 mark → 门 deny-by-default（fail-safe）。

## 验收（16 对抗测试 + 8 变异全杀 + 5-lens 复核 4 真发现全修）

`tests/test_copy_trade_gate.py`（16）：M17 命门(relay 截断+直连注入双夹) / deny-by-default 白名单 / notional /
真钱 fail-closed / 防重放 / testnet fail-open / 门拒 venue 不被调 / 向后兼容 / 四路径同判 / tier 映射 /
现货实盘放行(fix A) / 市价可信 mark 放行(fix B) / 无 mark fail-safe 拒 / mark 真用于名义额上限。
全量 **990 passed / 13 skipped**（基线 974 未破）。变异 8 个全杀（enforce_gate 失效 / fail-closed 失效 /
白名单放宽 / notional 兜底失效 / tier 恒非 LIVE / 现货 1x 兜底删除 / ref_price 取价删除 / policy 忽略 ref_price）。

## 诚实残余（🟡 未交付 → T-022）

- **INV-3 lease-唯一-key 通道**：生产 main.py **不注入 broker**——binance venue 仍在工厂 self-fetch key，
  未重构成「只认 lease 签名」。若现在注入 broker，会发 lease 又不交给 venue（no-op 仪式，T-018 复核 #2 已点名），
  故不接。broker 入参保留作前向兼容 + 测试覆盖。**venue 只认 lease 的重构触实盘交易基线 → 独立任务 T-022。**
- relayer 第 2 步 `keystore.fetch` 预检（key 存在性）仍直握 keystore 句柄——同属 T-022 收口。
- 非 relay 的直连 live 下单路径（若有）：本次复核未发现其它未守门的真钱路径；relay 是 live-money 主路径，已守。

## 下一步：T-022（INV-3 lease-唯一-key venue 重构）——脊柱安全门最后一里。
