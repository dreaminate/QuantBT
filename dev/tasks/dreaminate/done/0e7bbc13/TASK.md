---
uuid: 0e7bbc137eee4b35b1168a6b20c20d45
title: W4 D-RDP-1 Research Delivery Package schema + manifest + §17 四拒绝门（greenfield·北极星总闸）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: delivery-backend
source: developer-claude
source_ref: GOAL §17 交付标准（行 2033-2076 开放格式 RDP 全契约 + 4 拒绝门）
depends_on: []
---

# W4 D-RDP-1 Research Delivery Package + §17 4 拒绝门

## Scope [必填]
greenfield 新建 `app/backend/app/delivery/`：`rdp.py`（§17 ~25 字段 RDP schema dataclass + 开放格式 JSON 序列化）+ `rdp_gate.py`（§17 行 2069-2076 的 4 条拒绝门，缺字段【真拒】不静默填默认）。身份复用单一源 `lineage/ids.py:content_hash`（不另造哈希族）；只读引用已建对象字段（DatasetVersion / honest-N / Verifier verdict / Approval），不改它们。本卡落 schema + 序列化 + 4 门 + 对抗测试；门4 接真实 promote 路径作 follow-on（诚实标 P2），但门本身真能拒。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 关系（只读复用·扩展不替换） |
|---|---|---|
| app/backend/app/delivery/rdp.py | 新建 | RDPManifest + DatasetVersionRef + PromotionClaim + 开放序列化 |
| app/backend/app/delivery/rdp_gate.py | 新建 | 4 门 + validate_rdp/require_valid_rdp/assemble_rdp + RDPRejected |
| app/backend/app/delivery/__init__.py | 新建 | 包导出 |
| app/backend/app/lineage/ids.py | content_hash | rdp_id 复用单一身份源（只读） |
| app/backend/app/data_hash/dataset_hash.py | DatasetManifest(dataset_id,version) | DatasetVersionRef 只读引用其身份 |
| app/backend/app/lineage/ledger.py | Ledger.honest_n / HONEST_N_DISCLOSURE | honest_n 字段只读引用 |
| app/backend/app/verification/schema.py | VerdictRecord.verdict_id | verifier_verdict_refs 只读引用 |
| app/backend/app/approval/schema.py | ApprovalGate.gate_id | approval_refs 只读引用 |
| app/backend/tests/test_rdp_gate.py | 新建 | 对抗测试 22 例 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 门1：去掉 manifest 身份 / artifact_hash / reproducibility_command 任一 → assemble/validate 拒；削弱门（放过缺字段）→ 测试红。
2. 门2：去掉 DatasetVersion（或给空壳 dataset_id/version）或 IngestionSkill 引用 → 拒。
3. 门3：unverified_residual=None（未声明）→ 拒；显式空 + 无署名 attestation → 拒（诚实闸）。
4. 门4：晋级断言缺/错配 rdp_ref、张冠李戴（资产不符）、追溯到残缺 RDP → 拒。
全部经定点反向 edit（非 git checkout）验证：削弱对应门 → 对抗测试转红，还原 → 复绿。

## 验收一句话 [必填]
正式研究交付 = 开放格式（JSON 第三方可解析）RDP；缺 §17 四类必填（manifest/artifact hash/repro command、DatasetVersion/IngestionSkill、未验证残余、晋级 RDP 追溯）任一【真拒】；身份复用 ids.content_hash 单一源；不破基线。

## 实现设计（grounded · 2026-06-26 实证锁定）
**身份（单一源·RULES.project）**：`rdp_id = "rdp_" + content_hash(身份载荷)`，复用 `lineage.ids.content_hash`（16 hex 哈希族，绝不另造）。身份载荷 = 除 `rdp_id/created_at_utc/created_by` 外的全部内容 → 内容寻址（内容变 id 变；时间/署名装饰字段不改 id）。frozen dataclass + `object.__setattr__` 计算 id（镜像 spine.py 范式）。

**schema 容器 vs 门分离（镜像 spine.py / spine_gate.py 范式）**：`RDPManifest` 是纯数据容器，必填字段给默认值【只为能装半成品草稿】，`__post_init__` 仅校验 asset_kind 枚举合法 + list→tuple 规范化。完整性【由门强制】：缺字段在门处真拒、绝不静默填默认（§17 可证伪 + RULES §3 诚实）。

