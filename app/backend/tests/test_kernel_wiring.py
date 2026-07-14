"""T-023 · 确定性内核（T-014）接进 jobs / agent / engine 执行路径——接线层对抗测试。

内核【内部】行为（durable≠reproducible、节点身份、fork/rollback HALT、缺键拒、措辞诚实…）
已由 `test_dag_kernel.py`（25 测试）钉死。本文件只测【接线】：
- engine.run_dag(executor=...)：编排路径切到内核后 durable 复用 / effectful 去重 / 静态拓扑。
- jobs.InMemoryJobStore：kernel_dag job 的 retry「从 checkpoint 恢复 + is_consumed 去重、绝不重发单」、
  replay 模式 effectful 边界 HALT 收于 halted、SSE checkpoint 事件 + halted 终态。
- agent：AgentRuntime + RecordingLLMClient(replay) 整 turn 重放零 LLM 真调用（R11）。
- 变异：关掉 is_consumed 幂等闸 → 必重发单（证明闸是承重墙，门不是纸做的）。
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

import pytest

from app.agent.agent_runtime import AgentRuntime
from app.agent.llm_client import LLMClient, LLMResponse
from app.agent.replay.recording_client import RecordingLLMClient
from app.agent.replay.store import FixtureStore, ReplayMiss
from app.dag import DAGDefinition, DAGTask, register_op, run_dag
from app.dag.kernel import DurableExecutor
from app.jobs import InMemoryJobStore
from app.lineage.ids import content_hash
from app.llm.call_record import (
    CallRecordKind,
    CallStatus,
    LLMCallRecord,
    ReplayState,
    make_call_id,
    seal_record,
)
from app.llm.call_record_store import LLMCallRecordStore
from app.schemas import JobProgress, JobRecord


# ── 接线测试专用 op（与 test_dag.py 的 test.* 不冲突）──────────────────────
@register_op("wiring.echo")
def _w_echo(*, context, value):
    context.setdefault("calls", []).append(("echo", value))
    return {"value": value}


@register_op("wiring.place")
def _w_place(*, context, symbol="X"):
    """模拟 effectful 真下单：每真跑一次就 append 一笔（spy 重发单）。"""
    context.setdefault("placed", []).append(symbol)
    return {"venue_ref": f"o{len(context['placed'])}", "symbol": symbol}


@register_op("wiring.fail_once")
def _w_fail_once(*, context, **_kw):
    """C 节点：第一次跑崩（模拟 C 中途崩溃），retry 时第二次成功。"""
    runs = context["c_runs"]
    runs[0] += 1
    if runs[0] == 1:
        raise RuntimeError("crash at C")
    return {"ok": True}


def _wait(store: InMemoryJobStore, job_id: str, timeout: float = 5.0) -> JobRecord:
    end = time.time() + timeout
    while time.time() < end:
        job = store.get_job(job_id)
        if job.status in {"succeeded", "failed", "interrupted", "halted"}:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} 未在 {timeout}s 内结束，status={store.get_job(job_id).status}")


# ── A. engine.run_dag(executor=...) 接线 ──────────────────────────────────
def test_run_dag_executor_durable_reuse(tmp_path):
    """同图二次执行：第二次 pure 节点 reused、op 只真跑一次（durable 复用接进编排路径）。"""
    ex = DurableExecutor(root=tmp_path)
    defn = DAGDefinition(name="d", tasks=[DAGTask(id="a", op="wiring.echo", params={"value": 1})])
    ctx: dict = {"calls": []}  # 预置非空：kernel.run 对空 dict 会 `context or {}` 换新引用
    r1 = run_dag(defn, context=ctx, executor=ex)
    r2 = run_dag(defn, context=ctx, executor=ex)
    assert r1.tasks[0].status == "succeeded"
    assert r2.tasks[0].status == "reused"
    assert ctx["calls"] == [("echo", 1)]  # op 只跑一次


def test_run_dag_executor_effectful_no_double_dispatch(tmp_path):
    """effectful 节点同幂等键二次执行 → 第二次 reused，绝不重发单（M17 雷）。"""
    ex = DurableExecutor(root=tmp_path)
    task = DAGTask(id="b", op="wiring.place", kind="effectful",
                   effect_idempotency_key="k-1", params={"symbol": "BTC"})
    defn = DAGDefinition(name="e", tasks=[task])
    ctx: dict = {"placed": []}
    r1 = run_dag(defn, context=ctx, executor=ex)
    r2 = run_dag(defn, context=ctx, executor=ex)
    assert r1.tasks[0].status == "succeeded"
    assert r2.tasks[0].status == "reused"
    assert ctx["placed"] == ["BTC"]  # 只下一单


def test_run_dag_executor_static_topo_order(tmp_path):
    """调度只认运行前冻结的静态 deps（节点产出绝不改执行顺序）。"""
    ex = DurableExecutor(root=tmp_path)
    defn = DAGDefinition(name="topo", tasks=[
        DAGTask(id="a", op="wiring.echo", params={"value": 1}),
        DAGTask(id="b", op="wiring.echo", params={"value": 2}, deps=["a"]),
        DAGTask(id="c", op="wiring.echo", params={"value": 3}, deps=["b"]),
    ])
    ctx: dict = {"calls": []}
    run_dag(defn, context=ctx, executor=ex)
    assert ctx["calls"] == [("echo", 1), ("echo", 2), ("echo", 3)]


def test_run_dag_executor_reuse_still_counts_attempts(tmp_path):
    """复用省 compute，但 on_attempt 每次 attempt 仍通知账本——honest-N 绝不改小（R1/R8 红线）。"""
    attempts: list[str] = []
    ex = DurableExecutor(root=tmp_path, on_attempt=lambda nid, tid: attempts.append(tid))
    defn = DAGDefinition(name="n", tasks=[DAGTask(id="a", op="wiring.echo", params={"value": 1})])
    ctx: dict = {"calls": []}
    run_dag(defn, context=ctx, executor=ex)
    run_dag(defn, context=ctx, executor=ex)  # 第二次 reused
    assert attempts == ["a", "a"]          # 复用仍计 2 次 attempt
    assert ctx["calls"] == [("echo", 1)]   # 但 op 只真跑一次


def test_run_dag_without_executor_unchanged(tmp_path):
    """executor=None（默认）→ 现有全量串行语义零改动（向后兼容既有 DAG 测试）。"""
    defn = DAGDefinition(name="legacy", tasks=[DAGTask(id="a", op="wiring.echo", params={"value": 42})])
    ctx: dict = {}
    r = run_dag(defn, context=ctx)  # 不传 executor
    assert r.succeeded
    assert r.tasks[0].status == "succeeded"
    assert ctx["calls"] == [("echo", 42)]


# ── B. jobs.py kernel_dag 接线 ─────────────────────────────────────────────
def test_kernel_job_runs_succeeds(tmp_path):
    store = InMemoryJobStore(kernel_root=tmp_path / "k")
    ctx: dict = {}
    job = store.create_kernel_job(
        [DAGTask(id="a", op="wiring.echo", params={"value": 1})], context=ctx
    )
    j = _wait(store, job.job_id)
    assert j.status == "succeeded"
    assert j.result["node_id_by_task"]["a"]


def test_kernel_job_retry_no_redispatch(tmp_path):
    """retry kernel job → effectful 节点 is_consumed 命中 reused，绝不重发单。"""
    store = InMemoryJobStore(kernel_root=tmp_path / "k")
    placed: list[str] = []
    tasks = [DAGTask(id="b", op="wiring.place", kind="effectful",
                     effect_idempotency_key="k-noredis", params={"symbol": "BTC"})]
    job1 = store.create_kernel_job(tasks, context={"placed": placed})
    _wait(store, job1.job_id)
    job2 = store.retry_job(job1.job_id)
    j2 = _wait(store, job2.job_id)
    assert j2.status == "succeeded"
    assert placed == ["BTC"]  # retry 没重发
    assert any(n["task_id"] == "b" and n["reused"] for n in j2.result["nodes"])


def test_kernel_job_crash_recovery_resumes_from_checkpoint(tmp_path):
    """对抗 #6：A(pure)→B(effectful 已下单)→C，C 崩 → retry 不重跑 A/B、B 经 ledger 命中 0 新下单、C 重算。"""
    store = InMemoryJobStore(kernel_root=tmp_path / "k")
    placed: list[str] = []
    c_runs = [0]
    tasks = [
        DAGTask(id="a", op="wiring.echo", params={"value": 1}),
        DAGTask(id="b", op="wiring.place", kind="effectful",
                effect_idempotency_key="k-crash", params={"symbol": "BTC"}, deps=["a"]),
        DAGTask(id="c", op="wiring.fail_once", deps=["b"]),
    ]
    job1 = store.create_kernel_job(tasks, context={"placed": placed, "c_runs": c_runs})
    j1 = _wait(store, job1.job_id)
    assert j1.status == "failed"     # C 崩
    assert placed == ["BTC"]         # B 已下单一次
    assert c_runs[0] == 1

    job2 = store.retry_job(job1.job_id)
    j2 = _wait(store, job2.job_id)
    assert j2.status == "succeeded"  # 从 checkpoint 恢复，C 重算成功
    assert placed == ["BTC"]         # B 绝不重发单（is_consumed 命中）
    assert c_runs[0] == 2            # C 重算了一次
    nodes = {n["task_id"]: n for n in j2.result["nodes"]}
    assert nodes["a"]["reused"] and nodes["b"]["reused"]  # A/B 不重跑


