# 07 · HITL 审批门双通道(探索/确证) + promote 改造成带审批门状态机 + 幂等恢复
> 脊柱 build-ready 设计 · 接 R1–R29 决策 · 含 file:line 接线 + 对抗式测试 · Opus 4.8

---

## 1. 职责与边界（接哪些 R 决策，本部件负责/不负责什么）

本部件把"裸状态翻转的 `promote()`"升级成**带审批门的状态机**，并立起双通道审批层与幂等恢复语义。它是 R1/R8 honest-N 账本与 R7 交易所侧硬边界之间的"闸门"。

**接的 R 决策**
- **R1=C honest-N**：探索自由，但晋级到"可下注 confirmatory 结论"（staging/production）时强制显式提交试验账本——本部件就是那个"强制提交"的关卡。
- **R2 多证据三角**：promote 到 staging/production 必须附 DSR+PBO+bootstrap CI **同向**证据快照，缺任一即拒绝并返缺口清单；红绿灯一键下钻（暴露有效 N / 试验聚类 / 适用域空洞）。
- **R5 守门器自身模型风险明示**：门内裁决措辞必须标注"DSR/PBO/honest-N 本身是有模型风险的守门器"，不得说"已验证安全"。
- **R6 监管锚 NIST**：审批记录字段映射 NIST AI RMF（GOVERN/MAP/MEASURE/MANAGE）四联，**不宣称 SR11-7 合规**（已被 SR26-2 取代且划出 agentic）。
- **R7 真强制只在交易所侧 + 诚实非组织独立**：本部件左侧是"证据治理"（approver≠creator 是**约定 + 防篡改证据**，诚实标注非组织独立）；右侧门后挂的才是真硬限额（沿用既有 `SafetyService` 阶梯的单笔 notional cap）。"生成≠验证"靠独立验证官 agent（异模型/异种子/异数据切片）产出的 `verification_record_id`。
- **R11 重放读工件**：审批门里若引用 LLM 产出的风险陈述/独立验证结论，落不可变 fixture，恢复时**读已落盘工件、绝不重跑 LLM**。
- **R12 留出集隔离=约定 + 防篡改 + 一次性消费**：过拟合证据快照里若用到 OOS，诚实标注"防自欺非防恶意"。
- **P2 假设卡不挡探索**：探索通道（标 exploratory）零门或仅事后记录；只有 confirmatory 晋级才冻结假设卡 + 走重门。
- **管太宽分界**：研究侧旋钮不锁；本部件只在**动真钱/不可逆/外部可见的执行侧**（promote 到 production、门后下单/划转）上硬锁。

**本部件负责**
1. `promote()` 从裸三行翻转 → 审批门状态机（pending→approved/rejected/timed_out），晋升 staging/production 强制三要件校验。
2. 双通道分流：探索类轻量 / 确证类（上实盘/动钱/加杠杆/删历史）durable interrupt-and-approve，可挂数天。
3. 幂等恢复到下单/划转级（`idempotency_key` 去重，绝不重复副作用）。
4. 超时默认动作按 `action_kind` 分流（止损类到期默认放行 / 动钱类默认拒绝）。
5. 门后真实硬限额钩子（审批≠授权）。

**本部件不负责**（明确划界，防 scope 蔓延）
- 不实现 DSR/PBO/bootstrap 本体——这些已在 `eval/{dsr,pbo,bootstrap}.py`，本部件**只消费其快照**。
- 不实现 honest-N 账本本体（部件 02/试验账本负责），只消费 `config_hash` + `N_eff` + 试验聚类。
- 不实现独立验证官 agent 本体（部件 08 负责），只校验它产出的 `verification_record_id` 存在且 `approver≠creator`。
- 不实现交易所连接器/真实下单（`execution/*` 负责），只在门后调用其幂等下单接口并核对副作用边界。
- 不改前端 `RunDetailPage`"收益概述"页既有逻辑（已冻结）。

---

## 2. 现有代码现状（file:line：有什么、缺什么、哪里是 dossier 点名的洞）

路径根：`app/backend/app/`

**dossier 点名的洞**
- `experiments/store.py:232-238` `ModelRegistry.promote()`：**三行裸状态翻转**
  ```python
  232  def promote(self, model_id: str, version: int, stage: ModelStage) -> ModelVersion:
  233      for v in self.list_versions(model_id):
  234          if v.version == version:
  235              v.stage = stage          # ← 裸翻转，无审批/无证据/无 approver
  236              self._store.append(v.to_dict())
  237              return v
  238      raise KeyError(...)
  ```
  缺：审批门、approver≠creator、过拟合证据快照、独立验证记录、双通道、超时默认、幂等。任何人任何时刻能把任意 version 直接拍到 `production`。
