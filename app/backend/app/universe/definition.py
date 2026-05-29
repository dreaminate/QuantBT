"""M2 · 资产池定义（动态/静态）。

`UniverseRules` 声明入池规则；`resolve_universe` 在给定 as-of 日按规则解析出成分。
规则全部作用于「截至 as-of 的数据」，因此天然 point-in-time，
只要喂入的面板保留了退市/下架标的的历史即可避免幸存者偏差。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class UniverseRules(BaseModel):
    """入池规则。

    两种模式：
    - 静态：给定 `static_symbols`，成分固定（仍会减去 `exclude_symbols`），其余排序/过滤忽略。
    - 动态：按面板数据逐 as-of 解析——上市天数/最低成交额/最低价/ST 过滤，再按 `rank_by` 取前 `top_n`。

    字段命名与字段宇宙的 canonical 对齐（amount/close…），跨 A 股与加密通用。
    """

    market: str
    static_symbols: list[str] | None = None

    rank_by: str | None = Field(default=None, description="排序字段（如 amount/circ_mv/total_mv），降序取前 top_n")
    top_n: int | None = Field(default=None, ge=1)

    min_history_days: int = Field(default=0, ge=0, description="要求截至 as-of 的历史 bar 数 ≥ 此值（上市天数代理）")
    lookback_days: int = Field(default=20, ge=1, description="流动性/最新价/排序值取最近多少根 bar")

    min_avg_amount: float | None = Field(default=None, description="近 lookback 平均成交额下限")
    amount_col: str = "amount"
    min_price: float | None = Field(default=None, description="最新价下限")
    price_col: str = "close"

    st_col: str | None = Field(default=None, description="若设置，该列为真的标的视为 ST/风险警示并剔除")
    exclude_symbols: list[str] = Field(default_factory=list)


class UniverseDefinition(BaseModel):
    """命名资产池：规则 + 元信息。"""

    id: str
    name: str
    market: str
    rules: UniverseRules
    description: str = ""


def universe_presets() -> list[UniverseDefinition]:
    """内置常用资产池（数据驱动，不硬编码指数成分）。

    指数成分（沪深300 等）需 Tushare index_weight，按需用 `static_symbols` 注入；
    这里给出全市场与流动性 Top-N 两类数据驱动池，跨市场通用。
    """

    return [
        UniverseDefinition(
            id="cn_all",
            name="A股全市场",
            market="stocks_cn",
            rules=UniverseRules(market="stocks_cn"),
            description="全部有数据的 A 股（含已退市，保留历史以避免幸存者偏差）",
        ),
        UniverseDefinition(
            id="cn_liquid_300",
            name="A股流动性 Top300",
            market="stocks_cn",
            rules=UniverseRules(
                market="stocks_cn", rank_by="amount", top_n=300, min_history_days=60, lookback_days=20
            ),
            description="按近 20 日成交额降序取前 300，近似大盘流动性池",
        ),
        UniverseDefinition(
            id="crypto_top30",
            name="加密成交额 Top30",
            market="binanceusdm",
            rules=UniverseRules(
                market="binanceusdm", rank_by="amount", top_n=30, min_history_days=30, lookback_days=30
            ),
            description="Binance USDM 永续按近 30 根成交额降序取前 30",
        ),
    ]
