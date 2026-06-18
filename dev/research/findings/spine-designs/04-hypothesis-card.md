# 04 · 可证伪假设卡 + 预注册 + confirmatory/exploratory(P2 不挡探索)
> 脊柱 build-ready 设计 · 接 R1–R29 决策 · 含 file:line 接线 + 对抗式测试 · Opus 4.8
> 本版已吸收 `00-contracts-and-coherence.md` 跨部件契约复核的全部点名修正（§1.2 A/D/F/G/H + §2.1/§2.2 测试加固）。

---

## 1. 职责与边界（接哪些 R 决策，本部件负责/不负责什么）

### 1.1 一句话
把"在看最终 OOS 前，把一个**可证伪**的策略假设连同其经济机制、证伪条件、停机规则冻结成只读 + 时间戳 + 内容哈希的卡"，做成**仅在晋级到「可下注 confirmatory 结论」时才触发的结构性闸门**——探索阶段完全不挡（P2）。

### 1.2 接哪些 R 决策

| 决策 | 本部件如何接 |
|---|---|
| **P2**（决策 L86）假设卡不挡探索 | 核心约束。`layer=exploratory` 的卡/run 永远是 `draft`，无任何冻结门、无任何阻塞；只有用户**主动点"晋级 confirmatory"**才触发冻结流程。探索三必填可空。 |
| **R1 = C** honest-N 同一本账 | 冻结一张 confirmatory 卡 = R1 所说的"晋级到可下注结论时强制显式提交试验账本"。本部件**消费** honest-N 的当前计数（来自部件 03 账本），把它写进卡的 `multiplicity` 字段做**快照**，并在闸门里产出"N 偏高→门槛应抬高"的**软警告**。本部件**不**拥有 honest-N 计数器、**不**能改小它、**不**自己算 config_hash。 |
| **R8 / R1 同一本账** | `multiplicity` 只存"本卡所属 config_hash 簇 id（`config_hash_cluster`）+ 账本条目 ref（`ledger_ref`=部件03的 `entry_id`）"，**不重算 config_hash**（口径权威属部件03，见 §6 契约 C2 / `00` §1.2-A）。冻结一张 confirmatory 卡向账本写一条 `kind="card_freeze"` 条目 → "卡的数量本身计入 N"。 |
| **R3 = B / P1**（L32, L85）门槛档不强制锁定 | 卡里的 `significance_floor` 记录"谨慎/标准/宽松"哪一档 + 当时门槛值，但**可切换**；切换计入 honest-N、显示门槛抬高，**本部件不锁死**。卡只做"冻结时刻的快照留痕"，不阻止之后调档。 |
| **R5 = B** 守门器自身模型风险明示 | 卡的裁决面板必须打印"本闸门是启发式、非统计确定性；N 不可观测、DSR 是标度修正不是真理"的免责声明（§5 T12 裁决措辞）。 |
| **R6 = B** NIST AI RMF 锚 / 不宣称合规 | `economic_mechanism` = NIST MAP 阶段的意图/假设/约束留痕；`stop_rule` = 持续监控触发器。措辞用 NIST 语言，**不写 SR 11-7 合规字样**。 |
| **R7 = B** 诚实非组织独立 | 卡的 `review` 字段记录"异模型验证官 agent 的**一致性检查**结果"，字段名 `consistency_check`、`verdict_id`，**禁止**出现 "independent validation" / "组织独立" 字样。验证官裁决权威属部件12，本部件只**消费** `verdict_id` 并落 fixture（`00` §1.2-G）。 |
| **R11 = B** 重放读工件 | 卡冻结时若调用了 LLM（对话式填卡 / 验证官复核），其输出**落不可变 fixture**（`review.replay_ref`=部件01 `node_id`）；重放只读该 fixture，绝不重跑 LLM。`temp=0` 也不假装逐位可复现 → 走 durable（读缓存）非 reproducible（`00` §1.2-E）。 |
| **R12 = B** 留出集一次性消费 | 卡冻结时**绑定** frozen_oos 切片引用（`dataset_version` + slice 描述）；闸门检查 `consumed` 标志（触碰留痕，由部件 06 数据访问层维护）。本部件**不**自己实现访问控制——它只读取 `consumed` 证据 + 冻结约定，诚实标注"防自欺非防恶意"。 |
| **谱系归一**（`00` §1.2-D） | 卡每次状态跃迁（draft→frozen→deviated→retired）**必须作为 PROV Activity 发到部件03谱系总线**（freeze = `wasGeneratedBy`，产出冻结卡 Entity）。不允许卡状态只写 `hypothesis_cards.jsonl` 而不进谱系，否则审计轨迹缺一段。 |

### 1.3 负责 / 不负责

**负责：**
- `HypothesisCard` schema（三必填新字段 + 因果链 + 分层 + 状态机）。
- 假设卡的 append-only 落盘存储（复用 experiments 的 `_JsonlStore` 模式）。
- 冻结操作：content_hash 计算（canonical_json）、frozen_at 时间戳、只读强制（冻结后任何字段变更 → 必须 fork 新卡）。
- 可证伪性**启发式检测器**（套套逻辑 / 无前置 X / 无可观测阈值 / 纯噪声）—— 真检测逻辑，**非字数门**。
- `can_touch_final_oos(card)` 软闸门：返回 `allow + warnings + needs_human_review`，**永不**硬 fail（除"未冻结"/"探索层"/"OOS 已消费"这三个结构性 BLOCK）。
- confirmatory/exploratory 分层 + 探索→确认的"重开冻结卡 + 未污染数据"晋级路径。
- 每次状态跃迁向谱系总线发 PROV 事件。
- REST 端点（创建/冻结/查询/晋级/闸门检查/偏离）。

