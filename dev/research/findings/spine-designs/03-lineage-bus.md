# 03 · 谱系/溯源总线(PROV) + run 快照可复现强制属性
> 脊柱 build-ready 设计 · 接 R1–R29 决策 · 含 file:line 接线 + 对抗式测试 · Opus 4.8
> 设计日期：2026-06-16 · dossier 背书：`research/03-prov-lineage-bus.md`（§7 对抗核查已读、§5 乐观推荐按 §7 打折）
> 跨部件契约锚：`spine/00-contracts-and-coherence.md`（本部件被 00 §标注②列为「第 0 层地基·并列最先」，并被指定为 `config_hash` / `ledger_entry` / `event` 汇聚 / 谱系 Entity `content_hash` 的**权威产方**）

---

## 1. 职责与边界（接哪些 R 决策，本部件负责/不负责什么）

### 1.1 一句话职责
把 prompt / response / 工具调用 / 产出 / dataset_version / 下游指标接成一条**可审计、可重现、可归因**的 PROV DAG，并在每个 `*Run` 节点上**强制**采集「冷启动重现」所需的全部属性（dataset_version+content_hash / split / 预处理 / seed / env 指纹 / git_sha），缺任一项即把该 run 打上 `reproducible=False` 标记「DAG 完整但不可重现」。本部件同时是 honest-N 试验账本（R8/R1 同一本账）与全脊柱事件汇聚点（00 §1.2-D）的**承载存储**。

### 1.2 定位红线（dossier §1 / §7 核心、必须刻进实现）
- **谱系 ≠ 信任。** 谱系只回答「怎么来的 / 能否重现 / 错在哪一步」。信任由**独立校准证据**（OOS/CSCV/PBO/持续性能反馈/regime 健壮性，部件 02/12/14/16）承载。任何 UI / 裁决文案**绝不**把「DAG 完整」渲染成「结论可信」（dossier §7 已确证反证：Patterns 2022 / CHI 2023，透明度过载诱发过度信任）。→ 见 §5-T8、§5-T12。
- **谱系是必要不充分。** 有 dataset_version 不等于能重现（约 14% 可精确重现，Semmelrock 2025）。所以强制属性是**门**，不是装饰。→ 见 §5-T4。
- **生成 ≠ 验证。** 本部件只**记录**事实，不下信任结论。一致性裁决由部件 12 验证官（异模型/异种子/异切片）产 `verdict_id`，本部件只把它作为 Entity 引用挂上 DAG（R7：诚实标注「非组织独立」，措辞用 `consistency_check`）。

### 1.3 接的 R 决策
| R 决策 | 本部件如何落地 |
|---|---|
| **R8/R1 同一本账（honest-N）** | `config_hash = sha256(canonical_json(因子AST+params+universe+dataset_version+freq+label))[:16]`，append-only `ledger.jsonl`。遍历命中即返缓存**不重跑**（省 compute），同时每个 distinct config 计入 honest-N。**memoize 与 honest-N 是同一本账。** → §3.4 |
| **R1=C honest-N** | 探索自由（`stage="exploratory"` 只计数不挡）；晋级 confirmatory 时由部件 04 读 `honest_n_at_freeze`（本部件产、**不可手动改小**，硬）。 |
| **R11 重放读工件** | LLM 节点输出落**不可变 fixture**（record/replay），重放**只读已落盘工件、绝不重跑 LLM**；temp=0 也不保证逐位可复现 → 用 durable（复用日志）而非 reproducible（重算）语义。→ §3.5、§5-T6 |
| **R12 留出集隔离=约定非强制** | dataset_version 内容不可变靠既有 `dataset_hash.py` 防篡改证据；本部件记录 `consumed` 触碰留痕。诚实标注「防自欺非防恶意」（本地开放落盘无真访问控制边界）。一次性消费的**硬闸**在部件 06，本部件只**记录**触碰事件。 |
| **R7 诚实非组织独立** | 验证记录字段名强制 `consistency_check`，禁出现 `independent validation` / 「组织独立」。 |
| **R6 监管锚 NIST** | 防篡改/留存做工程稳健性预留，**不宣称合规**（dossier §7：SR26-2 把 agentic 划出范围；EU AI Act tamper-evident 是分析师 gloss 非法条 MUST）。 |
| **P2 假设卡不挡探索** | 谱系**全程发射**（探索也记），但 `stage` 区分 exploratory/confirmatory；探索不冻结、不挡。 |

### 1.4 本部件**不负责**
- 不算 DSR/PBO/CSCV 数值（部件 02/14/16）；只把它们作为下游 `MetricSet` Entity 挂 DAG。
- 不产信任裁决（部件 12）；只引用 `verdict_id`。
- 不做硬访问控制 / 一次性消费的**拒绝**（部件 06）；只记录 `consumed` 触碰事件。
- 不做样本级/列级细粒度追踪（dossier §7 pitfall：对单用户中低频是 gold-plating）。粒度锁定决策关键节点：意图→假设→因子→数据集→训练/回测→护栏→产出。
- 不引 Redis/Kafka/对象存储 broker（dossier §8 开放问题3：单机单用户过重）。落地为**本地 JSONL append-only + sha256 链**，复用既有 `_JsonlStore`。

---

## 2. 现有代码现状（file:line：有什么、缺什么、哪里是 dossier 点名的洞）

