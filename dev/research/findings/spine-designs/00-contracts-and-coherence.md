# 00 · 脊柱跨部件契约一致性 + 测试真实性复核

> 异角色复核（Opus 4.8，与设计 agent 隔离）· 不写新设计、只做对账与审计 · 中文
> 复核日期：2026-06-16（全 7 份 build-ready 设计齐备版，取代 2026-06-16 早先「仅 04 存在」初版）

---

## 0. 复核前提：7 份部件设计现已全部落 `spine/`

`docs/institutional-agent-os/spine/` 现有 7 份带「§4 file:line 接线 + §5 对抗测试规约」的 build-ready 设计：

```
01-deterministic-kernel.md   确定性 DAG 内核 + checkpoint/replay/fork/rollback + effectful 边界
02-llm-record-replay.md      LLM 节点 record/replay + 受控翻译层
03-lineage-bus.md            PROV 谱系总线 + run 快照强制属性 + config_hash/ledger/event 权威产方
04-hypothesis-card.md        可证伪假设卡 + 预注册 + confirmatory/exploratory
05-trial-ledger.md           R1/R8 内容寻址试验账本 + N_eff 收益相关聚类 + 多证据三角 gate
06-security-rbac-gate.md     Agent 安全 + 确定性策略门 deny-by-default + 交易所侧硬墙
07-approval-gates.md         HITL 审批门双通道 + promote 状态机 + 幂等恢复
```

**初版（只有 04）已下的 C1–C10 裁定，本版全部用真实 7 份设计复核并更新**。各部件已把初版 §1.2-A..H 裁定写进自己的正文（如 01 §1.1/§6、03 §3.4/§6、04 §1.2 全引），因此本版**不推翻已被采纳的裁定**，只做两件新事：(1) 把「悬空契约」逐条改判为「已落地 / 仍冲突」并指出**真实冲突点**；(2) 对 7 份 §5 做真实的「真对抗 vs 剧场 vs 缺探针」审计——这是本版的核心增量，因为初版只能审 04 一份。

**最重要结论先行（本版新发现的真冲突，按严重度排序）**：

1. 🔴 **`config_hash` 双产方冲突**：03 与 05 **都声称自己产 `config_hash` 且算法不同**——03 用 `sha256(canonical(因子AST+params+universe+dataset_version+freq+label))[:16]` 无前缀；05 用 `"cfg_"+sha256(...)[:24]` **24 位 + cfg_ 前缀 + factor_formula(非AST对象) + CONFIG_HASH_VERSION**。两者同名异值，且 **05 的 24 位直接违反全库 16 位脊柱不变量（§1.2-B）**。这是必须落地前解决的头号冲突。
2. 🟠 **`honest-N` / `N_eff` / 试验账本本体双实现**：03（`lineage/ledger.py` 的 `Ledger`）与 05（`experiments/trial_ledger.py` 的 `TrialLedger`）**各建一本 append-only 账**，落盘路径不同（`lineage/ledger.jsonl` vs `experiments/trial_ledger.jsonl`），聚类/计数 API 不同名。04/07 消费的「同一本账」到底是哪一本未裁定 → honest-N 会被劈成两本，R8「同一本账」根目标落空。
3. 🟠 **`effect_idempotency_key` vs `idempotency_key` 命名拆分只做了一半**：01/02/04 已改用 `effect_idempotency_key` / `request_idempotency_key`（遵从 §1.2-F），但 05 §6.2 仍写裸 `idempotency_key`、06/07 仍用裸 `idempotency_key` 表交易键。同名在 06/07 里指交易副作用键、在 04 里指 HTTP 端点键，跨部件读 `gate_event`/`ledger_entry` 时会混。
4. 🟡 **「独立验证记录 id」三处命名未收敛**：04 用 `verdict_id`、06 用 `verification_record_id`(在 `attestation` 内)、07 用 `verification_record_id`(顶层字段)。都指部件12验证官产物，但字段名两套（`verdict_id` vs `verification_record_id`），跨部件 join 会断。

下文任务 1 给统一契约表 + 逐条冲突裁定，任务 2 给 7 份 §5 的真实性审计。

---

## 任务 1 · 跨部件共享契约对账

### 1.1 统一契约表（10 类共享字段，全 7 份实测）

> 「产方」= 谁拥有该字段权威定义并落盘；「消费方」= 谁只读。第 4 列「口径冲突」标真实差异。

| # | 字段 | 语义 | 权威口径（应当） | 产方 → 消费方 | 实测一致性状态 |
|---|---|---|---|---|---|
| C1 | `run_id` | 一次 run 的身份句柄 | `str` = `run-{uuid4.hex[:12]}`（store.py:31，**已实做**），**非内容哈希** | 03 RunStore → 01/02/04/06/07 | ✅ 01 §6/02 §6.2/03 §6.2 一致声明「uuid 句柄，与 node_id 一对多、不混用」。无冲突。 |
| C2 | `config_hash` | 试验配置簇去重/计数键，honest-N 最小单元 | `sha256(canonical_json(因子AST+params+universe+dataset_version+freq+label))[:16]`，**排除** name/desc/tags | **03 试验账本**（初版裁定）→ 04/05/06/07 | 🔴 **双产方双算法**：03 与 05 都产，05 用 `cfg_`+`[:24]`+`factor_formula`，与 03 的 `[:16]`+`factor_ast` 冲突。见 §1.2-A。 |
| C3 | `dataset_version` | 数据集内容版本，frozen_oos 绑定 | `str` = `sha256(fp_blob)[:16]`（data_packages.py:70，**已实做**，已核） | 既有 data_packages + 06 数据访问层 → 01/03/04/05/07 | ✅ 全 7 份口径一致（16 位）。01 §6 把它进 node_id 的 inputs、05 §6.2 进 config_hash，正交使用正确。 |
| C4 | `content_hash` | 卡/工件冻结内容指纹 | `str` = `sha256(canonical_json)[:16]` | 04 产卡的、03 产 PROV Entity 的 → 验证官/执行侧 | ✅ 03 §3.2/§6.1 已明写「16 位，禁全长 64 位」，04 §3.5 同。初版 §1.2-B 不变量已被采纳。 |
| C5 | `checkpoint_id` | durable execution 可恢复锚点 | `checkpoint_id == node_id`（初版裁定，直接复用） | **01 内核** → 03/04/07 | ✅ 01 §1.1/§6「`checkpoint_id = node_id`」已落；03 §6.2/07 隐式消费。无冲突。 |
| C6 | `event` | 谱系/账本生命周期事件流 | 统一发到 03 `LineageBus`；`ProvEvent ∈ {START,COMPLETE,FAIL,ABORT,freeze,deviate,approve,reject,consumed,...}` | **03 谱系总线**（唯一汇聚点）← 01/04/06/07 发 | ⚠️ 词表未完全对齐：01 发 `START/COMPLETE/FAIL/HALT/RECONCILE_REQUIRED/CHECKPOINT`，02 发 `fingerprint_drift/consumed_again/model_id_is_alias`，06 发 `ORDER_GATED/ORDER_DENIED/REPLAY_REJECTED/LEASE_*`。03 的 `ProvEvent` 枚举**未含**这些扩展事件。见 §1.2-D。 |
| C7 | `node_id` | 内核 DAG 节点内容寻址身份 | `sha256(canonical_json(structure,inputs,sorted(upstream)))[:16]`，与 03 `content_hash` 同哈希族 | **01 内核** → 03（作 PROV Activity id）、05（去重）、02（=fixture_key） | ✅ 01 §1.1/§6 是权威产方，03 §3.2「同 sha256[:16] 哈希族」、02「fixture_key 即 node_id」。初版 §1.2-E 裁定已贯彻。 |
| C8 | `effect_idempotency_key` | 交易副作用去重键（防重复下单/划转） | 业务级 `client_order_id`/`transfer_request_id`；内核 `EffectLedger` 与 copy_trade `ct_dispatches` 同口径 | 执行侧产 → 01 ledger 登记、06/07 消费 | 🟠 **拆分只做一半**：01/02/04 已用 `effect_idempotency_key`/`request_idempotency_key`；05 §6.2、06、07 仍用裸 `idempotency_key`。见 §1.2-F。 |
| C9 | `verdict_id` / 独立验证记录 id | 异模型一致性检查记录主键 | **部件12验证官产** `verdict_id`；措辞强制 `consistency_check`，禁「组织独立」 | 部件12 → 04/06/07 消费 | 🟡 **字段名两套**：04 用 `verdict_id`，06/07 用 `verification_record_id`。同物异名。见 §1.2-G。 |
| C10 | `ledger_entry` | honest-N 一本账的单条记录 | `{entry_id=config_hash, config_hash, dataset_version, strategy_goal_ref, kind∈{backtest,train,card_freeze,factor_eval}, stage, returns_corr_cluster_id, created_at, result_ref}` | **03 试验账本**（初版裁定）→ 04/07 | 🟠 **05 另立一套 `TrialRecord`**（字段名 `research_theme_id`/`superseded_by`/`returns_ref`，与 03 `strategy_goal_ref`/`tombstone`/`result_ref` 不同名）。两套账本条目 schema 并存。见 §1.2-I。 |

