from __future__ import annotations

from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import Any

import pytest

from app.copy_trade.service import Follower, copy_trade_subscription_ref
from app.ide.service import StrategyFile
from app.lineage.ids import content_hash
from app.research_os.asset_lifecycle import (
    AssetCategory,
    GovernedAssetRecord,
    LifecycleState,
)
from app.research_os.compiler import PersistentCompilerIRStore
from app.research_os.goal_coverage import (
    PersistentGoalEntrypointCoverageRegistry,
    goal_entrypoint_coverage_identity,
)
from app.research_os.platform_business_attestations import (
    PlatformBusinessAttestationService,
)
from app.research_os.platform_business_history_m16_m21 import (
    m21_governed_template_snapshot_hash,
    m21_ide_strategy_snapshot_hash,
)
from app.research_os.platform_coverage import (
    PlatformCapabilityRecord,
    PlatformSpecificRef,
)
from app.research_os.platform_source_lineage_policies_m16_m21 import (
    PlatformSourceLineagePoliciesM16M21Context,
    PlatformSourceLineagePolicyM16M21Error,
    PlatformSourceLineagePolicyResolverM16M21,
    build_platform_source_lineage_policy_resolver_m16_m21,
)
from app.research_os.ref_resolution import RealRefResolver
from app.research_os.spine import PersistentResearchGraphStore
from app.sharing import SharingService
from tests.test_platform_business_attestations import (
    OWNER as PERSISTENT_ATTESTATION_OWNER,
    _CompilerHarness as _PersistentAttestationCompilerHarness,
    _ReplayResolver as _PersistentAttestationCoverageResolver,
    _m17_system as _persistent_m17_system,
    _policy_context as _persistent_policy_context,
)


OWNER = "owner:platform-policy:m16-m21"
OTHER_OWNER = "owner:platform-policy:m16-m21:other"

DIRECT_GOAL_SECTIONS = {
    "M17": ("§0", "§1", "§6", "§8", "§16"),
    "M18": ("§0", "§1", "§6", "§7", "§8", "§17"),
    "M20": ("§0", "§1", "§8", "§16"),
}

POST_BINDING_GOAL_SECTIONS = {
    "M16": ("§0", "§1", "§6", "§8", "§16"),
    "M19": ("§0", "§1", "§6", "§8", "§17"),
    "M21": ("§0", "§1", "§6", "§8"),
}


def _unique(*groups: Any) -> tuple[str, ...]:
    refs: list[str] = []
    for group in groups:
        values = group if isinstance(group, (tuple, list)) else (group,)
        for value in values:
            ref = str(value)
            if ref not in refs:
                refs.append(ref)
    return tuple(refs)


class _Unavailable:
    def __getattr__(self, name: str):
        def missing(*_args: Any, **_kwargs: Any) -> Any:
            raise KeyError(name)

        return missing


class _Graph:
    def __init__(self, qro: Any, command: Any) -> None:
        self._qros = {qro.qro_id: qro}
        self._commands = [command]
        self._projections = {
            qro.qro_id: self._projection(qro=qro, command=command)
        }

    @staticmethod
    def _projection(*, qro: Any, command: Any) -> Any:
        return SimpleNamespace(
            projection_ref=f"rgproj:{command.command_id}",
            qro_id=qro.qro_id,
            qro_type=str(getattr(qro, "qro_type", "")),
            command_id=command.command_id,
            owner=qro.owner,
            actor=command.actor,
            source=command.source,
            actor_source=getattr(command, "actor_source", ""),
            evidence_refs=tuple(getattr(qro, "evidence_refs", ()) or ()),
            mathematical_refs=tuple(qro.mathematical_refs),
            input_contract_hash=content_hash(qro.input_contract),
            output_contract_hash=content_hash(qro.output_contract),
            qro_version=int(getattr(qro, "version", 1) or 1),
        )

    def qro(self, ref: str) -> Any:
        if ref not in self._qros:
            raise KeyError(ref)
        return self._qros[ref]

    def commands(self) -> list[Any]:
        return list(self._commands)

    def projection_index(self, *, owner: str) -> list[Any]:
        return [
            item
            for item in self._projections.values()
            if item.owner == owner
        ]

    def add(self, qro: Any, command: Any) -> None:
        self._qros[qro.qro_id] = qro
        self._commands.append(command)
        self._projections[qro.qro_id] = self._projection(qro=qro, command=command)

    def add_history(self, command: Any) -> None:
        self._commands.append(command)


class _Compiler:
    def __init__(self, ir: Any, compiler_pass: Any) -> None:
        self._irs = {ir.ir_ref: ir}
        self._passes = {compiler_pass.pass_ref: compiler_pass}

    def ir(self, ref: str, *, owner: str | None = None) -> Any:
        if ref not in self._irs or owner != OWNER:
            raise KeyError(ref)
        return self._irs[ref]

    def compiler_pass(self, ref: str, *, owner: str | None = None) -> Any:
        if ref not in self._passes or owner != OWNER:
            raise KeyError(ref)
        return self._passes[ref]

    def canonical_ir(self, ref: str, *, owner: str) -> Any:
        return self.ir(ref, owner=owner)

    def canonical_compiler_pass(self, ref: str, *, owner: str) -> Any:
        return self.compiler_pass(ref, owner=owner)

    def add(self, ir: Any, compiler_pass: Any) -> None:
        self._irs[ir.ir_ref] = ir
        self._passes[compiler_pass.pass_ref] = compiler_pass

    def irs(self, *, owner: str) -> list[Any]:
        return [item for item in self._irs.values() if item.owner == owner]

    def passes(self, *, owner: str) -> list[Any]:
        return [item for item in self._passes.values() if item.actor == owner]


class _Entrypoints:
    def __init__(self, records: list[Any]) -> None:
        self.records_value = records
        self.accepted = True
        self.rejected_refs: set[str] = set()
        self.rejected_proof_refs: set[str] = set()
        self.validation_calls: list[str] = []

    def records(self, *, owner: str) -> tuple[Any, ...]:
        if owner != OWNER:
            return ()
        return tuple(self.records_value)

    def validate_real_backing(self, coverage: Any) -> Any:
        self.validation_calls.append(coverage.coverage_ref)
        proof_refs = {
            *tuple(getattr(coverage, "evidence_refs", ()) or ()),
            *tuple(getattr(coverage, "validation_refs", ()) or ()),
        }
        return SimpleNamespace(
            accepted=(
                self.accepted
                and coverage.coverage_ref not in self.rejected_refs
                and not proof_refs.intersection(self.rejected_proof_refs)
            ),
            violations=(),
        )


class _Spine:
    def __init__(self, chain: Any) -> None:
        self._chains = {chain.chain_ref: chain}

    def verified_chain(self, ref: str, *, owner: str) -> Any:
        if ref not in self._chains or owner != OWNER:
            raise KeyError(ref)
        return self._chains[ref]

    def add(self, chain: Any) -> None:
        self._chains[chain.chain_ref] = chain


@dataclass
class _Business:
    row: str
    entry_source: str
    entrypoint: str
    qro: Any
    command: Any
    chain: Any
    ir: Any
    compiler_pass: Any
    coverage: Any
    graph: _Graph
    compiler: _Compiler
    entrypoints: _Entrypoints
    spine: _Spine
    historical_qro: Any | None = None
    historical_command: Any | None = None
    historical_ir: Any | None = None
    historical_compiler_pass: Any | None = None
    historical_coverage: Any | None = None


def _business(
    row: str,
    *,
    qro_type: str,
    input_contract: dict[str, Any],
    output_contract: dict[str, Any],
    entry_source: str = "api",
    entrypoint: str,
    additional_evidence_refs: tuple[str, ...] = (),
    trailing_evidence_refs: tuple[str, ...] = (),
    validation_refs: tuple[str, ...] = (),
    chain_evidence_refs: tuple[str, ...] = (),
    chain_validation_refs: tuple[str, ...] = (),
    variant: str = "",
) -> _Business:
    suffix = row.lower().replace("-", "_")
    if variant:
        suffix = f"{suffix}_{variant}"
    direct = row in DIRECT_GOAL_SECTIONS
    post_binding = row in POST_BINDING_GOAL_SECTIONS
    governed_current = direct or post_binding
    anchor_key = {
        "M16": "shared_asset_ref",
        "M17": "submission_ref",
        "M18": "consistency_check_ref",
        "M19": "tutorial_asset_ref",
        "M20": "kill_switch_ref",
    }.get(row)
    if row == "M21":
        anchor = str(
            output_contract.get("ide_strategy_ref")
            if "governed_asset_ref" in input_contract
            else input_contract.get("asset_ref", "")
        )
    else:
        anchor = str(input_contract.get(anchor_key, "")) if anchor_key else ""
    chain = SimpleNamespace(
        chain_ref=f"math_spine_chain:{suffix}",
        recorded_by=OWNER,
        risk_policy_ref=str(input_contract.get("risk_gate_ref", "")),
        execution_policy_ref="",
        evidence_refs=tuple(chain_evidence_refs),
        validation_refs=tuple(chain_validation_refs),
    )
    evidence_refs = _unique(
        tuple(input_contract.values()),
        additional_evidence_refs,
        chain.chain_ref,
        trailing_evidence_refs,
    )
    attestation_validation_refs = (
        () if row == "M18" else _unique(validation_refs, chain.chain_ref)
    )
    compiler_evidence_refs = (
        (f"entrypoint_evidence:{suffix}:aggregate",)
        if direct
        else evidence_refs
    )
    compiler_validation_refs = (
        _unique(
            attestation_validation_refs,
            f"goal_validation_receipt:{suffix}:aggregate",
        )
        if direct
        else attestation_validation_refs
    )
    implementation_hash = "platform_business_attestation_" + content_hash(
        {
            "schema_version": 1,
            "row": row,
            "owner_user_id": OWNER,
            "input_contract": input_contract,
            "output_contract": output_contract,
            "mathematical_spine_chain_ref": chain.chain_ref,
        }
    )
    qro = SimpleNamespace(
        qro_id=f"qro_{suffix}_aggregate",
        qro_type=qro_type,
        owner=OWNER,
        actor="user_manual" if governed_current else "",
        input_contract=dict(input_contract),
        output_contract=dict(output_contract),
        lineage=_unique(tuple(input_contract.values()), chain.chain_ref),
        implementation_hash=implementation_hash,
        permission=(
            f"platform.business_attestation:{row.lower()}:owner"
            if direct
            else ""
        ),
        evidence_refs=evidence_refs,
        mathematical_refs=(chain.chain_ref,),
        version=1,
    )
    command_id = (
        "rgcmd_"
        + content_hash(
            {
                "schema_version": 1,
                "record_type": "platform_business_attestation",
                "row": row,
                "owner_user_id": OWNER,
                "anchor_ref": anchor,
                "entrypoint_ref": entrypoint,
                "qro_ref": qro.qro_id,
                "mathematical_spine_chain_ref": chain.chain_ref,
            }
        )
        if direct
        else f"rgcmd_{suffix}_aggregate"
    )
    command = SimpleNamespace(
        command_id=command_id,
        source=entry_source,
        command_type="upsert_qro",
        actor_source="user_manual" if governed_current else "",
        actor=OWNER,
        payload={"qro": qro},
        evidence_refs=evidence_refs,
        tool_record_refs=(entrypoint,) if governed_current else (),
    )
    canonical = _unique(
        f"research_graph_command:{command.command_id}",
        (anchor, chain.chain_ref) if governed_current else (),
        (
            (str(input_contract["canonical_code_command_ref"]),)
            if row == "M18"
            else ()
        ),
        f"entrypoint:{entrypoint}",
    )
    permission_ref = (
        f"platform.business_attestation:{row.lower()}:user_manual"
        if direct
        else (
            f"platform.spine_binding:{row.lower()}:user_manual"
            if post_binding
            else ""
        )
    )
    ir = SimpleNamespace(
        ir_ref=f"compiler_ir:{suffix}:aggregate",
        source_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        mathematical_spine_chain_refs=(chain.chain_ref,),
        canonical_command_refs=canonical,
        evidence_refs=compiler_evidence_refs,
        validation_refs=compiler_validation_refs,
        permission_ref=permission_ref,
        owner=OWNER,
    )
    compiler_pass = SimpleNamespace(
        pass_ref=f"compiler_pass:{suffix}:aggregate",
        output_ir_ref=ir.ir_ref,
        input_ir_refs=(),
        input_qro_refs=(qro.qro_id,),
        graph_command_refs=(command.command_id,),
        canonical_command_refs=canonical,
        actor=OWNER,
        actor_source="user_manual" if governed_current else "",
        entry_source=entry_source,
        permission_ref=permission_ref,
        tool_record_refs=(
            (entrypoint, anchor, chain.chain_ref, "api:compile_qro")
            if governed_current
            else ()
        ),
        evidence_refs=compiler_evidence_refs,
        validation_refs=compiler_validation_refs,
        status="compiled",
    )
    goal_sections = DIRECT_GOAL_SECTIONS.get(
        row,
        POST_BINDING_GOAL_SECTIONS.get(row, ("§1",)),
    )
    coverage_ref = (
        goal_entrypoint_coverage_identity(
            entry_source=entry_source,
            entrypoint_ref=entrypoint,
            goal_sections=goal_sections,
            qro_refs=(qro.qro_id,),
            research_graph_command_refs=(command.command_id,),
            compiler_ir_refs=(ir.ir_ref,),
            compiler_pass_refs=(compiler_pass.pass_ref,),
        )
        if governed_current
        else f"goal_entrypoint_coverage:{suffix}:business"
    )
    coverage = SimpleNamespace(
        coverage_ref=coverage_ref,
        recorded_by=OWNER,
        goal_sections=goal_sections,
        entry_source=entry_source,
        entrypoint_ref=entrypoint,
        qro_refs=(qro.qro_id,),
        research_graph_command_refs=(command.command_id,),
        compiler_ir_refs=(ir.ir_ref,),
        compiler_pass_refs=(compiler_pass.pass_ref,),
        canonical_command_refs=canonical,
        evidence_refs=compiler_evidence_refs,
        validation_refs=compiler_validation_refs,
        permission_refs=(permission_ref,) if governed_current else (),
        silent_mock_fallback_used=False,
        raw_payload_persisted=False,
    )
    return _Business(
        row=row,
        entry_source=entry_source,
        entrypoint=entrypoint,
        qro=qro,
        command=command,
        chain=chain,
        ir=ir,
        compiler_pass=compiler_pass,
        coverage=coverage,
        graph=_Graph(qro, command),
        compiler=_Compiler(ir, compiler_pass),
        entrypoints=_Entrypoints([coverage]),
        spine=_Spine(chain),
    )


