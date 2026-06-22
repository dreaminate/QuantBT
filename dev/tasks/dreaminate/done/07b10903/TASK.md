---
uuid: 07b10903e8184d1d8ccbc5b7b6970c13
title: DS-6 装机收口——跨平台一键启动 + mkdir（可缓·docker compose 兜底）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: onboarding-docs
source: developer-claude
source_ref: 2026-06-22 D-DELIVERY-SLICE · audit blocker #9/#10
depends_on: []
---

# DS-6 装机收口

## Scope [必填]
陌生人「能装」收口（可缓，docker compose 已是兜底）：① 跨平台一键启动——`npm run dev` 现链 PowerShell-only `start-qb.ps1`（Mac/Linux 失败），加 `start.sh` / Makefile / npm concurrently（无 PowerShell 依赖）或首推 `docker compose up -d` 作唯一一键入口，README 与 installer-guide 统一（现自相矛盾）；② `cp deploy/secrets.yaml.example ~/.quantbt/secrets.yaml` 前加 `mkdir -p ~/.quantbt`（全新机 cp 失败）或启动时自动 mkdir。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/package.json | 6 npm run dev → ps1 | 跨平台 launcher |
| README + installer-guide | 自相矛盾 + 无 mkdir | 统一指向一键入口 + 加 mkdir |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Mac/Linux 跑文档首选命令不报 PowerShell 错（手验或 CI lint 脚本存在性）。
2. 全新机（无 ~/.quantbt）按文档走 cp 不失败。

## 验收一句话 [必填]
陌生人在 Mac/Linux 按文档一条命令起得来；cp 不因缺目录失败；不破基线。

## 完成记录（2026-06-23 · PR #1 merged→delivery-slice · 实跑为准）
跨平台一键启动：新 start.sh(POSIX) + start-qb.js(Node dispatcher 按平台选 sh/ps1)，保留 Windows；mkdir -p ~/.quantbt 兜底（README/installer-guide + start.sh）；A股 token-gated 诚实引导（crypto 自带样本即开即用、A股需自配 TUSHARE_TOKEN）；文档统一指向 npm run dev。code-review 抓 2 bug 全修，bash -n/node --check/docker compose config/npm build 全过。
整合后全量后端 **1292 passed / 13 skipped**、前端 **267 测 + tsc/build 绿**、validate_dev PASS。