### 2.1 有什么（可复用的地基）
- `app/backend/app/experiments/store.py`（259 行）
  - `Run` dataclass：`store.py:47-63`。现有 lineage 字段仅 `parent_run_id`（:58）、`forked_from`（:59）。`inputs/metrics/artifact_paths/tags`（:54-57）。
  - `RunStore.create_run`：`store.py:129-149`；`update_run`：`store.py:151-170`；`get_run`：`store.py:172-176`；`list_runs`：`store.py:178-185`；`lineage`：`store.py:187-201`（只回溯 parent/fork 链，**不是 PROV DAG**）。
  - `_JsonlStore`：`store.py:80-103`，含崩溃容错跳坏行（:98-102）+ `threading.Lock`（:86）。append-only 语义现成。
  - `ModelRegistry.register_version`：`store.py:209-230`（已有 `source_run_id` 回链，:214/:227）。
  - `__all__`：`store.py:251-259`。
- `app/backend/app/data_hash/dataset_hash.py`（223 行）
  - `DatasetManifest` / `FileEntry`：`dataset_hash.py:30-67`，**per-file sha256**（:36/:123）。
  - `create_manifest`：`dataset_hash.py:95-132`；`write_manifest`（含同 version 内容不可变防覆盖 raise）：`dataset_hash.py:135-159`；`verify_manifest`（重算 hash 对账）：`dataset_hash.py:162-184`。
  - `FactorBinding`（`factor_id+dataset_id+dataset_version` 三元组、`composite_key`）：`dataset_hash.py:192-213`。
- `app/backend/app/data_packages.py:70`：`data_version = sha256(fp_blob)[:16]` —— **全库 16 位截断约定的权威来源**（00 §1.2-B 钉死的不变量）。
- 调用现场（自动埋点要接的真实点）：
  - `app/backend/app/training/service.py:228-233`（`create_run`，训练 run 起点）、`:257-263`（`update_run` succeeded + metrics）、`:264-271`（`register_version`）、`:280-284`（失败分支 `update_run failed`）。
  - `app/backend/app/main.py:90-92`（三 store 实例化，root=`DATA_ROOT/"experiments"`）、`:387-392`（`/api/experiment_runs/{run_id}/lineage` 端点）。
- DL/ML seed 现状（要被快照采集）：`app/models/dl/trainer.py:103-104`（`torch.manual_seed(seed)` / `np.random.seed(seed)`）；`app/models/training.py:135`（`random_seed: 42`）；`app/strategy_goal.py:83`（`EvaluationWindow.random_seed=42`）。

### 2.2 缺什么（dossier 点名的洞）
1. **`Run` 没有可重现强制属性。** `store.py:48-59` 整个 `Run` 没有 dataset_version / content_hash / split / preprocessing / seed / env_fingerprint / git_sha 字段。dossier §5.4「必要不充分」直接落空——现有 run **DAG 上的祖先链能查，但任何一条都不可冷启动重现**。
2. **`lineage()` 不是 PROV DAG，只是单链回溯。** `store.py:187-201` 只沿 `parent_run_id or forked_from` 走单链，无 `used`（消费的输入 Entity）/ `wasGeneratedBy`（产出）/ `wasInformedBy`（上游决策）三类 PROV 关系，无法回答「这个回测净值用了哪个 dataset_version + 哪段 prompt + 哪个模型工件」。
3. **无 config_hash / 试验账本。** 全库 grep `config_hash` / `honest_n` / `ledger` **零命中**（已核）。R8/R1「同一本账」无承载——遍历不去重、honest-N 无处计、memoize 不存在。
4. **无自动埋点 + 无覆盖盲区告警。** 训练 run 是**手写** `create_run`（service.py:228），回测桥 `backtest_bridge.py:82-170` **完全不进谱系**（`backtest_trained_model` 返 dict 就走，无 run 注册）。dossier §5.7「血缘腐烂」+「未覆盖路径必须告警」无任何实现 → 谱系会有大片审计盲区却自以为全覆盖。
5. **LLM prompt/response 不落不可变 fixture。** R11 重放无承载；当前 LLM 调用不进谱系、不可 record/replay。
6. **谱系事件未汇聚。** 00 §1.2-D 要求卡状态机/审批/run 生命周期都向谱系总线发 PROV Activity，当前各写各的 jsonl，无统一 `event` 汇聚点。

---

## 3. 目标设计（schema / Pydantic 草图 + 模块布局 + 状态机）

### 3.1 模块布局（新建 `app/backend/app/lineage/`，与 `experiments/` 平级、不推翻它）
```
app/backend/app/lineage/
  __init__.py            # 导出公共面
  prov.py                # PROV 语义层：Entity/Activity/Agent + 关系 + ProvStore(append-only sha256 链)
  snapshot.py            # RunSnapshot 强制属性 + reproducibility_gate() + env/git/seed 采集
  config_hash.py         # config_hash 权威算法（00 §1.2-A 指定本部件拥有）
  ledger.py              # 试验账本 LedgerEntry + honest-N 计数 + memoize 缓存（R8/R1 同一本账）
  emit.py                # 自动埋点：@provenance_activity 装饰器 + record_llm() fixture + coverage 监控
  bus.py                 # LineageBus 门面：唯一事件汇聚入口（00 §1.2-D），其它部件只调它
```
> 设计原则：**扩展不破坏。** 既有 `RunStore` 保留；新 `Run` 字段全部带默认值（向后兼容旧 jsonl 行，`store.py:99` 的 `Run(**row)` 不会因缺字段炸）。谱系 DAG 与试验账本是**新增侧车**，通过 `bus.py` 与 `RunStore` 协同。

