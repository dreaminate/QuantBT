"""LLM record/replay + 受控翻译层的【对抗式】测试（T-016 / spine 02 §5）。

验收标准（RULES §2）：种一个已知坏，门必抓。覆盖 spine 02 §5 的 A1–A6/B1–B3/C1/D1–D4/E1：
replay 偷跑真 API / fixture 篡改 / cache key 碰撞 / 确定地错 / fingerprint 漂移 / 别名冒充版本 /
逐字节重放 / 三级度量 / 独立重算 fixture_key / put 幂等 / tombstone 不减 N / 崩溃恢复 / 一次性消费。
"""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import stat
from datetime import UTC, datetime
from itertools import count
from unittest.mock import Mock

import pytest

from app.agent.llm_client import LLMClient, LLMMessage, LLMResponse
from app.agent.replay.fixture import (
    FixtureKey,
    LLMFixture,
    ModelPin,
    compute_hmac,
    is_alias_model_id,
    prompt_digest,
    verify_hmac,
)
from app.agent.replay.recording_client import RecordingLLMClient
from app.agent.replay.repro import ReproLevel, pass_caret_k
from app.agent.replay.store import (
    FixtureConflict,
    FixtureStore,
    IntegrityError,
    OwnerScopeError,
    ReplayMiss,
)
from app.agent.replay.translation import ControlledTranslator
from app.lineage.ids import canonical_json
from app.lineage.ids import content_hash
from app.llm.call_record import (
    CallRecordKind,
    CallStatus,
    LLMCallRecord,
    LLMRecordError,
    ReplayState,
    assert_record_admissible,
    make_call_id,
    response_ref_from_digest,
    seal_record,
    unavailable_cost_evidence,
)
from app.llm.call_record_store import LLMCallRecordStore


OWNER_A = "owner-a"
OWNER_B = "owner-b"


class _FakeLLM(LLMClient):
    provider = "fake"
    default_model = "claude-sonnet-4-5-20991231"   # 带日期 = 非别名

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.calls = 0
        self.last_record: LLMCallRecord | None = None
        self._audit_owner = ""
        self._audit_seal: bytes | None = None
        self._audit_sink = None
        self._audit_invocations = count(1)

    def enable_gateway_audit(
        self,
        *,
        owner_user_id: str,
        seal_secret: bytes,
        record_sink=None,
    ) -> None:
        self._audit_owner = owner_user_id
        self._audit_seal = seal_secret
        self._audit_sink = record_sink

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):
        self.calls += 1
        if self._responses:
            response = self._responses.pop(0)
        else:
            response = LLMResponse(content="ok", tool_calls=[])
        if self._audit_seal is not None:
            invocation = f"fixture-origin-{next(self._audit_invocations)}"
            now = datetime.now(UTC).isoformat()
            request_digest = content_hash({
                "messages": [
                    {"role": item.role, "content": item.content, "tool_calls": item.tool_calls,
                     "tool_call_id": item.tool_call_id, "name": item.name}
                    for item in messages
                ],
                "tools": tools,
            })
            response_digest = content_hash({
                "content": response.content,
                "tool_calls": response.tool_calls,
            })
            common = dict(
                provider="fake",
                model=model or self.default_model,
                auth_ref="secretref://fake/fake",
                replay_state=ReplayState.LIVE.value,
                owner_user_id=self._audit_owner,
                workflow_id="fixture-origin",
                invocation_id=invocation,
                attempt_no=1,
                routing_policy_ref="routing:runtime:test-fixture-origin",
                routing_policy_state="runtime_digest",
                prompt_digest=request_digest,
                prompt_hash=request_digest,
                tool_schema_hash=content_hash(tools or []),
                response_digest=response_digest,
                response_ref=response_ref_from_digest(response_digest),
                started_at=now,
                finished_at=now,
                latency_ms=0.0,
                cost=unavailable_cost_evidence("provider_cost_not_reported"),
                status=CallStatus.OK.value,
            )
            records = []
            for kind in (CallRecordKind.ATTEMPT.value, CallRecordKind.TERMINAL.value):
                record = LLMCallRecord(
                    **common,
                    record_kind=kind,
                    call_id=make_call_id(
                        prompt_digest="", provider="", model="", role="", session_id="", seq=1,
                        owner_user_id=self._audit_owner,
                        workflow_id="fixture-origin",
                        invocation_id=invocation,
                        record_kind=kind,
                        attempt_no=1,
                    ),
                )
                record.seal = seal_record(record, self._audit_seal)
                if self._audit_sink is not None:
                    self._audit_sink(record)
                records.append(record)
            self.last_record = records[-1]
        return response


def _msgs(text="hi"):
    return [LLMMessage(role="user", content=text)]


def _invocation_factory(prefix: str):
    sequence = count(1)
    return lambda: f"{prefix}-{next(sequence)}"


def _audited_recorder(
    inner: _FakeLLM,
    fixture_store: FixtureStore,
    audit_store: LLMCallRecordStore,
    *,
    run_id: str,
    owner_user_id: str = OWNER_A,
) -> RecordingLLMClient:
    inner.enable_gateway_audit(
        owner_user_id=owner_user_id,
        seal_secret=audit_store.seal_secret,
        record_sink=audit_store.append,
    )
    return RecordingLLMClient(
        inner,
        fixture_store,
        mode="record",
        run_id=run_id,
        owner_user_id=owner_user_id,
        seal_secret=audit_store.seal_secret,
    )


def _audited_replay(
    inner: _FakeLLM,
    fixture_store: FixtureStore,
    audit_store: LLMCallRecordStore,
    *,
    run_id: str,
    owner_user_id: str = OWNER_A,
    workflow_id: str = "replay-workflow",
    invocation_id_factory=None,
) -> RecordingLLMClient:
    return RecordingLLMClient(
        inner,
        fixture_store,
        mode="replay",
        run_id=run_id,
        owner_user_id=owner_user_id,
        workflow_id=workflow_id,
        invocation_id_factory=(
            invocation_id_factory or _invocation_factory(workflow_id)
        ),
        record_sink=audit_store.append,
        seal_secret=audit_store.seal_secret,
    )


def _fixture(key: str, *, content: str = "a") -> LLMFixture:
    return LLMFixture(
        fixture_key=key,
        run_id="r1",
        repro_level="decision",
        model_pin=ModelPin("p", "m-20240101", None).to_dict(),
        request={"messages": [{"role": "user", "content": "private"}]},
        response={"content": content},
        tool_calls=[],
        translation_status="ok",
    )


def _cross_process_fixture_put(root, content, ready, start, result):
    """Spawn-safe worker used to prove the JSONL conflict gate is process-wide."""

    try:
        store = FixtureStore(root)
        fixture = LLMFixture(
            fixture_key="llmfx-cross-process-conflict",
            run_id="shared-run",
            repro_level="decision",
            model_pin=ModelPin("provider", "model-20240101", "fp1").to_dict(),
            request={"messages": [{"role": "user", "content": "private"}]},
            response={"content": content},
            tool_calls=[],
            translation_status="ok",
        )
        ready.put("ready")
        if not start.wait(10):
            result.put(("error", "start timeout"))
            return
        store.put(fixture, owner_user_id=OWNER_A)
        result.put(("ok", content))
    except Exception as exc:  # noqa: BLE001 - child reports exact class/message to parent.
        result.put((type(exc).__name__, str(exc)))


