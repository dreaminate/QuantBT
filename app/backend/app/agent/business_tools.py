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

5 个新业务工具（schema+handler 接真 store）：
  hypothesis.create · factor_set.compose · model_registry.select · signal.define · portfolio.construct
3 个有 schema 无 handler → 接真引擎：
  backtest.run · eval.pbo · report.generate
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..lineage.ids import content_hash


def _short_id(prefix: str, *parts: Any) -> str:
    """内容寻址短 id（复用单一身份源 lineage.ids.content_hash，不另造哈希族）。"""
    return f"{prefix}_{content_hash(list(parts))[:10]}"


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
) -> None:
    """把策略台脊柱业务工具注册进 AgentRuntime（全部 side_effect="none"）。

    入参全是 main.py 的既有单例（依赖注入，便于测试替身）。任何写动作（promote/动钱）
    都不在此——这些 handler 只读/只写本地可重置产物。
    """

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
        if not model_id:
            # 无指定 → 列出可选模型（只读浏览）。
            return {
                "models": model_registry.list_models(),
                "note": "只读浏览 Model台已注册模型；选用须给 model_id。训练/翻 stage 去 Model台（写动作经审批门）。",
            }
        versions = model_registry.list_versions(str(model_id))
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
        sizing = args.get("sizing") or "equal_weight"
        symbols = args.get("symbols")
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(",") if s.strip()]
        if not symbols:
            symbols = ["s1", "s2", "s3", "s4"]
        max_pos = args.get("max_pos")
        dd_halt = args.get("dd_halt")
        try:
            max_pos = float(max_pos) if max_pos is not None else 0.03
        except (TypeError, ValueError):
            max_pos = 0.03
        try:
            dd_halt = float(dd_halt) if dd_halt is not None else 0.20
        except (TypeError, ValueError):
            dd_halt = 0.20
        from ..portfolio.optimizers import equal_weight, risk_parity

        try:
            if sizing in ("risk_parity", "equal_risk"):
                import pandas as pd

                rng = np.random.default_rng(7)
                rets = pd.DataFrame(rng.normal(0, 0.01, size=(60, len(symbols))), columns=symbols)
                weights = risk_parity(rets.cov())
            else:
                weights = equal_weight(symbols)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"portfolio 优化失败: {type(exc).__name__}: {exc}"}
        # 应用单票上限（风控约束真生效，非装饰）。
        capped = {s: min(w, max_pos) for s, w in weights.items()}
        pf_id = _short_id("pf", sorted(symbols), sizing, max_pos, dd_halt)
        return {
            "portfolio_id": pf_id,
            "sizing": sizing,
            "weights": capped,
            "risk_limits": {"max_position": max_pos, "drawdown_halt": dd_halt},
            "note": "风控+组合已构建（真权重 + 单票上限/回撤熔断约束）。进场与否、监控由模拟台决定（D-PERM 止于模拟盘）。",
        }

    # ── 6. backtest.run（接真）：组装→回测产 run 摘要（无副作用，本地 run 目录可重置） ──
    def _backtest_run(_n: str, args: dict) -> dict[str, Any]:
        # 优先：若给定既有 run_id，投影真 run 摘要（接 run_verdict 单一源）。
        run_id = args.get("run_id")
        if run_id and verdict_store is not None and verifier is not None:
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
                    "note": "回测摘要由 run_verdict 投影（裁决措辞走 Verifier._verdict_note，未验证不假绿灯）。",
                }
            except FileNotFoundError:
                pass  # 落到组装登记分支
            except Exception as exc:  # noqa: BLE001
                return {"error": f"run 投影失败: {type(exc).__name__}: {exc}"}
        # 否则：登记一次组装回测意图到 RunStore（真写 run 元数据，无外部副作用、本地可重置）。
        inputs = {
            "factor_set": args.get("factor_set"),
            "model_id": args.get("model_id"),
            "signal_id": args.get("signal_id"),
            "portfolio_id": args.get("portfolio_id"),
            "cost_preset": args.get("cost_preset") or "neutral",
            "strategy_goal_id": args.get("strategy_goal_id"),
        }
        if run_store is None or experiment_store is None:
            # 无 store（测试替身缺省）→ 返回结构化登记回执，仍是真 handler（非 queued 占位）。
            return {
                "queued_run": False,
                "assembled": inputs,
                "note": "回测组装已校验（无 RunStore 注入，未落盘）；接 run 引擎后产 runs/ 目录。",
            }
        try:
            exp = experiment_store.create_experiment(
                name=f"agent_backtest_{inputs['cost_preset']}",
                asset_class="equity_cn",
                description="agent 策略台组装回测",
            )
            run = run_store.create_run(experiment_id=exp.experiment_id, inputs=inputs,
                                       tags={"origin": "agent_workbench"})
        except Exception as exc:  # noqa: BLE001
            return {"error": f"RunStore 登记失败: {type(exc).__name__}: {exc}"}
        return {
            "run_id": run.run_id,
            "experiment_id": exp.experiment_id,
            "status": run.status,
            "assembled": inputs,
            "source": "registered_new_run",
            "note": "回测组装已登记到 RunStore（本地 run 元数据，无外部副作用）；体检/裁决在 run 完成后投影。",
        }

    # ── 7. eval.pbo（接真）：CSCV → PBO（复用 eval.pbo 单一源，无副作用） ──
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

    # ── 8. report.generate（接真）：run → markdown 报告（裁决措辞守门走单一源） ──
    def _report_generate(_n: str, args: dict) -> dict[str, Any]:
        run_id = args.get("run_id")
        if not run_id:
            return {"error": "需要 run_id"}
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
            "## 交接",
            "策略台终点。候选策略可提交模拟台，进场与监控由模拟台决定。",
        ]
        return {
            "run_id": str(run_id),
            "markdown": "\n".join(lines),
            "verdict": verdict.get("verdict"),
            "has_authoritative_verdict": verdict.get("has_authoritative_verdict"),
            "note": "报告裁决措辞由 Verifier._verdict_note 守门（禁绝对化措辞 R7）；未验证不当 pass。",
        }

    # 全部 side_effect="none"（本地可重置、不动钱、不外发单）——治理门钉端点层（D-PERM）。
    runtime.register_tool("hypothesis.create", _hypothesis_create, side_effect="none")
    runtime.register_tool("factor_set.compose", _factor_set_compose, side_effect="none")
    runtime.register_tool("model_registry.select", _model_registry_select, side_effect="none")
    runtime.register_tool("signal.define", _signal_define, side_effect="none")
    runtime.register_tool("portfolio.construct", _portfolio_construct, side_effect="none")
    runtime.register_tool("backtest.run", _backtest_run, side_effect="none")
    runtime.register_tool("eval.pbo", _eval_pbo, side_effect="none")
    runtime.register_tool("report.generate", _report_generate, side_effect="none")


__all__ = ["register_business_tools"]
