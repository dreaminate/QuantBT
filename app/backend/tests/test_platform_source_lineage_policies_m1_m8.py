from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
from types import SimpleNamespace

import pytest
from conftest import build_verified_spine_chain

from app.factor_factory.registry import FactorRegistry
from app.lineage.ids import content_hash
from app.research_os.asset_lifecycle import (
    GovernedAssetRecord,
    PersistentAssetLifecycleRegistry,
)
from app.research_os.asset_rag import PersistentResearchAssetRAGIndex
from app.research_os.compiler import (
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.entrypoint_evidence import (
    PersistentEntrypointEvidenceRegistry,
)
from app.research_os.goal_coverage import (
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    goal_entrypoint_coverage_identity,
)
from app.research_os.goal_validation_receipts import (
    GoalValidationOutcome,
    GoalValidationReceipt,
    PersistentGoalValidationReceiptRegistry,
)
from app.research_os.market_data_contract import DatasetSemanticsRecord, InstrumentSpec
from app.research_os.platform_coverage import PlatformCapabilityRecord
from app.research_os.platform_row_sources import PersistentPlatformRowSourceRegistry
from app.research_os.platform_source_adapters_m1_m8 import (
    PlatformSourceAdaptersM1M8Context,
    build_platform_source_adapters_m1_m8,
)
from app.research_os.platform_source_lineage_core import (
    PlatformSourceLineageCoreError,
    PlatformSourceLineageFinalizer,
)
from app.research_os.platform_source_lineage_policies_m1_m8 import (
    M1_M2_SPINE_BINDING_ENTRYPOINT_REF,
    M3_SPINE_BINDING_ENTRYPOINT_REF,
    M4_M5_SPINE_BINDING_ENTRYPOINT_REF,
    M6_SPINE_BINDING_ENTRYPOINT_REF,
    M7_M8_SPINE_BINDING_ENTRYPOINT_REF,
    PlatformSourceLineagePoliciesM1M8Context,
    PlatformSourceLineagePolicyM1M8Error,
    build_platform_source_lineage_policy_resolver_m1_m8,
)
from app.research_os.platform_typed_sources import RealPlatformTypedSourceResolver
from app.research_os.ref_resolution import build_real_ref_resolver
from app.research_os.research_design_assets import (
    PersistentResearchDesignAssetRegistry,
    ResearchDesignLinkage,
    make_hypothesis_envelope,
    make_factor_envelope,
    make_label_definition_record,
    make_regime_scenario_record,
    make_universe_definition_record,
    source_object_hash,
)
from app.research_os.spine import (
    ActorSource,
    ConsistencyStatus,
    DefinitionStatus,
    EntrySource,
    EvidenceStatus,
    MathematicalSpineChainRecord,
    PersistentResearchGraphStore,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    RuntimeStatus,
)


OWNER = "owner-policy-m1-m8"


class _LegacyTestCompilerStore(PersistentCompilerIRStore):
    """No-ledger compatibility store for the finalizer integration fixture."""

    def canonical_records(self, *, owner: str) -> SimpleNamespace:
        return SimpleNamespace(
            owner=owner,
            irs=tuple(self.irs(owner=owner)),
            passes=tuple(self.passes(owner=owner)),
            artifacts=(),
        )

    def canonical_ir(self, ir_ref: str, *, owner: str) -> CompilerIRRecord:
        return self.ir(ir_ref, owner=owner)

    def canonical_compiler_pass(
        self,
        pass_ref: str,
        *,
        owner: str,
    ) -> CompilerPassRecord:
        return self.compiler_pass(pass_ref, owner=owner)
OTHER_OWNER = "owner-policy-m1-m8-foreign"

BINDING_ENTRYPOINTS = {
    "M1-M2": M1_M2_SPINE_BINDING_ENTRYPOINT_REF,
    "M3": M3_SPINE_BINDING_ENTRYPOINT_REF,
    "M4-M5": M4_M5_SPINE_BINDING_ENTRYPOINT_REF,
    "M6": M6_SPINE_BINDING_ENTRYPOINT_REF,
    "M7-M8": M7_M8_SPINE_BINDING_ENTRYPOINT_REF,
}

BUSINESS_ENTRYPOINTS = {
    "M1-M2": "api:hypothesis_cards",
    "M3": "api:research_os.market_data.datasets",
    "M4-M5": "api:factors",
    "M6": "api:training.jobs",
    "M7-M8": "api:portfolios.promote",
}


@dataclass
class _Goal:
    goal_id: str
    title: str


@dataclass
class _Card:
    card_id: str
    strategy_goal_ref: str
    statement: str


@dataclass
class _Factor:
    factor_id: str
    version: int
    formula: str


@dataclass
class _Signal:
    signal_id: str
    name: str


class _Graph:
    def __init__(self) -> None:
        self.qro_by_ref: dict[str, object] = {}
        self.command_rows: list[object] = []
        self.projection_rows: list[object] = []

    def add(
        self,
        qro: object,
        graph_ref: str,
        *,
        actor: str = OWNER,
        source: str = "api",
        actor_source: str = "user_manual",
        evidence_refs: tuple[str, ...] = (),
        tool_record_refs: tuple[str, ...] = (),
    ) -> object:
        self.qro_by_ref[str(getattr(qro, "qro_id"))] = qro
        command = SimpleNamespace(
            command_id=graph_ref,
            command_type="upsert_qro",
            actor=actor,
            source=source,
            actor_source=actor_source,
            payload={"qro": qro},
            evidence_refs=evidence_refs,
            tool_record_refs=tool_record_refs,
        )
        self.command_rows.append(command)
        return command

    def project(
        self,
        qro: object,
        command: object,
        *,
        projection_ref: str,
        actor: str = OWNER,
        source: str = "api",
    ) -> object:
        projection = SimpleNamespace(
            projection_ref=projection_ref,
            qro_id=str(getattr(qro, "qro_id")),
            command_id=str(getattr(command, "command_id")),
            owner=OWNER,
            actor=actor,
            source=source,
            mathematical_refs=tuple(getattr(qro, "mathematical_refs", ()) or ()),
        )
        self.projection_rows.append(projection)
        return projection

    def qro(self, ref: str):
        return self.qro_by_ref[ref]

    def commands(self):
        return list(self.command_rows)

    def projection_index(self, *, owner: str):
        return [item for item in self.projection_rows if item.owner == owner]


class _Compiler:
    def __init__(self) -> None:
        self.ir_rows: list[object] = []
        self.pass_rows: list[object] = []

    def add(
        self,
        qro: object,
        graph_ref: str,
        *,
        chain_ref: str | None,
        entrypoint: str,
        entry_source: str = "api",
        suffix: str = "",
    ) -> tuple[object, object]:
        token = suffix or str(getattr(qro, "qro_id")).replace(":", "-")
        canonical_refs = (
            f"research_graph_command:{graph_ref}",
            f"entrypoint:{entrypoint}",
        )
        ir = SimpleNamespace(
            ir_ref=f"compiler_ir:{token}",
            source_qro_refs=(str(getattr(qro, "qro_id")),),
            graph_command_refs=(graph_ref,),
            canonical_command_refs=canonical_refs,
            mathematical_spine_chain_refs=(chain_ref,) if chain_ref else (),
            owner=OWNER,
        )
        compiler_pass = SimpleNamespace(
            pass_ref=f"compiler_pass:{token}",
            output_ir_ref=ir.ir_ref,
            input_qro_refs=(str(getattr(qro, "qro_id")),),
            graph_command_refs=(graph_ref,),
            canonical_command_refs=canonical_refs,
            actor=OWNER,
            entry_source=entry_source,
            status="compiled",
        )
        self.ir_rows.append(ir)
        self.pass_rows.append(compiler_pass)
        return ir, compiler_pass

    def irs(self, *, owner: str):
        return [item for item in self.ir_rows if item.owner == owner]

    def passes(self, *, owner: str):
        return [item for item in self.pass_rows if item.actor == owner]


class _Spines:
    def __init__(self) -> None:
        self.rows: list[object] = []

    def chains(self, *, owner: str):
        return [item for item in self.rows if item.recorded_by == owner]

    def verified_chain(self, ref: str, *, owner: str):
        matches = [
            item
            for item in self.rows
            if item.chain_ref == ref and item.recorded_by == owner
        ]
        if len(matches) != 1:
            raise KeyError(ref)
        return matches[0]


class _Lifecycle:
    def __init__(self) -> None:
        self.assets: dict[tuple[str, str], object] = {}
        self.updates: list[object] = []

    def governed_asset(self, ref: str, *, owner_user_id: str):
        return self.assets[(owner_user_id, ref)]

    def ingestion_skill_updates(self, *, owner_user_id: str):
        return [item for item in self.updates if item.recorded_by == owner_user_id]


class _Design:
    def __init__(self) -> None:
        self.hypotheses: dict[tuple[str, str], object] = {}
        self.universes: dict[tuple[str, str], object] = {}
        self.regimes: dict[tuple[str, str], object] = {}
        self.factors: dict[tuple[str, str], object] = {}
        self.labels: dict[tuple[str, str], object] = {}
        self.policies: dict[tuple[str, str], object] = {}
        self.strategies: dict[tuple[str, str], object] = {}
        self.signals: dict[tuple[str, str], object] = {}

    def hypothesis_envelope(self, ref: str, *, owner_user_id: str):
        return self.hypotheses[(owner_user_id, ref)]

    def universe_definition(self, ref: str, *, owner_user_id: str):
        return self.universes[(owner_user_id, ref)]

    def regime_scenario(self, ref: str, *, owner_user_id: str):
        return self.regimes[(owner_user_id, ref)]

    def factor_envelope(self, ref: str, *, owner_user_id: str):
        return self.factors[(owner_user_id, ref)]

    def label_definition(self, ref: str, *, owner_user_id: str):
        return self.labels[(owner_user_id, ref)]

    def portfolio_policy(self, ref: str, *, owner_user_id: str):
        return self.policies[(owner_user_id, ref)]

    def strategy_book(self, ref: str, *, owner_user_id: str):
        return self.strategies[(owner_user_id, ref)]

    def signal_contract_envelope(self, ref: str, *, owner_user_id: str):
        return self.signals[(owner_user_id, ref)]


class _Goals:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}

    def get(self, ref: str):
        return self.rows[ref]