- `main.py:405-410` `promote_model` 端点：直接转调上面裸 `promote()`，`payload` 只取 `version` + `stage`，**无 approver、无证据 id**。

**可复用的现成基建（不要重造）**
- `experiments/store.py:23` `ModelStage = Literal["dev","staging","production","archived"]`——状态机的状态集已在。
- `experiments/store.py:65-78` `ModelVersion` dataclass（`stage` 字段在 line 68）——审批门要在它旁边挂证据引用。
- `experiments/store.py:80-103` `_JsonlStore`（append-only + 容损读）——审批门事件可复用同一 append-only 模式（接 R28/R29 全保留）。
- `eval/dsr.py:41` `deflated_sharpe_ratio(returns, n_trials, periods_per_year)` → DSR∈[0,1]；`eval/pbo.py:58` `cscv_pbo(...) -> PBOResult(pbo,...)`（`pbo.py:21` dataclass，含 `lambda_logit_mean` 审计字段）；`eval/bootstrap.py:23` `bootstrap_sharpe_ci(...) -> BootstrapCI(estimate,lower,upper,n_boot)`（`bootstrap.py:13` dataclass）——**三角证据的本体源**。
- `trading/safety.py:187` `SafetyService` + `safety.py:99` `LiveLadderState` + 文件头 `safety.py:16-21` 的 notional 阶梯（level_2 $50 / level_3 $200 / level_4 $1000 单笔上限）——**门后真实硬限额**已存在，promote-to-production 的门后授权必须落到这个阶梯，而非自造。
- `copy_trade/beta.py:113` `make_idempotency_key(signal_id, follower_id)` + `beta.py:124-152` `record_dispatch`（INSERT 前 `is_dispatched` 查重，已 dispatched 抛 `IdempotencyViolation`）+ `copy_trade/executor.py:82-87` 的"duplicate dispatch (idempotent skip)"——**幂等到下单级的现成范式**，恢复语义直接照搬这套"先查 key 再执行、命中即 skip 绝不重发"。
- `dag/engine.py:52` `DAGTask.idempotency_key` + `engine.py:53` `sla_seconds`——DAG 层已有 idempotency_key 与 SLA 概念，审批门的 durable interrupt 与这套对齐。
- `execution/generic_trading.py:123` / `binance_um_futures.py:132` / `binance_spot.py:109`：`client_order_id` 幂等已贯穿下单层——门后幂等键最终落到这里。

**缺什么（本部件要补）**
1. 审批门记录的 schema + append-only store（`ApprovalGate`）。
2. `promote()` 的三要件校验 + 状态机 + 缺口清单返回。
3. 双通道分流策略（exploratory vs confirmatory）。
4. 超时默认动作引擎（按 action_kind 分流）。
5. 恢复入口（resume）+ 门后幂等执行护栏。
6. main.py 端点改造（收 approver/verification_record_id/evidence_snapshot，返缺口清单）+ 新增 approve/reject/resume 端点。

---

## 3. 目标设计（schema/Pydantic 草图 + 模块布局 + 状态机）

### 3.1 模块布局

新增 `app/backend/app/approval/`（与既有 `experiments/`、`trading/`、`copy_trade/` 同级）：
```
approval/
  __init__.py
  schema.py        # ApprovalGate / EvidenceSnapshot / GateDecision dataclass + 校验异常
  store.py         # ApprovalGateStore：append-only JSONL（复用 _JsonlStore 模式）
  gate.py          # ApprovalGateService：open_gate / approve / reject / resume / on_sla_expire
  channels.py      # 双通道分流：classify_channel(action_kind) + 超时默认表
  hard_limits.py   # 门后硬限额钩子：把 approved 的 production promote 绑到 SafetyService 阶梯
```
`promote()` 不再自己翻转 stage，而是委托 `ApprovalGateService`。`ModelRegistry` 持有一个 `gate_service` 引用（构造期注入，默认 None=向后兼容 dev/archived 直翻）。

### 3.2 schema 草图（dataclass，append-only 落 JSONL）