def test_kernel_job_replay_halts_at_effectful_boundary(tmp_path):
    """replay 模式 job：effectful 边界一律 HALT → job 收于 halted、发 RECONCILE_REQUIRED、绝不触达券商。"""
    store = InMemoryJobStore(kernel_root=tmp_path / "k")
    placed: list[str] = []
    tasks = [
        DAGTask(id="a", op="wiring.echo", params={"value": 7}),
        DAGTask(id="b", op="wiring.place", kind="effectful",
                effect_idempotency_key="k-halt", deps=["a"]),
    ]
    job = store.create_kernel_job(tasks, context={"placed": placed}, mode="replay")
    j = _wait(store, job.job_id)
    assert j.status == "halted"
    assert placed == []  # replay 路径绝不下单
    events = j.result["events"]
    assert any(e["event"] == "HALT" for e in events)
    assert any(e["event"] == "RECONCILE_REQUIRED" for e in events)
    assert any(n["task_id"] == "b" and n["halted"] and n["requires_reconcile"]
               for n in j.result["nodes"])


def test_kernel_job_retry_preserves_replay_mode(tmp_path):
    """5-lens MEDIUM：replay job 的 retry 必须仍是 replay（仍 HALT、绝不真下单），不静默降级为 run。"""
    store = InMemoryJobStore(kernel_root=tmp_path / "k")
    placed: list[str] = []
    tasks = [
        DAGTask(id="a", op="wiring.echo", params={"value": 1}),
        DAGTask(id="b", op="wiring.place", kind="effectful",
                effect_idempotency_key="k-replay-retry", deps=["a"]),
    ]
    job = store.create_kernel_job(tasks, context={"placed": placed}, mode="replay")
    j = _wait(store, job.job_id)
    assert j.status == "halted" and placed == []
    # retry：必须保持 replay 语义（spec.mode 透传）→ 仍 HALT、绝不因降级 run 而真下单。
    job2 = store.retry_job(job.job_id)
    j2 = _wait(store, job2.job_id)
    assert j2.status == "halted"
    assert placed == []


