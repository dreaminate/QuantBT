# QuantBT 开发 OS（dev/）

这里是「**怎么建**」——四台 + Goal Loop。产品本身的手册/运行数据在 `../docs/`（glossary、model_cards 是 app 运行时读的，留在 docs/）。

## 四台

| 台 | 文件/目录 | 职责 |
|---|---|---|
| 目标台 | `GOAL.md` | 项目**完整最终形态**（终态，非任何过渡阶段）。慢变契约，所有 gap 对照它。 |
| — | `DECISIONS.md` | 决策账本 R1–R29 / S1–S4（**append-only**，`confirmed_by` 锁定后不改既往）。 |
| — | `STATE.md` | **诚实 gap 陈述器**输出：现状 vs GOAL（每 loop 重生；🟡未验证 ≠ ✅）。 |
| — | `RULES.md` | 开发铁律：复用+性能 / 对抗测试标准 / 不破坏测试 / 致命错误即停工。 |
| 任务台 | `tasks/` | `BOARD.md`(活跃板) + `active/<id>/` + `done/<id>/` + `_templates/`。 |
| 研究台 | `research/` | `INDEX.md` + `findings/` + `archive/`(36 dossier / 蓝图 / plans / survey)。研究归研究。 |
| 执行台 | `exec/` | `LOG.md`(滚动日志) + `HANDOFF.md`(新 session 入口) + `archive/`。 |

## Goal Loop（开发循环）

```
诚实查现状(STATE gap) → gap变任务(BOARD) → 执行(active/<id> 建+对抗测试 pytest绿)
   → 完成落档(active→done, BOARD刷新) → 重跑 gap陈述器(STATE) → 再循环
```

dogfood：开发 OS 用产品同款治理纪律（诚实 gap 不假绿灯、决策账本不改既往、对抗测试「种已知bug门必抓」）。

**自检**：`python dev/scripts/validate_dev.py` —— harness 不靠手工纪律，能自检（四台文件齐全 / BOARD✅done ↔ `done/<id>/` 一一对应 / 活跃文档无迁移前悬空路径 / 脊柱地基在）。挂 CI 或 pre-commit 即防漂移。

## 新 session 怎么开始

读 `GOAL.md`(终态) + `STATE.md`(现状) + `tasks/BOARD.md`(下一步)，拿 `exec/HANDOFF.md` 当入口提示词。重资料（dossier/蓝图）在 `research/archive/`，**read-on-demand，不默认加载**——这就是「瘦身」：活跃面只 4 个小文件。
