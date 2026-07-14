"""Prospective mathless business history for platform rows M16, M19, and M21.

The three business routes call this module immediately after their typed
business write.  It records the immutable, mathless QRO/Graph/compiler/
coverage head that a later server-owned Mathematical Spine attestation may
bind.  It never reconstructs history after a Mathematical Spine head exists.

Public inputs are authenticated owner/row/anchor values plus one row-specific
bundle of already-persisted typed business objects.  Caller supplied QRO,
Graph, compiler, coverage, Mathematical Spine, or validation refs are not
accepted.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from ..cross_process_lock import acquire_exclusive_fd
from ..ide.service import StrategyFile
from ..lineage.ids import content_hash
from ..sharing.service import (
    SharedAssetPermissionRecord,
    SharedAssetSourceRecord,
    SharedAssetStatusRecord,
    SharedStrategy,
    shared_strategy_asset_ref,
    shared_strategy_permission,
    shared_strategy_source,
    shared_strategy_status,
)
from .asset_lifecycle import GovernedAssetRecord
from .entrypoint_evidence import (
    CompositeEntrypointEvidenceRegistry,
    PersistentEntrypointEvidenceRegistry,
)
from .goal_coverage import goal_entrypoint_coverage_identity
from .qro_spine_binding import _PROCESS_BINDING_LOCK
from .ref_resolution import is_placeholder_ref
from .spine import (
    ActorSource,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    GovernanceStatus,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    RuntimeStatus,
)
from .teaching_assets import TeachingAssetBundle
from .platform_typed_sources import (
    platform_compiler_snapshot,
    platform_compiler_snapshot_required_methods,
)


M16 = "M16"
M19 = "M19"
M21 = "M21"
SUPPORTED_ROWS = (M16, M19, M21)

ENTRYPOINT_REFS = {
    M16: "api:sharing.publish",
    M19: "api:research_os.teaching.assets",
    M21: "api:strategies.templates.fork_to_ide",
}

_GOAL_SECTIONS = {
    M16: ("§0", "§1", "§8", "§16"),
    M19: ("§0", "§1", "§8", "§17"),
    M21: ("§0", "§1", "§8"),
}

_ANCHOR_CONTRACT_FIELDS = {
    M16: ("input_contract", "shared_asset_ref"),
    M19: ("input_contract", "tutorial_asset_ref"),
    M21: ("output_contract", "ide_strategy_ref"),
}

_PROCESS_HISTORY_LOCK = _PROCESS_BINDING_LOCK


class PlatformBusinessHistoryM16M21Error(ValueError):
    """Typed business state cannot form one prospective immutable history."""


class PlatformBusinessHistoryM16M21CommitError(RuntimeError):
    """A history commit stopped after reporting the state observable in stores.

    Successfully appended history remains durable for an exact retry to reuse;
    this error never claims that an earlier append was compensated or removed.
    """

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        graph_history_current: bool | None,
        graph_command_ref: str = "",
        graph_command_created: bool | None = False,
        compiler_history_current: bool | None = False,
        compiler_ir_ref: str = "",
        compiler_pass_ref: str = "",
        entrypoint_coverage_ref: str = "",
    ) -> None:
        super().__init__(message)
        self.phase = str(phase)
        self.graph_history_current = (
            None
            if graph_history_current is None
            else bool(graph_history_current)
        )
        self.graph_command_ref = str(graph_command_ref or "")
        self.graph_command_created = (
            None
            if graph_command_created is None
            else bool(graph_command_created)
        )
        self.compiler_history_current = (
            None
            if compiler_history_current is None
            else bool(compiler_history_current)
        )
        self.compiler_ir_ref = str(compiler_ir_ref or "")
        self.compiler_pass_ref = str(compiler_pass_ref or "")
        self.entrypoint_coverage_ref = str(entrypoint_coverage_ref or "")


@dataclass(frozen=True)
class M16BusinessHistorySubject:
    strategy: SharedStrategy
    permission: SharedAssetPermissionRecord
    source: SharedAssetSourceRecord
    status: SharedAssetStatusRecord
    governed_asset: GovernedAssetRecord


@dataclass(frozen=True)
class M19BusinessHistorySubject:
    bundle: TeachingAssetBundle
    governed_asset: GovernedAssetRecord


@dataclass(frozen=True)
class M21BusinessHistorySubject:
    governed_asset: GovernedAssetRecord
    ide_strategy: StrategyFile


BusinessHistorySubject = (
    M16BusinessHistorySubject
    | M19BusinessHistorySubject
    | M21BusinessHistorySubject
)


@dataclass(frozen=True)
class PlatformBusinessHistoryM16M21CompilePlan:
    row: str
    owner_user_id: str
    anchor_ref: str
    entrypoint_ref: str
    pass_name: str
    validation_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    environment_lock_ref: str
    permission_ref: str
    deterministic_run_plan_ref: str
    rollback_ref: str
    tool_record_refs: tuple[str, ...]
    node_refs: tuple[str, ...]
    canonical_command_refs: tuple[str, ...]
    lifecycle_refs: tuple[str, ...]
    rdp_refs: tuple[str, ...]
    theory_binding_refs: tuple[str, ...]
    consistency_check_refs: tuple[str, ...]
    mathematical_spine_chain_refs: tuple[str, ...]
    goal_sections: tuple[str, ...]


@dataclass(frozen=True)
class PlatformBusinessHistoryM16M21Plan:
    owner_user_id: str
    row: str
    anchor_ref: str
    entrypoint_ref: str
    qro: QRORecord
    command: ResearchGraphCommand
    compile_plan: PlatformBusinessHistoryM16M21CompilePlan


@dataclass(frozen=True)
class PlatformBusinessHistoryM16M21Context:
    research_graph_store: Any
    compiler_store: Any
    entrypoint_registry: Any
    apply_graph: Callable[[ResearchGraphCommand], str]
    compile_history: Callable[
        [
            QRORecord,
            ResearchGraphCommand,
            PlatformBusinessHistoryM16M21CompilePlan,
        ],
        Mapping[str, Any],
    ]
    entrypoint_view_factory: Callable[[], Any] | None = None
    compiler_view_factory: Callable[[], Any] | None = None
    validation_receipt_registry: Any = None
    entrypoint_evidence_registry: Any = None
    entrypoint_evidence_view_factory: Callable[[], Any] | None = None


@dataclass(frozen=True)
class PlatformBusinessHistoryM16M21Result:
    owner_user_id: str
    row: str
    anchor_ref: str
    entrypoint_ref: str
    qro_ref: str
    graph_command_ref: str
    graph_command_created: bool
    compiler_ir_ref: str
    compiler_pass_ref: str
    entrypoint_coverage_ref: str


@dataclass(frozen=True)
class _PreparedBusiness:
    qro_type: QROType
    input_contract: dict[str, Any]
    output_contract: dict[str, Any]
    market: str
    universe: str
    evidence_refs: tuple[str, ...]
    lifecycle_refs: tuple[str, ...]
    canonical_business_refs: tuple[str, ...]
    event_time: str | None


@dataclass(frozen=True)
class _ObservedHistory:
    graph_current: bool | None
    command_observed: bool | None
    compiler_current: bool | None
    compiler_ir_ref: str = ""
    compiler_pass_ref: str = ""
    coverage_ref: str = ""


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _owner(value: Any) -> str:
    return str(
        getattr(
            value,
            "owner_user_id",
            getattr(
                value,
                "owner",
                getattr(
                    value,
                    "recorded_by",
                    getattr(value, "author_id", getattr(value, "actor", "")),
                ),
            ),
        )
        or ""
    ).strip()


def _exact(
    value: Any,
    *,
    field: str,
    prefix: str | tuple[str, ...] = (),
) -> str:
    raw = str(getattr(value, "value", value) or "")
    token = raw.strip()
    if (
        not token
        or token != raw
        or any(ord(char) < 32 for char in token)
        or is_placeholder_ref(token)
    ):
        raise PlatformBusinessHistoryM16M21Error(
            f"{field} is not an exact stable ref"
        )
    prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
    if prefixes and not token.startswith(prefixes):
        raise PlatformBusinessHistoryM16M21Error(
            f"{field} does not use its canonical prefix"
        )
    return token


def _refs(values: Any, *, field: str, allow_empty: bool = False) -> tuple[str, ...]:
    refs = tuple(_exact(value, field=field) for value in tuple(values or ()))
    if not refs and not allow_empty:
        raise PlatformBusinessHistoryM16M21Error(
            f"{field} must contain at least one ref"
        )
    if len(refs) != len(set(refs)):
        raise PlatformBusinessHistoryM16M21Error(
            f"{field} contains duplicate refs"
        )
    return refs


def _unique_refs(*groups: Any) -> tuple[str, ...]:
    refs: list[str] = []
    for group in groups:
        if group is None:
            continue
        values = (
            group
            if isinstance(group, (tuple, list, set, frozenset))
            else (group,)
        )
        for value in values:
            ref = _exact(value, field="derived reference")
            if ref not in refs:
                refs.append(ref)
    return tuple(refs)


def _has_exact_trusted_validation_refs(
    values: Any,
) -> bool:
    refs = tuple(str(value or "").strip() for value in tuple(values or ()))
    return (
        len(refs) == 1
        and refs[0].startswith("goal_validation_receipt:")
    )


def _require_methods(value: Any, methods: tuple[str, ...], *, label: str) -> None:
    missing = tuple(
        method for method in methods if not callable(getattr(value, method, None))
    )
    if missing:
        raise PlatformBusinessHistoryM16M21Error(
            f"{label} is missing required methods: {', '.join(missing)}"
        )


def _entrypoint_read_methods(view: Any) -> tuple[str, ...]:
    """Prefer canonical proof heads, with explicit legacy-fixture fallback."""

    if (
        getattr(view, "canonical_projection_available", None) is not False
        and callable(getattr(view, "canonical_records", None))
        and callable(getattr(view, "canonical_coverage", None))
    ):
        return ("canonical_records", "canonical_coverage", "validate_real_backing")
    return ("records", "coverage", "validate_real_backing")


def _entrypoint_records(view: Any, *, owner: str) -> tuple[Any, ...]:
    methods = _entrypoint_read_methods(view)
    return tuple(getattr(view, methods[0])(owner=owner) or ())


def _entrypoint_coverage(view: Any, ref: str, *, owner: str) -> Any:
    methods = _entrypoint_read_methods(view)
    return getattr(view, methods[1])(ref, owner=owner)


def _command_qro(command: Any) -> Any:
    payload = getattr(command, "payload", None)
    return payload.get("qro") if isinstance(payload, dict) else None


def m21_ide_strategy_snapshot_hash(strategy: StrategyFile) -> str:
    """Content-bind the exact typed IDE strategy state used by M21."""

    if not isinstance(strategy, StrategyFile):
        raise PlatformBusinessHistoryM16M21Error(
            "M21 IDE snapshot requires a canonical StrategyFile"
        )
    return content_hash(
        {
            "schema_version": 1,
            "record_type": "m21_ide_strategy_snapshot",
            "strategy_id": str(strategy.strategy_id),
            "owner_username": str(strategy.owner_username),
            "name": str(strategy.name),
            "code": str(strategy.code),
            "asset_class": str(strategy.asset_class),
            "description": str(strategy.description),
            "updated_at_utc": str(strategy.updated_at_utc),
            "market_data_use_validation_refs": tuple(
                str(ref)
                for ref in tuple(strategy.market_data_use_validation_refs or ())
            ),
        }
    )


def m21_governed_template_snapshot_hash(asset: GovernedAssetRecord) -> str:
    """Content-bind the full stable governed-template state used by M21."""

    if not isinstance(asset, GovernedAssetRecord):
        raise PlatformBusinessHistoryM16M21Error(
            "M21 template snapshot requires a canonical GovernedAssetRecord"
        )
    return content_hash(
        {
            "schema_version": 1,
            "record_type": "m21_governed_template_snapshot",
            "asset_ref": str(asset.asset_ref),
            "asset_type": str(asset.asset_type),
            "category": _enum_text(asset.category),
            "lifecycle_state": _enum_text(asset.lifecycle_state),
            "evidence_refs": tuple(str(ref) for ref in asset.evidence_refs),
            "validation_plan_ref": asset.validation_plan_ref,
            "promotion_history": tuple(
                str(ref) for ref in asset.promotion_history
            ),
            "source_category": (
                _enum_text(asset.source_category)
                if asset.source_category is not None
                else None
            ),
            "retire_reason": asset.retire_reason,
            "consistency_check_ref": asset.consistency_check_ref,
            "methodology_choice_ref": asset.methodology_choice_ref,
            "responsibility_boundary_ref": asset.responsibility_boundary_ref,
            "display_label": str(asset.display_label),
            "mock_label_ref": asset.mock_label_ref,
            "asset_category_ref": asset.asset_category_ref,
        }
    )


def _prepare_m16(
    *,
    owner: str,
    anchor: str,
    subject: BusinessHistorySubject,
) -> _PreparedBusiness:
    if not isinstance(subject, M16BusinessHistorySubject):
        raise PlatformBusinessHistoryM16M21Error(
            "M16 requires M16BusinessHistorySubject"
        )
    if not isinstance(subject.strategy, SharedStrategy) or not all(
        (
            isinstance(subject.permission, SharedAssetPermissionRecord),
            isinstance(subject.source, SharedAssetSourceRecord),
            isinstance(subject.status, SharedAssetStatusRecord),
            isinstance(subject.governed_asset, GovernedAssetRecord),
        )
    ):
        raise PlatformBusinessHistoryM16M21Error(
            "M16 subject contains non-canonical typed records"
        )
    expected_permission = shared_strategy_permission(subject.strategy)
    expected_source = shared_strategy_source(subject.strategy)
    expected_status = shared_strategy_status(subject.strategy)
    governed_evidence = set(
        _refs(
            subject.governed_asset.evidence_refs,
            field="M16 governed_asset.evidence_refs",
        )
    )
    if (
        subject.strategy.author_id != owner
        or shared_strategy_asset_ref(subject.strategy) != anchor
        or subject.permission != expected_permission
        or subject.source != expected_source
        or subject.status != expected_status
        or any(
            _owner(record) != owner
            for record in (subject.permission, subject.source, subject.status)
        )
        or subject.governed_asset.asset_ref != anchor
        or subject.governed_asset.asset_type != "SharedStrategy"
        or not {
            subject.permission.permission_ref,
            subject.source.source_ref,
            subject.status.status_ref,
        }.issubset(governed_evidence)
    ):
        raise PlatformBusinessHistoryM16M21Error(
            "M16 persisted sharing/lifecycle records are stale or recombined"
        )
    input_contract = {
        "entry_source": EntrySource.API.value,
        "shared_asset_ref": anchor,
        "permission_ref": subject.permission.permission_ref,
        "source_ref": subject.source.source_ref,
    }
    output_contract = {
        "status_ref": subject.status.status_ref,
        "status": subject.status.status,
    }
    evidence = _unique_refs(
        anchor,
        subject.permission.permission_ref,
        subject.source.source_ref,
        subject.status.status_ref,
        subject.governed_asset.evidence_refs,
    )
    return _PreparedBusiness(
        qro_type=QROType.STRATEGY_BOOK,
        input_contract=input_contract,
        output_contract=output_contract,
        market=str(subject.strategy.asset_class or "cross_market"),
        universe=f"shared_strategy:{subject.strategy.share_id}",
        evidence_refs=evidence,
        lifecycle_refs=(anchor,),
        canonical_business_refs=(
            f"sharing_strategy:{subject.strategy.share_id}",
            f"run:{subject.strategy.run_id}",
            subject.permission.permission_ref,
            subject.source.source_ref,
            subject.status.status_ref,
        ),
        event_time=str(subject.strategy.created_at_utc or "").strip() or None,
    )


def _prepare_m19(
    *,
    owner: str,
    anchor: str,
    subject: BusinessHistorySubject,
) -> _PreparedBusiness:
    if not isinstance(subject, M19BusinessHistorySubject):
        raise PlatformBusinessHistoryM16M21Error(
            "M19 requires M19BusinessHistorySubject"
        )
    if not isinstance(subject.bundle, TeachingAssetBundle) or not isinstance(
        subject.governed_asset,
        GovernedAssetRecord,
    ):
        raise PlatformBusinessHistoryM16M21Error(
            "M19 subject contains non-canonical typed records"
        )
    tutorial = subject.bundle.tutorial
    weakness = subject.bundle.weakness
    evidence = subject.bundle.evidence
    weakness_refs = _refs(weakness.weakness_refs, field="M19 weakness_refs")
    teaching_evidence_refs = _refs(
        evidence.evidence_refs,
        field="M19 teaching evidence_refs",
    )
    if (
        tutorial.tutorial_asset_ref != anchor
        or tutorial.tutorial_asset_ref != tutorial.canonical_ref
        or weakness.weakness_disclosure_ref != weakness.canonical_ref
        or evidence.teaching_evidence_ref != evidence.canonical_ref
        or any(_owner(record) != owner for record in (tutorial, weakness, evidence))
        or tutorial.governed_asset_ref != subject.governed_asset.asset_ref
        or weakness.tutorial_asset_ref != anchor
        or evidence.tutorial_asset_ref != anchor
        or evidence.weakness_disclosure_ref != weakness.weakness_disclosure_ref
        or weakness.visible_by_default is not True
        or _enum_text(subject.governed_asset.category) != tutorial.category
        or tutorial.category not in {"tutorial", "example", "template"}
    ):
        raise PlatformBusinessHistoryM16M21Error(
            "M19 persisted teaching/lifecycle records are stale or recombined"
        )
    input_contract = {
        "entry_source": EntrySource.API.value,
        "tutorial_asset_ref": anchor,
        "weakness_disclosure_ref": weakness.weakness_disclosure_ref,
        "teaching_evidence_ref": evidence.teaching_evidence_ref,
        "governed_asset_ref": tutorial.governed_asset_ref,
    }
    output_contract = {
        "status": "teaching_bundle_current",
        "weakness_visible": True,
    }
    history_evidence = _unique_refs(
        anchor,
        weakness.weakness_disclosure_ref,
        evidence.teaching_evidence_ref,
        tutorial.governed_asset_ref,
        weakness_refs,
        teaching_evidence_refs,
    )
    return _PreparedBusiness(
        qro_type=QROType.DOCUMENT_ARTIFACT,
        input_contract=input_contract,
        output_contract=output_contract,
        market="cross_market",
        universe=f"teaching_catalog:{tutorial.category}",
        evidence_refs=history_evidence,
        lifecycle_refs=(tutorial.governed_asset_ref,),
        canonical_business_refs=(
            anchor,
            weakness.weakness_disclosure_ref,
            evidence.teaching_evidence_ref,
            tutorial.governed_asset_ref,
        ),
        event_time=None,
    )


def _prepare_m21(
    *,
    owner: str,
    anchor: str,
    subject: BusinessHistorySubject,
) -> _PreparedBusiness:
    if not isinstance(subject, M21BusinessHistorySubject):
        raise PlatformBusinessHistoryM16M21Error(
            "M21 requires M21BusinessHistorySubject"
        )
    if not isinstance(subject.governed_asset, GovernedAssetRecord) or not isinstance(
        subject.ide_strategy,
        StrategyFile,
    ):
        raise PlatformBusinessHistoryM16M21Error(
            "M21 subject contains non-canonical typed records"
        )
    asset = subject.governed_asset
    governed_asset_ref = _exact(
        asset.asset_ref,
        field="M21 governed asset ref",
    )
    category = _enum_text(asset.category)
    mock_label_ref = _exact(
        asset.mock_label_ref,
        field="M21 mock_label_ref",
        prefix="mock_label:",
    )
    category_ref = _exact(
        asset.asset_category_ref,
        field="M21 asset_category_ref",
        prefix="asset_category:",
    )
    strategy_ref = _exact(
        f"ide_strategy:{subject.ide_strategy.strategy_id}",
        field="M21 IDE strategy ref",
        prefix="ide_strategy:",
    )
    _exact(
        subject.ide_strategy.owner_username,
        field="M21 IDE owner_username",
    )
    asset_class = _exact(
        subject.ide_strategy.asset_class,
        field="M21 IDE asset_class",
    )
    if (
        strategy_ref != anchor
        or category not in {"demo", "template", "example", "tutorial"}
        or asset.asset_type != "StrategyTemplate"
        or not category_ref.startswith(f"asset_category:{asset_class}:")
        or not str(asset.display_label or "").strip()
        or not str(subject.ide_strategy.name or "").strip()
        or not str(subject.ide_strategy.code or "").strip()
    ):
        raise PlatformBusinessHistoryM16M21Error(
            "M21 persisted governed asset/IDE strategy is stale or incomplete"
        )
    input_contract = {
        "entry_source": EntrySource.API.value,
        "governed_asset_ref": governed_asset_ref,
    }
    output_contract = {
        "ide_strategy_ref": strategy_ref,
        "ide_strategy_snapshot_hash": m21_ide_strategy_snapshot_hash(
            subject.ide_strategy
        ),
        "governed_template_snapshot_hash": (
            m21_governed_template_snapshot_hash(asset)
        ),
        "mock_label_ref": mock_label_ref,
        "asset_category_ref": category_ref,
        "status": "template_fork_recorded",
    }
    evidence = _unique_refs(
        governed_asset_ref,
        mock_label_ref,
        category_ref,
        strategy_ref,
        asset.evidence_refs,
    )
    return _PreparedBusiness(
        qro_type=QROType.STRATEGY_BOOK,
        input_contract=input_contract,
        output_contract=output_contract,
        market=asset_class,
        universe=f"governed_template:{category}",
        evidence_refs=evidence,
        lifecycle_refs=(governed_asset_ref,),
        canonical_business_refs=(
            governed_asset_ref,
            mock_label_ref,
            category_ref,
            strategy_ref,
        ),
        event_time=str(subject.ide_strategy.updated_at_utc or "").strip() or None,
    )


def _build_qro(
    *,
    owner: str,
    row: str,
    anchor: str,
    prepared: _PreparedBusiness,
) -> QRORecord:
    implementation_hash = "platform_business_history_" + content_hash(
        {
            "schema_version": 1,
            "row": row,
            "owner_user_id": owner,
            "anchor_ref": anchor,
            "input_contract": prepared.input_contract,
            "output_contract": prepared.output_contract,
        }
    )
    return QRORecord(
        qro_type=prepared.qro_type,
        owner=owner,
        actor=ActorSource.USER_MANUAL,
        input_contract=dict(prepared.input_contract),
        output_contract=dict(prepared.output_contract),
        market=str(prepared.market or "cross_market"),
        universe=str(prepared.universe),
        horizon="business_event",
        frequency="event_driven",
        lineage=_unique_refs(
            anchor,
            tuple(
                value
                for key, value in prepared.input_contract.items()
                if key != "entry_source"
            ),
            tuple(
                value
                for key, value in prepared.output_contract.items()
                if key.endswith("_ref")
            ),
        ),
        implementation_hash=implementation_hash,
        assumptions=(
            "The typed business objects were returned by the owner-scoped write that immediately precedes this history record.",
        ),
        known_limits=(
            "This mathless record proves prospective business history only; it does not claim a Mathematical Spine, CI, production, or user acceptance.",
        ),
        failure_modes=(
            "A duplicate, recombined, foreign-owner, or already-math-bound head invalidates prospective history recording.",
        ),
        validation_plan=(
            "Validate the original business entrypoint, current mathless Graph projection, exact compiler lineage, and strict non-section-14 coverage.",
        ),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.SUFFICIENT,
        governance_status=GovernanceStatus.UNREVIEWED,
        runtime_status=RuntimeStatus.OFFLINE,
        event_time=prepared.event_time,
        evidence_refs=prepared.evidence_refs,
        mathematical_refs=(),
        permission=f"platform.business_history:{row.lower()}:owner",
        responsibility_boundary=(
            "Prospective business-history write only; no Mathematical Spine binding, order, reservation, secret, RDP, or HALT mutation."
        ),
        allowed_environment=RuntimeStatus.OFFLINE,
    )


def _build_command(
    *,
    owner: str,
    row: str,
    qro: QRORecord,
    prepared: _PreparedBusiness,
) -> ResearchGraphCommand:
    entrypoint = ENTRYPOINT_REFS[row]
    timestamp = "content-addressed:" + content_hash(
        {
            "schema_version": 1,
            "entrypoint_ref": entrypoint,
            "qro_ref": qro.qro_id,
            "evidence_refs": prepared.evidence_refs,
        }
    )
    return ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=owner,
        payload={"qro": qro},
        evidence_refs=prepared.evidence_refs,
        tool_record_refs=(entrypoint,),
        timestamp=timestamp,
    )


def _build_compile_plan(
    *,
    owner: str,
    row: str,
    anchor: str,
    qro: QRORecord,
    command: ResearchGraphCommand,
    prepared: _PreparedBusiness,
) -> PlatformBusinessHistoryM16M21CompilePlan:
    entrypoint = ENTRYPOINT_REFS[row]
    row_token = row.lower()
    deterministic_ref = content_hash(
        {
            "qro_ref": qro.qro_id,
            "graph_command_ref": command.command_id,
            "entrypoint_ref": entrypoint,
            "anchor_ref": anchor,
        }
    )
    return PlatformBusinessHistoryM16M21CompilePlan(
        row=row,
        owner_user_id=owner,
        anchor_ref=anchor,
        entrypoint_ref=entrypoint,
        pass_name=f"api_platform_business_history_{row_token}_qro_to_ir",
        validation_refs=(
            f"validation:platform_business_history:{row_token}:{deterministic_ref}",
        ),
        evidence_refs=prepared.evidence_refs,
        environment_lock_ref=f"env:platform_business_history:{row_token}:v1",
        permission_ref=f"platform.business_history:{row_token}:user_manual",
        deterministic_run_plan_ref=(
            f"runplan:platform_business_history:{row_token}:{deterministic_ref}"
        ),
        rollback_ref=(
            f"rollback:platform_business_history:{row_token}:append_only_repair_required"
        ),
        tool_record_refs=(entrypoint, anchor, "api:compile_qro"),
        node_refs=(
            f"qro:{qro.qro_id}",
            f"qro_type:{_enum_text(qro.qro_type)}",
            anchor,
            f"entrypoint:{entrypoint}",
        ),
        canonical_command_refs=_unique_refs(
            f"research_graph_command:{command.command_id}",
            f"entrypoint:{entrypoint}",
            anchor,
            prepared.canonical_business_refs,
        ),
        lifecycle_refs=prepared.lifecycle_refs,
        rdp_refs=(),
        theory_binding_refs=(),
        consistency_check_refs=(),
        mathematical_spine_chain_refs=(),
        goal_sections=_GOAL_SECTIONS[row],
    )


def prepare_platform_business_history_m16_m21(
    *,
    owner_user_id: str,
    row: str,
    anchor_ref: str,
    subject: BusinessHistorySubject,
) -> PlatformBusinessHistoryM16M21Plan:
    """Deterministically plan one prospective mathless business history."""

    owner = _exact(owner_user_id, field="owner_user_id")
    row_token = str(getattr(row, "value", row) or "")
    if row_token not in SUPPORTED_ROWS:
        raise PlatformBusinessHistoryM16M21Error(
            f"unsupported M16/M19/M21 business history row: {row_token!r}"
        )
    anchor = _exact(
        anchor_ref,
        field=f"{row_token} anchor_ref",
        prefix={
            M16: "shared_asset:",
            M19: "tutorial_asset:",
            M21: "ide_strategy:",
        }[row_token],
    )
    prepared = {
        M16: _prepare_m16,
        M19: _prepare_m19,
        M21: _prepare_m21,
    }[row_token](owner=owner, anchor=anchor, subject=subject)
    qro = _build_qro(
        owner=owner,
        row=row_token,
        anchor=anchor,
        prepared=prepared,
    )
    command = _build_command(
        owner=owner,
        row=row_token,
        qro=qro,
        prepared=prepared,
    )
    compile_plan = _build_compile_plan(
        owner=owner,
        row=row_token,
        anchor=anchor,
        qro=qro,
        command=command,
        prepared=prepared,
    )
    if (
        tuple(qro.mathematical_refs)
        or not compile_plan.goal_sections
        or "§14" in compile_plan.goal_sections
        or compile_plan.mathematical_spine_chain_refs
    ):
        raise PlatformBusinessHistoryM16M21Error(
            "business history plan is not strictly mathless/non-section-14"
        )
    return PlatformBusinessHistoryM16M21Plan(
        owner_user_id=owner,
        row=row_token,
        anchor_ref=anchor,
        entrypoint_ref=ENTRYPOINT_REFS[row_token],
        qro=qro,
        command=command,
        compile_plan=compile_plan,
    )


@contextmanager
def _history_transaction(
    context: PlatformBusinessHistoryM16M21Context,
    plan: PlatformBusinessHistoryM16M21Plan,
):
    with _PROCESS_HISTORY_LOCK:
        raw_path = getattr(context.research_graph_store, "path", None)
        if raw_path is None:
            yield
            return
        lock_path = Path(str(raw_path) + ".platform-qro-lineage.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(lock_path, 0o600)
            try:
                held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
                for store in (
                    context.research_graph_store,
                    context.compiler_store,
                    context.entrypoint_registry,
                ):
                    refresh = getattr(store, "refresh", None)
                    if callable(refresh):
                        refresh()
            except Exception as exc:  # noqa: BLE001 - no history write started.
                raise PlatformBusinessHistoryM16M21CommitError(
                    f"business history lock/refresh failed:{type(exc).__name__}:{exc}",
                    phase="history_lock",
                    graph_history_current=None,
                    graph_command_ref=plan.command.command_id,
                    graph_command_created=None,
                    compiler_history_current=None,
                ) from exc
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)


class PlatformBusinessHistoryM16M21Recorder:
    """Persist, observe, and idempotently reuse one exact history head.

    Writes are forward-only: a late failure preserves the exact append prefix,
    and a retry either continues that prefix or reuses the completed bundle.
    """

    def __init__(self, context: PlatformBusinessHistoryM16M21Context) -> None:
        self._context = context
        _require_methods(
            context.research_graph_store,
            ("qro", "commands", "projection_index"),
            label="research_graph_store",
        )
        _require_methods(
            context.compiler_store,
            platform_compiler_snapshot_required_methods(context.compiler_store),
            label="compiler_store",
        )
        _require_methods(
            context.entrypoint_registry,
            _entrypoint_read_methods(context.entrypoint_registry),
            label="entrypoint_registry",
        )
        if not callable(context.apply_graph):
            raise PlatformBusinessHistoryM16M21Error(
                "apply_graph must be callable"
            )
        if not callable(context.compile_history):
            raise PlatformBusinessHistoryM16M21Error(
                "compile_history must be callable"
            )
        if context.entrypoint_view_factory is not None and not callable(
            context.entrypoint_view_factory
        ):
            raise PlatformBusinessHistoryM16M21Error(
                "entrypoint_view_factory must be callable"
            )
        if context.compiler_view_factory is not None and not callable(
            context.compiler_view_factory
        ):
            raise PlatformBusinessHistoryM16M21Error(
                "compiler_view_factory must be callable"
            )
        if context.entrypoint_evidence_view_factory is not None and not callable(
            context.entrypoint_evidence_view_factory
        ):
            raise PlatformBusinessHistoryM16M21Error(
                "entrypoint_evidence_view_factory must be callable"
            )

    def _compiler(self) -> Any:
        view = (
            self._context.compiler_store
            if self._context.compiler_view_factory is None
            else self._context.compiler_view_factory()
        )
        _require_methods(
            view,
            platform_compiler_snapshot_required_methods(view),
            label="fresh compiler view",
        )
        return view

    @staticmethod
    def _require_evidence_store(value: Any) -> Any:
        _require_methods(
            value,
            (
                "evidence",
                "evidences",
                "validate_current",
            ),
            label="entrypoint_evidence_registry",
        )
        return value

    def _attached_evidence_store(self) -> Any | None:
        """Return the exact generic ledger already attached by the compiler.

        The coverage resolver owns the public attachment API.  The recorder
        only unwraps a provider that exposes exact durable listing and current
        validation; it never treats coverage or compiler containment as
        evidence.
        """

        entrypoints = self._context.entrypoint_registry
        resolver = getattr(entrypoints, "_resolver", None)
        if resolver is None:
            resolver = getattr(
                getattr(entrypoints, "_delegate", None),
                "_resolver",
                None,
            )
        attached = getattr(
            resolver,
            "_platform_source_evidence_registry",
            None,
        )
        if attached is None:
            return None
        candidates = tuple(getattr(attached, "registries", ())) or (attached,)
        exact = tuple(
            candidate
            for candidate in candidates
            if all(
                callable(getattr(candidate, method, None))
                for method in (
                    "evidence",
                    "evidences",
                    "validate_current",
                )
            )
        )
        if not exact:
            return None
        compiler_path = getattr(self._context.compiler_store, "path", None)
        if compiler_path is not None:
            expected_path = Path(compiler_path).with_name(
                "entrypoint_evidence.jsonl"
            )
            matching = tuple(
                candidate
                for candidate in exact
                if getattr(candidate, "path", None) == expected_path
            )
            if len(matching) == 1:
                return matching[0]
            if len(matching) > 1:
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence provider is owner/path ambiguous"
                )
        if len(exact) != 1:
            raise PlatformBusinessHistoryM16M21Error(
                "entrypoint evidence provider is ambiguous"
            )
        return exact[0]

    def _entrypoint_evidence(self) -> Any | None:
        factory = self._context.entrypoint_evidence_view_factory
        if factory is not None:
            return self._require_evidence_store(factory())
        configured = self._context.entrypoint_evidence_registry
        if configured is not None:
            return self._require_evidence_store(configured)

        validation_registry = self._context.validation_receipt_registry
        compiler_path = getattr(self._context.compiler_store, "path", None)
        if validation_registry is not None and compiler_path is not None:
            try:
                refresh = getattr(validation_registry, "refresh", None)
                if callable(refresh):
                    refresh()
                return PersistentEntrypointEvidenceRegistry(
                    Path(compiler_path).with_name("entrypoint_evidence.jsonl"),
                    research_graph_store=self._context.research_graph_store,
                    compiler_store=self._compiler(),
                    validation_receipt_registry=validation_registry,
                )
            except Exception as exc:
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence reopen failed:"
                    f"{type(exc).__name__}:{exc}"
                ) from exc
        return self._attached_evidence_store()

    def _entrypoints(self) -> Any:
        view = (
            self._context.entrypoint_registry
            if self._context.entrypoint_view_factory is None
            else self._context.entrypoint_view_factory()
        )
        _require_methods(
            view,
            _entrypoint_read_methods(view),
            label="fresh entrypoint view",
        )
        evidence_store = self._entrypoint_evidence()
        if evidence_store is not None:
            attach = getattr(
                view,
                "attach_platform_source_evidence_registry",
                None,
            )
            if not callable(attach):
                raise PlatformBusinessHistoryM16M21Error(
                    "fresh entrypoint view cannot attach independent evidence"
                )
            attach(CompositeEntrypointEvidenceRegistry((evidence_store,)))
        return view

    def _validate_entrypoint_evidence_binding(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
        *,
        compiler_ir: Any | None = None,
        compiler_pass: Any | None = None,
        coverage: Any | None = None,
        evidence_record: Any | None = None,
        allow_incomplete_compiler: bool = False,
    ) -> str | None:
        """Validate the content-addressed evidence behind one compiler bundle.

        Legacy in-memory harnesses may still present the exact typed-business
        refs.  Those refs remain subject to the entrypoint registry's strict
        real-backing decision.  A current ``entrypoint_evidence:*`` bundle,
        however, is accepted only after reopening the durable evidence record
        and matching its complete owner/QRO/Graph/compiler/GOAL context.
        """

        records = tuple(
            record
            for record in (compiler_ir, compiler_pass, coverage)
            if record is not None
        )
        evidence_sets = tuple(
            tuple(getattr(record, "evidence_refs", ()) or ())
            for record in records
        )
        if evidence_sets and any(refs != evidence_sets[0] for refs in evidence_sets):
            raise PlatformBusinessHistoryM16M21Error(
                "business history compiler/coverage evidence linkage differs"
            )
        linked_refs = evidence_sets[0] if evidence_sets else ()
        if linked_refs == plan.compile_plan.evidence_refs:
            if evidence_record is not None:
                raise PlatformBusinessHistoryM16M21Error(
                    "legacy business refs cannot masquerade as entrypoint evidence"
                )
            return None
        if evidence_record is None:
            if len(linked_refs) != 1 or not linked_refs[0].startswith(
                "entrypoint_evidence:"
            ):
                raise PlatformBusinessHistoryM16M21Error(
                    "business history requires one content-addressed entrypoint evidence ref"
                )
            evidence_ref = _exact(
                linked_refs[0],
                field="entrypoint_evidence_ref",
                prefix="entrypoint_evidence:",
            )
            registry = self._entrypoint_evidence()
            if registry is None:
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence registry is unavailable"
                )
            try:
                evidence_record = registry.evidence(
                    evidence_ref,
                    owner_user_id=plan.owner_user_id,
                )
            except Exception as exc:
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence lookup failed:"
                    f"{type(exc).__name__}:{exc}"
                ) from exc
        else:
            evidence_ref = _exact(
                getattr(evidence_record, "evidence_ref", ""),
                field="entrypoint_evidence_ref",
                prefix="entrypoint_evidence:",
            )
            if linked_refs and linked_refs != (evidence_ref,):
                raise PlatformBusinessHistoryM16M21Error(
                    "compiler lineage does not cite the exact evidence record"
                )
            registry = self._entrypoint_evidence()
            if registry is None:
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence registry is unavailable"
                )

        canonical_ref = _enum_text(
            getattr(evidence_record, "canonical_evidence_ref", "")
        )
        expected = (
            ("owner_user_id", plan.owner_user_id),
            ("entry_source", EntrySource.API.value),
            ("entrypoint_ref", plan.entrypoint_ref),
            ("goal_sections", plan.compile_plan.goal_sections),
            ("qro_ref", plan.qro.qro_id),
            ("research_graph_ref", plan.command.command_id),
            ("actor_source", ActorSource.USER_MANUAL.value),
            ("pass_name", plan.compile_plan.pass_name),
            ("permission_ref", plan.compile_plan.permission_ref),
            ("environment_lock_ref", plan.compile_plan.environment_lock_ref),
            (
                "deterministic_run_plan_ref",
                plan.compile_plan.deterministic_run_plan_ref,
            ),
            ("rollback_ref", plan.compile_plan.rollback_ref),
            ("lifecycle_refs", plan.compile_plan.lifecycle_refs),
            ("rdp_refs", plan.compile_plan.rdp_refs),
            ("theory_binding_refs", plan.compile_plan.theory_binding_refs),
            (
                "consistency_check_refs",
                plan.compile_plan.consistency_check_refs,
            ),
            (
                "mathematical_spine_chain_refs",
                plan.compile_plan.mathematical_spine_chain_refs,
            ),
        )
        if canonical_ref != evidence_ref or any(
            (
                tuple(getattr(evidence_record, field_name, ()) or ())
                if isinstance(expected_value, tuple)
                else _enum_text(getattr(evidence_record, field_name, ""))
            )
            != expected_value
            for field_name, expected_value in expected
        ):
            raise PlatformBusinessHistoryM16M21Error(
                "entrypoint evidence owner/entrypoint/GOAL context is stale or recombined"
            )

        validation_ref = _enum_text(
            getattr(evidence_record, "validation_ref", "")
        )
        if compiler_ir is not None:
            if (
                _enum_text(getattr(evidence_record, "compiler_ir_ref", ""))
                != _enum_text(getattr(compiler_ir, "ir_ref", ""))
                or validation_ref
                not in tuple(getattr(compiler_ir, "validation_refs", ()) or ())
            ):
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence compiler IR/validation identity differs"
                )
        if compiler_pass is not None:
            if (
                _enum_text(getattr(evidence_record, "compiler_pass_ref", ""))
                != _enum_text(getattr(compiler_pass, "pass_ref", ""))
                or validation_ref
                not in tuple(getattr(compiler_pass, "validation_refs", ()) or ())
            ):
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence compiler pass/validation identity differs"
                )
        if coverage is not None:
            if (
                _enum_text(getattr(evidence_record, "coverage_ref", ""))
                != _enum_text(getattr(coverage, "coverage_ref", ""))
                or validation_ref
                not in tuple(getattr(coverage, "validation_refs", ()) or ())
            ):
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence coverage/validation identity differs"
                )
        elif compiler_ir is not None and compiler_pass is not None:
            expected_coverage_ref = goal_entrypoint_coverage_identity(
                entry_source=EntrySource.API,
                entrypoint_ref=plan.entrypoint_ref,
                goal_sections=plan.compile_plan.goal_sections,
                qro_refs=(plan.qro.qro_id,),
                research_graph_command_refs=(plan.command.command_id,),
                compiler_ir_refs=(
                    _enum_text(getattr(compiler_ir, "ir_ref", "")),
                ),
                compiler_pass_refs=(
                    _enum_text(getattr(compiler_pass, "pass_ref", "")),
                ),
            )
            if (
                _enum_text(getattr(evidence_record, "coverage_ref", ""))
                != expected_coverage_ref
            ):
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence predicted coverage identity differs"
                )

        try:
            decision = registry.validate_current(
                evidence_record,
                owner_user_id=plan.owner_user_id,
            )
        except Exception as exc:
            raise PlatformBusinessHistoryM16M21Error(
                "entrypoint evidence current validation failed:"
                f"{type(exc).__name__}:{exc}"
            ) from exc
        if not bool(getattr(decision, "accepted", False)):
            violations = tuple(getattr(decision, "violations", ()) or ())
            incomplete_only = (
                bool(allow_incomplete_compiler)
                and (compiler_ir is None or compiler_pass is None)
                and bool(violations)
                and all(
                    _enum_text(getattr(item, "code", ""))
                    == "entrypoint_evidence_compiler_linkage_invalid"
                    for item in violations
                )
            )
            if not incomplete_only:
                status = ",".join(
                    f"{_enum_text(getattr(item, 'code', ''))}:"
                    f"{_enum_text(getattr(item, 'field', ''))}"
                    for item in violations
                )
                raise PlatformBusinessHistoryM16M21Error(
                    "entrypoint evidence is not current"
                    + (f":{status}" if status else "")
                )
        return evidence_ref

    def _entrypoint_evidence_snapshot(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
    ) -> dict[str, Any]:
        registry = self._entrypoint_evidence()
        if registry is None:
            return {}
        try:
            rows = tuple(
                registry.evidences(owner_user_id=plan.owner_user_id) or ()
            )
        except Exception as exc:
            raise PlatformBusinessHistoryM16M21Error(
                "entrypoint evidence snapshot failed:"
                f"{type(exc).__name__}:{exc}"
            ) from exc
        return {
            _exact(
                getattr(record, "evidence_ref", ""),
                field="entrypoint_evidence_ref",
                prefix="entrypoint_evidence:",
            ): record
            for record in rows
        }

    @staticmethod
    def _graph_command_exact(
        plan: PlatformBusinessHistoryM16M21Plan,
        command: Any,
    ) -> bool:
        return (
            command == plan.command
            and _command_qro(command) == plan.qro
            and _enum_text(getattr(command, "source", ""))
            == EntrySource.API.value
            and _enum_text(getattr(command, "actor_source", ""))
            == ActorSource.USER_MANUAL.value
            and _owner(command) == plan.owner_user_id
            and tuple(getattr(command, "tool_record_refs", ()) or ())
            == (plan.entrypoint_ref,)
            and not tuple(getattr(plan.qro, "mathematical_refs", ()) or ())
        )

    def _commands_for_history(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
    ) -> tuple[Any, ...]:
        candidates: list[Any] = []
        anchor_contract, anchor_field = _ANCHOR_CONTRACT_FIELDS[plan.row]
        for command in tuple(self._context.research_graph_store.commands() or ()):
            embedded = _command_qro(command)
            if embedded is None or _owner(embedded) != plan.owner_user_id:
                continue
            same_qro = (
                _enum_text(getattr(embedded, "qro_id", "")) == plan.qro.qro_id
            )
            input_contract = getattr(embedded, "input_contract", None)
            output_contract = getattr(embedded, "output_contract", None)
            anchor_contract_value = getattr(embedded, anchor_contract, None)
            contract_anchor = (
                _enum_text(anchor_contract_value.get(anchor_field, ""))
                if isinstance(anchor_contract_value, dict)
                else ""
            )
            new_m21_contract = (
                plan.row != M21
                or (
                    isinstance(input_contract, dict)
                    and isinstance(output_contract, dict)
                    and "governed_asset_ref" in input_contract
                    and "asset_ref" not in input_contract
                    and output_contract.get("ide_strategy_ref")
                    == plan.anchor_ref
                )
            )
            same_business_anchor = (
                plan.entrypoint_ref
                in tuple(getattr(command, "tool_record_refs", ()) or ())
                and new_m21_contract
                and (
                    contract_anchor == plan.anchor_ref
                    or (
                        plan.row != M21
                        and (
                            plan.anchor_ref
                            in tuple(getattr(command, "evidence_refs", ()) or ())
                            or plan.anchor_ref
                            in tuple(getattr(embedded, "lineage", ()) or ())
                        )
                    )
                )
            )
            if same_qro or same_business_anchor:
                candidates.append(command)
        return tuple(candidates)

    def _existing_graph_command(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
    ) -> Any | None:
        graph = self._context.research_graph_store
        commands = self._commands_for_history(plan)
        for command in commands:
            embedded = _command_qro(command)
            if tuple(getattr(embedded, "mathematical_refs", ()) or ()):
                raise PlatformBusinessHistoryM16M21Error(
                    "prospective history is forbidden after a current Mathematical Spine head"
                )
            if embedded != plan.qro or not self._graph_command_exact(plan, command):
                raise PlatformBusinessHistoryM16M21Error(
                    "business history Graph command is stale, different, or recombined"
                )
        if len(commands) > 1:
            raise PlatformBusinessHistoryM16M21Error(
                "duplicate business history Graph commands exist for one QRO"
            )

        try:
            stored_qro = graph.qro(plan.qro.qro_id)
        except (KeyError, LookupError):
            stored_qro = None
        except Exception as exc:
            raise PlatformBusinessHistoryM16M21Error(
                f"business history QRO lookup failed:{type(exc).__name__}:{exc}"
            ) from exc
        projections = tuple(
            item
            for item in tuple(graph.projection_index(owner=plan.owner_user_id) or ())
            if _enum_text(getattr(item, "qro_id", "")) == plan.qro.qro_id
        )
        if stored_qro is None:
            if commands or projections:
                raise PlatformBusinessHistoryM16M21Error(
                    "business history command/projection exists without its QRO"
                )
            return None
        if tuple(getattr(stored_qro, "mathematical_refs", ()) or ()):
            raise PlatformBusinessHistoryM16M21Error(
                "prospective history is forbidden after a current Mathematical Spine head"
            )
        if stored_qro != plan.qro:
            raise PlatformBusinessHistoryM16M21Error(
                "business history QRO identity is stale, different, or recombined"
            )
        if len(commands) != 1 or len(projections) != 1:
            raise PlatformBusinessHistoryM16M21Error(
                "business history QRO must have one command and one current projection"
            )
        projection = projections[0]
        if (
            _owner(projection) != plan.owner_user_id
            or _enum_text(getattr(projection, "command_id", ""))
            != plan.command.command_id
            or _enum_text(getattr(projection, "source", ""))
            != EntrySource.API.value
            or _enum_text(getattr(projection, "actor", ""))
            != plan.owner_user_id
            or tuple(getattr(projection, "mathematical_refs", ()) or ())
        ):
            raise PlatformBusinessHistoryM16M21Error(
                "business history current projection is stale or recombined"
            )
        return commands[0]

    def _relevant_compiler(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
    ) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
        owner = plan.owner_user_id
        compiler = platform_compiler_snapshot(
            self._compiler(),
            owner=owner,
        )
        qro_ref = plan.qro.qro_id
        command_ref = plan.command.command_id
        irs = tuple(
            record
            for record in compiler.irs
            if qro_ref in tuple(getattr(record, "source_qro_refs", ()) or ())
            or command_ref in tuple(getattr(record, "graph_command_refs", ()) or ())
        )
        passes = tuple(
            record
            for record in compiler.passes
            if qro_ref in tuple(getattr(record, "input_qro_refs", ()) or ())
            or command_ref in tuple(getattr(record, "graph_command_refs", ()) or ())
        )
        return irs, passes

    def _coverage_candidates(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
    ) -> tuple[Any, ...]:
        view = self._entrypoints()
        try:
            records = _entrypoint_records(view, owner=plan.owner_user_id)
        except Exception as exc:
            raise PlatformBusinessHistoryM16M21Error(
                f"business history coverage listing failed:{type(exc).__name__}:{exc}"
            ) from exc
        return tuple(
            record
            for record in records
            if plan.qro.qro_id in tuple(getattr(record, "qro_refs", ()) or ())
            or plan.command.command_id
            in tuple(getattr(record, "research_graph_command_refs", ()) or ())
        )

    def _preflight_partial_state(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
        *,
        graph_exists: bool,
    ) -> None:
        irs, passes = self._relevant_compiler(plan)
        coverage = self._coverage_candidates(plan)
        if len(irs) > 1 or len(passes) > 1 or len(coverage) > 1:
            raise PlatformBusinessHistoryM16M21Error(
                "duplicate compiler/coverage state targets the business history head"
            )
        if not graph_exists and (irs or passes or coverage):
            raise PlatformBusinessHistoryM16M21Error(
                "compiler/coverage state exists before its business history Graph head"
            )
        if irs:
            compiler_ir = irs[0]
            try:
                self._validate_entrypoint_evidence_binding(
                    plan,
                    compiler_ir=compiler_ir,
                    compiler_pass=(passes[0] if passes else None),
                    allow_incomplete_compiler=not passes,
                )
            except PlatformBusinessHistoryM16M21Error as exc:
                raise PlatformBusinessHistoryM16M21Error(
                    "partial business history compiler IR is stale, recombined, or carries math"
                ) from exc
            canonical_refs = tuple(
                getattr(compiler_ir, "canonical_command_refs", ()) or ()
            )
            if (
                _owner(compiler_ir) != plan.owner_user_id
                or tuple(getattr(compiler_ir, "source_qro_refs", ()) or ())
                != (plan.qro.qro_id,)
                or tuple(getattr(compiler_ir, "graph_command_refs", ()) or ())
                != (plan.command.command_id,)
                or len(canonical_refs) != len(set(canonical_refs))
                or canonical_refs != plan.compile_plan.canonical_command_refs
                or tuple(getattr(compiler_ir, "node_refs", ()) or ())
                != plan.compile_plan.node_refs
                or tuple(getattr(compiler_ir, "edge_refs", ()) or ())
                or tuple(getattr(compiler_ir, "artifact_refs", ()) or ())
                or tuple(getattr(compiler_ir, "theory_binding_refs", ()) or ())
                != plan.compile_plan.theory_binding_refs
                or tuple(
                    getattr(compiler_ir, "consistency_check_refs", ()) or ()
                )
                != plan.compile_plan.consistency_check_refs
                or not _has_exact_trusted_validation_refs(
                    getattr(compiler_ir, "validation_refs", ()),
                )
                or _enum_text(getattr(compiler_ir, "permission_ref", ""))
                != plan.compile_plan.permission_ref
                or _enum_text(
                    getattr(compiler_ir, "deterministic_run_plan_ref", "")
                )
                != plan.compile_plan.deterministic_run_plan_ref
                or _enum_text(getattr(compiler_ir, "rollback_ref", ""))
                != plan.compile_plan.rollback_ref
                or _enum_text(getattr(compiler_ir, "environment_lock_ref", ""))
                != plan.compile_plan.environment_lock_ref
                or tuple(
                    getattr(compiler_ir, "mathematical_spine_chain_refs", ()) or ()
                )
                or _enum_text(getattr(compiler_ir, "target_runtime", ""))
                != RuntimeStatus.OFFLINE.value
                or _enum_text(getattr(compiler_ir, "mock_profile", ""))
                != "none"
            ):
                raise PlatformBusinessHistoryM16M21Error(
                    "partial business history compiler IR is stale, recombined, or carries math"
                )
        if passes:
            compiler_pass = passes[0]
            if not irs or (
                _owner(compiler_pass) != plan.owner_user_id
                or _enum_text(getattr(compiler_pass, "pass_name", ""))
                != plan.compile_plan.pass_name
                or _enum_text(getattr(compiler_pass, "entry_source", ""))
                != EntrySource.API.value
                or _enum_text(getattr(compiler_pass, "actor_source", ""))
                != ActorSource.USER_MANUAL.value
                or tuple(getattr(compiler_pass, "input_ir_refs", ()) or ())
                != ()
                or tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
                != (plan.qro.qro_id,)
                or tuple(getattr(compiler_pass, "graph_command_refs", ()) or ())
                != (plan.command.command_id,)
                or _enum_text(getattr(compiler_pass, "output_ir_ref", ""))
                != _enum_text(getattr(irs[0], "ir_ref", ""))
                or tuple(
                    getattr(compiler_pass, "canonical_command_refs", ()) or ()
                )
                != tuple(getattr(irs[0], "canonical_command_refs", ()) or ())
                or _enum_text(getattr(compiler_pass, "permission_ref", ""))
                != plan.compile_plan.permission_ref
                or tuple(getattr(compiler_pass, "tool_record_refs", ()) or ())
                != plan.compile_plan.tool_record_refs
                or tuple(getattr(compiler_pass, "validation_refs", ()) or ())
                != tuple(getattr(irs[0], "validation_refs", ()) or ())
                or _enum_text(
                    getattr(compiler_pass, "deterministic_run_plan_ref", "")
                )
                != plan.compile_plan.deterministic_run_plan_ref
                or _enum_text(getattr(compiler_pass, "rollback_ref", ""))
                != plan.compile_plan.rollback_ref
                or _enum_text(getattr(compiler_pass, "status", ""))
                != "compiled"
                or bool(getattr(compiler_pass, "direct_graph_mutation", False))
                or bool(getattr(compiler_pass, "bypassed_permission", False))
                or bool(
                    getattr(compiler_pass, "raw_llm_output_embedded_as_ir", False)
                )
            ):
                raise PlatformBusinessHistoryM16M21Error(
                    "partial business history compiler pass is stale or recombined"
                )
        if coverage and (not irs or not passes):
            raise PlatformBusinessHistoryM16M21Error(
                "business history coverage exists without complete compiler state"
            )

    def _validate_persisted_lineage(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
        *,
        coverage_ref: str,
    ) -> tuple[str, str, str]:
        command = self._existing_graph_command(plan)
        if command is None:
            raise PlatformBusinessHistoryM16M21Error(
                "business history coverage exists without its Graph head"
            )
        self._preflight_partial_state(plan, graph_exists=True)
        candidates = self._coverage_candidates(plan)
        if len(candidates) != 1:
            raise PlatformBusinessHistoryM16M21Error(
                "business history coverage must be unique for its QRO/Graph head"
            )
        coverage = candidates[0]
        if _enum_text(getattr(coverage, "coverage_ref", "")) != coverage_ref:
            raise PlatformBusinessHistoryM16M21Error(
                "business history coverage ref is stale or recombined"
            )
        view = self._entrypoints()
        try:
            stored_coverage = _entrypoint_coverage(
                view,
                coverage_ref,
                owner=plan.owner_user_id,
            )
            decision = view.validate_real_backing(stored_coverage)
            if not bool(getattr(decision, "accepted", False)):
                raise PlatformBusinessHistoryM16M21Error(
                    "business history coverage lacks strict real backing"
                )
            ir_ref = tuple(stored_coverage.compiler_ir_refs)
            pass_ref = tuple(stored_coverage.compiler_pass_refs)
            if len(ir_ref) != 1 or len(pass_ref) != 1:
                raise PlatformBusinessHistoryM16M21Error(
                    "business history coverage must bind one compiler IR/pass"
                )
            compiler = platform_compiler_snapshot(
                self._compiler(),
                owner=plan.owner_user_id,
            )
            compiler_ir = compiler.ir(ir_ref[0])
            compiler_pass = compiler.compiler_pass(pass_ref[0])
            stored_qro = self._context.research_graph_store.qro(plan.qro.qro_id)
        except PlatformBusinessHistoryM16M21Error:
            raise
        except Exception as exc:
            raise PlatformBusinessHistoryM16M21Error(
                f"persisted business history lookup failed:{type(exc).__name__}:{exc}"
            ) from exc
        expected_coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=EntrySource.API,
            entrypoint_ref=plan.entrypoint_ref,
            goal_sections=plan.compile_plan.goal_sections,
            qro_refs=(plan.qro.qro_id,),
            research_graph_command_refs=(plan.command.command_id,),
            compiler_ir_refs=(ir_ref[0],),
            compiler_pass_refs=(pass_ref[0],),
        )
        sections = tuple(
            _enum_text(section)
            for section in tuple(stored_coverage.goal_sections or ())
        )
        irs, passes = self._relevant_compiler(plan)
        canonical_refs = tuple(
            getattr(compiler_ir, "canonical_command_refs", ()) or ()
        )
        expected_replay_refs = (
            f"replay:research_graph:{plan.command.command_id}",
            f"replay:compiler_ir:{ir_ref[0]}",
            f"replay:compiler_pass:{pass_ref[0]}",
        )
        try:
            self._validate_entrypoint_evidence_binding(
                plan,
                compiler_ir=compiler_ir,
                compiler_pass=compiler_pass,
                coverage=stored_coverage,
            )
        except PlatformBusinessHistoryM16M21Error as exc:
            raise PlatformBusinessHistoryM16M21Error(
                "persisted business history is stale, different, or recombined"
            ) from exc
        if (
            coverage_ref != expected_coverage_ref
            or stored_coverage != coverage
            or _owner(stored_coverage) != plan.owner_user_id
            or _enum_text(stored_coverage.entry_source) != EntrySource.API.value
            or _enum_text(stored_coverage.entrypoint_ref) != plan.entrypoint_ref
            or not sections
            or sections != plan.compile_plan.goal_sections
            or "§14" in sections
            or tuple(stored_coverage.qro_refs) != (plan.qro.qro_id,)
            or tuple(stored_coverage.research_graph_command_refs)
            != (plan.command.command_id,)
            or stored_qro != plan.qro
            or tuple(plan.qro.mathematical_refs)
            or tuple(compiler_ir.source_qro_refs) != (plan.qro.qro_id,)
            or tuple(compiler_ir.graph_command_refs)
            != (plan.command.command_id,)
            or tuple(compiler_ir.mathematical_spine_chain_refs)
            or _owner(compiler_ir) != plan.owner_user_id
            or _enum_text(compiler_pass.output_ir_ref) != ir_ref[0]
            or tuple(compiler_pass.input_qro_refs) != (plan.qro.qro_id,)
            or tuple(compiler_pass.graph_command_refs)
            != (plan.command.command_id,)
            or _owner(compiler_pass) != plan.owner_user_id
            or _enum_text(compiler_pass.actor_source)
            != ActorSource.USER_MANUAL.value
            or _enum_text(compiler_pass.entry_source) != EntrySource.API.value
            or tuple(compiler_pass.canonical_command_refs) != canonical_refs
            or tuple(stored_coverage.canonical_command_refs) != canonical_refs
            or tuple(getattr(stored_coverage, "validation_refs", ()) or ())
            != tuple(getattr(compiler_ir, "validation_refs", ()) or ())
            or tuple(getattr(stored_coverage, "permission_refs", ()) or ())
            != (plan.compile_plan.permission_ref,)
            or tuple(getattr(stored_coverage, "replay_refs", ()) or ())
            != expected_replay_refs
            or tuple(getattr(stored_coverage, "lifecycle_refs", ()) or ())
            != plan.compile_plan.lifecycle_refs
            or tuple(getattr(stored_coverage, "rdp_refs", ()) or ())
            != plan.compile_plan.rdp_refs
            or bool(
                getattr(stored_coverage, "claims_full_product_entrypoint", False)
            )
            or bool(getattr(stored_coverage, "silent_mock_fallback_used", False))
            or bool(getattr(stored_coverage, "raw_payload_persisted", False))
            or irs != (compiler_ir,)
            or passes != (compiler_pass,)
        ):
            raise PlatformBusinessHistoryM16M21Error(
                "persisted business history is stale, different, or recombined"
            )
        return ir_ref[0], pass_ref[0], coverage_ref

    def _observe(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
    ) -> _ObservedHistory:
        command_observed: bool | None
        try:
            commands = tuple(self._context.research_graph_store.commands() or ())
            observed = tuple(
                command
                for command in commands
                if _enum_text(getattr(command, "command_id", ""))
                == plan.command.command_id
                and command == plan.command
            )
            command_observed = len(observed) == 1
        except Exception:  # noqa: BLE001 - observation must not mask commit state.
            command_observed = None
        try:
            graph_current = self._existing_graph_command(plan) is not None
        except PlatformBusinessHistoryM16M21Error:
            graph_current = False
        except Exception:  # noqa: BLE001 - durable state is genuinely unknown.
            graph_current = None
        compiler_observed = True
        try:
            irs, passes = self._relevant_compiler(plan)
        except Exception:  # noqa: BLE001 - report unknown without masking cause.
            irs, passes = (), ()
            compiler_observed = False
        coverage_observed = True
        try:
            coverage = self._coverage_candidates(plan)
        except Exception:  # noqa: BLE001 - report unknown without masking cause.
            coverage = ()
            coverage_observed = False
        ir_ref = (
            _enum_text(getattr(irs[0], "ir_ref", "")) if len(irs) == 1 else ""
        )
        pass_ref = (
            _enum_text(getattr(passes[0], "pass_ref", ""))
            if len(passes) == 1
            else ""
        )
        coverage_ref = (
            _enum_text(getattr(coverage[0], "coverage_ref", ""))
            if len(coverage) == 1
            else ""
        )
        compiler_current: bool | None = None
        if graph_current is False:
            compiler_current = False
        elif graph_current and compiler_observed and coverage_observed:
            compiler_current = False
        if graph_current and compiler_observed and coverage_observed and coverage_ref:
            try:
                self._validate_persisted_lineage(
                    plan,
                    coverage_ref=coverage_ref,
                )
            except PlatformBusinessHistoryM16M21Error:
                pass
            except Exception:  # noqa: BLE001 - currentness cannot be established.
                compiler_current = None
            else:
                compiler_current = True
        return _ObservedHistory(
            graph_current=graph_current,
            command_observed=command_observed,
            compiler_current=compiler_current,
            compiler_ir_ref=ir_ref,
            compiler_pass_ref=pass_ref,
            coverage_ref=coverage_ref,
        )

    @staticmethod
    def _result(
        plan: PlatformBusinessHistoryM16M21Plan,
        *,
        created: bool,
        ir_ref: str,
        pass_ref: str,
        coverage_ref: str,
    ) -> PlatformBusinessHistoryM16M21Result:
        return PlatformBusinessHistoryM16M21Result(
            owner_user_id=plan.owner_user_id,
            row=plan.row,
            anchor_ref=plan.anchor_ref,
            entrypoint_ref=plan.entrypoint_ref,
            qro_ref=plan.qro.qro_id,
            graph_command_ref=plan.command.command_id,
            graph_command_created=created,
            compiler_ir_ref=ir_ref,
            compiler_pass_ref=pass_ref,
            entrypoint_coverage_ref=coverage_ref,
        )

    def _record_locked(
        self,
        plan: PlatformBusinessHistoryM16M21Plan,
    ) -> PlatformBusinessHistoryM16M21Result:
        existing = self._existing_graph_command(plan)
        coverage = self._coverage_candidates(plan)
        if len(coverage) > 1:
            raise PlatformBusinessHistoryM16M21Error(
                "duplicate business history coverage records exist"
            )
        if coverage:
            if existing is None:
                raise PlatformBusinessHistoryM16M21Error(
                    "business history coverage exists without its Graph head"
                )
            coverage_ref = _exact(
                getattr(coverage[0], "coverage_ref", ""),
                field="entrypoint_coverage_ref",
            )
            ir_ref, pass_ref, coverage_ref = self._validate_persisted_lineage(
                plan,
                coverage_ref=coverage_ref,
            )
            return self._result(
                plan,
                created=False,
                ir_ref=ir_ref,
                pass_ref=pass_ref,
                coverage_ref=coverage_ref,
            )

        self._preflight_partial_state(plan, graph_exists=existing is not None)
        created = False
        if existing is None:
            try:
                returned_ref = self._context.apply_graph(plan.command)
            except Exception as exc:  # noqa: BLE001 - report observed append state.
                observed = self._observe(plan)
                raise PlatformBusinessHistoryM16M21CommitError(
                    f"Research Graph business history write failed:{type(exc).__name__}:{exc}",
                    phase="research_graph",
                    graph_history_current=observed.graph_current,
                    graph_command_ref=plan.command.command_id,
                    graph_command_created=observed.command_observed,
                    compiler_history_current=observed.compiler_current,
                    compiler_ir_ref=observed.compiler_ir_ref,
                    compiler_pass_ref=observed.compiler_pass_ref,
                    entrypoint_coverage_ref=observed.coverage_ref,
                ) from exc
            observed = self._observe(plan)
            if _enum_text(returned_ref) != plan.command.command_id:
                raise PlatformBusinessHistoryM16M21CommitError(
                    "Research Graph business history write returned a different command ref",
                    phase="research_graph_ack",
                    graph_history_current=observed.graph_current,
                    graph_command_ref=plan.command.command_id,
                    graph_command_created=observed.command_observed,
                    compiler_history_current=observed.compiler_current,
                    compiler_ir_ref=observed.compiler_ir_ref,
                    compiler_pass_ref=observed.compiler_pass_ref,
                    entrypoint_coverage_ref=observed.coverage_ref,
                )
            if not observed.graph_current:
                raise PlatformBusinessHistoryM16M21CommitError(
                    "Research Graph business history write is not the exact current head",
                    phase="research_graph_verify",
                    graph_history_current=observed.graph_current,
                    graph_command_ref=plan.command.command_id,
                    graph_command_created=observed.command_observed,
                )
            created = True

        try:
            compiled = self._context.compile_history(
                plan.qro,
                plan.command,
                plan.compile_plan,
            )
            if not isinstance(compiled, Mapping):
                raise TypeError("compile_history result must be a mapping")
            if set(compiled) != {
                "compiler_ir_ref",
                "compiler_pass_ref",
                "entrypoint_coverage_ref",
            }:
                raise ValueError(
                    "compile_history result must contain exactly the three persisted refs"
                )
            ir_ref = _exact(compiled.get("compiler_ir_ref"), field="compiler_ir_ref")
            pass_ref = _exact(
                compiled.get("compiler_pass_ref"),
                field="compiler_pass_ref",
            )
            coverage_ref = _exact(
                compiled.get("entrypoint_coverage_ref"),
                field="entrypoint_coverage_ref",
            )
            verified = self._validate_persisted_lineage(
                plan,
                coverage_ref=coverage_ref,
            )
            if verified != (ir_ref, pass_ref, coverage_ref):
                raise PlatformBusinessHistoryM16M21Error(
                    "compiler callback refs differ from persisted business history"
                )
        except Exception as exc:  # noqa: BLE001 - report observed compiler boundary.
            evidence_observation_failure = ""
            try:
                current_evidence = self._entrypoint_evidence_snapshot(plan)
            except Exception as observation_exc:  # noqa: BLE001 - preserve original failure.
                current_evidence = {}
                evidence_observation_failure = (
                    f"{type(observation_exc).__name__}:{observation_exc}"
                )
            preserved_evidence = tuple(
                record
                for record in current_evidence.values()
                if _enum_text(getattr(record, "owner_user_id", ""))
                == plan.owner_user_id
                and _enum_text(getattr(record, "entrypoint_ref", ""))
                == plan.entrypoint_ref
                and _enum_text(getattr(record, "qro_ref", ""))
                == plan.qro.qro_id
                and _enum_text(getattr(record, "research_graph_ref", ""))
                == plan.command.command_id
            )
            observed = self._observe(plan)
            raise PlatformBusinessHistoryM16M21CommitError(
                f"compiler/coverage business history write failed:{type(exc).__name__}:{exc}"
                + (
                    "; forward-only entrypoint evidence prefix preserved:"
                    + ",".join(
                        _enum_text(getattr(record, "evidence_ref", ""))
                        for record in preserved_evidence
                    )
                    if preserved_evidence
                    else ""
                )
                + (
                    "; entrypoint evidence observation failed:"
                    + evidence_observation_failure
                    if evidence_observation_failure
                    else ""
                ),
                phase="compiler_coverage",
                graph_history_current=observed.graph_current,
                graph_command_ref=plan.command.command_id,
                graph_command_created=observed.command_observed,
                compiler_history_current=observed.compiler_current,
                compiler_ir_ref=observed.compiler_ir_ref,
                compiler_pass_ref=observed.compiler_pass_ref,
                entrypoint_coverage_ref=observed.coverage_ref,
            ) from exc
        return self._result(
            plan,
            created=created,
            ir_ref=ir_ref,
            pass_ref=pass_ref,
            coverage_ref=coverage_ref,
        )

    def record(
        self,
        *,
        owner_user_id: str,
        row: str,
        anchor_ref: str,
        subject: BusinessHistorySubject,
    ) -> PlatformBusinessHistoryM16M21Result:
        plan = prepare_platform_business_history_m16_m21(
            owner_user_id=owner_user_id,
            row=row,
            anchor_ref=anchor_ref,
            subject=subject,
        )
        with _history_transaction(self._context, plan):
            return self._record_locked(plan)


def record_platform_business_history_m16_m21(
    *,
    context: PlatformBusinessHistoryM16M21Context,
    owner_user_id: str,
    row: str,
    anchor_ref: str,
    subject: BusinessHistorySubject,
) -> PlatformBusinessHistoryM16M21Result:
    """Record or reuse one prospective business history."""

    return PlatformBusinessHistoryM16M21Recorder(context).record(
        owner_user_id=owner_user_id,
        row=row,
        anchor_ref=anchor_ref,
        subject=subject,
    )


__all__ = [
    "ENTRYPOINT_REFS",
    "M16",
    "M19",
    "M21",
    "SUPPORTED_ROWS",
    "M16BusinessHistorySubject",
    "M19BusinessHistorySubject",
    "M21BusinessHistorySubject",
    "PlatformBusinessHistoryM16M21CommitError",
    "PlatformBusinessHistoryM16M21CompilePlan",
    "PlatformBusinessHistoryM16M21Context",
    "PlatformBusinessHistoryM16M21Error",
    "PlatformBusinessHistoryM16M21Plan",
    "PlatformBusinessHistoryM16M21Recorder",
    "PlatformBusinessHistoryM16M21Result",
    "m21_governed_template_snapshot_hash",
    "m21_ide_strategy_snapshot_hash",
    "prepare_platform_business_history_m16_m21",
    "record_platform_business_history_m16_m21",
]
