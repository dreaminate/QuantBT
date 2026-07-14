from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.copy_trade.service import Follower, copy_trade_subscription_ref
from app.ide.service import StrategyFile
from app.research_os.asset_lifecycle import GovernedAssetRecord
from app.research_os.platform_business_history_m16_m21 import (
    m21_governed_template_snapshot_hash,
    m21_ide_strategy_snapshot_hash,
)
from app.sharing import SharingService
from app.research_os.platform_coverage import (
    PlatformCapabilityRecord,
    PlatformSpecificRef,
)
from app.research_os.platform_source_adapters_m16_m21 import (
    PlatformSourceAdaptersM16M21Context,
    build_platform_source_adapters_m16_m21,
    unavailable_platform_source_rows_m16_m21,
)


OWNER = "owner-platform-m16-m21"


def _record(
    row: str,
    specific: dict[str, str],
    **overrides,
) -> PlatformCapabilityRecord:
    values = {
        "m_row": row,
        "qro_ref": f"qro:{row}",
        "research_graph_ref": f"rgcmd:{row}",
        "lifecycle_ref": f"lifecycle:{row}",
        "governance_ref": f"goal_validation_receipt:{row}",
        "rag_ref": f"rag:{row}",
        "math_spine_ref": f"math:{row}",
        "evidence_refs": (f"evidence:{row}",),
        "specific_refs": tuple(
            PlatformSpecificRef(key, ref) for key, ref in specific.items()
        ),
    }
    values.update(overrides)
    return PlatformCapabilityRecord(**values)


def test_builder_exposes_rows_without_complete_typed_bundles() -> None:
    adapters, validators = build_platform_source_adapters_m16_m21(
        PlatformSourceAdaptersM16M21Context()
    )
    unavailable = unavailable_platform_source_rows_m16_m21(
        PlatformSourceAdaptersM16M21Context()
    )

    assert adapters == {}
    assert validators == {}
    assert set(unavailable) == {"M16", "M17", "M18", "M19", "M20", "M21"}
    assert "sharing_service" in " ".join(unavailable["M16"])
    assert "teaching_asset_registry" in " ".join(unavailable["M19"])


def test_m21_availability_requires_ide_loader_without_affecting_m16() -> None:
    dependency = object()
    without_loader = PlatformSourceAdaptersM16M21Context(
        research_graph_store=dependency,
        sharing_service=dependency,
        asset_lifecycle_registry=dependency,
        rag_index=dependency,
        spine_chain_registry=dependency,
    )

    unavailable = unavailable_platform_source_rows_m16_m21(without_loader)

    assert "M16" not in unavailable
    assert unavailable["M21"] == ("missing dependency:ide_strategy_loader",)
    with_loader = replace(
        without_loader,
        ide_strategy_loader=lambda _ref, _owner: dependency,
    )
    assert "M21" not in unavailable_platform_source_rows_m16_m21(with_loader)


def _m16_fixture(tmp_path):
    run_root = tmp_path / "runs"
    run_dir = run_root / "run-shared"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text("{}", encoding="utf-8")
    sharing = SharingService(tmp_path / "community.db", run_root)
    strategy = sharing.publish_strategy(
        "run-shared",
        OWNER,
        "Shared strategy",
        asset_class="equity_cn",
        public=True,
    )
    refs = strategy.to_dict()
    exact_refs = {
        refs["shared_asset_ref"],
        refs["permission_ref"],
        refs["source_ref"],
        refs["status_ref"],
    }
    qro = SimpleNamespace(
        qro_id="qro:M16",
        owner=OWNER,
        input_contract={"sharing_refs": tuple(exact_refs)},
        output_contract={"status": "published"},
        mathematical_refs=("math:M16",),
    )
    asset = SimpleNamespace(
        asset_ref=refs["shared_asset_ref"],
        asset_type="SharedStrategy",
        lifecycle_state="linked",
        evidence_refs=(refs["permission_ref"], refs["source_ref"], refs["status_ref"]),
    )
    document = SimpleNamespace(metadata={"sharing_refs": tuple(exact_refs)})
    chain = SimpleNamespace(chain_ref="math:M16", recorded_by=OWNER)

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    class Lifecycle:
        def governed_asset(self, ref, *, owner_user_id):
            if ref != asset.asset_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return asset

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != "rag:M16" or owner_user_id != OWNER or require_current is not True:
                raise KeyError(ref)
            return document

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "math:M16" or owner != OWNER:
                raise KeyError(ref)
            return chain

    context = PlatformSourceAdaptersM16M21Context(
        research_graph_store=Graph(),
        sharing_service=sharing,
        asset_lifecycle_registry=Lifecycle(),
        rag_index=RAG(),
        spine_chain_registry=Spine(),
    )
    record = _record(
        "M16",
        {
            "shared_asset_ref": refs["shared_asset_ref"],
            "permission_ref": refs["permission_ref"],
            "source_ref": refs["source_ref"],
            "status_ref": refs["status_ref"],
        },
        lifecycle_ref=refs["shared_asset_ref"],
    )
    return context, record, strategy


