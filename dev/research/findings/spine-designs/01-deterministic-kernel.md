# 01 · 确定性 DAG 内核 + checkpoint/replay/fork/rollback + 交易副作用不可幂等边界

> 脊柱 build-ready 设计 · 接 R1–R29 决策 · 含 file:line 接线 + 对抗式测试 · Opus 4.8
> 上游契约基线：`docs/institutional-agent-os/spine/00-contracts-and-coherence.md`（C5/C7/C8 已对本部件下裁定，本文严格遵从，不重新发明 id 口径）

---

## 1. 职责与边界（接哪些 R 决策，本部件负责/不负责什么）

### 1.1 本部件负责（脊柱 P0 脊椎骨）

把研究/回测/实盘的整条工作流建成**确定性图内核**，交付五件事：

1. **节点内容寻址身份** `node_id = sha256(canonical_json(structure, inputs, sorted(upstream)))[:16]`，与谱系 Entity `content_hash` 同一哈希族（00-contracts §1.2-E / C7 裁定）。结构/输入/上游任一变则 id 变；不变则**复用工件、不重跑**。
2. **durable execution（复用日志）**：重放路径默认读已落盘工件，**绝不重跑 LLM 节点**（R11）。明确选边 durable，不奢望 reproducible（dossier §7 贯穿性结论：商用 LLM temp=0 也不逐位可复现）。
3. **checkpoint / replay / fork(what-if) / rollback** 四语义，`checkpoint_id = node_id`（00-contracts C5 裁定，不另立 id 体系）。
4. **节点分类纪律**：`pure`（可自由 replay/fork/rollback）vs `effectful`（触达券商/资金，必带 `effect_idempotency_key`）。fork/rollback/replay 撞到 `effectful` 边界**截断**（`HALT_AT_BOUNDARY`）→ 触发对账而非重发单。
5. **LLM 永远在节点内、绝不当控制器**：控制器是确定性图调度器；LLM 节点输出落不可变 fixture（record/replay）。

### 1.2 接哪些 R 决策

- **R11**（重放读工件、不重跑 LLM；时间敏感自托管钉版本）→ 本部件的 replay 语义核心，§3 状态机 + §5 T-DET 探针。
- **R10 / M17**（护栏接所有执行路径含中继/桥）→ `effectful` 边界把 copy_trade 的 `is_dispatched`/`record_dispatch` 幂等账（`app/copy_trade/beta.py`）泛化为内核级 `EffectLedger`，让**所有** effectful 节点（不止跟单）都走同一道幂等闸。
- **R12**（留出集隔离=约定+防篡改证据+一次性消费，诚实标注"防自欺非防恶意"）→ 内核 fixture/工件落盘走 content-addressed + 触碰留痕，但**口径诚实**：本地开放落盘无真访问控制边界，§7 标注。
- **R7**（真强制只在交易所侧硬边界；左侧证据治理诚实承认非组织独立）→ 内核唯一**硬锁**是 `effectful` 边界（动钱/不可逆）；pure 侧 replay/fork 完全放开（研究自由）。裁决措辞禁说"可信/安全"。
- **R1/R8 honest-N**（同一本 content-addressed 账，memoize 命中即复用且仍计 N）→ 内核的"命中工件即复用、不重跑"是 memoize 的执行层；但**内核不拥有 honest-N 计数**（那是部件03试验账本），内核只产 `node_id` 供其去重。**红线：内核的 memoize 复用绝不能反过来把 N 改小**——复用是省 compute，计数是诚信账，两者同源不同账。

### 1.3 本部件**不**负责（避免越界 / 避免重复造）

