"""Tushare 全 A股数据补充编排。

吃现有 `tushare_quant1.tushare_provider.TokenPool`（多 token 限流 + 用量统计）。
定义"能拉到的全部 A股接口"，对 per_symbol 接口遍历全标的，断点续传(跳过已落 parquet)。

`call(api_name, **params)->DataFrame|list[dict]` 可注入：单测/离线传 mock，
真实用 `build_token_pool().call`（token 来自 ~/.quantbt/secrets.yaml，绝不打印）。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

Call = Callable[..., Any]


@dataclass(frozen=True)
class TushareInterface:
    name: str
    api_name: str
    scope: str  # "market" | "per_symbol"
    params: dict[str, Any] | None = None


# Tushare 2000 积分可拉到的主流 A股接口（行情 + 基础 + 资金 + 财务 + 指数）
A_SHARE_INTERFACES: tuple[TushareInterface, ...] = (
    # 市场级（一次/少次）
    TushareInterface("stock_basic", "stock_basic", "market", {"list_status": "L"}),
    TushareInterface("trade_cal", "trade_cal", "market"),
    TushareInterface("namechange", "namechange", "market"),
    TushareInterface("index_basic", "index_basic", "market"),
    TushareInterface("hs_const", "hs_const", "market", {"hs_type": "SH"}),
    # 标的级（遍历全 ts_code）
    TushareInterface("daily", "daily", "per_symbol"),
    TushareInterface("weekly", "weekly", "per_symbol"),
    TushareInterface("monthly", "monthly", "per_symbol"),
    TushareInterface("adj_factor", "adj_factor", "per_symbol"),
    TushareInterface("daily_basic", "daily_basic", "per_symbol"),
    TushareInterface("moneyflow", "moneyflow", "per_symbol"),
    TushareInterface("stk_limit", "stk_limit", "per_symbol"),
    TushareInterface("income", "income", "per_symbol"),
    TushareInterface("balancesheet", "balancesheet", "per_symbol"),
    TushareInterface("cashflow", "cashflow", "per_symbol"),
    TushareInterface("fina_indicator", "fina_indicator", "per_symbol"),
    TushareInterface("dividend", "dividend", "per_symbol"),
    TushareInterface("forecast", "forecast", "per_symbol"),
    TushareInterface("express", "express", "per_symbol"),
    TushareInterface("stk_holdernumber", "stk_holdernumber", "per_symbol"),
)


def _to_df(result: Any) -> pd.DataFrame:
    if isinstance(result, pd.DataFrame):
        return result
    if isinstance(result, list):
        return pd.DataFrame(result)
    return pd.DataFrame()


def list_a_share_symbols(call: Call, *, include_delisted: bool = True) -> list[str]:
    """全 A股 ts_code（上市 L + 退市 D + 暂停 P）。"""
    codes: list[str] = []
    statuses = ["L", "D", "P"] if include_delisted else ["L"]
    for st in statuses:
        df = _to_df(call("stock_basic", list_status=st, fields="ts_code"))
        if "ts_code" in df:
            codes.extend(df["ts_code"].astype(str).tolist())
    return sorted(set(codes))


@dataclass
class BackfillSummary:
    interface: str
    scope: str
    units_done: int  # 写了多少个 parquet（market=1；per_symbol=标的数）
    units_skipped: int
    rows: int
    errors: int
    empty: int = 0  # 返回空结果、未落盘的标的数（下次 resume 会重试）

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface, "scope": self.scope, "units_done": self.units_done,
            "units_skipped": self.units_skipped, "rows": self.rows, "errors": self.errors,
            "empty": self.empty,
        }


def backfill_interface(
    iface: TushareInterface,
    call: Call,
    *,
    data_root: Path,
    symbols: list[str] | None = None,
    skip_existing: bool = True,
    progress: Callable[[str], None] | None = None,
) -> BackfillSummary:
    base = data_root / "tushare" / iface.name
    base.mkdir(parents=True, exist_ok=True)
    extra = dict(iface.params or {})

    if iface.scope == "market":
        target = base.with_suffix(".parquet")
        if skip_existing and target.exists():
            return BackfillSummary(iface.name, iface.scope, 0, 1, 0, 0)
        try:
            df = _to_df(call(iface.api_name, **extra))
            df.to_parquet(target)
            if progress:
                progress(f"{iface.name} market · {len(df)} 行")
            return BackfillSummary(iface.name, iface.scope, 1, 0, len(df), 0)
        except Exception:  # noqa: BLE001
            return BackfillSummary(iface.name, iface.scope, 0, 0, 0, 1)

    # per_symbol
    syms = symbols if symbols is not None else list_a_share_symbols(call)
    done = skipped = rows = errors = empty = 0
    for code in syms:
        target = base / f"{code}.parquet"
        if skip_existing and target.exists():
            skipped += 1
            continue
        try:
            df = _to_df(call(iface.api_name, ts_code=code, **extra))
            if df.empty:
                # 空结果不落盘：否则 resume 会把"恰好为空/瞬时失败"的标的永久跳过。
                empty += 1
                continue
            df.to_parquet(target)
            done += 1
            rows += len(df)
            if progress and done % 50 == 0:
                progress(f"{iface.name} · {done}/{len(syms)} 标的")
        except Exception:  # noqa: BLE001
            errors += 1
    return BackfillSummary(iface.name, iface.scope, done, skipped, rows, errors, empty)


def backfill_all_a_share(
    call: Call,
    *,
    data_root: Path,
    interfaces: tuple[TushareInterface, ...] = A_SHARE_INTERFACES,
    symbols: list[str] | None = None,
    skip_existing: bool = True,
    progress: Callable[[str], None] | None = None,
) -> list[BackfillSummary]:
    """全量编排：所有接口 × 全标的，断点续传。返回每接口汇总。"""
    if symbols is None:
        symbols = list_a_share_symbols(call)
    out: list[BackfillSummary] = []
    for iface in interfaces:
        if progress:
            progress(f"开始接口 {iface.name}")
        out.append(
            backfill_interface(
                iface, call, data_root=data_root, symbols=symbols,
                skip_existing=skip_existing, progress=progress,
            )
        )
    return out


def read_tushare(name: str, *, data_root: Path, ts_code: str | None = None) -> pd.DataFrame:
    """像 API 一样读已落地的 Tushare 数据。"""
    base = data_root / "tushare" / name
    if ts_code:
        p = base / f"{ts_code}.parquet"
    else:
        p = base.with_suffix(".parquet")
    return pd.read_parquet(p) if p.exists() else pd.DataFrame()


def _resolve_tushare_token() -> str | None:
    """token 来源：env TUSHARE_TOKEN > ~/.quantbt/secrets.yaml 的 tushare.token。不打印/不入日志。"""
    import os

    import yaml

    token = os.environ.get("TUSHARE_TOKEN")
    sec = Path.home() / ".quantbt" / "secrets.yaml"
    if not token and sec.exists():
        data = yaml.safe_load(sec.read_text(encoding="utf-8")) or {}
        token = ((data.get("tushare") or {}).get("token")) or (
            ((data.get("data_sources") or {}).get("tushare") or {}).get("token")
        )
    return token


def build_token_pool(points: int = 2000):  # pragma: no cover - 真实用，需 token + 网络
    """构建限流 TokenPool（token 绝不打印）。TokenClient 字段较多，按其 dataclass 正确装配。"""
    import tushare as ts

    from ..tushare_quant1.tushare_provider import TokenClient, TokenPool, _mask_token

    token = _resolve_tushare_token()
    if not token:
        raise RuntimeError("未找到 Tushare token（~/.quantbt/secrets.yaml 的 tushare.token 或 env TUSHARE_TOKEN）")
    client = TokenClient(
        slot=1,
        token=token,
        token_mask=_mask_token(token),
        points=points,
        expires_at=None,
        ts_module=ts,
        pro_client=ts.pro_api(token),
    )
    return TokenPool([client])


__all__ = [
    "A_SHARE_INTERFACES",
    "BackfillSummary",
    "TushareInterface",
    "backfill_all_a_share",
    "backfill_interface",
    "build_token_pool",
    "list_a_share_symbols",
    "read_tushare",
]
