"""训练评价图数据源 —— 把训练 result 转成"图就绪"的序列。

训练台"训练结束自动画图评价"：本模块从 TrainResult(.to_dict / result.json) 算出
各评价图的数据（前端用内联 SVG 按回测详情页风格渲染，单图为主）。

产出 charts 列表，每项 {id, title, kind, ...data}：
- feature_importance  (bar)   特征重要度
- learning_curve      (line)  train/val loss（DL）
- pred_vs_actual      (scatter+line) 预测-实际（回归）
- residual            (scatter) 残差（回归）
- roc                 (line)  ROC 曲线（二分类，有 proba）
- fold_metrics        (bar)   分 fold 指标
"""

from __future__ import annotations

from typing import Any

import numpy as np


def _bar(id_: str, title: str, labels: list[str], values: list[float]) -> dict[str, Any]:
    return {"id": id_, "title": title, "kind": "bar", "labels": labels, "values": [float(v) for v in values]}


def _line(id_: str, title: str, series: list[dict[str, Any]], x: list[float] | None = None) -> dict[str, Any]:
    return {"id": id_, "title": title, "kind": "line", "x": x, "series": series}


def _scatter(id_: str, title: str, points: list[list[float]], *, ref_line: bool = False,
             x_label: str = "", y_label: str = "") -> dict[str, Any]:
    return {
        "id": id_, "title": title, "kind": "scatter", "points": points,
        "ref_line": ref_line, "x_label": x_label, "y_label": y_label,
    }


def _roc_curve(y_true: np.ndarray, y_score: np.ndarray) -> tuple[list[float], list[float], float]:
    """无 sklearn 依赖的 ROC + AUC（梯形法）。"""
    order = np.argsort(-y_score)
    yt = y_true[order]
    P = float(np.sum(yt == 1)) or 1.0
    N = float(np.sum(yt == 0)) or 1.0
    tps = np.cumsum(yt == 1)
    fps = np.cumsum(yt == 0)
    tpr = np.concatenate([[0.0], tps / P])
    fpr = np.concatenate([[0.0], fps / N])
    # np.trapz 在 NumPy 2.x 被移除 → 用 trapezoid（兼容老版本回退）
    _trap = getattr(np, "trapezoid", None) or np.trapz  # type: ignore[attr-defined]
    auc = float(_trap(tpr, fpr))
    return fpr.tolist(), tpr.tolist(), auc


def build_eval_charts(result: dict[str, Any]) -> list[dict[str, Any]]:
    """从训练 result dict 生成评价图列表。容错：缺数据的图自动跳过。"""
    charts: list[dict[str, Any]] = []

    # 1) 特征重要度
    fi = result.get("feature_importance")
    if isinstance(fi, dict) and fi:
        items = sorted(fi.items(), key=lambda kv: abs(kv[1]), reverse=True)[:30]
        charts.append(_bar("feature_importance", "特征重要度", [k for k, _ in items], [v for _, v in items]))

    # 2) 学习曲线（DL）
    curves = result.get("curves") or {}
    if curves.get("train_loss"):
        series = [{"name": "train_loss", "values": [float(v) for v in curves["train_loss"]]}]
        if curves.get("val_loss"):
            series.append({"name": "val_loss", "values": [float(v) for v in curves["val_loss"]]})
        charts.append(_line("learning_curve", "学习曲线（损失）", series))

    # 3) OOS 预测相关
    oos = result.get("oos_predictions") or {}
    y_true = oos.get("y_true")
    y_pred = oos.get("y_pred")
    task = (result.get("spec") or {}).get("task", "")
    if y_true and y_pred and len(y_true) == len(y_pred):
        yt = np.asarray(y_true, dtype=float)
        yp = np.asarray(y_pred, dtype=float)
        # 下采样到 ≤500 点，避免前端卡
        n = len(yt)
        idx = np.linspace(0, n - 1, min(n, 500)).astype(int)
        if task == "classification":
            proba = oos.get("y_proba")
            if proba and len(proba) == n and len(np.unique(yt)) == 2:
                fpr, tpr, auc = _roc_curve(yt, np.asarray(proba, dtype=float))
                charts.append(_line(
                    "roc", f"ROC 曲线 (AUC={auc:.3f})",
                    [{"name": "ROC", "values": tpr}, {"name": "随机", "values": fpr}], x=fpr,
                ))
        else:
            pts = [[float(yt[i]), float(yp[i])] for i in idx]
            charts.append(_scatter("pred_vs_actual", "预测 vs 实际", pts, ref_line=True, x_label="实际", y_label="预测"))
            resid_pts = [[float(yp[i]), float(yt[i] - yp[i])] for i in idx]
            charts.append(_scatter("residual", "残差图", resid_pts, x_label="预测", y_label="残差"))

    # 4) 分 fold 指标（树/线性 CV）
    folds = result.get("fold_metrics") or []
    if folds:
        # 选第一个数值型指标
        first_metrics = folds[0].get("metrics", {}) if isinstance(folds[0], dict) else {}
        metric_key = next((k for k, v in first_metrics.items() if isinstance(v, (int, float))), None)
        if metric_key:
            labels = [f"fold{f.get('fold_index', i)}" for i, f in enumerate(folds)]
            values = [float(f.get("metrics", {}).get(metric_key, 0.0)) for f in folds]
            charts.append(_bar("fold_metrics", f"分 fold · {metric_key}", labels, values))

    return charts


def summarize_metrics(result: dict[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in (result.get("oos_metrics") or {}).items() if isinstance(v, (int, float))}


__all__ = ["build_eval_charts", "summarize_metrics"]
