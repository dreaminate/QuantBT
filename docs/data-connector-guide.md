# 数据源对接指南

QuantBT 把数据接入统一抽象为 `DataConnector`。你有 3 种方式接新数据源：

| 方式 | 改 Python | 适合 | 难度 |
|---|---|---|---|
| **GenericRESTConnector**（YAML 驱动） | ❌ 不改 | 任何 REST API | ⭐ |
| **UserUploadConnector**（上传 + mapping） | ❌ 不改 | csv / parquet / zip 文件 | ⭐ |
| **写新 Python connector** | ✅ 改 | 复杂协议 / WebSocket / FIX | ⭐⭐⭐ |

---

## 1. GenericRESTConnector · YAML 驱动

90% 的数据源走这条。

### YAML 完整 schema

```yaml
connector_name: my_alpha_source
label: My Alpha Source
asset_class: equity_cn             # 任选 equity_cn / crypto_spot / crypto_perp / external_macro / custom
supported_markets: [stocks_cn]
supported_intervals: [1d]

base_url: https://api.example.com

auth:
  mode: header                     # none / bearer / header / query
  header_name: X-API-KEY           # 仅 header 模式
  value_env: MY_TOKEN_ENV          # 真实值走环境变量；不写 YAML

endpoints:
  ohlcv:
    method: GET
    path: /v1/quote/{symbol}/daily
    query:
      start: "{start_date}"
      end: "{end_date}"
    pagination:
      style: cursor                # cursor / page / offset / none
      cursor_in: "$.next"
      cursor_out_param: cursor
    rate_limit_per_minute: 60
    response_mapping:
      records: "$.data[*]"         # 把数组拿出来
      fields:
        ts: timestamp
        open: o
        high: h
        low: l
        close: c
        volume: v
      ts_unit: ms                  # s / ms / us / iso / date
      tz: UTC

schema_target: ohlcv
```

### 模板变量

`{symbol}` `{interval}` `{market}` `{start_date}` `{end_date}` `{start_iso}` `{end_iso}`
`{start}`（秒级 unix）`{end}`，以及 `FetchRequest.extra` 中的任何 key。

### 4 个真实例子

#### 例 1：本地 ollama Q&A endpoint（虽然不是数据源，演示 YAML 模板能力）

```yaml
connector_name: local_mock
base_url: http://localhost:8080
endpoints:
  ohlcv:
    method: GET
    path: /ohlcv/{symbol}
    response_mapping:
      records: "$.bars"
      fields: {ts: t, open: o, high: h, low: l, close: c, volume: v}
      ts_unit: ms
```

#### 例 2：CoinGecko 价格（免费 30 req/min）

```yaml
connector_name: coingecko_market_chart
asset_class: crypto_spot
supported_intervals: [1d]
base_url: https://api.coingecko.com/api/v3
endpoints:
  ohlcv:
    method: GET
    path: /coins/{symbol}/market_chart
    query: {vs_currency: "usd", days: "{days}"}
    rate_limit_per_minute: 30
    response_mapping:
      records: "$.prices[*]"       # [[ts_ms, price]]
      fields:
        ts: 0                       # 数组 index 风格，JSONPath 子集不支持，需要写 Python adapter
        close: 1
      ts_unit: ms
```
（CoinGecko 数组型响应需要更复杂的 mapping，这里仅示意 — 真实场景建议写 Python connector）

#### 例 3：私有 quant1 API（兼容 OpenAPI）

```yaml
connector_name: my_quant1
asset_class: equity_cn
supported_markets: [stocks_cn]
base_url: https://internal.quant1.example
auth:
  mode: bearer
  value_env: QUANT1_TOKEN
endpoints:
  ohlcv:
    method: GET
    path: /v2/stock/{symbol}/daily
    query: {from: "{start_date}", to: "{end_date}"}
    rate_limit_per_minute: 600
    response_mapping:
      records: "$.data[*]"
      fields: {ts: date, open: open, high: high, low: low, close: close, volume: volume, amount: amount}
      ts_unit: date
```

#### 例 4：玩腻 hosted LLM 想接 Glassnode 链上指标作外部概率特征

