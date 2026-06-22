"""DS-1 · 把 StrategyGoal/对话意图【合成】成沙箱可跑的最小策略 Python。

脊梁要求（Fork3=A）：陌生人对话回测路径不再造 RunStore 占位，而是
  合成最小策略 Python → ide.sandbox.run_user_strategy(读 DATA_DIR 真样本) → emit_result(真净值)
  → ide.promote.promote_ide_run 落 RUN_ROOT → 真 run_id。

两条合成路（接 Fork1=C）：
  · 有 LLM（key / Hermes 等 OpenAI 兼容代理）→ agent 真生成策略（DS-2 注入 llm_client；本模块留 seam）。
  · 无 LLM → 按市场套**确定性模板**（动量/趋势），读真样本产真净值——脊梁兜底，不依赖 LLM。

【诚实纪律 §3】两条都必须读真捆绑样本（sample_data.SAMPLE_REL）跑真回测；绝不合成假数据冒充。
生成码确定性（同 goal+market+lookback → 同码 → 同 config_hash → ledger 不重刷 honest-N）。
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template

from .sample_data import SAMPLE_BENCHMARK, sample_rel

# 起步样本数据版本（进 config_hash；样本内容变了才 bump，保证同 goal 重跑哈希稳定）。
SAMPLE_DATASET_VERSION = "delivery-slice-sample-v1"

# asset_class（StrategyGoal）→ market（emit_result.metadata.market 取值域）。
_ASSET_TO_MARKET: dict[str, str] = {
    "equity_cn": "stocks_cn",
    "crypto_perp": "crypto_perp",
    "crypto_spot": "crypto_spot",
    "stocks_cn": "stocks_cn",  # 已是 market 形态时幂等
    "crypto": "crypto_perp",
}

_VALID_MARKETS = {"stocks_cn", "crypto_perp", "crypto_spot"}


def normalize_market(raw: str | None) -> str:
    """把 asset_class / market 各种写法归一到 emit_result.metadata.market 取值域。

    缺省/无法识别 → crypto_perp（起步样本里 BTC 永远可用，stocks_cn 需先捆 Tushare 样本）。
    """
    if not raw:
        return "crypto_perp"
    key = str(raw).strip().lower()
    if key in _VALID_MARKETS:
        return key
    return _ASSET_TO_MARKET.get(key, "crypto_perp")


@dataclass(frozen=True)
class SynthResult:
    code: str
    market: str
    benchmark: str
    strategy_name: str
    method: str           # "template" | "llm"
    dataset_version: str
    lookback: int


# string.Template（$-占位）避免与生成码里大量 {} 冲突。
# 用 stdlib csv 读样本（**不用 polars.read_csv**：沙箱锁了 socket/asyncio，polars 读字符串路径会走
# fsspec→asyncio→socket 被拦；csv 是纯 stdlib、在锁定沙箱里稳）。
_TEMPLATE = Template(
    '"""$strategy_name（DS-1 合成 · $market 动量基线）。"""\n'
    "import os\n"
    "import csv\n"
    "\n"
    "# 读后端注入的真行情样本（DATA_DIR=DATA_ROOT；样本由 sample_data 捆绑，真 OHLCV 非合成）。\n"
    'DATA_DIR = os.environ["DATA_DIR"]\n'
    "_rows = []\n"
    'with open(f"{DATA_DIR}/$sample_rel", newline="") as _f:\n'
    "    for _r in csv.DictReader(_f):\n"
    "        _rows.append(_r)\n"
    '_rows.sort(key=lambda r: r["timestamp"])\n'
    'ts = [str(r["timestamp"]) for r in _rows]\n'
    'close = [float(r["close"]) for r in _rows]\n'
    "\n"
    "LOOKBACK = $lookback\n"
    "equity = 1.0\n"
    "equity_curve = []\n"
    "for i in range(len(close)):\n"
    "    if i == 0:\n"
    '        equity_curve.append({"t": ts[0], "equity": 1.0, "net_return": 0.0, "benchmark_return": 0.0})\n'
    "        continue\n"
    "    prev = close[i - 1]\n"
    "    daily_ret = (close[i] / prev - 1.0) if prev else 0.0\n"
    "    # 仅用昨日及更早信息定仓（无前视）：昨收 > LOOKBACK 日前收 → 持有，否则空仓。\n"
    "    pos = 1 if (i - 1 - LOOKBACK >= 0 and close[i - 1] > close[i - 1 - LOOKBACK]) else 0\n"
    "    strat_ret = pos * daily_ret\n"
    "    equity *= (1.0 + strat_ret)\n"
    "    equity_curve.append({\n"
    '        "t": ts[i],\n'
    '        "equity": round(equity, 8),\n'
    '        "net_return": round(strat_ret, 8),\n'
    '        "benchmark_return": round(daily_ret, 8),\n'
    "    })\n"
    "\n"
    "quantbt.emit_result({\n"
    '    "equity_curve": equity_curve,\n'
    '    "trades": [],\n'
    '    "metadata": {\n'
    '        "strategy_name": "$strategy_name",\n'
    '        "market": "$market",\n'
    '        "frequency": "1d",\n'
    '        "benchmark": "$benchmark",\n'
    '        "research_theme_id": "$goal_ref",\n'
    '        "factor_formula": "momentum_$lookback",\n'
    '        "params": {"lookback": $lookback},\n'
    '        "dataset_version": "$dataset_version",\n'
    '        "label": "net_return",\n'
    "    },\n"
    "})\n"
)


def _template_code(
    *, market: str, strategy_name: str, benchmark: str, goal_ref: str, lookback: int
) -> str:
    return _TEMPLATE.substitute(
        strategy_name=_sanitize(strategy_name),
        market=market,
        sample_rel=sample_rel(market),
        benchmark=_sanitize(benchmark),
        goal_ref=_sanitize(goal_ref),
        lookback=int(lookback),
        dataset_version=SAMPLE_DATASET_VERSION,
    )


def _sanitize(s: str) -> str:
    """挡住会破坏生成码字符串字面量的字符（引号/换行/反斜杠）——防注入、防语法破坏。"""
    return (
        str(s)
        .replace("\\", "")
        .replace('"', "'")
        .replace("\n", " ")
        .replace("\r", " ")
        .strip()
    )[:120] or "strategy"


def synthesize_strategy_code(
    *,
    market: str | None = None,
    asset_class: str | None = None,
    strategy_name: str | None = None,
    benchmark: str | None = None,
    strategy_goal_ref: str | None = None,
    lookback: int = 20,
    llm_client: object | None = None,
) -> SynthResult:
    """从对话意图合成最小可跑策略 Python（有 LLM 真生成 / 无 LLM 套模板）。

    返回 SynthResult；调用方拿 .code 喂 sandbox.run_user_strategy。
    """

    mkt = normalize_market(market or asset_class)
    bench = _sanitize(benchmark) if benchmark else SAMPLE_BENCHMARK.get(mkt, "BTC-USDT")
    name = _sanitize(strategy_name) if strategy_name else f"{mkt} 动量基线 v1"
    goal_ref = _sanitize(strategy_goal_ref) if strategy_goal_ref else name
    lb = int(lookback) if isinstance(lookback, int) and lookback > 0 else 20

    # —— LLM 路（DS-2 注入 llm_client；本模块只留经验证的 seam，失败兜底模板）——
    if llm_client is not None:
        code = _llm_code(
            llm_client, market=mkt, strategy_name=name, benchmark=bench, lookback=lb
        )
        if code is not None:
            return SynthResult(
                code=code, market=mkt, benchmark=bench, strategy_name=name,
                method="llm", dataset_version=SAMPLE_DATASET_VERSION, lookback=lb,
            )

    code = _template_code(
        market=mkt, strategy_name=name, benchmark=bench, goal_ref=goal_ref, lookback=lb
    )
    return SynthResult(
        code=code, market=mkt, benchmark=bench, strategy_name=name,
        method="template", dataset_version=SAMPLE_DATASET_VERSION, lookback=lb,
    )


def _llm_code(
    llm_client: object, *, market: str, strategy_name: str, benchmark: str, lookback: int
) -> str | None:
    """让 LLM 生成策略码；必须含 emit_result + 读 DATA_DIR，否则判废返 None（兜底模板）。

    seam 设计：llm_client 须有 `complete(prompt) -> str`（QuantBT LLM 客户端契约）。任何异常 / 不合
    格式 → 返 None，调用方落模板。**绝不**把不含 emit_result 的输出当回测（防假绿灯）。
    """

    prompt = (
        f"写一个 {market} 市场、{strategy_name} 的最小日频策略 Python。"
        f"要求：用 `import os, csv` 读 `os.environ['DATA_DIR']` 下的 `{sample_rel(market)}`（列 timestamp/open/high/low/close/volume；"
        f"沙箱锁了 socket/asyncio，**不要用 polars/pandas.read_csv 读路径**，用 stdlib csv.DictReader）；"
        f"维护 equity_curve（list of dict，键 t/equity/net_return/benchmark_return），benchmark_return 用买入持有日收益；"
        f"无前视（仓位只用昨日及更早信息，lookback={lookback}）；"
        f"末尾必须调用 `quantbt.emit_result({{...}})`，metadata 含 market='{market}'/frequency='1d'/benchmark='{benchmark}'。"
        f"只输出 Python 代码，不要解释。"
    )
    try:
        complete = getattr(llm_client, "complete", None)
        if complete is None:
            return None
        raw = complete(prompt)
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(raw, str):
        return None
    code = _strip_code_fence(raw)
    # 硬校验：必须读 DATA_DIR + 调 emit_result，否则不是真回测码（§3 防假绿灯）。
    if "emit_result" not in code or "DATA_DIR" not in code:
        return None
    return code


def _strip_code_fence(raw: str) -> str:
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        # 去首行 ```lang 与末行 ```
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        s = "\n".join(lines)
    return s.strip()


__all__ = [
    "SynthResult",
    "SAMPLE_DATASET_VERSION",
    "normalize_market",
    "synthesize_strategy_code",
]