def _add_historical_business_head(
    business: _Business,
    *,
    entrypoint: str,
    variant: str = "",
) -> None:
    suffix = business.row.lower().replace("-", "_")
    if variant:
        suffix = f"{suffix}_{variant}"
    historical_qro = SimpleNamespace(
        **{
            **vars(business.qro),
            "input_contract": dict(business.qro.input_contract),
            "output_contract": dict(business.qro.output_contract),
            "mathematical_refs": (),
        }
    )
    command = SimpleNamespace(
        command_id=f"rgcmd_{suffix}_historical_business",
        source="api",
        command_type="upsert_qro",
        actor_source="user_manual",
        actor=OWNER,
        payload={"qro": historical_qro},
        evidence_refs=(f"business_evidence:{suffix}",),
        tool_record_refs=(entrypoint,),
    )
    if business.row in POST_BINDING_GOAL_SECTIONS:
        business.command.evidence_refs = (
            business.chain.chain_ref,
            command.command_id,
        )
    canonical = (
        f"research_graph_command:{command.command_id}",
        f"entrypoint:{entrypoint}",
    )
    compiler_ir = SimpleNamespace(
        ir_ref=f"compiler_ir:{suffix}:historical_business",
        source_qro_refs=(historical_qro.qro_id,),
        graph_command_refs=(command.command_id,),
        mathematical_spine_chain_refs=(),
        canonical_command_refs=canonical,
        owner=OWNER,
    )
    compiler_pass = SimpleNamespace(
        pass_ref=f"compiler_pass:{suffix}:historical_business",
        output_ir_ref=compiler_ir.ir_ref,
        input_qro_refs=(historical_qro.qro_id,),
        graph_command_refs=(command.command_id,),
        canonical_command_refs=canonical,
        actor=OWNER,
        entry_source="api",
        status="compiled",
    )
    goal_sections = ("§1",)
    qro_refs = (historical_qro.qro_id,)
    graph_refs = (command.command_id,)
    ir_refs = (compiler_ir.ir_ref,)
    pass_refs = (compiler_pass.pass_ref,)
    coverage = SimpleNamespace(
        coverage_ref=goal_entrypoint_coverage_identity(
            entry_source="api",
            entrypoint_ref=entrypoint,
            goal_sections=goal_sections,
            qro_refs=qro_refs,
            research_graph_command_refs=graph_refs,
            compiler_ir_refs=ir_refs,
            compiler_pass_refs=pass_refs,
        ),
        recorded_by=OWNER,
        goal_sections=goal_sections,
        entry_source="api",
        entrypoint_ref=entrypoint,
        qro_refs=qro_refs,
        research_graph_command_refs=graph_refs,
        compiler_ir_refs=ir_refs,
        compiler_pass_refs=pass_refs,
        canonical_command_refs=canonical,
        evidence_refs=(f"evidence:{suffix}:historical_business",),
        validation_refs=(f"goal_validation_receipt:{suffix}:historical_business",),
        permission_refs=(f"permission:{suffix}:historical_business",),
        replay_refs=(
            f"replay:research_graph:{command.command_id}",
            f"replay:compiler_ir:{compiler_ir.ir_ref}",
            f"replay:compiler_pass:{compiler_pass.pass_ref}",
        ),
        claims_full_product_entrypoint=False,
        silent_mock_fallback_used=False,
        raw_payload_persisted=False,
    )
    business.graph.add_history(command)
    business.compiler.add(compiler_ir, compiler_pass)
    business.entrypoints.records_value.append(coverage)
    business.historical_qro = historical_qro
    business.historical_command = command
    business.historical_ir = compiler_ir
    business.historical_compiler_pass = compiler_pass
    business.historical_coverage = coverage


class _Lifecycle:
    def __init__(self, assets: tuple[Any, ...] = ()) -> None:
        self.assets = {asset.asset_ref: asset for asset in assets}

    def governed_asset(self, ref: str, *, owner_user_id: str) -> Any:
        if owner_user_id != OWNER:
            raise KeyError(ref)
        return self.assets[ref]

    def governed_asset_by_mock_label_ref(
        self,
        ref: str,
        *,
        owner_user_id: str,
    ) -> Any:
        matches = [
            asset
            for asset in self.assets.values()
            if owner_user_id == OWNER and asset.mock_label_ref == ref
        ]
        if len(matches) != 1:
            raise KeyError(ref)
        return matches[0]

    def governed_asset_by_category_ref(
        self,
        ref: str,
        *,
        owner_user_id: str,
    ) -> Any:
        matches = [
            asset
            for asset in self.assets.values()
            if owner_user_id == OWNER and asset.asset_category_ref == ref
        ]
        if len(matches) != 1:
            raise KeyError(ref)
        return matches[0]


def _context(
    business: _Business,
    *,
    lifecycle: Any | None = None,
    sharing: Any | None = None,
    copy_trade: Any | None = None,
    promotions: Any | None = None,
    risks: Any | None = None,
    submissions: Any | None = None,
    intents: Any | None = None,
    ledger: Any | None = None,
    rdps: Any | None = None,
    teaching: Any | None = None,
    onboarding: Any | None = None,
    calls: Any | None = None,
    halts: Any | None = None,
    ide_strategy_loader=None,
    entrypoint_view_factory=None,
) -> PlatformSourceLineagePoliciesM16M21Context:
    unavailable = _Unavailable()
    return PlatformSourceLineagePoliciesM16M21Context(
        research_graph_store=business.graph,
        compiler_store=business.compiler,
        entrypoint_registry=business.entrypoints,
        spine_chain_registry=business.spine,
        asset_lifecycle_registry=lifecycle or _Lifecycle(),
        sharing_service=sharing or unavailable,
        copy_trade_service=copy_trade or unavailable,
        runtime_promotion_registry=promotions or unavailable,
        follower_risk_state_store=risks or unavailable,
        execution_order_submission_registry=submissions or unavailable,
        execution_order_intent_registry=intents or unavailable,
        canonical_spine_ledger=ledger or unavailable,
        rdp_store=rdps or unavailable,
        teaching_asset_registry=teaching or unavailable,
        onboarding_registry=onboarding or unavailable,
        llm_call_record_store=calls or unavailable,
        account_halt_barrier=halts or unavailable,
        ide_strategy_loader=ide_strategy_loader,
        llm_service_owner_user_id="service:llm",
        entrypoint_view_factory=entrypoint_view_factory,
    )


def _specific(resolution: Any) -> dict[str, str]:
    return {item.key: item.ref for item in resolution.specific_refs}


def _assert_business_metadata(resolution: Any, business: _Business) -> None:
    metadata = dict(resolution.row_policy_metadata)
    assert len(metadata) == len(resolution.row_policy_metadata)
    assert metadata["business_coverage_ref"] == business.coverage.coverage_ref
    assert metadata["graph_command_ref"] == business.command.command_id
    assert metadata["compiler_ir_ref"] == business.ir.ir_ref
    assert metadata["compiler_pass_ref"] == business.compiler_pass.pass_ref


def _assert_post_business_metadata(resolution: Any, business: _Business) -> None:
    metadata = dict(resolution.row_policy_metadata)
    assert metadata["binding_projection_ref"] == (
        f"rgproj:{business.command.command_id}"
    )
    assert metadata["business_graph_command_ref"] == (
        business.historical_command.command_id
    )
    assert metadata["historical_business_coverage_ref"] == (
        business.historical_coverage.coverage_ref
    )
    assert metadata["business_compiler_ir_ref"] == business.historical_ir.ir_ref
    assert metadata["business_compiler_pass_ref"] == (
        business.historical_compiler_pass.pass_ref
    )
    assert metadata["historical_business_entry_source"] == "api"


def _add_duplicate_business_attestation(
    business: _Business,
    *,
    suffix: str,
) -> None:
    qro = SimpleNamespace(
        **{
            **vars(business.qro),
            "qro_id": f"qro_{business.row.lower()}_aggregate_{suffix}",
            "input_contract": dict(business.qro.input_contract),
            "output_contract": dict(business.qro.output_contract),
        }
    )
    command = SimpleNamespace(
        **{
            **vars(business.command),
            "command_id": f"rgcmd_{business.row.lower()}_aggregate_{suffix}",
            "payload": {"qro": qro},
        }
    )
    canonical = (
        f"research_graph_command:{command.command_id}",
        f"entrypoint:{business.entrypoint}",
    )
    ir = SimpleNamespace(
        **{
            **vars(business.ir),
            "ir_ref": f"compiler_ir:{business.row.lower()}:aggregate:{suffix}",
            "source_qro_refs": (qro.qro_id,),
            "graph_command_refs": (command.command_id,),
            "canonical_command_refs": canonical,
        }
    )
    compiler_pass = SimpleNamespace(
        **{
            **vars(business.compiler_pass),
            "pass_ref": f"compiler_pass:{business.row.lower()}:aggregate:{suffix}",
            "output_ir_ref": ir.ir_ref,
            "input_qro_refs": (qro.qro_id,),
            "graph_command_refs": (command.command_id,),
            "canonical_command_refs": canonical,
        }
    )
    coverage = SimpleNamespace(
        **{
            **vars(business.coverage),
            "coverage_ref": (
                f"goal_entrypoint_coverage:{business.row.lower()}:business:{suffix}"
            ),
            "qro_refs": (qro.qro_id,),
            "research_graph_command_refs": (command.command_id,),
            "compiler_ir_refs": (ir.ir_ref,),
            "compiler_pass_refs": (compiler_pass.pass_ref,),
            "canonical_command_refs": canonical,
        }
    )
    business.graph.add(qro, command)
    business.compiler.add(ir, compiler_pass)
    business.entrypoints.records_value.append(coverage)


def _m16_system(tmp_path):
    run_root = tmp_path / "runs"
    (run_root / "run-m16").mkdir(parents=True)
    sharing = SharingService(tmp_path / "sharing.sqlite3", run_root)
    strategy = sharing.publish_strategy(
        "run-m16",
        OWNER,
        "Shared M16 strategy",
        asset_class="equity_cn",
        public=True,
    )
    refs = strategy.to_dict()
    asset = SimpleNamespace(
        asset_ref=refs["shared_asset_ref"],
        asset_type="SharedStrategy",
        evidence_refs=(
            refs["permission_ref"],
            refs["source_ref"],
            refs["status_ref"],
        ),
        mock_label_ref=None,
        asset_category_ref=None,
    )
    business = _business(
        "M16",
        qro_type="StrategyBook",
        input_contract={
            "shared_asset_ref": refs["shared_asset_ref"],
            "permission_ref": refs["permission_ref"],
            "source_ref": refs["source_ref"],
        },
        output_contract={"status_ref": refs["status_ref"]},
        entrypoint="api:research_os.platform.business_attestations.m16",
    )
    _add_historical_business_head(business, entrypoint="api:sharing.publish")
    context = _context(
        business,
        lifecycle=_Lifecycle((asset,)),
        sharing=sharing,
    )
    return business, context, refs


