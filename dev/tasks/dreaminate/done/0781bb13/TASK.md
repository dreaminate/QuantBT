---
uuid: 0781bb130bb740c18f271f91bb8d9d5f
title: RDP 聚合器——从真血统装配 RDP（DatasetVersion/LLMCallRecord/honest-N/verdict 真填）（D-RDP-2）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: delivery
source: goal
source_ref: GOAL §17(RDP ~25 字段·DatasetVersion/IngestionSkill/LLMCallRecord/replay/honest-N/verdict/approval 引用)；D-RDP-1(9d593481)建 schema+4 拒绝门·本卡聚合真血统填字段
depends_on: [9d593481fd674978930926f541f2b7b3, 640b66a0cfb44c3295b2fa8cf57a3568]
branch: wave4/d-rdp-2
---

# RDP 聚合器（D-RDP-2·北极星 §17 总闸·LLM Gateway 已解锁）

## Scope [先读 GOAL §17·已读 行 2033-2076]
D-RDP-1（9d593481）建了 RDP schema（`delivery/rdp.py`）+ §17 四拒绝门（`delivery/rdp_gate.py`）。本卡建 **RDP 聚合器**——从**真血统**装配 RDP：① DatasetVersion（data_quality）② LLMCallRecord（llm/call_record）③ artifact hash（lineage/ids）④ honest-N（lineage/ledger）⑤ Verifier verdict / Approval ⑥ 未验证残余（诚实闸）。聚合器产**真 RDP** 喂 D-RDP-1 拒绝门校验。

## 领地（只动·扩展不替换）
扩 `app/backend/app/delivery/`——**新增** `aggregator.py`（standalone 子模块）。**未改** `rdp.py` schema / `rdp_gate.py` 4 门语义 / `delivery/__init__.py`（刻意不改 __init__：避免每个 `app.delivery` importer〔paper/desk、approval/gate〕被迫拉全 llm gateway 栈·零 import 图爆破半径）。**只读**：llm/call_record、data_quality、lineage/ids·ledger、verification/schema、approval/schema。**未碰** main.py、被读模块内部、其他在飞线、RunDetailPage。

## 完成记录（2026-06-26 · 实跑为准 · 隔离 worktree·中心整合+全量+land）

### 新建文件（2 个·扩展不替换）
- `app/backend/app/delivery/aggregator.py` —— RDP 聚合器：`aggregate_rdp(...) -> RDPAssembly`（真血统→RDP string ref 映射 + 喂 `validate_rdp` D-RDP-1 门 + honest_gaps 诚实披露 + known_secrets 安全扫描）；`require_aggregated_rdp(...)`（装配即强制过门·未过 raise RDPRejected）；`RDPAssembly`（rdp + validation + honest_gaps·开放 to_dict）。
- `app/backend/tests/test_rdp_aggregator.py` —— 24 个对抗式测试（全程真源类·零 mock）。

### 真测试汇总行（scoped·带 timeout·凭真汇总行判绿）
- `tests/test_rdp_aggregator.py` 单跑：**24 passed in 0.33s**。
- 回归（聚合器 + 既有交付门）：`test_rdp_aggregator.py + test_rdp_gate.py + test_rdp_wire.py` → **61 passed in 0.73s**（既有 37 不破）。
- collect-only：baseline **2010** → 加本卡 **2034**（+24·零 collection error）。
- py_compile 两新文件 OK。ruff 本机未装（跳过·非阻断）。

### 真血统映射（单一身份源·不另造）
| RDP 字段 | 真源 | 映射 |
|---|---|---|
| dataset_versions | `DatasetVersion`(data_quality) | `DatasetVersionRef(dataset_id, version_id, sha256)` |
| ingestion_skill_refs | `DatasetVersion.ingestion_skill_version` ∪ 显式 | 派生+合并 |
| data_source_refs | `DatasetVersion.source_name/source_ref` ∪ 显式 | 派生+合并 |
| llm_call_record_refs / llm_provider / replay_state | `LLMCallRecord.call_id/provider/replay_state` | 真 id（**不取 auth_ref/明文**） |
| honest_n | `Ledger.honest_n(goal_ref)` | 真查询·无 Ledger→None（不补 0） |
| verifier_verdict_refs | `VerdictRecord.verdict_id` | 真 id |
| approval_refs | `ApprovalGate.gate_id` | 真 id |
| artifact_hash | `lineage.ids.content_hash(artifact)` | 缺时由真 artifact 派生（单一哈希族） |

