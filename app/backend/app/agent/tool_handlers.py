"""数据平台 v2 · 给 M14 Agent 加的"字段对齐"工具 handler。

在两个接缝辅助：① 入库时把用户源陌生列对齐到 canonical（infer→apply）；
② 消费时校验因子表达式引用的列是否在当前可用字段宇宙内（validate_columns）。

handler 都是轻 wrapper，接现有单例（FieldCatalog / FieldMappingStore），由 main.py 的 _agent_runtime 注册。
"""

from __future__ import annotations

import ast
from typing import Any

from ..factor_factory.operators import OPERATOR_REGISTRY
from ..field_catalog import FieldMapping
from ..field_catalog.infer import infer_mapping, infer_mapping_report

_STRUCTURAL = {"ts", "symbol", "market", "interval"}


def referenced_columns(formula: str) -> set[str]:
    """抽出因子表达式里引用的列名（排除算子名）。"""
    tree = ast.parse(formula, mode="eval")  # 可能抛 SyntaxError，调用方捕获
    # 属性访问(df.close / np.log)会让 ast.Name 漏列或误收模块名 → 因子 DSL 不允许，显式拒绝
    if any(isinstance(n, ast.Attribute) for n in ast.walk(tree)):
        raise ValueError("不支持属性访问（如 df.close / np.log(...)）；请直接用列名与算子，如 ts_mean(close, 5)")
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    return names - set(OPERATOR_REGISTRY.keys())


def register_field_tools(runtime, *, field_catalog, mapping_store) -> None:
    def _list_sources(_n: str, _args: dict) -> dict[str, Any]:
        # 从字段目录枚举当前数据源（官方/用户）；无开关、不隔离，仅告知 Agent 有哪些源
        seen: dict[str, dict] = {}
        for ds in field_catalog.list_datasets():
            entry = seen.setdefault(
                ds.source_name,
                {
                    "source": ds.source_name,
                    "kind": "user" if str(ds.source_name).startswith("user_") else "official",
                    "markets": set(),
                    "data_kinds": set(),
                },
            )
            if ds.market:
                entry["markets"].add(ds.market)
            if ds.data_kind:
                entry["data_kinds"].add(ds.data_kind)
        return {
            "sources": [
                {"source": v["source"], "kind": v["kind"], "markets": sorted(v["markets"]), "data_kinds": sorted(v["data_kinds"])}
                for v in seen.values()
            ]
        }

    def _describe_fields(_n: str, args: dict) -> dict[str, Any]:
        market = args.get("market")
        if not market:
            return {"error": "需要 market 参数"}
        interval = args.get("interval")
        uni = field_catalog.available_fields(market, interval=interval)
        datasets = [
            {
                "dataset_id": d.dataset_id,
                "source": d.source_name,
                "data_kind": d.data_kind,
                "interval": d.interval,
                "columns": d.columns,
            }
            for d in field_catalog.list_datasets(market=market, interval=interval)
        ]
        return {**uni.to_dict(), "datasets": datasets}

    def _infer_mapping(_n: str, args: dict) -> dict[str, Any]:
        columns = args.get("columns") or []
        return infer_mapping_report(columns, market=args.get("market"), data_kind=args.get("data_kind", "ohlcv"), sample=args.get("sample"))

    def _apply_mapping(_n: str, args: dict) -> dict[str, Any]:
        source = args.get("source")
        data_kind = args.get("data_kind", "ohlcv")
        maps = args.get("mappings") or []
        if not source or not maps:
            return {"error": "需要 source 与 mappings"}
        applied: list[dict] = []
        errors: list[dict] = []
        for m in maps:
            raw = m.get("raw_column")
            fid = m.get("field_id")
            if not raw or not fid:
                continue
            try:
                mapping_store.set(
                    FieldMapping(
                        source=source,
                        data_kind=data_kind,
                        raw_column=raw,
                        field_id=fid,
                        is_freeform=bool(m.get("is_freeform", False)),
                    )
                )
                applied.append({"raw_column": raw, "field_id": fid})
            except ValueError as exc:
                errors.append({"raw_column": raw, "field_id": fid, "error": str(exc)})
        return {"applied": applied, "count": len(applied), "errors": errors}

    def _validate_columns(_n: str, args: dict) -> dict[str, Any]:
        formula = args.get("formula")
        market = args.get("market")
        if not formula or not market:
            return {"error": "需要 formula 与 market"}
        try:
            refs = referenced_columns(formula)
        except SyntaxError as exc:
            return {"ok": False, "error": f"表达式语法错误: {exc}（提示：不支持 a?b:c 三元，请用 a if cond else b）"}
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        uni = field_catalog.available_fields(market, interval=args.get("interval"))
        available = set(uni.ids()) | _STRUCTURAL
        missing = sorted(refs - available)
        return {
            "ok": not missing,
            "referenced": sorted(refs),
            "missing": missing,
            "suggestions": infer_mapping(missing, market=market) if missing else [],
            "available_sample": sorted(available)[:30],
        }

    runtime.register_tool("data.list_sources", _list_sources)
    runtime.register_tool("data.describe_fields", _describe_fields)
    runtime.register_tool("data.infer_mapping", _infer_mapping)
    runtime.register_tool("data.apply_mapping", _apply_mapping)
    runtime.register_tool("factor.validate_columns", _validate_columns)


__all__ = ["register_field_tools", "referenced_columns"]