- **不**拥有 `config_hash` / honest-N 计数 / 试验账本 → 部件03（00-contracts C2）。内核只产 `node_id`，试验账本消费它。
- **不**拥有 PROV 谱系总线的事件存储 → 部件03。内核**发** `node_id` + lifecycle event 上总线，不自存血缘 UI。
- **不**拥有审批门（HITL 挂起-恢复）→ 部件04。内核**提供** `HALT_AT_BOUNDARY` 暂停点 + `checkpoint_id` 让 04 能挂起/恢复，但审批策略在 04。
- **不**改前端 `RunDetailPage`"收益概述"页既有逻辑（已冻结）。
- **不**引 Temporal/Prefect/Dagster 集群（dossier §5 运维税：单用户 Postgres/SQLite 为中心 → 倾向同库事务，不背分布式租约的运维重量）。

---

## 2. 现有代码现状（file:line：有什么、缺什么、dossier 点名的洞）

### 2.1 `app/backend/app/dag/engine.py`（260 行）— 有骨架，缺内核四件

| 已有 | file:line | 评 |
|---|---|---|
| `DAGTask` dataclass，**已有 `idempotency_key: str | None`** 字段 | engine.py:43-53（`idempotency_key` 在 :52） | 🟡 **字段在但纯装饰**：全文件无任何代码读它。dossier §5.4 / 任务书点名"把字段升级为强制约束"——就是这里。 |
| `DAGTaskStatus` 状态枚举 | engine.py:25 | 缺 `halted`（边界截断态）、`reused`（durable 命中态）。 |
| 拓扑排序 + 环检测 | engine.py:192-214 | ✅ 可直接复用为图调度器骨架。 |
| 串行执行 + retry 指数退避 + timeout | engine.py:94-189 | 🔴 **重试是"重跑函数"**（:136-164）——对 `effectful` 节点这是 M17 同类雷：重试 = 重发单。无幂等闸拦它。 |
| `register_op` / `_OPS` 全局注册表 | engine.py:28-41 | ✅ 节点 op 注册可复用。 |
| `Scheduler`（cron 软触发） | engine.py:217-247 | 与内核正交，不动。 |

**缺（dossier 点名的洞 + 00-contracts 悬空契约）**：
- ❌ 无 `node_id` 内容寻址（C7 悬空）。`DAGTask.id` 是人给的字符串句柄，不是 `hash(结构,输入,上游)`。
- ❌ 无 durable execution：每次 `run_dag` 全量重跑，无工件 store、无"命中即复用"（dossier §6 的 `store.get(node_id)` 缺失）。
- ❌ 无 checkpoint/replay/fork/rollback（C5 悬空，无 `checkpoint_id`）。
- ❌ 无 `pure`/`effectful` 分类，无 `HALT_AT_BOUNDARY`（dossier §6 节点契约缺失，**领域地雷未补**）。
- ❌ 无 `EffectLedger`：`idempotency_key` 字段不接任何幂等账。

### 2.2 `app/backend/app/copy_trade/beta.py`（278 行）— **已有的 effectful 边界，要泛化**

这是内核 `effectful` 边界的**唯一现成正确实现**，必须复用其形态而非另造：
- `IdempotencyViolation` 异常 + `ct_dispatches` 表 `UNIQUE(signal_id, follower_id)` | beta.py:26, :45-46
- `make_idempotency_key` / `is_dispatched` / `record_dispatch` 三件套 | beta.py:113-152
- `apply_follower_leverage_cap` 杠杆硬截断 | beta.py:250-264
- 消费方 `SignalRelayer._relay_to_one`：**下单前查 `is_dispatched` → 跳过**（executor.py:82-87），**下单后 `record_dispatch`**（executor.py:148-160），并发竞态靠 UNIQUE 兜底 + CRITICAL 日志（executor.py:156-160）。

→ 内核 `EffectLedger` = 把这套从"signal/follower 二元键"抽象成"`effect_idempotency_key` 单键 + 任意 effectful 节点"。**copy_trade 保持现状不回退**，内核 ledger 与它共享 `effect_idempotency_key` 口径（00-contracts C8）。

### 2.3 `app/backend/app/agent/agent_runtime.py`（120 行）— LLM 当了控制器，要降级进节点