def test_m16_binds_shared_asset_permission_source_status_and_lifecycle(tmp_path) -> None:
    context, record, _strategy = _m16_fixture(tmp_path)
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {
        key: adapters[key].load(refs[key], OWNER, record)
        for key in refs
    }

    assert validators["M16"](record, OWNER, values) == ()


def test_m16_rejects_recombined_governance_record(tmp_path) -> None:
    context, record, _strategy = _m16_fixture(tmp_path)
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {
        key: adapters[key].load(refs[key], OWNER, record)
        for key in refs
    }
    values["status_ref"] = SimpleNamespace(
        shared_asset_ref="shared_asset:other",
        owner_user_id=OWNER,
        status="published_public",
    )

    assert "recombine" in " ".join(validators["M16"](record, OWNER, values))


def test_m16_rejects_same_owner_unrelated_lifecycle_asset(tmp_path) -> None:
    context, record, _strategy = _m16_fixture(tmp_path)
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {key: adapters[key].load(refs[key], OWNER, record) for key in refs}

    recombined = replace(record, lifecycle_ref="shared_asset:same-owner-unrelated")

    assert "common lifecycle ref is not the shared strategy asset" in " ".join(
        validators["M16"](recombined, OWNER, values)
    )


def test_m16_rejects_qro_without_exact_math_binding(tmp_path) -> None:
    context, record, _strategy = _m16_fixture(tmp_path)
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {key: adapters[key].load(refs[key], OWNER, record) for key in refs}
    context.research_graph_store.qro(record.qro_ref).mathematical_refs = ()

    assert "must bind exactly" in " ".join(
        validators["M16"](record, OWNER, values)
    )


def _m17_fixture():
    promotion_ref = "runtime_promotion_copy_trade"
    risk_ref = "copy_risk_check_current"
    audit_ref = "copy_submission_audit_current"
    follower = Follower(
        follower_id="follower-owner::master-a",
        user_id=OWNER,
        master_id="master-a",
        account_binding_ref="account:owner",
        credential_binding_ref="credential:owner",
        runtime_promotion_ref=promotion_ref,
        status="active",
    )
    subscription_ref = copy_trade_subscription_ref(follower)
    from app.lineage.ids import content_hash

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
        permission_gate_ref="permission:copy-trade",
        order_guard_ref="order_guard:copy-trade",
    )
    reservation = SimpleNamespace(
        reservation_ref="copy_reservation_current",
        risk_check_ref=risk_ref,
        follower_id=follower.follower_id,
        account_binding_ref=follower.account_binding_ref,
    )
    submission = SimpleNamespace(
        submission_ref="order_submission_current",
        audit_record_ref=audit_ref,
        runtime_promotion_ref=promotion_ref,
        permission_gate_ref=promotion.permission_gate_ref,
        order_guard_ref=promotion.order_guard_ref,
        submit_enabled=True,
    )
    exact_refs = {
        subscription_ref,
        promotion_ref,
        risk_ref,
        audit_ref,
    }
    qro = SimpleNamespace(
        qro_id="qro:M17",
        owner=OWNER,
        input_contract={"source_refs": tuple(exact_refs)},
        output_contract={"status": "guarded"},
        mathematical_refs=("math:M17",),
    )
    document = SimpleNamespace(metadata={"source_refs": tuple(exact_refs)})
    chain = SimpleNamespace(chain_ref="math:M17", recorded_by=OWNER)

    class Subscriptions:
        def subscription(self, ref, *, owner_user_id):
            if ref != subscription_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return follower

    class Promotions:
        def promotion(self, ref):
            if ref != promotion_ref:
                raise KeyError(ref)
            return promotion

    class Risks:
        def reservation_by_risk_check_ref(self, ref):
            if ref != risk_ref:
                raise KeyError(ref)
            return reservation

        def reservation_for_submission(self, ref):
            if ref != submission.submission_ref:
                raise KeyError(ref)
            return reservation

    class Submissions:
        def submission_by_audit_record_ref(self, ref):
            if ref != audit_ref:
                raise KeyError(ref)
            return submission

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != "rag:M17" or owner_user_id != OWNER or require_current is not True:
                raise KeyError(ref)
            return document

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "math:M17" or owner != OWNER:
                raise KeyError(ref)
            return chain

    context = PlatformSourceAdaptersM16M21Context(
        research_graph_store=Graph(),
        copy_trade_service=Subscriptions(),
        runtime_promotion_registry=Promotions(),
        follower_risk_state_store=Risks(),
        execution_order_submission_registry=Submissions(),
        rag_index=RAG(),
        spine_chain_registry=Spine(),
    )
    record = _record(
        "M17",
        {
            "copy_trade_subscription_ref": subscription_ref,
            "runtime_promotion_ref": promotion_ref,
            "risk_gate_ref": risk_ref,
            "execution_audit_ref": audit_ref,
        },
        lifecycle_ref=promotion_ref,
    )
    return context, record, reservation, submission


