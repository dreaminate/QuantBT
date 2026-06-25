---
uuid: 6e264c59f82043fe9934eb913324a6f4
title: 回测成本逐成分诚实归因（impact 单列不混入 commission）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: execution-cost
source: pool-card
source_ref: 池卡 e2afc5c2 验收 #1（eng「fill 报告 impact 并入 commission 字段、下游误读」）
depends_on: [7179ba36278e4091a8e29b4d58336525]
---

# 回测成本逐成分诚实归因

## Scope [必填]
做池卡 **e2afc5c2 #1**（correctness/honesty）。fill 报告原 `commission` 字段实装的是**总成本**
（commission+slippage+stamp+transfer+impact），下游做成本拆解/TCA 会把市场冲击误读成手续费。
**修**：抽 `_cost_breakdown` 返逐成分 + total，impact **单列绝不并入 commission**；fill 报告 **additive**
加 `cost_breakdown`，顶层 `commission` 保留=total 仅向后兼容。`_cost_for_trade` 变薄壳返 total。

## 治理（命门·不假绿灯/向后兼容）[必填]
- impact **单列**、各成分非负、**求和==total**（守恒测试）；绝不把 impact 偷并进 commission 成分。
- 顶层 `commission`=total（含 impact）**向后兼容**：`cost_drift`（取总实现成本）等旧消费者不破。
- `step` **一次算** breakdown（避免重算令 warmup 计数器双增）。warmup（自估 prefix 不足）→ impact 成分=0、求和仍守恒。

## e2afc5c2 #2（三档预设默认 size-aware）= 用户方法学决策（不替拍板）
启用 impact 仍需冲击系数 Y（无万能默认、须用户/校准给），选 Y 是用户那摊；seam 已就绪
（任何预设 caller 可传 `impact_coef` + 无泄露自估[卡 d9bf88b1]/显式 ADV），生产默认保持关直到用户给 Y。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/execution/backtest_venue.py | +`_cost_breakdown`/`_cost_for_trade`(薄壳)/`step`(附 cost_breakdown) | 逐成分归因 additive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 逐成分求和==total + impact 单列 + commission 成分==纯 commission_bps（反证：与「impact 关」逐位相同）。
2. fill 报告 additive 含 cost_breakdown；顶层 commission=total 向后兼容；total>纯 commission 成分；JSON-safe。
3. warmup→impact 成分=0、求和仍守恒（不假绿灯）。
4. **MUT-C（impact 并入 commission 成分）验证有牙**：commission 成分虚高被抓。

## 验收一句话 [必填]
回测 fill 报告逐成分诚实归因（impact 单列不混入 commission、求和守恒、向后兼容 commission=total），
MUT-C 验证有牙；#2 预设默认启用=用户方法学决策（seam 就绪、默认关）；全量后端绿、基线不破。

## 完成记录（2026-06-25 · autonomous-loop / D-COST-ATTRIBUTION）
- **honesty 修**：`_cost_breakdown` 逐成分 + total，impact 单列；fill 报告 additive 加 `cost_breakdown`，顶层 commission=total 向后兼容；`step` 一次算避免 warmup 计数双增。finding「成本逐成分诚实归因」节 + 顺手修 slice-9 误留的「## 复用」重复节。
- **验证**：`test_sqrt_impact_cost.py` 23 passed（+3 归因测试）；**MUT-C（impact 并入 commission）验证有牙**（commission 成分虚高 33.5 被抓）；**全量后端 1574 passed / 13 skipped / 0 failed / 192s**（基线 1571 未破，净 +3）。
- **诚实纠错**：本切片首次全量跑用了 `run_in_background` 且与遗留 pytest 僵尸叠跑 → 触发 test_dag_kernel 并发测试在重负载下挂死、后台无 timeout → 空挂 7h，harness 误报「exit 0」=假绿。已识破假绿、杀僵尸、单独前台带 timeout 重跑得真绿 1574，并加全局 timeout 兜底（commit 443fca9）。
- **land main 待用户授权**（本轮 loop「commit 不擅自 push」→ 本地 commit、未 push）。