**不负责（依赖其它部件，仅消费其契约）：**
- `config_hash` 计算口径 + honest-N 计数器本体（**部件 03** 实验账本）。本部件只引簇 id。
- DSR/PBO/bootstrap 三角统计计算（部件 02 多证据三角守门器）。
- 验证官 agent 的异模型复核逻辑 + `verdict_id` 产出（**部件 12** 验证官）。
- frozen_oos 切片的真访问控制 / `consumed` 触碰留痕落盘 + `touched_versions` 写回（**部件 06** 数据访问层）。
- 谱系总线本体 / PROV 存储（**部件 03**）。本部件只发事件、不存谱系。
- 前端 RunDetailPage"收益概述"既有逻辑（**冻结，禁改**；本部件只能在别处新增页面/字段）。

---

## 2. 现有代码现状（file:line：有什么、缺什么、哪里是 dossier 点名的洞）

### 2.1 `app/backend/app/strategy_goal.py` — StrategyGoal 定义
- `class StrategyGoal(BaseModel)` 定义在 **strategy_goal.py:92-148**。字段全是"做什么策略"的工程参数（asset_class/objective/cost_model/evaluation_window…），到 **strategy_goal.py:107**（`description: str | None`）为止。
- **缺**：dossier §5.4 + 决策 L86 点名的三必填 — `economic_mechanism`（赌哪个风险溢价/行为偏差）、`falsification_condition`（若 X 则该效应应消失/反号）、`stop_rule`。当前 `StrategyGoal` **完全没有任何可证伪性字段**，没有"为什么应该有效"的留痕 → 这是 dossier §5.1「假设卡=强制门禁产物而非可选文档」的核心洞。
- `EvaluationWindow`（**strategy_goal.py:77-89**）是新 sub-model 的同构插入点（结束于 :89 的 `_check_range`）。
- `model_validator(mode="after") _consistency` 在 **strategy_goal.py:116-130** 已是字段级一致性校验的挂载点（A股杠杆 :120-121、cost_model 类型 :124-129）。新三必填的"可证伪性"**不挂这里强制**（保 P2），只在 `card.freeze()` 强制。
- `__all__` 在 **strategy_goal.py:209-222**。

### 2.2 `app/backend/app/experiments/store.py` — append-only 存储
- `_JsonlStore`（**store.py:80-103**）= 现成的 append-only + 行级容错（**store.py:98-102** 容忍崩溃半行）+ 线程锁（**store.py:86** `threading.Lock`，**store.py:89** `with self._lock` 串行化写）。**这是假设卡存储要复用的底座**，不要重造。
- `_now()`（**store.py:26-27**）= ISO8601 UTC；`_gen_id(prefix)`（**store.py:30-31**）= `{prefix}-{uuid4.hex[:12]}`。card_id 复用同约定。
- `Run`（**store.py:47-63**）有 `inputs: dict`（**store.py:55**）、`parent_run_id`/`forked_from`（**store.py:58-59**）—— run 已能挂任意 inputs 和血缘，但**没有任何 `hypothesis_card_id` / `layer` 字段** → run 与假设卡**当前无连接**，这是要补的接线洞。
- `RunStore.create_run`（**store.py:129-149**）/ `update_run`（**store.py:151-170**）是 run 落盘入口；`list_runs` 的 latest-wins 读取（**store.py:178-185**）是假设卡 store 要照抄的读取模式。
- **缺**：没有 `HypothesisCardStore`，没有 content_hash 概念，没有 frozen 状态机。

### 2.3 `app/backend/app/main.py` — 装配与端点
- store 实例化在 **main.py:90-92**（`EXPERIMENT_STORE` / `RUN_STORE` / `MODEL_REGISTRY`，root = `DATA_ROOT/"experiments"`）。假设卡 store 在同一处实例化。
- experiments 的 import 在 **main.py:52**。
- M12 实验端点块 **main.py:368-411**（`/api/experiments` :368、`/api/experiments/{id}/runs` :382、`/api/experiment_runs/{run_id}/lineage` :387、`/api/models*` :395-411），假设卡端点紧随其后新增，**不动**既有端点。
- `StrategyGoalSlotFiller` 在 **main.py:203** 实例化；tool `strategy_goal.create` 注册在 **main.py:220**（`runtime.register_tool("strategy_goal.create", ...)`）—— 对话式填卡的接入点。

### 2.4 已有的 dataset_version / 哈希约定（契约对齐用）
- **data_packages.py:70** 用 `hashlib.sha256(fp_blob.encode("utf-8")).hexdigest()[:16]` 算 `data_version` —— **全库 content_hash / frozen_oos.dataset_version 一律复用此 `sha256(...)[:16]` 约定**（`00` §1.2-B 钉成脊柱级不变量）。
- **run_detail_core.py:151-152**（`dataset_versions` / `universe_snapshot_id` 来自 manifest）、**:558-592**（按 `dataset_version`/`universe_snapshot_id` 过滤）、**schemas.py:80-81**（`dataset_version` / `universe_snapshot_id` 查询字段）—— 假设卡的 `frozen_oos` 复用这套既有标识符，**不新造**数据集版本概念。

