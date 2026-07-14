from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from inspect import signature
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any

import pytest

from app.copy_trade.service import Follower, copy_trade_subscription_ref
from app.lineage.ids import content_hash
from app.research_os.compiler import (
    CompilerIRRecord,
    CompilerPassRecord,
    PersistentCompilerIRStore,
)
from app.research_os.goal_coverage import (
    GoalEntrypointCoverageRecord,
    PersistentGoalEntrypointCoverageRegistry,
    goal_entrypoint_coverage_identity,
)
from app.research_os.platform_business_attestations import (
    ENTRYPOINT_REFS,
    PlatformBusinessAttestationCommitError,
    PlatformBusinessAttestationContext,
    PlatformBusinessAttestationError,
    PlatformBusinessAttestationService,
    record_platform_business_attestation,
)
from app.research_os.platform_source_lineage_policies_m16_m21 import (
    PlatformSourceLineagePoliciesM16M21Context,
    build_platform_source_lineage_policy_resolver_m16_m21,
)
from app.research_os.spine import (
    ActorSource,
    EntrySource,
    QRORecord,
    QROType,
    ResearchGraphCommand,
    ResearchGraphDurabilityError,
    ResearchGraphError,
    ResearchGraphProjectionRecord,
    ResearchGraphStore,
    PersistentResearchGraphStore,
)


OWNER = "owner:platform-business-attestation"


class _Chains:
    def __init__(self, *chains: Any) -> None:
        self.current = list(chains)

    def chains(self, *, owner: str | None = None):
        if owner is None:
            return list(self.current)
        return [chain for chain in self.current if chain.recorded_by == owner]

    def verified_chain(self, ref: str, *, owner: str | None = None):
        matches = [
            chain
            for chain in self.current
            if chain.chain_ref == ref and (owner is None or chain.recorded_by == owner)
        ]
        if len(matches) != 1:
            raise KeyError(ref)
        return matches[0]


class _CompilerStore:
    def __init__(self) -> None:
        self._irs: dict[tuple[str, str], CompilerIRRecord] = {}
        self._passes: dict[tuple[str, str], CompilerPassRecord] = {}

    def put_ir(self, record: CompilerIRRecord) -> None:
        key = (record.owner, record.ir_ref)
        existing = self._irs.get(key)
        if existing is not None and existing != record:
            raise ValueError("IR collision")
        self._irs[key] = record

    def put_pass(self, record: CompilerPassRecord) -> None:
        key = (record.actor, record.pass_ref)
        existing = self._passes.get(key)
        if existing is not None and existing != record:
            raise ValueError("pass collision")
        self._passes[key] = record

    def ir(self, ref: str, *, owner: str | None = None):
        if owner is None:
            matches = [record for (_owner, key), record in self._irs.items() if key == ref]
            if len(matches) != 1:
                raise KeyError(ref)
            return matches[0]
        return self._irs[(owner, ref)]

    def compiler_pass(self, ref: str, *, owner: str | None = None):
        if owner is None:
            matches = [record for (_owner, key), record in self._passes.items() if key == ref]
            if len(matches) != 1:
                raise KeyError(ref)
            return matches[0]
        return self._passes[(owner, ref)]

    def irs(self, *, owner: str | None = None):
        return [
            record
            for (record_owner, _ref), record in self._irs.items()
            if owner is None or record_owner == owner
        ]

    def passes(self, *, owner: str | None = None):
        return [
            record
            for (record_owner, _ref), record in self._passes.items()
            if owner is None or record_owner == owner
        ]

    def rollback_exact_bundle(
        self,
        *,
        ir: CompilerIRRecord,
        compiler_pass: CompilerPassRecord | None = None,
        owner: str | None = None,
    ) -> bool:
        exact_owner = str(owner or ir.owner)
        ir_key = (exact_owner, ir.ir_ref)
        current_ir = self._irs.get(ir_key)
        if current_ir is None:
            return False
        if current_ir != ir:
            raise ValueError("compiler IR rollback identity mismatch")
        dependent_passes = tuple(
            record
            for (record_owner, _), record in self._passes.items()
            if record_owner == exact_owner and record.output_ir_ref == ir.ir_ref
        )
        if compiler_pass is None:
            if dependent_passes:
                raise ValueError("compiler IR rollback has a dependent pass")
        else:
            pass_key = (exact_owner, compiler_pass.pass_ref)
            if self._passes.get(pass_key) != compiler_pass:
                raise ValueError("compiler pass rollback identity mismatch")
            if dependent_passes != (compiler_pass,):
                raise ValueError("compiler rollback has unexpected dependent passes")
            del self._passes[pass_key]
        del self._irs[ir_key]
        return True


class _CoverageRegistry:
    def __init__(self) -> None:
        self._records: dict[tuple[str, str], GoalEntrypointCoverageRecord] = {}
        self.rejected_proof_refs: set[str] = set()

    def put(self, record: GoalEntrypointCoverageRecord) -> None:
        key = (record.recorded_by, record.coverage_ref)
        existing = self._records.get(key)
        if existing is not None and existing != record:
            raise ValueError("coverage collision")
        self._records[key] = record

    def records(self, *, owner: str | None = None):
        return [
            record
            for (record_owner, _ref), record in self._records.items()
            if owner is None or record_owner == owner
        ]

    def coverage(self, ref: str, *, owner: str | None = None):
        if owner is None:
            matches = [record for (_owner, key), record in self._records.items() if key == ref]
            if len(matches) != 1:
                raise KeyError(ref)
            return matches[0]
        return self._records[(owner, ref)]

    def validate_real_backing(self, record: GoalEntrypointCoverageRecord):
        proof_refs = {
            *tuple(record.evidence_refs),
            *tuple(record.validation_refs),
        }
        return SimpleNamespace(
            accepted=(
                record in self._records.values()
                and not proof_refs.intersection(self.rejected_proof_refs)
            )
        )

    def rollback_exact_coverage(
        self,
        record: GoalEntrypointCoverageRecord,
    ) -> bool:
        key = (record.recorded_by, record.coverage_ref)
        current = self._records.get(key)
        if current is None:
            return False
        if current != record:
            raise ValueError("coverage rollback identity mismatch")
        del self._records[key]
        return True