- `AgentRuntime.run` 是单线程 reAct loop，`for _ in range(self._max_steps)`（agent_runtime.py:69），**LLM 决定下一步调哪个工具**（agent_runtime.py:70-115）——这正是 dossier §1 "LLM 当控制器"的反模式。
- 工具派发 `handler(tool_name, arguments)`（agent_runtime.py:97）无幂等、无 checkpoint、无副作用分类。
- 缺 `max_steps` 用尽的降级落点是字符串（agent_runtime.py:116），无 stall 计数器 / 受控 replan（dossier §6 Progress Ledger 模式）。

→ 内核接线：把 `AgentRuntime` 包成一个**节点内**的有界自治单元（pure 或 effectful 按它调的工具定），控制权交还确定性调度器；agent 的每个 LLM 输出落 fixture，replay 时读 fixture（R11）。**本部件不重写 agent_runtime 内部 reAct**，只在调度器侧把它当节点、在边界处加幂等闸。

### 2.4 `app/backend/app/jobs.py`（318 行）— 内存 SSE，要加 checkpoint 事件流

- `InMemoryJobStore` 内存态 + `threading.Condition` 驱动 SSE（jobs.py:16-74）。
- `stream_job` 终态 `{succeeded, failed, interrupted}`（jobs.py:46, :69）——缺 `halted`（边界截断）事件。
- `_run_data_pull_job` 崩溃即 `failed`（jobs.py:199-219），**无从 checkpoint 恢复**：retry_job 是整段重跑（jobs.py:132-138）——对含 effectful 步的 job 这是 M17 雷。
- `JobRecord.run_id`（schemas.py:128）已存在 → 内核 `run_id ↔ node_id` 一对多映射的句柄就挂这里（00-contracts C1）。

→ 内核接线：`stream_job` 增 `checkpoint`/`halted` 事件类型；崩溃恢复读最近 `checkpoint_id`。**SSE 既有事件不删不改语义，仅加事件类型**（向后兼容）。

---

## 3. 目标设计（schema 草图 + 模块布局 + 状态机）

### 3.1 模块布局（新增，不动既有文件结构）

```
app/backend/app/dag/
  engine.py          # 既有：升级 DAGTask（加 kind/effect_idempotency_key 强制约束）
  node_id.py         # 新增：内容寻址身份 sha256[:16]，与谱系 content_hash 同族
  artifact_store.py  # 新增：durable 工件 store（get/put/exists），content-addressed 落盘
  effect_ledger.py   # 新增：泛化 copy_trade/beta.py 的幂等账 → 任意 effectful 节点
  kernel.py          # 新增：DurableExecutor（replay/fork/rollback/HALT_AT_BOUNDARY）
```

### 3.2 schema 草图（Pydantic / dataclass）

```python
# node_id.py —— 内容寻址身份（C7：与 research-03 content_hash 同一 sha256[:16] 哈希族）
def compute_node_id(structure: dict, inputs: dict, upstream: list[str]) -> str:
    payload = {
        "structure": structure,   # 节点 op 名 + 版本 + 配置 schema 指纹
        "inputs": _io_normalize(inputs),    # IO 归一化（排序键、规整 float、去非确定字段）
        "upstream": sorted(upstream),       # 上游 node_id 进哈希 → 内容寻址、血缘即身份
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]   # 口径同 dataset_version/config_hash
```

```python
# engine.py 升级（强制约束，不是新字段堆叠）
NodeKind = Literal["pure", "effectful"]
ReplayPolicy = Literal["REUSE_ARTIFACT", "HALT_AT_BOUNDARY"]
DAGTaskStatus = Literal[
    "pending","running","succeeded","failed","skipped","timeout",
    "reused",     # 新增：durable 命中、读工件未重跑
    "halted",     # 新增：effectful 边界在 fork/rollback/replay 被截断
]

@dataclass
class DAGTask:
    id: str
    op: str
    params: dict = field(default_factory=dict)
    deps: list[str] = field(default_factory=list)
    retries: int = 0
    # ... 既有 timeout/sla 字段不动 ...
    kind: NodeKind = "pure"                       # 新增：默认 pure（安全默认）
    effect_idempotency_key: str | None = None     # 新增（C8，取代裸 idempotency_key 的语义）
    # 强制约束（__post_init__ 校验）：
    #   kind=="effectful" ⇒ effect_idempotency_key 必填，否则 raise（升级"字段→约束"）
    #   kind=="pure"      ⇒ effect_idempotency_key 必须为 None（防误标）

@dataclass
class NodeRunResult:        # 扩展既有 DAGTaskResult
    node_id: str            # 新增：内容寻址身份
    reused: bool = False    # 新增：True=读工件、未执行
    halted: bool = False    # 新增：True=边界截断
    effect_idempotency_key: str | None = None
```