```python
# approval/schema.py
GateChannel  = Literal["exploratory", "confirmatory"]
ActionKind   = Literal["promote_staging","promote_production",
                       "live_order","transfer","leverage_up","data_delete",
                       "stop_loss","risk_reduction"]
GateDecision = Literal["pending","approved","rejected","timed_out"]
TimeoutDefault = Literal["default_reject","default_allow","escalate"]

@dataclass
class EvidenceSnapshot:
    # R2 三角证据快照（promote staging/production 必填，内容不可空）
    config_hash: str               # R8 content-addressed，绑到那一本账
    dataset_version: str           # R12 留出集隔离锚点
    n_eff: int                     # honest-N 有效试验数（收益相关聚类后），不可手填改小
    n_trials_raw: int              # 原始遍历数（用于 DSR n_trials）
    dsr: float                     # eval/dsr.py:41 产出 ∈[0,1]
    pbo: float                     # eval/pbo.py:58 产出 ∈[0,1]
    bootstrap_ci: tuple[float,float]  # eval/bootstrap.py:23 (lower, upper)
    bootstrap_estimate: float
    champion_challenger: dict      # {"champion_id","challenger_id","verdict","delta_sharpe"}
    returns_sha256: str            # 收益序列内容指纹（防换序列绕过 / 复算对账锚）
    triangle_aligned: bool         # 三者同向放行（派生，落盘留痕）
    applicability_gaps: list[str]  # 适用域空洞（R2 一键下钻暴露）

@dataclass
class ApprovalGate:
    gate_id: str
    model_id: str
    version: int
    from_stage: ModelStage
    to_stage: ModelStage
    channel: GateChannel
    action_kind: ActionKind
    created_by: str                # creator（agent 或 user）
    created_at_utc: str
    # —— 三要件（晋升 staging/production 缺任一即拒绝）——
    verification_record_id: str | None   # (a) 独立验证官记录（异模型/种子/切片）
    approver: str | None                 # (b) 审批人；硬约束 approver != created_by
    evidence: EvidenceSnapshot | None    # (c) 过拟合证据快照
    # —— durable interrupt / 超时 ——
    idempotency_key: str                 # 恢复重跑去重（门后副作用级）
    sla_deadline_utc: str | None         # 到期触发默认动作
    on_timeout: TimeoutDefault
    escalate_to: str | None
    # —— 决策 ——
    decision: GateDecision               # pending / approved / rejected / timed_out
    decision_reason: str | None          # 强制非空、反套话（confirmatory 必填）
    risk_restated: str | None            # restate-the-risk 输入
    decided_at_utc: str | None
    gap_list: list[str]                  # 缺口清单（拒绝时返回，何处不满足）
    # —— 门后副作用边界 ——
    side_effect_executed: bool           # 门后动作是否已落地（幂等护栏读这个）
    side_effect_ref: str | None          # client_order_id / transfer_id / ladder_txn_id
    nist_phase: str                      # R6：MEASURE→MANAGE 映射标签（非合规宣称）
```

### 3.3 状态机

```
                       open_gate(model_id, version, to_stage, created_by, ...)
                                          │
              ┌───────── classify_channel(action_kind) ─────────┐
              │                                                  │
        exploratory                                        confirmatory
   (to_stage∈{dev,archived})                       (to_stage∈{staging,production} 或
              │                                     action_kind∈高影响集)
   直接 approved（仅事后记录，                              │
   不冻结假设卡 P2）                          validate_three_requirements()
              │                                            │
              ▼                              ┌─────────────┴──────────────┐
         [approved]                      三要件齐全                   缺任一
                                            │                          │
                                       decision=pending          decision=rejected
                                    （durable interrupt，          + gap_list（缺口清单）
                                      落盘，可挂数天）              ← 永不进入 pending
                                            │
                        ┌───────────────────┼───────────────────────┐
                   approve(approver,    reject(approver,         SLA 到期
                   reason,risk_restated) reason)              on_sla_expire()
                        │                   │                       │
              approver==created_by?      [rejected]        按 action_kind 分流：
                        │                                  stop_loss/risk_reduction
              是→raise(approver≠creator)                   → default_allow→[approved]
              否→[approved]                                add_position/transfer/
                        │                                  leverage_up → default_reject
                        ▼                                  → [timed_out]
            after_approved_execute()                       其它 → escalate
            （门后硬限额 + 幂等护栏）
                        │
       resume(gate_id)  │（崩溃/重启后从最近落盘 gate 恢复）
                        ▼
        if side_effect_executed: skip（绝不重发）
        else: hard_limit_check() → execute(idempotency_key) → mark executed
```

### 3.4 三要件校验 + 缺口清单（伪代码）

