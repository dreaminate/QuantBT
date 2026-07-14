from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

from app.research_os.backtest_artifact_resolver import (
    CANONICAL_ATTRIBUTION_COLUMNS,
    BacktestArtifactResolutionError,
    CanonicalBacktestArtifactResolver,
    canonical_attribution_csv_bytes,
)
from app.research_os.backtest_evidence import (
    BacktestArtifactState,
    BacktestAttributionRecord,
    PersistentBacktestEvidenceRegistry,
)
from app.research_os.spine import QROType


OWNER = "owner-backtest-artifact"
OTHER_OWNER = "owner-backtest-artifact-other"
QRO_REF = "qro_backtest_artifact"
SOURCE_RUN_ID = "sandbox-run-42"
SOURCE_RUN_REF = f"ide_run:{SOURCE_RUN_ID}"
PROMOTED_RUN_ID = "formal-run-42"
_CANONICAL_HEADER = (",".join(CANONICAL_ATTRIBUTION_COLUMNS) + "\n").encode()
_ROW_MARKET = b"2026-01,market,0.6,0.5,0.10,0.08,0.07,0.001,0.010,0.002,0.001,0.012\n"
_ROW_SELECTION = b"2026-01,selection,0.4,0.5,0.04,0.06,0.07,0.001,-0.010,0.002,0.0005,-0.0075\n"
_ROW_MARKET_CHANGED = b"2026-01,market,0.6,0.5,0.11,0.08,0.07,0.001,0.015,0.003,0.001,0.018\n"
VALID_ATTRIBUTION_CSV = _CANONICAL_HEADER + _ROW_MARKET + _ROW_SELECTION
ONE_ROW_ATTRIBUTION_CSV = _CANONICAL_HEADER + _ROW_MARKET
CHANGED_ATTRIBUTION_CSV = _CANONICAL_HEADER + _ROW_MARKET_CHANGED + _ROW_SELECTION


class Graph:
    def __init__(self, qro) -> None:
        self.qro_record = qro

    def qro(self, ref):
        if ref != self.qro_record.qro_id:
            raise KeyError(ref)
        return self.qro_record


def _qro(*, output_contract=None, owner: str = OWNER, qro_type=QROType.BACKTEST_RUN):
    return SimpleNamespace(
        qro_id=QRO_REF,
        qro_type=qro_type,
        owner=owner,
        input_contract={"source_run_id": SOURCE_RUN_ID},
        output_contract=output_contract
        or {
            "source_run_id": SOURCE_RUN_ID,
            "promoted_run_id": PROMOTED_RUN_ID,
            "status": "completed",
        },
        lineage=(SOURCE_RUN_ID, PROMOTED_RUN_ID),
    )


def _resolver(tmp_path, data: bytes, *, qro=None):
    run_root = tmp_path / "runs"
    run_dir = run_root / PROMOTED_RUN_ID
    run_dir.mkdir(parents=True)
    artifact = run_dir / "attribution.csv"
    artifact.write_bytes(data)
    resolved_qro = qro or _qro()
    return (
        CanonicalBacktestArtifactResolver(
            run_root=run_root,
            research_graph_store=Graph(resolved_qro),
        ),
        artifact,
    )


def _resolve(resolver) -> BacktestArtifactState:
    return resolver(OWNER, QRO_REF, SOURCE_RUN_REF, "attribution.csv")


def test_resolver_derives_hash_rows_and_components_from_exact_csv_bytes(tmp_path) -> None:
    data = VALID_ATTRIBUTION_CSV
    resolver, artifact = _resolver(tmp_path, data)

    first = _resolve(resolver)
    second = _resolve(resolver)

    assert first == second
    assert first.artifact_sha256 == "sha256:" + hashlib.sha256(data).hexdigest()
    assert first.row_count == 2
    assert len(first.component_refs) == len(CANONICAL_ATTRIBUTION_COLUMNS)
    assert len(set(first.component_refs)) == len(CANONICAL_ATTRIBUTION_COLUMNS)
    assert all(
        ref.startswith("attribution_component:sha256:")
        for ref in first.component_refs
    )
    artifact.write_bytes(CHANGED_ATTRIBUTION_CSV)
    changed = _resolve(resolver)
    assert changed.artifact_sha256 != first.artifact_sha256
    assert changed.component_refs != first.component_refs