# ── A1 · replay 偷跑真 API 探针（R11 命门）──────────────────────────────────────
def test_replay_miss_never_calls_real_api(tmp_path):
    store = FixtureStore(tmp_path)
    audit_store = LLMCallRecordStore(tmp_path / "llm-audit.jsonl")
    inner = _FakeLLM([LLMResponse(content="should-not-run")])
    client = _audited_replay(
        inner, store, audit_store, run_id="r1",
    )
    with pytest.raises(ReplayMiss):
        client.chat(_msgs("never recorded"))
    assert inner.calls == 0, "replay 未命中却回退打真 API → R11 命门破（门坏）"
    [row] = audit_store.read_all(owner_user_id=OWNER_A)
    assert (row.record_kind, row.status, row.failure_stage) == ("terminal", "refused", "replay")
    assert row.replay_state == ReplayState.LIVE.value


def test_fixture_jsonl_contains_no_prompt_or_output_plaintext(tmp_path):
    prompt_marker = "PRIVATE_PROMPT_MARKER_7cf3f9"
    output_marker = "PRIVATE_OUTPUT_MARKER_51a821"
    raw_marker = "PRIVATE_RAW_MARKER_149d77"
    store = FixtureStore(tmp_path)
    audit_store = LLMCallRecordStore(tmp_path / "llm-audit.jsonl")
    client = _audited_recorder(
        _FakeLLM([LLMResponse(content=output_marker, raw={"trace": raw_marker})]),
        store, audit_store, run_id="private-run-id",
    )
    recorded = client.chat(_msgs(prompt_marker))

    fixture_blob = store.path.read_text(encoding="utf-8")
    for marker in (prompt_marker, output_marker, raw_marker, "private-run-id", OWNER_A):
        assert marker not in fixture_blob
    row = json.loads(fixture_blob.splitlines()[-1])
    assert not {"request", "response", "tool_calls", "run_id"}.intersection(row)
    assert row["payload_alg"] == "AES-256-GCM"

    replay = _audited_replay(
        _FakeLLM(), FixtureStore(tmp_path), audit_store,
        run_id="private-run-id",
    )
    replayed = replay.chat(_msgs(prompt_marker))
    assert replayed.content == recorded.content == output_marker


def test_owner_scope_blocks_cross_owner_replay_and_records_miss(tmp_path):
    store = FixtureStore(tmp_path)
    audit_store = LLMCallRecordStore(tmp_path / "llm-audit.jsonl")
    recorder = _audited_recorder(
        _FakeLLM([LLMResponse(content="owner-a-only")]),
        store, audit_store, run_id="shared-run",
    )
    recorded = recorder.chat(_msgs("same prompt"))

    foreign_inner = _FakeLLM([LLMResponse(content="must-not-run")])
    foreign = _audited_replay(
        foreign_inner, store, audit_store, run_id="shared-run", owner_user_id=OWNER_B,
        workflow_id="foreign-replay",
    )
    with pytest.raises(ReplayMiss):
        foreign.chat(_msgs("same prompt"))
    assert foreign_inner.calls == 0
    with pytest.raises(KeyError):
        store.get(recorded.fixture_key, owner_user_id=OWNER_B)
    assert [event["event"] for event in store.replay_events(owner_user_id=OWNER_B)] == ["replay_miss"]


def test_replay_hit_and_miss_audit_survive_restart(tmp_path):
    store = FixtureStore(tmp_path)
    audit_store = LLMCallRecordStore(tmp_path / "llm-audit.jsonl")
    _audited_recorder(
        _FakeLLM([LLMResponse(content="recorded")]),
        store, audit_store, run_id="audit-run",
    ).chat(_msgs("recorded prompt"))

    hit_inner = _FakeLLM([LLMResponse(content="must-not-run")])
    _audited_replay(
        hit_inner, store, audit_store, run_id="audit-run",
        workflow_id="audit-hit",
    ).chat(_msgs("recorded prompt"))
    miss_inner = _FakeLLM([LLMResponse(content="must-not-run")])
    with pytest.raises(ReplayMiss):
        _audited_replay(
            miss_inner, store, audit_store, run_id="missing-run",
            workflow_id="audit-miss",
        ).chat(_msgs("missing prompt"))
    assert hit_inner.calls == miss_inner.calls == 0

    reopened = FixtureStore(tmp_path)
    events = reopened.replay_events(owner_user_id=OWNER_A)
    assert [event["event"] for event in events] == ["replay_hit", "replay_miss"]
    audit_blob = reopened.audit_path.read_text(encoding="utf-8")
    assert "recorded prompt" not in audit_blob and "missing prompt" not in audit_blob
    assert OWNER_A not in audit_blob
    llm_reopened = LLMCallRecordStore(audit_store.path)
    rows = [
        row for row in llm_reopened.read_all(owner_user_id=OWNER_A)
        if row.workflow_id in {"audit-hit", "audit-miss"}
    ]
    assert [(row.replay_state, row.status, row.failure_stage) for row in rows] == [
        ("replayed", "ok", ""),
        ("live", "refused", "replay"),
    ]
    assert all(row.schema_version == 3 for row in rows)
    assert rows[0].routing_policy_state == "replay_origin"
    assert rows[0].response_ref == f"llm_response:{rows[0].response_digest}"
    assert rows[0].cost["reason"] == "replay_no_provider_cost"
    assert rows[1].routing_policy_state == "unresolved_pre_route"


def test_schema_v2_exact_row_reloads_only_as_read_only_legacy_history(tmp_path):
    store = LLMCallRecordStore(tmp_path / "legacy-audit.jsonl")
    now = datetime.now(UTC).isoformat()
    legacy = LLMCallRecord(
        provider="legacy-provider",
        model="legacy-model-20240101",
        auth_ref="secretref://legacy/legacy",
        replay_state=ReplayState.REPLAYED.value,
        schema_version=2,
        owner_user_id=OWNER_A,
        workflow_id="legacy-workflow",
        invocation_id="legacy-invocation",
        record_kind=CallRecordKind.TERMINAL.value,
        attempt_no=1,
        call_id=make_call_id(
            prompt_digest="",
            provider="",
            model="",
            role="",
            session_id="",
            seq=1,
            owner_user_id=OWNER_A,
            workflow_id="legacy-workflow",
            invocation_id="legacy-invocation",
            record_kind=CallRecordKind.TERMINAL.value,
            attempt_no=1,
            schema_version=2,
        ),
        prompt_digest="1111111111111111",
        response_digest="2222222222222222",
        fixture_key="llmfx-legacy-v2-history",
        started_at=now,
        finished_at=now,
        latency_ms=0.0,
        status=CallStatus.OK.value,
    )
    legacy.seal = seal_record(legacy, store.seal_secret)
    payload = store._to_persisted_payload(legacy)  # noqa: SLF001 - pre-v3 journal fixture.
    with store._locked_file():  # noqa: SLF001 - seed exact historical bytes + checkpoint.
        store._transactional_append_locked(  # noqa: SLF001
            (canonical_json(payload) + "\n").encode("utf-8")
        )

    [reloaded] = LLMCallRecordStore(store.path).read_all(owner_user_id=OWNER_A)
    assert reloaded.schema_version == 2
    assert reloaded.to_dict()["routing_policy_ref"] == ""
    with pytest.raises(LLMRecordError, match="schema_version"):
        assert_record_admissible(reloaded)
    with pytest.raises(LLMRecordError, match="read-only legacy history"):
        LLMCallRecordStore(store.path).append(reloaded)


