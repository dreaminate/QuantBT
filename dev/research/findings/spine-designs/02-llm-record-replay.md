# 02 · LLM 节点 record/replay 确定性 + 受控翻译层
> 脊柱 build-ready 设计 · 接 R1–R29 决策 · 含 file:line 接线 + 对抗式测试 · Opus 4.8

---

## 1. 职责与边界（接哪些 R 决策，本部件负责/不负责什么）

### 1.1 一句话定位

把现有 `AgentRuntime → LLMClient.chat()` 这条**裸调真实 API、输出无凭证、不可重放**的链路，改造成
**「受控翻译层（LLM 只产受 schema 约束的结构化对象、不持决策权）+ 不可变 fixture record/replay（带 HMAC 完整性 + 内容寻址 cache key）」**。
LLM 是「触手」，确定性脊柱（部件 01 内核 / 部件 03 账本 / 部件 04 审批 / 部件 12 验证官）是「骨架」。本部件是触手与骨架之间那层**防伪、可回放、可审计的硬接口**。

### 1.2 接哪些 R 决策

| R 决策 | 本部件怎么落 |
|---|---|
| **R11 重放读工件、绝不重跑 LLM** | 本部件的命根子。replay 模式下 `chat()` 完全绕过真实 API，从 fixture 读已落盘输出；time-travel/验证官/谱系全靠它。**「durable 非 reproducible」**（00 §1.2-E）：node_id 哈希进去的是被缓存的工件引用，不假装重跑得到同输出。 |
| **R7 诚实非组织独立** | fixture 里 LLM 自评/自打分字段一律不持决策权（`decision_authority=none`）；验证官复核走的也是「读本部件 fixture 逐字节重放」，措辞必须叫 `consistency_check`，**禁出现 "independent validation"/"组织独立"**（00 §1.2-G 红线）。 |
| **R12 OOS 约定非强制 / 防自欺非防恶意** | fixture 的 HMAC 完整性保护诚实标注「**防篡改/防自欺、非防本机恶意**」——本地开放落盘，HMAC key 与 fixture 同机即无真访问控制边界。不宣称密码学审计级不可抵赖。 |
| **R8/R1 同一本账 · content-addressed** | 本部件的 `fixture_key` 与部件 03 试验账本的 `config_hash`/部件 01 内核的 `node_id` **同哈希族**（sha256[:16]，canonical_json）。LLM 调用命中已有 fixture 即返缓存【不重发 API】（省 token），但**每个 distinct fixture_key 仍登记**——memoize 与可复现账是同一本。 |
| **R6 监管锚 NIST** | fixture = NIST AI RMF MEASURE/MANAGE 的可追溯证据载体（红队 run / 失败 / 缓解可回放）。**不宣称 SR 11-7 合规**（dossier §7.2 已澄清 SR11-7 GenAI 适用性是第三方外推）。 |
| **honest-N 不可改小但可自由跑（P2 / 管太宽分界）** | 本部件只**如实记录**每次 LLM 调用为一条 fixture，N 由部件 03 聚类计数，本部件不提供「删 fixture 刷低 N」的 API（append-only + tombstone）。研究侧自由跑（record 模式随便调），只有 fixture 不可静默篡改/抹除。 |

### 1.3 负责 / 不负责

**负责**：① LLM 调用的 record/replay 引擎（fixture 落盘/读取/HMAC）；② cache key 内容寻址（编码图中位置 + 上游依赖 + run_index，防 best-of-N/分支碰撞）；③ 受控翻译层（structured/constrained decoding 强制 + schema 校验 + 翻译失败兜底）；④ 三级可复现分级声明与度量（bitwise/decision/semantic）；⑤ 把 fixture 引用暴露成 `node_id`/`checkpoint_id` 给脊柱挂 DAG。

**不负责**（消费方/上游，本部件只产契约）：① honest-N 的聚类计数（部件 03）；② config_hash 的权威定义（部件 03）；③ DAG 编排/checkpoint 恢复语义（部件 01）；④ 审批挂起-恢复（部件 04）；⑤ 验证官异模型复核裁决 `verdict_id`（部件 12）；⑥ 决策/打分/阈值（确定性脊柱，本部件**强制**把这些从 LLM 手里夺走、不在本部件实现规则引擎，只保证 LLM 输出不直接当决策用）。⑦ **不改前端 RunDetailPage「收益概述」既有逻辑**（冻结）。

