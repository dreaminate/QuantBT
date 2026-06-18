"""脊柱内核 01 · DurableExecutor 的【对抗式】测试（T-DET-1..10 + EffectLedger/ArtifactStore 单元）。

验收标准（RULES §2）：种一个已知的坏，门必须抓住，否则门是纸做的。每条都先种坏、再断言门反应。
核心命门：effectful 边界在 replay/fork/rollback 一律 HALT、绝不重发副作用（种重发单→门必抓）。
"""

from __future__ import annotations

import pytest

from app.dag import (
    DAGTask,
    DurableExecutor,
    EffectIdempotencyViolation,
    EffectLedger,
    compute_node_id,
)


class VenueSpy:
    """券商打桩：数 place_order / cancel 次数（断言「绝不重发单 / 绝不撤单」）。"""

    def __init__(self) -> None:
        self.place_calls = 0
        self.cancel_calls = 0

    def place_order(self, **kw):
        self.place_calls += 1
        return f"ord-{self.place_calls}"

    def cancel(self, **kw):
        self.cancel_calls += 1
        return "cancelled"


def _order_op(*, context):
    return {"order_id": context["venue"].place_order(symbol="BTC")}


# ── T-DET-1 · durable ≠ reproducible：replay 读工件、绝不重跑 op（R11 命门）───────
def test_durable_replay_does_not_rerun_op(tmp_path):
    calls = {"n": 0}

    def _llm(*, context):
        calls["n"] += 1                      # 每次真跑都自增（模拟「重跑会漂移」）
        return {"out": calls["n"]}

    ex = DurableExecutor(tmp_path, ops={"llm": _llm})
    tasks = [DAGTask(id="a", op="llm")]
    r1 = ex.run(tasks)
    assert r1.node("a").status == "succeeded" and r1.node("a").result == {"out": 1}
    assert calls["n"] == 1

    r2 = ex.replay(tasks)
    assert r2.node("a").reused is True, "replay 没走复用路径（门坏）"
    assert r2.node("a").result == {"out": 1}, "replay 没读到原工件（门坏）"
    assert calls["n"] == 1, "replay 重跑了 op → 计数自增 → durable≠reproducible 命门被破（门坏）"


# ── T-DET-2 · 节点身份内容寻址不变量（00-contracts C7）──────────────────────────
def test_node_id_content_addressed():
    a = DAGTask(id="a", op="calc", params={"x": 1, "note": "hello"})
    b = DAGTask(id="b", op="calc", params={"x": 1, "note": "WORLD"})   # 仅装饰字段 note 不同
    c = DAGTask(id="c", op="calc", params={"x": 2})
    assert compute_node_id(a) == compute_node_id(b), "装饰字段 note 改变了 node_id → durable/honest-N 分叉（门坏）"
    assert compute_node_id(a) != compute_node_id(c), "真实输入 x 变了 node_id 没变 → 假命中风险（门坏）"
    assert compute_node_id(a, ["up1"]) != compute_node_id(a, ["up2"]), "上游变 node_id 没变 → 非内容寻址（门坏）"


# ── T-DET-3 · effectful 幂等：同 key 重跑绝不重发单（R10/M17 命门）───────────────
def test_effectful_idempotent_no_double_dispatch(tmp_path):
    venue = VenueSpy()
    ex = DurableExecutor(tmp_path, ops={"order": _order_op})
    tasks = [DAGTask(id="o", op="order", kind="effectful", effect_idempotency_key="k1")]
    ctx = {"venue": venue}

    r1 = ex.run(tasks, ctx)
    assert r1.node("o").status == "succeeded" and venue.place_calls == 1

    r2 = ex.run(tasks, ctx)   # 模拟信号重发 / 网络重试
    assert r2.node("o").reused is True, "同 effect key 第二次没命中幂等（门坏）"
    assert venue.place_calls == 1, "同 effect key 重跑又下了一单 → M17 重发单（门坏）"