> 颜色：✅ 已对齐 · ⚠️ 可扩展枚举/可补但不阻断 · 🟡 同物异名需统一 · 🟠 双实现需合并 · 🔴 硬冲突，落地前必堵。

### 1.2 不一致点 + 统一裁定（逐条）

**A. `config_hash`（C2）— 双产方双算法 [🔴 头号冲突]**
- 实测：
  - **03**（`lineage/config_hash.py`，§3.4）：`config_hash(factor_ast, params, universe, dataset_version, freq, label) -> sha256(canonical_json(...))[:16]`，**无前缀、16 位、入参是 `factor_ast` 对象**。03 §1.3 被 00 初版指定为权威产方。
  - **05**（`experiments/trial_ledger.py`，§3.1）：`config_hash(factor_formula, params, universe, dataset_version, freq, label) -> "cfg_"+sha256(...)[:24]`，**有 `cfg_` 前缀、24 位、入参是 `factor_formula` 字符串经 `normalize_factor_ast` 做 `ast.dump`**，并额外把 `CONFIG_HASH_VERSION="v1"` 进哈希。
- 三处实质差异：① 截断位数 16 vs 24（05 **违反 §1.2-B 全库 16 位不变量**，data_packages.py:70 已核为 16）；② 前缀 `cfg_` 有无；③ 因子归一化口径（03 哈希 AST 对象的 canonical_json，05 哈希 `ast.dump` 字符串）；④ 05 多一个版本命名空间字段。
- **裁定**：
  1. **权威产方仍是 03**（它是 PROV/event/ledger 汇聚地基，被全脊柱消费）。**05 不得自立第二套 `config_hash` 算法**——05 的 `experiments/trial_ledger.py` 应 `from ..lineage.config_hash import config_hash` 复用，不重写。
  2. 若保留 05 的 `cfg_` 前缀与 `CONFIG_HASH_VERSION`（口径版本化是好设计），则**把这两个增量上移进 03 的权威定义**，让全库统一为 `"cfg_v1_"+sha256(...)[:16]`，但**截断必须改回 16**（05 的 `[:24]` 是硬错）。
  3. 因子归一化：03 的「AST 对象 canonical_json」与 05 的「`ast.dump` 字符串」必须二选一并写进同一函数。05 §2.4/§7-1 已诚实承认 `ast.dump` 只挡空格/括号级同义、挡不住 `a*2`↔`a+a`——这点与 03 一致，靠 N_eff 收益聚类做第二道防线。建议采用 05 的 `normalize_factor_ast`（有 `__raw__:` 退化分支，对非表达式策略更鲁棒）作为 03 `factor_ast` 入参的预处理。
  - **未裁定即落地的后果**：03 算 `cfg_a1b2c3d4e5f6...`（16 位无前缀）、05 算 `cfg_a1b2c3d4e5f6a7b8...`（24 位带前缀），**同一策略两个 hash**，honest-N 在 04 freeze（读 03）与 05 promote gate（读 05 自己）两侧各数各的 → R8「同一本账」当场裂开。

**B. `content_hash` / 全库哈希 16 位截断 [✅ 已采纳，仅监督 05 回退]**
- 全库 `config_hash/content_hash/dataset_version/node_id/fixture_key` 一律 `sha256(...)[:16]`（data_packages.py:70 既有约定，已核）。03/04/01/02 全遵。**唯一回退点是 05 的 `[:24]`（见 A）**，落地前必须改回 16。

**C. `checkpoint_id`（C5）[✅ 已落地]**
- `checkpoint_id == node_id`（01 §1.1/§6 权威落地）。03/04/07 消费。无新冲突。

**D. `event` 词表归一 [⚠️ 03 枚举需扩展]**
- 实测：03 的 `ProvEvent` 枚举（§3.6）只列 `START|COMPLETE|FAIL|ABORT|freeze|deviate|approve|reject|consumed`，但 01 要发 `HALT/RECONCILE_REQUIRED/CHECKPOINT`、02 要发 `fingerprint_drift/consumed_again/model_id_is_alias`、06 要发 `ORDER_GATED/ORDER_DENIED/REPLAY_REJECTED/LEASE_ISSUED/LEASE_REVOKED`。这些事件 03 的枚举装不下。
- **裁定**：03 是唯一汇聚点（§1.2-D 初版裁定不变），但其 `ProvEvent` 须**扩成开放枚举或分类命名空间**（如 `kernel.HALT`、`llm.fingerprint_drift`、`security.ORDER_DENIED`），否则 01/02/06 发事件时要么被 03 拒、要么各记各的旁路 jsonl（审计轨迹再次裂开，正是 §1.2-D 要防的）。落地前 03 须把这三类部件的事件名收进枚举表。

