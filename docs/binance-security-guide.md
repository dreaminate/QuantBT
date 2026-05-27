# Binance 实盘安全指南

> QuantBT 把 Binance 实盘默认放在「最严」安全档位。本指南教你正确配置 API key
> 并理解软件在每个边界做了什么，**不要绕过任何检查**。

---

## 1. 准备 Binance API key

1. 登录 Binance → API 管理 → **创建 API key**（推荐"系统生成"模式）。
2. **权限严格按以下勾选**：
   - ✅ 启用读取 (Enable Reading)
   - ✅ 启用现货 & 杠杆交易 (Enable Spot & Margin Trading)
   - ✅ 启用合约 (Enable Futures) — 仅当你要做 USDM Futures
   - ❌ **关闭 提现 (Enable Withdrawals)** — **必须关**，QuantBT 启动时会校验
   - ❌ 关闭 万能划转 (Enable Internal Transfer / Universal Transfer)
3. 开启 **IP 白名单**：把你跑 QuantBT 的机器公网 IP 加进去。
4. 妥善保管 secret —— Binance 只会显示一次。

---

## 2. 写入 QuantBT keystore

不要把 key/secret 放进任何 `.yaml` / `.json` / 环境变量 / 代码注释。
通过 UI（工坊 → Binance 交易台）或 REST：

```bash
curl -X POST http://127.0.0.1:8000/api/security/keystore \
  -H 'Content-Type: application/json' \
  -d '{"name":"binance_mainnet","api_key":"<KEY>","api_secret":"<SECRET>"}'
```

QuantBT 自动选择 backend：
- 优先 **macOS Keychain / Win Credential Manager / Linux libsecret**（`keyring`）
- 退到 **Fernet 加密文件**（`cryptography` + 用户主密码，PBKDF2 200k 迭代）
- CI/测试退到 **内存**

---

## 3. 软件做的硬约束（违反任意一条都拒绝下单）

| 边界 | 检查 | 失败时的行为 |
|---|---|---|
| 启动前 | `GET /sapi/v1/account/apiRestrictions` 或 `/fapi/v1/apiKey/permissions` 必须返回 withdraw=false | `BinanceWithdrawPermissionError` 抛出，进程不接管 |
| 启动前 | `/api/v3/time` 或 `/fapi/v1/time` 校时 + 缓存时差 | 失败仅 warning（不拦截，但下单时签名会失败让你修） |
| 启动前 | `exchangeInfo` 拉一次 LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL 缓存 | 缺则下单时按交易所拒绝 |
| 下单前 | 单笔名义上限 (`per_order_max_usdt`，默认 100) | `PreTradeError` |
| 下单前 | 黑名单 symbol | `PreTradeError` |
| 下单前 | 肥手指：限价偏离 mark > `fat_finger_pct`（默认 2%） | `PreTradeError` |
| 下单时 | 自动 quantize 数量到 LOT_SIZE 步长、价格到 PRICE_FILTER 步长 | 不达 minNotional 拒单 |
| 下单时 | 强制 `clientOrderId`（默认 uuid） | 网络抖动重传不会重复成交 |
| 运行中 | 单日下单笔数上限（默认 200） | 触达后 RiskMonitor 自动 `pause`，新单全部拒 |
| 运行中 | 单日亏损上限（默认 -5%） | 同上，且写入 audit log |
| 运行中 | 持仓集中度（单 symbol < 30% 净值） | warning 级别告警 |
| 一键 | **Kill Switch** (`POST /api/risk/kill_switch`) | 撤销所有挂单 + 市价平所有仓位 |

---

## 4. testnet → mainnet 切换

**强烈建议**：先在 Binance testnet（`https://testnet.binance.vision` /
`https://testnet.binancefuture.com`）跑通一周完整策略再上 mainnet。

切换在 BinanceCredentials 上做：

```python
from app.execution.binance_client import BinanceCredentials, BinanceClient
from app.security import SecureKeystore

ks = SecureKeystore.open()
rec = ks.fetch("binance_mainnet")
cred = BinanceCredentials.from_record(rec, network="mainnet")  # ← 显式 mainnet
client = BinanceClient(cred, product="spot")
client.assert_safe_startup()   # 此处会撞 withdraw 校验，若没关会抛
```

UI 上 mainnet 切换需要**二次确认弹窗** + 写入 audit log（`/data/audit/`）。

---

## 5. 强制阅读的"致命错误清单"（GOAL §12）

如果你或团队成员触犯任意一条，立即停下：

- ❌ **Binance API key 启动时未做"无 withdraw 权限"校验** → QuantBT 已自动校验，但请勿魔改源码
- ❌ **Binance API key / secret 明文落 YAML / 数据库 / 日志** → 走 keystore
- ❌ **加密策略在 mainnet 没经过 testnet 跑通就直接放出去** → 强烈不建议
- ❌ A股策略代码出现 `import vnpy / easytrader / ths_trader` 等券商网关 → A股不下单

---

## 6. 紧急情况

- **Kill Switch 不响应**：直接登 Binance 网页 → 取消所有挂单 → 转为现货 / 平仓
- **API key 疑似泄露**：立即在 Binance 网页删除 key，重新创建 + IP 白名单 + 关 withdraw，QuantBT 这边走 `DELETE /api/security/keystore/{name}` 删本地。
- **数据被改**：`data/datasets/registry.jsonl` 是 append-only，新写不能改旧版本；用 sha256 校验。