# ── T-DET-4 · fork 在 effectful 边界截断，what-if 绝不真发单（命门）──────────────
def test_fork_halts_at_effectful_boundary(tmp_path):
    venue = VenueSpy()

    def _calc(*, context, x=1):
        return {"x": x}

    def _report(*, context):
        return {"done": True}

    ex = DurableExecutor(tmp_path, ops={"calc": _calc, "order": _order_op, "report": _report})
    tasks = [
        DAGTask(id="calc", op="calc", params={"x": 1}),
        DAGTask(id="order", op="order", deps=["calc"], kind="effectful", effect_idempotency_key="k1"),
        DAGTask(id="report", op="report", deps=["order"]),
    ]
    ctx = {"venue": venue}
    assert ex.run(tasks, ctx).succeeded and venue.place_calls == 1

    f = ex.fork(tasks, from_task_id="calc", overrides={"x": 2}, context=ctx)
    assert f.node("order").status == "halted" and f.node("order").halted is True
    assert venue.place_calls == 1, "fork 透传到下单 → 假设分支真金白银发单（门坏）"
    assert any(e["event"] == "RECONCILE_REQUIRED" and e["task_id"] == "order" for e in f.events), \
        "fork 截断没发 reconcile_required（门坏）"


# ── T-DET-5 · rollback 不撤单、走对账（R7 硬边界）───────────────────────────────
def test_rollback_no_cancel_emits_reconcile(tmp_path):
    venue = VenueSpy()

    def _calc(*, context, x=1):
        return {"x": x}

    ex = DurableExecutor(tmp_path, ops={"calc": _calc, "order": _order_op})
    tasks = [
        DAGTask(id="calc", op="calc", params={"x": 1}),
        DAGTask(id="order", op="order", deps=["calc"], kind="effectful", effect_idempotency_key="k1"),
    ]
    ctx = {"venue": venue}
    ex.run(tasks, ctx)
    assert venue.place_calls == 1

    # 复核 #6：必须把 ctx 传进 rollback，venue spy 才是【活】闸——否则 cancel_calls==0 是空断言。
    rb = ex.rollback(tasks, to_task_id="calc", context=ctx)
    assert rb.node("order").status == "halted" and rb.node("order").requires_reconcile is True
    assert venue.cancel_calls == 0, "rollback 自动撤单/反向单 → 触达券商（门坏）"
    assert venue.place_calls == 1, "rollback 竟又下单（门坏）"
    assert any(e["event"] == "RECONCILE_REQUIRED" for e in rb.events), "rollback 没发 reconcile（门坏）"


# ── T-DET-6 · 崩溃从 checkpoint 恢复，不重发已下的单（直击 jobs.py 整段重跑雷）─────
def test_crash_recovery_no_redispatch(tmp_path):
    venue = VenueSpy()
    boom = {"armed": True}

    def _a(*, context):
        return {"a": 1}

    def _c(*, context):
        if boom["armed"]:
            raise RuntimeError("crash in C")
        return {"c": 1}

    ex = DurableExecutor(tmp_path, ops={"a": _a, "order": _order_op, "c": _c})
    tasks = [
        DAGTask(id="a", op="a"),
        DAGTask(id="ord", op="order", deps=["a"], kind="effectful", effect_idempotency_key="k1"),
        DAGTask(id="c", op="c", deps=["ord"]),
    ]
    ctx = {"venue": venue}
    r1 = ex.run(tasks, ctx)   # a ok → ord 下单(1) → c 崩
    assert venue.place_calls == 1 and r1.node("c").status == "failed"

    boom["armed"] = False
    r2 = ex.run(tasks, ctx)   # 恢复：a 读工件、ord 幂等命中、c 重算
    assert r2.node("a").reused is True and r2.node("ord").reused is True
    assert venue.place_calls == 1, "崩溃恢复整段重跑 → ord 重发单（M17 雷，门坏）"
    assert r2.node("c").status == "succeeded" and r2.succeeded is True