class _CompilerHarness:
    def __init__(self) -> None:
        self.store = _CompilerStore()
        self.coverage = _CoverageRegistry()
        self.calls = 0
        self.fail_after: str | None = None

    def compile(self, qro, command, plan):
        self.calls += 1
        canonical_refs = tuple(dict.fromkeys((*plan.canonical_command_refs, f"entrypoint:{plan.entrypoint_ref}")))
        ir_ref = "compiler_ir:" + content_hash(
            {
                "qro_ref": qro.qro_id,
                "graph_command_ref": command.command_id,
                "entrypoint_ref": plan.entrypoint_ref,
            }
        )
        pass_ref = "compiler_pass:" + content_hash(
            {"ir_ref": ir_ref, "entrypoint_ref": plan.entrypoint_ref}
        )
        receipt_ref = "goal_validation_receipt:" + content_hash(
            {
                "owner_user_id": plan.owner_user_id,
                "qro_ref": qro.qro_id,
                "graph_command_ref": command.command_id,
                "validation_refs": plan.validation_refs,
            }
        )
        compiler_validation_refs = (
            (receipt_ref,)
            if plan.row == "M18"
            else (*plan.validation_refs, receipt_ref)
        )
        compiler_evidence_refs = (
            "entrypoint_evidence:"
            + content_hash(
                {
                    "owner_user_id": plan.owner_user_id,
                    "qro_ref": qro.qro_id,
                    "graph_command_ref": command.command_id,
                    "compiler_ir_ref": ir_ref,
                    "compiler_pass_ref": pass_ref,
                    "validation_ref": receipt_ref,
                }
            ),
        )
        ir = CompilerIRRecord(
            ir_ref=ir_ref,
            source_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            canonical_command_refs=canonical_refs,
            node_refs=plan.node_refs,
            edge_refs=(),
            artifact_refs=(),
            theory_binding_refs=plan.theory_binding_refs,
            consistency_check_refs=plan.consistency_check_refs,
            evidence_refs=compiler_evidence_refs,
            validation_refs=compiler_validation_refs,
            permission_ref=plan.permission_ref,
            deterministic_run_plan_ref=plan.deterministic_run_plan_ref,
            rollback_ref=plan.rollback_ref,
            environment_lock_ref=plan.environment_lock_ref,
            mathematical_spine_chain_refs=plan.mathematical_spine_chain_refs,
            owner=plan.owner_user_id,
        )
        self.store.put_ir(ir)
        if self.fail_after == "ir":
            raise OSError("compiler stopped after IR append")
        compiler_pass = CompilerPassRecord(
            pass_ref=pass_ref,
            pass_name=plan.pass_name,
            input_ir_refs=(),
            output_ir_ref=ir_ref,
            input_qro_refs=(qro.qro_id,),
            graph_command_refs=(command.command_id,),
            canonical_command_refs=canonical_refs,
            actor=plan.owner_user_id,
            actor_source=ActorSource.USER_MANUAL,
            entry_source=EntrySource.API,
            permission_ref=plan.permission_ref,
            tool_record_refs=(*plan.tool_record_refs, "api:compile_qro"),
            evidence_refs=compiler_evidence_refs,
            validation_refs=compiler_validation_refs,
            deterministic_run_plan_ref=plan.deterministic_run_plan_ref,
            rollback_ref=plan.rollback_ref,
        )
        self.store.put_pass(compiler_pass)
        if self.fail_after == "pass":
            raise OSError("compiler stopped after pass append")
        coverage_ref = goal_entrypoint_coverage_identity(
            entry_source=EntrySource.API,
            entrypoint_ref=plan.entrypoint_ref,
            goal_sections=plan.goal_sections,
            qro_refs=(qro.qro_id,),
            research_graph_command_refs=(command.command_id,),
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
        )
        coverage = GoalEntrypointCoverageRecord(
            coverage_ref=coverage_ref,
            entry_source=EntrySource.API,
            entrypoint_ref=plan.entrypoint_ref,
            goal_sections=plan.goal_sections,
            qro_refs=(qro.qro_id,),
            research_graph_command_refs=(command.command_id,),
            compiler_ir_refs=(ir_ref,),
            compiler_pass_refs=(pass_ref,),
            evidence_refs=compiler_evidence_refs,
            validation_refs=compiler_validation_refs,
            permission_refs=(plan.permission_ref,),
            replay_refs=(
                f"replay:research_graph:{command.command_id}",
                f"replay:compiler_ir:{ir_ref}",
                f"replay:compiler_pass:{pass_ref}",
            ),
            canonical_command_refs=canonical_refs,
            lifecycle_refs=plan.lifecycle_refs,
            rdp_refs=plan.rdp_refs,
            recorded_by=plan.owner_user_id,
        )
        self.coverage.put(coverage)
        return {
            "compiler_ir_ref": ir_ref,
            "compiler_pass_ref": pass_ref,
            "entrypoint_coverage_ref": coverage_ref,
        }


class _ReplayResolver:
    """Strict-store resolver for the persistence replay test only."""

    def __init__(self, graph, compiler, *, owner: str, lifecycle_ref: str) -> None:
        self.graph = graph
        self.compiler = compiler
        self.owner = owner
        self.lifecycle_ref = lifecycle_ref

    def for_owner(self, owner: str):
        if owner != self.owner:
            raise KeyError(owner)
        return self

    def has_qro(self, ref: str) -> bool:
        try:
            return self.graph.qro(ref).owner == self.owner
        except (KeyError, LookupError):
            return False

    def has_research_graph_command(self, ref: str) -> bool:
        return sum(
            command.command_id == ref and command.actor == self.owner
            for command in self.graph.commands()
        ) == 1

    def has_compiler_ir(self, ref: str) -> bool:
        try:
            return self.compiler.ir(ref, owner=self.owner).owner == self.owner
        except (KeyError, LookupError):
            return False

    def has_compiler_pass(self, ref: str) -> bool:
        try:
            return self.compiler.compiler_pass(ref, owner=self.owner).actor == self.owner
        except (KeyError, LookupError):
            return False

    def has_evidence(self, ref: str) -> bool:
        return any(
            ref in tuple(record.evidence_refs)
            for record in (
                *self.compiler.irs(owner=self.owner),
                *self.compiler.passes(owner=self.owner),
            )
        )

    def has_lifecycle_record(self, ref: str) -> bool:
        return ref == self.lifecycle_ref

    def has_rdp(self, _ref: str) -> bool:
        return False

    def entrypoint_linkage_violations(self, _record):
        return ()