```python
# effect_ledger.py —— 泛化 copy_trade/beta.py（同 effect_idempotency_key 口径，R10/M17）
class EffectIdempotencyViolation(Exception): ...

class EffectLedger:
    """所有 effectful 节点的统一幂等账。落盘 SQLite，UNIQUE(effect_idempotency_key)。
    与 copy_trade/beta.py 的 ct_dispatches 同形态：先 is_consumed 后 record。"""
    def is_consumed(self, key: str) -> bool: ...
    def record(self, key: str, node_id: str, venue_ref: str | None) -> None:
        # UNIQUE 冲突 → raise EffectIdempotencyViolation（并发兜底，同 executor.py:156-160）
```

### 3.3 状态机（节点级 + 内核操作级）

**节点执行状态机**（DurableExecutor 对每个节点）：
```
                          ┌────────── pure ──────────┐
pending ──schedule──▶ resolve node_id              │
                          │ store.exists(node_id)?  │
                          ├─ yes ─▶ reused (读工件，绝不重跑) ──▶ succeeded
                          └─ no  ─▶ running ─▶ store.put ─▶ succeeded
                                       └─ fail ─▶ retry≤N ─▶ failed/timeout

                          ┌──────── effectful ────────┐
running(effectful) ──▶ ledger.is_consumed(key)?       │
                          ├─ yes ─▶ reused（返存量、不重发单）──▶ succeeded
                          └─ no  ─▶ 执行副作用 ─▶ ledger.record(key) ─▶ succeeded
```

**内核操作语义**（replay / fork / rollback）：
```
replay(run_id):       for n in topo: 读 store[node_id] → 复用（R11，绝不重跑 LLM）
                      若某 node_id 工件缺失 ⇒ 仅该节点重算（pure）/ 对 effectful ⇒ HALT
fork(from_node_id):   clone 上游血缘（保 provenance）；下游 effectful 节点
                      replay_policy 强制改 HALT_AT_BOUNDARY（dossier §6）→ what-if 只在 pure 下游自由
rollback(to_node_id): 丢弃 to 之后的 pure 工件；遇 effectful 已 consumed ⇒
                      不"撤单"，而是 HALT + 发 reconcile event（对账，非重发/反向单）
```

**核心纪律落地**：`effectful` 节点在 replay/fork/rollback 三条路径**全部** `HALT_AT_BOUNDARY`，截断后发 `reconcile_required` 事件交对账，**绝不在 what-if / 恢复路径里触达券商**。

---

## 4. 代码接线点（逐条 file:line，均已打开核实）

> 约定：⊕=新增文件 ✎=改既有行 ✚=既有函数加参数/分支。不动任何已冻结前端逻辑。

