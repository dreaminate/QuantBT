# T-025 · 真钱执行路径审计 + 急停/kill 控件收尾 + GenericVenue 接活

- **状态**：done · **review_status**：1（用户 2026-06-19 过目通过，同 T-023）
- **来源**：spine-designs 06 + STATE 诚实残余 + T-022 卡注 + R10/M17 + D-T025/D-T025-DIY · **依赖**：T-021/T-022 · **优先级**：P1

## 做了什么

1. **审计坐实**（`tests/test_realmoney_audit_killswitch.py`）：审计不变量测试——扫全 app `place_order` 直发调用点
   ⊆ {门后路径：`execution/leased_binance.py`、`copy_trade/executor.py`}（OrderGuard 经 `inner(order)` 别名调用=门本体，
   不计）；含探针自检（种门外调用点 → 必抓，证明非 no-op）。
2. **急停控件收尾**（`main.py`，D-T025 平仓 fail-open / 护栏在「谁能按按钮」）：
   - `/api/risk/kill_switch`：补人在环 **IP + 密码二次鉴权**（复用 `mainnet_guards`）；之前**无鉴权**。
   - `emergency_close_all`：从空壳（仅 log 意图）改为**真调 `KILL_SWITCH.trigger`**（cancel_all_open + close_position 全 symbol）。
   - 平仓/撤单本体 **fail-open**（门坏也要能救命平仓），与「下新单 fail-closed」相反方向，分开处理。
3. **GenericTradingVenue 接活**（`execution/generic_trading.py`，D-T025-DIY）：加 `deny_by_default` 白名单（空白名单=全拒）；
   `guarded_generic_venue()` 工厂——恒 deny-by-default + `OrderGuard.wrap`（与 relay/lease 同一道门，CRYPTO_LIVE 缺 nonce 台
   fail-closed）；**唯一受支持的「DIY venue 进真钱面」入口**。既有 `blacklist_symbols` 语义保留（向后兼容死代码期行为）。
4. **relay 向后兼容陷阱闭合**（`copy_trade/executor.py`）：`enforce_gate=False` 直发路径加真钱守卫——CRYPTO_LIVE
   即便 enforce_gate=False 也 fail-closed 拒（生产恒 True，此为纵深防御防误配旁路真钱）。

## 验收（对抗测试 + 5-lens 复核）

`tests/test_realmoney_audit_killswitch.py` 15 passed：绕门审计不变量 + 探针自检；kill 端点未登录/非白名单 IP/缺密码 → 403、
鉴权齐 → 真撤单真平仓 + 幂等重放；emergency 真平仓（非空 log）+ 非白名单 IP 403；relay 向后兼容真钱(mainnet)单 → rejected
且 venue.place_order 绝不被调；generic deny-by-default（空/非白名单拒）+ 向后兼容（默认不启用白名单）+ guarded venue 经
OrderGuard CRYPTO_LIVE fail-closed。全量 **1046 passed / 13 skipped**（基线未破）。

**5-lens 对抗复核**：1 HIGH + 1 LOW 真发现已修——`emergency_close_all`/`kill_switch` 把含 venue 平仓失败的 results
硬编码为 `ok:True` 且审计 `result="ok"`（🟡含失败当✅，真钱急停最不容假绿灯）；新增 `_killswitch_status()` 据 per-venue
results 派生诚实状态（全成功 ok / 部分 partial / 全失败 failed），失败 symbol·error 透传进响应与审计；补 2 条对抗测试
（平仓抛错 → ok:False + 审计非 'ok'）。

## 诚实限界（TCB 天花板，I-001 同源，不会再改）

本地门/审计只是**防篡改证据非防篡改**；急停 fail-open 平仓仍受**交易所侧**可用性约束（本地保证「不被本地门挡」，
不保证交易所一定成交）。GenericVenue「接活」= 提供 deny-by-default + OrderGuard 的受守构造入口 + 审计不变量钉死，
而非配置真实 DIY YAML/key 的 live 全局（无真实凭证）。