def _chain(**overrides):
    values = {
        "chain_ref": "math_spine_chain:business-attestation:v1",
        "recorded_by": OWNER,
        "risk_policy_ref": "copy_risk_check_business",
        "execution_policy_ref": "permission:copy-trade:live",
        "theory_binding_refs": ("tib:business:v1",),
        "consistency_check_refs": ("cc_business_v1",),
        "evidence_refs": ("evidence:business:v1",),
        "validation_refs": ("validation:business:v1",),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _matching_policy_resolution(result):
    return SimpleNamespace(
        m_row=result.row,
        anchor_ref=result.anchor_ref,
        qro_ref=result.qro_ref,
        business_entry_source=EntrySource.API,
        business_entrypoint_ref=result.entrypoint_ref,
        math_spine_ref=result.mathematical_spine_chain_ref,
    )


def _context(
    *,
    graph,
    chain_store,
    harness,
    validate_current_attestation=_matching_policy_resolution,
    **row_dependencies,
):
    return PlatformBusinessAttestationContext(
        research_graph_store=graph,
        compiler_store=harness.store,
        entrypoint_registry=harness.coverage,
        spine_chain_registry=chain_store,
        compile_attestation=harness.compile,
        validate_current_attestation=validate_current_attestation,
        **row_dependencies,
    )


class _UnusedSource:
    def __getattr__(self, name: str):
        def unavailable(*_args, **_kwargs):
            raise AssertionError(f"unused source method called: {name}")

        return unavailable


def _policy_context(system, *, row: str):
    unused = _UnusedSource()
    values = {
        "research_graph_store": system.graph,
        "compiler_store": system.harness.store,
        "entrypoint_registry": system.harness.coverage,
        "spine_chain_registry": system.context.spine_chain_registry,
        "asset_lifecycle_registry": unused,
        "sharing_service": unused,
        "copy_trade_service": unused,
        "runtime_promotion_registry": unused,
        "follower_risk_state_store": unused,
        "execution_order_submission_registry": unused,
        "execution_order_intent_registry": unused,
        "canonical_spine_ledger": unused,
        "rdp_store": unused,
        "teaching_asset_registry": unused,
        "onboarding_registry": unused,
        "llm_call_record_store": unused,
        "account_halt_barrier": unused,
        "llm_service_owner_user_id": OWNER,
    }
    if row == "M17":
        values.update(
            copy_trade_service=system.context.copy_trade_service,
            runtime_promotion_registry=system.context.runtime_promotion_registry,
            follower_risk_state_store=system.context.follower_risk_state_store,
            execution_order_submission_registry=system.context.execution_order_submission_registry,
            execution_order_intent_registry=system.context.execution_order_intent_registry,
        )
    elif row == "M18":
        values.update(
            canonical_spine_ledger=system.context.canonical_spine_ledger,
            rdp_store=system.context.rdp_store,
        )
    elif row == "M20":
        values.update(
            onboarding_registry=system.context.onboarding_registry,
            llm_call_record_store=system.context.llm_call_record_store,
            account_halt_barrier=system.context.account_halt_barrier,
        )
    return PlatformSourceLineagePoliciesM16M21Context(**values)


def _m17_system():
    graph = ResearchGraphStore()
    harness = _CompilerHarness()
    promotion_ref = "runtime_promotion_" + content_hash("m17-promotion")
    permission_ref = "permission:copy-trade:live"
    guard_ref = "order_guard:copy-trade:live"
    follower = Follower(
        follower_id="follower:m17",
        user_id=OWNER,
        master_id="master:m17",
        account_binding_ref="account:m17",
        runtime_promotion_ref=promotion_ref,
        status="active",
    )
    subscription_ref = copy_trade_subscription_ref(follower)
    subject_ref = "copy_trade_subject_" + content_hash(
        {
            "follower_id": follower.follower_id,
            "user_id": follower.user_id,
            "master_id": follower.master_id,
            "account_binding_ref": follower.account_binding_ref,
        }
    )
    promotion = SimpleNamespace(
        runtime_promotion_ref=promotion_ref,
        target_runtime="live",
        subject_ref=subject_ref,
        permission_gate_ref=permission_ref,
        order_guard_ref=guard_ref,
    )
    reservation_ref = "copy_reservation_" + content_hash("m17-reservation")
    risk_ref = "copy_risk_check_" + content_hash("m17-risk")
    reservation = SimpleNamespace(
        reservation_ref=reservation_ref,
        risk_check_ref=risk_ref,
        follower_id=follower.follower_id,
        account_binding_ref=follower.account_binding_ref,
    )
    intent_ref = "order_intent_" + content_hash("m17-intent")
    intent = SimpleNamespace(
        order_intent_ref=intent_ref,
        recorded_by=OWNER,
        execution_policy_ref=permission_ref,
        risk_policy_ref=risk_ref,
        runtime="live",
        asset_class="crypto_perp",
        instrument_ref="instrument:BTCUSDT:perp",
        permission_gate_ref=permission_ref,
        order_guard_ref=guard_ref,
    )
    submission_ref = "order_submission_" + content_hash("m17-submission")
    audit_ref = "copy_submission_audit_" + content_hash(reservation_ref)
    submission = SimpleNamespace(
        submission_ref=submission_ref,
        order_intent_ref=intent_ref,
        runtime_promotion_ref=promotion_ref,
        audit_record_ref=audit_ref,
        recorded_by="copy_trade_signal_relayer",
        submitter_ref="copy_trade_signal_relayer:v1",
        submit_enabled=True,
        submission_mode="live",
        permission_gate_ref=permission_ref,
        order_guard_ref=guard_ref,
    )

    class CopyTrade:
        relay_calls = 0

        def get_follower(self, ref):
            return follower if ref == follower.follower_id else None

        def subscription(self, ref, *, owner_user_id):
            if ref != copy_trade_subscription_ref(follower) or owner_user_id != OWNER:
                raise KeyError(ref)
            return follower

        def relay_signal(self, *_args, **_kwargs):
            self.relay_calls += 1
            raise AssertionError("attestation cannot relay")

    class Promotions:
        def promotion(self, ref):
            if ref != promotion_ref:
                raise KeyError(ref)
            return promotion

    class Risks:
        reserve_calls = 0
        current = reservation

        def reservation_for_submission(self, ref):
            if ref != submission_ref:
                raise KeyError(ref)
            return self.current

        def reservation_by_risk_check_ref(self, ref):
            if ref != self.current.risk_check_ref:
                raise KeyError(ref)
            return self.current

        def reserve(self, *_args, **_kwargs):
            self.reserve_calls += 1
            raise AssertionError("attestation cannot reserve")

    class Submissions:
        record_calls = 0
        audit_result = None

        def refresh(self):
            return None

        def submission(self, ref):
            if ref != submission_ref:
                raise KeyError(ref)
            return submission

        def submission_by_audit_record_ref(self, ref):
            if ref != audit_ref:
                raise KeyError(ref)
            return self.audit_result

        def record_submission(self, *_args, **_kwargs):
            self.record_calls += 1
            raise AssertionError("attestation cannot submit")

    class Intents:
        def intent(self, ref):
            if ref != intent_ref:
                raise KeyError(ref)
            return intent

    copy_trade = CopyTrade()
    risks = Risks()
    submissions = Submissions()
    submissions.audit_result = submission
    chain = _chain(risk_policy_ref=risk_ref, execution_policy_ref=permission_ref)
    context = _context(
        graph=graph,
        chain_store=_Chains(chain),
        harness=harness,
        copy_trade_service=copy_trade,
        runtime_promotion_registry=Promotions(),
        follower_risk_state_store=risks,
        execution_order_submission_registry=submissions,
        execution_order_intent_registry=Intents(),
    )
    return SimpleNamespace(
        context=context,
        graph=graph,
        harness=harness,
        chain=chain,
        follower=follower,
        reservation=reservation,
        submission=submission,
        intent=intent,
        promotion=promotion,
        copy_trade=copy_trade,
        risks=risks,
        submissions=submissions,
        refs={
            "submission_ref": submission_ref,
            "copy_trade_subscription_ref": subscription_ref,
            "runtime_promotion_ref": promotion_ref,
            "risk_gate_ref": risk_ref,
            "execution_audit_ref": audit_ref,
        },
    )


def _source_code_qro() -> QRORecord:
    return QRORecord(
        qro_type=QROType.STRATEGY_BOOK,
        owner=OWNER,
        actor=ActorSource.USER_MANUAL,
        input_contract={"entry_source": "ide", "code_hash": "code:m18:v1"},
        output_contract={"status": "saved"},
        market="crypto_perp",
        universe="BTCUSDT",
        horizon="daily",
        frequency="1d",
        lineage=("code:m18:v1",),
        implementation_hash="implementation:m18:v1",
        assumptions=("The source command is an existing IDE save.",),
        known_limits=("The source QRO is not itself an attestation.",),
        failure_modes=("Source mutation makes the package stale.",),
        validation_plan=("Use the RDP consistency check.",),
    )


def _m18_system():
    graph = ResearchGraphStore()
    harness = _CompilerHarness()
    source_qro = _source_code_qro()
    source_command = ResearchGraphCommand(
        source=EntrySource.IDE,
        command_type="upsert_qro",
        actor_source=ActorSource.USER_MANUAL,
        actor=OWNER,
        payload={"qro": source_qro},
    )
    graph.apply(source_command)
    check_ref = "cc_m18_current"
    binding_ref = "tib:m18:v1"
    package_ref = "rdp:m18:v1"
    check = SimpleNamespace(check_id=check_ref, binding_id=binding_ref, result="pass")
    binding = SimpleNamespace(binding_id=binding_ref, used_by=(source_command.command_id,))
    manifest = SimpleNamespace(
        package_id=package_ref,
        consistency_check_refs=(check_ref,),
        graph_refs=(source_command.command_id,),
        code_refs=("code:m18:v1",),
        test_refs=("test:m18:v1",),
        unverified_residuals=(),
        mathematical_spine_chain_refs=("math_spine_chain:m18:v1",),
    )

    class Ledger:
        def check(self, ref, *, owner):
            if ref != check_ref or owner != OWNER:
                raise KeyError(ref)
            return check

        def binding(self, ref, *, owner):
            if ref != binding_ref or owner != OWNER:
                raise KeyError(ref)
            return binding

    class RDPs:
        mutation_calls = 0
        current = [manifest]

        def manifests(self, *, owner_user_id):
            return list(self.current) if owner_user_id == OWNER else []

        def record_manifest(self, *_args, **_kwargs):
            self.mutation_calls += 1
            raise AssertionError("attestation cannot rewrite the historical RDP")

    rdp = RDPs()
    chain = _chain(
        chain_ref="math_spine_chain:m18:v1",
        theory_binding_refs=(binding_ref,),
        consistency_check_refs=(check_ref,),
    )
    context = _context(
        graph=graph,
        chain_store=_Chains(chain),
        harness=harness,
        canonical_spine_ledger=Ledger(),
        rdp_store=rdp,
    )
    return SimpleNamespace(
        context=context,
        graph=graph,
        harness=harness,
        chain=chain,
        check=check,
        binding=binding,
        manifest=manifest,
        rdp=rdp,
        source_command=source_command,
        refs={
            "canonical_code_command_ref": source_command.command_id,
            "consistency_check_ref": check_ref,
            "rdp_package_ref": package_ref,
        },
    )


def _m20_system():
    graph = ResearchGraphStore()
    harness = _CompilerHarness()
    halt_ref = "account_halt_m20_current"
    secret_ref = "secretref:llm:m20"
    call_id = "m20-current"
    halt = SimpleNamespace(
        owner_user_id=OWNER,
        halt_ref=halt_ref,
        owner_state="halted",
        owner_epoch=3,
        account_binding_refs=("account:m20",),
        flat_proof_refs=("flat:m20",),
    )
    terminal = SimpleNamespace(
        owner_user_id=OWNER,
        call_id=call_id,
        record_kind="terminal",
        status="ok",
        auth_ref=secret_ref,
    )
    secret = SimpleNamespace(secret_ref=secret_ref, status="active")

    class Halts:
        mutation_calls = 0

        def halt_evidence(self, ref, *, owner_user_id):
            if ref != halt_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return halt

        def begin_halt_many(self, *_args, **_kwargs):
            self.mutation_calls += 1
            raise AssertionError("attestation cannot begin HALT")

        def finalize_halt_many(self, *_args, **_kwargs):
            self.mutation_calls += 1
            raise AssertionError("attestation cannot finalize HALT")

    class Calls:
        current = [terminal]

        def read_all(self, *, owner_user_id):
            return list(self.current) if owner_user_id == OWNER else []

    class Secrets:
        def secret_ref(self, ref, *, owner_user_id):
            if ref != secret_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return secret

    halts = Halts()
    calls = Calls()
    chain = _chain(
        chain_ref="math_spine_chain:m20:v1",
        evidence_refs=(secret_ref, f"llm_gateway:{call_id}", "flat:m20"),
        validation_refs=(halt_ref, "flat:m20"),
    )
    context = _context(
        graph=graph,
        chain_store=_Chains(chain),
        harness=harness,
        account_halt_barrier=halts,
        llm_call_record_store=calls,
        onboarding_registry=Secrets(),
        llm_service_owner_user_id=OWNER,
    )
    return SimpleNamespace(
        context=context,
        graph=graph,
        harness=harness,
        chain=chain,
        halt=halt,
        terminal=terminal,
        halts=halts,
        calls=calls,
        refs={
            "secret_ref": secret_ref,
            "llm_gateway_ref": f"llm_gateway:{call_id}",
            "kill_switch_ref": halt_ref,
        },
    )


def test_public_operation_accepts_only_context_owner_row_and_anchor() -> None:
    assert tuple(signature(record_platform_business_attestation).parameters) == (
        "context",
        "owner_user_id",
        "row",
        "anchor_ref",
    )
    assert tuple(signature(PlatformBusinessAttestationService.record).parameters) == (
        "self",
        "owner_user_id",
        "row",
        "anchor_ref",
    )


def test_m17_records_exact_execution_policy_without_relay_reserve_or_submit() -> None:
    system = _m17_system()

    result = record_platform_business_attestation(
        context=system.context,
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )

    qro = system.graph.qro(result.qro_ref)
    assert qro.qro_type == QROType.EXECUTION_POLICY
    assert qro.input_contract == system.refs
    assert qro.output_contract == {"status": "guarded_submission_recorded"}
    assert qro.mathematical_refs == (system.chain.chain_ref,)
    command = system.graph.commands()[-1]
    assert command.source == EntrySource.API
    assert command.actor_source == ActorSource.USER_MANUAL
    assert command.actor == OWNER
    assert command.tool_record_refs == (ENTRYPOINT_REFS["M17"],)
    assert system.copy_trade.relay_calls == 0
    assert system.risks.reserve_calls == 0
    assert system.submissions.record_calls == 0


def test_exact_current_attestation_is_reused_without_new_graph_or_compiler_write() -> None:
    system = _m17_system()
    service = PlatformBusinessAttestationService(system.context)
    first = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    command_count = len(system.graph.commands())
    second = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )

    assert first.graph_command_created is True
    assert second.graph_command_created is False
    assert second == replace(first, graph_command_created=False)
    assert len(system.graph.commands()) == command_count == 1
    assert system.harness.calls == 1


