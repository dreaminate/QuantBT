---
uuid: a00b39560f5b4fb7b8945141cc307724
title: Mathematical Spine 一致性硬门核心（数据模型 + 升级健全谓词门 + append-only 账）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: math-spine
source: goal
source_ref: GOAL §6（可证伪验收 1107-1116）+ §8（治理硬不变量 1366-1369）+ 决策 D-MATH-SPINE + finding spine-consistency-gate/00
depends_on: []
---

# Mathematical Spine 一致性硬门核心

## Scope [必填]
建 Mathematical Spine 的数据模型（MathematicalArtifact / TheoryImplementationBinding / ConsistencyCheck / MethodologyChoiceRecord，§6 字段全含）+ 升级健全谓词门 `evaluate_promotion`（强标签需过 Π 的 8 条必需子句，逐条对 §6/§8 一条「→ 拒」）+ append-only spine 账（复用 `_ChainStore` 哈希链、无改小/伪造 API）。**做**：让「公式无 binding / 实现不一致 / binding 过期 / 跳过证明却标 proof-backed / estimator 不绑 PIT」在真代码里真的被拒。**不做**：把 data→factor→model→signal→portfolio→execution→backtest→attribution→monitor 全链每个数学点都接上 binding（贯穿是后续切片，state 据此标 🟡）。

## 上下文 / 动机 [按需]
头号 gap #3「Mathematical Spine 未成为运行时脊柱」是北极星 #4 监管对齐的命门——理论对、实现跑偏=全盘皆输。state.md 明说「当前不能声称数学一致性门已建」。地基优先：下游因子轨/组合/信任层都依赖这道门。理论先行 finding：`dev/research/findings/dreaminate/spine-consistency-gate/00-consistency-gate-theory.md`。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/lineage/ids.py` | `content_hash`/`canonical_json` | 复用做 binding staleness 内容指纹（绝不另造身份源）|
| `app/backend/app/lineage/ledger.py` | `_ChainStore`/`GENESIS_HASH` | 复用 append-only 哈希链做 spine 账完整性 |
| `app/backend/app/lineage/spine.py` | 新增 | 4 个 frozen 数据模型 |
| `app/backend/app/lineage/spine_gate.py` | 新增 | `evaluate_promotion` 一致性门 |
| `app/backend/app/lineage/spine_ledger.py` | 新增 | `SpineLedger` append-only 账 |
| `app/backend/app/lineage/__init__.py` | 导出块 | 扩展导出 spine 符号 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. ¬binding-exists：公式无 test_ref 请求 promote → 门拒、granted=draft。
2. ¬binding-complete：缺 data_contract_ref/config_ref → 门拒。
3. ¬consistency-present：有 binding 无决定性 ConsistencyCheck（含只有 pending）→ 门拒。
4. ¬consistency-pass：种一条 result=fail → 门拒、granted=challenged。
5. ¬fresh：bind 后改 code 源（真 content_hash 变）→ staleness 必拒；binding 从未冻结指纹→拒。
6. ¬proof-honest：waiver 在场 / proof_status=sketch 却请求 proof_backed/production_ready → 门拒、granted=放权标签。
7. ¬pit-bound：estimator 的 data_contract 缺 known_at/effective_at → 门拒。
8. ¬claim-grounded：请求 proof_backed 但 artifact=None / statement 空 → 门拒。
9. 全绿路径：8 子句全过 → promotable=True、granted=proof_backed（门非一刀切）。
10. wording：拒绝 verdict_text 不出现越权正向断言词（假绿灯反噬自身）。
11. 账本：无 set_label/force_promote/delete/update 改小 API；篡改链可检。

## 复用 [按需]
`ids.content_hash`（staleness 指纹）· `ledger._ChainStore`（哈希链）· 现有 gate frozen-verdict 范式（参 `security/gate/policy.py` PolicyDecision、approval gate gap_list）。

## 红线 [按需]
- 诚实（§3）：未证明 ≠ 已证明；门自检拒绝口径不许越权词。
- 单一身份源（RULES.project）：staleness 指纹只走 `lineage/ids.py`，不另造哈希族。
- look-ahead 红线：estimator 不绑 PIT(known_at∧effective_at) → 拒。
- D-MATH-SPINE 边界：user waiver 只改责任归属，不能把未证明伪装成已证明。

## 非目标 [按需]
- 不做全链数学点贯穿（后续切片）。
- 门不证明 code 真的实现了 definition（靠 ConsistencyCheck 内容 + Verifier/Critic）。
- PIT 子句目前只校验 data_contract 携带 known_at/effective_at 键，未与 R28 双时态 resolver 真连点查。

## 收尾结果（done）
- 实装 3 模块 + 扩展导出 + 理论 finding；新增 `tests/test_mathematical_spine_consistency_gate.py`。
- 验证：新对抗测试 **28 passed**（0.08s）；lineage/ledger 基线 **33 passed**（未破，import sanity ok）；全量后端套件后台验证（真汇总行见 log）。
- 推进 GOAL §6/§8 + 头号 gap #3：⬜「未成为运行时脊柱」→ 🟡「一致性门核心已建并验证、全链贯穿待续」。
