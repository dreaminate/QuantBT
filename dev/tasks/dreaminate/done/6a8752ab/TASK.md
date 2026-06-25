---
uuid: 6a8752abcc324ec18cbfa910e1e78376
title: PIT 训练全链激活——TrainingService train_now/submit 透传 as_of_known（B-PIT-1 activate）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: data-pit
source: goal
source_ref: GOAL §11 + e01bf12f 完成记录诚实残余（codegen 路 ✅·service 层全链 🟡）
depends_on: [e01bf12fcac34eadb1bd048e218cbe45]
branch: wave2/w2-pit-service-activate
---

# PIT 训练全链激活（B-PIT-1 activate）

> 规格原文：`dev/tasks/pool/6a8752ab/TASK.md`（卡分配路径写的 `dev/tasks/dreaminate/6a8752ab/TASK.md`
> 实际不存在，规格在 pool）。本记录自含。

## 接的是什么
e01bf12f（第一波 land）已通 codegen→生成脚本→`load_pit_panel` 全链（11 对抗·POST /codegen 可激活），
但其完成记录第 48 行诚实残余：**service 层全链 🟡**——`TrainingRequest` 缺 `as_of_known` 字段、
`_train_ml` 进程内路 PIT 未接。本卡就接这一段，使 `train_now/submit` 全链走 R28 双时态 PIT。

## 改了什么（只动 service.py·扩展不替换·additive）
**领地**：`app/backend/app/training/service.py`（唯一动的生产代码）。
1. `TrainingRequest` 加 **additive** 字段 `as_of_known: str | None = None`（默认 None=现状）。
   `to_dict()` 是 `asdict(self)` → 自动透传到 spec。
2. **DL/脚本路**（`_resolve_result` family==dl → `spec_to_code(request.to_dict())`）：`to_dict` 透传
   `as_of_known` 后，生成脚本自动走 `load_pit_panel`（第一波已建）→ 子进程读盘点查。**零额外改动**，
   仅靠字段 + to_dict 透传激活。
3. **ML 进程内路**（`_train_ml`，不渲染脚本、直接 `train_model`）：新增 `_pit_view()`——`as_of_known`
   给定时把内存 panel 落一份**临时** parquet（用完即清，不在 job_dir 留未过滤快照）→ 走**同一单一源**
   `codegen.load_pit_panel` 折叠点查 → 再 `train_model`。`as_of_known=None` → 逐字返回原 panel（无
   round-trip、byte-identical）。

**复用单一源**：`_pit_view` 不自己写折叠/边界逻辑，整段折叠由 `codegen.load_pit_panel`（内部复用
`resolver.as_of_bound` + 镜像 `catalog._materialize_sub`）完成 → 与 DL 子进程路、与 field_catalog
单一源逐条对齐（不另造平行 PIT 逻辑）。

**未碰**（红线）：`main.py`（中心独占）、`training/codegen.py`（第一波已定·只读）、`universe/resolver.py`、
`field_catalog/catalog.py`（只读复用）、其他在飞线领地、state/log/board/DEVMAP/GOAL/pool。

## 对抗测试（种坏门必抓·新文件扩展不替换）
新增 `app/backend/tests/test_training_pit_service_activate.py`（**12 passed**，6.06s）。
未改任何既有测试。

| 准则 | 测试 | 守的门 |
|---|---|---|
| 1 未来行必挡 | `test_train_now_ml_inprocess_blocks_future_known_at` / `..._submit_...` / `..._latest_known_restatement` | 打桩 `train_model` 直录其**真正看见的 panel**，断言只剩截至 as_of_known 已知行（未来重述 1.5 / 纯未来 9.0 被挡、known_at 折叠后 drop） |
| 2 None 逐字不变 | `..._none_is_verbatim` / `..._explicit_none_is_verbatim` / `..._real_no_as_of_known_unchanged` | 缺省/显式 None → train_model 见全 3 行含未来、known_at 列保留；真 xgboost 既有训练逐字不破 |
| 3 进程内无前视 | `..._missing_known_at_is_noop` / `..._pit_real_chain_succeeds` / `..._pit_real_chain_filters_poison` | 无 known_at 列→原样返回不假装过滤；真链 round-trip+loader+train_model 集成产 model.pkl；未来行带毒(label=NaN)被 PIT 挡→真训练成功 |
| 4 复用单一源 | `..._pit_reuses_single_source` | service 进程内路折叠 == 直接 `load_pit_panel` 单一源点查，逐条一致 |
| DL 接线 | `test_to_dict_threads_as_of_known_into_dl_codegen` / `test_training_request_as_of_known_additive_default_none` | to_dict 透传后 DL 脚本走 `load_pit_panel`（None→裸读）；新字段 additive 默认 None |

