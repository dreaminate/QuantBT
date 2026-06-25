---
uuid: ec7a7d9a07764b37bc23d49abb4c1284
title: 数据写门 scope 余项——11 字段 + data 级 lineage + on-disk manifest 自动接线（B-VERSION-1 余）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: data-pit
source: goal
source_ref: GOAL §11/§16 + 0430cd78 完成记录诚实残余（核心 block 门 ✅·scope 余项 🟡）
depends_on: [0430cd78e7a944db83f3644451fd42ae]
spec_ref: dev/tasks/pool/ec7a7d9a/TASK.md
branch: wave2/w3-dataset-fields
---

# 数据写门 scope 余项（B-VERSION-1 余）· 完成记录

> 自含卡。spec = `dev/tasks/pool/ec7a7d9a/TASK.md`。只动领地四处
> （`connectors/base.py` · `data_quality.py` · `lineage/` · `data_pull.py` 仅实证未改），
> 未碰 field_catalog/ · training/ · main.py · data_hash/。中心负责整合 + 跑全量 + land。

## 改动文件（扩展不替换）
- `app/backend/app/connectors/base.py` — FetchResult 补 §11 信封·源/采集侧字段
  （source_ref / ingestion_skill_version / secret_ref / known_at_utc / effective_at_utc，全 optional 默认空）；
  新增 `is_secret_reference()`；`validate_for_write` 扩 `require_provenance` 门 + secret_ref 引用守门。
- `app/backend/app/data_quality.py` — DatasetVersion 补 §11 信封字段（含 quality_verdict / lineage_id /
  manifest_path）；`from_dict` 加固（缺键填默认 + 未知键忽略·向后/向前兼容）；`register()` 扩 keyword-only
  信封参数 + 自动派生 data 级 lineage + on-disk manifest 自动落+校验（落账前·拒则不落账）。
- `app/backend/app/lineage/data_lineage.py` — **新增** data 级谱系（DatasetLineageNode / DataToFactorEdge /
  derive_dataset_lineage / trace_dataset_to_factors），id 全走 `ids.content_hash` 不另造。
- `app/backend/app/lineage/__init__.py` — 导出上述 data 级谱系符号（扩展 __all__）。
- `app/backend/tests/test_dataset_envelope_lineage.py` — **新增** 18 条对抗验收（4 验收 + 红线）。

## 实证结论（卡首动作）
1. **canonical 写口 = `field_catalog/intake.py::register_official_dataset` → `DatasetRegistry.register()`**
   （off-limits 领地，第一波 0430cd78 已接 `validate_for_write` block 门）。本卡的 manifest/lineage/信封
   全接在 `register()` 单点 → canonical 写路径全覆盖。
2. **`data_pull.py` 写路径完全绕过 register 门**（实证·未改）：`save_csv()`→`frame.write_csv(path)`
   （L311-313），调用点 L925/1036/1038；全文 **0 处**触达 DatasetRegistry / register / FetchResult /
   validate_for_write / write_manifest。Tushare 子路径（`tushare_quant1/`）同样不登记 DatasetRegistry
   （写 parquet + catalog inventory.json）。
   → **结论：legacy quant1-style 批量拉取（Tushare + Binance fapi）不在 register 门覆盖内。是否回收进门
   = 拍板项（见下），本卡按领地限定「写路径实证」未擅自接线**（接线要动 main.py 的 DATASET_REGISTRY 单例
   + tushare_quant1，越领地且有拉取 perf/baseline 风险）。
3. `DatasetVersion(` 全库仅 data_quality.py 内部构造（无外部构造方）；`DATASET_REGISTRY`（main.py）只读
   不 register dataset；`FetchResult.to_meta()` 无外部调用 → 加字段零外部破面。

## 字段↔GOAL §11「每次数据更新记录」信封映射
| §11 信封 | 落点 | 状态 |
|---|---|---|
| source_ref | FetchResult + DatasetVersion | ✅ 新增 |
| ingestion_skill_version（=skill_version）| 同上 | ✅ 新增 |
| secret_ref（引用·不落明文）| 同上 + 写时引用守门 | ✅ 新增 |
| checksum | DatasetVersion.sha256 | ✅ 既有 |
| dataset_version | DatasetVersion.version_id | ✅ 既有 |
| known_at / effective_at | FetchResult + DatasetVersion | ✅ 新增 |
| quality_verdict | DatasetVersion（由 ge_results 派生 pass/fail/unknown）| ✅ 新增 |
| lineage | DatasetVersion.lineage_id（register 内 content_hash 自动派生·恒在场）| ✅ 新增 |
| schema_drift_status | DatasetVersion（信封槽位·真 drift 检测非本卡 scope）| 🟡 槽位 |
| freshness_status | **刻意不冻结**（随时间变·由 compute_freshness 活算）| 设计取舍 |