def test_canonical_encoder_round_trips_exact_brinson_and_cost_schema() -> None:
    row = dict(
        zip(
            CANONICAL_ATTRIBUTION_COLUMNS,
            (
                "2026-01",
                "market",
                "0.6",
                "0.5",
                "0.10",
                "0.08",
                "0.07",
                "0.001",
                "0.010",
                "0.002",
                "0.001",
                "0.012",
            ),
            strict=True,
        )
    )

    assert canonical_attribution_csv_bytes([row]) == ONE_ROW_ATTRIBUTION_CSV


@pytest.mark.parametrize(
    ("data", "message"),
    (
        (b"component,pnl,cost\nmarket,1.25,0.10\n", "canonical Brinson/cost"),
        (
            _CANONICAL_HEADER
            + b"2026-01,market,0.6,0.5,nan,0.08,0.07,0.001,0.010,0.002,0.001,0.012\n",
            "finite",
        ),
        (
            _CANONICAL_HEADER
            + b"2026-01,market,0.6,0.5,0.10,0.08,0.07,0.001,0.999,0.002,0.001,0.012\n",
            "selection_effect does not reconcile",
        ),
        (
            _CANONICAL_HEADER
            + b"2026-01,market,0.6,0.5,0.10,0.08,0.07,0.001,0.010,0.002,-0.001,0.014\n",
            "cost_effect cannot be negative",
        ),
        (
            _CANONICAL_HEADER
            + _ROW_MARKET
            + _ROW_MARKET,
            "duplicates period/component",
        ),
    ),
)
def test_resolver_rejects_semantically_false_attribution_rows(
    tmp_path,
    data,
    message,
) -> None:
    resolver, _artifact = _resolver(tmp_path, data)

    with pytest.raises(BacktestArtifactResolutionError, match=message):
        _resolve(resolver)


def test_resolver_is_the_registry_artifact_resolver_signature(tmp_path) -> None:
    resolver, _artifact = _resolver(
        tmp_path,
        ONE_ROW_ATTRIBUTION_CSV,
    )
    state = _resolve(resolver)
    registry = PersistentBacktestEvidenceRegistry(
        tmp_path / "backtest_evidence.jsonl",
        artifact_resolver=resolver,
    )
    record = BacktestAttributionRecord(
        owner_user_id=OWNER,
        recorded_by=OWNER,
        backtest_run_ref=QRO_REF,
        source_run_ref=SOURCE_RUN_REF,
        validation_methodology_ref="validation_methodology:formal-run-42",
        validation_depth_ref="validation_depth:formal-run-42",
        artifact_path="attribution.csv",
        artifact_sha256=state.artifact_sha256,
        row_count=state.row_count,
        component_refs=state.component_refs,
        cost_model_refs=("cost_model:fees",),
    )

    assert registry.record_attribution(record) == record


@pytest.mark.parametrize(
    ("owner", "backtest", "source", "path", "message"),
    (
        (OTHER_OWNER, QRO_REF, SOURCE_RUN_REF, "attribution.csv", "owner mismatch"),
        (OWNER, "qro_backtest_other", SOURCE_RUN_REF, "attribution.csv", "unavailable"),
        (OWNER, QRO_REF, "ide_run:other", "attribution.csv", "does not match"),
        (OWNER, QRO_REF, SOURCE_RUN_REF, "portfolio.csv", "must equal"),
    ),
)
def test_resolver_rejects_wrong_owner_run_source_and_artifact_path(
    tmp_path,
    owner,
    backtest,
    source,
    path,
    message,
) -> None:
    resolver, _artifact = _resolver(tmp_path, b"component,pnl\nmarket,1.0\n")

    with pytest.raises(BacktestArtifactResolutionError, match=message):
        resolver(owner, backtest, source, path)


