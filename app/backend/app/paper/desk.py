"""模拟台后端服务层（P2 · /api/paper/* 的引擎聚合，不重造）。

把已建引擎拼成模拟台一层：
- 多 run 注册表：每个 run = 一个 PaperScheduler(PaperVenue) 实例（复用 scheduler.py / paper_venue.py）。
- 持仓 / 成交 / 余额 / 净值：直接读 venue.snapshot / ExecutionAuditLog(paper_fill) / equity log，不另存第二份。
- 晋级判定聚合：4 门（≥28 天 / 模拟段超额>0 / 风险门 0 违规 / 实盘衰减<阈值）只读派生，绝不在此自动晋级。
- 人工审批晋级：approver≠creator + 验证背书（INV-5），复用 approval 异常族；动钱/晋级永不暴露为 agent tool。
- 风险门发布冻结哈希 + append-only 违规链：门限发布时 content_hash 冻结；会话内改门请求被拒并入哈希链
  （hash 链=前一条 hash + 本条内容，篡改/重排即断链）。本地门=防篡改【证据】非防篡改（TCB 诚实声明）。

治理铁律（与 enforcer/policy/verifier 单一源一致）：
- A股永不 live：下单一律走 OrderGuard，A股映射 TrustTier.PAPER，live 下单端点恒拒（致命错误防线）。
- 裁决/note 措辞守门走 verifier._verdict_note（禁「可信/安全/排除过拟合」），本模块不自造合规结论文案。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..execution.base import ExecutionAuditLog
from ..execution.paper_venue import PaperVenue
from ..lineage.ids import content_hash
from .replay_provider import (
    ReplayBarProvider,
    make_bar_provider,
    make_mark_provider,
    seed_positions,
)
from .scheduler import MarketKind, PaperScheduler, PaperSchedulerConfig


# ── 晋级判定阈值（参数化，与 factor_factory.lifecycle 语义一致：模拟 1 月 > 基准）──
PROMO_MIN_DAYS = 28
PROMO_MAX_DECAY = 0.30  # 实盘衰减门：>30% 即不合格（与设计稿「实盘衰减<30%」一致）


@dataclass
class PaperRunRecord:
    """一条模拟盘 run：scheduler/venue + 元数据 + 晋级/风险所需输入。"""

    run_id: str
    name: str
    origin: str
    market: MarketKind
    symbols: list[str]
    bench: str
    creator: str
    scheduler: PaperScheduler
    venue: PaperVenue
    equity_log_path: Path
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    # 晋级判定输入（由真实运行/对账填；初始保守=未达标，绝不假绿灯）
    days_running: int = 0
    paper_excess_return: float = 0.0
    backtest_annual: float = 0.0
    paper_annual: float = 0.0
    promoted: bool = False
    promotion_gate_id: str | None = None
    # 回放 provider（模拟 bar/mark 源，非实盘 key）。注入即 tick_once 真喂数据产净值；None=空壳。
    provider: ReplayBarProvider | None = None
    simulated_source: str | None = None  # 数据来源标注（bundled_sample_replay）——明确是模拟非实盘
    initial_cash: float = 1_000_000.0  # 注册时起始现金（prime_run 幂等重置基准）


class PaperRunNotFound(KeyError):
    """请求的 paper run 不存在。"""


class AShareLiveForbidden(Exception):
    """A股 live 下单：项目范围硬约束，永远拒绝（致命错误防线）。"""


class RiskGateMutationForbidden(Exception):
    """会话内试图改已冻结风险门：拒绝并入违规链（会话外不可改）。"""


# ════════════════════════════════════════════════════════════════════
# 风险门：发布冻结哈希 + append-only 违规哈希链
# ════════════════════════════════════════════════════════════════════
class FrozenRiskGate:
    """门限发布时冻结其内容哈希；会话内任何改门请求被拒并记入 append-only 哈希链。

    哈希链：每条记录 chain_hash = content_hash({prev, entry})；篡改任一历史项或重排都断链
    （verify_chain 复算即发现）。这是【防篡改证据】不是防篡改本体——单机 TCB 之外无硬保证。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._frozen: dict[str, str] = {}            # run_id → 冻结门内容哈希
        self._limits: dict[str, dict[str, Any]] = {} # run_id → 发布时门限快照（只读）
        self._chain: dict[str, list[dict[str, Any]]] = {}  # run_id → 违规/事件链

    def publish(self, run_id: str, limits: dict[str, Any]) -> str:
        """发布并冻结门限；返回冻结哈希。重复 publish 同 run 视为新发布世代（覆盖冻结）。"""

        with self._lock:
            frozen = content_hash({"run_id": run_id, "limits": limits})
            self._frozen[run_id] = frozen
            self._limits[run_id] = dict(limits)
            self._append(run_id, kind="gate_published", detail="门限发布并冻结哈希", payload={"frozen_hash": frozen})
            return frozen

    def frozen_hash(self, run_id: str) -> str | None:
        with self._lock:
            return self._frozen.get(run_id)

    def attempt_mutation(self, run_id: str, proposed: dict[str, Any], *, actor: str = "session") -> None:
        """会话内改门请求：恒拒，并把【被拒事件】入哈希链（不真改门）。

        raise RiskGateMutationForbidden —— 调用方（含 agent）拿不到「改门成功」。
        """

        with self._lock:
            if run_id not in self._frozen:
                raise PaperRunNotFound(run_id)
            self._append(
                run_id, kind="gate_mutation_denied",
                detail=f"会话内改门请求被拒（会话外不可改）：actor={actor}",
                payload={"proposed": proposed, "frozen_hash": self._frozen[run_id]},
            )
            raise RiskGateMutationForbidden(
                "风险门发布时已冻结，会话内永不可改；本请求被拒并记入违规链。"
            )

    def record_violation(self, run_id: str, *, title: str, detail: str) -> dict[str, Any]:
        """真实风险违规入链（如触线/熔断）。返回新增条目。"""

        with self._lock:
            if run_id not in self._frozen:
                raise PaperRunNotFound(run_id)
            return self._append(run_id, kind="violation", detail=detail, payload={"title": title})

    def chain(self, run_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._chain.get(run_id, [])]

    def violation_count(self, run_id: str) -> int:
        """真实违规计数（不含发布/被拒事件）——晋级「风险门 0 违规」门用。"""

        with self._lock:
            return sum(1 for e in self._chain.get(run_id, []) if e.get("kind") == "violation")

    def verify_chain(self, run_id: str) -> bool:
        """复算整链 hash；任一断裂返 False（篡改/重排自证）。"""

        with self._lock:
            prev = ""
            for e in self._chain.get(run_id, []):
                recomputed = content_hash({"prev": prev, "entry": _chain_body(e)})
                if recomputed != e.get("chain_hash"):
                    return False
                prev = e["chain_hash"]
            return True

    def _append(self, run_id: str, *, kind: str, detail: str, payload: dict[str, Any]) -> dict[str, Any]:
        chain = self._chain.setdefault(run_id, [])
        prev = chain[-1]["chain_hash"] if chain else ""
        body = {
            "seq": len(chain),
            "kind": kind,
            "detail": detail,
            "payload": payload,
            "at_utc": datetime.now(UTC).isoformat(),
        }
        entry = dict(body)
        entry["prev_hash"] = prev
        entry["chain_hash"] = content_hash({"prev": prev, "entry": body})
        chain.append(entry)
        return dict(entry)