**E. `node_id` vs 谱系 Entity id（C7）[✅ 已落地]**
- `node_id`=Activity 身份、`content_hash`=产出 Entity 身份、同 sha256[:16] 哈希族、靠 `wasGeneratedBy` 关联、durable 非 reproducible（01 §1.1/§6、03 §3.2 全落地）。任务书点名核心问题已闭合。**注**：02 的 `fixture_key="llmfx-"+sha256[:16]` 自带 `llmfx-` 前缀，而 01 的 `node_id` 无前缀但又说「fixture_key 即 node_id」——前缀不一致是个小缝：03 拿 `fixture_key` 当 PROV Activity id 时，到底带不带 `llmfx-`？建议统一为「`node_id` 不带前缀，`fixture_key` 是 `node_id` 的带前缀别名」，03/05 去重时一律 strip 前缀比对。

**F. `effect_idempotency_key` vs `request_idempotency_key`（C8）— 拆分做一半 [🟠]**
- 实测：01 §6（`effect_idempotency_key`）、02 §6.3（`request_idempotency_key`/`effect_idempotency_key` 明确分家）、04 §3.6/§6（freeze 用 `request_idempotency_key`）**已遵从初版 §1.2-F 拆名**。但：
  - **05 §6.2** 仍写裸 `idempotency_key`（「与 config_hash 对齐：promote 用 config_hash 做幂等键」）——这其实是「业务记账幂等」，但用裸名。
  - **06 §6**（`gate_event.idempotency_key = f(signal_id,follower_id) 或 f(order canonical)`）、**07**（`ApprovalGate.idempotency_key`）仍用裸 `idempotency_key` 表交易副作用键。
- **裁定**：把交易/门后副作用键全部改名 `effect_idempotency_key`（06/07 应改），HTTP 端点去重键全部 `request_idempotency_key`（已改）。05 的 promote 幂等键属「业务记账幂等」，建议直接复用 `config_hash` 做键并改名 `effect_idempotency_key`（与 01 `EffectLedger` 对齐），避免裸 `idempotency_key` 在 `gate_event`/`ledger_entry` 里同名两义。**这是 M17 同类雷区**——MEMORY 记录跟单中继曾绕过幂等，根因正是「同名键覆盖不全」。

**G. 「独立验证记录 id」（C9）— 同物异名 [🟡]**
- 实测：04 用 `verdict_id`（§3.3 `ConsistencyReview.verdict_id`）；06 在 `attestation` 内、07 在 `ApprovalGate.verification_record_id` 顶层字段。都指部件12验证官产物。
- **裁定**：统一字段名为 `verdict_id`（04 已用、语义更准——它是「一致性裁决」而非「验证证明」）。06/07 的 `verification_record_id` 应改名 `verdict_id`（或在 schema 里显式 `verdict_id = verification_record_id` 别名映射）。**红线（R7）全 4 份已正确**：04/06/07 都强制措辞 `consistency_check`、禁「组织独立/independent validation」，部件12 落地不得反悔。06 §7-4 还诚实点出「验证官与生成 agent 可能共享盲点，独立性需被度量非假定」——这条比单纯改名更重要，须传到部件12。

**H. `event` 双词表（卡状态机 vs run 生命周期）[✅ 已落地]**
- 04 §1.2/§3.4 已把卡状态跃迁（draft→frozen→deviated→retired）映射为 PROV Activity 发到 03 总线（03 §3.6 `LineageBus.emit_event` 含 `freeze/deviate/approve/reject`）。无冲突，但受 §1.2-D 枚举扩展约束。

**I. `ledger_entry` / 试验账本本体双实现（C10）[🟠 与 A 同根]**
- 实测：03 §3.4 `LedgerEntry`（`entry_id/config_hash/dataset_version/strategy_goal_ref/kind/stage/returns_corr_cluster_id/result_ref`，落 `lineage/ledger.jsonl`）与 05 §3.2 `TrialRecord`（`config_hash/research_theme_id/result/returns_ref/metrics/asset_class/stage/superseded_by`，落 `experiments/trial_ledger.jsonl`）是**两本物理不同的账**，字段名也不同（`strategy_goal_ref` vs `research_theme_id`；`result_ref` vs `returns_ref`/`result`；tombstone 软删 vs `superseded_by` 软删）。
- **裁定**：这是「同一本账」原则（R8）的最大结构性威胁，必须合并为一本：
  1. **谁拥有账本本体？** 03 是 PROV/event 汇聚地基且被 04/07 直接消费 `honest_n_at_freeze`；05 拥有 N_eff 收益聚类 + 多证据三角 gate 的全部算法。建议：**账本存储与 `config_hash`/`honest_n` 计数归 03**（一本 `ledger.jsonl`），**N_eff 收益聚类 + overfit_gate 算法归 05**（05 的 `n_eff`/`run_overfit_gate` 读 03 的账本，不自存第二本）。
  2. 字段名统一：`research_theme_id`（05）≡ `strategy_goal_ref`（03/04）——这是同一个「主题/卡家族聚类外键」，必须取一个名（建议 `strategy_goal_ref`，与 04 `multiplicity.strategy_goal_ref`、07 一致）。否则 04 按 `strategy_goal_ref` 聚卡家族、05 按 `research_theme_id` 累计 N，**两个维度对不上，honest-N 双账**。
  3. 软删语义统一：03 用 tombstone、05 用 `superseded_by`——都「不减 N」，但实现两套，合并时取一。
  - **未裁定即落地的后果**：04 freeze 读 03 的 `honest_n`、05 promote gate 读 05 的 `n_observed`，**同一研究主题两个 N**；R8「memoize 与 honest-N 同一本账」根目标在两本账上无法成立。

### 1.3 衔接关系小结（任务书三个点名问题的直接回答）

1. **内核 node_id 哈希口径 vs 谱系 Entity id 是否对齐？** → **已对齐**（§1.2-E）：同 sha256[:16] 哈希族，node_id=Activity 身份、content_hash=产出 Entity 身份，靠 `wasGeneratedBy` 关联，durable 非 reproducible。01/03 正文均已落。残留小缝：fixture_key 的 `llmfx-` 前缀在被 03 当 Activity id 时要 strip。
2. **试验账本 config_hash 与谱系 dataset_version 怎么衔接？** → **正交不混用**：`dataset_version`（C3，数据内容哈希，回答「用了哪份数据」）进 `config_hash`（C2）的输入之一；`config_hash` 回答「这是第几次试同一个想法」。03 §3.4 `LedgerEntry` 同时存这两个键（`config_hash` + 独立的 `dataset_version`），让「同 config 换数据集反复试」也被识别（防换数据集刷 N）——设计正确。**但前提是 config_hash 只有一套算法**（§1.2-A 必须先解决双产方冲突，否则衔接的是两个不同的 config_hash）。
3. **审批门引用的「独立验证记录 id」是谁产的？** → **部件12验证官产 `verdict_id`**（§1.2-G）；04/06/07 都只引用；措辞强制 `consistency_check`、禁「组织独立」。残留问题：字段名 `verdict_id`（04）vs `verification_record_id`（06/07）须统一。