### 3.2 PROV 语义层（`prov.py`，对齐 W3C PROV-O Entity/Activity/Agent）
```python
ProvKind = Literal["Entity", "Activity", "Agent"]
ProvRel  = Literal["used", "wasGeneratedBy", "wasInformedBy",
                   "wasDerivedFrom", "wasAssociatedWith"]

class ProvNode(BaseModel):
    node_id: str            # 内容寻址身份；与内核 node_id 同哈希族 sha256[:16]（00 §1.2-E）
    kind: ProvKind
    type: str               # Activity: AgentStep|ToolCall|ModelInvocation|BacktestRun|TrainRun
                            # Entity:   Prompt|ResponseData|DatasetVersion|ModelArtifact|MetricSet
                            # Agent:    AIAgent|HumanUser
    content_hash: str       # sha256(canonical_json(payload))[:16]  ← 全库统一16位（00 §1.2-B）
    run_id: str | None      # 关联 RunStore 句柄（uuid，非内容哈希；一对多映射，00 C1）
    created_at_utc: str
    attrs: dict[str, Any] = {}          # 含 reproducible 旗标、coverage 标记等

class ProvEdge(BaseModel):
    rel: ProvRel
    src: str                # node_id
    dst: str                # node_id
    # 例: Entity(BacktestRun产出) --wasGeneratedBy--> Activity(BacktestRun)
    #     Activity(BacktestRun)   --used-->           Entity(DatasetVersion)
    #     Activity(BacktestRun)   --wasInformedBy-->   Activity(TrainRun)

class ProvStore:                # 复用 _JsonlStore 的 append-only + sha256 链
    # prov_nodes.jsonl / prov_edges.jsonl，每行带 prev_hash = H(上一行)（哈希链 tamper-evident）
    def add_node(n: ProvNode) -> None: ...
    def add_edge(e: ProvEdge) -> None: ...
    def dag(run_id: str, depth: int = -1) -> ProvDAG: ...   # 真·PROV DAG（非单链）
```
> **node_id ↔ content_hash（00 §1.2-E 裁定）**：`node_id` = Activity/计算节点身份；`content_hash` = 该节点产出 Entity 身份；二者靠 `wasGeneratedBy` 关联，**同一 sha256[:16] 哈希族**。LLM 节点走 **durable**（node_id 哈希进的是**被缓存的工件引用**，非「重跑得相同输出」），不假装 reproducible。

### 3.3 可复现强制属性（`snapshot.py`，挂在每个 `*Run` 上）
```python
class RunSnapshot(BaseModel):
    dataset_version: str            # = data_packages.py:70 的 sha256[:16]；空→缺
    dataset_content_hash: str       # = DatasetManifest 全文件 sha256 聚合（dataset_hash.py）
    split: dict | None              # {train, val, test, scheme: walk_forward, embargo_days}
    preprocessing: dict | None      # {steps:[...], params_hash}
    seed: int | None                # torch.manual_seed / np.random.seed 实际用值（非声明值）
    env_fingerprint: dict | None    # {python, platform, libs_lock_hash}
    git_sha: str | None             # `git rev-parse HEAD`（+ dirty 标记）

    REQUIRED = ("dataset_version","dataset_content_hash","split",
                "preprocessing","seed","env_fingerprint","git_sha")

    def missing(self) -> list[str]:
        return [k for k in self.REQUIRED if not getattr(self, k)]

def reproducibility_gate(snap: RunSnapshot) -> tuple[bool, list[str]]:
    miss = snap.missing()
    return (len(miss) == 0, miss)   # False → run.attrs["reproducible"]=False, reason="DAG完整但不可重现: "+miss

def capture_env() -> dict:          # python/platform + importlib.metadata 锁文件 hash
def capture_git_sha() -> str | None # subprocess git rev-parse；失败返 None（不崩，标缺）
```
> **实盘/paper 边界（dossier §8 开放问题6）**：`type="LiveRun"|"PaperRun"` 的节点**显式标 `replayable=False`**（市场不重演），`reproducibility_gate` 对它**只采集归因属性、不要求可重现**，文案改「可事后归因、不可重放」。绝不让实盘 run 假装能冷启动重现。

