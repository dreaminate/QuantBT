---
uuid: 5745c2c3944f4aa08be5da096c5d3cb4
title: W3 · B-VERSION-1 · 数据写时强约束——缺 dataset_version/checksum 的写入→拒
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: data-layer
source: goal-gap
source_ref: GOAL §11 数据层（dataset version + checksum）+ §17 RDP「缺 DatasetVersion 引用→拒」；不可变门已建（dataset_hash.py）但未接进实际登记写路径
depends_on: []
---

# W3 · B-VERSION-1 · 数据写时强约束（缺 dataset_version/checksum → 拒）

## Scope [必填]
把已建的不可变寻址原语**接进实际登记写路径**：登记/落库前缺 `dataset_version` 必备身份、缺 checksum、
或 checksum 被篡改的写入→直接 raise，绝不静默落账退化版本。**不是重建不可变门**。

## 写路径实证结论（第一步·必做·grep + 实跑坐实）[必填]
- **真实写入单点 = `DatasetRegistry.register()`（`app/backend/app/data_quality.py:180`）**。所有落库写路径都汇到此处：
  - 官方源/爬虫接入 `field_catalog/intake.py:register_official_dataset()` → `make_wide_fetch_result(frame)` → `registry.register(did, fr, file_paths=[parquet], metadata=meta)`（intake.py:51-61）。
  - connector 拉取产 `FetchResult`（`connectors/*` 全部经 `make_fetch_result` / `make_wide_fetch_result`，无一处裸构造 `FetchResult(...)`——repo grep 仅 base.py:175/205 两个工厂内部）。
- **现状 = advisory（非 gate）**：`register()` 原样把 `version_id = make_version_id(fetched_at_utc, sha256)` 算出来就 `_append`，**无任何缺字段/篡改校验**。`FetchResult` 注释明写"便于 data_quality.py 登记 dataset_version"=登记便利，看不到任何拒绝逻辑。
- **不可变门已建但未接活**：`dataset_hash.py` 的 `write_manifest`（同 version 文件 hash 变→raise）/`verify_manifest`（重算核对）只在 `tests/test_academic_audit_v2.py` 被调用，**生产登记路径 register() 从不触达**。
- **结论**：本卡真 gap = 在唯一登记单点 `register()` 强制写时校验（缺 dataset_version 必备身份 / 缺 checksum / checksum 与 frame 重算不匹配→拒）。gate 放 `register()` 即覆盖 intake.py 等全部写路径，**无需碰 field_catalog/（W2 领地）**。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么（扩展不替换） |
|---|---|---|
| app/backend/app/connectors/base.py | +`DatasetWriteIntegrityError`；`FetchResult.validate_for_write()`（FetchResult 写时校验单源）；`__all__` 导出 | additive |
| app/backend/app/data_quality.py | `DatasetRegistry.register()` 顶部调 `fetch_result.validate_for_write(dataset_id=dataset_id)` | additive（登记口只调用、不另造） |
| app/backend/tests/test_dataset_write_gate.py | 新建·11 对抗+正路径测试 | 新增 |

校验和重算**复用既有单源 `_sha256_of_frame`（connectors/base.py）**，绝不另造哈希；未碰 `lineage/ids.py`、未碰 `field_catalog/`、未改/未替 `dataset_hash.py` 不可变门。

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **缺 dataset_version**：blank/空 `dataset_id` → 拒且不落账；空 `fetched_at_utc`（version_id 无法成形）→ 拒。
2. **缺/篡改 checksum**：空 `sha256` / 非 64-hex → 拒；合法 64-hex 但与 frame 内容不符（`"0"*64`）→ 重算 verify 失败→拒；保留旧 sha 换 frame（内容漂移）→ 拒。全部拒后 `list_versions()==[]`（绝不半写）。
3. **正路径不误伤·向后兼容**：`make_wide/_fetch_result` 产出 → 正常落账；**空 frame（空哈希仍有效 64-hex）→ 不误伤**；落账 jsonl 内容 == FetchResult 派生值（门不改写已写字节）。
- **MUT-A（神门接线）**：register() 注释掉 validate 调用 → 7 个登记路径对抗测试全红（DID NOT RAISE）、4 个正路径/直调方法测试仍绿 → 还原（Edit 反向，**绝不 git checkout 带未提交改动**）→ 全绿。证 register() 接线 load-bearing。
- **MUT-B（篡改分支非纸门）**：`validate_for_write` 重算比对分支 `if actual != sha` 改 `and False` 神化 → 仅 `test_tampered_checksum_rejected` + `test_frame_swapped_under_declared_checksum_rejected` 2 测红、其余 9 绿 → 还原 → 全绿。证篡改检测分支 load-bearing、每条对抗测试精准映射一个 gate 分支。

## 验收一句话 [必填]
数据登记唯一单点 `DatasetRegistry.register()` 现强制写时校验：缺 dataset_version 必备身份 / 缺 checksum /
checksum 与 frame 重算不匹配（篡改）→ 拒且不落账；正路径（含空 frame）不误伤、向后兼容（落账字节不变）；
MUT-A/B 双变异证门有牙且分支精准；scoped 全绿（见完成记录），不破基线。