def test_schema_v3_persisted_field_set_rejects_missing_and_unknown_fields(tmp_path):
    audit_store = LLMCallRecordStore(tmp_path / "v3-audit.jsonl")
    with pytest.raises(ReplayMiss):
        _audited_replay(
            _FakeLLM(),
            FixtureStore(tmp_path / "fixtures"),
            audit_store,
            run_id="v3-field-set",
            workflow_id="v3-field-set",
            invocation_id_factory=lambda: "v3-field-set-invocation",
        ).chat(_msgs("missing"))
    payload = json.loads(audit_store.path.read_text(encoding="utf-8").splitlines()[-1])

    missing = dict(payload)
    missing.pop("cost")
    with pytest.raises(LLMRecordError, match="persisted field mismatch"):
        LLMCallRecordStore._from_dict(missing)  # noqa: SLF001

    unknown = {**payload, "caller_verdict": "pass"}
    with pytest.raises(LLMRecordError, match="persisted field mismatch"):
        LLMCallRecordStore._from_dict(unknown)  # noqa: SLF001


def test_replay_hit_persists_standalone_terminal_with_safe_fixture_evidence(tmp_path):
    fixture_store = FixtureStore(tmp_path / "fixtures")
    audit_store = LLMCallRecordStore(tmp_path / "audit" / "llm.jsonl")
    prompt_marker = "PROMPT_REPLAY_PRIVATE_1a6c"
    output_marker = "OUTPUT_REPLAY_PRIVATE_2b7d"
    recorder = _audited_recorder(
        _FakeLLM([LLMResponse(content=output_marker)]),
        fixture_store,
        audit_store,
        run_id="standalone-hit",
    )
    recorded = recorder.chat(_msgs(prompt_marker))

    inner = _FakeLLM([LLMResponse(content="MUST_NOT_RUN")])
    replay = _audited_replay(
        inner,
        FixtureStore(tmp_path / "fixtures"),
        audit_store,
        run_id="standalone-hit",
        workflow_id="standalone-hit-workflow",
        invocation_id_factory=lambda: "standalone-hit-invocation",
    )
    replayed = replay.chat(_msgs(prompt_marker))

    assert inner.calls == 0
    assert replayed.content == recorded.content == output_marker
    [row] = [
        candidate for candidate in audit_store.read_all(owner_user_id=OWNER_A)
        if candidate.workflow_id == "standalone-hit-workflow"
    ]
    assert (row.record_kind, row.status, row.replay_state) == ("terminal", "ok", "replayed")
    assert row.fixture_key == recorded.fixture_key
    assert row.workflow_id == "standalone-hit-workflow"
    assert row.invocation_id == "standalone-hit-invocation"
    assert row.provider == "fake"
    assert row.model == _FakeLLM.default_model
    assert row.auth_ref == "secretref://fake/fake"

    fixture_row = json.loads(fixture_store.path.read_text(encoding="utf-8").splitlines()[-1])
    gateway_audit = fixture_row["model_pin"]["gateway_audit"]
    assert set(gateway_audit) == {"provider", "model", "auth_ref", "origin_call_ref"}
    assert gateway_audit["origin_call_ref"]
    for path in (
        candidate for candidate in tmp_path.rglob("*")
        if candidate.suffix in {".json", ".jsonl"}
    ):
        blob = path.read_text(encoding="utf-8")
        assert prompt_marker not in blob
        assert output_marker not in blob
        assert "MUST_NOT_RUN" not in blob


def test_legacy_fixture_without_gateway_audit_is_refused_and_audited(tmp_path):
    fixture_store = FixtureStore(tmp_path / "fixtures")
    audit_store = LLMCallRecordStore(tmp_path / "audit" / "llm.jsonl")
    # No seal is supplied to record mode, so this intentionally represents an
    # old fixture with encrypted payload but no verifiable gateway provenance.
    RecordingLLMClient(
        _FakeLLM([LLMResponse(content="legacy-output")]),
        fixture_store,
        mode="record",
        run_id="legacy-run",
        owner_user_id=OWNER_A,
    ).chat(_msgs("legacy-prompt"))
    inner = _FakeLLM([LLMResponse(content="MUST_NOT_RUN")])
    replay = _audited_replay(
        inner,
        fixture_store,
        audit_store,
        run_id="legacy-run",
        workflow_id="legacy-refusal",
        invocation_id_factory=lambda: "legacy-refusal-invocation",
    )

    with pytest.raises(ReplayMiss, match="gateway audit"):
        replay.chat(_msgs("legacy-prompt"))
    assert inner.calls == 0
    [row] = audit_store.read_all(owner_user_id=OWNER_A)
    assert (row.status, row.failure_stage, row.error_kind) == (
        "refused", "replay", "fixture_audit_metadata_missing",
    )
    assert row.replay_state == "replayed"
    assert row.provider == row.model == row.auth_ref == ""


def test_fixture_rejects_unsafe_gateway_audit_metadata_before_disk_write(tmp_path):
    fixture_store = FixtureStore(tmp_path / "fixtures")
    marker = "PRIVATE GATEWAY AUDIT MARKER 83ce"
    fixture = _fixture("llmfx-unsafe-gateway-audit")
    fixture.model_pin["gateway_audit"] = {
        "provider": "fake",
        "model": marker,
        "auth_ref": "secretref://fake/fake",
        "origin_call_ref": "0123456789abcdef",
    }

    with pytest.raises(ValueError, match="malformed or unsafe"):
        fixture_store.put(fixture, owner_user_id=OWNER_A)
    assert marker not in fixture_store.path.read_text(encoding="utf-8")


def test_fixture_with_unresolved_origin_call_ref_cannot_authorize_replay(tmp_path):
    fixture_store = FixtureStore(tmp_path / "fixtures")
    audit_store = LLMCallRecordStore(tmp_path / "audit" / "llm.jsonl")
    probe = RecordingLLMClient(
        _FakeLLM(), fixture_store, mode="record", run_id="forged-run", owner_user_id=OWNER_A,
    )
    key, pin, request = probe._fixture_key(_msgs("forged-prompt"), None, None, 0.2)
    forged_pin = pin.to_dict()
    forged_pin["gateway_audit"] = {
        "provider": "fake",
        "model": _FakeLLM.default_model,
        "auth_ref": "secretref://fake/fake",
        "origin_call_ref": "0" * 16,
    }
    fixture_store.put(
        LLMFixture(
            fixture_key=key,
            run_id="forged-run",
            repro_level="decision",
            model_pin=forged_pin,
            request=request,
            response={"content": "forged-output"},
            tool_calls=[],
            translation_status="ok",
        ),
        owner_user_id=OWNER_A,
    )
    inner = _FakeLLM([LLMResponse(content="MUST_NOT_RUN")])
    replay = _audited_replay(
        inner,
        fixture_store,
        audit_store,
        run_id="forged-run",
        workflow_id="forged-origin-refusal",
        invocation_id_factory=lambda: "forged-origin-refusal-1",
    )

    with pytest.raises(ReplayMiss, match="verified gateway audit origin"):
        replay.chat(_msgs("forged-prompt"))
    assert inner.calls == 0
    [row] = audit_store.read_all(owner_user_id=OWNER_A)
    assert row.error_kind == "fixture_audit_origin_unverified"
    assert row.failure_stage == "replay"


