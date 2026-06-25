---
uuid: 6a8752abcc324ec18cbfa910e1e78376
title: PIT 训练全链激活——TrainingService train_now/submit 透传 as_of_known（B-PIT-1 activate）
status: todo
owner: wait
assigned_by: dreaminate
review_status: 0
priority: P2
area: data-pit
source: goal
source_ref: GOAL §11 + e01bf12f 完成记录诚实残余（codegen 路 ✅·service 层全链 🟡）
depends_on: [e01bf12fcac34eadb1bd048e218cbe45]
---

# PIT 训练全链激活（B-PIT-1 activate）

## Scope [必填]
e01bf12f 已通 codegen→生成脚本→load_pit_panel 全链（11 对抗测试·POST /codegen 可激活·🟡 service 全链未通）。本卡接 service 层：`TrainingRequest` 加 additive `as_of_known` 字段 + `to_dict()` 透传到 spec，使 `train_now/submit` 全链 PIT；`_train_ml` 进程内路（不渲染脚本）由调用方建 panel 时经 `load_panel(as_of_known=...)` 解决。**additive·向后兼容默认 None=现状不变**。

## 接线点（实现复核）[必填]
- `app/backend/app/training/service.py`（TrainingRequest +as_of_known 字段 + to_dict 透传 + _train_ml 路 panel 建法）
- `app/backend/app/main.py:1279`（train 入口透传 as_of_known·若有）

## 对抗验收（种坏门必抓）[必填]
1. train_now 带 as_of_known→训练只见截至该 known_at 行（端到端·种 known_at 晚于时点的未来行必剔；MUT 不透传→泄露→红）。
2. as_of_known=None→逐字现状不变（向后兼容·既有训练测试不破）。
3. _train_ml 进程内路同样无前视（panel 经 PIT 建）。

## 红线 [按需]
look-ahead 泄露即停·复用 field_catalog 单一 PIT 源·扩展不替换·向后兼容默认不变。