---

## 任务 2 · 测试真实性审计（核心）

> 判定口径：**真对抗** = 种一个已知 bug（拆掉/绕过这道门），测试会**因此 fail**；**剧场** = 门即使坏了/被绕过测试照样 pass（只测函数跑通/字段存在/覆盖率）；**缺探针** = 该部件职责里有一类失效模式但 §5 无任何测试会抓它。

### 2.1 部件 01 · 确定性内核 —— §5 T-DET-1..10

| 测试 | 判定 | 理由（关键看「门坏了会不会 fail」） |
|---|---|---|
| T-DET-1 durable≠reproducible（replay 不重跑 LLM，spy 断言 LLM op 调 0 次） | **真对抗** | spy 断言 `LLM op 被调 0 次`+计数器不自增——replay 偷跑 LLM 则计数器变、spy>0 → fail。这是 R11 命门的真探针。 |
| T-DET-2 node_id 内容寻址不变量（装饰字段同 id、upstream 变则 id 变） | **真对抗** | 直测内容寻址核心不变量，归一化错（漏排/多排字段）→ 假命中或永不命中 → fail。 |
| T-DET-3 effectful 边界幂等（重复 run 同 key，place_order 只调 1 次） | **真对抗（本部件最重）** | venue spy `place_order 调用次数==1`——重发单则 2 次 → fail。形态同 test_copy_trade.py 幂等回归，已验证范式。 |
| T-DET-4 fork 在 effectful 边界截断（fork 下游订单不重发、发 reconcile） | **真对抗** | `effectful_order 状态==halted` + `place_order 0 次新调用` + 发 `reconcile_required`——fork 透传到下单则真金白银重发 → fail。 |
| T-DET-5 rollback 不撤单走对账（无 cancel/反向单） | **真对抗** | 断言 venue 无 cancel/反向 order 调用——rollback 自动撤单则 fail。守 R7 硬边界。 |
| T-DET-6 崩溃从 checkpoint 恢复（不重跑 A/B，B 经 is_consumed 命中） | **真对抗** | 恢复后 B `place_order 0 次新调用`——恢复整段重跑则 B 重发单 → fail。直击 jobs.py:132-138 现有「整段重跑」雷。 |
| T-DET-7 effectful 缺幂等键构造即 raise | **真对抗** | `pytest.raises(ValueError, match=...)`——裸字段不校验则能构造出会重发单的节点 → fail。这是「字段→约束」升级的验收点。 |
| T-DET-8 LLM 当控制器回归（LLM 输出篡改 deps 被忽略） | **真对抗** | 执行顺序==静态拓扑序——LLM 改了调度则偏离 → fail。守 dossier §1 核心纪律。 |
| T-DET-9 memoize 复用不把 honest-N 改小（命中 2 次但账本通知 3 次） | **真对抗（跨部件，但有缝）** | 断言账本 `on_attempt` 回调被调 3 次——命中即不计 N 则只 1 次 → fail。**缝**：本测 mock 账本钩子，真实账本是 03/05（双账，§1.2-I 未解决），mock 绿不证明真账本不吞通知。应标 `[集成必补]`。 |
| T-DET-10 裁决措辞（禁 reproducible/可信/安全/组织独立） | **真对抗** | 正则黑白名单——宣称 reproducible/可信则 fail。 |

**01 缺探针**：① **`_io_normalize` 字段白名单探针缺**——§7-1 自己点名「漏排→假命中（最危险）」，但 §5 无一条专测「装饰字段白名单与 03 config_hash 排除集（name/desc/tags）一致」。T-DET-2 只测「无关装饰字段同 id」一例，未覆盖「白名单边界 = 03 排除集」的一致性。这是 01 自承的最大风险点却无探针。② **effect_idempotency_key 由 LLM 产 → 重跑漂移换 key 绕幂等闸**（§7-2 自己点名 M17 同类雷），§5 无探针种「LLM 节点产 key」这个坏。③ **跨存储原子性**（§7-4：工件已写 ledger 未记的窗口），无崩溃注入探针打这个窗口。

### 2.2 部件 02 · LLM record/replay —— §5 A/B/C/D/E/F

| 测试 | 判定 | 理由 |
|---|---|---|
| A1 replay 偷跑真 API（mock inner.chat 调用 0 次） | **真对抗** | `chat 调用次数==0`——fallback 打真 API 则 mock 被调 → fail。R11 命门。 |
| A2 fixture 篡改（改 tool_calls 不更新 integrity） | **真对抗** | `verify_hmac raise IntegrityError`——裸读不校验则脏数据进下游 → fail。 |
| A3 cache key 碰撞（同 node_pos 不同 run_index/upstream） | **真对抗** | 两 key 必不等、并存——key 只哈 prompt 则错命中 → fail。直击 dossier §7.3 best-of-N 碰撞。 |
| A4 翻译「确定地错」（schema 合规但 leverage=30 超上限） | **真对抗** | 返 `human_confirm_required`+tool 未派发——schema 合规即放行则错误被放大 → fail。 |
| A5 fingerprint 静默漂移 | **真对抗** | 产 `fingerprint_drift` 事件——不记 fingerprint 则无事件 → fail。**缝**：事件发到 03 总线，但 03 `ProvEvent` 枚举不含此事件（§1.2-D），真集成会被 03 拒。 |
| A6 别名冒充版本（model_id 传滚动别名） | **真对抗** | 标 `model_id_is_alias=True`+告警——别名当不可变 id 则复现承诺无痕作废 → fail。 |
| B1 replay 逐字节确定 | **真对抗** | 两遍 canonical_json 逐字节相同。 |
| B2 翻译被夹死不静默降质（pass^k） | **真对抗（口径诚实）** | 同时断言 `caveat` 存在——这条还防了「强制 temp=0 反致 SEMANTIC 级低」被藏。 |
| B3 三级度量解耦 | **真对抗** | `pass^k(action)>pass^k(decision)` + 含「高确定性≠高正确性」caveat。 |
| C1 两套实现对账 fixture_key | **真对抗** | 独立参考实现重算，不一致 BLOCK。 |
| C2 验证官 consistency_check 措辞守门 | **真对抗（有依赖缝）** | 断言 `"independent" not in 记录` + 含 `verdict_id`。**缝**：`verdict_id` 字段名与 06/07 的 `verification_record_id` 不一致（§1.2-G），跨部件 join 会断；应标 `[集成必补]`。 |
| D1 put 幂等 / D2 tombstone 不减 N / D3 崩溃中段恢复 / D4 一次性消费留痕 | **真对抗** | D2 断言 distinct 计数不减（honest-N 不可改小）；D3 mock inner chat 调 0 次覆盖已录 step；D4 二次读产 `consumed_again`。均种坏断言。 |
| E1 复现报告措辞 | **真对抗** | 黑白名单措辞匹配。 |
| F1 record↔replay 对账 | **真对抗** | decision 级不一致 fail 并打印 diff。本部件版「回测↔paper 对账」。 |

