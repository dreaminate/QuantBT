"""统一数据补充 CLI —— 一条命令把全量历史拉到本地、像 API 一样读。

  # 加密：全市场(或指定 symbol)月+日 zip → 连续 parquet（断点续传）
  python scripts/backfill.py binance --market um --intervals 1d,1h --start 2020-01-01
  python scripts/backfill.py binance --symbols BTCUSDT,ETHUSDT --intervals 1d

  # A股：全接口 × 全标的（token 取自 ~/.quantbt/secrets.yaml，不打印）
  python scripts/backfill.py tushare
  python scripts/backfill.py tushare --symbols 000001.SZ,600000.SH

  # 全都拉
  python scripts/backfill.py all

读取（和 API 一样丝滑）：
  from app.data_backfill.binance import read_klines
  from app.data_backfill.tushare import read_tushare
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app" / "backend"))

from app.data_backfill import binance, tushare  # noqa: E402

DEFAULT_ROOT = Path("data/lake")


def _p(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def run_binance(args: argparse.Namespace) -> None:
    plan = binance.BinanceBackfillPlan(
        market=args.market,
        kind=args.kind,
        intervals=tuple(x.strip() for x in args.intervals.split(",") if x.strip()),
        symbols=tuple(x.strip().upper() for x in args.symbols.split(",") if x.strip()),
        start=date.fromisoformat(args.start),
    )
    print(f"[binance] market={plan.market} intervals={plan.intervals} symbols={plan.symbols or '全市场'} start={plan.start}")
    res = binance.backfill_all_binance(plan, data_root=Path(args.data_root), progress=_p)
    ok = [r for r in res if r.path]
    print(f"[binance] 完成 {len(ok)} 个序列，总行数 {sum(r.rows for r in ok)}，缺口 {sum(r.gaps for r in ok)}")


def run_tushare(args: argparse.Namespace) -> None:
    pool = tushare.build_token_pool()  # token 不打印
    syms = [x.strip() for x in args.symbols.split(",") if x.strip()] or None
    print(f"[tushare] 接口 {len(tushare.A_SHARE_INTERFACES)} 个 × {'指定标的' if syms else '全标的'}")
    res = tushare.backfill_all_a_share(pool.call, data_root=Path(args.data_root), symbols=syms, progress=_p)
    for s in res:
        print(f"  [{s.interface}] done={s.units_done} skip={s.units_skipped} rows={s.rows} err={s.errors}")


def main() -> None:
    ap = argparse.ArgumentParser(description="QuantBT 数据补充")
    ap.add_argument("--data-root", default=str(DEFAULT_ROOT))
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("binance")
    b.add_argument("--market", default="um", choices=["um", "cm", "spot"])
    b.add_argument("--kind", default="klines")
    b.add_argument("--intervals", default="1d,1h")
    b.add_argument("--symbols", default="")
    b.add_argument("--start", default="2020-01-01")

    t = sub.add_parser("tushare")
    t.add_argument("--symbols", default="")

    sub.add_parser("all")

    args = ap.parse_args()
    if args.cmd == "binance":
        run_binance(args)
    elif args.cmd == "tushare":
        run_tushare(args)
    elif args.cmd == "all":
        run_binance(argparse.Namespace(market="um", kind="klines", intervals="1d,1h", symbols="", start="2020-01-01", data_root=args.data_root))
        run_tushare(argparse.Namespace(symbols="", data_root=args.data_root))


if __name__ == "__main__":
    main()