---

## 2. 现有代码现状（file:line：有什么、缺什么、哪里是 dossier 点名的洞）

### 2.1 现有链路（已核对行号）

| 位置 | 现状 | 缺口 |
|---|---|---|
| `agent/agent_runtime.py:70` `response = self._llm.chat(messages, tools=TOOL_SCHEMA)` | reAct loop 每步**裸调** `chat()` | 无 fixture、无 cache key、无 replay 开关。崩溃即丢、不可回放。 |
| `agent/agent_runtime.py:62-117` `AgentRuntime.run()` | 同步 loop，`AgentStep` 只在内存（`agent_runtime.py:26-35`），`turn` 不落盘 | 无 `run_index`/`node 位置`概念；并行 best-of-N 必碰撞（dossier §7.3 AI21 实证）。 |
| `agent/llm_client.py:43-51` `LLMClient.chat(...)` 抽象签名 | 入参 `messages/tools/model/temperature`，**无 seed / top_p / response_format** | constrained decoding 无接口；`temperature` 默认 0.2（dossier §7.3：temp=0 也不保证确定，但翻译层须能强制 temp=0+seed）。 |
| `agent/llm_client.py:27-31` `LLMResponse` | `content / tool_calls / raw` | **无 `system_fingerprint` / `model_id` / `seed` / `fixture_key` / `repro_level`**——dossier §5.3/§7.3 点名必须记的可复现元数据全缺。 |
| `agent/llm_providers.py:99-140` `AnthropicLLM.chat` payload | 写死 `max_tokens=4096`、`temperature` 透传，**不传 seed**，`data = r.json()` 直接丢 raw | 不抽 `system_fingerprint`（Anthropic 在 `response.model` + usage 里有版本线索）；不固定不可变 model_id（`default_model="claude-sonnet-4-5"` 是**别名**，dossier §5.4 禁用别名）。 |
| `agent/llm_providers.py:232-244` `OpenAILLM.chat` 解析 | 抽了 `content/tool_calls`，**丢弃 `system_fingerprint`**（OpenAI 在 `data["system_fingerprint"]`，dossier §4 点名必记） | seed 不传、fingerprint 不记 = 复现承诺随供应商静默更新作废（dossier §7.3）。 |
| `agent/llm_providers.py:406` `make_llm_client(...)` | 工厂返回裸 client | 无「record/replay 包装层」注入点；replay 时仍会建真 client 打真 API。 |
| `main.py:207-210` `_current_agent_llm()` / `main.py:217-230` `_agent_runtime()` | 每 turn 现选 provider，不缓存 | **没有 run_id 锚点**、没有 replay 模式开关、不传 fixture store。 |

### 2.2 dossier 点名、现状全缺的洞

- **§8.1 安全面**：fixture 完整存 prompt + tool 返回 + 输出 = 敏感数据/投毒/越权面，且语义缓存有键碰撞攻击（arXiv 2601.23088）。现状**连 fixture 都没有**，更无 HMAC/签名/访问控制 → 本部件从零建。
- **§7.3 cache key 碰撞**：现状无任何 cache key；上线前必须直接做成「编码图中位置 + 上游依赖 + run_index」的内容寻址键，不能先做 prompt-only 哈希再补。
- **§8.4「确定地错」**：现状 LLM 输出（`tool_calls`）**直接进** `AgentRuntime` 派发执行（`agent_runtime.py:81-107`），没有 schema 语义校验/人工确认门 → 翻译错会被确定性放大。
- **§8.3 托管 API bitwise 不可达**：现状全是托管 API（Anthropic/OpenAI/Qwen），fingerprint 不记 → 供应商换模型后无法区分「我改了 prompt 还是供应商换了模型」。

---

## 3. 目标设计（schema/Pydantic 草图 + 模块布局 + 状态机）

### 3.1 模块布局（新增 1 包 + 1 测试，最小侵入既有 agent）

