"""生成 docs/model_cards/*.md（模型卡 bootstrap）。

集中维护各模型结构化数据 → 渲染成 markdown(frontmatter + L1-L4)。
生成后 md 即 catalog 的 source of truth（可手工/GPT-Pro 续填）。重跑会覆盖同名卡。

用法：python scripts/gen_model_cards.py
"""

from __future__ import annotations

from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parents[1] / "docs" / "model_cards"


def P(type_: str, default, lo=None, hi=None, help_: str = "") -> dict:
    d: dict = {"type": type_, "default": default, "help": help_}
    if lo is not None:
        d["min"] = lo
    if hi is not None:
        d["max"] = hi
    return d


# 公共超参块
_SEQ = {
    "max_epochs": P("int", 20, 1, 500, "训练轮数（demo 用小值跑 CPU）"),
    "learning_rate": P("float", 1e-3, 1e-5, 1e-1, "学习率（先调）"),
    "batch_size": P("int", 64, 8, 1024, "批大小"),
    "lookback": P("int", 20, 5, 120, "回看窗口长度（贴预测视野）"),
    "dropout": P("float", 0.1, 0.0, 0.6, "dropout 正则"),
}
ML_PERSIST = "model.pkl（pickle/joblib）；reload→.predict；注意 pin 库版本避免跨版本反序列化失败。"
DL_PERSIST = "model.pt（state_dict + arch config）；reload 按 config 重建网络再 load_state_dict。"