**4 门**（`rdp_gate.py`，纯函数返 `RDPGateOutcome`，`validate_rdp` 聚合、`require_valid_rdp`/`assemble_rdp` 抛 `RDPRejected`）：
- 门1 `gate_manifest_completeness`：asset_ref / rdp_id / schema_version / artifact_hash / reproducibility_command 非空。
- 门2 `gate_dataset_lineage`：≥1 个可解析 DatasetVersionRef（dataset_id+version 非空，空壳不算）+ ≥1 个 IngestionSkill ref。
- 门3 `gate_unverified_residual`：None=未声明→拒；显式空()+无 residual_attestation→拒；非空 / 空+署名→过（区分「忘了想」vs「想过并署名说没有」）。
- 门4 `gate_promotion_traceability(PromotionClaim, RDPManifest|None)`：无 RDP/空 rdp_ref/ref 不解析/资产不符（张冠李戴）/追溯到残缺 RDP → 拒。

**§17 命名但全仓尚无类的对象**（`LLMCallRecord` / `ResponsibilityDisclosureRecord` / `TheorySpec`）→ RDP 按字符串 ref 持有（诚实：是引用，不内嵌不造类）。已建对象（DatasetVersion / honest-N / VerdictRecord / ApprovalGate）按其真实身份字段只读引用。

**开放格式**：`to_json` = `json.dumps(ensure_ascii=False, sort_keys=True)`，任何 `json.loads` 可解析、无私有二进制；`from_dict` 重建时不信任外部 rdp_id、按内容重算（防伪造 id 蒙混追溯）。

## 完成记录（2026-06-26 · 实跑为准）
**建了什么**（greenfield·零改既有文件·扩展不替换）：
- `app/backend/app/delivery/rdp.py`（新）：`RDPManifest`（§17 ~25 字段全含）+ `DatasetVersionRef`（只读引用 data_hash）+ `PromotionClaim`（门4 输入）+ 开放 JSON 往返。rdp_id 复用 `ids.content_hash`。
- `app/backend/app/delivery/rdp_gate.py`（新）：4 门 + `RDPRejected` + `RDPGateOutcome/RDPValidation` + `validate_rdp/require_valid_rdp/assemble_rdp`。
- `app/backend/app/delivery/__init__.py`（新）：包导出。
- `app/backend/tests/test_rdp_gate.py`（新·22 测）：4 门各坏门必抓 + 开放格式往返 + rdp_id 复用单一源 + 内容寻址 + 装饰字段不改 id + 伪造 id 不被信任。

**验证（实跑·scoped）**：`test_rdp_gate.py` **22 passed in 0.03s**（带 pytest.ini timeout=120 兜底）。变异验证（定点反向 edit，非 git checkout，逐门削弱后还原）：
- 门1 削 artifact_hash 检查 → `test_gate1_missing_artifact_hash_rejected` 红。
- 门2 削 dataset_versions 检查 → `test_gate2_missing_dataset_versions_rejected` + `..._hollow_...` 2 红。
- 门3 削 residual=None 守卫 → `test_gate3_residual_none_rejected` 红。
- 门4 削 mismatch 追溯核心 → `test_gate4_promotion_ref_mismatch_rejected` 红。
全部还原后复跑 22 passed，无残留 MUT 标记。

**北极星**：correctness（§17 契约一致 + 缺字段真拒不静默填默认）+ 安全不变量（未触碰任何执行/下单/key 路径，纯交付 schema 层）。无撞拍板项、无安全不变量风险。

**诚实残余**（非半成品·明确边界·follow-on 标清）：
1. **门4 未接真实 promote 路径**（P2 follow-on）：`gate_promotion_traceability` 是纯逻辑门、真能拒（给残缺/错配追溯断言即返拒、单测覆盖），但**尚未**被 `approval.gate.ApprovalGateService` / `paper.desk.PromotionGate` 的真实晋级流调用。接进去 = 在那两处 promote 前调 `require_valid_rdp(rdp, promotion=claim)`。本卡设计分工明确不强求端到端。
2. **§17 三个命名对象无类**（`LLMCallRecord` / `ResponsibilityDisclosureRecord` / `TheorySpec`）：全仓 0 类，RDP 现按字符串 ref 持有。这些类建好后可把对应 ref 字段收紧成 typed 引用 + 一致性校验。
3. **~20 个「契约携带」字段非硬门**：§17 列的 ~25 字段全部进 schema，但只有 4 门点名的 6 个 gate-critical 字段是硬拒；其余（归因/成本假设/deployment plan 等）随包带但本卡不逐条硬拒。是否把更多字段升级为硬门 = 方法学松紧，属用户那摊（提供流程不强加），本卡不替用户默认收紧，只守 §17 明列的 4 门 correctness。

**接缝**：晋级路径（approval/paper）接 `require_valid_rdp(..., promotion=claim)` 即兑现 §17「任何正式晋级须追溯 RDP」端到端；RDP 开放 JSON 可直接落盘/导出/第三方审计。