def test_m17_binds_subscription_promotion_risk_gate_and_guarded_submission() -> None:
    context, record, _reservation, _submission = _m17_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {
        key: adapters[key].load(refs[key], OWNER, record)
        for key in refs
    }

    assert validators["M17"](record, OWNER, values) == ()


def test_m17_rejects_same_owner_risk_reservation_recombination() -> None:
    context, record, reservation, _submission = _m17_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {
        key: adapters[key].load(refs[key], OWNER, record)
        for key in refs
    }
    values["risk_gate_ref"] = SimpleNamespace(
        reservation_ref="copy_reservation_other",
        risk_check_ref=reservation.risk_check_ref,
        follower_id=reservation.follower_id,
        account_binding_ref=reservation.account_binding_ref,
    )

    assert "different risk reservation" in " ".join(
        validators["M17"](record, OWNER, values)
    )


def test_m17_rejects_same_owner_unrelated_lifecycle_promotion() -> None:
    context, record, _reservation, _submission = _m17_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {key: adapters[key].load(refs[key], OWNER, record) for key in refs}

    recombined = replace(record, lifecycle_ref="runtime_promotion_same_owner_other")

    assert "common lifecycle ref is not the selected runtime promotion" in " ".join(
        validators["M17"](recombined, OWNER, values)
    )


def _m18_fixture():
    command_ref = "rgcmd_ide_code_current"
    check_ref = "cc_ide_code_current"
    code_hash = "sha256:ide-code-current"
    qro = SimpleNamespace(
        qro_id="qro:M18:ide-source",
        owner=OWNER,
        input_contract={"entry_source": "ide", "code_hash": code_hash},
        output_contract={"status": "ok"},
        mathematical_refs=("math:M18",),
    )
    command = SimpleNamespace(
        command_id=command_ref,
        actor=OWNER,
        source="ide",
        payload={"qro": qro},
    )
    binding = SimpleNamespace(
        binding_id="tib_ide_code_current",
        used_by=(command_ref,),
    )
    check = SimpleNamespace(
        check_id=check_ref,
        binding_id=binding.binding_id,
        result="pass",
        input_refs=(command_ref,),
    )
    manifest = SimpleNamespace(
        package_id="rdp_ide_code_current",
        graph_refs=(command_ref,),
        code_refs=(code_hash,),
        asset_refs=(),
        source_file_refs=(),
        consistency_check_refs=(check_ref,),
        test_refs=("test:ide-code",),
        unverified_residuals=(),
        mathematical_spine_chain_refs=("math:M18",),
    )
    document = SimpleNamespace(
        metadata={
            "canonical_code_command_ref": command_ref,
            "consistency_check_ref": check_ref,
        }
    )
    chain = SimpleNamespace(chain_ref="math:M18", recorded_by=OWNER)

    class Graph:
        current = [command]

        def commands(self):
            return list(self.current)

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
        current = [manifest]

        def manifests(self, *, owner_user_id):
            return list(self.current) if owner_user_id == OWNER else []

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != "rag:M18" or owner_user_id != OWNER or require_current is not True:
                raise KeyError(ref)
            return document

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "math:M18" or owner != OWNER:
                raise KeyError(ref)
            return chain

    context = PlatformSourceAdaptersM16M21Context(
        research_graph_store=Graph(),
        canonical_spine_ledger=Ledger(),
        rdp_store=RDPs(),
        rag_index=RAG(),
        spine_chain_registry=Spine(),
    )
    record = _record(
        "M18",
        {
            "canonical_code_command_ref": command_ref,
            "consistency_check_ref": check_ref,
        },
        qro_ref="qro:M18:business-attestation",
        research_graph_ref="rgcmd:M18:business-attestation",
        lifecycle_ref=manifest.package_id,
    )
    return context, record, manifest