MODELS: list[dict] = [
    # ========================= ML =========================
    dict(
        key="lgbm", family="ml", display_name="LightGBM", tasks=["classification", "regression", "lambdarank"],
        runnable=True, compute="cpu", requires_import="lightgbm",
        description="梯度提升树（leaf-wise）。默认主力模型，速度快、表格/截面数据强基线。",
        pros=["训练快、内存省", "表格/截面数据强基线", "原生处理缺失值与类别", "特征重要度可解释", "支持排序任务(lambdarank)"],
        cons=["小样本高噪声易过拟合（量化收益预测正是如此）", "不建模时序依赖", "num_leaves/depth 调不好易过拟合"],
        when_use="横截面选股打分、中低频、特征已工程化；需要排序(lambdarank)时首选。",
        when_avoid="原始序列直接喂（交给 LSTM/TFT）、极小样本。",
        tuning_tip="先 n_estimators 设高 + 早停；再调 learning_rate(0.01–0.1) 与 num_leaves(7–255) 定容量；过拟合看 train-val 裂口 + PBO。",
        data_req="无需标准化；NaN 原生处理；截面对齐；样本越多越稳。",
        eval_charts=["特征重要度(gain)", "ROC/PR(分类)", "预测-实际/残差(回归)", "分fold IC"],
        default_params={"n_estimators": 100, "learning_rate": 0.05, "num_leaves": 31},
        param_schema={
            "n_estimators": P("int", 100, 10, 2000, "树的数量"),
            "learning_rate": P("float", 0.05, 0.001, 0.5, "学习率"),
            "num_leaves": P("int", 31, 7, 255, "叶子数（控复杂度）"),
            "max_depth": P("int", -1, -1, 32, "树深，-1 不限"),
        },
        related=["xgboost", "catboost"],
    ),
    dict(
        key="xgboost", family="ml", display_name="XGBoost", tasks=["classification", "regression"],
        runnable=True, compute="cpu", requires_import="xgboost",
        description="梯度提升树（level-wise）。与 LightGBM 互为对照，正则更强。排序任务暂交给 LightGBM。",
        pros=["正则手段多（gamma/min_child_weight/L1L2）抗过拟合可控", "截面特征上开箱即强", "原生处理缺失值", "确定性好（固定 seed）"],
        cons=["超参多、调不好易翻车", "不建模时序", "类别极不平衡需调 scale_pos_weight"],
        when_use="横截面选股、与 LightGBM 做模型对照、需要更强正则时。",
        when_avoid="原始序列、极小样本。",
        tuning_tip="①n_estimators 高 + 早停 → ②定容量(learning_rate + max_depth 3–8) → ③抗过拟合(subsample/colsample 0.7–0.9) → ④精修(min_child_weight/gamma/reg_lambda)。",
        data_req="无需标准化；NaN 原生处理；截面对齐。",
        eval_charts=["特征重要度(gain)", "ROC/PR(分类)", "预测-实际/残差(回归)", "分fold IC"],
        default_params={"n_estimators": 200, "learning_rate": 0.05, "max_depth": 6},
        param_schema={
            "n_estimators": P("int", 200, 10, 2000, "树的数量"),
            "learning_rate": P("float", 0.05, 0.001, 0.5, "学习率"),
            "max_depth": P("int", 6, 1, 16, "树深"),
            "subsample": P("float", 1.0, 0.3, 1.0, "行采样比例"),
            "colsample_bytree": P("float", 1.0, 0.3, 1.0, "列采样比例"),
        },
        related=["lgbm", "catboost"],
    ),
    dict(
        key="catboost", family="ml", display_name="CatBoost", tasks=["classification", "regression"],
        runnable=True, compute="cpu", requires_import="catboost",
        description="梯度提升树（ordered boosting + 对称树）。对类别特征友好、默认参数就很稳，抗过拟合好。",
        pros=["默认参数即强、调参负担小", "ordered boosting 抗过拟合（小样本友好）", "对类别特征原生支持", "确定性好"],
        cons=["训练比 LGBM 慢", "模型体积大", "极大数据上不如 LGBM 快"],
        when_use="小到中样本、想少调参拿稳基线、类别特征多。",
        when_avoid="超大数据要极致速度（用 LGBM）。",
        tuning_tip="多数情况默认即可；要调先 depth(4–10) + learning_rate(0.03–0.1) + l2_leaf_reg(1–10)；iterations 高 + 早停。",
        data_req="无需标准化；NaN/类别原生处理。",
        eval_charts=["特征重要度", "ROC/PR(分类)", "预测-实际/残差(回归)"],
        default_params={"iterations": 300, "learning_rate": 0.05, "depth": 6},
        param_schema={
            "iterations": P("int", 300, 50, 3000, "迭代次数"),
            "learning_rate": P("float", 0.05, 0.005, 0.3, "学习率"),
            "depth": P("int", 6, 3, 12, "对称树深度"),
            "l2_leaf_reg": P("float", 3.0, 1.0, 30.0, "L2 正则"),
        },
        related=["lgbm", "xgboost"],
    ),
    dict(
        key="sklearn_rf", family="ml", display_name="随机森林", tasks=["classification", "regression"],
        runnable=True, compute="cpu", requires_import="sklearn",
        description="Bagging 决策树集成。抗过拟合稳健基线，几乎不用调参。",
        pros=["几乎不用调参、稳健", "抗过拟合（bagging 平均）", "可并行、可解释重要度"],
        cons=["精度通常不如 GBDT", "外推能力弱（树模型通病）", "模型大、预测慢"],
        when_use="想要零调参的稳健对照基线。",
        when_avoid="追求最高精度（用 GBDT）、需外推。",
        tuning_tip="n_estimators 越多越稳（100–500）；max_depth/min_samples_leaf 控过拟合；通常默认即可。",
        data_req="无需标准化；NaN 需先处理。",
        eval_charts=["特征重要度", "ROC/PR", "预测-实际/残差"],
        default_params={"n_estimators": 100},
        param_schema={
            "n_estimators": P("int", 100, 10, 1000, "树的数量"),
            "max_depth": P("int", 0, 0, 64, "树深，0 不限"),
            "min_samples_leaf": P("int", 1, 1, 50, "叶最小样本"),
        },
        related=["extra_trees", "lgbm"],
    ),
    dict(
        key="extra_trees", family="ml", display_name="极端随机树", tasks=["classification", "regression"],
        runnable=True, compute="cpu", requires_import="sklearn",
        description="Extra-Trees：分裂阈值也随机，比随机森林方差更低、更快。",
        pros=["比 RF 更快、方差更低", "抗过拟合", "零调参可用"],
        cons=["偏差可能略高", "精度一般不及 GBDT", "外推弱"],
        when_use="想要比 RF 更快的稳健基线。",
        when_avoid="追求最高精度。",
        tuning_tip="同随机森林：n_estimators 多即可；max_depth/min_samples_leaf 控过拟合。",
        data_req="无需标准化；NaN 需先处理。",
        eval_charts=["特征重要度", "ROC/PR", "预测-实际/残差"],
        default_params={"n_estimators": 200},
        param_schema={
            "n_estimators": P("int", 200, 10, 1000, "树的数量"),
            "max_depth": P("int", 0, 0, 64, "树深，0 不限"),
            "min_samples_leaf": P("int", 1, 1, 50, "叶最小样本"),
        },
        related=["sklearn_rf"],
    ),
    dict(
        key="sklearn_logreg", family="ml", display_name="逻辑回归", tasks=["classification"],
        runnable=True, compute="cpu", requires_import="sklearn",
        description="线性分类基线，可解释、训练快。用于对照复杂模型是否真有增益。",
        pros=["可解释（系数即权重）", "训练快、稳定", "概率输出校准好"],
        cons=["只能线性边界", "需特征标准化", "对共线性敏感"],
        when_use="二分类基线、要可解释、对照复杂模型。",
        when_avoid="强非线性关系。",
        tuning_tip="主要调 C（正则强度倒数，0.01–10）；特征先标准化；类别不平衡用 class_weight。",
        data_req="建议标准化；NaN 需先处理。",
        eval_charts=["ROC/PR", "混淆矩阵", "系数权重"],
        default_params={"C": 1.0, "max_iter": 300},
        param_schema={
            "C": P("float", 1.0, 0.001, 100.0, "正则强度倒数"),
            "max_iter": P("int", 300, 50, 5000, "最大迭代"),
        },
        related=["ridge", "elastic_net"],
    ),
    dict(
        key="ridge", family="ml", display_name="岭回归", tasks=["regression"],
        runnable=True, compute="cpu", requires_import="sklearn",
        description="L2 正则线性回归。共线性下稳定的可解释基线。",
        pros=["共线性下稳定", "可解释、训练极快", "闭式解、无随机性"],
        cons=["只能线性", "不做特征选择（系数不为0）", "需标准化"],
        when_use="线性回归基线、特征共线性强。",
        when_avoid="需稀疏/特征选择（用 Lasso）、强非线性。",
        tuning_tip="只调 alpha（L2 强度，0.01–100）；特征务必标准化。",
        data_req="必须标准化；NaN 需先处理。",
        eval_charts=["预测-实际/残差", "系数权重"],
        default_params={"alpha": 1.0},
        param_schema={"alpha": P("float", 1.0, 0.001, 100.0, "L2 正则强度")},
        related=["lasso", "elastic_net"],
    ),
    dict(
        key="lasso", family="ml", display_name="Lasso 回归", tasks=["regression"],
        runnable=True, compute="cpu", requires_import="sklearn",
        description="L1 正则线性回归。自动特征选择（稀疏系数）。",
        pros=["自动特征选择（稀疏）", "可解释", "高维下抗过拟合"],
        cons=["共线性下选择不稳定", "只能线性", "需标准化"],
        when_use="高维特征想自动筛选、要稀疏可解释模型。",
        when_avoid="特征强共线（用 ElasticNet）。",
        tuning_tip="调 alpha（越大越稀疏，0.0001–1）；特征标准化。",
        data_req="必须标准化；NaN 需先处理。",
        eval_charts=["预测-实际/残差", "非零系数"],
        default_params={"alpha": 0.001},
        param_schema={"alpha": P("float", 0.001, 0.00001, 1.0, "L1 正则强度")},
        related=["ridge", "elastic_net"],
    ),
    dict(
        key="elastic_net", family="ml", display_name="ElasticNet", tasks=["regression"],
        runnable=True, compute="cpu", requires_import="sklearn",
        description="L1+L2 混合正则线性回归。兼顾稀疏与共线性稳定。",
        pros=["兼顾特征选择与共线性稳定", "高维稳健", "可解释"],
        cons=["多一个 l1_ratio 要调", "只能线性", "需标准化"],
        when_use="高维 + 共线性特征的线性基线。",
        when_avoid="强非线性。",
        tuning_tip="调 alpha（总强度）+ l1_ratio（0=岭，1=Lasso，常 0.5）；特征标准化。",
        data_req="必须标准化；NaN 需先处理。",
        eval_charts=["预测-实际/残差", "系数权重"],
        default_params={"alpha": 0.001, "l1_ratio": 0.5},
        param_schema={
            "alpha": P("float", 0.001, 0.00001, 1.0, "总正则强度"),
            "l1_ratio": P("float", 0.5, 0.0, 1.0, "L1 占比(0岭/1Lasso)"),
        },
        related=["ridge", "lasso"],
    ),
    # ========================= DL（已实现 runnable=True）=========================
    dict(
        key="lstm", family="dl", display_name="LSTM 序列模型", tasks=["regression", "classification", "forecasting"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="LSTM 序列回归/分类（纯 torch 自实现）。建模时序依赖，DL 入门基线。",
        pros=["建模时序依赖/记忆", "比 TFT 轻、上手快", "原始序列可直接喂"],
        cons=["需较多数据、易过拟合金融噪声", "训练慢、GPU 更顺", "可解释性弱、对非平稳敏感"],
        when_use="单/多标的时序，有足够历史，想建模时间依赖。",
        when_avoid="纯截面、小样本（用 GBDT）。",
        tuning_tip="lr 先调(1e-3)→ hidden_size/num_layers 定容量 → lookback 贴预测视野 → dropout 正则；按 symbol 分组建窗防串味；早停看 val_loss。",
        data_req="需足够长序列；特征建议标准化；按 symbol 分组建窗。",
        eval_charts=["学习曲线(train/val loss)", "预测-实际/残差", "TensorBoard 训练过程"],
        default_params={"hidden_size": 32, "num_layers": 1, "dropout": 0.1, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 20},
        param_schema={
            "hidden_size": P("int", 32, 8, 256, "隐藏维度"),
            "num_layers": P("int", 1, 1, 4, "LSTM 层数"),
            **_SEQ,
        },
        related=["gru", "alstm", "tcn"],
    ),
    dict(
        key="gru", family="dl", display_name="GRU 序列模型", tasks=["regression", "classification", "forecasting"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="GRU 序列模型（纯 torch）。比 LSTM 参数少、训练略快，效果常相近。",
        pros=["比 LSTM 轻、收敛常更快", "建模时序依赖", "原始序列直接喂"],
        cons=["长依赖略弱于 LSTM", "仍需较多数据、易过拟合", "可解释性弱"],
        when_use="时序建模、想要比 LSTM 更省的选择。",
        when_avoid="纯截面、小样本。",
        tuning_tip="同 LSTM：lr 先调 → hidden_size/num_layers 定容量 → lookback → dropout；早停看 val_loss。",
        data_req="需足够长序列；特征标准化；按 symbol 分组建窗。",
        eval_charts=["学习曲线", "预测-实际/残差", "TensorBoard"],
        default_params={"hidden_size": 32, "num_layers": 1, "dropout": 0.1, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 20},
        param_schema={"hidden_size": P("int", 32, 8, 256, "隐藏维度"), "num_layers": P("int", 1, 1, 4, "GRU 层数"), **_SEQ},
        related=["lstm", "alstm"],
    ),
    dict(
        key="alstm", family="dl", display_name="Attention-LSTM", tasks=["regression", "forecasting"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="注意力 LSTM（qlib 风）：对时间步做注意力加权汇聚再预测，比普通 LSTM 更会抓关键时刻。",
        pros=["注意力聚焦关键时间步", "常优于普通 LSTM", "注意力权重略可解释"],
        cons=["比 LSTM 重一点", "仍需较多数据", "易过拟合金融噪声"],
        when_use="时序建模、关键信息集中在某些时间点。",
        when_avoid="纯截面、小样本。",
        tuning_tip="同 LSTM；注意力让模型更敏感，dropout/早停更重要。",
        data_req="需足够长序列；特征标准化；按 symbol 分组。",
        eval_charts=["学习曲线", "注意力权重", "预测-实际", "TensorBoard"],
        default_params={"hidden_size": 32, "num_layers": 1, "dropout": 0.1, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 20},
        param_schema={"hidden_size": P("int", 32, 8, 256, "隐藏维度"), "num_layers": P("int", 1, 1, 4, "LSTM 层数"), **_SEQ},
        related=["lstm", "transformer"],
    ),
    dict(
        key="mlp", family="dl", display_name="MLP（多层感知机）", tasks=["regression", "classification"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="把回看窗摊平喂全连接网络（纯 torch）。不建模时序顺序，作 DL 基线/对照。",
        pros=["简单、训练快", "可吃任意特征", "DL 入门对照"],
        cons=["不建模时序顺序（摊平）", "对噪声敏感", "可解释性弱"],
        when_use="DL 基线对照、特征本身已含时序信息。",
        when_avoid="强时序依赖（用 LSTM/TCN）。",
        tuning_tip="lr 先调 → hidden_size/dropout 控容量；lookback 小一点即可；早停。",
        data_req="特征标准化；lookback 摊平。",
        eval_charts=["学习曲线", "预测-实际/残差", "TensorBoard"],
        default_params={"hidden_size": 64, "dropout": 0.1, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 20},
        param_schema={"hidden_size": P("int", 64, 16, 512, "隐藏维度"), **_SEQ},
        related=["lstm"],
    ),
    dict(
        key="tcn", family="dl", display_name="TCN 时序卷积", tasks=["regression", "forecasting"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="因果膨胀卷积网络（纯 torch）。并行训练快，长感受野，时序强基线。",
        pros=["并行快（卷积）", "膨胀卷积长感受野", "训练稳定、梯度好"],
        cons=["感受野受层数/核限制", "需调结构", "需较多数据"],
        when_use="时序建模、想要比 RNN 快且稳定。",
        when_avoid="纯截面、小样本。",
        tuning_tip="num_layers 决定感受野(2^L)；kernel_size 3–5；lr 先调；dropout 正则；早停。",
        data_req="需足够长序列；特征标准化；按 symbol 分组。",
        eval_charts=["学习曲线", "预测-实际/残差", "TensorBoard"],
        default_params={"hidden_size": 32, "num_layers": 2, "kernel_size": 3, "dropout": 0.1, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 20},
        param_schema={
            "hidden_size": P("int", 32, 8, 256, "通道数"),
            "num_layers": P("int", 2, 1, 6, "卷积层数(感受野 2^L)"),
            "kernel_size": P("int", 3, 2, 7, "卷积核"),
            **_SEQ,
        },
        related=["lstm", "transformer"],
    ),
    dict(
        key="transformer", family="dl", display_name="Transformer 编码器", tasks=["regression", "forecasting"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="自注意力编码器（纯 torch）。全局依赖建模强，数据足时上限高。",
        pros=["自注意力捕捉全局依赖", "并行训练", "数据足时上限高"],
        cons=["数据需求最大、最易过拟合", "训练最重、强烈需 GPU", "超参敏感"],
        when_use="数据充足的时序、需要全局依赖建模。",
        when_avoid="小样本（必过拟合）、纯截面。",
        tuning_tip="n_heads 整除 hidden_size；lr 小(1e-3~1e-4)+warmup 心态；dropout 大些；早停严格；务必 Purged 切分。",
        data_req="数据量需求大；特征标准化；按 symbol 分组。",
        eval_charts=["学习曲线", "注意力图", "预测-实际", "TensorBoard"],
        default_params={"hidden_size": 32, "num_layers": 2, "n_heads": 4, "dropout": 0.1, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 20},
        param_schema={
            "hidden_size": P("int", 32, 16, 256, "模型维度(需被 n_heads 整除)"),
            "num_layers": P("int", 2, 1, 6, "编码层数"),
            "n_heads": P("int", 4, 1, 8, "注意力头数"),
            **_SEQ,
        },
        related=["alstm", "tft"],
    ),
    # ========================= DL（高级时序，纯 torch 已实现 runnable=True）=========================
    dict(
        key="tft", family="dl", display_name="TFT 时序融合 Transformer", tasks=["regression", "forecasting"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="Temporal Fusion Transformer：变量选择 + 门控残差 + 可解释多头注意力，多标的多特征时序的强模型。",
        pros=["变量选择网络可解释特征贡献", "建模多变量+长短期依赖", "多步预测强、带分位数"],
        cons=["数据量需求大、易过拟合", "训练最慢、必需 GPU", "结构复杂、超参多"],
        when_use="多标的多特征时序、需要可解释贡献与多步预测。",
        when_avoid="小样本、想快速出基线。",
        tuning_tip="hidden_size/attention_head_size 定容量；lr 1e-3；dropout 正则；early stop；Purged 切分防泄露。",
        data_req="数据量需求大；多特征；按 symbol 分组。",
        eval_charts=["学习曲线", "变量选择权重", "分位数预测", "TensorBoard"],
        default_params={"hidden_size": 32, "lstm_layers": 1, "attention_head_size": 4, "dropout": 0.1, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 20},
        param_schema={
            "hidden_size": P("int", 32, 8, 256, "隐藏维度"),
            "lstm_layers": P("int", 1, 1, 4, "LSTM 层数"),
            "attention_head_size": P("int", 4, 1, 8, "注意力头数"),
            **_SEQ,
        },
        related=["transformer", "alstm"],
    ),
    dict(
        key="nbeats", family="dl", display_name="N-BEATS", tasks=["regression", "forecasting"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="纯前馈残差堆叠的时序预测网络，可分解趋势/季节。单变量预测强。",
        pros=["单变量预测 SOTA 级", "趋势/季节可分解可解释", "不需循环、训练快"],
        cons=["原版偏单变量", "协变量支持需扩展", "需较多数据"],
        when_use="单序列多步预测、要可分解解释。",
        when_avoid="强多变量交互（用 TFT）。",
        tuning_tip="num_blocks/hidden_size 定容量；lookback 取预测长度数倍；early stop。",
        data_req="单变量序列为主；足够历史。",
        eval_charts=["学习曲线", "趋势/季节分解", "预测-实际"],
        default_params={"hidden_size": 64, "num_blocks": 3, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 20},
        param_schema={"hidden_size": P("int", 64, 16, 512, "隐藏维度"), "num_blocks": P("int", 3, 1, 8, "残差块数"), **_SEQ},
        related=["nhits", "tft"],
    ),
    dict(
        key="nhits", family="dl", display_name="N-HiTS", tasks=["regression", "forecasting"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="N-BEATS 的多尺度升级：分层池化 + 多频率，长程预测更快更准。",
        pros=["长程预测准、比 N-BEATS 省算力", "多尺度分层", "训练快"],
        cons=["单变量为主", "实现较复杂", "需较多数据"],
        when_use="长程多步预测。",
        when_avoid="强多变量交互。",
        tuning_tip="hidden_size 定容量；lookback 取长一些以利多尺度池化；early stop。",
        data_req="单变量为主；长历史。",
        eval_charts=["学习曲线", "多尺度分解", "预测-实际"],
        default_params={"hidden_size": 64, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 30},
        param_schema={"hidden_size": P("int", 64, 16, 512, "隐藏维度"), **_SEQ, "lookback": P("int", 30, 5, 200, "回看窗口")},
        related=["nbeats"],
    ),
    dict(
        key="deepar", family="dl", display_name="DeepAR", tasks=["regression", "forecasting"],
        runnable=True, compute="gpu", tensorboard=True, requires_import="torch",
        description="自回归 RNN 概率预测：LSTM 输出 μ/σ 分布参数（点预测用 μ，σ 头保留供区间预测），适合带不确定性的多序列预测。",
        pros=["概率预测（给区间/分位数）", "多序列联合学习", "适合不确定性度量"],
        cons=["训练较慢", "需较多数据", "点估计未必优于判别模型"],
        when_use="需要预测区间/风险度量、多序列。",
        when_avoid="只要点估计且追求最高精度。",
        tuning_tip="hidden_size/num_layers 定容量；lr 1e-3；early stop。（当前实现点预测用 μ 头。）",
        data_req="多序列；足够历史。",
        eval_charts=["学习曲线", "预测区间", "覆盖率校准"],
        default_params={"hidden_size": 32, "num_layers": 1, "dropout": 0.1, "max_epochs": 20, "learning_rate": 1e-3, "batch_size": 64, "lookback": 20},
        param_schema={"hidden_size": P("int", 32, 8, 256, "隐藏维度"), "num_layers": P("int", 1, 1, 4, "LSTM 层数"), **_SEQ},
        related=["tft"],
    ),
]


def render(m: dict) -> str:
    fm = {
        "key": m["key"],
        "family": m["family"],
        "display_name": m["display_name"],
        "tasks": m["tasks"],
        "description": m["description"],
        "pros": m["pros"],
        "cons": m["cons"],
        "tuning_tip": m["tuning_tip"],
        "default_params": m["default_params"],
        "param_schema": m["param_schema"],
        "needs_dl": m["family"] == "dl",
        "tensorboard": m.get("tensorboard", False),
        "requires_import": m.get("requires_import"),
        "runnable": m["runnable"],
        "compute": m["compute"],
        "persistence": DL_PERSIST if m["family"] == "dl" else ML_PERSIST,
        "related": m.get("related", []),
    }
    front = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=100)
    rows = "\n".join(
        f"| `{k}` | {s.get('help','')} | {s['default']} | {s.get('min','-')}–{s.get('max','-')} |"
        for k, s in m["param_schema"].items()
    )
    pros = "\n".join(f"- {x}" for x in m["pros"])
    cons = "\n".join(f"- {x}" for x in m["cons"])
    charts = "、".join(m["eval_charts"])
    runnable_line = "✅ 已实现训练模板，可直接训练。" if m["runnable"] else "🟡 卡片已收录；训练模板排队中（加一个架构即可跑）。"
    body = f"""## L1 · 定位
{m['description']}

## L2 · 优缺点 & 适用
**✅ 优点**
{pros}

**⚠️ 缺点**
{cons}

**适用**：{m['when_use']}
**不适用**：{m['when_avoid']}

## L3 · 调参 & 数据要求
**调参策略**：{m['tuning_tip']}

| 超参 | 作用 | 默认 | 范围 |
|---|---|---|---|
{rows}

**数据要求**：{m['data_req']}

## L4 · 保存本体 & 评价
**保存本体**：{DL_PERSIST if m['family']=='dl' else ML_PERSIST}
**评价图**：{charts}
**算力**：{'GPU 推荐(cuda/mps)，CPU 可小规模' if m['compute']=='gpu' else 'CPU 即可'}
**可训练**：{runnable_line}
"""
    return f"---\n{front}---\n\n{body}"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for m in MODELS:
        (OUT / f"{m['key']}.md").write_text(render(m), encoding="utf-8")
    print(f"生成 {len(MODELS)} 张模型卡 → {OUT}")


if __name__ == "__main__":
    main()