```python
# approval/gate.py
def validate_three_requirements(gate) -> list[str]:
    gaps = []
    if gate.to_stage in ("staging", "production"):
        # (a) 独立验证记录
        if not gate.verification_record_id:
            gaps.append("缺独立验证记录(verification_record_id)：'生成≠验证'未满足")
        # (b) approver ≠ creator —— 注意：这是在 approve() 时才有 approver，
        #     open 阶段只校验"声明了需要一个不同于 creator 的 approver 槽位"
        # (c) 过拟合证据快照三角
        ev = gate.evidence
        if ev is None:
            gaps.append("缺过拟合证据快照(DSR+PBO+bootstrap CI)")
        else:
            if ev.dsr is None:        gaps.append("证据缺 DSR")
            if ev.pbo is None:        gaps.append("证据缺 PBO")
            if ev.bootstrap_ci is None: gaps.append("证据缺 bootstrap CI")
            if not ev.champion_challenger.get("verdict"):
                gaps.append("缺 champion/challenger 结论")
            # R2 同向放行：DSR 高 + PBO 低 + CI 下界>0 才算三角对齐
            if ev.dsr < DSR_FLOOR or ev.pbo > PBO_CEIL or ev.bootstrap_ci[0] <= 0:
                gaps.append(
                    f"三角不同向：DSR={ev.dsr}(需≥{DSR_FLOOR}) "
                    f"PBO={ev.pbo}(需≤{PBO_CEIL}) CI下界={ev.bootstrap_ci[0]}(需>0)"
                )
    return gaps   # 空=通过；非空=拒绝并把 gap_list 返给调用方

def open_gate(...):
    channel = classify_channel(action_kind, to_stage)
    if channel == "exploratory":
        return _record_and_approve(...)         # P2：探索不挡
    gaps = validate_three_requirements(gate)
    if gaps:
        gate.decision = "rejected"; gate.gap_list = gaps
        store.append(gate); return gate          # 缺口清单，绝不进 pending
    gate.decision = "pending"
    gate.sla_deadline_utc = now() + sla_for(action_kind)
    store.append(gate); return gate              # durable interrupt
```

### 3.5 approve / 恢复 / 门后硬限额（伪代码）

```python
def approve(gate_id, approver, reason, risk_restated):
    gate = store.get(gate_id)
    if gate.decision != "pending":
        raise GateStateError(f"非 pending 不可批准: {gate.decision}")
    if approver == gate.created_by:                      # (b) 硬约束
        raise ApproverEqualsCreator("approver 不得等于 creator")
    if gate.channel == "confirmatory" and not _is_substantive(reason):
        raise EmptyReason("confirmatory 审批理由不可空/不可纯套话")
    gate.approver = approver; gate.decision_reason = reason
    gate.risk_restated = risk_restated; gate.decision = "approved"
    gate.decided_at_utc = now(); store.append(gate)
    return _after_approved_execute(gate)

def _after_approved_execute(gate):
    # 幂等护栏（照搬 copy_trade/executor.py:82-87 范式）
    if gate.side_effect_executed:                        # ④ 重复 resume 命中存量
        return gate                                     # 绝不重发
    if gate.to_stage == "production" and gate.action_kind in MONEY_ACTIONS:
        hard_limits.enforce(gate)                       # R7 门后真硬限额（SafetyService 阶梯）
    ref = _execute_with_key(gate)                       # 用 idempotency_key 下单/翻 stage
    gate.side_effect_executed = True; gate.side_effect_ref = ref
    store.append(gate); return gate

def resume(gate_id):
    # 崩溃/重启后：从最近落盘 gate 读状态，不重跑前面的副作用
    gate = store.get(gate_id)                            # 读已落盘工件（R11）
    if gate.decision == "approved":
        return _after_approved_execute(gate)            # 内部 side_effect_executed 查重
    if gate.decision in ("rejected","timed_out"):
        return gate                                     # record_and_halt
    return gate                                         # 仍 pending：继续等
```

### 3.6 双通道分流 + 超时默认表

```python
# approval/channels.py
HIGH_IMPACT = {"live_order","transfer","leverage_up","data_delete","promote_production"}
def classify_channel(action_kind, to_stage):
    if to_stage in ("staging","production") or action_kind in HIGH_IMPACT:
        return "confirmatory"
    return "exploratory"

TIMEOUT_DEFAULT = {            # dossier §5/§6：延迟即风险 vs 动钱默认拒
    "stop_loss":      "default_allow",
    "risk_reduction": "default_allow",
    "add_position":   "default_reject",
    "transfer":       "default_reject",
    "leverage_up":    "default_reject",
    "promote_production": "default_reject",
}  # 缺省 → "escalate"
```

