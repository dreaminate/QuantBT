"""脊柱 · Mathematical Spine 绑定器——把【真实 Python 实现】绑到数学定义并做数值对账。

这是「全链贯穿」的可复用范式（决策 D-MATH-SPINE）：任何声称「按理论实现」的真函数，
都能：
1. `code_fingerprint(*fns)` —— 用 `inspect.getsource` 取整条计算链的真源码、`ids.content_hash`
   冻结指纹。改实现任一环（含 helper）→ 指纹变 → 一致性门 fresh 子句抓 staleness。**复用单一
   身份源，绝不另造哈希族。**
2. `numerical_consistency_check(...)` —— impl 与【独立 oracle】（从数学定义另路重算）在 fixtures
   上对账；偏差超容差即 result=fail（= 代码实现与数学定义不一致 → 门拒）。
3. `bind_callable(...)` —— 便捷产出 TheoryImplementationBinding，code_content_hash 走 1。

诚实边界：数值对账抓的是「impl 偏离 oracle 重算的定义」；它**不**判定定义本身对错（那靠
Verifier/Critic + 文献）。oracle 与 impl 须真独立（不同算路），否则共享 bug 抓不到——调用方
负责让 oracle 走另一条计算路径（如 scipy 矩 vs 手算矩）。
"""

from __future__ import annotations

import inspect
import math
from typing import Any, Callable, Mapping, Sequence

from .ids import content_hash
from .spine import ConsistencyCheck


def code_fingerprint(*fns: Callable[..., Any]) -> str:
    """整条实现链的真源码内容指纹（`inspect.getsource` + `ids.content_hash`）。

    传 impl 主函数 + 它依赖的 helper（如 DSR 的 `_skew`/`_expected_max_sr`）——任一环改动
    都让指纹变，杜绝「改 helper 绕过 binding」。源码取不到（C 扩展/动态）→ 拒，不静默放过。
    """

    if not fns:
        raise ValueError("code_fingerprint 至少需要一个函数")
    sources: list[dict[str, str]] = []
    for fn in fns:
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError) as exc:  # 源码不可得 → 不可指纹 → 不静默放过
            raise ValueError(f"无法取 {getattr(fn, '__qualname__', fn)!r} 源码做指纹：{exc}") from exc
        sources.append({"qualname": getattr(fn, "__qualname__", repr(fn)), "src": src})
    return content_hash(sources)


def _max_abs_deviation(impl_out: Any, oracle_out: Any) -> float:
    """标量/序列输出的最大绝对偏差（NaN 视为无穷大偏差 → 必判 fail）。"""

    def _flatten(x: Any) -> list[float]:
        if isinstance(x, (list, tuple)):
            out: list[float] = []
            for v in x:
                out.extend(_flatten(v))
            return out
        return [float(x)]

    a = _flatten(impl_out)
    b = _flatten(oracle_out)
    if len(a) != len(b):
        return math.inf
    dev = 0.0
    for x, y in zip(a, b):
        if math.isnan(x) or math.isnan(y):
            return math.inf
        dev = max(dev, abs(x - y))
    return dev


def numerical_consistency_check(
    binding_id: str,
    impl: Callable[..., Any],
    oracle: Callable[..., Any],
    fixtures: Sequence[Mapping[str, Any]],
    *,
    tolerance: float = 1e-6,
    check_type: str = "numerical",
    verifier_ref: str = "",
    affected_assets: tuple[str, ...] = (),
) -> ConsistencyCheck:
    """impl vs 独立 oracle 在 fixtures（kwargs dict 列表）上对账，产出 ConsistencyCheck。

    全部 fixture 偏差 ≤ tolerance → pass；任一超出（含长度不符/NaN）→ fail，failure_reason
    指出最坏 fixture 与偏差。oracle 必须从数学定义另路重算（独立性由调用方保证）。
    """

    if not fixtures:
        raise ValueError("numerical_consistency_check 需要至少一个 fixture")
    worst_dev = 0.0
    worst_idx = -1
    worst_pair: tuple[Any, Any] = (None, None)
    for i, fx in enumerate(fixtures):
        impl_out = impl(**dict(fx))
        oracle_out = oracle(**dict(fx))
        dev = _max_abs_deviation(impl_out, oracle_out)
        if dev > worst_dev:
            worst_dev, worst_idx, worst_pair = dev, i, (impl_out, oracle_out)
    passed = worst_dev <= tolerance
    return ConsistencyCheck(
        binding_id=binding_id,
        check_type=check_type,
        result="pass" if passed else "fail",
        expected_property=f"∀ fixture: |impl − oracle| ≤ {tolerance:g}（oracle = 从数学定义独立重算）",
        observed_property=f"max|impl − oracle| = {worst_dev:g} @ fixture#{worst_idx}",
        tolerance=tolerance,
        failure_reason=(
            "" if passed
            else f"fixture#{worst_idx} impl={worst_pair[0]!r} vs oracle={worst_pair[1]!r}，"
                 f"偏差 {worst_dev:g} > 容差 {tolerance:g} → 实现偏离定义"
        ),
        affected_assets=affected_assets,
        verifier_ref=verifier_ref,
    )


def property_consistency_check(
    binding_id: str,
    properties: Sequence[tuple[str, bool, str]],
    *,
    check_type: str = "property",
    verifier_ref: str = "",
    affected_assets: tuple[str, ...] = (),
) -> ConsistencyCheck:
    """从数学定义推出的【必要性质】对账（用于难做闭式独立 oracle 的实现，如 CSCV-PBO / bootstrap）。

    `properties`: (性质名, 是否成立, 观测明细) 列表——调用方跑实现、判每条性质。任一不满足 →
    result=fail（实现偏离定义）。**诚实边界**：性质是【必要非充分】，抓不到「全性质满足但数值细微偏离」
    的 bug——那需更强 oracle/Verifier；故 check_type="property" 标明弱于 numerical 对账。
    """

    if not properties:
        raise ValueError("property_consistency_check 需要至少一条性质")
    failed = [(n, o) for (n, ok, o) in properties if not ok]
    return ConsistencyCheck(
        binding_id=binding_id,
        check_type=check_type,
        result="pass" if not failed else "fail",
        expected_property="∀ property 成立（从数学定义推出的必要性质）",
        observed_property="; ".join(f"{n}={'✓' if ok else '✗'}({o})" for (n, ok, o) in properties),
        failure_reason=(
            "" if not failed
            else "违反必要性质 → 实现偏离定义: " + "; ".join(f"{n}({o})" for n, o in failed)
        ),
        affected_assets=affected_assets,
        verifier_ref=verifier_ref,
    )
