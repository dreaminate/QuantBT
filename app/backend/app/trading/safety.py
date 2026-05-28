"""v0.8.8 · Binance 实盘安全阶梯 SafetyService (W9)。

SafeKey wizard 5 步:
  1. enableWithdrawals=False
  2. enableInternalTransfer=False
  3. enableUniversalTransfer=False
  4. ipRestrict=True (推荐 IP 白名单)
  5. enableFutures=True (要交易 futures 才需要)

Testnet Order Matrix (6 种 × 2 方向):
  LIMIT BUY / SELL · MARKET BUY / SELL · STOP_MARKET BUY / SELL
  TAKE_PROFIT_MARKET BUY / SELL · STOP / TAKE_PROFIT · TRAILING_STOP_MARKET
  每格状态: pending / ok / failed / not_attempted

Live Ladder 5 级:
  level_0: paper only
  level_1: testnet small order ≤ 0.001 BTC
  level_2: mainnet $50 单笔 (1 小时 1 次)
  level_3: mainnet $200 单笔 (1 天 5 次)
  level_4: mainnet $1000 单笔 (1 天 20 次)
  level_5: 用户自定义

晋级条件: 上一级 24h+ 无 kill switch 严重事件 + 完成 N 笔成功订单
降级条件: kill switch 触发 / loss > 2% / 异常 disconnect 超过 30s
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal


class SafetyServiceError(Exception):
    pass


LadderLevel = Literal["level_0", "level_1", "level_2", "level_3", "level_4", "level_5"]
CellStatus = Literal["pending", "ok", "failed", "not_attempted"]


@dataclass
class SafeKeyChecklist:
    user_id: str
    key_id_hash: str
    enable_withdrawals: bool
    enable_internal_transfer: bool
    enable_universal_transfer: bool
    enable_margin: bool
    enable_futures: bool
    ip_restricted: bool
    passed: bool
    failures: list[str]
    warnings: list[str]
    checked_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestnetMatrixCell:
    order_type: str
    side: str
    status: CellStatus
    last_attempt_utc: str | None
    place_ok: bool
    query_ok: bool
    cancel_ok: bool
    reconcile_ok: bool
    error_code: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TestnetMatrixState:
    user_id: str
    cells: list[TestnetMatrixCell]
    completed_count: int
    total_count: int

    @property
    def completion_pct(self) -> float:
        return (self.completed_count / self.total_count * 100) if self.total_count else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "completion_pct": self.completion_pct,
        }


@dataclass
class LiveLadderState:
    user_id: str
    current_level: LadderLevel
    last_promotion_at_utc: str | None
    last_demotion_at_utc: str | None
    promotion_blocked_until_utc: str | None
    blocked_reason: str | None
    successful_orders_at_level: int
    safekey_passed: bool
    testnet_matrix_passed: bool
    can_promote: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# 6 种 order type × 2 side = 12 cells
_DEFAULT_MATRIX_CELLS = [
    (t, s)
    for t in ["limit", "market", "stop_market", "take_profit", "stop_loss", "trailing_stop_market"]
    for s in ["buy", "sell"]
]


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS trading_safety_checklist (
        user_id TEXT NOT NULL,
        key_id_hash TEXT NOT NULL,
        payload TEXT NOT NULL,
        checked_at_utc TEXT NOT NULL,
        PRIMARY KEY (user_id, key_id_hash)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trading_testnet_matrix (
        user_id TEXT NOT NULL,
        order_type TEXT NOT NULL,
        side TEXT NOT NULL,
        status TEXT NOT NULL,
        place_ok INTEGER NOT NULL DEFAULT 0,
        query_ok INTEGER NOT NULL DEFAULT 0,
        cancel_ok INTEGER NOT NULL DEFAULT 0,
        reconcile_ok INTEGER NOT NULL DEFAULT 0,
        error_code TEXT,
        last_attempt_utc TEXT,
        PRIMARY KEY (user_id, order_type, side)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS trading_live_ladder (
        user_id TEXT PRIMARY KEY,
        current_level TEXT NOT NULL DEFAULT 'level_0',
        last_promotion_at_utc TEXT,
        last_demotion_at_utc TEXT,
        promotion_blocked_until_utc TEXT,
        blocked_reason TEXT,
        successful_orders_at_level INTEGER NOT NULL DEFAULT 0,
        updated_at_utc TEXT NOT NULL
    )
    """,
]

LADDER_ORDER = ["level_0", "level_1", "level_2", "level_3", "level_4", "level_5"]
PROMOTION_REQ_ORDERS = {
    # 晋级到该 level 需要的"在上一级别已经成功完成的 *mainnet 订单* 数"。
    # testnet_matrix 通过率单独由 can_promote 逻辑校验，不算在这里。
    "level_0": 0,
    "level_1": 0,  # 升 level_1 只要 SafeKey
    "level_2": 0,  # 升 level_2 只要 testnet_matrix 100%
    "level_3": 5,  # mainnet level_2 时成功 5 单
    "level_4": 20,  # mainnet level_3 成功 20 单
    "level_5": 50,
}


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def init_safety_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as c:
        for stmt in _SCHEMA:
            c.execute(stmt)
        c.commit()


