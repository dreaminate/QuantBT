"""A4 · Agent 业务工具 handler（策略台脊柱：立题→因子集→模型→信号→风控→回测→报告）。

补齐设计稿剧本用到、但后端缺 handler 的 8 个工具——全部 **side_effect="none"**（本地可重置、
不动钱、不外发单）。治理红线（由对抗测试把守）：

  · 这里【绝不】注册任何 realmoney/external 工具——动钱/晋级/发单永远只在端点层经 OrderGuard/
    审批门（D-PERM 权限轴 ⟂ 治理轴）。本模块全部 register_tool 都显式 side_effect="none"。
  · 复用既有单一源引擎，不重造：HypothesisCardStore / FactorRegistry（QUALIFIED 血统门）/
    ModelRegistry（只读 select，绝不翻 stage）/ signals.fuse_signals / portfolio.optimizers /
    eval.pbo（CSCV）/ run_verdict（裁决投影，措辞守门走 Verifier._verdict_note）。
  · model_registry.select 是【只读】——只 list_versions/挑 stage，绝不 promote/apply_stage（写动作
    永远在端点层经审批门 approver≠creator）。

5 个新业务工具（schema+handler 接入真实 store）：
  hypothesis.create · factor_set.compose · model_registry.select · signal.define · portfolio.construct
3 个有 schema 无 handler → 接入真实引擎：
  backtest.run · eval.pbo · report.generate
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..lineage.ids import content_hash


def _short_id(prefix: str, *parts: Any) -> str:
    """内容寻址短 id（复用单一身份源 lineage.ids.content_hash，不另造哈希族）。"""
    return f"{prefix}_{content_hash(list(parts))[:10]}"


def _synth_execution_blocks(
    *,
    market: str,
    has_assembly: bool,
    assembly_injected: bool,
    live_source_ref: str = "",
) -> list[dict[str, Any]] | None:
    """把一次合成回测的【执行诚实】映射成 run.json `execution_blocks`（字段镜像 mock_honesty.ExecutionBlock，
    由 release_gate.promote_assembler 组装→evaluate_release 的 Mock 诚实门核查）。

    §16 诚实映射（判定单一源仍在 evaluate_release·本函数只产【诚实数据】、绝不自裁）：
    - has_assembly & 未注入 → 回测是动量模板基线却被当作所选组装结果 → `template`+`production` 块：
      正撞 §16 致命「未注入资产却声称已采用 / template 不生成 production success」→ R4/R5 硬拒。
    - has_assembly & 真注入 → 所选组装从 live source 真注入合成策略 → `live`+`live_source_ref` 块
      （R3 须有源）。DS-1 当前不走此路；保留为注入落地后的诚实映射、由单测覆盖（非死码）。
    - 无组装 → 诚实动量基线、无「已采用」假声明 → 返回 None 不写块（向后兼容·不污染既有 run.json；
      组装器会把「无执行诚实标识」surface 成软 gap，而非静默当作已核 live）。

    绝不为未注入的合成块伪造 mode=live/伪 source 蒙混过门——那正是本门要抓的坏门（写成 live 冒充
    → 致命门平凡过）。
    """

    if not has_assembly:
        return None
    # 复用 §16 Mock 诚实词汇表【单一源】(mock_honesty)·不在 agent 层另造 mode/grade 字面量。
    # 懒导入：避开 release_gate 包 __init__ 重依赖污染 business_tools 模块导入（且无组装路径不触发）。
    from ..release_gate.mock_honesty import GRADE_PRODUCTION, MODE_LIVE, MODE_TEMPLATE

    block_id = f"synth_{market}"
    if assembly_injected:
        return [{
            "block_id": block_id,
            "mode": MODE_LIVE,
            "result_grade": GRADE_PRODUCTION,
            "live_source_ref": live_source_ref,
            "note": "所选组装从 live source 真注入合成策略（DS-1 注入落地后路径）",
        }]
    return [{
        "block_id": block_id,
        "mode": MODE_TEMPLATE,
        "result_grade": GRADE_PRODUCTION,
        "note": (
            f"DS-1 合成器未注入所选组装；本回测为 {market} 动量模板基线，"
            "不得作为所选策略的生产结果（§16：no template false success / 未注入资产却声称已采用）"
        ),
    }]


def _market_data_use_validation_refs(
    args: dict[str, Any],
    market_data_registry: Any | None,
    *,
    owner_user_id: str | None,
    operation: str = "backtest.run",
    require_dataset_timing: bool = False,
    allowed_use_contexts: tuple[str, ...] = (),
) -> tuple[str, ...] | dict[str, Any]:
    """Validate refs before strategy synthesis/backtest builder side effects."""
    owner = str(owner_user_id or "").strip()
    if not owner:
        return {
            "error": f"{operation} requires an authenticated owner_user_id",
            "field": "market_data_use_validation_refs",
            "no_write": True,
        }
    if market_data_registry is None:
        return {
            "error": f"{operation} requires MarketDataUse registry before execution",
            "field": "market_data_use_validation_refs",
            "no_write": True,
        }
    raw_refs = args.get("market_data_use_validation_refs")
    if isinstance(raw_refs, str):
        refs = [part.strip() for part in raw_refs.replace(",", "\n").splitlines() if part.strip()]
    elif isinstance(raw_refs, (list, tuple)):
        refs = [str(ref).strip() for ref in raw_refs if str(ref or "").strip()]
    else:
        return {
            "error": f"{operation} requires market_data_use_validation_refs",
            "field": "market_data_use_validation_refs",
            "no_write": True,
        }
    if not refs:
        return {
            "error": f"{operation} requires non-empty market_data_use_validation_refs",
            "field": "market_data_use_validation_refs",
            "no_write": True,
        }
    resolved: list[str] = []
    for ref in refs:
        try:
            record = market_data_registry.use_validation(
                ref,
                owner_user_id=owner,
            )
        except Exception:  # noqa: BLE001
            return {
                "error": f"unknown MarketDataUse validation ref: {ref}",
                "field": "market_data_use_validation_refs",
                "validation_ref": ref,
                "no_write": True,
            }
        if str(getattr(record, "recorded_by", "") or "").strip() != owner:
            return {
                "error": f"MarketDataUse validation ref owner mismatch: {ref}",
                "field": "market_data_use_validation_refs",
                "validation_ref": ref,
                "no_write": True,
            }
        if not bool(getattr(record, "accepted", False)):
            return {
                "error": f"MarketDataUse validation ref is not accepted: {ref}",
                "field": "market_data_use_validation_refs",
                "validation_ref": ref,
                "no_write": True,
            }
        violations = tuple(getattr(record, "violation_codes", ()) or ())
        if violations:
            return {
                "error": f"MarketDataUse validation ref has violations: {ref}",
                "field": "market_data_use_validation_refs",
                "validation_ref": ref,
                "violation_codes": list(violations),
                "no_write": True,
            }
        context = str(getattr(record, "use_context", "") or "")
        if allowed_use_contexts and context not in set(allowed_use_contexts):
            return {
                "error": f"MarketDataUse validation ref has wrong use_context for {operation}: {ref}",
                "field": "market_data_use_validation_refs",
                "validation_ref": ref,
                "use_context": context,
                "allowed_use_contexts": list(allowed_use_contexts),
                "no_write": True,
            }
        if require_dataset_timing:
            dataset_refs = tuple(str(dataset_ref) for dataset_ref in (getattr(record, "dataset_refs", ()) or ()))
            if not dataset_refs:
                return {
                    "error": f"MarketDataUse validation ref has no dataset refs for {operation}: {ref}",
                    "field": "market_data_use_validation_refs",
                    "validation_ref": ref,
                    "no_write": True,
                }
            for dataset_ref in dataset_refs:
                try:
                    dataset = market_data_registry.dataset(
                        dataset_ref,
                        owner_user_id=owner,
                    )
                except Exception:  # noqa: BLE001
                    return {
                        "error": f"unknown DatasetSemantics ref for {operation}: {dataset_ref}",
                        "field": "market_data_use_validation_refs",
                        "validation_ref": ref,
                        "dataset_ref": dataset_ref,
                        "no_write": True,
                    }
                missing_timing = [
                    field
                    for field in ("known_at_ref", "effective_at_ref", "pit_bitemporal_rules_ref")
                    if not str(getattr(dataset, field, "") or "").strip()
                ]
                if missing_timing:
                    return {
                        "error": f"DatasetSemantics missing PIT/bitemporal timing refs for {operation}: {dataset_ref}",
                        "field": "market_data_use_validation_refs",
                        "validation_ref": ref,
                        "dataset_ref": dataset_ref,
                        "missing_timing_refs": missing_timing,
                        "no_write": True,
                    }
        resolved.append(ref)
    return tuple(resolved)


def _synth_and_promote(
    *,
    args: dict,
    ledger: Any,
    returns_store: Any,
    data_root: Any,
    verdict_store: Any,
    verifier: Any,
    llm_client: Any,
    market_data_registry: Any | None = None,
    owner_user_id: str | None = None,
) -> dict[str, Any]:
    """DS-1 脊梁：对话意图 → 合成最小策略 → 沙箱跑真样本 → promote 落 RUN_ROOT → 真 run_id。

    复用单一源：strategy_synth（合成）/ ide.sandbox（执行引擎）/ ide.promote（落盘契约 + 三角 gate）
    / run_verdict（裁决投影）。零新引擎。§3 诚实：样本缺 / 沙箱无净值 → 显式失败，绝不伪造 run。
    """

    from pathlib import Path

    from ..ide.promote import PromoteError, promote_ide_run
    from ..ide.sandbox import run_user_strategy
    from .sample_data import has_sample
    from .strategy_synth import synthesize_strategy_code

    validation_refs = _market_data_use_validation_refs(
        args,
        market_data_registry,
        owner_user_id=owner_user_id,
        operation="backtest.run strategy synthesis",
        require_dataset_timing=True,
        allowed_use_contexts=("strategy_builder_backtest", "backtest", "confirmatory_validation"),
    )
    if isinstance(validation_refs, dict):
        return validation_refs

    # 单旋钮 data_root：同控样本读取位置 + run_root 派生（缺省 paths.DATA_ROOT，测试可注入 tmp）。
    if data_root is not None:
        eff_root = Path(data_root)
    else:
        from ..paths import DATA_ROOT as _DR
        eff_root = _DR
    run_root = eff_root / "artifacts" / "experiments"

    goal = args.get("strategy_goal") if isinstance(args.get("strategy_goal"), dict) else {}
    goal_ref = (args.get("strategy_goal_id") or args.get("strategy_goal_ref")
                or goal.get("strategy_goal_id") or goal.get("name"))
    lb = args.get("lookback") or 20
    try:
        lb = int(lb)
    except (TypeError, ValueError):
        lb = 20

    synth = synthesize_strategy_code(
        market=args.get("market"),
        asset_class=args.get("asset_class") or goal.get("asset_class"),
        strategy_name=args.get("strategy_name") or (goal.get("name") if goal else None),
        benchmark=args.get("benchmark") or (goal.get("benchmark") if goal else None),
        strategy_goal_ref=str(goal_ref) if goal_ref else None,
        lookback=lb,
        llm_client=llm_client,
    )

    # M1 诚实：捕获用户的组装意图（factor_set/model_id/signal_id/portfolio_id/cost_preset）。
    # DS-1 合成器尚未把这些注入策略码（只按 market 套确定性动量模板）——绝不静默丢弃这层意图：
    # 落进 run metadata 可追溯，并在返回 note 里诚实披露「回测的是模板基线、组装被记录但未注入」。
    assembly_inputs: dict[str, Any] = {}
    for _k in ("factor_set", "factor_set_id", "model_id", "signal_id", "portfolio_id", "cost_preset"):
        _v = args.get(_k)
        if _v is not None and _v != "" and _v != [] and _v != {}:
            assembly_inputs[_k] = _v
    has_assembly = bool(assembly_inputs)

    # §16 执行诚实：DS-1 合成器仍按 market 套确定性动量模板、未把组装注入策略码（assembly_injected 恒 False）。
    # 故用户做了组装却走 promote 时，回测的是模板基线而非所选组装——正撞 §16 致命「未注入资产却声称已采用 /
    # 模板基线冒充生产」。把这层执行诚实映射成 execution_blocks（template+production）落进 run.json，让组装器→
    # evaluate_release 的 R4/R5 硬拒（门有牙）。未来 DS-1 真注入后置 assembly_injected=True，helper 自然改出
    # live+source 块（R3 满足）。无组装 → helper 返回 None → promote 不写该键（向后兼容）。
    assembly_injected = False
    execution_blocks = _synth_execution_blocks(
        market=synth.market, has_assembly=has_assembly, assembly_injected=assembly_injected,
    )

    # §3 诚实：样本未捆 → 显式失败（绝不伪造回测）。错误信息清晰引导前端诚实展示（H1）。
    if not has_sample(synth.market, data_root=eff_root):
        return {
            "error": (
                f"market={synth.market} 的真行情样本未捆绑——不伪造回测（§3）。"
                "crypto 自带 BTC 样本即用；"
                "A股（stocks_cn）需设 TUSHARE_TOKEN 后跑 sample_data.bundle_hs300_daily 捆样本。"
            ),
            "market": synth.market,
            "needs_sample": True,
            "guidance": (
                "crypto 自带 BTC 样本即用；"
                "A股需设 TUSHARE_TOKEN 后跑 bundle_hs300_daily"
            ),
        }

    # 沙箱真跑（读 DATA_DIR 真样本产真净值）。
    sb = run_user_strategy(synth.code, extra_env={"DATA_DIR": str(eff_root)})
    ur = sb.user_result
    if not isinstance(ur, dict) or not ur.get("equity_curve"):
        return {
            "error": (
                f"合成策略未产出 equity_curve（沙箱 exit={sb.exit_code}）；"
                f"stderr: {(sb.stderr or '')[:400]}"
            ),
            "synthesis_method": synth.method,
        }

    # 落 RUN_ROOT 单一契约。沙箱 emit_result 是 caller-controlled；这里不把它写入
    # confirmatory overfit ledger，正式证据须由 canonical run/data lineage 另行晋级。
    try:
        owner = str(owner_user_id or "").strip()
        promoted = promote_ide_run(
            ide_run_id=f"agentbt_{synth.market}",
            owner_username=owner,
            owner_user_id=owner,
            strategy_name=synth.strategy_name,
            strategy_code=synth.code,
            result=ur,
            record_name=f"{synth.strategy_name} · agent 对话回测",
            run_root=run_root,
            # M1：把用户组装意图落进 run.json（assembly_inputs），不静默丢弃。
            extra_metadata=(assembly_inputs or None),
            # §16：把执行诚实块（未注入=template+production）落进 run.json，供组装器→R4/R5 硬拒模板冒充。
            execution_blocks=execution_blocks,
            market_data_use_validation_refs=validation_refs,
        )
    except PromoteError as exc:
        return {"error": f"落盘 promote 失败: {exc}", "synthesis_method": synth.method}

    out: dict[str, Any] = {
        "run_id": promoted.run_id,
        "market": synth.market,
        "benchmark": synth.benchmark,
        "strategy_name": synth.strategy_name,
        "synthesis_method": synth.method,
        "market_data_use_validation_refs": list(validation_refs),
        "metrics": {
            k: promoted.metrics[k]
            for k in ("sharpe", "total_return", "max_drawdown", "annualized_return", "volatility")
            if k in promoted.metrics
        },
        "source": "synthesized_backtest_run",
        "note": (
            "agent 对话回测产真 run（RUN_ROOT 契约·真净值·读真捆绑样本）；run_id 可贯穿裁决/paper。"
        ),
    }
    # M1 诚实披露：用户做了组装但 DS-1 合成器尚未注入 → 回测的是模板基线，不假装回测了组装。
    if has_assembly:
        out["assembly_inputs"] = assembly_inputs
        out["assembly_injected"] = False
        out["note"] = (
            f"本回测为 {synth.market} 动量模板基线（DS-1 合成器尚未注入所选因子/模型组装）；"
            "已记录你的组装于 metadata（run.json assembly_inputs），组装注入见后续。"
        )
    if promoted.gate_verdict is not None:
        out["overfit"] = {
            "color": promoted.gate_verdict.get("color"),
            "pbo": promoted.gate_verdict.get("pbo"),
            "dsr": promoted.metrics.get("dsr"),
            "honest_n": promoted.gate_verdict.get("honest_n"),
            "config_hash": promoted.gate_verdict.get("config_hash"),
        }
    # 顺手投影裁决（单一源 run_verdict；措辞守门走 Verifier，未验证不假绿灯）。
    if verdict_store is not None and verifier is not None:
        try:
            from ..run_verdict import project_verdict

            vp = project_verdict(promoted.run_id, verdict_store=verdict_store, verifier=verifier)
            out["verdict"] = vp.get("verdict")
            out["verdictNote"] = vp.get("verdictNote")
            out["has_authoritative_verdict"] = vp.get("has_authoritative_verdict")
        except Exception:  # noqa: BLE001  投影失败不阻断 run_id 返回（防御）。
            pass
    return out


def register_business_tools(
    runtime,
    *,
    hypothesis_store,
    factor_registry,
    model_registry,
    run_store=None,
    experiment_store=None,
    verdict_store=None,
    verifier=None,
    ledger=None,
    returns_store=None,
    data_root=None,
    llm_client=None,
    market_data_registry=None,
    owner_user_id: str | None = None,
) -> None:
    """把策略台脊柱业务工具注册进 AgentRuntime（全部 side_effect="none"）。

    入参全是 main.py 的既有单例（依赖注入，便于测试替身）。任何写动作（promote/动钱）
    都不在此——这些 handler 只读/只写本地可重置产物。

    DS-1 脊梁（Fork3=A）新增注入：
      · ledger / returns_store —— promote 落 RUN_ROOT 时跑多证据三角 gate（honest-N 单一源）。
      · data_root —— 真行情样本位置 + run_root 派生的单旋钮（缺省 paths.DATA_ROOT；测试可注入 tmp）。
      · llm_client —— 合成器 LLM 路 seam（缺省 None 走确定性模板；DS-2 注入真客户端）。
      · owner_user_id —— 由认证入口注入的稳定用户 id；工具参数中的 owner 字段不参与授权。
    全部有默认值 → 既有调用方（只传 3 store 的测试）不受影响（扩展不替换）。
    """

    authenticated_owner_user_id = str(owner_user_id or "").strip() or None

    # ── 1. hypothesis.create：建可证伪假设卡（exploratory 默认，P2 不挡探索） ──
    def _hypothesis_create(_n: str, args: dict) -> dict[str, Any]:
        goal_ref = args.get("goal_ref") or args.get("strategy_goal_id") or args.get("strategy_goal_ref")
        if not goal_ref:
            return {"error": "需要 goal_ref（strategy_goal 引用）"}
        # 探索卡：falsifiable 可空（create 永不校验可证伪性，冻结时才强制——HypothesisCardStore 契约）。
        # layer 钉死 exploratory：策略台 agent 只立探索假设，confirmatory 冻结是端点层人工动作。
        falsifiable = args.get("falsifiable") if isinstance(args.get("falsifiable"), dict) else None
        try:
            card = hypothesis_store.create(
                strategy_goal_ref=str(goal_ref),
                layer="exploratory",
                falsifiable=falsifiable,
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": f"{type(exc).__name__}: {exc}"}
        return {
            "card_id": card.card_id,
            "strategy_goal_ref": card.strategy_goal_ref,
            "layer": card.layer,
            "status": card.status,
            "note": "exploratory 假设卡已建；confirmatory 冻结（三必填+一次性OOS）是端点层人工动作，agent 不冻结。",
        }

    # ── 2. factor_set.compose：从因子台选 QUALIFIED+ 因子组（血统门，绝不在策略台造因子） ──
    _QUALIFIED_OK = {"QUALIFIED", "PROBATION", "OBSERVATION"}  # QUALIFIED 及以上可选用

    def _factor_set_compose(_n: str, args: dict) -> dict[str, Any]:
        requested = args.get("factor_ids")
        if isinstance(requested, str):
            requested = [s.strip() for s in requested.split(",") if s.strip()]
        all_factors = factor_registry.list()
        # 血统门（R17/GOAL §3）：只选用 state>=QUALIFIED 的因子；策略台不造因子。
        qualified = {f.factor_id: f for f in all_factors if f.lifecycle_state in _QUALIFIED_OK}
        if requested:
            selected_ids = [fid for fid in requested if fid in qualified]
            rejected = [
                {"factor_id": fid,
                 "reason": ("未注册" if fid not in {f.factor_id for f in all_factors}
                            else f"血统不足（state={qualified.get(fid) and qualified[fid].lifecycle_state or next((f.lifecycle_state for f in all_factors if f.factor_id == fid), '?')}，须 ≥QUALIFIED）")}
                for fid in requested if fid not in qualified
            ]
        else:
            selected_ids = sorted(qualified.keys())
            rejected = []
        members = [
            {"factor_id": fid, "state": qualified[fid].lifecycle_state,
             "ic_summary": qualified[fid].ic_summary}
            for fid in selected_ids
        ]
        fs_id = _short_id("fs", sorted(selected_ids))
        return {
            "factor_set_id": fs_id,
            "lineage": "← 因子台 · filter state>=QUALIFIED",
            "members": members,
            "count": len(members),
            "rejected": rejected,
            "note": "只选用 QUALIFIED+ 因子（血统门）；策略台不在此造因子。被拒因子血统弱点一等呈现（R25）。",
        }

    # ── 3. model_registry.select（只读）：从 Model台选已发布模型，绝不训练/翻 stage ──
    def _model_registry_select(_n: str, args: dict) -> dict[str, Any]:
        model_id = args.get("model_id") or args.get("model")
        want_stage = args.get("stage")
        if authenticated_owner_user_id is None:
            return {"error": "Model台查询需要认证 owner_user_id"}
        if not model_id:
            # 无指定 → 列出可选模型（只读浏览）。
            return {
                "models": model_registry.list_models(
                    owner_user_id=authenticated_owner_user_id
                ),
                "note": "只读浏览 Model台已注册模型；选用须给 model_id。训练/翻 stage 去 Model台（写动作经审批门）。",
            }
        versions = model_registry.list_versions(
            str(model_id),
            owner_user_id=authenticated_owner_user_id,
        )
        if not versions:
            return {"error": f"Model台无此模型: {model_id}"}
        # 血统门：策略台只引用 staging/production 的已发布模型（dev 是探索通道，不该直接进策略组装）。
        publishable = [v for v in versions if v.stage in ("staging", "production")]
        pool = [v for v in versions if (want_stage is None or v.stage == want_stage)]
        chosen = None
        candidates = publishable if publishable else []
        if want_stage:
            candidates = [v for v in versions if v.stage == want_stage]
        if candidates:
            chosen = max(candidates, key=lambda v: v.version)
        return {
            "model_id": str(model_id),
            "selected_version": chosen.version if chosen else None,
            "selected_stage": chosen.stage if chosen else None,
            "metrics": chosen.metrics if chosen else None,
            "lineage": f"← Model台 · {chosen.stage if chosen else '未选出'}",
            "available": [{"version": v.version, "stage": v.stage} for v in pool],
            "readonly": True,
            "note": ("只引用 model_id，不在策略台训练（重训去 Model台）；翻 stage 是写动作、经审批门 approver≠creator。"
                     if chosen else
                     "未选出已发布版本（staging/production）；dev 版不进策略组装，请先在 Model台晋级（经审批门）。"),
        }

    # ── 4. signal.define：模型分 → 可交易信号规则（fuse_signals 真融合，无副作用） ──
    def _signal_define(_n: str, args: dict) -> dict[str, Any]:
        rule = args.get("rule") or "rank(score) top decile"
        rebalance = args.get("rebalance") or "weekly_fri"
        top_pct = args.get("top_pct")
        try:
            top_pct = float(top_pct) if top_pct is not None else 0.10
        except (TypeError, ValueError):
            top_pct = 0.10
        long_only = bool(args.get("long_only", True))
        # 真跑一次 fuse_signals 做规则自检（确定性小样本，证明信号管线接通、非占位 queued）。
        import polars as pl

        from ..signals.core import fuse_signals

        try:
            demo = pl.DataFrame({"symbol": ["a", "b", "c", "d"], "score": [0.8, 0.2, -0.3, 0.5]})
            fused = fuse_signals(demo, score_col="score", long_only=long_only)
            directions = fused["direction"].to_list()
            n_long = sum(1 for d in directions if d == "long")
        except Exception as exc:  # noqa: BLE001
            return {"error": f"signal fuse 自检失败: {type(exc).__name__}: {exc}"}
        sig_id = _short_id("sig", rule, rebalance, top_pct, long_only)
        return {
            "signal_id": sig_id,
            "rule": rule,
            "rebalance": rebalance,
            "top_pct": top_pct,
            "direction": "long_only" if long_only else "long_short",
            "fuse_selftest": {"directions": directions, "n_long": n_long},
            "note": "信号规则已定义并通过 fuse_signals 自检（模型分→方向/强度/置信度三元组）。",
        }

    # ── 5. portfolio.construct：风控+组合构建（optimizers 真权重，无副作用） ──
    def _portfolio_construct(_n: str, args: dict) -> dict[str, Any]:
        # sizing 缺省【仅 key 缺失】才补 equal_weight（codex floor R3 #2：旧 `or` 让 ""/None/0/[]/{}
        # 等 falsey 非法值也静默退等权·回显原串）；任何显式值都过白名单 fail-closed（codex R2 #6）。
        sizing = args.get("sizing", "equal_weight")
        if sizing not in ("equal_weight", "risk_parity", "equal_risk"):
            return {"error": f"未知 sizing={sizing!r}（仅 equal_weight / risk_parity / equal_risk）"}
        symbols = args.get("symbols")
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbols:
            symbols = ["s1", "s2", "s3", "s4"]
        # max_pos/dd_halt：仅 key 缺失才补缺省（codex floor R4 #4：显式 None 不算缺失·bool 不当数值）；
        # 显式 None/bool/非数值/非有限/越界 → fail-closed error（codex R3 #3：不静默换 0.03 却标 requested·谎报）。
        if "max_pos" not in args:
            max_pos = 0.03
        else:
            mp = args["max_pos"]
            if mp is None or isinstance(mp, bool):
                return {"error": f"max_pos 非法: {mp!r}（须 0<x≤1 数值）"}
            try:
                max_pos = float(mp)
            except (TypeError, ValueError):
                return {"error": f"max_pos 非数值: {mp!r}"}
            if not (np.isfinite(max_pos) and 0.0 < max_pos <= 1.0):
                return {"error": f"max_pos 越界（须 0<max_pos≤1）: {max_pos}"}
        if "dd_halt" not in args:
            dd_halt = 0.20
        else:
            dh = args["dd_halt"]
            if dh is None or isinstance(dh, bool):
                return {"error": f"dd_halt 非法: {dh!r}（须 0<x≤1 数值）"}
            try:
                dd_halt = float(dh)
            except (TypeError, ValueError):
                return {"error": f"dd_halt 非数值: {dh!r}"}
            if not (np.isfinite(dd_halt) and 0.0 < dd_halt <= 1.0):
                return {"error": f"dd_halt 越界（须 0<dd_halt≤1）: {dd_halt}"}
        from ..portfolio.optimizers import equal_risk_contribution, equal_weight, risk_parity

        import pandas as pd

        note = "风控+组合已构建（真权重 + 单票上限/回撤熔断约束）。进场与否、监控由模拟台决定（D-PERM 止于模拟盘）。"
        # covariance_source 诚实披露（codex floor R2 #2）：risk_parity/equal_risk 用 synthetic demo 协方差
        # （60 条 IID 随机·非真标的收益·非 PIT），据实标注、绝不冒充真数据；equal_weight 不需协方差。
        cov_source = "none"
        # risk_limits 诚实（codex floor R2 #3）：equal_risk 不施 post-hoc cap（破 RC）→ 报 requested +
        # enforced=False，不混进已生效风控；capped 路径 enforced=True。
        risk_limits = {"max_position": max_pos, "drawdown_halt": dd_halt, "max_position_enforced": True}
        try:
            if sizing == "equal_risk":
                # 真 ERC（等风险贡献·命门绑定 spine_binding）。⚠️ 不施 post-hoc 单票上限——截断权重会破坏
                # RC 相等（codex floor R1 #2：约束 ERC 待实现·登记 follow-on）；返回纯 long-only ERC。
                rng = np.random.default_rng(7)
                rets = pd.DataFrame(rng.normal(0, 0.01, size=(60, len(symbols))), columns=symbols)
                weights = equal_risk_contribution(rets.cov())
                capped = weights  # 不 cap，保等风险贡献不变量
                cov_source = "synthetic_demo"
                risk_limits = {
                    "requested_max_position": max_pos,
                    "max_position_enforced": False,  # 未施：post-hoc 截断会破坏 ERC 的 RC 相等
                    "drawdown_halt": dd_halt,
                }
                note = (
                    "真 ERC（等风险贡献·long-only 全额）已构建于 synthetic demo 协方差（非真标的收益）。"
                    "⚠️ 未施单票上限：post-hoc 截断会破坏 RC 相等（约束 ERC 待实现）。进场/监控由模拟台决定（D-PERM）。"
                )
            else:
                if sizing == "risk_parity":
                    # inverse-volatility 启发式（**非**真 ERC·见 optimizers.inverse_volatility 诚实边界）。
                    rng = np.random.default_rng(7)
                    rets = pd.DataFrame(rng.normal(0, 0.01, size=(60, len(symbols))), columns=symbols)
                    weights = risk_parity(rets.cov())
                    cov_source = "synthetic_demo"
                    note = (
                        "inverse-volatility 启发式（非真 ERC）已构建于 synthetic demo 协方差（非真标的收益）+ "
                        "单票上限/回撤熔断约束。进场/监控由模拟台决定（D-PERM 止于模拟盘）。"
                    )
                else:
                    weights = equal_weight(symbols)
                # 应用单票上限（风控约束真生效，非装饰）。
                capped = {s: min(w, max_pos) for s, w in weights.items()}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"portfolio 优化失败: {type(exc).__name__}: {exc}"}
        pf_id = _short_id("pf", sorted(symbols), sizing, max_pos, dd_halt)
        return {
            "portfolio_id": pf_id,
            "sizing": sizing,
            "weights": capped,
            "covariance_source": cov_source,
            "risk_limits": risk_limits,
            "note": note,
        }

    # ── 5b. portfolio.gate（C · D-WAVE1A）：组合层多证据三角守门预览（复用单一源 gate，无副作用、不记账） ──
    def _portfolio_gate(_n: str, args: dict) -> dict[str, Any]:
        from ..portfolio.gate import gate_portfolio

        weights = args.get("weights") or {}
        if not isinstance(weights, dict) or not weights:
            return {"error": "portfolio.gate 需 weights={symbol: weight}（先 portfolio.construct）"}
        asset_returns = args.get("asset_returns") or {}
        if not isinstance(asset_returns, dict) or not asset_returns:
            return {"error": "portfolio.gate 需 asset_returns={symbol: [逐期已实现收益]}（先 backtest.run 各成分）"}
        markets = args.get("markets") or []
        if isinstance(markets, str):
            markets = [m.strip() for m in markets.split(",") if m.strip()]
        pid = args.get("portfolio_id") or _short_id("pf", sorted(weights), "gate")
        try:
            res = gate_portfolio(
                portfolio_id=str(pid),
                weights={str(k): float(v) for k, v in weights.items()},
                asset_returns={str(k): [float(x) for x in v] for k, v in asset_returns.items()},
                markets=markets,
                freq=str(args.get("freq") or "1d"),
                record=False,
            )
        except Exception as exc:  # noqa: BLE001
            return {"error": f"组合 gate 失败: {type(exc).__name__}: {exc}"}
        v = res.verdict
        # ③ 组合成分独立 bet 计数（descriptor·**只读·不改 gate verdict**）：相关成分坍缩成同一 bet、
        #    同族不重复计独立性（复用**锁定** n_eff 口径）。接组合三角呈现；**绝不**喂 DSR 的 honest_n 通缩
        #    （那是过拟合保守端兜底、honest-N 不可改小——本计数是 descriptor、非 deflation floor）。
        independent_bets = None
        try:
            from ..portfolio.independence import independent_bet_count

            w_norm = {str(k): float(x) for k, x in weights.items()}
            ar_norm = {str(k): [float(z) for z in seq] for k, seq in asset_returns.items()}
            held_syms = [s for s in w_norm if s in ar_norm and ar_norm[s]]
            if held_syms:
                length = min(len(ar_norm[s]) for s in held_syms)
                if length > 0:
                    mat = np.array([[ar_norm[s][t] for s in held_syms] for t in range(length)], dtype=float)
                    wv = np.array([w_norm[s] for s in held_syms], dtype=float)
                    neff = independent_bet_count(mat, weights=wv)
                    independent_bets = {
                        "point": neff.point, "low": neff.low, "high": neff.high,
                        "n_held": neff.n_observed, "disclaimer": neff.disclaimer,
                    }
        except Exception:  # noqa: BLE001  # descriptor 失败绝不拖垮 gate 预览
            independent_bets = None
        return {
            "portfolio_id": str(pid),
            "color": v.color,
            "pbo": v.pbo,
            "dsr_conservative": v.dsr_conservative,
            "bootstrap_ci": list(v.bootstrap_ci),
            "honest_n": res.honest_n,
            "independent_bets": independent_bets,
            "config_hash": res.config_hash,
            "verdict_phrasing": v.verdict_phrasing,
            "note": "组合层多证据三角守门（预览/只读、不记账）。冷启动 PBO=N/A，A2 凭 DSR+CI 双正放行、过拟合仍 red；honest-N 记账走 promote 治理流。independent_bets=组合成分独立 bet 计数（去重族数·descriptor·不改 verdict·不喂 honest_n）。",
        }

    # ── 6. backtest.run（真实引擎）：组装→回测产 run 摘要（无副作用，本地 run 目录可重置） ──
    def _backtest_run(_n: str, args: dict) -> dict[str, Any]:
        # 优先：若给定既有 run_id，投影真 run 摘要（接 run_verdict 单一源）。
        run_id = args.get("run_id")
        if run_id and verdict_store is not None and verifier is not None:
            validation_refs = _market_data_use_validation_refs(
                args,
                market_data_registry,
                owner_user_id=authenticated_owner_user_id,
                operation="backtest.run existing run projection",
                require_dataset_timing=True,
                allowed_use_contexts=("backtest", "confirmatory_validation"),
            )
            if isinstance(validation_refs, dict):
                return validation_refs
            try:
                from ..run_verdict import project_overfit, project_verdict

                verdict = project_verdict(str(run_id), verdict_store=verdict_store, verifier=verifier)
                overfit = project_overfit(str(run_id))
                return {
                    "run_id": str(run_id),
                    "verdict": verdict.get("verdict"),
                    "verdictNote": verdict.get("verdictNote"),
                    "overfit": {"pbo": overfit.get("pbo"), "dsr": overfit.get("dsr"),
                                "gate_label": overfit.get("gate_label")},
                    "source": "projected_existing_run",
                    "market_data_use_validation_refs": list(validation_refs),
                    "note": "回测摘要由 run_verdict 投影（裁决措辞走 Verifier._verdict_note，未验证不假绿灯）。",
                }
            except FileNotFoundError:
                pass  # 落到组装登记分支
            except Exception as exc:  # noqa: BLE001
                return {"error": f"run 投影失败: {type(exc).__name__}: {exc}"}
        # 否则（无既有 run_id）：DS-1 脊梁——合成最小策略 → 沙箱跑真样本 → promote 落 RUN_ROOT 产真 run_id。
        # 消灭 RunStore 占位（status=running 无净值的空 run）；run_id 自然贯穿裁决/paper（Fork3=A 单一注册表）。
        return _synth_and_promote(
            args=args,
            ledger=ledger,
            returns_store=returns_store,
            data_root=data_root,
            verdict_store=verdict_store,
            verifier=verifier,
            llm_client=llm_client,
            market_data_registry=market_data_registry,
            owner_user_id=authenticated_owner_user_id,
        )

    # ── 7. eval.pbo（真实计算）：CSCV → PBO（复用 eval.pbo 单一源，无副作用） ──
    def _eval_pbo(_n: str, args: dict) -> dict[str, Any]:
        from ..eval.pbo import cscv_pbo

        matrix = args.get("returns_matrix")
        s_blocks = args.get("s_blocks") or 8
        max_combinations = args.get("max_combinations") or 200
        try:
            s_blocks = int(s_blocks)
            max_combinations = int(max_combinations)
        except (TypeError, ValueError):
            return {"error": "s_blocks/max_combinations 必须是整数"}
        if matrix is None:
            # 无矩阵 → 确定性示例矩阵（证明 CSCV 管线接通、非占位）。
            rng = np.random.default_rng(11)
            arr = rng.normal(0, 0.01, size=(s_blocks * 4, 12))
        else:
            try:
                arr = np.asarray(matrix, dtype=float)
            except Exception as exc:  # noqa: BLE001
                return {"error": f"returns_matrix 非法: {exc}"}
        result = cscv_pbo(arr, s_blocks=s_blocks, max_combinations=max_combinations)
        out = result.to_dict()
        out["note"] = "PBO 由 eval.pbo CSCV 真算（López de Prado）；衡量策略选择程序的过拟合概率，非单策略好坏。"
        out["used_demo_matrix"] = matrix is None
        return out

    # ── 8. report.generate（真实报告）：run → markdown 报告（裁决措辞守门走单一源） ──
    def _report_generate(_n: str, args: dict) -> dict[str, Any]:
        run_id = args.get("run_id")
        if not run_id:
            return {"error": "需要 run_id"}
        validation_refs = _market_data_use_validation_refs(
            args,
            market_data_registry,
            owner_user_id=authenticated_owner_user_id,
            operation="report.generate",
            require_dataset_timing=True,
            allowed_use_contexts=("backtest", "confirmatory_validation"),
        )
        if isinstance(validation_refs, dict):
            return validation_refs
        if verdict_store is None or verifier is None:
            return {"error": "report.generate 需注入 verdict_store + verifier（措辞守门单一源）"}
        try:
            from ..run_verdict import project_cost_sensitivity, project_overfit, project_verdict

            verdict = project_verdict(str(run_id), verdict_store=verdict_store, verifier=verifier)
            overfit = project_overfit(str(run_id))
            cost = project_cost_sensitivity(str(run_id))
        except FileNotFoundError as exc:
            return {"error": f"run 不存在: {exc}"}
        except Exception as exc:  # noqa: BLE001
            return {"error": f"报告投影失败: {type(exc).__name__}: {exc}"}
        lines = [
            f"# {run_id} · 回测报告",
            "",
            "## 裁决",
            f"- verdict: {verdict.get('verdict')}",
            f"- {verdict.get('verdictNote')}",  # 措辞守门：Verifier._verdict_note 供给（禁可信/安全/排除过拟合）
            "",
            "## 过拟合门",
            f"- PBO {overfit.get('pbo')} / DSR {overfit.get('dsr')} · {overfit.get('gate_label')}",
            "",
            "## 成本敏感性（派生区间，非独立重跑）",
        ]
        for cell in cost.get("cost", []):
            lines.append(f"- {cell['preset']}: sharpe {cell['sharpe']} · excess {cell['excess']}")
        lines += [
            "",
            "## 数据使用证明",
            "- MarketDataUse validation refs: " + ", ".join(validation_refs),
            "- 这些 refs 已在报告生成前回查 accepted/no-violation 和 DatasetSemantics PIT/bitemporal timing refs。",
            "",
            "## 交接",
            "策略台终点。候选策略可提交模拟台，进场与监控由模拟台决定。",
        ]
        return {
            "run_id": str(run_id),
            "markdown": "\n".join(lines),
            "verdict": verdict.get("verdict"),
            "has_authoritative_verdict": verdict.get("has_authoritative_verdict"),
            "market_data_use_validation_refs": list(validation_refs),
            "note": "报告裁决措辞由 Verifier._verdict_note 守门（禁绝对化措辞 R7）；未验证不当 pass。",
        }

    # 全部 side_effect="none"（本地可重置、不动钱、不外发单）——治理门钉端点层（D-PERM）。
    runtime.register_tool("hypothesis.create", _hypothesis_create, side_effect="none")
    runtime.register_tool("factor_set.compose", _factor_set_compose, side_effect="none")
    runtime.register_tool("model_registry.select", _model_registry_select, side_effect="none")
    runtime.register_tool("signal.define", _signal_define, side_effect="none")
    runtime.register_tool("portfolio.construct", _portfolio_construct, side_effect="none")
    runtime.register_tool("portfolio.gate", _portfolio_gate, side_effect="none")
    runtime.register_tool("backtest.run", _backtest_run, side_effect="none")
    runtime.register_tool("eval.pbo", _eval_pbo, side_effect="none")
    runtime.register_tool("report.generate", _report_generate, side_effect="none")


__all__ = ["register_business_tools"]