### 3.4 config_hash + 试验账本（`config_hash.py` + `ledger.py`，R8/R1 同一本账，00 §1.2-A）
```python
def config_hash(*, factor_ast: Any, params: dict, universe: str,
                dataset_version: str, freq: str, label: str) -> str:
    # 显式只哈希这 6 项；显式排除 name/description/tags 等装饰字段（00 §1.2-A：防改无关字段刷 N）
    blob = canonical_json({"factor_ast": factor_ast, "params": params, "universe": universe,
                           "dataset_version": dataset_version, "freq": freq, "label": label})
    return sha256(blob)[:16]

class LedgerEntry(BaseModel):           # 00 §1.2-H 指定的外键齐全
    entry_id: str                       # = config_hash（content-addressed）
    config_hash: str
    dataset_version: str                # 正交于 config_hash（00 §1.3-2：防换数据集刷 N）
    strategy_goal_ref: str | None       # 部件04 卡家族聚类外键
    kind: Literal["backtest","train","card_freeze","factor_eval"]
    stage: Literal["exploratory","confirmatory"]
    returns_corr_cluster_id: str | None # N_eff 用收益序列相关聚类（防换等价公式绕过）
    created_at_utc: str
    result_ref: str | None              # 缓存命中时指向已落盘产出（memoize）

class Ledger:
    def record_or_hit(entry: LedgerEntry) -> tuple[LedgerEntry, bool]:
        # 命中(同 config_hash 已存在) → 返缓存 result_ref, hit=True【不重跑】；仍计 honest-N
        # 未命中 → append-only 落账, hit=False
    def honest_n(strategy_goal_ref: str) -> int:          # distinct config_hash 计数（含 card_freeze 一等条目）
    def n_eff(strategy_goal_ref: str) -> int:             # 收益相关聚类后的下界（明示非精确）
```
> **honest-N 不可改小（管太宽分界·硬）**：`Ledger` 无任何 `set_n` / 删条目 API；`honest_n()` 永远实时从 append-only 账本数 distinct config，**调用方不能传入 N**（部件 04 freeze 时只能**读** `honest_n_at_freeze`，不能写）。→ §5-T7。
> **诚实标注（R2/R5/dossier §8 开放问题4）**：`n_eff` 永远带 `disclaimer="有效独立N不可观测，此为相关聚类下界，非精确计数"`（00 §1.2-A）。

### 3.5 自动埋点 + 覆盖盲区告警（`emit.py`，dossier §5.7）
```python
@provenance_activity(type="BacktestRun")   # 装饰器把函数包成 PROV Activity，自动 used/wasGeneratedBy
def backtest_trained_model(...): ...

def record_llm(prompt, response, model, *, run_id) -> str:
    # R11: prompt/response 落不可变 fixture（content-addressed），返 node_id；重放只读它、绝不重跑
    # 时间敏感部分自托管钉版本（dossier §6）

class CoverageMonitor:
    REGISTERED_PATHS: set[str]              # 声明应被埋点的关键执行路径白名单
    def check_uncovered(window) -> list[str]:
        # 跑过但没发谱系事件的路径 → 告警（非崩溃）。dossier §7 pitfall: 血缘腐烂/审计盲区
```

### 3.6 事件汇聚门面（`bus.py`，00 §1.2-D 唯一汇聚点）
```python
class LineageBus:
    # 全脊柱唯一事件入口：run 生命周期 + 卡状态机 + 审批门 都向它发 PROV Activity
    def emit_event(self, *, event: ProvEvent, run_id, payload) -> str: ...
    # ProvEvent = START|COMPLETE|FAIL|ABORT|freeze|deviate|approve|reject|consumed
    # 卡状态变更(draft/frozen/deviated/retired) → 映射为 freeze/deviate 等 Activity，挂同一 DAG
```

### 3.7 状态机（run 生命周期 → 谱系事件）
```
            START                 COMPLETE
 (create) ─────────► running ─────────────► succeeded ──► [reproducibility_gate]
                        │                                     ├─ pass → reproducible=True
                        │ FAIL/ABORT                          └─ fail → reproducible=False
                        ▼                                            (reason: 缺哪几项)
                     failed ────────────────────────────────► [仍落谱系：失败也可归因]
每次跃迁 LineageBus.emit_event → ProvStore.add_node(Activity) + add_edge
```

---

## 4. 代码接线点（逐条 file:line：改哪行/在哪加新文件/动了哪个函数签名）

> 已实际打开核实下列每个坐标。**不触碰已冻结的 RunDetailPage 既有逻辑**——前端只在「收益概述」页**加字段展示**（reproducible 旗标 + 缺失项），属允许的「加字段」三类改动之一，不改既有排版/逻辑。

### W1 — `Run` dataclass 加可复现强制属性（`experiments/store.py:47-63`）
在 `Run`（:48）追加字段（**全带默认值**，向后兼容旧 jsonl）：
```python
    # 可复现强制属性（部件03 RunSnapshot 投影；缺任一 → reproducible=False）
    snapshot: dict[str, Any] = field(default_factory=dict)   # RunSnapshot.model_dump()
    reproducible: bool | None = None                          # gate 结果；None=未评估
    repro_missing: list[str] = field(default_factory=list)    # 缺哪几项
    config_hash: str | None = None                            # 关联试验账本（00 C2）
    prov_node_id: str | None = None                           # 关联 PROV DAG（00 C7）
```
- `to_dict()`（:61-62）`asdict(self)` 自动带出新字段，无需改。
- `RunStore.create_run`（:129-149）签名加 `snapshot: dict | None = None, config_hash: str | None = None`，落进 `Run(...)`（:137-147）。
- `RunStore.update_run`（:151-170）加可选 `snapshot` 合并 + 在 `finished=True`（:167）后调 `reproducibility_gate` 写 `reproducible/repro_missing`。
- `__all__`（:251-259）无需改（不导出新内部类）。

### W2 — `lineage()` 升级为真 PROV DAG（`experiments/store.py:187-201`）
- **保留** `lineage()`（单链回溯，向后兼容现有端点 main.py:390）。
- **新增** `RunStore.prov_dag(run_id)` 委托 `ProvStore.dag(run_id)`（`lineage/prov.py`），返三类 PROV 关系。旧 `lineage` 不动，避免破坏 `test_experiments.py:32-46` 的现有断言。

### W3 — 新建 `app/backend/app/lineage/` 全套（§3.1 七文件）
全新增，不改既有文件结构。`__init__.py` 导出 `LineageBus / ProvStore / RunSnapshot / reproducibility_gate / config_hash / Ledger / provenance_activity / record_llm / CoverageMonitor`。