def test_resolver_requires_backtest_qro_and_promoted_run_id(tmp_path) -> None:
    wrong_type, _artifact = _resolver(
        tmp_path / "wrong-type",
        b"component,pnl\nmarket,1.0\n",
        qro=_qro(qro_type="ValidationDossier"),
    )
    with pytest.raises(BacktestArtifactResolutionError, match="not a BacktestRun"):
        _resolve(wrong_type)

    missing_promoted, _artifact = _resolver(
        tmp_path / "missing-promoted",
        b"component,pnl\nmarket,1.0\n",
        qro=_qro(output_contract={"source_run_id": SOURCE_RUN_ID}),
    )
    with pytest.raises(BacktestArtifactResolutionError, match="promoted_run_id"):
        _resolve(missing_promoted)

    mismatched_source = _qro()
    mismatched_source.input_contract = {"source_run_id": "different-source"}
    resolver, _artifact = _resolver(
        tmp_path / "mismatched-source",
        b"component,pnl\nmarket,1.0\n",
        qro=mismatched_source,
    )
    with pytest.raises(BacktestArtifactResolutionError, match="input/output"):
        _resolve(resolver)


def test_legacy_run_id_requires_canonical_source_backing(tmp_path) -> None:
    backed_qro = _qro(
        output_contract={
            "run_id": SOURCE_RUN_ID,
            "promoted_run_id": PROMOTED_RUN_ID,
        }
    )
    resolver, _artifact = _resolver(
        tmp_path / "backed",
        ONE_ROW_ATTRIBUTION_CSV,
        qro=backed_qro,
    )
    assert _resolve(resolver).row_count == 1

    unbacked_qro = _qro(
        output_contract={
            "run_id": SOURCE_RUN_ID,
            "promoted_run_id": PROMOTED_RUN_ID,
        }
    )
    unbacked_qro.input_contract = {}
    unbacked_qro.lineage = (PROMOTED_RUN_ID,)
    resolver, _artifact = _resolver(
        tmp_path / "unbacked",
        ONE_ROW_ATTRIBUTION_CSV,
        qro=unbacked_qro,
    )
    with pytest.raises(BacktestArtifactResolutionError, match="lacks canonical"):
        _resolve(resolver)


@pytest.mark.parametrize(
    "data",
    (
        b"component,component\nmarket,1.0\n",
        b"component,\nmarket,1.0\n",
        b"component,pnl\n",
        b"component,pnl\n,\n",
        b"component,pnl\nmarket\n",
    ),
)
def test_resolver_rejects_duplicate_blank_or_empty_csv_structure(tmp_path, data) -> None:
    resolver, _artifact = _resolver(tmp_path, data)

    with pytest.raises(BacktestArtifactResolutionError):
        _resolve(resolver)


def test_resolver_rejects_run_and_artifact_symlinks(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "attribution.csv").write_text(
        "component,pnl\nmarket,1.0\n",
        encoding="utf-8",
    )
    run_root = tmp_path / "runs"
    run_root.mkdir()
    try:
        (run_root / PROMOTED_RUN_ID).symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    resolver = CanonicalBacktestArtifactResolver(
        run_root=run_root,
        research_graph_store=Graph(_qro()),
    )
    with pytest.raises(BacktestArtifactResolutionError, match="linked"):
        _resolve(resolver)

    (run_root / PROMOTED_RUN_ID).unlink()
    run_dir = run_root / PROMOTED_RUN_ID
    run_dir.mkdir()
    (run_dir / "attribution.csv").symlink_to(outside / "attribution.csv")
    with pytest.raises(BacktestArtifactResolutionError, match="linked"):
        _resolve(resolver)


def test_resolver_rejects_traversal_and_internal_read_drift(tmp_path, monkeypatch) -> None:
    traversal_qro = _qro(
        output_contract={
            "source_run_id": SOURCE_RUN_ID,
            "promoted_run_id": "../outside",
        }
    )
    traversal, _artifact = _resolver(
        tmp_path / "traversal",
        b"component,pnl\nmarket,1.0\n",
        qro=traversal_qro,
    )
    with pytest.raises(BacktestArtifactResolutionError, match="direct run_root child"):
        _resolve(traversal)

    resolver, artifact = _resolver(
        tmp_path / "drift",
        b"component,pnl\nmarket,1.0\n",
    )
    original = resolver._read_snapshot
    calls = 0

    def read_then_drift(promoted_run_id):
        nonlocal calls
        snapshot = original(promoted_run_id)
        calls += 1
        if calls == 1:
            artifact.write_bytes(b"component,pnl\nmarket,2.0\n")
        return snapshot

    monkeypatch.setattr(resolver, "_read_snapshot", read_then_drift)
    with pytest.raises(BacktestArtifactResolutionError, match="stable resolution"):
        _resolve(resolver)