def test_replay_exact_retry_is_idempotent_but_scope_collision_is_rejected(tmp_path):
    fixture_store = FixtureStore(tmp_path / "fixtures")
    audit_store = LLMCallRecordStore(tmp_path / "audit" / "llm.jsonl")
    _audited_recorder(
        _FakeLLM([LLMResponse(content="stable")]),
        fixture_store,
        audit_store,
        run_id="retry-run",
    ).chat(_msgs("same"))

    for _ in range(2):
        inner = _FakeLLM([LLMResponse(content="MUST_NOT_RUN")])
        replay = _audited_replay(
            inner,
            FixtureStore(tmp_path / "fixtures"),
            LLMCallRecordStore(audit_store.path),
            run_id="retry-run",
            workflow_id="retry-workflow",
            invocation_id_factory=lambda: "retry-invocation",
        )
        assert replay.chat(_msgs("same")).content == "stable"
        assert inner.calls == 0

    assert len([
        row for row in LLMCallRecordStore(audit_store.path).read_all(owner_user_id=OWNER_A)
        if row.workflow_id == "retry-workflow"
    ]) == 1
    colliding_inner = _FakeLLM([LLMResponse(content="MUST_NOT_RUN")])
    colliding = _audited_replay(
        colliding_inner,
        fixture_store,
        LLMCallRecordStore(audit_store.path),
        run_id="different-run",
        workflow_id="retry-workflow",
        invocation_id_factory=lambda: "retry-invocation",
    )
    with pytest.raises(LLMRecordError, match="collision"):
        colliding.chat(_msgs("different"))
    assert colliding_inner.calls == 0


def _fail_next_fsync_for_inode(monkeypatch, path):
    real_fsync = os.fsync
    target = path.stat().st_ino
    failed = False

    def injected(fd):
        nonlocal failed
        if not failed and os.fstat(fd).st_ino == target:
            failed = True
            raise OSError("injected journal fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", injected)


def test_fixture_fsync_failure_restores_prior_journal_and_checkpoint(tmp_path, monkeypatch):
    store = FixtureStore(tmp_path)
    before_journal = store.path.read_bytes()
    before_head = (tmp_path / "fixtures.head.json").read_bytes()
    _fail_next_fsync_for_inode(monkeypatch, store.path)

    with pytest.raises(OSError, match="injected journal fsync failure"):
        store.put(_fixture("llmfx-fsync-fixture"), owner_user_id=OWNER_A)

    assert store.path.read_bytes() == before_journal
    assert (tmp_path / "fixtures.head.json").read_bytes() == before_head
    assert FixtureStore(tmp_path).distinct_count(owner_user_id=OWNER_A) == 0


def test_audit_fsync_failure_restores_prior_journal_and_checkpoint(tmp_path, monkeypatch):
    store = FixtureStore(tmp_path)
    before_journal = store.audit_path.read_bytes()
    before_head = (tmp_path / "replay_audit.head.json").read_bytes()
    _fail_next_fsync_for_inode(monkeypatch, store.audit_path)

    with pytest.raises(OSError, match="injected journal fsync failure"):
        store.record_replay_event(
            "replay_miss",
            owner_user_id=OWNER_A,
            fixture_key="llmfx-no-audit-partial",
            run_id="private-run",
        )

    assert store.audit_path.read_bytes() == before_journal
    assert (tmp_path / "replay_audit.head.json").read_bytes() == before_head
    assert FixtureStore(tmp_path).replay_events(owner_user_id=OWNER_A) == ()


