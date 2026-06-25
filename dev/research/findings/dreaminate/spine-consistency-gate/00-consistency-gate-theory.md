# FINDING · Mathematical Spine 一致性门 — 形式化模型与必要性证明

- **蒸馏自**:GOAL §6（Mathematical Research Layer 字段契约 + 可证伪验收 1107-1116）· §8 治理脊柱硬不变量（1366-1369）· 决策 D-MATH-SPINE（一致性硬门 / 用户放权）· active 实现
- **证据强度**:中——形式化谓词与必要性论证可被对抗测试逐条证伪（每条门种一个反例必抓）；不声称证明了任何下游数学定理，只证明「门的拒绝集合恰好挡住 GOAL §6 列出的越权升级」。
- **适用域**:成立条件 = 一致性由「声明的 binding + ConsistencyCheck 结果 + 实现内容指纹」三者判定。**不成立的边界**：门不自行证明 `code_ref` 真的实现了 `definition`（那是 Verifier/Critic + 数值检查的活）；门只挡「声明与证据不自洽」和「声明强于证据」。

## 核心主张（可证伪）[必填]

若一个 `MathematicalArtifact` A 被请求升级到强标签 L ∈ {evidence_sufficient, proof_backed, production_ready}，当且仅当下列**升级健全谓词** Π(A, B, C, L, code_now) 全部子句成立时，门才放行该标签；任一子句失败 → 门拒绝该强标签、把产物降级到诚实标签（draft / challenged / 用户放权环境），且**绝不**把降级后的产物展示成 proof-backed。

```text
设：
  A = MathematicalArtifact（assumptions / definition / statement / derivation / proof_status）
  B = TheoryImplementationBinding（theory_ref, code_ref, config_ref, data_contract_ref,
        test_refs, code_content_hash := content_hash(code_ref 冻结源)）
  C = {ConsistencyCheck}，每条 result ∈ {pass, fail, pending}
  L = 请求标签
  code_now = 当前实现源（运行时取，用于 staleness）

Π 子句（每条对应 GOAL §6/§8 一条「→ 拒」）：
  (1) binding-exists    : B 存在且 B.test_refs ≠ ∅              [§6 公式无 impl/test binding → 不得 promoted]
  (2) binding-complete  : code_ref ∧ config_ref ∧ data_contract_ref 皆非空 [§8 TIB ⇒ code+config+data_contract]
  (3) consistency-present: C ≠ ∅ 且 ∃ 非 pending 决定性检查      [§8 TIB ⇒ ConsistencyCheck；§6 监控/执行称数学依据缺 CC → 拒]
  (4) consistency-pass  : ∀ c∈C, c.result ≠ fail                [§6 代码实现与数学定义不一致 → 拒]
  (5) fresh             : content_hash(code_now) == B.code_content_hash [§6 实现改动后未刷新 binding → 拒]
  (6) proof-honest      : L=proof_backed/production_ready ⇒ A.proof_status=proof_backed ∧ B.waiver_ref=∅
                                                                [§6 理论证明被 user 跳过但标 proof-backed → 拒]
  (7) pit-bound         : A.artifact_type ∈ {estimator, statistical_test, data_timing}
                          ⇒ B.data_contract_ref 带 PIT 时间语义(known_at ∧ effective_at) [§6 estimator 未绑 PIT → 拒]
  (8) claim-grounded    : L=proof_backed ⇒ A 存在且 statement∧derivation 非空 [§8 TheoryClaim ⇒ Artifact exists]

放行规则：
  L ∈ STRONG ⇒ 需 (1)(2)(3)(4)(5)(7)(8)；L ∈ {proof_backed, production_ready} 另需 (6)。
  任一必需子句失败 → granted_label 降级（见下），promotable=False。
```

## 必要性论证（每条门为何不可省 → 即对抗测试的反例）

健全性主张：**若 Π 任一必需子句失败，则存在一个场景，使被标成强标签的产物事实上 inconsistent / stale / 未证明**——即标签越权。故每条子句都是健全性的*必要*条件（不是锦上添花）。构造法：对子句 k，造一个满足除 k 外全部子句的 binding，证明产物若放行即假绿灯。

- **¬(1)** 有公式无任何 test_ref：声称「按理论实现」却无任何实现/测试证据 → 放行即纯声明假绿灯。
- **¬(2)** binding 缺 data_contract_ref：实现存在但不知喂什么数据契约 → 同一 code 在泄露数据上「一致」毫无意义。
- **¬(3)** 有 binding 无 ConsistencyCheck：从未比对过理论与实现 → 「一致」是未验证声称（§6 监控/执行触发器命门）。
- **¬(4)** 有一条 ConsistencyCheck result=fail：实现与定义已知不一致却放行 → 这正是 D-MATH-SPINE「理论对实现跑偏=系统错误」的核心。
- **¬(5)** code 改了但 binding.code_content_hash 是旧的：曾经一致 ≠ 现在一致；不抓 staleness 则改一行实现即可悄悄绕过所有 ConsistencyCheck。用 `content_hash` 做内容寻址指纹，改实现必变 hash → 门必抓。
- **¬(6)** user 放弃严格证明（waiver_ref 非空 / proof_status≠proof_backed）却请求 proof_backed：把未证明伪装成已证明，违 D-MATH-SPINE 边界「waiver 只改责任归属，不能伪装」。
- **¬(7)** estimator 不绑 PIT 时间：估计器在未来信息上「一致」是 look-ahead 泄露，撞安全不变量级红线。
- **¬(8)** 请求 proof_backed 但根本无 MathematicalArtifact（或 statement 空）：声明有数学依据却拿不出数学产物 → §8 `TheoryClaim ⇒ Artifact exists`。