def test_m18_binds_ide_command_consistency_check_tests_and_rdp() -> None:
    context, record, _manifest = _m18_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {
        key: adapters[key].load(refs[key], OWNER, record)
        for key in refs
    }

    assert validators["M18"](record, OWNER, values) == ()
    assert record.research_graph_ref != refs["canonical_code_command_ref"]
    assert record.qro_ref != values["canonical_code_command_ref"].payload[
        "qro"
    ].qro_id


@pytest.mark.parametrize("mutation", ("missing", "foreign_owner"))
def test_m18_rejects_missing_or_foreign_canonical_ide_command(
    mutation: str,
) -> None:
    context, record, _manifest = _m18_fixture()
    adapters, _validators = build_platform_source_adapters_m16_m21(context)
    if mutation == "missing":
        context.research_graph_store.current = []
    else:
        context.research_graph_store.current[0].actor = "owner:foreign"

    with pytest.raises(LookupError, match="owned IDE QRO command|missing"):
        adapters["canonical_code_command_ref"].load(
            "rgcmd_ide_code_current",
            OWNER,
            record,
        )


def test_m18_rejects_same_owner_ide_command_not_bound_by_selected_rdp() -> None:
    context, record, _manifest = _m18_fixture()
    unrelated_ref = "rgcmd_ide_code_same_owner_unrelated"
    unrelated_qro = SimpleNamespace(
        qro_id="qro:M18:ide-source:unrelated",
        owner=OWNER,
        input_contract={
            "entry_source": "ide",
            "code_hash": "sha256:ide-code-unrelated",
        },
    )
    context.research_graph_store.current.append(
        SimpleNamespace(
            command_id=unrelated_ref,
            actor=OWNER,
            source="ide",
            payload={"qro": unrelated_qro},
        )
    )
    recombined = replace(
        record,
        specific_refs=tuple(
            PlatformSpecificRef(
                item.key,
                unrelated_ref
                if item.key == "canonical_code_command_ref"
                else item.ref,
            )
            for item in record.specific_refs
        ),
    )
    adapters, _validators = build_platform_source_adapters_m16_m21(context)
    assert (
        adapters["canonical_code_command_ref"].load(
            unrelated_ref,
            OWNER,
            recombined,
        ).command_id
        == unrelated_ref
    )

    with pytest.raises(LookupError, match="one exact owner RDP"):
        adapters["consistency_check_ref"].load(
            "cc_ide_code_current",
            OWNER,
            recombined,
        )


@pytest.mark.parametrize("mutation", ("missing", "ambiguous"))
def test_m18_rejects_missing_or_ambiguous_selected_rdp_binding(
    mutation: str,
) -> None:
    context, record, manifest = _m18_fixture()
    adapters, _validators = build_platform_source_adapters_m16_m21(context)
    if mutation == "missing":
        manifest.graph_refs = ()
    else:
        context.rdp_store.current.append(SimpleNamespace(**vars(manifest)))

    with pytest.raises(LookupError, match="one exact owner RDP"):
        adapters["consistency_check_ref"].load(
            "cc_ide_code_current",
            OWNER,
            record,
        )


@pytest.mark.parametrize("mutation", ("code_hash", "math_chain"))
def test_m18_rejects_recombined_rdp_code_or_math_binding(mutation: str) -> None:
    context, record, manifest = _m18_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {key: adapters[key].load(refs[key], OWNER, record) for key in refs}
    if mutation == "code_hash":
        manifest.code_refs = ("sha256:ide-code-unrelated",)
    else:
        manifest.mathematical_spine_chain_refs = (
            "math:M18:same-owner-unrelated",
        )

    violations = " ".join(validators["M18"](record, OWNER, values))
    assert (
        "IDE code hash" in violations
        if mutation == "code_hash"
        else "exact verified Mathematical Spine chain" in violations
    )


def test_m18_rejects_rdp_that_drops_test_evidence() -> None:
    context, record, manifest = _m18_fixture()
    adapters, _validators = build_platform_source_adapters_m16_m21(context)
    manifest.test_refs = ()

    resolved = adapters["consistency_check_ref"].load(
        "cc_ide_code_current", OWNER, record
    )
    assert "no tests" in " ".join(
        adapters["consistency_check_ref"].validate_linkage(
            resolved, OWNER, record
        )
    )