def test_stream_job_emits_checkpoint_and_halted_terminal():
    """SSE：checkpoint 推进发 checkpoint 事件、halted 收于 done（终态集合含 halted）。"""
    store = InMemoryJobStore()
    job = JobRecord(job_id="k1", job_type="kernel_dag", status="running", payload={},
                    submitted_at="2024-01-01T00:00:00Z",
                    progress=JobProgress(percent=0, stage="run", stage_label="跑", message="跑"))
    with store._lock:
        store._jobs["k1"] = job
        store._revisions["k1"] = 0
    events: list[dict] = []
    done = threading.Event()

    def _consume() -> None:
        for evt in store.stream_job("k1", timeout_s=0.5):
            events.append(evt)
            if evt["event"] in {"done", "error"} or len(events) > 8:
                done.set()
                return

    t = threading.Thread(target=_consume, daemon=True)
    t.start()
    time.sleep(0.05)
    with store._lock:
        job.checkpoint = "node-abc"
        store._bump("k1")
    time.sleep(0.05)
    with store._lock:
        job.status = "halted"
        store._bump("k1")
    done.wait(timeout=3)
    t.join(timeout=3)

    kinds = [e["event"] for e in events]
    assert "checkpoint" in kinds
    assert any(e["event"] == "checkpoint" and e["data"]["checkpoint"] == "node-abc" for e in events)
    assert any(e["event"] == "done" and e["data"]["final_status"] == "halted" for e in events)


