/**
 * v0.8.4 Day 3 · RunDetail metric key → glossary term slug 映射。
 *
 * RunDetail 的 jq_overview_metrics 字段是 snake_case 实例（运行结果），
 * glossary 的 slug 是概念 ID（学术术语）。这张表是两者的 bridge。
 *
 * 缺失映射的字段（如 win_rate / profit_count）不显示 ⓘ ；map 中没有的 key
 * `getGlossarySlugForMetric` 返 null。
 *
 * 当 baseline 30 条 .md 还没全到位时，部分 slug 对应的词条会 404；
 * GlossaryInfoButton 处理这种情况显示 fallback。
 */

export const METRIC_GLOSSARY_MAP: Record<string, string> = {
  // 直接对应
  sharpe_ratio: "sharpe_ratio",
  sortino_ratio: "sortino_ratio",
  information_ratio: "information_ratio",
  max_drawdown: "max_drawdown",
  alpha: "alpha",
  beta: "beta",

  // 近义映射（同一概念的衍生指标→其原型）
  strategy_volatility: "volatility",
  benchmark_volatility: "volatility",
  excess_sharpe_ratio: "sharpe_ratio",
  excess_max_drawdown: "max_drawdown",
  max_drawdown_period: "max_drawdown",
  strategy_annual_return: "calmar_ratio", // 年化和 Calmar 同源思路

  // 暂无对应的指标，留空保持不显示 ⓘ：
  //   strategy_return / benchmark_return / excess_return  ← 这些是"事实数值"非概念
  //   win_rate / daily_win_rate / profit_count / loss_count / profit_loss_ratio
  //   avg_daily_excess_return
};

export function getGlossarySlugForMetric(metricKey: string): string | null {
  return METRIC_GLOSSARY_MAP[metricKey] ?? null;
}
