"""模拟台后端服务层（P2 · /api/paper/* 的引擎聚合，不重造）。

把已建引擎拼成模拟台一层：
- 多 run 注册表：每个 run = 一个 PaperScheduler(PaperVenue) 实例（复用 scheduler.py / paper_venue.py）。
- 持仓 / 成交 / 余额 / 净值：直接读 venue.snapshot / ExecutionAuditLog(paper_fill) / equity log，不另存第二份。
- 晋级判定聚合：5 门（≥28 天 / 模拟段超额>0 / 风险门 0 违规 / 实盘衰减<阈值 / 未降级 testnet 实时数据源）只读派生，绝不在此自动晋级。
- 人工审批晋级：approver≠creator + 验证背书（INV-5），复用 approval 异常族；动钱/晋级永不暴露为 agent tool。
- 风险门发布冻结哈希 + append-only 违规链：门限发布时 content_hash 冻结；会话内改门请求被拒并入哈希链
  （hash 链=前一条 hash + 本条内容，篡改/重排即断链）。本地门=防篡改【证据】非防篡改（TCB 诚实声明）。

治理铁律（与 enforcer/policy/verifier 单一源一致）：
- A股永不 live：下单一律走 OrderGuard，A股映射 TrustTier.PAPER，live 下单端点恒拒（致命错误防线）。
- 裁决/note 措辞守门走 verifier._verdict_note（禁「可信/安全/排除过拟合」），本模块不自造合规结论文案。
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..delivery import PromotionClaim, RDPManifest, require_promotion_rdp
from ..execution.base import ExecutionAuditLog
from ..execution.paper_venue import PaperVenue
from ..lineage.ids import canonical_json, content_hash
from .replay_provider import (
    ReplayBarProvider,
    make_bar_provider,
    make_mark_provider,
    seed_positions,
)
from .scheduler import MarketKind, PaperScheduler, PaperSchedulerConfig
from .testnet_provider import (
    DEFAULT_TESTNET_KEYSTORE_NAME,
    TESTNET_SOURCE,
    TestnetBarProvider,
    TestnetMarketClient,
    make_testnet_provider,
)


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
    # bar/mark provider（注入即 tick_once 真喂数据产净值；None=空壳）。两类档（duck-typed 同形接口）：
    #   · ReplayBarProvider  = 兜底（真捆样本回放 / 合成游走，非实盘 key），无 key 也能跑。
    #   · TestnetBarProvider = testnet 真喂可选档（配 key 时 Binance testnet 公共实时 bar）。
    provider: Any | None = None
    simulated_source: str | None = None  # 数据来源标注：bundled_sample_replay(crypto 真捆样本) / deterministic_sim_walk(无样本市场合成兜底) / binance_testnet_live(testnet 真喂)——均为模拟非实盘真钱
    # provider 档位 + 降级留痕（DS-4 testnet 可选档 · fail-open 留痕，§3 诚实不假绿灯）：
    #   provider_kind ∈ {"testnet"(真喂), "replay_fallback"(请求 testnet 但无 key/连接失败→回退兜底),
    #                    "replay"(未请求 testnet 的默认兜底), "empty"(simulate=False 空壳)}。
    #   degrade_reason：请求 testnet 却回退兜底时记降级原因（诚实留痕；回退态 source 绝不标 testnet）。
    provider_kind: str = "empty"
    degrade_reason: str | None = None
    provider_status: dict[str, Any] = field(default_factory=dict)
    initial_cash: float = 1_000_000.0  # 注册时起始现金（prime_run 幂等重置基准）


class PaperRunNotFound(KeyError):
    """请求的 paper run 不存在。"""


class AShareLiveForbidden(Exception):
    """A股 live 下单：项目范围硬约束，永远拒绝（致命错误防线）。"""


class RiskGateMutationForbidden(Exception):
    """会话内试图改已冻结风险门：拒绝并入违规链（会话外不可改）。"""


class RiskEvidenceCorrupted(RuntimeError):
    """风险证据链已损坏；禁止继续追加或把残链重新锚定。"""


class PromotionReviewerUnauthorized(PermissionError):
    """当前认证主体没有这一个晋级门的有效 reviewer grant。"""


class PromotionEndorsementRejected(ValueError):
    """晋级背书不存在、已篡改、未绑定本门或不是可放行裁决。"""


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
        # 独立保存已提交链头和长度，令整条链被截断/清空也不能重新变成“完整”。
        self._chain_anchors: dict[str, tuple[int, str]] = {}

    def publish(self, run_id: str, limits: dict[str, Any]) -> str:
        """发布并冻结门限；返回冻结哈希。重复 publish 同 run 视为新发布世代（覆盖冻结）。"""

        with self._lock:
            if (
                run_id in self._frozen
                or run_id in self._chain
                or run_id in self._chain_anchors
            ) and not self._verify_chain_locked(run_id):
                raise RiskEvidenceCorrupted(
                    "risk evidence chain is corrupted; refusing to publish over it"
                )
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
        """复算整链 hash；篡改、重排、截断或清空均返 False。"""

        with self._lock:
            return self._verify_chain_locked(run_id)

    def promotion_snapshot(self, run_id: str) -> tuple[int, bool]:
        """原子读取晋级所需的违规数与证据链完整性。"""

        with self._lock:
            chain = self._chain.get(run_id, [])
            violations = sum(1 for e in chain if e.get("kind") == "violation")
            return violations, self._verify_chain_locked(run_id)

    @contextmanager
    def promotion_guard(self) -> Iterator[None]:
        """在最终晋级复核与翻态期间阻止风险历史并发写入。"""

        with self._lock:
            yield

    def _verify_chain_locked(self, run_id: str) -> bool:
        chain = self._chain.get(run_id, [])
        anchor = self._chain_anchors.get(run_id)
        if run_id not in self._frozen or anchor is None or not chain:
            return False
        prev = ""
        for expected_seq, entry in enumerate(chain):
            try:
                recomputed = content_hash({"prev": prev, "entry": _chain_body(entry)})
            except (KeyError, TypeError):
                return False
            if (
                entry.get("seq") != expected_seq
                or entry.get("prev_hash") != prev
                or recomputed != entry.get("chain_hash")
            ):
                return False
            prev = str(entry["chain_hash"])
        return anchor == (len(chain), prev)

    def _append(self, run_id: str, *, kind: str, detail: str, payload: dict[str, Any]) -> dict[str, Any]:
        chain = self._chain.setdefault(run_id, [])
        anchor = self._chain_anchors.get(run_id)
        if anchor is not None and not self._verify_chain_locked(run_id):
            raise RiskEvidenceCorrupted(
                "risk evidence chain is corrupted; refusing to append or re-anchor it"
            )
        if anchor is None and (chain or kind != "gate_published"):
            raise RiskEvidenceCorrupted(
                "risk evidence chain anchor is missing; refusing to append or re-anchor it"
            )
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
        self._chain_anchors[run_id] = (len(chain), entry["chain_hash"])
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
    verification_target_ref: str
    decision: Literal["pending", "approved", "superseded"] = "pending"
    approver: str | None = None
    endorsement_ref: str | None = None   # 验证背书（verdict_id / 验证记录引用）——INV-5 必填
    endorsement_evidence_sha256: str | None = None
    reviewer_grant_id: str | None = None
    reviewer_grant_record_sha256: str | None = None
    reviewer_authority_ref: str | None = None
    reason: str | None = None
    decided_at_utc: str | None = None
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id, "run_id": self.run_id, "creator": self.creator,
            "checks": self.checks, "eligible": self.eligible, "decision": self.decision,
            "verification_target_ref": self.verification_target_ref,
            "approver": self.approver, "endorsement_ref": self.endorsement_ref,
            "endorsement_evidence_sha256": self.endorsement_evidence_sha256,
            "reviewer_grant_id": self.reviewer_grant_id,
            "reviewer_grant_record_sha256": self.reviewer_grant_record_sha256,
            "reviewer_authority_ref": self.reviewer_authority_ref,
            "reason": self.reason, "decided_at_utc": self.decided_at_utc,
            "created_at_utc": self.created_at_utc,
        }


@dataclass(frozen=True)
class PaperPromotionReviewerGrant:
    """会话内 exact-gate reviewer authority；身份来自认证主体而不是请求别名。"""

    grant_id: str
    gate_id: str
    run_id: str
    verification_target_ref: str
    owner_user_id: str
    reviewer_user_id: str
    permissions: tuple[str, ...]
    expires_at_utc: str
    issued_at_utc: str
    record_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": self.grant_id,
            "gate_id": self.gate_id,
            "run_id": self.run_id,
            "verification_target_ref": self.verification_target_ref,
            "owner_user_id": self.owner_user_id,
            "reviewer_user_id": self.reviewer_user_id,
            "permissions": list(self.permissions),
            "expires_at_utc": self.expires_at_utc,
            "issued_at_utc": self.issued_at_utc,
            "record_sha256": self.record_sha256,
        }


def _sha256_ref(kind: str, payload: Any) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{kind}:sha256:{digest}"


def _promotion_verification_target(
    *, gate_id: str, run_id: str, creator: str, checks: list[dict[str, Any]]
) -> str:
    return _sha256_ref(
        "paper_promotion_target",
        {
            "schema": "paper_promotion_target.v1",
            "gate_id": gate_id,
            "run_id": run_id,
            "creator": creator,
            "checks": checks,
        },
    )


def _actor(value: Any, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise PromotionReviewerUnauthorized(f"{field_name} is required")
    return normalized


def _parse_future_utc(value: Any) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise PromotionReviewerUnauthorized("reviewer grant expiry must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PromotionReviewerUnauthorized("reviewer grant expiry must include a timezone")
    normalized = parsed.astimezone(UTC)
    if normalized <= datetime.now(UTC):
        raise PromotionReviewerUnauthorized("reviewer grant expiry must be in the future")
    return normalized.isoformat()


def aggregate_promotion_checks(
    rec: PaperRunRecord, risk: FrozenRiskGate, *, min_days: int = PROMO_MIN_DAYS,
    max_decay: float = PROMO_MAX_DECAY,
) -> tuple[list[dict[str, Any]], bool]:
    """5 门聚合（只读派生）：运行指标 4 门 + 未降级 Binance testnet 实时数据源。

    返回 (checks, eligible)。eligible = 5 门全过。回放/合成/降级/来源缺失均 fail closed。
    绝不在此晋级——这只是判定，不是动作。
    """

    decay = _decay(rec.backtest_annual, rec.paper_annual)
    violations, risk_chain_intact = risk.promotion_snapshot(rec.run_id)
    source_eligible = (
        rec.market == "crypto"
        and rec.simulated_source == TESTNET_SOURCE
        and rec.provider_kind == "testnet"
        and rec.degrade_reason is None
    )
    source_value = f"{rec.simulated_source or 'missing'} · provider={rec.provider_kind or 'missing'}"
    if rec.degrade_reason:
        source_value += f" · degraded={rec.degrade_reason}"
    checks = [
        {"key": "days", "label": "模拟运行满 1 个月（≥28 天）",
         "value": f"{rec.days_running} / {min_days} 天", "passed": rec.days_running >= min_days},
        {"key": "excess", "label": "模拟段年化 > 基准",
         "value": f"{rec.paper_excess_return:+.2%}", "passed": rec.paper_excess_return > 0},
        {"key": "zero_violation", "label": "风险门 0 违规且证据链完整",
         "value": (
             "全绿" if risk_chain_intact and violations == 0
             else "证据链损坏" if not risk_chain_intact
             else f"{violations} 违规"
         ),
         "passed": risk_chain_intact and violations == 0},
        {"key": "decay", "label": f"实盘衰减 < {max_decay:.0%}",
         "value": (f"{decay:+.0%}" if decay is not None else "n/a"),
         "passed": decay is not None and decay > -max_decay},
        {"key": "data_source", "label": "晋级数据源 · 加密市场 Binance testnet 实时 bar",
         "value": source_value, "passed": source_eligible},
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
        self._reviewer_grants: dict[str, PaperPromotionReviewerGrant] = {}
        self._endorsement_lookup: Callable[[str | None], Any] | None = None
        self._reviewer_authority_lookup: Callable[[str], str | None] | None = None
        self.risk = FrozenRiskGate()
        self._keystore: Any = None  # 惰性 SecureKeystore（仅 testnet provider 查 key 名存在性用，不 fetch 本体）

    def configure_promotion_endorsement_lookup(
        self, lookup: Callable[[str | None], Any]
    ) -> None:
        """接权威 VerdictStore 读路径；未配置时审批 fail closed。"""

        if not callable(lookup):
            raise TypeError("promotion endorsement lookup must be callable")
        with self._lock:
            self._endorsement_lookup = lookup

    def configure_promotion_reviewer_authority(
        self, lookup: Callable[[str], str | None]
    ) -> None:
        """接机器侧 verifier allowlist；普通请求不能自行扩充该信任根。"""

        if not callable(lookup):
            raise TypeError("promotion reviewer authority lookup must be callable")
        with self._lock:
            self._reviewer_authority_lookup = lookup

    def _resolve_keystore(self) -> Any:
        """惰性打开 SecureKeystore（仅供 testnet provider 查 **key 名存在性**，绝不 fetch 明文 secret）。

        失败/无 keyring 返 None（make_testnet_provider 视为未配 → 诚实回退兜底，不抛、不空跑伪装）。
        """

        if self._keystore is not None:
            return self._keystore
        try:
            from ..security.keystore import SecureKeystore

            self._keystore = SecureKeystore.open()
        except Exception:  # noqa: BLE001  无 keystore 后端 → None（testnet 回退兜底，fail-safe）
            self._keystore = None
        return self._keystore

    # ----- run 注册 / 生命周期 -----
    def register_run(
        self, *, run_id: str, name: str, origin: str, market: MarketKind,
        symbols: list[str], bench: str, creator: str, equity_log_path: Path,
        cash: float = 1_000_000.0, days_running: int = 0,
        paper_excess_return: float = 0.0, backtest_annual: float = 0.0,
        paper_annual: float = 0.0, risk_limits: dict[str, Any] | None = None,
        simulate: bool = True,
        testnet: bool = False,
        testnet_keystore: Any = None,
        testnet_keystore_name: str = DEFAULT_TESTNET_KEYSTORE_NAME,
        testnet_client_factory: Callable[[], TestnetMarketClient] | None = None,
        provider_override: Any | None = None,
        provider_status: dict[str, Any] | None = None,
    ) -> PaperRunRecord:
        """注册一条 paper run。simulate=True（默认）注入 provider + 建仓种子单：

        tick_once 真喂 bars 撮合 → MTM 写出移动净值序列。simulate=False 留空壳（无 provider）——
        tick_once 返 0、净值不动（诚实：未喂数据即不假绿灯）。

        provider 分流（DS-4「都做」）：
          · testnet=False（默认）→ ReplayBarProvider 兜底（crypto 真捆样本回放 / 无样本市场合成游走），无 key。
          · testnet=True（用户配 testnet key 时）→ **试** TestnetBarProvider（Binance testnet 公共实时 bar）：
              - 配 key 且连接成功 → 注入 testnet 真喂（provider_kind="testnet", source=binance_testnet_live）。
              - 无 key / 连接失败 → **诚实回退** ReplayBarProvider 兜底（provider_kind="replay_fallback" +
                degrade_reason 留痕；source 仍为兜底真实标签，**绝不**标成 testnet 真喂）——fail-open 留痕。

        治理：testnet 行情走【公共】端点、**仅查 key 名存在性不取明文**（R10/INV-3，testnet key 不进 LLM）；
        testnet 永走模拟撮合不调 live 下单；A股恒 paper（live 下单仍走 attempt_live_order 恒拒）；不绕审批/动钱。
        """

        # ── testnet 解析在锁外（含网络 I/O：拉 klines）：避免占 self._lock 拖垮全 desk / 首屏 <2s（H2）。──
        testnet_provider: TestnetBarProvider | None = None
        degrade_reason: str | None = None
        if simulate and symbols and testnet and provider_override is None:
            ks = testnet_keystore if testnet_keystore is not None else self._resolve_keystore()
            testnet_provider, degrade_reason = make_testnet_provider(
                market, list(symbols), keystore=ks, keystore_name=testnet_keystore_name,
                client_factory=testnet_client_factory,
            )
            # testnet_provider!=None → 真喂；==None → degrade_reason 已含原因，下方回退兜底。

        with self._lock:
            audit = ExecutionAuditLog()
            venue = PaperVenue(cash=cash, equity_log_path=equity_log_path, audit=audit)
            cfg = PaperSchedulerConfig(strategy_id=run_id, symbols=list(symbols), market=market,
                                       equity_log_path=equity_log_path)
            provider: Any | None = None
            provider_kind = "empty"
            bar_p = mark_p = None
            if simulate and symbols:
                if provider_override is not None:
                    provider = provider_override
                    provider_kind = "testnet" if getattr(provider, "source", None) else "replay"
                elif testnet_provider is not None:
                    # testnet 真喂档：Binance testnet 公共实时 bar（无 key 公共端点；仅模拟撮合不下真单）。
                    provider = testnet_provider
                    provider_kind = "testnet"
                else:
                    # 兜底档（默认，或请求 testnet 但无 key/连接失败回退）：crypto 配捆样本→真 BTC close 回放
                    # (bundled_sample_replay)，无样本市场(A股)→合成游走兜底(deterministic_sim_walk)，标签诚实分流。
                    provider = ReplayBarProvider(symbols=list(symbols), market=market)
                    # 请求过 testnet 却回退 → replay_fallback（留痕）；未请求 testnet → 普通 replay。
                    provider_kind = "replay_fallback" if testnet else "replay"
                bar_p = make_bar_provider(provider)
                mark_p = make_mark_provider(provider)
                # 注入模拟建仓引子（非下单路径）：entry_price/qty 用各 symbol 序列首价反推
                # （真样本首价 ~47704 / testnet 真价 ~60000 → qty=notional/首价），MTM 不跨尺度失真。
                seed_positions(venue, list(symbols), provider=provider)
            sched = PaperScheduler(venue, cfg, bar_provider=bar_p, mark_provider=mark_p)
            rec = PaperRunRecord(
                run_id=run_id, name=name, origin=origin, market=market, symbols=list(symbols),
                bench=bench, creator=creator, scheduler=sched, venue=venue,
                equity_log_path=equity_log_path, days_running=days_running,
                paper_excess_return=paper_excess_return, backtest_annual=backtest_annual,
                paper_annual=paper_annual, provider=provider,
                simulated_source=(provider.source if provider else None),
                provider_kind=provider_kind,
                # 留痕仅当请求 testnet 却回退兜底时（否则 None）：诚实记降级原因，回退态 source 绝不标 testnet。
                degrade_reason=(degrade_reason if provider_kind == "replay_fallback" else None),
                provider_status=dict(provider_status or {}),
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

        并发安全（M4）：复位/喂 bar/写净值前先停后台调度循环（scheduler.stop() join 线程），避免
        后台 _bar_loop/_mtm_loop 与 prime 并发改同 venue/state/equity_log → 撕裂写、equity_log 损坏、
        bars_fed 错乱。复位前若 loop 在跑，prime 后按原态重启（用户视角：re-prime 不停掉已启动的 run）。
        """

        with self._lock:
            rec = self.get(run_id)
            # 空壳（无 provider）不喂数据：tick_once 返 0、也不写假 MTM 平线（§3 不假绿灯）。
            # 唯有真喂到 bar 才 MTM 写净值——净值序列与 bars_fed>0 严格绑定。
            if rec.provider is None:
                return {
                    "run_id": run_id, "bars_fed": rec.scheduler.state.bars_fed,
                    "mtm_count": rec.scheduler.state.mtm_count, "fills": 0,
                    "equity_points": rec.scheduler.state.mtm_count,
                    "simulated": False, "source": None, "provider_status": dict(rec.provider_status),
                }
            # M4：先停后台循环并 join，确保复位/喂 bar 期间无并发改同 venue/state/equity_log。
            was_running = rec.scheduler.state.running
            if was_running:
                rec.scheduler.stop()
            reset_ok = False
            try:
                # 幂等复位：游标归零 + venue 清态/复位现金/清空 equity_log + 计数归零 + 重新建仓引子。
                rec.provider.reset()
                rec.venue.reset_simulation_state(rec.initial_cash)
                rec.scheduler.state.bars_fed = 0
                rec.scheduler.state.mtm_count = 0
                # 复位重建仓必须传同一 provider：用各 symbol 序列首价反推 entry_price/qty，
                # 否则 re-prime 会按首价 100 重建仓而 mark 喂 47704 → 重新引入 P&L 失真（A7）。
                seed_positions(rec.venue, rec.symbols, provider=rec.provider)
                fills = 0
                for _ in range(max(0, ticks)):
                    fills += rec.scheduler.tick_once()
                    rec.scheduler.mtm_once()
                reset_ok = True
            finally:
                # 复位前在跑则按原态重启（prime 不应静默停掉用户已 start 的 run）。
                # 仅在复位段全部成功后重启：若 reset/喂数据中途抛错（如 equity_log 写盘失败），
                # 不把后台 loop 拉回半复位的 venue/state 上跑（异常安全：宁可保持 stopped 让异常上浮）。
                if was_running and reset_ok:
                    rec.scheduler.start()
            return {
                "run_id": run_id,
                "bars_fed": rec.scheduler.state.bars_fed,
                "mtm_count": rec.scheduler.state.mtm_count,
                "fills": fills,
                # perf：equity_points 直取内存 mtm_count（=净值行数），不重读 json.loads 整个 jsonl。
                "equity_points": rec.scheduler.state.mtm_count,
                "simulated": rec.simulated_source is not None,
                "source": rec.simulated_source,
                "provider_status": dict(rec.provider_status),
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
        # 持 desk _lock：与 prime_run 串行化，杜绝「prime 复位中途被并发 start 启动后台循环」竞态（M4）。
        with self._lock:
            rec = self.get(run_id)
            rec.scheduler.start()
            return self.status(run_id)

    def stop(self, run_id: str) -> dict[str, Any]:
        with self._lock:
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
        # 数据来源标注：bundled_sample_replay(真捆样本) / deterministic_sim_walk(合成兜底) /
        # binance_testnet_live(testnet 真喂) / None(空壳未喂数据)。provider_kind + degrade_reason 让
        # 「testnet 真喂 vs 回退兜底」对用户透明（§3 诚实：回退态 source 绝不标 testnet，degrade 留痕）。
        snap["simulated_source"] = rec.simulated_source
        snap["provider_kind"] = rec.provider_kind
        snap["degrade_reason"] = rec.degrade_reason
        snap["provider_status"] = dict(rec.provider_status)
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
            "simulated_source": rec.simulated_source,
            "provider_kind": rec.provider_kind,
            "degrade_reason": rec.degrade_reason,
        }

    def open_promotion_gate(self, run_id: str, *, creator: str) -> PromotionGate:
        """开晋级判定门（pending）。仅判定+落门，绝不翻态——晋级是后续人工动作。"""

        with self._lock:
            creator_id = _actor(creator, "creator")
            rec = self.get(run_id)
            run_owner = _actor(rec.creator, "run creator")
            if creator_id.casefold() != run_owner.casefold():
                raise PromotionReviewerUnauthorized(
                    "only the authenticated paper run owner can open a promotion gate"
                )
            if rec.promoted:
                from ..approval.schema import GateStateError

                raise GateStateError(
                    "paper run is already promoted; a new pending promotion gate is not allowed"
                )
            checks, eligible = aggregate_promotion_checks(rec, self.risk)
            gate_id = f"promo_{run_id}_{uuid.uuid4().hex}"
            verification_target_ref = _promotion_verification_target(
                gate_id=gate_id,
                run_id=run_id,
                creator=creator_id,
                checks=checks,
            )
            gate = PromotionGate(
                gate_id=gate_id,
                run_id=run_id,
                creator=creator_id,
                checks=checks,
                eligible=eligible,
                verification_target_ref=verification_target_ref,
            )
            prior_gate = self._gates.get(str(rec.promotion_gate_id or ""))
            if prior_gate is not None and prior_gate.decision == "pending":
                prior_gate.decision = "superseded"
            self._gates[gate_id] = gate
            rec.promotion_gate_id = gate_id
            return gate

    def grant_promotion_reviewer(
        self,
        gate_id: str,
        *,
        owner_user_id: str,
        reviewer_user_id: str,
        permissions: tuple[str, ...],
        expires_at_utc: str,
    ) -> PaperPromotionReviewerGrant:
        """由门创建者向另一个认证主体授予 exact-gate 审批权。"""

        with self._lock:
            gate = self._gates.get(gate_id)
            if gate is None:
                raise PaperRunNotFound(gate_id)
            owner = _actor(owner_user_id, "owner_user_id")
            reviewer = _actor(reviewer_user_id, "reviewer_user_id")
            if owner != gate.creator:
                raise PromotionReviewerUnauthorized("only the exact gate creator can grant review")
            if reviewer.casefold() == owner.casefold():
                raise PromotionReviewerUnauthorized("reviewer must differ from gate creator")
            allowed = tuple(sorted({str(item or "").strip() for item in permissions if str(item or "").strip()}))
            if allowed != ("approve",):
                raise PromotionReviewerUnauthorized("paper reviewer grant requires exactly approve")
            expiry = _parse_future_utc(expires_at_utc)
            issued_at = datetime.now(UTC).isoformat()
            identity = {
                "schema": "paper_promotion_reviewer_grant.v1",
                "gate_id": gate.gate_id,
                "run_id": gate.run_id,
                "verification_target_ref": gate.verification_target_ref,
                "owner_user_id": owner,
                "reviewer_user_id": reviewer,
                "permissions": list(allowed),
                "expires_at_utc": expiry,
                "issued_at_utc": issued_at,
            }
            grant_id = _sha256_ref("paper_reviewer_grant", {
                key: value for key, value in identity.items() if key != "issued_at_utc"
            })
            record_sha256 = _sha256_ref("paper_reviewer_grant_record", identity)
            grant = PaperPromotionReviewerGrant(
                grant_id=grant_id,
                gate_id=gate.gate_id,
                run_id=gate.run_id,
                verification_target_ref=gate.verification_target_ref,
                owner_user_id=owner,
                reviewer_user_id=reviewer,
                permissions=allowed,
                expires_at_utc=expiry,
                issued_at_utc=issued_at,
                record_sha256=record_sha256,
            )
            stale_grants = [
                identity
                for identity, current in self._reviewer_grants.items()
                if current.gate_id == gate.gate_id
                and current.owner_user_id == owner
                and current.reviewer_user_id == reviewer
            ]
            for identity in stale_grants:
                self._reviewer_grants.pop(identity, None)
            self._reviewer_grants[grant_id] = grant
            return grant

    def _authorize_promotion_reviewer(
        self, gate: PromotionGate, approver: str
    ) -> tuple[PaperPromotionReviewerGrant, str]:
        reviewer = _actor(approver, "approver")
        now = datetime.now(UTC)
        candidates = [
            grant
            for grant in self._reviewer_grants.values()
            if grant.gate_id == gate.gate_id
            and grant.run_id == gate.run_id
            and grant.verification_target_ref == gate.verification_target_ref
            and grant.owner_user_id == gate.creator
            and grant.reviewer_user_id == reviewer
            and grant.permissions == ("approve",)
        ]
        if len(candidates) != 1:
            raise PromotionReviewerUnauthorized(
                "promotion gate not found or authenticated reviewer is not authorized"
            )
        grant = candidates[0]
        expires = datetime.fromisoformat(grant.expires_at_utc).astimezone(UTC)
        if expires <= now:
            raise PromotionReviewerUnauthorized(
                "promotion gate not found or authenticated reviewer is not authorized"
            )
        expected_identity = {
            "schema": "paper_promotion_reviewer_grant.v1",
            "gate_id": grant.gate_id,
            "run_id": grant.run_id,
            "verification_target_ref": grant.verification_target_ref,
            "owner_user_id": grant.owner_user_id,
            "reviewer_user_id": grant.reviewer_user_id,
            "permissions": list(grant.permissions),
            "expires_at_utc": grant.expires_at_utc,
            "issued_at_utc": grant.issued_at_utc,
        }
        if grant.record_sha256 != _sha256_ref("paper_reviewer_grant_record", expected_identity):
            raise PromotionReviewerUnauthorized("reviewer grant record hash does not match content")
        if self._reviewer_authority_lookup is None:
            raise PromotionReviewerUnauthorized(
                "trusted paper verifier authority is not configured"
            )
        try:
            authority_ref = str(self._reviewer_authority_lookup(reviewer) or "").strip()
        except Exception as exc:  # noqa: BLE001 - authority lookup fails closed.
            raise PromotionReviewerUnauthorized(
                "trusted paper verifier authority could not be resolved"
            ) from exc
        if not authority_ref:
            raise PromotionReviewerUnauthorized(
                "authenticated reviewer is not in the machine paper verifier allowlist"
            )
        return grant, authority_ref

    def _resolve_promotion_endorsement(
        self, gate: PromotionGate, endorsement_ref: str | None
    ) -> tuple[Any, str]:
        ref = str(endorsement_ref or "").strip()
        if not ref:
            from ..approval.schema import EmptyReason

            raise EmptyReason(
                "缺验证背书（endorsement_ref）：裸翻必拒（INV-5，未验证≠已验证）"
            )
        if self._endorsement_lookup is None:
            raise PromotionEndorsementRejected("paper promotion endorsement authority is unavailable")
        try:
            record = self._endorsement_lookup(ref)
        except Exception as exc:  # noqa: BLE001 - tamper/read errors fail closed.
            raise PromotionEndorsementRejected(
                "paper promotion endorsement could not be verified"
            ) from exc
        if record is None:
            raise PromotionEndorsementRejected("paper promotion endorsement was not found")

        from ..verification.schema import VerdictRecord, verdict_id_of

        if not isinstance(record, VerdictRecord):
            raise PromotionEndorsementRejected("paper promotion endorsement is not typed")
        if record.verdict_id != ref or verdict_id_of(record) != ref:
            raise PromotionEndorsementRejected("paper promotion endorsement content id is invalid")
        if record.target_ref != gate.verification_target_ref:
            raise PromotionEndorsementRejected(
                "paper promotion endorsement is not bound to this exact run/gate snapshot"
            )
        if record.verdict != "consistent":
            raise PromotionEndorsementRejected(
                f"paper promotion endorsement verdict={record.verdict!r} is not releasable"
            )
        if (
            not record.independence.established
            or not record.independence.model_differs
            or record.generator_model == record.checker_model
        ):
            raise PromotionEndorsementRejected(
                "paper promotion endorsement lacks a distinct-model verification challenge"
            )
        if not record.consistency_check or not record.replay_ref:
            raise PromotionEndorsementRejected(
                "paper promotion endorsement requires exact checks and replay_ref"
            )
        evidence_hash = _sha256_ref("paper_promotion_endorsement", record.to_dict())
        return record, evidence_hash

    def approve_promotion(
        self, gate_id: str, *, approver: str, endorsement_ref: str | None, reason: str,
        rdp: RDPManifest | None = None, promotion_claim: PromotionClaim | None = None,
        require_rdp: bool = False,
    ) -> PromotionGate:
        """人工审批晋级（INV-5 硬门 + §17 RDP 追溯接线）：

        - approver == creator → ApproverEqualsCreator（防自审，生成≠验证不可自我满足）。
        - 无/无效/错绑 endorsement_ref → 拒（必须解析成绑定本门的 consistent typed verdict）。
        - approver 必须是认证主体，且持有 creator 签发给本门的当前 reviewer grant。
        - 5 门未全过（eligible=False，含数据源门）→ GateStateError（不可跳级）。
        - 非 pending → GateStateError。
        - §17 RDP 追溯（D-RDP-1 wire）：翻态前调 `require_promotion_rdp(rdp, promotion_claim, ...)`——
          残缺 RDP（缺 manifest/hash/repro/DatasetVersion/未验证残余）或追溯断裂 → RDPRejected，不翻态。
          默认 rdp=None+require_rdp=False = 向后兼容 no-op（不破基线；全量强制待 D-RDP-2 聚合器供 RDP）。
        全过才翻 promoted=True 并联动因子台状态（PROBATION→OBSERVATION 由上游 lifecycle 执行）。
        """

        from ..approval.schema import ApproverEqualsCreator, EmptyReason, GateStateError

        with self._lock:
            gate = self._gates.get(gate_id)
            if gate is None:
                raise PaperRunNotFound(gate_id)
            if gate.decision != "pending":
                raise GateStateError(f"门非 pending（当前 {gate.decision}），不可再审批")
            if not str(endorsement_ref or "").strip():
                raise EmptyReason(
                    "缺验证背书（endorsement_ref）：裸翻必拒（INV-5，未验证≠已验证）"
                )
            approver_id = _actor(approver, "approver")
            if approver_id.casefold() == gate.creator.casefold():
                raise ApproverEqualsCreator("approver 不得等于 creator（防自审，INV-5）")
            if not (reason or "").strip():
                raise EmptyReason("审批理由不得为空（反敷衍）")
            # 审批瞬间重新聚合当前 run，防止开门后数据源降级或指标恶化仍沿用旧快照。
            # 已经不合格的旧门不会因后续状态变化自行转绿；须重新开门留新快照。
            rec = self.get(gate.run_id)
            if rec.promotion_gate_id != gate.gate_id:
                raise GateStateError(
                    "晋级门已被更新门取代；旧门不可审批，须使用当前 gate"
                )
            current_checks, current_eligible = aggregate_promotion_checks(rec, self.risk)
            current_target_ref = _promotion_verification_target(
                gate_id=gate.gate_id,
                run_id=gate.run_id,
                creator=gate.creator,
                checks=current_checks,
            )
            if not gate.eligible or not current_eligible or current_target_ref != gate.verification_target_ref:
                gaps = [c["label"] for c in current_checks if not c["passed"]]
                if not gaps:
                    gaps = ["门快照已变化或打开时未达标，须重新开门并重新验证"]
                raise GateStateError("晋级判定 5 门未全过，不可晋级（不可跳级）：" + "；".join(gaps))
            reviewer_grant, reviewer_authority_ref = self._authorize_promotion_reviewer(
                gate, approver_id
            )
            _endorsement, endorsement_evidence_sha256 = self._resolve_promotion_endorsement(
                gate, endorsement_ref
            )
            # §17 RDP 追溯接线：fail-closed 在翻态之前（残缺/断裂 RDP raise RDPRejected，promoted 不动）。
            require_promotion_rdp(rdp, promotion_claim, require_rdp=require_rdp)
            # 外部验证完成后，在风险锁内做最后一次快照并翻态。这样并发违规只能
            # 线性化在本次晋级之前（被下方复核拒绝）或之后，不能插进快照与 commit 之间。
            with self.risk.promotion_guard():
                final_checks, final_eligible = aggregate_promotion_checks(rec, self.risk)
                final_target_ref = _promotion_verification_target(
                    gate_id=gate.gate_id,
                    run_id=gate.run_id,
                    creator=gate.creator,
                    checks=final_checks,
                )
                if (
                    not gate.eligible
                    or not final_eligible
                    or final_target_ref != gate.verification_target_ref
                ):
                    gaps = [c["label"] for c in final_checks if not c["passed"]]
                    if not gaps:
                        gaps = ["门快照已变化或打开时未达标，须重新开门并重新验证"]
                    raise GateStateError(
                        "晋级判定 5 门未全过，不可晋级（不可跳级）：" + "；".join(gaps)
                    )
                # All gates passed. Commit the in-memory gate/run state while both
                # PaperDeskService._lock and the risk evidence lock are held.
                gate.checks = final_checks
                gate.eligible = True
                gate.decision = "approved"
                gate.approver = approver_id
                gate.endorsement_ref = str(endorsement_ref).strip()
                gate.endorsement_evidence_sha256 = endorsement_evidence_sha256
                gate.reviewer_grant_id = reviewer_grant.grant_id
                gate.reviewer_grant_record_sha256 = reviewer_grant.record_sha256
                gate.reviewer_authority_ref = reviewer_authority_ref
                gate.reason = reason.strip()
                gate.decided_at_utc = datetime.now(UTC).isoformat()
                rec.promoted = True
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
            "provider_kind": rec.provider_kind, "degrade_reason": rec.degrade_reason,
            "provider_status": dict(rec.provider_status),
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
    "PaperRunRecord", "PromotionGate", "RiskEvidenceCorrupted", "RiskGateMutationForbidden",
    "aggregate_promotion_checks", "PROMO_MIN_DAYS", "PROMO_MAX_DECAY",
]
