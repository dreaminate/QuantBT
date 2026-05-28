from __future__ import annotations

from pathlib import Path

import pytest

from app.observability import init_error_reporting


def test_init_without_dsn_keeps_sentry_off(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    reporter = init_error_reporting(tmp_path / "errors.jsonl")
    assert reporter.sentry_enabled is False
    assert reporter.sentry_dsn_set is False


def test_report_writes_to_local_log(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    log_path = tmp_path / "errors.jsonl"
    reporter = init_error_reporting(log_path)
    try:
        raise ValueError("hello")
    except ValueError as exc:
        reporter.report(exc, {"path": "/x"})
    assert log_path.exists()
    snap = reporter.info_snapshot()
    assert snap["sentry_enabled"] is False
    assert snap["recent"]
    last = snap["recent"][-1]
    assert last["exc_type"] == "ValueError"
    assert last["exc_msg"] == "hello"
    assert last["context"]["path"] == "/x"


def test_dsn_set_but_sdk_unavailable_falls_back_gracefully(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SENTRY_DSN", "https://abc@sentry.example/1")
    # 即使 sentry-sdk 装了，也不真发到 Sentry —— init 只会触发一次 SDK init
    reporter = init_error_reporting(tmp_path / "e.jsonl")
    assert reporter.sentry_dsn_set is True
    # 即使 sentry init 成功了，report 也要先写本地
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        reporter.report(exc)
    assert (tmp_path / "e.jsonl").exists()
