from __future__ import annotations

import json
import multiprocessing
import os
from dataclasses import replace

import pytest

import app.llm.use_binding as use_binding_module
from app.agent.llm_client import LLMMessage, LLMResponse
from app.llm import (
    GatewayError,
    LLMCredentialPool,
    LLMGateway,
    LLMModelProfile,
    LLMRequest,
    LLMUseBindingError,
    ModelRoutingPolicy,
    ModelTier,
    PersistentLLMUseBindingStore,
    RoleCapabilityRequest,
    SecretRef,
    make_llm_gateway_use_binding,
    seal_llm_gateway_use_binding,
)
from app.llm.call_record_store import LLMCallRecordStore
from app.lineage.ids import canonical_json
from app.security import InMemoryKeystore, KeystoreRecord, SecureKeystore


OWNER = "owner-use-binding"
SERVICE = "service:local-llm-gateway"
WORKFLOW = "workflow-use-binding"
INVOCATION = "invocation-use-binding"
PROMPT_MARKER = "PRIVATE_PROMPT_MUST_NOT_PERSIST_7f4a"
OUTPUT_MARKER = "PRIVATE_OUTPUT_MUST_NOT_PERSIST_8e5b"
SECRET_MARKER = "sk-PRIVATE-LLM-KEY-MUST-NOT-PERSIST-123456"


class _StubClient:
    def __init__(self, *, fail_provider: str = "", fail_all: bool = False) -> None:
        self.fail_provider = fail_provider
        self.fail_all = fail_all
        self.calls: list[str] = []

    def for_credential(self, credential):
        outer = self

        class _Client:
            def chat(self, *args, **kwargs):
                outer.calls.append(credential.provider)
                if outer.fail_all or credential.provider == outer.fail_provider:
                    raise RuntimeError("provider failed with private text")
                return LLMResponse(content=OUTPUT_MARKER)

        return _Client()


def _profiles() -> list[LLMModelProfile]:
    return [
        LLMModelProfile(
            provider="anthropic",
            model="claude-opus-4",
            capability_tier=ModelTier.STRONG.value,
            pool_id="anthropic-runtime",
        ),
        LLMModelProfile(
            provider="openai",
            model="gpt-4o",
            capability_tier=ModelTier.STRONG.value,
            pool_id="openai-runtime",
        ),
    ]


def _pool(profiles: list[LLMModelProfile]) -> LLMCredentialPool:
    keystore = SecureKeystore(InMemoryKeystore())
    pool = LLMCredentialPool(keystore)
    for profile in profiles:
        key = SECRET_MARKER + "-" + profile.provider
        keystore.store(
            KeystoreRecord(
                name=profile.pool_id,
                api_key=key,
                api_secret=key,
            )
        )
        pool.register(
            profile.pool_id,
            SecretRef(
                keystore_name=profile.pool_id,
                provider=profile.provider,
                auth_kind="api_key",
            ),
            default_model=profile.model,
        )
    return pool


def _pool_refs() -> dict[str, str]:
    return {
        "anthropic-runtime": "pool:llm:anthropic:default",
        "openai-runtime": "pool:llm:openai:default",
    }


def _policy_refs() -> dict[str, str]:
    return {
        "anthropic-runtime": "routing:llm:anthropic:default",
        "openai-runtime": "routing:llm:openai:default",
    }


def _request(*, invocation_id: str = INVOCATION, owner: str = OWNER) -> LLMRequest:
    return LLMRequest(
        messages=[LLMMessage(role="user", content=PROMPT_MARKER)],
        capability=RoleCapabilityRequest(role="agent", difficulty="hard"),
        owner_user_id=owner,
        workflow_id=WORKFLOW,
        invocation_id=invocation_id,
        session_id=WORKFLOW,
    )


def _stores(tmp_path):
    call_store = LLMCallRecordStore(tmp_path / "llm_call_records.jsonl")
    binding_store = PersistentLLMUseBindingStore(
        tmp_path / "llm_use_bindings.jsonl",
        seal_secret=call_store.seal_secret,
        terminal_record_resolver=call_store.resolve_terminal_record,
    )
    return call_store, binding_store


def _gateway(
    call_store: LLMCallRecordStore,
    binding_store: PersistentLLMUseBindingStore,
    stub: _StubClient,
) -> LLMGateway:
    profiles = _profiles()
    return LLMGateway(
        policy=ModelRoutingPolicy(profiles),
        credential_pool=_pool(profiles),
        client_factory=stub.for_credential,
        seal_secret=call_store.seal_secret,
        record_sink=call_store.append,
        use_binding_sink=binding_store.append,
        service_principal_ref=SERVICE,
        credential_pool_refs=_pool_refs(),
        routing_policy_refs=_policy_refs(),
    )