# ── C. agent 接线：整 turn 重放零 LLM 真调用（复用 T-016 RecordingLLMClient）──
class _SpyLLM(LLMClient):
    provider = "spy"

    def __init__(self) -> None:
        self.calls = 0
        self.last_record: LLMCallRecord | None = None
        self._owner = ""
        self._seal: bytes | None = None
        self._sink = None

    def enable_audit(self, *, owner_user_id: str, seal_secret: bytes, record_sink=None) -> None:
        self._owner = owner_user_id
        self._seal = seal_secret
        self._sink = record_sink

    def chat(self, messages, *, tools=None, model=None, temperature=0.2):  # noqa: ARG002
        self.calls += 1
        response = LLMResponse(content="hello-world", tool_calls=[])
        if self._seal is not None:
            invocation = f"spy-origin-{self.calls}"
            now = datetime.now(UTC).isoformat()
            prompt_hash = content_hash({"messages": [m.content for m in messages], "tools": tools})
            response_digest = content_hash({"content": response.content, "tool_calls": []})
            common = dict(
                provider="spy",
                model="spy-model-20240101",
                auth_ref="secretref://spy/spy",
                replay_state=ReplayState.LIVE.value,
                owner_user_id=self._owner,
                workflow_id="spy-origin",
                invocation_id=invocation,
                routing_policy_ref="routing:runtime:spy-test",
                routing_policy_state="runtime_digest",
                prompt_digest=prompt_hash,
                prompt_hash=prompt_hash,
                tool_schema_hash=content_hash(tools or []),
                response_digest=response_digest,
                response_ref=f"llm_response:{response_digest}",
                started_at=now,
                finished_at=now,
                latency_ms=0.0,
                cost={
                    "status": "unavailable", "currency": "USD", "amount": None,
                    "source": "none", "reason": "provider_cost_not_reported",
                },
                status=CallStatus.OK.value,
            )
            records = []
            for kind in (CallRecordKind.ATTEMPT.value, CallRecordKind.TERMINAL.value):
                record = LLMCallRecord(
                    **common,
                    record_kind=kind,
                    call_id=make_call_id(
                        prompt_digest="", provider="", model="", role="", session_id="", seq=1,
                        owner_user_id=self._owner, workflow_id="spy-origin",
                        invocation_id=invocation, record_kind=kind, attempt_no=1,
                    ),
                )
                record.seal = seal_record(record, self._seal)
                if self._sink is not None:
                    self._sink(record)
                records.append(record)
            self.last_record = records[-1]
        return response


