"""Resolve canonical persisted evidence for the production IDE promote path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..delivery.rdp import RDPManifest
from ..governance.enforcement_policy import ProducerStatusLedger
from ..lineage.spine import (
    PROMOTION_LABELS,
    STRONG_LABELS,
    WAIVER_LABELS,
    TheorySpec,
)
from ..release_gate.section17_rdp_gate import SECTION17_RDP_PRODUCER_KEY
from ..release_gate.section13_trust_gate import SECTION13_TRUST_PRODUCER_KEY
from ..release_gate.section6_mathchain_gate import SECTION6_MATHCHAIN_PRODUCER_KEY
from ..release_gate.section16_engineering_standards_gate import (
    SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY,
)
from ..release_gate.section9_boundary_gate import SECTION9_BOUNDARY_PRODUCER_KEY
from ..release_gate.section10_methodology_gate import (
    SECTION10_CONTROLPLANE_PRODUCER_KEY,
    SECTION10_COST_PRODUCER_KEY,
)
from ..release_gate.promote_assembler import Section10TierClaim, Section9StrategyBook
from ..research_os.spine import QROType, Section6PromotionClaim


class PromotionEvidenceError(ValueError):
    """Canonical promote evidence is absent, ambiguous, foreign, or incoherent."""


@dataclass(frozen=True)
class CanonicalPromotionEvidence:
    mathchain_claims: tuple[Section6PromotionClaim, ...] = ()
    expert_reviews: tuple[Any, ...] = ()
    release_gates: tuple[Any, ...] = ()
    release_checks: tuple[Any, ...] = ()
    pressure_runs: tuple[Any, ...] = ()
    release_approvals: tuple[Any, ...] = ()
    mock_records: tuple[Any, ...] = ()
    data_updates: tuple[Any, ...] = ()
    llm_calls: tuple[Any, ...] = ()
    theory_claims: tuple[Any, ...] = ()
    fatal_records: tuple[Any, ...] = ()
    performance_records: tuple[Any, ...] = ()
    factor_library_entries: tuple[Any, ...] = ()
    factor_generators: tuple[Any, ...] = ()
    signal_protocols: tuple[Any, ...] = ()
    strategy_books: tuple[Any, ...] = ()
    validation_methodologies: tuple[Any, ...] = ()
    validation_depths: tuple[Any, ...] = ()
    tier_claims: tuple[Any, ...] = ()
    verified_producer_keys: tuple[str, ...] = ()
    honest_gaps: tuple[str, ...] = ()

    def producer_status(self) -> ProducerStatusLedger:
        ledger = ProducerStatusLedger()
        for key in self.verified_producer_keys:
            ledger.mark_green(key)
        return ledger


class CanonicalPromotionEvidenceResolver:
    """Read-only resolver from owner RDP + Spine stores to promote typed inputs."""

    def __init__(
        self,
        *,
        research_graph_store: Any,
        spine_chain_registry: Any,
        spine_ledger: Any,
        current_hash_resolver: Callable[[str, str, str], str | None] | None = None,
        trust_disclosure_registry: Any = None,
        trust_release_gate_registry: Any = None,
        trust_release_check_registry: Any = None,
        trust_pressure_run_registry: Any = None,
        trust_release_approval_registry: Any = None,
        engineering_standards_registry: Any = None,
        section9_evidence_registry: Any = None,
        signal_validation_registry: Any = None,
        validation_methodology_registry: Any = None,
        validation_depth_registry: Any = None,
        methodology_calculator_registry: Any = None,
        methodology_runtime_drill_registry: Any = None,
    ) -> None:
        self._research_graph_store = research_graph_store
        self._spine_chain_registry = spine_chain_registry
        self._spine_ledger = spine_ledger
        self._current_hash_resolver = current_hash_resolver
        self._trust_disclosure_registry = trust_disclosure_registry
        self._trust_release_gate_registry = trust_release_gate_registry
        self._trust_release_check_registry = trust_release_check_registry
        self._trust_pressure_run_registry = trust_pressure_run_registry
        self._trust_release_approval_registry = trust_release_approval_registry
        self._engineering_standards_registry = engineering_standards_registry
        self._section9_evidence_registry = section9_evidence_registry
        self._signal_validation_registry = signal_validation_registry
        self._validation_methodology_registry = validation_methodology_registry
        self._validation_depth_registry = validation_depth_registry
        self._methodology_calculator_registry = methodology_calculator_registry
        self._methodology_runtime_drill_registry = methodology_runtime_drill_registry

    def resolve_section10(
        self,
        *,
        owner: str,
        source_ide_run_id: str,
        requested_label: str,
        chains: tuple[Any, ...],
    ) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Section10TierClaim, ...]] | None:
        if (
            self._validation_methodology_registry is None
            or self._validation_depth_registry is None
            or self._methodology_calculator_registry is None
            or self._methodology_runtime_drill_registry is None
        ):
            return None
        methodologies: list[Any] = []
        depths: list[Any] = []
        tiers: list[Section10TierClaim] = []
        found_any = False
        source_run_ref = f"ide_run:{source_ide_run_id}"
        for chain in chains:
            chain_methodologies: list[Any] = []
            chain_depths: list[Any] = []
            for ref in tuple(chain.validation_refs):
                found_for_ref = 0
                try:
                    methodology = self._validation_methodology_registry.methodology(
                        ref,
                        owner_user_id=owner,
                    )
                    chain_methodologies.append(methodology)
                    found_for_ref += 1
                except KeyError:
                    pass
                try:
                    depth = self._validation_depth_registry.depth(
                        ref,
                        owner_user_id=owner,
                    )
                    chain_depths.append(depth)
                    found_for_ref += 1
                except KeyError:
                    pass
                if found_for_ref > 1:
                    raise PromotionEvidenceError(
                        "§10 validation ref is ambiguous across canonical registries"
                    )
                found_any = found_any or bool(found_for_ref)
            if not chain_methodologies and not chain_depths:
                continue
            if len(chain_methodologies) != 1 or len(chain_depths) != 1:
                raise PromotionEvidenceError(
                    "§10 chain must cite exactly one methodology and one validation depth"
                )
            methodology = chain_methodologies[0]
            depth = chain_depths[0]
            methodology_binding = self._validation_methodology_registry.methodology_binding(
                methodology.validation_ref,
                owner_user_id=owner,
            )
            depth_binding = self._validation_depth_registry.depth_binding(
                depth.depth_ref,
                owner_user_id=owner,
            )
            for binding in (methodology_binding, depth_binding):
                if (
                    binding.owner_user_id != owner
                    or binding.source_run_ref != source_run_ref
                    or binding.backtest_run_ref != chain.backtest_run_ref
                ):
                    raise PromotionEvidenceError(
                        "§10 evidence envelope does not bind the exact owner source run and BacktestRun"
                    )
            if (
                depth.claim_ref != methodology.validation_ref
                or methodology.claim_label != requested_label
                or depth.claim_label != requested_label
                or methodology.methodology_choice_ref != chain.methodology_choice_ref
                or depth.methodology_choice_ref != chain.methodology_choice_ref
                or methodology.responsibility_boundary_ref
                != chain.responsibility_boundary_ref
                or depth.responsibility_boundary_ref != chain.responsibility_boundary_ref
                or methodology.target_environment != depth.target_environment
                or methodology.target_environment != str(chain.target_runtime)
            ):
                raise PromotionEvidenceError(
                    "§10 methodology/depth/choice/responsibility/runtime closure is incoherent"
                )
            try:
                cpcv = self._methodology_calculator_registry.cpcv(
                    str(methodology.cpcv_ref or ""),
                    owner_user_id=owner,
                )
                conformal = self._methodology_calculator_registry.conformal(
                    str(depth.conformal_ref or ""),
                    owner_user_id=owner,
                )
                tca = self._methodology_calculator_registry.tca(
                    str(methodology.tca_ref or ""),
                    owner_user_id=owner,
                )
                fault_drills = tuple(
                    self._methodology_runtime_drill_registry.by_fault_injection_ref(
                        ref,
                        owner_user_id=owner,
                    )
                    for ref in depth.fault_injection_refs
                )
                recovery_drills = tuple(
                    self._methodology_runtime_drill_registry.by_recovery_drill_ref(
                        ref,
                        owner_user_id=owner,
                    )
                    for ref in depth.recovery_drill_refs
                )
            except KeyError as exc:
                raise PromotionEvidenceError(
                    "§10 methodology/depth cites unpersisted owner calculator or runtime drill evidence"
                ) from exc
            calculators = (
                ("cpcv", cpcv.cpcv_ref, cpcv),
                ("conformal", conformal.conformal_ref, conformal),
                ("tca", tca.tca_ref, tca),
            )
            for kind, ref, calculator in calculators:
                binding = self._methodology_calculator_registry.binding(
                    kind,
                    ref,
                    owner_user_id=owner,
                )
                if (
                    binding.source_run_ref != source_run_ref
                    or binding.backtest_run_ref != chain.backtest_run_ref
                    or calculator.claim_ref != methodology.validation_ref
                ):
                    raise PromotionEvidenceError(
                        "§10 calculator evidence does not bind the exact validation and source run"
                    )
            if depth.cpcv_ref != methodology.cpcv_ref or depth.tca_ref != methodology.tca_ref:
                raise PromotionEvidenceError(
                    "§10 methodology and depth calculator refs are inconsistent"
                )
            runtime_drills = {*fault_drills, *recovery_drills}
            if len(runtime_drills) != len(fault_drills) or len(runtime_drills) != len(recovery_drills):
                raise PromotionEvidenceError(
                    "§10 fault and recovery refs must resolve to the same exact runtime drill set"
                )
            for drill in runtime_drills:
                binding = self._methodology_runtime_drill_registry.runtime_drill_binding(
                    drill.runtime_drill_ref,
                    owner_user_id=owner,
                )
                if (
                    binding.source_run_ref != source_run_ref
                    or binding.backtest_run_ref != chain.backtest_run_ref
                    or drill.claim_ref != methodology.validation_ref
                    or drill.target_environment != methodology.target_environment
                ):
                    raise PromotionEvidenceError(
                        "§10 runtime drill does not bind the exact validation and source run"
                    )
            choice = self._spine_ledger.choice(
                chain.methodology_choice_ref,
                owner=owner,
            )
            methodologies.append(methodology)
            depths.append(depth)
            tiers.append(
                Section10TierClaim(
                    claimed_label=requested_label,
                    methodology_choice=choice,
                )
            )
        if not found_any:
            return None
        if len(methodologies) != len(chains) or len(depths) != len(chains):
            raise PromotionEvidenceError(
                "§10 evidence must cover every promoted Mathematical Spine chain"
            )
        return tuple(methodologies), tuple(depths), tuple(tiers)

    @staticmethod
    def _qro_type(qro: Any) -> str:
        value = getattr(qro, "qro_type", "")
        return str(getattr(value, "value", value) or "")

    def resolve_section9(
        self,
        *,
        owner: str,
        chains: tuple[Any, ...],
        run_qros: dict[str, Any],
    ) -> tuple[Any, Section9StrategyBook] | None:
        if self._section9_evidence_registry is None:
            return None
        if self._signal_validation_registry is None:
            raise PromotionEvidenceError(
                "§9 canonical signal validation registry is unavailable"
            )
        snapshot_refs: set[str] = set()
        strategy_refs: set[str] = set()
        for chain in chains:
            qro = run_qros[chain.chain_ref]
            input_contract = getattr(qro, "input_contract", None)
            if not isinstance(input_contract, dict):
                raise PromotionEvidenceError("§9 requires a typed BacktestRun input contract")
            snapshot_ref = str(input_contract.get("section9_evidence_ref") or "").strip()
            strategy_ref = str(input_contract.get("strategy_id") or "").strip()
            if not snapshot_ref:
                return None
            if not strategy_ref:
                raise PromotionEvidenceError("§9 BacktestRun QRO is missing source strategy identity")
            snapshot_refs.add(snapshot_ref)
            strategy_refs.add(strategy_ref)
        if len(snapshot_refs) != 1 or len(strategy_refs) != 1:
            raise PromotionEvidenceError(
                "§9 Mathematical Spine chains must bind one exact pre-run snapshot and strategy"
            )
        snapshot_ref = next(iter(snapshot_refs))
        try:
            snapshot = self._section9_evidence_registry.snapshot(
                snapshot_ref,
                owner_user_id=owner,
            )
        except KeyError as exc:
            raise PromotionEvidenceError(
                "§9 pre-run snapshot is not persisted for this owner"
            ) from exc
        if snapshot.source_strategy_ref != next(iter(strategy_refs)):
            raise PromotionEvidenceError(
                "§9 pre-run snapshot does not bind the BacktestRun source strategy"
            )

        factor_refs = {str(chain.factor_ref) for chain in chains}
        signal_refs = {str(chain.signal_contract_ref) for chain in chains}
        strategy_book_refs = {str(chain.strategy_book_ref) for chain in chains}
        if factor_refs != {str(item.factor_ref) for item in snapshot.factor_library_entries}:
            raise PromotionEvidenceError("§9 factor snapshot does not match Mathematical Spine")
        if signal_refs != {str(item.signal_ref) for item in snapshot.signal_protocols}:
            raise PromotionEvidenceError("§9 signal snapshot does not match Mathematical Spine")
        if strategy_book_refs != {str(snapshot.strategy_book.strategy_book_ref)}:
            raise PromotionEvidenceError("§9 StrategyBook snapshot does not match Mathematical Spine")

        for refs, expected_type, label in (
            (factor_refs, QROType.FACTOR.value, "factor"),
            (signal_refs, QROType.SIGNAL.value, "signal"),
            (strategy_book_refs, QROType.STRATEGY_BOOK.value, "StrategyBook"),
        ):
            for ref in refs:
                try:
                    qro = self._research_graph_store.qro(ref)
                except (KeyError, LookupError) as exc:
                    raise PromotionEvidenceError(
                        f"§9 {label} ref is not a persisted QRO"
                    ) from exc
                if str(getattr(qro, "owner", "") or "") != owner or self._qro_type(qro) != expected_type:
                    raise PromotionEvidenceError(
                        f"§9 {label} QRO has wrong owner or QROType"
                    )

        factor_library = {
            str(item.factor_ref): item for item in snapshot.factor_library_entries
        }
        signal_protocols = {
            str(item.signal_ref): item for item in snapshot.signal_protocols
        }
        signal_validations = {
            str(item.validation_id): item for item in snapshot.signal_validations
        }
        for validation_ref, embedded_validation in signal_validations.items():
            try:
                persisted_validation = self._signal_validation_registry.validation(
                    validation_ref,
                    owner_user_id=owner,
                )
            except KeyError as exc:
                raise PromotionEvidenceError(
                    "§9 snapshot signal validation is not persisted for this owner"
                ) from exc
            if persisted_validation != embedded_validation:
                raise PromotionEvidenceError(
                    "§9 snapshot signal validation does not exactly match the owner registry"
                )
        return snapshot, Section9StrategyBook(
            book=snapshot.strategy_book,
            factor_library=factor_library,
            signal_protocols=signal_protocols,
            signal_validations=signal_validations,
            require_signal_validation=True,
        )

    def resolve_engineering_standards(
        self,
        *,
        manifest: RDPManifest,
        owner: str,
        source_ide_run_id: str,
        requested_label: str,
        mathchain_claims: tuple[Section6PromotionClaim, ...],
    ) -> Any | None:
        if self._engineering_standards_registry is None:
            return None
        source_run_ref = f"ide_run:{source_ide_run_id}"
        try:
            record = self._engineering_standards_registry.run_record(
                source_run_ref,
                owner_user_id=owner,
            )
        except KeyError:
            return None
        if str(record.source_run_ref) != source_run_ref:
            raise PromotionEvidenceError(
                "engineering standards record does not bind the exact IDE source run"
            )

        expected_dataset_refs = {str(ref) for ref in manifest.dataset_version_refs}
        actual_dataset_refs = {
            str(item.dataset_version_ref or "") for item in record.data_updates
        }
        if actual_dataset_refs != expected_dataset_refs:
            raise PromotionEvidenceError(
                "engineering standards data updates do not exactly match RDP dataset versions"
            )

        expected_llm_refs = {str(ref) for ref in manifest.llm_call_refs}
        actual_llm_refs = {str(item.call_ref) for item in record.llm_calls}
        if actual_llm_refs != expected_llm_refs:
            raise PromotionEvidenceError(
                "engineering standards LLM records do not exactly match RDP llm_call_refs"
            )

        expected_theory_pairs = {
            (str(claim.binding.binding_id), str(check.check_id))
            for claim in mathchain_claims
            for check in claim.consistency_checks
        }
        actual_theory_pairs = {
            (
                str(item.theory_implementation_binding_ref or ""),
                str(item.consistency_check_ref or ""),
            )
            for item in record.theory_claims
        }
        if (
            actual_theory_pairs != expected_theory_pairs
            or any(item.display_label != requested_label for item in record.theory_claims)
        ):
            raise PromotionEvidenceError(
                "engineering standards theory records do not exactly match the promote Mathematical Spine closure"
            )
        return record

    def resolve_trust_release(
        self,
        manifest: RDPManifest,
        *,
        owner: str,
    ) -> tuple[tuple[Any, ...], tuple[Any, ...], tuple[Any, ...], tuple[Any, ...], tuple[Any, ...]]:
        release_ref = str(manifest.trust_release_ref or "").strip()
        if not release_ref:
            return (), (), (), (), ()
        registries = (
            self._trust_disclosure_registry,
            self._trust_release_gate_registry,
            self._trust_release_check_registry,
            self._trust_pressure_run_registry,
            self._trust_release_approval_registry,
        )
        if any(registry is None for registry in registries):
            raise PromotionEvidenceError(
                "RDP trust_release_ref requires the canonical trust registry bundle"
            )
        approval_ref = str(manifest.approval_ref or "").strip()
        if not approval_ref:
            raise PromotionEvidenceError(
                "RDP trust_release_ref requires approval_ref"
            )
        try:
            gate = self._trust_release_gate_registry.gate(
                release_ref,
                owner_user_id=owner,
            )
            approval = self._trust_release_approval_registry.approval(
                approval_ref,
                owner_user_id=owner,
            )
            pressure = self._trust_pressure_run_registry.run(
                approval.pressure_run_ref,
                owner_user_id=owner,
            )
            review = self._trust_disclosure_registry.external_expert_review(
                approval.expert_review_ref,
                owner_user_id=owner,
            )
        except (KeyError, LookupError, ValueError) as exc:
            raise PromotionEvidenceError(
                "RDP trust release bundle is not persisted for this owner"
            ) from exc
        gate_check_refs = tuple(
            str(ref)
            for ref in (
                gate.anti_flattery_pressure_test_ref,
                gate.multi_turn_pressure_test_ref,
                gate.expert_veto_ref,
                gate.weakness_collapse_check_ref,
                gate.mock_honesty_check_ref,
                gate.cold_start_honesty_check_ref,
            )
            if str(ref or "").strip()
        )
        if len(gate_check_refs) != 6:
            raise PromotionEvidenceError(
                "RDP trust release gate must cite all six canonical checks"
            )
        try:
            checks = tuple(
                self._trust_release_check_registry.check(
                    check_ref,
                    owner_user_id=owner,
                )
                for check_ref in gate_check_refs
            )
        except (KeyError, LookupError, ValueError) as exc:
            raise PromotionEvidenceError(
                "RDP trust release gate cites an unpersisted owner check"
            ) from exc
        if any(check.release_ref != release_ref for check in checks):
            raise PromotionEvidenceError(
                "RDP trust release checks do not bind the exact release_ref"
            )
        if (
            approval.release_ref != release_ref
            or approval.release_gate_ref != release_ref
            or pressure.release_ref != release_ref
            or pressure.release_gate_ref != release_ref
            or review.release_ref != release_ref
            or approval.pressure_run_ref != pressure.runner_ref
            or approval.expert_review_ref != review.review_ref
            or set(pressure.check_refs) != set(gate_check_refs)
            or approval.artifact_ref not in set(manifest.asset_refs)
        ):
            raise PromotionEvidenceError(
                "RDP trust release gate/check/pressure/review/approval lineage is incoherent"
            )
        return (review,), (gate,), checks, (pressure,), (approval,)

    @staticmethod
    def _label(requested_label: str) -> str:
        value = str(requested_label or "").strip()
        if value not in PROMOTION_LABELS:
            raise PromotionEvidenceError(f"unsupported promote requested_label: {value!r}")
        return value

    @staticmethod
    def _exact_refs(
        manifest: RDPManifest,
        closures: tuple[Any, ...],
        *,
        manifest_field: str,
        closure_field: str,
    ) -> None:
        actual = {str(ref) for ref in tuple(getattr(manifest, manifest_field, ()) or ())}
        expected = {
            str(ref)
            for closure in closures
            for ref in tuple(getattr(closure, closure_field, ()) or ())
        }
        if actual != expected:
            raise PromotionEvidenceError(
                f"RDP {manifest_field} does not exactly match verified Mathematical Spine closure"
            )

    def resolve(
        self,
        *,
        owner_user_id: str,
        source_ide_run_id: str,
        requested_label: str,
        rdp: RDPManifest | None,
        source_result_content_hash: str | None = None,
    ) -> CanonicalPromotionEvidence:
        owner = str(owner_user_id or "").strip()
        if not owner:
            raise PromotionEvidenceError("promotion evidence resolver requires owner_user_id")
        label = self._label(requested_label)
        expected_result_hash = str(source_result_content_hash or "").strip()
        if rdp is None:
            return CanonicalPromotionEvidence(
                honest_gaps=(
                    "section6_mathchain:canonical RDP and Mathematical Spine closure absent",
                    "section13_trust:canonical trust release bundle absent",
                    "section17_rdp:canonical persisted RDP absent",
                )
            )

        chain_refs = tuple(str(ref) for ref in rdp.mathematical_spine_chain_refs)
        if not chain_refs:
            raise PromotionEvidenceError(
                "persisted RDP does not cite a Mathematical Spine chain"
            )

        chains: list[Any] = []
        closures: list[Any] = []
        run_qros: dict[str, Any] = {}
        for chain_ref in chain_refs:
            try:
                chain = self._spine_chain_registry.verified_chain(
                    chain_ref,
                    owner=owner,
                )
                closure = self._spine_chain_registry.verified_chain_record_refs(
                    chain_ref,
                    owner=owner,
                )
                qro = self._research_graph_store.qro(chain.backtest_run_ref)
            except (KeyError, LookupError, ValueError) as exc:
                raise PromotionEvidenceError(
                    f"Mathematical Spine chain {chain_ref!r} is not currently owner-verified"
                ) from exc
            qro_type = str(getattr(getattr(qro, "qro_type", ""), "value", getattr(qro, "qro_type", "")) or "")
            output_contract = getattr(qro, "output_contract", None)
            if (
                str(getattr(qro, "owner", "") or "") != owner
                or qro_type != QROType.BACKTEST_RUN.value
                or not isinstance(output_contract, dict)
                or str(output_contract.get("run_id") or "") != source_ide_run_id
            ):
                raise PromotionEvidenceError(
                    "Mathematical Spine backtest_run_ref must bind the exact owner IDE run QRO"
                )
            if expected_result_hash and str(
                output_contract.get("result_content_hash") or ""
            ) != expected_result_hash:
                raise PromotionEvidenceError(
                    "Mathematical Spine BacktestRun QRO does not bind the exact IDE result content"
                )
            chains.append(chain)
            closures.append(closure)
            run_qros[chain_ref] = qro

        closure_tuple = tuple(closures)
        for manifest_field, closure_field in (
            ("mathematical_refs", "mathematical_refs"),
            ("theory_binding_refs", "theory_binding_refs"),
            ("consistency_check_refs", "consistency_check_refs"),
            ("methodology_choice_refs", "methodology_choice_refs"),
            ("responsibility_refs", "responsibility_refs"),
        ):
            self._exact_refs(
                rdp,
                closure_tuple,
                manifest_field=manifest_field,
                closure_field=closure_field,
            )

        claims: list[Section6PromotionClaim] = []
        for chain, closure in zip(chains, closures, strict=True):
            qro = run_qros[chain.chain_ref]
            checks = tuple(
                self._spine_ledger.check(ref, owner=owner)
                for ref in closure.consistency_check_refs
            )
            choice = self._spine_ledger.choice(
                chain.methodology_choice_ref,
                owner=owner,
            )
            for binding_ref in closure.theory_binding_refs:
                binding = self._spine_ledger.binding(binding_ref, owner=owner)
                theory = self._spine_ledger.theory(binding.theory_ref, owner=owner)
                artifact = (
                    self._spine_ledger.artifact(theory.artifact_ref, owner=owner)
                    if isinstance(theory, TheorySpec)
                    else theory
                )
                bound_checks = tuple(
                    check for check in checks if check.binding_id == binding.binding_id
                )
                if not bound_checks:
                    raise PromotionEvidenceError(
                        "verified Mathematical Spine closure has no check for a cited binding"
                    )
                current_code_hash = (
                    self._current_hash_resolver("code", binding.code_ref, owner)
                    if self._current_hash_resolver is not None
                    else None
                )
                if label in STRONG_LABELS and current_code_hash is None:
                    raise PromotionEvidenceError(
                        "strong promote label requires current implementation hash resolution"
                    )
                claims.append(
                    Section6PromotionClaim(
                        requested_label=label,
                        artifact=artifact,
                        binding=binding,
                        consistency_checks=bound_checks,
                        choice=choice,
                        data_contract={
                            "known_at": getattr(qro, "known_at", None),
                            "effective_at": getattr(qro, "effective_at", None),
                        },
                        current_code_hash=current_code_hash,
                        asset_ref=qro.qro_id,
                    )
                )
        if not claims:
            raise PromotionEvidenceError(
                "verified Mathematical Spine closure produced no promotion claims"
            )
        expert_reviews, release_gates, release_checks, pressure_runs, approvals = (
            self.resolve_trust_release(rdp, owner=owner)
        )
        verified_keys = [
            SECTION6_MATHCHAIN_PRODUCER_KEY,
            SECTION17_RDP_PRODUCER_KEY,
        ]
        honest_gaps: list[str] = []
        if release_gates:
            verified_keys.append(SECTION13_TRUST_PRODUCER_KEY)
        else:
            honest_gaps.append(
                "section13_trust:canonical trust release bundle absent"
            )

        engineering_record = self.resolve_engineering_standards(
            manifest=rdp,
            owner=owner,
            source_ide_run_id=source_ide_run_id,
            requested_label=label,
            mathchain_claims=tuple(claims),
        )
        if engineering_record is not None:
            verified_keys.append(SECTION16_ENGINEERING_STANDARDS_PRODUCER_KEY)
        else:
            honest_gaps.append(
                "section16_engineering_standards:canonical owner run package absent"
            )
        section9 = self.resolve_section9(
            owner=owner,
            chains=tuple(chains),
            run_qros=run_qros,
        )
        if section9 is not None:
            section9_snapshot, section9_book = section9
            verified_keys.append(SECTION9_BOUNDARY_PRODUCER_KEY)
        else:
            section9_snapshot = None
            section9_book = None
            honest_gaps.append("section9_boundary:canonical pre-run snapshot absent")
        section10 = self.resolve_section10(
            owner=owner,
            source_ide_run_id=source_ide_run_id,
            requested_label=label,
            chains=tuple(chains),
        )
        if section10 is not None:
            validation_methodologies, validation_depths, tier_claims = section10
            verified_keys.extend(
                (
                    SECTION10_COST_PRODUCER_KEY,
                    SECTION10_CONTROLPLANE_PRODUCER_KEY,
                )
            )
        else:
            validation_methodologies = ()
            validation_depths = ()
            tier_claims = ()
            honest_gaps.append("section10:canonical chain validation evidence absent")
        return CanonicalPromotionEvidence(
            mathchain_claims=tuple(claims),
            expert_reviews=expert_reviews,
            release_gates=release_gates,
            release_checks=release_checks,
            pressure_runs=pressure_runs,
            release_approvals=approvals,
            mock_records=(
                engineering_record.mock_records if engineering_record is not None else ()
            ),
            data_updates=(
                engineering_record.data_updates if engineering_record is not None else ()
            ),
            llm_calls=(engineering_record.llm_calls if engineering_record is not None else ()),
            theory_claims=(
                engineering_record.theory_claims if engineering_record is not None else ()
            ),
            fatal_records=(
                engineering_record.fatal_records if engineering_record is not None else ()
            ),
            performance_records=(
                engineering_record.performance_records
                if engineering_record is not None
                else ()
            ),
            factor_library_entries=(
                section9_snapshot.factor_library_entries
                if section9_snapshot is not None
                else ()
            ),
            factor_generators=(
                tuple(item.generator for item in section9_snapshot.factor_generations)
                if section9_snapshot is not None
                else ()
            ),
            signal_protocols=(
                section9_snapshot.signal_protocols
                if section9_snapshot is not None
                else ()
            ),
            strategy_books=((section9_book,) if section9_book is not None else ()),
            validation_methodologies=validation_methodologies,
            validation_depths=validation_depths,
            tier_claims=tier_claims,
            verified_producer_keys=tuple(verified_keys),
            honest_gaps=tuple(honest_gaps),
        )


__all__ = [
    "CanonicalPromotionEvidence",
    "CanonicalPromotionEvidenceResolver",
    "PromotionEvidenceError",
]
