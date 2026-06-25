"""Research Delivery Package（RDP）schema + 开放格式 manifest 序列化（GOAL §17 契约）。

正式研究交付 = 开放格式 RDP（GOAL §17 行 2033-2076）。本模块只做两件事：
1. `RDPManifest`——把 §17 列的 ~25 字段装进一个**内容寻址**容器（frozen dataclass）。
2. 序列化为**开放格式 JSON**（第三方可解析、无私有二进制；`to_json`/`from_json` 往返）。

为什么 id 走 `lineage.ids.content_hash`（单一身份源 · RULES.project「身份源 ids.py 不另造」）：
- `rdp_id = "rdp_" + content_hash(身份载荷)`——与 content_hash / node_id / config_hash 同一哈希族，
  **绝不**自造第二套。改内容 → rdp_id 变（内容寻址）；改 created_at/created_by 这类**时间/署名**
  装饰字段 → rdp_id 不变（它们不改变「这份交付的实质内容」）。

诚实边界（RULES §3）：
- 本模块只是「容器 + 内容寻址身份 + 开放序列化」。它**不**判定交付是否完整——那是 `rdp_gate`
  的 4 条拒绝门的活。容器对必填字段给默认值只为「能装半成品草稿」；**完整性由门强制**，
  门缺字段【真拒】、绝不静默填默认（§17 可证伪验收）。
- `dataset_versions` 是对 `data_hash.dataset_hash.DatasetManifest(dataset_id, version)` 的**只读引用**
  （身份 + manifest sha256），不嵌入也不改 DatasetManifest 本身。
- `llm_call_record_refs` / `responsibility_disclosure_refs` / `theory_spec_refs`：§17 命名但全仓尚无
  对应类，故按**字符串 ref** 持有（诚实：是引用，不是已建对象的内嵌）。接真实类作 follow-on。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from ..lineage.ids import content_hash

# RDP schema 版本（口径变更时 +1，旧包凭此字段区分世代）。
RDP_SCHEMA_VERSION = "rdp_v1"

# §17 交付物所描述的资产类别（因子/模型/信号/StrategyBook 版本）。
ASSET_FACTOR = "factor"
ASSET_MODEL = "model"
ASSET_SIGNAL = "signal"
ASSET_STRATEGYBOOK = "strategybook"
ASSET_KINDS = frozenset({ASSET_FACTOR, ASSET_MODEL, ASSET_SIGNAL, ASSET_STRATEGYBOOK})

# 计算 rdp_id 时**排除**的字段：时间/署名/id 自身——它们不改变交付的实质内容。
# （镜像 ids.DECORATIVE_KEYS 的思想：装饰字段入哈希会让「改个署名」被误算成新交付。）
_IDENTITY_EXCLUDED = frozenset({"rdp_id", "created_at_utc", "created_by"})

# 声明为 `tuple[...]` 的字段名——外部 JSON 进来是 list，__post_init__ 统一回 tuple
# （frozen + 内容寻址要求字段规范化，否则 list/tuple 混入会让 from_dict 往返漂移）。
_TUPLE_FIELDS = frozenset(
    {
        "dataset_versions",
        "ingestion_skill_refs",
        "data_source_refs",
        "llm_call_record_refs",
        "math_artifact_refs",
        "theory_spec_refs",
        "theory_binding_refs",
        "consistency_check_refs",
        "methodology_choice_refs",
        "responsibility_disclosure_refs",
        "asset_versions",
        "code_refs",
        "source_file_refs",
        "test_refs",
        "adversarial_test_refs",
        "backtest_run_refs",
        "training_run_refs",
        "validation_run_refs",
        "known_limitations",
        "verifier_verdict_refs",
        "approval_refs",
        # unverified_residual 不在此列：它的 None 哨兵（未声明）必须保留，不能被强转成 ()。
    }
)


@dataclass(frozen=True)
class DatasetVersionRef:
    """对一个 DatasetVersion 的只读引用（→ data_hash.dataset_hash.DatasetManifest）。

    `dataset_id` + `version` 是 DatasetManifest 的不可变身份；`manifest_sha256` 是其 manifest.json
    的内容指纹（可选，但带上才能事后 audit「我引用的 dataset 内容是否真没变」）。
    空 `dataset_id`/`version` = 空壳引用，gate_dataset_lineage 据此拒（不当有效血统）。
    """

    dataset_id: str
    version: str
    manifest_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetVersionRef":
        return cls(
            dataset_id=d.get("dataset_id", ""),
            version=d.get("version", ""),
            manifest_sha256=d.get("manifest_sha256", ""),
        )

    @property
    def is_resolvable(self) -> bool:
        """两段身份都非空才算可解析的真引用。"""

        return bool(self.dataset_id.strip()) and bool(self.version.strip())


@dataclass(frozen=True)
class PromotionClaim:
    """一次晋级请求对 RDP 的追溯断言（gate_promotion_traceability 的输入）。

    §17：任何正式因子/模型/信号/StrategyBook 晋级都必须能追溯到一套 RDP。本结构把
    「被晋级资产 + 它声称依据的 rdp_ref」绑在一起；门校验 rdp_ref 真解析到一份**关于本资产**
    的有效 RDP（防空 ref / 张冠李戴 / 追溯到残缺 RDP）。

    本卡只落纯逻辑门；接进真实 ApprovalGateService / paper.PromotionGate 是 follow-on（诚实标 P2）。
    """

    asset_ref: str
    asset_kind: str
    rdp_ref: str
    requested_stage: str = ""
    actor: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RDPManifest:
    """开放格式 Research Delivery Package（§17 ~25 字段契约）。

    字段分两类：
    - **门强制**（完整性由 rdp_gate 4 门把守，缺即拒）：asset_ref（manifest 身份）、artifact_hash、
      reproducibility_command、dataset_versions、ingestion_skill_refs、unverified_residual。
    - **契约携带**（§17 要求随包带，承载上下文/可追溯；本卡不逐条硬拒，留 follow-on 按需收紧）。

    id 走单一身份源：rdp_id = "rdp_" + content_hash(除时间/署名外的全部内容)。frozen + 内容寻址
    保证「同内容同 id」「内容一改 id 就变」。
    """

    # ── manifest 身份（§17 manifest 行 · 门1 校验 asset_ref 非空）────────────────
    asset_ref: str
    asset_kind: str
    schema_version: str = RDP_SCHEMA_VERSION
    rdp_id: str = ""
    created_at_utc: str = ""
    created_by: str = ""

    # ── 研究命题 / Research Graph（§17）─────────────────────────────────────────
    research_proposition: str = ""
    research_graph_ref: str = ""

    # ── 数据 / PIT 语义 / 来源 / DatasetVersion / IngestionSkill（§17 · 门2）──────
    data_pit_semantics: str = ""
    dataset_versions: tuple[DatasetVersionRef, ...] = ()
    ingestion_skill_refs: tuple[str, ...] = ()
    data_source_refs: tuple[str, ...] = ()

    # ── LLM Provider / ModelRoutingPolicy / LLMCallRecord / replay（§17 · ref 持有）─
    llm_provider: str = ""
    model_routing_policy_ref: str = ""
    llm_call_record_refs: tuple[str, ...] = ()
    replay_state: str = ""

    # ── 数学定义 / TheorySpec / Binding / ConsistencyCheck（§17 · spine refs）──────
    math_artifact_refs: tuple[str, ...] = ()
    theory_spec_refs: tuple[str, ...] = ()
    theory_binding_refs: tuple[str, ...] = ()
    consistency_check_refs: tuple[str, ...] = ()

    # ── MethodologyChoiceRecord / ResponsibilityDisclosureRecord（§17）───────────
    methodology_choice_refs: tuple[str, ...] = ()
    responsibility_disclosure_refs: tuple[str, ...] = ()

    # ── 因子/模型/信号/StrategyBook 版本（§17）──────────────────────────────────
    asset_versions: tuple[str, ...] = ()

    # ── 代码/环境/hash/seed + reproducibility command（§17 · 门1）────────────────
    code_refs: tuple[str, ...] = ()
    environment: str = ""
    code_hash: str = ""
    seed: int | None = None
    reproducibility_command: str = ""
    source_file_refs: tuple[str, ...] = ()
    artifact_hash: str = ""
    environment_lock: str = ""

    # ── 测试 / 对抗测试（§17）───────────────────────────────────────────────────
    test_refs: tuple[str, ...] = ()
    adversarial_test_refs: tuple[str, ...] = ()

    # ── 回测 / 训练 / 验证运行（§17）────────────────────────────────────────────
    backtest_run_refs: tuple[str, ...] = ()
    training_run_refs: tuple[str, ...] = ()
    validation_run_refs: tuple[str, ...] = ()

    # ── honest-N / 选择过程（§17 · → lineage.ledger.Ledger.honest_n）─────────────
    honest_n: int | None = None
    honest_n_strategy_goal_ref: str = ""
    honest_n_disclosure: str = ""
    selection_process: str = ""

    # ── 成本与执行假设 / 归因 / 已知限制（§17）─────────────────────────────────
    cost_execution_assumptions: str = ""
    attribution: str = ""
    known_limitations: tuple[str, ...] = ()

    # ── 未验证残余（§17 · 门3 诚实闸）───────────────────────────────────────────
    #   None = 【未声明】→ 门3 拒。()（显式空）+ 非空 residual_attestation = 显式断言「已审无残余」。
    #   非空 = 已列残余。区分「忘了想」与「想过并署名说没有」。
    unverified_residual: tuple[str, ...] | None = None
    residual_attestation: str = ""

    # ── Verifier verdict / Approval / promotion record（§17）────────────────────
    #   → verification.schema.VerdictRecord.verdict_id / approval.schema.ApprovalGate.gate_id
    verifier_verdict_refs: tuple[str, ...] = ()
    approval_refs: tuple[str, ...] = ()
    promotion_record: str = ""

    # ── Deployment / monitor / rollback / retire 清单（§17）─────────────────────
    deployment_plan: str = ""
    monitor_plan: str = ""
    rollback_plan: str = ""
    retire_plan: str = ""

    def __post_init__(self) -> None:
        if self.asset_kind not in ASSET_KINDS:
            raise ValueError(
                f"asset_kind 非法：{self.asset_kind!r} ∉ {sorted(ASSET_KINDS)}"
            )
        # list → tuple 规范化（外部 JSON 进来是 list；frozen 用 object.__setattr__ 改）。
        for fname in _TUPLE_FIELDS:
            val = getattr(self, fname)
            if isinstance(val, list):
                object.__setattr__(self, fname, tuple(val))
        # dataset_versions 里若混入 dict（from JSON），转成 DatasetVersionRef。
        dvs = tuple(
            v if isinstance(v, DatasetVersionRef) else DatasetVersionRef.from_dict(v)
            for v in self.dataset_versions
        )
        object.__setattr__(self, "dataset_versions", dvs)
        # unverified_residual 的 list → tuple，但保留 None 哨兵（不强转）。
        if isinstance(self.unverified_residual, list):
            object.__setattr__(self, "unverified_residual", tuple(self.unverified_residual))
        # 内容寻址 id（复用单一身份源 ids.content_hash，绝不另造哈希族）。
        if not self.rdp_id:
            object.__setattr__(self, "rdp_id", "rdp_" + content_hash(self._identity_payload()))

    def _identity_payload(self) -> dict[str, Any]:
        """rdp_id 的哈希载荷 = 除时间/署名/id 自身外的全部字段（内容寻址）。"""

        d = asdict(self)
        for k in _IDENTITY_EXCLUDED:
            d.pop(k, None)
        return d

    # ── 开放格式序列化（JSON 可第三方解析；绝不私有二进制）────────────────────
    def to_dict(self) -> dict[str, Any]:
        """纯 dict（tuple → list、嵌套 DatasetVersionRef → dict）；json 安全。"""

        return asdict(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        """开放格式 JSON 串：UTF-8 直出、键有序、任何 `json.loads` 可解析。"""

        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=indent)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RDPManifest":
        """从开放 dict 重建（只取已知字段，dataset_versions dict → ref）。"""

        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        data = {k: v for k, v in d.items() if k in known}
        if "dataset_versions" in data and data["dataset_versions"] is not None:
            data["dataset_versions"] = [
                DatasetVersionRef.from_dict(x) if isinstance(x, dict) else x
                for x in data["dataset_versions"]
            ]
        # rdp_id 不从外部信任：重建时清空让 __post_init__ 按内容重算（防伪造 id）。
        data.pop("rdp_id", None)
        return cls(**data)

    @classmethod
    def from_json(cls, text: str) -> "RDPManifest":
        return cls.from_dict(json.loads(text))


__all__ = [
    "RDP_SCHEMA_VERSION",
    "ASSET_KINDS",
    "ASSET_FACTOR",
    "ASSET_MODEL",
    "ASSET_SIGNAL",
    "ASSET_STRATEGYBOOK",
    "DatasetVersionRef",
    "PromotionClaim",
    "RDPManifest",
]
