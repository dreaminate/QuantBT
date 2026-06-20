"""T-034 · 实盘因子血统门（D-PROVENANCE）。

上真钱线（CRYPTO_LIVE）前，逐一校验策略所用每个因子是否走完治理流程
（假设卡 → 独立验证 → 审批 = cleared）。未走完 → 警告 + 知情确认（acknowledge 留痕）后仍可上
（硬透明 + 软决定，§0.1 用户自己的钱与判断；绝不死挡，与 D-T024-FALS 同范式）。

注（接线，端点/谱系侧）：`status_lookup` 由调用方注入——从 lineage 谱系查「策略→因子」、
从 hypothesis/store + verification 查各因子治理状态。本模块只做【判定 + 知情确认】纯逻辑，可严格测。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# 因子治理状态查询：factor_id -> status 字符串（"cleared" = 走完假设卡→验证→审批）。
FactorStatusLookup = Callable[[str], str]

_CLEARED = ("cleared",)


@dataclass
class ProvenanceVerdict:
    cleared: bool
    uncleared_factors: list[str] = field(default_factory=list)
    requires_acknowledge: bool = False
    acknowledged: bool = False
    message: str = ""


def check_factor_provenance(
    factor_ids: list[str],
    status_lookup: FactorStatusLookup,
    *,
    cleared_status: tuple[str, ...] = _CLEARED,
) -> ProvenanceVerdict:
    """逐因子查治理状态；任一未 cleared → 列入 uncleared + requires_acknowledge。查询异常按未过处理（fail-safe）。"""
    uncleared: list[str] = []
    for fid in factor_ids:
        try:
            st = status_lookup(fid)
        except Exception:  # noqa: BLE001  查询失败按「未过」处理，绝不当作已过（fail-safe 偏保守）
            st = "unknown"
        if st not in cleared_status:
            uncleared.append(fid)
    if not uncleared:
        return ProvenanceVerdict(cleared=True, message="全部因子已走完治理流程（假设卡→验证→审批）")
    return ProvenanceVerdict(
        cleared=False, uncleared_factors=uncleared, requires_acknowledge=True,
        message=f"以下因子未走完治理流程，上真钱线前请知情确认：{', '.join(uncleared)}",
    )


def gate_live_promotion(
    factor_ids: list[str],
    status_lookup: FactorStatusLookup,
    *,
    acknowledged: bool = False,
    cleared_status: tuple[str, ...] = _CLEARED,
) -> ProvenanceVerdict:
    """上真钱线血统门：全过 → 放行；含未过且未知情确认 → requires_acknowledge=True（调用方弹警告）；
    含未过但已知情确认 → 放行 + 留痕（绝不死挡：硬透明 + 软决定，用户自己的钱与判断）。
    """
    v = check_factor_provenance(factor_ids, status_lookup, cleared_status=cleared_status)
    if v.cleared:
        return v
    if acknowledged:
        v.requires_acknowledge = False
        v.acknowledged = True
        v.message = f"[知情确认] 用户已确认在含未过检验因子（{', '.join(v.uncleared_factors)}）情况下上真钱线"
    return v


__all__ = ["ProvenanceVerdict", "FactorStatusLookup", "check_factor_provenance", "gate_live_promotion"]
