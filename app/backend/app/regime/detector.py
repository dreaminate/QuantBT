"""M2 · 市场状态划分（regime）。

依赖轻量：仅 numpy/polars，不引 hmmlearn/arch/ruptures。
用 Wilder ADX 判趋势强度 + 方向（+DI/-DI）划分 bull/bear/range，
再用波动率 z-score 识别 crisis（波动聚集）。

输出 `(ts, regime, adx, plus_di, minus_di, vol_z)`，其中
`regime ∈ {bull, bear, range, crisis}`，可直接 `select(["ts","regime"])`
喂给 M7 的 `apply_regime_gating`。

设计取舍：
- 规则法（非 HMM/GARCH）→ 确定性、可测、零额外依赖；HMM/GARCH 留作后续可插后端。
- crisis 优先级最高（波动聚集压过趋势判定），符合「危机即高波动」的常识。
- 前 2n-1 根（Wilder ADX 收敛前）强制 range（安全默认），不臆造状态。
- 数值健壮：停牌/坏 tick 导致的 0/负价不会顺着 inf/NaN 误判成 crisis。
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class RegimeConfig:
    """regime 判定阈值。

    - adx_window: Wilder ADX/DI 平滑窗口（经典 14）。
    - adx_trend: ADX ≥ 此值视为有趋势（经典 25）。
    - vol_window: 计算近端波动率（收益率滚动标准差）的窗口。
    - vol_baseline_window: 波动率基线窗口，用于把近端波动率 z 标准化。
    - crisis_z: 波动率 z-score 超过此值判 crisis。
    """

    adx_window: int = 14
    adx_trend: float = 25.0
    vol_window: int = 20
    vol_baseline_window: int = 100
    crisis_z: float = 2.0


_OUT_SCHEMA = {
    "regime": pl.Utf8,
    "adx": pl.Float64,
    "plus_di": pl.Float64,
    "minus_di": pl.Float64,
    "vol_z": pl.Float64,
}


def detect_regime(
    prices: pl.DataFrame,
    *,
    ts_col: str = "ts",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    config: RegimeConfig | None = None,
) -> pl.DataFrame:
    """从单一基准 OHLC 序列推断逐时点市场状态。

    入参 `prices` 需含 ts/high/low/close 四列（基准指数或某一标的）。
    返回按 ts 升序的 `(ts, regime, adx, plus_di, minus_di, vol_z)`。
    """

    config = config or RegimeConfig()
    missing = [c for c in (ts_col, high_col, low_col, close_col) if c not in prices.columns]
    if missing:
        raise ValueError(f"prices 缺少列 {missing}")

    if prices.height == 0:
        schema = {ts_col: prices.schema.get(ts_col, pl.Datetime("us")), **_OUT_SCHEMA}
        return pl.DataFrame(schema=schema)

    n = config.adx_window
    alpha = 1.0 / n
    # 波动率两个滚动窗口至少要有几个样本才有意义。
    vol_min = max(2, config.vol_window // 2)

    df = prices.sort(ts_col).with_columns(
        prev_close=pl.col(close_col).shift(1),
        prev_high=pl.col(high_col).shift(1),
        prev_low=pl.col(low_col).shift(1),
    )

    df = df.with_columns(
        up_move=pl.col(high_col) - pl.col("prev_high"),
        down_move=pl.col("prev_low") - pl.col(low_col),
        tr=pl.max_horizontal(
            pl.col(high_col) - pl.col(low_col),
            (pl.col(high_col) - pl.col("prev_close")).abs(),
            (pl.col(low_col) - pl.col("prev_close")).abs(),
        ),
    )

    df = df.with_columns(
        plus_dm=pl.when((pl.col("up_move") > pl.col("down_move")) & (pl.col("up_move") > 0))
        .then(pl.col("up_move"))
        .otherwise(0.0),
        minus_dm=pl.when((pl.col("down_move") > pl.col("up_move")) & (pl.col("down_move") > 0))
        .then(pl.col("down_move"))
        .otherwise(0.0),
    )

    # Wilder 平滑用 EWM(alpha=1/n, adjust=False) 近似（首值 seeding，前 2n-1 根未收敛 → 下方 warmup 段强制 range）。
    df = df.with_columns(
        atr=pl.col("tr").ewm_mean(alpha=alpha, adjust=False),
        plus_dm_s=pl.col("plus_dm").ewm_mean(alpha=alpha, adjust=False),
        minus_dm_s=pl.col("minus_dm").ewm_mean(alpha=alpha, adjust=False),
    )

    df = df.with_columns(
        plus_di=pl.when(pl.col("atr") > 0).then(100.0 * pl.col("plus_dm_s") / pl.col("atr")).otherwise(0.0),
        minus_di=pl.when(pl.col("atr") > 0).then(100.0 * pl.col("minus_dm_s") / pl.col("atr")).otherwise(0.0),
    )
    df = df.with_columns(di_sum=pl.col("plus_di") + pl.col("minus_di"))
    df = df.with_columns(
        dx=pl.when(pl.col("di_sum") > 0)
        .then(100.0 * (pl.col("plus_di") - pl.col("minus_di")).abs() / pl.col("di_sum"))
        .otherwise(0.0)
    )
    df = df.with_columns(adx=pl.col("dx").ewm_mean(alpha=alpha, adjust=False))

    # 波动率：收益率滚动标准差，再相对长基线做 z 标准化。
    # prev_close<=0（停牌/坏 tick/0 打印）置 null，避免 ±inf 顺着 rolling 传成 NaN 误判 crisis。
    df = df.with_columns(
        ret=pl.when(pl.col("prev_close") > 0)
        .then(pl.col(close_col) / pl.col("prev_close") - 1.0)
        .otherwise(None)
    )
    df = df.with_columns(
        vol=pl.col("ret").rolling_std(window_size=config.vol_window, min_samples=vol_min)
    )
    # 基线只用历史（shift 掉当前点），避免当前波动稀释自身 z 值、削弱 crisis 灵敏度。
    df = df.with_columns(vol_prev=pl.col("vol").shift(1))
    df = df.with_columns(
        vol_mean=pl.col("vol_prev").rolling_mean(window_size=config.vol_baseline_window, min_samples=config.vol_window),
        vol_std=pl.col("vol_prev").rolling_std(window_size=config.vol_baseline_window, min_samples=config.vol_window),
    )
    # 守卫连 NaN 一起判（polars 里 NaN≠null 且 NaN>x 为真），最后 fill_nan+fill_null 双兜底。
    df = df.with_columns(
        vol_z=pl.when(
            pl.col("vol_std").is_not_null()
            & pl.col("vol_std").is_finite()
            & (pl.col("vol_std") > 0)
            & pl.col("vol").is_finite()
        )
        .then((pl.col("vol") - pl.col("vol_mean")) / pl.col("vol_std"))
        .otherwise(0.0)
        .fill_nan(0.0)
        .fill_null(0.0)
    )

    # warmup：Wilder ADX 在前 2n-1 根尚未收敛，EWM 首值 seeding 会人为抬高 → 强制 range。
    warmup = 2 * config.adx_window - 1
    crisis_hit = pl.col("vol_z").is_finite() & (pl.col("vol_z") > config.crisis_z)
    regime = (
        pl.when(pl.int_range(pl.len()) < warmup)
        .then(pl.lit("range"))
        .when(crisis_hit)
        .then(pl.lit("crisis"))
        .when(pl.col("adx") >= config.adx_trend)
        .then(
            pl.when(pl.col("plus_di") >= pl.col("minus_di"))
            .then(pl.lit("bull"))
            .otherwise(pl.lit("bear"))
        )
        .otherwise(pl.lit("range"))
    )
    df = df.with_columns(regime=regime)
    return df.select([ts_col, "regime", "adx", "plus_di", "minus_di", "vol_z"])


def regime_summary(regimes: pl.DataFrame) -> dict[str, int]:
    """统计各 regime 出现次数，便于诊断/回测报告。"""
    if regimes.height == 0 or "regime" not in regimes.columns:
        return {}
    grouped = regimes.group_by("regime").agg(pl.len().alias("n"))
    return {str(row["regime"]): int(row["n"]) for row in grouped.iter_rows(named=True)}
