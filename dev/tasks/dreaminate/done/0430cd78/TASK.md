---
uuid: 0430cd78e7a944db83f3644451fd42ae
title: 数据更新写时强约束——dataset_version/checksum/lineage 升 block 门（B-VERSION-1）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: data-pit
source: goal
source_ref: GOAL §11/§16（数据缺 dataset_version/checksum/lineage→拒·致命错误）+ 施工图 LINE-B W3
depends_on: []
---

# 数据更新写时强约束（B-VERSION-1）

## Scope [必填]
`DatasetVersion` + `dataset_hash` 对象已建，但**写时是否过 version gate 需运行期实证（存疑·可能只 advisory）**，且 lineage 是 strategy 级非 data 级。本卡：**首动作=实证 data_pull 写时是 gate 还是 advisory**；补 11 字段（skill_version/secret_ref/effective_at）+ 把约束提级为 **block**（缺即拒，非警告）+ data 级 lineage。

## 文件领地（owner·并发隔离）
`data_pull.py` `data_quality.py`(写门) `lineage/`(data 级 lineage)。**LINE-B·与 B-PIT(training/) 不同文件可并行**。

## 接线点（file:line·实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/data_pull.py` | 数据写入路径 | 实证写时门→提级 block + 补字段 |
| `app/backend/app/data_quality.py` | 写门 | 缺 dataset_version/checksum→拒 |
| `app/backend/app/lineage/` | lineage | data 级（非仅 strategy 级） |

## 对抗测试设计（种坏门必抓）[必填]
1. **命门**：数据写入缺 `dataset_version`/`checksum` → 必拒（红线致命·种坏门必抓）。
2. 数据缺 PIT 语义进 confirmatory validation → 拒。
3. 变异：把 block 退回 advisory → 测试必红（证明是真 gate 不是警告）。

## 复用 [按需]
`DatasetVersion`/`dataset_hash`（已 done）· `lineage/ids.py` content_hash（**不另造**）· B-PIT 的 PIT 机制。

## 红线 [按需]
数据更新缺 dataset_version/checksum/lineage 即停（§16 致命）· 扩展不替换 · 单一身份源。

## 非目标 [按需]
不做 IngestionSkill 生命周期（B-SKILL 另卡）；不改 PIT resolver。

## 完成记录（2026-06-26·第一波整合 land·中心 orchestrator）
- 实现 commit `d1d69a9`（分支 `wave1/w3-dataset-write-gate`）→ 中心 merge `6ea6097`。
- 写路径实证 = 唯一登记单点 `DatasetRegistry.register()`（data_quality.py）原为 advisory（算 version_id 直接 append·零校验）；接 `FetchResult.validate_for_write`（缺 dataset_version / 缺 checksum / checksum 重算篡改→拒），复用 `_sha256_of_frame` 单源·绝不另造哈希·不碰 field_catalog。**advisory→block 门已立**。
- 对抗：`test_dataset_write_gate.py` 11 passed·MUT-A（register 接线）7 红 / MUT-B（篡改分支）2 红双抓·向后兼容（含空 frame）不误伤。✅
- **诚实状态：核心写时 block 门（缺 version/checksum→拒）✅；本卡 scope 余项 🟡 = follow-on P2**——① `data_pull.py` 写路径直接接线（本卡选 register 单点已覆盖 intake 等全部写路径）② 11 字段补全（skill_version/secret_ref/effective_at）③ data 级 lineage ④ on-disk manifest（dataset_hash.write_manifest）自动接线 均未做。核心红线门已强制。