def _append_binding_worker(call_path: str, binding_path: str, binding, result) -> None:
    try:
        call_store = LLMCallRecordStore(call_path)
        store = PersistentLLMUseBindingStore(
            binding_path,
            seal_secret=call_store.seal_secret,
            terminal_record_resolver=call_store.resolve_terminal_record,
        )
        persisted = store.append(binding)
        result.put(("ok", persisted.binding_ref))
    except Exception as exc:  # noqa: BLE001
        result.put((type(exc).__name__, str(exc)))


def test_gateway_persists_exact_server_derived_terminal_use_binding(tmp_path) -> None:
    call_store, binding_store = _stores(tmp_path)
    stub = _StubClient()
    gateway = _gateway(call_store, binding_store, stub)
    request = _request()
    request.service_principal_ref = "service:caller-injected"  # type: ignore[attr-defined]
    request.credential_pool_ref = "pool:caller-injected"  # type: ignore[attr-defined]
    request.routing_policy_ref = "routing:caller-injected"  # type: ignore[attr-defined]

    result = gateway.complete(request)

    binding = result.use_binding
    assert binding is not None
    assert binding.owner_user_id == OWNER
    assert binding.service_principal_ref == SERVICE
    assert binding.provider_ref == "anthropic"
    assert binding.auth_ref == "secretref://anthropic/anthropic-runtime"
    assert binding.credential_pool_ref == _pool_refs()["anthropic-runtime"]
    assert binding.routing_policy_ref == _policy_refs()["anthropic-runtime"]
    assert binding.terminal_call_id == result.record.call_id
    assert binding.invocation_id == INVOCATION
    assert binding.workflow_id == WORKFLOW
    assert binding.terminal_record_kind == "terminal"
    assert binding.terminal_status == "ok"
    assert binding.record_revision == 1
    assert binding.state_hash.startswith("sha256:") and len(binding.state_hash) == 71
    assert binding_store.binding(binding.binding_ref, owner_user_id=OWNER) == binding
    assert binding_store.binding_for_terminal(
        result.record.call_id,
        owner_user_id=OWNER,
    ) == binding
    assert binding_store.validate_current(binding.binding_ref, owner_user_id=OWNER).accepted
    terminal = call_store.resolve_terminal_record(result.record.call_id, OWNER)
    assert terminal == result.record
    blob = binding_store.path.read_text(encoding="utf-8")
    for marker in (
        PROMPT_MARKER,
        OUTPUT_MARKER,
        SECRET_MARKER,
        "service:caller-injected",
        "pool:caller-injected",
        "routing:caller-injected",
    ):
        assert marker not in blob


def test_fallback_binding_uses_actual_final_provider_pool_policy_and_auth(tmp_path) -> None:
    call_store, binding_store = _stores(tmp_path)
    stub = _StubClient(fail_provider="anthropic")

    result = _gateway(call_store, binding_store, stub).complete(_request())

    assert stub.calls == ["anthropic", "openai"]
    assert result.record.provider == "openai"
    binding = result.use_binding
    assert binding is not None
    assert binding.provider_ref == "openai"
    assert binding.auth_ref == "secretref://openai/openai-runtime"
    assert binding.credential_pool_ref == _pool_refs()["openai-runtime"]
    assert binding.routing_policy_ref == _policy_refs()["openai-runtime"]


def test_failed_terminal_call_never_gets_success_binding(tmp_path) -> None:
    call_store, binding_store = _stores(tmp_path)
    stub = _StubClient(fail_all=True)
    gateway = _gateway(call_store, binding_store, stub)

    with pytest.raises(GatewayError):
        gateway.complete(_request())

    rows = call_store.read_all(owner_user_id=OWNER)
    assert rows[-1].record_kind == "terminal" and rows[-1].status == "error"
    assert binding_store.read_all(owner_user_id=OWNER) == ()


def test_binding_sink_failure_prevents_response_return_after_terminal_audit(tmp_path) -> None:
    call_store = LLMCallRecordStore(tmp_path / "calls.jsonl")
    profiles = _profiles()
    stub = _StubClient()

    def broken_binding_sink(_binding):
        raise OSError("binding disk unavailable")

    gateway = LLMGateway(
        policy=ModelRoutingPolicy(profiles),
        credential_pool=_pool(profiles),
        client_factory=stub.for_credential,
        seal_secret=call_store.seal_secret,
        record_sink=call_store.append,
        use_binding_sink=broken_binding_sink,
        service_principal_ref=SERVICE,
        credential_pool_refs=_pool_refs(),
        routing_policy_refs=_policy_refs(),
    )

    with pytest.raises(OSError, match="binding disk unavailable"):
        gateway.complete(_request())

    assert stub.calls == ["anthropic"]
    rows = call_store.read_all(owner_user_id=OWNER)
    assert [(row.record_kind, row.status) for row in rows] == [
        ("attempt", "ok"),
        ("terminal", "ok"),
    ]