```
app/backend/app/agent/replay/           # 新增包
  __init__.py
  fixture.py        # LLMFixture / FixtureKey / HMAC 完整性
  store.py          # FixtureStore (append-only + tombstone, 落 DATA_ROOT/artifacts/llm_fixtures/)
  recording_client.py  # RecordingLLMClient —— 包住任意 LLMClient 的装饰器
  translation.py    # ControlledTranslator —— constrained decoding + schema 校验 + 兜底
  repro.py          # ReproLevel 枚举 + pass^k 度量
app/backend/tests/test_llm_record_replay.py   # 本部件对抗式测试
```

### 3.2 核心 schema（Pydantic / dataclass 草图）

```python
# repro.py
class ReproLevel(str, Enum):
    BITWISE = "bitwise"      # 仅自托管批不变内核档（本项目默认不用）
    DECISION = "decision"    # 中低频默认：k 次全同到「足以支撑同一下游决策」
    SEMANTIC = "semantic"    # 语义等价即可

# fixture.py
@dataclass(frozen=True)            # 不可变
class ModelPin:
    provider: str
    model_id: str                  # 不可变版本 id，禁别名（dossier §5.4）
    system_fingerprint: str | None # 录制时供应商回传；None=供应商未提供（诚实标注）
    params: dict                   # {temperature, top_p, seed, max_tokens}

@dataclass(frozen=True)
class FixtureKey:
    """cache key = sha256[:16] of canonical_json(以下全部)。与 node_id 同哈希族（00 §1.2-E）。"""
    node_pos: str        # 图中位置：f"{run_id}:{turn_idx}:{step_idx}"（agent loop 内稳定坐标）
    prompt_digest: str   # sha256(canonical(messages+tools)) —— 不存明文于 key，明文在 fixture body
    model_pin_digest: str# sha256(canonical(ModelPin))
    upstream_digest: str # 上游依赖摘要：上一 fixture_key + 注入的工具返回摘要（防分支碰撞）
    run_index: int       # best-of-N / 并行分支序号（防同坐标多采样碰撞）
    def compute(self) -> str: ...   # -> "llmfx-<sha256[:16]>"

@dataclass
class LLMFixture:
    fixture_key: str               # = FixtureKey.compute()，也充当本 LLM 节点的 node_id
    run_id: str                    # C1，部件03 RunStore 句柄
    repro_level: str               # ReproLevel
    decision_authority: str        # 恒 "none"（LLM 不持决策权，R7）
    model_pin: dict                # ModelPin.to_dict()
    request: dict                  # 完整 messages + tools + 请求参数（明文，敏感→加密落盘）
    response: dict                 # content + tool_calls + raw（完整供应商返回）
    tool_calls: list               # 解析后的结构化 tool_calls（受控翻译产物）
    schema_ref: str | None         # 受控翻译用的 schema 引用
    translation_status: str        # "ok"|"schema_invalid"|"human_confirm_required"
    created_at_utc: str
    integrity: str                 # HMAC-SHA256(canonical(除 integrity 外全字段), key)
    consumed: bool = False         # 一次性消费留痕（R12，对 frozen_oos 类 fixture）
    tombstoned: bool = False       # 软删除，N 不因此减少（honest-N 不可改小）
```

### 3.3 双层数据流与状态机

```
        record 模式                              replay 模式
user_input                                  user_input
   │                                           │
   ▼                                           ▼
AgentRuntime.run loop ──► RecordingLLMClient.chat()
   │  (node_pos, run_index, upstream_digest)   │
   ▼                                           ▼
  ┌─ FixtureStore.get(fixture_key) ────────────┤  命中→ HMAC 校验→ 返回 fixture.response
  │     未命中 (record only)                    │  未命中 (replay) → RAISE ReplayMiss（绝不打真 API）
  ▼                                           
真实 client.chat()  ──► ControlledTranslator   ──► schema 校验
   │  (传 seed/temp=0/response_format)            ├─ ok            → LLMResponse
   ▼                                              ├─ schema_invalid→ reject_and_retry(≤N)
抽 system_fingerprint / model_id                  └─ 语义存疑      → human_confirm（不放行下游）
   │
   ▼
LLMFixture(+HMAC) → FixtureStore.put（append-only）
```