# ── T-DET-7 · effectful 缺幂等键构造即拒（字段→强制约束的验收点）─────────────────
def test_effectful_without_key_raises():
    with pytest.raises(ValueError, match="effect_idempotency_key"):
        DAGTask(id="o", op="order", kind="effectful")
    with pytest.raises(ValueError, match="pure"):
        DAGTask(id="p", op="calc", kind="pure", effect_idempotency_key="k1")


# ── T-DET-8 · 调度只认静态拓扑，节点产出绝不能改图（LLM 不当控制器）──────────────
def test_schedule_is_static_topo_ignores_node_output(tmp_path):
    def _step(*, context, who):
        context["order"].append(who)
        return {"who": who, "next_task": "HACK"}   # 企图用产出影响调度

    ex = DurableExecutor(tmp_path, ops={"step": _step})
    tasks = [
        DAGTask(id="a", op="step", params={"who": "a"}),
        DAGTask(id="b", op="step", params={"who": "b"}, deps=["a"]),
        DAGTask(id="c", op="step", params={"who": "c"}, deps=["b"]),
    ]
    ctx = {"order": []}
    ex.run(tasks, ctx)
    assert ctx["order"] == ["a", "b", "c"], "执行顺序偏离静态拓扑 → 节点产出改了调度（LLM 当控制器，门坏）"


# ── T-DET-9 · durable 复用绝不把 honest-N 改小（R1/R8 红线，跨部件）──────────────
def test_reuse_still_notifies_every_attempt(tmp_path):
    attempts = []
    calls = {"n": 0}

    def _calc(*, context):
        calls["n"] += 1
        return {"x": 1}

    ex = DurableExecutor(tmp_path, ops={"calc": _calc}, on_attempt=lambda nid, tid: attempts.append(nid))
    tasks = [DAGTask(id="a", op="calc")]
    for _ in range(3):
        ex.run(tasks)
    assert calls["n"] == 1, "durable 没省 compute（第 2/3 次仍重算 → 复用失效）"
    assert len(attempts) == 3, "复用把 attempt 通知吞了 → honest-N 被 memoize 改小（红线破，门坏）"


# ── T-DET-10 · 报告措辞诚实：durable 证据不渲染成「可信」（R7/dossier §7）────────
def test_report_wording_honest(tmp_path):
    ex = DurableExecutor(tmp_path, ops={"calc": lambda *, context: {"x": 1}})
    tasks = [DAGTask(id="a", op="calc")]
    ex.run(tasks)
    report = DurableExecutor.render_report(ex.replay(tasks))
    assert "durable" in report and ("复用工件" in report or "未验证" in report)
    for banned in ("reproducible", "可信", "安全", "组织独立"):
        assert banned not in report, f"报告出现禁词「{banned}」→ 把 durable 证据渲染成结论可信（门坏）"


# ── T-DET-11 · replay 已消费的 effectful → 复用不 HALT、不重发（补 replay 路径）──
def test_replay_effectful_consumed_reused(tmp_path):
    venue = VenueSpy()
    ex = DurableExecutor(tmp_path, ops={"order": _order_op})
    tasks = [DAGTask(id="o", op="order", kind="effectful", effect_idempotency_key="k1")]
    ctx = {"venue": venue}
    ex.run(tasks, ctx)
    assert venue.place_calls == 1

    r = ex.replay(tasks, ctx)
    assert r.node("o").reused is True and r.node("o").halted is False, "已消费 effectful 重放应复用（门坏）"
    assert venue.place_calls == 1, "replay 重发了已消费的单（门坏）"