class _Cards(_Goals):
    pass


class _Factors:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, int], object] = {}

    def get(self, factor_id: str, version: int):
        return self.rows[(factor_id, version)]


class _Onboarding:
    def __init__(self) -> None:
        self.skills: dict[tuple[str, str], object] = {}
        self.sources: dict[tuple[str, str], object] = {}
        self.pit_rules: dict[tuple[str, str], object] = {}

    def ingestion_skill(self, ref: str, *, owner_user_id: str):
        return self.skills[(owner_user_id, ref)]

    def data_source(self, ref: str, *, owner_user_id: str):
        return self.sources[(owner_user_id, ref)]

    def data_connector_pit_bitemporal_rule(self, ref: str, *, owner_user_id: str):
        return self.pit_rules[(owner_user_id, ref)]


class _Market:
    def __init__(self) -> None:
        self.dataset_rows: dict[tuple[str, str], object] = {}
        self.instrument_rows: dict[str, list[object]] = {}

    def dataset(self, ref: str, *, owner_user_id: str):
        return self.dataset_rows[(owner_user_id, ref)]

    def instruments(self, *, owner_user_id: str):
        return list(self.instrument_rows.get(owner_user_id, ()))


class _Versions:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}

    def resolve_version_ref(self, ref: str):
        return self.rows[ref]


class _Passports:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], object] = {}

    def passport(self, ref: str, *, owner_user_id: str):
        return self.rows[(owner_user_id, ref)]


class _Training:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}

    def get_job(self, ref: str):
        return self.rows[ref]


class _Models:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], list[object]] = {}

    def list_versions(self, model_id: str, *, owner_user_id: str):
        return list(self.rows.get((owner_user_id, model_id), ()))


class _Signals:
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}

    def get(self, ref: str):
        return self.rows[ref]


class _SignalValidations:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], object] = {}

    def validation(self, ref: str, *, owner_user_id: str):
        return self.rows[(owner_user_id, ref)]