def test_current_policy_replays_for_new_and_reused_attestation() -> None:
    system = _m17_system()
    calls = []

    def validate(result):
        calls.append(result)
        return _matching_policy_resolution(result)

    service = PlatformBusinessAttestationService(
        replace(system.context, validate_current_attestation=validate)
    )
    first = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    second = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )

    assert calls == [first, second]
    assert second == replace(first, graph_command_created=False)
    assert len(system.graph.commands()) == 1
    assert system.harness.calls == 1


def test_source_change_before_final_policy_replay_preserves_forward_only_history() -> None:
    system = _m17_system()
    mutate_once = True

    def mutate_then_validate(result):
        nonlocal mutate_once
        if mutate_once:
            mutate_once = False
            system.follower.status = "stopped"
        return build_platform_source_lineage_policy_resolver_m16_m21(
            _policy_context(system, row="M17")
        ).resolve(
            owner_user_id=OWNER,
            m_row="M17",
            anchor_ref=result.anchor_ref,
        )

    service = PlatformBusinessAttestationService(
        replace(
            system.context,
            validate_current_attestation=mutate_then_validate,
        )
    )

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert captured.value.phase == "policy_replay"
    assert captured.value.graph_attestation_current is True
    assert captured.value.graph_command_created is True
    assert len(system.graph.commands()) == 1
    assert len(system.harness.store.irs(owner=OWNER)) == 1
    assert len(system.harness.store.passes(owner=OWNER)) == 1
    assert len(system.harness.coverage.records(owner=OWNER)) == 1

    system.follower.status = "active"
    repaired = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    assert repaired.graph_command_created is False
    assert len(system.graph.commands()) == 1
    assert system.harness.calls == 1


def test_concurrent_identical_calls_serialize_and_reuse_one_exact_command() -> None:
    system = _m17_system()
    services = (
        PlatformBusinessAttestationService(system.context),
        PlatformBusinessAttestationService(system.context),
    )
    start = Barrier(2)

    def record(service):
        start.wait(timeout=5)
        return service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(record, services))

    assert sorted(result.graph_command_created for result in results) == [False, True]
    assert len({result.graph_command_ref for result in results}) == 1
    assert len(system.graph.commands()) == 1
    assert system.harness.calls == 1


def test_concurrent_persistent_graph_instances_refresh_under_attestation_lock(
    tmp_path: Path,
) -> None:
    system = _m17_system()
    graph_path = tmp_path / "research_graph.jsonl"
    contexts = tuple(
        replace(system.context, research_graph_store=PersistentResearchGraphStore(graph_path))
        for _ in range(2)
    )
    services = tuple(PlatformBusinessAttestationService(context) for context in contexts)
    start = Barrier(2)

    def record(service):
        start.wait(timeout=5)
        return service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(record, services))

    replay = PersistentResearchGraphStore(graph_path)
    assert sorted(result.graph_command_created for result in results) == [False, True]
    assert len({result.graph_command_ref for result in results}) == 1
    assert len(replay.commands()) == 1
    assert system.harness.calls == 1


def test_exact_current_attestation_replays_from_persistent_stores(
    tmp_path: Path,
) -> None:
    system = _m17_system()
    graph_path = tmp_path / "research_graph.jsonl"
    compiler_path = tmp_path / "compiler.jsonl"
    coverage_path = tmp_path / "coverage.jsonl"
    graph = PersistentResearchGraphStore(graph_path)
    compiler = PersistentCompilerIRStore(compiler_path)
    resolver = _ReplayResolver(
        graph,
        compiler,
        owner=OWNER,
        lifecycle_ref=system.refs["runtime_promotion_ref"],
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        resolver=resolver,
    )

    def persist_compile(qro, command, plan):
        built = _CompilerHarness()
        result = built.compile(qro, command, plan)
        for ir in built.store.irs(owner=OWNER):
            compiler.record_ir(ir)
        for compiler_pass in built.store.passes(owner=OWNER):
            compiler.record_pass(compiler_pass)
        for record in built.coverage.records(owner=OWNER):
            coverage.record_coverage(record)
        return result

    context = replace(
        system.context,
        research_graph_store=graph,
        compiler_store=compiler,
        entrypoint_registry=coverage,
        compile_attestation=persist_compile,
    )
    first = PlatformBusinessAttestationService(context).record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )

    replay_graph = PersistentResearchGraphStore(graph_path)
    replay_compiler = PersistentCompilerIRStore(compiler_path)
    replay_resolver = _ReplayResolver(
        replay_graph,
        replay_compiler,
        owner=OWNER,
        lifecycle_ref=system.refs["runtime_promotion_ref"],
    )
    replay_coverage = PersistentGoalEntrypointCoverageRegistry(
        coverage_path,
        resolver=replay_resolver,
    )
    callback_calls = 0

    def must_not_compile(_qro, _command, _plan):
        nonlocal callback_calls
        callback_calls += 1
        raise AssertionError("exact persistent replay must reuse coverage")

    replay_context = replace(
        system.context,
        research_graph_store=replay_graph,
        compiler_store=replay_compiler,
        entrypoint_registry=replay_coverage,
        compile_attestation=must_not_compile,
    )
    replayed = PlatformBusinessAttestationService(replay_context).record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )

    assert replayed == replace(first, graph_command_created=False)
    assert callback_calls == 0
    assert len(replay_graph.commands()) == 1


