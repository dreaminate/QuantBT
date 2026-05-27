from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from app.factor_factory import (
    FactorObservation,
    FactorRegistry,
    LifecycleManager,
    LifecycleThresholds,
    alpha_lite_specs,
    evaluate_on_panel,
    evaluate_transition,
    register_alpha_lite,
)


def _panel(n_symbols: int = 4, n_days: int = 80) -> pl.DataFrame:
    rows = []
    base = datetime(2024, 1, 1, tzinfo=UTC)
    for sid in range(n_symbols):
        prev = 10.0 + sid
        for i in range(n_days):
            wiggle = ((i * (sid + 2) * 7) % 11 - 5) * 0.04
            close = prev + wiggle
            rows.append(
                {
                    "ts": base + timedelta(days=i),
                    "symbol": f"SYM{sid}",
                    "open": prev,
                    "high": max(prev, close) + 0.05,
                    "low": min(prev, close) - 0.05,
                    "close": close,
                    "volume": 1000 + sid * 100 + (i * (sid + 3)) % 41,
                    "amount": (1000 + sid * 100) * close,
                }
            )
            prev = close
    return pl.DataFrame(rows).sort(["symbol", "ts"])


def test_alpha_lite_has_30_specs() -> None:
    specs = list(alpha_lite_specs())
    assert len(specs) >= 30
    ids = {s.factor_id for s in specs}
    assert len(ids) == len(specs), "factor_id 必须唯一"


def test_register_alpha_lite_into_registry(tmp_path: Path) -> None:
    reg = FactorRegistry(tmp_path / "factors.json")
    ids = register_alpha_lite(reg)
    assert len(ids) >= 30
    listed = reg.list()
    assert len(listed) >= 30
    assert all(f.lifecycle_state == "NEW" for f in listed)


def test_all_alpha_lite_factors_can_evaluate() -> None:
    panel = _panel()
    failures: list[tuple[str, str]] = []
    nonnull_counts: dict[str, int] = {}
    for spec in alpha_lite_specs():
        try:
            out = evaluate_on_panel(panel, spec.formula, alias="x")
            nonnull_counts[spec.factor_id] = out.drop_nulls("x").height
        except Exception as exc:  # noqa: BLE001
            failures.append((spec.factor_id, f"{type(exc).__name__}: {exc}"))
    assert not failures, f"以下因子表达式无法求值：{failures}"
    # 至少 70% 的因子在固定 fixture 下应该能给出非空值（剩余可能因 fixture 退化）
    productive = sum(1 for v in nonnull_counts.values() if v > 0)
    assert productive >= int(0.7 * len(nonnull_counts)), nonnull_counts


def test_lifecycle_new_to_qualified() -> None:
    factor_dict = {"factor_id": "x", "version": 1, "formula": "close", "lifecycle_state": "NEW"}
    from app.factor_factory.registry import Factor

    factor = Factor.from_dict({**factor_dict, "author": "u", "params": {}, "ic_summary": None,
                                "created_at_utc": "2024-01-01T00:00:00+00:00", "description": ""})
    observations = [
        FactorObservation(
            factor_id="x",
            version=1,
            observed_at_utc="2024-02-01T00:00:00+00:00",
            horizon=5,
            ic_mean=0.05,
            ic_ir=0.8,
            rank_ic_mean=0.04,
            sample_t=5.0,
        )
    ]
    assert evaluate_transition(factor, observations) == "QUALIFIED"


def test_lifecycle_warning_persists_to_retired(tmp_path: Path) -> None:
    reg = FactorRegistry(tmp_path / "factors.json")
    factor = reg.register("z", "close")
    reg.update_state("z", factor.version, "WARNING")
    mgr = LifecycleManager(reg, thresholds=LifecycleThresholds(warning_persist_weeks=2))
    for _ in range(2):
        mgr.record_observation(
            FactorObservation(
                factor_id="z",
                version=factor.version,
                observed_at_utc=datetime.now(UTC).isoformat(),
                horizon=5,
                ic_mean=-0.02,
                ic_ir=-0.4,
                rank_ic_mean=-0.02,
                sample_t=4.0,
            )
        )
    event = mgr.evaluate("z", factor.version)
    assert event is not None
    assert event.from_state == "WARNING"
    assert event.to_state == "RETIRED"
    assert reg.get("z").lifecycle_state == "RETIRED"


def test_lifecycle_observation_decay_to_warning(tmp_path: Path) -> None:
    reg = FactorRegistry(tmp_path / "factors.json")
    factor = reg.register("y", "close")
    reg.update_state("y", factor.version, "OBSERVATION")
    mgr = LifecycleManager(reg)
    # 给 29 个健康观测 + 1 个崩塌
    for i in range(29):
        mgr.record_observation(
            FactorObservation(
                factor_id="y",
                version=factor.version,
                observed_at_utc=f"2024-01-{i+1:02d}T00:00:00+00:00",
                horizon=5,
                ic_mean=0.05,
                ic_ir=0.7,
                rank_ic_mean=0.04,
                sample_t=4.0,
            )
        )
    mgr.record_observation(
        FactorObservation(
            factor_id="y",
            version=factor.version,
            observed_at_utc="2024-01-30T00:00:00+00:00",
            horizon=5,
            ic_mean=0.005,
            ic_ir=0.1,
            rank_ic_mean=0.001,
            sample_t=2.0,
        )
    )
    event = mgr.evaluate("y", factor.version)
    assert event is not None
    assert event.to_state == "WARNING"


def test_lifecycle_event_log_audit(tmp_path: Path) -> None:
    reg = FactorRegistry(tmp_path / "factors.json")
    reg.register("a", "close")
    mgr = LifecycleManager(reg)
    mgr.record_observation(
        FactorObservation(
            factor_id="a",
            version=1,
            observed_at_utc="2024-01-01T00:00:00+00:00",
            horizon=5,
            ic_mean=0.05,
            ic_ir=0.8,
            rank_ic_mean=0.04,
            sample_t=5.0,
        )
    )
    mgr.evaluate("a", 1)
    assert any(e.factor_id == "a" for e in mgr.events())