---

## 3. 目标设计（schema/Pydantic 草图 + 模块布局 + 状态机）

### 3.1 模块布局
```
app/backend/app/hypothesis/
  __init__.py            # 导出 HypothesisCard, HypothesisCardStore, GateDecision, can_touch_final_oos
  card.py                # Pydantic schema + content_hash + 状态机方法
  falsifiability.py      # 可证伪性启发式检测器（套套逻辑/无前置X/无阈值/噪声）— 真检测，非字数门
  store.py               # HypothesisCardStore（复用 experiments._JsonlStore 模式）
  gate.py                # can_touch_final_oos 软闸门 + 三结构性 BLOCK
  lineage_hook.py        # 状态跃迁 → 向部件03谱系总线发 PROV 事件（依赖未就绪时 no-op + 留痕）
```
落盘：`DATA_ROOT/experiments/hypothesis_cards.jsonl`（与 runs/models 同目录，复用 append-only 模式）。

### 3.2 StrategyGoal 三必填（strategy_goal.py 增量，非可选文档）
> P2 关键：这三字段在 `layer=exploratory` 时**可空**（探索自由）；只有冻结 confirmatory 卡时才**强制非空 + 过可证伪性启发式**。所以**不**直接给 StrategyGoal 加必填，而是给一个**可空 sub-model**，由冻结闸门强制。

```python
# strategy_goal.py — 新增（插在 EvaluationWindow(:89) 之后、StrategyGoal(:92) 之前）
class EconomicMechanism(BaseModel):
    """因果优先的可证伪经济故事。dossier §5.4：引导写故事 + 人工审阅，
    不自动跑因果发现算法（PC/LiNGAM 在金融观察序列不可靠，dossier §7 降权）。"""
    risk_premium_or_bias: str = Field(..., min_length=12,
        description="赌哪个风险溢价 / 行为偏差（如 动量=处置效应+反应不足）")
    causal_chain: str = Field(..., min_length=12,
        description="一句话因果链：X 驱动 → Y 错价 → 我们收割 Z")
    confounder_concerns: list[str] = Field(default_factory=list,
        description="混杂/对撞担忧（可空，但空会在裁决里降信心）")

class FalsifiableTriplet(BaseModel):
    """冻结 confirmatory 卡时强制非空的三必填。"""
    economic_mechanism: EconomicMechanism
    falsification_condition: str = Field(..., min_length=12,
        description="若 X 则该效应应消失/反号（必须含一个可观测、独立于结果的判据）")
    stop_rule: str = Field(..., min_length=8,
        description="停机规则：达到什么条件就停（回撤/样本/时段/失效信号）")
```
- StrategyGoal **strategy_goal.py:107** 后新增：`falsifiable: FalsifiableTriplet | None = None`（默认 None → 探索不挡）。
- StrategyGoal 的 `_consistency`（**strategy_goal.py:116-130**）**不**强制 `falsifiable` 非空（保 P2）。强制只发生在 `card.freeze()`。

### 3.3 HypothesisCard schema（hypothesis/card.py）
```python
Layer  = Literal["exploratory", "secondary", "confirmatory"]
Status = Literal["draft", "frozen", "deviated", "retired"]

class FrozenOOS(BaseModel):
    dataset_version: str                # 复用 data_packages.py:70 的 sha256[:16] 约定
    universe_snapshot_id: str | None = None
    time_slice: str                     # e.g. "2024-01-01..2025-12-31"（时间后段）
    regime_warning: str | None = None   # §7.3：跨制度突变（2015/2016/2020）标注，由部件regime产
    consumed: bool = False              # 触碰留痕，由部件06维护；本部件只读

class MultiplicitySnapshot(BaseModel):
    """只存对部件03账本的引用，本部件不重算 config_hash（00 §1.2-A）。"""
    honest_n_at_freeze: int             # 冻结时刻从部件03账本读到的 N（快照，不可改小）
    config_hash_cluster: str            # 本卡所属 config_hash 簇 id（部件03 权威产，本部件不重算）
    n_cluster_note: str = ""            # 收益序列相关聚类口径说明（来自部件03）
    significance_floor: dict            # {tier:"标准", value:3.0, adjustable:True}（R3/P1，可切换）
    ledger_ref: str                     # 部件03账本条目 entry_id（kind="card_freeze"）

class ConsistencyReview(BaseModel):
    """R7：异模型一致性检查，禁称'组织独立'。verdict 权威属部件12（00 §1.2-G）。"""
    verdict_id: str                     # 部件12验证官产的主键，本部件只引用
    checker_model: str                  # 异模型标识
    verdict: Literal["consistent", "concern", "blocked"]
    notes: str = ""
    replay_ref: str | None = None       # R11：LLM 输出落 fixture（= 部件01 node_id），重放只读它

class HypothesisCard(BaseModel):
    card_id: str                        # "card-" + uuid4[:12]（同 store.py:30-31）
    strategy_goal_ref: str              # 指向 StrategyGoal（name 或 yaml hash）
    layer: Layer
    status: Status = "draft"
    created_at_utc: str                 # 同 store.py:26-27 _now()
    frozen_at_utc: str | None = None
    content_hash: str | None = None     # sha256(canonical_json(冻结内容))[:16]
    parent_card_id: str | None = None   # 探索→确认升级指向源卡
    touched_versions: list[str] = Field(default_factory=list)  # 本卡探索期碰过的 dataset_version（部件06写回）
    # 冻结时强制非空（confirmatory）：
    falsifiable: FalsifiableTriplet | None = None
    frozen_oos: FrozenOOS | None = None
    multiplicity: MultiplicitySnapshot | None = None
    review: ConsistencyReview | None = None
    deviations: list[dict] = Field(default_factory=list)  # {when,where,why,severity,auto_downgrade}
```