def test_agent_replay_zero_llm_calls_byte_identical(tmp_path):
    """record 一遍 → replay 整 turn：inner LLM 调用 0 次、turn 逐字段一致（R11/durable≠reproducible）。"""
    store = FixtureStore(tmp_path / "fx")
    audit_store = LLMCallRecordStore(tmp_path / "audit" / "llm.jsonl")
    inner1 = _SpyLLM()
    inner1.enable_audit(
        owner_user_id="user:kernel-replay", seal_secret=audit_store.seal_secret,
        record_sink=audit_store.append,
    )
    rec = RecordingLLMClient(
        inner1,
        store,
        mode="record",
        run_id="agent-1",
        owner_user_id="user:kernel-replay",
        seal_secret=audit_store.seal_secret,
    )
    turn1 = AgentRuntime(rec).run("hello")
    assert inner1.calls == 1
    assert turn1.final_message == "hello-world"

    inner2 = _SpyLLM()
    rep = RecordingLLMClient(
        inner2,
        store,
        mode="replay",
        run_id="agent-1",
        owner_user_id="user:kernel-replay",
        workflow_id="kernel-replay",
        invocation_id_factory=lambda: "kernel-replay-1",
        record_sink=audit_store.append,
        seal_secret=audit_store.seal_secret,
    )
    turn2 = AgentRuntime(rep).run("hello")
    assert inner2.calls == 0  # 重放绝不重跑 LLM
    assert turn2.final_message == turn1.final_message
    assert turn2.steps[1].content == turn1.steps[1].content


def test_agent_replay_miss_raises_not_silent_realapi(tmp_path):
    """R11 命门：replay 未命中绝不回退打真 API → 抛 ReplayMiss，inner 调用 0 次。"""
    store = FixtureStore(tmp_path / "fx")
    audit_store = LLMCallRecordStore(tmp_path / "audit" / "llm.jsonl")
    inner = _SpyLLM()
    inner.enable_audit(
        owner_user_id="user:kernel-replay", seal_secret=audit_store.seal_secret,
        record_sink=audit_store.append,
    )
    AgentRuntime(
        RecordingLLMClient(
            inner,
            store,
            mode="record",
                run_id="r",
                owner_user_id="user:kernel-replay",
                seal_secret=audit_store.seal_secret,
        )
    ).run("hello")

    inner2 = _SpyLLM()
    rep = RecordingLLMClient(
        inner2,
        store,
        mode="replay",
        run_id="r",
        owner_user_id="user:kernel-replay",
        workflow_id="kernel-replay-miss",
        invocation_id_factory=lambda: "kernel-replay-miss-1",
        record_sink=audit_store.append,
        seal_secret=audit_store.seal_secret,
    )
    with pytest.raises(ReplayMiss):
        AgentRuntime(rep).run("一个没录过的全新 prompt")
    assert inner2.calls == 0


# ── D. 变异测试：关掉幂等闸 → 必重发单（证明 is_consumed 是承重墙）──────────
def test_mutation_disable_is_consumed_causes_redispatch(tmp_path, monkeypatch):
    """种已知坏：把 EffectLedger.is_consumed 改成永远 False（=拆掉幂等闸）→ retry 重发单。

    与 test_kernel_job_retry_no_redispatch（placed 只一次）对照：闸一旦失效，门就抓不住重发——
    证明该闸是承重墙、不是装饰（门不是纸做的）。
    """
    from app.dag.effect_ledger import EffectLedger

    store = InMemoryJobStore(kernel_root=tmp_path / "k")
    placed: list[str] = []
    tasks = [DAGTask(id="b", op="wiring.place", kind="effectful",
                     effect_idempotency_key="k-mut", params={"symbol": "X"})]
    monkeypatch.setattr(EffectLedger, "is_consumed", lambda self, key: False)
    job1 = store.create_kernel_job(tasks, context={"placed": placed})
    _wait(store, job1.job_id)
    job2 = store.retry_job(job1.job_id)
    _wait(store, job2.job_id)
    assert placed == ["X", "X"]  # 闸被拆 → 重发了（反证闸的承重性）