def test_m16_derives_current_shared_strategy_and_governed_lifecycle(tmp_path) -> None:
    business, context, refs = _m16_system(tmp_path)
    resolver = build_platform_source_lineage_policy_resolver_m16_m21(context)

    result = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M16",
        anchor_ref=refs["shared_asset_ref"],
    )

    assert isinstance(resolver, PlatformSourceLineagePolicyResolverM16M21)
    assert resolver.registered_rows == ("M16", "M17", "M18", "M19", "M20", "M21")
    assert _specific(result) == {
        "shared_asset_ref": refs["shared_asset_ref"],
        "permission_ref": refs["permission_ref"],
        "source_ref": refs["source_ref"],
        "status_ref": refs["status_ref"],
    }
    assert result.qro_ref == business.qro.qro_id
    assert result.math_spine_ref == business.chain.chain_ref
    assert result.business_entrypoint_ref == (
        "api:research_os.platform.business_attestations.m16"
    )
    _assert_business_metadata(result, business)
    _assert_post_business_metadata(result, business)
    assert dict(result.row_policy_metadata)[
        "historical_business_entrypoint_ref"
    ] == "api:sharing.publish"


def test_m16_rejects_shared_asset_without_governed_lifecycle(tmp_path) -> None:
    _business_row, context, refs = _m16_system(tmp_path)
    context = replace(context, asset_lifecycle_registry=_Lifecycle())

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="typed sharing lookup failed",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M16",
            anchor_ref=refs["shared_asset_ref"],
        )


def _m17_system():
    promotion_ref = "runtime_promotion_m17_current"
    follower = Follower(
        follower_id="follower-m17",
        user_id=OWNER,
        master_id="master-m17",
        account_binding_ref="account:m17",
        credential_binding_ref="credential:m17",
        runtime_promotion_ref=promotion_ref,
        status="active",
    )
    subscription_ref = copy_trade_subscription_ref(follower)
    promotion = SimpleNamespace(
        runtime_promotion_ref=promotion_ref,
        target_runtime="live",
        subject_ref="copy_trade_subject_"
        + content_hash(
            {
                "follower_id": follower.follower_id,
                "user_id": follower.user_id,
                "master_id": follower.master_id,
                "account_binding_ref": follower.account_binding_ref,
            }
        ),
        permission_gate_ref="permission:m17",
        order_guard_ref="order_guard:m17",
    )
    reservation = SimpleNamespace(
        reservation_ref="copy_reservation_m17_current",
        risk_check_ref="copy_risk_check_m17_current",
        follower_id=follower.follower_id,
        account_binding_ref=follower.account_binding_ref,
    )
    audit_ref = "copy_submission_audit_" + content_hash(
        reservation.reservation_ref
    )
    intent_ref = "order_intent_" + content_hash("m17-current")
    intent = SimpleNamespace(
        order_intent_ref=intent_ref,
        recorded_by=OWNER,
        execution_policy_ref=promotion.permission_gate_ref,
        risk_policy_ref=reservation.risk_check_ref,
        runtime="live",
        asset_class="crypto_perp",
        instrument_ref="instrument:BTCUSDT:perp",
        permission_gate_ref=promotion.permission_gate_ref,
        order_guard_ref=promotion.order_guard_ref,
    )
    submission = SimpleNamespace(
        submission_ref="order_submission_m17_current",
        order_intent_ref=intent_ref,
        audit_record_ref=audit_ref,
        runtime_promotion_ref=promotion_ref,
        permission_gate_ref=promotion.permission_gate_ref,
        order_guard_ref=promotion.order_guard_ref,
        submitter_ref="copy_trade_signal_relayer:v1",
        submit_enabled=True,
        submission_mode="live",
        recorded_by="copy_trade_signal_relayer",
    )
    refs = {
        "submission_ref": submission.submission_ref,
        "copy_trade_subscription_ref": subscription_ref,
        "runtime_promotion_ref": promotion_ref,
        "risk_gate_ref": reservation.risk_check_ref,
        "execution_audit_ref": audit_ref,
    }
    business = _business(
        "M17",
        qro_type="ExecutionPolicy",
        input_contract=refs,
        output_contract={"status": "guarded_submission_recorded"},
        entrypoint="api:research_os.platform.business_attestations.m17",
        additional_evidence_refs=(
            reservation.reservation_ref,
            intent_ref,
            follower.account_binding_ref,
            promotion.order_guard_ref,
        ),
        validation_refs=(reservation.risk_check_ref, audit_ref),
    )
    business.chain.execution_policy_ref = promotion.permission_gate_ref

    class CopyTrade:
        def get_follower(self, ref):
            return follower if ref == follower.follower_id else None

        def subscription(self, ref, *, owner_user_id):
            if ref != subscription_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return follower

    class Promotions:
        def __init__(self, current: Any) -> None:
            self.current = current

        def promotion(self, ref):
            if ref != promotion_ref:
                raise KeyError(ref)
            return self.current

    class Risks:
        bound = reservation

        def reservation_for_submission(self, ref):
            if ref != submission.submission_ref:
                raise KeyError(ref)
            return self.bound

        def reservation_by_risk_check_ref(self, ref):
            if ref != self.bound.risk_check_ref:
                raise KeyError(ref)
            return self.bound

    class Submissions:
        def __init__(self) -> None:
            self.current = submission
            self.audit_ref = audit_ref
            self.audit_result = submission
            self.mutation_calls = 0

        def refresh(self):
            return None

        def submission(self, ref):
            if ref != self.current.submission_ref:
                raise KeyError(ref)
            return self.current

        def submission_by_audit_record_ref(self, ref):
            if ref != self.audit_ref:
                raise KeyError(ref)
            return self.audit_result

        def record_submission(self, *_args, **_kwargs):
            self.mutation_calls += 1
            raise AssertionError("policy must not record or submit an order")

    class Intents:
        def __init__(self) -> None:
            self.current = intent

        def refresh(self):
            return None

        def intent(self, ref):
            if ref != self.current.order_intent_ref:
                raise KeyError(ref)
            return self.current

    context = _context(
        business,
        copy_trade=CopyTrade(),
        promotions=Promotions(promotion),
        risks=Risks(),
        submissions=Submissions(),
        intents=Intents(),
    )
    return business, context, refs, reservation


def test_m17_derives_subscription_promotion_risk_and_audit_from_submission() -> None:
    business, context, refs, _reservation = _m17_system()

    result = build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
        owner_user_id=OWNER,
        m_row="M17",
        anchor_ref=refs["submission_ref"],
    )

    assert _specific(result) == {
        key: value for key, value in refs.items() if key != "submission_ref"
    }
    assert result.lifecycle_ref == refs["runtime_promotion_ref"]
    assert result.qro_ref == business.qro.qro_id
    assert result.business_entrypoint_ref == (
        "api:research_os.platform.business_attestations.m17"
    )
    assert dict(result.row_policy_metadata)["submission_ref"] == refs["submission_ref"]
    assert context.execution_order_submission_registry.mutation_calls == 0
    _assert_business_metadata(result, business)


def test_m17_rejects_same_owner_recombined_formal_risk_reservation() -> None:
    _business_row, context, refs, reservation = _m17_system()
    risks = context.follower_risk_state_store
    risks.bound = replace(
        reservation,
        account_binding_ref="account:same-owner-unrelated",
    ) if hasattr(reservation, "__dataclass_fields__") else SimpleNamespace(
        **{
            **vars(reservation),
            "account_binding_ref": "account:same-owner-unrelated",
        }
    )

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="stale or recombined",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=refs["submission_ref"],
        )


def test_m17_rejects_same_owner_recombined_runtime_promotion_subject() -> None:
    _business_row, context, refs, _reservation = _m17_system()
    context.runtime_promotion_registry.current.subject_ref = (
        "copy_trade_subject_same-owner-unrelated"
    )

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="stale or recombined",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=refs["submission_ref"],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("recorded_by", OWNER),
        ("submitter_ref", "generic_order_submitter:v1"),
    ),
)
def test_m17_rejects_noncanonical_underlying_relayer_actor(
    field: str,
    value: str,
) -> None:
    _business_row, context, refs, _reservation = _m17_system()
    submission = context.execution_order_submission_registry.submission(
        refs["submission_ref"]
    )
    setattr(submission, field, value)

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="stale or recombined",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=refs["submission_ref"],
        )
    assert context.execution_order_submission_registry.mutation_calls == 0


@pytest.mark.parametrize("mutation", ("missing", "recombined"))
def test_m17_rejects_missing_or_recombined_durable_submission_audit(
    mutation: str,
) -> None:
    business, context, refs, _reservation = _m17_system()
    submissions = context.execution_order_submission_registry
    if mutation == "missing":
        missing_ref = "copy_submission_audit_missing"
        submissions.current.audit_record_ref = missing_ref
        business.qro.input_contract["execution_audit_ref"] = missing_ref
    else:
        submissions.audit_result = SimpleNamespace(
            **{
                **vars(submissions.current),
                "submission_ref": "order_submission_same-owner-unrelated",
            }
        )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=refs["submission_ref"],
        )
    assert submissions.mutation_calls == 0


@pytest.mark.parametrize(
    "reservation_ref",
    ("", "copy_reservation_placeholder", "copy_reservation_same-owner-unrelated"),
)
def test_m17_rejects_missing_placeholder_or_recombined_reservation_identity(
    reservation_ref: str,
) -> None:
    _business_row, context, refs, reservation = _m17_system()
    context.follower_risk_state_store.bound = SimpleNamespace(
        **{**vars(reservation), "reservation_ref": reservation_ref}
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=refs["submission_ref"],
        )
    assert context.execution_order_submission_registry.mutation_calls == 0


@pytest.mark.parametrize("cardinality", ("zero", "two"))
def test_m17_rejects_zero_or_multiple_owner_api_attestations(
    cardinality: str,
) -> None:
    business, context, refs, _reservation = _m17_system()
    if cardinality == "zero":
        business.qro.qro_type = "StrategyBook"
    else:
        _add_duplicate_business_attestation(business, suffix="second")

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="strict business QRO/Graph/compiler lineage",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=refs["submission_ref"],
        )
    assert context.execution_order_submission_registry.mutation_calls == 0


@pytest.mark.parametrize(
    "contract_key",
    (
        "submission_ref",
        "copy_trade_subscription_ref",
        "runtime_promotion_ref",
        "risk_gate_ref",
        "execution_audit_ref",
    ),
)
def test_m17_rejects_recombined_owner_attestation_contract(
    contract_key: str,
) -> None:
    business, context, refs, _reservation = _m17_system()
    business.qro.input_contract[contract_key] = f"{contract_key}:same-owner-unrelated"

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="strict business QRO/Graph/compiler lineage",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=refs["submission_ref"],
        )
    assert context.execution_order_submission_registry.mutation_calls == 0


@pytest.mark.parametrize(
    "mutation",
    ("foreign_follower", "foreign_attestation", "stopped_subscription"),
)
def test_m17_rejects_foreign_or_stale_owner_state(mutation: str) -> None:
    business, context, refs, _reservation = _m17_system()
    follower = context.copy_trade_service.get_follower("follower-m17")
    if mutation == "foreign_follower":
        follower.user_id = OTHER_OWNER
    elif mutation == "foreign_attestation":
        business.qro.owner = OTHER_OWNER
    else:
        follower.status = "stopped"

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=refs["submission_ref"],
        )
    assert context.execution_order_submission_registry.mutation_calls == 0


def _m18_system():
    check_ref = "cc_m18_current"
    canonical_command_ref = "rgcmd_m18_ide_code"
    package_ref = "rdp_m18_current"
    code_hash = "sha256:m18-code-current"
    binding_ref = "tib_m18_current"
    source_qro_ref = "qro_m18_ide_code"
    test_ref = "pytest:m18"
    business = _business(
        "M18",
        qro_type="ValidationDossier",
        input_contract={
            "canonical_code_command_ref": canonical_command_ref,
            "consistency_check_ref": check_ref,
            "rdp_package_ref": package_ref,
        },
        output_contract={
            "status": "current_code_package_attested",
        },
        entry_source="api",
        entrypoint="api:research_os.platform.business_attestations.m18",
        additional_evidence_refs=(binding_ref, source_qro_ref, code_hash),
        trailing_evidence_refs=(test_ref,),
        validation_refs=(),
    )
    canonical_qro = SimpleNamespace(
        qro_id=source_qro_ref,
        qro_type="BacktestRun",
        owner=OWNER,
        input_contract={"entry_source": "ide", "code_hash": code_hash},
        output_contract={"status": "run_recorded"},
        mathematical_refs=(),
    )
    canonical_command = SimpleNamespace(
        command_id=canonical_command_ref,
        source="ide",
        command_type="upsert_qro",
        actor=OWNER,
        payload={"qro": canonical_qro},
    )
    business.graph.add(canonical_qro, canonical_command)
    binding = SimpleNamespace(
        binding_id=binding_ref,
        used_by=(canonical_command_ref,),
    )
    check = SimpleNamespace(
        check_id=check_ref,
        binding_id=binding.binding_id,
        result="pass",
    )
    business.chain.consistency_check_refs = (check_ref,)
    business.chain.theory_binding_refs = (binding.binding_id,)
    manifest = SimpleNamespace(
        package_id=package_ref,
        graph_refs=(canonical_command_ref,),
        code_refs=(code_hash,),
        consistency_check_refs=(check_ref,),
        test_refs=(test_ref,),
        unverified_residuals=(),
        mathematical_spine_chain_refs=(business.chain.chain_ref,),
    )

    class Ledger:
        def check(self, ref, *, owner):
            if ref != check_ref or owner != OWNER:
                raise KeyError(ref)
            return check

        def binding(self, ref, *, owner):
            if ref != binding.binding_id or owner != OWNER:
                raise KeyError(ref)
            return binding

    class RDPs:
        manifests_value = [manifest]

        def manifests(self, *, owner_user_id):
            return list(self.manifests_value) if owner_user_id == OWNER else []

    context = _context(business, ledger=Ledger(), rdps=RDPs())
    return business, context, check_ref, manifest, canonical_qro, canonical_command