**A. `app/backend/app/dag/engine.py`**
- ✎ `engine.py:25` — `DAGTaskStatus` 增 `"reused"`, `"halted"` 两态。
- ✎ `engine.py:43-53` — `DAGTask` 加 `kind: NodeKind="pure"` 与 `effect_idempotency_key: str|None=None`；保留旧 `idempotency_key` 字段为 deprecated alias（`__post_init__` 里若旧字段非空且新字段空则迁移 + 警告，向后兼容既有 YAML）。
- ✚ `engine.py:43-53` 后加 `DAGTask.__post_init__` — **强制约束**（任务书核心要求）：`kind=="effectful"` 且 `effect_idempotency_key is None` ⇒ `raise ValueError("effectful 节点必须带 effect_idempotency_key")`；`kind=="pure"` 且 key 非空 ⇒ raise。这是"字段→约束"的升级点。
- ✚ `engine.py:124-169` `_run_task` — 入口处增 durable 短路：算 `node_id`，`store.exists(node_id)` 则返 `reused`（不进 :136 的执行循环）。**对 `kind=="effectful"`**：执行前 `ledger.is_consumed(key)` 命中则返 `reused`（语义同 executor.py:82-87），执行后 `ledger.record`（同 executor.py:148-160）。
- ✚ `engine.py:136-164` 重试循环 — `effectful` 节点重试前**必须**先 `ledger.is_consumed`，命中即停（堵住 :136 "重试=重发单"的 M17 雷）。
- ✚ `engine.py:94-121` `run_dag` — 增可选参 `executor: DurableExecutor | None`，None 时保持现有全量串行行为（向后兼容，既有 7 个 test_dag.py 测试不破）。

**B. `app/backend/app/dag/node_id.py`** ⊕ — `compute_node_id` + `_io_normalize`（§3.2）。复用 `app/data_hash/dataset_hash.py` 的 sha256[:16] 截断口径（dataset_hash.py:70-78 `_sha256_file` 同族，但这里哈希 canonical_json 非文件）。

**C. `app/backend/app/dag/artifact_store.py`** ⊕ — `ArtifactStore.get/put/exists(node_id)`，content-addressed 落盘（SQLite 索引 + parquet/json blob）。R12 诚实标注：本地开放落盘、防自欺非防恶意，触碰留痕（mtime + access log）。

**D. `app/backend/app/dag/effect_ledger.py`** ⊕ — 泛化 `copy_trade/beta.py:101-172` 的三件套到 `effect_idempotency_key` 单键。**不动 copy_trade**（它继续用自己的 `ct_dispatches`）；内核 ledger 是平行的、给非跟单 effectful 节点（实盘下单/提币/桥）用，口径与 beta.py 一致（00-contracts C8）。

**E. `app/backend/app/dag/kernel.py`** ⊕ — `DurableExecutor`：`run/replay/fork/rollback`（§3.3 状态机）。fork 时遍历 `downstream(from_node_id)`，对 `kind=="effectful"` 强制 `replay_policy=HALT_AT_BOUNDARY`（dossier §6 伪码落地）。

**F. `app/backend/app/jobs.py`**
- ✚ `jobs.py:29-74` `stream_job` — 终态集合 `{succeeded, failed, interrupted}`（:46, :69）增 `"halted"`；新增 `event: "checkpoint"` 类型（不改既有 snapshot/progress/done/heartbeat 语义）。
- ✚ `jobs.py:132-138` `retry_job` — 含 effectful 步的 job 改为"从最近 checkpoint_id 恢复"而非整段重跑；恢复路径走 `EffectLedger.is_consumed` 去重。
- 复用 `JobRecord.run_id`（schemas.py:128）作 `run_id ↔ node_id` 映射句柄（C1）。

**G. `app/backend/app/agent/agent_runtime.py`**
- ✚ `agent_runtime.py:62-117` `AgentRuntime.run` — 包一层 `KernelNodeAdapter`：把整个 reAct turn 当**一个节点**，LLM 输出经 `ArtifactStore` 落 fixture；replay 时读 fixture 不重跑（R11）。**不重写内部 reAct loop**，只在节点边界加 record/replay + 副作用分类。agent 调的工具若触达 effectful op ⇒ 该子节点走 EffectLedger。

**H. 测试** ⊕ `app/backend/tests/test_dag_kernel.py`（§5 全部探针）。既有 `tests/test_dag.py` 7 测试不动（向后兼容验证）。

---

## 5. 对抗式测试规约（按 TEST_STANDARD：种已知坏→门必抓→断言）

> 验收标准不是覆盖率，是"种一个已知的坏，门必须抓住，否则门是纸做的"。每条都先种坏、再断言门反应。