class _World:
    def __init__(self) -> None:
        self.graph = _Graph()
        self.compiler = _Compiler()
        self.spines = _Spines()
        self.lifecycle = _Lifecycle()
        self.design = _Design()
        self.goals = _Goals()
        self.cards = _Cards()
        self.factors = _Factors()
        self.onboarding = _Onboarding()
        self.market = _Market()
        self.versions = _Versions()
        self.passports = _Passports()
        self.training = _Training()
        self.models = _Models()
        self.signals = _Signals()
        self.validations = _SignalValidations()
        self.anchors: dict[str, str] = {}
        self.business_qros: dict[str, object] = {}
        self.business_commands: dict[str, object] = {}
        self.binding_qros: dict[str, object] = {}
        self.binding_commands: dict[str, object] = {}
        self.binding_projections: dict[str, object] = {}
        self._m1()
        self._m3()
        self._m4()
        self._m6()
        self._m7()

    def context(
        self,
        *,
        graph=None,
        compiler=None,
        spines=None,
        design=None,
        lifecycle=None,
        factors=None,
    ):
        return PlatformSourceLineagePoliciesM1M8Context(
            research_graph_store=graph or self.graph,
            compiler_store=compiler or self.compiler,
            spine_chain_registry=spines or self.spines,
            asset_lifecycle_registry=lifecycle or self.lifecycle,
            research_design_registry=design or self.design,
            strategy_goal_store=self.goals,
            hypothesis_store=self.cards,
            factor_registry=factors or self.factors,
            onboarding_registry=self.onboarding,
            market_data_registry=self.market,
            dataset_registry=self.versions,
            model_governance_registry=self.passports,
            training_service=self.training,
            model_registry=self.models,
            signal_contract_registry=self.signals,
            signal_validation_registry=self.validations,
        )

    def _record_split_lineage(
        self,
        *,
        row: str,
        qro: object,
        business_graph_ref: str,
        chain_ref: str,
        business_entrypoint: str,
        binding_entrypoint: str,
    ) -> object:
        business_qro = SimpleNamespace(
            **{**vars(qro), "mathematical_refs": ()}
        )
        business_command = self.graph.add(business_qro, business_graph_ref)
        self.compiler.add(
            business_qro,
            business_graph_ref,
            chain_ref=None,
            entrypoint=business_entrypoint,
            suffix=f"{row.lower()}-business",
        )
        binding_qro = SimpleNamespace(
            **{**vars(business_qro), "mathematical_refs": (chain_ref,)}
        )
        binding_graph_ref = f"{business_graph_ref}:spine-binding"
        binding_command = self.graph.add(
            binding_qro,
            binding_graph_ref,
            evidence_refs=(chain_ref, business_graph_ref),
            tool_record_refs=(binding_entrypoint,),
        )
        self.compiler.add(
            binding_qro,
            binding_graph_ref,
            chain_ref=chain_ref,
            entrypoint=binding_entrypoint,
            suffix=f"{row.lower()}-spine-binding",
        )
        projection = self.graph.project(
            binding_qro,
            binding_command,
            projection_ref=f"rgproj:{row.lower()}:spine-binding",
        )
        self.business_qros[row] = business_qro
        self.business_commands[row] = business_command
        self.binding_qros[row] = binding_qro
        self.binding_commands[row] = binding_command
        self.binding_projections[row] = projection
        return binding_qro

    def _m1(self) -> None:
        goal = _Goal("goal-m1-policy", "M1 policy goal")
        goal_ref = f"strategy_goal:{goal.goal_id}"
        card = _Card("card-m1-policy", goal_ref, "falsifiable claim")
        anchor = f"hypothesis_card:{card.card_id}"
        universe_ref = "universe:m1-policy"
        regime_ref = "regime:m1-policy"
        qro_ref = "qro:m1-policy"
        graph_ref = "rgcmd:m1-policy"
        chain_ref = "math_spine_chain:m1-policy"
        linkage = SimpleNamespace(
            qro_ref=qro_ref,
            research_graph_ref=graph_ref,
            lifecycle_ref=anchor,
        )
        self.goals.rows[goal.goal_id] = goal
        self.cards.rows[card.card_id] = card
        self.design.hypotheses[(OWNER, anchor)] = SimpleNamespace(
            hypothesis_card_ref=anchor,
            owner_user_id=OWNER,
            card_id=card.card_id,
            source_content_hash=source_object_hash(card),
            strategy_goal_ref=goal_ref,
            universe_definition_ref=universe_ref,
            regime_scenario_ref=regime_ref,
            linkage=linkage,
        )
        self.design.universes[(OWNER, universe_ref)] = SimpleNamespace(
            universe_definition_ref=universe_ref,
            owner_user_id=OWNER,
        )
        self.design.regimes[(OWNER, regime_ref)] = SimpleNamespace(
            regime_scenario_ref=regime_ref,
            universe_definition_ref=universe_ref,
            owner_user_id=OWNER,
        )
        qro = SimpleNamespace(
            qro_id=qro_ref,
            qro_type="QuantIntent",
            owner=OWNER,
            mathematical_refs=(chain_ref,),
            output_contract={
                "strategy_goal_ref": goal_ref,
                "strategy_goal_hash": source_object_hash(goal),
                "hypothesis_card_ref": anchor,
                "universe_definition_ref": universe_ref,
                "regime_scenario_ref": regime_ref,
            },
        )
        self.lifecycle.assets[(OWNER, anchor)] = SimpleNamespace(
            asset_ref=anchor,
            asset_type="HypothesisCard",
        )
        self.spines.rows.append(
            SimpleNamespace(
                chain_ref=chain_ref,
                recorded_by=OWNER,
                validation_refs=(goal_ref, anchor),
                evidence_refs=(universe_ref, regime_ref),
            )
        )
        self._record_split_lineage(
            row="M1-M2",
            qro=qro,
            business_graph_ref=graph_ref,
            chain_ref=chain_ref,
            business_entrypoint="api:hypothesis_cards",
            binding_entrypoint=M1_M2_SPINE_BINDING_ENTRYPOINT_REF,
        )
        self.anchors["M1-M2"] = anchor

    def _m3(self) -> None:
        anchor = "dataset:bars-policy:v1"
        update_ref = "ingestion_update:bars-policy:v1"
        skill_ref = "ingestion_skill:bars-policy:v1"
        source_ref = "datasource:bars-policy"
        pit_ref = "pit:bars-policy:v1"
        version_ref = "dataset_version:bars-policy:v1"
        schema_ref = "schema_mapping:bars-policy:v1"
        chain_ref = "math_spine_chain:m3-policy"
        dataset = DatasetSemanticsRecord(
            dataset_ref=anchor,
            source_ref=source_ref,
            version="v1",
            known_at_ref="known_at:bars-policy:v1",
            effective_at_ref="effective_at:bars-policy:v1",
            pit_bitemporal_rules_ref=pit_ref,
            quality_status="passed",
            lineage_refs=(
                update_ref,
                "lineage:bars-policy:v1",
                pit_ref,
                "field_mapping:bars-policy:v1",
                "schema_probe:bars-policy:v1",
            ),
            freshness_status="fresh",
            checksum="sha256:bars-policy",
        )
        update = SimpleNamespace(
            update_ref=update_ref,
            skill_ref=skill_ref,
            skill_version="v1",
            dataset_version_ref=version_ref,
            checksum=dataset.checksum,
            lineage_ref="lineage:bars-policy:v1",
            source_ref=source_ref,
            known_at_ref=dataset.known_at_ref,
            effective_at_ref=dataset.effective_at_ref,
            row_count=17,
            recorded_by=OWNER,
        )
        skill = SimpleNamespace(
            skill_id=skill_ref,
            owner_user_id=OWNER,
            source_ref=source_ref,
            version="v1",
            lifecycle_state="active",
            pit_bitemporal_rules_ref=pit_ref,
            schema_mapping_ref=schema_ref,
            output_dataset_id="bars-policy",
        )
        self.market.dataset_rows[(OWNER, anchor)] = dataset
        self.lifecycle.updates.append(update)
        self.onboarding.skills[(OWNER, skill_ref)] = skill
        self.onboarding.sources[(OWNER, source_ref)] = SimpleNamespace(
            source_ref=source_ref
        )
        self.onboarding.pit_rules[(OWNER, pit_ref)] = SimpleNamespace(
            rule_ref=pit_ref,
            skill_id=skill_ref,
            source_ref=source_ref,
        )
        self.versions.rows[version_ref] = SimpleNamespace(
            dataset_id="bars-policy",
            version_id="v1",
            sha256=dataset.checksum,
            row_count=17,
        )
        self.market.instrument_rows[OWNER] = [
            InstrumentSpec(
                instrument_ref="instrument:BTCUSDT-policy",
                asset_class="crypto_spot",
                instrument_type="spot",
                currency="USDT",
                exchange_calendar_ref="calendar:crypto:247",
                symbol_mapping_ref=schema_ref,
            )
        ]
        qro = SimpleNamespace(
            qro_id="qro:m3-policy",
            qro_type="Dataset",
            owner=OWNER,
            mathematical_refs=(chain_ref,),
            input_contract={
                "record_hash": content_hash(dataset.to_dict()),
            },
            output_contract={
                "status": "dataset_semantics_recorded",
                "dataset_ref": anchor,
                "known_at_ref": dataset.known_at_ref,
                "effective_at_ref": dataset.effective_at_ref,
                "pit_bitemporal_rules_ref": pit_ref,
                "quality_status": dataset.quality_status,
                "freshness_status": dataset.freshness_status,
            },
            implementation_hash="market_data_dataset:" + content_hash(dataset.to_dict()),
        )
        self.spines.rows.append(
            SimpleNamespace(
                chain_ref=chain_ref,
                recorded_by=OWNER,
                data_semantics_ref=anchor,
            )
        )
        self._record_split_lineage(
            row="M3",
            qro=qro,
            business_graph_ref="rgcmd:m3-policy",
            chain_ref=chain_ref,
            business_entrypoint="api:research_os.market_data.datasets",
            binding_entrypoint=M3_SPINE_BINDING_ENTRYPOINT_REF,
        )
        self.anchors["M3"] = anchor

    def _m4(self) -> None:
        factor = _Factor("momentum-policy", 1, "close / delay(close, 5) - 1")
        anchor = "factor:momentum-policy:v1"
        label_ref = "label:forward-return-policy"
        qro_ref = "qro:m4-policy"
        graph_ref = "rgcmd:m4-policy"
        chain_ref = "math_spine_chain:m4-policy"
        linkage = SimpleNamespace(
            qro_ref=qro_ref,
            research_graph_ref=graph_ref,
            lifecycle_ref=anchor,
        )
        self.factors.rows[(factor.factor_id, factor.version)] = factor
        self.design.factors[(OWNER, anchor)] = SimpleNamespace(
            factor_ref=anchor,
            factor_id=factor.factor_id,
            version=factor.version,
            owner_user_id=OWNER,
            source_content_hash=source_object_hash(factor),
            label_ref=label_ref,
            linkage=linkage,
        )
        self.design.labels[(OWNER, label_ref)] = SimpleNamespace(
            label_ref=label_ref,
            owner_user_id=OWNER,
        )
        formula_hash = content_hash({"formula": factor.formula})
        qro = SimpleNamespace(
            qro_id=qro_ref,
            qro_type="Factor",
            owner=OWNER,
            mathematical_refs=(chain_ref,),
            input_contract={"formula_hash": formula_hash},
            output_contract={"factor_ref": anchor, "label_ref": label_ref},
        )
        self.lifecycle.assets[(OWNER, anchor)] = SimpleNamespace(
            asset_ref=anchor,
            asset_type="Factor",
            evidence_refs=(anchor,),
        )
        self.spines.rows.append(
            SimpleNamespace(
                chain_ref=chain_ref,
                recorded_by=OWNER,
                factor_ref=anchor,
                validation_refs=(label_ref,),
                evidence_refs=(),
            )
        )
        self._record_split_lineage(
            row="M4-M5",
            qro=qro,
            business_graph_ref=graph_ref,
            chain_ref=chain_ref,
            business_entrypoint="api:factors",
            binding_entrypoint=M4_M5_SPINE_BINDING_ENTRYPOINT_REF,
        )
        self.anchors["M4-M5"] = anchor

    def _m6(self) -> None:
        anchor = "model_passport:m6-policy"
        job_id = "training-m6-policy"
        dossier_ref = f"validation_dossier:{job_id}"
        model_id = "ridge-policy"
        model_version_ref = f"model_version:{model_id}:v1"
        chain_ref = "math_spine_chain:m6-policy"
        request = {"feature_cols": ["f1"], "label_col": "label:y"}
        metrics = {"sharpe": 1.1}
        passport = SimpleNamespace(
            passport_id=anchor,
            owner_user_id=OWNER,
            model_version_ref=model_version_ref,
            validation_dossier_ref=dossier_ref,
        )
        job = SimpleNamespace(
            job_id=job_id,
            owner_user_id=OWNER,
            status="succeeded",
            model=model_id,
            model_version=1,
            model_passport_ref=anchor,
            validation_dossier_ref=dossier_ref,
            run_id="run:m6-policy",
            qro_id="qro:m6-policy",
            research_graph_command_id="rgcmd:m6-policy",
            request=request,
            metrics=metrics,
        )
        version = SimpleNamespace(
            version=1,
            stage="dev",
            model_passport_ref=anchor,
            validation_dossier_ref=dossier_ref,
            source_run_id=job.run_id,
        )
        self.passports.rows[(OWNER, anchor)] = passport
        self.training.rows[job_id] = job
        self.models.rows[(OWNER, model_id)] = [version]
        qro = SimpleNamespace(
            qro_id=job.qro_id,
            qro_type="Model",
            owner=OWNER,
            mathematical_refs=(chain_ref,),
            output_contract={
                "status": "succeeded",
                "job_id": job_id,
                "model": model_id,
                "model_version": 1,
                "model_version_ref": model_version_ref,
                "model_passport_ref": anchor,
                "validation_dossier_ref": dossier_ref,
                "run_id": job.run_id,
                "metrics_hash": content_hash(metrics),
            },
            implementation_hash="training_job:"
            + content_hash(
                {
                    "job_id": job_id,
                    "model_version_ref": model_version_ref,
                    "request_hash": content_hash(request),
                    "metrics_hash": content_hash(metrics),
                }
            ),
        )
        self.spines.rows.append(
            SimpleNamespace(
                chain_ref=chain_ref,
                recorded_by=OWNER,
                model_ref=model_version_ref,
            )
        )
        self._record_split_lineage(
            row="M6",
            qro=qro,
            business_graph_ref=job.research_graph_command_id,
            chain_ref=chain_ref,
            business_entrypoint="api:training.jobs",
            binding_entrypoint=M6_SPINE_BINDING_ENTRYPOINT_REF,
        )
        self.anchors["M6"] = anchor

    def _m7(self) -> None:
        contract = _Signal("sig::policy", "policy signal")
        raw_signal_ref = contract.signal_id
        signal_ref = f"signal_contract:{raw_signal_ref}"
        validation_ref = "signal_validation:policy:oos"
        strategy_ref = "strategy_book:policy"
        anchor = "portfolio_policy:policy"
        chain_ref = "math_spine_chain:m7-policy"
        strategy_payload = {
            "signal_refs": [raw_signal_ref],
            "signal_validation_refs": [validation_ref],
        }
        strategy = SimpleNamespace(
            strategy_book_ref=strategy_ref,
            owner_user_id=OWNER,
            strategy_book=strategy_payload,
            source_content_hash=content_hash(strategy_payload),
        )
        signal_envelope = SimpleNamespace(
            signal_contract_ref=signal_ref,
            owner_user_id=OWNER,
            source_content_hash=source_object_hash(contract),
        )
        validation = SimpleNamespace(
            validation_id=validation_ref,
            owner_user_id=OWNER,
            verdict="accepted",
            signal_ref=raw_signal_ref,
        )
        linkage = SimpleNamespace(
            qro_ref="qro:m7-policy",
            research_graph_ref="rgcmd:m7-policy",
            lifecycle_ref=anchor,
        )
        policy = SimpleNamespace(
            portfolio_policy_ref=anchor,
            owner_user_id=OWNER,
            portfolio_id="portfolio-policy",
            signal_contract_ref=signal_ref,
            signal_validation_ref=validation_ref,
            strategy_book_ref=strategy_ref,
            signal_contract_source_hash=signal_envelope.source_content_hash,
            strategy_book_source_hash=strategy.source_content_hash,
            source_content_hash="policy-source-hash",
            linkage=linkage,
        )
        self.signals.rows[raw_signal_ref] = contract
        self.validations.rows[(OWNER, validation_ref)] = validation
        self.design.signals[(OWNER, signal_ref)] = signal_envelope
        self.design.strategies[(OWNER, strategy_ref)] = strategy
        self.design.policies[(OWNER, anchor)] = policy
        qro = SimpleNamespace(
            qro_id=linkage.qro_ref,
            qro_type="PortfolioPolicy",
            owner=OWNER,
            mathematical_refs=(chain_ref,),
            output_contract={
                "signal_contract_ref": signal_ref,
                "signal_validation_ref": validation_ref,
                "strategy_book_ref": strategy_ref,
                "portfolio_policy_ref": anchor,
            },
        )
        self.lifecycle.assets[(OWNER, anchor)] = SimpleNamespace(
            asset_ref=anchor,
            asset_type="PortfolioPolicy",
        )
        self.spines.rows.append(
            SimpleNamespace(
                chain_ref=chain_ref,
                recorded_by=OWNER,
                signal_contract_ref=signal_ref,
                strategy_book_ref=strategy_ref,
                portfolio_policy_ref=anchor,
            )
        )
        self._record_split_lineage(
            row="M7-M8",
            qro=qro,
            business_graph_ref=linkage.research_graph_ref,
            chain_ref=chain_ref,
            business_entrypoint="api:portfolios.promote",
            binding_entrypoint=M7_M8_SPINE_BINDING_ENTRYPOINT_REF,
        )
        self.anchors["M7-M8"] = anchor