def test_m18_rejects_same_owner_unrelated_lifecycle_rdp() -> None:
    context, record, _manifest = _m18_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {key: adapters[key].load(refs[key], OWNER, record) for key in refs}

    recombined = replace(record, lifecycle_ref="rdp_same_owner_unrelated")

    assert "common lifecycle ref is not the selected RDP manifest" in " ".join(
        validators["M18"](recombined, OWNER, values)
    )


def _m19_fixture():
    tutorial_ref = "tutorial_asset:lesson-current"
    weakness_ref = "weakness_disclosure:lesson-current"
    teaching_ref = "teaching_evidence:lesson-current"
    governed_ref = "lesson:current"
    evidence_ref = "evidence:lesson-current"
    tutorial = SimpleNamespace(
        tutorial_asset_ref=tutorial_ref,
        owner_user_id=OWNER,
        governed_asset_ref=governed_ref,
        category="tutorial",
        title="Evidence-first lesson",
    )
    weakness = SimpleNamespace(
        weakness_disclosure_ref=weakness_ref,
        owner_user_id=OWNER,
        tutorial_asset_ref=tutorial_ref,
        weakness_refs=("weakness:small-sample",),
        visible_by_default=True,
    )
    evidence = SimpleNamespace(
        teaching_evidence_ref=teaching_ref,
        owner_user_id=OWNER,
        tutorial_asset_ref=tutorial_ref,
        weakness_disclosure_ref=weakness_ref,
        evidence_refs=(evidence_ref,),
    )
    exact_refs = {tutorial_ref, weakness_ref, teaching_ref}
    qro = SimpleNamespace(
        qro_id="qro:M19",
        owner=OWNER,
        input_contract={"teaching_refs": tuple(exact_refs)},
        output_contract={"weakness_visible": True},
        mathematical_refs=("math:M19",),
    )
    document = SimpleNamespace(metadata={"teaching_refs": tuple(exact_refs)})
    chain = SimpleNamespace(chain_ref="math:M19", recorded_by=OWNER)
    asset = SimpleNamespace(asset_ref=governed_ref, category="tutorial")

    class Teaching:
        def tutorial_asset(self, ref, *, owner_user_id):
            if ref != tutorial_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return tutorial

        def weakness_disclosure(self, ref, *, owner_user_id):
            if ref != weakness_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return weakness

        def teaching_evidence(self, ref, *, owner_user_id):
            if ref != teaching_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return evidence

    class Lifecycle:
        def governed_asset(self, ref, *, owner_user_id):
            if ref != governed_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return asset

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != "rag:M19" or owner_user_id != OWNER or require_current is not True:
                raise KeyError(ref)
            return document

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "math:M19" or owner != OWNER:
                raise KeyError(ref)
            return chain

    context = PlatformSourceAdaptersM16M21Context(
        research_graph_store=Graph(),
        teaching_asset_registry=Teaching(),
        asset_lifecycle_registry=Lifecycle(),
        rag_index=RAG(),
        spine_chain_registry=Spine(),
    )
    record = _record(
        "M19",
        {
            "tutorial_asset_ref": tutorial_ref,
            "weakness_disclosure_ref": weakness_ref,
            "teaching_evidence_ref": teaching_ref,
        },
        lifecycle_ref=governed_ref,
        evidence_refs=(evidence_ref,),
    )
    return context, record, weakness


def test_m19_binds_tutorial_visible_weakness_and_teaching_evidence() -> None:
    context, record, _weakness = _m19_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {
        key: adapters[key].load(refs[key], OWNER, record)
        for key in refs
    }

    assert validators["M19"](record, OWNER, values) == ()


def test_m19_rejects_hidden_weaknesses() -> None:
    context, record, weakness = _m19_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {
        key: adapters[key].load(refs[key], OWNER, record)
        for key in refs
    }
    weakness.visible_by_default = False

    assert "not visible" in " ".join(validators["M19"](record, OWNER, values))