**翻译层状态机**（dossier §8.4「确定地错」兜底）：
`RAW_OUTPUT → [constrained decoding] → SCHEMA_VALID? → [语义不变量校验] → OK | RETRY(≤N) | HUMAN_CONFIRM`。
HUMAN_CONFIRM 态**不把 tool_calls 交给 `AgentRuntime` 派发**，挂起等部件 04 审批门。

### 3.4 fingerprint 漂移检测

`FixtureStore.put` 时，若同一 `(provider, model_id)` 的 `system_fingerprint` 与上次记录不同 → 写一条 `fingerprint_drift` 事件给部件 03 谱系总线（C6 `event`），**不静默**。这是「是我改了 prompt 还是供应商换了模型」可区分性的物理实现（dossier §5.4 / §8.3）。

---

## 4. 代码接线点（逐条 file:line：改哪行/在哪加新文件/动了哪个函数签名）

> 全部已实际打开文件核对。新增包不破坏既有 import；既有签名只做**向后兼容扩展**（新增 keyword-only 参数，默认 None → 退化为现状行为）。

### 4.1 扩展 `LLMResponse` 记可复现元数据 —— `agent/llm_client.py:27-31`

在 `LLMResponse` dataclass（`llm_client.py:27`）**新增字段**（全部带默认值，向后兼容）：
```python
    model_id: str | None = None          # 不可变版本 id
    system_fingerprint: str | None = None
    seed: int | None = None
    fixture_key: str | None = None       # replay/record 回填
    repro_level: str = "decision"
```

### 4.2 扩展 `chat()` 签名支持 constrained decoding —— `agent/llm_client.py:43-51`

`LLMClient.chat` 抽象签名（`llm_client.py:44-51`）**新增 keyword-only**：`seed: int | None = None`、`top_p: float = 1.0`、`response_format: dict | None = None`（JSON-schema/grammar）。三档实现（`llm_providers.py`）对应：
- `AnthropicLLM.chat`（`llm_providers.py:54-140`）：payload（`:99`）加 `"top_p"`；解析（`:128-140`）抽 `model_id = data.get("model")`，`system_fingerprint` Anthropic 暂无则置 None（诚实标注），回填进 `LLMResponse`。
- `OpenAILLM.chat`（`llm_providers.py:162-244`）：payload（`:191-195`）加 `"seed"`、`"top_p"`、`"response_format"`；解析（`:232-244`）抽 `data.get("system_fingerprint")` 与 `data.get("model")` 回填 `LLMResponse`（**这是现状直接丢弃的字段**）。
- `QwenLLM`（`:314-322`）/ `OpenAICompatibleLLM`（`:350-358`）透传给内部 `OpenAILLM`，自动继承。

> `DevLocalLLM.chat`（`llm_client.py:89-106`）签名同步加这三个 keyword（`# noqa: ARG002` 忽略），保证开发期/CI 不破。

### 4.3 新增 record/replay 装饰器 —— 新文件 `agent/replay/recording_client.py`

`RecordingLLMClient(LLMClient)` 包住任意 `LLMClient`：构造入参 `inner: LLMClient`、`store: FixtureStore`、`mode: Literal["record","replay","passthrough"]`、`run_id`、`node_pos_provider`（从 runtime 取 turn/step 坐标）。其 `chat()`：算 `FixtureKey` → `store.get` 命中则 HMAC 校验后返缓存（record/replay 皆命中即返，省 token）；replay 未命中 → `raise ReplayMiss`（**绝不打真 API**，R11）；record 未命中 → 调 `inner.chat` → 过 `ControlledTranslator` → `store.put`。

### 4.4 新增 fixture/store/翻译/度量 —— 新文件

