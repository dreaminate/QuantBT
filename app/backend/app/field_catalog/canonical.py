"""数据平台 v2 · canonical 受控字段词典（规范核心）。

各数据源的原始列对齐到 canonical id（如 ``vol`` → ``volume``、``turnover_rate`` 直命中），
因子/策略据此**跨源移植**；词典外的列由 catalog 归类为带命名空间的 freeform 字段。

单一真相源是 ``DEFAULT_CANONICAL_FIELDS``（纯 Python，零依赖、可被 typecheck）。
若同目录存在 ``canonical_fields.yaml`` 且环境装了 pyyaml，则在其上**合并/覆盖**
（团队可编辑扩展）；缺 yaml 或解析失败时静默回退到默认词典。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CanonicalField:
    id: str
    dtype: str = "f64"                 # f64 | i64 | str | datetime
    unit: str = ""
    markets: tuple[str, ...] = ()      # 空 = 适用全市场
    aliases: tuple[str, ...] = ()
    description: str = ""
    group: str = "misc"                # price / valuation / financial / moneyflow / crypto ...

    def applies_to(self, market: str | None) -> bool:
        return not self.markets or market is None or market in self.markets


# --- 首版受控词表（对齐 docs/plans/v2-data-platform.md §4）-----------------------

_CN = ("stocks_cn",)
_PERP = ("binanceusdm",)
_CRYPTO = ("binanceusdm", "binance_spot")

DEFAULT_CANONICAL_FIELDS: tuple[CanonicalField, ...] = (
    # 价量核心（全市场）
    CanonicalField("open", group="price", description="开盘价"),
    CanonicalField("high", group="price", description="最高价"),
    CanonicalField("low", group="price", description="最低价"),
    CanonicalField("close", group="price", description="收盘价"),
    CanonicalField("volume", aliases=("vol",), group="price", description="成交量"),
    CanonicalField(
        "amount",
        aliases=("turnover", "amt", "quote_volume", "quote_asset_volume"),
        group="price",
        description="成交额",
    ),
    CanonicalField("pct_change", aliases=("pct_chg",), unit="%", group="price", description="涨跌幅"),
    # 复权（A股）
    CanonicalField("adj_factor", markets=_CN, group="adjust", description="复权因子"),
    # A股估值（daily_basic）
    CanonicalField("pe_ttm", markets=_CN, group="valuation", description="市盈率 TTM"),
    CanonicalField("pb", markets=_CN, group="valuation", description="市净率"),
    CanonicalField("ps_ttm", markets=_CN, group="valuation", description="市销率 TTM"),
    CanonicalField("total_mv", markets=_CN, unit="万元", group="valuation", description="总市值"),
    CanonicalField("circ_mv", markets=_CN, unit="万元", group="valuation", description="流通市值"),
    CanonicalField("turnover_rate", markets=_CN, unit="%", group="valuation", description="换手率"),
    CanonicalField("volume_ratio", markets=_CN, group="valuation", description="量比"),
    CanonicalField("dv_ttm", markets=_CN, unit="%", group="valuation", description="股息率 TTM"),
    # A股财务（fina_indicator）
    CanonicalField("roe", markets=_CN, unit="%", group="financial", description="净资产收益率"),
    CanonicalField("roa", markets=_CN, unit="%", group="financial", description="总资产收益率"),
    CanonicalField("net_profit_margin", markets=_CN, unit="%", group="financial", description="销售净利率"),
    CanonicalField("gross_margin", markets=_CN, unit="%", group="financial", description="毛利率"),
    CanonicalField("debt_to_assets", markets=_CN, unit="%", group="financial", description="资产负债率"),
    CanonicalField("eps", markets=_CN, group="financial", description="每股收益"),
    CanonicalField("bps", markets=_CN, group="financial", description="每股净资产"),
    # A股资金流（moneyflow）
    CanonicalField("net_mf_amount", markets=_CN, unit="万元", group="moneyflow", description="净流入额"),
    CanonicalField("buy_lg_amount", markets=_CN, unit="万元", group="moneyflow", description="大单买入额"),
    CanonicalField("sell_lg_amount", markets=_CN, unit="万元", group="moneyflow", description="大单卖出额"),
    # A股估值/股本扩展（daily_basic / index_dailybasic）
    CanonicalField("pe", markets=_CN, group="valuation", description="市盈率(静态)"),
    CanonicalField("ps", markets=_CN, group="valuation", description="市销率(静态)"),
    CanonicalField("dv_ratio", markets=_CN, unit="%", group="valuation", description="股息率(静态)"),
    CanonicalField("turnover_rate_free", markets=_CN, unit="%", aliases=("turnover_rate_f",), group="valuation", description="自由流通换手率"),
    CanonicalField("total_share", markets=_CN, unit="万股", group="valuation", description="总股本"),
    CanonicalField("float_share", markets=_CN, unit="万股", group="valuation", description="流通股本"),
    CanonicalField("free_share", markets=_CN, unit="万股", group="valuation", description="自由流通股本"),
    CanonicalField("float_mv", markets=_CN, group="valuation", description="流通市值(指数)"),
    # 通用财务（universal —— 留空 markets 以便未来其它股票源共用）
    CanonicalField("total_assets", group="financial", description="资产总计"),
    CanonicalField("total_liab", group="financial", description="负债合计"),
    CanonicalField("total_equity", aliases=("total_hldr_eqy_inc_min_int",), group="financial", description="股东权益合计"),
    CanonicalField("total_revenue", group="financial", description="营业总收入"),
    CanonicalField("revenue", group="financial", description="营业收入"),
    CanonicalField("net_income", aliases=("n_income",), group="financial", description="净利润"),
    CanonicalField("operating_cashflow", aliases=("n_cashflow_act",), group="financial", description="经营活动现金流净额"),
    CanonicalField("free_cashflow", aliases=("fcff",), group="financial", description="企业自由现金流"),
    CanonicalField("ebit", group="financial", description="息税前利润"),
    CanonicalField("ebitda", group="financial", description="息税折旧摊销前利润"),
    CanonicalField("roic", markets=_CN, unit="%", group="financial", description="投入资本回报率"),
    CanonicalField("current_ratio", markets=_CN, group="financial", description="流动比率"),
    CanonicalField("quick_ratio", markets=_CN, group="financial", description="速动比率"),
    # 加密永续 / 衍生品
    CanonicalField("funding_rate", markets=_PERP, aliases=("last_funding_rate", "lastfundingrate", "fundingrate"), group="crypto", description="资金费率"),
    CanonicalField("funding_interval_hours", markets=_PERP, unit="h", group="crypto", description="资金费率结算周期"),
    CanonicalField("interest_rate", markets=_PERP, aliases=("interestrate",), group="crypto", description="利率"),
    CanonicalField("open_interest", markets=_PERP, aliases=("openinterest", "sum_open_interest", "sumopeninterest"), group="crypto", description="未平仓量"),
    CanonicalField("open_interest_value", markets=_PERP, aliases=("sum_open_interest_value", "sumopeninterestvalue"), group="crypto", description="持仓名义额"),
    CanonicalField("mark_price", markets=_PERP, aliases=("markprice",), group="crypto", description="标记价格"),
    CanonicalField("index_price", markets=_PERP, aliases=("indexprice",), group="crypto", description="指数价格"),
    CanonicalField("long_short_ratio", markets=_PERP, aliases=("longshortratio",), group="crypto", description="多空比(通用)"),
    CanonicalField("top_trader_ls_ratio_positions", markets=_PERP, aliases=("sum_toptrader_long_short_ratio",), group="crypto", description="大户持仓多空比"),
    CanonicalField("top_trader_ls_ratio_accounts", markets=_PERP, aliases=("count_toptrader_long_short_ratio",), group="crypto", description="大户账户多空比"),
    CanonicalField("global_ls_ratio_accounts", markets=_PERP, aliases=("count_long_short_ratio",), group="crypto", description="全市场账户多空比"),
    CanonicalField("taker_ls_vol_ratio", markets=_PERP, aliases=("sum_taker_long_short_vol_ratio", "buysellratio", "buy_sell_ratio"), group="crypto", description="主动买卖量比"),
    CanonicalField("long_account_ratio", markets=_PERP, aliases=("longaccount",), group="crypto", description="多头账户占比"),
    CanonicalField("short_account_ratio", markets=_PERP, aliases=("shortaccount",), group="crypto", description="空头账户占比"),
    CanonicalField("trade_count", markets=_CRYPTO, dtype="i64", aliases=("count", "number_of_trades"), group="crypto", description="成交笔数"),
    CanonicalField("taker_buy_volume", markets=_CRYPTO, aliases=("buy_vol",), group="crypto", description="主动买入量"),
    CanonicalField("taker_sell_volume", markets=_CRYPTO, aliases=("sell_vol",), group="crypto", description="主动卖出量"),
    CanonicalField("taker_buy_amount", markets=_CRYPTO, aliases=("taker_buy_quote_volume", "taker_buy_quote_asset_volume"), group="crypto", description="主动买入额"),
    CanonicalField("best_bid", markets=_PERP, aliases=("best_bid_price",), group="crypto", description="最优买价"),
    CanonicalField("best_ask", markets=_PERP, aliases=("best_ask_price",), group="crypto", description="最优卖价"),
    CanonicalField("best_bid_qty", markets=_PERP, group="crypto", description="最优买量"),
    CanonicalField("best_ask_qty", markets=_PERP, group="crypto", description="最优卖量"),
)


class CanonicalRegistry:
    def __init__(self, fields: list[CanonicalField] | tuple[CanonicalField, ...]) -> None:
        self._by_id: dict[str, CanonicalField] = {}
        self._alias: dict[str, str] = {}
        for f in fields:
            self._by_id[f.id] = f
            self._alias[f.id.lower()] = f.id
            for a in f.aliases:
                self._alias[a.lower()] = f.id

    def get(self, field_id: str) -> CanonicalField | None:
        return self._by_id.get(field_id)

    def all(self) -> list[CanonicalField]:
        return list(self._by_id.values())

    def ids(self) -> list[str]:
        return list(self._by_id.keys())

    def resolve(self, raw_column: str, market: str | None = None) -> str | None:
        """原始列名 → canonical id（命中 id 或 alias，大小写不敏感）；不命中或市场不适用返回 None。"""
        fid = self._alias.get(str(raw_column).strip().lower())
        if fid is None:
            return None
        return fid if self._by_id[fid].applies_to(market) else None

    @classmethod
    def load_default(cls) -> "CanonicalRegistry":
        fields: dict[str, CanonicalField] = {f.id: f for f in DEFAULT_CANONICAL_FIELDS}
        yaml_path = Path(__file__).with_name("canonical_fields.yaml")
        for f in _maybe_load_yaml(yaml_path):
            fields[f.id] = f
        return cls(tuple(fields.values()))


def _maybe_load_yaml(path: Path) -> list[CanonicalField]:
    if not path.exists():
        return []
    try:
        import yaml  # type: ignore

        raw: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        out: list[CanonicalField] = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or "id" not in item:
                continue
            out.append(
                CanonicalField(
                    id=str(item["id"]),
                    dtype=str(item.get("dtype", "f64")),
                    unit=str(item.get("unit", "")),
                    markets=tuple(item.get("markets", []) or []),
                    aliases=tuple(item.get("aliases", []) or []),
                    description=str(item.get("description", "")),
                    group=str(item.get("group", "misc")),
                )
            )
        return out
    except Exception:  # noqa: BLE001 - yaml 缺失/损坏时静默回退默认词典
        return []


# 进程内全局词典
CANONICAL = CanonicalRegistry.load_default()


__all__ = ["CanonicalField", "CanonicalRegistry", "CANONICAL", "DEFAULT_CANONICAL_FIELDS"]
