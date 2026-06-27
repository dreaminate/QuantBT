---
uuid: 8d40a946f9734c89bc8f0d7bfafecbcb
title: EffectLedger 并发初始化锁等待——修全量测试卡住
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: dag
source: verification-finding
source_ref: 2026-06-26 full backend pytest hang at test_effect_ledger_concurrent_same_key
depends_on: []
---

# EffectLedger 并发初始化锁等待

## Scope [必填]
全量 pytest 第二轮在 `test_effect_ledger_concurrent_same_key` 卡住：多个线程同时构造 `EffectLedger(tmp_path)`，其中线程在 `PRAGMA journal_mode=WAL` 处遇到 sqlite `database is locked`，异常发生在测试 worker 的 try/except 之前，导致 barrier 等待卡住。修复 `EffectLedger.__init__`，让并发 first-open WAL setup 等锁重试，不改幂等账的 UNIQUE 语义。

## 完成记录
- `app/backend/app/dag/effect_ledger.py`：连接设置 `timeout=30`，先设 `busy_timeout=30000`，对 `PRAGMA journal_mode=WAL` 和建表加入短 retry。
- 验证：`cd app/backend && python -m pytest tests/test_dag_kernel.py::test_effect_ledger_concurrent_same_key -v` → 1 passed；`cd app/backend && python -m pytest tests/test_dag_kernel.py -q` → 25 passed；`cd app/backend && python -m pytest -q` → 1309 passed / 13 skipped。