**02 缺探针**：① **honest-N 计数到底落哪本账**——D2 测「tombstone 不减 N」但 N 由「部件03 聚类计数」（02 §1.3），而 03/05 双账（§1.2-I）；02 §5 无探针验证「fixture 的 distinct 计数与 03 账本的 honest_n 对得上」。② **`request` 加密落盘覆盖性**（§7-5 自承敏感数据面 + 键碰撞攻击 arXiv 2601.23088），§5 无探针种「敏感字段未加密落盘」或「locality-key 碰撞」。A3 测的是 key 不碰撞、未测「攻击者构造碰撞 prompt 抗碰撞校验」。

### 2.3 部件 03 · 谱系总线 —— §5 T1..T15

| 测试 | 判定 | 理由 |
|---|---|---|
| T1 可复现强制属性缺失（缺 seed → reproducible=False；七项全齐→True） | **真对抗（正反双向）** | 正反都断言——gate 把缺 seed 当可重现则两向 fail。dossier「必要不充分」命门。 |
| T2 谱系覆盖盲区告警（绕装饰器调原始函数） | **真对抗** | 未覆盖路径∈告警、已覆盖∉。监控漏报则 fail。对冲「血缘腐烂」。 |
| T3 谱系污染/伪造（插断裂边 + 篡改 prev_hash） | **真对抗（措辞诚实）** | 标 `tampered=True`+悬空边不返回；且报告写「检出哈希链不连续」不写「保证内容真实」（防过度声称）。 |
| T4 dataset_version 不可变变形 | **真对抗** | 复用 dataset_hash.py 的 `DatasetIntegrityError`，改字节重写 raise。 |
| T5 canonical_json 键序/Unicode 不变量 | **真对抗（00 §2.2 点名缺探针，已补）** | 键序乱 + NFC/NFD 同哈希——键序敏感则 honest-N 高估 → fail。 |
| T6 LLM 重放确定性（replay 时 client 抛错） | **真对抗** | client mock `call_count==0`+逐字节相同——偷跑则 >0 → fail。 |
| T7 honest-N 不可改小（无 set_n API、谎报被忽略） | **真对抗（命门·硬）** | `hasattr(Ledger,"set_n") is False` + 谎报 N=2 实读 5。**与 04 T5/07 T5 同一不变量**，三侧独立测须口径一致。 |
| T8 memoize 命中不重跑且不重复计 N | **真对抗** | 第二次 `hit=True`+计算函数 `call_count==1`+`honest_n` 不 +1。 |
| T9 换无关字段不刷 N + N_eff 等价公式不翻倍 | **真对抗** | 同 config_hash、`honest_n` 只 +1；等价公式收益相关聚回 1 簇。**缝**：依赖 config_hash 单一算法，§1.2-A 双产方未解则本测在 03 算法下绿、05 算法下行为不同。 |
| T10 谱系事件幂等 / T11 崩溃恢复跳坏行 | **真对抗** | T10 同 `request_idempotency_key` 重复 emit 只一条；T11 半行后仍可 dag/honest_n。 |
| T12 实盘/paper 不假装可重现 | **真对抗** | Live 节点 `replayable=False` 即便 snapshot 完整。守边界。 |
| T13 谱系≠信任文案守门（中英黑名单） | **真对抗** | 子串黑名单（可信/安全/trustworthy/组织独立）——把 DAG 完整渲染成可信则 fail。 |
| T14 n_eff 诚实免责守门 | **真对抗** | 含「相关聚类下界/非精确计数」disclaimer。 |
| T15 回测↔paper 关联 + 背离告警（A股分支单独断言无 live） | **真对抗（分资产）** | A股 `asset_class=="equity_cn"` 时无 live 段、不空跑显绿。 |

**03 §5 自身诚实度高**（§5 末尾已标 T7/T13/T14/T15 为 `@pytest.mark.integration_pending`，明示 mock 绿不冒充系统绿——这是 7 份里最诚实的测试规约）。**03 缺探针**：① **子进程 DL 训练真实 seed 回传**——§7-5 自承「主进程装饰器采集的是主进程 seed、与子进程实际执行可能不一致 → T1 在 DL 路径退化为剧场」，但 §5 **无任何探针**种「子进程实际 seed≠主进程声明 seed」这个坏。这是 03 自承的「T1 最大剧场化风险点」却无对抗测试，**必补**。② **CoverageMonitor 白名单自身过时**（§7-6），T2 测「绕装饰器被抓」，未测「新路径忘登记则白名单漏报」。

### 2.4 部件 04 · 假设卡 —— §5 T1..T13（沿用初版逐条审，补充集成缝）

| 测试 | 判定 | 理由 |
|---|---|---|
| T1 不可证伪条件（四规则 + 字数达标的套套逻辑 (d)） | **真对抗** | (d) 专验「没退化成字数门」——启发式退化为 min_length 则 (d) 漏过 → fail。 |
| T2 空机制（含反向：探索留空必放行） | **真对抗（正反）** | 误卡探索或放过空 confirmatory 两向都 fail。 |
| T3 OOS 泄露（晋级绑已碰过的数据） | **真对抗 + [集成必补]** | mock 下抓；`touched_versions` 写回方是部件06，§5 已标必补真集成。诚实。 |
| T4 探索层越权摸 OOS | **真对抗** | BLOCK。P2 硬边界。 |
| T5 honest-N 不可改小 | **真对抗 + [集成必补]** | 与 03 T7/07 T5 同一不变量；标必补真账本集成。 |
| T5b 噪声探针（垃圾随机文本字数达标） | **真对抗** | 规则4 noise 命中或验证官 concern，绝不判 high。T1 的噪声兜底。 |
| T6/T6b content_hash 篡改 + 键序/NFC 不变量 | **真对抗** | exclude 集正确性双向验。 |
| T7 冻结只读 / T8 晋级谱系 | **真对抗** | setattr 抛 CardFrozenError；晋级发 PROV 事件。 |
| T9 验证官一致性检查对账 | **真对抗 + [集成必补]** | concern 当 pass/漏「组织独立」/重放重跑都 fail；标部件12 必补。 |
| T10/T10b 冻结幂等 + 并发双写 | **真对抗** | 同 `request_idempotency_key` 返存量不重跑验证官；并发靠 threading.Lock 只一条。 |
| T11 崩溃恢复跳坏行 | **真对抗** | 复用 store.py:98-102 容错。 |
| T12 措辞守门（中英扩展黑名单 + needs_human_review=True） | **真对抗** | 永不自动放行下注。 |
| T13 阶梯一致性（A股分支单独断言无 live） | **真对抗（分资产）** | A股不走 live 分支、不空跑显绿。 |

