# T-013 · lineage 一本账（SQLite WAL + JSONL，honest-N + memoize）

- **状态**：✅ done（2026-06-17）
- **review_status**：1（用户 2026-06-19 确认）
- **来源**：spine-designs 03（§3.4 ledger / §5 T3/T7/T8/T9/T11）+ 05（§5 T10–T15）+ S2/S4 + 复核 00 §1.2-A/I
- **优先级**：P0 · **依赖**：T-012（`ids.py` 单一身份源）

## Scope（单一能力单元）

建【一本账】= honest-N 计数 + memoize 缓存【物理同源】的 append-only 试验账本。
**只做**存储 + honest_n + memoize + tombstone + 防篡改对账；
**不做** N_eff 收益聚类 / DSR-PBO-bootstrap gate（那是 T-015，读本账）。

## 做了什么

新建 `app/backend/app/lineage/ledger.py`（`__init__.py` 扩展导出，不改 `ids.py`）：

- **双存储（S4 / RULES §1，升级了设计 03/05 的「纯 JSONL」）**：
  - `ledger.jsonl` = append-only + sha256 哈希链 = 防篡改、可重建的【持久真相】。
  - `ledger.sqlite`（WAL）= 从 JSONL 同步的【快查询索引】，honest_n / get 走 O(log n)。
  - `ledger.hwm` = 独立高水位见证（防 JSONL 末尾截断）。
  - JSONL 先落、SQLite 后同步；崩溃/丢库 init 时前向恢复（replay JSONL → SQLite）自愈。
- **计数键 = 复合键 `(config_hash, strategy_goal_ref)`**（对抗复核纠正）：`config_hash` 主题无关
  （ids.py 单一源），但 honest_n 按主题累计——同一想法跨主题各计一次，不互相吞没。
- **`LedgerEntry`**（00 C10 schema + §1.2-I 字段名收敛）：`LedgerEntry.create(...)` 经
  **ids.config_hash 唯一算法**算主键，伪造主键 raise → 堵死 §1.2-A 双产方回潮。
- **`Ledger`**：`record_or_hit` / `memoize`（命中即返不重跑、并发对同键 compute 至多一次）/
  `honest_n`（distinct 实时计数，**无 set_n/delete API**）/ `tombstone`（软删不减 N、行数只增）/
  `update_fields`（回填 returns_corr_cluster_id 供 T-015）/ `verify_integrity`（链 + 列对账 + 截断检测）。
- **读路径 == 被核验路径**：删除冗余 payload_json，get/list 从被 verify 核验的列重建条目。

## 验收（对抗测试 · 25 全绿 + 13 变异全杀 + 二轮复核无缺陷）

`app/backend/tests/test_lineage_ledger.py`（每条「种坏→门必抓」）：
- T-LED-1..14：memoize 不重跑/不双计、honest-N 无改小 API、tombstone 不减 N、config_hash 单一源、
  装饰字段不刷 N、等价写法各计 N、跨 session 持久、崩溃容错、哈希链防篡改、SQLite↔JSONL 对账、
  丢库重建、免责措辞、get 语义、幂等。
- T-LED-15..25（对抗复核 wf_ada4a4e4 的 11 发现各配回归）：跨主题同 config 不吞没、UPSERT 不改主题/
  内容、并发 memoize compute 至多一次、占位后回填 result_ref、软删不返陈旧、读路径列篡改被检出、
  截断经 hwm 检出、坏 payload 行不炸账本、SQLite 行删集合背离被检出、tombstone 列写入对账、update_fields。

`cd app/backend && python -m pytest tests/test_lineage_ledger.py -v` → **25 passed**。
全量回归 **796 passed / 13 skipped**（基线未破）。
变异测试（种 13 个已知 bug 各跑对应测试）→ **13/13 mutation killed**。

## 对抗复核（ultracode workflow + 二轮）

1. 自跑变异测试 6/6 杀 → 5-lens 对抗复核 workflow（honest-N/memoize/防篡改/契约复用/测试剧场）
   确认 **11 个真发现**（2 个 HIGH：跨主题 config_hash 撞行洗白 + UPSERT 改主题减 N；及并发重算、
   占位不算、软删陈旧、截断、payload 读路径、坏行炸库、集合背离、列覆盖、update_fields 未测）。
2. 11 项全修 + 各配回归 + 变异验证（新增 7 变异全杀）。
3. 二轮 second-look 复核：死锁/honest-N 操纵/复活洗白/hwm/列绑定/verify 正确性 **均无缺陷**；
   仅 2 个 LOW（已硬化 T-LED-17 的并发断言；compute 返回非 str 不回填属已知良性属性）。

## 踩坑（开发中被自家测试/复核抓住的真 bug）

1. `verify_integrity` 初版只比冗余 blob，漏检 honest_n 实际查的列篡改（T-LED-10 当场红）→ 改比可查询列。
2. 复核揪出最严重设计错：只用 config_hash 当主键，第二个主题的同 config 试验被静默吞掉（honest-N 洗白）
   → 改复合键 `(config_hash, strategy_goal_ref)`。
3. `list_entries` 按 seq 排序被 tombstone 扰动 → 加 `created_seq` 稳定创建序。

## 下一步

T-014 确定性内核（node 身份/durable/effectful 边界）+ T-015 试验账本算法层（N_eff 聚类 +
多证据三角 gate，读本账）。