def test_m18_derives_exact_ide_command_check_binding_rdp_and_math() -> None:
    business, context, check_ref, manifest, _canonical_qro, canonical_command = (
        _m18_system()
    )

    result = build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
        owner_user_id=OWNER,
        m_row="M18",
        anchor_ref=check_ref,
    )

    assert _specific(result) == {
        "canonical_code_command_ref": canonical_command.command_id,
        "consistency_check_ref": check_ref,
    }
    assert result.lifecycle_ref == manifest.package_id
    assert result.business_entry_source == "api"
    assert result.business_entrypoint_ref == (
        "api:research_os.platform.business_attestations.m18"
    )
    assert business.command.command_id not in manifest.graph_refs
    assert dict(result.row_policy_metadata)["canonical_code_qro_ref"] == (
        "qro_m18_ide_code"
    )
    _assert_business_metadata(result, business)


@pytest.mark.parametrize(
    "manifest_chain_refs",
    (
        (),
        ("math_spine_chain:m18", "math_spine_chain:m18:same-owner-other"),
        ("math_spine_chain:foreign-owner:m18",),
        ("math_spine_chain:m18:same-owner-other",),
    ),
    ids=("missing", "multiple", "foreign", "mismatched"),
)
def test_m18_policy_rejects_rdp_without_one_exact_selected_math_chain(
    manifest_chain_refs: tuple[str, ...],
) -> None:
    business, context, check_ref, manifest, _canonical_qro, _canonical_command = (
        _m18_system()
    )
    manifest.mathematical_spine_chain_refs = manifest_chain_refs

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="mathematical_spine_chain_refs|exact verified Mathematical Spine chain",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


def _add_second_m18_attestation(business: _Business) -> None:
    qro = SimpleNamespace(
        **{
            **vars(business.qro),
            "qro_id": "qro_m18_aggregate_second",
            "input_contract": dict(business.qro.input_contract),
            "output_contract": dict(business.qro.output_contract),
        }
    )
    command = SimpleNamespace(
        **{
            **vars(business.command),
            "command_id": "rgcmd_m18_aggregate_second",
            "payload": {"qro": qro},
        }
    )
    canonical = (
        f"research_graph_command:{command.command_id}",
        f"entrypoint:{business.entrypoint}",
    )
    ir = SimpleNamespace(
        **{
            **vars(business.ir),
            "ir_ref": "compiler_ir:m18:aggregate:second",
            "source_qro_refs": (qro.qro_id,),
            "graph_command_refs": (command.command_id,),
            "canonical_command_refs": canonical,
        }
    )
    compiler_pass = SimpleNamespace(
        **{
            **vars(business.compiler_pass),
            "pass_ref": "compiler_pass:m18:aggregate:second",
            "output_ir_ref": ir.ir_ref,
            "input_qro_refs": (qro.qro_id,),
            "graph_command_refs": (command.command_id,),
            "canonical_command_refs": canonical,
        }
    )
    coverage = SimpleNamespace(
        **{
            **vars(business.coverage),
            "coverage_ref": "goal_entrypoint_coverage:m18:business:second",
            "qro_refs": (qro.qro_id,),
            "research_graph_command_refs": (command.command_id,),
            "compiler_ir_refs": (ir.ir_ref,),
            "compiler_pass_refs": (compiler_pass.pass_ref,),
            "canonical_command_refs": canonical,
        }
    )
    business.graph.add(qro, command)
    business.compiler.add(ir, compiler_pass)
    business.entrypoints.records_value.append(coverage)


@pytest.mark.parametrize("cardinality", ("zero", "two"))
def test_m18_rejects_zero_or_multiple_canonical_ide_commands(
    cardinality: str,
) -> None:
    _business_row, context, check_ref, manifest, canonical_qro, _command = (
        _m18_system()
    )
    binding = context.canonical_spine_ledger.binding(
        "tib_m18_current",
        owner=OWNER,
    )
    if cardinality == "zero":
        binding.used_by = ("rgcmd_m18_same_owner_unrelated",)
    else:
        second_command = SimpleNamespace(
            command_id="rgcmd_m18_ide_code_second",
            source="ide",
            command_type="upsert_qro",
            actor=OWNER,
            payload={"qro": canonical_qro},
        )
        context.research_graph_store._commands.append(second_command)
        manifest.graph_refs = (*manifest.graph_refs, second_command.command_id)
        binding.used_by = (*binding.used_by, second_command.command_id)

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="canonical IDE code command",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


@pytest.mark.parametrize("cardinality", ("zero", "two"))
def test_m18_rejects_zero_or_multiple_post_evidence_attestations(
    cardinality: str,
) -> None:
    business, context, check_ref, _manifest, _canonical_qro, _command = (
        _m18_system()
    )
    if cardinality == "zero":
        business.qro.qro_type = "BacktestRun"
    else:
        _add_second_m18_attestation(business)

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="strict business QRO/Graph/compiler lineage",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


@pytest.mark.parametrize("foreign_record", ("canonical_source", "attestation"))
def test_m18_rejects_foreign_owner_lineage(foreign_record: str) -> None:
    business, context, check_ref, _manifest, canonical_qro, _command = (
        _m18_system()
    )
    if foreign_record == "canonical_source":
        canonical_qro.owner = OTHER_OWNER
    else:
        business.qro.owner = OTHER_OWNER

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing_tests", "unverified_residual", "attestation_inside_old_rdp"),
)
def test_m18_rejects_stale_rdp_or_temporal_cycle(mutation: str) -> None:
    business, context, check_ref, manifest, _canonical_qro, _command = (
        _m18_system()
    )
    if mutation == "missing_tests":
        manifest.test_refs = ()
    elif mutation == "unverified_residual":
        manifest.unverified_residuals = ("unverified:m18",)
    else:
        manifest.graph_refs = (*manifest.graph_refs, business.command.command_id)

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


@pytest.mark.parametrize("mutation", ("missing_qro_math", "recombined_ir_math"))
def test_m18_rejects_missing_or_recombined_attestation_math(mutation: str) -> None:
    business, context, check_ref, _manifest, _canonical_qro, _command = (
        _m18_system()
    )
    if mutation == "missing_qro_math":
        business.qro.mathematical_refs = ()
    else:
        business.ir.mathematical_spine_chain_refs = (
            "math_spine_chain:same-owner-unrelated",
        )

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="strict business QRO/Graph/compiler lineage",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


def test_m18_rejects_canonical_command_qro_code_recombination() -> None:
    _business_row, context, check_ref, _manifest, canonical_qro, _command = (
        _m18_system()
    )
    canonical_qro.input_contract["code_hash"] = "sha256:same-owner-unrelated"

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="stale or recombined",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


def test_m18_replay_is_stable_and_does_not_require_attestation_in_old_rdp() -> None:
    business, context, check_ref, manifest, _canonical_qro, _command = (
        _m18_system()
    )
    resolver = build_platform_source_lineage_policy_resolver_m16_m21(context)

    first = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M18",
        anchor_ref=check_ref,
    )
    second = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M18",
        anchor_ref=check_ref,
    )

    assert first == second
    assert business.command.command_id not in manifest.graph_refs


def test_m18_rejects_ambiguous_rdp_for_one_consistency_check() -> None:
    _business_row, context, check_ref, manifest, _canonical_qro, _command = (
        _m18_system()
    )
    context.rdp_store.manifests_value.append(
        SimpleNamespace(**{**vars(manifest), "package_id": "rdp_m18_other"})
    )

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="exactly one current record",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


def test_m18_rejects_missing_rdp_for_one_consistency_check() -> None:
    _business_row, context, check_ref, _manifest, _canonical_qro, _command = (
        _m18_system()
    )
    context.rdp_store.manifests_value.clear()

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="exactly one current record",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "non_pass_result",
        "recombined_consistency_check",
        "recombined_theory_binding",
    ),
)
def test_m18_rejects_non_pass_or_recombined_spine_sources(mutation: str) -> None:
    business, context, check_ref, _manifest, _canonical_qro, _command = (
        _m18_system()
    )
    if mutation == "non_pass_result":
        context.canonical_spine_ledger.check(check_ref, owner=OWNER).result = "checked"
    elif mutation == "recombined_consistency_check":
        business.chain.consistency_check_refs = ("cc_same_owner_unrelated",)
    else:
        business.chain.theory_binding_refs = ("tib_same_owner_unrelated",)

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=check_ref,
        )


def _m19_system():
    governed_ref = "governed_asset:teaching:m19"
    tutorial = SimpleNamespace(
        tutorial_asset_ref="tutorial_asset:m19-current",
        owner_user_id=OWNER,
        governed_asset_ref=governed_ref,
        category="tutorial",
        title="Evidence-first tutorial",
    )
    weakness = SimpleNamespace(
        weakness_disclosure_ref="weakness_disclosure:m19-current",
        owner_user_id=OWNER,
        tutorial_asset_ref=tutorial.tutorial_asset_ref,
        weakness_refs=("weakness:m19:small-sample",),
        visible_by_default=True,
    )
    evidence = SimpleNamespace(
        teaching_evidence_ref="teaching_evidence:m19-current",
        owner_user_id=OWNER,
        tutorial_asset_ref=tutorial.tutorial_asset_ref,
        weakness_disclosure_ref=weakness.weakness_disclosure_ref,
        evidence_refs=("evidence:m19:tutorial",),
    )
    bundle = SimpleNamespace(tutorial=tutorial, weakness=weakness, evidence=evidence)
    asset = SimpleNamespace(
        asset_ref=governed_ref,
        category="tutorial",
        mock_label_ref=None,
        asset_category_ref=None,
    )
    refs = {
        "tutorial_asset_ref": tutorial.tutorial_asset_ref,
        "weakness_disclosure_ref": weakness.weakness_disclosure_ref,
        "teaching_evidence_ref": evidence.teaching_evidence_ref,
    }
    business = _business(
        "M19",
        qro_type="DocumentArtifact",
        input_contract={**refs, "governed_asset_ref": governed_ref},
        output_contract={"weakness_visible": True},
        entrypoint="api:research_os.platform.business_attestations.m19",
    )
    _add_historical_business_head(
        business,
        entrypoint="api:research_os.teaching.assets",
    )

    class Teaching:
        def __init__(self, current_bundle: Any) -> None:
            self.bundle = current_bundle

        def tutorial_asset(self, ref, *, owner_user_id):
            if ref != self.bundle.tutorial.tutorial_asset_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return self.bundle.tutorial

        def bundles(self, *, owner_user_id):
            return (self.bundle,) if owner_user_id == OWNER else ()

    context = _context(
        business,
        lifecycle=_Lifecycle((asset,)),
        teaching=Teaching(bundle),
    )
    return business, context, refs


def test_m19_derives_visible_weakness_and_teaching_evidence_bundle() -> None:
    business, context, refs = _m19_system()

    result = build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
        owner_user_id=OWNER,
        m_row="M19",
        anchor_ref=refs["tutorial_asset_ref"],
    )

    assert _specific(result) == refs
    assert result.qro_ref == business.qro.qro_id
    assert result.primary_rag_asset_ref == "governed_asset:teaching:m19"
    assert result.business_entrypoint_ref == (
        "api:research_os.platform.business_attestations.m19"
    )
    _assert_business_metadata(result, business)
    _assert_post_business_metadata(result, business)
    assert dict(result.row_policy_metadata)[
        "historical_business_entrypoint_ref"
    ] == "api:research_os.teaching.assets"


def test_m19_rejects_hidden_current_weakness_disclosure() -> None:
    _business_row, context, refs = _m19_system()
    context.teaching_asset_registry.bundle.weakness.visible_by_default = False

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="stale or recombined",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M19",
            anchor_ref=refs["tutorial_asset_ref"],
        )