def _m20_fixture():
    secret_ref = "secretref:llm:openai"
    gateway_ref = "llm_gateway:call-security"
    halt_ref = "account_halt_security"
    secret = SimpleNamespace(secret_ref=secret_ref, status="active")
    call = SimpleNamespace(
        call_id="call-security",
        record_kind="terminal",
        status="ok",
        owner_user_id=OWNER,
        auth_ref=secret_ref,
    )
    halt = SimpleNamespace(
        halt_ref=halt_ref,
        owner_user_id=OWNER,
        owner_state="halted",
        account_binding_refs=("account:a",),
        flat_proof_refs=("flat:a",),
    )
    qro = SimpleNamespace(
        qro_id="qro:M20",
        owner=OWNER,
        input_contract={
            "secret_ref": secret_ref,
            "llm_gateway_ref": gateway_ref,
            "kill_switch_ref": halt_ref,
        },
        output_contract={"status": "security_controls_verified"},
        mathematical_refs=("math:M20",),
    )
    chain = SimpleNamespace(
        chain_ref="math:M20",
        recorded_by=OWNER,
    )
    document = SimpleNamespace(
        metadata={
            "secret_ref": secret_ref,
            "llm_gateway_ref": gateway_ref,
            "kill_switch_ref": halt_ref,
        }
    )

    class Onboarding:
        def secret_ref(self, ref, *, owner_user_id):
            if ref != secret_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return secret

    class Calls:
        def read_all(self, *, owner_user_id):
            return [call] if owner_user_id == OWNER else []

    class Halts:
        def halt_evidence(self, ref, *, owner_user_id):
            if ref != halt_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return halt

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "math:M20" or owner != OWNER:
                raise KeyError(ref)
            return chain

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != "rag:M20" or owner_user_id != OWNER or require_current is not True:
                raise KeyError(ref)
            return document

    context = PlatformSourceAdaptersM16M21Context(
        research_graph_store=Graph(),
        onboarding_registry=Onboarding(),
        llm_call_record_store=Calls(),
        account_halt_barrier=Halts(),
        rag_index=RAG(),
        spine_chain_registry=Spine(),
    )
    record = _record(
        "M20",
        {
            "secret_ref": secret_ref,
            "llm_gateway_ref": gateway_ref,
            "kill_switch_ref": halt_ref,
        },
        lifecycle_ref=halt_ref,
    )
    return context, record, call


def test_m20_binds_secret_terminal_gateway_call_and_halted_account() -> None:
    context, record, _call = _m20_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    values = {
        key: adapter.load(dict((item.key, item.ref) for item in record.specific_refs)[key], OWNER, record)
        for key, adapter in adapters.items()
    }

    assert set(adapters) == {"secret_ref", "llm_gateway_ref", "kill_switch_ref"}
    assert validators["M20"](record, OWNER, values) == ()


def test_m20_rejects_same_owner_gateway_call_using_a_different_secret() -> None:
    context, record, call = _m20_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    values = {
        key: adapter.load(dict((item.key, item.ref) for item in record.specific_refs)[key], OWNER, record)
        for key, adapter in adapters.items()
    }
    call.auth_ref = "secretref:llm:other"

    assert "selected SecretRef" in " ".join(
        validators["M20"](record, OWNER, values)
    )


def test_m20_rejects_same_owner_unrelated_lifecycle_halt() -> None:
    context, record, _call = _m20_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    refs = {item.key: item.ref for item in record.specific_refs}
    values = {key: adapters[key].load(refs[key], OWNER, record) for key in refs}

    recombined = replace(record, lifecycle_ref="account_halt_same_owner_unrelated")

    assert "common lifecycle ref is not the selected account HALT evidence" in " ".join(
        validators["M20"](recombined, OWNER, values)
    )


def _example(asset_ref: str = "template:example") -> GovernedAssetRecord:
    return GovernedAssetRecord(
        asset_ref=asset_ref,
        asset_type="StrategyTemplate",
        category="template",
        lifecycle_state="draft",
        evidence_refs=("evidence:example",),
        validation_plan_ref="validation:example",
        promotion_history=(),
        display_label="EXAMPLE - not production",
        mock_label_ref="mock_label:strategy:example",
        asset_category_ref="asset_category:equity_cn:example",
    )


