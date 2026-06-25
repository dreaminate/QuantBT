"""多证据三角 gate 的接线层（T-015）：把 gate 接到 T-013 一本账 + 收益快照存储。

这是「接线活性证明」的中枢：promote 关卡调本模块 → 记账（honest-N）+ 存收益快照 + 拼同主题
历史矩阵 → 算 N_eff → 跑 gate → 把 dsr/pbo 注入 metrics（让 risk_summary 的 _rule_dsr/_rule_pbo
从「永远拿 None 不触发」变成真生效）。

边界：
- 账本存储复用 **T-013 `Ledger`**（绝不自建第二本，复核 00 §1.2-I）；config_hash 复用
  **`ids.config_hash`** 单一源。
- 收益快照存储 duck-typed（`put(key, list)` / `get(key) -> list`，KeyError 表缺失）——
  生产用 dag `ArtifactStore`（内容寻址不可覆盖），测试可塞内存假store。
- preview（只读）**不记账**（不 +honest-N，防预览刷 N）；promote（确证）才记账。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from ..lineage import config_hash as _config_hash, content_hash as _content_hash
from ..lineage.ledger import Ledger, LedgerEntry
from .n_eff import n_eff_from_matrix
from .overfit_gate import GateVerdict, run_overfit_gate


@dataclass
class GateRunResult:
    verdict: GateVerdict
    config_hash: str
    honest_n: int


def asset_class_of(market: str | None) -> str:
    """market → gate 资产类（a_share 用更长 min_T / 纯多头；其它走 crypto 口径）。"""

    m = (market or "").lower()
    if "stock" in m or "cn" in m or "a_share" in m or "ashare" in m:
        return "a_share"
    return "crypto"


def freq_to_ppy(freq: str | None) -> int:
    """频率 → 年化周期数（DSR studentized 后不依赖它，但 Sharpe/Bootstrap 年化需正确）。"""

    f = (freq or "1d").lower().strip()
    return {"1m": 252 * 390, "5m": 252 * 78, "15m": 252 * 26, "30m": 252 * 13,
            "1h": 252 * 24, "4h": 252 * 6, "1d": 252, "1w": 52, "1mo": 12}.get(f, 252)


def _theme_matrix(
    ledger: Ledger | None,
    returns_store,
    strategy_goal_ref: str,
    target_len: int,
    *,
    include_current: list[float] | None = None,
) -> np.ndarray | None:
    """拼同主题历史试验的收益矩阵（PBO/N_eff 用）。

    只纳入【与本次同长】的收益列（近似同期/同频；不同长度直接跳过，宁缺毋滥——
    混不同长度会让相关/PBO 把苹果橘子混算，复核 05 §7-3）。<2 列 → 返 None。
    """

    series: list[list[float]] = []
    seen_refs: set[str] = set()
    if ledger is not None and returns_store is not None:
        for e in ledger.list_entries(strategy_goal_ref):
            ref = e.returns_ref or e.config_hash
            if ref in seen_refs:
                continue
            try:
                s = returns_store.get(ref)
            except KeyError:
                continue
            if isinstance(s, list) and len(s) == target_len:
                seen_refs.add(ref)
                series.append([float(x) for x in s])
    if include_current is not None and len(include_current) == target_len:
        # preview 去重（复核 #6）：当前列若已在账本里取过（同 returns 内容指纹）则不重复纳入。
        cur_ref = _content_hash([float(x) for x in include_current])
        if cur_ref not in seen_refs:
            series.append([float(x) for x in include_current])
    if len(series) < 2:
        return None
    return np.column_stack([np.asarray(s, dtype=float) for s in series])


def evaluate_overfit_gate(
    *,
    returns: list[float],
    factor,
    params=None,
    universe: str = "default",
    dataset_version: str = "unknown",
    freq: str = "1d",
    label: str = "net_return",
    strategy_goal_ref: str,
    asset_class: str = "crypto",
    periods_per_year: int = 252,
    ledger: Ledger | None = None,
    returns_store=None,
    allow_pbo_absent_green: bool = False,
    cpcv_distribution: dict | None = None,
    cpcv_policy: Literal["report_only", "cpcv_conservative"] = "report_only",
    record: bool,
) -> GateRunResult:
    """跑一次三角 gate。`record=True`（promote）记账 + 存快照；`record=False`（preview）只读。

    `allow_pbo_absent_green`（组合层 A2，D-WAVE1A）：透传给 run_overfit_gate；默认 False 单策略不变。

    `cpcv_distribution` / `cpcv_policy`（CPCV q05→gate 接线）：透传给 run_overfit_gate。默认
    `report_only`（只附报告·绝不改裁决·守「方法学松紧=用户拍板」），调用方显式传 `cpcv_conservative`
    才允许 q05<基线的脆弱分布把 green 降级为 yellow（advisory·绝不硬 red、绝不升级）。默认 None →
    行为与接线前逐位一致（不假绿灯：未传 CPCV ≠ 编造）。
    """

    chash = _config_hash(
        factor=factor, params=params, universe=universe,
        dataset_version=dataset_version, freq=freq, label=label,
    )
    ret_list = [float(x) for x in returns]
    # 收益快照【内容寻址】（复核 low-note）：不同收益 → 不同 ref，杜绝 config_hash 撞键时静默共享。
    returns_ref = _content_hash(ret_list)

    if record and ledger is not None:
        entry = LedgerEntry.create(
            factor=factor, params=params, universe=universe, dataset_version=dataset_version,
            freq=freq, label=label, strategy_goal_ref=strategy_goal_ref, kind="backtest",
            stage="confirmatory", asset_class=asset_class, returns_ref=returns_ref,
        )
        ledger.record_or_hit(entry)
        if returns_store is not None:
            returns_store.put(returns_ref, ret_list)

    # 拼矩阵：promote 已记账（当前列已在账本里，不重复加）；preview 显式把当前列纳入（内部去重）。
    matrix = _theme_matrix(
        ledger, returns_store, strategy_goal_ref, len(ret_list),
        include_current=None if record else ret_list,
    )
    if matrix is not None:
        neff = n_eff_from_matrix(matrix)
    else:
        neff = n_eff_from_matrix(np.asarray(ret_list, dtype=float).reshape(-1, 1))

    # honest_n 先算（含本次已记账）→ 作保守端通缩兜底传入 gate（复核 #1/#4）。
    honest_n = ledger.honest_n(strategy_goal_ref) if ledger is not None else neff.n_observed
    verdict = run_overfit_gate(
        ret_list, n_eff=neff, honest_n=honest_n, returns_matrix=matrix,
        asset_class=asset_class, periods_per_year=periods_per_year,
        allow_pbo_absent_green=allow_pbo_absent_green,
        cpcv_distribution=cpcv_distribution, cpcv_policy=cpcv_policy,
    )
    return GateRunResult(verdict=verdict, config_hash=chash, honest_n=honest_n)


__all__ = ["GateRunResult", "asset_class_of", "evaluate_overfit_gate"]
