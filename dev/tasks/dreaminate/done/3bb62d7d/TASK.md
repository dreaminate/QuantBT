---
uuid: 3bb62d7dc49f4791a886edac6422eaf5
title: 无副作用业务工具接真引擎（agent 一句话真跑回测）——T-027 残余
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: agent
source: interaction
source_ref: 2026-06-20 T-035 拆分 + T-027 残余（北极星最后一公里）
depends_on: [edc1e32623674b1f870b264119db2421]
---

# 无副作用业务工具接真引擎（agent 一句话真跑回测）

## Scope [必填]
把无副作用业务工具接真引擎、让 agent 真能跑：`backtest.run`（接 codegen/sandbox/runner）、`eval.pbo`、`report.generate` 真 handler，按 T-027 框架注册 side_effect=none（auto/bypass 自主）；testnet 类标 external（轻确认）。这是 T-027 残余 + agent 窗口「能用」前提。动钱/晋级永不注册（治理门在端点层）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/main.py | 283-292 _agent_runtime register_tool | 注册 backtest.run/eval.pbo/report.generate(side_effect=none) |
| app/backend/app/ide/sandbox.py + codegen + runner | — | backtest.run handler 接真回测 |
| app/backend/app/eval/ | pbo/dsr | eval.pbo handler |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. agent auto 模式一句话 → backtest.run 真跑出结果（非 stub）；种"backtest.run 仍 stub/未接" → 抓。
2. 治理正交：动钱/晋级工具仍不注册；种"动钱工具混入 register" → 必抓（致命，§5）。
3. 生成代码受脊柱约束：shift(1) 防前视、缺列报错、过拟合三角门仍生效。

## 验收一句话 [必填]
agent 一句话真跑无副作用回测/IC/PBO；动钱工具永不注册；不破基线。

## 实装说明（epic cfb0fea9 A4 覆盖）
- 无副作用业务工具接真引擎由 A4（business_tools.py：5 业务工具 + backtest.run/eval.pbo/report.generate 接真，全 side_effect=none）实现 + workbench_stream SSE + candidate_pool handoff（止 paper_desk）。20 对抗测试绿。leader 2026-06-21 self-review 置 1 + 落档。
