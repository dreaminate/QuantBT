"""v0.9.7 学术 audit v2 contract test (patch1 §G.a #4, #5, #6, #7, #15)。

任何改动量化算法的 PR 必须先过这些 contract test。CI 阻断不绕过。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from app.data_hash.dataset_hash import (
    DatasetIntegrityError,
    DatasetManifest,
    FactorBinding,
    FileEntry,
    create_manifest,
    verify_manifest,
    write_manifest,
)
from app.factor_factory.audit import assert_shift_invariant
from app.models.walk_forward_v2 import (
    ParamCandidate,
    WalkForwardReport,
    detect_gridsearch_leak,
    run_walk_forward_v2,
)
from app.portfolio.hrp_audit import (
    is_near_singular,
    ledoit_wolf_shrinkage,
    optimize_hrp_safe,
)


# ============================================================
# §G.a #4 · Walk-forward per-window selection log
# ============================================================


def _toy_evaluator(params: dict, X: np.ndarray, y: np.ndarray) -> float:
    """简单 evaluator: y 与 X[:, 0] * params['w'] 的负 MSE."""
    w = params.get("w", 1.0)
    pred = X[:, 0] * w
    return -float(np.mean((y - pred) ** 2))


def test_walk_forward_v2_basic_run():
    np.random.seed(0)
    n = 200
    X = np.random.randn(n, 2)
    y = X[:, 0] * 2.5 + np.random.randn(n) * 0.1
    grid = [{"w": w} for w in [1.0, 2.0, 2.5, 3.0]]
    report = run_walk_forward_v2(
        X=X, y=y, param_grid=grid, evaluator=_toy_evaluator,
        train_size=50, test_size=20,
    )
    assert len(report.windows) > 0
    assert report.deterministic is True


def test_walk_forward_v2_per_window_independent_selection():
    """关键 contract: 每个 window 必须有完整 candidate evaluation。"""
    np.random.seed(0)
    n = 200
    X = np.random.randn(n, 2)
    y = X[:, 0] * 2.0 + np.random.randn(n) * 0.5
    grid = [{"w": w} for w in [1.0, 2.0, 3.0]]
    report = run_walk_forward_v2(
        X=X, y=y, param_grid=grid, evaluator=_toy_evaluator,
        train_size=50, test_size=20,
    )
    for window in report.windows:
        # 每个 window 必须 evaluate 全部 candidate
        assert len(window.candidates_evaluated) == len(grid)
        assert len(window.candidate_train_metrics) == len(grid)
        assert window.selected_params_hash in [c.params_hash for c in window.candidates_evaluated]


def test_walk_forward_v2_selected_train_metric_is_max():
    np.random.seed(0)
    X = np.random.randn(100, 2)
    y = X[:, 0] * 2.0
    grid = [{"w": w} for w in [0.5, 1.0, 2.0, 3.0]]
    report = run_walk_forward_v2(
        X=X, y=y, param_grid=grid, evaluator=_toy_evaluator,
        train_size=50, test_size=20,
    )
    for w in report.windows:
        # selected_train_metric 必须是该 window candidate metrics 的最大值
        assert math.isclose(w.selected_train_metric, max(w.candidate_train_metrics), abs_tol=1e-9)


def test_walk_forward_v2_test_fold_no_train_overlap():
    np.random.seed(0)
    X = np.random.randn(200, 2)
    y = np.random.randn(200)
    grid = [{"w": 1.0}, {"w": 2.0}]
    report = run_walk_forward_v2(
        X=X, y=y, param_grid=grid, evaluator=_toy_evaluator,
        train_size=50, test_size=20, embargo=5,
    )
    for w in report.windows:
        # train [start, train_end) 和 test [test_start, test_end) 之间有 embargo
        assert w.test_start >= w.train_end + 5  # embargo


def test_walk_forward_v2_empty_grid_raises():
    with pytest.raises(ValueError, match="param_grid"):
        run_walk_forward_v2(
            X=np.zeros((10, 2)), y=np.zeros(10),
            param_grid=[], evaluator=_toy_evaluator,
            train_size=5, test_size=2,
        )


def test_walk_forward_v2_shape_mismatch_raises():
    with pytest.raises(ValueError):
        run_walk_forward_v2(
            X=np.zeros((10, 2)), y=np.zeros(8),  # mismatch
            param_grid=[{"w": 1}], evaluator=_toy_evaluator,
            train_size=5, test_size=2,
        )


def test_detect_gridsearch_leak_single_candidate_heuristic():
    """只传 1 candidate 进 walk_forward 触发 heuristic warning."""
    np.random.seed(0)
    X = np.random.randn(100, 2)
    y = np.random.randn(100)
    report = run_walk_forward_v2(
        X=X, y=y, param_grid=[{"w": 2.0}],  # 只 1 个
        evaluator=_toy_evaluator,
        train_size=50, test_size=20,
    )
    leak, msg = detect_gridsearch_leak(report)
    assert leak is True
    assert "1 candidate" in msg or "外部 GridSearch" in msg


def test_walk_forward_aggregate_oos_metric():
    np.random.seed(0)
    X = np.random.randn(200, 2)
    y = X[:, 0] * 2.0
    grid = [{"w": w} for w in [1.0, 2.0, 3.0]]
    report = run_walk_forward_v2(
        X=X, y=y, param_grid=grid, evaluator=_toy_evaluator,
        train_size=50, test_size=20,
    )
    assert not math.isnan(report.aggregate_oos_metric)


# ============================================================
# §G.a #5 · 因子 AST shift-invariance
# ============================================================


def test_correct_ts_mean_passes_shift_invariance():
    """正确的 ts_mean (只看 t-w+1 到 t) 必须过 contract test."""
    def correct_ts_mean(x: np.ndarray, w: int) -> np.ndarray:
        out = np.full_like(x, np.nan, dtype=float)
        for i in range(w - 1, len(x)):
            out[i] = float(np.mean(x[i - w + 1:i + 1]))
        return out

    result = assert_shift_invariant(correct_ts_mean, "correct_ts_mean", window=5)
    assert result.passed, result.detail


def test_lookahead_ts_mean_fails_shift_invariance():
    """中心化均值 (center=True) 必须被 contract test 抓到。"""
    def lookahead_ts_mean(x: np.ndarray, w: int) -> np.ndarray:
        out = np.full_like(x, np.nan, dtype=float)
        half = w // 2
        for i in range(half, len(x) - half):
            out[i] = float(np.mean(x[i - half:i + half + 1]))
        return out

    result = assert_shift_invariant(lookahead_ts_mean, "lookahead_ts_mean", window=5)
    assert result.passed is False
    assert "LOOKAHEAD" in result.detail or result.diff_at_index is not None


def test_correct_delta_passes():
    def correct_delta(x: np.ndarray, n: int) -> np.ndarray:
        out = np.full_like(x, np.nan, dtype=float)
        for i in range(n, len(x)):
            out[i] = x[i] - x[i - n]
        return out

    result = assert_shift_invariant(correct_delta, "correct_delta", window=3)
    assert result.passed


def test_constant_series_vacuous_pass():
    """常数序列 ts_mean 输出常数，shift-invariance vacuous true."""
    def const_ts(x: np.ndarray, w: int) -> np.ndarray:
        return np.full_like(x, 42.0, dtype=float)

    result = assert_shift_invariant(const_ts, "const_ts", window=5)
    assert result.passed


# ============================================================
# §G.a #15 · HRP 协方差奇异 fallback
# ============================================================


def test_hrp_normal_low_correlation_uses_hrp():
    """协方差正常 → fallback_used='hrp'."""
    np.random.seed(0)
    returns = np.random.randn(252, 5) * 0.01
    symbols = [f"A{i}" for i in range(5)]
    result = optimize_hrp_safe(returns, symbols)
    assert result.fallback_used == "hrp"
    assert result.singularity_detected is False
    assert math.isclose(sum(result.weights.values()), 1.0, abs_tol=1e-6)
    assert all(0 <= w <= 1 for w in result.weights.values())


def test_hrp_high_correlation_falls_back():
    """N > T 时协方差秩亏 → fallback (not 'hrp')."""
    np.random.seed(0)
    # 5 资产 × 4 时间点 → N(5) > T(4) 协方差必秩亏
    n_assets = 5
    base = np.random.randn(4) * 0.01
    returns = np.column_stack([base + np.random.randn(4) * 0.0001 for _ in range(n_assets)])
    symbols = [f"X{i}" for i in range(n_assets)]
    result = optimize_hrp_safe(returns, symbols, singularity_threshold=1e-4)
    # 应该 fallback shrunk / risk_parity
    assert result.fallback_used in ("hrp_shrunk", "risk_parity")
    assert result.singularity_detected is True
    # 权重无 NaN
    assert all(math.isfinite(w) for w in result.weights.values())
    assert math.isclose(sum(result.weights.values()), 1.0, abs_tol=1e-3)


def test_hrp_extreme_corr_99_falls_back():
    """构造严格 corr=1 的资产 → 必 fallback."""
    np.random.seed(0)
    base = np.random.randn(252) * 0.01
    # 用同一 base 直接复制 (相关性 1.0)
    returns = np.column_stack([base.copy() for _ in range(5)])
    symbols = [f"Y{i}" for i in range(5)]
    result = optimize_hrp_safe(returns, symbols, singularity_threshold=1e-4)
    assert result.fallback_used in ("hrp_shrunk", "risk_parity", "equal_weight")
    assert all(math.isfinite(w) for w in result.weights.values())


def test_hrp_single_asset_returns_100pct():
    returns = np.random.randn(100, 1) * 0.01
    result = optimize_hrp_safe(returns, ["BTC"])
    assert result.weights == {"BTC": 1.0}
    assert result.fallback_used == "equal_weight"


def test_hrp_diagonal_cov_equivalent_to_risk_parity():
    """协方差是对角阵 → fallback risk_parity 结果与 inverse-vol 接近."""
    np.random.seed(0)
    n_assets = 4
    vols = [0.01, 0.02, 0.03, 0.04]
    returns = np.column_stack([np.random.randn(252) * v for v in vols])
    symbols = [f"D{i}" for i in range(n_assets)]
    result = optimize_hrp_safe(returns, symbols)
    # 权重应大致按 inverse vol 分配
    weights_list = [result.weights[s] for s in symbols]
    assert weights_list[0] > weights_list[3]  # 低 vol 资产权重应更高


def test_is_near_singular_detects_rank_deficient():
    # 构造秩 1 矩阵 (奇异)
    v = np.array([1.0, 2.0, 3.0])
    cov = np.outer(v, v)  # rank 1
    singular, min_eig, cond = is_near_singular(cov)
    assert singular is True
    assert min_eig < 1e-8 or cond > 1e10


def test_is_near_singular_passes_well_conditioned():
    cov = np.eye(3)  # 完美 conditioned
    singular, min_eig, cond = is_near_singular(cov)
    assert singular is False
    assert math.isclose(cond, 1.0)


def test_ledoit_wolf_shrinkage_improves_condition():
    """对奇异矩阵 shrinkage 后 condition number 必须下降."""
    v = np.array([1.0, 2.0, 3.0])
    cov = np.outer(v, v) + np.eye(3) * 0.001  # 接近奇异
    cov_shrunk = ledoit_wolf_shrinkage(cov, shrinkage=0.3)
    _, _, cond_before = is_near_singular(cov)
    _, _, cond_after = is_near_singular(cov_shrunk)
    assert cond_after < cond_before


# ============================================================
# §G.a #6 + #7 · dataset_version SHA-256 manifest + FactorBinding
# ============================================================


def test_create_manifest_basic(tmp_path: Path):
    root = tmp_path / "ds"
    root.mkdir()
    (root / "a.csv").write_text("x,y\n1,2\n3,4\n")
    (root / "b.parquet").write_bytes(b"placeholder")  # 不是真 parquet, row_count 会 None
    m = create_manifest("test_ds", "v1", root)
    assert m.dataset_id == "test_ds"
    assert m.version == "v1"
    assert len(m.files) == 2
    # 文件按 path 排序
    assert m.files[0].relative_path == "a.csv"
    assert m.files[0].sha256
    assert len(m.files[0].sha256) == 64  # SHA-256 hex


def test_manifest_sha256_changes_when_content_changes(tmp_path: Path):
    root = tmp_path / "ds"
    root.mkdir()
    f = root / "a.csv"
    f.write_text("v1")
    m1 = create_manifest("test", "v1", root)
    f.write_text("v2")  # 内容变了
    m2 = create_manifest("test", "v1", root)
    assert m1.files[0].sha256 != m2.files[0].sha256


def test_write_manifest_rejects_content_change(tmp_path: Path):
    """同 (dataset_id, version) 再写入但 hash 不一致 → raise (内容不可变)."""
    root = tmp_path / "ds"
    root.mkdir()
    (root / "a.csv").write_text("v1")
    m1 = create_manifest("test", "v1", root)
    mf_path = tmp_path / "manifest.json"
    write_manifest(m1, mf_path)

    # 改文件内容后再创建同 version 的 manifest
    (root / "a.csv").write_text("v2")
    m2 = create_manifest("test", "v1", root)
    with pytest.raises(DatasetIntegrityError, match="sha256 不一致"):
        write_manifest(m2, mf_path)


def test_verify_manifest_passes_unchanged(tmp_path: Path):
    root = tmp_path / "ds"
    root.mkdir()
    (root / "a.csv").write_text("hello")
    m = create_manifest("test", "v1", root)
    mf = tmp_path / "manifest.json"
    write_manifest(m, mf)
    ok, mismatches = verify_manifest(mf, root)
    assert ok is True
    assert mismatches == []


def test_verify_manifest_detects_external_modification(tmp_path: Path):
    root = tmp_path / "ds"
    root.mkdir()
    (root / "a.csv").write_text("hello")
    m = create_manifest("test", "v1", root)
    mf = tmp_path / "manifest.json"
    write_manifest(m, mf)
    # 外部篡改
    (root / "a.csv").write_text("hello tampered")
    ok, mismatches = verify_manifest(mf, root)
    assert ok is False
    assert any("sha256 mismatch" in m for m in mismatches)


def test_verify_manifest_detects_missing_file(tmp_path: Path):
    root = tmp_path / "ds"
    root.mkdir()
    (root / "a.csv").write_text("hello")
    m = create_manifest("test", "v1", root)
    mf = tmp_path / "manifest.json"
    write_manifest(m, mf)
    (root / "a.csv").unlink()
    ok, mismatches = verify_manifest(mf, root)
    assert ok is False
    assert any("文件丢失" in m for m in mismatches)


def test_factor_binding_composite_key():
    fb1 = FactorBinding(factor_id="alpha_001", expression="ts_mean(close, 20)",
                          dataset_id="hs300_daily", dataset_version="v1")
    fb2 = FactorBinding(factor_id="alpha_001", expression="ts_mean(close, 20)",
                          dataset_id="hs300_daily", dataset_version="v2")
    fb3 = FactorBinding(factor_id="alpha_001", expression="ts_mean(close, 20)",
                          dataset_id="binance_btc", dataset_version="v1")
    # 同 factor_id 不同 dataset_version → 不同 composite key
    assert fb1.composite_key != fb2.composite_key
    # 同 factor_id 不同 dataset_id → 不同 composite key
    assert fb1.composite_key != fb3.composite_key
    # 含 universe_snapshot
    fb4 = FactorBinding(factor_id="alpha_001", expression="x",
                          dataset_id="ds", dataset_version="v1",
                          universe_snapshot_id="snap_hs300_2024Q4")
    assert "snap_hs300_2024Q4" in fb4.composite_key


def test_factor_binding_to_dict():
    fb = FactorBinding(factor_id="x", expression="y", dataset_id="d", dataset_version="v")
    d = fb.to_dict()
    assert d["factor_id"] == "x"
    assert d["dataset_version"] == "v"