- `agent/replay/fixture.py`：`ModelPin`/`FixtureKey`/`LLMFixture` + `compute_hmac(record, key)` / `verify_hmac(...)`。HMAC key 经 `security.keystore.derive_key_from_password`（**复用** `keystore.py:173-176`）派生，存 keystore 名 `llm_fixture_hmac`。
- `agent/replay/store.py`：`FixtureStore`，落 `DATA_ROOT/artifacts/llm_fixtures/`（`paths.py:9` `DATA_ROOT` + 仿 `RUN_ROOT` 模式）。append-only：`put` 拒覆盖已存在 key（除非内容 HMAC 相同=幂等）；`tombstone(key)` 软删不减 N；敏感 `request` 字段经 Fernet 加密落盘（**复用** `keystore.FernetFileBackend` 模式，`keystore.py:131-170`）。
- `agent/replay/translation.py`：`ControlledTranslator`，入 `LLMResponse` + `schema_ref` → 校验 tool_calls 是否符合 `tool_schema.py` 的 JSON schema → 返 `(status, tool_calls)`；语义不变量钩子（如 `leverage_max ≤ 注入上限`）。
- `agent/replay/repro.py`：`ReproLevel` + `pass_caret_k(fixtures: list, level) -> float`（pass^k=k 次全同，dossier §7.3 严口径，**非** pass@k）。
- 新增 `agent/replay/__init__.py` 导出上述符号；`paths.py:14-17` `ensure_runtime_dirs()` 加一行 `(DATA_ROOT/"artifacts"/"llm_fixtures").mkdir(parents=True, exist_ok=True)`。

### 4.5 runtime 注入坐标 + 翻译门 —— `agent/agent_runtime.py`

- `AgentRuntime.__init__`（`agent_runtime.py:47-57`）新增 keyword `run_id: str | None = None`；loop 里用 `enumerate` 暴露 `step_idx`（`agent_runtime.py:69` `for _ in range(...)` → `for step_idx in range(...)`），传给 `RecordingLLMClient`（经 `node_pos_provider`），使 fixture_key 编码图中位置。
- `agent_runtime.py:70` `response = self._llm.chat(...)`：**不改这一行的形态**，因为 `RecordingLLMClient` 就是个 `LLMClient`，从 `main.py` 注入即生效（依赖倒置，runtime 无感）。
- **翻译门**：`agent_runtime.py:77` `if not response.tool_calls:` 之前插一道——若 `response` 的 fixture `translation_status == "human_confirm_required"`，则不进 `:81-107` 的派发，把 turn 标 `succeeded=False` + 挂起态返回，交部件 04。

### 4.6 工厂 + 入口接线 —— `agent/llm_providers.py:406` 与 `main.py:207-230`

- `make_llm_client`（`llm_providers.py:406-468`）末尾（`:468` `return DevLocalLLM()` 之前的 return 路径）**不改内部**；改为在 `main.py:_current_agent_llm()`（`main.py:207-210`）外层包：
  ```python
  def _current_agent_llm():
      inner = make_llm_client(keystore=KEYSTORE)
      mode = os.environ.get("LLM_REPLAY_MODE", "record")  # record|replay|passthrough
      return RecordingLLMClient(inner, store=FIXTURE_STORE, mode=mode, run_id=...) if mode!="passthrough" else inner
  ```
- `main.py:217-230` `_agent_runtime()`：`AgentRuntime(_current_agent_llm(), run_id=<当前 run_id>)`。`FIXTURE_STORE` 在 `main.py` 模块级单例（仿 `main.py:200-201` `RISK_MONITOR` 模式）。
- `agent/__init__.py:14-50`：导出 `RecordingLLMClient` / `FixtureStore` / `LLMFixture` / `ReproLevel`，加进 `__all__`。

### 4.7 不碰的冻结区

前端 `RunDetailPage`「收益概述」既有逻辑**零改动**。三级可复现度量/fixture 凭证若要上面板，只能**新增**字段/新页签，不动既有收益概述显示逻辑。

---

## 5. 对抗式测试规约（按 TEST_STANDARD：种已知坏→门必抓→断言什么）

> 文件 `app/backend/tests/test_llm_record_replay.py`。每条都是「种一个已知的坏，门必须抓住」，不是覆盖率。

### 5.1 种已知坏 → 门必抓（①）