**04 §5 诚实度高**（T3/T5/T9/T13 全标 `[集成必补]`，§5 开头明示「mock 下绿只证 mock 的诚实」）。**04 缺探针**：基本无致命缺口；唯一可补的是 **`lineage_hook` 在部件03未就绪时的 `pending_lineage` 对账补发**（§7-7），T8 测了「emit 被调/pending 落地」，未测「03 上线后 pending 被正确回填且不重复」。

### 2.5 部件 05 · 试验账本 + 多证据三角 gate —— §5 T1..T16

| 测试 | 判定 | 理由 |
|---|---|---|
| T1 噪声探针（50 列纯随机 → gate 不返 green） | **真对抗** | `color!="green"`+`all_agree_positive False`。升级为整个 gate 必抓。 |
| T2 泄露探针（虚高 Sharpe + 30 高相关变体 → N_eff<<N_observed） | **真对抗** | `n_eff.point<n_observed`+`dsr_conservative<dsr_optimistic`（通缩区间非退化）。 |
| T3 已知真信号必过（抓误杀） | **真对抗** | `color=="green"`+三支同向正——保守主义误杀真信号则 fail。 |
| T4 短样本判证据不足非虚假红绿 | **真对抗** | `insufficient_evidence`+不输出会被误读为「修复后好夏普」的单点。 |
| T5 打乱时间 → block bootstrap 比 iid 更敏感 | **真对抗** | block 变化幅度 > iid——证明 block bootstrap 真用序列信息（iid 对 shuffle 不变）。 |
| T6 换种子 verdict 不翻色 | **真对抗** | green↔red 不翻转。 |
| T7 加成本净 Sharpe 下降 | **真对抗** | `sharpe(net)<=sharpe(gross)`。 |
| T8 三支不同向必不放行（无单点承重） | **真对抗** | DSR 单支过关但 CI 跨零 → 必 yellow。证 DSR 永不单点裁决。 |
| T9 独立重算对账（scipy 算 skew/kurt） | **真对抗** | 差异 >1e-6 即 FAIL。 |
| T10 memoize 幂等不重复计 N | **真对抗** | 第二次命中、`n_observed` 差=1。 |
| T11 换等价写法 N_eff 必抓（a*2 vs a+a 收益相同聚 1 簇） | **真对抗（核心断言）** | `n_observed==2`+`n_eff.point==1`。防换等价公式绕过的命门。 |
| T12 N 不可手动改小 | **真对抗（硬）** | supersede 后 N 不减、文件行数只增。 |
| T13 崩溃恢复跳坏行 / T14 换 session/theme 不重置 | **真对抗** | T14 按 theme_id 跨 session 累计。 |
| T15 措辞断言 | **真对抗** | 禁可信/安全/保证、含「只与诚实 N 一样诚实」。 |
| T16 gate 输出可被 risk_summary 消费（接线活性证明） | **真对抗（点睛）** | 种 `dsr=0.1` → `trust_level=="high_risk"`+flag `low_dsr_confidence`。**直接证明「守门器从死接活」**——dossier 点名的洞被补上。这是 7 份里最锋利的「接线活性」探针。 |

**05 §5 是 7 份里对抗强度最高的**（T11 防换公式、T16 接线活性、T5 block-vs-iid 敏感度差都是真探针）。**05 缺探针 / 风险**：① **config_hash 双产方未测**——05 §5 全程用自己的 `cfg_[:24]` 算法，**无一条探针验证「05 算的 config_hash == 03 算的 config_hash」**（§1.2-A）。若两本账并存，T10/T14 的「N 跨 session 累计」在 05 自己的账上绿，但 04 freeze 读的是 03 的账，**两个 N 对不上而 §5 抓不到**——这是 05 最大的剧场化风险（测试在单账假设下绿，真系统双账下裂）。**必补**：一条「03 与 05 对同一策略算出同一 config_hash + 同一本账」的集成探针。② **var_sr_hat(V) 估计不可靠时的退化**（§7-5 自承 V 估计噪声大），T2 测通缩区间存在，未测「V 不可估退化为旧近似时披露明示通缩可能不足」。

### 2.6 部件 06 · 安全策略门 —— §5 T1..T18

| 测试 | 判定 | 理由 |
|---|---|---|
| T1 注入绕过策略门（+ broker.issue 从未被调） | **真对抗（核心）** | `allow False`+`broker.issue.assert_not_called()`——注入成功也取不出 key。INV-3 真探针。 |
| T2 白名单 deny-by-default（空集=deny-all） | **真对抗** | 空白名单 deny 而非 allow。 |
| T3 提币默认禁（类型级 Literal["deny"]） | **真对抗** | `PolicyGate(withdraw="allow")` 抛 ValidationError——结构上装不下 allow。 |
| T4 杠杆上限不被中继绕过（relay+直连两路都夹，M17 回归） | **真对抗** | 到交易所内核 `leverage<=2`，两路都被夹——证明门接全了不止 relay。 |
| T5 重放探针（同 nonce 两次） | **真对抗** | 第二次 REJECT_REPLAY+nonce 留痕。 |
| T6 密钥泄漏（序列化 token grep api_secret） | **真对抗** | 产物不含 api_secret 子串；broker 外 fetch 抛 PermissionError。 |
| T7 决策值语义投毒（signal_score=99 离群） | **真对抗** | `anomaly_flags` 含 poison_suspect+`trust=untrusted` 不能单独驱动 go_live。 |
| T8 escalate 缺 attestation 必 BLOCK | **真对抗** | CRYPTO_LIVE 大额无 attestation → allow False+missing_attestation。 |
| T9 正常单必须放行（抓误杀） | **真对抗** | 白名单内合规单 allow True。 |
| T10 路径不变量：四路径同判 | **真对抗（M17 命门）** | paper/binance_um/generic/relay 喂同一违规单返回 violations 一致——证明是一个会话外门而非四套局部检查。 |
| T11 tier 单调性 / T12 提高门槛不放水 | **真对抗** | CRYPTO_LIVE 拒的 PAPER 不一定拒、反之必拒；调小 max_notional 后原 allow 变 deny。 |
| T13 双实现对账（1000 随机单） | **真对抗** | 逐单 allow 一致，不一致 BLOCK。 |
| T14 验证官异模型复算 | **真对抗（措辞）** | 符号不翻 + 报告含「非组织独立」声明。 |
| T15 幂等 lease / T16 崩溃恢复不重发 | **真对抗** | 同 key 返存量、broker 不二次发 lease、place_order 调 1 次；崩溃从 nonce+dispatch 表判已发不重发。 |
| T17 措辞门（+ TCB 诚实「本地对属主仅防篡改证据非防篡改」） | **真对抗** | 正则黑名单禁安全/可信/保证。 |
| T18 阶梯 + 回测↔paper 对账 | **真对抗** | testnet 未 100% → CRYPTO_LIVE 拒；门决策对不上=指向 bug 标红。 |

