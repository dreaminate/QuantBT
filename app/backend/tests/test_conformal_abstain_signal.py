"""conformal 校准区间接进信号层弃权（消费侧·R23）对抗测试。

门必抓：
- **跨阈值弃权**：预测区间 [score±q̂] 含阈值（|score−thr|≤q̂）→ flat/magnitude=0/abstained=True；区间整侧→保留方向。
- **边界 ≤**：|score−thr| 恰 ==q̂ → 弃权（误用 < 会漏边界）。
- **band≤0 向后兼容**：不弃权、direction 同 fuse。缺 score_col → raise（不用 confidence 代）。
- **命门交叉校验**：弃权 band == model_eval.conformal_prediction_band 的 band_half_width（同一 q̂）。
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import polars as pl
import pytest

from app.eval.model_eval import conformal_prediction_band
from app.signals import conformal_abstain_gate, fuse_signals


def _fused(scores: list[float], thr: float = 0.0) -> pl.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    df = pl.DataFrame({"ts": [base] * len(scores), "symbol": [f"S{i}" for i in range(len(scores))],
                       "score": scores})
    return fuse_signals(df, direction_threshold=thr)


def test_abstain_when_interval_straddles_threshold():
    """**门有牙**：|score−thr|≤q̂（区间含阈值）→ 弃权 flat/0/abstained；区间整侧 → 保留方向。

    种坏：把区间含阈值的噪声 score 仍发方向（不弃权）→ 此断言崩。
    """
    out = conformal_abstain_gate(_fused([0.7, -0.5, 0.05, -0.1, 0.25]), conformal_band=0.2)
    rows = out.to_dicts()
    exp = [("long", False), ("short", False), ("flat", True), ("flat", True), ("long", False)]
    for r, (d, ab) in zip(rows, exp):
        assert r["direction"] == d and r["abstained"] is ab, f"score={r['score']} 得 {r['direction']}/{r['abstained']} 期望 {d}/{ab}"
        if ab:
            assert r["magnitude"] == 0.0                       # 弃权 magnitude 归零


def test_abstain_boundary_is_inclusive():
    """边界 ≤：|score−thr| 恰 ==q̂ → 弃权（用 < 会漏边界 → 此测抓）。"""
    out = conformal_abstain_gate(_fused([0.2, 0.2001], thr=0.0), conformal_band=0.2).to_dicts()
    assert out[0]["abstained"] is True                          # ==q̂ → 弃权
    assert out[1]["abstained"] is False                         # 略超 q̂ → 保留


def test_abstain_monotonic_in_band():
    """band 越大 → 弃权数单调不减（覆盖更宽=更多噪声 score 不可辨）。"""
    fused = _fused([0.05, 0.15, 0.3, 0.6, -0.25], thr=0.0)
    counts = [int(conformal_abstain_gate(fused, conformal_band=b)["abstained"].sum()) for b in (0.0, 0.1, 0.2, 0.4, 1.0)]
    assert counts == sorted(counts) and counts[0] == 0 and counts[-1] == 5


def test_band_nonpositive_backward_compatible():
    """band≤0 → 不弃权（abstained 全 False、direction 同 fuse）；向后兼容（未调用此门=原行为）。"""
    fused = _fused([0.7, 0.05, -0.5], thr=0.0)
    out = conformal_abstain_gate(fused, conformal_band=0.0)
    assert out["abstained"].sum() == 0
    assert out["direction"].to_list() == fused["direction"].to_list()


def test_missing_score_col_raises_not_silent():
    """缺 score_col → raise（弃权判定必须用原始 score 量纲、绝不用 confidence/magnitude 代）。"""
    fused = _fused([0.7, 0.05]).drop("score")
    with pytest.raises(ValueError, match="score"):
        conformal_abstain_gate(fused, conformal_band=0.2)


def test_abstain_band_consistent_with_model_eval_conformal_band():
    """**命门交叉校验**：信号弃权 band 用 model_eval.conformal_prediction_band 的 band_half_width（同一 q̂）。

    残差 σ→split-conformal q̂；预测=score 同量纲 → 距阈值<q̂ 的 score 不可辨须弃权、>>q̂ 的须保留。绑两侧 q̂ 语义。
    """
    rng = np.random.default_rng(0)
    n = 400
    yt = rng.standard_normal(n) * 5.0
    yp = yt + rng.standard_normal(n) * 1.0                      # 残差 σ≈1
    band = conformal_prediction_band(
        {"spec": {"task": "regression"}, "oos_predictions": {"y_true": yt.tolist(), "y_pred": yp.tolist()}},
        alpha=0.1,
    )["band_half_width"]
    assert band is not None and band > 0
    # score 距阈值 0.1*band（远内）→ 弃权；3*band（远外）→ 保留
    out = conformal_abstain_gate(_fused([0.1 * band, 3.0 * band], thr=0.0), conformal_band=band).to_dicts()
    assert out[0]["abstained"] is True and out[0]["direction"] == "flat"
    assert out[1]["abstained"] is False and out[1]["direction"] == "long"
