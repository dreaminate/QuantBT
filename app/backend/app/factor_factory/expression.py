"""M4 · 因子表达式引擎 (Python AST → polars Expr)。

支持例：
    rank(ts_corr(close, volume, 20))
    ts_zscore(close / ts_mean(close, 60), 20) * sign(ts_delta(close, 5))
    cs_demean(log(volume + 1))

字面量 (int/float/bool) 与列名都被识别。算子来自 `OPERATOR_REGISTRY`。

**重要约束**：横截面算子 (`cs_*` / `rank` / `zscore` / `cs_demean` /
`cs_winsorize` / `cs_quantile`) 必须出现在表达式的**最外层**（root
节点）；不允许嵌套在算术运算或时序算子里。原因：polars 当前不支持
同一表达式链中 `over("symbol")` → `over("ts")` 的双层 over，会全 null。
推荐写法：先把横截面外层结果物化，再做二次组合：
    f1 = rank(ts_mean(close, 5))
    f2 = sign(ts_delta(close, 5))
    final = f1 * f2  # 通过 join 而不是同一表达式
"""

from __future__ import annotations

import ast
from typing import Any

import polars as pl

from .operators import OPERATOR_REGISTRY


CS_OPERATORS: frozenset[str] = frozenset(
    {"cs_rank", "rank", "cs_zscore", "zscore", "cs_demean", "cs_winsorize", "cs_quantile"}
)


_BINOP_MAP = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a.pow(b) if hasattr(a, "pow") else a ** b,
}


_UNARYOP_MAP = {
    ast.USub: lambda a: -a,
    ast.UAdd: lambda a: +a,
}


class ExpressionError(ValueError):
    pass


def parse_expression(formula: str) -> ast.AST:
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"表达式语法错误: {exc}") from exc
    return tree.body


def compile_expression(formula: str, available_columns: set[str] | None = None) -> pl.Expr:
    """把表达式文本编译成单个 polars 表达式。

    Args:
        formula: 类似 ``rank(ts_corr(close, volume, 20))``。
        available_columns: 仅用于校验列名是否存在；None 表示不校验。
    """

    node = parse_expression(formula)
    return _eval_node(node, available_columns)


def _eval_node(node: ast.AST, columns: set[str] | None) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if columns is not None and node.id not in columns:
            raise ExpressionError(f"未知列或符号: {node.id}（已知列: {sorted(columns)[:10]}...）")
        return pl.col(node.id)
    if isinstance(node, ast.BinOp):
        a = _eval_node(node.left, columns)
        b = _eval_node(node.right, columns)
        op = _BINOP_MAP.get(type(node.op))
        if op is None:
            raise ExpressionError(f"不支持的二元运算: {type(node.op).__name__}")
        return op(a, b)
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, columns)
        op = _UNARYOP_MAP.get(type(node.op))
        if op is None:
            raise ExpressionError(f"不支持的一元运算: {type(node.op).__name__}")
        return op(operand)
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("仅支持简单函数调用（不允许属性访问 / lambda）")
        fn_name = node.func.id
        fn = OPERATOR_REGISTRY.get(fn_name)
        if fn is None:
            raise ExpressionError(f"未知算子: {fn_name}（已注册 {len(OPERATOR_REGISTRY)} 个）")
        if node.keywords:
            raise ExpressionError("算子不支持关键字参数；请按位置传参")
        args = [_eval_node(a, columns) for a in node.args]
        return fn(*args)
    raise ExpressionError(f"不支持的 AST 节点: {type(node).__name__}")


def evaluate_on_panel(
    panel: pl.DataFrame,
    formula: str,
    alias: str = "factor",
    available_columns: set[str] | None = None,
) -> pl.DataFrame:
    """把一份 panel (ts, symbol, ...) 应用表达式，返回 (ts, symbol, alias)。

    若 root 节点是 cs_* 算子，自动两阶段执行：先物化 inner，再做截面运算，
    绕开 polars 双层 over 限制。
    """

    if available_columns is None:
        available_columns = set(panel.columns)
    node = parse_expression(formula)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in CS_OPERATORS
        and len(node.args) >= 1
    ):
        cs_fn = OPERATOR_REGISTRY[node.func.id]
        inner_formula = ast.unparse(node.args[0])
        extra_args = [ast.literal_eval(a) for a in node.args[1:]]
        inner_alias = "_cs_inner_"
        materialized = evaluate_on_panel(panel, inner_formula, alias=inner_alias, available_columns=available_columns)
        return materialized.select(
            pl.col("ts"),
            pl.col("symbol"),
            cs_fn(pl.col(inner_alias), *extra_args).alias(alias),
        )
    expr = compile_expression(formula, available_columns)
    return panel.select(
        pl.col("ts"),
        pl.col("symbol"),
        expr.alias(alias),
    )


__all__ = [
    "ExpressionError",
    "compile_expression",
    "evaluate_on_panel",
    "parse_expression",
]