## 完成记录（2026-06-26 · deep-opus 任务线 · 隔离 worktree）
- **gap 性质 = 接线非重建**：不可变门（dataset_hash.py write_manifest/verify_manifest + FactorBinding 三元组）早建好，但仅 test 触达；生产登记口 `register()` 此前 advisory（算 version_id 直接 append、零校验）。本卡把"写时强约束"接到唯一单点。
- **实现（additive·扩展不替换）**：
  - `connectors/base.py`：新增 `DatasetWriteIntegrityError(ValueError)` + `FetchResult.validate_for_write(*, dataset_id=None)`——三类退化写入拒（缺身份 / 缺 checksum / checksum 重算不匹配）。**写时门**（不在 `__post_init__` 拦，FetchResult 仍可自由构造做只读/预览，仅持久化时强约束）。重算复用 `_sha256_of_frame`，零新哈希。
  - `data_quality.py`：`register()` 顶部一行 `fetch_result.validate_for_write(dataset_id=dataset_id)`——单源校验、登记口只调用。覆盖 intake.py 等全部写路径，未碰 field_catalog。
- **确定性前置实证**（门的安全前提）：`_sha256_of_frame` 对同一内存 frame 重算逐位稳定（wide/ohlcv/空 frame/全新重建同数据 均 stored==recompute），故"重算比对"零误伤——不会随机拒掉合法写入（实跑验证，非推断）。
- **验证（实跑·scoped，不跑全量）**：
  - `tests/test_dataset_write_gate.py` 11 测 + 触及改动模块的全部 scoped 文件（test_data_contract / test_field_store / test_academic_audit_v2 / test_data_quality / test_connectors / **test_intake**（实际登记写路径 e2e）/ test_field_catalog / test_dataset_sources / test_data_platform_review_fixes / test_agent_field_tools / test_tushare_fields）：**102 passed / 0 failed / 2.00s**。
  - 改动前同一 scoped 子集基线绿（42 passed），改动后含新 11 测 → 53→102 全绿，无回归。
- **变异（§2 种坏门必抓·定点反向 edit + Edit 还原）**：MUT-A（register 接线）7 红/4 绿；MUT-B（篡改分支）2 红/9 绿；均 Edit 反向还原后全绿，源中无残留 MUT 标记（grep 实证 none）。
- **未 land·未跑全量**：仅 deep-opus 任务线在隔离 worktree 实现 + scoped 验证；全量 1734 collected 基线与 land main 由中心 orchestrator（唯一写主仓库）跑。push 分支 `wave1/w3-dataset-write-gate` 待中心整合。

## 红线合规逐条自检
- **复用 lineage/ids.py·绝不另造哈希**：✅ frame 校验和重算复用既有 `_sha256_of_frame`（frame 检验和单源）；未引入任何新哈希函数；未碰 `lineage/ids.py`（其 content_hash 是 config/身份指纹、与 frame 校验和不同层，本卡无需）。
- **扩展不替换**：✅ 三处均纯新增（exception/method/__all__ 一行/register 一行/新测试文件）；未删未替 `dataset_hash.py` 不可变门、未改任何既有函数签名/行为。
- **向后兼容（合法写入字节不变）**：✅ 门是纯前置 READ 校验，不改 `_append` 写的 DatasetVersion；正路径（含空 frame）恒过；落账 jsonl 内容 == 接线前（test_registered_record_matches_fetch_result + 既有 42 测全绿佐证）。
- **不碰 field_catalog（W2 领地）**：✅ gate 放 register() 单点即覆盖 intake.py，field_catalog/ 零改动。
- **不破基线**：✅ scoped 102 passed/0 failed；全量由中心跑（未在本线跑全量，遵"只跑 scoped"）。
- **未验证≠已验证（§3）**：✅ 确定性/门有牙/scoped 绿均实跑坐实；全量 1734 + land 明标未做（中心职责）。

## 拍板项命中
无。本卡纯 correctness 接线（缺字段/篡改→拒），无经济/产品判断、无不可逆操作、无真实工程取舍二选一岔路——gate 落点（register 唯一单点）由写路径实证唯一确定，未触任何 `[需拍板]`。

## 诚实残余（非半成品·明确边界）
1. **on-disk manifest 门（dataset_hash.write_manifest/verify_manifest）仍只被 create_manifest 调用方触达**，register() 未自动为每次登记创建/校验磁盘 manifest——本卡选择在**写时单点**强约束 FetchResult 级完整性（覆盖实际 ingest 写路径、满足全部验收），文件级 on-disk 不可变 manifest 的自动接线属更大面、未纳入本卡（避免 register 与磁盘 manifest 目录的新耦合）。若后续要"每次登记自动落+校验 manifest"，可 mint follow-on（register 在有 file_paths 时调 create_manifest+write_manifest）。
2. **重算成本**：每次 register 多算一次 frame IPC+sha256（O(frame size)）——登记是每 dataset-version 一次（非每行），相对 fetch 可忽略；性能预算（沪深300×10年<3s）针对 fetch 非登记，无影响。
