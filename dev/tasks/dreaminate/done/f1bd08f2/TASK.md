---
uuid: f1bd08f2c6bf4e42908e1ef1a757b352
title: CPCV q05→gate 最后一公里——promote_ide_run 真实路径读 emit cpcv 透传 gate（死接线修复）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: eval-methodology
source: audit-finding
source_ref: 方法学消费侧 correctness 审计（workflow wm8x329vn）#8 发现（高假绿灯）；done 卡 89e7be1e（cpcv→gate 接入）的生产 promote 残口
depends_on: [89e7be1e67e14fa4a8f6c4a859769115]
---

# CPCV q05→gate 最后一公里——promote 真实路径透传 cpcv

## Scope [必填]
done 卡 89e7be1e 让 `run_overfit_gate` + `gate_runner.evaluate_overfit_gate` 接受 cpcv_distribution/cpcv_policy，
但**生产 promote 真实路径** `promote.py:_run_overfit_gate` 调 `evaluate_overfit_gate` 时**从不传 cpcv** →
gate 在 promote 永远以 `cpcv=None` 跑：我上一个切片建的 cpcv_conservative 策略在真实晋级路径**永远触发不了**
（审计 #8 标「高假绿灯」：split-fragile 策略经 promote 时 CPCV 脆弱度检测形同虚设）。本卡补这条死接线。

## 治理（护栏·correctness / 不替用户拍板）[必填]
- **additive·向后兼容**：emit 带 `cpcv_distribution`（顶层或 metadata 内·dict 且 status=ok）才透传；缺 → None
  （**不编造·未算≠已算**），行为与接线前逐位一致。
- **不替方法学拍板**：`cpcv_policy` 从 emit metadata 读，默认 `report_only`（只附报告绝不改裁决）；用户显式
  `cpcv_conservative` 才允许脆弱分布 green→yellow advisory；**非法值回落 report_only**（绝不因脏输入误降级）。
- **correctness 不松**：沿用 89e7be1e 的 gate 侧不变量（q05 弱证据·绝不硬 red/不升级·CPCV 路径≠cscv_pbo）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/ide/promote.py | `_run_overfit_gate` 读 result/meta 的 cpcv_distribution + cpcv_policy，透传 evaluate_overfit_gate | additive |
| app/backend/tests/test_gate_wiring.py | +3 测试（T-GW-7 promote 层透传） | additive |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. emit 带 cpcv（fragile）+ meta cpcv_policy=cpcv_conservative → promote 的 run.json gate_verdict.cpcv 非空、fragile=True、policy=cpcv_conservative（证 emit→gate 真透传 + policy 真读）。
2. emit 不带 cpcv → gate_verdict.cpcv=None（不编造）。
3. emit 给非法 cpcv_policy → 回落 report_only、绝不降级（脏输入不误判）。
- **MUT**（promote 丢 cpcv 透传）→ 测试 1+3 红（gate_verdict.cpcv 恒 None）、测试 2 仍绿 ✓

## 验收一句话 [必填]
promote_ide_run 真实晋级路径真把 emit 的 cpcv_distribution + cpcv_policy 透传给 gate（此前恒 cpcv=None 的死接线已修复），
缺则 None 不编造、非法 policy 回落 report_only、守不替方法学拍板；MUT 抓；全量后端 1626 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-CPCV-PROMOTE）
- **审计驱动**：correctness 审计 workflow（wm8x329vn）#8——cpcv→gate 库+wrapper 全就绪有牙，但生产 promote
  调 evaluate_overfit_gate 时 cpcv=None，最后一公里断线。读 promote.py:140 原文复核坐实。
- **实现（additive）**：`_run_overfit_gate` 读 `result.get("cpcv_distribution")`（退 meta 内·须 dict）+ `meta.cpcv_policy`
  （默认 report_only·非法回落）→ 透传 `evaluate_overfit_gate`。verdict.to_dict() 经 asdict 含 cpcv → run.json gate_verdict 携带。
- **对抗 + 变异**：test_gate_wiring +3（T-GW-7）。MUT（promote 丢 cpcv 透传）→ 透传/非法回落两测试红、缺-则-None 测试仍绿（精准）；定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：test_gate_wiring 11 passed（+3）；**全量后端 1626 passed / 13 skipped / 0 failed / 149s**（基线 1623，净 +3）。
- **CPCV 全链端到端完整**：库→消费(regression+二分类)→train_model opt-in→result.json→eval 端点→UI 卡→gate(run/gate_runner)→**promote 真实路径**。剩 861182e6 ③（cv_scheme UI 选项+双轨 report+Sharpe/DSR 转换=用户方法学）池卡留。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户·分支续 land-ready）。