def _m20_system():
    halt_ref = "account_halt_m20_current"
    secret_ref = "secretref:llm:m20"
    call_id = "m20-current"
    gateway_ref = f"llm_gateway:{call_id}"
    account_ref = "account:m20"
    flat_proof_ref = "flat:m20"
    business = _business(
        "M20",
        qro_type="RiskPolicy",
        input_contract={
            "secret_ref": secret_ref,
            "llm_gateway_ref": gateway_ref,
            "kill_switch_ref": halt_ref,
        },
        output_contract={"status": "halted_security_controls_verified"},
        entrypoint="api:research_os.platform.business_attestations.m20",
        additional_evidence_refs=(call_id, account_ref, flat_proof_ref),
        validation_refs=(halt_ref, flat_proof_ref),
        chain_evidence_refs=(secret_ref, gateway_ref, flat_proof_ref),
        chain_validation_refs=(halt_ref, flat_proof_ref),
    )
    halt = SimpleNamespace(
        owner_user_id=OWNER,
        halt_ref=halt_ref,
        owner_state="halted",
        owner_epoch=3,
        account_binding_refs=(account_ref,),
        flat_proof_refs=(flat_proof_ref,),
    )
    terminal = SimpleNamespace(
        call_id=call_id,
        owner_user_id=OWNER,
        record_kind="terminal",
        status="ok",
        auth_ref=secret_ref,
    )
    secret = SimpleNamespace(secret_ref=secret_ref, status="active")

    class Halts:
        def __init__(self, current: Any) -> None:
            self.current = current
            self.mutation_calls = 0

        def halt_evidence(self, ref, *, owner_user_id):
            if ref != halt_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return self.current

        def begin_halt_many(self, *_args, **_kwargs):
            self.mutation_calls += 1
            raise AssertionError("policy must not trigger HALT")

        def finalize_halt_many(self, *_args, **_kwargs):
            self.mutation_calls += 1
            raise AssertionError("policy must not finalize HALT")

    class Calls:
        def __init__(self, current_terminal: Any) -> None:
            self.records = [current_terminal]

        def read_all(self, *, owner_user_id):
            return list(self.records) if owner_user_id == OWNER else []

    class Onboarding:
        record = secret

        def secret_ref(self, ref, *, owner_user_id):
            if ref != secret_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return self.record

    halts = Halts(halt)
    calls = Calls(terminal)
    context = _context(
        business,
        onboarding=Onboarding(),
        calls=calls,
        halts=halts,
    )
    return business, context, halt_ref, secret_ref, gateway_ref, halts, calls


def _direct_policy_case(row: str):
    if row == "M17":
        built = _m17_system()
        return built[0], built[1], built[2]["submission_ref"]
    if row == "M18":
        built = _m18_system()
        return built[0], built[1], built[2]
    if row == "M20":
        built = _m20_system()
        return built[0], built[1], built[2]
    raise AssertionError(row)


def _rekey_direct_attestation(business: _Business, *, command_ref: str) -> None:
    old_ref = business.command.command_id
    business.command.command_id = command_ref
    projection = business.graph._projections[business.qro.qro_id]
    projection.command_id = command_ref
    business.ir.graph_command_refs = (command_ref,)
    business.compiler_pass.graph_command_refs = (command_ref,)
    business.coverage.research_graph_command_refs = (command_ref,)
    canonical = tuple(
        (
            f"research_graph_command:{command_ref}"
            if ref == f"research_graph_command:{old_ref}"
            else ref
        )
        for ref in business.ir.canonical_command_refs
    )
    business.ir.canonical_command_refs = canonical
    business.compiler_pass.canonical_command_refs = canonical
    business.coverage.canonical_command_refs = canonical
    business.coverage.coverage_ref = goal_entrypoint_coverage_identity(
        entry_source=business.coverage.entry_source,
        entrypoint_ref=business.coverage.entrypoint_ref,
        goal_sections=business.coverage.goal_sections,
        qro_refs=business.coverage.qro_refs,
        research_graph_command_refs=(command_ref,),
        compiler_ir_refs=business.coverage.compiler_ir_refs,
        compiler_pass_refs=business.coverage.compiler_pass_refs,
    )


@pytest.mark.parametrize("row", ("M17", "M18", "M20"))
def test_direct_attestation_rejects_stale_non_current_graph_head(row: str) -> None:
    business, context, anchor = _direct_policy_case(row)
    business.graph._projections[business.qro.qro_id].command_id = (
        "rgcmd_same_owner_stale_head"
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M17", "M18", "M20"))
@pytest.mark.parametrize(
    "mutation",
    (
        "command_actor_source",
        "projection_actor_source",
        "command_tool_entrypoint",
        "compiler_actor_source",
        "compiler_tool_entrypoint",
    ),
)
def test_direct_attestation_rejects_wrong_actor_source_or_tool_entrypoint(
    row: str,
    mutation: str,
) -> None:
    business, context, anchor = _direct_policy_case(row)
    if mutation == "command_actor_source":
        business.command.actor_source = "agent"
    elif mutation == "projection_actor_source":
        business.graph._projections[business.qro.qro_id].actor_source = "agent"
    elif mutation == "command_tool_entrypoint":
        business.command.tool_record_refs = (
            "api:research_os.platform.business_attestations.same-owner-wrong",
        )
    elif mutation == "compiler_actor_source":
        business.compiler_pass.actor_source = "agent"
    else:
        business.compiler_pass.tool_record_refs = (
            "api:research_os.platform.business_attestations.same-owner-wrong",
            anchor,
            business.chain.chain_ref,
        )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M17", "M18", "M20"))
def test_direct_attestation_rejects_self_consistent_wrong_goal_sections(
    row: str,
) -> None:
    business, context, anchor = _direct_policy_case(row)
    business.coverage.goal_sections = ("§1",)
    business.coverage.coverage_ref = goal_entrypoint_coverage_identity(
        entry_source=business.coverage.entry_source,
        entrypoint_ref=business.coverage.entrypoint_ref,
        goal_sections=business.coverage.goal_sections,
        qro_refs=business.coverage.qro_refs,
        research_graph_command_refs=business.coverage.research_graph_command_refs,
        compiler_ir_refs=business.coverage.compiler_ir_refs,
        compiler_pass_refs=business.coverage.compiler_pass_refs,
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M17", "M18", "M20"))
def test_direct_attestation_rejects_structurally_rekeyed_command(row: str) -> None:
    business, context, anchor = _direct_policy_case(row)
    _rekey_direct_attestation(
        business,
        command_ref=f"rgcmd_{row.lower()}_same_owner_forged",
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M17", "M18", "M20"))
def test_direct_attestation_rejects_second_owner_entrypoint_command(
    row: str,
) -> None:
    business, context, anchor = _direct_policy_case(row)
    business.graph._commands.append(
        SimpleNamespace(
            command_id=f"rgcmd_{row.lower()}_same_owner_stale",
            actor=OWNER,
            actor_source="user_manual",
            source="api",
            command_type="upsert_qro",
            payload={"qro": business.qro},
            evidence_refs=business.command.evidence_refs,
            tool_record_refs=(business.entrypoint, "tool:same-owner-extra"),
        )
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M17", "M18", "M20"))
def test_direct_attestation_rejects_recombined_command_evidence(row: str) -> None:
    business, context, anchor = _direct_policy_case(row)
    business.command.evidence_refs = (
        *business.command.evidence_refs,
        "evidence:same-owner-unrelated",
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("mutation", ("missing", "multiple"))
def test_m18_direct_attestation_requires_exactly_one_validation_receipt(
    mutation: str,
) -> None:
    business, context, anchor = _direct_policy_case("M18")
    current = tuple(business.ir.validation_refs)
    receipts = tuple(
        ref for ref in current if ref.startswith("goal_validation_receipt:")
    )
    assert len(receipts) == 1
    if mutation == "missing":
        mutated = tuple(ref for ref in current if ref != receipts[0])
    else:
        mutated = (*current, "goal_validation_receipt:m18:second")
    business.ir.validation_refs = mutated
    business.compiler_pass.validation_refs = mutated
    business.coverage.validation_refs = mutated

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="strict business QRO/Graph/compiler lineage",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=anchor,
        )


def test_m18_direct_attestation_rejects_domain_validation_refs() -> None:
    business, context, anchor = _direct_policy_case("M18")
    current = tuple(business.ir.validation_refs)
    domain = tuple(
        ref for ref in current if not ref.startswith("goal_validation_receipt:")
    )
    assert domain == ()
    mutated = ("validation:m18:same-owner-unrelated", *current)
    business.ir.validation_refs = mutated
    business.compiler_pass.validation_refs = mutated
    business.coverage.validation_refs = mutated

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="semantic validation evidence is stale or recombined",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=anchor,
        )


def test_m18_direct_attestation_rejects_divergent_compiler_evidence() -> None:
    business, context, anchor = _direct_policy_case("M18")
    business.compiler_pass.evidence_refs = (
        "entrypoint_evidence:m18:divergent",
    )

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="strict business QRO/Graph/compiler lineage",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=anchor,
        )


def test_m18_direct_attestation_rejects_mutated_semantic_evidence() -> None:
    business, context, anchor = _direct_policy_case("M18")
    mutated = (*business.qro.evidence_refs, "evidence:m18:same-owner-unrelated")
    business.qro.evidence_refs = mutated
    business.command.evidence_refs = mutated
    business.graph._projections[business.qro.qro_id].evidence_refs = mutated

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="semantic attestation evidence is stale or recombined",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=anchor,
        )


def test_m18_policy_ignores_its_derived_section_14_coverage() -> None:
    business, context, anchor = _direct_policy_case("M18")
    derived = SimpleNamespace(
        **{
            **vars(business.coverage),
            "goal_sections": ("§14",),
            "coverage_ref": goal_entrypoint_coverage_identity(
                entry_source=business.coverage.entry_source,
                entrypoint_ref=business.coverage.entrypoint_ref,
                goal_sections=("§14",),
                qro_refs=business.coverage.qro_refs,
                research_graph_command_refs=(business.command.command_id,),
                compiler_ir_refs=business.coverage.compiler_ir_refs,
                compiler_pass_refs=business.coverage.compiler_pass_refs,
            ),
        }
    )
    business.entrypoints.records_value.append(derived)

    resolution = build_platform_source_lineage_policy_resolver_m16_m21(
        context
    ).resolve(
        owner_user_id=OWNER,
        m_row="M18",
        anchor_ref=anchor,
    )

    assert resolution.qro_ref == business.qro.qro_id


@pytest.mark.parametrize(
    ("proof_kind", "state"),
    (
        ("receipt", "foreign"),
        ("receipt", "stale"),
        ("evidence", "foreign"),
        ("evidence", "stale"),
    ),
)
def test_m18_direct_attestation_does_not_trust_proof_prefixes_without_backing(
    proof_kind: str,
    state: str,
) -> None:
    business, context, anchor = _direct_policy_case("M18")
    if proof_kind == "receipt":
        current = tuple(business.ir.validation_refs)
        original = next(
            ref for ref in current if ref.startswith("goal_validation_receipt:")
        )
        untrusted = f"goal_validation_receipt:m18:{state}"
        mutated = tuple(untrusted if ref == original else ref for ref in current)
        business.ir.validation_refs = mutated
        business.compiler_pass.validation_refs = mutated
        business.coverage.validation_refs = mutated
    else:
        untrusted = f"entrypoint_evidence:m18:{state}"
        mutated = (untrusted,)
        business.ir.evidence_refs = mutated
        business.compiler_pass.evidence_refs = mutated
        business.coverage.evidence_refs = mutated
    business.entrypoints.rejected_proof_refs.add(untrusted)

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="strict business QRO/Graph/compiler lineage",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M18",
            anchor_ref=anchor,
        )
    assert business.entrypoints.validation_calls == (
        [business.coverage.coverage_ref]
    )


@pytest.mark.parametrize("mutation", ("policy_ref", "same_owner_swap"))
def test_m17_rejects_recombined_current_order_intent(mutation: str) -> None:
    _business_row, context, refs, _reservation = _m17_system()
    intents = context.execution_order_intent_registry
    if mutation == "policy_ref":
        intents.current = SimpleNamespace(
            **{
                **vars(intents.current),
                "risk_policy_ref": "copy_risk_check_same-owner-unrelated",
            }
        )
    else:
        swapped_ref = "order_intent_" + content_hash("same-owner-swapped")
        intents.current = SimpleNamespace(
            **{**vars(intents.current), "order_intent_ref": swapped_ref}
        )
        context.execution_order_submission_registry.current.order_intent_ref = (
            swapped_ref
        )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=refs["submission_ref"],
        )


@pytest.mark.parametrize(
    "mutation",
    ("missing_gateway_evidence", "missing_halt_validation", "missing_flat_proof"),
)
def test_m20_rejects_chain_not_bound_to_row_evidence(mutation: str) -> None:
    business, context, halt_ref, _secret_ref, gateway_ref, _halts, _calls = (
        _m20_system()
    )
    if mutation == "missing_gateway_evidence":
        business.chain.evidence_refs = tuple(
            ref for ref in business.chain.evidence_refs if ref != gateway_ref
        )
    elif mutation == "missing_halt_validation":
        business.chain.validation_refs = tuple(
            ref for ref in business.chain.validation_refs if ref != halt_ref
        )
    else:
        business.chain.evidence_refs = tuple(
            ref for ref in business.chain.evidence_refs if ref != "flat:m20"
        )
        business.chain.validation_refs = tuple(
            ref for ref in business.chain.validation_refs if ref != "flat:m20"
        )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M20",
            anchor_ref=halt_ref,
        )