### W4 — 训练 run 自动埋点（`training/service.py:228-284`）
- `create_run`（:228-232）：传入 `snapshot=RunSnapshot(dataset_version=..., split={train_fraction}, seed=..., env=capture_env(), git_sha=capture_git_sha())` + `config_hash=config_hash(...)`。dataset_version 取自训练 panel 的 manifest；split 取 `request.train_fraction`（service.py:241-242 已有该切分逻辑）；seed 取 `trainer.py:103` 实际用值。
- `update_run` succeeded（:257-263）：之后调 `Ledger.record_or_hit(...)` + `LineageBus.emit_event(COMPLETE)`；产出 `ModelArtifact` Entity（`wasGeneratedBy` TrainRun）。
- 失败分支（:280-284）：`emit_event(FAIL)`（失败 run 也落谱系，可归因）。

### W5 — 回测桥进谱系（`training/backtest_bridge.py:82-151` + `:154-170`）—— **dossier §2.4 点名的最大盲区**
- 给 `backtest_trained_model`（:82）加 `@provenance_activity(type="BacktestRun")`，自动注册 Activity + `used`→DatasetVersion/ModelArtifact Entity、`wasGeneratedBy`→MetricSet（:141-150 的 metrics）。
- 函数签名加可选 `run_id: str | None = None`（不传则装饰器自建匿名 run）；返回 dict（:142-150）追加 `prov_node_id`。
- `MetricSet` Entity 挂 `oos_cutoff`（:124/:150），下游 PBO/DSR（部件 02）以 `wasDerivedFrom` 续挂——**信任旗标来自 MetricSet 的独立校准，不来自 DAG 完整性**（§1.2 红线）。

### W6 — 三 store 旁加 lineage 实例 + bus（`main.py:90-92`）
在 `:92` 后加：
```python
LINEAGE_BUS = LineageBus(DATA_ROOT / "lineage")
LEDGER      = Ledger(DATA_ROOT / "lineage")
```
`TrainingService(...)`（main.py:425-431）注入 `lineage_bus=LINEAGE_BUS, ledger=LEDGER`（service.py:95-107 构造函数加可选参数，默认自建）。

### W7 — 新增只读端点（`main.py:387-392` 同块之后）
不改现有 `/api/experiment_runs/{run_id}/lineage`（:387-392，保留单链）。新增：
- `GET /api/experiment_runs/{run_id}/prov_dag` → `RUN_STORE.prov_dag(...)`（PROV DAG）
- `GET /api/experiment_runs/{run_id}/reproducibility` → `{reproducible, repro_missing, snapshot}`
- `GET /api/ledger/honest_n?strategy_goal_ref=...` → `{honest_n, n_eff, disclaimer}`（带 R2/R5 明示）

### W8 — 前端「收益概述」页加字段（仅展示，**不改既有逻辑**）
RunDetailPage 收益概述页加一个只读旗标块：`reproducible ✓/✗ + 缺失项` + `honest_n / n_eff(下界)`。属冻结约束允许的「加字段」改动；**不动既有排版/显示逻辑**。

### W9 — CoverageMonitor 接线（`emit.py` + 启动注册）
`CoverageMonitor.REGISTERED_PATHS` 在 `main.py` 启动时注册关键路径白名单（train/backtest/llm_call/factor_eval）；周期 `check_uncovered` 把「跑过但没发谱系」的路径写告警日志（非崩溃，dossier §7 血缘腐烂）。

---

## 5. 对抗式测试规约（按 TEST_STANDARD：种已知坏→门必抓→断言什么）

> 验收口径（同 00 §任务2）：**真对抗** = 种一个已知 bug（拆/绕这道门），测试**因此 fail**；**剧场** = 门坏了测试照样 pass。下列每条都「种坏」。文件：`tests/test_lineage_bus.py`、`tests/test_repro_snapshot.py`、`tests/test_ledger_honest_n.py`。

### ① 种已知坏 → 门必须抓

**T1 · 可复现强制属性缺失探针（核心门）** — *种坏：建一个 run，snapshot 缺 seed（或 git_sha / split / dataset_version 任一）。*
- 门必抓：`reproducibility_gate` 返 `(False, ["seed"])`，run.attrs `reproducible=False`、reason 含「DAG完整但不可重现」。
- 断言：①缺任一 REQUIRED 项 → `reproducible is False` 且 `repro_missing` 精确列出缺项；②**反向**：七项全齐 → `reproducible is True`。门坏（gate 把缺 seed 当可重现）→ 反向+正向都 fail。**这是 dossier §5.4「必要不充分」的命门测试。**

**T2 · 谱系覆盖盲区告警探针** — *种坏：调一条**没被 `@provenance_activity` 埋点**的执行路径（直接调原始 `backtest_trained_model.__wrapped__` 绕过装饰器）。*
- 门必抓：`CoverageMonitor.check_uncovered` 把该路径列入告警。
- 断言：未覆盖路径 ∈ 告警列表；已覆盖路径 ∉。门坏（监控漏报）→ fail。直接对冲 dossier §7「血缘腐烂/审计盲区却自以为全覆盖」。