| # | 种什么已知坏 | 哪个门必抓 | 断言 |
|---|---|---|---|
| **A1 · replay 偷跑真 API 探针** | replay 模式下喂一个 store 里**没有**的 fixture_key | R11 重放只读工件门 | `RecordingLLMClient.chat` `raise ReplayMiss`；用 mock inner client 断言其 `chat` **调用次数 == 0**（真 API 一次都不许打）。门坏（fallback 去打真 API）→ mock 被调 → fail。 |
| **A2 · fixture 篡改探针** | 取一条落盘 fixture，篡改其 `response.tool_calls`（如把 `leverage_max:3` 改 `30`），**不**更新 `integrity` | HMAC 完整性门 | `store.get` / `verify_hmac` 必 `raise IntegrityError`、绝不返回被改内容。门坏（裸读不校验）→ 脏数据进下游 → fail。 |
| **A3 · cache key 碰撞探针** | 同 `node_pos` + 同 prompt，但 `run_index` 不同 / `upstream_digest` 不同（模拟 best-of-N 两分支） | 内容寻址 key 门（dossier §7.3 AI21） | 两次 `FixtureKey.compute()` **必不相等**；store 里并存两条、互不覆盖。门坏（key 只哈 prompt）→ 第二分支错命中第一条 → fail。 |
| **A4 · 翻译「确定地错」探针** | 注入一个 schema 合规但语义越界的 tool_call（`leverage_max=30` 超注入上限 3） | 翻译层语义不变量门（dossier §8.4） | `ControlledTranslator` 返 `status="human_confirm_required"`；`AgentRuntime` **不派发**该 tool_call（断言 tool handler 未被调用）。门坏（schema 合规即放行）→ 错误被确定性放大 → fail。 |
| **A5 · fingerprint 静默漂移探针** | 录两条同 `(provider, model_id)` fixture，第二条 `system_fingerprint` 不同 | fingerprint 漂移检测门（dossier §5.4/§8.3） | `store.put` 第二条时产 `fingerprint_drift` 事件；断言事件被发出、且**不静默吞掉**。门坏（不记 fingerprint）→ 无事件 → fail。 |
| **A6 · 别名冒充版本探针** | ModelPin.model_id 传别名（如 `"claude-sonnet-4-5"` 这种会滚动的别名）| 不可变版本门（dossier §5.4） | `ModelPin` 构造或 `store.put` 对已知别名模式**告警/拒绝**（至少标 `model_id_is_alias=True` 并发警告事件）。门坏（别名当不可变 id）→ 复现承诺随供应商滚动作废且无痕 → fail。 |

### 5.2 变形/不变量测试（②）

| # | 变形 | 必然结果 | 断言 |
|---|---|---|---|
| **B1 · replay 逐字节确定** | 同一 run 连续 replay 两遍 | decision 级以上必逐字节相同（读同 fixture） | 两遍 `response` canonical_json **逐字节相同**（这正是 00 §T9 要的「重放逐字节相同」防偷跑 LLM）。 |
| **B2 · 翻译被夹死不静默降质** | 同 prompt 在 record 模式跑两次（真 client mock 成返不同措辞但同 tool_call 结构）| decision 级可复现：决策不变、措辞可变 | `pass_caret_k(level=DECISION)` 在「tool_call 结构相同」时 == 1.0；同时 dossier §8.6 张力：若 `pass_caret_k(level=SEMANTIC)` 因强制 temp=0 反而异常低，需在报告里**显式标注**而非藏（断言报告含 `caveat`）。 |
| **B3 · 三级度量解耦** | 构造 action 级全同但 decision 级分歧的 fixture 组 | 三级 pass^k 必各自独立、不互相污染 | `pass_caret_k(action) > pass_caret_k(decision)` 成立；面板字段含「高确定性≠高正确性」caveat（dossier §6.6/§8.5，防被误读为质量分）。 |

### 5.3 交叉验证（③）

| # | 种什么 | 断言 |
|---|---|---|
| **C1 · 两套独立实现对账 fixture_key** | 用一份独立的「朴素 canonical_json + sha256」参考实现重算 `FixtureKey.compute()` | 两实现对同一输入**必同**；不一致 BLOCK（防 key 算法实现 bug 让命中漂移）。 |
| **C2 · 验证官 consistency_check 措辞守门** | 让 fixture 走「异模型重放对账」路径，检查输出记录字段名 | 记录字段叫 `consistency_check`，**断言 `"independent" not in 记录 and "组织独立" not in 记录`**（00 §1.2-G / R7 红线）；含 `verdict_id` 引用部件 12。门坏（漏出"independent validation"）→ fail。 |

