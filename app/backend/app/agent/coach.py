"""v0.8.6.1 · Mode 2 教练主动建议 + Socratic 响应决策 (W6 教练闭环)。

patch1 §D.d 5 步状态机的 SOCRATIC_DECISION 阶段在 backend 落实：
  response_mode: ask / explain / refuse / recommend_experiment

主动建议触发规则（基于 v0.8.4 risk_summary + 用户行为）：
  - PBO > 0.6  → "我帮你诊断这个高过拟合风险？"
  - DSR < 0.2  → "这个 Sharpe 真有效吗？我帮你查"
  - MaxDD > 25% → "回撤这么深，要不要看看仓位约束？"
  - Sharpe 1-2 + 无 walk-forward → "建议跑 walk-forward 验证"
  - 连续 3 次 rerun 同策略无指标改善 → "换个变量试试"

one-variable experiment 推荐：让用户改一个最小变量。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal


ResponseMode = Literal["ask", "explain", "refuse", "recommend_experiment"]


@dataclass
class CoachSuggestion:
    severity: Literal["info", "warning", "critical"]
    headline: str           # 8-20 字一句话
    detail: str             # 1-2 句说明
    suggested_chat_query: str  # 点入 chat 时自动填的 query
    related_glossary: list[str]  # 相关词条 slug
    one_variable_hint: str | None = None  # 推荐的下一步实验

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def suggest_from_risk_summary(risk_summary: dict[str, Any] | None) -> CoachSuggestion | None:
    """从 risk_summary 推断要不要主动建议；返 None 表示无需建议。"""

    if not risk_summary:
        return None
    trust = risk_summary.get("trust_level")
    flags = risk_summary.get("flags") or []
    if trust == "ok":
        return None

    # 找最高 severity 的 flag
    high = [f for f in flags if f.get("severity") == "high"]
    medium = [f for f in flags if f.get("severity") == "medium"]
    target = high[0] if high else (medium[0] if medium else None)
    if not target:
        if trust == "insufficient_data":
            return CoachSuggestion(
                severity="info",
                headline="你这次缺反过拟合证据，我帮你查？",
                detail="Sharpe 已有但缺 PBO/DSR。多次试验偏差没量化前，Sharpe 数值不可信。",
                suggested_chat_query="我这个策略只有 Sharpe 没有 PBO 和 DSR，怎么判断是否真有效？",
                related_glossary=["pbo", "deflated_sharpe"],
                one_variable_hint="先在 RunDetail 跑 PBO 和 DSR 计算，再决定下一步。",
            )
        return None

    name = target.get("name", "")
    message = target.get("message", "")

    # 按 flag 名分发
    mapping: dict[str, dict[str, Any]] = {
        "high_overfit_risk": {
            "severity": "critical",
            "headline": "PBO 偏高，我帮你诊断这个策略可信吗？",
            "detail": "CSCV 过拟合概率超出可接受阈值，建议跑 walk-forward 复测。",
            "suggested_chat_query": "这个策略 PBO 高于 0.6，怎么判断是不是过拟合？我下一步该怎么验证？",
            "related_glossary": ["pbo", "walk_forward", "purged_kfold"],
            "one_variable_hint": "把参数搜索次数从当前减半，重新跑一遍，看 PBO 是否下降。",
        },
        "low_dsr_confidence": {
            "severity": "critical",
            "headline": "DSR 低，这个 Sharpe 多半是运气",
            "detail": "试验次数偏差很大；当前 Sharpe 不能直接作为决策依据。",
            "suggested_chat_query": "我的 DSR 很低，怎么改善？要继续优化还是换思路？",
            "related_glossary": ["deflated_sharpe", "sharpe_ratio", "pbo"],
            "one_variable_hint": "把策略代码里所有 magic number 暴露为参数，统计真正试了多少次。",
        },
        "high_max_drawdown": {
            "severity": "warning",
            "headline": "回撤偏深，要不要看仓位约束？",
            "detail": "单次回测最大回撤超过 25%，资金曲线深度受伤。",
            "suggested_chat_query": "我的最大回撤太深了，应该加什么风控？",
            "related_glossary": ["max_drawdown", "kelly_fraction"],
            "one_variable_hint": "在策略里加单标的仓位上限 < 15%，重新跑一次。",
        },
        "low_sharpe": {
            "severity": "info",
            "headline": "Sharpe 偏低，我帮你想想？",
            "detail": "收益风险比偏低；可能因子方向不对，或标签设计有问题。",
            "suggested_chat_query": "我的 Sharpe 只有 {value:.2f}，你觉得最可能是哪个环节出了问题？",
            "related_glossary": ["sharpe_ratio", "ic", "triple_barrier"],
            "one_variable_hint": "尝试把 label horizon 从当前缩短一半（如从 20 日 → 10 日）。",
        },
        "low_factor_predictive": {
            "severity": "info",
            "headline": "因子预测能力不足",
            "detail": "IC-IR 偏低，因子稳定性不够，单期 IC 高也容易被噪声盖住。",
            "suggested_chat_query": "我的因子 IC-IR < 0.3，是该换因子还是改用更长 lookback？",
            "related_glossary": ["ic", "rank_ic", "ic_ir"],
            "one_variable_hint": "把因子计算窗口加长 50%（如 20 日 → 30 日），看 IC-IR 是否稳。",
        },
        "excessive_turnover": {
            "severity": "warning",
            "headline": "年化换手率太高，成本会吃掉收益",
            "detail": "Turnover > 300% 意味着每周都在换仓，交易成本对净收益侵蚀显著。",
            "suggested_chat_query": "我的策略换手率太高，怎么降低？",
            "related_glossary": ["slippage"],
            "one_variable_hint": "加 rebalance frequency limit（如每 5 日才能调仓一次）。",
        },
        "high_concentration": {
            "severity": "warning",
            "headline": "集中度过高，单标的占比超过 25%",
            "detail": "组合集中风险大；某一资产黑天鹅会拖崩整体。",
            "suggested_chat_query": "我的组合太集中了，怎么分散？",
            "related_glossary": ["hrp", "risk_parity"],
            "one_variable_hint": "在组合优化层加 max_single_weight=0.15 约束。",
        },
    }

    cfg = mapping.get(name, {
        "severity": "info",
        "headline": "这次结果有些信号，要不要让我看看？",
        "detail": message,
        "suggested_chat_query": f"我这次跑出来 {message}，你帮我看看下一步该怎么办",
        "related_glossary": [],
        "one_variable_hint": None,
    })
    return CoachSuggestion(**cfg)


def classify_response_mode(
    *,
    user_text: str,
    has_rag_hit: bool,
    market_mode: str,
    is_binance_live: bool,
) -> ResponseMode:
    """SOCRATIC_DECISION 状态机的简化版决策。

    用户问题 + 上下文 → response_mode。
    完整版在 Mode 2 chat 里由 LLM 决定，本函数提供 backend 提示给 system prompt。
    """

    text = user_text.lower().strip()

    # refuse 类（A股实盘 / 绕安全 / 保证收益）
    refuse_signals = [
        "a股实盘", "下单买入", "买入哪", "我该买", "推荐买",  # A股实盘
        "绕过", "跳过 safekey", "禁用 kill switch",            # 绕安全
        "保证", "稳赚", "肯定能赚", "100% 收益",                # 保证收益
    ]
    if any(s in text for s in refuse_signals):
        return "refuse"

    # Binance live 严格模式
    if is_binance_live and any(s in text for s in ["mainnet", "实盘", "真钱"]):
        return "refuse"

    # 问题特征：含问句 + 涉及指标名 → explain
    explain_signals = ["是什么", "什么意思", "解释", "为什么", "公式", "怎么算"]
    if any(s in text for s in explain_signals) and has_rag_hit:
        return "explain"

    # 含 "怎么改" / "下一步" / "试试" → recommend_experiment
    experiment_signals = ["怎么改", "下一步", "改进", "优化", "试试", "试一下"]
    if any(s in text for s in experiment_signals):
        return "recommend_experiment"

    # 默认：ask Socratic
    return "ask"


__all__ = ["CoachSuggestion", "ResponseMode", "classify_response_mode", "suggest_from_risk_summary"]
