# T-022 · 安全门 INV-3：venue 只认 lease 签名（移除 self-fetch）+ 生产注入 broker

- **状态**：✅ done（2026-06-18，relay 路径 INV-3 闭合）· **review_status**：0
- **来源**：spine 06 §4 + INV-3 + R7/R12 · **依赖**：T-021（relay 闸门生产强制）
- **优先级**：P2

## 做了什么

T-021 把 deny-by-default 策略门接进 relay（INV-2/M17/INV-4 生产强制），但生产 binance venue 仍在工厂
self-fetch key（构造即持 creds）。T-022 关掉 self-fetch，落地 **INV-3 lease-唯一-key 通道**：

- 新增 `app/execution/leased_binance.py` `LeasedBinanceVenue`：**构造时不持任何 key**；`place_order(order, lease)`
  从 `lease.record` 现造 creds+client+真 venue 签名提交——真 key 只在放行后那一刻活在后端内存。无 lease →
  `PermissionError` fail-closed（INV-3：无 lease=无 key=下不了单）。私有端点（get_position/balance/cancel）同样只认 lease。
- `get_mark_price`：**keyless 公共端点**（futures premiumIndex / spot ticker），lease 之前即可核名义额 →
  保住 T-021 fix B（市价单名义额核验）在 lease-only 下仍可用；失败/0 → None（门 fail-safe deny）。
- `KeyBroker.has_key`：存在性预检走 `keystore.list_names()`（**只查名字、不 fetch 本体**）→ relayer 预检不物化 key。
- executor `_place`：注入 broker 时 OrderGuard S4 发 JIT lease → `_submit(order, lease)` → LeasedBinanceVenue
  从 lease 现造 creds；`_trusted_mark` 优先用 lease-free 的 `get_mark_price`（退化到 get_position 兼容 mock）。
- main.py：`ORDER_BROKER = KeyBroker(KEYSTORE)`；`_binance_venue_for_follower` 返回 creds-less LeasedBinanceVenue
  （不再 eager fetch）；生产 relayer 注入 `broker=ORDER_BROKER`。
- **既有 BinanceUMFuturesVenue / BinanceSpotVenue / BinanceClient 零改动**（additive：成为 lease 现造的内核）→
  实盘签名逻辑零回归面。

## 验收（10 对抗测试 + 4 变异全杀 + 5-lens 复核 15→1 真发现[LOW]修）

`tests/test_leased_binance.py`（8：构造不持 key / 无 lease fail-closed / creds 只从 lease 现造 / spot 内核 /
公共 mark keyless / 取价失败 fail-safe / 带 lease 委托内核）+ `tests/test_copy_trade_gate.py` 新增 2
（**INV-3 命门：真 key 只在门放行后 S4 物化恰一次、门拒则永不物化** / has_key 不物化）。
全量 **1000 passed / 13 skipped**（基线 990 未破）。变异 4 个全杀（lease-required 删除 / has_key 改 fetch 物化 /
_kernel 忽略 lease / INV-3 计时）。

**5-lens 对抗复核**：15 raw → **1 真发现（LOW）**：executor `_place` 旧注释称「生产未注入 broker」与 T-022
main.py 接线矛盾 → 已更正。0 HIGH / 0 MEDIUM——additive 设计（既有 venue 不动）+ key 物化时序正确 +
lease-only 强制，经异模型复核无真实 INV-3 漏洞。

## 诚实 TCB 边界 / 残余

- **TCB 天花板**（设计 §7-5）：broker 与 venue 都在属主机进程内存——lease 把 key 暴露窗口从「venue 全生命周期」
  收窄到「单次 place_order」，**抬高代价、非干净修复**；被攻破属主机时短时 lease 仍可被截。本地门对属主始终
  只是防篡改证据，唯一真硬墙在交易所侧（子账户限额 / 交易专用+IP 白名单 key）。
- relayer 构造仍传 keystore 句柄，但 T-022 后存在性预检走 broker.has_key（list_names 不 fetch）→ relay 路径
  不再经 relayer 物化 key；keystore 句柄保留作非 broker 旧调用兼容。
- 非 relay live 路径（emergency_close_all 等）：本次复核未确认其它未走 lease 的真钱下单路径；relay 是 live-money 主路径。

## 脊柱安全门收口

T-018 gate 组件 → T-019 审批门 → T-020 验证官 → **T-021 relay 闸门生产强制（INV-2/M17/INV-4）→ T-022 INV-3
key 只在门后物化**。安全门生产接线全链闭合。**BOARD 无 todo**——脊柱 + 治理漏斗 + 安全门生产强制全部建并验证。