def test_checkpoint_fsync_failure_rolls_back_fixture_append(tmp_path, monkeypatch):
    store = FixtureStore(tmp_path)
    before_journal = store.path.read_bytes()
    before_head = (tmp_path / "fixtures.head.json").read_bytes()
    real_fsync = os.fsync
    calls = 0

    def injected(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected checkpoint fsync failure")
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", injected)
    with pytest.raises(OSError, match="injected checkpoint fsync failure"):
        store.put(_fixture("llmfx-fsync-checkpoint"), owner_user_id=OWNER_A)

    assert store.path.read_bytes() == before_journal
    assert (tmp_path / "fixtures.head.json").read_bytes() == before_head
    assert FixtureStore(tmp_path).distinct_count(owner_user_id=OWNER_A) == 0


@pytest.mark.parametrize("final_state", ["consume", "tombstone"])
def test_fixture_tail_deletion_of_final_state_is_detected(tmp_path, final_state):
    store = FixtureStore(tmp_path)
    key = f"llmfx-tail-{final_state}"
    store.put(_fixture(key), owner_user_id=OWNER_A)
    getattr(store, final_state)(key, owner_user_id=OWNER_A)
    lines = store.path.read_bytes().splitlines(keepends=True)
    assert len(lines) == 2
    store.path.write_bytes(b"".join(lines[:-1]))

    with pytest.raises(IntegrityError, match="journal size diverged"):
        store.get(key, owner_user_id=OWNER_A)
    with pytest.raises(IntegrityError, match="journal size diverged"):
        FixtureStore(tmp_path)


def test_audit_tail_deletion_is_detected(tmp_path):
    store = FixtureStore(tmp_path)
    for event in ("replay_hit", "replay_miss"):
        store.record_replay_event(
            event,
            owner_user_id=OWNER_A,
            fixture_key="llmfx-audit-tail",
            run_id="private-run",
        )
    lines = store.audit_path.read_bytes().splitlines(keepends=True)
    store.audit_path.write_bytes(b"".join(lines[:-1]))

    with pytest.raises(IntegrityError, match="journal size diverged"):
        store.replay_events(owner_user_id=OWNER_A)
    with pytest.raises(IntegrityError, match="journal size diverged"):
        FixtureStore(tmp_path)


def test_checkpoint_tamper_is_detected(tmp_path):
    store = FixtureStore(tmp_path)
    store.put(_fixture("llmfx-head-tamper"), owner_user_id=OWNER_A)
    head_path = tmp_path / "fixtures.head.json"
    head = json.loads(head_path.read_text(encoding="utf-8"))
    head["size"] = int(head["size"]) + 1
    head_path.write_text(json.dumps(head) + "\n", encoding="utf-8")

    with pytest.raises(IntegrityError, match="checkpoint HMAC failed"):
        FixtureStore(tmp_path)


def test_replay_files_are_owned_mode_0600(tmp_path):
    FixtureStore(tmp_path)
    for name in (
        "hmac.key",
        ".replay.lock",
        "fixtures.jsonl",
        "replay_audit.jsonl",
        "fixtures.head.json",
        "replay_audit.head.json",
    ):
        file_stat = os.lstat(tmp_path / name)
        assert stat.S_ISREG(file_stat.st_mode)
        assert file_stat.st_uid == os.geteuid()
        assert stat.S_IMODE(file_stat.st_mode) == 0o600


def test_insecure_key_mode_is_rejected(tmp_path):
    FixtureStore(tmp_path)
    os.chmod(tmp_path / "hmac.key", 0o644)
    with pytest.raises(IntegrityError, match="key mode must be 0600"):
        FixtureStore(tmp_path)


def test_symlink_key_is_rejected(tmp_path):
    target = tmp_path / "outside.key"
    target.write_text("11" * 32, encoding="ascii")
    os.chmod(target, 0o600)
    (tmp_path / "hmac.key").symlink_to(target)
    with pytest.raises(IntegrityError, match="regular non-symlink"):
        FixtureStore(tmp_path)


def test_key_chmod_failure_is_not_swallowed(tmp_path, monkeypatch):
    tmp_path.mkdir(exist_ok=True)
    lock = tmp_path / ".replay.lock"
    lock.touch(mode=0o600)
    os.chmod(lock, 0o600)

    def denied(_fd, _mode):
        raise PermissionError("injected key chmod denial")

    monkeypatch.setattr(os, "fchmod", denied)
    with pytest.raises(PermissionError, match="injected key chmod denial"):
        FixtureStore(tmp_path)
    assert not (tmp_path / "hmac.key").exists()


def test_legacy_plaintext_row_is_quarantined_without_file_migration(tmp_path):
    legacy = {
        "storage_version": 1,
        "fixture_key": "llmfx-legacy-plaintext",
        "request": {"prompt": "legacy secret"},
        "response": {"content": "legacy output"},
    }
    fixture_path = tmp_path / "fixtures.jsonl"
    original = (json.dumps(legacy) + "\n").encode("utf-8")
    fixture_path.write_bytes(original)

    store = FixtureStore(tmp_path)
    assert fixture_path.read_bytes() == original
    assert store.distinct_count(owner_user_id=OWNER_A) == 0
    with pytest.raises(KeyError):
        store.get("llmfx-legacy-plaintext", owner_user_id=OWNER_A)


def test_cross_process_conflicting_put_is_atomic_and_peer_visible(tmp_path):
    observer = FixtureStore(tmp_path)
    ctx = multiprocessing.get_context("spawn")
    ready = ctx.Queue()
    result = ctx.Queue()
    start = ctx.Event()
    processes = [
        ctx.Process(
            target=_cross_process_fixture_put,
            args=(str(tmp_path), content, ready, start, result),
        )
        for content in ("first-output", "second-output")
    ]
    for process in processes:
        process.start()
    assert [ready.get(timeout=15) for _ in processes] == ["ready", "ready"]
    start.set()
    outcomes = [result.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=15)
        assert process.exitcode == 0

    assert sorted(status for status, _ in outcomes) == ["FixtureConflict", "ok"]
    # The observer was constructed before either child write. Its read must
    # reload under the process lock and see the peer's single accepted row.
    stored = observer.get(
        "llmfx-cross-process-conflict",
        owner_user_id=OWNER_A,
    )
    assert stored.response["content"] in {"first-output", "second-output"}
    rows = [line for line in observer.path.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 1
    assert "private" not in rows[0]


def test_persisted_operations_fail_closed_without_owner(tmp_path):
    store = FixtureStore(tmp_path)
    with pytest.raises(ValueError, match="owner_user_id"):
        RecordingLLMClient(_FakeLLM(), store, mode="record", run_id="r1")
    fixture = LLMFixture(
        fixture_key="llmfx-owner-required", run_id="r1", repro_level="decision",
        model_pin=ModelPin("p", "m-20240101", None).to_dict(),
        request={}, response={"content": "a"}, tool_calls=[], translation_status="ok",
    )
    with pytest.raises(OwnerScopeError):
        store.put(fixture, owner_user_id="")
    with pytest.raises(OwnerScopeError):
        store.get(fixture.fixture_key, owner_user_id="")
    with pytest.raises(ValueError, match="persisted replay requires explicit"):
        RecordingLLMClient(
            _FakeLLM(), store, mode="replay", run_id="r1", owner_user_id=OWNER_A,
        )


# ── A2 · fixture 篡改探针（HMAC 完整性门）──────────────────────────────────────
def test_tampered_fixture_raises_integrity_error(tmp_path):
    store = FixtureStore(tmp_path)
    inner = _FakeLLM([LLMResponse(content="x", tool_calls=[{"name": "t", "arguments": '{"leverage": 3}'}])])
    rec = RecordingLLMClient(
        inner, store, mode="record", run_id="r1", owner_user_id=OWNER_A,
    )
    resp = rec.chat(_msgs("trade"))
    key = resp.fixture_key

    # 种坏：改落盘 metadata 的 response digest，但不重加密/重签。
    fpath = tmp_path / "fixtures.jsonl"
    lines = fpath.read_text().splitlines()
    row = json.loads(lines[-1])
    row["response_digest"] = "0" * 64
    lines[-1] = json.dumps(row, ensure_ascii=False)
    fpath.write_text("\n".join(lines) + "\n")

    with pytest.raises(IntegrityError, match="journal digest diverged"):
        FixtureStore(tmp_path)


# ── A3 · cache key 碰撞探针（内容寻址 key 门，dossier §7.3）──────────────────────
def test_cache_key_no_collision_across_run_index_and_upstream():
    base = dict(node_pos="r1:0", prompt_digest="pd", model_pin_digest="md")
    k_a = FixtureKey(**base, upstream_digest="u1", run_index=0).compute()
    k_b = FixtureKey(**base, upstream_digest="u1", run_index=1).compute()   # best-of-N 第二分支
    k_c = FixtureKey(**base, upstream_digest="u2", run_index=0).compute()   # 上游不同分支
    assert k_a != k_b != k_c and k_a != k_c, "同坐标同 prompt 不同 run_index/upstream 撞 key（门坏）"
    assert all(k.startswith("llmfx-") for k in (k_a, k_b, k_c))


# ── A4 · 翻译「确定地错」探针（语义不变量门，dossier §8.4）──────────────────────
def test_translation_human_confirm_for_over_leverage():
    tr = ControlledTranslator(leverage_cap=3.0)
    # schema 合规但语义越界：杠杆 30 > 上限 3
    calls = [{"name": "order.place", "arguments": json.dumps({"constraints": {"leverage_max": 30}})}]
    res = tr.translate(calls)
    assert res.status == "human_confirm_required", "schema 合规即放行越界杠杆 → 确定地错被放大（门坏）"
    # 合规杠杆放行
    ok = tr.translate([{"name": "order.place", "arguments": json.dumps({"leverage": 2})}])
    assert ok.status == "ok"


# ── A4b · AgentRuntime 翻译门：human_confirm 的 tool_call 不派发 ──────────────────
def test_agent_runtime_does_not_dispatch_human_confirm(tmp_path):
    from app.agent.agent_runtime import AgentRuntime

    placed = {"n": 0}

    def _order(_name, _args):
        placed["n"] += 1
        return {"ok": True}

    llm = _FakeLLM([LLMResponse(content="下单", tool_calls=[
        {"id": "c1", "name": "order.place", "arguments": json.dumps({"leverage_max": 30})}])])
    rt = AgentRuntime(llm, tools={"order.place": _order},
                      translator=ControlledTranslator(leverage_cap=3.0))
    turn = rt.run("用 30 倍杠杆梭哈")
    assert placed["n"] == 0, "越界杠杆 tool_call 被派发 → LLM 直接动手下了 30x（门坏）"
    assert turn.succeeded is False


# ── A5 · fingerprint 静默漂移探针（dossier §5.4/§8.3）──────────────────────────
def test_fingerprint_drift_emits_event(tmp_path):
    events = []
    store = FixtureStore(tmp_path, on_event=lambda e, p: events.append((e, p)))

    def _mk(fp, key):
        return LLMFixture(
            fixture_key=key, run_id="r1", repro_level="decision",
            model_pin=ModelPin("anthropic", "claude-x-20240101", fp).to_dict(),
            request={}, response={"content": "a"}, tool_calls=[], translation_status="ok",
        )

    store.put(_mk("fp_v1", "llmfx-aaaa000000000001"), owner_user_id=OWNER_A)
    store.put(  # 同 (provider, model_id) 指纹变了
        _mk("fp_v2", "llmfx-bbbb000000000002"), owner_user_id=OWNER_A,
    )
    drift = [e for e in events if e[0] == "fingerprint_drift"]
    assert drift and drift[0][1]["from"] == "fp_v1" and drift[0][1]["to"] == "fp_v2", \
        "供应商静默换指纹未发 fingerprint_drift 事件 → 「我改了还是供应商换了」不可区分（门坏）"


def test_fingerprint_drift_is_detected_after_restart(tmp_path):
    first = FixtureStore(tmp_path)
    first.put(
        LLMFixture(
            fixture_key="llmfx-restart-fp-one",
            run_id="r1",
            repro_level="decision",
            model_pin=ModelPin("anthropic", "claude-x-20240101", "fp_v1").to_dict(),
            request={},
            response={"content": "one"},
            tool_calls=[],
            translation_status="ok",
        ),
        owner_user_id=OWNER_A,
    )
    events = []
    reopened = FixtureStore(tmp_path, on_event=lambda event, payload: events.append((event, payload)))
    reopened.put(
        LLMFixture(
            fixture_key="llmfx-restart-fp-two",
            run_id="r2",
            repro_level="decision",
            model_pin=ModelPin("anthropic", "claude-x-20240101", "fp_v2").to_dict(),
            request={},
            response={"content": "two"},
            tool_calls=[],
            translation_status="ok",
        ),
        owner_user_id=OWNER_A,
    )
    drift = [payload for event, payload in events if event == "fingerprint_drift"]
    assert drift and drift[-1]["from"] == "fp_v1" and drift[-1]["to"] == "fp_v2"


# ── A6 · 别名冒充版本探针（dossier §5.4）──────────────────────────────────────
def test_alias_model_id_detected_and_event(tmp_path):
    assert is_alias_model_id("claude-sonnet-4-5") is True       # 无日期 = 别名
    assert is_alias_model_id("gpt-4o-latest") is True           # latest = 别名
    assert is_alias_model_id("claude-3-5-sonnet-20241022") is False   # 带日期 = 不可变
    events = []
    store = FixtureStore(tmp_path, on_event=lambda e, p: events.append((e, p)))
    store.put(LLMFixture(
        fixture_key="llmfx-cccc000000000003", run_id="r1", repro_level="decision",
        model_pin=ModelPin("anthropic", "claude-sonnet-4-5", None).to_dict(),
        request={}, response={"content": "a"}, tool_calls=[], translation_status="ok",
    ), owner_user_id=OWNER_A)
    assert any(e[0] == "model_id_is_alias" for e in events), "别名当不可变 id 未告警（门坏）"


# ── B1 · replay 逐字节确定（00 §T9：重放逐字节相同防偷跑）────────────────────────
def test_replay_byte_identical(tmp_path):
    store = FixtureStore(tmp_path)
    audit_store = LLMCallRecordStore(tmp_path / "llm-audit.jsonl")
    inner = _FakeLLM([LLMResponse(content="hello", tool_calls=[{"name": "t", "arguments": "{}"}])])
    rec = _audited_recorder(
        inner, store, audit_store, run_id="r1",
    )
    r_rec = rec.chat(_msgs("q"))

    replay = _audited_replay(
        _FakeLLM([LLMResponse(content="DIFFERENT")]), store, audit_store,
        run_id="r1", workflow_id="byte-one",
    )
    r1 = replay.chat(_msgs("q"))
    replay2 = _audited_replay(
        _FakeLLM(), store, audit_store, run_id="r1", workflow_id="byte-two",
    )
    r2 = replay2.chat(_msgs("q"))
    proj = lambda r: canonical_json({"content": r.content, "tool_calls": r.tool_calls})
    assert proj(r1) == proj(r2) == proj(r_rec), "replay 两遍不逐字节相同 → 偷跑/漂移（门坏）"


# ── B3 · 三级度量解耦：pass^k(decision) 与 (semantic) 各自独立 ───────────────────
def test_pass_caret_k_levels_decouple():
    # 同 tool 名、不同 arguments → semantic 全同(1.0)，decision 分歧(<1.0)
    resps = [
        {"content": "a", "tool_calls": [{"name": "order", "arguments": {"qty": 1}}]},
        {"content": "b", "tool_calls": [{"name": "order", "arguments": {"qty": 2}}]},
    ]
    assert pass_caret_k(resps, ReproLevel.SEMANTIC) == 1.0
    assert pass_caret_k(resps, ReproLevel.DECISION) < 1.0, "decision 级该分歧却报全同（三级未解耦，门坏）"
    # 完全相同 → 各级全 1.0
    same = [resps[0], dict(resps[0])]
    assert pass_caret_k(same, ReproLevel.DECISION) == 1.0


# ── C1 · 两套独立实现对账 fixture_key（防 key 算法 bug 让命中漂移）────────────────
def test_fixture_key_independent_recompute():
    fk = FixtureKey(node_pos="r1:2", prompt_digest="pd", model_pin_digest="md",
                    upstream_digest="ud", run_index=1)
    ours = fk.compute()
    # 独立朴素参考实现：canonical_json + sha256[:16] + llmfx- 前缀
    payload = {"node_pos": "r1:2", "prompt_digest": "pd", "model_pin_digest": "md",
               "upstream_digest": "ud", "run_index": 1}
    ref = "llmfx-" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()[:16]
    assert ours == ref, f"fixture_key 两实现不一致（命中会漂移，门坏）：{ours} vs {ref}"


# ── D1 · put 幂等 / 同 key 异内容拒覆盖（append-only）────────────────────────────
def test_put_idempotent_and_conflict(tmp_path):
    store = FixtureStore(tmp_path)
    f1 = LLMFixture(fixture_key="llmfx-dddd000000000004", run_id="r1", repro_level="decision",
                    model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                    request={}, response={"content": "a"}, tool_calls=[], translation_status="ok")
    store.put(f1, owner_user_id=OWNER_A)
    # 同 key 同内容 → 幂等不报错、不新增行
    n1 = len((tmp_path / "fixtures.jsonl").read_text().splitlines())
    store.put(
        LLMFixture(**{**f1.to_memory_dict(), "integrity": ""}),
        owner_user_id=OWNER_A,
    )
    assert len((tmp_path / "fixtures.jsonl").read_text().splitlines()) == n1, "幂等 put 却新增行（门坏）"
    # 同 key 异内容 → 拒
    with pytest.raises(FixtureConflict):
        store.put(
            LLMFixture(**{
                **f1.to_memory_dict(), "response": {"content": "TAMPERED"}, "integrity": "",
            }),
            owner_user_id=OWNER_A,
        )


# ── D2 · tombstone 不减 distinct 计数（honest-N 不可改小，R8）──────────────────────
def test_tombstone_does_not_reduce_distinct_count(tmp_path):
    store = FixtureStore(tmp_path)
    for i in range(3):
        store.put(
            LLMFixture(fixture_key=f"llmfx-eeee00000000000{i}", run_id="r1", repro_level="decision",
                       model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                       request={}, response={"content": str(i)}, tool_calls=[], translation_status="ok"),
            owner_user_id=OWNER_A,
        )
    assert store.distinct_count(owner_user_id=OWNER_A) == 3
    store.tombstone("llmfx-eeee000000000000", owner_user_id=OWNER_A)
    assert store.distinct_count(owner_user_id=OWNER_A) == 3, \
        "tombstone 减少了 distinct 计数 → 可删 fixture 刷低 N（门坏）"


# ── D2b · tombstone 后 get 仍过完整性门（HMAC 随 tombstoned 重算，不自打篡改告警）──────
def test_tombstone_preserves_integrity(tmp_path):
    store = FixtureStore(tmp_path)
    key = "llmfx-eeee100000000000"
    store.put(
        LLMFixture(fixture_key=key, run_id="r1", repro_level="decision",
                   model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                   request={}, response={"content": "a"}, tool_calls=[], translation_status="ok"),
        owner_user_id=OWNER_A,
    )
    store.tombstone(key, owner_user_id=OWNER_A)
    # 新进程从 JSONL 重建：最新行带 tombstoned=True 且 HMAC 自洽 → get 不报 IntegrityError。
    fx = FixtureStore(tmp_path).get(key, owner_user_id=OWNER_A)
    assert fx.tombstoned is True, "tombstone 后最新行未带 tombstoned（状态丢了，门坏）"
    assert verify_hmac(fx, store._key) is True, "tombstone 未重算 HMAC → 合法软删自触发完整性门（门坏）"


# ── D3 · 崩溃中段恢复：前序 step 从 fixture 读、inner 调 0 次 ──────────────────────
def test_crash_recovery_replays_recorded_steps(tmp_path):
    store = FixtureStore(tmp_path)
    audit_store = LLMCallRecordStore(tmp_path / "llm-audit.jsonl")
    # record 跑 2 步
    rec = _audited_recorder(
        _FakeLLM([LLMResponse(content="s0", tool_calls=[{"name": "t", "arguments": "{}"}]),
                  LLMResponse(content="s1", tool_calls=[])]),
        store, audit_store, run_id="r1",
    )
    rec.chat(_msgs("step0"))
    rec.chat(_msgs("step1"))
    # 新进程 replay：相同坐标 → 命中，inner 一次都不调
    inner2 = _FakeLLM([LLMResponse(content="LIVE")])
    replay = _audited_replay(
        inner2, FixtureStore(tmp_path), audit_store, run_id="r1",
        workflow_id="crash-replay",
    )
    a = replay.chat(_msgs("step0"))
    b = replay.chat(_msgs("step1"))
    assert a.content == "s0" and b.content == "s1"
    assert inner2.calls == 0, "崩溃恢复 replay 偷跑了真 API（门坏）"


# ── D4 · 一次性消费留痕：第二次消费产 consumed_again 事件（R12）────────────────────
def test_consume_twice_emits_consumed_again(tmp_path):
    events = []
    store = FixtureStore(tmp_path, on_event=lambda e, p: events.append((e, p)))
    store.put(
        LLMFixture(fixture_key="llmfx-ffff000000000005", run_id="r1", repro_level="decision",
                   model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                   request={}, response={"content": "a"}, tool_calls=[], translation_status="ok"),
        owner_user_id=OWNER_A,
    )
    store.consume("llmfx-ffff000000000005", owner_user_id=OWNER_A)
    store.consume("llmfx-ffff000000000005", owner_user_id=OWNER_A)
    assert any(e[0] == "consumed_again" for e in events), "二次消费未留痕 consumed_again（门坏）"


# ── D4b · consume 后 get 仍过完整性门（HMAC 随 consumed 重算）──────────────────────
def test_consume_preserves_integrity(tmp_path):
    store = FixtureStore(tmp_path)
    key = "llmfx-ffff100000000005"
    store.put(
        LLMFixture(fixture_key=key, run_id="r1", repro_level="decision",
                   model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                   request={}, response={"content": "a"}, tool_calls=[], translation_status="ok"),
        owner_user_id=OWNER_A,
    )
    store.consume(key, owner_user_id=OWNER_A)
    # 新进程从 JSONL 重建：最新行带 consumed=True 且 HMAC 自洽 → get 不报 IntegrityError。
    fx = FixtureStore(tmp_path).get(key, owner_user_id=OWNER_A)
    assert fx.consumed is True, "consume 后最新行未带 consumed（一次性留痕丢了，门坏）"
    assert verify_hmac(fx, store._key) is True, "consume 未重算 HMAC → 合法消费自触发完整性门（门坏）"


# ── E1 · 措辞：fixture/翻译裁决不得出现「可信/安全/已合规」──────────────────────
def test_wording_no_absolutes():
    from app.agent.replay.repro import PASS_CARET_K_CAVEAT

    tr = ControlledTranslator(leverage_cap=3.0)
    res = tr.translate([{"name": "order", "arguments": json.dumps({"leverage": 30})}])
    text = res.reason + " " + PASS_CARET_K_CAVEAT
    for banned in ("可信", "安全", "已合规", "保证"):
        assert banned not in text, f"出现绝对化措辞「{banned}」（门坏）"
    assert "高确定性 ≠ 高正确性" in PASS_CARET_K_CAVEAT


# ── 复核 #8/#9/#10 · 翻译门绕过：字符串/列表/变体名杠杆都必抓 ────────────────────
@pytest.mark.parametrize("args", [
    {"leverage": "30"},                       # #8 字符串数值
    {"leverage": [10, 30]},                   # #9 列表
    {"leverageMax": 30},                      # #10 camelCase
    {"max_leverage_limit": 30},               # #10 加词变体
    {"constraints": {"nested": {"lev": 30}}}, # 深层嵌套
], ids=["string", "list", "camelCase", "wordy", "deep"])
def test_translation_leverage_bypass_variants_caught(args):
    tr = ControlledTranslator(leverage_cap=3.0)
    res = tr.translate([{"name": "order.place", "arguments": json.dumps(args)}])
    assert res.status == "human_confirm_required", f"越界杠杆变体 {args} 绕过了翻译门（门坏）"


def test_translation_does_not_false_trigger_on_relevance_or_bool():
    tr = ControlledTranslator(leverage_cap=3.0)
    # 'relevance' 含 'lev' 子串但不是杠杆字段 → 不误伤
    assert tr.translate([{"name": "t", "arguments": json.dumps({"relevance": 99})}]).status == "ok"
    # bool True 不被当 1.0 杠杆
    assert tr.translate([{"name": "t", "arguments": json.dumps({"leverage": True})}]).status == "ok"
    # 合规杠杆（==cap）放行
    assert tr.translate([{"name": "t", "arguments": json.dumps({"leverage": 3})}]).status == "ok"


# ── 复核 #11 · schema_invalid 也不派发（非法 tool_call 不执行）────────────────────
def test_agent_runtime_blocks_schema_invalid(tmp_path):
    from app.agent.agent_runtime import AgentRuntime

    placed = {"n": 0}
    llm = _FakeLLM([LLMResponse(content="x", tool_calls=[
        {"id": "c1", "name": "unknown_tool", "arguments": "{}"}])])
    rt = AgentRuntime(llm, tools={"order.place": lambda *_: placed.__setitem__("n", placed["n"] + 1)},
                      translator=ControlledTranslator(leverage_cap=3.0, known_tools={"order.place"}))
    turn = rt.run("call unknown")
    assert placed["n"] == 0 and turn.succeeded is False, "schema_invalid tool_call 仍被派发（门坏）"


# ── 复核 #4 · tombstone/consume 后 get 仍可读（不因改可变字段误报篡改）──────────────
def test_get_works_after_tombstone_and_consume(tmp_path):
    store = FixtureStore(tmp_path)
    f = LLMFixture(fixture_key="llmfx-2222000000000007", run_id="r1", repro_level="decision",
                   model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                   request={}, response={"content": "real"}, tool_calls=[], translation_status="ok")
    store.put(f, owner_user_id=OWNER_A)
    store.tombstone("llmfx-2222000000000007", owner_user_id=OWNER_A)
    store.consume("llmfx-2222000000000007", owner_user_id=OWNER_A)
    got = store.get("llmfx-2222000000000007", owner_user_id=OWNER_A)  # 不得抛 IntegrityError
    assert got.response["content"] == "real" and got.tombstoned is True


# ── 复核 #5 · 追加伪造行必须锁死读取，不得回退到旧状态 ────────────────────────────
def test_forged_appended_line_fails_closed_without_prior_valid_fallback(tmp_path):
    store = FixtureStore(tmp_path)
    f = LLMFixture(fixture_key="llmfx-3333000000000008", run_id="r1", repro_level="decision",
                   model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                   request={}, response={"content": "good"}, tool_calls=[], translation_status="ok")
    store.put(f, owner_user_id=OWNER_A)
    # 种坏：直接追加一条同 key 的伪造行（错 integrity）。
    forged = json.loads((tmp_path / "fixtures.jsonl").read_text().splitlines()[-1])
    forged["response_digest"] = "f" * 64
    with (tmp_path / "fixtures.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged, ensure_ascii=False) + "\n")
    with pytest.raises(IntegrityError, match="journal size diverged"):
        FixtureStore(tmp_path)


# ── 复核 #12 · 坏 JSONL 行不静默缩水 distinct（受保护 journal 直接拒绝）──────────────
def test_corrupt_line_fails_closed(tmp_path):
    store = FixtureStore(tmp_path)
    for i in range(2):
        store.put(
            LLMFixture(fixture_key=f"llmfx-4444000000000{i:03d}", run_id="r1", repro_level="decision",
                       model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                       request={}, response={"content": str(i)}, tool_calls=[], translation_status="ok"),
            owner_user_id=OWNER_A,
        )
    # 种坏：中间插一条坏 JSON 行。
    with (tmp_path / "fixtures.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{ this is not json\n")
    with pytest.raises(IntegrityError, match="journal size diverged"):
        FixtureStore(tmp_path)


# ── 复核 #13 · tombstone 后【重建】distinct 仍不减（honest-N 不可改小，rebuild 路径）────
def test_tombstone_distinct_preserved_after_rebuild(tmp_path):
    store = FixtureStore(tmp_path)
    keys = []
    for i in range(3):
        k = f"llmfx-5555000000000{i:03d}"
        keys.append(k)
        store.put(
            LLMFixture(fixture_key=k, run_id="r1", repro_level="decision",
                       model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                       request={}, response={"content": str(i)}, tool_calls=[], translation_status="ok"),
            owner_user_id=OWNER_A,
        )
    store.tombstone(keys[0], owner_user_id=OWNER_A)
    store2 = FixtureStore(tmp_path)   # 从盘重建
    assert store2.distinct_count(owner_user_id=OWNER_A) == 3, \
        "重建后 tombstone 减少了 distinct → 可删 fixture 刷低 N（门坏）"


# ── 复核 #2 · 不同 run_id 同 prompt 不撞 key（record 模式不静默复用陈旧答案）──────────
def test_different_run_id_no_stale_reuse(tmp_path):
    store = FixtureStore(tmp_path)
    a = RecordingLLMClient(
        _FakeLLM([LLMResponse(content="PNL +5%")]), store,
        mode="record", run_id="agent-aaa", owner_user_id=OWNER_A,
    )
    r_a = a.chat(_msgs("pnl?"))
    inner_b = _FakeLLM([LLMResponse(content="PNL -90% LIQUIDATED")])
    b = RecordingLLMClient(
        inner_b, store, mode="record", run_id="agent-bbb", owner_user_id=OWNER_A,
    )   # 不同逻辑 run
    r_b = b.chat(_msgs("pnl?"))
    assert inner_b.calls == 1, "不同 run_id 同 prompt 撞 key → 真 LLM 被跳过、复用陈旧答案（门坏）"
    assert r_b.content == "PNL -90% LIQUIDATED" and r_a.content == "PNL +5%"


# ── D1b · HMAC 自洽：compute → verify 通过；改一字段 → verify 失败 ────────────────
def test_hmac_self_consistency(tmp_path):
    key = b"x" * 32
    fx = LLMFixture(fixture_key="llmfx-1111000000000006", run_id="r1", repro_level="decision",
                    model_pin=ModelPin("p", "m-20240101", None).to_dict(),
                    request={}, response={"content": "a"}, tool_calls=[], translation_status="ok")
    fx.integrity = compute_hmac(fx, key)
    assert verify_hmac(fx, key) is True
    fx.response = {"content": "TAMPERED"}
    assert verify_hmac(fx, key) is False, "改了 response 但 HMAC 仍验过（门坏）"