> 阈值常量 `DSR_FLOOR / PBO_CEIL` 不硬编为信仰值：依 R 决策 "t>3 不硬编"，做成可配置档位（研究侧旋钮不锁，但**显示通缩真相**且记入 honest-N），默认给保守档并在裁决里明示"这是档位选择、非物理常数"。

---

## 4. 代码接线点（逐条 file:line：改哪行/在哪加新文件/动了哪个函数签名）

> 全部基于实际打开核实的行号。

**A. 新增模块（5 个新文件）**
- 新建 `app/backend/app/approval/__init__.py`：导出 `ApprovalGate`、`EvidenceSnapshot`、`ApprovalGateService`、`ApprovalGateStore`、`classify_channel`、异常类。
- 新建 `app/backend/app/approval/schema.py`：§3.2 的 dataclass + 异常（`ApproverEqualsCreator`、`MissingEvidence`、`GateStateError`、`EmptyReason`）。
- 新建 `app/backend/app/approval/store.py`：`ApprovalGateStore(root)`，复用 `experiments/store.py:80-103` `_JsonlStore` 同款 append-only + 容损读（落 `data/experiments/approval_gates.jsonl`）。
- 新建 `app/backend/app/approval/gate.py`：`ApprovalGateService`（open_gate/approve/reject/resume/on_sla_expire/validate_three_requirements）。
- 新建 `app/backend/app/approval/channels.py` + `hard_limits.py`：§3.6 分流表 + 门后硬限额钩子。

**B. 改 `experiments/store.py`（核心洞）**
- `store.py:65-78` `ModelVersion`：新增字段 `last_gate_id: str | None = None`（指向最近一次 promote 审批门，append-only 留痕）。向后兼容（默认 None）。
- `store.py:204-208` `ModelRegistry.__init__`：签名加可选注入 `gate_service: ApprovalGateService | None = None`（默认 None=维持 dev/archived 直翻、不破坏现有 761 测试里 `test_experiments.py:50` 的 dev 路径；但**production/staging 路径在 None 时必须 raise**，不再允许裸翻）。
- `store.py:232-238` `promote()`：**这是 dossier 点名的三行洞**。改造签名为：
  ```python
  def promote(self, model_id, version, stage, *,
              created_by=None, approver=None,
              verification_record_id=None, evidence=None,
              decision_reason=None, risk_restated=None) -> ModelVersion | GateRejection:
  ```
  逻辑：`stage in ("staging","production")` → 委托 `self._gate_service.open_gate(...)`；若 gate.decision=="rejected" → 返回带 `gap_list` 的 `GateRejection`（**不翻 stage**）；若 "approved" → 才执行原 line 235 的 `v.stage = stage` + append。`dev/archived` 保持原直翻路径（探索通道）。

**C. 改 `main.py`（端点）**
- `main.py:92` `MODEL_REGISTRY = ModelRegistry(DATA_ROOT / "experiments")`：改为注入 gate_service：
  ```python
  APPROVAL_STORE = ApprovalGateStore(DATA_ROOT / "experiments")
  GATE_SERVICE = ApprovalGateService(APPROVAL_STORE, safety_service=SAFETY_SERVICE)
  MODEL_REGISTRY = ModelRegistry(DATA_ROOT / "experiments", gate_service=GATE_SERVICE)
  ```
  注意 `SAFETY_SERVICE` 在 `main.py:106` 定义——需把 `SAFETY_SERVICE` 上移到 `MODEL_REGISTRY` 之前，或对 gate_service 延迟绑定 safety_service（二选一，推荐上移，纯顺序调整无逻辑改动）。
- `main.py:405-410` `promote_model` 端点：扩 payload 解析，转调新签名，并把拒绝→422 + gap_list：
  ```python
  @app.post("/api/models/{model_id}/promote")
  def promote_model(model_id, payload=Body(...), user=Depends(require_user_dependency)):
      result = MODEL_REGISTRY.promote(
          model_id, int(payload["version"]), payload["stage"],
          created_by=payload.get("created_by"),
          approver=payload.get("approver"),
          verification_record_id=payload.get("verification_record_id"),
          evidence=payload.get("evidence"),
          decision_reason=payload.get("decision_reason"),
      )
      if isinstance(result, GateRejection):
          raise HTTPException(422, detail={"rejected": True, "gaps": result.gap_list})
      return result.to_dict()
  ```
  （`require_user_dependency` 已用于 `main.py:2162`/`2581` 等端点，creator 默认取 `user.user_id`。）
- 在 `main.py:410` 之后**新增 3 个端点**：`POST /api/models/{model_id}/gates/{gate_id}/approve`、`.../reject`、`.../resume`，分别转调 `GATE_SERVICE.approve/reject/resume`；approve 收 `approver`/`reason`/`risk_restated`，approver==creator → 422。新增 `GET /api/approval/gates/{gate_id}` 供前端下钻（R2 一键暴露 N_eff/聚类/适用域空洞）。