def test_discarding_binding_sink_cannot_fake_persistence_confirmation(tmp_path) -> None:
    call_store = LLMCallRecordStore(tmp_path / "calls.jsonl")
    profiles = _profiles()
    gateway = LLMGateway(
        policy=ModelRoutingPolicy(profiles),
        credential_pool=_pool(profiles),
        client_factory=_StubClient().for_credential,
        seal_secret=call_store.seal_secret,
        record_sink=call_store.append,
        use_binding_sink=lambda _binding: None,
        service_principal_ref=SERVICE,
        credential_pool_refs=_pool_refs(),
        routing_policy_refs=_policy_refs(),
    )

    with pytest.raises(LLMUseBindingError, match="did not confirm"):
        gateway.complete(_request())


def test_binding_enabled_gateway_requires_stable_server_configuration(tmp_path) -> None:
    profiles = _profiles()
    pool = _pool(profiles)
    sink = lambda binding: binding

    with pytest.raises(ValueError, match="stable seal_secret"):
        LLMGateway(
            policy=ModelRoutingPolicy(profiles),
            credential_pool=pool,
            use_binding_sink=sink,
        )
    with pytest.raises(ValueError, match="service_principal_ref"):
        LLMGateway(
            policy=ModelRoutingPolicy(profiles),
            credential_pool=pool,
            seal_secret=b"x" * 32,
            use_binding_sink=sink,
            credential_pool_refs=_pool_refs(),
            routing_policy_refs=_policy_refs(),
        )
    with pytest.raises(ValueError, match="every runtime pool"):
        LLMGateway(
            policy=ModelRoutingPolicy(profiles),
            credential_pool=pool,
            seal_secret=b"x" * 32,
            use_binding_sink=sink,
            service_principal_ref=SERVICE,
            credential_pool_refs={"anthropic-runtime": "pool:one"},
            routing_policy_refs={"anthropic-runtime": "routing:one"},
        )


def test_binding_enabled_gateway_requires_terminal_record_sink_before_provider(tmp_path) -> None:
    profiles = _profiles()
    stub = _StubClient()
    gateway = LLMGateway(
        policy=ModelRoutingPolicy(profiles),
        credential_pool=_pool(profiles),
        client_factory=stub.for_credential,
        seal_secret=b"x" * 32,
        use_binding_sink=lambda binding: binding,
        service_principal_ref=SERVICE,
        credential_pool_refs=_pool_refs(),
        routing_policy_refs=_policy_refs(),
    )

    with pytest.raises(LLMUseBindingError, match="record_sink"):
        gateway.complete(_request())

    assert stub.calls == []


def test_binding_store_owner_isolation_replay_and_collision(tmp_path) -> None:
    call_store, binding_store = _stores(tmp_path)
    result = _gateway(call_store, binding_store, _StubClient()).complete(_request())
    binding = result.use_binding
    assert binding is not None
    before = binding_store.path.read_bytes()

    assert binding_store.append(binding) == binding
    assert binding_store.path.read_bytes() == before
    with pytest.raises(KeyError):
        binding_store.binding(binding.binding_ref, owner_user_id="owner-other")
    colliding = make_llm_gateway_use_binding(
        result.record,
        service_principal_ref=SERVICE,
        credential_pool_ref=binding.credential_pool_ref,
        routing_policy_ref="routing:llm:other:default",
        seal_secret=call_store.seal_secret,
    )
    with pytest.raises(LLMUseBindingError, match="collision"):
        binding_store.append(colliding)


def test_binding_shape_and_gateway_hmac_tamper_fail_closed(tmp_path) -> None:
    call_store, binding_store = _stores(tmp_path)
    result = _gateway(call_store, binding_store, _StubClient()).complete(_request())
    binding = result.use_binding
    assert binding is not None
    changed = replace(binding, routing_policy_ref="routing:llm:tampered:default")
    with pytest.raises(LLMUseBindingError, match="invalid LLM use binding"):
        binding_store.append(changed)
    resealed_without_identity_update = replace(
        changed,
        gateway_seal=seal_llm_gateway_use_binding(changed, call_store.seal_secret),
    )
    with pytest.raises(LLMUseBindingError, match="invalid LLM use binding"):
        binding_store.append(resealed_without_identity_update)


