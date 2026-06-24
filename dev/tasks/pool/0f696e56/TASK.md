---
uuid: 0f696e563b314ecc958158f68f522618
title: 平方根冲击 ADV/σ 滚动无泄露自估（消除回测前视泄露）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P2
area: execution-cost
source: goal-gap
source_ref: 卡 7179ba36（sqrt-impact）多透镜评审 HIGH 前视残余；RULES.project §17 look-ahead 红线
depends_on: [7179ba36278e4091a8e29b4d58336525]
---

# 平方根冲击 ADV/σ 滚动无泄露自估

## Scope [必填]
卡 7179ba36 的 sqrt-impact 自估 ADV/σ 用**全样本**（含未来 bar）→ 启用 impact 的回测有**前视泄露**（成本偏乐观）。
当前处置：default-off + 响亮 warning + 显式无泄露入口（用户自负）。本卡补**根治**：自估改**滚动/扩张无泄露**——
对每笔成交按其 ts 只用 ≤ts-1（或 ≤ 当前 bar）的数据估 ADV/σ（trailing-N 或 expanding + shift(1)），
消除前视、让 impact 自估也能安全启用。

## 上下文 / 动机 [按需]
评审实测：低量→高量 regime 切换下，早期成交参与率被未来高量稀释 50x → 冲击低估 ~7x。RULES.project §17 列
look-ahead 为致命错误级；当前靠 default-off + 诚实标注 + 用户自负规避，但自估便利路径要真正可信须无泄露。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/execution/backtest_venue.py | _precompute_impact_stats / _cost_for_trade | 自估改滚动/扩张无泄露（每笔成交按 ts 用 ≤ts-1 数据）；warmup 不足时诚实处置 |
| app/execution/impact.py | 复用公式 | 不改 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种低量→高量 regime：早期成交冲击成本用**仅历史可见**口径，断言不被未来高量稀释（与全样本口径明显不同）。
2. warmup 不足（首笔无历史）→ 诚实处置（raise/skip-with-warning，绝不用未来数据）。
3. 无泄露后：自估路径不再 emit 前视 warning（残余消除）。

## 验收一句话 [必填]
sqrt-impact 自估 ADV/σ 改滚动/扩张无泄露（每笔成交只用历史可见数据），消除回测前视泄露，自估路径安全可启用，不破基线。
