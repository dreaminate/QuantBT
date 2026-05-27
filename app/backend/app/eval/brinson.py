"""Brinson 风格归因（GOAL §6.1 + §2.2 A股策略硬指标）。

Brinson-Fachler 模型把组合超额收益拆成：
- 行业/风格 Allocation：组合权重偏离基准 × 基准内行业收益
- Stock Selection：组合内行业选股能力
- Interaction：两者交互项

输入：
- portfolio_panel: (ts, symbol, weight, return, group, ...) — group 可以是行业/市值/风格三层
- benchmark_panel: (ts, symbol, weight, return, group, ...) 同上

输出：每 ts 每 group 一行的 Allocation / Selection / Interaction 贡献。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import polars as pl


@dataclass
class BrinsonResult:
    by_period: pl.DataFrame
    total: dict[str, float]

    def to_dict(self) -> dict:
        return {
            "by_period": self.by_period.to_dicts()[:1000],
            "total": self.total,
        }


def brinson_attribution(
    portfolio: pl.DataFrame,
    benchmark: pl.DataFrame,
    group_col: str = "sector",
) -> BrinsonResult:
    """对两份 panel 跑 Brinson-Fachler 归因。

    要求两份 panel 都含列：ts / symbol / weight / return / group_col。
    """

    required = {"ts", "symbol", "weight", "return", group_col}
    for name, df in [("portfolio", portfolio), ("benchmark", benchmark)]:
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"{name} 缺少列 {missing}")

    port_agg = (
        portfolio.group_by(["ts", group_col])
        .agg(
            (pl.col("weight").sum()).alias("port_weight"),
            ((pl.col("weight") * pl.col("return")).sum() / pl.col("weight").sum()).alias("port_return"),
        )
    )
    bench_agg = (
        benchmark.group_by(["ts", group_col])
        .agg(
            (pl.col("weight").sum()).alias("bench_weight"),
            ((pl.col("weight") * pl.col("return")).sum() / pl.col("weight").sum()).alias("bench_return"),
        )
    )
    joined = port_agg.join(bench_agg, on=["ts", group_col], how="full", coalesce=True).fill_null(0.0)
    bench_total_return = (
        benchmark.group_by("ts")
        .agg(((pl.col("weight") * pl.col("return")).sum() / pl.col("weight").sum()).alias("bench_total_return"))
    )
    enriched = joined.join(bench_total_return, on="ts", how="left").with_columns(
        ((pl.col("port_weight") - pl.col("bench_weight")) * (pl.col("bench_return") - pl.col("bench_total_return")))
        .alias("allocation"),
        (pl.col("bench_weight") * (pl.col("port_return") - pl.col("bench_return"))).alias("selection"),
        ((pl.col("port_weight") - pl.col("bench_weight")) * (pl.col("port_return") - pl.col("bench_return")))
        .alias("interaction"),
    )
    by_period = enriched.select(
        ["ts", group_col, "port_weight", "bench_weight", "port_return", "bench_return",
         "allocation", "selection", "interaction"]
    )
    totals = {
        "allocation": float(by_period["allocation"].sum()),
        "selection": float(by_period["selection"].sum()),
        "interaction": float(by_period["interaction"].sum()),
    }
    totals["active_return"] = totals["allocation"] + totals["selection"] + totals["interaction"]
    return BrinsonResult(by_period=by_period, total=totals)


__all__ = ["BrinsonResult", "brinson_attribution"]
