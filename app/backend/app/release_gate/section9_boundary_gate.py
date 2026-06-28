"""C-S9-BOUNDARY-ENFORCE · §9 因子/模型/信号/策略边界 check（插 SA-3 promote 门链）。

**这张卡只建 PARALLEL-SAFE 的 check + 注册函数**——把（库级已建的）§9 边界 validator 经
SA-3 门链接到 promote 收口。**不**在此串进 `ide/promote.py`（那是后续 CENTER-SERIAL 的一次性
改·两步法）；本模块是新建孤立件，中心后续调 `register_section9_boundary_gate(default_chain())`。

**复用不重造（RULES §1 单一源）**：§9 边界判定的唯一源是 `research_os.factor_strategy_boundary`
的 5 个 canonical validator（`validate_factor_library_entry` 拒模型体入因子库 / 因子数学缺 run_config
绑定·`validate_factor_generator` 拒守门指标入 generator fitness / 缺独立 gatekeeper·
`validate_signal_protocol` ML/DL 信号缺泄漏控制+typed 语义·`validate_strategy_book` 拒退役因子默认
采用 / 缺契约 / short-intent 缺执行检查 / 数学缺绑定）。本模块**只**做 manifest(dict)→dataclass 的
薄适配 + 聚合，**绝不**重写任何边界判定逻辑。

**职责分离（gaming-proof）**：check **只懂「这个 promote run 的 §9 边界过没过」**，返回
`GateCheckResult(ok, reason, missing)`——它**不**决定自己是 advisory 还是 enforce。advisory/enforce
由 SA-2 策略（`governance.enforcement_policy`）经门链统一盖章：仅当 `s9_boundary_runjson_producers`
（§9 边界结构进 manifest 的接线测试）转绿，门才从 advisory 翻 enforce（LOCKED 决策 1）。于是本 check
**无法自封 enforce 绕过 producer 绿灯门**——它连 mode 字段都没有。

**manifest 契约（中心后续的 §9 producer 据此填）**：check 读 `manifest["section9_boundary"]`（一个
dict），内含四个可选列表/映射：
  - `factor_library_entries`: list[dict] —— 本 run 采用的因子库条目（→ validate_factor_library_entry）
  - `factor_generators`:      list[dict] —— 因子生成器规格（→ validate_factor_generator）
  - `signal_protocols`:       list[dict] —— 信号契约记录（→ validate_signal_protocol）
  - `strategy_books`:         list[dict] —— 策略本契约（→ validate_strategy_book·可内嵌
      `factor_library`/`signal_protocols`/`signal_validations` 映射供交叉校验）
每个 dict 的字段名 = 对应 dataclass 字段名（faithful 序列化）。

**诚实限界（RULES §3·设计极限·非残余）**：`section9_boundary` 缺省/为空 → `ok=True`，语义是
**「未声明 §9 结构 ⇒ 无可证伪边界违例」**，**不**代表「整本 run 已查清 §9」。「是否真的有 §9 资产
被如实写进 manifest」由 producer 绿灯门（`s9_boundary_runjson_producers` 接线测试）负责——producer
未绿时本门只 advisory，绝不在未接线门上误拒诚实 run。节存在但格式非法 → fail-closed 记 ok=False。

**冷导入安全**：本模块顶层只 import 同包 `promote_gate_chain`（cold-safe·已证）与
`research_os.factor_strategy_boundary`（cold-safe·已证·不触 governance 冷循环）。**不**在顶层 import
governance（SA-2 符号由门链在 evaluate 期惰性载入）。**不**碰 `release_gate/__init__.py`（既有冷导入
环·SA-3 note）——消费方从本子模块直接 import。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable, Iterator

from ..research_os.factor_strategy_boundary import (
    BoundaryDecision,
    FactorAssetKind,
    FactorGeneratorSpec,
    FactorLibraryEntry,
    SignalProtocolRecord,
    StrategyBookContract,
    StrategyLegContract,
    StrategySide,
    signal_validation_record_from_dict,
    validate_factor_generator,
    validate_factor_library_entry,
    validate_signal_protocol,
    validate_strategy_book,
)
from .promote_gate_chain import GateCheckResult, PromoteGateChain, RunManifest

# —— 门身份 + 证据 producer key（中心注册/绿灯账据此钉）——
# gate_name 与 promote 门链其它节门同族短名（s9/s10/s13/s16/s17）。
SECTION9_BOUNDARY_GATE_NAME = "s9_boundary"
# 证据 producer：§9 边界结构进 promote manifest 的接线测试。转绿前门停 advisory（LOCKED 决策 1）。
SECTION9_BOUNDARY_PRODUCER_KEY = "s9_boundary_runjson_producers"
# manifest 里承载 §9 边界结构的 key（producer 填·check 读）。
SECTION9_BOUNDARY_MANIFEST_KEY = "section9_boundary"

_NOTHING_DECLARED = (
    "§9：manifest 未声明 section9_boundary 结构 —— 无可证伪边界违例"
    "（诚实限界：非『整本已查清』·查清由 producer 绿灯门负责）"
)
_ALL_SATISFIED = "§9 边界全部满足（已声明结构无违例）"


# ════════════════════════════════════════════════════════════════════════════
# manifest(dict) → factor_strategy_boundary dataclass 的薄适配（只构造·不判定）
# ════════════════════════════════════════════════════════════════════════════
def _items(value: Any) -> Iterator[tuple[Any, Any]]:
    if isinstance(value, Mapping):
        yield from value.items()


def _iter_dicts(value: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, Mapping):
                yield item


def _factor_library_entry_from_dict(d: Mapping[str, Any]) -> FactorLibraryEntry:
    return FactorLibraryEntry(
        factor_ref=str(d.get("factor_ref") or ""),
        kind=d.get("kind") or FactorAssetKind.EXPRESSION,
        ref=str(d.get("ref") or ""),
        lifecycle_state=str(d.get("lifecycle_state") or "NEW"),
        adopted_by_default=bool(d.get("adopted_by_default", False)),
        mathematical_refs=d.get("mathematical_refs"),
        theory_binding_ref=d.get("theory_binding_ref"),
        run_config_binding_ref=d.get("run_config_binding_ref"),
    )


def _factor_generator_from_dict(d: Mapping[str, Any]) -> FactorGeneratorSpec:
    return FactorGeneratorSpec(
        generator_ref=str(d.get("generator_ref") or ""),
        structure_inputs=d.get("structure_inputs"),
        fitness_inputs=d.get("fitness_inputs"),
        gatekeeper_ref=d.get("gatekeeper_ref"),
    )


def _signal_protocol_from_dict(d: Mapping[str, Any]) -> SignalProtocolRecord:
    return SignalProtocolRecord(
        signal_ref=str(d.get("signal_ref") or ""),
        source_model_ref=d.get("source_model_ref"),
        oof=bool(d.get("oof", False)),
        purge=bool(d.get("purge", False)),
        embargo=bool(d.get("embargo", False)),
        train_test_lock_ref=d.get("train_test_lock_ref"),
        honest_n_ref=d.get("honest_n_ref"),
        forecast_time_ref=d.get("forecast_time_ref"),
        prediction_horizon_ref=d.get("prediction_horizon_ref"),
        unit_ref=d.get("unit_ref"),
        direction_semantics_ref=d.get("direction_semantics_ref"),
        confidence_ref=d.get("confidence_ref"),
        expires_at_ref=d.get("expires_at_ref"),
        source_layer=str(d.get("source_layer") or "signal"),
    )


def _strategy_leg_from_dict(d: Mapping[str, Any]) -> StrategyLegContract:
    return StrategyLegContract(
        intent_ref=str(d.get("intent_ref") or ""),
        side=d.get("side") or StrategySide.LONG,
        instrument_ref=str(d.get("instrument_ref") or ""),
        expected_pnl_ref=d.get("expected_pnl_ref"),
        venue_ref=d.get("venue_ref"),
        borrow_check_ref=d.get("borrow_check_ref"),
        margin_check_ref=d.get("margin_check_ref"),
        regulation_check_ref=d.get("regulation_check_ref"),
        permission_check_ref=d.get("permission_check_ref"),
    )


def _as_ref_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return [str(value)]


def _strategy_book_from_dict(d: Mapping[str, Any]) -> StrategyBookContract:
    # fail-closed 归一（gaming-proof）：canonical retired-default-adoption 只迭代 factor_refs
    # （factor_strategy_boundary L557-577）；把 default_factor_refs 并进 factor_refs，确保任何被默认
    # 采用的退役因子都被 canonical 规则评到——即便 producer 只填 default_factor_refs、漏填 factor_refs。
    # 只补全输入·**不**在此重写规则（判定仍全委托 validate_strategy_book）。
    factor_refs = tuple(dict.fromkeys(
        _as_ref_list(d.get("factor_refs")) + _as_ref_list(d.get("default_factor_refs"))
    ))
    return StrategyBookContract(
        strategy_book_ref=str(d.get("strategy_book_ref") or ""),
        factor_refs=factor_refs,
        signal_refs=d.get("signal_refs"),
        legs=tuple(_strategy_leg_from_dict(leg) for leg in _iter_dicts(d.get("legs"))),
        default_factor_refs=d.get("default_factor_refs"),
        mathematical_refs=d.get("mathematical_refs"),
        theory_binding_refs=d.get("theory_binding_refs"),
        run_config_binding_refs=d.get("run_config_binding_refs"),
        signal_validation_refs=d.get("signal_validation_refs"),
        market_data_use_validation_refs=d.get("market_data_use_validation_refs"),
        portfolio_of_strategies_refs=d.get("portfolio_of_strategies_refs"),
        correlation_budget_ref=d.get("correlation_budget_ref"),
        capacity_budget_ref=d.get("capacity_budget_ref"),
        drawdown_budget_ref=d.get("drawdown_budget_ref"),
        capital_allocation_ref=d.get("capital_allocation_ref"),
    )


# ════════════════════════════════════════════════════════════════════════════
# 每族 dict → canonical validator（判定全部委托回 factor_strategy_boundary）
# ════════════════════════════════════════════════════════════════════════════
def _validate_factor_library_entry_dict(d: Mapping[str, Any]) -> BoundaryDecision:
    return validate_factor_library_entry(_factor_library_entry_from_dict(d))


def _validate_factor_generator_dict(d: Mapping[str, Any]) -> BoundaryDecision:
    return validate_factor_generator(_factor_generator_from_dict(d))


def _validate_signal_protocol_dict(d: Mapping[str, Any]) -> BoundaryDecision:
    return validate_signal_protocol(_signal_protocol_from_dict(d))


def _validate_strategy_book_dict(d: Mapping[str, Any]) -> BoundaryDecision:
    book = _strategy_book_from_dict(d)
    factor_library = {
        str(k): _factor_library_entry_from_dict(v)
        for k, v in _items(d.get("factor_library"))
        if isinstance(v, Mapping)
    }
    signal_protocols = {
        str(k): _signal_protocol_from_dict(v)
        for k, v in _items(d.get("signal_protocols"))
        if isinstance(v, Mapping)
    }
    signal_validations = {
        str(k): signal_validation_record_from_dict(dict(v))
        for k, v in _items(d.get("signal_validations"))
        if isinstance(v, Mapping)
    }
    return validate_strategy_book(
        book,
        factor_library=factor_library or None,
        signal_protocols=signal_protocols or None,
        signal_validations=signal_validations or None,
        require_signal_validation=bool(d.get("require_signal_validation", False)),
    )


def _ref_of(d: Mapping[str, Any]) -> str:
    for key in ("factor_ref", "generator_ref", "signal_ref", "strategy_book_ref", "ref"):
        val = d.get(key)
        if val:
            return str(val)
    return ""


def _collect_family(
    out: list[tuple[str, str]],
    section: Mapping[str, Any],
    key: str,
    validate: Callable[[Mapping[str, Any]], BoundaryDecision],
    family: str,
) -> None:
    """跑一族 §9 结构 · fail-closed（不静默 skip 让违例溜走）。

    缺省/None → 未声明（跳过·诚实空）；**present 但非 list/tuple**（如被填成 {id:rec} 映射 / 标量）
    → 记 `section9_<family>_malformed`（ok=False·不当作空通过）；list 内非 dict 项 → 同样 malformed；
    单条 validate 抛 → 记 `section9_<family>_unparseable`。判定全委托 canonical validator。
    """

    value = section.get(key)
    if value is None:
        return
    if not isinstance(value, (list, tuple)):
        out.append((f"section9_{family}_malformed", ""))
        return
    for item in value:
        if not isinstance(item, Mapping):
            out.append((f"section9_{family}_malformed", ""))
            continue
        try:
            decision = validate(item)
        except Exception:  # noqa: BLE001 — 单条解析/校验炸 → fail-closed 记族违例（不静默放行·不炸整链）
            out.append((f"section9_{family}_unparseable", _ref_of(item)))
            continue
        for violation in getattr(decision, "violations", ()) or ():
            out.append((violation.code, violation.ref or ""))


# ════════════════════════════════════════════════════════════════════════════
# 公开 check：promote manifest → GateCheckResult（门链插它）
# ════════════════════════════════════════════════════════════════════════════
def section9_boundary_check(manifest: RunManifest) -> GateCheckResult:
    """§9 边界 check：跑 4 族 canonical validator·聚合违例·返回过/不过（不碰 advisory/enforce）。

    - 节缺省/为空 → ok=True（无可证伪违例·诚实限界见模块 docstring）。
    - 节存在但非 dict → ok=False（fail-closed·格式非法不静默放行）。
    - 任一族任一条违例 → ok=False·missing=去重违例码·reason=带 ref 样本。
    """

    # 非 Mapping manifest → manifest.get 抛 → 由门链 _run_one fail-closed（errored·绝不静默放行）。
    # 刻意不在此 catch 成 ok=True（那是 fail-open）。
    section = manifest.get(SECTION9_BOUNDARY_MANIFEST_KEY)

    if section is None:
        return GateCheckResult(ok=True, reason=_NOTHING_DECLARED)
    if not isinstance(section, Mapping):
        return GateCheckResult(
            ok=False,
            reason="§9 边界节存在但格式非法（应为对象/dict）—— fail-closed 视为未过",
            missing=("section9_boundary_malformed",),
        )

    violations: list[tuple[str, str]] = []
    _collect_family(violations, section, "factor_library_entries",
                    _validate_factor_library_entry_dict, "factor_library_entry")
    _collect_family(violations, section, "factor_generators",
                    _validate_factor_generator_dict, "factor_generator")
    _collect_family(violations, section, "signal_protocols",
                    _validate_signal_protocol_dict, "signal_protocol")
    _collect_family(violations, section, "strategy_books",
                    _validate_strategy_book_dict, "strategy_book")

    if not violations:
        return GateCheckResult(ok=True, reason=_ALL_SATISFIED)

    codes = tuple(dict.fromkeys(code for code, _ in violations))  # 去重·保首现序
    sample = "; ".join(f"{code}@{ref}" if ref else code for code, ref in violations[:8])
    more = "" if len(violations) <= 8 else f" …(+{len(violations) - 8})"
    reason = f"§9 边界违例 {len(violations)} 项: {sample}{more}"
    return GateCheckResult(ok=False, reason=reason, missing=codes)


def register_section9_boundary_gate(
    chain: PromoteGateChain, *, enforce_intent: bool = True
) -> None:
    """把 §9 边界 check 注册进给定门链（中心后续串 promote.py 时调一次）。

    用法（CENTER-SERIAL·第三波）：
        from app.release_gate.promote_gate_chain import default_chain
        from app.release_gate.section9_boundary_gate import register_section9_boundary_gate
        register_section9_boundary_gate(default_chain())

    `enforce_intent=True`：§9 门有 GOAL「拒」语义（拒模型体入因子库 / 守门指标入 fitness / 退役因子
    默认采用），**有资格** enforce——但仅当 `s9_boundary_runjson_producers` 转绿才真翻 enforce；未绿
    则被 SA-2 策略降级 advisory + 记录（绝不误拒诚实 run）。
    """

    chain.register(
        gate_name=SECTION9_BOUNDARY_GATE_NAME,
        check=section9_boundary_check,
        required_producer=SECTION9_BOUNDARY_PRODUCER_KEY,
        enforce_intent=enforce_intent,
    )


__all__ = [
    "SECTION9_BOUNDARY_GATE_NAME",
    "SECTION9_BOUNDARY_PRODUCER_KEY",
    "SECTION9_BOUNDARY_MANIFEST_KEY",
    "section9_boundary_check",
    "register_section9_boundary_gate",
]
