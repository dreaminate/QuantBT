"""promote 证据组装器 —— 把「已 promote 的 run」诚实映射成 `ReleaseCandidate`（§16 release gate 的缺失输入管线）。

`release_gate.evaluate_release(ReleaseCandidate) → ReleaseValidation`（§16 八门聚合）目前【无生产调用方】：
缺一块把 run.json manifest（+ 可选 ledger 证据）映射成 `ReleaseCandidate` 的输入端。本模块补这块——
**只组装输入·判定全委派 `evaluate_release`**（RULES §1 单一源·不重造任何一致性/必填判定）。

诚实核心红线（= GOAL §0「任一生产结果走 silent mock fallback → 拒」对准组装器自己）：
- **缺证据绝不编造**。run.json 没有的证据，组装器留 `None` / `()`，让 `evaluate_release` 诚实 surface 缺口。
  绝不为「蒙混过门」造空 binding / 占位 checksum / 假执行块 / 假 MCR。种这种坏门必被 test 抓
  （见 tests/test_promote_assembler.py）。
- **缺即标缺**：留空的字段记进 `AssembledRelease.absent_fields`，软披露记进 `honest_gaps`——不静默吞。
- **不静默丢组装输入**：run.json 的 `assembly_inputs`（factor_set/model_id/signal_id/portfolio_id/cost_preset）
  原样透传进 `AssembledRelease.assembly_inputs`，并在 `honest_gaps` 钉「这是组装【意图】、run.json 不携带
  `assembly_injected`，'已注入'无从在此核」——对准 §16 致命「未注入资产却声称已采用」。

单一身份源（RULES.project：身份源 `lineage.ids`，不另造）：
- `asset_ref` 直接用 run.json 的 `run_id`（缺则 `strategy_id`）——run_id 本身即该次 promote 的唯一身份，
  **不**对 manifest 另算一个 content_hash 当 asset_ref（那是「另造身份族」）。真要内容寻址身份时复用
  `ids.content_hash`，本模块不自立第二套哈希。

证据来源优先级（每类证据）：
1. 显式注入参数（`binding=` / `dataset_versions=` / `llm_call_records=` ...）——中心接真 promote 端点时
   喂真证据的主路径；
2. run.json manifest 里【已声明】的诚实工件（`execution_blocks` / `dataset_versions` 若 future manifest 带）；
3. 可选 `ledger` 的 duck-typed 探针（SpineLedger 形：TIB/ConsistencyCheck/MCR「若在→填」）；
4. 都没有 → `None` / `()`（诚实留空）。

诚实限界（不号称做到的·设计极限）：
- 本组装器**不**判定 run 是否真 live / 真注入了组装——它只映射【声明的证据】。当前 `ide/promote.py` 写的
  run.json **不**携带执行诚实标识 / dataset 身份 / LLMCallRecord / `assembly_injected`，故对这类 run 组装器
  恒留空并标缺（见模块尾 `KNOWN_RUN_GAPS`）；让 run.json 携带这些是中心接 promote 端点的 follow-on。
- 判定全在 `evaluate_release`。本模块绝不改 release_gate / promote.py / approval（领地禁区）。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from ..delivery.rdp import DatasetVersionRef, PromotionClaim, RDPManifest
from ..lineage.spine import (
    LABEL_EXPLORATORY,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from ..llm.call_record import LLMCallRecord
from ..methodology.control_plane import MethodologyTier
from ..research_os.factor_strategy_boundary import (
    FactorGeneratorSpec,
    FactorLibraryEntry,
    SignalPerformanceValidationRecord,
    SignalProtocolRecord,
    StrategyBookContract,
)
from ..research_os.methodology_validation import (
    ValidationDepthRecord,
    ValidationMethodologyRecord,
)
from ..research_os.spine import (
    Section6PromotionClaim,
    build_section6_mathchain_record,
)
from ..research_os.trust_layer import (
    ExternalExpertReviewRecord,
    FunctionalIndependenceDisclosure,
    TrustClaimRecord,
    TrustPressureRunRecord,
    TrustReleaseApprovalRecord,
    TrustReleaseCheckRecord,
    TrustReleaseGateRecord,
    UserAutonomyRecord,
)
from ..research_os.engineering_standards import (
    DataUpdateStandardRecord,
    FatalRuntimeStandardRecord,
    LLMReplayStandardRecord,
    MockHonestyRecord,
    PerformanceBaselineMeasurement,
    TheoryImplementationStandardRecord,
)
from .mock_honesty import ExecutionBlock
from .release_gate import ReleaseCandidate, ReleaseValidation, evaluate_release

# producer 契约 key = 各 section_*_gate 的 MANIFEST_KEY 单一源（**只读复用·不重定义**·防漂；
# 门若重命名 key → 此 import 立刻炸·loud-fail）。section gate 模块经实证冷导入安全（各自 cold-import 测）。
from .section6_mathchain_gate import SECTION6_MATHCHAIN_MANIFEST_KEY, SECTION6_MATHCHAIN_PRODUCER_KEY
from .section9_boundary_gate import SECTION9_BOUNDARY_MANIFEST_KEY, SECTION9_BOUNDARY_PRODUCER_KEY
from .section10_methodology_gate import (
    SECTION10_CONTROLPLANE_MANIFEST_KEY,
    SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION10_COST_MANIFEST_KEY,
    SECTION10_COST_PRODUCER_KEY,
)
from .section13_trust_gate import SECTION13_TRUST_MANIFEST_KEY, SECTION13_TRUST_PRODUCER_KEY
from .section16_engineering_standards_gate import (
    SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY,
    SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
)
from .section17_rdp_gate import SECTION17_RDP_MANIFEST_KEY, SECTION17_RDP_PRODUCER_KEY

# run.json 缺省（`ide/promote.py.promote_ide_run` 当前不写）→ 组装器对这些 run 恒留空标缺的证据类。
# 中心接真 promote 端点时要知道：携带这些证据是 run/ledger 端 follow-on，不是组装器能凭空补的。
KNOWN_RUN_GAPS = (
    "execution_blocks",      # 执行诚实标识（live/mock/fallback/template）——run.json 无
    "dataset_versions",      # dataset_version + checksum——run.json 无（gate_verdict 也不携带 checksum）
    "llm_call_records",      # LLMCallRecord——run.json 无（run 用没用 LLM 也未记）
    "assembly_injected",     # 组装是否真注入——run.json 只记 assembly_inputs（意图），不记 injected
)

# run.json 不声明升级标签时的诚实默认：弱标签 exploratory（一次跑出结果但未证任何强命题）。
# 弱标签 → spine 一致性门 / MCR 门【不触发】（无强证据义务），但也【不**因此**放行强标签】——
# 真要 proof_backed/production_ready 须显式传 requested_label，届时缺 TIB/CC 即被 spine 门诚实硬拒。
# 刻意不默认强标签：那会对没声称强证据的 run 编造一个晋级野心、反致误拒。
DEFAULT_REQUESTED_LABEL = LABEL_EXPLORATORY

# 默认 asset_kind（纯描述·不被任何门消费）：promote 的对象是一次策略 run。
DEFAULT_ASSET_KIND = "run"


class AssemblyError(ValueError):
    """run manifest 无法建立资产身份（缺 run_id 且缺 strategy_id）——fail-closed，不伪造身份放行。"""


_SECTION_PRODUCER_BY_MANIFEST_KEY = {
    SECTION6_MATHCHAIN_MANIFEST_KEY: SECTION6_MATHCHAIN_PRODUCER_KEY,
    SECTION9_BOUNDARY_MANIFEST_KEY: SECTION9_BOUNDARY_PRODUCER_KEY,
    SECTION10_COST_MANIFEST_KEY: SECTION10_COST_PRODUCER_KEY,
    SECTION10_CONTROLPLANE_MANIFEST_KEY: SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION13_TRUST_MANIFEST_KEY: SECTION13_TRUST_PRODUCER_KEY,
    SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY: SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
    SECTION17_RDP_MANIFEST_KEY: SECTION17_RDP_PRODUCER_KEY,
}


def _clean(s: object) -> str:
    """非空白字符串视图（None / 非串 / 纯空白 → ""）——与 release_gate._clean 同口径。"""

    return s.strip() if isinstance(s, str) and s.strip() else ""


def _resolve_requested_label(
    manifest: Mapping[str, Any], explicit: str | None
) -> str:
    """解析标签优先级，并对两个输入面做 fail-closed 类型校验。

    ``None`` 表示未声明；空白字符串沿用既有优先级回退语义。任何其他非字符串值都不是可解释的
    标签声明，必须拒绝，而不能经 ``_clean`` 静默变成 exploratory。
    """

    manifest_value = manifest.get("requested_label")
    for source, value in (
        ("requested_label parameter", explicit),
        ("run_manifest.requested_label", manifest_value),
    ):
        if value is not None and not isinstance(value, str):
            raise AssemblyError(
                f"{source} 须为 str 或 None，得到 {type(value).__name__}"
                "（fail-closed·不把畸形标签静默降级为 exploratory）"
            )
    return _clean(explicit) or _clean(manifest_value) or DEFAULT_REQUESTED_LABEL


@dataclass(frozen=True)
class AssembledRelease:
    """组装结果：`ReleaseCandidate` + 诚实账（哪些证据真填了 / 哪些缺留空 / 软披露）。

    `candidate` 喂 `evaluate_release`。`assembly_inputs` 是 run.json 组装意图的【透传】（绝不静默丢）。
    `mapped_fields` / `absent_fields` 让中心一眼看清「这个 run 哪些证据齐、哪些恒空被诚实拦」。
    """

    candidate: ReleaseCandidate
    assembly_inputs: Mapping[str, Any]
    mapped_fields: tuple[str, ...]
    absent_fields: tuple[str, ...]
    honest_gaps: tuple[str, ...]


# ════════════════════════════════════════════════════════════════════════════
# manifest → 各证据字段（诚实映射·缺即留空·绝不编造）
# ════════════════════════════════════════════════════════════════════════════
def _resolve_asset_ref(manifest: Mapping[str, Any]) -> str:
    """asset_ref = run_id（缺则 strategy_id）。两者皆缺 → raise（无身份的 run 不可发版·fail-closed）。"""

    asset_ref = _clean(manifest.get("run_id")) or _clean(manifest.get("strategy_id"))
    if not asset_ref:
        raise AssemblyError(
            "run manifest 缺 run_id 且缺 strategy_id——无法建立资产身份，拒组装"
            "（不伪造身份放行·缺即真拒）"
        )
    return asset_ref


def _block_from_dict(raw: Mapping[str, Any], idx: int) -> ExecutionBlock:
    """把 manifest 里一条【已声明】的执行诚实标识映射成 ExecutionBlock（缺 mode = 不可分类 → raise）。

    非法 mode / result_grade 由 ExecutionBlock.__post_init__ fail-closed raise——绝不静默吞一个分类不明的
    块（吞了就等于放过 silent mock）。只透传声明的标识，绝不替块补 live_source_ref / mock_marked。
    """

    mode = _clean(raw.get("mode"))
    if not mode:
        raise AssemblyError(
            f"execution_blocks[{idx}] 缺 mode——无法诚实分类执行块（不静默吞·缺即拒组装）"
        )
    mock_marked = raw.get("mock_marked", False)
    if not isinstance(mock_marked, bool):
        raise AssemblyError(
            f"execution_blocks[{idx}].mock_marked 须为 bool，得到 "
            f"{type(mock_marked).__name__}（fail-closed·不以 truthiness 改写声明）"
        )
    return ExecutionBlock(
        block_id=_clean(raw.get("block_id")) or f"block_{idx}",
        mode=mode,
        result_grade=_clean(raw.get("result_grade")) or "none",
        mock_marked=mock_marked,
        live_source_ref=_clean(raw.get("live_source_ref")),
        fallback_reason=_clean(raw.get("fallback_reason")),
        note=_clean(raw.get("note")),
    )


def _resolve_execution_blocks(
    manifest: Mapping[str, Any], explicit: Sequence[ExecutionBlock] | None
) -> tuple[ExecutionBlock, ...]:
    """显式注入 > manifest 已声明 > ()（留空·当前 ide run.json 无执行诚实标识）。"""

    if explicit is not None:
        return tuple(explicit)
    if "execution_blocks" not in manifest:
        return ()
    raw_blocks = manifest.get("execution_blocks")
    if not isinstance(raw_blocks, Sequence) or isinstance(raw_blocks, (str, bytes)):
        raise AssemblyError(
            "run_manifest.execution_blocks 须为非字符串 Sequence，得到 "
            f"{type(raw_blocks).__name__}（fail-closed·不把畸形声明当成未声明）"
        )
    blocks: list[ExecutionBlock] = []
    for i, raw_block in enumerate(raw_blocks):
        if not isinstance(raw_block, Mapping):
            raise AssemblyError(
                f"execution_blocks[{i}] 须为 Mapping，得到 "
                f"{type(raw_block).__name__}（fail-closed·不静默丢执行声明）"
            )
        blocks.append(_block_from_dict(raw_block, i))
    return tuple(blocks)


def _dataset_ref_from_dict(raw: Mapping[str, Any]) -> DatasetVersionRef:
    """映射 dataset 身份（duck-type DatasetVersion / DatasetVersionRef 两种字段名）。

    **绝不补 checksum**：声明缺 checksum 就留空 manifest_sha256——gate_dataset_version 据此诚实硬拒
    （§16：未追踪数据不得发版），而非组装器造个假 checksum 蒙混。
    """

    version = _clean(raw.get("version")) or _clean(raw.get("version_id"))
    checksum = _clean(raw.get("manifest_sha256")) or _clean(raw.get("sha256"))
    return DatasetVersionRef(
        dataset_id=_clean(raw.get("dataset_id")),
        version=version,
        manifest_sha256=checksum,
    )


def _resolve_dataset_versions(
    manifest: Mapping[str, Any], explicit: Sequence[Any] | None
) -> tuple[Any, ...]:
    """显式注入 > manifest 已声明 > ()（留空·当前 ide run.json 无 dataset 身份）。"""

    if explicit is not None:
        return tuple(explicit)
    raw = manifest.get("dataset_versions")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return tuple(
            _dataset_ref_from_dict(d) if isinstance(d, Mapping) else d for d in raw
        )
    return ()


# ── 可选 ledger 探针（SpineLedger 形·duck-typed·缺则留空·绝不 raise / 绝不编造）─────────────
def _binding_from_payload(payload: Mapping[str, Any]) -> TheoryImplementationBinding | None:
    """从 SpineLedger 的 binding payload 重建 TIB（id 由内容重算·与原条目一致）。失败 → None（不编造）。"""

    try:
        return TheoryImplementationBinding(
            theory_ref=str(payload.get("theory_ref", "")),
            code_ref=str(payload.get("code_ref", "")),
            code_content_hash=str(payload.get("code_content_hash", "")),
            config_ref=str(payload.get("config_ref", "")),
            data_contract_ref=str(payload.get("data_contract_ref", "")),
            test_refs=tuple(payload.get("test_refs") or ()),
            waiver_ref=str(payload.get("waiver_ref", "")),
            consistency_verdict=str(payload.get("consistency_verdict", "")),
        )
    except Exception:
        return None


def _check_from_payload(payload: Mapping[str, Any]) -> ConsistencyCheck | None:
    try:
        return ConsistencyCheck(
            binding_id=str(payload.get("binding_id", "")),
            check_type=str(payload.get("check_type", "")),
            result=str(payload.get("result", "")),
            expected_property=str(payload.get("expected_property", "")),
            observed_property=str(payload.get("observed_property", "")),
            failure_reason=str(payload.get("failure_reason", "")),
            affected_assets=tuple(payload.get("affected_assets") or ()),
        )
    except Exception:
        return None


def _choice_from_payload(payload: Mapping[str, Any]) -> MethodologyChoiceRecord | None:
    try:
        return MethodologyChoiceRecord(
            chosen_path=str(payload.get("chosen_path", "")),
            asset_ref=str(payload.get("asset_ref", "")),
            run_ref=str(payload.get("run_ref", "")),
            responsibility_boundary=str(payload.get("responsibility_boundary", "")),
            allowed_environment=str(payload.get("allowed_environment", "")),
            actor=str(payload.get("actor", "")),
            skipped_steps=tuple(payload.get("skipped_steps") or ()),
        )
    except Exception:
        return None


def _probe_ledger_spine(
    ledger: Any, *, asset_ref: str, theory_ref: str | None
) -> tuple[
    TheoryImplementationBinding | None,
    tuple[ConsistencyCheck, ...],
    MethodologyChoiceRecord | None,
]:
    """duck-typed 探 SpineLedger 形 ledger 的 TIB/ConsistencyCheck/MCR（「若在→填」）。

    - TIB + CC：需 `theory_ref` 提示（run.json 无 theory_ref，故无提示则不探 binding）。
    - MCR：按 asset_ref（= run_id）查 choices_for。
    任何缺方法 / 无匹配 / 异常 → 留空（None/()）。绝不因探针失败而 raise 或编造证据。
    """

    binding: TheoryImplementationBinding | None = None
    checks: tuple[ConsistencyCheck, ...] = ()
    choice: MethodologyChoiceRecord | None = None
    if ledger is None:
        return binding, checks, choice

    # —— TIB + 其 ConsistencyCheck（需 theory_ref 提示）——
    if theory_ref and hasattr(ledger, "latest_binding"):
        try:
            b_payload = ledger.latest_binding(theory_ref)
        except Exception:
            b_payload = None
        if isinstance(b_payload, Mapping):
            binding = _binding_from_payload(b_payload)
            if binding is not None and hasattr(ledger, "checks_for"):
                try:
                    rows = ledger.checks_for(binding.binding_id)
                except Exception:
                    rows = []
                checks = tuple(
                    c for c in (
                        _check_from_payload(r) for r in rows if isinstance(r, Mapping)
                    ) if c is not None
                )

    # —— MCR（按 asset_ref=run_id）——
    if hasattr(ledger, "choices_for"):
        try:
            rows = ledger.choices_for(asset_ref)
        except Exception:
            rows = []
        for r in rows:
            if isinstance(r, Mapping):
                mcr = _choice_from_payload(r)
                if mcr is not None:
                    choice = mcr  # 取最近一条（链上顺序末位即最新）
    return binding, checks, choice


def _probe_ledger_llm(
    ledger: Any,
    *,
    asset_ref: str,
    owner_user_id: str | None,
) -> tuple[LLMCallRecord, ...]:
    """duck-typed 探 ledger 的 LLMCallRecord（forward-compat：若 ledger 暴露 llm_records_for）。

    SpineLedger / T-013 Ledger 都不持 LLMCallRecord——故默认探不到、留空。绝不编造账。
    """

    if ledger is not None and hasattr(ledger, "llm_records_for"):
        owner = _clean(owner_user_id)
        if not owner:
            raise AssemblyError("owner_user_id is required for owner-scoped LLM record lookup")
        rows = ledger.llm_records_for(asset_ref, owner_user_id=owner)
        return tuple(r for r in rows if isinstance(r, LLMCallRecord))
    return ()


# ════════════════════════════════════════════════════════════════════════════
# 主组装
# ════════════════════════════════════════════════════════════════════════════
def assemble(
    run_manifest: Mapping[str, Any],
    *,
    ledger: Any = None,
    owner_user_id: str | None = None,
    requested_label: str | None = None,
    asset_kind: str | None = None,
    theory_ref: str | None = None,
    # —— 显式证据注入（中心喂真证据的主路径·缺则不编造）——
    execution_blocks: Sequence[ExecutionBlock] | None = None,
    dataset_versions: Sequence[Any] | None = None,
    artifact: MathematicalArtifact | None = None,
    binding: TheoryImplementationBinding | None = None,
    consistency_checks: Sequence[ConsistencyCheck] | None = None,
    methodology_choice: MethodologyChoiceRecord | None = None,
    user_waived: bool = False,
    current_code_hash: str | None = None,
    data_contract: Mapping[str, Any] | None = None,
    llm_used: bool | None = None,
    llm_call_records: Sequence[LLMCallRecord] | None = None,
    gateway_secret: bytes | None = None,
    known_secrets: Sequence[str] = (),
    verifier_verdict: Any = None,
    approval: Any = None,
    rdp: Any = None,
    promotion: Any = None,
) -> AssembledRelease:
    """从 run.json manifest（+ 可选 ledger / 显式证据）诚实组装 `ReleaseCandidate`。

    缺的证据一律留空并记进 `absent_fields` / `honest_gaps`——绝不编造。返回 `AssembledRelease`
    （含透传的 `assembly_inputs`），供中心读「哪些证据齐 / 哪些缺被诚实拦」。
    """

    if not isinstance(run_manifest, Mapping):
        raise AssemblyError(f"run_manifest 须为 Mapping，得到 {type(run_manifest).__name__}")

    asset_ref = _resolve_asset_ref(run_manifest)
    kind = _clean(asset_kind) or _clean(run_manifest.get("asset_kind")) or DEFAULT_ASSET_KIND
    label = _resolve_requested_label(run_manifest, requested_label)

    # —— assembly_inputs 透传（绝不静默丢；它是组装【意图】，非「已注入」证明）——
    raw_ai = run_manifest.get("assembly_inputs")
    assembly_inputs: dict[str, Any] = dict(raw_ai) if isinstance(raw_ai, Mapping) else {}

    blocks = _resolve_execution_blocks(run_manifest, execution_blocks)
    datasets = _resolve_dataset_versions(run_manifest, dataset_versions)

    # —— spine 证据：显式 > ledger 探针 > None/() ——
    probed_binding, probed_checks, probed_choice = _probe_ledger_spine(
        ledger, asset_ref=asset_ref, theory_ref=theory_ref
    )
    final_binding = binding if binding is not None else probed_binding
    final_checks = (
        tuple(consistency_checks) if consistency_checks is not None else probed_checks
    )
    final_choice = (
        methodology_choice if methodology_choice is not None else probed_choice
    )

    # —— LLM 账：显式 > ledger 探针 > () ——
    final_llm_records = (
        tuple(llm_call_records)
        if llm_call_records is not None
        else _probe_ledger_llm(
            ledger,
            asset_ref=asset_ref,
            owner_user_id=owner_user_id,
        )
    )

    candidate = ReleaseCandidate(
        asset_ref=asset_ref,
        asset_kind=kind,
        requested_label=label,
        execution_blocks=blocks,
        dataset_versions=datasets,
        artifact=artifact,
        binding=final_binding,
        consistency_checks=final_checks,
        methodology_choice=final_choice,
        user_waived=user_waived,
        current_code_hash=current_code_hash,
        data_contract=data_contract,
        llm_used=llm_used,
        llm_call_records=final_llm_records,
        gateway_secret=gateway_secret,
        known_secrets=tuple(known_secrets),
        verifier_verdict=verifier_verdict,
        approval=approval,
        rdp=rdp,
        promotion=promotion,
    )

    mapped, absent, gaps = _provenance(
        candidate, run_manifest, assembly_inputs, label
    )
    return AssembledRelease(
        candidate=candidate,
        assembly_inputs=assembly_inputs,
        mapped_fields=mapped,
        absent_fields=absent,
        honest_gaps=gaps,
    )


def _provenance(
    candidate: ReleaseCandidate,
    manifest: Mapping[str, Any],
    assembly_inputs: Mapping[str, Any],
    label: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """记账：哪些证据真填了 / 哪些缺留空 / 软披露（诚实账·缺即标缺·绝不静默吞）。"""

    mapped: list[str] = ["asset_ref"]
    absent: list[str] = []
    gaps: list[str] = []

    def _track(name: str, present: bool) -> None:
        (mapped if present else absent).append(name)

    _track("execution_blocks", bool(candidate.execution_blocks))
    _track("dataset_versions", bool(candidate.dataset_versions))
    _track("binding", candidate.binding is not None)
    _track("consistency_checks", bool(candidate.consistency_checks))
    _track("artifact", candidate.artifact is not None)
    _track("methodology_choice", candidate.methodology_choice is not None)
    _track("llm_call_records", bool(candidate.llm_call_records))
    _track("verifier_verdict", candidate.verifier_verdict is not None)
    _track("approval", candidate.approval is not None)
    _track("rdp", candidate.rdp is not None)

    # —— assembly_inputs 透传 + §16 致命「未注入资产却声称已采用」诚实钉 ——
    if assembly_inputs:
        keys = ",".join(sorted(assembly_inputs))
        gaps.append(
            f"assembly:intent_recorded_injection_unverified({keys})——run.json 仅携带组装【意图】、"
            "不携带 assembly_injected；'已注入'无从在此核（§16 致命'未注入资产却声称已采用'须靠中心把"
            "injection 状态写进 run.json 才能兑现）"
        )

    # —— 当前 ide run.json 恒缺的证据类（诚实标缺·非组装器能凭空补）——
    if not candidate.execution_blocks:
        gaps.append(
            "execution:honesty_undeclared——run.json 无执行诚实标识（live/mock/fallback/template），"
            "gate_mock_honesty 因无块而平凡过（非'已核 live'）；中心 follow-on：promote 端写执行诚实标识"
        )
    if not candidate.dataset_versions:
        gaps.append(
            "dataset:identity_unrecorded——run.json 无 dataset_version+checksum，gate_dataset_version "
            "因无引用而平凡过（非'数据已追踪'）；读捆绑/live 样本的 run 须由中心记 dataset 身份"
        )
    if not candidate.llm_call_records and candidate.llm_used is None:
        gaps.append(
            "llm:usage_unrecorded——run.json 不记 run 是否用 LLM；无账时 gate_llm_gateway 推断'未用 LLM'，"
            "若实际用过却无账则该门会漏（中心 follow-on：用 LLM 合成的 run 须落 LLMCallRecord）"
        )

    # —— 强标签但缺核心理论证据：诚实预警（evaluate_release 会硬拒·这里只 surface）——
    if candidate.is_strong_label and candidate.binding is None:
        gaps.append(
            f"spine:strong_label_without_binding(label={label})——强标签缺 TheoryImplementationBinding，"
            "evaluate_release 将经 spine 门硬拒（binding-exists）；组装器不编造空壳 binding"
        )

    # —— overfit 三角裁决（§17/证据层·非 §16 release gate 输入）：surface 不映射进门 ——
    gv = manifest.get("gate_verdict")
    if isinstance(gv, Mapping) and gv.get("color"):
        gaps.append(
            f"overfit:gate_verdict.color={gv.get('color')}——§17/证据层裁决，非 §16 release gate 输入；"
            "组装器不把它映射成发版门（中心按 §17 RDP 路径消费）"
        )

    return tuple(mapped), tuple(absent), tuple(gaps)


# ════════════════════════════════════════════════════════════════════════════
# 卡契约入口（薄·返回 prompt 指定类型）
# ════════════════════════════════════════════════════════════════════════════
def assemble_release_candidate(
    run_manifest: Mapping[str, Any], *, ledger: Any = None, **kwargs: Any
) -> ReleaseCandidate:
    """从 run.json manifest（+ 可选 ledger / 显式证据）诚实组装 `ReleaseCandidate`。

    薄包 `assemble`，只取 `.candidate`（要看透传/缺字段诚实账走 `assemble`）。缺证据留空·不编造。
    """

    return assemble(run_manifest, ledger=ledger, **kwargs).candidate


def evaluate_run_releasable(
    run_manifest: Mapping[str, Any], *, ledger: Any = None, **kwargs: Any
) -> ReleaseValidation:
    """薄 helper：组装 → `evaluate_release`（判定全委派）。

    把组装器的诚实账（assembly_inputs 透传缺字段 / KNOWN_RUN_GAPS）merge 进 `honest_gaps` 软披露面
    （**扩展不替换**：`ok` / `outcomes` 原样取自 evaluate_release，绝不改门裁定）。
    """

    asm = assemble(run_manifest, ledger=ledger, **kwargs)
    v = evaluate_release(asm.candidate)
    return ReleaseValidation(
        ok=v.ok,
        outcomes=v.outcomes,
        honest_gaps=tuple(v.honest_gaps) + asm.honest_gaps,
    )


# ════════════════════════════════════════════════════════════════════════════
# C-S17-RUNJSON-PRODUCERS · promote 门链 section 记录组装（§6 数学链 / §9 边界 / §10 成本+控制面 / §17 RDP）
# ════════════════════════════════════════════════════════════════════════════
# 缺口（codemap C-S17-RUNJSON-PRODUCERS + NC-S6-MATHCHAIN-PRODUCER）：promote 真路径未把各 section
# 记录如实组装进 manifest，故 §6/§9/§10/§17 节门恒见「未声明」→ producer 接线测试无真对象、producer
# 无从诚实转绿。本段补这块：从
# **真血统/真运行产物**（typed domain 对象）如实序列化成各 section_*_gate 的 producer 契约 dict——
# 让门有真对象可判（合规 run 过、坏 run 拒）。**只组装·零判定**：判定全留给 section_*_gate→canonical。
#
# 诚实红线（= 模块顶 KNOWN_RUN_GAPS / GOAL §0「no silent mock / no template false success」对准本段自己）：
#   - **缺即真缺（honest-absent）**：某节无真证据 → **不发该 section key**。节门对「未声明」honest-bound
#     （不声明≠违例·ok=True），故不误拒「只是没那类资产」的诚实 run。**绝不**发空壳/占位 section 让门误判
#     合规（那就是假绿灯·撞 RULES.project「未验证≠已验证」）。
#   - **零重造判定（单一源）**：本段**只序列化**真对象成 dict，判定（完整性/边界/成本/封顶）全委托给
#     section_*_gate → canonical（`validate_rdp` / `factor_strategy_boundary` / `methodology_validation` /
#     `control_plane`）。坏对象（artifact_hash 空的 RDP / model_body 因子 / 强标签缺成本 record / 放宽档强
#     verdict）**如实序列化** → 门据真值拒，**绝不**在此预判/过滤/洗白（洗白=假绿灯）。
#   - **faithful 往返**：序列化口径 = 各 section_*_gate 的 `_*_from_dict` 读的 key（key 名 import 自各门
#     MANIFEST_KEY 常量·单一源）。§17 复用 `RDPManifest.to_dict`/`from_dict`（已测内容寻址往返）。
#   - **fail-closed 入参**：喂错类型对象 → raise `AssemblyError`（不静默吞坏输入·不产占位 dict）。


def _json_safe(value: Any) -> Any:
    """typed 对象 → 纯 JSON 结构（dataclass→dict·enum→value·tuple→list·递归）。

    **无损序列化·不改任何字段值**（坏值如实保留 → 让门据真值判·绝不洗白）。镜像
    `factor_strategy_boundary._stable` / `methodology_validation._json_value` 同款口径。
    `unverified_residual=None` 这类哨兵原样保留（None 不被强转·门据此判「未声明残余」）。
    """

    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)  # 递归展开嵌套 dataclass→dict（enum/tuple 仍留待下方逐项归一）
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _typed_list(seq: Sequence[Any] | None, typ: type, what: str) -> list[Any]:
    """把入参序列归一为 list，并 fail-closed 校验每项类型（不静默吞坏输入·不产占位）。"""

    items = list(seq or ())
    for it in items:
        if not isinstance(it, typ):
            raise AssemblyError(
                f"{what} 须为 {typ.__name__}，得到 {type(it).__name__}"
                "（fail-closed·不静默吞坏输入·不伪造 section 记录）"
            )
    return items


# ── §6 数学链 producer（复用 research_os.spine builder 单一源·本段不重写序列化）─────────────
def _assemble_section6_mathchain(
    mathchain_claims: Sequence[Section6PromotionClaim],
) -> dict[str, Any] | None:
    """§6 数学链：canonical Section6PromotionClaim 序列 → producer dict；无 claim → None。

    复用 `research_os.spine.build_section6_mathchain_record`，让 §6 的 typed 对象校验、no-whitewash、
    fail-closed None/错 flavor 等语义保持单一源。本函数只作为 promote_assembler 的接入口，不重造 §6
    序列化或判定。
    """

    return build_section6_mathchain_record(mathchain_claims)


# ── §10 控制面 tier-claim 与 §9 StrategyBook 交叉引用的 producer 输入类型（复用 canonical 类型·不重造）──
@dataclass(frozen=True)
class Section10TierClaim:
    """一条 §10 控制面 tier-claim（producer 契约·复用 `control_plane` 档位语义·不重造 tier 规则）。

    定档二选一：`tier`（`MethodologyTier` 或档名串）/ `methodology_choice`（含 `chosen_path`·门复用
    `tier_of` 反推）。`claimed_label` = 下游证据门拟授标签。控制面门据 `effective_label` 判放宽档是否把
    强 verdict 显出（封顶）。两者皆缺而 `claimed_label` 强 → 序列化只带 claimed_label，门 fail-closed 记
    `tier_unresolved`（堵「省档位躲封顶」dodge·诚实暴露·非洗白）。
    """

    claimed_label: str
    tier: "MethodologyTier | str | None" = None
    methodology_choice: "MethodologyChoiceRecord | None" = None


@dataclass(frozen=True)
class Section9StrategyBook:
    """一条 §9 StrategyBook + 其交叉引用（producer 契约·喂 `validate_strategy_book` 的交叉校验）。

    `book` 主契约；`factor_library`/`signal_protocols`/`signal_validations` 是交叉校验所需的 ref→record
    映射（退役因子默认采用 / 信号契约缺失 / 信号验证未通过 等判定要用）；`require_signal_validation` 透传。
    全由 §9 节门 canonical 判定·本段只序列化。
    """

    book: StrategyBookContract
    factor_library: "Mapping[str, FactorLibraryEntry]" = field(default_factory=dict)
    signal_protocols: "Mapping[str, SignalProtocolRecord]" = field(default_factory=dict)
    signal_validations: "Mapping[str, SignalPerformanceValidationRecord]" = field(default_factory=dict)
    require_signal_validation: bool = False


@dataclass(frozen=True)
class AssembledSections:
    """promote 门链 section 组装结果（要 merge 进 manifest 的 section dict + 诚实账）。

    `sections` **只含真有证据的节**（honest-absent·无证据的节不出现）；`emitted`/`absent` 让中心一眼看清
    哪些节有真证据被组装、哪些诚实留空（无该类资产·非违例）；`honest_gaps` 软披露每个留空节的诚实限界。
    """

    sections: Mapping[str, Any]
    emitted: tuple[str, ...]
    absent: tuple[str, ...]
    honest_gaps: tuple[str, ...]
    verified_producer_keys: tuple[str, ...] = ()

    def apply_to(self, run_manifest: Mapping[str, Any]) -> dict[str, Any]:
        """返回 `run_manifest` 浅拷贝 + 已组装 section（中心串 promote.py 时 `evaluate` 前调）。

        **扩展不替换**：只新增 section key、不动 manifest 既有字段（section key 与 run.json 既有字段不重名）；
        绝不就地改入参 manifest（返回新 dict）。
        """

        merged = dict(run_manifest)
        merged.update(self.sections)
        return merged

    def producer_status(self) -> Any:
        """Return green only for producer keys carrying resolver receipts."""

        from ..governance.enforcement_policy import ProducerStatusLedger

        ledger = ProducerStatusLedger()
        for producer_key in self.verified_producer_keys:
            ledger.mark_green(producer_key)
        return ledger


# ── 各节序列化（只组装·缺子键即不发·绝不补占位）──────────────────────────────────────────
def _assemble_section17(
    rdp: RDPManifest | None, promotion: PromotionClaim | None
) -> dict[str, Any] | None:
    """§17：rdp/promotion 任一在场 → `{"rdp": ..., "promotion": ...}`（缺即不放该子键）；皆缺 → None。

    复用 `RDPManifest.to_dict`/`PromotionClaim.to_dict`（单一源序列化·与 §17 节门 `from_dict` 内容寻址往返
    一致）。rdp 缺而 promotion 在 → 仍发节（只带 promotion）：门据 gate4「无 RDP 可追溯」**真拒**
    （self-promote without RDP·诚实暴露·非洗白）。
    """

    if rdp is None and promotion is None:
        return None
    if rdp is not None and not isinstance(rdp, RDPManifest):
        raise AssemblyError(f"rdp 须为 RDPManifest，得到 {type(rdp).__name__}（fail-closed）")
    if promotion is not None and not isinstance(promotion, PromotionClaim):
        raise AssemblyError(f"promotion 须为 PromotionClaim，得到 {type(promotion).__name__}（fail-closed）")
    section: dict[str, Any] = {}
    if rdp is not None:
        section["rdp"] = _json_safe(rdp)
    if promotion is not None:
        section["promotion"] = _json_safe(promotion)
    return section


def _serialize_strategy_book(bundle: Section9StrategyBook) -> dict[str, Any]:
    """§9 StrategyBook bundle → producer dict（主契约 + 交叉引用映射·faithful 喂 validate_strategy_book）。"""

    out = _json_safe(bundle.book)  # StrategyBookContract → dict（fresh·可加交叉引用键）
    if not isinstance(out, dict):  # 防御：book 非 dataclass（理应被类型挡住）
        raise AssemblyError("Section9StrategyBook.book 序列化非 dict（fail-closed）")
    if bundle.factor_library:
        out["factor_library"] = {str(k): _json_safe(v) for k, v in bundle.factor_library.items()}
    if bundle.signal_protocols:
        out["signal_protocols"] = {str(k): _json_safe(v) for k, v in bundle.signal_protocols.items()}
    if bundle.signal_validations:
        out["signal_validations"] = {str(k): _json_safe(v) for k, v in bundle.signal_validations.items()}
    if bundle.require_signal_validation:
        out["require_signal_validation"] = True
    return out


def _assemble_section9(
    factor_library_entries: Sequence[FactorLibraryEntry],
    factor_generators: Sequence[FactorGeneratorSpec],
    signal_protocols: Sequence[SignalProtocolRecord],
    strategy_books: Sequence[Section9StrategyBook],
) -> dict[str, Any]:
    """§9：四族 boundary 记录 → producer dict（每族非空才发其 key·全空 → {}）。"""

    section: dict[str, Any] = {}
    fle = _typed_list(factor_library_entries, FactorLibraryEntry, "factor_library_entries[*]")
    if fle:
        section["factor_library_entries"] = [_json_safe(e) for e in fle]
    fg = _typed_list(factor_generators, FactorGeneratorSpec, "factor_generators[*]")
    if fg:
        section["factor_generators"] = [_json_safe(g) for g in fg]
    sp = _typed_list(signal_protocols, SignalProtocolRecord, "signal_protocols[*]")
    if sp:
        section["signal_protocols"] = [_json_safe(s) for s in sp]
    sb = _typed_list(strategy_books, Section9StrategyBook, "strategy_books[*]")
    if sb:
        section["strategy_books"] = [_serialize_strategy_book(b) for b in sb]
    return section


def _assemble_section10_cost(
    validation_methodologies: Sequence[ValidationMethodologyRecord],
    validation_depths: Sequence[ValidationDepthRecord],
) -> dict[str, Any]:
    """§10 成本：方法学/深度记录 → producer dict（每族非空才发其 key·全空 → {}）。"""

    section: dict[str, Any] = {}
    vm = _typed_list(validation_methodologies, ValidationMethodologyRecord, "validation_methodologies[*]")
    if vm:
        section["validation_methodologies"] = [_json_safe(r) for r in vm]
    vd = _typed_list(validation_depths, ValidationDepthRecord, "validation_depths[*]")
    if vd:
        section["validation_depths"] = [_json_safe(r) for r in vd]
    return section


def _serialize_tier_claim(claim: Section10TierClaim) -> dict[str, Any]:
    """§10 控制面 tier-claim → producer dict（tier 或 methodology_choice 定档·皆缺只带 claimed_label）。"""

    out: dict[str, Any] = {"claimed_label": claim.claimed_label}
    if claim.tier is not None:
        out["tier"] = claim.tier.value if isinstance(claim.tier, MethodologyTier) else str(claim.tier)
    elif claim.methodology_choice is not None:
        out["methodology_choice"] = {"chosen_path": str(claim.methodology_choice.chosen_path)}
    return out


def _assemble_section10_controlplane(
    tier_claims: Sequence[Section10TierClaim],
) -> dict[str, Any]:
    """§10 控制面：tier-claims → producer dict（非空才发 tier_claims key·空 → {}）。"""

    claims = _typed_list(tier_claims, Section10TierClaim, "tier_claims[*]")
    if not claims:
        return {}
    return {"tier_claims": [_serialize_tier_claim(c) for c in claims]}


def _assemble_section13(
    trust_claims: Sequence[TrustClaimRecord],
    independence_disclosures: Sequence[FunctionalIndependenceDisclosure],
    expert_reviews: Sequence[ExternalExpertReviewRecord],
    user_choices: Sequence[UserAutonomyRecord],
    release_gates: Sequence[TrustReleaseGateRecord],
    release_checks: Sequence[TrustReleaseCheckRecord],
    pressure_runs: Sequence[TrustPressureRunRecord],
    release_approvals: Sequence[TrustReleaseApprovalRecord],
) -> dict[str, Any]:
    """§13 信任：八族 trust_layer typed records → producer dict（每族非空才发其 key·全空 → {}）。"""

    section: dict[str, Any] = {}
    claims = _typed_list(trust_claims, TrustClaimRecord, "trust_claims[*]")
    if claims:
        section["trust_claims"] = [_json_safe(r) for r in claims]
    disclosures = _typed_list(
        independence_disclosures,
        FunctionalIndependenceDisclosure,
        "independence_disclosures[*]",
    )
    if disclosures:
        section["independence_disclosures"] = [_json_safe(r) for r in disclosures]
    reviews = _typed_list(expert_reviews, ExternalExpertReviewRecord, "expert_reviews[*]")
    if reviews:
        section["expert_reviews"] = [_json_safe(r) for r in reviews]
    choices = _typed_list(user_choices, UserAutonomyRecord, "user_choices[*]")
    if choices:
        section["user_choices"] = [_json_safe(r) for r in choices]
    gates = _typed_list(release_gates, TrustReleaseGateRecord, "release_gates[*]")
    if gates:
        section["release_gates"] = [_json_safe(r) for r in gates]
    checks = _typed_list(release_checks, TrustReleaseCheckRecord, "release_checks[*]")
    if checks:
        section["release_checks"] = [_json_safe(r) for r in checks]
    runs = _typed_list(pressure_runs, TrustPressureRunRecord, "pressure_runs[*]")
    if runs:
        section["pressure_runs"] = [_json_safe(r) for r in runs]
    approvals = _typed_list(release_approvals, TrustReleaseApprovalRecord, "release_approvals[*]")
    if approvals:
        section["release_approvals"] = [_json_safe(r) for r in approvals]
    return section


def _assemble_section16(
    mock_records: Sequence[MockHonestyRecord],
    data_updates: Sequence[DataUpdateStandardRecord],
    llm_calls: Sequence[LLMReplayStandardRecord],
    theory_claims: Sequence[TheoryImplementationStandardRecord],
    fatal_records: Sequence[FatalRuntimeStandardRecord],
    performance_records: Sequence[PerformanceBaselineMeasurement],
) -> dict[str, Any]:
    """§16 工程标准：六族 engineering_standards typed records → producer dict（每族非空才发其 key）。"""

    section: dict[str, Any] = {}
    mock = _typed_list(mock_records, MockHonestyRecord, "mock_records[*]")
    if mock:
        section["mock_records"] = [_json_safe(r) for r in mock]
    updates = _typed_list(data_updates, DataUpdateStandardRecord, "data_updates[*]")
    if updates:
        section["data_updates"] = [_json_safe(r) for r in updates]
    llm = _typed_list(llm_calls, LLMReplayStandardRecord, "llm_calls[*]")
    if llm:
        section["llm_calls"] = [_json_safe(r) for r in llm]
    theory = _typed_list(
        theory_claims,
        TheoryImplementationStandardRecord,
        "theory_claims[*]",
    )
    if theory:
        section["theory_claims"] = [_json_safe(r) for r in theory]
    fatal = _typed_list(fatal_records, FatalRuntimeStandardRecord, "fatal_records[*]")
    if fatal:
        section["fatal_records"] = [_json_safe(r) for r in fatal]
    perf = _typed_list(
        performance_records,
        PerformanceBaselineMeasurement,
        "performance_records[*]",
    )
    if perf:
        section["performance_records"] = [_json_safe(r) for r in perf]
    return section


# ── 主入口：真血统 → 五节 producer 契约 dict（honest-absent）──────────────────────────────
def assemble_promote_sections(
    run_manifest: Mapping[str, Any],
    *,
    # —— §6 数学链（复用 research_os.spine builder / section6_mathchain_gate 单一源）——
    mathchain_claims: Sequence[Section6PromotionClaim] = (),
    # —— §17 RDP（复用 delivery.rdp / rdp_gate 单一源）——
    rdp: RDPManifest | None = None,
    promotion: PromotionClaim | None = None,
    # —— §9 边界（复用 factor_strategy_boundary 单一源）——
    factor_library_entries: Sequence[FactorLibraryEntry] = (),
    factor_generators: Sequence[FactorGeneratorSpec] = (),
    signal_protocols: Sequence[SignalProtocolRecord] = (),
    strategy_books: Sequence[Section9StrategyBook] = (),
    # —— §10 成本/控制面（复用 methodology_validation / control_plane 单一源）——
    validation_methodologies: Sequence[ValidationMethodologyRecord] = (),
    validation_depths: Sequence[ValidationDepthRecord] = (),
    tier_claims: Sequence[Section10TierClaim] = (),
    # —— §13 信任（复用 trust_layer 单一源）——
    trust_claims: Sequence[TrustClaimRecord] = (),
    independence_disclosures: Sequence[FunctionalIndependenceDisclosure] = (),
    expert_reviews: Sequence[ExternalExpertReviewRecord] = (),
    user_choices: Sequence[UserAutonomyRecord] = (),
    release_gates: Sequence[TrustReleaseGateRecord] = (),
    release_checks: Sequence[TrustReleaseCheckRecord] = (),
    pressure_runs: Sequence[TrustPressureRunRecord] = (),
    release_approvals: Sequence[TrustReleaseApprovalRecord] = (),
    # —— §16 工程标准（复用 engineering_standards 单一源）——
    mock_records: Sequence[MockHonestyRecord] = (),
    data_updates: Sequence[DataUpdateStandardRecord] = (),
    llm_calls: Sequence[LLMReplayStandardRecord] = (),
    theory_claims: Sequence[TheoryImplementationStandardRecord] = (),
    fatal_records: Sequence[FatalRuntimeStandardRecord] = (),
    performance_records: Sequence[PerformanceBaselineMeasurement] = (),
    verified_producer_keys: Sequence[str] = (),
) -> AssembledSections:
    """从真血统/真运行产物（typed 对象）组装 §6/§9/§10/§17 节门的 producer 契约 dict（honest-absent）。

    每节：有真证据 → 序列化进 `sections`（key = 对应 section_*_gate 的 MANIFEST_KEY）；无证据 → **不发**该
    key（门 honest-bound·不误拒「只是没那类资产」的诚实 run）。**只序列化·零判定**：坏对象如实序列化让门据
    真值拒，绝不预判/洗白（防假绿灯）。返回 `AssembledSections`（`.apply_to(manifest)` 得待评估 manifest）。
    """

    if not isinstance(run_manifest, Mapping):
        raise AssemblyError(
            f"run_manifest 须为 Mapping，得到 {type(run_manifest).__name__}"
        )

    sections: dict[str, Any] = {}
    emitted: list[str] = []
    absent: list[str] = []
    gaps: list[str] = []

    def _take(key: str, payload: dict[str, Any] | None, undeclared_gap: str) -> None:
        if payload:
            sections[key] = payload
            emitted.append(key)
        else:
            absent.append(key)
            gaps.append(undeclared_gap)

    _take(
        SECTION6_MATHCHAIN_MANIFEST_KEY,
        _assemble_section6_mathchain(mathchain_claims),
        "section6_mathchain:undeclared——本 run 无 §6 数学链升级断言，诚实留空（未声明≠违例）",
    )
    _take(
        SECTION17_RDP_MANIFEST_KEY,
        _assemble_section17(rdp, promotion),
        "section17_rdp:undeclared——本 run 无 RDP/晋级断言，§17 节诚实留空"
        "（门 honest-bound：未声明≠违例·非『已查清 §17』·查清由 producer 绿灯负责）",
    )
    _take(
        SECTION9_BOUNDARY_MANIFEST_KEY,
        _assemble_section9(factor_library_entries, factor_generators, signal_protocols, strategy_books),
        "section9_boundary:undeclared——本 run 无 §9 边界资产，诚实留空（未声明≠违例）",
    )
    _take(
        SECTION10_COST_MANIFEST_KEY,
        _assemble_section10_cost(validation_methodologies, validation_depths),
        "section10_cost:undeclared——本 run 无 §10 方法学/成本记录，诚实留空（未声明≠违例）",
    )
    _take(
        SECTION10_CONTROLPLANE_MANIFEST_KEY,
        _assemble_section10_controlplane(tier_claims),
        "section10_control_plane:undeclared——本 run 无 §10 档位声明，诚实留空（未声明≠违例）",
    )
    _take(
        SECTION13_TRUST_MANIFEST_KEY,
        _assemble_section13(
            trust_claims,
            independence_disclosures,
            expert_reviews,
            user_choices,
            release_gates,
            release_checks,
            pressure_runs,
            release_approvals,
        ),
        "section13_trust:undeclared——本 run 无 §13 信任发版结构，诚实留空（未声明≠违例）",
    )
    _take(
        SECTION16_ENGINEERING_STANDARDS_MANIFEST_KEY,
        _assemble_section16(
            mock_records,
            data_updates,
            llm_calls,
            theory_claims,
            fatal_records,
            performance_records,
        ),
        "section16_engineering_standards:undeclared——本 run 无 §16 工程标准结构，诚实留空（未声明≠违例）",
    )

    emitted_producer_keys = {
        _SECTION_PRODUCER_BY_MANIFEST_KEY[key]
        for key in emitted
        if key in _SECTION_PRODUCER_BY_MANIFEST_KEY
    }
    verified = tuple(dict.fromkeys(str(key or "") for key in verified_producer_keys if str(key or "")))
    unknown = sorted(set(verified) - emitted_producer_keys)
    if unknown:
        raise AssemblyError(
            "verified producer receipt has no emitted canonical section: "
            + ",".join(unknown)
        )
    return AssembledSections(
        sections=sections,
        emitted=tuple(emitted),
        absent=tuple(absent),
        honest_gaps=tuple(gaps),
        verified_producer_keys=verified,
    )


__all__ = [
    "AssemblyError",
    "AssembledRelease",
    "KNOWN_RUN_GAPS",
    "DEFAULT_REQUESTED_LABEL",
    "DEFAULT_ASSET_KIND",
    "assemble",
    "assemble_release_candidate",
    "evaluate_run_releasable",
    # —— C-S17-RUNJSON-PRODUCERS：promote 门链 section 组装 ——
    "Section6PromotionClaim",
    "Section10TierClaim",
    "Section9StrategyBook",
    "AssembledSections",
    "assemble_promote_sections",
    "TrustClaimRecord",
    "FunctionalIndependenceDisclosure",
    "ExternalExpertReviewRecord",
    "UserAutonomyRecord",
    "TrustReleaseGateRecord",
    "TrustReleaseCheckRecord",
    "TrustPressureRunRecord",
    "TrustReleaseApprovalRecord",
    "MockHonestyRecord",
    "DataUpdateStandardRecord",
    "LLMReplayStandardRecord",
    "TheoryImplementationStandardRecord",
    "FatalRuntimeStandardRecord",
    "PerformanceBaselineMeasurement",
]