@pytest.mark.parametrize(
    ("row", "entrypoint"),
    (
        ("M1-M2", M1_M2_SPINE_BINDING_ENTRYPOINT_REF),
        ("M3", M3_SPINE_BINDING_ENTRYPOINT_REF),
        ("M4-M5", M4_M5_SPINE_BINDING_ENTRYPOINT_REF),
        ("M6", M6_SPINE_BINDING_ENTRYPOINT_REF),
        ("M7-M8", M7_M8_SPINE_BINDING_ENTRYPOINT_REF),
    ),
)
def test_group_resolver_derives_each_row_from_one_business_anchor(row, entrypoint):
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    result = resolver.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=world.anchors[row],
    )

    assert result.m_row == row
    assert result.anchor_ref == world.anchors[row]
    assert result.business_entry_source == "api"
    assert result.business_entrypoint_ref == entrypoint
    assert result.qro_ref.startswith("qro:")
    assert result.math_spine_ref.startswith("math_spine_chain:")
    assert result.lifecycle_ref
    assert result.primary_rag_asset_ref
    metadata = dict(result.row_policy_metadata)
    assert metadata["graph_command_ref"].startswith("rgcmd:")
    assert metadata["compiler_ir_ref"].startswith("compiler_ir:")
    assert metadata["compiler_pass_ref"].startswith("compiler_pass:")
    assert metadata["binding_projection_ref"].startswith("rgproj:")
    assert metadata["business_graph_command_ref"] == (
        world.business_commands[row].command_id
    )
    assert metadata["business_entrypoint_ref"] == {
        "M1-M2": "api:hypothesis_cards",
        "M3": "api:research_os.market_data.datasets",
        "M4-M5": "api:factors",
        "M6": "api:training.jobs",
        "M7-M8": "api:portfolios.promote",
    }[row]
    assert world.business_qros[row].mathematical_refs == ()
    if row == "M6":
        assert result.lifecycle_ref == f"stage:{OWNER}:ridge-policy:v1:dev"


_ROW_QRO_REFS = {
    "M1-M2": "qro:m1-policy",
    "M3": "qro:m3-policy",
    "M4-M5": "qro:m4-policy",
    "M6": "qro:m6-policy",
    "M7-M8": "qro:m7-policy",
}


def _world_lineage(world: _World, row: str) -> tuple[object, object, object]:
    qro_ref = _ROW_QRO_REFS[row]
    qro = world.graph.qro_by_ref[qro_ref]
    command_ref = world.binding_commands[row].command_id
    compiler_ir = next(
        item
        for item in world.compiler.ir_rows
        if item.source_qro_refs == (qro_ref,)
        and item.graph_command_refs == (command_ref,)
    )
    compiler_pass = next(
        item
        for item in world.compiler.pass_rows
        if item.output_ir_ref == compiler_ir.ir_ref
    )
    return qro, compiler_ir, compiler_pass


@pytest.mark.parametrize("row", tuple(_ROW_QRO_REFS))
@pytest.mark.parametrize("mode", ("missing", "duplicate"))
def test_every_row_rejects_missing_or_duplicate_qro_math_binding(row, mode):
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())
    qro, _compiler_ir, _compiler_pass = _world_lineage(world, row)
    chain_ref = qro.mathematical_refs[0]
    qro.mathematical_refs = () if mode == "missing" else (chain_ref, chain_ref)

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match="exactly one Mathematical Spine|duplicate refs",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.anchors[row],
        )


@pytest.mark.parametrize("row", tuple(_ROW_QRO_REFS))
def test_every_row_rejects_qro_compiler_math_mismatch_without_writes(row):
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())
    _qro, compiler_ir, _compiler_pass = _world_lineage(world, row)
    before = (
        len(world.graph.command_rows),
        len(world.compiler.ir_rows),
        len(world.compiler.pass_rows),
        len(world.spines.rows),
    )
    compiler_ir.mathematical_spine_chain_refs = (
        "math_spine_chain:other-current-owner-chain",
    )

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match="QRO/compiler IR Mathematical Spine binding mismatch",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.anchors[row],
        )

    assert (
        len(world.graph.command_rows),
        len(world.compiler.ir_rows),
        len(world.compiler.pass_rows),
        len(world.spines.rows),
    ) == before


@pytest.mark.parametrize("mode", ("missing", "duplicate"))
def test_resolver_rejects_missing_or_duplicate_exact_compiler_pair(mode):
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())
    _qro, _compiler_ir, compiler_pass = _world_lineage(world, "M1-M2")
    if mode == "missing":
        world.compiler.pass_rows.remove(compiler_pass)
    else:
        world.compiler.pass_rows.append(
            SimpleNamespace(
                **{
                    **vars(compiler_pass),
                    "pass_ref": "compiler_pass:qro-m1-policy-duplicate",
                }
            )
        )

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match="exactly one owner compiler IR/pass pair",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M1-M2",
            anchor_ref=world.anchors["M1-M2"],
        )


def test_resolver_rejects_duplicate_compiler_math_declaration():
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())
    qro, compiler_ir, _compiler_pass = _world_lineage(world, "M1-M2")
    chain_ref = qro.mathematical_refs[0]
    compiler_ir.mathematical_spine_chain_refs = (chain_ref, chain_ref)

    with pytest.raises(PlatformSourceLineagePolicyM1M8Error, match="duplicate refs"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M1-M2",
            anchor_ref=world.anchors["M1-M2"],
        )


@pytest.mark.parametrize("component", ("ir_graph", "pass_qro"))
def test_resolver_rejects_recombined_graph_ir_pass_lineage(component):
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())
    _qro, compiler_ir, compiler_pass = _world_lineage(world, "M1-M2")
    if component == "ir_graph":
        compiler_ir.graph_command_refs = ("rgcmd:m3-policy",)
    else:
        compiler_pass.input_qro_refs = ("qro:m3-policy",)

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match="exactly one owner compiler IR/pass pair",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M1-M2",
            anchor_ref=world.anchors["M1-M2"],
        )


def test_m3_rejects_compiler_metadata_from_a_different_api_entrypoint():
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())
    _qro, compiler_ir, compiler_pass = _world_lineage(world, "M3")
    recombined_refs = (
        "research_graph_command:rgcmd:m3-policy",
        "entrypoint:api:research_os.market_data.instruments",
    )
    compiler_ir.canonical_command_refs = recombined_refs
    compiler_pass.canonical_command_refs = recombined_refs

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match="current binding compiler entrypoint mismatch",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M3",
            anchor_ref=world.anchors["M3"],
        )