### 3.4 状态机
```
        晋级 confirmatory + 填三必填(过启发式) + 绑 OOS + 读N快照 + 验证官 verdict
draft ─────────────────────────────────────────────────────────────────► frozen
 │  (exploratory 永远停 draft，不挡)                                        │
 │                                                                          │ 偏离提交(带 severity)
 │  freeze 失败:三必填空 / 不可证伪 / N不可读 / verdict=blocked              ▼
 └──────► 仍 draft (返回可读 BLOCK 原因)                                  deviated ──► (auto downgrade: layer 降级标记)
                                                                            │
                                                stop_rule 触发 / 用户归档   ▼
                                                                         retired
```
- `frozen` 后字段只读：任何修改尝试 → 抛 `CardFrozenError`，必须 `fork_card()` 开新卡（`parent_card_id` 指回）。
- 探索→确认晋级：`promote_to_confirmatory(source_card, fresh_dataset_version)` —— 校验新 OOS 切片**未被 source 卡触碰过**（`fresh.dataset_version not in source.touched_versions`），否则 BLOCK"探索污染"。
- **每次状态跃迁** `lineage_hook.emit(card, transition)` 向部件03发 PROV 事件（`00` §1.2-D）；部件03 未就绪时 hook no-op 但本地留一条 `pending_lineage` 标记，防"审计轨迹缺一段"被静默吞掉。

### 3.5 冻结时 content_hash（防篡改证据，非防恶意 — R12）
```python
def compute_content_hash(card: HypothesisCard) -> str:
    payload = card.model_dump(mode="json", exclude={
        "content_hash", "frozen_at_utc", "status", "deviations", "review"})
    # 键序 + Unicode 归一化必须稳定（00 §2.2 变形探针）：
    canonical = json.dumps(_nfc_normalize(payload), sort_keys=True,
                           ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]  # 同 data_packages.py:70
```
- 重新计算与落盘值不符 → 篡改告警（但诚实标注：本地开放落盘，这是自欺检测非访问控制）。
- `_nfc_normalize` 对所有字符串值做 NFC 归一，保证 NFC/NFD 同内容得同 hash（防跨平台假阳性，`00` §2.2）。

### 3.6 软闸门（gate.py，伪代码 — 永不伪装统计确定性）
```python
def can_touch_final_oos(card, honest_n_now) -> GateDecision:
    # —— 三个结构性 BLOCK（硬，因为是"诚信底线/防灾难"，不是研究旋钮）——
    if card.layer == "exploratory":
        return BLOCK("探索层不得触碰最终 OOS；先晋级 confirmatory 重开冻结卡")
    if card.status != "frozen":
        return BLOCK("假设卡未冻结（缺只读+时间戳+哈希）")
    if card.frozen_oos and card.frozen_oos.consumed:
        return BLOCK("该 OOS 切片已被消费一次（R12 一次性消费，触碰留痕）")
    # —— 软护栏：产风险提示 + 要人工裁决，不自动 pass/fail ——
    warnings = []
    if honest_n_now > card.multiplicity.honest_n_at_freeze:
        warnings.append(f"冻结后 N 又涨了（{card.multiplicity.honest_n_at_freeze}→{honest_n_now}），"
                        "卡层面 garden-of-forking-paths 风险，门槛应人工抬高")
    if not card.falsifiable.economic_mechanism.confounder_concerns:
        warnings.append("未声明混杂担忧，因果信心降级")
    if card.review and card.review.verdict == "concern":
        warnings.append("异模型一致性检查报 concern（非组织独立验证，仅一致性检查）")
    if card.frozen_oos and card.frozen_oos.regime_warning:
        warnings.append(f"frozen_oos {card.frozen_oos.regime_warning}（A股制度突变，代表性存疑）")
    return GateDecision(allow=True, warnings=warnings, needs_human_review=True,
        disclaimer="本闸门为启发式，非统计确定性；N 不可观测，DSR 是标度修正非真理（R5）。"
                   "本裁决只陈述证据充分/不足 + 适用域 + 未验证项，不宣称可信/安全。")
```

### 3.7 可证伪性启发式（falsifiability.py — 真检测，非字数门）
> `00` §2.1 对 T1 点名："若启发式只查 min_length≥12，套套逻辑字符串会漏过、退化为字数门"。故启发式必须做**真语义检测**，每条规则各配 fixture：