**T3 · 谱系污染/伪造探针（dossier §8 开放问题2 结构性弱点）** — *种坏：往 `prov_edges.jsonl` 手工插一条断裂的边（dst 指向不存在的 node_id），并篡改某行使 `prev_hash` 链断。*
- 门必抓：`ProvStore.dag` 校验哈希链时检出断裂行 + 悬空边。
- 断言：①哈希链断裂行被标 `tampered=True` 不静默；②悬空边不被当作合法 DAG 边返回。门坏（伪造边当真因果链）→ fail。**注意措辞**：断言报告写「检出哈希链不连续/防自欺」，**不写**「保证记录内容真实」（签名只防传输后改、不防 garbage-in，dossier §8）。

### ② 变形测试（无标准答案时的不变量）

**T4 · dataset_version 不可变变形** — *种坏：同 `(dataset_id, version)` 但改一个文件字节后重 `create_manifest` + `write_manifest`。*
- 门必抓：复用 `dataset_hash.py:135-159` 的 `DatasetIntegrityError`（同 version 内容必须不可变）。
- 断言：raise `DatasetIntegrityError`；且若该 version 已被某 run 引用，`reproducibility_gate` 对老 run 的 `verify_manifest`（dataset_hash.py:162-184）返 mismatch。门坏（内容被悄改、谱系还显示同 version）→ fail。

**T5 · canonical_json 键序/Unicode 不变量（00 §2.2 点名的缺探针）** — *种坏：同一 config 内容、dict 键顺序打乱 + 中文 NFC/NFD 两种归一化。*
- 门必抓：`config_hash` 与 PROV `content_hash` 对两种序列化得**同一 16 位哈希**。
- 断言：`config_hash(a) == config_hash(b_键序乱)`；NFC/NFD 归一后同哈希。门坏（键序敏感 → 同 config 算出两个 hash → honest-N 被高估、跨平台假阳性告警）→ fail。

**T6 · LLM 重放确定性（R11）** — *种坏：record 一段 LLM prompt/response 落 fixture 后，replay 时让底层 LLM client 抛错（模拟「绝不该被调用」）。*
- 门必抓：`record_llm` 重放**只读 fixture、绝不调 LLM client**。
- 断言：replay 返回与 record **逐字节相同**的 response，且 LLM client mock `call_count == 0`。门坏（重放偷偷重跑 LLM → 输出漂移、call_count>0）→ fail。durable 非 reproducible 语义直测。

### ③ 交叉验证 / 多证据三角

**T7 · honest-N 不可改小探针（决策「不让你藏试验」命门·硬）** — *种坏：①账本里已有 5 个 distinct config_hash；②尝试 `Ledger.set_n(2)`（应不存在该 API）；③调用方 freeze 时谎报 N=2。*
- 门必抓：`Ledger` 无任何改小/删条目 API；`honest_n()` 永远实时数 append-only 账本；部件 04 freeze 只能**读** `honest_n_at_freeze`，传入的 N 被忽略。
- 断言：①`hasattr(Ledger, "set_n") is False`；②真账本 N=5 时，谎报 N=2，`honest_n_at_freeze == 5`；③删条目无 API（append-only）。门坏（允许改小/删）→ fail。**对账**：与部件 04 T5 同一不变量，两侧独立测、口径必须一致（不一致即 BLOCK）。

**T8 · memoize 命中即返缓存不重跑（R8 同一本账）** — *种坏：同一 config_hash 提交两次，第二次让真实计算函数 mock 抛错（模拟「绝不该重跑」）。*
- 门必抓：`record_or_hit` 第二次 `hit=True` 返缓存 `result_ref`，**不触发重算**。
- 断言：第二次 `hit is True`、计算函数 `call_count == 1`（只第一次跑）；**同时**两次都计入 honest-N 的 distinct？→ **否**：同 config_hash 计一次（distinct config 才 +1），但 memoize 与计数是同一本账（断言 `honest_n` 不因第二次提交而 +1）。门坏（重跑烧 compute / 或第二次又 +1 高估 N）→ fail。

**T9 · 换无关字段不刷 N（00 §1.2-A 防作弊）** — *种坏：同因子+universe+dataset_version+freq+label，只改 `name`/`description`/`tags`，提交 N 次。*
- 门必抓：`config_hash` 显式排除装饰字段。
- 断言：N 次提交得**同一 config_hash**，`honest_n` 只 +1。门坏（换 description 就换簇 → N 被低估、绕过 honest-N）→ fail。
- **补充 N_eff 探针**：换**等价公式**（如 `a-b` vs `-(b-a)`）但收益序列高度相关 → `n_eff` 聚类后不因等价公式翻倍。

### ④ 幂等 / 恢复

**T10 · 谱系事件幂等** — *种坏：同 `request_idempotency_key`（00 §1.2-F 命名：端点幂等键、非交易幂等键）重复 `emit_event(freeze)` 两次。*
- 门必抓：第二次返存量 node、不产第二条 prov 节点。
- 断言：`prov_nodes.jsonl` 该事件只一条；`emit_event` 第二次返同 node_id。门坏（每次 emit 都新建）→ fail。

**T11 · 崩溃恢复（复用 store.py:98-102 容错）** — *种坏：往 `prov_nodes.jsonl` / `ledger.jsonl` 末尾写半行 JSON。*
- 门必抓：`ProvStore` / `Ledger` 读取跳坏行、返最近完整记录，不整库不可读。
- 断言：半行后仍能 `dag()` / `honest_n()`，坏行被跳过。门坏（一个坏行炸全库）→ fail。复用既有 `_JsonlStore` 容错路径（store.py:98-102）。