def test_deterministic_binding_replay_selects_current_projection_and_keeps_business_linkage():
    world = _World()
    anchor = world.anchors["M1-M2"]
    envelope = world.design.hypotheses[(OWNER, anchor)]
    qro = world.binding_qros["M1-M2"]
    business_command = world.business_commands["M1-M2"]
    replay_ref = "rgcmd:m1-policy:spine-binding:replay"
    replay_command = world.graph.add(
        qro,
        replay_ref,
        evidence_refs=(
            qro.mathematical_refs[0],
            business_command.command_id,
        ),
        tool_record_refs=(M1_M2_SPINE_BINDING_ENTRYPOINT_REF,),
    )
    replay_ir, replay_pass = world.compiler.add(
        qro,
        replay_ref,
        chain_ref=qro.mathematical_refs[0],
        entrypoint=M1_M2_SPINE_BINDING_ENTRYPOINT_REF,
        suffix="m1-policy-replay",
    )
    replay_projection = world.graph.project(
        qro,
        replay_command,
        projection_ref="rgproj:m1-m2:spine-binding:replay",
    )
    world.graph.projection_rows[:] = [replay_projection]
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    result = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M1-M2",
        anchor_ref=anchor,
    )

    metadata = dict(result.row_policy_metadata)
    assert result.qro_ref == qro.qro_id
    assert result.math_spine_ref == qro.mathematical_refs[0]
    assert metadata["graph_command_ref"] == replay_ref
    assert metadata["compiler_ir_ref"] == replay_ir.ir_ref
    assert metadata["compiler_pass_ref"] == replay_pass.pass_ref
    assert metadata["binding_projection_ref"] == replay_projection.projection_ref
    assert metadata["business_graph_command_ref"] == business_command.command_id
    assert envelope.linkage.research_graph_ref == business_command.command_id


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("command_type", "record_consistency_check"),
        ("actor_source", "agent"),
        ("tool_record_refs", ("api:research_os.platform.spine_bindings.other",)),
        (
            "evidence_refs",
            ("math_spine_chain:m1-policy", "rgcmd:m1-policy:other-history"),
        ),
    ),
)
def test_binding_command_provenance_must_be_exact(field, value):
    world = _World()
    setattr(world.binding_commands["M1-M2"], field, value)
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(
        world.context()
    )

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match=r"binding command (?:provenance mismatch|does not name)",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M1-M2",
            anchor_ref=world.anchors["M1-M2"],
        )


@pytest.mark.parametrize("row", tuple(_ROW_QRO_REFS))
def test_each_row_exposes_binding_and_historical_business_lineage(row):
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    result = resolver.resolve(
        owner_user_id=OWNER,
        m_row=row,
        anchor_ref=world.anchors[row],
    )
    metadata = dict(result.row_policy_metadata)

    assert result.business_entrypoint_ref == BINDING_ENTRYPOINTS[row]
    assert metadata["graph_command_ref"] == world.binding_commands[row].command_id
    assert metadata["binding_projection_ref"] == (
        world.binding_projections[row].projection_ref
    )
    assert metadata["business_graph_command_ref"] == (
        world.business_commands[row].command_id
    )
    assert metadata["business_entrypoint_ref"] == BUSINESS_ENTRYPOINTS[row]
    assert metadata["business_entry_source"] == "api"
    assert world.business_qros[row].mathematical_refs == ()
    assert world.binding_qros[row].mathematical_refs == (
        result.math_spine_ref,
    )


@pytest.mark.parametrize("row", ("M1-M2", "M4-M5", "M6", "M7-M8"))
def test_immutable_business_linkage_never_rewrites_to_binding_command(row):
    world = _World()
    binding_ref = world.binding_commands[row].command_id
    if row == "M1-M2":
        anchor = world.anchors[row]
        world.design.hypotheses[(OWNER, anchor)].linkage.research_graph_ref = binding_ref
    elif row == "M4-M5":
        anchor = world.anchors[row]
        world.design.factors[(OWNER, anchor)].linkage.research_graph_ref = binding_ref
    elif row == "M6":
        anchor = world.anchors[row]
        job_id = world.passports.rows[(OWNER, anchor)].validation_dossier_ref.removeprefix(
            "validation_dossier:"
        )
        world.training.rows[job_id].research_graph_command_id = binding_ref
    else:
        anchor = world.anchors[row]
        world.design.policies[(OWNER, anchor)].linkage.research_graph_ref = binding_ref
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match="immutable business linkage mismatch",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.anchors[row],
        )


@pytest.mark.parametrize("row", tuple(_ROW_QRO_REFS))
@pytest.mark.parametrize("history", ("missing", "ambiguous"))
def test_each_row_requires_exactly_one_historical_business_head(row, history):
    world = _World()
    business = world.business_commands[row]
    if history == "missing":
        world.graph.command_rows[:] = [
            item for item in world.graph.command_rows if item is not business
        ]
        world.compiler.ir_rows[:] = [
            item
            for item in world.compiler.ir_rows
            if item.graph_command_refs != (business.command_id,)
        ]
        world.compiler.pass_rows[:] = [
            item
            for item in world.compiler.pass_rows
            if item.graph_command_refs != (business.command_id,)
        ]
    else:
        duplicate = SimpleNamespace(
            command_id=f"{business.command_id}:ambiguous",
            actor=business.actor,
            source=business.source,
            payload={"qro": world.business_qros[row]},
        )
        world.graph.command_rows.append(duplicate)
        world.compiler.add(
            world.business_qros[row],
            duplicate.command_id,
            chain_ref=None,
            entrypoint=BUSINESS_ENTRYPOINTS[row],
            suffix=f"{row.lower()}-business-ambiguous",
        )
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match="historical business command is missing or ambiguous",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.anchors[row],
        )


@pytest.mark.parametrize("row", tuple(_ROW_QRO_REFS))
def test_each_row_rejects_wrong_binding_compiler_entrypoint(row):
    world = _World()
    command_ref = world.binding_commands[row].command_id
    compiler_ir = next(
        item
        for item in world.compiler.ir_rows
        if item.graph_command_refs == (command_ref,)
    )
    compiler_pass = next(
        item
        for item in world.compiler.pass_rows
        if item.graph_command_refs == (command_ref,)
    )
    wrong = tuple(
        "entrypoint:api:research_os.platform.spine_bindings.wrong"
        if str(item).startswith("entrypoint:")
        else item
        for item in compiler_ir.canonical_command_refs
    )
    compiler_ir.canonical_command_refs = wrong
    compiler_pass.canonical_command_refs = wrong
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match="current binding compiler entrypoint mismatch",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.anchors[row],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("projection_math", "authenticated API binding head"),
        ("foreign_actor", "current projection"),
        ("foreign_owner", "current projected QRO"),
        ("stale_projection", "stale QRO/Graph lineage"),
        ("ambiguous_projection", "ambiguous current projections"),
        ("non_math_identity", "fields other than mathematical_refs"),
    ),
)
def test_binding_head_rejects_projection_drift_and_non_math_recombination(
    mutation,
    message,
):
    world = _World()
    row = "M1-M2"
    projection = world.binding_projections[row]
    if mutation == "projection_math":
        projection.mathematical_refs = ("math_spine_chain:same-owner-unrelated",)
    elif mutation == "foreign_actor":
        world.binding_commands[row].actor = OTHER_OWNER
    elif mutation == "foreign_owner":
        projection.owner = OTHER_OWNER
    elif mutation == "stale_projection":
        projection.command_id = world.business_commands[row].command_id
    elif mutation == "ambiguous_projection":
        duplicate = SimpleNamespace(**vars(projection))
        duplicate.projection_ref = f"{projection.projection_ref}:ambiguous"
        world.graph.projection_rows.append(duplicate)
    else:
        world.binding_qros[row].implementation_hash = "implementation:recombined"
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    with pytest.raises(PlatformSourceLineagePolicyM1M8Error, match=message):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.anchors[row],
        )


@pytest.mark.parametrize("row", tuple(_ROW_QRO_REFS))
def test_each_row_rejects_recombined_historical_business_entrypoint(row):
    world = _World()
    command_ref = world.business_commands[row].command_id
    compiler_ir = next(
        item
        for item in world.compiler.ir_rows
        if item.graph_command_refs == (command_ref,)
    )
    compiler_pass = next(
        item
        for item in world.compiler.pass_rows
        if item.graph_command_refs == (command_ref,)
    )
    wrong = tuple(
        "entrypoint:api:same-owner-unrelated"
        if str(item).startswith("entrypoint:")
        else item
        for item in compiler_ir.canonical_command_refs
    )
    compiler_ir.canonical_command_refs = wrong
    compiler_pass.canonical_command_refs = wrong
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    with pytest.raises(
        PlatformSourceLineagePolicyM1M8Error,
        match="historical business compiler lineage mismatch",
    ):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.anchors[row],
        )


def test_binding_policy_resolution_is_read_only():
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    def snapshot():
        return (
            tuple(item.command_id for item in world.graph.command_rows),
            tuple(item.projection_ref for item in world.graph.projection_rows),
            tuple(sorted(world.graph.qro_by_ref)),
            tuple(item.ir_ref for item in world.compiler.ir_rows),
            tuple(item.pass_ref for item in world.compiler.pass_rows),
            tuple(item.chain_ref for item in world.spines.rows),
        )

    before = snapshot()
    for row in _ROW_QRO_REFS:
        resolver.resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=world.anchors[row],
        )

    assert snapshot() == before