def test_binding_journal_and_checkpoint_tamper_are_detected(tmp_path) -> None:
    call_store, binding_store = _stores(tmp_path)
    _gateway(call_store, binding_store, _StubClient()).complete(_request())
    row = json.loads(binding_store.path.read_text(encoding="utf-8"))
    row["routing_policy_ref"] = "routing:llm:tampered:default"
    binding_store.path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(LLMUseBindingError, match="checkpoint"):
        PersistentLLMUseBindingStore(
            binding_store.path,
            seal_secret=call_store.seal_secret,
            terminal_record_resolver=call_store.resolve_terminal_record,
        )

    clean_root = tmp_path / "checkpoint"
    clean_call_store, clean_binding_store = _stores(clean_root)
    _gateway(clean_call_store, clean_binding_store, _StubClient()).complete(
        _request(invocation_id="checkpoint-invocation")
    )
    checkpoint = json.loads(clean_binding_store.checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["size"] += 1
    clean_binding_store.checkpoint_path.write_text(
        canonical_json(checkpoint) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(LLMUseBindingError, match="HMAC"):
        PersistentLLMUseBindingStore(
            clean_binding_store.path,
            seal_secret=clean_call_store.seal_secret,
            terminal_record_resolver=clean_call_store.resolve_terminal_record,
        )


def test_binding_fsync_failure_rolls_back_journal_and_checkpoint(tmp_path, monkeypatch) -> None:
    call_store = LLMCallRecordStore(tmp_path / "calls.jsonl")
    profiles = _profiles()
    gateway = LLMGateway(
        policy=ModelRoutingPolicy(profiles),
        credential_pool=_pool(profiles),
        client_factory=_StubClient().for_credential,
        seal_secret=call_store.seal_secret,
        record_sink=call_store.append,
    )
    result = gateway.complete(_request())
    binding = make_llm_gateway_use_binding(
        result.record,
        service_principal_ref=SERVICE,
        credential_pool_ref=_pool_refs()["anthropic-runtime"],
        routing_policy_ref=_policy_refs()["anthropic-runtime"],
        seal_secret=call_store.seal_secret,
    )
    binding_store = PersistentLLMUseBindingStore(
        tmp_path / "bindings.jsonl",
        seal_secret=call_store.seal_secret,
        terminal_record_resolver=call_store.resolve_terminal_record,
    )
    before_journal = binding_store.path.read_bytes()
    before_checkpoint = binding_store.checkpoint_path.read_bytes()
    real_fsync = use_binding_module.os.fsync
    target_inode = binding_store.path.stat().st_ino
    failed = False

    def injected(fd):
        nonlocal failed
        if not failed and os.fstat(fd).st_ino == target_inode:
            failed = True
            raise OSError("injected binding fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(use_binding_module.os, "fsync", injected)
    with pytest.raises(OSError, match="injected binding fsync failure"):
        binding_store.append(binding)

    assert binding_store.path.read_bytes() == before_journal
    assert binding_store.checkpoint_path.read_bytes() == before_checkpoint


def test_binding_cross_process_first_append_is_atomic_and_idempotent(tmp_path) -> None:
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("binding cross-process probe requires fork")
    call_store = LLMCallRecordStore(tmp_path / "calls.jsonl")
    profiles = _profiles()
    result = LLMGateway(
        policy=ModelRoutingPolicy(profiles),
        credential_pool=_pool(profiles),
        client_factory=_StubClient().for_credential,
        seal_secret=call_store.seal_secret,
        record_sink=call_store.append,
    ).complete(_request())
    binding = make_llm_gateway_use_binding(
        result.record,
        service_principal_ref=SERVICE,
        credential_pool_ref=_pool_refs()["anthropic-runtime"],
        routing_policy_ref=_policy_refs()["anthropic-runtime"],
        seal_secret=call_store.seal_secret,
    )
    binding_path = tmp_path / "bindings.jsonl"
    context = multiprocessing.get_context("fork")
    results = context.Queue()
    processes = [
        context.Process(
            target=_append_binding_worker,
            args=(str(call_store.path), str(binding_path), binding, results),
        )
        for _index in range(8)
    ]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=15) for _process in processes]
    for process in processes:
        process.join(15)

    assert [process.exitcode for process in processes] == [0] * len(processes)
    assert {status for status, _value in outcomes} == {"ok"}
    assert {value for _status, value in outcomes} == {binding.binding_ref}
    assert len(binding_path.read_text(encoding="utf-8").splitlines()) == 1