**T12 · 实盘/paper 节点不假装可重现（dossier §8 开放问题6 边界）** — *种坏：建一个 `type="LiveRun"` 节点，snapshot 故意完整。*
- 门必抓：`reproducibility_gate` 对 Live/Paper 节点返 `replayable=False`，文案「可事后归因、不可重放」，**不**因 snapshot 完整就标 `reproducible=True`（市场不重演）。
- 断言：Live 节点 `replayable is False` 且不渲染「可冷启动重现」。门坏（实盘 run 假装能重放）→ fail。

### ⑤ 裁决措辞

**T13 · 谱系 ≠ 信任 文案守门（dossier §1/§7 核心反证）** — *种坏：构造一个「DAG 完整 + 全部 reproducible=True」的 run，请求其展示文案/摘要。*
- 门必抓：摘要文案**子串黑名单**断言。
- 断言：文案含「可审计/可重现/可归因 + 适用域 + 未验证项（信任由独立校准证据承载）」句式；**不存在** `可信`/`安全`/`保证正确`/`结论成立`/`已验证为真`/`trustworthy`/`independent validation`/`组织独立` 任一子串（中英双语）。门坏（把 DAG 完整渲染成「结论可信」、或漏出「组织独立」）→ fail。

**T14 · n_eff 诚实免责守门（R2/R5 + dossier §8 开放问题4）** — *种坏：请求 `honest_n` 端点输出。*
- 门必抓：`n_eff` 永远带 disclaimer。
- 断言：输出含「有效独立N不可观测/相关聚类下界/非精确计数」；**不**出现「精确 N」/「真实试验数」绝对化措辞。门坏（把 n_eff 当精确真理）→ fail。

### ⑥ 经验网（回测↔paper 对账）

**T15 · 回测↔paper 谱系关联 + 背离告警** — *种坏：同一 config_hash 的回测 run 与 paper run，paper 净值与回测核心指标背离超阈。*
- 门必抓：两 run 经 `config_hash` / `prov_node_id` 关联同一 DAG；背离超阈产 `warning`（指向 bug/机制失效）。
- 断言：①两 run 在同一 PROV DAG（`wasInformedBy`/共享 config_hash）；②背离超阈 → warning。**A股分支单独断言**：`asset_class=="equity_cn"` 时无 live 段、只回测↔paper 两段（别让 A股路径空跑显绿，00 §2.1-T13）。门坏（对账缺失/A股假装有 live）→ fail。

> **集成测试待依赖落地（诚实标注）**：T7（与部件 04 对账）、T13/T14（与部件 12 验证官文案）、T15（与部件 06 consumed 触碰）在依赖部件落地前先在本部件 mock 下绿，并**显式标 `@pytest.mark.integration_pending`**——绝不用 mock 的绿冒充系统的绿（00 §2.3 红线）。

---

## 6. 与其他脊柱部件的契约（产出/消费的共享 schema）

> 锚定 00 §1.1 契约表。本部件被 00 指定为 **C2/C6/C10 的权威产方**，并参与 C1/C7 的 id 对齐。

### 6.1 本部件**产**（权威产方，落盘）
| 字段 | 口径（权威约定） | 落盘 | 消费方 |
|---|---|---|---|
| **`config_hash`** (00 C2) | `sha256(canonical_json(因子AST+params+universe+dataset_version+freq+label))[:16]`，**显式排除** name/description/tags | `lineage/ledger.jsonl` | 部件04（`multiplicity.ledger_ref`，只读不重算）、验证官 |
| **`ledger_entry`** (00 C10) | `{entry_id=config_hash, config_hash, dataset_version, strategy_goal_ref, kind∈{backtest,train,card_freeze,factor_eval}, stage, returns_corr_cluster_id, created_at, result_ref}`；`card_freeze` 是一等条目 | `lineage/ledger.jsonl` | 部件04（`ledger_ref=entry_id`，卡家族聚类）|
| **`honest_n` / `n_eff`** | 实时数 distinct config_hash；`n_eff`=收益相关聚类下界 + 强制 disclaimer | 计算态（不落盘，防改小）| 部件04 freeze（只读 `honest_n_at_freeze`）|
| **`event`** (00 C6) | `ProvEvent ∈ {START,COMPLETE,FAIL,ABORT,freeze,deviate,approve,reject,consumed}`；卡状态机/审批/run 生命周期统一发到 `LineageBus` | `lineage/prov_nodes.jsonl` | 全脊柱（唯一汇聚点，00 §1.2-D）|
| **PROV `content_hash`** (00 C4) | `sha256(canonical_json(payload))[:16]`，**16 位**（00 §1.2-B 不变量，禁全长 64 位）| `lineage/prov_nodes.jsonl` | 部件04（卡 Entity 关联）、验证官 |
| **`node_id`** (00 C7) | 与内核同 sha256[:16] 哈希族；Activity 身份，靠 `wasGeneratedBy` 关联产出 Entity 的 `content_hash` | `lineage/prov_nodes.jsonl` | 内核（回放锚点 = `checkpoint_id`，00 §1.2-C）、验证官 fixture 引用 |
| **`reproducible` / `repro_missing` / `snapshot`** | gate 结果 + 缺项 + RunSnapshot（7 强制属性）| `Run`（store.py，W1）| 前端「收益概述」展示、验证官 |