def test_group_resolver_rejects_cross_owner_stale_source_and_ambiguous_recombination():
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())

    with pytest.raises(PlatformSourceLineagePolicyM1M8Error, match="typed anchor lookup"):
        resolver.resolve(
            owner_user_id="other-owner",
            m_row="M1-M2",
            anchor_ref=world.anchors["M1-M2"],
        )

    factor = world.factors.rows[("momentum-policy", 1)]
    factor.formula = "close / delay(close, 20) - 1"
    with pytest.raises(PlatformSourceLineagePolicyM1M8Error, match="stale or recombined"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M4-M5",
            anchor_ref=world.anchors["M4-M5"],
        )

    skill = world.onboarding.skills[(OWNER, "ingestion_skill:bars-policy:v1")]
    world.market.instrument_rows[OWNER].append(
        InstrumentSpec(
            instrument_ref="instrument:ETHUSDT-policy",
            asset_class="crypto_spot",
            instrument_type="spot",
            currency="USDT",
            exchange_calendar_ref="calendar:crypto:247",
            symbol_mapping_ref=skill.schema_mapping_ref,
        )
    )
    with pytest.raises(PlatformSourceLineagePolicyM1M8Error, match="InstrumentSpec"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M3",
            anchor_ref=world.anchors["M3"],
        )


def test_group_resolver_rejects_unsupported_row_and_policy_semantic_recombination():
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())
    with pytest.raises(PlatformSourceLineagePolicyM1M8Error, match="unsupported"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M9",
            anchor_ref="execution_boundary:unrelated",
        )

    resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M1-M2",
        anchor_ref=world.anchors["M1-M2"],
    )
    metadata = dict(resolution.row_policy_metadata)
    capability = PlatformCapabilityRecord(
        m_row=resolution.m_row,
        qro_ref=resolution.qro_ref,
        research_graph_ref=metadata["graph_command_ref"],
        lifecycle_ref="hypothesis_card:other-same-owner",
        governance_ref="goal_validation_receipt:m1-policy",
        rag_ref="ragdoc:m1-policy",
        math_spine_ref=resolution.math_spine_ref,
        evidence_refs=("evidence:m1-policy",),
        specific_refs=resolution.specific_refs,
    )
    coverage = SimpleNamespace(
        recorded_by=OWNER,
        entry_source="api",
        entrypoint_ref=resolution.business_entrypoint_ref,
        qro_refs=(resolution.qro_ref,),
        research_graph_command_refs=(metadata["graph_command_ref"],),
        compiler_ir_refs=(metadata["compiler_ir_ref"],),
        compiler_pass_refs=(metadata["compiler_pass_ref"],),
    )
    rag = SimpleNamespace(
        asset_ref=resolution.primary_rag_asset_ref,
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(resolution.primary_rag_asset_ref,),
        ),
    )

    violations = resolver.semantic_violations(
        resolution,
        owner_user_id=OWNER,
        business_coverage=coverage,
        capability_record=capability,
        rag_document=rag,
    )

    assert "capability lifecycle mismatch" in violations


def test_policy_semantics_reject_stale_binding_coverage_refs():
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())
    resolution = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M3",
        anchor_ref=world.anchors["M3"],
    )
    metadata = dict(resolution.row_policy_metadata)
    coverage = SimpleNamespace(
        recorded_by=OWNER,
        entry_source=resolution.business_entry_source,
        entrypoint_ref=resolution.business_entrypoint_ref,
        qro_refs=(resolution.qro_ref,),
        research_graph_command_refs=(metadata["business_graph_command_ref"],),
        compiler_ir_refs=(metadata["compiler_ir_ref"],),
        compiler_pass_refs=(metadata["compiler_pass_ref"],),
    )
    capability = PlatformCapabilityRecord(
        m_row=resolution.m_row,
        qro_ref=resolution.qro_ref,
        research_graph_ref=metadata["graph_command_ref"],
        lifecycle_ref=resolution.lifecycle_ref,
        governance_ref="goal_validation_receipt:m3-policy",
        rag_ref="ragdoc:m3-policy",
        math_spine_ref=resolution.math_spine_ref,
        evidence_refs=("evidence:m3-policy",),
        specific_refs=resolution.specific_refs,
    )
    rag = SimpleNamespace(
        asset_ref=resolution.primary_rag_asset_ref,
        permission=SimpleNamespace(
            allowed_users=(OWNER,),
            allowed_assets=(resolution.primary_rag_asset_ref,),
        ),
    )

    violations = resolver.semantic_violations(
        resolution,
        owner_user_id=OWNER,
        business_coverage=coverage,
        capability_record=capability,
        rag_document=rag,
    )

    assert "business coverage research_graph_command_refs mismatch" in violations


def test_m1_positive_uses_persistent_design_and_lifecycle_owner_stores(tmp_path):
    world = _World()
    world.graph = _Graph()
    world.compiler = _Compiler()
    anchor = "hypothesis_card:persistent-policy"
    goal = _Goal("persistent-policy-goal", "Persistent goal")
    goal_ref = f"strategy_goal:{goal.goal_id}"
    card = _Card("persistent-policy", goal_ref, "persistent falsifiable claim")
    qro_ref = "qro:m1-persistent-policy"
    graph_ref = "rgcmd:m1-persistent-policy"
    chain_ref = "math_spine_chain:m1-persistent-policy"
    linkage = ResearchDesignLinkage(
        qro_ref=qro_ref,
        research_graph_ref=graph_ref,
        lifecycle_ref=anchor,
    )
    design = PersistentResearchDesignAssetRegistry(tmp_path / "research_design.jsonl")
    universe = design.record(
        make_universe_definition_record(
            {
                "id": "persistent-policy-universe",
                "name": "Persistent policy universe",
                "market": "binanceusdm",
                "rules": {
                    "market": "binanceusdm",
                    "static_symbols": ["BTCUSDT"],
                },
            },
            owner_user_id=OWNER,
            linkage=linkage,
        )
    )
    regime = design.record(
        make_regime_scenario_record(
            owner_user_id=OWNER,
            universe_definition_ref=universe.universe_definition_ref,
            scenario={
                "name": "persistent-volatility",
                "detector": "realized_volatility",
                "config": {"window": 20, "threshold": 0.8},
            },
            linkage=linkage,
        )
    )
    design.record(
        make_hypothesis_envelope(
            card,
            owner_user_id=OWNER,
            strategy_goal_ref=goal_ref,
            universe_definition_ref=universe.universe_definition_ref,
            regime_scenario_ref=regime.regime_scenario_ref,
            linkage=linkage,
        )
    )
    lifecycle = PersistentAssetLifecycleRegistry(tmp_path / "lifecycle.jsonl")
    lifecycle.record_governed_asset(
        GovernedAssetRecord(
            asset_ref=anchor,
            asset_type="HypothesisCard",
            category="user_asset",
            lifecycle_state="specified",
            evidence_refs=(qro_ref, graph_ref, anchor),
            validation_plan_ref=f"validation_plan:{anchor}",
            promotion_history=(),
        ),
        owner_user_id=OWNER,
    )
    world.goals.rows[goal.goal_id] = goal
    world.cards.rows[card.card_id] = card
    qro = SimpleNamespace(
        qro_id=qro_ref,
        qro_type="QuantIntent",
        owner=OWNER,
        mathematical_refs=(chain_ref,),
        output_contract={
            "strategy_goal_ref": goal_ref,
            "strategy_goal_hash": source_object_hash(goal),
            "hypothesis_card_ref": anchor,
            "universe_definition_ref": universe.universe_definition_ref,
            "regime_scenario_ref": regime.regime_scenario_ref,
        },
    )
    world.spines.rows.append(
        SimpleNamespace(
            chain_ref=chain_ref,
            recorded_by=OWNER,
            validation_refs=(goal_ref, anchor),
            evidence_refs=(
                universe.universe_definition_ref,
                regime.regime_scenario_ref,
            ),
        )
    )
    world._record_split_lineage(
        row="M1-M2",
        qro=qro,
        business_graph_ref=graph_ref,
        chain_ref=chain_ref,
        business_entrypoint="api:hypothesis_cards",
        binding_entrypoint=M1_M2_SPINE_BINDING_ENTRYPOINT_REF,
    )
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(
        world.context(design=design, lifecycle=lifecycle)
    )

    result = resolver.resolve(
        owner_user_id=OWNER,
        m_row="M1-M2",
        anchor_ref=anchor,
    )

    assert result.anchor_ref == anchor
    assert result.qro_ref == qro_ref
    assert result.lifecycle_ref == anchor
    assert dict((item.key, item.ref) for item in result.specific_refs) == {
        "strategy_goal_ref": goal_ref,
        "hypothesis_card_ref": anchor,
        "universe_definition_ref": universe.universe_definition_ref,
        "regime_scenario_ref": regime.regime_scenario_ref,
    }


class _StrictCoverageLifecycleLoader:
    def __init__(self, lifecycle: PersistentAssetLifecycleRegistry) -> None:
        self._lifecycle = lifecycle

    def __call__(self, ref: str, owner: str):
        asset = self._lifecycle.governed_asset(ref, owner_user_id=owner)
        return SimpleNamespace(
            lifecycle_ref=asset.asset_ref,
            owner_user_id=owner,
            recorded_by=owner,
            governed_asset=asset,
        )