### 5.4 幂等/恢复（④）

| # | 种什么 | 断言 |
|---|---|---|
| **D1 · put 幂等** | 同 fixture_key + **内容相同**的 fixture put 两次 | 第二次不新建第二条、不报错（内容 HMAC 一致即幂等返存量）。**内容不同**的同 key put → `raise`（append-only 不许静默覆盖）。 |
| **D2 · tombstone 不减 N** | tombstone 一条 fixture 后查 honest-N 计数视图 | distinct fixture_key 计数**不减少**（honest-N 不可改小，R8/管太宽分界）；fixture 标 `tombstoned=True` 但留痕。门坏（删 fixture 刷低 N）→ 计数下降 → fail。 |
| **D3 · 崩溃中段恢复读 fixture** | record 跑到第 2 step 崩，重启 replay | 前 2 step 从 fixture 读（mock inner `chat` 调用 0 次覆盖已录 step）、只第 3 step 起需 record；`node_pos` 坐标稳定使 key 对得上。 |
| **D4 · 一次性消费留痕（R12）** | 对 `frozen_oos` 类 fixture 第二次读 | 第一次读后 `consumed=True`；第二次读产 `consumed_again` 告警事件（防自欺非防恶意，诚实标注）。 |

### 5.5 裁决措辞（⑤）

| # | 断言 |
|---|---|
| **E1** | 任何复现报告/凭证文本**不得**出现「可信/安全/已合规」；必须是「decision 级证据充分 / bitwise 未验证（托管 API 不可达）/ 供应商换模型后只能重放录制结果」式措辞（dossier §5.7/§8.3 残余不确定性披露）。断言报告字符串匹配白名单措辞、命中黑名单词即 fail。 |

### 5.6 经验网（⑥）

| # | 断言 |
|---|---|
| **F1 · record↔replay 对账** | 同一 turn 的 record 跑结果与 replay 跑结果，decision 级必一致；对不上=指向 bug（fixture 漏字段/key 不稳）→ 测试 fail 并打印 diff。这是本部件版的「回测↔paper 对账」。 |

---

## 6. 与其他脊柱部件的契约（产出/消费的共享 schema）

> 以 00-contracts-and-coherence.md 为权威，本部件**产** LLM 节点的 fixture 工件、**消费**上游 id。

### 6.1 本部件产出

| 字段 | 口径 | 谁消费 |
|---|---|---|
| `fixture_key` = `"llmfx-" + sha256(canonical(FixtureKey 全字段))[:16]` | **同 node_id 哈希族**（00 §1.2-E：sha256[:16]）。一个 LLM 节点的 `node_id` 即其 `fixture_key`；`checkpoint_id = node_id`（00 §1.2-C 裁定）。 | 部件 01 内核（挂 DAG）、部件 03 谱系（PROV Entity）、部件 04（replay_ref）、部件 12（重放对账） |
| `LLMFixture`（含 `model_pin`/`request`/`response`/`integrity`） | append-only + tombstone；HMAC 完整性 | 部件 12 验证官逐字节重放；部件 03 账本 |
| `event: fingerprint_drift` / `consumed_again` / `model_id_is_alias` | C6 生命周期事件，发谱系总线（OpenLineage 风格 + 业务事件） | 部件 03 谱系 |
| `repro_report{ pass_caret_k{action,signature,decision}, caveat }` | pass^k 严口径；**与 CSCV/PBO/DSR 面板分区**（dossier §6.6/§8.5） | 面板（新增页签，不动 RunDetailPage 收益概述） |

### 6.2 本部件消费