**MUT（定点反向 edit→红、还原→绿，绝不 git checkout）**：把 `_pit_view` 的 `if request.as_of_known is None`
改成 `if True`（=不透传 as_of_known、进程内路退回原 panel）→ **5 failed**：
- 4 条打桩泄露门：`assert [1.0, 1.5, 9.0] == [1.0]`（未来行泄露进 train_model 看见的 panel）
- 1 条真链毒门：`XGBoostError`（带毒未来行泄露→NaN label 喂真 xgboost→job failed）

→ 证明探针确实贴泄露面（打桩 + 真训两条独立机制各抓）。Edit 还原 `if request.as_of_known is None` →
全绿。

## 真测试汇总行（实跑·非推断）
- 新文件：`tests/test_training_pit_service_activate.py` → **12 passed in 6.06s**。
- scoped（新 + `test_training_service.py` + `test_training_pit_wiring.py`）→ **34 passed in 16.47s**
  （collect-only 实测基线 22，新增 12，既有 11+11 不破）。
- 训练簇（上述 + `test_training_api.py` + `test_training_runner.py` + `test_dl_trainer_fixes.py`）→
  **60 passed in 29.72s**（4 warnings = main.py 既有 FastAPI on_event Deprecation，与本卡无关）。
- 未跑全量（卡令只跑 scoped）。

## 红线合规（逐条）
- look-ahead 泄露即停：进程内 ML 路 + DL 子进程路双堵，MUT 双机制证泄露被抓。✅
- 复用 field_catalog/codegen 单一 PIT 源不另造：`_pit_view` 整段折叠走 `codegen.load_pit_panel`
  （→ `resolver.as_of_bound` + 镜像 `_materialize_sub`），等价性测试逐条对齐。✅
- 扩展不替换：service.py 纯加（1 import 改 + 1 字段 + 1 方法 + _train_ml 1 行）；新测试文件，未改既有测试。✅
- 向后兼容默认不变：`as_of_known=None` 逐字原 panel、无 round-trip、byte-identical；既有 60 测试全绿。✅
- 不碰 main.py / codegen.py / 其他领地 / dev 状态台。✅
- M6 不变量（主进程不 import torch）：`_pit_view` 只 pandas/parquet，import 探针确认主进程无 torch。✅

## 拍板项命中
无。本卡纯接线，无工程取舍四面分歧、无未覆盖岔路需停下拍板。
（一处自决并记录：ML 进程内路用**临时** parquet round-trip 复用 path-based 单一源 `load_pit_panel`，
而非在 job_dir 持久化 `_pit_panel.parquet`——理由：持久化的是**未过滤**输入快照、于 PIT 任务里误导，
且 ML 进程内路本就不持久化训练面板，临时件零侵入更诚实。若中心要审计留痕，可后续单加一卡持久化
**已过滤** PIT 视图，不在本卡范围。）

## 诚实残余（留中心）
- **main.py 入口透传**：`POST /api/training/jobs`（main.py:1509 构造 `TrainingRequest`）尚未把
  `payload.get("as_of_known")` 喂进 request——卡令 main.py 中心独占，入口透传由中心整合时补一行
  （`as_of_known=payload.get("as_of_known")`）。在此之前，端到端 HTTP 路的 as_of_known 仍是 None；
  service 全链能力已就位且对抗证明无泄露，只差入口那一行。
- `load_training_panel`（datasets.py）当前合成 demo panel **无 known_at 列**——故即便入口透传，demo
  数据集走 `_pit_view` 也是 mirror noop（无知识轴可过滤）。真 known_at 数据集接入是数据层另卡，
  不在本卡。本卡守的是「有 known_at 时必正确折叠、无时不假装」，两面都已测。