def _m4_chain_candidate(*, factor_ref: str, label_ref: str) -> MathematicalSpineChainRecord:
    return MathematicalSpineChainRecord(
        chain_ref="math_spine_chain:pending",
        data_semantics_ref="dataset:m4-policy-integration:v1",
        factor_ref=factor_ref,
        model_ref="model:m4-policy-integration:none",
        forecast_ref="forecast:m4-policy-integration:none",
        signal_contract_ref="signal_contract:m4-policy-integration:none",
        strategy_book_ref="strategy_book:m4-policy-integration:none",
        portfolio_policy_ref="portfolio_policy:m4-policy-integration:none",
        risk_policy_ref="risk_policy:m4-policy-integration:none",
        execution_policy_ref="execution_policy:m4-policy-integration:offline",
        backtest_run_ref="backtest_run:m4-policy-integration:none",
        attribution_ref="attribution:m4-policy-integration:none",
        monitor_ref="monitor:m4-policy-integration:none",
        theory_binding_refs=("theory_binding:pending",),
        consistency_check_refs=("consistency_check:pending",),
        methodology_choice_ref="methodology_choice:pending",
        responsibility_boundary_ref="responsibility:pending",
        evidence_refs=(factor_ref,),
        validation_refs=(label_ref,),
        consistency_verdict=ConsistencyStatus.ACCEPTED,
        target_runtime=RuntimeStatus.OFFLINE,
        recorded_by=OWNER,
    )


def _m4_finalizer_system(tmp_path):
    evidence_ref = "evidence:m4-policy-finalizer"
    permission_ref = "permission:m4-policy-finalizer"
    business_entrypoint_ref = "api:factors"
    entrypoint_ref = M4_M5_SPINE_BINDING_ENTRYPOINT_REF
    factors = FactorRegistry(tmp_path / "factors.json")
    factor = factors.register(
        "policy_finalizer_factor",
        "close / delay(close, 5) - 1",
        author=OWNER,
    )
    factor_ref = f"factor:{factor.factor_id}:v{factor.version}"
    formula_hash = content_hash({"formula": factor.formula})

    design = PersistentResearchDesignAssetRegistry(tmp_path / "research_design.jsonl")
    label = design.record(
        make_label_definition_record(
            owner_user_id=OWNER,
            label_kind="time_series",
            output_column="forward_return_5d",
            horizon=5,
            parameters={"price_column": "close"},
            known_at_rule="known after the five-day horizon closes",
            effective_at_rule="effective at the forecast origin",
            linkage=ResearchDesignLinkage(
                qro_ref="qro:m4-policy-label",
                research_graph_ref="rgcmd:m4-policy-label",
                lifecycle_ref="lifecycle:m4-policy-label",
            ),
        )
    )
    spine, chain, _ledger = build_verified_spine_chain(
        tmp_path / "spine",
        _m4_chain_candidate(factor_ref=factor_ref, label_ref=label.label_ref),
    )
    graph = PersistentResearchGraphStore(tmp_path / "research_graph.jsonl")
    qro = QRORecord(
        qro_type=QROType.FACTOR,
        owner=OWNER,
        actor=ActorSource.USER_MANUAL,
        input_contract={
            "factor_id": factor.factor_id,
            "version": factor.version,
            "formula_hash": formula_hash,
        },
        output_contract={
            "factor_ref": factor_ref,
            "label_ref": label.label_ref,
            "lifecycle_state": factor.lifecycle_state,
        },
        market="unspecified",
        universe=factor_ref,
        horizon="factor_formula",
        frequency="factor_formula",
        lineage=("factor_registry", factor_ref, f"formula_hash:{formula_hash}"),
        implementation_hash="factor_register:"
        + content_hash(
            {
                "factor_id": factor.factor_id,
                "version": factor.version,
                "formula_hash": formula_hash,
            }
        ),
        assumptions=("the formula is a persisted research definition",),
        known_limits=("factor registration is not alpha validation",),
        failure_modes=("formula or label drift invalidates this lineage",),
        validation_plan=("bind the exact factor, label, and Mathematical Spine",),
        definition_status=DefinitionStatus.IMPLEMENTED,
        evidence_status=EvidenceStatus.EXPLORATORY,
        runtime_status=RuntimeStatus.OFFLINE,
        evidence_refs=(factor_ref, evidence_ref),
        mathematical_refs=(),
        permission=permission_ref,
        allowed_environment=RuntimeStatus.OFFLINE,
    )
    command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": qro},
        evidence_refs=qro.evidence_refs,
        tool_record_refs=(business_entrypoint_ref, factor_ref),
    )
    graph.apply(command)
    bound_qro = replace(qro, mathematical_refs=(chain.chain_ref,))
    binding_command = ResearchGraphCommand(
        source=EntrySource.API,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": bound_qro},
        evidence_refs=(chain.chain_ref, command.command_id),
        tool_record_refs=(entrypoint_ref,),
    )
    graph.apply(binding_command)
    lifecycle = PersistentAssetLifecycleRegistry(tmp_path / "asset_lifecycle.jsonl")
    lifecycle.record_governed_asset(
        GovernedAssetRecord(
            asset_ref=factor_ref,
            asset_type="Factor",
            category="user_asset",
            lifecycle_state="specified",
            evidence_refs=(factor_ref, qro.qro_id, command.command_id),
            validation_plan_ref=f"validation_plan:{factor_ref}",
            promotion_history=(),
        ),
        owner_user_id=OWNER,
    )
    design.record(
        make_factor_envelope(
            factor,
            owner_user_id=OWNER,
            label_ref=label.label_ref,
            linkage=ResearchDesignLinkage(
                qro_ref=qro.qro_id,
                research_graph_ref=command.command_id,
                lifecycle_ref=factor_ref,
            ),
        )
    )

    receipts = PersistentGoalValidationReceiptRegistry(
        tmp_path / "goal_validation_receipts.jsonl"
    )
    provisional = GoalValidationReceipt(
        validation_ref="",
        owner_user_id=OWNER,
        subject_qro_refs=(qro.qro_id,),
        graph_command_refs=(binding_command.command_id,),
        validator_identifiers=("runtime_validator:m4_policy_finalizer_v1",),
        test_identifiers=("runtime_check:m4_policy_finalizer",),
        outcome=GoalValidationOutcome.PASSED,
        evidence_refs=(evidence_ref,),
        evidence_digests=(
            "sha256:" + hashlib.sha256(evidence_ref.encode("utf-8")).hexdigest(),
        ),
    )
    receipt = receipts.record_receipt(
        replace(
            provisional,
            validation_ref=provisional.canonical_validation_ref,
        )
    )
    compiler = _LegacyTestCompilerStore(tmp_path / "compiler.jsonl")
    business_canonical_refs = (
        f"research_graph_command:{command.command_id}",
        f"entrypoint:{business_entrypoint_ref}",
    )
    business_ir = compiler.record_ir(
        CompilerIRRecord(
            ir_ref="compiler_ir:m4-policy-finalizer:business",
            source_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            canonical_command_refs=business_canonical_refs,
            node_refs=(
                f"qro:{qro.qro_id}",
                f"entrypoint:{business_entrypoint_ref}",
            ),
            edge_refs=(),
            artifact_refs=(factor_ref,),
            theory_binding_refs=(),
            consistency_check_refs=(),
            evidence_refs=(evidence_ref,),
            validation_refs=(receipt.validation_ref,),
            permission_ref=permission_ref,
            deterministic_run_plan_ref="runplan:m4-policy-finalizer:business",
            rollback_ref="rollback:m4-policy-finalizer:business",
            environment_lock_ref="env:m4-policy-finalizer:business:v1",
            mathematical_spine_chain_refs=(),
            owner=OWNER,
            target_runtime=RuntimeStatus.OFFLINE,
            mock_profile="none",
        )
    )
    compiler.record_pass(
        CompilerPassRecord(
            pass_ref="compiler_pass:m4-policy-finalizer:business",
            pass_name="api_factor_business_qro_to_factor_ir",
            input_ir_refs=(),
            output_ir_ref=business_ir.ir_ref,
            input_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            canonical_command_refs=business_canonical_refs,
            actor=OWNER,
            actor_source=ActorSource.USER_MANUAL,
            entry_source=EntrySource.API,
            permission_ref=permission_ref,
            tool_record_refs=(business_entrypoint_ref, factor_ref),
            evidence_refs=(evidence_ref,),
            validation_refs=(receipt.validation_ref,),
            deterministic_run_plan_ref=business_ir.deterministic_run_plan_ref,
            rollback_ref=business_ir.rollback_ref,
        )
    )
    canonical_refs = (
        f"research_graph_command:{binding_command.command_id}",
        f"entrypoint:{entrypoint_ref}",
    )
    coverage_ref = goal_entrypoint_coverage_identity(
        entry_source=EntrySource.API,
        entrypoint_ref=entrypoint_ref,
        goal_sections=("§1",),
        qro_refs=(qro.qro_id,),
        research_graph_command_refs=(binding_command.command_id,),
        compiler_ir_refs=("compiler_ir:m4-policy-finalizer",),
        compiler_pass_refs=("compiler_pass:m4-policy-finalizer",),
    )
    evidence_registry = PersistentEntrypointEvidenceRegistry(
        tmp_path / "entrypoint_evidence.jsonl",
        research_graph_store=graph,
        compiler_store=compiler,
        validation_receipt_registry=receipts,
    )
    entrypoint_evidence = evidence_registry.prepare_record(
        owner_user_id=OWNER,
        entry_source=EntrySource.API.value,
        entrypoint_ref=entrypoint_ref,
        goal_sections=("§1",),
        qro_ref=qro.qro_id,
        research_graph_ref=binding_command.command_id,
        validation_ref=receipt.validation_ref,
        compiler_ir_ref="compiler_ir:m4-policy-finalizer",
        compiler_pass_ref="compiler_pass:m4-policy-finalizer",
        coverage_ref=coverage_ref,
        actor_source=ActorSource.USER_MANUAL.value,
        pass_name="api_factor_qro_to_factor_ir",
        permission_ref=permission_ref,
        environment_lock_ref="env:m4-policy-finalizer:v1",
        deterministic_run_plan_ref="runplan:m4-policy-finalizer",
        rollback_ref="rollback:m4-policy-finalizer",
        lifecycle_refs=(factor_ref,),
        mathematical_spine_chain_refs=(chain.chain_ref,),
    )
    entrypoint_evidence = evidence_registry.record_evidence(entrypoint_evidence)
    ir = compiler.record_ir(
        CompilerIRRecord(
            ir_ref="compiler_ir:m4-policy-finalizer",
            source_qro_refs=(qro.qro_id,),
            graph_command_refs=(binding_command.command_id,),
            canonical_command_refs=canonical_refs,
            node_refs=(f"qro:{qro.qro_id}", f"entrypoint:{entrypoint_ref}"),
            edge_refs=(),
            artifact_refs=(factor_ref,),
            theory_binding_refs=(),
            consistency_check_refs=(),
            evidence_refs=(entrypoint_evidence.evidence_ref,),
            validation_refs=(receipt.validation_ref,),
            permission_ref=permission_ref,
            deterministic_run_plan_ref="runplan:m4-policy-finalizer",
            rollback_ref="rollback:m4-policy-finalizer",
            environment_lock_ref="env:m4-policy-finalizer:v1",
            mathematical_spine_chain_refs=(chain.chain_ref,),
            owner=OWNER,
            target_runtime=RuntimeStatus.OFFLINE,
            mock_profile="none",
        )
    )
    compiler_pass = compiler.record_pass(
        CompilerPassRecord(
            pass_ref="compiler_pass:m4-policy-finalizer",
            pass_name="api_factor_qro_to_factor_ir",
            input_ir_refs=(),
            output_ir_ref=ir.ir_ref,
            input_qro_refs=(qro.qro_id,),
            graph_command_refs=(binding_command.command_id,),
            canonical_command_refs=canonical_refs,
            actor=OWNER,
            actor_source=ActorSource.USER_MANUAL,
            entry_source=EntrySource.API,
            permission_ref=permission_ref,
            tool_record_refs=(entrypoint_ref, factor_ref),
            evidence_refs=(entrypoint_evidence.evidence_ref,),
            validation_refs=(receipt.validation_ref,),
            deterministic_run_plan_ref=ir.deterministic_run_plan_ref,
            rollback_ref=ir.rollback_ref,
        )
    )
    rag = PersistentResearchAssetRAGIndex(tmp_path / "research_asset_rag.jsonl")
    strict_resolver = build_real_ref_resolver(
        research_graph_store=graph,
        lifecycle_registry=object(),
        governance_registry=None,
        rag_index=rag,
        spine_chain_registry=spine,
        compiler_store=compiler,
        goal_validation_receipt_registry=receipts,
        platform_source_evidence_registry=evidence_registry,
        lifecycle_loaders=(_StrictCoverageLifecycleLoader(lifecycle),),
    )
    entrypoints = PersistentGoalEntrypointCoverageRegistry(
        tmp_path / "goal_entrypoint_coverage.jsonl",
        resolver=strict_resolver,
    )
    business = entrypoints.record_coverage(
        GoalEntrypointCoverageRecord(
            coverage_ref=coverage_ref,
            entry_source=EntrySource.API,
            entrypoint_ref=entrypoint_ref,
            goal_sections=("§1",),
            qro_refs=(qro.qro_id,),
            research_graph_command_refs=(binding_command.command_id,),
            compiler_ir_refs=(ir.ir_ref,),
            compiler_pass_refs=(compiler_pass.pass_ref,),
            evidence_refs=(entrypoint_evidence.evidence_ref,),
            validation_refs=(receipt.validation_ref,),
            permission_refs=(permission_ref,),
            replay_refs=(
                f"replay:research_graph:{binding_command.command_id}",
                f"replay:compiler_ir:{ir.ir_ref}",
                f"replay:compiler_pass:{compiler_pass.pass_ref}",
            ),
            canonical_command_refs=canonical_refs,
            lifecycle_refs=(factor_ref,),
            recorded_by=OWNER,
            claims_full_product_entrypoint=False,
            silent_mock_fallback_used=False,
            raw_payload_persisted=False,
        )
    )
    adapters, validators = build_platform_source_adapters_m1_m8(
        PlatformSourceAdaptersM1M8Context(
            research_design_registry=design,
            factor_registry=factors,
            research_graph_store=graph,
            asset_lifecycle_registry=lifecycle,
            rag_index=rag,
            spine_chain_registry=spine,
        )
    )

    def load_lifecycle(ref: str, owner: str, _record):
        return lifecycle.governed_asset(ref, owner_user_id=owner)

    typed = RealPlatformTypedSourceResolver(
        research_graph_store=graph,
        lifecycle_loaders=(load_lifecycle,),
        goal_validation_receipt_registry=receipts,
        rag_index=rag,
        spine_chain_registry=spine,
        compiler_store=compiler,
        specific_adapters=adapters,
        row_validators=validators,
    )
    rows = PersistentPlatformRowSourceRegistry(
        tmp_path / "platform_row_sources.jsonl",
        entrypoint_registry=entrypoints,
        rag_index=rag,
        source_resolver=typed,
    )
    world = _World()
    policy = build_platform_source_lineage_policy_resolver_m1_m8(
        world.context(
            graph=graph,
            compiler=compiler,
            spines=spine,
            design=design,
            lifecycle=lifecycle,
            factors=factors,
        )
    )
    finalizer = PlatformSourceLineageFinalizer(
        policy_resolver=policy,
        entrypoint_registry=entrypoints,
        rag_index=rag,
        row_source_registry=rows,
        source_resolver=typed,
    )
    return SimpleNamespace(
        factor=factor,
        factor_ref=factor_ref,
        formula_hash=formula_hash,
        label_ref=label.label_ref,
        business=business,
        entrypoints=entrypoints,
        rag=rag,
        rows=rows,
        finalizer=finalizer,
    )


