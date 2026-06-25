---
uuid: fe46991c
title: W2 · B-PIT-1 训练管线消费 PIT 点查，堵 look-ahead
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: training-backend
source: developer-claude
source_ref: 2026-06-26 W2 数据层 R28 双时态 PIT · 训练管线死接线修复
depends_on: []
---

# W2 · B-PIT-1 训练管线消费 PIT 点查

## Scope [必填]
`codegen.spec_to_code` 生成的训练脚本（ML/DL 两路）此前裸 `panel = pd.read_parquet(os.environ["QUANTBT_PANEL_PATH"])` 全量读盘，不经任何 known_at as-of 边界——panel 若带未来重述（known_at 晚于训练知识时点）直接泄露进训练（前视）。`field_catalog.load_panel(as_of_known=...)`（R28 双时态点查）已实现但训练管线零消费=死接线。本卡把 `as_of_known` 沿 **codegen → 生成脚本 → load_pit_panel** 串通：spec 带 `as_of_known` 时 header 改走新 `load_pit_panel`（按 `known_at<=as_of_known` 折叠点查、取最新已知重述），与 field_catalog 单一源折叠语义逐条对齐。向后兼容硬保：无 as_of_known / known_at 列缺失 → 逐字回退 `_HEADER`（既有训练一字不改）。

## 接线点（file:line，实现复核为准）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/training/codegen.py | 新增 `load_pit_panel` + `_panel_load_header` + `_as_of_known_literal`；`_ml_code`/`_dl_code` 的 `_HEADER` → `_panel_load_header(spec)` | as_of_known 透传 + PIT 点查入口 |
| app/backend/app/universe/resolver.py | `as_of_bound`（公共别名） | **只读复用**单一 as-of 边界原语，绝不改 |
| app/backend/app/field_catalog/catalog.py | `_materialize_sub` 折叠语义 | **只读镜像**（不 import 私有符号、不改） |
| app/backend/tests/test_training_pit_wiring.py | 新建 11 测 | 对抗/向后兼容/等价/e2e |

## 对抗测试设计（种已知坏门，门必抓）[必填]
1. **泄露守卫**：构造含「未来重述 roe=10.5(known 2024-04-15)」+「纯未来行 roe=99.0(known 2024-09-01)」的双时态 panel，`load_pit_panel(as_of_known='2024-02-01')` 必只见首披 10.0。MUT-1（`load_pit_panel` 退回裸 read_parquet/忽略 as_of_known）→ 99.0/10.5 泄露 → 5 测红（含 e2e 子进程 3.0≠1.0）；还原→全绿。
2. **codegen 接线 load-bearing**：MUT-2（`_panel_load_header` 永远返回 `_HEADER`，不透传 as_of_known）→ 生成脚本回退裸读 → 4 测红（3 字符串断言 + e2e 子进程）；还原→全绿。
3. **复用单一源·等价证明**：同一份双时态数据，`field_catalog.load_panel(as_of_known=X).panel` 与 `load_pit_panel(parquet, as_of_known=X)` 解析值逐条一致（X∈{2024-02-01, 2024-05-01}）。
4. **e2e 真子进程**：生成 PIT header 经真 `run_code` 跑（`from app.training.codegen import load_pit_panel` 真 import），as_of_known 在场只见 1 行、去掉则全 3 行——证明 codegen→脚本→loader 全链通。

## 验收一句话 [必填]
训练生成脚本按 as_of_known 走 R28 双时态点查、未来 known_at 行必被挡在训练之外；复用 field_catalog 单一 as-of 源（as_of_bound + 折叠语义等价）不另造；无 as_of_known/列缺失逐字向后兼容、不破基线。

