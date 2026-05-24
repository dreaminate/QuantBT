# Domain Model

status: pending_review

review_status: 0

confirmed_by:

confirmed_at:

## Core Objects

| 对象 | 说明 | 关键字段 |
|---|---|---|
| MarketDataset | 一个可复现的数据集切片 | market、data_kind、interval、symbols、start、end、path、version |
| FeatureSet | 从数据集生成的一组特征 | feature_set_id、inputs、feature_names、windows、code_ref |
| ModelRun | 一次模型训练或推理 | model_id、model_version、inputs、output_schema、metrics |
| DecisionSnapshot | 标准决策接口实例 | timestamp、symbol、expected_return、probability、volatility、tail_risk、confidence、regime |
| OptimizerRun | 一次优化决策 | optimizer_id、objective、constraints、inputs、positions |
| RiskDecision | 风控层输出 | allowed、reasons、limits、overrides |
| BacktestRun | 一次回测实验 | run_id、config_snapshot、data_dependencies、metrics、artifacts |
| ResearchTask | 一个可验收平台能力 | task_id、version、layer、inputs、outputs、acceptance |

## Layer Boundaries

```text
MarketDataset
  -> FeatureSet
  -> ModelRun / RuleSignal
  -> DecisionSnapshot
  -> OptimizerRun
  -> RiskDecision
  -> BacktestRun
  -> Artifact / Web Detail / Notebook
```

## Standard Decision Interface

标准决策对象应优先包含：

- `timestamp`
- `symbol`
- `side_hint`
- `expected_return`
- `up_probability`
- `down_probability`
- `forecast_interval`
- `volatility_forecast`
- `tail_risk`
- `confidence`
- `regime_label`
- `scenario_ref`
- `feature_set_id`
- `model_ref`

字段可为空，但任务必须说明为空原因。优化器只能依赖声明过的字段。

## Existing Artifact Contract

现有 Web 和 Notebook 已读取 `data/artifacts/experiments/{run_id}/`。新研究流程优先复用该协议，除非任务卡明确引入新 artifact 并说明迁移策略。
