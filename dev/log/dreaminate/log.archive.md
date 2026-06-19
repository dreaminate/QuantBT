# LOG 归档 · 旧 session 条目（read-on-demand）

> 从 `LOG.md` 滚下来的旧条目，最新在上。**查历史别手翻——跑 `python dev/scripts/build_log_index.py` 看活跃+归档统一索引**（索引仅定位、必读原文）。

## 2026-06-17 · 审计 dev/ + 修复边界与 harness 卫生

- **审计**：迁移字节级完整（34/34 git-删除文件全等落点）；无 runtime 读取指向被移走文件（功能安全）；dev→docs 方向分得干净。
- **发现并修复**：
  1. v2/v3 plans 是被项目代码引用的**项目设计文档**，被误卷进 `dev/research/archive/plans/` → 归位 `docs/plans/`（3 处 field_catalog 注释引用零改动重新生效）；`agent-os-technical-architecture`（超期研究、不同来源）留 dev。
  2. 旧 codex 任务残留 `TASK-0001/` + `index.md` → 移 `tasks/_archive/`。
  3. 补 `done/T-012/`（BOARD 标 done 却缺落档）。
  4. 建本 `LOG.md`（README 描述过但从未创建）。
  5. 写 `dev/scripts/validate_dev.py` —— harness 从「纯手工纪律」升级为**可自检**（BOARD↔done 一致 / 四台文件齐全 / 无迁移前悬空路径）。
- **下一步**：T-013 一本账（SQLite WAL + JSONL，honest-N + memoize）。

## 2026-06-16 · 建脊柱第 0 层地基 + 蒸馏 GOAL

- T-012 `lineage/ids.py` 单一身份源 ✅（8 对抗测试绿）。
- T-001 蒸馏 `dev/GOAL.md` 完整最终形态 ✅（两层相乘：功能平台 × 治理）。
- 重构 docs/ → dev/ 四台开发 OS（只搬开发那一套；glossary/model_cards 留 docs/ 因 app 运行时读）。
- **下一步**：T-013 一本账。