**D. 门后硬限额接线（R7，approval≠authorization）**
- `approval/hard_limits.py` 的 `enforce(gate)`：production 且 `action_kind∈MONEY_ACTIONS` 时，读 `SafetyService.get_ladder(user).current_level`（`trading/safety.py:368` 区域），按 `safety.py:16-21` 阶梯的单笔 notional cap 卡死——审批通过不解除 cap。**不新造限额**，复用既有阶梯。

**E. 幂等执行接线**
- `approval/gate.py` 的 `_execute_with_key`：照搬 `copy_trade/beta.py:124-152` `record_dispatch` 的"INSERT 前查 key、命中即 skip"范式；门后真实下单时 `idempotency_key` 透传到 `execution/generic_trading.py:123` 的 `client_order_id`。stage 翻转本身的幂等用 gate 的 `side_effect_executed` 标志（append-only 落盘，崩溃可读回）。

> 不触碰：前端 `RunDetailPage`"收益概述"页既有逻辑（冻结）。前端如需展示门状态/缺口清单/下钻，仅走"加字段/显示逻辑/排版"三类允许改动，且在独立组件里，不改既有收益概述逻辑。

---

## 5. 对抗式测试规约（按 TEST_STANDARD：种已知坏→门必抓→断言什么）

> 验收标准是"种一个已知的坏，门必须抓住"。新建 `tests/test_approval_gates.py`。每条都是"已知坏/已知真信号 + 断言门的反应"，不是覆盖率。

### ① 种已知坏 → 门必须抓

- **T1 噪声探针（纯随机信号 → PBO→1/DSR 判过拟合 → 门必拒）**
  种：用 `rng.normal()` 造一条纯随机收益序列，喂 `eval/pbo.py:58` + `eval/dsr.py:41` 得 PBO≈1、DSR≈0，封进 `EvidenceSnapshot`，promote 到 production。
  断言：`promote()` 返 `GateRejection`，`gap_list` 含"三角不同向"，`decision=="rejected"`，**stage 未翻到 production**（拉 `list_versions` 确认仍 dev）。

- **T2 泄露探针（塞一个=次日收益的特征 → Sharpe 虚高 → 三角必拆穿）**
  种：造一条注入未来信息的收益序列（in-sample Sharpe 极高但 PBO 高 / bootstrap CI 下界靠近 0），三者不同向。
  断言：即便 `dsr` 字段被调用方填高，门也因 `pbo>PBO_CEIL` 或 `bootstrap_ci[0]<=0` 拒绝；`gap_list` 点名具体不同向项。**门不因单一漂亮指标放行**（R2 无单一承重点）。

- **T3 缺要件三连（缺任一即拒 + 返缺口清单）**
  种 3 个 case：(a) `verification_record_id=None`；(b) `evidence=None`；(c) `champion_challenger.verdict` 缺。
  断言：每个 case 返 `GateRejection`，`gap_list` 精确命中对应缺口字符串，且**三个 case 的 gap 文案各不相同**（不是笼统"缺东西"）。

- **T4 approver==creator（防自审 → 门必拒）**
  种：open_gate(created_by="alice")，然后 approve(approver="alice")。
  断言：抛 `ApproverEqualsCreator`，gate 仍 pending，stage 未翻。**"生成≠验证"的分离不可自我满足**（R7）。

- **T5 honest-N 不可改小（防作弊）**
  种：同一 `config_hash` 已在账本计 N_eff=40，调用方在 `EvidenceSnapshot.n_eff` 手填 3 想抬高 DSR。
  断言：门用账本侧 N_eff（或 `n_trials_raw`）而非调用方手填值重算 DSR；手填更小的 N 不能让 DSR 虚高过线。（接 R8 "N 不可手动改小，硬"。）

- **T6 已知真信号探针（必须通过，抓误杀）**
  种：造一条真有 edge 的收益（DSR 高、PBO 低、bootstrap CI 下界>0、champion/challenger verdict=challenger 胜、verification_record_id 齐、approver≠creator）。
  断言：open→pending→approve→approved，stage 翻到 production。**门不能把真信号也杀掉**（防"门太严=纸门反面"）。

### ② 变形测试（不变量）

- **T7 打乱时间 → Sharpe 坍塌 → 同一份证据快照重算应拒**
  种：T6 的真信号序列做时间 shuffle，重算 DSR/PBO。
  断言：shuffle 后三角不再同向，门从 approved 翻为 reject。**时间结构被破坏后门必须察觉**。