def _m21_fixture():
    asset = _example()
    strategy = StrategyFile(
        strategy_id="strategy-m21-example-fork",
        owner_username="platform_m21_owner",
        name="m21_example_fork",
        code="def generate_signal(ctx):\n    return 0\n",
        asset_class="equity_cn",
        description="forked from the governed M21 template",
        updated_at_utc="2026-07-13T00:00:00Z",
        market_data_use_validation_refs=[],
    )
    asset_state = {"row": asset}
    strategy_state = {"row": strategy}
    qro = SimpleNamespace(
        qro_id="qro:M21",
        owner=OWNER,
        input_contract={
            "entry_source": "api",
            "governed_asset_ref": asset.asset_ref,
        },
        output_contract={
            "ide_strategy_ref": f"ide_strategy:{strategy.strategy_id}",
            "ide_strategy_snapshot_hash": m21_ide_strategy_snapshot_hash(
                strategy
            ),
            "governed_template_snapshot_hash": (
                m21_governed_template_snapshot_hash(asset)
            ),
            "mock_label_ref": asset.mock_label_ref,
            "asset_category_ref": asset.asset_category_ref,
            "status": "template_fork_recorded",
        },
        mathematical_refs=("math:M21",),
        _asset_state=asset_state,
        _strategy_state=strategy_state,
    )
    permission = SimpleNamespace(
        allowed_users=(OWNER,),
        allowed_assets=(asset.asset_ref,),
    )
    document = SimpleNamespace(asset_ref=asset.asset_ref, permission=permission)
    chain = SimpleNamespace(chain_ref="math:M21", recorded_by=OWNER)

    class Lifecycle:
        def governed_asset_by_mock_label_ref(self, ref, *, owner_user_id):
            current = asset_state["row"]
            if ref != current.mock_label_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return current

        def governed_asset_by_category_ref(self, ref, *, owner_user_id):
            current = asset_state["row"]
            if ref != current.asset_category_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return current

        def governed_asset(self, ref, *, owner_user_id):
            current = asset_state["row"]
            if ref != current.asset_ref or owner_user_id != OWNER:
                raise KeyError(ref)
            return current

    class Graph:
        def qro(self, ref):
            if ref != qro.qro_id:
                raise KeyError(ref)
            return qro

    class RAG:
        def document_for_owner(self, ref, *, owner_user_id, require_current):
            if ref != "rag:M21" or owner_user_id != OWNER or require_current is not True:
                raise KeyError(ref)
            return document

    class Spine:
        def verified_chain(self, ref, *, owner):
            if ref != "math:M21" or owner != OWNER:
                raise KeyError(ref)
            return chain

    def load_ide_strategy(ref, owner):
        current = strategy_state["row"]
        if (
            current is None
            or owner != OWNER
            or ref != f"ide_strategy:{current.strategy_id}"
        ):
            raise KeyError(ref)
        return current

    context = PlatformSourceAdaptersM16M21Context(
        research_graph_store=Graph(),
        asset_lifecycle_registry=Lifecycle(),
        rag_index=RAG(),
        spine_chain_registry=Spine(),
        ide_strategy_loader=load_ide_strategy,
    )
    record = _record(
        "M21",
        {
            "mock_label_ref": str(asset.mock_label_ref),
            "asset_category_ref": str(asset.asset_category_ref),
        },
        lifecycle_ref=asset.asset_ref,
    )
    return context, record, asset, qro


def _m21_values(context, record, asset):
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    values = {
        "mock_label_ref": adapters["mock_label_ref"].load(
            str(asset.mock_label_ref), OWNER, record
        ),
        "asset_category_ref": adapters["asset_category_ref"].load(
            str(asset.asset_category_ref), OWNER, record
        ),
    }
    return validators, values


def test_m21_binds_both_labels_to_one_current_governed_example() -> None:
    context, record, asset, qro = _m21_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    values = {
        "mock_label_ref": adapters["mock_label_ref"].load(
            str(asset.mock_label_ref), OWNER, record
        ),
        "asset_category_ref": adapters["asset_category_ref"].load(
            str(asset.asset_category_ref), OWNER, record
        ),
    }

    assert validators["M21"](record, OWNER, values) == ()
    assert qro.input_contract == {
        "entry_source": "api",
        "governed_asset_ref": asset.asset_ref,
    }
    assert qro.output_contract["ide_strategy_ref"].startswith("ide_strategy:")
    assert set(qro.output_contract) == {
        "ide_strategy_ref",
        "ide_strategy_snapshot_hash",
        "governed_template_snapshot_hash",
        "mock_label_ref",
        "asset_category_ref",
        "status",
    }


def test_m21_rejects_same_owner_label_recombination() -> None:
    context, record, asset, _qro = _m21_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    values = {
        "mock_label_ref": asset,
        "asset_category_ref": _example("strategy:other"),
    }

    assert "recombine" in " ".join(validators["M21"](record, OWNER, values))


def test_m21_rejects_same_owner_unrelated_lifecycle_asset() -> None:
    context, record, asset, _qro = _m21_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    values = {
        "mock_label_ref": adapters["mock_label_ref"].load(
            str(asset.mock_label_ref), OWNER, record
        ),
        "asset_category_ref": adapters["asset_category_ref"].load(
            str(asset.asset_category_ref), OWNER, record
        ),
    }

    recombined = replace(record, lifecycle_ref="strategy:same-owner-unrelated")

    assert "common lifecycle ref is not the governed example asset" in " ".join(
        validators["M21"](recombined, OWNER, values)
    )