**06 §5 对抗强度高**（T1 broker.assert_not_called、T10 四路径同判、T13 双实现对账都是真探针）。**06 自承的诚实边界极强**（§7-6 遗漏攻击「选择性不记录」hash-chain 防不住、§7-7「通过本测试集≠防住自适应攻击」）。**06 缺探针**：① **「选择性不记录」遗漏攻击**（§7-6 自己点名 hash-chain 只防改已记录、防不住 agent 不写不便的 gate_event），§5 **无探针**种「agent 跳过写 audit」这个坏——这是 06 自承的主导攻击却无对抗测试（虽然 §7-7 诚实承认测试集天花板，但至少应有一条「漏记被下游对账抓到」的探针）。② **fail-open/fail-closed**（§7-3 自承 broker/验证官宕机时 CRYPTO_LIVE 怎么办未定），T8 测缺 attestation BLOCK，未测「attestation 服务宕机时是 fail-closed 还是 fail-open」。

### 2.7 部件 07 · 审批门 —— §5 T1..T16

| 测试 | 判定 | 理由 |
|---|---|---|
| T1 噪声探针（纯随机 → PBO≈1/DSR≈0 → 拒，stage 未翻） | **真对抗** | 返 GateRejection+`list_versions` 确认仍 dev。 |
| T2 泄露探针（三角不同向必拆穿，即便 dsr 填高） | **真对抗** | `pbo>PBO_CEIL` 或 `ci[0]<=0` 拒——不因单一漂亮指标放行。 |
| T3 缺要件三连（三 case gap 文案各不同） | **真对抗** | 精确命中对应缺口字符串，非笼统「缺东西」。 |
| T4 approver==creator 防自审 | **真对抗** | 抛 ApproverEqualsCreator、stage 未翻。R7「生成≠验证」不可自我满足。 |
| T5 honest-N 不可改小（手填 n_eff=3 抬 DSR） | **真对抗（硬）** | 用账本侧 N_eff 重算、手填更小 N 不能让 DSR 过线。**与 03 T7/04 T5 同一不变量。** |
| T6 已知真信号必过（抓误杀） | **真对抗** | open→pending→approve→approved，stage 翻 production。 |
| T7 打乱时间 → 同证据重算应拒 / T8 换种子不翻符号 / T9 加成本拉到拒绝侧 | **真对抗** | 时间结构破坏后门必察觉；裁决对种子稳定；成本敏感性传导到门。 |
| T10 独立复算对账（creator 自报与独立验证差>容差 BLOCK，不取均值） | **真对抗** | R7 异模型不一致即 BLOCK。 |
| T11 returns_sha256 防换等价公式 | **真对抗** | 不同 config_hash 同 returns_sha256 → 识别同序列计同聚类。 |
| T12 重复 idempotency_key 不重发（mock venue place_order 调 1 次） | **真对抗** | `side_effect_executed==True` 返存量。照搬 executor.py:82-87。 |
| T13 崩溃从最近 checkpoint 恢复（fork/rollback 截断非重发） | **真对抗** | side_effect_ref 已写则不重发；崩在 INSERT/ack 间用 client_order_id 反查对账。 |
| T14 超时默认按 action_kind 分流 | **真对抗** | stop_loss→default_allow、transfer→default_reject，都留痕。 |
| T15 措辞断言 | **真对抗** | 禁安全/可信/保证、含具体 gap+适用域空洞。 |
| T16 阶梯 + 回测↔paper 对账（审批≠授权，批了仍被阶梯卡死） | **真对抗** | `hard_limits.enforce` 拒绝超 cap；对不上指向 bug 拒晋级。 |

**07 缺探针 / 风险**：① **T5/T10/T11 全押在「账本能按 config_hash 查到 n_eff + returns 指纹」**，而账本是 03/05 双账（§1.2-I）+ config_hash 双算法（§1.2-A）。07 §7-2 自己诚实点名「若账本未就绪门只能退化到信任 n_trials_raw，需定义降级措辞」——但 §5 **无探针**种「账本未接入时门是否正确退化 + 是否诚实标注 N 未独立核验」。T5 在 mock 账本下绿，真双账下「读哪本」未定 → 剧场风险。**必补 `[集成必补]`**。② **`_is_substantive` reason 反套话**（§7-5 自承纯长度/关键词易绕过且可能误杀），T15 测措辞黑名单，未测「纯套话 reason 被 `_is_substantive` 拒」这个坏（confirmatory 审批理由空泛是 dossier 点名的「装样子」）。③ **单用户 approver≠creator**（§7-6 自承单用户属主既是 creator 又是唯一审批人），T4 测 `approver=="alice"==creator` 抛错，但**未测**「单用户场景下验证官 agent 充当 approver 身份」这条 §7-6 提出的落地路径是否真能过门。

### 2.8 跨部件「同一不变量三处独立测」对账纪律（最高价值发现）

honest-N 不可改小这一条不变量被 **03 T7 / 04 T5 / 05 T12 / 07 T5** 四处独立测——这是好的（多证据无单一承重点）。但**前提是四处读的是同一本账、同一个 config_hash**。当前 §1.2-A（config_hash 双算法）+ §1.2-I（账本双实现）未解决，意味着：

- 03 T7 在 `lineage/ledger.jsonl` + 03 的 config_hash 下绿；
- 05 T12 在 `experiments/trial_ledger.jsonl` + 05 的 `cfg_[:24]` 下绿；
- 04 T5 / 07 T5 mock 账本下绿。

**四处全绿，但测的是三本不同的账。** 这正是初版担心的「契约缝上裂开」的具体形态：每个部件的 §5 在自己的假设下诚实，合起来却不构成「同一本账的 honest-N 不可改小」。**裁定：§1.2-A + §1.2-I 必须先合并为一本账一套 config_hash，然后补一条跨部件集成探针——「03/04/05/07 对同一 strategy_goal_ref 读到的 honest_n 完全相同」**，否则这四条真对抗探针合起来仍是「四本账各自的剧场」。

---

## 标注① · 接线点 file:line 核对（抽查实代码，逐条核实）