def test_compiler_partial_state_is_preserved_and_retry_continues_forward() -> None:
    system = _m17_system()
    system.harness.fail_after = "ir"
    service = PlatformBusinessAttestationService(system.context)

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    error = captured.value
    assert error.phase == "compiler_coverage"
    assert error.graph_attestation_current is True
    assert error.graph_command_created is True
    assert len(system.graph.commands()) == 1
    assert len(system.harness.store.irs(owner=OWNER)) == 1
    assert system.harness.store.passes(owner=OWNER) == []
    assert not system.harness.coverage.records(owner=OWNER)
    preserved_command = system.graph.commands()[0]
    preserved_ir = system.harness.store.irs(owner=OWNER)[0]

    system.harness.fail_after = None
    result = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    assert result.graph_command_created is False
    assert system.graph.commands() == [preserved_command]
    assert system.harness.store.irs(owner=OWNER) == [preserved_ir]
    assert len(system.harness.store.passes(owner=OWNER)) == 1
    assert len(system.harness.coverage.records(owner=OWNER)) == 1


def test_graph_append_then_error_preserves_exact_attempt_and_retry_reuses_it() -> None:
    system = _m17_system()

    class ApplyThenRaiseGraph(ResearchGraphStore):
        fail = True

        def apply(self, command):
            ref = super().apply(command)
            if self.fail:
                self.fail = False
                raise OSError("durability acknowledgement unavailable")
            return ref

    graph = ApplyThenRaiseGraph()
    context = replace(system.context, research_graph_store=graph)
    service = PlatformBusinessAttestationService(context)

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert captured.value.phase == "research_graph"
    assert captured.value.graph_attestation_current is True
    assert captured.value.graph_command_created is True
    assert len(graph.commands()) == 1
    assert system.harness.calls == 0
    preserved_command = graph.commands()[0]

    result = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    assert result.graph_command_created is False
    assert graph.commands() == [preserved_command]


def test_persistent_pre_append_failure_reports_false_and_replays_empty(
    tmp_path: Path,
) -> None:
    system = _m17_system()
    graph_path = tmp_path / "pre-append-failure.jsonl"

    class FailBeforePersistentAppend(PersistentResearchGraphStore):
        def _append_command_row_unlocked(self, _row):
            raise OSError("persistent append unavailable")

    graph = FailBeforePersistentAppend(graph_path)
    service = PlatformBusinessAttestationService(
        replace(system.context, research_graph_store=graph)
    )

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert captured.value.graph_attestation_current is False
    assert captured.value.graph_command_created is False
    assert PersistentResearchGraphStore(graph_path).commands() == []
    assert system.harness.calls == 0


def test_persistent_post_fsync_publish_failure_preserves_and_reuses_history(
    tmp_path: Path,
) -> None:
    system = _m17_system()
    graph_path = tmp_path / "post-fsync-publish-failure.jsonl"

    class PublishThenRaise(PersistentResearchGraphStore):
        fail_once = True

        def _publish_projection_unlocked(self, fresh):
            super()._publish_projection_unlocked(fresh)
            if self.fail_once:
                self.fail_once = False
                raise OSError("projection publication acknowledgement unavailable")

    graph = PublishThenRaise(graph_path)
    service = PlatformBusinessAttestationService(
        replace(system.context, research_graph_store=graph)
    )

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert captured.value.graph_attestation_current is True
    assert captured.value.graph_command_created is True
    replay_after_failure = PersistentResearchGraphStore(graph_path)
    assert len(replay_after_failure.commands()) == 1
    preserved_command = replay_after_failure.commands()[0]
    assert system.harness.calls == 0

    result = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    assert result.graph_command_created is False
    assert PersistentResearchGraphStore(graph_path).commands() == [preserved_command]
    assert system.harness.calls == 1


class _FailOncePersistentAttestationCoverage(
    PersistentGoalEntrypointCoverageRegistry
):
    fail_before_append_once = False
    fail_after_append_once = False

    def record_coverage(self, record):
        if self.fail_before_append_once:
            self.fail_before_append_once = False
            raise OSError("injected attestation coverage append failure")
        persisted = super().record_coverage(record)
        if self.fail_after_append_once:
            self.fail_after_append_once = False
            raise OSError(
                "injected attestation coverage durability acknowledgement failure"
            )
        return persisted


class _PersistentAttestationCompilerAdapter:
    def __init__(self, *, compiler, coverage, failure: str) -> None:
        self.compiler = compiler
        self.coverage = coverage
        self.failure = failure
        self.calls = 0

    def compile(self, qro, command, plan):
        self.calls += 1
        built = _CompilerHarness()
        result = built.compile(qro, command, plan)
        compiler_ir = built.store.irs(owner=plan.owner_user_id)[0]
        compiler_pass = built.store.passes(owner=plan.owner_user_id)[0]
        coverage = built.coverage.records(owner=plan.owner_user_id)[0]

        self.compiler.record_ir(compiler_ir)
        if self.failure == "after_ir":
            self.failure = ""
            raise OSError("injected attestation failure after IR append")
        self.compiler.record_pass(compiler_pass)
        if self.failure == "after_pass":
            self.failure = ""
            raise OSError("injected attestation failure after pass append")
        if self.failure == "coverage_failure":
            self.failure = ""
            self.coverage.fail_before_append_once = True
        elif self.failure == "coverage_ack":
            self.failure = ""
            self.coverage.fail_after_append_once = True
        self.coverage.record_coverage(coverage)
        return result


def _persistent_attestation_runtime(tmp_path: Path, *, failure: str):
    base = _m17_system()
    graph_path = tmp_path / f"{failure}-research-graph.jsonl"
    compiler_path = tmp_path / f"{failure}-compiler.jsonl"
    coverage_path = tmp_path / f"{failure}-coverage.jsonl"
    graph = PersistentResearchGraphStore(graph_path)
    compiler = PersistentCompilerIRStore(compiler_path)
    backing = _ReplayResolver(
        graph,
        compiler,
        owner=OWNER,
        lifecycle_ref=base.refs["runtime_promotion_ref"],
    )
    coverage = _FailOncePersistentAttestationCoverage(
        coverage_path,
        resolver=backing,
    )
    adapter = _PersistentAttestationCompilerAdapter(
        compiler=compiler,
        coverage=coverage,
        failure=failure,
    )

    def fresh_compiler():
        return PersistentCompilerIRStore(compiler_path)

    def fresh_coverage():
        fresh_graph = PersistentResearchGraphStore(graph_path)
        fresh_compiler_store = PersistentCompilerIRStore(compiler_path)
        fresh_backing = _ReplayResolver(
            fresh_graph,
            fresh_compiler_store,
            owner=OWNER,
            lifecycle_ref=base.refs["runtime_promotion_ref"],
        )
        return PersistentGoalEntrypointCoverageRegistry(
            coverage_path,
            resolver=fresh_backing,
        )

    context = replace(
        base.context,
        research_graph_store=graph,
        compiler_store=compiler,
        entrypoint_registry=coverage,
        compile_attestation=adapter.compile,
        compiler_view_factory=fresh_compiler,
        entrypoint_view_factory=fresh_coverage,
    )
    return SimpleNamespace(
        base=base,
        context=context,
        graph=graph,
        compiler=compiler,
        coverage=coverage,
        adapter=adapter,
        paths={
            "graph": graph_path,
            "compiler": compiler_path,
            "coverage": coverage_path,
        },
    )


