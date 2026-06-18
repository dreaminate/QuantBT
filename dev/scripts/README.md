# dev/scripts · 校验 + 账本脚本

> 命名正名：`validate_dev` 只管 **dev OS 结构**，项目专属检查拆到 `validate_project`——和 `RULES.md` / `RULES.project.md` 同一套「**【开发os级别】 vs 【项目级别】**」分界。

| 文件 | 归属 | 干啥 |
|---|---|---|
| `validate_dev.py` | **【开发os级别】勿改** | dev/ 结构校验：四台齐全 / 目录 / BOARD↔done 一致 / 活跃任务孤儿。跑它会**自动连带跑 `validate_project.py`**。 |
| `validate_project.py` | **【项目级别】填** | 本项目专属：`PROJECT_ANCHORS`（关键文件存在性）+ `STALE_PREFIXES`（活跃文档不该有的旧路径）+ 任意自定义检查。 |
| `build_ledger.py` | 【开发os级别】勿改 | tasks 全含量账本（扫 `active/`+`done/` 现生成，BOARD 是活跃版）。 |

## 跑
```bash
python dev/scripts/validate_dev.py   # 一条命令：OS 结构 + 项目检查一起跑
python dev/scripts/build_ledger.py   # 全含量任务表
```

## 适配新项目
**只改 `validate_project.py`**（填 `PROJECT_ANCHORS` / `STALE_PREFIXES`）；**别动 `validate_dev.py`**（改了就不是这套 OS 的自检）。
