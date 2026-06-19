# dev/scripts · 自检 + 生成脚本（团队并发）

> 命名正名：`validate_dev` 只管 **dev OS 结构**，项目专属检查拆到 `validate_project`——同一套「**【开发os级别】 vs 【项目级别】**」分界。

| 文件 | 归属 | 干啥 |
|---|---|---|
| `validate_dev.py` | **【开发os级别】勿改** | dev/ 结构 + 团队并发校验：身份∈TEAM / leader 唯一 / 卡 owner==所在文件夹 / 文件名==uuid8 / 依赖无悬空 + DAG 无环 / 本机 state+log 在 / state 不假绿灯 / OQ 标签+计数 / 必填节 / tasks 文件夹归属合法。跑它**自动连带跑 `validate_project.py`**。 |
| `validate_project.py` | **【项目级别】填** | 本项目专属：`PROJECT_ANCHORS`（关键文件存在性）+ `STALE_PREFIXES`（活跃文档不该有的旧路径）+ 任意自定义检查。 |
| `build_board.py` | 【开发os级别】勿改 | 从 `tasks/{本机}/` 生成本人 `board/{id}/board.md`（只含本人 active 卡，生成视图）。 |
| `build_dev_map.py` | 【开发os级别】勿改 | 遍历全员卡 → `DEVMAP.md`（按 developer + area）+ 各 folder `_NAV.md`。**导航 only，实时看原文+代码**。 |
| `build_ledger.py` | 【开发os级别】勿改 | 扫 pool + 每人 active/done → 全含量任务账本（含 owner 列）。 |
| `build_card_counters.py` | 【开发os级别】勿改 | 从卡 OQ 标签派生 `已决 D/总` 写回（人别手敲）。 |
| `build_log_index.py` | 【开发os级别】勿改 | 遍历全员 `log/*/log.md` → 统一时间线索引（支撑「强制查 LOG」）。 |

## 跑
```bash
python dev/scripts/validate_dev.py     # OS 结构 + 团队 + 项目检查一起跑
python dev/scripts/build_board.py       # 刷新本人工作板 board/{你}/board.md
python dev/scripts/build_dev_map.py     # 刷新全局导航 DEVMAP.md + 各 _NAV.md
python dev/scripts/build_ledger.py      # 全含量任务表
```

## 适配新项目
**只改 `validate_project.py`**（填 `PROJECT_ANCHORS` / `STALE_PREFIXES`）；**别动 `validate_dev.py` 与 `build_*` 脚本**（改了就不是这套 OS 的自检）。