def _fresh_persistent_attestation_state(runtime):
    graph = PersistentResearchGraphStore(runtime.paths["graph"])
    compiler = PersistentCompilerIRStore(runtime.paths["compiler"])
    backing = _ReplayResolver(
        graph,
        compiler,
        owner=OWNER,
        lifecycle_ref=runtime.base.refs["runtime_promotion_ref"],
    )
    coverage = PersistentGoalEntrypointCoverageRegistry(
        runtime.paths["coverage"],
        resolver=backing,
    )
    return SimpleNamespace(
        graph=graph,
        compiler=compiler,
        coverage=coverage,
    )


@pytest.mark.parametrize(
    "failure",
    ("after_ir", "after_pass", "coverage_failure", "coverage_ack"),
)
def test_persistent_attestation_failure_preserves_append_prefix_then_retries_once(
    tmp_path: Path,
    failure: str,
) -> None:
    runtime = _persistent_attestation_runtime(tmp_path, failure=failure)
    service = PlatformBusinessAttestationService(runtime.context)

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=runtime.base.refs["submission_ref"],
        )

    error = captured.value
    assert error.phase == "compiler_coverage"
    assert error.graph_attestation_current is True
    assert error.graph_command_created is True
    assert isinstance(error.__cause__, OSError)
    assert "injected" in str(error.__cause__)

    failed_replay = _fresh_persistent_attestation_state(runtime)
    expected_counts = {
        "after_ir": (1, 0, 0),
        "after_pass": (1, 1, 0),
        "coverage_failure": (1, 1, 0),
        "coverage_ack": (1, 1, 1),
    }[failure]
    assert len(failed_replay.graph.commands()) == 1
    assert len(failed_replay.compiler.irs(owner=OWNER)) == expected_counts[0]
    assert len(failed_replay.compiler.passes(owner=OWNER)) == expected_counts[1]
    assert len(failed_replay.coverage.records(owner=OWNER)) == expected_counts[2]
    preserved_command = failed_replay.graph.commands()[0]
    preserved_ir_refs = tuple(
        record.ir_ref for record in failed_replay.compiler.irs(owner=OWNER)
    )
    preserved_pass_refs = tuple(
        record.pass_ref for record in failed_replay.compiler.passes(owner=OWNER)
    )
    preserved_coverage_refs = tuple(
        record.coverage_ref
        for record in failed_replay.coverage.records(owner=OWNER)
    )
    failed_bytes = {
        key: (path.read_bytes() if path.exists() else b"")
        for key, path in runtime.paths.items()
    }

    repaired = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=runtime.base.refs["submission_ref"],
    )
    reused = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=runtime.base.refs["submission_ref"],
    )

    assert repaired.graph_command_created is False
    assert reused == replace(repaired, graph_command_created=False)
    assert runtime.adapter.calls == (1 if failure == "coverage_ack" else 2)
    success_replay = _fresh_persistent_attestation_state(runtime)
    assert success_replay.graph.commands() == [preserved_command]
    assert runtime.paths["graph"].read_bytes() == failed_bytes["graph"]
    assert runtime.paths["compiler"].read_bytes().startswith(
        failed_bytes["compiler"]
    )
    assert runtime.paths["coverage"].read_bytes().startswith(
        failed_bytes["coverage"]
    )
    assert [
        record.ir_ref for record in success_replay.compiler.irs(owner=OWNER)
    ] == [repaired.compiler_ir_ref]
    assert [
        record.pass_ref for record in success_replay.compiler.passes(owner=OWNER)
    ] == [repaired.compiler_pass_ref]
    assert [
        record.coverage_ref
        for record in success_replay.coverage.records(owner=OWNER)
    ] == [repaired.entrypoint_coverage_ref]
    assert set(preserved_ir_refs).issubset(
        {record.ir_ref for record in success_replay.compiler.irs(owner=OWNER)}
    )
    assert set(preserved_pass_refs).issubset(
        {record.pass_ref for record in success_replay.compiler.passes(owner=OWNER)}
    )
    assert set(preserved_coverage_refs).issubset(
        {
            record.coverage_ref
            for record in success_replay.coverage.records(owner=OWNER)
        }
    )


def test_graph_pre_append_failure_reports_observed_false_false() -> None:
    system = _m17_system()

    class FailBeforeApplyGraph(ResearchGraphStore):
        def apply(self, _command):
            raise OSError("append was not attempted")

    service = PlatformBusinessAttestationService(
        replace(system.context, research_graph_store=FailBeforeApplyGraph())
    )

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert captured.value.graph_attestation_current is False
    assert captured.value.graph_command_created is False
    assert system.harness.calls == 0


def test_graph_durability_error_with_observable_empty_store_reports_false_false() -> None:
    system = _m17_system()

    class UnknownDurabilityGraph(ResearchGraphStore):
        fail_once = True

        def apply(self, command):
            if self.fail_once:
                self.fail_once = False
                raise ResearchGraphDurabilityError(
                    "durable state cannot be observed"
                )
            return super().apply(command)

    graph = UnknownDurabilityGraph()
    service = PlatformBusinessAttestationService(
        replace(system.context, research_graph_store=graph)
    )

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert captured.value.graph_attestation_current is False
    assert captured.value.graph_command_created is False
    assert graph.commands() == []
    assert system.harness.calls == 0

    result = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    assert result.graph_command_created is True
    assert len(graph.commands()) == 1


def test_attestation_lock_refresh_failure_reports_unknown_unknown(
    tmp_path: Path,
) -> None:
    system = _m17_system()

    class RefreshFailureGraph(ResearchGraphStore):
        path = tmp_path / "refresh-failure.jsonl"

        def refresh(self):
            raise OSError("refresh unavailable")

    service = PlatformBusinessAttestationService(
        replace(system.context, research_graph_store=RefreshFailureGraph())
    )

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert captured.value.phase == "attestation_lock"
    assert captured.value.graph_attestation_current is None
    assert captured.value.graph_command_created is None
    assert captured.value.graph_command_ref == ""
    assert system.harness.calls == 0


def test_graph_wrong_ack_preserves_exact_attempt_and_retry_reuses_it() -> None:
    system = _m17_system()

    class WrongAckGraph(ResearchGraphStore):
        wrong_once = True

        def apply(self, command):
            ref = super().apply(command)
            if self.wrong_once:
                self.wrong_once = False
                return "rgcmd_wrong_ack"
            return ref

    graph = WrongAckGraph()
    service = PlatformBusinessAttestationService(
        replace(system.context, research_graph_store=graph)
    )

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert captured.value.phase == "research_graph_ack"
    assert captured.value.graph_attestation_current is True
    assert captured.value.graph_command_created is True
    assert len(graph.commands()) == 1
    assert system.harness.calls == 0
    preserved_command = graph.commands()[0]

    result = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    assert result.graph_command_created is False
    assert graph.commands() == [preserved_command]
    assert system.harness.calls == 1