def test_m20_only_consumes_preexisting_terminal_halt_and_gateway_evidence() -> None:
    business, context, halt_ref, secret_ref, gateway_ref, halts, _calls = _m20_system()

    result = build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
        owner_user_id=OWNER,
        m_row="M20",
        anchor_ref=halt_ref,
    )

    assert _specific(result) == {
        "secret_ref": secret_ref,
        "llm_gateway_ref": gateway_ref,
        "kill_switch_ref": halt_ref,
    }
    assert result.qro_ref == business.qro.qro_id
    assert result.business_entrypoint_ref == (
        "api:research_os.platform.business_attestations.m20"
    )
    assert halts.mutation_calls == 0
    _assert_business_metadata(result, business)


def test_m20_rejects_same_owner_terminal_call_using_other_secret() -> None:
    _business_row, context, halt_ref, _secret_ref, _gateway_ref, halts, calls = _m20_system()
    calls.records[0].auth_ref = "secretref:llm:same-owner-other"

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="exactly one current record",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M20",
            anchor_ref=halt_ref,
        )
    assert halts.mutation_calls == 0


@pytest.mark.parametrize("cardinality", ("zero", "two"))
def test_m20_rejects_zero_or_multiple_owner_api_attestations(
    cardinality: str,
) -> None:
    business, context, halt_ref, _secret_ref, _gateway_ref, halts, _calls = (
        _m20_system()
    )
    if cardinality == "zero":
        business.qro.qro_type = "ExecutionPolicy"
    else:
        _add_duplicate_business_attestation(business, suffix="second")

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="exactly one current record",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M20",
            anchor_ref=halt_ref,
        )
    assert halts.mutation_calls == 0


@pytest.mark.parametrize(
    "contract_key",
    ("secret_ref", "llm_gateway_ref", "kill_switch_ref"),
)
def test_m20_rejects_recombined_owner_attestation_contract(
    contract_key: str,
) -> None:
    business, context, halt_ref, _secret_ref, _gateway_ref, halts, _calls = (
        _m20_system()
    )
    business.qro.input_contract[contract_key] = f"{contract_key}:same-owner-unrelated"

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="exactly one current record",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M20",
            anchor_ref=halt_ref,
        )
    assert halts.mutation_calls == 0


@pytest.mark.parametrize(
    "mutation",
    (
        "foreign_terminal",
        "foreign_halt",
        "foreign_attestation",
        "stale_halt",
        "stale_secret",
        "revoked_secret",
    ),
)
def test_m20_rejects_foreign_or_stale_post_state_sources(mutation: str) -> None:
    business, context, halt_ref, _secret_ref, _gateway_ref, halts, calls = (
        _m20_system()
    )
    if mutation == "foreign_terminal":
        calls.records[0].owner_user_id = OTHER_OWNER
    elif mutation == "foreign_halt":
        halts.current.owner_user_id = OTHER_OWNER
    elif mutation == "foreign_attestation":
        business.qro.owner = OTHER_OWNER
    elif mutation == "stale_halt":
        halts.current.owner_state = "halting"
    elif mutation == "stale_secret":
        context.onboarding_registry.record.status = "stale"
    else:
        context.onboarding_registry.record.status = "revoked"

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M20",
            anchor_ref=halt_ref,
        )
    assert halts.mutation_calls == 0


@pytest.mark.parametrize(
    "system_builder,row,anchor_getter",
    (
        (_m17_system, "M17", lambda value: value[2]["submission_ref"]),
        (_m20_system, "M20", lambda value: value[2]),
    ),
)
@pytest.mark.parametrize("cardinality", ("zero", "two"))
def test_m17_m20_reject_qro_math_chain_cardinality_other_than_one(
    system_builder,
    row: str,
    anchor_getter,
    cardinality: str,
) -> None:
    built = system_builder()
    business = built[0]
    context = built[1]
    anchor = anchor_getter(built)
    business.qro.mathematical_refs = (
        ()
        if cardinality == "zero"
        else (business.chain.chain_ref, "math_spine_chain:same-owner-unrelated")
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


class _M21IDEStrategyLoader:
    def __init__(self, *strategies: StrategyFile) -> None:
        self.rows = {
            f"ide_strategy:{strategy.strategy_id}": strategy
            for strategy in strategies
        }

    def __call__(self, ref: str, owner: str) -> StrategyFile:
        if owner != OWNER or ref not in self.rows:
            raise KeyError(ref)
        return self.rows[ref]

    def add(self, strategy: StrategyFile) -> None:
        self.rows[f"ide_strategy:{strategy.strategy_id}"] = strategy


def _m21_system(
    *,
    variant: str = "",
    asset: GovernedAssetRecord | None = None,
    anchor_ref: str = "",
    legacy: bool = False,
    input_extra: dict[str, Any] | None = None,
    output_extra: dict[str, Any] | None = None,
    status: str = "template_fork_recorded",
):
    asset = asset or GovernedAssetRecord(
        asset_ref="governed_asset:template:m21",
        asset_type="StrategyTemplate",
        category=AssetCategory.TEMPLATE,
        lifecycle_state=LifecycleState.LINKED,
        evidence_refs=("evidence:m21:template",),
        validation_plan_ref="validation_plan:m21:template",
        promotion_history=(),
        display_label="TEMPLATE - candidate context only",
        mock_label_ref="mock_label:template:m21",
        asset_category_ref="asset_category:template:m21",
    )
    strategy_token = variant or "current"
    ide_strategy_ref = anchor_ref or f"ide_strategy:strategy-m21-{strategy_token}"
    strategy = StrategyFile(
        strategy_id=ide_strategy_ref.removeprefix("ide_strategy:"),
        owner_username="platform_policy_m21_owner",
        name=(
            "m21_" + ide_strategy_ref.removeprefix("ide_strategy:").replace("-", "_")
        ),
        code="def generate_signal(ctx):\n    return 0\n",
        asset_class="template",
        description="forked from the governed M21 template",
        updated_at_utc="2026-07-13T00:00:00Z",
        market_data_use_validation_refs=[],
    )
    refs = {
        "mock_label_ref": asset.mock_label_ref,
        "asset_category_ref": asset.asset_category_ref,
    }
    input_contract = (
        {"entry_source": "api", "asset_ref": asset.asset_ref}
        if legacy
        else {
            "entry_source": "api",
            "governed_asset_ref": asset.asset_ref,
        }
    )
    input_contract.update(input_extra or {})
    output_contract = {
        "ide_strategy_ref": ide_strategy_ref,
        **(
            {}
            if legacy
            else {
                "ide_strategy_snapshot_hash": (
                    m21_ide_strategy_snapshot_hash(strategy)
                ),
                "governed_template_snapshot_hash": (
                    m21_governed_template_snapshot_hash(asset)
                ),
            }
        ),
        **refs,
        "status": status,
    }
    output_contract.update(output_extra or {})
    business = _business(
        "M21",
        qro_type="StrategyBook",
        input_contract=input_contract,
        output_contract=output_contract,
        entrypoint="api:research_os.platform.business_attestations.m21",
        variant=variant,
    )
    _add_historical_business_head(
        business,
        entrypoint="api:strategies.templates.fork_to_ide",
        variant=variant,
    )
    ide_strategies = _M21IDEStrategyLoader(strategy)
    business.ide_strategy = strategy
    business.ide_strategies = ide_strategies
    context = _context(
        business,
        lifecycle=_Lifecycle((asset,)),
        ide_strategy_loader=ide_strategies,
    )
    return business, context, asset, refs


def _m21_anchor(business: _Business) -> str:
    if "governed_asset_ref" in business.qro.input_contract:
        return str(business.qro.output_contract["ide_strategy_ref"])
    return str(business.qro.input_contract["asset_ref"])


def test_m21_derives_both_labels_from_one_current_governed_asset() -> None:
    business, context, asset, refs = _m21_system()
    anchor = _m21_anchor(business)

    result = build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
        owner_user_id=OWNER,
        m_row="M21",
        anchor_ref=anchor,
    )

    assert _specific(result) == refs
    assert result.anchor_ref == anchor
    assert result.lifecycle_ref == asset.asset_ref
    assert result.primary_rag_asset_ref == asset.asset_ref
    assert result.qro_ref == business.qro.qro_id
    assert result.business_entrypoint_ref == (
        "api:research_os.platform.business_attestations.m21"
    )
    _assert_business_metadata(result, business)
    _assert_post_business_metadata(result, business)
    assert dict(result.row_policy_metadata)[
        "historical_business_entrypoint_ref"
    ] == "api:strategies.templates.fork_to_ide"


def test_m21_rejects_same_owner_recombined_category_label() -> None:
    business, context, asset, _refs = _m21_system()
    context.asset_lifecycle_registry.assets[asset.asset_ref] = replace(
        asset,
        asset_category_ref="asset_category:template:same-owner-other",
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M21",
            anchor_ref=_m21_anchor(business),
        )


def _merge_business_lineage(target: _Business, source: _Business) -> None:
    target.graph.add(source.qro, source.command)
    target.graph.add_history(source.historical_command)
    target.compiler.add(source.ir, source.compiler_pass)
    target.compiler.add(
        source.historical_ir,
        source.historical_compiler_pass,
    )
    target.entrypoints.records_value.extend(
        (source.coverage, source.historical_coverage)
    )
    target.spine.add(source.chain)
    target.ide_strategies.add(source.ide_strategy)


def test_m21_two_fork_anchors_share_one_template_without_global_ambiguity() -> None:
    first, context, asset, _refs = _m21_system(variant="first")
    second, _second_context, _asset, _second_refs = _m21_system(
        variant="second",
        asset=asset,
    )
    _merge_business_lineage(first, second)
    first_anchor = _m21_anchor(first)
    second_anchor = _m21_anchor(second)
    assert first_anchor != second_anchor
    resolver = build_platform_source_lineage_policy_resolver_m16_m21(context)

    first_resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M21",
        anchor_ref=first_anchor,
    )
    second_resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M21",
        anchor_ref=second_anchor,
    )

    assert first_resolution.qro_ref == first.qro.qro_id
    assert second_resolution.qro_ref == second.qro.qro_id
    assert first_resolution.lifecycle_ref == asset.asset_ref
    assert second_resolution.lifecycle_ref == asset.asset_ref
    assert first_resolution.primary_rag_asset_ref == asset.asset_ref
    assert second_resolution.primary_rag_asset_ref == asset.asset_ref
    assert len(first.graph.commands()) == 4
    assert len(first.compiler.irs(owner=OWNER)) == 4
    assert len(first.compiler.passes(owner=OWNER)) == 4
    assert len(first.entrypoints.records(owner=OWNER)) == 4

    duplicate, _duplicate_context, _asset, _duplicate_refs = _m21_system(
        variant="same_anchor_duplicate",
        asset=asset,
        anchor_ref=first_anchor,
    )
    _merge_business_lineage(first, duplicate)

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="exactly one current record",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M21",
            anchor_ref=first_anchor,
        )


def test_m21_legacy_template_anchor_history_remains_readable() -> None:
    business, context, asset, refs = _m21_system(
        variant="legacy",
        legacy=True,
    )

    result = build_platform_source_lineage_policy_resolver_m16_m21(
        context
    ).resolve(
        owner_user_id=OWNER,
        m_row="M21",
        anchor_ref=asset.asset_ref,
    )

    assert _specific(result) == refs
    assert result.anchor_ref == asset.asset_ref
    assert result.lifecycle_ref == asset.asset_ref
    assert result.primary_rag_asset_ref == asset.asset_ref
    assert result.qro_ref == business.qro.qro_id


@pytest.mark.parametrize(
    ("legacy", "input_extra", "output_extra", "status"),
    (
        (False, {"entry_source": "ide"}, None, "template_fork_recorded"),
        (False, {"unexpected": "poison"}, None, "template_fork_recorded"),
        (False, None, {"unexpected": "poison"}, "template_fork_recorded"),
        (False, None, None, "recorded"),
        (True, {"unexpected": "poison"}, None, "template_fork_recorded"),
        (True, None, {"unexpected": "poison"}, "template_fork_recorded"),
        (True, None, None, "recorded"),
    ),
)
def test_m21_rejects_non_exact_current_and_legacy_contracts(
    legacy: bool,
    input_extra: dict[str, Any] | None,
    output_extra: dict[str, Any] | None,
    status: str,
) -> None:
    business, context, asset, _refs = _m21_system(
        variant="poison",
        legacy=legacy,
        input_extra=input_extra,
        output_extra=output_extra,
        status=status,
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M21",
            anchor_ref=(asset.asset_ref if legacy else _m21_anchor(business)),
        )