def test_m4_finalizer_policy_drift_is_prewrite_then_closes_three_real_ledgers(tmp_path):
    system = _m4_finalizer_system(tmp_path)
    original_formula = system.factor.formula
    coverage_before = len(system.entrypoints.records(owner=OWNER))
    rag_before = len(system.rag.owned_documents(owner_user_id=OWNER))
    rows_before = len(system.rows.current_certifications(owner_user_id=OWNER))
    system.factor.formula = "close / delay(close, 20) - 1"

    with pytest.raises(PlatformSourceLineageCoreError, match="policy resolution failed"):
        system.finalizer.record_current(
            owner_user_id=OWNER,
            m_row="M4-M5",
            anchor_ref=system.factor_ref,
        )

    assert len(system.entrypoints.records(owner=OWNER)) == coverage_before
    assert len(system.rag.owned_documents(owner_user_id=OWNER)) == rag_before
    assert len(system.rows.current_certifications(owner_user_id=OWNER)) == rows_before

    system.factor.formula = original_formula
    result = system.finalizer.record_current(
        owner_user_id=OWNER,
        m_row="M4-M5",
        anchor_ref=system.factor_ref,
    )

    assert result.business_coverage_ref == system.business.coverage_ref
    assert result.coverage.goal_sections == ("§14",)
    assert result.rag_document.source_id == "platform_source_lineage:M4-M5"
    assert result.rag_document.metadata["formula_hash"] == system.formula_hash
    assert result.rag_document.metadata["row_policy"]["formula_hash"] == system.formula_hash
    assert result.certification.resolved_row.record.m_row == "M4-M5"
    assert result.certification.resolved_row.record.rag_ref == result.rag_document.document_id
    assert len(system.entrypoints.records(owner=OWNER)) == coverage_before + 1
    assert len(system.rag.owned_documents(owner_user_id=OWNER)) == rag_before + 1
    assert len(system.rows.current_certifications(owner_user_id=OWNER)) == rows_before + 1


def test_m7_policy_source_hash_recombination_is_rejected():
    world = _World()
    resolver = build_platform_source_lineage_policy_resolver_m1_m8(world.context())
    anchor = world.anchors["M7-M8"]
    policy = world.design.policies[(OWNER, anchor)]
    world.design.policies[(OWNER, anchor)] = replace(
        policy,
        strategy_book_source_hash="different-source-hash",
    ) if hasattr(policy, "__dataclass_fields__") else SimpleNamespace(
        **{
            **vars(policy),
            "strategy_book_source_hash": "different-source-hash",
        }
    )

    with pytest.raises(PlatformSourceLineagePolicyM1M8Error, match="stale or recombined"):
        resolver.resolve(
            owner_user_id=OWNER,
            m_row="M7-M8",
            anchor_ref=anchor,
        )