```python
def assess_falsifiability(triplet: FalsifiableTriplet) -> FalsifiabilityVerdict:
    flags = []
    fc = triplet.falsification_condition
    # 规则1 套套逻辑：判据等价于结果本身（循环论证）
    if _refers_only_to_own_pnl(fc):      # "如果不赚钱就说明假设错了"类
        flags.append(("tautology", "证伪判据等价于策略结果本身，无独立可观测变量"))
    # 规则2 无前置 X：falsification 缺"若 X 则…"的可观测前置条件
    if not _has_antecedent_condition(fc):
        flags.append(("no_antecedent", "缺可观测前置条件 X（'若X则效应消失'的X缺失）"))
    # 规则3 无可观测阈值：缺数值/方向判据（消失/反号/低于阈值）
    if not _has_observable_threshold(fc):
        flags.append(("no_threshold", "缺可观测阈值或方向（消失/反号/<阈值）"))
    # 规则4 噪声：机制是垃圾随机文本（与 risk_premium 无语义连贯）
    if _is_incoherent_noise(triplet):
        flags.append(("noise", "经济机制与证伪条件语义不连贯，疑似随机文本"))
    confidence = "high" if not flags else ("low" if len(flags) >= 2 else "medium")
    return FalsifiabilityVerdict(flags=flags, confidence=confidence)
```
- 裁决策略（dossier §8.7 / §7.2）：`confidence="low"` → **不静默冻结**；放行须 `needs_human_review=True` + 触发验证官 agent 二次挑战。**绝不**因字数达标就判 high。

---

## 4. 代码接线点（逐条 file:line）

> 全部基于实际打开核实的行号（见 §2）。不改 RunDetailPage 既有逻辑。

1. **strategy_goal.py:89 之后、:92 之前** — 新增 `EconomicMechanism`、`FalsifiableTriplet` 两个 BaseModel（§3.2）。紧跟 `EvaluationWindow`（结束于 :89 的 `_check_range`）之后，与现有 sub-model 同构。

2. **strategy_goal.py:107**（`description: str | None = None`）后 — 新增一行字段：
   `falsifiable: FalsifiableTriplet | None = None`。默认 None 保证 P2 探索不挡。

3. **strategy_goal.py:116-130**（`_consistency` validator）— **不改其强制逻辑**（不把 falsifiable 设必填，保 P2）。仅可选地在末尾加一条**防呆软提示**：若 `execution_mode in {"paper","live_crypto"}` 且 `falsifiable is None` → 不报错，仅日志 warning（"执行侧要冻结卡是闸门的事，不是 schema 的事"）。

4. **strategy_goal.py:209-222**（`__all__`）— 追加 `"EconomicMechanism"`, `"FalsifiableTriplet"`。

5. **新文件 `app/backend/app/hypothesis/card.py`** — `HypothesisCard` schema + 状态机方法（`freeze` / `fork_card` / `promote_to_confirmatory`）+ `compute_content_hash`（复用 data_packages.py:70 的 sha256[:16]，含 NFC 归一）。

6. **新文件 `app/backend/app/hypothesis/falsifiability.py`** — `assess_falsifiability` + 四规则检测器（§3.7）。

7. **新文件 `app/backend/app/hypothesis/store.py`** — `HypothesisCardStore`，**复用 `experiments/store.py:80-103` 的 `_JsonlStore`**（`from ..experiments.store import _JsonlStore`，或先把 `_JsonlStore` 提升为公共 util，见 §7.5）。落盘 `hypothesis_cards.jsonl`，latest-wins 读取同 `RunStore.list_runs`（store.py:178-185）。

8. **新文件 `app/backend/app/hypothesis/gate.py`** — `can_touch_final_oos` + `GateDecision`（§3.6）。

9. **新文件 `app/backend/app/hypothesis/lineage_hook.py`** — `emit(card, transition)` 向部件03谱系总线发 PROV 事件；依赖未就绪时 no-op + 写 `pending_lineage` 标记（`00` §1.2-D）。

10. **新文件 `app/backend/app/hypothesis/__init__.py`** — 导出公共符号。

11. **store.py:47-59**（`Run` dataclass）— 新增两个可空字段：`hypothesis_card_id: str | None = None`、`layer: str | None = None`（默认 None → 旧 run 兼容，探索 run 不带卡）。这是 run↔卡连接洞的补丁。

12. **store.py:129-149**（`RunStore.create_run`）— 签名加 `hypothesis_card_id: str | None = None, layer: str | None = None`，透传进 `Run(...)`（:137-147）。**不**在 store 层强制校验（保数据层纯净）。

13. **main.py:52**（import 行旁）— 新增 `from .hypothesis import HypothesisCard, HypothesisCardStore, can_touch_final_oos`。

14. **main.py:90-92**（store 实例化块）— 新增 `HYPOTHESIS_STORE = HypothesisCardStore(DATA_ROOT / "experiments")`。

15. **main.py:411 之后**（M12 端点块尾，紧接 `promote_model` 端点）— 新增端点（不动既有）：
    - `POST /api/hypothesis_cards` 创建 draft 卡
    - `POST /api/hypothesis_cards/{card_id}/freeze` 冻结（强制三必填非空 + 过启发式 + 绑 OOS + 读 honest-N 快照 + 触发验证官一致性检查并落 fixture + 发 PROV 事件 + 写 `kind="card_freeze"` 账本条目）。带 `request_idempotency_key`（HTTP 层去重，**非**交易幂等键，`00` §1.2-F）。
    - `POST /api/hypothesis_cards/{card_id}/promote` 探索→确认晋级（校验未污染数据）
    - `GET /api/hypothesis_cards/{card_id}/gate` 调 `can_touch_final_oos`，返回 GateDecision
    - `POST /api/hypothesis_cards/{card_id}/deviation` 提交偏离（自动降级标记 + 发 PROV 事件）

16. **confirmatory backtest 创建路径**（调用 `RUN_STORE.create_run` 处）— 当 run 的 `layer="confirmatory"` 且 `execution_mode in {paper,live_crypto}` 时，先调 `can_touch_final_oos`；返回结构性 BLOCK 则 `HTTPException(409)`。**探索 run 跳过此检查**（P2）。此为闸门唯一硬接入点，**不接到 RunDetailPage**。

