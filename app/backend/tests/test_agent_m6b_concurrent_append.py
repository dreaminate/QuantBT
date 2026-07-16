"""M6b concurrent-append safety — agent canvas writes under contention.

Two+ agent turns can create canvas nodes at the same time. The store serializes
appends under spine's write lock (in-process RLock + cross-process flock; the
first construct is done under the lock too — server.py:104-106), so concurrent
writes cannot tear a JSONL row, lose a command, or double-apply. deep-opus traced
this as an EXISTING guarantee; this is the verifying probe for the AGENT write path.

Mutation contract (RULES §2 种坏门必抓):
- Remove the store's write lock (``PersistentResearchGraphStore.apply`` /
  ``_persistent_research_graph_write_lock``) → concurrent appends interleave → a
  fresh reload raises ``ResearchGraphError`` on a torn line, or the node count /
  uniqueness assertion fails → RED.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest


def _fields(worker: int, i: int) -> dict:
    # Unique content per (worker, i) so each node gets a distinct content-derived id.
    tag = f"{worker}-{i}"
    return {
        "qro_type": "factor",
        "market": "ashare_hs300",
        "universe": "hs300",
        "horizon": "20d",
        "frequency": "daily",
        "assumptions": [f"assume-{tag}"],
        "known_limits": [f"limit-{tag}"],
        "failure_modes": [f"fail-{tag}"],
        "validation_plan": [f"validate-{tag}"],
    }


def test_concurrent_agent_canvas_writes_all_land_uniquely(tmp_path, monkeypatch):
    from app.agent_mcp import server as mcp_server
    from app.research_os.spine import PersistentResearchGraphStore

    # Isolate the agent write path to this test's own JSONL (not the shared audit log).
    path = tmp_path / "audit" / "commands.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mcp_server, "RESEARCH_GRAPH_COMMANDS_PATH", path)
    monkeypatch.setattr(mcp_server, "_STORE", None)
    monkeypatch.setenv("QB_OWNER", "owner-x")

    # Warm the singleton once (avoids the benign _STORE-construction race between
    # threads) so every thread then goes through refresh() + apply() under the lock.
    mcp_server.canvas_create_node(_fields(-1, 0))

    n_threads, per = 6, 8
    results: list[str] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def _work(worker: int) -> None:
        local: list[str] = []
        try:
            for i in range(per):
                res = mcp_server.canvas_create_node(_fields(worker, i))
                local.append(res["qro_id"])
        except BaseException as exc:  # noqa: BLE001 — surface, don't swallow
            with guard:
                errors.append(exc)
            return
        with guard:
            results.extend(local)

    threads = [threading.Thread(target=_work, args=(w,), daemon=True) for w in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "a writer thread hung under contention"
    assert not errors, f"concurrent agent writes errored: {errors}"

    expected = n_threads * per
    assert len(results) == expected
    assert len(set(results)) == expected, "duplicate qro_ids — a command was double-applied/torn"

    # A fresh reload must SUCCEED (no torn tail — fail-closed replay would raise on a
    # partial row) and project every warmed+concurrent node for owner-x (1 warm +
    # expected concurrent). The reload succeeding + the exact count IS the no-corruption
    # proof; the OFFLINE/L-D envelope is pinned separately by the M5b write-tool tests.
    fresh = PersistentResearchGraphStore(path)
    nodes = fresh.projection_index(owner="owner-x")
    assert len(nodes) == expected + 1
    reloaded_ids = {n.qro_id for n in nodes}
    assert set(results) <= reloaded_ids  # every concurrently-created node survived the reload
