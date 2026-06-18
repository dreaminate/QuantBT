# T-025 · 真钱执行路径审计 + 急停/kill 控件收尾

- **状态**：todo（卡已过目，待 2 岔路点头后开工）
- **review_status**：0
- **来源**：spine-designs 06 + STATE 诚实残余#2 + T-022 卡注（非-relay live 路径未逐一确认）+ R10/M17
- **优先级**：P1（安全收尾，但**经主进程现实核对：live 下单面已基本设防**，本卡是审计坐实 + 补急停控件）
- **依赖**：T-021（relay 闸门）、T-022（INV-3 lease）
- **波次**：簇A 脊柱收尾（收口第一波）

## 现实核对结论（主进程已 grep/读源坐实，纠正侦察初稿的过度报警）

**真实 live 下单面 100% 经门**：全 app 唯一的 `place_order` 调用点是 `executor.py:148`（OrderGuard 门后路径）、`executor.py:122`（`enforce_gate=False` 向后兼容,testnet/paper）、`leased_binance.py:60`（门后 S4 现造）。生产 relayer `main.py:1814` 已 `enforce_gate=True`。`GenericTradingVenue` **全 app 无实例化**（死代码,未接活路径）；`BinanceUM/Spot` 只在 `LeasedBinanceVenue` 内部（门后）实例化。

**所以 T-025 的真残余不是「真钱可被绕过下单」,而是「急停/kill 控件不完整 + 端点鉴权缺口」**，按此校准 scope。

## 真钱路径清单（审计现状）

| 路径 | 文件 | 现状 |
|---|---|---|
| relay 下单 | `copy_trade/executor.py:148` | ✅ 门后（`enforce_gate=True` 生产，CRYPTO_LIVE fail-closed） |
| lease 现造下单 | `execution/leased_binance.py:60` | ✅ 门后 S4（无 lease→PermissionError，INV-3） |
| 向后兼容直发 | `copy_trade/executor.py:122` | ⚠️ 仅 `enforce_gate=False`（testnet/paper）；生产不走 |
| `/api/risk/kill_switch` | `main.py:1322` | ❌ **端点无鉴权**；`KILL_SWITCH=KillSwitch([])` 当前空 venue |
| `KillSwitch.trigger` | `risk/checks.py:155-185` | ⚠️ getattr 动态派发 cancel/close（风险**降低**动作,非下新单） |
| `emergency_close_all` | `main.py:981-998` | ❌ **空壳**：仅 log 意图、不真平仓（需 IP+密码）→ 急停按钮当前无效 |
| `GenericTradingVenue.place_order` | `execution/generic_trading.py:114` | ⚠️ 局部黑名单非 deny-by-default；但**未被实例化**（死代码） |

## Scope（单一能力单元）

1. **审计坐实**：写审计测试钉死「除门后路径外无活的 `place_order` 调用点」这一不变量（防未来新增绕门路径）。
2. **急停控件收尾**：
   - `emergency_close_all`：从空壳改为真调 venue cancel/close（经 OrderGuard 或显式豁免——见 Open Question）。
   - `/api/risk/kill_switch`：补端点鉴权（IP+密码二次,对齐 `mainnet_guards`）。
3. **防回归**：`GenericTradingVenue` 若未来接活,工厂处必经 OrderGuard.wrap + deny-by-default。

## 对抗测试设计（种已知 bug，门必抓）

1. **绕门不变量**：审计测试断言全 app `place_order` 调用点集合 ⊆ {门后路径}；种一个直连 `venue.place_order` 调用 → 测试必红。
2. **kill_switch 端点鉴权**：未带 IP/密码 POST `/api/risk/kill_switch` → 403（当前缺失,必补）。
3. **relay 向后兼容陷阱**：`enforce_gate=False` 下真钱单 → 须拒/告警（生产强制 True）。
4. **emergency 真执行**：调 `emergency_close_all` 后 venue cancel/close **真被调**（当前仅 log → 必红直到修）。
5. **generic deny-by-default**：若接活,空白名单下单不存在 symbol → 拒。
6. **kill/close 重放幂等**：连发两次 kill → 幂等或拒（按 fail 模式决策）。
7. **tier 单调**：CRYPTO_LIVE 拒的单,任何路径都拒。

## 复用模块

`security/gate/enforcer.py:OrderGuard` · `policy.py:PolicyGate` · `broker.py:KeyBroker` · `nonce.py:NonceLedger` · `copy_trade/gate_binding.py:follower_gate` · `security/mainnet_guards.py:assert_mainnet_allowed`（已存在,kill/emergency 复用其 IP+密码校验）。

## 红线（RULES §5）

- **杠杆护栏被中继/DIY 绕过即停工**：审计不变量是硬测试,新增绕门路径必红。
- **任何真钱 `place_order` 无 OrderGuard 即红线**。
- **CRYPTO_LIVE 缺 nonce/fail-closed = 可下重放单**（已由 T-021 守,本卡回归测试钉住）。

## Open Questions（需关闭——含 1 个需用户拍板的新岔路）

- **[需拍板·新岔路]** **kill_switch / emergency_close_all 的 fail 模式?** DECISIONS（D-T021-3 只覆盖 relay 下新单 fail-closed）未覆盖**风险降低**动作。候选：(a) **fail-open**（紧急优先,平仓/撤单永不被门挡,只在 trigger 端点加人在环 IP+密码）；(b) fail-closed（close 也过门,门坏则拒——危险,可能挡住救命平仓）。**建议 (a)**：平仓本体 fail-open，护栏放在「谁能按按钮」（端点鉴权）而非「能不能平仓」。需你定。
- `emergency_close_all` 当前是设计未落地还是 v0.9 placeholder？建议本卡落地为真执行（依 fail 模式决策）。
- `mainnet_guards` 与 OrderGuard 升级链路重复（各自 log+check）：是否统一？建议本卡只复用 `mainnet_guards` 做端点鉴权,不重写。
- `GenericTradingVenue` 是否计划接活（DIY 策略）？若否,标死代码 + 加「接活必经门」测试守护即可,不在本卡实现 wrap。

## 验收一句话

种一个绕门 `place_order` → 审计测试必抓；kill_switch 端点无鉴权 → 403；emergency 真调 venue 平仓（非空 log）；不破坏 1001 基线。