def _chain_body(entry: dict[str, Any]) -> dict[str, Any]:
    """从链条目还原入哈希的 body（剔除链字段），供 verify_chain 复算。"""

    return {k: entry[k] for k in ("seq", "kind", "detail", "payload", "at_utc")}


# ════════════════════════════════════════════════════════════════════
# 晋级判定 + 人工审批门（INV-5）
# ════════════════════════════════════════════════════════════════════
@dataclass
class PromotionGate:
    gate_id: str
    run_id: str
    creator: str
    checks: list[dict[str, Any]]
    eligible: bool
    decision: Literal["pending", "approved"] = "pending"
    approver: str | None = None
    endorsement_ref: str | None = None   # 验证背书（verdict_id / 验证记录引用）——INV-5 必填
    reason: str | None = None
    decided_at_utc: str | None = None
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id, "run_id": self.run_id, "creator": self.creator,
            "checks": self.checks, "eligible": self.eligible, "decision": self.decision,
            "approver": self.approver, "endorsement_ref": self.endorsement_ref,
            "reason": self.reason, "decided_at_utc": self.decided_at_utc,
            "created_at_utc": self.created_at_utc,
        }


def aggregate_promotion_checks(
    rec: PaperRunRecord, risk: FrozenRiskGate, *, min_days: int = PROMO_MIN_DAYS,
    max_decay: float = PROMO_MAX_DECAY,
) -> tuple[list[dict[str, Any]], bool]:
    """4 门聚合（只读派生）：≥28 天 / 模拟段超额>0 / 风险门 0 违规 / 实盘衰减<阈值。

    返回 (checks, eligible)。eligible = 4 门全过。绝不在此晋级——这只是判定，不是动作。
    """

    decay = _decay(rec.backtest_annual, rec.paper_annual)
    violations = risk.violation_count(rec.run_id)
    checks = [
        {"key": "days", "label": "模拟运行满 1 个月（≥28 天）",
         "value": f"{rec.days_running} / {min_days} 天", "passed": rec.days_running >= min_days},
        {"key": "excess", "label": "模拟段年化 > 基准",
         "value": f"{rec.paper_excess_return:+.2%}", "passed": rec.paper_excess_return > 0},
        {"key": "zero_violation", "label": "风险门 0 违规",
         "value": ("全绿" if violations == 0 else f"{violations} 违规"), "passed": violations == 0},
        {"key": "decay", "label": f"实盘衰减 < {max_decay:.0%}",
         "value": (f"{decay:+.0%}" if decay is not None else "n/a"),
         "passed": decay is not None and decay > -max_decay},
    ]
    eligible = all(c["passed"] for c in checks)
    return checks, eligible


