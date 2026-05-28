"""集成测试：跑两个端到端 demo 脚本，校验产物落盘 + 指标在合理范围。

这两个 demo 是 §13.2 / §13.3 的"能用"证据；它们崩 = 全栈崩。
故意用 deterministic seed，使得测试可重复。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest


EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"


@pytest.fixture(autouse=True)
def _add_examples_to_syspath():
    if str(EXAMPLES_DIR) not in sys.path:
        sys.path.insert(0, str(EXAMPLES_DIR))
    yield


def _assert_standard_run_dir(run_id: str) -> Path:
    root = Path(__file__).resolve().parents[3] / "data" / "artifacts" / "experiments" / run_id
    for name in ("run.json", "metrics.json", "portfolio.csv", "trades.csv", "report.md"):
        assert (root / name).exists(), f"缺产物：{name}"
    return root


def test_a_share_ml_demo_end_to_end(tmp_path_factory):
    from run_a_share_ml_demo import run as run_a  # type: ignore[import-not-found]

    out = run_a(run_id="a_share_ml_demo_test", days=160, top_n=5)
    root = _assert_standard_run_dir("a_share_ml_demo_test")
    metrics = json.loads((root / "metrics.json").read_text(encoding="utf-8"))
    # 关键指标必须存在
    assert "sharpe" in metrics
    assert "pbo" in metrics
    assert "deflated_sharpe" in metrics
    assert "bootstrap_sharpe_ci" in metrics
    assert "brinson_total" in metrics  # A股 demo 强制 Brinson
    # PBO ∈ [0, 1]
    assert 0.0 <= metrics["pbo"]["pbo"] <= 1.0
    # DSR ∈ [0, 1]
    assert 0.0 <= metrics["deflated_sharpe"] <= 1.0
    # Bootstrap CI 包含 estimate
    ci = metrics["bootstrap_sharpe_ci"]
    assert ci["lower"] <= ci["estimate"] <= ci["upper"]
    # portfolio.csv 有列
    port = pd.read_csv(root / "portfolio.csv")
    for col in ("timestamp", "equity", "net_return", "drawdown"):
        assert col in port.columns
    assert len(port) > 100
    # report.md 含三项过拟合 + Brinson
    report = (root / "report.md").read_text(encoding="utf-8")
    for must_have in ("PBO", "DSR", "Bootstrap", "Brinson", "Allocation", "Selection"):
        assert must_have in report, f"report.md 缺：{must_have}"


def test_crypto_perp_demo_end_to_end(tmp_path_factory):
    from run_crypto_perp_demo import run as run_c  # type: ignore[import-not-found]

    out = run_c(run_id="crypto_perp_demo_test", days=160)
    root = _assert_standard_run_dir("crypto_perp_demo_test")
    metrics = json.loads((root / "metrics.json").read_text(encoding="utf-8"))
    # 关键指标
    assert "sharpe" in metrics
    assert "pbo" in metrics
    assert "deflated_sharpe" in metrics
    assert "bootstrap_sharpe_ci" in metrics
    # 加密必须有成本拖累分解
    cost = metrics["cost_breakdown"]
    assert {"total_fee", "total_funding", "total_slippage", "total_cost"} == set(cost)
    assert cost["total_funding"] >= 0
    # 365 天年化（加密 24/7）
    assert metrics["sharpe"] != 0  # 默认 deterministic seed 下应非零
    # portfolio.csv 有 funding/fee 列
    port = pd.read_csv(root / "portfolio.csv")
    for col in ("timestamp", "equity", "funding_total", "fee_total"):
        assert col in port.columns
    # report.md 含成本分解 + PBO/DSR
    report = (root / "report.md").read_text(encoding="utf-8")
    for must_have in ("PBO", "DSR", "成本拖累", "手续费", "资金费率"):
        assert must_have in report, f"report.md 缺：{must_have}"


def test_run_json_metadata_completeness():
    """两个 demo 都已经跑过（前两个测试），run.json 元数据必须完整。"""

    for run_id in ("a_share_ml_demo_test", "crypto_perp_demo_test"):
        root = Path(__file__).resolve().parents[3] / "data" / "artifacts" / "experiments" / run_id
        if not (root / "run.json").exists():
            pytest.skip(f"{run_id} 未运行；先跑前两个测试")
        run_json = json.loads((root / "run.json").read_text(encoding="utf-8"))
        for key in ("run_id", "started_at", "status", "metrics", "asset_class"):
            assert key in run_json, f"run.json 缺字段：{key}"
        assert run_json["status"] == "completed"