## 完成记录（2026-06-26 · 实跑为准）
**改了什么**（只动领地 codegen.py，扩展不替换、零改 LINE-B 单一源）：
- `app/backend/app/training/codegen.py`（扩展）：
  - 新 `load_pit_panel(panel_path, *, as_of_known=None, ts_col, symbol_col, known_at_col)`：训练管线 PIT 点查入口。`as_of_known=None` → 逐字 `pd.read_parquet`（向后兼容）；无 known_at 列 → 原样返回（mirror `_materialize_sub` 同分支，不假装过滤、不报错）；有 known_at + as_of_known → 复用 `universe.resolver.as_of_bound`（单一边界原语）过滤 `known_at<=as_of_known`，再同 `(ts,symbol)`（缺 symbol 退化为 ts-only 键）取最新已知重述、drop known_at。
  - 新 `_panel_load_header(spec)`：无 as_of_known/None → **逐字返回 `_HEADER`**（一字不动）；有 → 渲染走 `load_pit_panel` 的 header。`_ml_code`/`_dl_code` 由 `_HEADER` 改 `_panel_load_header(spec)`。
  - 新 `_as_of_known_literal(value)`：date/datetime→ISO 字符串，其余→`repr(str(...))`（注入安全）；非法值留运行时 `as_of_bound` fail-loud 校验（不静默跳守卫）。
  - `load_pit_panel` 入 `__all__`；`_HEADER` 字面量未动。
- `app/backend/tests/test_training_pit_wiring.py`（新·11 测）：codegen 透传/无旁路、向后兼容逐字、列缺失 noop、泄露守卫（含无 symbol）、最新重述、单一源等价、e2e 子进程。

**验证（实跑·2026-06-26）**：
- 新 PIT 套件 **11 passed in 5.38s**（`test_training_pit_wiring.py`）。
- 变异实证（精准 in-place edit→跑→还原，绝不 git checkout）：MUT-1 守卫旁路→5 红（leak/equivalence/e2e）；MUT-2 codegen 不透传→4 红（字符串+e2e）；两次还原后均回全绿，两处 seed 标记已清。
- 回归（codegen 触及的 scoped 套件）：`test_training_pit_wiring + test_training_runner + test_model_cards + test_model_desk_m2 + test_data_contract + test_universe + test_known_at_writelayer` **90 passed in 34.78s**（基线先验 36 passed，0 破坏；4 warning 是 pre-existing FastAPI on_event 弃用、与本卡无关）。
- 未跑全量套件（按编排：中心负责全量 + land）。

**红线合规**：look-ahead 守卫 load-bearing（MUT 证）；复用 field_catalog 单一 PIT 源（as_of_bound 公共别名 read-only）不另造边界/dtype 逻辑；只动 codegen.py（catalog/resolver 零改、零 import 私有符号）；扩展不替换、`_HEADER` 逐字保留、向后兼容默认不变；非法 as_of_known fail-loud 不静默回落裸读。无新数学公式（重点 correctness）。

**诚实残余/限界**（非半成品·明确边界）：
1. **service 层激活是领地外 follow-up**：本卡让 codegen 在 spec 带 `as_of_known` 时正确点查并 e2e 证通。但 `TrainingService.train_now/submit` 经 `TrainingRequest.to_dict()` 喂 spec，而 `TrainingRequest`（service.py）无 `as_of_known` 字段——加该 additive 字段=service.py 领地（本卡领地仅 codegen.py，未碰）。**当前激活路径**：`POST /codegen` 端点（main.py:1332 直传 payload）已可带 `as_of_known` 激活；`train_now/submit` 全链激活待 service 层 owner 加一个 additive 字段透传。
2. **ML 进程内训练路（`_train_ml`）不经 codegen**：service 对 ML family 走进程内 `train_model`（service.py:306-309），不渲染脚本，故不经本 PIT header；该路 PIT 应由调用方在建 panel 时经 `load_panel(as_of_known=...)` 解决（领地外）。本卡覆盖的是 codegen 生成脚本路（DL family + `/codegen` 端点 + spec_to_code 全部 ML 卡）。
3. **None 路与 catalog None 语义有意不同**：训练 None=逐字 `pd.read_parquet`（向后兼容，不折叠）；catalog None=本层 keep=last 折叠。两层契约不同、不纳入等价断言（已在测试与 docstring 写明）。