### 对抗测试（种坏门必抓·MUT·绝不 git checkout·Edit 注入+复原）
- **MUT-A 缺真 DatasetVersion 门拒**：注入「无 dataset 时伪造默认 ref」→ `test_missing_dataset_version_gate2_rejects` 转红（`dataset_versions` 从 missing 消失）→ 复原绿。证明聚合漏真 DatasetVersion → D-RDP-1 门2【真拒】、伪造默认放行必被抓。
- **MUT-B 真血统不编造**：注入「LLM 用了但无 record 时塞假 call ref」→ `test_llm_used_no_record_marks_missing_not_beautify` 转红（`llm_call_record_refs != ()`）→ 复原绿。证明缺 LLMCallRecord 标 missing 不美化、塞假 ref 必被抓。
- **MUT-C 安全闸**：注入「关掉 known_secrets 扫描」→ `test_plaintext_live_key_in_freetext_caught_by_safety_gate` 转红（DID NOT RAISE）→ 复原绿。证明实盘明文进 RDP 自由文本必 raise SecretLeakError。
- 额外真血统反映：honest_n 从真 Ledger 查（3 试验→3·7 试验→7·无 Ledger→None）、DatasetVersionRef 镜像真 version/sha（篡改源→ref 变→rdp_id 变）、call_id/verdict_id/gate_id 均来自真对象。

### 红线合规（逐条）
1. **复用单一源不另造** ✅：rdp_id/artifact_hash 走 `lineage.ids.content_hash`、honest_n 走 `Ledger.honest_n`、secret 扫描复用 `llm.call_record.scan_messages_for_secret`——零自造哈希/扫描器。
2. **开放格式 JSON** ✅：RDP `to_json` 第三方 `json.loads` 可解析、往返 rdp_id 稳定（`test_assembly_open_json_roundtrip_stable_id`）。
3. **缺字段诚实标 missing·no template false success** ✅：缺 LLMCallRecord/Ledger/verdict/approval → honest_gaps 标 missing、绝不塞假；honest_n 无源→None 不补 0。
4. **实盘 key 不进 RDP** ✅：LLMCallRecord 只取 call_id/provider/replay_state，auth_ref(SecretRef) 根本不写进 RDP（`test_record_auth_ref_secretref_not_in_rdp_only_call_id`）；known_secrets 给出则装配后扫开放 JSON·明文命中即 SecretLeakError（撞即停）。
5. **扩展不替换** ✅：rdp.py/rdp_gate.py/__init__.py 全未改（`git diff --stat` 空）；只新增 aggregator.py + 测试。
6. **RunDetailPage 冻结·不碰 main.py/被读模块内部/其他在飞线** ✅：git status 仅 2 新文件。
7. **无新公式不强造 MathematicalArtifact** ✅：未造数学工件；math/theory refs 走 context_fields string ref passthrough。

### 拍板项命中
- **无新拍板岔路**。D-SCOPE-CONSERVATIVE（RDP 强制档常开待用户）= 已决不问：本卡只产聚合器+真血统填+喂门，**未**把 `require_rdp=True` 接进真 promote 端到端常开（守「等聚合器即本卡·常开仍待用户」边界）。

### 诚实残余（未验证/留 follow-on）
- **命名对象 typed 化**：LLMCallRecord 已 typed 引用（runtime import·消费真对象产 call_id）；DatasetVersion/VerdictRecord/ApprovalGate/Ledger 走 `TYPE_CHECKING` 注解 + duck-typed 读真属性（避免 delivery 层 runtime 拉 polars/sqlite 重依赖·传入仍是真实例）。TheorySpec/ResponsibilityDisclosureRecord 全仓未建 → context_fields string ref passthrough·不强造。
- **端到端强制档**：`require_aggregated_rdp` 真能拒，但**未**接进 `approval.gate`/`paper.desk` 的真 promote 路径常开（require_rdp 仍默认关）——待用户拍 D-SCOPE-CONSERVATIVE 常开档。这是【接线 follow-on】，非本卡 scope。
- **secret 扫描限界**：known_secrets「已知明文逐字匹配」（与 LLM Gateway 门2 同口径），不号称识别任意未在册高熵串。
- **__init__ 未导出**：`aggregate_rdp` 经 `app.delivery.aggregator` 导入（非 `app.delivery`）——刻意保守降 import 图爆破半径；若中心要顶层导出可后议（扩展 __init__·非本卡擅动）。

## 非目标（守住）
不改 D-RDP-1 schema/4 门语义；不接真 promote 端到端强制档（用户拍）；TheorySpec 类未建不强造。

## 交接给中心
分支 `wave4/d-rdp-2`（基 origin/main·前四波已 land）。中心整合点：跑全量后端（带 timeout·凭真汇总行）+ validate_dev + 决定是否顶层导出 aggregate_rdp + 是否接 require_rdp 常开（待用户）。