### 6.2 本部件**消费**（只读，他人产）
| 字段 | 产方 | 用途 |
|---|---|---|
| **`run_id`** (00 C1) | 部件03 `RunStore`（`run-{uuid4[:12]}`，store.py:30-31）| PROV 节点 `run_id` 关联（句柄，非内容哈希；一对多映射 node_id）|
| **`dataset_version`** (00 C3) | 既有 `data_packages.py:70` + 部件06 数据访问层（`sha256[:16]`）| RunSnapshot.dataset_version + config_hash 输入 |
| **`checkpoint_id`** (00 C5) | 部件01 内核（裁定 `= node_id`，00 §1.2-C）| 回放/恢复锚点 |
| **`verdict_id`** (00 C9) | 部件12 验证官 | 作 `consistency_check` Entity 挂 DAG（R7：禁「组织独立」措辞）|
| **`consumed` 触碰** | 部件06 数据访问层（一次性消费硬闸）| 记录 `consumed` 事件（本部件只记录，不拒绝）|

### 6.3 与既有代码的不变量（不得违反）
- **16 位截断全库统一**：所有哈希（config_hash / content_hash / dataset_version）一律 `sha256(...)[:16]`，对齐 `data_packages.py:70`（00 §1.2-B）。
- **append-only**：复用 `_JsonlStore`（store.py:80-103），新字段全带默认值，旧 jsonl 行 `Run(**row)`（store.py:99）不炸。
- **honest-N 单调不可减**：账本无删/改小 API（硬）。

---

## 7. 开放问题 / 风险（落地前必答）

1. **PII / 删除权 vs 不可变哈希链的根本张力（dossier §8 开放问题1）。** 把 prompt/response 全量落不可变 fixture + 哈希链，与 D2（加密落盘）/「可删除某条 PII」在密码学上对立。**落地前必答**：fixture 存「哈希指针 + 加密 blob」（可删 blob、留指针证明曾存在）还是明文留存？建议 MVP 落「内容寻址指针 + 单独加密 payload 存储，payload 可硬删、指针标 tombstone」，但这会让「逐字节重放」（T6）在 payload 删除后退化为「指针存在但内容不可重放」——需明确这是**可接受的降级**（删除权优先于重放）。

2. **谱系总线本身是攻击面（dossier §8 开放问题2，T3 已部分覆盖但不够）。** 能写谱系的对手/被 prompt 注入的 agent 可制造「看似可信的虚假因果链」。哈希链只防**事后篡改**、不防**写入时 garbage-in**。**必答**：谱系做 agent 自检底座时，是否需要写入侧的最小校验（如 dataset_version 必须能被 `verify_manifest` 验过才允许作 `used` 边）？建议至少对 DatasetVersion/ModelArtifact 这类有 manifest 的 Entity 做「写入即验」，prompt/response 类无法验（诚实标注）。

3. **config_hash 的「因子AST」口径未定（00 §1.2-A 埋雷）。** `factor_ast` 到底哈希到什么粒度？算术因子的 AST、ML/DL 模型的超参 + 架构、还是 StrategyGoal 子集？**必答**：需与部件 23（算术因子暴力遍历，AST 天然存在）、24/25（ML/DL）对齐「同一想法」的等价判定边界，否则 honest-N 在不同因子族口径不一。建议先为算术因子族落地（AST 明确），ML/DL 用 `(model_id, hyperparams_canonical)` 近似，**明示这是近似下界**。

4. **`returns_corr_cluster_id` 计算时机与成本。** N_eff 的收益相关聚类需要收益序列已算出——但 config_hash 在 run **开始**时就要定。**必答**：聚类是 run 完成后回填（异步）还是阻塞？建议异步回填，`n_eff` 查询时实时聚类（带缓存），避免阻塞探索（P2：不挡探索）。

5. **`@provenance_activity` 对子进程 DL 训练的埋点边界。** DL/代码训练走全功率子进程（主进程不 import torch，见 MEMORY v3）；装饰器在主进程，子进程内的 seed（trainer.py:103）/env 如何回传谱系？**必答**：子进程需把实际用的 seed/env/git_sha 写进 `result.json`（service.py:246-248 已落 result.json），主进程读回填 snapshot——否则 snapshot 采集的是主进程值、与子进程实际执行环境可能不一致（假可重现）。这是 T1 在 DL 路径下退化为剧场的最大风险点，落地必须有「子进程真实 seed 回传」的集成测试。

6. **CoverageMonitor 的 `REGISTERED_PATHS` 维护成本（dossier §7 血缘腐烂的元层版本）。** 白名单本身会过时——新增执行路径忘了登记，监控就漏报。**必答**：白名单是手维护还是从 `@provenance_activity` 装饰过的函数自动收集？建议自动收集（装饰器注册时写入），手维护只补「应被埋但还没埋」的待办——否则监控自己就是新的盲区。

7. **谱系优先级论证依赖的合规驱动已被 dossier §7 降权。** SR26-2 把 agentic 划出范围、EU AI Act tamper-evident 是分析师 gloss。**必答（已答，记录在此防回潮）**：本部件价值主张收敛到「工程可审计/可归因/可重现 + agent 自检红队底座 + honest-N 承载」（证据扎实），**不**主张「合规强制」（适用性存疑）或「提升用户信任」（已被证伪）。优先级靠「它是 config_hash/event/ledger 的权威产方、被全脊柱消费」（00 §标注②第 0 层地基）成立，而非合规。
