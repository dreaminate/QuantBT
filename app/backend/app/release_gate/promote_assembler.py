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

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..delivery.rdp import DatasetVersionRef
from ..lineage.spine import (
    LABEL_EXPLORATORY,
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)
from ..llm.call_record import LLMCallRecord
from .mock_honesty import ExecutionBlock
from .release_gate import ReleaseCandidate, ReleaseValidation, evaluate_release

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


def _clean(s: object) -> str:
    """非空白字符串视图（None / 非串 / 纯空白 → ""）——与 release_gate._clean 同口径。"""

    return s.strip() if isinstance(s, str) and s.strip() else ""


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
    return ExecutionBlock(
        block_id=_clean(raw.get("block_id")) or f"block_{idx}",
        mode=mode,
        result_grade=_clean(raw.get("result_grade")) or "none",
        mock_marked=bool(raw.get("mock_marked", False)),
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
    raw_blocks = manifest.get("execution_blocks")
    if isinstance(raw_blocks, Sequence) and not isinstance(raw_blocks, (str, bytes)):
        return tuple(
            _block_from_dict(b, i) for i, b in enumerate(raw_blocks) if isinstance(b, Mapping)
        )
    return ()


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


def _probe_ledger_llm(ledger: Any, *, asset_ref: str) -> tuple[LLMCallRecord, ...]:
    """duck-typed 探 ledger 的 LLMCallRecord（forward-compat：若 ledger 暴露 llm_records_for）。

    SpineLedger / T-013 Ledger 都不持 LLMCallRecord——故默认探不到、留空。绝不编造账。
    """

    if ledger is not None and hasattr(ledger, "llm_records_for"):
        try:
            rows = ledger.llm_records_for(asset_ref)
        except Exception:
            rows = []
        return tuple(r for r in rows if isinstance(r, LLMCallRecord))
    return ()


# ════════════════════════════════════════════════════════════════════════════
# 主组装
# ════════════════════════════════════════════════════════════════════════════
def assemble(
    run_manifest: Mapping[str, Any],
    *,
    ledger: Any = None,
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
    label = (
        _clean(requested_label)
        or _clean(run_manifest.get("requested_label"))
        or DEFAULT_REQUESTED_LABEL
    )

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
        else _probe_ledger_llm(ledger, asset_ref=asset_ref)
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


__all__ = [
    "AssemblyError",
    "AssembledRelease",
    "KNOWN_RUN_GAPS",
    "DEFAULT_REQUESTED_LABEL",
    "DEFAULT_ASSET_KIND",
    "assemble",
    "assemble_release_candidate",
    "evaluate_run_releasable",
]