def test_compiler_state_without_graph_head_fails_read_only_preflight() -> None:
    system = _m17_system()
    service = PlatformBusinessAttestationService(system.context)
    prepared = service.prepare(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    command = service._command(prepared)
    plan = service._compile_plan(prepared=prepared, command=command)
    system.harness.fail_after = "ir"
    with pytest.raises(OSError):
        system.harness.compile(prepared.qro, command, plan)
    system.harness.fail_after = None

    with pytest.raises(PlatformBusinessAttestationError, match="before its.*Graph head"):
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert system.graph.commands() == []


def _persist_m18_bundle_for_lineage_validation(system):
    service = PlatformBusinessAttestationService(system.context)
    prepared = service.prepare(
        owner_user_id=OWNER,
        row="M18",
        anchor_ref=system.refs["consistency_check_ref"],
    )
    command = service._command(prepared)
    system.graph.apply(command)
    plan = service._compile_plan(prepared=prepared, command=command)
    result = system.harness.compile(prepared.qro, command, plan)
    return service, prepared, command, result


def _replace_m18_compiler_proof(
    system,
    result,
    *,
    ir_evidence_refs=None,
    pass_evidence_refs=None,
    coverage_evidence_refs=None,
    validation_refs=None,
):
    ir = system.harness.store.ir(result["compiler_ir_ref"], owner=OWNER)
    compiler_pass = system.harness.store.compiler_pass(
        result["compiler_pass_ref"],
        owner=OWNER,
    )
    coverage = system.harness.coverage.coverage(
        result["entrypoint_coverage_ref"],
        owner=OWNER,
    )
    new_ir = replace(
        ir,
        evidence_refs=(
            ir.evidence_refs
            if ir_evidence_refs is None
            else tuple(ir_evidence_refs)
        ),
        validation_refs=(
            ir.validation_refs
            if validation_refs is None
            else tuple(validation_refs)
        ),
    )
    new_pass = replace(
        compiler_pass,
        evidence_refs=(
            new_ir.evidence_refs
            if pass_evidence_refs is None
            else tuple(pass_evidence_refs)
        ),
        validation_refs=new_ir.validation_refs,
    )
    new_coverage = replace(
        coverage,
        evidence_refs=(
            new_ir.evidence_refs
            if coverage_evidence_refs is None
            else tuple(coverage_evidence_refs)
        ),
        validation_refs=new_ir.validation_refs,
    )
    system.harness.store._irs[(OWNER, ir.ir_ref)] = new_ir
    system.harness.store._passes[(OWNER, compiler_pass.pass_ref)] = new_pass
    system.harness.coverage._records[(OWNER, coverage.coverage_ref)] = (
        new_coverage
    )
    return new_ir, new_pass, new_coverage


@pytest.mark.parametrize(
    ("proof_kind", "mutation"),
    (
        ("evidence", "missing"),
        ("evidence", "multiple"),
        ("evidence", "foreign"),
        ("evidence", "stale"),
        ("receipt", "missing"),
        ("receipt", "multiple"),
        ("receipt", "foreign"),
        ("receipt", "stale"),
    ),
)
def test_persisted_m18_lineage_rejects_untrusted_or_wrong_cardinality_proof(
    proof_kind: str,
    mutation: str,
) -> None:
    system = _m18_system()
    service, prepared, command, result = (
        _persist_m18_bundle_for_lineage_validation(system)
    )
    ir = system.harness.store.ir(result["compiler_ir_ref"], owner=OWNER)
    evidence_refs = tuple(ir.evidence_refs)
    validation_refs = tuple(ir.validation_refs)
    untrusted = ""
    if proof_kind == "evidence":
        if mutation == "missing":
            evidence_refs = ()
        elif mutation == "multiple":
            evidence_refs = (*evidence_refs, "entrypoint_evidence:m18:second")
        else:
            untrusted = f"entrypoint_evidence:m18:{mutation}"
            evidence_refs = (untrusted,)
    else:
        receipt = next(
            ref
            for ref in validation_refs
            if ref.startswith("goal_validation_receipt:")
        )
        if mutation == "missing":
            validation_refs = tuple(
                ref for ref in validation_refs if ref != receipt
            )
        elif mutation == "multiple":
            validation_refs = (
                *validation_refs,
                "goal_validation_receipt:m18:second",
            )
        else:
            untrusted = f"goal_validation_receipt:m18:{mutation}"
            validation_refs = tuple(
                untrusted if ref == receipt else ref
                for ref in validation_refs
            )
    _replace_m18_compiler_proof(
        system,
        result,
        ir_evidence_refs=evidence_refs,
        validation_refs=validation_refs,
    )
    if untrusted:
        system.harness.coverage.rejected_proof_refs.add(untrusted)

    expected = (
        "lacks strict real backing"
        if untrusted
        else "stale, different, or recombined"
    )
    with pytest.raises(PlatformBusinessAttestationError, match=expected):
        service._validate_persisted_lineage(
            prepared=prepared,
            command=command,
            coverage_ref=result["entrypoint_coverage_ref"],
        )


def test_persisted_m18_lineage_rejects_divergent_compiler_evidence() -> None:
    system = _m18_system()
    service, prepared, command, result = (
        _persist_m18_bundle_for_lineage_validation(system)
    )
    _replace_m18_compiler_proof(
        system,
        result,
        pass_evidence_refs=("entrypoint_evidence:m18:divergent",),
    )

    with pytest.raises(
        PlatformBusinessAttestationError,
        match="stale, different, or recombined",
    ):
        service._validate_persisted_lineage(
            prepared=prepared,
            command=command,
            coverage_ref=result["entrypoint_coverage_ref"],
        )


def test_persisted_m18_lineage_rejects_mutated_semantic_qro_evidence() -> None:
    system = _m18_system()
    service, prepared, command, result = (
        _persist_m18_bundle_for_lineage_validation(system)
    )
    system.graph._qros[prepared.qro.qro_id] = replace(
        prepared.qro,
        evidence_refs=(
            *prepared.qro.evidence_refs,
            "evidence:m18:same-owner-unrelated",
        ),
    )

    with pytest.raises(
        PlatformBusinessAttestationError,
        match="stale, different, or recombined",
    ):
        service._validate_persisted_lineage(
            prepared=prepared,
            command=command,
            coverage_ref=result["entrypoint_coverage_ref"],
        )


def test_m17_recombined_reverse_audit_fails_before_any_write() -> None:
    system = _m17_system()
    system.submissions.audit_result = SimpleNamespace(submission_ref="order_submission_other")

    with pytest.raises(PlatformBusinessAttestationError, match="stale or recombined"):
        PlatformBusinessAttestationService(system.context).record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert system.graph.commands() == []
    assert system.harness.calls == 0


def test_m17_ambiguous_matching_spine_chain_fails_before_any_write() -> None:
    system = _m17_system()
    duplicate = _chain(
        chain_ref="math_spine_chain:business-attestation:duplicate",
        risk_policy_ref=system.refs["risk_gate_ref"],
        execution_policy_ref=system.intent.execution_policy_ref,
    )
    system.context.spine_chain_registry.current.append(duplicate)

    with pytest.raises(Exception, match="exactly one"):
        PlatformBusinessAttestationService(system.context).record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert system.graph.commands() == []
    assert system.harness.calls == 0


def test_source_change_rejects_stale_attestation_instead_of_appending_new_head() -> None:
    system = _m17_system()
    service = PlatformBusinessAttestationService(system.context)
    service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    system.follower.status = "paused"

    with pytest.raises(PlatformBusinessAttestationError, match="different or stale"):
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert len(system.graph.commands()) == 1
    assert system.harness.calls == 1


def test_later_same_qro_projection_drift_is_rejected_by_graph_immutability() -> None:
    system = _m17_system()
    service = PlatformBusinessAttestationService(system.context)
    first = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    current = system.graph.qro(first.qro_ref)
    drifted = replace(current, permission="platform.business_attestation:m17:drift")
    with pytest.raises(ResearchGraphError, match="platform-bound QRO is immutable"):
        system.graph.apply(
            ResearchGraphCommand(
                source=EntrySource.API,
                command_type="upsert_qro",
                actor_source=ActorSource.USER_MANUAL,
                actor=OWNER,
                payload={"qro": drifted},
                evidence_refs=("evidence:unrelated-drift",),
                tool_record_refs=("api:unrelated.same_qro_drift",),
            )
        )

    reused = service.record(
        owner_user_id=OWNER,
        row="M17",
        anchor_ref=system.refs["submission_ref"],
    )
    assert reused == replace(first, graph_command_created=False)
    assert len(system.graph.commands()) == 1
    assert system.harness.calls == 1


def test_projection_drift_during_compile_cannot_return_a_stale_success() -> None:
    system = _m17_system()

    class AdversarialDriftGraph(ResearchGraphStore):
        def force_projection_drift(self, command):
            qro = command.payload["qro"]
            with self._write_lock:
                self._commands.append(command)
                self._qros[qro.qro_id] = qro
                self._projection_index[qro.qro_id] = (
                    ResearchGraphProjectionRecord.from_qro_command(
                        command=command,
                        qro=qro,
                    )
                )

    graph = AdversarialDriftGraph()

    def compile_then_drift(qro, command, plan):
        result = system.harness.compile(qro, command, plan)
        graph.force_projection_drift(
            ResearchGraphCommand(
                source=EntrySource.API,
                command_type="upsert_qro",
                actor_source=ActorSource.USER_MANUAL,
                actor=OWNER,
                payload={
                    "qro": replace(
                        qro,
                        permission="platform.business_attestation:m17:compile-drift",
                    )
                },
                evidence_refs=("evidence:compile-drift",),
                tool_record_refs=("api:unrelated.compile_drift",),
            )
        )
        return result

    service = PlatformBusinessAttestationService(
        replace(
            system.context,
            research_graph_store=graph,
            compile_attestation=compile_then_drift,
        )
    )

    with pytest.raises(PlatformBusinessAttestationCommitError) as captured:
        service.record(
            owner_user_id=OWNER,
            row="M17",
            anchor_ref=system.refs["submission_ref"],
        )

    assert captured.value.phase == "compiler_coverage"
    assert captured.value.graph_attestation_current is False
    assert captured.value.graph_command_created is True
    assert len(graph.commands()) == 2


def test_m18_records_separate_validation_dossier_without_mutating_old_rdp() -> None:
    system = _m18_system()
    original_graph_refs = system.manifest.graph_refs

    result = PlatformBusinessAttestationService(system.context).record(
        owner_user_id=OWNER,
        row="M18",
        anchor_ref=system.refs["consistency_check_ref"],
    )

    qro = system.graph.qro(result.qro_ref)
    assert qro.qro_type == QROType.VALIDATION_DOSSIER
    assert qro.input_contract == system.refs
    assert qro.output_contract == {"status": "current_code_package_attested"}
    assert result.graph_command_ref not in original_graph_refs
    assert system.manifest.graph_refs == original_graph_refs
    assert system.rdp.mutation_calls == 0
    coverage = system.harness.coverage.coverage(result.entrypoint_coverage_ref, owner=OWNER)
    assert coverage.rdp_refs == (system.refs["rdp_package_ref"],)
    ir = system.harness.store.ir(result.compiler_ir_ref, owner=OWNER)
    assert ir.theory_binding_refs == (system.binding.binding_id,)
    assert ir.consistency_check_refs == (system.check.check_id,)


def test_m18_multiple_owner_rdps_fail_before_graph_write() -> None:
    system = _m18_system()
    system.rdp.current.append(
        SimpleNamespace(
            **{
                **vars(system.manifest),
                "package_id": "rdp:m18:duplicate",
            }
        )
    )

    with pytest.raises(PlatformBusinessAttestationError, match="exactly one"):
        PlatformBusinessAttestationService(system.context).record(
            owner_user_id=OWNER,
            row="M18",
            anchor_ref=system.refs["consistency_check_ref"],
        )

    assert system.graph.commands() == [system.source_command]
    assert system.harness.calls == 0


@pytest.mark.parametrize(
    "manifest_chain_refs",
    (
        (),
        (
            "math_spine_chain:m18:v1",
            "math_spine_chain:m18:same-owner-other",
        ),
        ("math_spine_chain:foreign-owner:m18",),
        ("math_spine_chain:m18:same-owner-other",),
    ),
    ids=("missing", "multiple", "foreign", "mismatched"),
)
def test_m18_rejects_rdp_without_one_exact_selected_math_chain(
    manifest_chain_refs: tuple[str, ...],
) -> None:
    system = _m18_system()
    system.manifest.mathematical_spine_chain_refs = manifest_chain_refs

    with pytest.raises(
        PlatformBusinessAttestationError,
        match="mathematical_spine_chain_refs|exact verified Mathematical Spine chain",
    ):
        PlatformBusinessAttestationService(system.context).record(
            owner_user_id=OWNER,
            row="M18",
            anchor_ref=system.refs["consistency_check_ref"],
        )

    assert system.graph.commands() == [system.source_command]
    assert system.harness.calls == 0


def test_m20_records_risk_policy_without_triggering_or_finalizing_halt() -> None:
    system = _m20_system()

    result = PlatformBusinessAttestationService(system.context).record(
        owner_user_id=OWNER,
        row="M20",
        anchor_ref=system.refs["kill_switch_ref"],
    )

    qro = system.graph.qro(result.qro_ref)
    assert qro.qro_type == QROType.RISK_POLICY
    assert qro.input_contract == system.refs
    assert qro.output_contract == {"status": "halted_security_controls_verified"}
    assert qro.mathematical_refs == (system.chain.chain_ref,)
    assert system.halts.mutation_calls == 0


def test_m20_multiple_eligible_terminal_calls_fail_before_any_write() -> None:
    system = _m20_system()
    system.calls.current.append(
        SimpleNamespace(
            owner_user_id=OWNER,
            call_id="m20-other",
            record_kind="terminal",
            status="ok",
            auth_ref=system.refs["secret_ref"],
        )
    )

    with pytest.raises(PlatformBusinessAttestationError, match="exactly one"):
        PlatformBusinessAttestationService(system.context).record(
            owner_user_id=OWNER,
            row="M20",
            anchor_ref=system.refs["kill_switch_ref"],
        )

    assert system.graph.commands() == []
    assert system.harness.calls == 0
    assert system.halts.mutation_calls == 0


def test_m20_unrelated_owner_chain_is_ignored_by_typed_evidence_constraints() -> None:
    system = _m20_system()
    system.context.spine_chain_registry.current.append(
        _chain(chain_ref="math_spine_chain:m20:other")
    )

    result = PlatformBusinessAttestationService(system.context).record(
        owner_user_id=OWNER,
        row="M20",
        anchor_ref=system.refs["kill_switch_ref"],
    )

    assert result.mathematical_spine_chain_ref == system.chain.chain_ref
    assert len(system.graph.commands()) == 1
    assert system.halts.mutation_calls == 0


def test_m20_owner_chain_without_exact_halt_gateway_proof_fails_closed() -> None:
    system = _m20_system()
    system.context.spine_chain_registry.current[:] = [
        _chain(chain_ref="math_spine_chain:m20:unrelated-only")
    ]

    with pytest.raises(Exception, match="exactly one"):
        PlatformBusinessAttestationService(system.context).record(
            owner_user_id=OWNER,
            row="M20",
            anchor_ref=system.refs["kill_switch_ref"],
        )

    assert system.graph.commands() == []
    assert system.halts.mutation_calls == 0


def test_m20_multiple_chains_for_exact_halt_gateway_proof_fail_closed() -> None:
    system = _m20_system()
    system.context.spine_chain_registry.current.append(
        _chain(
            chain_ref="math_spine_chain:m20:matching-other",
            evidence_refs=(
                system.refs["secret_ref"],
                system.refs["llm_gateway_ref"],
                "flat:m20",
            ),
            validation_refs=(system.refs["kill_switch_ref"], "flat:m20"),
        )
    )

    with pytest.raises(Exception, match="exactly one"):
        PlatformBusinessAttestationService(system.context).record(
            owner_user_id=OWNER,
            row="M20",
            anchor_ref=system.refs["kill_switch_ref"],
        )

    assert system.graph.commands() == []
    assert system.halts.mutation_calls == 0


@pytest.mark.parametrize(
    ("row", "factory", "anchor_key"),
    (
        ("M17", _m17_system, "submission_ref"),
        ("M18", _m18_system, "consistency_check_ref"),
        ("M20", _m20_system, "kill_switch_ref"),
    ),
)
def test_persisted_attestation_replays_through_real_row_policy(
    row: str,
    factory,
    anchor_key: str,
) -> None:
    system = factory()
    resolutions = []

    def validate(result):
        resolution = build_platform_source_lineage_policy_resolver_m16_m21(
            _policy_context(system, row=row)
        ).resolve(
            owner_user_id=OWNER,
            m_row=row,
            anchor_ref=result.anchor_ref,
        )
        resolutions.append(resolution)
        return resolution

    result = PlatformBusinessAttestationService(
        replace(system.context, validate_current_attestation=validate)
    ).record(
        owner_user_id=OWNER,
        row=row,
        anchor_ref=system.refs[anchor_key],
    )
    (resolution,) = resolutions

    assert resolution.qro_ref == result.qro_ref
    assert resolution.business_entrypoint_ref == ENTRYPOINT_REFS[row]
    assert resolution.math_spine_ref == result.mathematical_spine_chain_ref
