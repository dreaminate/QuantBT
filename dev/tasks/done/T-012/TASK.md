# T-012 · `lineage/ids.py` 单一身份源

- **状态**：✅ done（2026-06-16）
- **review_status**：0（未经用户确认）
- **来源**：spine-designs 01/03 + S1（单一身份源裁决）
- **优先级**：P0

## 做了什么

建 `app/backend/app/lineage/ids.py` 作为**唯一身份源**（消灭 config_hash 双产方，复核 §1.2-A 抓出的反面）：
- `canonical_json(obj)`：sort_keys + NFC 归一 + 紧凑分隔符
- `content_hash(obj)` = sha256(canonical_json)[:16]
- `node_id(*, structure, inputs, upstream)`：content-addressed，upstream 排序后纳入
- `config_hash(*, factor, params, universe, dataset_version, freq, label)` = `cfg_v1_` + sha256[:16]，剔除装饰性键（name/desc/tags/note/comment）
- `normalize_factor_ast()`：表达式走 AST 归一（语法同义折叠），非表达式诚实降级
- `fixture_key()/strip_fixture_prefix()`

## 验收（对抗测试 · 8 全绿）

`app/backend/tests/test_lineage_node_id.py`：
- T-NID-1 装饰键剔除、dataset_version 变 → hash 变
- T-NID-2 键序 + NFC/NFD 不变量
- T-NID-3 16-bit 块独立性
- T-NID-4 `cfg_v1_` 前缀
- **T-NID-5 诚实边界**：语法同义 `a*2≡(a*2)` 折叠，语义 `a*2≠a+a` 不折叠
- T-NID-6 非表达式降级
- T-NID-7 fixture_key ↔ node_id 往返
- T-NID-8 node_id upstream content-addressed

`cd app/backend && python -m pytest tests/test_lineage_node_id.py -v` → **8 passed**。

## 踩坑

模块名碰撞：`node_id.py` 导出同名函数 `node_id`，`from app.lineage import node_id` 导入到函数而非模块 → 8 测试失败。修复：`mv node_id.py ids.py`，`__init__.py` 改 `from .ids import`、测试改 `from app.lineage import ids as nid`。

## 下一步

T-013 一本账（SQLite WAL + JSONL，honest-N + memoize）——复用本文件的 `config_hash` 做主键。