## 真测试汇总（point-in-time·命令自带 timeout）
- 新卡对抗：`tests/test_dataset_envelope_lineage.py` → **18 passed**（`python3 -m pytest … -q`，从 app/backend 跑）。
- 不破基线 scoped 重跑（12 文件：write_gate / data_quality / intake / field_catalog / agent_field_tools /
  data_contract / field_store / training_pit_wiring / dataset_sources / lineage_node_id / lineage_ledger / 本卡）
  → **111 passed**。改动前同集基线 = 93 passed（26+67），新增 18 → 111，**零回归**。
- 只跑 scoped、未跑全量（中心整合时跑全量）。

## 对抗测试（种坏门必抓·MUT 定点反向 edit·绝不 git checkout）
- **MUT on-disk manifest**：`_write_and_verify_manifest` 退回 advisory（删旧 manifest 再写·绕过不可变比对）
  → `test_ondisk_manifest_blocks_disk_tamper_same_version` + `test_ondisk_manifest_detects_manifest_file_tamper`
  **2 红（DID NOT RAISE DatasetIntegrityError）**。反向 edit 还原 → 复绿。
- **MUT 缺字段（provenance/secret）**：`validate_for_write` 放过 require_provenance + secret_ref 守门
  → `test_require_provenance_rejects_missing_skill_and_secret` + `test_plaintext_secret_rejected_and_not_echoed`
  **2 红（DID NOT RAISE DatasetWriteIntegrityError）**。反向 edit 还原 → 复绿。
- MUT 残留扫描：`grep MUT-1|MUT-2|临时放过|退回 advisory` → CLEAN。

## 可证伪验收逐条
1. 缺 skill_version/secret_ref → 拒（`require_provenance=True`）✅；明文裸 key（无 scheme）→ 拒且诊断不回显 ✅。
2. on-disk manifest 同 version 内容漂移 / manifest 被篡改 → register 自动校验拒（不可变门）✅，拒后不落账 ✅。
3. data 级 lineage 可追溯 dataset→factor（复用 FactorBinding 三元组 → DataToFactorEdge 连通）✅。
4. 向后兼容：信封不进 version_id/checksum（身份不被扰动）✅；无/占位 file_paths→无 manifest 不炸 ✅；
   旧 registry 行（无信封键）from_dict 仍解析 ✅。

## 红线合规逐条
- 数据缺 dataset_version/checksum → 拒（第一波门保留·未删未替）✅；缺 lineage → **不可能缺**
  （register 内 content_hash 自动派生·恒在场）✅。
- 复用 `lineage.ids.content_hash`（lineage_id / edge_id）+ `dataset_hash` 文件哈希·`_sha256_of_frame`
  → **绝不另造哈希族** ✅。
- 扩展不替换：不可变门（dataset_hash.write_manifest）+ 第一波写门（validate_for_write）一行未删未替 ✅。
- 实盘 key/secret 不落明文：secret_ref 写时强制引用形（scheme:…），裸 key 拒；诊断/异常绝不回显凭据原值
  （测试 `assert raw_key not in str(ei.value)` 钉死）；secret_ref 不进 manifest ✅。
- 不破基线：先 collect+run 实测基线 93 绿再动手 ✅；MUT 用反向 edit 非 git checkout ✅。

## 拍板项（涉口径/越领地·停报中心·未擅自定）
1. **字段提级必备**：skill_version/secret_ref 是否对所有数据写入【强制必备】？本卡按「提供机制不强加口径」
   做成 **opt-in `require_provenance=False` 默认关**（开则缺即拒）——默认关保既有 intake 写入不破。
   提级为默认必备会 break 既有 canonical caller（intake.py 不传这两字段）+ 属方法学口径，**留给中心/用户拍**。
2. **data_pull.py 回收进门**：legacy 批量拉取要不要接进 register 单点？需动 main.py 的 DATASET_REGISTRY 单例
   + tushare_quant1（越本卡领地），且对拉取 perf/向后兼容有 baseline 风险。**未擅自接·留中心定**。

## 诚实残余（🟡）
- `schema_drift_status` 仅落信封槽位，**未实现真 drift 检测**（需对比上版列集/类型，属上游 IngestionSkill /
  field_catalog 职责，非本卡领地）。
- `data_pull.py` legacy 写路径未进门（见实证 ②·拍板项 ②）——canonical 新写口（intake）已全覆盖。
- data 级 lineage 是**容器 + 内容寻址身份**：trace 出 dataset→factor 边表达「绑定关系」，**不**声称 factor
  数值正确（与 spine.py 诚实边界一致）。
- on-disk manifest 多文件分支用 `os.path.commonpath` 取 root；当前所有真实 caller（intake/field_catalog）
  均传**单 file_path**，多文件跨目录为未触达边界（单文件路径全测覆盖）。