- **T8 换种子 → DSR 不翻符号**
  种：`bootstrap_sharpe_ci` 换 `seed`（`eval/bootstrap.py:23` 默认 42）重算 T6。
  断言：CI 下界正负号不翻、门裁决（approve/reject）不翻。**裁决对随机种子稳定**。

- **T9 加微小成本 → 净 Sharpe 下降 → 高换手策略被拉到拒绝侧**
  种：对一条高换手序列扣微小手续费重算证据。
  断言：净 Sharpe 下降使 `bootstrap_ci[0]` 跌破 0，门翻为拒。**成本敏感性必须传导到门**。

### ③ 交叉验证（无单一承重点）

- **T10 独立复算对账（两套实现/独立验证官 → 不一致即 BLOCK）**
  种：`verification_record_id` 指向的独立验证结论与 creator 自报的 `dsr/pbo` 差异 > 容差。
  断言：门 BLOCK（拒绝 + gap "creator 自报与独立验证不一致"），**不取二者均值放行**。（R7 异模型/种子/切片。）

- **T11 returns_sha256 防换等价公式绕过**
  种：两个不同 `config_hash` 但 `returns_sha256` 相同（换了等价公式）。
  断言：门识别为同一收益序列、计同一 honest-N 聚类，不让"换公式刷 N"绕过通缩。（R8 N_eff 用收益相关聚类。）

### ④ 幂等 / 恢复

- **T12 重复 idempotency_key 返存量不重发**
  种：同一 gate approved 后，连续调用 `resume(gate_id)` / `_after_approved_execute` 两次。
  断言：第二次因 `side_effect_executed==True` 返存量，`side_effect_ref` 不变，**下单/翻 stage 只发生一次**（mock venue 的 place_order 被调用恰好 1 次）。照搬 `copy_trade/executor.py:82-87` "duplicate skip" 语义验证。

- **T13 崩溃从最近 checkpoint 恢复（副作用边界截断而非重发）**
  种：approve 落盘后、`_execute_with_key` 内 mock 抛崩溃（已 INSERT idempotency_key 但 venue 已 ack）；重启后 `resume`。
  断言：`resume` 读回 append-only 最新 gate，若 `side_effect_ref` 已写则不重发；若崩在 INSERT 与 ack 之间，用 idempotency_key 查 venue 既有单（`generic_trading.py:123` client_order_id）对账，**fork/rollback 截断而非盲目重发单**。

- **T14 超时默认动作按 action_kind 分流**
  种：两个到期 pending gate——`action_kind="stop_loss"` 与 `action_kind="transfer"`，调 `on_sla_expire`。
  断言：stop_loss→`default_allow`→approved→执行；transfer→`default_reject`→timed_out→不执行。**延迟即风险类放行 / 动钱类拒绝**，且都落 append-only 留痕（R29 全保留）。

### ⑤ 裁决措辞

- **T15 措辞断言（永远说证据充分/不足 + 适用域 + 没验证的，绝不说可信/安全）**
  种：approve 成功的 gate 与 reject 的 gate 各取裁决文案。
  断言：文案含"证据充分/不足""适用域""未验证"等字样，**正则断言不含"安全""可信""保证"**；reject 文案含具体 gap 与适用域空洞（R5 守门器自身模型风险明示）。

### ⑥ 经验网

- **T16 阶梯 + 回测↔paper 对账（门后硬限额真生效 + 对不上=指向 bug）**
  种：promote production approved 后，门后动钱动作的 notional 超过当前 `SafetyService` 阶梯 cap（`safety.py:16-21`）。
  断言：`hard_limits.enforce` 拒绝执行（**审批≠授权**：批了仍被阶梯卡死）；且要求 paper/testnet 阶段对账记录存在，回测 vs paper 净值偏差超阈值时门拒绝晋级（对不上=指向 bug）。

> 回归保护：保留 `tests/test_experiments.py:49-61` 现有 dev-path 用例绿（gate_service=None 时 dev/archived 仍直翻），证明改造**向后兼容、不破坏既有 761 测试**。

---

## 6. 与其他脊柱部件的契约（共享 schema 字段约定）