17. **main.py:220**（`runtime.register_tool("strategy_goal.create", ...)`）旁 — 可新增 tool `hypothesis_card.draft` 让 Agent 对话式填卡（落 draft，不自动冻结，保 P2）。

18. **前端**（如需）— 新增独立 `HypothesisCardPage` / 在创建策略向导加"晋级 confirmatory"步骤。**禁止**改 `RunDetailPage` 收益概述既有逻辑（已冻结）；最多在 RunDetail 只读展示一个"关联假设卡"链接字段（属"加字段"允许范围）。

---

## 5. 对抗式测试规约（按 TEST_STANDARD：种已知坏→门必抓）

> 本节是验收标准，不是覆盖率清单。文件：`app/backend/tests/test_hypothesis_card.py`（+ `test_hypothesis_card_integration.py` 集成项）。
> **系统性诚实边界**（`00` §2.1 总评）：T3/T5/T9/T13 的真实有效性依赖**尚未存在的部件03/06/12**。当前 mock 下绿只证明"mock 的诚实"。**凡标 [集成必补] 者，被依赖部件落地后必须补真系统集成测试**，否则视为测试剧场不予验收。

### ① 种已知坏 → 门必须抓

**T1 · 不可证伪条件探针（种已知坏：套套逻辑伪装可证伪）。**
- 种四个 fixture，各打中 §3.7 一条规则：
  (a) 套套逻辑 `"如果策略不赚钱就说明假设错了"`（判据≡结果）；
  (b) 无前置 X `"该效应会一直有效"`（缺"若X"）；
  (c) 无阈值 `"若市场变化则效应改变"`（缺可观测方向/阈值）；
  (d) **字数达标的套套逻辑**（≥12 字但仍循环论证）—— 专门验证**没退化成字数门**。
- 断言：(a)(b)(c)(d) 在 confirmatory 层 `freeze()` 全部判 `confidence in {low,medium}` 且**不静默冻结成功**（needs_human_review=True）。门坏（启发式退化为 min_length）→ (d) 会漏过 → fail。

**T2 · 空机制探针（种已知坏：三必填留空当文档）。**
- 种：confirmatory 卡 `economic_mechanism / falsification_condition / stop_rule` 任一为空白串/全空格。
- 断言：`freeze()` BLOCK，返回**可读**原因（dossier §7「仅时间戳字段空泛=装样子」）。**反向断言**：`layer=exploratory` 同样留空 → 必须放行（P2 不挡探索的反向断言，防误杀探索）。门坏（误卡探索 或 放过空 confirmatory）两向都 fail。

**T3 · OOS 泄露探针（种已知坏：冻结卡绑了已被探索碰过的数据）。**
- 种：`promote_to_confirmatory(source_card, fresh_dataset_version=X)`，其中 `X in source_card.touched_versions`。
- 断言：晋级 BLOCK"探索污染：新 OOS 切片已被源卡触碰"。再种 `frozen_oos.consumed=True` 后调 `can_touch_final_oos` → BLOCK"已消费"。一次性消费门必须抓住二次触碰。
- **[集成必补]**：`touched_versions` 写回方是部件06。补"真实部件06 把探索碰过的 dataset_version 写回 + 二次访问"的端到端测试，否则 mock 里永远能抓、真环境抓不到（`00` §2.1 T3 隐患）。

**T4 · 探索层越权探针（种已知坏：exploratory 卡直接摸 OOS）。**
- 种：`layer=exploratory` 的卡调 `can_touch_final_oos`。
- 断言：BLOCK"探索层不得直接触碰最终 OOS"。**这是 P2 硬边界**——探索自由 ≠ 探索能下注。

**T5 · honest-N 不可改小探针（种已知坏：尝试把 N 写小绕门）。**
- 种：(a) 冻结后直接改 `multiplicity.honest_n_at_freeze` 调小；(b) 冻结时调用方传入 < 账本实际值的 N。
- 断言：`freeze()` 从部件03账本**实读** N（**不接受**调用方传入的 N）；(a) 因 `frozen` 只读被 `CardFrozenError` 拒绝。（决策 0.1「不让你藏试验」硬边界。）
- **[集成必补]**：部件03落地后补"真账本 N=5、调用方谎报 N=2、freeze 仍按 5 算"的集成测试，否则只测了 mock 的诚实（`00` §2.1 T5）。

**T5b · 噪声探针（`00` §2.2 点名缺失，本版补）。**
- 种：一张机制是**垃圾随机文本**、但字数和格式都达标的 confirmatory 卡（dossier §8.7「Agent 幻觉出貌似严谨实则不可证伪」）。
- 断言：`assess_falsifiability` 给 `confidence=low`（规则4 noise 命中）**或**验证官报 `concern`；绝不判 high。门坏（噪声蒙混过关）→ fail。这是 T1 启发式的噪声压力测试兜底。

### ② 变形测试（不变量）

**T6 · content_hash 篡改不变量。**
- 变形：冻结后逐字节改卡任一受哈希字段（如 falsification_condition 改一字）。
- 断言：重算 content_hash ≠ 落盘值 → 篡改告警。反向：只改 `deviations`/`review`（exclude 字段）→ hash 不变（证明 exclude 集正确）。门坏（exclude 集算错/漏哈希关键字段）→ 某一向 fail。

