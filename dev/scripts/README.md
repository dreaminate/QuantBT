# dev/scripts · 自检 + 生成脚本（团队并发）

> 命名正名：`validate_dev` 只管 **dev OS 结构**，项目专属检查拆到 `validate_project`——同一套「**【开发os级别】 vs 【项目级别】**」分界。
> **派生视图一律不入库**（`dev/.gitignore` 已挡）：现用现生成,没有「新鲜度」要守、多分支 land 零冲突。

| 文件 | 归属 | 干啥 |
|---|---|---|
| `os.py` | **【开发os级别】勿改** | 卡生命周期 CLI：`mint`(自动 uuid/模板/依赖前缀解析) · `assign`(目录+owner 原子同改) · `done`(status/done_at/落档) · `archive`(done 卡按季归档) · `refresh`(重建全部派生视图) · `log`(契约格式落日志+按月滚动) · `validate`。多步手工易错点全收进这里。 |
| `_oslib.py` | **【开发os级别】勿改** | 共用库(单一源)：frontmatter 解析 / TEAM 读取 / 卡遍历(含归档) / OQ 标签统计。 |
| `validate_dev.py` | **【开发os级别】勿改** | dev/ 结构 + 团队并发校验：身份∈TEAM / leader 唯一 / 卡 owner==所在文件夹 / 文件名==uuid8 / 依赖无悬空 + DAG 无环(归档卡在册) / state 不假绿灯 + 无续接堆叠 / area slug 合法 / 研究台归属合法 / 派生视图未被 track / OQ 标签规范 + 执行闸。跑它**自动连带跑 `validate_project.py`**。 |
| `validate_project.py` | **【项目级别】填** | 本项目专属：`PROJECT_ANCHORS`（关键文件存在性）+ `STALE_PREFIXES`（活跃文档不该有的旧路径）+ 任意自定义检查。 |
| `build_board.py` | 【开发os级别】勿改 | 从 `tasks/{本机}/` 生成本人 `board/{id}/board.md`（active 卡 + 「已决 D/总」从标签现算）。 |
| `build_dev_map.py` | 【开发os级别】勿改 | 遍历全员卡 → `DEVMAP.md`（**活跃面**:active+pool,done 只计数）+ 各 folder `_NAV.md`。**导航 only，实时看原文+代码**。 |
| `build_ledger.py` | 【开发os级别】勿改 | 扫 pool + 每人 active/done(**含季度归档**) → 全含量任务账本（历史面）。 |
| `build_trace.py` | 【开发os级别】勿改 | 从卡 `goal_section` 聚合 → `research/TRACE.coverage.md`（GOAL 节×卡覆盖,TRACE 手填层只装慢变溯源）。 |
| `build_log_index.py` | 【开发os级别】勿改 | 遍历全员 `log/*/log.md` + `log/*/archive/*.md` → 统一时间线索引（支撑「强制查 LOG」）。 |

## 跑
```bash
python dev/scripts/os.py refresh        # 重建全部派生视图(DEVMAP/_NAV/board/TRACE.coverage)
python dev/scripts/os.py mint "<标题>" --area <slug>   # 造卡(其余命令 os.py -h)
python dev/scripts/validate_dev.py      # OS 结构 + 团队 + 项目检查一起跑(= os.py validate)
python dev/scripts/build_ledger.py      # 全含量任务表(历史面,含归档)
python dev/scripts/build_log_index.py   # 全员日志统一索引(含归档)
```

## 适配新项目
**只改 `validate_project.py`**（填 `PROJECT_ANCHORS` / `STALE_PREFIXES`）；**别动 `validate_dev.py` / `os.py` / `_oslib.py` 与 `build_*` 脚本**（改了就不是这套 OS 的自检）。