### T-DET-1 · durable≠reproducible 探针【④幂等/恢复 + dossier §7 贯穿性结论】
- **种坏**：注册一个 LLM 节点，op 内部用一个每次调用自增的计数器（模拟"重跑会漂移"）。先 `run` 落工件，再 `replay`。
- **门必抓**：replay 路径**读工件、计数器不自增**。
- **断言**：`replay 结果 == run 结果`（逐字段）；且 op 内计数器调用次数在 replay 后**不变**（用 spy 断言 LLM op 被调 0 次）。门坏（replay 重跑 LLM）⇒ 计数器变 ⇒ fail。

### T-DET-2 · 节点身份内容寻址不变量【dossier §6 + 00-contracts C7】
- **种坏**：构造两个节点 A、B，仅 `inputs` 差一个无关装饰字段（如注释）经 `_io_normalize` 后应相同；再构造 C，`upstream` 不同。
- **门必抓**：A、B 的 `node_id` 相同（复用同一工件）；C 的 `node_id` 不同。
- **断言**：`compute_node_id(A)==compute_node_id(B)` 且 `!=compute_node_id(C)`；改 structure/inputs/upstream 任一 ⇒ id 必变。这是"内容寻址"的核心不变量。

### T-DET-3 · effectful 边界幂等探针【④ + R10/M17 — 本部件最重】
- **种坏**：一个 `kind="effectful"` 下单节点，带 `effect_idempotency_key="k1"`。**重复 `run` 两次同 key**（模拟信号重发/网络重试）。
- **门必抓**：第二次返存量（`reused=True`）、`venue.place_order` **只被调一次**。
- **断言**：venue spy `place_order` 调用次数 == 1；第二次 result `reused is True`。门坏（重发单）⇒ 调 2 次 ⇒ fail。形态与 `tests/test_copy_trade.py` 的幂等回归同源。

### T-DET-4 · fork 在 effectful 边界截断探针【④ + dossier §6 领域地雷】
- **种坏**：DAG = `pure_calc → effectful_order → pure_report`，已 `run` 完（订单已下、已 consumed）。对 `pure_calc` 做 `fork`（what-if 改参数）。
- **门必抓**：fork 下游的 `effectful_order` 节点 `replay_policy` 被强制为 `HALT_AT_BOUNDARY`，**不重发单**；what-if 只在 `pure_report` 自由重算。
- **断言**：fork 分支里 `effectful_order` 状态 == `"halted"`，venue `place_order` **0 次新调用**，且发出 `reconcile_required` 事件。门坏（fork 透传到下单）⇒ 真金白银重发 ⇒ fail。

### T-DET-5 · rollback 不撤单、走对账探针【④ + R7 硬边界】
- **种坏**：`run` 完含一个已 consumed 的 effectful 下单节点，调 `rollback(to=该节点之前)`。
- **门必抓**：rollback **不调用任何"撤单/反向单"**；effectful 节点 `halted` + 发 `reconcile_required`。
- **断言**：venue 上无 cancel/反向 order 调用；rollback 返回里 effectful 段标 `requires_reconcile=True`。门坏（rollback 自动撤单/反向）⇒ fail。

### T-DET-6 · 崩溃从 checkpoint 恢复探针【④幂等/恢复】
- **种坏**：DAG = `A(pure) → B(effectful, 已下单) → C(pure)`，在 C 执行中注入崩溃（raise）。然后 `retry_job`/恢复。
- **门必抓**：恢复**不重跑 A、B**（A 读工件、B 经 ledger.is_consumed 命中），只重算 C。
- **断言**：恢复后 B 的 `venue.place_order` **0 次新调用**（is_consumed 命中）；A `reused=True`；C 重算一次。门坏（恢复整段重跑）⇒ B 重发单 ⇒ fail。直击 jobs.py:132-138 现有"整段重跑"雷。