```yaml
connector_name: glassnode_free
asset_class: external_onchain
supported_intervals: [1d]
base_url: https://api.glassnode.com/v1/metrics
auth:
  mode: query
  query_param: api_key
  value_env: GLASSNODE_KEY
endpoints:
  ohlcv:
    method: GET
    path: /indicators/sopr
    query: {a: "{symbol}", since: "{start}", until: "{end}", i: "24h"}
    rate_limit_per_minute: 10
    response_mapping:
      records: "$"                  # Glassnode 返回数组顶层
      fields: {ts: t, close: v}
      ts_unit: s
```

### 注册到 QuantBT

把 YAML 落到 `connectors/your_name.yaml`，然后：

```python
from app.connectors import GenericRESTConfig, GenericRESTConnector, registry
cfg = GenericRESTConfig.from_yaml(open("connectors/your_name.yaml").read())
registry.register_instance(cfg.connector_name, GenericRESTConnector(cfg))
```

或在 UI 数据中心 → connector 表单粘贴 YAML 一键导入（前端待补）。

---

## 2. UserUploadConnector · 上传文件

适合：你有别处导出的 csv / parquet / zip，想用 QuantBT 跑回测。

```python
from app.connectors import UploadFieldMapping, UploadDatasetRegistration, UserUploadConnector
from pathlib import Path

reg = UploadDatasetRegistration(
    upload_id="my-2024-data",
    files=["klines.csv"],
    mapping=UploadFieldMapping(
        ts="date",
        symbol_constant="BTCUSDT",
        close="close",
        open="open",
        high="high",
        low="low",
        volume="volume",
        ts_unit="date",
        market="custom",
        interval="1d",
    ),
)
conn = UserUploadConnector(reg, upload_root=Path("data/raw/uploads"))
```

---

## 3. 写新 Python connector

继承 `DataConnector`，实现 `describe()` 和 `fetch()`：

```python
from app.connectors.base import DataConnector, ConnectorCapability, FetchRequest, FetchResult, make_fetch_result

class MyConnector(DataConnector):
    def describe(self):
        return ConnectorCapability(
            name="my_connector",
            label="My Custom Data",
            asset_class="custom",
            supported_markets=("custom",),
            supported_intervals=("1d",),
            supported_data_kinds=("ohlcv",),
            auth_mode="none",
            rate_limit_per_minute=None,
            realtime=False,
        )

    def fetch(self, request: FetchRequest) -> FetchResult:
        # 你自己拉数据，返回 polars DataFrame
        df = ...
        return make_fetch_result(df, source_name="my_connector")
```

注册：
```python
from app.connectors import registry
registry.register_instance("my", MyConnector())
```

---

## 4. UnifiedOHLCV schema（所有 connector 必须遵守）

```
ts:       pl.Datetime("us", "UTC")
symbol:   str
market:   str (任意，比如 "stocks_cn" / "binanceusdm")
interval: str (比如 "1d" / "1h" / "1m")
open:     f64
high:     f64
low:      f64
close:    f64
volume:   f64
amount:   f64 (turnover；缺失填 0.0)
```

`enforce_unified_schema(df)` 工具函数会自动补缺失列、cast 类型、按 (symbol, ts) 排序。

---

## 5. dataset_version 注册（GOAL §M3 数据治理）

每次 `fetch()` 返回的 `FetchResult` 都带 sha256 + coverage + row_count，自动可入
`DatasetRegistry`（append-only，**永远不可变**）：

```python
from app.data_quality import DatasetRegistry, GERule
reg = DatasetRegistry(Path("data/datasets/registry.jsonl"))
result = my_connector.fetch(FetchRequest(symbol="BTC", interval="1d"))
version = reg.register(
    dataset_id="btc_daily",
    fetch_result=result,
    file_paths=["raw/btc.parquet"],
    rules=[
        GERule(column="close", rule_type="not_null"),
        GERule(column="ts", rule_type="unique"),
        GERule(column="ts", rule_type="monotonic", params={"order": "asc"}),
    ],
)
```

`compute_freshness(dataset_id, market_kind, reg)` 返回 green/yellow/red 报告。