降级映射（被拒后给诚实标签，不是一律 block）：
```text
有 waiver/choice 放权路径   → 该放权标签(user_waived_theory / exploratory)   # 诚实「用户选择跳过」
否则有 consistency-fail     → challenged                                      # 已知不一致，可留待 repair
否则缺 binding/CC           → draft                                           # 还没接实现
否则                        → exploratory
```

## 用户放权语义（D-MATH-SPINE 边界）

门**不**拒绝放权产物的*存在*——`MethodologyChoiceRecord.chosen_path ∈ {exploratory, user_waived_theory, ...}` 时，产物可在 `allowed_environment` 内继续研究/试验/paper。门只拒绝*越权标注*（把放权产物叫 proof_backed）。这严格落地 D-MATH-SPINE：「user waiver 只能改变研究/方法学松紧与责任归属，不能把未证明内容伪装成已证明内容」。放权不绕 secret 隔离 / OrderGuard / kill switch / no-silent-mock / A股 live 边界。

## 接线点（本项目 file:line）[必填]

| 文件 | 位置 | 接什么 |
|---|---|---|
| `app/backend/app/lineage/ids.py` | `content_hash` / `canonical_json` | binding staleness 指纹（复用单一身份源，绝不另造）|
| `app/backend/app/lineage/ledger.py` | `_ChainStore` / `GENESIS_HASH` | spine 账 append-only 哈希链（复用完整性范式）|
| `app/backend/app/lineage/spine.py` | 新增 | 4 个 frozen 数据模型（§6 字段全含）|
| `app/backend/app/lineage/spine_gate.py` | 新增 | `evaluate_promotion` 升级健全谓词门 |
| `app/backend/app/lineage/spine_ledger.py` | 新增 | binding/check/choice append-only 账（无改小 API）|

## §5 对抗测试要点（种已知 bug，门必抓）[必填]

1. ¬(1) 公式无 test_ref 请求 promote → 门拒、granted=draft。
2. ¬(2) binding 缺 data_contract_ref → 门拒。
3. ¬(3) 有 binding 无 ConsistencyCheck → 门拒。
4. ¬(4) 种一条 ConsistencyCheck result=fail → 门拒、granted=challenged。
5. ¬(5) bind 后改 code 源（content_hash 变）→ 门检出 stale 必拒。
6. ¬(6) waiver 在场却请求 proof_backed → 门拒、granted=放权标签。
7. ¬(7) estimator 的 data_contract 无 known_at/effective_at → 门拒。
8. ¬(8) 请求 proof_backed 但无 artifact / statement 空 → 门拒。
9. 全绿路径：8 子句全过 → promotable=True、granted=proof_backed（不一刀切全拒，证明门不是摆设）。
10. wording：被拒 verdict_text 不得出现「已证明/proof-backed/保证/可信」等越权词（防假绿灯口径反噬自身）。
11. ledger 无 `set_label`/`force_promote`/`delete`/`update` 改小 API（honest 不可手动伪造）。

## 复用 [按需]

`ids.content_hash`（staleness 指纹）· `ledger._ChainStore`（append-only 哈希链）· 现有 gate 范式（frozen verdict dataclass + violations 列表，参 `security/gate/policy.py` 的 `PolicyDecision`、approval gate 的 gap_list）。

## 未验证残余（诚实）[必填]

- 门**不证明** code 真的实现了 definition；它判定「声明 vs 证据是否自洽 + 强度是否够」。真正「实现对不对」靠 ConsistencyCheck 的 numerical/symbolic 检查内容质量 + Verifier/Critic——门只保证*有*这些检查且*都没失败*且*没过期*。
- 本切片只建门 + 数据模型 + 账，**尚未**把 data→factor→model→signal→portfolio→execution→backtest→attribution→monitor 全链每个数学点都接上 binding（gap #3 的「贯穿」部分仍是后续切片）。state.md 据此标 🟡 而非 ✅。
- PIT 子句(7)目前只校验 data_contract_ref 携带 known_at/effective_at 键，未与 R28 双时态 resolver 真连点查（后续切片接）。

## → 拆成的任务（已在本切片实现，落 done）[必填]

| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | 11 条对抗门全抓 + 全绿路径放行 + ledger 无改小 API | P0 | spine A 簇(ids/ledger)✅ |
