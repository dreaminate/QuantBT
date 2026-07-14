"""Server-owned source-lineage policies for GOAL section 14 M1-M8.

The public finalizer accepts only ``owner_user_id``, ``m_row`` and one
business ``anchor_ref``.  This module turns that anchor into the exact current
typed lineage produced by the existing application endpoints.  It never
accepts proof refs from a caller and rejects ambiguous same-owner candidates.

Canonical anchors:

* M1-M2: current ``HypothesisCard`` owner envelope
* M3: current ``DatasetSemantics`` record
* M4-M5: current ``Factor`` owner envelope
* M6: current ``ModelPassport``
* M7-M8: current ``PortfolioPolicy``
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Callable, Iterable

from ..lineage.ids import content_hash
from .platform_coverage import PlatformCapabilityRecord, PlatformSpecificRef
from .platform_source_lineage_core import PlatformSourceLineagePolicyResolution
from .platform_typed_sources import (
    platform_compiler_snapshot,
    platform_compiler_snapshot_required_methods,
)
from .qro_spine_binding import (
    QROSpineBindingError,
    platform_spine_binding_historical_command_ref,
)
from .ref_resolution import is_placeholder_ref
from .research_design_assets import source_object_hash
from .spine import EntrySource


M1_M2 = "M1-M2"
M3 = "M3"
M4_M5 = "M4-M5"
M6 = "M6"
M7_M8 = "M7-M8"

SUPPORTED_ROWS = (M1_M2, M3, M4_M5, M6, M7_M8)

M1_M2_SPINE_BINDING_ENTRYPOINT_REF = (
    "api:research_os.platform.spine_bindings.m1_m2"
)
M3_SPINE_BINDING_ENTRYPOINT_REF = "api:research_os.platform.spine_bindings.m3"
M4_M5_SPINE_BINDING_ENTRYPOINT_REF = (
    "api:research_os.platform.spine_bindings.m4_m5"
)
M6_SPINE_BINDING_ENTRYPOINT_REF = "api:research_os.platform.spine_bindings.m6"
M7_M8_SPINE_BINDING_ENTRYPOINT_REF = (
    "api:research_os.platform.spine_bindings.m7_m8"
)

_SPINE_BINDING_ENTRYPOINT_BY_ROW = {
    M1_M2: M1_M2_SPINE_BINDING_ENTRYPOINT_REF,
    M3: M3_SPINE_BINDING_ENTRYPOINT_REF,
    M4_M5: M4_M5_SPINE_BINDING_ENTRYPOINT_REF,
    M6: M6_SPINE_BINDING_ENTRYPOINT_REF,
    M7_M8: M7_M8_SPINE_BINDING_ENTRYPOINT_REF,
}

_BUSINESS_ENTRYPOINT_BY_ROW = {
    M1_M2: (EntrySource.API.value, "api:hypothesis_cards"),
    M3: (EntrySource.API.value, "api:research_os.market_data.datasets"),
    M4_M5: (EntrySource.API.value, "api:factors"),
    M6: (EntrySource.API.value, "api:training.jobs"),
    M7_M8: (EntrySource.API.value, "api:portfolios.promote"),
}


class PlatformSourceLineagePolicyM1M8Error(ValueError):
    """An anchor does not resolve to one exact current M1-M8 lineage."""


def _text(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: _plain(child) for key, child in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_plain(child) for child in value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain(value.to_dict())
    if hasattr(value, "__dict__"):
        return _plain(vars(value))
    return value


def _exact(value: Any, *, field: str, prefix: str | tuple[str, ...] = ()) -> str:
    raw = str(getattr(value, "value", value) or "")
    token = raw.strip()
    if (
        not token
        or token != raw
        or any(ord(char) < 32 for char in token)
        or is_placeholder_ref(token)
    ):
        raise PlatformSourceLineagePolicyM1M8Error(
            f"{field} is not an exact stable ref"
        )
    prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
    if prefixes and not token.startswith(prefixes):
        raise PlatformSourceLineagePolicyM1M8Error(
            f"{field} does not use its canonical prefix"
        )
    return token


def _owner(value: Any) -> str:
    return _text(getattr(value, "owner_user_id", getattr(value, "owner", "")))


def _one(values: Iterable[Any], *, label: str) -> Any:
    matches = tuple(values)
    if len(matches) != 1:
        raise PlatformSourceLineagePolicyM1M8Error(
            f"{label} must resolve to exactly one current record"
        )
    return matches[0]


def _mapping(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlatformSourceLineagePolicyM1M8Error(f"{field} is malformed")
    return value


def _require_equal(actual: Any, expected: Any, *, field: str) -> None:
    if _text(actual) != _text(expected):
        raise PlatformSourceLineagePolicyM1M8Error(f"{field} mismatch")


def _specific_map(record: PlatformCapabilityRecord) -> dict[str, str]:
    return {_text(item.key): _text(item.ref) for item in record.specific_refs}


def _model_version_parts(model_version_ref: str) -> tuple[str, int]:
    prefix = "model_version:"
    if not model_version_ref.startswith(prefix) or ":v" not in model_version_ref:
        raise PlatformSourceLineagePolicyM1M8Error(
            "ModelPassport model_version_ref is not canonical"
        )
    model_id, version_text = model_version_ref[len(prefix) :].rsplit(":v", 1)
    if not model_id or not version_text.isdigit() or int(version_text) < 1:
        raise PlatformSourceLineagePolicyM1M8Error(
            "ModelPassport model_version_ref is not canonical"
        )
    return model_id, int(version_text)


@dataclass(frozen=True)
class PlatformSourceLineagePoliciesM1M8Context:
    """Typed stores required to derive all five canonical M1-M8 rows."""

    research_graph_store: Any
    compiler_store: Any
    spine_chain_registry: Any
    asset_lifecycle_registry: Any
    research_design_registry: Any
    strategy_goal_store: Any
    hypothesis_store: Any
    factor_registry: Any
    onboarding_registry: Any
    market_data_registry: Any
    dataset_registry: Any
    model_governance_registry: Any
    training_service: Any
    model_registry: Any
    signal_contract_registry: Any
    signal_validation_registry: Any


@dataclass(frozen=True)
class _CompilerLineage:
    qro: Any
    command: Any
    compiler_ir: Any
    compiler_pass: Any
    entry_source: str
    entrypoint_ref: str

    @property
    def qro_ref(self) -> str:
        return _text(getattr(self.qro, "qro_id", ""))

    @property
    def command_ref(self) -> str:
        return _text(getattr(self.command, "command_id", ""))

    @property
    def ir_ref(self) -> str:
        return _text(getattr(self.compiler_ir, "ir_ref", ""))

    @property
    def pass_ref(self) -> str:
        return _text(getattr(self.compiler_pass, "pass_ref", ""))


class PlatformSourceLineagePolicyResolverM1M8:
    """Resolve current M1-M8 business anchors without caller-supplied proofs."""

    registered_rows = SUPPORTED_ROWS

    def __init__(self, context: PlatformSourceLineagePoliciesM1M8Context) -> None:
        self._context = context
        requirements = (
            (
                context.research_graph_store,
                ("qro", "commands", "projection_index"),
                "research_graph_store",
            ),
            (
                context.compiler_store,
                platform_compiler_snapshot_required_methods(
                    context.compiler_store
                ),
                "compiler_store",
            ),
            (context.spine_chain_registry, ("verified_chain",), "spine_chain_registry"),
            (
                context.asset_lifecycle_registry,
                ("governed_asset", "ingestion_skill_updates"),
                "asset_lifecycle_registry",
            ),
            (
                context.research_design_registry,
                (
                    "hypothesis_envelope",
                    "universe_definition",
                    "regime_scenario",
                    "factor_envelope",
                    "label_definition",
                    "portfolio_policy",
                    "strategy_book",
                    "signal_contract_envelope",
                ),
                "research_design_registry",
            ),
            (context.strategy_goal_store, ("get",), "strategy_goal_store"),
            (context.hypothesis_store, ("get",), "hypothesis_store"),
            (context.factor_registry, ("get",), "factor_registry"),
            (
                context.onboarding_registry,
                (
                    "ingestion_skill",
                    "data_source",
                    "data_connector_pit_bitemporal_rule",
                ),
                "onboarding_registry",
            ),
            (
                context.market_data_registry,
                ("dataset", "instruments"),
                "market_data_registry",
            ),
            (context.dataset_registry, ("resolve_version_ref",), "dataset_registry"),
            (
                context.model_governance_registry,
                ("passport",),
                "model_governance_registry",
            ),
            (
                context.training_service,
                ("get_job",),
                "training_service",
            ),
            (
                context.model_registry,
                ("list_versions",),
                "model_registry",
            ),
            (
                context.signal_contract_registry,
                ("get",),
                "signal_contract_registry",
            ),
            (
                context.signal_validation_registry,
                ("validation",),
                "signal_validation_registry",
            ),
        )
        for value, methods, label in requirements:
            missing = [name for name in methods if not callable(getattr(value, name, None))]
            if missing:
                raise TypeError(f"{label} is missing required methods: {missing}")

    @staticmethod
    def _exact_ref_tuple(values: Any, *, field: str) -> tuple[str, ...]:
        if not isinstance(values, (tuple, list)):
            raise PlatformSourceLineagePolicyM1M8Error(f"{field} is malformed")
        refs = tuple(
            _exact(value, field=f"{field}[{index}]")
            for index, value in enumerate(values)
        )
        if len(set(refs)) != len(refs):
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{field} contains duplicate refs"
            )
        return refs

    def _qro(self, ref: str, owner: str) -> Any:
        try:
            qro = self._context.research_graph_store.qro(ref)
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"current QRO lookup failed:{type(exc).__name__}"
            ) from exc
        if _text(getattr(qro, "qro_id", "")) != ref or _owner(qro) != owner:
            raise PlatformSourceLineagePolicyM1M8Error(
                "current QRO identity/owner mismatch"
            )
        return qro

    def _select_current_projected_qro(
        self,
        owner: str,
        predicate: Callable[[Any], bool],
        *,
        label: str,
    ) -> tuple[Any, Any, Any]:
        matches: dict[str, tuple[Any, Any, Any]] = {}
        for projection in tuple(
            self._context.research_graph_store.projection_index(owner=owner) or ()
        ):
            if _owner(projection) != owner:
                continue
            qro_ref = _exact(
                getattr(projection, "qro_id", ""),
                field=f"{label} projection qro_id",
            )
            qro = self._qro(qro_ref, owner)
            if not predicate(qro):
                continue
            command_ref = _exact(
                getattr(projection, "command_id", ""),
                field=f"{label} projection command_id",
            )
            commands = tuple(
                item
                for item in tuple(self._context.research_graph_store.commands() or ())
                if _text(getattr(item, "command_id", "")) == command_ref
            )
            if len(commands) != 1:
                raise PlatformSourceLineagePolicyM1M8Error(
                    f"{label} current projection must bind exactly one Graph command"
                )
            command = commands[0]
            payload = getattr(command, "payload", None)
            embedded = payload.get("qro") if isinstance(payload, dict) else None
            if _text(getattr(command, "actor", "")) != owner or embedded != qro:
                raise PlatformSourceLineagePolicyM1M8Error(
                    f"{label} current projection carries stale QRO/Graph lineage"
                )
            if qro_ref in matches:
                raise PlatformSourceLineagePolicyM1M8Error(
                    f"{label} QRO has ambiguous current projections"
                )
            matches[qro_ref] = (qro, command, projection)
        if len(matches) != 1:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{label} anchor must select exactly one current projected QRO"
            )
        return next(iter(matches.values()))

    @staticmethod
    def _qro_identity_without_math(qro: Any, *, label: str) -> dict[str, Any]:
        payload = _plain(qro)
        if not isinstance(payload, dict) or "mathematical_refs" not in payload:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{label} QRO identity is unavailable"
            )
        payload.pop("mathematical_refs")
        return payload

    @staticmethod
    def _entrypoint_from_refs(*groups: Any) -> str:
        entrypoints: list[str] = []
        for group in groups:
            refs = PlatformSourceLineagePolicyResolverM1M8._exact_ref_tuple(
                group,
                field="compiler canonical_command_refs",
            )
            candidates = tuple(
                ref.removeprefix("entrypoint:")
                for ref in refs
                if ref.startswith("entrypoint:")
            )
            if len(candidates) != 1:
                raise PlatformSourceLineagePolicyM1M8Error(
                    "compiler lineage must bind exactly one canonical entrypoint"
                )
            entrypoints.append(candidates[0])
        if not entrypoints or len(set(entrypoints)) != 1:
            raise PlatformSourceLineagePolicyM1M8Error(
                "compiler lineage must bind exactly one canonical entrypoint"
            )
        return entrypoints[0]

    def _compiler_lineage(
        self,
        *,
        owner: str,
        qro: Any,
        command: Any,
    ) -> _CompilerLineage:
        qro_ref = _exact(getattr(qro, "qro_id", ""), field="compiler qro_ref")
        command_ref = _exact(
            getattr(command, "command_id", ""),
            field="compiler graph_command_ref",
        )
        compiler = platform_compiler_snapshot(
            self._context.compiler_store,
            owner=owner,
        )
        irs = tuple(
            item
            for item in compiler.irs
            if tuple(getattr(item, "source_qro_refs", ()) or ()) == (qro_ref,)
            and tuple(getattr(item, "graph_command_refs", ()) or ()) == (command_ref,)
            and _text(getattr(item, "owner", "")) == owner
        )
        pairs: list[tuple[Any, Any]] = []
        for compiler_ir in irs:
            for compiler_pass in compiler.passes:
                if (
                    _text(getattr(compiler_pass, "output_ir_ref", ""))
                    == _text(getattr(compiler_ir, "ir_ref", ""))
                    and tuple(getattr(compiler_pass, "input_qro_refs", ()) or ())
                    == (qro_ref,)
                    and tuple(getattr(compiler_pass, "graph_command_refs", ()) or ())
                    == (command_ref,)
                    and _text(getattr(compiler_pass, "actor", "")) == owner
                    and _text(getattr(compiler_pass, "status", "compiled")).lower()
                    == "compiled"
                ):
                    pairs.append((compiler_ir, compiler_pass))
        if len(pairs) != 1:
            raise PlatformSourceLineagePolicyM1M8Error(
                "QRO/Graph must select exactly one owner compiler IR/pass pair"
            )
        compiler_ir, compiler_pass = pairs[0]
        _exact(
            getattr(compiler_ir, "ir_ref", ""),
            field="compiler_ir_ref",
            prefix="compiler_ir:",
        )
        _exact(
            getattr(compiler_pass, "pass_ref", ""),
            field="compiler_pass_ref",
            prefix="compiler_pass:",
        )
        entrypoint = self._entrypoint_from_refs(
            getattr(compiler_ir, "canonical_command_refs", ()),
            getattr(compiler_pass, "canonical_command_refs", ()),
        )
        source = _text(getattr(compiler_pass, "entry_source", ""))
        if source not in {item.value for item in EntrySource}:
            raise PlatformSourceLineagePolicyM1M8Error(
                "compiler pass has an unknown entry source"
            )
        return _CompilerLineage(
            qro=qro,
            command=command,
            compiler_ir=compiler_ir,
            compiler_pass=compiler_pass,
            entry_source=source,
            entrypoint_ref=entrypoint,
        )

    def _spine_binding_lineage(
        self,
        *,
        owner: str,
        row: str,
        predicate: Callable[[Any], bool],
    ) -> tuple[_CompilerLineage, Any, _CompilerLineage]:
        binding_entrypoint = _SPINE_BINDING_ENTRYPOINT_BY_ROW[row]
        business_source, business_entrypoint = _BUSINESS_ENTRYPOINT_BY_ROW[row]
        qro, binding_command, projection = self._select_current_projected_qro(
            owner,
            predicate,
            label=row,
        )
        declared = self._exact_ref_tuple(
            getattr(qro, "mathematical_refs", ()),
            field=f"{row} binding QRO mathematical_refs",
        )
        if len(declared) != 1:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{row} current binding QRO must declare exactly one Mathematical Spine chain"
            )
        projection_refs = self._exact_ref_tuple(
            getattr(projection, "mathematical_refs", ()),
            field=f"{row} binding projection mathematical_refs",
        )
        if (
            projection_refs != declared
            or _text(getattr(projection, "actor", "")) != owner
            or _text(getattr(projection, "source", "")) != EntrySource.API.value
            or _text(getattr(binding_command, "source", ""))
            != EntrySource.API.value
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{row} current owner projection is not the authenticated API binding head"
            )
        try:
            linked_business_command_ref = (
                platform_spine_binding_historical_command_ref(
                    binding_command,
                    owner_user_id=owner,
                    qro_ref=_text(getattr(qro, "qro_id", "")),
                    chain_ref=declared[0],
                    entrypoint_ref=binding_entrypoint,
                )
            )
        except QROSpineBindingError as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{row} current binding command provenance mismatch:{exc}"
            ) from exc
        binding_lineage = self._compiler_lineage(
            owner=owner,
            qro=qro,
            command=binding_command,
        )
        if (
            binding_lineage.entry_source != EntrySource.API.value
            or binding_lineage.entrypoint_ref != binding_entrypoint
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{row} current binding compiler entrypoint mismatch"
            )

        bound_identity = self._qro_identity_without_math(qro, label=row)
        business_lineages: list[_CompilerLineage] = []
        for command in tuple(self._context.research_graph_store.commands() or ()):
            payload = getattr(command, "payload", None)
            historical_qro = payload.get("qro") if isinstance(payload, dict) else None
            if _text(getattr(historical_qro, "qro_id", "")) != binding_lineage.qro_ref:
                continue
            if self._qro_identity_without_math(historical_qro, label=row) != bound_identity:
                raise PlatformSourceLineagePolicyM1M8Error(
                    f"{row} QRO history changes fields other than mathematical_refs"
                )
            historical_refs = self._exact_ref_tuple(
                getattr(historical_qro, "mathematical_refs", ()),
                field=f"{row} historical QRO mathematical_refs",
            )
            if _text(getattr(command, "command_id", "")) == binding_lineage.command_ref:
                if historical_qro != qro or historical_refs != declared:
                    raise PlatformSourceLineagePolicyM1M8Error(
                        f"{row} current binding command carries recombined QRO state"
                    )
                continue
            historical_lineage = self._compiler_lineage(
                owner=owner,
                qro=historical_qro,
                command=command,
            )
            if not historical_refs:
                if (
                    historical_lineage.entry_source != business_source
                    or historical_lineage.entrypoint_ref != business_entrypoint
                    or _text(getattr(command, "source", "")) != business_source
                    or _text(getattr(command, "actor", "")) != owner
                    or tuple(
                        getattr(
                            historical_lineage.compiler_ir,
                            "mathematical_spine_chain_refs",
                            (),
                        )
                        or ()
                    )
                ):
                    raise PlatformSourceLineagePolicyM1M8Error(
                        f"{row} historical business compiler lineage mismatch"
                    )
                business_lineages.append(historical_lineage)
                continue
            if (
                historical_qro != qro
                or historical_refs != declared
                or _text(getattr(command, "actor", "")) != owner
                or _text(getattr(command, "source", "")) != EntrySource.API.value
                or historical_lineage.entry_source != EntrySource.API.value
                or historical_lineage.entrypoint_ref != binding_entrypoint
                or tuple(
                    getattr(
                        historical_lineage.compiler_ir,
                        "mathematical_spine_chain_refs",
                        (),
                    )
                    or ()
                )
                != declared
            ):
                raise PlatformSourceLineagePolicyM1M8Error(
                    f"{row} unrecognized or recombined binding history"
                )
        if len(business_lineages) != 1:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{row} historical business command is missing or ambiguous; expected exactly one"
            )
        if business_lineages[0].command_ref != linked_business_command_ref:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{row} binding command does not name the selected historical business command"
            )
        return binding_lineage, projection, business_lineages[0]

    @staticmethod
    def _spine_binding_metadata(
        *,
        projection: Any,
        business_lineage: _CompilerLineage,
    ) -> tuple[tuple[str, Any], ...]:
        return (
            (
                "binding_projection_ref",
                _exact(
                    getattr(projection, "projection_ref", ""),
                    field="binding_projection_ref",
                ),
            ),
            ("business_graph_command_ref", business_lineage.command_ref),
            ("business_compiler_ir_ref", business_lineage.ir_ref),
            ("business_compiler_pass_ref", business_lineage.pass_ref),
            ("business_entry_source", business_lineage.entry_source),
            ("business_entrypoint_ref", business_lineage.entrypoint_ref),
        )

    def _math_chain(
        self,
        *,
        owner: str,
        lineage: _CompilerLineage,
        predicate: Callable[[Any], bool],
        label: str,
    ) -> Any:
        declared = self._exact_ref_tuple(
            getattr(lineage.qro, "mathematical_refs", ()),
            field=f"{label} QRO mathematical_refs",
        )
        if len(declared) != 1:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{label} QRO must bind exactly one Mathematical Spine chain"
            )
        chain_ref = _exact(
            declared[0],
            field=f"{label} Mathematical Spine chain_ref",
            prefix=("math_spine_chain:", "math_spine_chain_"),
        )
        compiler_math = self._exact_ref_tuple(
            getattr(lineage.compiler_ir, "mathematical_spine_chain_refs", ()),
            field=f"{label} compiler IR mathematical_spine_chain_refs",
        )
        if compiler_math != (chain_ref,):
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{label} QRO/compiler IR Mathematical Spine binding mismatch"
            )
        try:
            chain = self._context.spine_chain_registry.verified_chain(
                chain_ref,
                owner=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{label} declared Mathematical Spine lookup failed:{type(exc).__name__}"
            ) from exc
        if (
            _text(getattr(chain, "chain_ref", "")) != chain_ref
            or _text(getattr(chain, "recorded_by", "")) != owner
            or _text(getattr(lineage.compiler_pass, "output_ir_ref", ""))
            != lineage.ir_ref
            or tuple(getattr(lineage.compiler_pass, "input_qro_refs", ()) or ())
            != (lineage.qro_ref,)
            or tuple(getattr(lineage.compiler_pass, "graph_command_refs", ()) or ())
            != (lineage.command_ref,)
            or not predicate(chain)
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{label} QRO/IR/pass/Mathematical Spine lineage is stale or recombined"
            )
        return chain

    @staticmethod
    def _require_historical_linkage(
        *,
        lineage: _CompilerLineage,
        qro_ref: Any,
        command_ref: Any,
        label: str,
    ) -> None:
        if (
            lineage.qro_ref != _exact(qro_ref, field=f"{label} historical qro_ref")
            or lineage.command_ref
            != _exact(command_ref, field=f"{label} historical graph_command_ref")
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                f"{label} immutable business linkage mismatch"
            )

    def _m1_m2(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(anchor, field="M1-M2 anchor_ref", prefix="hypothesis_card:")
        try:
            envelope = self._context.research_design_registry.hypothesis_envelope(
                anchor,
                owner_user_id=owner,
            )
            card = self._context.hypothesis_store.get(_text(envelope.card_id))
            universe = self._context.research_design_registry.universe_definition(
                _text(envelope.universe_definition_ref),
                owner_user_id=owner,
            )
            regime = self._context.research_design_registry.regime_scenario(
                _text(envelope.regime_scenario_ref),
                owner_user_id=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"M1-M2 typed anchor lookup failed:{type(exc).__name__}"
            ) from exc
        if (
            _owner(envelope) != owner
            or _text(envelope.hypothesis_card_ref) != anchor
            or source_object_hash(card) != _text(envelope.source_content_hash)
            or _owner(universe) != owner
            or _owner(regime) != owner
            or _text(regime.universe_definition_ref)
            != _text(universe.universe_definition_ref)
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                "M1-M2 current owner design bundle is stale or recombined"
            )
        goal_ref = _exact(
            envelope.strategy_goal_ref,
            field="strategy_goal_ref",
            prefix=("strategy_goal:", "goal:"),
        )
        goal_id = goal_ref.split(":", 1)[1]
        try:
            goal = self._context.strategy_goal_store.get(goal_id)
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"M1-M2 StrategyGoal lookup failed:{type(exc).__name__}"
            ) from exc
        linkage = envelope.linkage
        binding, projection, business = self._spine_binding_lineage(
            owner=owner,
            row=M1_M2,
            predicate=lambda item: _text(getattr(item, "qro_type", ""))
            == "QuantIntent"
            and _text(getattr(item, "qro_id", "")) == _text(linkage.qro_ref),
        )
        self._require_historical_linkage(
            lineage=business,
            qro_ref=linkage.qro_ref,
            command_ref=linkage.research_graph_ref,
            label="M1-M2",
        )
        qro = binding.qro
        output = _mapping(qro.output_contract, field="M1-M2 QRO output_contract")
        expected = {
            "strategy_goal_ref": goal_ref,
            "strategy_goal_hash": source_object_hash(goal),
            "hypothesis_card_ref": anchor,
            "universe_definition_ref": _text(universe.universe_definition_ref),
            "regime_scenario_ref": _text(regime.regime_scenario_ref),
        }
        for key, value in expected.items():
            _require_equal(output.get(key), value, field=f"M1-M2 QRO output {key}")
        if _text(getattr(card, "strategy_goal_ref", "")) != goal_ref:
            raise PlatformSourceLineagePolicyM1M8Error(
                "M1-M2 HypothesisCard/StrategyGoal linkage mismatch"
            )
        lifecycle_ref = _exact(linkage.lifecycle_ref, field="M1-M2 lifecycle_ref")
        lifecycle = self._context.asset_lifecycle_registry.governed_asset(
            lifecycle_ref,
            owner_user_id=owner,
        )
        if (
            _text(getattr(lifecycle, "asset_type", "")) != "HypothesisCard"
            or _text(getattr(lifecycle, "asset_ref", "")) != anchor
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                "M1-M2 lifecycle does not bind the HypothesisCard"
            )
        specifics = (
            goal_ref,
            anchor,
            _text(universe.universe_definition_ref),
            _text(regime.regime_scenario_ref),
        )
        required = set(specifics)
        chain = self._math_chain(
            owner=owner,
            lineage=binding,
            predicate=lambda item: required.issubset(
                {
                    _text(ref)
                    for ref in (
                        *tuple(getattr(item, "validation_refs", ()) or ()),
                        *tuple(getattr(item, "evidence_refs", ()) or ()),
                    )
                }
            ),
            label="M1-M2 Mathematical Spine chain",
        )
        return PlatformSourceLineagePolicyResolution(
            m_row=M1_M2,
            anchor_ref=anchor,
            qro_ref=binding.qro_ref,
            business_entry_source="api",
            business_entrypoint_ref=_SPINE_BINDING_ENTRYPOINT_BY_ROW[M1_M2],
            lifecycle_ref=lifecycle_ref,
            math_spine_ref=_text(chain.chain_ref),
            specific_refs=tuple(
                PlatformSpecificRef(key, value)
                for key, value in zip(
                    (
                        "strategy_goal_ref",
                        "hypothesis_card_ref",
                        "universe_definition_ref",
                        "regime_scenario_ref",
                    ),
                    specifics,
                    strict=True,
                )
            ),
            primary_rag_asset_ref=anchor,
            row_policy_metadata=(
                ("graph_command_ref", binding.command_ref),
                ("compiler_ir_ref", binding.ir_ref),
                ("compiler_pass_ref", binding.pass_ref),
                *self._spine_binding_metadata(
                    projection=projection,
                    business_lineage=business,
                ),
                ("hypothesis_source_hash", _text(envelope.source_content_hash)),
                ("strategy_goal_source_hash", source_object_hash(goal)),
            ),
        )

    def _m3(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(anchor, field="M3 anchor_ref", prefix="dataset:")
        try:
            dataset = self._context.market_data_registry.dataset(
                anchor,
                owner_user_id=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"M3 DatasetSemantics lookup failed:{type(exc).__name__}"
            ) from exc
        if _text(getattr(dataset, "dataset_ref", "")) != anchor:
            raise PlatformSourceLineagePolicyM1M8Error(
                "M3 DatasetSemantics identity mismatch"
            )
        if _text(getattr(dataset, "quality_status", "")) not in {"accepted", "passed"}:
            raise PlatformSourceLineagePolicyM1M8Error(
                "M3 DatasetSemantics quality status is not accepted"
            )
        if _text(getattr(dataset, "freshness_status", "")) not in {"current", "fresh"}:
            raise PlatformSourceLineagePolicyM1M8Error(
                "M3 DatasetSemantics is not fresh/current"
            )
        lineage_refs = {_text(value) for value in tuple(dataset.lineage_refs or ())}
        update = _one(
            (
                item
                for item in self._context.asset_lifecycle_registry.ingestion_skill_updates(
                    owner_user_id=owner
                )
                if _text(getattr(item, "update_ref", "")) in lineage_refs
                and _text(getattr(item, "source_ref", ""))
                == _text(getattr(dataset, "source_ref", ""))
                and _text(getattr(item, "known_at_ref", ""))
                == _text(getattr(dataset, "known_at_ref", ""))
                and _text(getattr(item, "effective_at_ref", ""))
                == _text(getattr(dataset, "effective_at_ref", ""))
                and _text(getattr(item, "checksum", ""))
                == _text(getattr(dataset, "checksum", ""))
            ),
            label="M3 IngestionSkillUpdate",
        )
        try:
            skill = self._context.onboarding_registry.ingestion_skill(
                _text(update.skill_ref),
                owner_user_id=owner,
            )
            source = self._context.onboarding_registry.data_source(
                _text(skill.source_ref),
                owner_user_id=owner,
            )
            pit_rule = (
                self._context.onboarding_registry.data_connector_pit_bitemporal_rule(
                    _text(skill.pit_bitemporal_rules_ref),
                    owner_user_id=owner,
                )
            )
            version = self._context.dataset_registry.resolve_version_ref(
                _text(update.dataset_version_ref)
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"M3 ingestion lineage lookup failed:{type(exc).__name__}"
            ) from exc
        if (
            _owner(skill) != owner
            or _text(skill.lifecycle_state) != "active"
            or _text(skill.source_ref) != _text(source.source_ref)
            or _text(update.skill_ref) != _text(skill.skill_id)
            or _text(update.skill_version) != _text(skill.version)
            or _text(update.source_ref) != _text(skill.source_ref)
            or _text(dataset.source_ref) != _text(skill.source_ref)
            or _text(dataset.pit_bitemporal_rules_ref)
            != _text(skill.pit_bitemporal_rules_ref)
            or _text(getattr(pit_rule, "skill_id", "")) != _text(skill.skill_id)
            or _text(getattr(pit_rule, "source_ref", "")) != _text(skill.source_ref)
            or _text(getattr(version, "dataset_id", ""))
            != _text(skill.output_dataset_id)
            or _text(getattr(version, "version_id", "")) != _text(dataset.version)
            or _text(getattr(version, "sha256", "")) != _text(dataset.checksum)
            or getattr(version, "row_count", None) != getattr(update, "row_count", None)
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                "M3 Dataset/IngestionSkill/Version lineage is stale or recombined"
            )
        instrument = _one(
            (
                item
                for item in self._context.market_data_registry.instruments(
                    owner_user_id=owner
                )
                if _text(getattr(item, "symbol_mapping_ref", ""))
                == _text(skill.schema_mapping_ref)
            ),
            label="M3 InstrumentSpec",
        )
        dataset_record_hash = content_hash(dataset.to_dict())

        def matches_dataset_qro(candidate: Any) -> bool:
            output_contract = getattr(candidate, "output_contract", None)
            input_contract = getattr(candidate, "input_contract", None)
            return (
                _text(getattr(candidate, "qro_type", "")) == "Dataset"
                and isinstance(output_contract, dict)
                and isinstance(input_contract, dict)
                and _text(output_contract.get("dataset_ref")) == anchor
                and _text(input_contract.get("record_hash")) == dataset_record_hash
            )

        binding, projection, business = self._spine_binding_lineage(
            owner=owner,
            row=M3,
            predicate=matches_dataset_qro,
        )
        qro = binding.qro
        output = _mapping(qro.output_contract, field="M3 QRO output_contract")
        for key, expected in (
            ("status", "dataset_semantics_recorded"),
            ("dataset_ref", anchor),
            ("known_at_ref", dataset.known_at_ref),
            ("effective_at_ref", dataset.effective_at_ref),
            ("pit_bitemporal_rules_ref", dataset.pit_bitemporal_rules_ref),
            ("quality_status", dataset.quality_status),
            ("freshness_status", dataset.freshness_status),
        ):
            _require_equal(output.get(key), expected, field=f"M3 QRO output {key}")
        if _text(qro.implementation_hash) != "market_data_dataset:" + content_hash(
            dataset.to_dict()
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                "M3 Dataset QRO implementation hash mismatch"
            )
        chain = self._math_chain(
            owner=owner,
            lineage=binding,
            predicate=lambda item: _text(getattr(item, "data_semantics_ref", ""))
            == anchor,
            label="M3 Mathematical Spine chain",
        )
        return PlatformSourceLineagePolicyResolution(
            m_row=M3,
            anchor_ref=anchor,
            qro_ref=binding.qro_ref,
            business_entry_source="api",
            business_entrypoint_ref=_SPINE_BINDING_ENTRYPOINT_BY_ROW[M3],
            lifecycle_ref=_text(update.update_ref),
            math_spine_ref=_text(chain.chain_ref),
            specific_refs=(
                PlatformSpecificRef("ingestion_skill_ref", _text(skill.skill_id)),
                PlatformSpecificRef(
                    "instrument_spec_ref",
                    _text(instrument.instrument_ref),
                ),
            ),
            primary_rag_asset_ref=anchor,
            row_policy_metadata=(
                ("graph_command_ref", binding.command_ref),
                ("compiler_ir_ref", binding.ir_ref),
                ("compiler_pass_ref", binding.pass_ref),
                *self._spine_binding_metadata(
                    projection=projection,
                    business_lineage=business,
                ),
                ("dataset_version_ref", _text(update.dataset_version_ref)),
                ("dataset_checksum", _text(dataset.checksum)),
            ),
        )

    def _m4_m5(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(anchor, field="M4-M5 anchor_ref", prefix="factor:")
        try:
            envelope = self._context.research_design_registry.factor_envelope(
                anchor,
                owner_user_id=owner,
            )
            factor = self._context.factor_registry.get(
                _text(envelope.factor_id),
                int(envelope.version),
            )
            label = self._context.research_design_registry.label_definition(
                _text(envelope.label_ref),
                owner_user_id=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"M4-M5 typed anchor lookup failed:{type(exc).__name__}"
            ) from exc
        if (
            _owner(envelope) != owner
            or _text(envelope.factor_ref) != anchor
            or source_object_hash(factor) != _text(envelope.source_content_hash)
            or _owner(label) != owner
            or _text(envelope.label_ref) != _text(label.label_ref)
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                "M4-M5 Factor/Label lineage is stale or recombined"
            )
        linkage = envelope.linkage
        binding, projection, business = self._spine_binding_lineage(
            owner=owner,
            row=M4_M5,
            predicate=lambda item: _text(getattr(item, "qro_type", "")) == "Factor"
            and _text(getattr(item, "qro_id", "")) == _text(linkage.qro_ref),
        )
        self._require_historical_linkage(
            lineage=business,
            qro_ref=linkage.qro_ref,
            command_ref=linkage.research_graph_ref,
            label="M4-M5",
        )
        qro = binding.qro
        output = _mapping(qro.output_contract, field="M4-M5 QRO output_contract")
        _require_equal(output.get("factor_ref"), anchor, field="M4-M5 QRO factor_ref")
        _require_equal(
            output.get("label_ref"),
            label.label_ref,
            field="M4-M5 QRO label_ref",
        )
        formula_hash = content_hash({"formula": getattr(factor, "formula", "")})
        input_contract = _mapping(qro.input_contract, field="M4-M5 QRO input_contract")
        _require_equal(
            input_contract.get("formula_hash"),
            formula_hash,
            field="M4-M5 QRO formula_hash",
        )
        lifecycle_ref = _text(linkage.lifecycle_ref)
        lifecycle = self._context.asset_lifecycle_registry.governed_asset(
            lifecycle_ref,
            owner_user_id=owner,
        )
        if (
            _text(lifecycle.asset_ref) != anchor
            or _text(lifecycle.asset_type) != "Factor"
            or anchor not in tuple(getattr(lifecycle, "evidence_refs", ()) or ())
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                "M4-M5 lifecycle does not bind the Factor"
            )
        label_ref = _text(label.label_ref)
        chain = self._math_chain(
            owner=owner,
            lineage=binding,
            predicate=lambda item: _text(getattr(item, "factor_ref", "")) == anchor
            and label_ref
            in {
                _text(ref)
                for ref in (
                    *tuple(getattr(item, "validation_refs", ()) or ()),
                    *tuple(getattr(item, "evidence_refs", ()) or ()),
                )
            },
            label="M4-M5 Mathematical Spine chain",
        )
        return PlatformSourceLineagePolicyResolution(
            m_row=M4_M5,
            anchor_ref=anchor,
            qro_ref=binding.qro_ref,
            business_entry_source="api",
            business_entrypoint_ref=_SPINE_BINDING_ENTRYPOINT_BY_ROW[M4_M5],
            lifecycle_ref=lifecycle_ref,
            math_spine_ref=_text(chain.chain_ref),
            specific_refs=(
                PlatformSpecificRef("factor_ref", anchor),
                PlatformSpecificRef("label_ref", label_ref),
            ),
            primary_rag_asset_ref=anchor,
            row_policy_metadata=(
                ("graph_command_ref", binding.command_ref),
                ("compiler_ir_ref", binding.ir_ref),
                ("compiler_pass_ref", binding.pass_ref),
                *self._spine_binding_metadata(
                    projection=projection,
                    business_lineage=business,
                ),
                ("formula_hash", formula_hash),
                ("factor_source_hash", _text(envelope.source_content_hash)),
            ),
        )

    def _m6(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(
            anchor,
            field="M6 anchor_ref",
            prefix=("model_passport:", "model_passport_"),
        )
        try:
            passport = self._context.model_governance_registry.passport(
                anchor,
                owner_user_id=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"M6 ModelPassport lookup failed:{type(exc).__name__}"
            ) from exc
        if _owner(passport) != owner or _text(passport.passport_id) != anchor:
            raise PlatformSourceLineagePolicyM1M8Error(
                "M6 ModelPassport owner/identity mismatch"
            )
        dossier_ref = _exact(
            passport.validation_dossier_ref,
            field="M6 validation_dossier_ref",
            prefix="validation_dossier:",
        )
        job_id = dossier_ref.removeprefix("validation_dossier:")
        try:
            job = self._context.training_service.get_job(job_id)
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"M6 training job lookup failed:{type(exc).__name__}"
            ) from exc
        model_version_ref = _exact(
            passport.model_version_ref,
            field="M6 model_version_ref",
            prefix="model_version:",
        )
        model_id, version_number = _model_version_parts(model_version_ref)
        versions = self._context.model_registry.list_versions(
            model_id,
            owner_user_id=owner,
        )
        version = _one(
            (item for item in versions if getattr(item, "version", None) == version_number),
            label="M6 ModelVersion",
        )
        if (
            _owner(job) != owner
            or _text(job.status) != "succeeded"
            or _text(job.model) != model_id
            or getattr(job, "model_version", None) != version_number
            or _text(job.model_passport_ref) != anchor
            or _text(job.validation_dossier_ref) != dossier_ref
            or _text(getattr(version, "model_passport_ref", "")) != anchor
            or _text(getattr(version, "validation_dossier_ref", "")) != dossier_ref
            or _text(getattr(version, "source_run_id", "")) != _text(job.run_id)
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                "M6 Job/Passport/ModelVersion lineage is stale or recombined"
            )
        binding, projection, business = self._spine_binding_lineage(
            owner=owner,
            row=M6,
            predicate=lambda item: _text(getattr(item, "qro_type", "")) == "Model"
            and _text(getattr(item, "qro_id", "")) == _text(job.qro_id),
        )
        self._require_historical_linkage(
            lineage=business,
            qro_ref=job.qro_id,
            command_ref=job.research_graph_command_id,
            label="M6",
        )
        qro = binding.qro
        output = _mapping(qro.output_contract, field="M6 QRO output_contract")
        for key, expected in (
            ("status", "succeeded"),
            ("job_id", job_id),
            ("model", model_id),
            ("model_version", version_number),
            ("model_version_ref", model_version_ref),
            ("model_passport_ref", anchor),
            ("validation_dossier_ref", dossier_ref),
            ("run_id", job.run_id),
            ("metrics_hash", content_hash(dict(job.metrics or {}))),
        ):
            _require_equal(output.get(key), expected, field=f"M6 QRO output {key}")
        expected_implementation_hash = "training_job:" + content_hash(
            {
                "job_id": job_id,
                "model_version_ref": model_version_ref,
                "request_hash": content_hash(dict(job.request or {})),
                "metrics_hash": content_hash(dict(job.metrics or {})),
            }
        )
        _require_equal(
            qro.implementation_hash,
            expected_implementation_hash,
            field="M6 QRO implementation_hash",
        )
        chain = self._math_chain(
            owner=owner,
            lineage=binding,
            predicate=lambda item: _text(getattr(item, "model_ref", ""))
            in {model_version_ref, anchor},
            label="M6 Mathematical Spine chain",
        )
        stage = _exact(getattr(version, "stage", ""), field="M6 ModelVersion stage")
        lifecycle_ref = f"stage:{owner}:{model_id}:v{version_number}:{stage}"
        return PlatformSourceLineagePolicyResolution(
            m_row=M6,
            anchor_ref=anchor,
            qro_ref=binding.qro_ref,
            business_entry_source="api",
            business_entrypoint_ref=_SPINE_BINDING_ENTRYPOINT_BY_ROW[M6],
            lifecycle_ref=lifecycle_ref,
            math_spine_ref=_text(chain.chain_ref),
            specific_refs=(
                PlatformSpecificRef("model_passport_ref", anchor),
                PlatformSpecificRef("validation_dossier_ref", dossier_ref),
            ),
            primary_rag_asset_ref=model_version_ref,
            row_policy_metadata=(
                ("graph_command_ref", binding.command_ref),
                ("compiler_ir_ref", binding.ir_ref),
                ("compiler_pass_ref", binding.pass_ref),
                *self._spine_binding_metadata(
                    projection=projection,
                    business_lineage=business,
                ),
                ("model_version_ref", model_version_ref),
                ("model_stage", stage),
                ("training_job_id", job_id),
            ),
        )

    def _m7_m8(self, *, owner: str, anchor: str) -> PlatformSourceLineagePolicyResolution:
        anchor = _exact(anchor, field="M7-M8 anchor_ref", prefix="portfolio_policy:")
        try:
            policy = self._context.research_design_registry.portfolio_policy(
                anchor,
                owner_user_id=owner,
            )
            strategy = self._context.research_design_registry.strategy_book(
                _text(policy.strategy_book_ref),
                owner_user_id=owner,
            )
            signal_envelope = (
                self._context.research_design_registry.signal_contract_envelope(
                    _text(policy.signal_contract_ref),
                    owner_user_id=owner,
                )
            )
            contract = self._context.signal_contract_registry.get(
                _text(policy.signal_contract_ref).removeprefix("signal_contract:")
            )
            validation = self._context.signal_validation_registry.validation(
                _text(policy.signal_validation_ref),
                owner_user_id=owner,
            )
        except Exception as exc:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"M7-M8 typed anchor lookup failed:{type(exc).__name__}"
            ) from exc
        signal_ref = _text(policy.signal_contract_ref)
        raw_signal_ref = signal_ref.removeprefix("signal_contract:")
        strategy_payload = dict(getattr(strategy, "strategy_book", {}) or {})
        if (
            _owner(policy) != owner
            or _text(policy.portfolio_policy_ref) != anchor
            or _owner(strategy) != owner
            or _owner(signal_envelope) != owner
            or _owner(validation) != owner
            or source_object_hash(contract) != _text(signal_envelope.source_content_hash)
            or content_hash(strategy_payload) != _text(strategy.source_content_hash)
            or _text(policy.signal_contract_source_hash)
            != _text(signal_envelope.source_content_hash)
            or _text(policy.strategy_book_source_hash)
            != _text(strategy.source_content_hash)
            or _text(getattr(validation, "verdict", "")) != "accepted"
            or _text(getattr(validation, "signal_ref", "")) != raw_signal_ref
            or raw_signal_ref
            not in {_text(item) for item in strategy_payload.get("signal_refs", ())}
            or _text(policy.signal_validation_ref)
            not in {
                _text(item)
                for item in strategy_payload.get("signal_validation_refs", ())
            }
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                "M7-M8 policy bundle is stale or recombined"
            )
        linkage = policy.linkage
        binding, projection, business = self._spine_binding_lineage(
            owner=owner,
            row=M7_M8,
            predicate=lambda item: _text(getattr(item, "qro_type", ""))
            == "PortfolioPolicy"
            and _text(getattr(item, "qro_id", "")) == _text(linkage.qro_ref),
        )
        self._require_historical_linkage(
            lineage=business,
            qro_ref=linkage.qro_ref,
            command_ref=linkage.research_graph_ref,
            label="M7-M8",
        )
        qro = binding.qro
        output = _mapping(qro.output_contract, field="M7-M8 QRO output_contract")
        for key, expected in (
            ("signal_contract_ref", signal_ref),
            ("signal_validation_ref", policy.signal_validation_ref),
            ("strategy_book_ref", policy.strategy_book_ref),
            ("portfolio_policy_ref", anchor),
        ):
            _require_equal(output.get(key), expected, field=f"M7-M8 QRO output {key}")
        lifecycle_ref = _text(linkage.lifecycle_ref)
        lifecycle = self._context.asset_lifecycle_registry.governed_asset(
            lifecycle_ref,
            owner_user_id=owner,
        )
        if (
            _text(lifecycle.asset_ref) != anchor
            or _text(lifecycle.asset_type) != "PortfolioPolicy"
        ):
            raise PlatformSourceLineagePolicyM1M8Error(
                "M7-M8 lifecycle does not bind the PortfolioPolicy"
            )
        strategy_ref = _text(policy.strategy_book_ref)
        chain = self._math_chain(
            owner=owner,
            lineage=binding,
            predicate=lambda item: (
                _text(getattr(item, "signal_contract_ref", "")) == signal_ref
                and _text(getattr(item, "strategy_book_ref", "")) == strategy_ref
                and _text(getattr(item, "portfolio_policy_ref", "")) == anchor
            ),
            label="M7-M8 Mathematical Spine chain",
        )
        return PlatformSourceLineagePolicyResolution(
            m_row=M7_M8,
            anchor_ref=anchor,
            qro_ref=binding.qro_ref,
            business_entry_source="api",
            business_entrypoint_ref=_SPINE_BINDING_ENTRYPOINT_BY_ROW[M7_M8],
            lifecycle_ref=lifecycle_ref,
            math_spine_ref=_text(chain.chain_ref),
            specific_refs=(
                PlatformSpecificRef("signal_contract_ref", signal_ref),
                PlatformSpecificRef(
                    "signal_validation_ref",
                    _text(policy.signal_validation_ref),
                ),
                PlatformSpecificRef("strategy_book_ref", strategy_ref),
                PlatformSpecificRef("portfolio_policy_ref", anchor),
            ),
            primary_rag_asset_ref=anchor,
            row_policy_metadata=(
                ("graph_command_ref", binding.command_ref),
                ("compiler_ir_ref", binding.ir_ref),
                ("compiler_pass_ref", binding.pass_ref),
                *self._spine_binding_metadata(
                    projection=projection,
                    business_lineage=business,
                ),
                ("portfolio_policy_source_hash", _text(policy.source_content_hash)),
                ("strategy_book_source_hash", _text(strategy.source_content_hash)),
                ("signal_contract_source_hash", _text(signal_envelope.source_content_hash)),
            ),
        )

    def resolve(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineagePolicyResolution:
        owner = _exact(owner_user_id, field="owner_user_id")
        row = str(getattr(m_row, "value", m_row) or "")
        if row not in SUPPORTED_ROWS:
            raise PlatformSourceLineagePolicyM1M8Error(
                f"unsupported M1-M8 policy row: {row!r}"
            )
        resolver = {
            M1_M2: self._m1_m2,
            M3: self._m3,
            M4_M5: self._m4_m5,
            M6: self._m6,
            M7_M8: self._m7_m8,
        }[row]
        return resolver(owner=owner, anchor=anchor_ref)

    def semantic_violations(
        self,
        resolution: PlatformSourceLineagePolicyResolution,
        *,
        owner_user_id: str,
        business_coverage: Any,
        capability_record: PlatformCapabilityRecord,
        rag_document: Any,
    ) -> tuple[str, ...]:
        """Re-resolve the anchor and compare every server-derived relation."""

        violations: list[str] = []
        try:
            expected = self.resolve(
                owner_user_id=owner_user_id,
                m_row=resolution.m_row,
                anchor_ref=resolution.anchor_ref,
            )
        except Exception as exc:
            return (f"policy anchor is no longer current:{type(exc).__name__}",)
        if expected != resolution:
            violations.append("policy resolution differs from current typed stores")
        if _text(getattr(business_coverage, "recorded_by", "")) != owner_user_id:
            violations.append("business coverage owner mismatch")
        if _text(getattr(business_coverage, "entry_source", "")) != expected.business_entry_source:
            violations.append("business coverage entry source mismatch")
        if (
            _text(getattr(business_coverage, "entrypoint_ref", ""))
            != expected.business_entrypoint_ref
        ):
            violations.append("business coverage entrypoint mismatch")
        if tuple(getattr(business_coverage, "qro_refs", ()) or ()) != (expected.qro_ref,):
            violations.append("business coverage QRO mismatch")
        metadata = dict(expected.row_policy_metadata)
        for field, refs in (
            (
                "research_graph_command_refs",
                (metadata.get("graph_command_ref"),),
            ),
            ("compiler_ir_refs", (metadata.get("compiler_ir_ref"),)),
            ("compiler_pass_refs", (metadata.get("compiler_pass_ref"),)),
        ):
            if tuple(getattr(business_coverage, field, ()) or ()) != refs:
                violations.append(f"business coverage {field} mismatch")
        if _text(getattr(capability_record, "m_row", "")) != expected.m_row:
            violations.append("capability row mismatch")
        if _text(capability_record.qro_ref) != expected.qro_ref:
            violations.append("capability QRO mismatch")
        if _text(capability_record.research_graph_ref) != _text(
            metadata.get("graph_command_ref")
        ):
            violations.append("capability Research Graph command mismatch")
        if _text(capability_record.lifecycle_ref) != expected.lifecycle_ref:
            violations.append("capability lifecycle mismatch")
        if _text(capability_record.math_spine_ref) != expected.math_spine_ref:
            violations.append("capability Mathematical Spine mismatch")
        if _specific_map(capability_record) != {
            item.key: item.ref for item in expected.specific_refs
        }:
            violations.append("capability specific refs mismatch")
        if _text(getattr(rag_document, "asset_ref", "")) != expected.primary_rag_asset_ref:
            violations.append("reserved RAG asset mismatch")
        permission = getattr(rag_document, "permission", None)
        if owner_user_id not in tuple(getattr(permission, "allowed_users", ()) or ()):
            violations.append("reserved RAG owner permission mismatch")
        if expected.primary_rag_asset_ref not in tuple(
            getattr(permission, "allowed_assets", ()) or ()
        ):
            violations.append("reserved RAG asset permission mismatch")
        return tuple(violations)


def build_platform_source_lineage_policy_resolver_m1_m8(
    context: PlatformSourceLineagePoliciesM1M8Context,
) -> PlatformSourceLineagePolicyResolverM1M8:
    """Build the complete server-owned policy group for M1-M8."""

    return PlatformSourceLineagePolicyResolverM1M8(context)


__all__ = [
    "M1_M2_SPINE_BINDING_ENTRYPOINT_REF",
    "M3_SPINE_BINDING_ENTRYPOINT_REF",
    "M4_M5_SPINE_BINDING_ENTRYPOINT_REF",
    "M6_SPINE_BINDING_ENTRYPOINT_REF",
    "M7_M8_SPINE_BINDING_ENTRYPOINT_REF",
    "PlatformSourceLineagePoliciesM1M8Context",
    "PlatformSourceLineagePolicyM1M8Error",
    "PlatformSourceLineagePolicyResolverM1M8",
    "SUPPORTED_ROWS",
    "build_platform_source_lineage_policy_resolver_m1_m8",
]
