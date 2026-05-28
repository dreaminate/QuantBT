"""端到端 A股 ML demo · **真实 Tushare 数据**版本。

跟 `run_a_share_ml_demo.py` 同一套 7 层 pipeline（factor→label→model→signal→portfolio→backtest→eval），
区别只在 panel 来源：Tushare Pro daily（沪深 300 成分股子集）替换合成 panel。

用法：
    # 默认拉 50 只成分 × 2 年
    python examples/run_a_share_real_demo.py
    # 拉 100 只 × 3 年
    python examples/run_a_share_real_demo.py --top-n 8 --n-symbols 100 --years 3

依赖：~/.quantbt/secrets.yaml 含 tushare.token；启动 backend 后自动注入 TUSHARE_TOKEN env。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from _e2e_common import BACKEND_DIR  # noqa: F401  让 app.* 可 import
from run_a_share_ml_demo import _SECTORS, run as run_ml_demo  # type: ignore[import-not-found]

# 让 secrets.yaml 在 CLI 直接跑时也能 load（不依赖 backend 启动）
from app.security import InMemoryKeystore, SecureKeystore, load_secrets

_KS = SecureKeystore(InMemoryKeystore())
load_secrets(_KS)


def _pull_hs300_top_n(n_symbols: int, days: int) -> pl.DataFrame:
    """拉沪深 300 成分股前 n 只 daily（按权重排序），合成 panel。"""

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError(
            "TUSHARE_TOKEN 未配置；请填 ~/.quantbt/secrets.yaml 的 tushare.token 后重跑"
        )
    import tushare as ts

    ts.set_token(token)
    pro = ts.pro_api()

    # 1) 拉成分 + 权重
    # 系统时钟可能在未来；Tushare 实际数据库通常滞后。从今天起最多向前找 400 天。
    print(f"[1/3] 拉 hs300 成分股（权重排序前 {n_symbols} 只）...", flush=True)
    cursor = datetime.now(UTC).date()
    weights = None
    last_date = ""
    for i in range(400):
        trade_date = (cursor - timedelta(days=i)).strftime("%Y%m%d")
        try:
            weights = pro.index_weight(index_code="000300.SH", trade_date=trade_date)
        except Exception as exc:  # noqa: BLE001
            if i % 50 == 0:
                print(f"   ... 试 {trade_date} 失败：{exc}", flush=True)
            time.sleep(0.5)
            continue
        if weights is not None and not weights.empty:
            last_date = trade_date
            break
        if i % 30 == 0:
            print(f"   ... 试 {trade_date} 无数据，继续往前找", flush=True)
        time.sleep(0.15)
    if weights is None or weights.empty:
        raise RuntimeError(
            "拉 hs300 成分股失败（已向前找 400 天）：可能积分不足或网络问题"
        )
    print(f"   ✓ 命中 trade_date={last_date}", flush=True)
    top = weights.sort_values("weight", ascending=False).head(n_symbols)
    symbols = top["con_code"].tolist()
    print(f"      已选 {len(symbols)} 只，第一只 {symbols[0]} 权重 {top.iloc[0]['weight']:.2f}", flush=True)

    # 2) 拉行业（用 stock_basic 一次拉全市场，再 filter）
    print("[2/3] 拉行业分类 (stock_basic) ...", flush=True)
    basics = pro.stock_basic(exchange="", list_status="L", fields="ts_code,industry")
    sector_map = {row["ts_code"]: (row["industry"] or "其它") for _, row in basics.iterrows()}

    # 3) 循环拉每只股票的 daily（带令牌桶简单 throttle）
    print(f"[3/3] 拉每只股票近 {days} 天 daily（限流 500/min，约 {len(symbols)/8:.0f}s）...", flush=True)
    end = datetime.now(UTC).strftime("%Y%m%d")
    start = (datetime.now(UTC) - timedelta(days=days + 30)).strftime("%Y%m%d")
    rows: list[dict[str, Any]] = []
    n_ok = 0
    for i, ts_code in enumerate(symbols, 1):
        try:
            df = pro.daily(ts_code=ts_code, start_date=start, end_date=end)
        except Exception as exc:  # noqa: BLE001
            print(f"   ⚠ {ts_code} 拉失败：{exc}", flush=True)
            time.sleep(1.0)
            continue
        if df is None or df.empty:
            continue
        sector = sector_map.get(ts_code, "其它")
        # 归一化到 UnifiedOHLCV
        for _, r in df.iterrows():
            try:
                dt = datetime.strptime(str(r["trade_date"]), "%Y%m%d").replace(tzinfo=UTC)
            except Exception:  # noqa: BLE001
                continue
            rows.append(
                {
                    "ts": dt,
                    "symbol": ts_code,
                    "market": "stocks_cn",
                    "interval": "1d",
                    "open": float(r.get("open") or 0),
                    "high": float(r.get("high") or 0),
                    "low": float(r.get("low") or 0),
                    "close": float(r.get("close") or 0),
                    "volume": float(r.get("vol") or 0),
                    "amount": float(r.get("amount") or 0),
                    "sector": sector,
                }
            )
        n_ok += 1
        if i % 10 == 0:
            print(f"   ... {i}/{len(symbols)} 拉完", flush=True)
        # 简单 throttle：单 IP 200次/分钟（daily 接口），约 0.3s/req
        time.sleep(0.32)
    print(f"      {n_ok}/{len(symbols)} 只标的成功", flush=True)
    if not rows:
        raise RuntimeError("Tushare 拉到 0 行；token 可能积分不足或网络问题")
    panel = pl.DataFrame(rows).sort(["symbol", "ts"])
    return panel


def main() -> int:
    parser = argparse.ArgumentParser(description="QuantBT · A股 ML 端到端 demo（真实 Tushare 数据）")
    parser.add_argument("--run-id", default="a_share_real_demo")
    parser.add_argument("--n-symbols", type=int, default=50, help="hs300 取前 N 只权重大的")
    parser.add_argument("--years", type=float, default=2.0)
    parser.add_argument("--top-n", type=int, default=5)
    args = parser.parse_args()
    days = max(120, int(args.years * 252))

    print(f"==> 拉 Tushare 真数据：hs300 top-{args.n_symbols} × {args.years} 年", flush=True)
    panel = _pull_hs300_top_n(args.n_symbols, days)
    print(f"==> 拿到 panel: {panel.height} 行 × {panel['symbol'].n_unique()} 标的", flush=True)
    print(f"    日期范围 {panel['ts'].min()} → {panel['ts'].max()}", flush=True)

    print("==> 跑 ML pipeline ...", flush=True)
    out = run_ml_demo(
        run_id=args.run_id,
        days=days,
        top_n=args.top_n,
        panel=panel,
        strategy_name=f"A股 真数据 demo (hs300 top-{args.n_symbols} × LGBM × HRP)",
    )
    m = out["metrics"]
    print(
        f"\n✅ {args.run_id} done\n"
        f"   sharpe={m['sharpe']:.4f}  pbo={m['pbo']['pbo']:.4f}  dsr={m['deflated_sharpe']:.4f}\n"
        f"   total_return={m['total_return']:.4%}  max_dd={m['max_drawdown']:.4%}\n"
        f"   产物：data/artifacts/experiments/{args.run_id}/",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