# ── EffectLedger 单元：is_consumed / record / UNIQUE 兜底 ─────────────────────────
def test_effect_ledger_unique_backstop(tmp_path):
    led = EffectLedger(tmp_path)
    assert led.is_consumed("k") is False
    led.record("k", "nid-1", venue_ref="ord-1")
    assert led.is_consumed("k") is True
    with pytest.raises(EffectIdempotencyViolation):
        led.record("k", "nid-2")   # 并发重复提交兜底
    assert led.get("k").venue_ref == "ord-1"


# ── ArtifactStore 单元：put/exists/get/discard + 触碰留痕 ─────────────────────────
def test_artifact_store_put_get_discard(tmp_path):
    from app.dag import ArtifactStore

    st = ArtifactStore(tmp_path)
    assert st.exists("n1") is False
    st.put("n1", {"v": 42})
    assert st.exists("n1") is True and st.get("n1") == {"v": 42}
    assert st.meta("n1").access_count == 1   # get 记了一次触碰
    st.discard("n1")
    assert st.exists("n1") is False


# ── T-DET-12 · 复核 #5：pure 与 effectful 同 op+params 不撞同一 node_id ───────────
def test_pure_and_effectful_same_op_distinct_node_id():
    p = DAGTask(id="p", op="order", params={"sym": "BTC"})                       # pure
    e = DAGTask(id="e", op="order", params={"sym": "BTC"}, kind="effectful", effect_idempotency_key="k1")
    assert compute_node_id(p) != compute_node_id(e), \
        "pure 与 effectful 同 op+params 撞同一 node_id → effectful 工件被覆盖/重放取错工件（门坏）"


# ── T-DET-13 · 复核 #3：op 实现/版本变 → node_id 变 → 不复用陈旧工件 ────────────
def test_op_version_change_invalidates_artifact(tmp_path):
    from app.dag import register_op

    @register_op("kerneltest.versioned", version="1")
    def _v1(*, context):
        return {"v": 1}

    ex = DurableExecutor(tmp_path)   # 用全局注册表
    tasks = [DAGTask(id="a", op="kerneltest.versioned")]
    r1 = ex.run(tasks)
    nid1 = r1.node("a").node_id

    @register_op("kerneltest.versioned", version="2")   # 实现/版本 bump
    def _v2(*, context):
        return {"v": 2}

    r2 = ex.run(tasks)
    nid2 = r2.node("a").node_id
    assert nid1 != nid2, "op 版本变了 node_id 没变 → 复用陈旧工件（门坏）"
    assert r2.node("a").result == {"v": 2}, "版本变后仍返回旧工件（门坏）"


# ── T-DET-14 · 复核 #2：run 与 replay 工件逐字段一致（消除静默不对称）────────────
def test_run_replay_artifact_symmetric(tmp_path):
    def _op(*, context):
        return {"tup": (1, 2, 3), "n": 5}   # 元组：JSON round-trip 会变 list，暴露不对称

    ex = DurableExecutor(tmp_path, ops={"op": _op})
    tasks = [DAGTask(id="a", op="op")]
    r1 = ex.run(tasks)       # 修复后：run 也返回 round-trip 工件 → 与 replay 一致
    r2 = ex.replay(tasks)
    assert r1.node("a").result == r2.node("a").result, "run 返回活对象、replay 返回反序列化值 → 静默不对称（门坏）"
    assert r1.node("a").result["tup"] == [1, 2, 3], "run 没走 round-trip（元组没变 list → 不对称仍在，门坏）"


# ── T-DET-15 · 复核 #4：fork/rollback 未知目标 id 必 raise，不静默 no-op ──────────
def test_fork_rollback_unknown_target_raises(tmp_path):
    ex = DurableExecutor(tmp_path, ops={"calc": lambda *, context: {"x": 1}})
    tasks = [DAGTask(id="a", op="calc")]
    ex.run(tasks)
    with pytest.raises(ValueError, match="fork 目标未知"):
        ex.fork(tasks, from_task_id="nope", overrides={"x": 2})
    with pytest.raises(ValueError, match="rollback 目标未知"):
        ex.rollback(tasks, to_task_id="nope")


