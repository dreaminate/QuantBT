"""Typed-source adapters for GOAL section 14 rows M16-M21.

Only source families with an exact owner-scoped getter and a cross-source
lineage check are registered.  Community, IDE, and teaching rows remain
unavailable here until their complete required bundles have canonical typed
identities; a same-owner record or a reference-shaped string is not a
substitute for that missing producer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..ide.service import StrategyFile
from .asset_lifecycle import AssetCategory, GovernedAssetRecord
from .platform_business_history_m16_m21 import (
    m21_governed_template_snapshot_hash,
    m21_ide_strategy_snapshot_hash,
)
from .platform_coverage import PlatformCapabilityRecord
from .platform_typed_sources import (
    PlatformRowLinkValidator,
    PlatformTypedSourceAdapter,
)


M16 = "M16"
M17 = "M17"
M18 = "M18"
M19 = "M19"
M20 = "M20"
M21 = "M21"


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _owner_of(value: Any) -> str:
    return _text(getattr(value, "owner_user_id", getattr(value, "owner", "")))


def _row(record: PlatformCapabilityRecord) -> str:
    return _text(record.m_row)


def _specific(record: PlatformCapabilityRecord) -> dict[str, str]:
    return {_text(item.key): _text(item.ref) for item in record.specific_refs}


def _strings(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        token = value.strip()
        if token:
            found.add(token)
    elif isinstance(value, dict):
        for key, child in value.items():
            found.update(_strings(key))
            found.update(_strings(child))
    elif isinstance(value, (tuple, list, set, frozenset)):
        for child in value:
            found.update(_strings(child))
    elif value is not None and hasattr(value, "__dict__"):
        found.update(_strings(vars(value)))
    return found


def _qro_math_binding_violations(
    qro: Any,
    chain: Any,
    *,
    record: PlatformCapabilityRecord,
    owner: str,
    label: str,
) -> tuple[str, ...]:
    """Require one explicit QRO -> verified Mathematical Spine binding.

    M16-M21 business refs are not quant-stage refs and must not be accepted
    merely because they occur somewhere in a chain object's metadata.  The
    business QRO binds those refs in its typed contracts; its single declared
    Mathematical Spine ref binds the independently verified chain.
    """

    expected = _text(record.math_spine_ref)
    declared = tuple(
        _text(ref) for ref in tuple(getattr(qro, "mathematical_refs", ()) or ())
    )
    violations: list[str] = []
    if not expected or declared != (expected,):
        violations.append(
            f"{label} QRO must bind exactly the selected Mathematical Spine chain"
        )
    if chain is not None:
        if _text(getattr(chain, "chain_ref", "")) != expected:
            violations.append(f"{label} Mathematical Spine identity mismatch")
        recorded_by = _text(getattr(chain, "recorded_by", ""))
        if recorded_by and recorded_by != owner:
            violations.append(f"{label} Mathematical Spine owner mismatch")
    return tuple(violations)


@dataclass(frozen=True)
class PlatformSourceAdaptersM16M21Context:
    research_graph_store: Any = None
    onboarding_registry: Any = None
    llm_call_record_store: Any = None
    account_halt_barrier: Any = None
    asset_lifecycle_registry: Any = None
    rag_index: Any = None
    spine_chain_registry: Any = None
    llm_service_owner_user_id: str = ""
    copy_trade_service: Any = None
    runtime_promotion_registry: Any = None
    follower_risk_state_store: Any = None
    execution_order_submission_registry: Any = None
    canonical_spine_ledger: Any = None
    rdp_store: Any = None
    sharing_service: Any = None
    teaching_asset_registry: Any = None
    ide_strategy_loader: Callable[[str, str], Any] | None = None


@dataclass(frozen=True)
class ResolvedSecretSource:
    secret_ref: str
    stored_owner_user_id: str
    record: Any


@dataclass(frozen=True)
class ResolvedLLMGatewaySource:
    gateway_ref: str
    terminal_record: Any


@dataclass(frozen=True)
class ResolvedIDEConsistencySource:
    check_ref: str
    check: Any
    binding: Any
    rdp_manifest: Any


_STATIC_UNAVAILABLE: dict[str, tuple[str, ...]] = {
}


def unavailable_platform_source_rows_m16_m21(
    context: PlatformSourceAdaptersM16M21Context,
) -> dict[str, tuple[str, ...]]:
    unavailable = dict(_STATIC_UNAVAILABLE)
    m16_missing = tuple(
        name
        for name, value in (
            ("research_graph_store", context.research_graph_store),
            ("sharing_service", context.sharing_service),
            ("asset_lifecycle_registry", context.asset_lifecycle_registry),
            ("rag_index", context.rag_index),
            ("spine_chain_registry", context.spine_chain_registry),
        )
        if value is None
    )
    if m16_missing:
        unavailable[M16] = tuple(f"missing dependency:{name}" for name in m16_missing)
    m20_missing = tuple(
        name
        for name, value in (
            ("research_graph_store", context.research_graph_store),
            ("onboarding_registry", context.onboarding_registry),
            ("llm_call_record_store", context.llm_call_record_store),
            ("account_halt_barrier", context.account_halt_barrier),
            ("rag_index", context.rag_index),
            ("spine_chain_registry", context.spine_chain_registry),
        )
        if value is None
    )
    if m20_missing:
        unavailable[M20] = tuple(f"missing dependency:{name}" for name in m20_missing)
    m21_missing = tuple(
        name
        for name, value in (
            ("research_graph_store", context.research_graph_store),
            ("asset_lifecycle_registry", context.asset_lifecycle_registry),
            ("rag_index", context.rag_index),
            ("spine_chain_registry", context.spine_chain_registry),
            ("ide_strategy_loader", context.ide_strategy_loader),
        )
        if value is None
    )
    if m21_missing:
        unavailable[M21] = tuple(f"missing dependency:{name}" for name in m21_missing)
    m17_missing = tuple(
        name
        for name, value in (
            ("research_graph_store", context.research_graph_store),
            ("copy_trade_service", context.copy_trade_service),
            ("runtime_promotion_registry", context.runtime_promotion_registry),
            ("follower_risk_state_store", context.follower_risk_state_store),
            (
                "execution_order_submission_registry",
                context.execution_order_submission_registry,
            ),
            ("rag_index", context.rag_index),
            ("spine_chain_registry", context.spine_chain_registry),
        )
        if value is None
    )
    if m17_missing:
        unavailable[M17] = tuple(f"missing dependency:{name}" for name in m17_missing)
    m18_missing = tuple(
        name
        for name, value in (
            ("research_graph_store", context.research_graph_store),
            ("canonical_spine_ledger", context.canonical_spine_ledger),
            ("rdp_store", context.rdp_store),
            ("rag_index", context.rag_index),
            ("spine_chain_registry", context.spine_chain_registry),
        )
        if value is None
    )
    if m18_missing:
        unavailable[M18] = tuple(f"missing dependency:{name}" for name in m18_missing)
    m19_missing = tuple(
        name
        for name, value in (
            ("research_graph_store", context.research_graph_store),
            ("teaching_asset_registry", context.teaching_asset_registry),
            ("asset_lifecycle_registry", context.asset_lifecycle_registry),
            ("rag_index", context.rag_index),
            ("spine_chain_registry", context.spine_chain_registry),
        )
        if value is None
    )
    if m19_missing:
        unavailable[M19] = tuple(f"missing dependency:{name}" for name in m19_missing)
    return unavailable


def _m16(
    context: PlatformSourceAdaptersM16M21Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    sharing = context.sharing_service
    lifecycle = context.asset_lifecycle_registry
    rag = context.rag_index
    spine = context.spine_chain_registry

    def load_shared(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M16:
            raise LookupError("shared asset adapter only supports M16")
        return sharing.shared_asset(ref, owner_user_id=owner)

    def validate_shared(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        from ..sharing.service import shared_strategy_asset_ref

        violations: list[str] = []
        if _text(getattr(value, "author_id", "")) != owner:
            violations.append("M16 shared asset owner mismatch")
        if shared_strategy_asset_ref(value) != _specific(record).get("shared_asset_ref"):
            violations.append("M16 shared asset identity mismatch")
        return tuple(violations)

    def load_permission(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M16:
            raise LookupError("shared permission adapter only supports M16")
        return sharing.permission(ref, owner_user_id=owner)

    def load_source(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M16:
            raise LookupError("shared source adapter only supports M16")
        return sharing.source(ref, owner_user_id=owner)

    def load_status(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M16:
            raise LookupError("shared status adapter only supports M16")
        return sharing.status(ref, owner_user_id=owner)

    def validate_typed(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("M16 shared governance record owner mismatch")
        refs = _specific(record)
        identity_pairs = (
            ("permission_ref", "permission_ref"),
            ("source_ref", "source_ref"),
            ("status_ref", "status_ref"),
        )
        matching = [
            key
            for key, attribute in identity_pairs
            if _text(getattr(value, attribute, "")) == refs.get(key)
        ]
        if len(matching) != 1:
            violations.append("M16 shared governance record identity mismatch")
        if _text(getattr(value, "shared_asset_ref", "")) != refs.get("shared_asset_ref"):
            violations.append("M16 shared governance record asset mismatch")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        strategy = values.get("shared_asset_ref")
        permission = values.get("permission_ref")
        source = values.get("source_ref")
        status = values.get("status_ref")
        if any(item is None for item in (strategy, permission, source, status)):
            return ("M16 requires exact shared asset permission, source, and status records",)
        violations: list[str] = []
        shared_ref = _specific(record).get("shared_asset_ref", "")
        if _text(record.lifecycle_ref) != shared_ref:
            violations.append("M16 common lifecycle ref is not the shared strategy asset")
        if any(
            _text(getattr(item, "shared_asset_ref", "")) != shared_ref
            for item in (permission, source, status)
        ):
            violations.append("M16 governance records recombine different shared assets")
        if _text(getattr(source, "run_id", "")) != _text(getattr(strategy, "run_id", "")):
            violations.append("M16 shared source run mismatch")
        expected_visibility = "public" if bool(getattr(strategy, "public", False)) else "owner_only"
        if _text(getattr(permission, "visibility", "")) != expected_visibility:
            violations.append("M16 sharing permission does not match current visibility")
        expected_status = "published_public" if bool(getattr(strategy, "public", False)) else "published_private"
        if _text(getattr(status, "status", "")) != expected_status:
            violations.append("M16 sharing status does not match current publication state")
        try:
            asset = lifecycle.governed_asset(shared_ref, owner_user_id=owner)
        except Exception as exc:  # noqa: BLE001
            asset = None
            violations.append(f"M16 governed shared asset lookup failed:{type(exc).__name__}")
        if asset is not None:
            if _text(getattr(asset, "asset_ref", "")) != shared_ref:
                violations.append("M16 lifecycle lookup returned a different shared asset")
            if _text(getattr(asset, "asset_type", "")) != "SharedStrategy":
                violations.append("M16 lifecycle asset type is not SharedStrategy")
            lifecycle_evidence = set(_strings(getattr(asset, "evidence_refs", ())))
            required_evidence = {
                _specific(record).get("permission_ref", ""),
                _specific(record).get("source_ref", ""),
                _specific(record).get("status_ref", ""),
            }
            if not required_evidence.issubset(lifecycle_evidence):
                violations.append("M16 lifecycle omits permission/source/status lineage")
        exact_refs = set(_specific(record).values())
        try:
            qro = graph.qro(_text(record.qro_ref))
        except Exception as exc:  # noqa: BLE001
            return (*violations, f"M16 QRO lookup failed:{type(exc).__name__}")
        if _owner_of(qro) != owner:
            violations.append("M16 QRO owner mismatch")
        qro_refs = _strings(getattr(qro, "input_contract", None)) | _strings(
            getattr(qro, "output_contract", None)
        )
        if not exact_refs.issubset(qro_refs):
            violations.append("M16 QRO contracts do not bind every sharing source")
        try:
            document = rag.document_for_owner(
                _text(record.rag_ref), owner_user_id=owner, require_current=True
            )
        except Exception as exc:  # noqa: BLE001
            document = None
            violations.append(f"M16 RAG lookup failed:{type(exc).__name__}")
        if document is not None and not exact_refs.issubset(
            _strings(getattr(document, "metadata", None))
        ):
            violations.append("M16 RAG metadata does not bind every sharing source")
        try:
            chain = spine.verified_chain(_text(record.math_spine_ref), owner=owner)
        except Exception as exc:  # noqa: BLE001
            chain = None
            violations.append(f"M16 Mathematical Spine lookup failed:{type(exc).__name__}")
        violations.extend(
            _qro_math_binding_violations(
                qro, chain, record=record, owner=owner, label="M16"
            )
        )
        return tuple(violations)

    return (
        {
            "shared_asset_ref": PlatformTypedSourceAdapter(
                source_kind="shared_strategy_asset",
                load=load_shared,
                validate_linkage=validate_shared,
            ),
            "permission_ref": PlatformTypedSourceAdapter(
                source_kind="shared_strategy_permission",
                load=load_permission,
                validate_linkage=validate_typed,
            ),
            "source_ref": PlatformTypedSourceAdapter(
                source_kind="shared_strategy_source",
                load=load_source,
                validate_linkage=validate_typed,
            ),
            "status_ref": PlatformTypedSourceAdapter(
                source_kind="shared_strategy_status",
                load=load_status,
                validate_linkage=validate_typed,
            ),
        },
        validate_row,
    )


def _m17(
    context: PlatformSourceAdaptersM16M21Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    subscriptions = context.copy_trade_service
    promotions = context.runtime_promotion_registry
    risks = context.follower_risk_state_store
    submissions = context.execution_order_submission_registry
    rag = context.rag_index
    spine = context.spine_chain_registry

    def load_subscription(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M17:
            raise LookupError("copy-trade subscription adapter only supports M17")
        return subscriptions.subscription(ref, owner_user_id=owner)

    def validate_subscription(
        value: Any,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner and _text(getattr(value, "user_id", "")) != owner:
            violations.append("M17 subscription owner mismatch")
        if _text(getattr(value, "status", "")) == "stopped":
            violations.append("M17 subscription is terminally stopped")
        try:
            from ..copy_trade.service import copy_trade_subscription_ref

            current_ref = copy_trade_subscription_ref(value)
        except (AttributeError, TypeError, ValueError):
            current_ref = ""
        if current_ref != _specific(record).get("copy_trade_subscription_ref"):
            violations.append("M17 current subscription identity mismatch")
        return tuple(violations)

    def load_promotion(ref: str, _owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M17:
            raise LookupError("runtime promotion adapter only supports M17")
        return promotions.promotion(ref)

    def validate_promotion(
        value: Any,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _text(getattr(value, "runtime_promotion_ref", "")) != _specific(record).get(
            "runtime_promotion_ref"
        ):
            violations.append("M17 runtime promotion identity mismatch")
        if _text(getattr(value, "target_runtime", "")) != "live":
            violations.append("M17 runtime promotion is not the live boundary")
        if not _text(getattr(value, "permission_gate_ref", "")) or not _text(
            getattr(value, "order_guard_ref", "")
        ):
            violations.append("M17 runtime promotion lacks permission/order guards")
        return tuple(violations)

    def load_risk(ref: str, _owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M17:
            raise LookupError("copy-trade risk gate adapter only supports M17")
        return risks.reservation_by_risk_check_ref(ref)

    def validate_risk(
        value: Any,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        if _text(getattr(value, "risk_check_ref", "")) != _specific(record).get(
            "risk_gate_ref"
        ):
            return ("M17 risk gate identity mismatch",)
        return ()

    def load_audit(ref: str, _owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M17:
            raise LookupError("copy-trade execution audit adapter only supports M17")
        return submissions.submission_by_audit_record_ref(ref)

    def validate_audit(
        value: Any,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _text(getattr(value, "audit_record_ref", "")) != _specific(record).get(
            "execution_audit_ref"
        ):
            violations.append("M17 execution audit identity mismatch")
        if not bool(getattr(value, "submit_enabled", False)):
            violations.append("M17 execution audit is not a guarded enabled submission")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        follower = values.get("copy_trade_subscription_ref")
        promotion = values.get("runtime_promotion_ref")
        reservation = values.get("risk_gate_ref")
        submission = values.get("execution_audit_ref")
        if any(item is None for item in (follower, promotion, reservation, submission)):
            return (
                "M17 requires the exact subscription, promotion, risk gate, and submission audit",
            )
        violations: list[str] = []
        follower_id = _text(getattr(follower, "follower_id", ""))
        account_ref = _text(getattr(follower, "account_binding_ref", ""))
        promotion_ref = _text(getattr(promotion, "runtime_promotion_ref", ""))
        if _text(record.lifecycle_ref) != promotion_ref:
            violations.append("M17 common lifecycle ref is not the selected runtime promotion")
        if not follower_id or not account_ref:
            violations.append("M17 subscription lacks follower/account identity")
        if _text(getattr(follower, "runtime_promotion_ref", "")) != promotion_ref:
            violations.append("M17 subscription does not bind the selected runtime promotion")
        expected_subject = ""
        if follower_id and account_ref:
            try:
                from ..lineage.ids import content_hash

                expected_subject = "copy_trade_subject_" + content_hash(
                    {
                        "follower_id": follower_id,
                        "user_id": _text(getattr(follower, "user_id", "")),
                        "master_id": _text(getattr(follower, "master_id", "")),
                        "account_binding_ref": account_ref,
                    }
                )
            except (TypeError, ValueError):
                expected_subject = ""
        if _text(getattr(promotion, "subject_ref", "")) != expected_subject:
            violations.append("M17 runtime promotion subject does not bind the subscription")
        if _text(getattr(reservation, "follower_id", "")) != follower_id:
            violations.append("M17 risk gate follower mismatch")
        if _text(getattr(reservation, "account_binding_ref", "")) != account_ref:
            violations.append("M17 risk gate account mismatch")
        if _text(getattr(submission, "runtime_promotion_ref", "")) != promotion_ref:
            violations.append("M17 submission runtime promotion mismatch")
        if _text(getattr(submission, "permission_gate_ref", "")) != _text(
            getattr(promotion, "permission_gate_ref", "")
        ):
            violations.append("M17 submission permission gate mismatch")
        if _text(getattr(submission, "order_guard_ref", "")) != _text(
            getattr(promotion, "order_guard_ref", "")
        ):
            violations.append("M17 submission order guard mismatch")
        try:
            bound_reservation = risks.reservation_for_submission(
                _text(getattr(submission, "submission_ref", ""))
            )
        except Exception as exc:  # noqa: BLE001 - exact source resolution fails closed.
            bound_reservation = None
            violations.append(f"M17 formal risk binding lookup failed:{type(exc).__name__}")
        if bound_reservation is not None and bound_reservation != reservation:
            violations.append("M17 submission recombines a different risk reservation")

        refs = _specific(record)
        exact_refs = set(refs.values())
        try:
            qro = graph.qro(_text(record.qro_ref))
        except Exception as exc:  # noqa: BLE001
            return (*violations, f"M17 QRO lookup failed:{type(exc).__name__}")
        if _owner_of(qro) != owner:
            violations.append("M17 QRO owner mismatch")
        declared = _strings(getattr(qro, "input_contract", None)) | _strings(
            getattr(qro, "output_contract", None)
        )
        if not exact_refs.issubset(declared):
            violations.append("M17 QRO contracts do not bind every selected execution source")
        try:
            document = rag.document_for_owner(
                _text(record.rag_ref), owner_user_id=owner, require_current=True
            )
        except Exception as exc:  # noqa: BLE001
            document = None
            violations.append(f"M17 RAG lookup failed:{type(exc).__name__}")
        if document is not None and not exact_refs.issubset(
            _strings(getattr(document, "metadata", None))
        ):
            violations.append("M17 RAG metadata does not bind every selected execution source")
        try:
            chain = spine.verified_chain(_text(record.math_spine_ref), owner=owner)
        except Exception as exc:  # noqa: BLE001
            chain = None
            violations.append(f"M17 Mathematical Spine lookup failed:{type(exc).__name__}")
        violations.extend(
            _qro_math_binding_violations(
                qro, chain, record=record, owner=owner, label="M17"
            )
        )
        return tuple(violations)

    return (
        {
            "copy_trade_subscription_ref": PlatformTypedSourceAdapter(
                source_kind="copy_trade_subscription",
                load=load_subscription,
                validate_linkage=validate_subscription,
            ),
            "runtime_promotion_ref": PlatformTypedSourceAdapter(
                source_kind="runtime_promotion",
                load=load_promotion,
                validate_linkage=validate_promotion,
            ),
            "risk_gate_ref": PlatformTypedSourceAdapter(
                source_kind="copy_trade_risk_gate",
                load=load_risk,
                validate_linkage=validate_risk,
            ),
            "execution_audit_ref": PlatformTypedSourceAdapter(
                source_kind="copy_trade_guarded_submission_audit",
                load=load_audit,
                validate_linkage=validate_audit,
            ),
        },
        validate_row,
    )


def _m18(
    context: PlatformSourceAdaptersM16M21Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    ledger = context.canonical_spine_ledger
    rdps = context.rdp_store
    rag = context.rag_index
    spine = context.spine_chain_registry

    def load_command(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if (
            _row(record) != M18
            or ref != _specific(record).get("canonical_code_command_ref", "")
        ):
            raise LookupError(
                "M18 canonical code command must equal its selected IDE source ref"
            )
        matches = [
            command
            for command in graph.commands()
            if _text(getattr(command, "command_id", "")) == ref
        ]
        if len(matches) != 1:
            raise LookupError("M18 canonical IDE command is missing or ambiguous")
        command = matches[0]
        payload = getattr(command, "payload", None)
        qro = payload.get("qro") if isinstance(payload, dict) else None
        if (
            _text(getattr(command, "actor", "")) != owner
            or _text(getattr(command, "source", "")) != "ide"
            or qro is None
            or _owner_of(qro) != owner
        ):
            raise LookupError("M18 canonical command is not the owned IDE QRO command")
        return command

    def validate_command(
        value: Any,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _text(getattr(value, "command_id", "")) != _specific(record).get(
            "canonical_code_command_ref"
        ):
            violations.append("M18 canonical code command identity mismatch")
        if _text(getattr(value, "actor", "")) != owner:
            violations.append("M18 canonical code command owner mismatch")
        if _text(getattr(value, "source", "")) != "ide":
            violations.append("M18 canonical code command is not an IDE command")
        payload = getattr(value, "payload", None)
        qro = payload.get("qro") if isinstance(payload, dict) else None
        if qro is None or _owner_of(qro) != owner:
            violations.append("M18 canonical IDE QRO owner mismatch")
        return tuple(violations)

    def load_check(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M18:
            raise LookupError("ConsistencyCheck adapter only supports M18")
        check = ledger.check(ref, owner=owner)
        binding = ledger.binding(_text(getattr(check, "binding_id", "")), owner=owner)
        command_ref = _specific(record).get("canonical_code_command_ref", "")
        package_ref = _text(record.lifecycle_ref)
        matches = []
        for manifest in rdps.manifests(owner_user_id=owner):
            if (
                _text(getattr(manifest, "package_id", "")) == package_ref
                and command_ref
                in tuple(getattr(manifest, "graph_refs", ()) or ())
                and ref in tuple(getattr(manifest, "consistency_check_refs", ()) or ())
            ):
                matches.append(manifest)
        if len(matches) != 1:
            raise LookupError("M18 command/check must resolve to one exact owner RDP")
        return ResolvedIDEConsistencySource(ref, check, binding, matches[0])

    def validate_check(
        value: ResolvedIDEConsistencySource,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        check = value.check
        binding = value.binding
        manifest = value.rdp_manifest
        command_ref = _specific(record).get("canonical_code_command_ref", "")
        if value.check_ref != _specific(record).get("consistency_check_ref"):
            violations.append("M18 ConsistencyCheck identity mismatch")
        if _text(getattr(manifest, "package_id", "")) != _text(
            record.lifecycle_ref
        ):
            violations.append("M18 ConsistencyCheck resolved through a different RDP")
        if _text(getattr(check, "result", "")) != "pass":
            violations.append("M18 ConsistencyCheck is not pass")
        if _text(getattr(check, "binding_id", "")) != _text(
            getattr(binding, "binding_id", "")
        ):
            violations.append("M18 ConsistencyCheck binding mismatch")
        linked = _strings(getattr(check, "input_refs", ())) | _strings(
            getattr(binding, "used_by", ())
        )
        if command_ref not in linked:
            violations.append("M18 ConsistencyCheck/binding does not cite the code command")
        if not tuple(getattr(manifest, "test_refs", ()) or ()):
            violations.append("M18 RDP has no tests")
        if tuple(getattr(manifest, "unverified_residuals", ()) or ()):
            violations.append("M18 RDP retains unverified residuals")
        if value.check_ref not in tuple(
            getattr(manifest, "consistency_check_refs", ()) or ()
        ):
            violations.append("M18 RDP omits the ConsistencyCheck")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        command = values.get("canonical_code_command_ref")
        check_source = values.get("consistency_check_ref")
        if command is None or not isinstance(check_source, ResolvedIDEConsistencySource):
            return ("M18 requires the exact IDE command, ConsistencyCheck, binding, and RDP",)
        violations: list[str] = []
        payload = getattr(command, "payload", None)
        qro = payload.get("qro") if isinstance(payload, dict) else None
        inputs = getattr(qro, "input_contract", None)
        if not isinstance(inputs, dict) or _text(inputs.get("entry_source")) != "ide":
            violations.append("M18 QRO is not an IDE code workflow")
        code_hash = _text(inputs.get("code_hash")) if isinstance(inputs, dict) else ""
        if not code_hash:
            violations.append("M18 IDE QRO lacks a code hash")
        manifest = check_source.rdp_manifest
        if _text(record.lifecycle_ref) != _text(getattr(manifest, "package_id", "")):
            violations.append("M18 common lifecycle ref is not the selected RDP manifest")
        command_ref = _specific(record).get("canonical_code_command_ref", "")
        graph_refs = tuple(getattr(manifest, "graph_refs", ()) or ())
        code_refs = tuple(getattr(manifest, "code_refs", ()) or ())
        if graph_refs.count(command_ref) != 1:
            violations.append("M18 RDP does not bind one exact IDE command")
        if code_hash and code_refs.count(code_hash) != 1:
            violations.append("M18 RDP does not bind the IDE code hash")
        exact_refs = set(_specific(record).values())
        if not exact_refs.issubset(
            set(graph_refs)
            | set(getattr(manifest, "consistency_check_refs", ()) or ())
        ):
            violations.append("M18 RDP does not bind both selected sources")
        if qro is None or _owner_of(qro) != owner:
            violations.append("M18 QRO owner mismatch")
        try:
            chain = spine.verified_chain(_text(record.math_spine_ref), owner=owner)
        except Exception as exc:  # noqa: BLE001
            chain = None
            violations.append(f"M18 Mathematical Spine lookup failed:{type(exc).__name__}")
        chain_refs = tuple(
            getattr(manifest, "mathematical_spine_chain_refs", ()) or ()
        )
        if chain_refs != (_text(record.math_spine_ref),):
            violations.append(
                "M18 RDP does not bind the exact verified Mathematical Spine chain"
            )
        if (
            chain is None
            or _text(getattr(chain, "chain_ref", ""))
            != _text(record.math_spine_ref)
            or _text(
                getattr(chain, "recorded_by", _owner_of(chain))
            )
            != owner
        ):
            violations.append("M18 Mathematical Spine owner/identity mismatch")
        try:
            document = rag.document_for_owner(
                _text(record.rag_ref), owner_user_id=owner, require_current=True
            )
        except Exception as exc:  # noqa: BLE001
            document = None
            violations.append(f"M18 RAG lookup failed:{type(exc).__name__}")
        if document is not None and not exact_refs.issubset(
            _strings(getattr(document, "metadata", None))
        ):
            violations.append("M18 RAG metadata does not bind both selected sources")
        return tuple(violations)

    return (
        {
            "canonical_code_command_ref": PlatformTypedSourceAdapter(
                source_kind="ide_research_graph_code_command",
                load=load_command,
                validate_linkage=validate_command,
            ),
            "consistency_check_ref": PlatformTypedSourceAdapter(
                source_kind="ide_consistency_binding_rdp",
                load=load_check,
                validate_linkage=validate_check,
            ),
        },
        validate_row,
    )


def _m19(
    context: PlatformSourceAdaptersM16M21Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    teaching = context.teaching_asset_registry
    lifecycle = context.asset_lifecycle_registry
    rag = context.rag_index
    spine = context.spine_chain_registry

    def load_tutorial(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M19:
            raise LookupError("tutorial asset adapter only supports M19")
        return teaching.tutorial_asset(ref, owner_user_id=owner)

    def load_weakness(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M19:
            raise LookupError("weakness disclosure adapter only supports M19")
        return teaching.weakness_disclosure(ref, owner_user_id=owner)

    def load_evidence(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M19:
            raise LookupError("teaching evidence adapter only supports M19")
        return teaching.teaching_evidence(ref, owner_user_id=owner)

    def validate_typed(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("M19 teaching record owner mismatch")
        refs = _specific(record)
        candidates = (
            ("tutorial_asset_ref", "tutorial_asset_ref"),
            ("weakness_disclosure_ref", "weakness_disclosure_ref"),
            ("teaching_evidence_ref", "teaching_evidence_ref"),
        )
        if len(
            [key for key, attr in candidates if _text(getattr(value, attr, "")) == refs.get(key)]
        ) != 1:
            violations.append("M19 teaching record identity mismatch")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        tutorial = values.get("tutorial_asset_ref")
        weakness = values.get("weakness_disclosure_ref")
        evidence = values.get("teaching_evidence_ref")
        if any(item is None for item in (tutorial, weakness, evidence)):
            return ("M19 requires exact tutorial, visible weakness, and teaching evidence records",)
        violations: list[str] = []
        tutorial_ref = _text(getattr(tutorial, "tutorial_asset_ref", ""))
        weakness_ref = _text(getattr(weakness, "weakness_disclosure_ref", ""))
        if (
            _text(getattr(weakness, "tutorial_asset_ref", "")) != tutorial_ref
            or _text(getattr(evidence, "tutorial_asset_ref", "")) != tutorial_ref
            or _text(getattr(evidence, "weakness_disclosure_ref", "")) != weakness_ref
        ):
            violations.append("M19 teaching records recombine different bundles")
        if bool(getattr(weakness, "visible_by_default", False)) is not True:
            violations.append("M19 weaknesses are not visible by default")
        governed_ref = _text(getattr(tutorial, "governed_asset_ref", ""))
        if _text(record.lifecycle_ref) != governed_ref:
            violations.append("M19 lifecycle ref does not equal the tutorial governed asset")
        try:
            asset = lifecycle.governed_asset(governed_ref, owner_user_id=owner)
        except Exception as exc:  # noqa: BLE001
            asset = None
            violations.append(f"M19 governed tutorial lookup failed:{type(exc).__name__}")
        if asset is not None:
            if _text(getattr(asset, "category", "")) != _text(
                getattr(tutorial, "category", "")
            ):
                violations.append("M19 governed tutorial category mismatch")
            if _text(getattr(asset, "category", "")) not in {"tutorial", "example", "template"}:
                violations.append("M19 governed asset is not a teaching category")
        teaching_evidence_refs = set(
            _text(ref) for ref in tuple(getattr(evidence, "evidence_refs", ()) or ())
        )
        if not teaching_evidence_refs or not teaching_evidence_refs.issubset(
            set(_text(ref) for ref in record.evidence_refs)
        ):
            violations.append("M19 row evidence omits the teaching evidence lineage")
        exact_refs = set(_specific(record).values())
        try:
            qro = graph.qro(_text(record.qro_ref))
        except Exception as exc:  # noqa: BLE001
            return (*violations, f"M19 QRO lookup failed:{type(exc).__name__}")
        if _owner_of(qro) != owner:
            violations.append("M19 QRO owner mismatch")
        if not exact_refs.issubset(
            _strings(getattr(qro, "input_contract", None))
            | _strings(getattr(qro, "output_contract", None))
        ):
            violations.append("M19 QRO contracts do not bind every teaching source")
        try:
            document = rag.document_for_owner(
                _text(record.rag_ref), owner_user_id=owner, require_current=True
            )
        except Exception as exc:  # noqa: BLE001
            document = None
            violations.append(f"M19 RAG lookup failed:{type(exc).__name__}")
        if document is not None and not exact_refs.issubset(
            _strings(getattr(document, "metadata", None))
        ):
            violations.append("M19 RAG metadata does not bind every teaching source")
        try:
            chain = spine.verified_chain(_text(record.math_spine_ref), owner=owner)
        except Exception as exc:  # noqa: BLE001
            chain = None
            violations.append(f"M19 Mathematical Spine lookup failed:{type(exc).__name__}")
        violations.extend(
            _qro_math_binding_violations(
                qro, chain, record=record, owner=owner, label="M19"
            )
        )
        return tuple(violations)

    return (
        {
            "tutorial_asset_ref": PlatformTypedSourceAdapter(
                source_kind="tutorial_asset",
                load=load_tutorial,
                validate_linkage=validate_typed,
            ),
            "weakness_disclosure_ref": PlatformTypedSourceAdapter(
                source_kind="visible_weakness_disclosure",
                load=load_weakness,
                validate_linkage=validate_typed,
            ),
            "teaching_evidence_ref": PlatformTypedSourceAdapter(
                source_kind="teaching_evidence",
                load=load_evidence,
                validate_linkage=validate_typed,
            ),
        },
        validate_row,
    )


def _m20(
    context: PlatformSourceAdaptersM16M21Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    onboarding = context.onboarding_registry
    calls = context.llm_call_record_store
    halts = context.account_halt_barrier
    rag = context.rag_index
    spine = context.spine_chain_registry
    service_owner = _text(context.llm_service_owner_user_id)

    def load_secret(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M20:
            raise LookupError("SecretRef adapter only supports M20")
        candidates = tuple(dict.fromkeys((owner, service_owner)))
        matches: list[ResolvedSecretSource] = []
        for stored_owner in candidates:
            if not stored_owner:
                continue
            try:
                stored = onboarding.secret_ref(ref, owner_user_id=stored_owner)
            except (KeyError, LookupError, PermissionError, TypeError, ValueError):
                continue
            if _text(getattr(stored, "secret_ref", "")) == ref:
                matches.append(ResolvedSecretSource(ref, stored_owner, stored))
        if len(matches) != 1:
            raise LookupError("SecretRef is missing or ambiguous across owner/service scopes")
        return matches[0]

    def validate_secret(
        value: ResolvedSecretSource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        if _row(record) != M20:
            violations.append("SecretRef is not attached to M20")
        if value.secret_ref != _specific(record).get("secret_ref"):
            violations.append("M20 SecretRef identity mismatch")
        if value.stored_owner_user_id not in {owner, service_owner}:
            violations.append("M20 SecretRef owner/service-principal mismatch")
        if _text(getattr(value.record, "status", "")) == "revoked":
            violations.append("M20 SecretRef is revoked")
        return tuple(violations)

    def load_gateway(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M20 or not ref.startswith("llm_gateway:"):
            raise LookupError("LLM gateway ref is not canonical for M20")
        call_id = ref.removeprefix("llm_gateway:")
        if not call_id:
            raise LookupError("LLM gateway call id is required")
        records = calls.read_all(owner_user_id=owner)
        matches = [
            item
            for item in records
            if _text(getattr(item, "call_id", "")) == call_id
            and _text(getattr(item, "record_kind", "")) == "terminal"
        ]
        if len(matches) != 1:
            raise LookupError("LLM gateway terminal record is missing or ambiguous")
        return ResolvedLLMGatewaySource(ref, matches[0])

    def validate_gateway(
        value: ResolvedLLMGatewaySource,
        owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        terminal = value.terminal_record
        if value.gateway_ref != _specific(record).get("llm_gateway_ref"):
            violations.append("M20 LLM gateway identity mismatch")
        if _owner_of(terminal) != owner:
            violations.append("M20 LLM gateway owner mismatch")
        if _text(getattr(terminal, "status", "")) != "ok":
            violations.append("M20 LLM gateway terminal status is not ok")
        return tuple(violations)

    def load_halt(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M20:
            raise LookupError("account HALT adapter only supports M20")
        evidence = halts.halt_evidence(ref, owner_user_id=owner)
        if _text(getattr(evidence, "halt_ref", "")) != ref:
            raise LookupError("account HALT evidence identity mismatch")
        return evidence

    def validate_halt(value: Any, owner: str, record: PlatformCapabilityRecord) -> tuple[str, ...]:
        violations: list[str] = []
        if _owner_of(value) != owner:
            violations.append("M20 account HALT owner mismatch")
        if _text(getattr(value, "halt_ref", "")) != _specific(record).get(
            "kill_switch_ref"
        ):
            violations.append("M20 account HALT identity mismatch")
        accounts = tuple(getattr(value, "account_binding_refs", ()) or ())
        flat = tuple(getattr(value, "flat_proof_refs", ()) or ())
        if _text(getattr(value, "owner_state", "")) != "halted":
            violations.append("M20 account HALT is not terminally halted")
        if not accounts or len(flat) != len(accounts) or not all(_text(item) for item in flat):
            violations.append("M20 account HALT lacks complete flat proofs")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        secret = values.get("secret_ref")
        gateway = values.get("llm_gateway_ref")
        halt = values.get("kill_switch_ref")
        if not isinstance(secret, ResolvedSecretSource) or not isinstance(
            gateway, ResolvedLLMGatewaySource
        ) or halt is None:
            return ("M20 requires the exact SecretRef, terminal LLM call, and account HALT evidence",)
        violations: list[str] = []
        terminal = gateway.terminal_record
        if _text(getattr(terminal, "auth_ref", "")) != secret.secret_ref:
            violations.append("M20 terminal LLM call does not use the selected SecretRef")
        if _text(record.lifecycle_ref) != _text(getattr(halt, "halt_ref", "")):
            violations.append("M20 common lifecycle ref is not the selected account HALT evidence")
        try:
            qro = graph.qro(_text(record.qro_ref))
        except Exception as exc:  # noqa: BLE001 - source resolution must fail closed.
            return (f"M20 QRO lookup failed:{type(exc).__name__}",)
        if _owner_of(qro) != owner:
            violations.append("M20 QRO owner mismatch")
        declared = _strings(getattr(qro, "input_contract", None)) | _strings(
            getattr(qro, "output_contract", None)
        )
        exact_refs = {
            secret.secret_ref,
            gateway.gateway_ref,
            _text(getattr(halt, "halt_ref", "")),
        }
        if not exact_refs.issubset(declared):
            violations.append("M20 QRO contracts do not bind every selected security source")
        try:
            chain = spine.verified_chain(_text(record.math_spine_ref), owner=owner)
        except Exception as exc:  # noqa: BLE001
            chain = None
            violations.append(f"M20 Mathematical Spine lookup failed:{type(exc).__name__}")
        violations.extend(
            _qro_math_binding_violations(
                qro, chain, record=record, owner=owner, label="M20"
            )
        )
        try:
            document = rag.document_for_owner(
                _text(record.rag_ref), owner_user_id=owner, require_current=True
            )
        except Exception as exc:  # noqa: BLE001
            document = None
            violations.append(f"M20 RAG lookup failed:{type(exc).__name__}")
        if document is not None:
            metadata = getattr(document, "metadata", None)
            if not exact_refs.issubset(_strings(metadata)):
                violations.append("M20 RAG metadata does not bind every selected security source")
        return tuple(violations)

    return (
        {
            "secret_ref": PlatformTypedSourceAdapter(
                source_kind="settings_secret_ref",
                load=load_secret,
                validate_linkage=validate_secret,
            ),
            "llm_gateway_ref": PlatformTypedSourceAdapter(
                source_kind="llm_gateway_terminal_call",
                load=load_gateway,
                validate_linkage=validate_gateway,
            ),
            "kill_switch_ref": PlatformTypedSourceAdapter(
                source_kind="account_halt_evidence",
                load=load_halt,
                validate_linkage=validate_halt,
            ),
        },
        validate_row,
    )


def _m21(
    context: PlatformSourceAdaptersM16M21Context,
) -> tuple[dict[str, PlatformTypedSourceAdapter], PlatformRowLinkValidator]:
    graph = context.research_graph_store
    lifecycle = context.asset_lifecycle_registry
    rag = context.rag_index
    spine = context.spine_chain_registry
    ide_strategy_loader = context.ide_strategy_loader
    allowed_categories = {
        AssetCategory.DEMO.value,
        AssetCategory.TEMPLATE.value,
        AssetCategory.EXAMPLE.value,
        AssetCategory.TUTORIAL.value,
    }

    def load_mock(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M21:
            raise LookupError("mock label adapter only supports M21")
        return lifecycle.governed_asset_by_mock_label_ref(ref, owner_user_id=owner)

    def load_category(ref: str, owner: str, record: PlatformCapabilityRecord) -> Any:
        if _row(record) != M21:
            raise LookupError("asset category adapter only supports M21")
        return lifecycle.governed_asset_by_category_ref(ref, owner_user_id=owner)

    def validate_asset(
        value: GovernedAssetRecord,
        _owner: str,
        record: PlatformCapabilityRecord,
    ) -> tuple[str, ...]:
        violations: list[str] = []
        refs = _specific(record)
        if _text(getattr(value, "category", "")) not in allowed_categories:
            violations.append("M21 governed asset is not demo/template/example/tutorial")
        if _text(getattr(value, "mock_label_ref", "")) != refs.get("mock_label_ref"):
            violations.append("M21 governed asset mock label mismatch")
        if _text(getattr(value, "asset_category_ref", "")) != refs.get(
            "asset_category_ref"
        ):
            violations.append("M21 governed asset category ref mismatch")
        if not _text(getattr(value, "display_label", "")):
            violations.append("M21 governed asset lacks a visible mock/category label")
        return tuple(violations)

    def validate_row(
        record: PlatformCapabilityRecord,
        owner: str,
        values: dict[str, Any],
    ) -> tuple[str, ...]:
        mock_asset = values.get("mock_label_ref")
        category_asset = values.get("asset_category_ref")
        if not isinstance(mock_asset, GovernedAssetRecord) or not isinstance(
            category_asset, GovernedAssetRecord
        ):
            return ("M21 requires exact governed assets for both label refs",)
        violations: list[str] = []
        if mock_asset != category_asset or mock_asset.asset_ref != category_asset.asset_ref:
            violations.append("M21 mock/category refs recombine different governed assets")
            return tuple(violations)
        asset = mock_asset
        try:
            current = lifecycle.governed_asset(asset.asset_ref, owner_user_id=owner)
        except Exception as exc:  # noqa: BLE001
            return (f"M21 current governed asset lookup failed:{type(exc).__name__}",)
        if current != asset:
            violations.append("M21 governed asset is not current")
        if _text(record.lifecycle_ref) != _text(asset.asset_ref):
            violations.append("M21 common lifecycle ref is not the governed example asset")
        try:
            qro = graph.qro(_text(record.qro_ref))
        except Exception as exc:  # noqa: BLE001
            return (*violations, f"M21 QRO lookup failed:{type(exc).__name__}")
        if _owner_of(qro) != owner:
            violations.append("M21 QRO owner mismatch")
        input_contract = getattr(qro, "input_contract", None)
        output_contract = getattr(qro, "output_contract", None)
        legacy_contract = (
            isinstance(input_contract, dict)
            and isinstance(output_contract, dict)
            and set(input_contract) == {"entry_source", "asset_ref"}
            and set(output_contract)
            == {
                "ide_strategy_ref",
                "mock_label_ref",
                "asset_category_ref",
                "status",
            }
            and _text(input_contract.get("entry_source")) == "api"
            and _text(input_contract.get("asset_ref")) == asset.asset_ref
            and "governed_asset_ref" not in input_contract
            and _text(output_contract.get("status"))
            == "template_fork_recorded"
        )
        new_contract = (
            isinstance(input_contract, dict)
            and isinstance(output_contract, dict)
            and set(input_contract) == {"entry_source", "governed_asset_ref"}
            and set(output_contract)
            == {
                "ide_strategy_ref",
                "ide_strategy_snapshot_hash",
                "governed_template_snapshot_hash",
                "mock_label_ref",
                "asset_category_ref",
                "status",
            }
            and _text(input_contract.get("entry_source")) == "api"
            and _text(input_contract.get("governed_asset_ref"))
            == asset.asset_ref
            and "asset_ref" not in input_contract
            and _text(output_contract.get("ide_strategy_ref")).startswith(
                "ide_strategy:"
            )
            and _text(output_contract.get("status"))
            == "template_fork_recorded"
        )
        if legacy_contract == new_contract:
            violations.append(
                "M21 QRO must use exactly one legacy asset_ref or current "
                "governed_asset_ref/ide_strategy_ref contract"
            )
        ide_strategy = None
        ide_strategy_ref = (
            _text(output_contract.get("ide_strategy_ref"))
            if isinstance(output_contract, dict)
            else ""
        )
        if not callable(ide_strategy_loader):
            violations.append("M21 current IDE strategy loader is unavailable")
        else:
            try:
                ide_strategy = ide_strategy_loader(ide_strategy_ref, owner)
            except Exception as exc:  # noqa: BLE001 - typed source fails closed.
                violations.append(
                    f"M21 current IDE strategy lookup failed:{type(exc).__name__}"
                )
        if (
            not isinstance(ide_strategy, StrategyFile)
            or f"ide_strategy:{getattr(ide_strategy, 'strategy_id', '')}"
            != ide_strategy_ref
            or not _text(getattr(ide_strategy, "owner_username", ""))
        ):
            violations.append("M21 current IDE strategy identity mismatch")
        elif new_contract:
            if (
                _text(output_contract.get("ide_strategy_snapshot_hash"))
                != m21_ide_strategy_snapshot_hash(ide_strategy)
                or _text(output_contract.get("governed_template_snapshot_hash"))
                != m21_governed_template_snapshot_hash(asset)
            ):
                violations.append("M21 current IDE/template snapshot hash mismatch")
            if not _text(asset.asset_category_ref).startswith(
                f"asset_category:{_text(ide_strategy.asset_class)}:"
            ):
                violations.append("M21 IDE asset class/category mismatch")
        exact_refs = {
            asset.asset_ref,
            _text(asset.mock_label_ref),
            _text(asset.asset_category_ref),
        }
        declared = _strings(input_contract) | _strings(output_contract)
        if not exact_refs.issubset(declared):
            violations.append("M21 QRO contracts do not bind the governed example labels")
        try:
            document = rag.document_for_owner(
                _text(record.rag_ref), owner_user_id=owner, require_current=True
            )
        except Exception as exc:  # noqa: BLE001
            document = None
            violations.append(f"M21 RAG lookup failed:{type(exc).__name__}")
        if document is not None:
            permission = getattr(document, "permission", None)
            if _text(getattr(document, "asset_ref", "")) != asset.asset_ref:
                violations.append("M21 RAG asset_ref does not bind the governed example")
            if asset.asset_ref not in tuple(
                getattr(permission, "allowed_assets", ()) or ()
            ):
                violations.append("M21 RAG permission does not bind the governed example")
        try:
            chain = spine.verified_chain(_text(record.math_spine_ref), owner=owner)
        except Exception as exc:  # noqa: BLE001
            chain = None
            violations.append(f"M21 Mathematical Spine lookup failed:{type(exc).__name__}")
        violations.extend(
            _qro_math_binding_violations(
                qro, chain, record=record, owner=owner, label="M21"
            )
        )
        return tuple(violations)

    return (
        {
            "mock_label_ref": PlatformTypedSourceAdapter(
                source_kind="governed_asset_mock_label",
                load=load_mock,
                validate_linkage=validate_asset,
            ),
            "asset_category_ref": PlatformTypedSourceAdapter(
                source_kind="governed_asset_category",
                load=load_category,
                validate_linkage=validate_asset,
            ),
        },
        validate_row,
    )


def build_platform_source_adapters_m16_m21(
    context: PlatformSourceAdaptersM16M21Context,
) -> tuple[
    dict[str, PlatformTypedSourceAdapter],
    dict[str, PlatformRowLinkValidator],
]:
    unavailable = unavailable_platform_source_rows_m16_m21(context)
    adapters: dict[str, PlatformTypedSourceAdapter] = {}
    validators: dict[str, PlatformRowLinkValidator] = {}
    for row, builder in (
        (M16, _m16),
        (M17, _m17),
        (M18, _m18),
        (M19, _m19),
        (M20, _m20),
        (M21, _m21),
    ):
        if row in unavailable:
            continue
        row_adapters, validator = builder(context)
        overlap = set(adapters).intersection(row_adapters)
        if overlap:
            raise ValueError(f"duplicate M16-M21 platform adapters: {sorted(overlap)}")
        adapters.update(row_adapters)
        validators[row] = validator
    return adapters, validators


__all__ = [
    "PlatformSourceAdaptersM16M21Context",
    "ResolvedLLMGatewaySource",
    "ResolvedIDEConsistencySource",
    "ResolvedSecretSource",
    "build_platform_source_adapters_m16_m21",
    "unavailable_platform_source_rows_m16_m21",
]