### T-DET-7 · effectful 节点缺幂等键被强制约束拦住【①种已知坏→门必抓】
- **种坏**：定义 `DAGTask(kind="effectful", effect_idempotency_key=None)`。
- **门必抓**：`__post_init__` **构造即 raise**，不让这种节点进图。
- **断言**：`pytest.raises(ValueError, match="effectful.*effect_idempotency_key")`。这就是"把 idempotency_key 字段升级为强制约束"的验收点——门坏（裸字段不校验）⇒ 能构造出会重发单的节点 ⇒ fail。

### T-DET-8 · LLM 当控制器的回归防线【dossier §1 核心纪律】
- **种坏**：尝试让一个 LLM 节点的输出**直接决定调度顺序**（构造一个把 LLM 返回值塞进 `deps` 的图）。
- **门必抓**：调度器只认静态 `deps`/`node_id` 血缘，**忽略**任何运行时 LLM 产出对图结构的篡改；图结构在 `run` 前已冻结。
- **断言**：注入后的执行顺序 == 静态拓扑序（与 LLM 输出无关）；LLM 输出只能改节点**内**结果、不能改图。门坏（LLM 改了调度）⇒ 顺序偏离静态拓扑 ⇒ fail。

### T-DET-9 · memoize 复用绝不把 honest-N 改小【R1/R8 红线 + 跨部件】
- **种坏**：同一 config 的 pure 节点连跑 3 次（第 2、3 次命中工件 `reused`）。mock 一个试验账本钩子。
- **门必抓**：3 次都 `reused` 省 compute，但试验账本被通知 **3 次 distinct attempt**（N 不因复用被低估）。
- **断言**：`ArtifactStore` 命中 2 次（compute 省了），但账本 `on_attempt` 回调被调 3 次。门坏（命中即不计 N）⇒ 账本只收到 1 次 ⇒ fail。**注**：内核只负责"发通知给账本"，真正的 N_eff 聚类在部件03；本测断言内核不吞通知。

### T-DET-10 · 裁决措辞探针【⑤】
- **种坏**：构造一个 replay/fork 报告渲染。
- **门必抓**：报告措辞用"durable 复用工件 / 证据：节点 X 未重跑 / 未验证：LLM 重跑是否漂移"等，**禁出现**"reproducible / 可信 / 安全 / 组织独立验证"。
- **断言**：报告文本正则**不含** `可信|安全|reproducible|组织独立`；**含** `durable|复用工件|未验证`。门坏（宣称 reproducible/可信）⇒ fail。守 R7/dossier §7。

> **不做的测**（诚实标注，避免覆盖率剧场）：不测"LLM 输出逐位可复现"（dossier §7 明确不可保证，做这测是自欺）；不测"留出集防恶意篡改"（R12：本地落盘只防自欺，无真访问控制边界，测它会过度声称）。

---

## 6. 与其他脊柱部件的契约（共享 schema）

> 严格遵从 `00-contracts-and-coherence.md` 已下裁定，本部件是 C5/C7 的**权威产方**。

| 键 | 本部件角色 | 口径（不可改） | 流向 |
|---|---|---|---|
| `node_id`（C7） | **权威产方** | `sha256(canonical_json(structure,inputs,sorted(upstream)))[:16]`，与谱系 `content_hash` 同哈希族（durable 非 reproducible） | → 部件03 谱系作 PROV Activity id / 试验账本去重；→ 回放 |
| `checkpoint_id`（C5） | **权威产方** | `checkpoint_id == node_id`（直接复用，不另立 id） | → 部件04 审批门挂起-恢复；→ replay fixture 引用 |
| `effect_idempotency_key`（C8） | 共用约定（消费+登记） | 业务级 `client_order_id`/`transfer_request_id`；内核 `EffectLedger` 与 copy_trade `ct_dispatches` 同口径 | ← 执行侧产；内核 ledger 登记 + 边界去重 |
| `run_id`（C1） | 消费（挂句柄） | `run-{uuid4.hex[:12]}`（uuid 句柄，**非内容哈希**）；与 `node_id` 是**一对多**、显式映射、不混用 | ← `JobRecord.run_id`（schemas.py:128）；内核存映射 |
| `config_hash`（C2） | **不产**（只消费 node_id 供其算） | 部件03 拥有；内核**不**算它、**不**碰 honest-N 计数 | 内核 → 03（给 node_id）；03 自算 config_hash |
| `dataset_version`（C3） | 消费（进 node_id 的 inputs） | `sha256(fp_blob)[:16]`（data_packages.py 已实做） | ← 数据层；进节点 inputs 参与寻址 |
| `event`（C6） | 产 lifecycle event | 内核发 `START/COMPLETE/FAIL/HALT/RECONCILE_REQUIRED/CHECKPOINT` 上谱系总线；**不**自存血缘 UI | → 部件03 谱系总线 |