# ── T-DET-16 · 复核 #7：rollback 截断【传递】下游 effectful（非仅直接子节点）──────
def test_rollback_halts_transitive_effectful_descendant(tmp_path):
    venue = VenueSpy()

    def _calc(*, context, x=1):
        return {"x": x}

    def _mid(*, context):
        return {"m": 1}

    ex = DurableExecutor(tmp_path, ops={"calc": _calc, "mid": _mid, "order": _order_op})
    tasks = [
        DAGTask(id="calc", op="calc", params={"x": 1}),
        DAGTask(id="mid", op="mid", deps=["calc"]),                                    # 中间 pure
        DAGTask(id="order", op="order", deps=["mid"], kind="effectful", effect_idempotency_key="k1"),
    ]
    ctx = {"venue": venue}
    ex.run(tasks, ctx)
    assert venue.place_calls == 1

    rb = ex.rollback(tasks, to_task_id="calc", context=ctx)   # order 是 calc 的【传递】下游
    assert rb.node("order").status == "halted" and rb.node("order").requires_reconcile is True, \
        "传递下游 effectful 未被 rollback 截断（_descendants 只看直接子节点的话会漏，门坏）"
    assert rb.node("mid").status == "rolled_back"
    assert venue.cancel_calls == 0 and venue.place_calls == 1


# ── T-DET-17 · 复核 #8：旧 idempotency_key 迁移到 effect_idempotency_key（向后兼容）─
def test_legacy_idempotency_key_migrates():
    t = DAGTask(id="o", op="order", kind="effectful", idempotency_key="legacy-k")
    assert t.effect_idempotency_key == "legacy-k", "旧 idempotency_key 未迁移到新字段（YAML 向后兼容破，门坏）"
    # pure 节点带旧 idempotency_key 不报错（旧 YAML 里它只是装饰，被忽略）。
    p = DAGTask(id="p", op="calc", kind="pure", idempotency_key="legacy-k")
    assert p.effect_idempotency_key is None


# ── T-DET-18 · 复核 #1：context 非内容寻址——身份数据必须走 params（契约回归）──────
def test_context_is_not_content_addressed_contract(tmp_path):
    """契约：context 只携基础设施句柄，不携影响产出的数据；一切身份数据走 params。
    本测钉死该契约：把数据塞 context → 不同输入撞同一 node_id → 复用陈旧工件（这正是禁它的原因）。"""

    def _op(*, context):
        return {"seed": context["seed"]}

    ex = DurableExecutor(tmp_path, ops={"op": _op})
    tasks = [DAGTask(id="a", op="op")]
    r1 = ex.run(tasks, {"seed": 111})
    r2 = ex.run(tasks, {"seed": 222})   # 仅 context 变 → node_id 不变 → 取到陈旧 111
    assert r2.node("a").reused is True and r2.node("a").result == {"seed": 111}, \
        "若此断言变了，说明 context 语义被改——身份数据必须走 params，见模块 context 契约"
    # 正道：身份数据走 params → 不同输入必不同 node_id（不会假命中）。
    assert compute_node_id(DAGTask(id="x", op="op", params={"seed": 111})) != \
        compute_node_id(DAGTask(id="y", op="op", params={"seed": 222}))


# ── T-DET-19 · 复核 low：调度静态拓扑——菱形 DAG 多合法序仍按冻结序（非线性退化）──
def test_static_topo_diamond_ignores_node_output(tmp_path):
    def _step(*, context, who):
        context["order"].append(who)
        return {"who": who, "reorder_to": ["d", "c", "b", "a"]}   # 企图用产出重排

    ex = DurableExecutor(tmp_path, ops={"step": _step})
    tasks = [
        DAGTask(id="a", op="step", params={"who": "a"}),
        DAGTask(id="b", op="step", params={"who": "b"}, deps=["a"]),
        DAGTask(id="c", op="step", params={"who": "c"}, deps=["a"]),
        DAGTask(id="d", op="step", params={"who": "d"}, deps=["b", "c"]),
    ]
    ctx = {"order": []}
    ex.run(tasks, ctx)
    order = ctx["order"]
    assert order[0] == "a" and order[-1] == "d", "菱形 DAG 调度偏离静态拓扑约束（节点产出改了调度，门坏）"
    assert set(order) == {"a", "b", "c", "d"} and order.index("b") < order.index("d") \
        and order.index("c") < order.index("d")