@pytest.mark.parametrize(
    ("mutation", "strategy_changes"),
    (
        ("deleted", None),
        ("name", {"name": "m21_mutated_name"}),
        ("code", {"code": "def generate_signal(ctx):\n    return 1\n"}),
        ("description", {"description": "mutated after history"}),
        (
            "market_data_use_validation_refs",
            {"market_data_use_validation_refs": ["validation:mutated"]},
        ),
    ),
)
def test_m21_rejects_deleted_or_mutated_current_ide_strategy(
    mutation: str,
    strategy_changes: dict[str, Any] | None,
) -> None:
    business, context, _asset, _refs = _m21_system(variant=mutation)
    anchor = _m21_anchor(business)
    if strategy_changes is None:
        business.ide_strategies.rows.pop(anchor)
    else:
        business.ide_strategies.rows[anchor] = replace(
            business.ide_strategy,
            **strategy_changes,
        )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M21",
            anchor_ref=anchor,
        )


def test_m21_rejects_mutated_governed_template_snapshot() -> None:
    business, context, asset, _refs = _m21_system(
        variant="template_snapshot_mutated"
    )
    context.asset_lifecycle_registry.assets[asset.asset_ref] = replace(
        asset,
        display_label="TEMPLATE - mutated after history",
    )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row="M21",
            anchor_ref=_m21_anchor(business),
        )


@pytest.mark.parametrize(
    "system_builder,row,anchor_getter,error_pattern",
    (
        (
            _m17_system,
            "M17",
            lambda value: value[2]["submission_ref"],
            "strict business QRO/Graph/compiler lineage",
        ),
        (
            _m18_system,
            "M18",
            lambda value: value[2],
            "strict business QRO/Graph/compiler lineage",
        ),
        (
            _m19_system,
            "M19",
            lambda value: value[2]["tutorial_asset_ref"],
            "strict business QRO/Graph/compiler lineage",
        ),
        (
            _m20_system,
            "M20",
            lambda value: value[2],
            "exactly one current record",
        ),
        (
            _m21_system,
            "M21",
            lambda value: _m21_anchor(value[0]),
            "strict business QRO/Graph/compiler lineage",
        ),
    ),
)
def test_exact_math_and_compiler_chain_binding_is_mandatory(
    system_builder,
    row: str,
    anchor_getter,
    error_pattern: str,
) -> None:
    built = system_builder()
    business = built[0]
    context = built[1]
    anchor = anchor_getter(built)
    business.ir.mathematical_spine_chain_refs = (
        "math_spine_chain:same-owner-unrelated",
    )

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match=error_pattern,
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


def test_m21_unrelated_fresh_view_coverage_does_not_create_global_ambiguity() -> None:
    business, context, asset, _refs = _m21_system()
    anchor = _m21_anchor(business)
    stale_primary = business.entrypoints
    fresh = _Entrypoints(
        [business.coverage, business.historical_coverage]
    )
    context = replace(context, entrypoint_view_factory=lambda: fresh)
    resolver = build_platform_source_lineage_policy_resolver_m16_m21(context)

    assert resolver.resolve(
        owner_user_id=OWNER,
        m_row="M21",
        anchor_ref=anchor,
    ).qro_ref == business.qro.qro_id

    duplicate = SimpleNamespace(
        **{
            **vars(business.coverage),
            "coverage_ref": "goal_entrypoint_coverage:m21:ambiguous",
            "goal_sections": ("§2",),
        }
    )
    fresh.records_value.append(duplicate)
    assert len(stale_primary.records(owner=OWNER)) == 2

    assert resolver.resolve(
        owner_user_id=OWNER,
        m_row="M21",
        anchor_ref=anchor,
    ).qro_ref == business.qro.qro_id


def test_owner_isolation_and_semantic_revalidation_fail_closed() -> None:
    business, context, asset, refs = _m21_system()
    anchor = _m21_anchor(business)
    resolver = build_platform_source_lineage_policy_resolver_m16_m21(context)
    resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M21",
        anchor_ref=anchor,
    )
    capability = PlatformCapabilityRecord(
        m_row="M21",
        qro_ref=resolution.qro_ref,
        research_graph_ref=business.command.command_id,
        lifecycle_ref=resolution.lifecycle_ref,
        governance_ref="goal_validation_receipt:m21",
        rag_ref="rag:m21",
        math_spine_ref=resolution.math_spine_ref,
        evidence_refs=("evidence:m21",),
        specific_refs=tuple(
            PlatformSpecificRef(key, ref) for key, ref in refs.items()
        ),
    )
    rag = SimpleNamespace(
        asset_ref=asset.asset_ref,
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(asset.asset_ref,),
        ),
    )

    assert resolver.semantic_violations(
        resolution,
        owner_user_id=OWNER,
        business_coverage=business.coverage,
        capability_record=capability,
        rag_document=rag,
    ) == ()
    assert "specific refs mismatch" in " ".join(
        resolver.semantic_violations(
            resolution,
            owner_user_id=OWNER,
            business_coverage=business.coverage,
            capability_record=replace(
                capability,
                specific_refs=(
                    PlatformSpecificRef("mock_label_ref", refs["mock_label_ref"]),
                    PlatformSpecificRef(
                        "asset_category_ref",
                        "asset_category:template:same-owner-other",
                    ),
                ),
            ),
            rag_document=rag,
        )
    )
    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        resolver.resolve(
            owner_user_id=OTHER_OWNER,
            m_row="M21",
            anchor_ref=anchor,
        )


def _post_business_case(row: str, tmp_path):
    if row == "M16":
        business, context, refs = _m16_system(tmp_path)
        return business, context, refs["shared_asset_ref"]
    if row == "M19":
        business, context, refs = _m19_system()
        return business, context, refs["tutorial_asset_ref"]
    if row == "M21":
        business, context, _asset, _refs = _m21_system()
        return business, context, _m21_anchor(business)
    raise AssertionError(row)


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_post_business_historical_then_binding_resolves_from_fresh_views(
    row: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    compiler_calls = 0

    def fresh_compiler():
        nonlocal compiler_calls
        compiler_calls += 1
        return business.compiler

    context = replace(
        context,
        compiler_view_factory=fresh_compiler,
        entrypoint_view_factory=lambda: business.entrypoints,
    )
    result = build_platform_source_lineage_policy_resolver_m16_m21(
        context
    ).resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=anchor,
    )

    assert compiler_calls >= 2
    assert result.qro_ref == business.qro.qro_id
    assert business.historical_qro.mathematical_refs == ()
    assert business.command.evidence_refs == (
        business.chain.chain_ref,
        business.historical_command.command_id,
    )
    assert business.command.actor_source == "user_manual"
    assert business.command.tool_record_refs == (business.entrypoint,)
    assert business.coverage.goal_sections == POST_BINDING_GOAL_SECTIONS[row]


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "mutation",
    (
        "command_actor_source",
        "projection_actor_source",
        "compiler_actor_source",
        "wrong_command_tool",
        "extra_command_tool",
        "wrong_command_evidence",
        "wrong_compiler_input_ir",
        "wrong_compiler_tool",
        "wrong_goal_sections",
        "second_entrypoint_command",
    ),
)
def test_post_business_binding_rejects_non_production_current_shape(
    row: str,
    mutation: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    if mutation == "command_actor_source":
        business.command.actor_source = "agent"
    elif mutation == "projection_actor_source":
        business.graph._projections[business.qro.qro_id].actor_source = "agent"
    elif mutation == "compiler_actor_source":
        business.compiler_pass.actor_source = "agent"
    elif mutation == "wrong_command_tool":
        business.command.tool_record_refs = (
            "api:research_os.platform.business_attestations.same-owner-wrong",
        )
    elif mutation == "extra_command_tool":
        business.command.tool_record_refs = (
            business.entrypoint,
            "tool:same-owner-extra",
        )
    elif mutation == "wrong_command_evidence":
        business.command.evidence_refs = (
            business.chain.chain_ref,
            "rgcmd_same-owner-unrelated-history",
        )
    elif mutation == "wrong_compiler_input_ir":
        business.compiler_pass.input_ir_refs = (
            business.compiler_pass.output_ir_ref,
        )
    elif mutation == "wrong_compiler_tool":
        business.compiler_pass.tool_record_refs = (
            business.entrypoint,
            anchor,
            business.chain.chain_ref,
        )
    elif mutation == "wrong_goal_sections":
        business.coverage.goal_sections = ("§1",)
        business.coverage.coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=business.coverage.entry_source,
            entrypoint_ref=business.coverage.entrypoint_ref,
            goal_sections=business.coverage.goal_sections,
            qro_refs=business.coverage.qro_refs,
            research_graph_command_refs=(business.command.command_id,),
            compiler_ir_refs=business.coverage.compiler_ir_refs,
            compiler_pass_refs=business.coverage.compiler_pass_refs,
        )
    else:
        business.graph._commands.append(
            SimpleNamespace(
                command_id=f"rgcmd_{row.lower()}_same-owner-second-binding",
                source="api",
                command_type="upsert_qro",
                actor_source="user_manual",
                actor=OWNER,
                payload={"qro": business.qro},
                evidence_refs=(
                    business.chain.chain_ref,
                    business.historical_command.command_id,
                ),
                tool_record_refs=(business.entrypoint,),
            )
        )

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