def _decay(backtest_annual: float, paper_annual: float) -> float | None:
    """实盘衰减 =(paper-bt)/|bt|。bt=0 不可算返 None（不当 pass）。负=劣化。"""

    if not backtest_annual:
        return None
    return (paper_annual - backtest_annual) / abs(backtest_annual)


class PaperDeskService:
    """模拟台聚合服务：多 run + 晋级门 + 风险门，全部复用既有引擎。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runs: dict[str, PaperRunRecord] = {}
        self._gates: dict[str, PromotionGate] = {}
        self.risk = FrozenRiskGate()
        self._gate_seq = 0

    # ----- run 注册 / 生命周期 -----
    def register_run(
        self, *, run_id: str, name: str, origin: str, market: MarketKind,
        symbols: list[str], bench: str, creator: str, equity_log_path: Path,
        cash: float = 1_000_000.0, days_running: int = 0,
        paper_excess_return: float = 0.0, backtest_annual: float = 0.0,
        paper_annual: float = 0.0, risk_limits: dict[str, Any] | None = None,
        simulate: bool = True,
    ) -> PaperRunRecord:
        """注册一条 paper run。simulate=True（默认）注入回放 provider + 建仓种子单：

        tick_once 真喂【捆绑样本 bars（模拟，非实盘 key）】撮合 → MTM 写出移动净值序列。
        simulate=False 留空壳（无 provider）——tick_once 返 0、净值不动（诚实：未喂数据即不假绿灯）。

        治理：本方法只建模拟台 run，不绕审批、不动钱、A股恒 paper（live 下单仍走 attempt_live_order 恒拒）。
        """

        with self._lock:
            audit = ExecutionAuditLog()
            venue = PaperVenue(cash=cash, equity_log_path=equity_log_path, audit=audit)
            cfg = PaperSchedulerConfig(strategy_id=run_id, symbols=list(symbols), market=market,
                                       equity_log_path=equity_log_path)
            provider: ReplayBarProvider | None = None
            bar_p = mark_p = None
            if simulate and symbols:
                # 回放 provider = 模拟 bar/mark 源（绝非实盘 key 取数；A股仍恒拒 live，仅模拟撮合）。
                provider = ReplayBarProvider(symbols=list(symbols))
                bar_p = make_bar_provider(provider)
                mark_p = make_mark_provider(provider)
                # 注入模拟建仓引子（非下单路径）：MTM 反映持仓盈亏 → 净值非空壳。
                seed_positions(venue, list(symbols))
            sched = PaperScheduler(venue, cfg, bar_provider=bar_p, mark_provider=mark_p)
            rec = PaperRunRecord(
                run_id=run_id, name=name, origin=origin, market=market, symbols=list(symbols),
                bench=bench, creator=creator, scheduler=sched, venue=venue,
                equity_log_path=equity_log_path, days_running=days_running,
                paper_excess_return=paper_excess_return, backtest_annual=backtest_annual,
                paper_annual=paper_annual, provider=provider,
                simulated_source=(provider.source if provider else None),
                initial_cash=cash,
            )
            self._runs[run_id] = rec
            # 注册即发布并冻结风险门（门限会话外不可改）。
            self.risk.publish(run_id, risk_limits or _default_risk_limits(market))
            return rec

    def prime_run(self, run_id: str, *, ticks: int = 16) -> dict[str, Any]:
        """幂等：把 run 复位到刚注册态后驱动 N 轮 tick（喂模拟 bars）+ MTM（写净值）产真净值序列。

        幂等性（复位再跑）：每次先 reset provider 游标 + 清 venue 持仓/现金 + 清空 equity_log + 归零计数，
        再跑同一确定性窗口 → 重复 prime / 重复 submit / 重启 reseed 都产同一 N 点序列，不串行拼接、不漂。
        仅对已注入 provider 的 run 有效；空壳 run（无 provider）tick_once 返 0、净值恒空（§3 不假绿灯）。
        """

        with self._lock:
            rec = self.get(run_id)
            # 空壳（无 provider）不喂数据：tick_once 返 0、也不写假 MTM 平线（§3 不假绿灯）。
            # 唯有真喂到 bar 才 MTM 写净值——净值序列与 bars_fed>0 严格绑定。
            if rec.provider is None:
                return {
                    "run_id": run_id, "bars_fed": rec.scheduler.state.bars_fed,
                    "mtm_count": rec.scheduler.state.mtm_count, "fills": 0,
                    "equity_points": len(self.equity_log(run_id)),
                    "simulated": False, "source": None,
                }
            # 幂等复位：游标归零 + venue 清态/复位现金/清空 equity_log + 计数归零 + 重新建仓引子。
            rec.provider.reset()
            rec.venue.reset_simulation_state(rec.initial_cash)
            rec.scheduler.state.bars_fed = 0
            rec.scheduler.state.mtm_count = 0
            seed_positions(rec.venue, rec.symbols)
            fills = 0
            for _ in range(max(0, ticks)):
                fills += rec.scheduler.tick_once()
                rec.scheduler.mtm_once()
            return {
                "run_id": run_id,
                "bars_fed": rec.scheduler.state.bars_fed,
                "mtm_count": rec.scheduler.state.mtm_count,
                "fills": fills,
                "equity_points": len(self.equity_log(run_id)),
                "simulated": rec.simulated_source is not None,
                "source": rec.simulated_source,
            }

    def get(self, run_id: str) -> PaperRunRecord:
        with self._lock:
            rec = self._runs.get(run_id)
            if rec is None:
                raise PaperRunNotFound(run_id)
            return rec

    def list_runs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._run_summary(r) for r in self._runs.values()]

    def start(self, run_id: str) -> dict[str, Any]:
        rec = self.get(run_id)
        rec.scheduler.start()
        return self.status(run_id)

    def stop(self, run_id: str) -> dict[str, Any]:
        rec = self.get(run_id)
        rec.scheduler.stop()
        return self.status(run_id)

    # ----- 状态 / book 派生 -----
    def status(self, run_id: str) -> dict[str, Any]:
        rec = self.get(run_id)
        snap = rec.scheduler.snapshot()
        snap["run_id"] = run_id
        snap["name"] = rec.name
        snap["origin"] = rec.origin
        snap["bench"] = rec.bench
        snap["market"] = rec.market
        # 数据来源标注：simulated_source 非空 = 回放捆绑样本（模拟）；None = 空壳（未喂数据）。
        snap["simulated_source"] = rec.simulated_source
        return snap

    def positions(self, run_id: str) -> list[dict[str, Any]]:
        rec = self.get(run_id)
        out = []
        for sym, pos in rec.venue._positions.items():  # noqa: SLF001  venue 单一持仓源
            out.append({
                "symbol": sym, "quantity": pos.quantity, "entry_price": pos.entry_price,
                "mark_price": pos.mark_price,
                "unrealized_pnl": (pos.mark_price - pos.entry_price) * pos.quantity,
            })
        return out

    def balance(self, run_id: str) -> dict[str, Any]:
        rec = self.get(run_id)
        bal = rec.venue.get_balance()
        positions_value = sum(p.quantity * p.mark_price for p in rec.venue._positions.values())  # noqa: SLF001
        cash = sum(b.free for b in bal.values())
        return {
            "cash": cash, "positions_value": positions_value,
            "total_equity": cash + positions_value,
            "locked": sum(b.locked for b in bal.values()),
            "assets": {k: {"asset": v.asset, "free": v.free, "locked": v.locked} for k, v in bal.items()},
        }

    def fills(self, run_id: str) -> list[dict[str, Any]]:
        """成交回报：从 ExecutionAuditLog 的 paper_fill 事件派生（不另存第二份）。"""

        rec = self.get(run_id)
        out = []
        for r in rec.venue.audit.export():
            if r.get("kind") != "paper_fill":
                continue
            p = r.get("payload") or {}
            out.append({
                "ts": p.get("ts") or r.get("logged_at_utc"),
                "symbol": p.get("symbol"), "side": p.get("side"),
                "filled_qty": p.get("filled_qty"), "fill_price": p.get("fill_price"),
                "commission": p.get("commission"), "status": p.get("status"),
            })
        return out

    def equity_log(self, run_id: str) -> list[dict[str, Any]]:
        """净值曲线：读 mark_to_market 写的 JSONL（每收盘一笔）。"""

        import json

        rec = self.get(run_id)
        path = rec.equity_log_path
        if not path or not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    # ----- 晋级判定 + 人工审批（INV-5） -----
    def promotion_status(self, run_id: str) -> dict[str, Any]:
        rec = self.get(run_id)
        checks, eligible = aggregate_promotion_checks(rec, self.risk)
        return {
            "run_id": run_id, "checks": checks, "eligible": eligible,
            "promoted": rec.promoted, "gate_id": rec.promotion_gate_id,
            "days_running": rec.days_running,
        }

    def open_promotion_gate(self, run_id: str, *, creator: str) -> PromotionGate:
        """开晋级判定门（pending）。仅判定+落门，绝不翻态——晋级是后续人工动作。"""

        with self._lock:
            rec = self.get(run_id)
            checks, eligible = aggregate_promotion_checks(rec, self.risk)
            self._gate_seq += 1
            gate_id = f"promo_{run_id}_{self._gate_seq}"
            gate = PromotionGate(gate_id=gate_id, run_id=run_id, creator=creator,
                                 checks=checks, eligible=eligible)
            self._gates[gate_id] = gate
            rec.promotion_gate_id = gate_id
            return gate

    def approve_promotion(
        self, gate_id: str, *, approver: str, endorsement_ref: str | None, reason: str,
    ) -> PromotionGate:
        """人工审批晋级（INV-5 硬门）：

        - approver == creator → ApproverEqualsCreator（防自审，生成≠验证不可自我满足）。
        - 无 endorsement_ref（验证背书）→ EmptyReason（裸翻必拒，未验证 ≠ 已验证）。
        - 4 门未全过（eligible=False）→ GateStateError（不可跳级）。
        - 非 pending → GateStateError。
        全过才翻 promoted=True 并联动因子台状态（PROBATION→OBSERVATION 由上游 lifecycle 执行）。
        """

        from ..approval.schema import ApproverEqualsCreator, EmptyReason, GateStateError

        with self._lock:
            gate = self._gates.get(gate_id)
            if gate is None:
                raise PaperRunNotFound(gate_id)
            if gate.decision != "pending":
                raise GateStateError(f"门非 pending（当前 {gate.decision}），不可再审批")
            if not approver or approver == gate.creator:
                raise ApproverEqualsCreator("approver 不得等于 creator（防自审，INV-5）")
            if not (endorsement_ref or "").strip():
                raise EmptyReason("缺验证背书（endorsement_ref）：裸翻必拒（INV-5，未验证≠已验证）")
            if not (reason or "").strip():
                raise EmptyReason("审批理由不得为空（反敷衍）")
            if not gate.eligible:
                gaps = [c["label"] for c in gate.checks if not c["passed"]]
                raise GateStateError("晋级判定 4 门未全过，不可晋级（不可跳级）：" + "；".join(gaps))
            gate.decision = "approved"
            gate.approver = approver
            gate.endorsement_ref = endorsement_ref
            gate.reason = reason
            gate.decided_at_utc = datetime.now(UTC).isoformat()
            self.get(gate.run_id).promoted = True
            return gate

    def get_promotion_gate(self, gate_id: str) -> PromotionGate:
        with self._lock:
            gate = self._gates.get(gate_id)
            if gate is None:
                raise PaperRunNotFound(gate_id)
            return gate

    # ----- A股 live 下单：恒拒（致命错误防线） -----
    def attempt_live_order(self, run_id: str, order_payload: dict[str, Any]) -> None:
        """A股 live 下单端点：A股永不 live，任何此类请求恒拒（致命错误防线）。

        走 OrderGuard / policy 单一门：A股 asset_class 映射 TrustTier.PAPER，
        live 意图（is_live=True）与项目硬约束冲突 → AShareLiveForbidden。永不进取 key 路径。
        """

        from ..security.gate.policy import TrustTier, classify

        rec = self.get(run_id)
        asset_class = "equity_cn" if rec.market == "equity_cn" else "crypto"
        # A股：classify 恒返 PAPER（永不 live）。请求带 live 意图即与硬约束冲突 → 拒。
        tier = classify(asset_class, is_live=True)
        if rec.market == "equity_cn" or tier == TrustTier.PAPER:
            if self.risk.frozen_hash(run_id) is not None:
                self.risk.record_violation(
                    run_id, title="A股 live 下单被拒",
                    detail="A股永不 live（项目范围硬约束）；本地止于 paper，唯一硬墙在交易所侧远程信任域。",
                )
            raise AShareLiveForbidden(
                "A股永远拒绝 live 下单（致命错误防线）：本地止于 paper，"
                "唯一硬墙在交易所侧远程信任域。"
            )

    def _run_summary(self, rec: PaperRunRecord) -> dict[str, Any]:
        st = rec.scheduler.state
        return {
            "id": rec.run_id, "name": rec.name, "origin": rec.origin, "market": rec.market,
            "bench": rec.bench, "running": st.running, "days": rec.days_running,
            "promoted": rec.promoted, "bars_fed": st.bars_fed,
            "simulated_source": rec.simulated_source,
        }


def _default_risk_limits(market: MarketKind) -> dict[str, Any]:
    """发布时冻结的默认门限（保守）。A股纯多头、杠杆 1.0 锁死。"""

    return {
        "max_notional_pct": 0.10,
        "leverage": 1.0,
        "weekly_turnover_cap": 0.60,
        "max_drawdown_halt": 0.20,
        "single_sector_exposure": 0.30,
        "single_name_cap": 0.10,
    }


__all__ = [
    "AShareLiveForbidden", "FrozenRiskGate", "PaperDeskService", "PaperRunNotFound",
    "PaperRunRecord", "PromotionGate", "RiskGateMutationForbidden",
    "aggregate_promotion_checks", "PROMO_MIN_DAYS", "PROMO_MAX_DECAY",
]
