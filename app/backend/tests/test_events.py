"""v0.8.4 Day 5 · 事件埋点测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.events.service import ALLOWED_EVENT_NAMES, EventService, EventTrackError
from app.main import app


# ============================================================
# EventService 单测
# ============================================================


@pytest.fixture
def svc(tmp_path: Path) -> EventService:
    return EventService(tmp_path / "events.db")


def test_track_basic(svc: EventService):
    rec = svc.track("run_detail_viewed", user_id="u1", properties={"run_id": "r1"})
    assert rec.event_name == "run_detail_viewed"
    assert rec.user_id == "u1"
    assert rec.properties == {"run_id": "r1"}
    assert rec.event_id.startswith("evt_")
    assert svc.count() == 1


def test_track_anonymous(svc: EventService):
    rec = svc.track("glossary_term_viewed", anonymous_id="anon-1", properties={"term": "sharpe_ratio"})
    assert rec.user_id is None
    assert rec.anonymous_id == "anon-1"


def test_track_rejects_unknown_event_name(svc: EventService):
    with pytest.raises(EventTrackError):
        svc.track("hack_attempt", user_id="u1")


def test_track_rejects_empty_name(svc: EventService):
    with pytest.raises(EventTrackError):
        svc.track("", user_id="u1")


def test_track_rejects_non_dict_properties(svc: EventService):
    with pytest.raises(EventTrackError):
        svc.track("run_detail_viewed", properties="oops")  # type: ignore[arg-type]


def test_count_by_name(svc: EventService):
    svc.track("run_detail_viewed", user_id="u1")
    svc.track("run_detail_viewed", user_id="u1")
    svc.track("glossary_term_viewed", user_id="u1")
    assert svc.count("run_detail_viewed") == 2
    assert svc.count("glossary_term_viewed") == 1
    assert svc.count() == 3


def test_recent_returns_newest_first(svc: EventService):
    svc.track("run_detail_viewed", user_id="u1")
    svc.track("glossary_term_viewed", user_id="u1")
    rows = svc.recent(limit=10)
    assert len(rows) == 2
    # 时间顺序：newest first
    assert rows[0]["event_name"] == "glossary_term_viewed"


def test_recent_parses_properties(svc: EventService):
    svc.track("run_detail_viewed", user_id="u1", properties={"run_id": "r1", "view_duration_ms": 5000})
    rows = svc.recent(limit=1)
    assert rows[0]["properties"]["run_id"] == "r1"
    assert rows[0]["properties"]["view_duration_ms"] == 5000


def test_allowed_event_names_includes_v084_four():
    """v0.8.4 baseline 4 个事件必须在白名单。"""
    assert "run_detail_viewed" in ALLOWED_EVENT_NAMES
    assert "risk_metric_expanded" in ALLOWED_EVENT_NAMES
    assert "glossary_term_viewed" in ALLOWED_EVENT_NAMES
    assert "risk_summary_shown" in ALLOWED_EVENT_NAMES


# ============================================================
# API endpoint
# ============================================================


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_api_track_success(client: TestClient):
    r = client.post("/api/events/track", json={
        "event_name": "run_detail_viewed",
        "anonymous_id": "anon-test",
        "properties": {"run_id": "test_run"},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["event_id"].startswith("evt_")


def test_api_track_rejects_invalid_name(client: TestClient):
    r = client.post("/api/events/track", json={
        "event_name": "bogus_event",
        "anonymous_id": "anon",
    })
    assert r.status_code == 400


def test_api_track_missing_event_name(client: TestClient):
    r = client.post("/api/events/track", json={"anonymous_id": "anon"})
    assert r.status_code == 400


def test_api_events_recent_returns_array(client: TestClient):
    # 写一条
    client.post("/api/events/track", json={
        "event_name": "risk_metric_expanded",
        "anonymous_id": "anon",
        "properties": {"metric": "pbo", "depth": "l2"},
    })
    r = client.get("/api/events/recent?limit=10")
    assert r.status_code == 200
    events = r.json()
    assert isinstance(events, list)
    # 至少包含我们刚才写的事件
    assert any(e["event_name"] == "risk_metric_expanded" for e in events)