# ── T-DET-20 · 复核 low：ArtifactStore 内容寻址不可覆盖（同 node_id 即同内容）──────
def test_artifact_store_no_overwrite(tmp_path):
    from app.dag import ArtifactStore

    st = ArtifactStore(tmp_path)
    st.put("n1", {"v": 42})
    st.put("n1", {"v": 999})   # 内容寻址：同 node_id 覆盖应是 no-op
    assert st.get("n1") == {"v": 42}, "内容寻址工件被覆盖 → durable 不可信（门坏）"


# ── T-DET-21 · 复核 low：EffectLedger 真并发同键【至多一胜】（跨连接 UNIQUE 兜底）──
def test_effect_ledger_concurrent_same_key(tmp_path):
    import sqlite3
    import threading

    barrier = threading.Barrier(8)
    wins = []
    lock = threading.Lock()

    def worker():
        led = EffectLedger(tmp_path)   # 各自独立连接，模拟真并发
        barrier.wait()
        try:
            led.record("k", "nid")
            with lock:
                wins.append(1)
        except EffectIdempotencyViolation:
            pass                       # UNIQUE 兜底：别人先记了，本次不算胜
        except sqlite3.OperationalError:
            pass                       # 极端争用下锁超时=「未记账」（caller 须当 reconcile，非双记）

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # 命门：UNIQUE 保证同键【至多一条】成功——绝不会两个线程都把同一 effect 记成功（双发单）。
    assert sum(wins) == 1, f"并发同键有 {sum(wins)} 个 record 成功 → 幂等兜底失效，可双发单（门坏）"


# ── T-DET-22 · money-safety probe-4：记账失败不静默——标 reconcile + CRITICAL ─────
def test_effectful_record_failure_flags_reconcile_not_silent(tmp_path, caplog):
    import logging
    import sqlite3

    from app.dag import ArtifactStore

    venue = VenueSpy()

    class FlakeyLedger:   # 副作用已执行后、record 失败（锁超时）——最危险的「已发单未记账」
        def is_consumed(self, key):
            return False

        def record(self, key, node_id, venue_ref=None):
            raise sqlite3.OperationalError("database is locked")

    ex = DurableExecutor(store=ArtifactStore(tmp_path), ledger=FlakeyLedger(), ops={"order": _order_op})
    tasks = [DAGTask(id="o", op="order", kind="effectful", effect_idempotency_key="k1")]
    with caplog.at_level(logging.CRITICAL):
        res = ex.run(tasks, {"venue": venue})

    assert venue.place_calls == 1, "前提：副作用应已执行"
    n = res.node("o")
    assert n.status == "succeeded" and n.requires_reconcile is True, \
        "记账失败后未标 requires_reconcile → 已发单未记账被当干净成功（门坏，下次重发风险）"
    assert "记账失败" in caplog.text, "记账失败未记 CRITICAL → 静默吞（门坏）"


# ── 向后兼容：旧 run_dag 路径不受内核升级影响 ─────────────────────────────────────
def test_legacy_run_dag_still_works():
    from app.dag import DAGDefinition, register_op, run_dag

    @register_op("kerneltest.legacy_echo")
    def _echo(*, context, value):
        return value

    dag = DAGDefinition(name="legacy", tasks=[DAGTask(id="a", op="kerneltest.legacy_echo", params={"value": 7})])
    res = run_dag(dag)
    assert res.succeeded and res.tasks[0].result == 7