**T6b · canonical_json 键序 + Unicode 归一不变量（`00` §2.2 补）。**
- 变形：同内容、不同 dict 插入顺序 → 应同 hash；同字符串 NFC vs NFD 表示 → 应同 hash。
- 断言：两种变形 hash 相等。门坏（键序敏感/未做 NFC 归一）→ 跨平台假阳性篡改告警 → fail。

**T7 · 冻结只读不变量。**
- 变形：对 `status=frozen` 卡的任意核心字段 setattr。
- 断言：抛 `CardFrozenError`；要改必须 `fork_card()` 得新 `card_id` 且 `parent_card_id` 指回原卡。原卡 jsonl 行不被覆写（append-only 不变量，store.py:88-90）。

**T8 · 晋级谱系不变量。**
- 变形：`exploratory → promote → confirmatory` 链。
- 断言：confirmatory 卡 `parent_card_id == 源探索卡 id`；两卡共存于 jsonl（探索卡不被删，dossier §5.3「降级而非禁止」）；晋级时向谱系总线发了一条 PROV 事件（`00` §1.2-D，断言 `lineage_hook.emit` 被调用 / pending 标记落地）。

### ③ 交叉验证

**T9 · 验证官一致性检查对账（异模型，非组织独立）。**
- 种：让独立验证官 agent（异模型/异种子）对同一张卡复核；本部件落 `review.verdict` + `verdict_id` + `replay_ref`。
- 断言：
  - `verdict=blocked` → `freeze()` BLOCK；`verdict=concern` → **允许冻结但闸门带 warning**。
  - 措辞：`review` 字段文案含 `consistency_check`，**不含** `independent`/`组织独立`（R7 / `00` §1.2-G）。
  - 重放（R11）：第二次跑读 `replay_ref` fixture，**不重跑 LLM**，输出逐字节相同。门坏（concern 当 pass / 措辞漏"组织独立" / 重放重跑 LLM 漂移）→ fail。
- **[集成必补]**：部件12落地后，`verdict_id` 必须可复算（每个 BLOCK 带可复算依据），补真验证官集成测试。

### ④ 幂等 / 恢复

**T10 · 冻结幂等。**
- 种：同一 `card_id` 重复 `POST /freeze`（同 `request_idempotency_key`，**非**交易键，`00` §1.2-F）。
- 断言：返回**已冻结的存量卡**（同 content_hash、同 frozen_at），**不**产生第二条冻结记录、**不**重跑验证官（防烧钱）、**不**重复写账本 `card_freeze` 条目。门坏（每次 freeze 都新建/重跑/重复计入 N）→ fail。

**T10b · 并发双写竞态（`00` §2.2 补）。**
- 种：两个请求同时对同 `card_id` 调 freeze。
- 断言：只产一条冻结记录，靠 `_JsonlStore` 的 `threading.Lock`（store.py:86）兜住；honest-N 的 `card_freeze` 条目只 +1。门坏（无锁/双计）→ fail。

**T11 · 崩溃恢复。**
- 种：写 jsonl 中途崩溃留半行（复用 store.py:98-102 容错场景）。
- 断言：`HypothesisCardStore` 读取跳过坏行、返回最近完整冻结卡；闸门基于该卡正常工作，不因半行整库不可读。

### ⑤ 裁决措辞

**T12 · 措辞守门（中英双语 + 扩展黑名单，`00` §2.1 加固）。**
- 断言：`GateDecision.disclaimer` 与所有 warning 文案**只**出现"证据充分/不足 + 适用域 + 未验证项"句式；**断言不存在**子串黑名单：中文 `可信`/`安全`/`保证正确`/`统计显著确定`/`已确认`/`通过验证`/`有效`（绝对化语境）；英文 `trustworthy`/`safe`/`proven`/`guaranteed`/`validated`/`significant`（绝对化语境）。`can_touch_final_oos` 返回必带 `needs_human_review=True`（永不自动放行下注）。门坏（文案漏绝对化词/自动放行）→ fail。

### ⑥ 经验网（回测↔paper 对账）

**T13 · 阶梯一致性（分资产分支，`00` §2.1 加固）。**
- 种：同一 confirmatory 卡，记录各段 run 的 `hypothesis_card_id`。
  - **crypto 分支**：paper → 小额 live 两段。
  - **A股分支**：**只有回测↔paper 两段**（A股不存在 live，MEMORY 项目范围）—— 必须单独断言"无 live 段、不在 live 路径空跑显绿"。
- 断言：同卡各段 run 的 `content_hash` 关联同一冻结卡（卡未被偷改）；若 paper 与回测核心指标背离超阈值 → 闸门产 warning"回测↔paper 对不上，指向 bug 或机制失效"（dossier §8.5 再训练冲突早警）。门坏（背离不告警 / A股走了 live 分支）→ fail。

---

## 6. 与其他脊柱部件的契约（共享 schema 字段约定）

> 字段口径以 `00-contracts-and-coherence.md` §1.1 统一契约表为准；本节列本部件的产出/消费侧。

