# 给 GPT Pro 的 Binance Testnet 接入 audit prompt

> 用法：贴给 GPT Pro，让它输出 "我们这套 testnet 接入流程的 audit checklist + 12 cell matrix 真测参数 + 排错预案"。
> 假设 GPT Pro 已经看过 _NEW_PRO_HANDOFF.md，知道 M9 / M20 上下文。

---

## 提示词正文

你是 QuantBT 项目的 Binance USDM Futures testnet audit 专家。我手上有 **2025-12-09 已修复的** algoOrder migration 版本（v0.8.3.1 hotfix），即将给 testnet 真发单跑完整 12 cell matrix。

请给我一份**可直接执行的接入 audit 文档**，不要泛泛而谈。包含以下 7 节：

### §1. 注册 + Key 设置流程（要点检查）

逐步列出（我对照执行）：

1. 注册 https://testnet.binancefuture.com/ 的具体步骤
2. 创建 API key 时 default 给了哪些权限位 (enableTrade / enableReading / enableFutures / etc.)
3. 哪几个权限**必须显式关闭**才能通过我们 SafeKey wizard
4. testnet 上的 ipRestrict 行为和 mainnet 是否一致
5. testnet key 失效条件（什么时候会被回收）
6. testnet faucet 怎么领 USDT 测试余额（具体步骤）
7. testnet 与 mainnet symbol 命名差异（BTCUSDT vs BTC-USDT 之类）

### §2. 我们 12 cell matrix 的具体输入参数

我有 `app/backend/app/trading/safety.py` 的 `_DEFAULT_MATRIX_CELLS`:
```python
_DEFAULT_MATRIX_CELLS = [
    (t, s)
    for t in ["limit", "market", "stop_market", "take_profit", "stop_loss", "trailing_stop_market"]
    for s in ["buy", "sell"]
]
```

请给每个 cell 一份**精确的下单参数表**（用 BTCUSDT 测试）：

| cell | binance_type | side | quantity | price | stopPrice/triggerPrice | timeInForce | extra |
|---|---|---|---|---|---|---|---|
| limit buy | LIMIT | BUY | 0.002 | 当前价 -2% | — | GTC | reduceOnly=false |
| ... | | | | | | | |

要求：
- 给具体数字（quantity 用 minQty 上限的安全倍数；price 给"明显不会成交"的偏移避免污染 testnet 撮合）
- 区分老 `/fapi/v1/order` 和新 `/fapi/v1/algoOrder` endpoint
- 标明每个 cell 是 algoOrder 还是 legacy order
- 每个 cell 期望的 4 子指标 (place/query/cancel/reconcile) 该看什么字段判定 ok

### §3. 已知 testnet 与 mainnet 行为差异

至少列 8 条，每条给：
- 差异是什么
- 这个差异是否影响我们 12 cell matrix 的结果有效性
- 如果影响，怎么 mitigate

例如：testnet 撮合速度比 mainnet 慢 X / testnet funding rate 不真实 / testnet listenKey TTL 是否相同 / testnet 限频是否更严等。

### §4. WS UserDataStream 在 testnet 的特殊行为

`app/backend/app/execution/binance_ws.py` 的 BinanceUserDataStream:
- testnet WS URL 和 mainnet 是否不同？
- testnet listenKey 续期是否仍然是 25 分钟
- testnet 上 ORDER_TRADE_UPDATE 事件 schema 是否和 mainnet 完全一致
- testnet reconcile 走 GET /fapi/v1/openOrders 是否会被 rate limit

### §5. 我们这版条件单 (algoOrder) 在 testnet 是否真的工作

我们 hotfix 后走 POST `/fapi/v1/algoOrder` (params: algoType=CONDITIONAL, clientAlgoId, triggerPrice)。
请告诉我：
1. testnet 上这个 endpoint 是否 100% 可用
2. testnet 上 algoOrder 的 algoId 是否和 mainnet 一样是数字
3. cancel algoOrder 的 DELETE `/fapi/v1/algoOrder` 在 testnet 行为
4. 已知 bug / corner case（如果你知道）

### §6. 排错预案

列至少 10 个**最常见的 testnet error code** + 修复方法：

| 错误 | code | 触发场景 | 修法 |
|---|---|---|---|
| -1021 timestamp out of recv window | -1021 | 本地时间漂移 | sync_time() before signed |
| -1102 mandatory param missing | -1102 | 缺 quantity 或 triggerPrice | 检查 params dict |
| -2010 NEW_ORDER_REJECTED | -2010 | minQty/notional 不够 | 检查 exchangeInfo filter |
| -4120 algo order migration | -4120 | 条件单仍走旧 endpoint | 走 algoOrder（v0.8.3.1 hotfix 已修） |
| ... | | | |

特别要求：列出 **insufficient balance** / **margin insufficient** / **leverage 超出 max** 这几个的 error code 和我们 RiskMonitor 应如何拦截。

### §7. 完整 12 cell e2e 执行剧本

给出一份 bash + curl 风格的执行脚本（或 pytest fixture 形式），按依赖关系排序：

1. 启动 backend 后台
2. 注册测试用户 + 拿 token
3. 调 SafeKey wizard → 应通过
4. 配 Binance testnet key → 应通过
5. 跑 12 cell 顺序（哪些必须先于哪些）
6. 每个 cell 执行 + 验证 + 落 trading_testnet_matrix
7. 全 12 cell ok 后晋级 level_2

要求脚本带断言，失败时清楚提示哪步挂了。

---

### 输出格式要求

- 每节用 `## §X. ...` 标题
- 每节末尾给 "TL;DR 3 条" bullet
- 整体可粘进 `docs/operations/testnet_audit_v0.9.md`
- 总字数 ≥ 3500
- 数字必须基于 Binance 官方 docs（含 URL 引用）

---

### 我（用户）使用流程

1. 复制本文件 [docs/strategy/_PROMPT_FOR_GPT_PRO_TESTNET.md](docs/strategy/_PROMPT_FOR_GPT_PRO_TESTNET.md) 整段
2. 贴新对话给 GPT Pro
3. 把它输出存为 `docs/operations/testnet_audit_v0.9.md`
4. 我（Claude）拿到文档后：
   - audit §3 列出的 testnet/mainnet 差异，看哪些需要在代码里加 fallback
   - 把 §2 的 12 cell 参数表转成 pytest 真实 testnet e2e fixture
   - 把 §6 排错预案对照我们 RiskMonitor + binance_client 看是否都覆盖
   - 等用户 ready 给 testnet API key 后跑 §7 完整执行剧本