| 部件 | 引用 | 核实结果 |
|---|---|---|
| 01 | `engine.py:25` DAGTaskStatus | ✅ 准确（`Literal["pending","running","succeeded","failed","skipped","timeout"]`，确缺 reused/halted）。 |
| 01 | `engine.py:52` `DAGTask.idempotency_key` | ✅ 准确（:52 `idempotency_key: str|None=None`，:53 `sla_seconds`，确为纯装饰字段）。 |
| 01 | `beta.py:113` make_idempotency_key / `:124-152` record_dispatch | ✅ 准确，但**它们是 `BetaLedger` 的实例方法（带 self）**，01 §2.2 称「三件套」未点明是方法非模块函数——泛化为 `EffectLedger` 时要注意是实例方法形态。 |
| 01 | `executor.py:82-87` is_dispatched skip / `:148-160` record_dispatch | ✅ 基本准确：:82-87 幂等 skip 确在；record_dispatch 实际在 :150（01 写 :148-160 区间含它，:147 有 CRITICAL 注释），区间正确。 |
| 02 | `agent_runtime.py:70` `self._llm.chat(...)` / `:69` for-loop | ✅ 准确（:69 `for _ in range(self._max_steps)`、:70 `chat(messages, tools=TOOL_SCHEMA)`）。 |
| 03 | `store.py:31` `_gen_id`=`{prefix}-{uuid4.hex[:12]}` / `Run` :47-63 | ✅ 准确（:31 确为 hex[:12]；Run 字段 inputs/metrics/parent_run_id/forked_from 确在、确无 snapshot/config_hash）。 |
| 03 | `data_packages.py:70` `sha256(fp_blob)[:16]` | ✅ 准确（:70 `hashlib.sha256(fp_blob.encode("utf-8")).hexdigest()[:16]`）。**这正是 05 `[:24]` 违反的不变量源头。** |
| 04 | `store.py:80-103` `_JsonlStore` / :30-31 _now/_gen_id | ✅ 准确（已核 :31）。 |
| 05 | `eval/dsr.py:33` `_expected_max_sr(n_trials)` / `:41` deflated_sharpe_ratio | ✅ 准确（:33 确只吃 n_trials 无 V；:41 签名 `(returns, n_trials, periods_per_year=252)`，05 加 `var_sr_hat` 向后兼容成立）。 |
| 05 | `ide/promote.py:52` promote_ide_run / `:87` metrics=_compute_metrics | ✅ 准确（:52 def、:87 `metrics = _compute_metrics(rows)`，gate 插入点正确）。 |
| 06 | `executor.py:102` `_make_venue` / `:134` place_order | ✅ 准确（:102 `venue = self._make_venue(f, self._keystore)`、:134 `ack = venue.place_order(order)`）。 |
| 07 | `store.py:232-238` promote 三行裸翻转 | ✅ 准确（:232 def、:235 `v.stage = stage` 裸翻转，确无审批/approver/证据，dossier 点名洞属实）。 |
| 07 | `store.py:23` ModelStage / :65-78 ModelVersion（stage 在 :68） | ✅ 准确（:23 `Literal["dev","staging","production","archived"]`；ModelVersion.stage 在 :68）。 |

**无明显写错文件 / 越界行号**：抽查 14 处接线点全部命中或落在所述区间内。唯一可注意的措辞缝是 01 把 `make_idempotency_key/is_dispatched/record_dispatch` 称「三件套」而它们是 `BetaLedger` 实例方法（非 beta.py 模块级函数），泛化时形态要对齐。

---

## 标注② · 7 部件建设依赖顺序建议

> 依据：谁是「权威产方」被多方消费、谁只消费别人。地基先建，消费方后建。

```
第 0 层（地基·并列最先，互为对方的契约前提）
  ├─ 03 谱系总线 + 试验账本本体 + config_hash 权威 + event 汇聚
  │     （产 config_hash/content_hash/node_id 同族/ledger_entry/event/honest_n，被全脊柱消费）
  └─ 01 确定性内核（产 node_id/checkpoint_id/EffectLedger/HALT 暂停点；03 的 PROV Activity id 即 node_id）
     ↑ 01 与 03 必须同期对齐 node_id↔content_hash 哈希族（§1.2-E）+ checkpoint_id=node_id（§1.2-C），
       否则谁先建谁都要返工。建议同一冲刺内交付、共用一份 node_id.py。

第 1 层（紧贴地基，强依赖 01+03 的 id 与账本）
  └─ 05 试验账本算法层（N_eff 聚类 + 多证据三角 gate）
        ★ 关键：05 必须复用 03 的 config_hash 与账本本体（§1.2-A/§1.2-I），不自立第二套。
          所以 05 的「账本存储」其实属第 0 层归 03，05 只建「N_eff/overfit_gate 算法」读 03 的账。

第 2 层（消费 id + 账本 + LLM 工件）
  ├─ 02 LLM record/replay（产 fixture_key=node_id；消费 01 的 checkpoint、03 的 run_id/config_hash）
  └─ 04 假设卡（消费 03 的 honest_n/config_hash_cluster/ledger_ref、02/01 的 replay_ref、12 的 verdict_id）

第 3 层（执行侧硬墙 + 门，消费上面全部）
  ├─ 06 安全策略门（消费 attestation=03/05 账本产出、verdict_id=部件12、effect_idempotency_key=01）
  └─ 07 审批门（消费 03 的 n_eff/config_hash、06 的 SafetyService 阶梯、部件12 的 verdict_id、01 的恢复语义）

第 4 层（被 04/06/07 引用但未在本批 7 份内）
  └─ 部件12 验证官（产 verdict_id；04/06/07 都消费）—— 不在本批，但 04/06/07 的 [集成必补] 全卡它。
     建议紧随第 3 层或与之并行，否则 04 T9 / 06 T14 / 07 T10 永远只能 mock 绿。
```

**关键依赖纪律**：
1. **01 与 03 必须同期、共用 `node_id` 实现**（§1.2-E/C/A 全在这对接口上）。谁单独先建都会在 node_id↔content_hash↔checkpoint_id 三角上返工。
2. **05 不是独立第 1 层，它的「账本存储」归 03**（§1.2-I）。把 05 当独立账本先建，就会造出第二本账，R8 当场裂。05 落地第一件事是 `from ..lineage import config_hash, Ledger`，删掉自己的 `trial_ledger.py` 存储层、只留算法层。
3. **部件12（验证官）虽不在本批，但是 04/06/07 三份的 `[集成必补]` 共同阻塞点**——它产的 `verdict_id`（§1.2-G）是三份的三要件之一。建议把它提到第 3 层并行，否则脊柱右半边（卡/门）的真集成测试全部停在 mock。

---

## 附：本复核自身的诚实边界

- 本复核**只读 7 份 spine 设计文档 + 抽查 14 处真实代码行号**，未运行任何测试、未实现任何契约合并。「真对抗 / 剧场 / 缺探针」判定基于「§5 描述的种坏+断言**若按字面实现**是否会因门坏而 fail」——实现时若断言写虚（如只 assert 函数返回非 None 而不验值），仍可能从真对抗退化为剧场。**判定的是规约意图，不是实现保证。**
- 四个跨部件 `[集成必补]`（honest-N 三处对账 / verdict_id 三处 join / config_hash 双算法对账 / 账本双实现合并）在被依赖部件落地前**无法验证**，本复核只能指出缝、给裁定，不能证明缝已堵。
- 头号冲突 §1.2-A（config_hash 双产方）与 §1.2-I（账本双实现）是**结构性的、必须在 01/03/05 落地前由人拍板合并方案**——本复核给了裁定方向（归 03、05 只留算法层、截断回 16），但最终归属与字段命名需设计 agent 与用户确认。