def _append_duplicate_historical_business_head(
    business: _Business,
    *,
    suffix: str,
) -> None:
    historical_qro = SimpleNamespace(
        **{
            **vars(business.historical_qro),
            "input_contract": dict(business.historical_qro.input_contract),
            "output_contract": dict(business.historical_qro.output_contract),
        }
    )
    command = SimpleNamespace(
        command_id=f"{business.historical_command.command_id}:{suffix}",
        source="api",
        command_type="upsert_qro",
        actor=OWNER,
        payload={"qro": historical_qro},
    )
    historical_entrypoint = next(
        ref
        for ref in business.historical_ir.canonical_command_refs
        if ref.startswith("entrypoint:")
    )
    canonical = (
        f"research_graph_command:{command.command_id}",
        historical_entrypoint,
    )
    compiler_ir = SimpleNamespace(
        ir_ref=f"{business.historical_ir.ir_ref}:{suffix}",
        source_qro_refs=(historical_qro.qro_id,),
        graph_command_refs=(command.command_id,),
        mathematical_spine_chain_refs=(),
        canonical_command_refs=canonical,
        owner=OWNER,
    )
    compiler_pass = SimpleNamespace(
        pass_ref=f"{business.historical_compiler_pass.pass_ref}:{suffix}",
        output_ir_ref=compiler_ir.ir_ref,
        input_qro_refs=(historical_qro.qro_id,),
        graph_command_refs=(command.command_id,),
        canonical_command_refs=canonical,
        actor=OWNER,
        entry_source="api",
        status="compiled",
    )
    goal_sections = ("§1",)
    qro_refs = (historical_qro.qro_id,)
    graph_refs = (command.command_id,)
    ir_refs = (compiler_ir.ir_ref,)
    pass_refs = (compiler_pass.pass_ref,)
    entrypoint = historical_entrypoint.removeprefix("entrypoint:")
    coverage = SimpleNamespace(
        coverage_ref=goal_entrypoint_coverage_identity(
            entry_source="api",
            entrypoint_ref=entrypoint,
            goal_sections=goal_sections,
            qro_refs=qro_refs,
            research_graph_command_refs=graph_refs,
            compiler_ir_refs=ir_refs,
            compiler_pass_refs=pass_refs,
        ),
        recorded_by=OWNER,
        goal_sections=goal_sections,
        entry_source="api",
        entrypoint_ref=entrypoint,
        qro_refs=qro_refs,
        research_graph_command_refs=graph_refs,
        compiler_ir_refs=ir_refs,
        compiler_pass_refs=pass_refs,
        canonical_command_refs=canonical,
        evidence_refs=(f"evidence:{business.row.lower()}:{suffix}",),
        validation_refs=(f"goal_validation_receipt:{business.row.lower()}:{suffix}",),
        permission_refs=(f"permission:{business.row.lower()}:{suffix}",),
        replay_refs=(
            f"replay:research_graph:{command.command_id}",
            f"replay:compiler_ir:{compiler_ir.ir_ref}",
            f"replay:compiler_pass:{compiler_pass.pass_ref}",
        ),
        claims_full_product_entrypoint=False,
        silent_mock_fallback_used=False,
        raw_payload_persisted=False,
    )
    business.graph.add_history(command)
    business.compiler.add(compiler_ir, compiler_pass)
    business.entrypoints.records_value.append(coverage)


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "coverage_mutation",
    (
        "empty_sections",
        "section_14",
        "business_entrypoint",
        "wrong_canonical_entrypoint",
        "unbacked",
    ),
)
def test_post_business_attestation_requires_strict_non_section_14_coverage(
    row: str,
    coverage_mutation: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    if coverage_mutation == "empty_sections":
        business.coverage.goal_sections = ()
    elif coverage_mutation == "section_14":
        business.coverage.goal_sections = ("§1", "§14")
    elif coverage_mutation == "business_entrypoint":
        business.coverage.entrypoint_ref = next(
            ref.removeprefix("entrypoint:")
            for ref in business.historical_ir.canonical_command_refs
            if ref.startswith("entrypoint:")
        )
    elif coverage_mutation == "wrong_canonical_entrypoint":
        canonical = tuple(
            "entrypoint:api:research_os.platform.business_attestations.wrong"
            if ref.startswith("entrypoint:")
            else ref
            for ref in business.ir.canonical_command_refs
        )
        business.ir.canonical_command_refs = canonical
        business.compiler_pass.canonical_command_refs = canonical
        business.coverage.canonical_command_refs = canonical
    else:
        business.entrypoints.accepted = False

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="strict business QRO/Graph/compiler lineage",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "coverage_mutation",
    (
        "empty_sections",
        "section_14",
        "wrong_graph",
        "wrong_compiler",
        "identity_mismatch",
        "placeholder_evidence",
        "ambiguous",
    ),
)
def test_post_business_attestation_requires_strict_historical_business_coverage(
    row: str,
    coverage_mutation: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    coverage = business.historical_coverage
    if coverage_mutation == "empty_sections":
        coverage.goal_sections = ()
    elif coverage_mutation == "section_14":
        coverage.goal_sections = ("§1", "§14")
    elif coverage_mutation == "wrong_graph":
        coverage.research_graph_command_refs = (business.command.command_id,)
    elif coverage_mutation == "wrong_compiler":
        coverage.compiler_ir_refs = (business.ir.ir_ref,)
    elif coverage_mutation == "identity_mismatch":
        coverage.coverage_ref = f"{coverage.coverage_ref}:recombined"
    elif coverage_mutation == "placeholder_evidence":
        coverage.evidence_refs = ("goal_closure:synthetic",)
    else:
        duplicate = SimpleNamespace(**vars(coverage))
        business.entrypoints.records_value.append(duplicate)

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="historical",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_historical_coverage_is_structural_after_same_qro_current_binding(
    row: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    real_resolver = RealRefResolver(
        research_graph_store=business.graph,
        lifecycle_registry=_Unavailable(),
        governance_registry=_Unavailable(),
        rag_index=_Unavailable(),
        spine_chain_registry=business.spine,
        compiler_store=business.compiler,
        owner=OWNER,
    )

    real_violations = real_resolver.entrypoint_linkage_violations(
        business.historical_coverage
    )
    assert any(
        reason
        == "graph command QRO payload is stale or differs from current store state"
        for _field, _ref, reason in real_violations
    )

    # A same-id post-business math binding intentionally makes the old
    # command non-current. The policy validates that immutable head and its
    # content-bound coverage structurally; only the attestation coverage is
    # sent through the current-state real-backing gate.
    business.entrypoints.rejected_refs.add(
        business.historical_coverage.coverage_ref
    )
    result = build_platform_source_lineage_policy_resolver_m16_m21(
        context
    ).resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=anchor,
    )

    assert result.qro_ref == business.qro.qro_id
    assert context.entrypoint_registry.validation_calls == [
        business.coverage.coverage_ref
    ]


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize("history", ("missing", "ambiguous"))
def test_post_business_attestation_requires_one_immutable_historical_head(
    row: str,
    history: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    if history == "missing":
        business.graph._commands.remove(business.historical_command)
        business.compiler._irs.pop(business.historical_ir.ir_ref)
        business.compiler._passes.pop(business.historical_compiler_pass.pass_ref)
        business.entrypoints.records_value.remove(business.historical_coverage)
    else:
        _append_duplicate_historical_business_head(business, suffix="ambiguous")

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="immutable historical business Graph/compiler lineage",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "identity_mutation",
    ("qro_type", "input_contract", "output_contract", "owner"),
)
def test_post_business_attestation_allows_only_math_to_change_in_qro_history(
    row: str,
    identity_mutation: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    historical = business.historical_qro
    if identity_mutation == "qro_type":
        historical.qro_type = "RiskPolicy"
    elif identity_mutation == "input_contract":
        historical.input_contract["same_owner_recombined"] = "ref:unrelated"
    elif identity_mutation == "output_contract":
        historical.output_contract["status"] = "same_owner_recombined"
    else:
        historical.owner = OTHER_OWNER

    with pytest.raises(
        PlatformSourceLineagePolicyM16M21Error,
        match="fields other than mathematical_refs",
    ):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "projection_mutation",
    ("stale_command", "foreign_owner", "foreign_actor", "wrong_source", "wrong_math", "ambiguous"),
)
def test_post_business_attestation_requires_exact_owner_api_current_projection(
    row: str,
    projection_mutation: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    projection = business.graph._projections[business.qro.qro_id]
    if projection_mutation == "stale_command":
        projection.command_id = business.historical_command.command_id
    elif projection_mutation == "foreign_owner":
        projection.owner = OTHER_OWNER
    elif projection_mutation == "foreign_actor":
        projection.actor = OTHER_OWNER
    elif projection_mutation == "wrong_source":
        projection.source = "ide"
    elif projection_mutation == "wrong_math":
        projection.mathematical_refs = ("math_spine_chain:same-owner-unrelated",)
    else:
        duplicate = SimpleNamespace(**vars(projection))
        duplicate.projection_ref = f"{projection.projection_ref}:ambiguous"
        business.graph._projections["ambiguous"] = duplicate

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
@pytest.mark.parametrize(
    "compiler_mutation",
    ("historical_math", "foreign_actor", "wrong_entrypoint"),
)
def test_post_business_attestation_rejects_recombined_historical_compiler(
    row: str,
    compiler_mutation: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    if compiler_mutation == "historical_math":
        business.historical_ir.mathematical_spine_chain_refs = (
            business.chain.chain_ref,
        )
    elif compiler_mutation == "foreign_actor":
        business.historical_compiler_pass.actor = OTHER_OWNER
    else:
        canonical = tuple(
            "entrypoint:api:research_os.platform.business_attestations.wrong"
            if ref.startswith("entrypoint:")
            else ref
            for ref in business.historical_ir.canonical_command_refs
        )
        business.historical_ir.canonical_command_refs = canonical
        business.historical_compiler_pass.canonical_command_refs = canonical

    with pytest.raises(PlatformSourceLineagePolicyM16M21Error):
        build_platform_source_lineage_policy_resolver_m16_m21(context).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=anchor,
        )


@pytest.mark.parametrize("row", ("M16", "M19", "M21"))
def test_post_business_attestation_resolution_is_read_only_and_order_independent(
    row: str,
    tmp_path,
) -> None:
    business, context, anchor = _post_business_case(row, tmp_path)
    resolver = build_platform_source_lineage_policy_resolver_m16_m21(context)

    def snapshot() -> tuple[Any, ...]:
        return (
            tuple(item.command_id for item in business.graph._commands),
            tuple(business.compiler._irs),
            tuple(business.compiler._passes),
            tuple(item.coverage_ref for item in business.entrypoints.records_value),
            tuple(
                item.projection_ref
                for item in business.graph._projections.values()
            ),
        )

    before = snapshot()
    first = resolver.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=anchor,
    )
    assert snapshot() == before

    business.graph._commands.reverse()
    business.compiler._irs = dict(reversed(tuple(business.compiler._irs.items())))
    business.compiler._passes = dict(
        reversed(tuple(business.compiler._passes.items()))
    )
    reordered_before = snapshot()
    second = resolver.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=anchor,
    )

    assert second == first
    assert snapshot() == reordered_before


def test_m17_policy_fresh_factories_observe_another_worker_persistent_commit(
    tmp_path,
) -> None:
    """A worker opened before commit must resolve via read-only fresh views."""

    base = _persistent_m17_system()
    graph_path = tmp_path / "research_graph.jsonl"
    compiler_path = tmp_path / "compiler.jsonl"
    coverage_path = tmp_path / "coverage.jsonl"

    worker_a_graph = PersistentResearchGraphStore(graph_path)
    worker_a_compiler = PersistentCompilerIRStore(compiler_path)
    worker_a_backing = _PersistentAttestationCoverageResolver(
        worker_a_graph,
        worker_a_compiler,
        owner=PERSISTENT_ATTESTATION_OWNER,
        lifecycle_ref=base.refs["runtime_promotion_ref"],
    )
    worker_a_coverage = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        resolver=worker_a_backing,
    )

    # Worker B starts before A writes. Graph/compiler expose their startup
    # snapshots here; coverage reads intentionally reopen the durable head.
    worker_b_graph = PersistentResearchGraphStore(graph_path)
    worker_b_compiler = PersistentCompilerIRStore(compiler_path)
    worker_b_backing = _PersistentAttestationCoverageResolver(
        worker_b_graph,
        worker_b_compiler,
        owner=PERSISTENT_ATTESTATION_OWNER,
        lifecycle_ref=base.refs["runtime_promotion_ref"],
    )
    worker_b_coverage = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        resolver=worker_b_backing,
    )

    compile_calls = 0

    def persist_compile(qro, command, plan):
        nonlocal compile_calls
        compile_calls += 1
        built = _PersistentAttestationCompilerHarness()
        result = built.compile(qro, command, plan)
        for compiler_ir in built.store.irs(owner=PERSISTENT_ATTESTATION_OWNER):
            worker_a_compiler.record_ir(compiler_ir)
        for compiler_pass in built.store.passes(
            owner=PERSISTENT_ATTESTATION_OWNER
        ):
            worker_a_compiler.record_pass(compiler_pass)
        for coverage in built.coverage.records(
            owner=PERSISTENT_ATTESTATION_OWNER
        ):
            worker_a_coverage.record_coverage(coverage)
        return result

    worker_a_context = replace(
        base.context,
        research_graph_store=worker_a_graph,
        compiler_store=worker_a_compiler,
        entrypoint_registry=worker_a_coverage,
        compile_attestation=persist_compile,
    )
    committed = PlatformBusinessAttestationService(worker_a_context).record(
        owner_user_id=PERSISTENT_ATTESTATION_OWNER,
        row="M17",
        anchor_ref=base.refs["submission_ref"],
    )

    assert compile_calls == 1
    assert worker_b_graph.commands() == []
    assert worker_b_compiler.irs(owner=PERSISTENT_ATTESTATION_OWNER) == []
    assert worker_b_compiler.passes(owner=PERSISTENT_ATTESTATION_OWNER) == []
    worker_a_rows = worker_a_coverage.records(
        owner=PERSISTENT_ATTESTATION_OWNER
    )
    worker_b_rows = worker_b_coverage.records(
        owner=PERSISTENT_ATTESTATION_OWNER
    )
    assert len(worker_a_rows) == 1
    assert worker_b_rows == worker_a_rows
    assert worker_b_rows[0].recorded_by == PERSISTENT_ATTESTATION_OWNER
    assert worker_b_rows[0].coverage_ref == committed.entrypoint_coverage_ref

    factory_calls = {"graph": 0, "compiler": 0, "coverage": 0}

    def fresh_graph():
        factory_calls["graph"] += 1
        return PersistentResearchGraphStore(graph_path)

    def fresh_compiler():
        factory_calls["compiler"] += 1
        return PersistentCompilerIRStore(compiler_path)

    def fresh_coverage():
        factory_calls["coverage"] += 1
        graph = PersistentResearchGraphStore(graph_path)
        compiler = PersistentCompilerIRStore(compiler_path)
        backing = _PersistentAttestationCoverageResolver(
            graph,
            compiler,
            owner=PERSISTENT_ATTESTATION_OWNER,
            lifecycle_ref=base.refs["runtime_promotion_ref"],
        )
        return PersistentGoalEntrypointCoverageRegistry(
            coverage_path,
            resolver=backing,
        )

    worker_b = SimpleNamespace(
        graph=worker_b_graph,
        harness=SimpleNamespace(
            store=worker_b_compiler,
            coverage=worker_b_coverage,
        ),
        context=base.context,
    )
    policy_context = replace(
        _persistent_policy_context(worker_b, row="M17"),
        research_graph_view_factory=fresh_graph,
        compiler_view_factory=fresh_compiler,
        entrypoint_view_factory=fresh_coverage,
    )
    persisted_before = {
        path: path.read_bytes()
        for path in (graph_path, compiler_path, coverage_path)
    }

    resolution = build_platform_source_lineage_policy_resolver_m16_m21(
        policy_context
    ).resolve(
        owner_user_id=PERSISTENT_ATTESTATION_OWNER,
        m_row="M17",
        anchor_ref=base.refs["submission_ref"],
    )

    assert resolution.qro_ref == committed.qro_ref
    assert resolution.anchor_ref == base.refs["submission_ref"]
    assert resolution.business_entrypoint_ref == committed.entrypoint_ref
    assert resolution.math_spine_ref == committed.mathematical_spine_chain_ref
    assert factory_calls["graph"] == 1
    assert factory_calls["compiler"] >= 1
    assert factory_calls["coverage"] >= 1
    assert {
        path: path.read_bytes()
        for path in (graph_path, compiler_path, coverage_path)
    } == persisted_before
    assert worker_b_graph.commands() == []
    assert worker_b_compiler.irs(owner=PERSISTENT_ATTESTATION_OWNER) == []
    assert worker_b_coverage.records(
        owner=PERSISTENT_ATTESTATION_OWNER
    ) == worker_a_rows