def test_m21_rejects_ide_anchor_as_lifecycle_instead_of_template() -> None:
    context, record, asset, qro = _m21_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    values = {
        "mock_label_ref": adapters["mock_label_ref"].load(
            str(asset.mock_label_ref), OWNER, record
        ),
        "asset_category_ref": adapters["asset_category_ref"].load(
            str(asset.asset_category_ref), OWNER, record
        ),
    }
    wrong_lifecycle = replace(
        record,
        lifecycle_ref=qro.output_contract["ide_strategy_ref"],
    )

    assert "common lifecycle ref is not the governed example asset" in " ".join(
        validators["M21"](wrong_lifecycle, OWNER, values)
    )


def test_m21_rejects_qro_recombined_with_another_governed_template() -> None:
    context, record, asset, qro = _m21_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    values = {
        "mock_label_ref": adapters["mock_label_ref"].load(
            str(asset.mock_label_ref), OWNER, record
        ),
        "asset_category_ref": adapters["asset_category_ref"].load(
            str(asset.asset_category_ref), OWNER, record
        ),
    }
    qro.input_contract = {
        "entry_source": "api",
        "governed_asset_ref": "template:same-owner-unrelated",
    }

    violations = validators["M21"](record, OWNER, values)
    assert "current governed_asset_ref/ide_strategy_ref contract" in " ".join(
        violations
    )
    assert "contracts do not bind the governed example labels" in " ".join(
        violations
    )


def test_m21_legacy_asset_ref_contract_remains_accepted() -> None:
    context, record, asset, qro = _m21_fixture()
    adapters, validators = build_platform_source_adapters_m16_m21(context)
    values = {
        "mock_label_ref": adapters["mock_label_ref"].load(
            str(asset.mock_label_ref), OWNER, record
        ),
        "asset_category_ref": adapters["asset_category_ref"].load(
            str(asset.asset_category_ref), OWNER, record
        ),
    }
    qro.input_contract = {
        "entry_source": "api",
        "asset_ref": asset.asset_ref,
    }
    qro.output_contract.pop("ide_strategy_snapshot_hash")
    qro.output_contract.pop("governed_template_snapshot_hash")

    assert validators["M21"](record, OWNER, values) == ()


@pytest.mark.parametrize(
    "mutation",
    (
        "entry_source",
        "unexpected_input",
        "unexpected_output",
        "status",
    ),
)
def test_m21_rejects_non_exact_current_contract(mutation: str) -> None:
    context, record, asset, qro = _m21_fixture()
    validators, values = _m21_values(context, record, asset)
    if mutation == "entry_source":
        qro.input_contract["entry_source"] = "ide"
    elif mutation == "unexpected_input":
        qro.input_contract["unexpected"] = "poison"
    elif mutation == "unexpected_output":
        qro.output_contract["unexpected"] = "poison"
    else:
        qro.output_contract["status"] = "recorded"

    assert validators["M21"](record, OWNER, values)


@pytest.mark.parametrize(
    "mutation",
    ("unexpected_input", "unexpected_output", "status"),
)
def test_m21_rejects_non_exact_legacy_contract(mutation: str) -> None:
    context, record, asset, qro = _m21_fixture()
    qro.input_contract = {
        "entry_source": "api",
        "asset_ref": asset.asset_ref,
    }
    qro.output_contract.pop("ide_strategy_snapshot_hash")
    qro.output_contract.pop("governed_template_snapshot_hash")
    if mutation == "unexpected_input":
        qro.input_contract["unexpected"] = "poison"
    elif mutation == "unexpected_output":
        qro.output_contract["unexpected"] = "poison"
    else:
        qro.output_contract["status"] = "recorded"
    validators, values = _m21_values(context, record, asset)

    assert validators["M21"](record, OWNER, values)


@pytest.mark.parametrize(
    ("mutation", "changes"),
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
def test_m21_rejects_deleted_or_mutated_current_ide_snapshot(
    mutation: str,
    changes: dict[str, object] | None,
) -> None:
    context, record, asset, qro = _m21_fixture()
    validators, values = _m21_values(context, record, asset)
    current = qro._strategy_state["row"]
    qro._strategy_state["row"] = (
        None if changes is None else replace(current, **changes)
    )

    assert validators["M21"](record, OWNER, values)


def test_m21_rejects_mutated_governed_template_snapshot() -> None:
    context, record, asset, qro = _m21_fixture()
    qro._asset_state["row"] = replace(
        asset,
        display_label="EXAMPLE - mutated after history",
    )
    validators, values = _m21_values(context, record, asset)

    assert validators["M21"](record, OWNER, values)
