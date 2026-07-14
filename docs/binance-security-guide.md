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

QuantBT 不会自动降级 backend：
- `QUANTBT_KEYSTORE_BACKEND=keyring` 要求真实可用的系统 keychain
- `QUANTBT_KEYSTORE_BACKEND=fernet_file` 要求 `QUANTBT_MASTER_KEY`，并使用私有加密文件
- `memory` 只允许显式 test/development runtime，不能承载生产真钱凭证

---

## 3. 软件做的硬约束（违反任意一条都拒绝下单）

| 边界 | 检查 | 失败时的行为 |
|---|---|---|
| mainnet 激活 | 认证权限证明必须显示交易权限、IP 限制开启且无 withdraw/transfer 能力 | 激活 fail closed，不创建 active follower |
| mainnet 激活 | 认证账户 UID、one-way position mode、非 multi-assets margin 与正净值/行情快照必须完整 | 激活 fail closed |
| 下单预检 | `exchangeInfo` 的 LOT_SIZE / PRICE_FILTER / MIN_NOTIONAL 必须可解析并严格量化 | 缺失、畸形或量化为零都在 POST 前拒绝 |
| 下单前 | 单笔名义上限 (`per_order_max_usdt`，默认 100) | `PreTradeError` |
| 下单前 | 黑名单 symbol | `PreTradeError` |
| 下单前 | 肥手指：限价偏离 mark > `fat_finger_pct`（默认 2%） | `PreTradeError` |
| 下单时 | 自动 quantize 数量到 LOT_SIZE 步长、价格到 PRICE_FILTER 步长 | 不达 minNotional 拒单 |
| 下单时 | 强制 `clientOrderId`（默认 uuid） | 网络抖动重传不会重复成交 |
| 运行中 | 单日下单笔数上限（默认 200） | 触达后 RiskMonitor 自动 `pause`，新单全部拒 |
| 运行中 | 单日亏损上限（默认 -5%） | 同上，且写入 audit log |
| 运行中 | 持仓集中度（单 symbol < 30% 净值） | warning 级别告警 |
| 一键 | **Kill Switch** (`POST /api/risk/kill_switch`) | 先持久 HALT epoch 并排空旧 lease，再撤单/平仓；仅新鲜 flat proof 可记为 halted |

---

## 4. testnet → mainnet 切换

**强烈建议**：先在 Binance testnet（`https://testnet.binance.vision` /
`https://testnet.binancefuture.com`）跑通一周完整策略再上 mainnet。

testnet 与 mainnet 使用不同的 versioned credential；不能复用 alias 偷换物理 key。mainnet 激活必须经过
可信 IP、服务端密码/TOTP、账户 UID/权限/仓位模式安全证明、testnet promotion 与独立审批，之后才写入
active follower。重启时持久 credential binding 或安全句柄不匹配会 fail closed。

---

## 4.5 模拟台（paper）testnet 真喂（可选档）

模拟台（paper run）默认用**捆绑样本回放 / 合成游走**喂 bar（零依赖、无 key 也能跑，跑出移动净值）。
如果你配了 **Binance testnet** key，可让 crypto paper run 自动切到喂**交易所 testnet 真实时行情**
（公共 K 线 / mark），更贴近真盘——这一档**仍是模拟撮合、永不下真单、不动真钱**。

### 怎么配（走持久加密 keystore，不进 git）

把 testnet key 以名字 **`binance_testnet`** 写入 keystore（与第 2 节同一接口；切勿落 YAML/环境变量/代码）：

```bash
curl -X POST http://127.0.0.1:8000/api/security/keystore \
  -H 'Content-Type: application/json' \
  -d '{"name":"binance_testnet","api_key":"<TESTNET_KEY>","api_secret":"<TESTNET_SECRET>"}'
```

testnet key 在 Binance Futures testnet 控制台申请：<https://testnet.binancefuture.com>（与 mainnet 完全
独立、是假钱）。

### 配好后怎么用

注册 paper run 时带 `testnet=true`（默认 `false`）：

```bash
curl -X POST http://127.0.0.1:8000/api/paper/runs \
  -H 'Content-Type: application/json' \
  -d '{"run_id":"crypto_tn_demo","market":"crypto","symbols":["BTCUSDT"],"testnet":true}'
```

- **配了 `binance_testnet` key 且连得上** → 喂 testnet 真实时 bar，`status` 里
  `provider_kind="testnet"`、`simulated_source="binance_testnet_live"`。
- **没配 key / testnet 连不上** → **诚实回退**到样本/合成兜底（不空跑、不假装连上真交易所）：
  `provider_kind="replay_fallback"`、`degrade_reason` 写明回退原因，`simulated_source` 仍是兜底真实标签
  （`bundled_sample_replay` / `deterministic_sim_walk`），**绝不**标成 `binance_testnet_live`。

### 安全边界（与实盘同源，绝不削弱）

- **testnet key 永不进 LLM / agent 提示词**：testnet 行情走**公共**端点（K线 / premiumIndex，无需签名），
  系统**只查 key 名是否存在、绝不取出明文 secret**（与 KeyBroker「仅查名、不 fetch 本体」同则）。
- **永走模拟撮合、永不下真单**：testnet 档只**读行情**喂模拟台，不碰任何 `place_order` / 下单签名路径。
- **仅 crypto**：A股 paper run 永不走 testnet（恒走兜底），且 A股**永不 live 下单**（致命错误防线不破）。
- testnet 端到端真发单矩阵另见 `pytest -m testnet`（需上面 `binance_testnet` key；默认 skip）。

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
- **API key 疑似泄露**：立即在 Binance 网页删除 key，重新创建 + IP 白名单 + 关 withdraw，再通过 UI/API 写入一个新 credential version；active 版本不能原地覆盖。
- **数据被改**：`data/datasets/registry.jsonl` 是 append-only，新写不能改旧版本；用 sha256 校验。