**关键纪律（00-contracts §1.2-E 复述）**：`node_id` 哈希进去的"输出"必须是**被缓存的工件引用**、走 durable 语义，**不能**假装重跑得到相同 node_id。内核绝不向外承诺 reproducible。

---

## 7. 开放问题 / 风险（落地前必答）

1. **`_io_normalize` 的归一化边界谁定？** 哪些输入字段进 `node_id` 哈希、哪些是"装饰字段"被排除，直接决定 durable 命中率与正确性。漏排 → 假命中（复用了不该复用的工件，最危险）；多排 → 永不命中（durable 失效）。**必须先定一份字段白名单**，且与部件03 `config_hash` 的排除集（name/description/tags，00-contracts §1.2-A）保持一致逻辑，否则两边"同一想法"判定会分叉。

2. **`effect_idempotency_key` 由谁生成、何时生成？** copy_trade 是 `signal_id::follower_id`（确定性派生）。但通用 effectful 节点（如"实盘市价单"）的 key 若由 LLM 节点产 → 重跑漂移会换 key、绕过幂等闸（M17 同类雷）。**裁定建议**：key 必须由**确定性派生**（`node_id` + 业务维度），**禁** LLM 直接产 key。落地前须把这条写进 `__post_init__` 约束或 EffectLedger 入口。

3. **fork 后下游 pure 节点的 dataset_version 是否仍 PIT 安全？** what-if 改了上游参数，下游若复用旧 `dataset_version` 工件可能引入时间错配。需与部件09（bitemporal PIT）确认 fork 是否要重新解析 PIT 快照，还是 fork 必须显式声明"冻结数据视图"。

4. **崩溃恢复的 checkpoint 落盘原子性。** 单用户 SQLite 同库事务（dossier §5/§6 推荐）能给 step 的 exactly-once，但 `ArtifactStore`（文件 blob）与 `EffectLedger`（SQLite）跨两个存储 → "工件已写但 ledger 未记"的窗口存在。**落地前须定**：是否把 ledger record 与工件 put 包进同一 SQLite 事务（artifact blob 元数据进库、大 blob 落盘但 commit 以库为准），避免 effectful 节点"下了单但没记账"。

5. **agent_runtime 当节点后的 stall/成本预算未定**（dossier §8 开放问题1）。把 reAct turn 包成节点解决了控制权，但每 turn 多少 LLM 调用、stall 阈值、replan 频率仍是可调旋钮，未量化。本部件可先不接 Progress Ledger，但须留 hook，避免"有界自治"变成本黑洞。

6. **reconcile（对账）的下游消费方未定。** 本部件只负责在 effectful 边界 `HALT` + 发 `reconcile_required` 事件，**谁来对账、对账失败如何阻断后续 run** 不在本部件——需与执行侧/部件04 审批门确认对账闭环，否则"截断"只是发了个事件没人接。

7. **R7 诚实口径需贯穿渲染层。** 内核能产 durable 证据，但任何把"DAG 完整/工件齐全"渲染成"结论可信"的 UI 都违 R7/dossier §5.5。本部件管不到前端文案，须在契约里向部件03 谱系/部件04 明确："node_id 链完整 ≠ 结论可信"，且不得触碰已冻结的 RunDetailPage 逻辑。
