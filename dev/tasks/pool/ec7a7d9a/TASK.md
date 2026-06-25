---
uuid: ec7a7d9a07764b37bc23d49abb4c1284
title: 数据写门 scope 余项——11 字段 + data 级 lineage + on-disk manifest 自动接线（B-VERSION-1 余）
status: todo
owner: wait
assigned_by: dreaminate
review_status: 0
priority: P2
area: data-pit
source: goal
source_ref: GOAL §11/§16 + 0430cd78 完成记录诚实残余（核心 block 门 ✅·scope 余项 🟡）
depends_on: [0430cd78e7a944db83f3644451fd42ae]
---

# 数据写门 scope 余项（B-VERSION-1 余）

## Scope [必填]
0430cd78 已立核心写时 block 门（register 单点·缺 dataset_version/checksum/篡改→拒·11 对抗测试）。本卡补 canonical scope 余项（🟡）：① 补 11 字段（skill_version/secret_ref/effective_at 等）② data 级 lineage（现 lineage 是 strategy 级非 data 级）③ on-disk manifest（`dataset_hash.write_manifest`）随每次 register 自动落 + 校验（现仅 test 触达）④ `data_pull.py` 写路径直接接线（确认 register 单点已覆盖否则补）。**扩展不替换·实证驱动**。

## 接线点（实现复核）[必填]
- `app/backend/app/data_quality.py`（register 扩字段 + on-disk manifest 自动接）
- `app/backend/app/connectors/base.py`（FetchResult 补字段）
- `app/backend/app/lineage/`（data 级 lineage·复用 ids.py 不另造）
- `app/backend/app/data_pull.py`（写路径实证）

## 对抗验收（种坏门必抓）[必填]
1. 缺 skill_version/secret_ref → 拒（若提级为必备）。
2. on-disk manifest 同 version 内容漂移 → register 自动校验拒（接活已建不可变门）。
3. data 级 lineage 可追溯 dataset→factor。
4. 向后兼容（既有合法写入字节不变）。

## 红线 [按需]
数据缺 dataset_version/checksum/lineage 即停（§16 致命）·复用 lineage.ids.content_hash·扩展不替换·实盘 key/secret 不落明文（secret_ref 走引用）。
