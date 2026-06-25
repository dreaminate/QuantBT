---
uuid: e1a98c41ef2e47009bf31dc361fc4f04
title: binance_vision_pull reload-merge schema bug 修——多日同年 try_parse_dates 崩
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: data-connectors
source: developer-claude
source_ref: 2026-06-22 DS-1 实装时发现的 pre-existing bug（已绕开未碰）
depends_on: []
---

# binance_vision_pull reload-merge bug 修

## Scope [必填]
修 `app/backend/app/binance_vision_pull.py` 的 `pull_vision_klines_date_range`（经 `_pull_vision_kline_like`）多日同年 range 拉取时的预存 schema bug：第 2 天起 reload 已写分区用 `pl.read_csv(path, try_parse_dates=True)` 把 `timestamp` 读成 `Datetime`，与新解析的 `String` timestamp `pl.concat(how="vertical")` 报 `SchemaError: type String is incompatible with Datetime`。**DS-1 已绕开此函数（自写无状态并发捆绑），本卡修源函数本身**。修法：reload 不解析日期（`try_parse_dates=False`）或落盘前/读回后统一 timestamp dtype；扩展不替换，不破其它 vision 拉取路径。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/binance_vision_pull.py | ~301 `pl.read_csv(path, try_parse_dates=True)` + `_merge_by_timestamp_iso` | reload 不解析日期 / 统一 timestamp dtype，concat 不报 SchemaError |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. `pull_vision_klines_date_range` 跨多日同年（≥2 天）→ 不报 SchemaError、落盘 CSV 行数=有效天数（复现旧 bug：回滚修复→测试红）。
2. 单日 / 跨年 range 仍正常（不破其它路径）。

## 验收一句话 [必填]
多日同年 Vision 拉取不再 SchemaError 崩；其它拉取路径不破；不破基线。

## 完成记录（2026-06-24 · deliver-final）
- 修复在 commit `ac72b81`（已在 delivery-slice/deliver-final）：提取 `_reload_partition_csv(try_parse_dates=False)` 应用全 4 个 reload 点（klines/agg_trades/trades-metrics/funding），多日同年 concat 不再 SchemaError；含 3 对抗测试（复现旧 bug + 多日同年 merge + 单日/跨年兼容）。
- 本波收尾仅落档（卡此前已完成、未归档）；全量后端 1357 passed / 0 failed 覆盖。