class SafetyService:
    def __init__(self, db_path: Path) -> None:
        self._db = db_path
        init_safety_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db)
        c.row_factory = sqlite3.Row
        return c

    # ---------- SafeKey wizard ----------

    def record_safekey_check(
        self,
        user_id: str,
        key_id_hash: str,
        *,
        enable_withdrawals: bool,
        enable_internal_transfer: bool = False,
        enable_universal_transfer: bool = False,
        enable_margin: bool = False,
        enable_futures: bool = True,
        ip_restricted: bool = True,
    ) -> SafeKeyChecklist:
        failures: list[str] = []
        warnings: list[str] = []
        if enable_withdrawals:
            failures.append("enableWithdrawals=True 必须关闭")
        if enable_internal_transfer:
            failures.append("enableInternalTransfer=True 必须关闭")
        if enable_universal_transfer:
            failures.append("enableUniversalTransfer=True 必须关闭")
        if enable_margin:
            warnings.append("enableMargin=True 建议关闭（被攻破时放大损失）")
        if not ip_restricted:
            warnings.append("ipRestrict=False 建议加 IP 白名单")
        if not enable_futures:
            warnings.append("enableFutures=False 将无法交易期货")

        passed = len(failures) == 0
        rec = SafeKeyChecklist(
            user_id=user_id,
            key_id_hash=key_id_hash,
            enable_withdrawals=enable_withdrawals,
            enable_internal_transfer=enable_internal_transfer,
            enable_universal_transfer=enable_universal_transfer,
            enable_margin=enable_margin,
            enable_futures=enable_futures,
            ip_restricted=ip_restricted,
            passed=passed,
            failures=failures,
            warnings=warnings,
            checked_at_utc=_utc_now(),
        )
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO trading_safety_checklist (user_id, key_id_hash, payload, checked_at_utc) VALUES (?,?,?,?)",
                (user_id, key_id_hash, json.dumps(rec.to_dict(), ensure_ascii=False), rec.checked_at_utc),
            )
            c.commit()
        return rec

    def get_latest_safekey(self, user_id: str) -> SafeKeyChecklist | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT payload FROM trading_safety_checklist WHERE user_id=? ORDER BY checked_at_utc DESC LIMIT 1",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return SafeKeyChecklist(**json.loads(row["payload"]))

    # ---------- Testnet matrix ----------

    def record_matrix_attempt(
        self,
        user_id: str,
        order_type: str,
        side: str,
        *,
        place_ok: bool,
        query_ok: bool,
        cancel_ok: bool,
        reconcile_ok: bool,
        error_code: str | None = None,
    ) -> TestnetMatrixCell:
        status: CellStatus = "ok" if (place_ok and query_ok and cancel_ok and reconcile_ok) else "failed"
        now = _utc_now()
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO trading_testnet_matrix (user_id, order_type, side, status, place_ok, query_ok, cancel_ok, reconcile_ok, error_code, last_attempt_utc) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (user_id, order_type, side, status, int(place_ok), int(query_ok), int(cancel_ok), int(reconcile_ok), error_code, now),
            )
            c.commit()
        return TestnetMatrixCell(
            order_type=order_type, side=side, status=status,
            last_attempt_utc=now,
            place_ok=place_ok, query_ok=query_ok, cancel_ok=cancel_ok, reconcile_ok=reconcile_ok,
            error_code=error_code,
        )

    def get_matrix(self, user_id: str) -> TestnetMatrixState:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM trading_testnet_matrix WHERE user_id=?",
                (user_id,),
            ).fetchall()
        existing = {(r["order_type"], r["side"]): dict(r) for r in rows}
        cells: list[TestnetMatrixCell] = []
        completed = 0
        for ot, side in _DEFAULT_MATRIX_CELLS:
            key = (ot, side)
            if key in existing:
                r = existing[key]
                cell = TestnetMatrixCell(
                    order_type=ot, side=side, status=r["status"],
                    last_attempt_utc=r["last_attempt_utc"],
                    place_ok=bool(r["place_ok"]), query_ok=bool(r["query_ok"]),
                    cancel_ok=bool(r["cancel_ok"]), reconcile_ok=bool(r["reconcile_ok"]),
                    error_code=r["error_code"],
                )
                if cell.status == "ok":
                    completed += 1
            else:
                cell = TestnetMatrixCell(
                    order_type=ot, side=side, status="not_attempted",
                    last_attempt_utc=None,
                    place_ok=False, query_ok=False, cancel_ok=False, reconcile_ok=False,
                    error_code=None,
                )
            cells.append(cell)
        return TestnetMatrixState(
            user_id=user_id, cells=cells,
            completed_count=completed, total_count=len(_DEFAULT_MATRIX_CELLS),
        )

    # ---------- Live ladder ----------

    def get_ladder(self, user_id: str) -> LiveLadderState:
        with self._conn() as c:
            row = c.execute("SELECT * FROM trading_live_ladder WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            # 初始化为 level_0
            now = _utc_now()
            with self._conn() as c:
                c.execute(
                    "INSERT INTO trading_live_ladder (user_id, updated_at_utc) VALUES (?,?)",
                    (user_id, now),
                )
                c.commit()
            return self.get_ladder(user_id)
        sk = self.get_latest_safekey(user_id)
        mx = self.get_matrix(user_id)
        sk_passed = sk is not None and sk.passed
        mx_passed = mx.completion_pct >= 100.0
        current = row["current_level"]
        # can_promote: 当前级别要求满足 + SafeKey passed
        next_level_idx = LADDER_ORDER.index(current) + 1 if current in LADDER_ORDER else 0
        can_promote = False
        if next_level_idx < len(LADDER_ORDER):
            next_lvl = LADDER_ORDER[next_level_idx]
            req_orders = PROMOTION_REQ_ORDERS.get(next_lvl, 0)
            can_promote = (
                sk_passed
                and (mx_passed if next_lvl != "level_1" else sk_passed)
                and row["successful_orders_at_level"] >= req_orders
                and not row["promotion_blocked_until_utc"]
            )
        return LiveLadderState(
            user_id=user_id,
            current_level=current,
            last_promotion_at_utc=row["last_promotion_at_utc"],
            last_demotion_at_utc=row["last_demotion_at_utc"],
            promotion_blocked_until_utc=row["promotion_blocked_until_utc"],
            blocked_reason=row["blocked_reason"],
            successful_orders_at_level=row["successful_orders_at_level"],
            safekey_passed=sk_passed,
            testnet_matrix_passed=mx_passed,
            can_promote=can_promote,
        )

    def promote_level(self, user_id: str) -> LiveLadderState:
        state = self.get_ladder(user_id)
        if not state.can_promote:
            raise SafetyServiceError(
                f"无法晋级: SafeKey={'✓' if state.safekey_passed else '✗'} "
                f"testnet_matrix={'✓' if state.testnet_matrix_passed else '✗'} "
                f"orders={state.successful_orders_at_level} "
                f"blocked={state.blocked_reason or 'none'}"
            )
        next_idx = LADDER_ORDER.index(state.current_level) + 1
        if next_idx >= len(LADDER_ORDER):
            raise SafetyServiceError("已在最高级 level_5")
        new_level = LADDER_ORDER[next_idx]
        now = _utc_now()
        with self._conn() as c:
            c.execute(
                "UPDATE trading_live_ladder SET current_level=?, last_promotion_at_utc=?, successful_orders_at_level=0, updated_at_utc=? WHERE user_id=?",
                (new_level, now, now, user_id),
            )
            c.commit()
        return self.get_ladder(user_id)

    def demote(self, user_id: str, reason: str) -> LiveLadderState:
        state = self.get_ladder(user_id)
        cur_idx = LADDER_ORDER.index(state.current_level)
        if cur_idx == 0:
            return state  # 已在 level_0
        new_level = LADDER_ORDER[cur_idx - 1]
        now = _utc_now()
        # 阻断 24h 才能再晋级
        block_until = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
        with self._conn() as c:
            c.execute(
                "UPDATE trading_live_ladder SET current_level=?, last_demotion_at_utc=?, promotion_blocked_until_utc=?, blocked_reason=?, successful_orders_at_level=0, updated_at_utc=? WHERE user_id=?",
                (new_level, now, block_until, reason, now, user_id),
            )
            c.commit()
        return self.get_ladder(user_id)

    def record_successful_order(self, user_id: str) -> int:
        with self._conn() as c:
            c.execute(
                "UPDATE trading_live_ladder SET successful_orders_at_level = successful_orders_at_level + 1, updated_at_utc=? WHERE user_id=?",
                (_utc_now(), user_id),
            )
            c.commit()
            row = c.execute(
                "SELECT successful_orders_at_level FROM trading_live_ladder WHERE user_id=?",
                (user_id,),
            ).fetchone()
        return row[0] if row else 0


__all__ = [
    "LADDER_ORDER",
    "LiveLadderState",
    "PROMOTION_REQ_ORDERS",
    "SafeKeyChecklist",
    "SafetyService",
    "SafetyServiceError",
    "TestnetMatrixCell",
    "TestnetMatrixState",
    "init_safety_db",
]