本部件**消费**（上游产出）：
- `config_hash`（部件 02 试验账本，R8 content-addressed = hash(因子AST+params+universe+dataset_version+freq+label)）——`EvidenceSnapshot.config_hash`，用于绑账 + 缓存命中查询。
- `n_eff` / 试验聚类（部件 02 honest-N，收益相关聚类后；**不可手填改小**）——门重算 DSR 用它而非调用方自报。
- `dataset_version`（部件 03 数据平台，R12 留出集锚点）——`EvidenceSnapshot.dataset_version`。
- `verification_record_id`（部件 08 独立验证官，异模型/种子/切片产出，R11 落不可变 fixture）——三要件 (a)。
- `returns` 序列 + `returns_sha256`（部件 04 回测/eval 产出）——喂 `eval/{dsr,pbo,bootstrap}`。

本部件**产出**（下游消费）：
- `gate_id` / `ApprovalGate` 记录（append-only，R28/R29 全保留）——审计/治理部件消费，映射 NIST `nist_phase`（R6，非合规宣称）。
- `idempotency_key`（约定：`f"{model_id}::v{version}::{to_stage}::{config_hash[:12]}"` 形态，与 `copy_trade/beta.py:113` `make_idempotency_key` 风格一致）——门后执行部件 + `execution/*` 的 `client_order_id` 消费。
- `side_effect_ref`（`client_order_id` / `transfer_id` / `ladder_txn_id`）——对账部件 + 经验网回测↔paper 对账消费。
- `gap_list`（缺口清单）——前端下钻 + agent 辅助补证据消费。
- `decision` / `decision_reason` / `risk_restated`——审计 + 决策疲劳自我度量（门内停留时长 / override 率，dossier §8 域内验证缺口的补证）消费。

**字段约定锚点**（与既有代码对齐，不另造）：
- `ModelStage` 沿用 `experiments/store.py:23`。
- `idempotency_key` 去重语义沿用 `copy_trade/beta.py:124` `record_dispatch`（INSERT 前查、命中 skip）。
- `sla_deadline_utc` / `on_timeout` 与 `dag/engine.py:52-53` `idempotency_key`/`sla_seconds` 概念对齐。
- 门后硬限额 cap 来源 = `trading/safety.py` `SafetyService` 阶梯（`safety.py:16-21`），**唯一真硬边界事实源**。

---

## 7. 开放问题 / 风险（落地前必答）

1. **DSR_FLOOR / PBO_CEIL 档位标定**：dossier §8 明指止损默认放行 / 动钱默认拒绝的切分、SLA 窗口长度都需按资产/频率实证标定。阈值依 R 决策"t>3 不硬编"做成可配置档位 + honest-N 计数 + 显示通缩真相，**但默认档怎么定**仍需用户拍板（建议保守起步，上线后用门内 override 率自校）。
2. **honest-N 重算的数据可得性**：门要"用账本 N_eff 而非调用方自报值重算 DSR"（T5），前提是部件 02 账本在 promote 时能按 `config_hash` 查到 `n_eff` 与原始收益指纹。若账本未就绪，门只能退化到信任 `n_trials_raw`——需明确部件 02 接口先于本部件落地，或定义降级裁决措辞（"账本未接入，N 未独立核验"）。
3. **崩溃窗口的副作用对账**（T13）：门后真实下单时，"已 ack 但 gate 未落 side_effect_ref"的窗口需靠 `client_order_id` 反查交易所既有单。这依赖 `execution/*` 连接器提供"按 client_order_id 查单"能力——需逐连接器确认（`binance_um_futures.py` / `binance_spot.py` / `generic_trading.py`）。这正是 dossier §8 与本仓库 M17 同类雷区，**幂等键覆盖完整性（下单/划转/改杠杆/改风控参数/写状态）需逐动作清点**。
4. **决策疲劳/橡皮图章的域内验证缺口**（dossier §7 全部降权点）：双通道降橡皮图章率、反偏误手段疗效都是**未验证假设**，不可在裁决里宣称有效。落地必须带自我度量（门内停留时长、override 率、延迟成本），上线后补这层域内证据——这是 R5"守门器自身模型风险明示"的延伸。
5. **"reason 反套话"判定**（T15 的 `_is_substantive`）：如何判定审批理由非纯套话而不引入新的形式化敷衍（dossier §7 待验证点）？纯长度/关键词检测易被绕过且可能误杀，需谨慎设计或先只记录不强卡。
6. **单用户下 approver≠creator 的现实张力**：单用户场景属主既是 creator 又是唯一审批人。approver≠creator 的硬约束在单用户下怎么落地——是要求"独立验证官 agent 充当 approver 身份"（异模型背书），还是允许属主以不同角色二次确认 + 时间间隔？需用户决策。诚实标注：单机本地落盘**无真访问控制边界**（R12），approver≠creator 是防自欺约定 + 防篡改证据，非防恶意。
