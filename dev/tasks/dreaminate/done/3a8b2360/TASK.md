---
uuid: 3a8b23604bcd493e8dcdf8bee01c24a4
title: R28 全库双时态（known_at 轴 + as-of 重述基本面）（T-033 核验 gap）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: 数据
source: research
source_ref: 2026-06-20 T-033 核验（gap: pit_bitemporal）+ state.md:35 / R28
depends_on: []
---

# R28 全库双时态（known_at 轴 + as-of 重述基本面）

## Scope [必填]
落地 R28 全库双时态：当前连 first-seen `known_at` 都未在面板层落地（T-033 坐实 + state.md:35）。分阶段：① `known_at` 列（keep first）+ `load_panel` 的 `as_of_known` 参数；② `end_date × known_at` 双轴不折叠（支持基本面重述 as-of 查询）。

## 上下文 / 动机 [按需]
T-033：grep known_at/knowledge_date 全 0 命中（仅 ann_date）；catalog.py:233 `unique(subset=[ts,symbol],keep=last)` 把重述折叠成一行；resolver.py 的 PIT 是单轴 as-of（防 lookahead 非双时态）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/field_catalog/catalog.py | 44 _TS_CANDIDATES / 233 unique 折叠 | 加 known_at 轴、重述不折叠 |
| app/backend/app/connectors/tushare_provider.py | 1934-1953 ann_date | 落 first-seen known_at |
| app/backend/app/*/resolver.py | as-of | 加 as_of_known 双轴 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 同 (end_date, symbol) 两条重述（known_at=2024-01-30 值=10.0 / 2024-04-15 值=10.5）→ `as_of_known=2024-02-01` 读 10.0、`as_of_known=2024-05-01` 读 10.5；单轴折叠则读到 10.5 → 红。
2. 单轴 PIT 回归：universe 插未来 ts 行 → `resolve_universe(as_of)` 不纳入（守 lookahead 基线、防双时态改造回退）。

## 验收一句话 [必填]
as-of 重述读对应时点值；不破单轴 PIT 基线。

## 实现落账（done · 2026-06-22 · D-WAVE1A · 全 Stage①② · D-AXIS=A / D-NECESSITY=B）
**评审 CTV-4 修正（接线点路径也漂了）**：真 provider = `tushare_quant1/tushare_provider.py`（非卡写的 `connectors/tushare_provider.py`）。CTV-4 称「写层 keep='last' fold first-seen」**部分错**：财报 `unique_keys` 含 `ann_date`（line 598/658/...）→ **不同 ann_date 重述写层保留**；只有**同 ann_date 脏重述**（Tushare f_ann_date 复用/null）被 `keep='last'` 丢。真正系统性丢 first-seen 的是**读层** `catalog.py:233` 无条件折叠（被 `test_data_contract.py:139` 固化）。两子系统是「写 CSV→inventory→field_catalog 读」一条链 → known_at 写层造列、读层透传。

**实装（扩展不替换 · D-AXIS=A 写层 owns）：**
- 写层 `tushare_provider.py`：`KNOWN_AT_COLUMN`+`_spec_needs_known_at`（仅财报）+`_derive_known_at`（known_at=ann_date；脏/空→写入日下界）+`_upsert_partition` keep-first-on-known_at（同身份多 known_at 取最早=first-seen own+re-backfill 不推进；行情类无列走原 keep='last' 不变）。
- 读层 `field_catalog/catalog.py`：`load_panel` 加 `as_of_known`（known_at<=该日过滤→同(ts,symbol)取最新已知重述、折后 drop known_at 保宽表契约）+ `keep_known_at_axis`（Stage② 双轴长表）+ `_read_dataset` extra_cols 保 known_at + `_STRUCTURAL` 收 known_at（不当因子暴露）。默认 `as_of_known=None` 逐字现状（守 :139）。
- `contract.py`：`PanelResult` 加 `as_of_known`/`has_known_at_axis`（additive）。
- resolver `universe/resolver.py`：`resolve_universe`/`_series` 加 `as_of_known` 第二轴（默认 None 不破单轴 PIT）；`as_of_bound` 升 public（单一源，catalog 复用）。

**门必抓（8 测试 + 2 变异）：** 写层 `test_known_at_writelayer.py` 5 测试（不同 ann_date 重述各成行/同 ann_date 脏重述守首披/re-backfill 幂等/existing 不覆盖/行情类不变）；读层 `test_data_contract.py::..._as_of_known_restatement_query`（重述 as-of 点查 10.0↔10.5 + Stage② 双轴 + known_at 不暴露）；resolver `test_universe.py` 双轴 + 单轴回归（未来 ts 不绕过）。变异：写层 keep='first'→'last' 读 10.5 红；读层忽略 as_of_known 读 10.5 红。**全量 1251 passed/13 skipped**（基线 1243+8 未破，133s）；validate_dev PASS。

**取舍裁定：** 1=A（null known_at 排除 as_of_known 视图，守 §5 前视）· 3=A′（resolver 暴露 public `as_of_bound`、catalog 复用，比新建 util churn 小）· 4=接受 utc_now 兜底。**取舍2 默认 A**（机制全库就绪；v2 通用源 known_at 暂不强填，待价值分批回灌——你可改 B）。

**诚实残余/限界：** ① `keep_known_at_axis` 多数据集双轴对齐 ill-defined（各表重述 known_at 不齐），仅单数据集语义干净（限界，长表用于单财报集分析）。② v2 connectors（binance/upload/generic）落盘无 known_at（取舍2=A 范围边界，机制已就绪，按需回灌）。③ utc_now 兜底：删库全量重灌会改 ann_date-脏行的兜底 known_at（脏数据本无真相，first-seen 下界足够防前视）。④ 量化流程各模块尚未传 `as_of_known`（参数就绪、调用方按需接，非阻断）。