| 字段 | 来源 | 用法 |
|---|---|---|
| `run_id`（C1，`run-{uuid[:12]}`，`experiments/store.py:30-31`） | 部件 03 RunStore | 作 fixture `node_pos` 前缀，建 run→fixture 一对多映射（**不混用**：run_id 是 uuid 句柄、fixture_key 是内容哈希，00 §C1 警告） |
| `config_hash`（C2，部件 03 权威定义 `sha256(canonical(因子+universe+窗口+阈值))[:16]`，**排除** name/desc） | 部件 03 | fixture 可选挂 `config_hash` 让「同 config 反复试」的 LLM 调用被聚类计 N（honest-N），本部件**不自己算** config_hash |
| `dataset_version`（C3，`sha256(fp_blob)[:16]`，`data_packages.py:70` 已实做） | 数据访问层 | `frozen_oos` 类 fixture 绑定它，配合 `consumed` 一次性消费 |
| `verdict_id`（C9，部件 12 验证官产） | 部件 12 | `consistency_check` 记录引用它；**禁** "independent" 措辞（R7） |
| `effect_idempotency_key`（C8 拆分后，00 §1.2-F） | 部件 04 审批 | 翻译层 `human_confirm` 挂起后，下游真副作用用它去重——本部件只**传递不消费**（本部件无交易副作用） |

### 6.3 命名纪律（避坑）

- 本部件 fixture 的「重复 put 去重键」是 `fixture_key` 本身（内容寻址自带幂等），**不叫** `request_idempotency_key`（那是 HTTP 端点层，00 §1.2-F），不与交易 `effect_idempotency_key` 混。
- 异模型重放对账记录**必须**叫 `consistency_check`，含 `verdict_id`；任何文本禁出现 "independent validation"/"组织独立"（R7 + 00 §1.2-G 红线）。

---

## 7. 开放问题 / 风险（落地前必答）

1. **HMAC key 与 fixture 同机 = 无真访问控制边界（R12 诚实承认）。** 本部件 HMAC 只能「防自欺/防意外篡改」，防不了能读 keystore 的本机恶意进程。落地前须定：HMAC key 是否走 keyring（`KeyringBackend`，`keystore.py:80`）而非 Fernet 文件、是否给 fixture 目录设 0700。**裁定建议**：key 走 keyring、文本明示「防篡改非防恶意」，不宣称密码学不可抵赖。

2. **托管 API 路线 bitwise 根本不可达，连 decision 级都受供应商静默更新制约（dossier §8.3）。** 供应商换模型后「可回放凭证」只能重放**录制结果**、无法重放真实模型。必答：fingerprint 漂移后是否强制触发部件 12 重新验证？**裁定建议**：drift 事件 → 自动给受影响 confirmatory 结论打「待重验」标，且对用户/合规明说此供应商依赖。

3. **「把 LLM 夹得越死、翻译越可能失真」的张力未量化（dossier §8.6 Stochastic CHAOS 反方）。** 强制 temp=0 + constrained decoding 可能降低意图理解质量。必答：翻译层是否对 `human_confirm` 率设监控阈值（兜底是否过频=翻译质量塌了）？**裁定建议**：把 `human_confirm` 率与 schema_invalid 率进 repro_report，超阈值告警，而非默默让用户点确认。

4. **cache key 的 `upstream_digest` 边界到哪。** 上游依赖摘要若含全部历史 messages，则任何前序微小变化都换 key（命中率塌、token 省不下来）；若太粗则分支碰撞。必答：`upstream_digest` 取「上一 fixture_key + 本步注入的 tool 返回摘要」是否足够稳。**裁定建议**：先按此实现，配 A3 碰撞探针 + 命中率监控，迭代收敛。

5. **fixture 里 prompt/tool 返回含敏感数据（含可能的持仓/token 痕迹）+ 投毒面（dossier §8.1，键碰撞攻击 arXiv 2601.23088）。** 必答：`request` 字段加密落盘是否覆盖所有敏感路径；replay 命中前是否需对 `prompt_digest` 做抗碰撞校验（避免 locality-key 碰撞攻击）。**裁定建议**：`request` 全量 Fernet 加密、`fixture_key` 用抗碰撞 sha256（非语义 locality hash），二者分离。

6. **pass^k 进面板与 CSCV/PBO/DSR 的口径竞争（dossier §8.5）。** pass^k 是 LLM 层 case-level 全同口径，若与回测稳健性指标同框会被非技术用户误读为「模型质量分」。必答：面板分区方案（新页签 vs 同页签明确分区）——但**不得改 RunDetailPage 收益概述既有逻辑**（冻结）。**裁定建议**：独立「Agent 可复现」页签，与收益概述物理分离 + caveat。