**本部件产出（供他人消费）：**
- `card_id: str` —— 前缀 `card-` + uuid4[:12]（同 store.py:30-31 `_gen_id` 约定）。
- `content_hash: str` —— `sha256(canonical_json)[:16]`（**全库统一**，同 data_packages.py:70；`00` §1.2-B 脊柱级不变量，谱系不得用全长）。
- `frozen_at_utc: str` —— ISO8601 UTC（同 store.py:26-27 `_now()`）。
- `layer: Literal["exploratory","secondary","confirmatory"]` —— run 与卡共用。
- `GateDecision{allow, warnings, needs_human_review, disclaimer}` —— 供执行侧（部件实盘门）查询。
- 卡状态跃迁 PROV 事件 —— 发到部件03谱系总线（`freeze` = `wasGeneratedBy`，产冻结卡 Entity；`00` §1.2-D）。
- `card_freeze` 账本条目 —— 写部件03账本，`kind="card_freeze"`，让"卡的数量本身计入 N"（`00` §1.2-H / §7.1）。

**本部件消费（依赖他人产出）：**
- `honest_n_now: int` + `config_hash_cluster` + `n_cluster_note` + `ledger_ref`（=`entry_id`）← **部件 03 实验账本**（R1/R8 同一本账，config_hash 簇 + 收益序列相关聚类）。**只读、不可改小、不重算 config_hash**（`00` §1.2-A）。
- `dataset_version: str` / `universe_snapshot_id` ← **部件 06 数据访问层** + 既有 data_packages.py:70 / run_detail_core.py:151-152。frozen_oos 引用它。
- `consumed: bool` + `touched_versions: list[str]`（OOS 触碰留痕 / 探索碰过的数据版本）← **部件 06 数据访问层**。本部件只读。
- `ConsistencyReview{verdict_id, checker_model, verdict, replay_ref}` ← **部件 12 验证官 agent**（异模型，`verdict_id` 权威产方）。`replay_ref` 指向 **部件 11/01 重放** 的不可变 fixture（= `node_id`，`00` §1.2-E）。
- `request_idempotency_key` ← 冻结/晋级端点 HTTP 层去重键（**与交易副作用幂等键 `effect_idempotency_key` 严格区分**，`00` §1.2-F；MEMORY M17 幂等绕过同类雷区）。

**与 Run 的连接（store.py 改动）：**
- `Run.hypothesis_card_id: str | None` + `Run.layer: str | None` —— confirmatory run 必带 card_id，exploratory run 可不带（P2）。

---

## 7. 开放问题 / 风险（落地前必答）

1. **卡层面 garden-of-forking-paths 递归（dossier §8.1）。** 用户反复重开冻结卡直到某张在 OOS 通过——卡的数量本身需计入 honest-N。**已定方向**：冻结一张 confirmatory 卡 → 向部件03写一条 `kind="card_freeze"` 账本条目（`00` §1.2-H），同 `strategy_goal_ref` 下的卡冻结次数单独成簇显示。**落地前必答**：`card_freeze` 条目是否也参与 `config_hash` 聚类、还是独立计数？建议独立计数但在裁决面板并列展示，否则 N 被系统性低估。

2. **可证伪性启发式的误判率（dossier §8.7 / `00` §2.1 T1）。** §3.7 四规则靠语义检测，LLM 仍可能幻觉出"貌似严谨实则不可证伪"的条件。**必答**：`confidence=low` 时放行带标注还是 BLOCK？建议放行 + 强制人工确认（R5 明示启发式非确定性）+ 验证官 agent 二次挑战；T1+T5b 把这条钉成"门必抓"。

3. **A股 regime 断裂使 frozen_oos 脆弱（dossier §8.3）。** 冻结"时间后段"OOS 在 A股遇 2015/2016/2020 制度突变会失代表性。**已埋字段** `FrozenOOS.regime_warning`；**必答**：该 warning 由谁填（接部件 regime 检测）、是否升级为结构性 BLOCK 还是停在软 warning？建议停软 warning（保 P2 不过度刚性），但裁决面板高亮。

4. **"OOS 只碰一次"与持续再训练冲突（dossier §8.5 范式错配）。** v3 训练平台 walk-forward 必然反复消费近段数据。**必答**：confirmatory 卡的 frozen_oos 一次性消费如何与运营期滚动再训练共存？建议明确区分"晋级确认用的一次性 OOS"（冻结后只碰一次出裁决）与"运营期滚动验证集"（属部件04 之外），文档钉死二者不是同一切片，避免把元科学一次性范式生搬运营系统。

5. **`_JsonlStore` 复用方式。** 接线点 7 建议 `from ..experiments.store import _JsonlStore`（下划线私有）。**必答**：是否把 `_JsonlStore` 提升为 `app/backend/app/_jsonl.py` 公共 util？建议提升（避免跨包引私有符号），但需确认不破坏 761+ 既有测试（MEMORY 当前 761 绿）。

6. **被依赖部件未就绪 → 测试剧场风险（`00` §2.1 总评，最高系统性风险）。** T3/T5/T9/T13 当前只能在 mock 部件03/06/12 下绿。**必答 + 强制**：这四条标 `[集成必补]`，被依赖部件落地后必须补真系统集成测试；在此之前，CI 报告须显式标注"这些门当前在 mock 下验证、真系统未验证"，**不得渲染成"已验证安全"**（呼应 T12 措辞守门）。

7. **谱系事件的"漏发"如何抓（`00` §1.2-D）。** 卡状态跃迁必须发 PROV 事件，但 hook 在部件03未就绪时 no-op。**必答**：no-op 期间 `pending_lineage` 标记如何对账补发？建议部件03上线时做一次性回填 + 加"谱系覆盖盲区告警"探针（`00` §2.3 部件03 清单②），防"审计轨迹缺一段"被静默吞掉。
