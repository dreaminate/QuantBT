"""Copy trade service · sqlite + signal relay。

表前缀 `ct_` 避免与 auth/community/sharing 冲突。
"""

from __future__ import annotations

import json
import hmac
import math
import secrets
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Literal

from ..lineage.ids import content_hash
from ..security.mainnet_guards import MainnetGuardError, mainnet_audit_record_from_row
from .consent import PersistentUserRiskConsentStore, RiskConsentError


class CopyTradeError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gen(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


def copy_trade_signal_id(signal: Any) -> str:
    """Canonical identity for the immutable order-bearing signal envelope."""

    value = signal if isinstance(signal, dict) else signal.to_dict()
    payload = {
        key: value.get(key)
        for key in (
            "master_id",
            "symbol",
            "side",
            "quantity",
            "price",
            "order_type",
            "stop_loss",
            "take_profit",
            "leverage",
            "strategy_book_qro_id",
            "signal_validation_ref",
            "market_data_use_validation_ref",
            "instrument_ref",
            "status",
            "published_at_utc",
        )
    }
    payload["symbol"] = str(payload.get("symbol") or "").upper()
    return "signal-" + content_hash(payload)


SignalStatus = Literal["live", "canceled", "filled", "expired"]
FollowerStatus = Literal["activating", "active", "paused", "draining", "stopped"]
ExecutionStatus = Literal[
    "queued",
    "placed",
    "needs_reconcile",
    "filled",
    "rejected",
    "failed",
    "outcome_unknown",
    "skipped",
]


@dataclass
class Master:
    master_id: str
    user_id: str
    display_name: str
    description: str = ""
    asset_class: str = "crypto_perp"
    profit_share_pct: float = 0.10
    is_invite_only: bool = False
    invite_code: str = ""
    follower_count: int = 0
    total_signals: int = 0
    metric_total_return: float | None = None
    metric_sharpe: float | None = None
    metric_max_drawdown: float | None = None
    risk_params: dict[str, Any] = field(default_factory=dict)
    created_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Follower:
    follower_id: str
    user_id: str
    master_id: str
    invest_amount: float = 0.0
    per_order_max_usdt: float = 100.0
    daily_loss_limit_pct: float = 0.05
    max_positions: int = 5
    max_leverage: float | None = None  # v0.8.9 · follower 自己的杠杆硬上限；relay 时硬截断 master 信号杠杆
    binance_keystore_name: str = ""
    binance_network: str = "testnet"
    account_binding_ref: str = ""
    credential_binding_ref: str = ""
    runtime_promotion_ref: str = ""
    user_risk_choice_ref: str = ""
    user_risk_consent_event_ref: str = ""
    activation_ref: str = ""
    status: FollowerStatus = "active"
    started_at_utc: str = ""
    pnl_realized: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def copy_trade_subscription_ref(follower: Follower) -> str:
    """Return the content-addressed identity of the current subscription row.

    A follower row is mutable (pause, drain, activation, and risk-limit changes),
    so the platform source must bind the complete current row rather than the
    stable ``follower_id`` alone.  Any state change therefore invalidates an
    earlier certification instead of silently reusing it.
    """

    return "copy_trade_subscription_" + content_hash(
        {
            "schema_version": 1,
            "record_type": "copy_trade_subscription",
            "follower": follower.to_dict(),
        }
    )


@dataclass(frozen=True)
class MainnetActivationOperation:
    activation_ref: str
    follower_id: str
    user_id: str
    master_id: str
    account_binding_ref: str
    credential_binding_ref: str
    runtime_promotion_ref: str
    user_risk_choice_ref: str
    user_risk_consent_event_ref: str
    runtime_request_ref: str
    risk_profile_ref: str
    status: Literal["prepared", "committed"]
    created_at_utc: str
    updated_at_utc: str


@dataclass
class Signal:
    signal_id: str
    master_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: float | None = None
    order_type: Literal["market", "limit"] = "market"
    stop_loss: float | None = None
    take_profit: float | None = None
    leverage: float | None = None  # v0.8.9 · master 信号上的杠杆（perp/USDM）；relay 时被 follower cap 截断
    strategy_book_qro_id: str = ""
    signal_validation_ref: str = ""
    market_data_use_validation_ref: str = ""
    instrument_ref: str = ""
    note: str = ""
    status: SignalStatus = "live"
    published_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Execution:
    exec_id: str
    signal_id: str
    follower_id: str
    status: ExecutionStatus
    venue_order_id: str | None = None
    filled_qty: float = 0.0
    fill_price: float | None = None
    commission: float = 0.0
    error: str | None = None
    created_at_utc: str = ""
    finished_at_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_INIT_LOCK = threading.Lock()
_INITIALIZED: set[str] = set()


def init_copy_trade_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(db_path.resolve()) + "#copytrade"
    with _INIT_LOCK:
        if key in _INITIALIZED:
            return
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ct_masters (
                master_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL DEFAULT '',
                description TEXT DEFAULT '',
                asset_class TEXT DEFAULT 'crypto_perp',
                profit_share_pct REAL DEFAULT 0.10,
                is_invite_only INTEGER DEFAULT 0,
                invite_code TEXT DEFAULT '',
                follower_count INTEGER DEFAULT 0,
                total_signals INTEGER DEFAULT 0,
                metric_total_return REAL,
                metric_sharpe REAL,
                metric_max_drawdown REAL,
                risk_params TEXT DEFAULT '{}',
                created_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ct_followers (
                follower_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                master_id TEXT NOT NULL,
                invest_amount REAL DEFAULT 0,
                per_order_max_usdt REAL DEFAULT 100,
                daily_loss_limit_pct REAL DEFAULT 0.05,
                max_positions INTEGER DEFAULT 5,
                max_leverage REAL,
                binance_keystore_name TEXT DEFAULT '',
                binance_network TEXT DEFAULT 'testnet',
                account_binding_ref TEXT DEFAULT '',
                credential_binding_ref TEXT DEFAULT '',
                runtime_promotion_ref TEXT DEFAULT '',
                user_risk_choice_ref TEXT DEFAULT '',
                user_risk_consent_event_ref TEXT DEFAULT '',
                activation_ref TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                started_at_utc TEXT NOT NULL,
                pnl_realized REAL DEFAULT 0,
                UNIQUE(user_id, master_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ct_followers_master ON ct_followers(master_id);
            CREATE INDEX IF NOT EXISTS idx_ct_followers_user ON ct_followers(user_id);

            CREATE TABLE IF NOT EXISTS ct_mainnet_account_bindings (
                account_binding_ref TEXT PRIMARY KEY CHECK(account_binding_ref!=''),
                follower_id TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                master_id TEXT NOT NULL,
                first_bound_at_utc TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ct_mainnet_activation_operations (
                activation_ref TEXT PRIMARY KEY,
                follower_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                master_id TEXT NOT NULL,
                account_binding_ref TEXT NOT NULL,
                credential_binding_ref TEXT NOT NULL DEFAULT '',
                runtime_promotion_ref TEXT NOT NULL,
                user_risk_choice_ref TEXT NOT NULL,
                user_risk_consent_event_ref TEXT NOT NULL DEFAULT '',
                runtime_request_ref TEXT NOT NULL DEFAULT '',
                risk_profile_ref TEXT NOT NULL DEFAULT '',
                activation_audit_ref TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL
                    CHECK(status IN ('prepared','committed','audited','failed')),
                created_at_utc TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ct_mainnet_activation_status
                ON ct_mainnet_activation_operations(status, updated_at_utc);

            CREATE TABLE IF NOT EXISTS ct_signals (
                signal_id TEXT PRIMARY KEY,
                master_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL,
                order_type TEXT DEFAULT 'market',
                stop_loss REAL,
                take_profit REAL,
                leverage REAL,
                strategy_book_qro_id TEXT DEFAULT '',
                signal_validation_ref TEXT DEFAULT '',
                market_data_use_validation_ref TEXT DEFAULT '',
                instrument_ref TEXT DEFAULT '',
                note TEXT DEFAULT '',
                status TEXT DEFAULT 'live',
                published_at_utc TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ct_signals_master ON ct_signals(master_id);

            CREATE TABLE IF NOT EXISTS ct_executions (
                exec_id TEXT PRIMARY KEY,
                signal_id TEXT NOT NULL,
                follower_id TEXT NOT NULL,
                status TEXT NOT NULL,
                venue_order_id TEXT,
                filled_qty REAL DEFAULT 0,
                fill_price REAL,
                commission REAL DEFAULT 0,
                error TEXT,
                created_at_utc TEXT NOT NULL,
                finished_at_utc TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ct_exec_signal ON ct_executions(signal_id);
            CREATE INDEX IF NOT EXISTS idx_ct_exec_follower ON ct_executions(follower_id);

            CREATE TABLE IF NOT EXISTS ct_invites_redeemed (
                user_id TEXT NOT NULL,
                master_id TEXT NOT NULL,
                redeemed_at_utc TEXT NOT NULL,
                PRIMARY KEY (user_id, master_id)
            );
            """
        )
        # v0.8.9 · 已有库的轻量列迁移（杠杆截断需要 signal.leverage / follower.max_leverage）
        for table, col, decl in (
            ("ct_signals", "leverage", "REAL"),
            ("ct_followers", "max_leverage", "REAL"),
            ("ct_followers", "account_binding_ref", "TEXT DEFAULT ''"),
            ("ct_followers", "credential_binding_ref", "TEXT DEFAULT ''"),
            ("ct_followers", "runtime_promotion_ref", "TEXT DEFAULT ''"),
            ("ct_followers", "user_risk_choice_ref", "TEXT DEFAULT ''"),
            ("ct_followers", "user_risk_consent_event_ref", "TEXT DEFAULT ''"),
            ("ct_followers", "activation_ref", "TEXT DEFAULT ''"),
            ("ct_mainnet_activation_operations", "credential_binding_ref", "TEXT NOT NULL DEFAULT ''"),
            ("ct_mainnet_activation_operations", "user_risk_consent_event_ref", "TEXT NOT NULL DEFAULT ''"),
            ("ct_mainnet_activation_operations", "runtime_request_ref", "TEXT NOT NULL DEFAULT ''"),
            ("ct_mainnet_activation_operations", "risk_profile_ref", "TEXT NOT NULL DEFAULT ''"),
            ("ct_mainnet_activation_operations", "activation_audit_ref", "TEXT NOT NULL DEFAULT ''"),
            ("ct_signals", "strategy_book_qro_id", "TEXT DEFAULT ''"),
            ("ct_signals", "signal_validation_ref", "TEXT DEFAULT ''"),
            ("ct_signals", "market_data_use_validation_ref", "TEXT DEFAULT ''"),
            ("ct_signals", "instrument_ref", "TEXT DEFAULT ''"),
        ):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass  # 列已存在
        conn.execute("DROP INDEX IF EXISTS idx_ct_one_active_mainnet_account")
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ct_one_mainnet_account_history "
            "ON ct_followers(account_binding_ref) "
            "WHERE binance_network='mainnet' AND account_binding_ref!=''"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ct_one_activation_per_consent "
            "ON ct_mainnet_activation_operations(user_risk_consent_event_ref) "
            "WHERE user_risk_consent_event_ref!=''"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_ct_one_inflight_activation_per_follower "
            "ON ct_mainnet_activation_operations(follower_id) "
            "WHERE status IN ('prepared','committed')"
        )
        legacy_bindings = conn.execute(
            "SELECT account_binding_ref,follower_id,user_id,master_id,started_at_utc "
            "FROM ct_followers WHERE binance_network='mainnet' AND account_binding_ref!=''"
        ).fetchall()
        for account_ref, follower_id, user_id, master_id, started_at in legacy_bindings:
            by_account = conn.execute(
                "SELECT * FROM ct_mainnet_account_bindings WHERE account_binding_ref=?",
                (account_ref,),
            ).fetchone()
            by_follower = conn.execute(
                "SELECT * FROM ct_mainnet_account_bindings WHERE follower_id=?",
                (follower_id,),
            ).fetchone()
            for existing in (by_account, by_follower):
                if existing is not None and (
                    existing["account_binding_ref"] != account_ref
                    or existing["follower_id"] != follower_id
                    or existing["user_id"] != user_id
                    or existing["master_id"] != master_id
                ):
                    raise CopyTradeError(
                        "persisted mainnet account history contains an immutable binding conflict"
                    )
            if by_account is None and by_follower is None:
                conn.execute(
                    """
                    INSERT INTO ct_mainnet_account_bindings (
                        account_binding_ref,follower_id,user_id,master_id,first_bound_at_utc
                    ) VALUES (?,?,?,?,?)
                    """,
                    (account_ref, follower_id, user_id, master_id, started_at),
                )
        conn.commit()
        conn.close()
        _INITIALIZED.add(key)


class CopyTradeService:
    """所有 copy-trade 业务逻辑。Signal relay 由 SignalRelayer (executor.py) 异步触发。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        init_copy_trade_db(db_path)
        self.risk_consents = PersistentUserRiskConsentStore(db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        return conn

    # =========== Master ===========

    def register_master(
        self,
        user_id: str,
        display_name: str,
        *,
        description: str = "",
        asset_class: str = "crypto_perp",
        profit_share_pct: float = 0.10,
        is_invite_only: bool = False,
        risk_params: dict[str, Any] | None = None,
    ) -> Master:
        if asset_class not in {"equity_cn", "crypto_perp", "crypto_spot", "mixed"}:
            raise CopyTradeError(f"非法 asset_class: {asset_class}")
        if not 0 <= profit_share_pct <= 0.5:
            raise CopyTradeError("profit_share_pct 必须在 [0, 0.5] 之间")
        conn = self._conn()
        try:
            existing = conn.execute("SELECT master_id FROM ct_masters WHERE user_id = ?", (user_id,)).fetchone()
            if existing:
                raise CopyTradeError("该用户已经是 master，请用 update_master 修改")
            master_id = _gen("master")
            invite_code = secrets.token_urlsafe(12) if is_invite_only else ""
            now = _now()
            conn.execute(
                """
                INSERT INTO ct_masters (
                    master_id, user_id, display_name, description, asset_class,
                    profit_share_pct, is_invite_only, invite_code,
                    risk_params, created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    master_id, user_id, display_name, description, asset_class,
                    profit_share_pct, 1 if is_invite_only else 0, invite_code,
                    json.dumps(risk_params or {}), now,
                ),
            )
            return Master(
                master_id=master_id, user_id=user_id, display_name=display_name,
                description=description, asset_class=asset_class,
                profit_share_pct=profit_share_pct, is_invite_only=is_invite_only,
                invite_code=invite_code, risk_params=risk_params or {},
                created_at_utc=now,
            )
        finally:
            conn.close()

    def update_master(
        self,
        master_id: str,
        user_id: str,
        *,
        description: str | None = None,
        profit_share_pct: float | None = None,
        is_invite_only: bool | None = None,
        risk_params: dict[str, Any] | None = None,
    ) -> Master:
        conn = self._conn()
        try:
            row = conn.execute("SELECT user_id, is_invite_only, invite_code FROM ct_masters WHERE master_id = ?", (master_id,)).fetchone()
            if row is None:
                raise CopyTradeError("master 不存在")
            if row["user_id"] != user_id:
                raise PermissionError("只能修改自己注册的 master")
            sets: list[str] = []
            args: list[Any] = []
            if description is not None:
                sets.append("description = ?"); args.append(description)
            if profit_share_pct is not None:
                if not 0 <= profit_share_pct <= 0.5:
                    raise CopyTradeError("profit_share_pct 必须在 [0, 0.5]")
                sets.append("profit_share_pct = ?"); args.append(profit_share_pct)
            if is_invite_only is not None:
                sets.append("is_invite_only = ?"); args.append(1 if is_invite_only else 0)
                # 切到 invite_only 时若无 code 自动生成
                if is_invite_only and not row["invite_code"]:
                    sets.append("invite_code = ?"); args.append(secrets.token_urlsafe(12))
            if risk_params is not None:
                sets.append("risk_params = ?"); args.append(json.dumps(risk_params))
            if sets:
                args.append(master_id)
                conn.execute(f"UPDATE ct_masters SET {', '.join(sets)} WHERE master_id = ?", args)
            return self.get_master(master_id)  # type: ignore[return-value]
        finally:
            conn.close()

    def rotate_invite_code(self, master_id: str, user_id: str) -> str:
        """轮换 invite_code（已 redeem 的 follower 不受影响）。"""
        conn = self._conn()
        try:
            row = conn.execute("SELECT user_id FROM ct_masters WHERE master_id = ?", (master_id,)).fetchone()
            if row is None:
                raise CopyTradeError("master 不存在")
            if row["user_id"] != user_id:
                raise PermissionError("不是 master 拥有者")
            new_code = secrets.token_urlsafe(12)
            conn.execute("UPDATE ct_masters SET invite_code = ? WHERE master_id = ?", (new_code, master_id))
            return new_code
        finally:
            conn.close()

    def get_master(self, master_id: str) -> Master | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM ct_masters WHERE master_id = ?", (master_id,)).fetchone()
            if row is None:
                return None
            return _row_to_master(row)
        finally:
            conn.close()

    def get_master_by_user(self, user_id: str) -> Master | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM ct_masters WHERE user_id = ?", (user_id,)).fetchone()
            return _row_to_master(row) if row else None
        finally:
            conn.close()

    def list_masters(
        self,
        *,
        asset_class: str | None = None,
        sort_by: str = "followers",
        invite_only: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Master]:
        order_map = {
            "followers": "follower_count DESC, total_signals DESC",
            "sharpe": "metric_sharpe DESC NULLS LAST, follower_count DESC",
            "return": "metric_total_return DESC NULLS LAST, follower_count DESC",
            "drawdown_low": "metric_max_drawdown DESC NULLS LAST",  # max_drawdown 是负数；DESC = 回撤小
            "signals": "total_signals DESC",
            "recent": "created_at_utc DESC",
        }
        order = order_map.get(sort_by, order_map["followers"])
        where: list[str] = []
        params: list[Any] = []
        if asset_class:
            where.append("asset_class = ?"); params.append(asset_class)
        if invite_only is True:
            where.append("is_invite_only = 1")
        elif invite_only is False:
            where.append("is_invite_only = 0")
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.extend([limit, offset])
        conn = self._conn()
        try:
            rows = conn.execute(
                f"SELECT * FROM ct_masters {where_clause} ORDER BY {order} LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            return [_row_to_master(r) for r in rows]
        finally:
            conn.close()

    def set_master_metrics(
        self,
        master_id: str,
        *,
        total_return: float | None = None,
        sharpe: float | None = None,
        max_drawdown: float | None = None,
    ) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE ct_masters SET metric_total_return = ?, metric_sharpe = ?, metric_max_drawdown = ? WHERE master_id = ?",
                (total_return, sharpe, max_drawdown, master_id),
            )
        finally:
            conn.close()

    # =========== Follower / 订阅 ===========

    def redeem_invite(self, user_id: str, master_id: str, invite_code: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute("SELECT is_invite_only, invite_code FROM ct_masters WHERE master_id = ?", (master_id,)).fetchone()
            if row is None:
                raise CopyTradeError("master 不存在")
            if not row["is_invite_only"]:
                return True  # 公开 master 无需 redeem
            if invite_code != row["invite_code"]:
                raise CopyTradeError("invite_code 无效")
            try:
                conn.execute(
                    "INSERT INTO ct_invites_redeemed (user_id, master_id, redeemed_at_utc) VALUES (?, ?, ?)",
                    (user_id, master_id, _now()),
                )
            except sqlite3.IntegrityError:
                pass  # 已 redeem
            return True
        finally:
            conn.close()

    def has_redeemed(self, user_id: str, master_id: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM ct_invites_redeemed WHERE user_id = ? AND master_id = ?",
                (user_id, master_id),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def subscribe(
        self,
        user_id: str,
        master_id: str,
        *,
        invest_amount: float,
        binance_keystore_name: str,
        binance_network: str = "testnet",
        per_order_max_usdt: float = 100.0,
        daily_loss_limit_pct: float = 0.05,
        max_positions: int = 5,
        max_leverage: float | None = None,
        account_binding_ref: str = "",
        credential_binding_ref: str = "",
        runtime_promotion_ref: str = "",
        user_risk_choice_ref: str = "",
        user_risk_consent_event_ref: str = "",
        initial_status: str = "active",
    ) -> Follower:
        numeric = (invest_amount, per_order_max_usdt, daily_loss_limit_pct)
        if not all(math.isfinite(float(value)) for value in numeric):
            raise CopyTradeError("subscription risk limits must be finite")
        if invest_amount <= 0:
            raise CopyTradeError("invest_amount 必须 > 0")
        if per_order_max_usdt <= 0:
            raise CopyTradeError("per_order_max_usdt 必须 > 0")
        if not 0 < daily_loss_limit_pct <= 1:
            raise CopyTradeError("daily_loss_limit_pct 必须在 (0, 1] 之间")
        if max_positions <= 0:
            raise CopyTradeError("max_positions 必须 > 0")
        if max_leverage is not None and (not math.isfinite(float(max_leverage)) or max_leverage <= 0):
            raise CopyTradeError("max_leverage 必须 > 0")
        if not binance_keystore_name:
            raise CopyTradeError("必须填 binance_keystore_name (follower 自己的 keystore 引用)")
        if binance_network not in {"testnet", "mainnet"}:
            raise CopyTradeError("binance_network 必须是 testnet 或 mainnet")
        if binance_network == "mainnet" and (
            not account_binding_ref or not runtime_promotion_ref or not user_risk_choice_ref
        ):
            raise CopyTradeError(
                "mainnet subscription requires account_binding_ref, runtime_promotion_ref, and user_risk_choice_ref"
            )
        if initial_status not in {"active", "activating"}:
            raise CopyTradeError("subscription initial_status must be active or activating")
        if initial_status == "activating" and binance_network != "mainnet":
            raise CopyTradeError("activating status is reserved for staged mainnet activation")
        master = self.get_master(master_id)
        if master is None:
            raise CopyTradeError("master 不存在")
        if master.user_id == user_id:
            raise CopyTradeError("不能跟单自己")
        if master.is_invite_only and not self.has_redeemed(user_id, master_id):
            raise CopyTradeError("此 master 为私域，请先用 invite_code redeem")
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            fid = f"{user_id}::{master_id}"
            now = _now()
            if binance_network == "mainnet":
                account_history = conn.execute(
                    "SELECT * FROM ct_mainnet_account_bindings WHERE account_binding_ref=?",
                    (account_binding_ref,),
                ).fetchone()
                follower_history = conn.execute(
                    "SELECT * FROM ct_mainnet_account_bindings WHERE follower_id=?",
                    (fid,),
                ).fetchone()
                if account_history is not None and account_history["follower_id"] != fid:
                    raise CopyTradeError("该 Binance 账户已由另一个 mainnet follower 历史占用")
                if (
                    follower_history is not None
                    and follower_history["account_binding_ref"] != account_binding_ref
                ):
                    raise CopyTradeError("mainnet follower account binding is immutable")
                if account_history is None and follower_history is None:
                    conn.execute(
                        """
                        INSERT INTO ct_mainnet_account_bindings (
                            account_binding_ref,follower_id,user_id,master_id,first_bound_at_utc
                        ) VALUES (?,?,?,?,?)
                        """,
                        (account_binding_ref, fid, user_id, master_id, now),
                    )
            try:
                conn.execute(
                    """
                    INSERT INTO ct_followers (
                        follower_id, user_id, master_id, invest_amount, per_order_max_usdt,
                        daily_loss_limit_pct, max_positions, max_leverage, binance_keystore_name, binance_network,
                        account_binding_ref, credential_binding_ref, runtime_promotion_ref,
                        user_risk_choice_ref, user_risk_consent_event_ref, activation_ref,
                        status, started_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)
                    """,
                    (
                        fid, user_id, master_id, invest_amount, per_order_max_usdt,
                        daily_loss_limit_pct, max_positions, max_leverage, binance_keystore_name, binance_network,
                        account_binding_ref, credential_binding_ref, runtime_promotion_ref,
                        user_risk_choice_ref, user_risk_consent_event_ref,
                        initial_status, now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                existing = conn.execute(
                    "SELECT follower_id FROM ct_followers WHERE user_id=? AND master_id=?",
                    (user_id, master_id),
                ).fetchone()
                if existing is None:
                    raise CopyTradeError("mainnet account binding collided during subscription") from exc
                # 已订阅过 → 改成 active 并更新参数
                conn.execute(
                    """
                    UPDATE ct_followers SET
                        invest_amount = ?, per_order_max_usdt = ?, daily_loss_limit_pct = ?,
                        max_positions = ?, max_leverage = ?, binance_keystore_name = ?, binance_network = ?,
                        account_binding_ref = ?, credential_binding_ref = ?, runtime_promotion_ref = ?,
                        user_risk_choice_ref = ?, user_risk_consent_event_ref = ?,
                        activation_ref = '', status = ?
                    WHERE user_id = ? AND master_id = ?
                    """,
                    (invest_amount, per_order_max_usdt, daily_loss_limit_pct,
                     max_positions, max_leverage, binance_keystore_name, binance_network,
                     account_binding_ref, credential_binding_ref, runtime_promotion_ref,
                     user_risk_choice_ref, user_risk_consent_event_ref,
                     initial_status, user_id, master_id),
                )
            conn.execute(
                "UPDATE ct_masters SET follower_count = (SELECT COUNT(*) FROM ct_followers WHERE master_id = ? AND status = 'active') WHERE master_id = ?",
                (master_id, master_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        follower = self.get_follower(fid)
        if follower is None:  # pragma: no cover - committed transaction invariant.
            raise CopyTradeError("committed follower row disappeared")
        return follower

    @staticmethod
    def _activation_operation_from_row(row: sqlite3.Row) -> MainnetActivationOperation:
        values = {
            field: str(row[field] or "").strip()
            for field in (
                "activation_ref",
                "follower_id",
                "user_id",
                "master_id",
                "account_binding_ref",
                "credential_binding_ref",
                "runtime_promotion_ref",
                "user_risk_choice_ref",
                "user_risk_consent_event_ref",
                "runtime_request_ref",
                "risk_profile_ref",
                "status",
                "created_at_utc",
                "updated_at_utc",
            )
        }
        legacy_optional = {
            "credential_binding_ref",
            "user_risk_consent_event_ref",
            "runtime_request_ref",
            "risk_profile_ref",
        }
        if (
            not all(value for name, value in values.items() if name not in legacy_optional)
            or values["status"] not in {"prepared", "committed"}
        ):
            raise CopyTradeError("persisted mainnet activation operation is incomplete")
        return MainnetActivationOperation(**values)  # type: ignore[arg-type]

    def prepare_mainnet_activation(
        self,
        *,
        activation_ref: str,
        user_id: str,
        master_id: str,
        account_binding_ref: str,
        credential_binding_ref: str,
        runtime_promotion_ref: str,
        user_risk_choice_ref: str,
        user_risk_consent_event_ref: str,
        runtime_request_ref: str,
        risk_profile_ref: str,
    ) -> MainnetActivationOperation:
        """Persist the activation intent before the follower can become active."""

        values = {
            "activation_ref": str(activation_ref or "").strip(),
            "user_id": str(user_id or "").strip(),
            "master_id": str(master_id or "").strip(),
            "account_binding_ref": str(account_binding_ref or "").strip(),
            "credential_binding_ref": str(credential_binding_ref or "").strip(),
            "runtime_promotion_ref": str(runtime_promotion_ref or "").strip(),
            "user_risk_choice_ref": str(user_risk_choice_ref or "").strip(),
            "user_risk_consent_event_ref": str(user_risk_consent_event_ref or "").strip(),
            "runtime_request_ref": str(runtime_request_ref or "").strip(),
            "risk_profile_ref": str(risk_profile_ref or "").strip(),
        }
        if not all(values.values()):
            raise CopyTradeError("mainnet activation operation requires exact durable refs")
        follower_id = f"{values['user_id']}::{values['master_id']}"
        now = _now()
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            follower = conn.execute(
                "SELECT * FROM ct_followers WHERE follower_id=?",
                (follower_id,),
            ).fetchone()
            if follower is None or (
                follower["status"] != "activating"
                or follower["binance_network"] != "mainnet"
                or str(follower["activation_ref"] or "")
                or follower["account_binding_ref"] != values["account_binding_ref"]
                or follower["credential_binding_ref"] != values["credential_binding_ref"]
                or follower["runtime_promotion_ref"] != values["runtime_promotion_ref"]
                or follower["user_risk_choice_ref"] != values["user_risk_choice_ref"]
                or follower["user_risk_consent_event_ref"]
                != values["user_risk_consent_event_ref"]
            ):
                raise CopyTradeError("mainnet activation operation does not match the staged follower")
            self.risk_consents.validate_event_for_activation(
                conn,
                consent_event_ref=values["user_risk_consent_event_ref"],
                owner_user_id=values["user_id"],
                follower_id=follower_id,
                master_id=values["master_id"],
                account_binding_ref=values["account_binding_ref"],
                credential_binding_ref=values["credential_binding_ref"],
                runtime_request_ref=values["runtime_request_ref"],
                user_risk_choice_ref=values["user_risk_choice_ref"],
                risk_profile_ref=values["risk_profile_ref"],
            )
            existing = conn.execute(
                "SELECT * FROM ct_mainnet_activation_operations WHERE activation_ref=?",
                (values["activation_ref"],),
            ).fetchone()
            if existing is None:
                try:
                    conn.execute(
                        """
                        INSERT INTO ct_mainnet_activation_operations (
                            activation_ref,follower_id,user_id,master_id,account_binding_ref,
                            credential_binding_ref,runtime_promotion_ref,user_risk_choice_ref,
                            user_risk_consent_event_ref,runtime_request_ref,risk_profile_ref,status,
                            created_at_utc,updated_at_utc
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,'prepared',?,?)
                        """,
                        (
                            values["activation_ref"],
                            follower_id,
                            values["user_id"],
                            values["master_id"],
                            values["account_binding_ref"],
                            values["credential_binding_ref"],
                            values["runtime_promotion_ref"],
                            values["user_risk_choice_ref"],
                            values["user_risk_consent_event_ref"],
                            values["runtime_request_ref"],
                            values["risk_profile_ref"],
                            now,
                            now,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise CopyTradeError(
                        "mainnet activation consent or follower is already permanently claimed"
                    ) from exc
            else:
                operation = self._activation_operation_from_row(existing)
                if operation != MainnetActivationOperation(
                    activation_ref=values["activation_ref"],
                    follower_id=follower_id,
                    user_id=values["user_id"],
                    master_id=values["master_id"],
                    account_binding_ref=values["account_binding_ref"],
                    credential_binding_ref=values["credential_binding_ref"],
                    runtime_promotion_ref=values["runtime_promotion_ref"],
                    user_risk_choice_ref=values["user_risk_choice_ref"],
                    user_risk_consent_event_ref=values["user_risk_consent_event_ref"],
                    runtime_request_ref=values["runtime_request_ref"],
                    risk_profile_ref=values["risk_profile_ref"],
                    status="prepared",
                    created_at_utc=operation.created_at_utc,
                    updated_at_utc=operation.updated_at_utc,
                ):
                    raise CopyTradeError("mainnet activation operation identity collision")
            row = conn.execute(
                "SELECT * FROM ct_mainnet_activation_operations WHERE activation_ref=?",
                (values["activation_ref"],),
            ).fetchone()
            if row is None:  # pragma: no cover - transaction invariant.
                raise CopyTradeError("mainnet activation operation disappeared")
            operation = self._activation_operation_from_row(row)
            conn.commit()
            return operation
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def unfinished_mainnet_activations(self) -> tuple[MainnetActivationOperation, ...]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM ct_mainnet_activation_operations "
                "WHERE status IN ('prepared','committed') "
                "ORDER BY created_at_utc,activation_ref"
            ).fetchall()
        finally:
            conn.close()
        return tuple(self._activation_operation_from_row(row) for row in rows)

    def _finish_mainnet_activation(
        self,
        activation_ref: str,
        *,
        status: str,
        activation_audit_ref: str = "",
    ) -> None:
        if status not in {"audited", "failed"}:
            raise ValueError("mainnet activation terminal status is invalid")
        ref = str(activation_ref or "").strip()
        if not ref:
            raise CopyTradeError("mainnet activation_ref is required")
        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ct_mainnet_activation_operations WHERE activation_ref=?",
                (ref,),
            ).fetchone()
            if row is None:
                raise CopyTradeError("mainnet activation operation is missing")
            current = str(row["status"] or "")
            if current == status:
                if status == "audited" and not hmac.compare_digest(
                    str(row["activation_audit_ref"] or ""),
                    str(activation_audit_ref or ""),
                ):
                    raise CopyTradeError("mainnet activation audit ref changed after commit")
                conn.commit()
                return
            allowed = {"committed"} if status == "audited" else {"prepared", "committed"}
            if current not in allowed:
                raise CopyTradeError("mainnet activation operation is already terminal")
            exact_audit_ref = str(activation_audit_ref or "").strip()
            if status == "audited":
                if not exact_audit_ref:
                    raise CopyTradeError("mainnet activation requires its exact durable audit ref")
                try:
                    audit_row = conn.execute(
                        "SELECT * FROM mainnet_audit_log WHERE audit_ref=?",
                        (exact_audit_ref,),
                    ).fetchone()
                except sqlite3.OperationalError as exc:
                    raise CopyTradeError("mainnet activation audit store is unavailable") from exc
                if audit_row is None:
                    raise CopyTradeError("mainnet activation audit record is missing")
                try:
                    audit = mainnet_audit_record_from_row(audit_row)
                except MainnetGuardError as exc:
                    raise CopyTradeError("mainnet activation audit record is invalid") from exc
                if (
                    audit.user_id != str(row["user_id"])
                    or audit.operation != "copy_trade_subscription"
                    or audit.operation_ref != ref
                    or audit.result != "ok"
                ):
                    raise CopyTradeError("mainnet activation audit record does not authorize activation")
            cur = conn.execute(
                "UPDATE ct_mainnet_activation_operations "
                "SET status=?,activation_audit_ref=?,updated_at_utc=? "
                "WHERE activation_ref=? AND status=?",
                (status, exact_audit_ref, _now(), ref, current),
            )
            if cur.rowcount != 1:
                raise CopyTradeError("mainnet activation terminal CAS failed")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_mainnet_activation_audited(
        self,
        activation_ref: str,
        *,
        activation_audit_ref: str,
    ) -> None:
        self._finish_mainnet_activation(
            activation_ref,
            status="audited",
            activation_audit_ref=activation_audit_ref,
        )

    def mark_mainnet_activation_failed(self, activation_ref: str) -> None:
        self._finish_mainnet_activation(activation_ref, status="failed")

    def activate_subscription(
        self,
        user_id: str,
        master_id: str,
        *,
        activation_ref: str,
        account_binding_ref: str,
        binance_keystore_name: str,
        credential_binding_ref: str,
        runtime_promotion_ref: str,
        user_risk_choice_ref: str,
        user_risk_consent_event_ref: str,
        runtime_request_ref: str,
        risk_profile_ref: str,
    ) -> Follower:
        """Atomically expose a fully audited staged mainnet subscription to relays."""

        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            operation = conn.execute(
                "SELECT * FROM ct_mainnet_activation_operations WHERE activation_ref=?",
                (str(activation_ref or "").strip(),),
            ).fetchone()
            if operation is None or (
                operation["status"] != "prepared"
                or operation["follower_id"] != f"{user_id}::{master_id}"
                or operation["account_binding_ref"] != account_binding_ref
                or operation["credential_binding_ref"] != credential_binding_ref
                or operation["runtime_promotion_ref"] != runtime_promotion_ref
                or operation["user_risk_choice_ref"] != user_risk_choice_ref
                or operation["user_risk_consent_event_ref"] != user_risk_consent_event_ref
                or operation["runtime_request_ref"] != runtime_request_ref
                or operation["risk_profile_ref"] != risk_profile_ref
            ):
                raise CopyTradeError("mainnet activation operation does not authorize this follower CAS")
            cur = conn.execute(
                """
                UPDATE ct_followers SET status='active', activation_ref=?
                WHERE user_id=? AND master_id=? AND status='activating'
                  AND binance_network='mainnet' AND account_binding_ref=?
                  AND binance_keystore_name=? AND credential_binding_ref=?
                  AND runtime_promotion_ref=? AND user_risk_choice_ref=?
                  AND user_risk_consent_event_ref=? AND activation_ref=''
                """,
                (
                    str(activation_ref),
                    user_id,
                    master_id,
                    account_binding_ref,
                    binance_keystore_name,
                    credential_binding_ref,
                    runtime_promotion_ref,
                    user_risk_choice_ref,
                    user_risk_consent_event_ref,
                ),
            )
            if cur.rowcount != 1:
                raise CopyTradeError("staged mainnet subscription could not transition to active")
            activation_cur = conn.execute(
                "UPDATE ct_mainnet_activation_operations "
                "SET status='committed',updated_at_utc=? "
                "WHERE activation_ref=? AND status='prepared'",
                (_now(), str(activation_ref)),
            )
            if activation_cur.rowcount != 1:
                raise CopyTradeError("mainnet activation operation commit CAS failed")
            conn.execute(
                "UPDATE ct_masters SET follower_count = "
                "(SELECT COUNT(*) FROM ct_followers WHERE master_id=? AND status='active') "
                "WHERE master_id=?",
                (master_id, master_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        follower = self.get_follower(f"{user_id}::{master_id}")
        if follower is None:
            raise CopyTradeError("activated follower row disappeared")
        return follower

    def unsubscribe(self, user_id: str, master_id: str) -> bool:
        conn = self._conn()
        try:
            cur = conn.execute(
                "UPDATE ct_followers SET status = 'stopped' WHERE user_id = ? AND master_id = ? AND status != 'stopped'",
                (user_id, master_id),
            )
            if cur.rowcount > 0:
                conn.execute(
                    "UPDATE ct_masters SET follower_count = (SELECT COUNT(*) FROM ct_followers WHERE master_id = ? AND status = 'active') WHERE master_id = ?",
                    (master_id, master_id),
                )
                return True
            return False
        finally:
            conn.close()

    def begin_draining(self, user_id: str, master_id: str) -> bool:
        """Stop new relay selection while retaining emergency account controls."""

        conn = self._conn()
        try:
            cur = conn.execute(
                "UPDATE ct_followers SET status='draining' "
                "WHERE user_id=? AND master_id=? AND status IN ('activating','active','paused')",
                (user_id, master_id),
            )
            if cur.rowcount > 0:
                conn.execute(
                    "UPDATE ct_masters SET follower_count = "
                    "(SELECT COUNT(*) FROM ct_followers WHERE master_id=? AND status='active') "
                    "WHERE master_id=?",
                    (master_id, master_id),
                )
                return True
            return False
        finally:
            conn.close()

    def finalize_stop(self, user_id: str, master_id: str) -> bool:
        """Finalize a draining/stopped subscription after external exposure proof."""

        conn = self._conn()
        try:
            cur = conn.execute(
                "UPDATE ct_followers SET status='stopped' "
                "WHERE user_id=? AND master_id=? AND status='draining'",
                (user_id, master_id),
            )
            return cur.rowcount > 0
        finally:
            conn.close()

    def restore_follower_state(
        self,
        user_id: str,
        master_id: str,
        previous: Follower | None,
        *,
        expected_account_binding_ref: str,
        expected_binance_keystore_name: str,
        expected_runtime_promotion_ref: str,
        expected_user_risk_choice_ref: str,
        expected_credential_binding_ref: str = "",
        expected_user_risk_consent_event_ref: str = "",
    ) -> bool:
        """CAS-restore a staged activation without overwriting a concurrent drain."""

        conn = self._conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ct_followers WHERE user_id=? AND master_id=?",
                (user_id, master_id),
            ).fetchone()
            current = _row_to_follower(row) if row is not None else None
            if current is None:
                if previous is None:
                    conn.commit()
                    return True
                conn.rollback()
                return False
            if previous is not None and current == previous:
                conn.commit()
                return True
            staged_matches = (
                current.status == "activating"
                and current.binance_network == "mainnet"
                and current.account_binding_ref == expected_account_binding_ref
                and current.binance_keystore_name == expected_binance_keystore_name
                and current.credential_binding_ref == expected_credential_binding_ref
                and current.runtime_promotion_ref == expected_runtime_promotion_ref
                and current.user_risk_choice_ref == expected_user_risk_choice_ref
                and current.user_risk_consent_event_ref
                == expected_user_risk_consent_event_ref
                and not current.activation_ref
            )
            if not staged_matches:
                conn.rollback()
                return False
            if previous is None:
                cur = conn.execute(
                    """
                    DELETE FROM ct_followers
                    WHERE user_id=? AND master_id=? AND status='activating'
                      AND binance_network='mainnet' AND account_binding_ref=?
                      AND binance_keystore_name=? AND credential_binding_ref=?
                      AND runtime_promotion_ref=? AND user_risk_choice_ref=?
                      AND user_risk_consent_event_ref=?
                    """,
                    (
                        user_id,
                        master_id,
                        expected_account_binding_ref,
                        expected_binance_keystore_name,
                        expected_credential_binding_ref,
                        expected_runtime_promotion_ref,
                        expected_user_risk_choice_ref,
                        expected_user_risk_consent_event_ref,
                    ),
                )
                if cur.rowcount != 1:
                    raise CopyTradeError("staged follower compensation lost its activation CAS")
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO ct_followers (
                        follower_id, user_id, master_id, invest_amount, per_order_max_usdt,
                        daily_loss_limit_pct, max_positions, max_leverage, binance_keystore_name,
                        binance_network, account_binding_ref, credential_binding_ref,
                        runtime_promotion_ref, user_risk_choice_ref,
                        user_risk_consent_event_ref, activation_ref, status,
                        started_at_utc, pnl_realized
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        previous.follower_id,
                        previous.user_id,
                        previous.master_id,
                        previous.invest_amount,
                        previous.per_order_max_usdt,
                        previous.daily_loss_limit_pct,
                        previous.max_positions,
                        previous.max_leverage,
                        previous.binance_keystore_name,
                        previous.binance_network,
                        previous.account_binding_ref,
                        previous.credential_binding_ref,
                        previous.runtime_promotion_ref,
                        previous.user_risk_choice_ref,
                        previous.user_risk_consent_event_ref,
                        previous.activation_ref,
                        previous.status,
                        previous.started_at_utc,
                        previous.pnl_realized,
                    ),
                )
            conn.execute(
                "UPDATE ct_masters SET follower_count = "
                "(SELECT COUNT(*) FROM ct_followers WHERE master_id=? AND status='active') "
                "WHERE master_id=?",
                (master_id, master_id),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def pause_subscription(self, user_id: str, master_id: str, paused: bool = True) -> bool:
        conn = self._conn()
        try:
            target = "paused" if paused else "active"
            cur = conn.execute(
                "UPDATE ct_followers SET status = ? "
                "WHERE user_id = ? AND master_id = ? AND status IN ('active','paused')",
                (target, user_id, master_id),
            )
            if cur.rowcount > 0:
                conn.execute(
                    "UPDATE ct_masters SET follower_count = (SELECT COUNT(*) FROM ct_followers WHERE master_id = ? AND status = 'active') WHERE master_id = ?",
                    (master_id, master_id),
                )
                return True
            return False
        finally:
            conn.close()

    def get_follower(self, follower_id: str) -> Follower | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM ct_followers WHERE follower_id = ?", (follower_id,)).fetchone()
            return _row_to_follower(row) if row else None
        finally:
            conn.close()

    def subscription(self, subscription_ref: str, *, owner_user_id: str) -> Follower:
        """Resolve one exact current owner-scoped subscription identity."""

        ref = str(subscription_ref or "").strip()
        owner = str(owner_user_id or "").strip()
        if not ref.startswith("copy_trade_subscription_") or not owner:
            raise CopyTradeError("canonical subscription ref and owner are required")
        matches = [
            follower
            for follower in self.list_subscriptions(owner)
            if copy_trade_subscription_ref(follower) == ref
        ]
        if len(matches) != 1:
            raise CopyTradeError("subscription ref is missing, stale, or ambiguous")
        return matches[0]

    def list_followers(self, master_id: str, *, active_only: bool = True) -> list[Follower]:
        conn = self._conn()
        try:
            sql = "SELECT * FROM ct_followers WHERE master_id = ?"
            params: list[Any] = [master_id]
            if active_only:
                sql += " AND status = 'active'"
            rows = conn.execute(sql, params).fetchall()
            return [_row_to_follower(r) for r in rows]
        finally:
            conn.close()

    def list_subscriptions(self, user_id: str) -> list[Follower]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM ct_followers WHERE user_id = ? ORDER BY started_at_utc DESC",
                (user_id,),
            ).fetchall()
            return [_row_to_follower(r) for r in rows]
        finally:
            conn.close()

    def list_draining_mainnet_followers(self) -> list[Follower]:
        """Return durable unsubscribe operations that still need finalization."""

        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM ct_followers "
                "WHERE binance_network='mainnet' AND status='draining' "
                "ORDER BY user_id, account_binding_ref, follower_id"
            ).fetchall()
            return [_row_to_follower(row) for row in rows]
        finally:
            conn.close()

    def mainnet_account_status(self, account_binding_ref: str) -> str | None:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT status FROM ct_followers WHERE binance_network='mainnet' "
                "AND account_binding_ref=? AND status IN ('activating','active','paused','draining')",
                (account_binding_ref,),
            ).fetchall()
            if len(rows) != 1:
                return None
            return str(rows[0]["status"])
        finally:
            conn.close()

    def mainnet_capability_account_status(
        self,
        owner_user_id: str,
        account_binding_ref: str,
        binance_keystore_name: str,
        credential_binding_ref: str = "",
        *,
        require_audited_activation: bool,
    ) -> str | None:
        """Resolve one account status and, for executable states, its exact activation audit."""

        conn = self._conn()
        try:
            rows = conn.execute(
                """
                SELECT f.status AS follower_status,
                       f.activation_ref AS follower_activation_ref,
                       f.follower_id AS follower_id,
                       f.master_id AS master_id,
                       f.account_binding_ref AS account_binding_ref,
                       f.credential_binding_ref AS follower_credential_binding_ref,
                       f.runtime_promotion_ref AS runtime_promotion_ref,
                       f.user_risk_choice_ref AS user_risk_choice_ref,
                       f.user_risk_consent_event_ref AS follower_consent_event_ref,
                       op.status AS activation_status,
                       op.credential_binding_ref AS activation_credential_binding_ref,
                       op.user_risk_consent_event_ref AS activation_consent_event_ref,
                       op.runtime_request_ref AS runtime_request_ref,
                       op.risk_profile_ref AS risk_profile_ref,
                       op.activation_audit_ref AS activation_audit_ref
                FROM ct_followers AS f
                LEFT JOIN ct_mainnet_activation_operations AS op
                  ON op.activation_ref = f.activation_ref
                 AND op.follower_id = f.follower_id
                 AND op.user_id = f.user_id
                 AND op.master_id = f.master_id
                 AND op.account_binding_ref = f.account_binding_ref
                 AND op.credential_binding_ref = f.credential_binding_ref
                 AND op.runtime_promotion_ref = f.runtime_promotion_ref
                 AND op.user_risk_choice_ref = f.user_risk_choice_ref
                 AND op.user_risk_consent_event_ref = f.user_risk_consent_event_ref
                WHERE f.user_id=? AND f.binance_network='mainnet'
                  AND f.account_binding_ref=? AND f.binance_keystore_name=?
                  AND f.status IN ('activating','active','paused','draining')
                """,
                (
                    str(owner_user_id or ""),
                    str(account_binding_ref or ""),
                    str(binance_keystore_name or ""),
                ),
            ).fetchall()
            if len(rows) != 1:
                return None
            row = rows[0]
            status = str(row["follower_status"] or "")
            if require_audited_activation and status in {"active", "paused"}:
                if not str(row["follower_activation_ref"] or ""):
                    return None
                if str(row["activation_status"] or "") != "audited":
                    return None
                exact_audit_ref = str(row["activation_audit_ref"] or "")
                if not exact_audit_ref:
                    return None
                try:
                    audit_row = conn.execute(
                        "SELECT * FROM mainnet_audit_log WHERE audit_ref=?",
                        (exact_audit_ref,),
                    ).fetchone()
                    audit = (
                        mainnet_audit_record_from_row(audit_row)
                        if audit_row is not None
                        else None
                    )
                except (MainnetGuardError, sqlite3.OperationalError):
                    return None
                if (
                    audit is None
                    or audit.user_id != str(owner_user_id or "")
                    or audit.operation != "copy_trade_subscription"
                    or audit.operation_ref != str(row["follower_activation_ref"] or "")
                    or audit.result != "ok"
                ):
                    return None
                if not hmac.compare_digest(
                    str(row["follower_credential_binding_ref"] or ""),
                    str(credential_binding_ref or ""),
                ):
                    return None
                try:
                    self.risk_consents.validate_event_for_activation(
                        conn,
                        consent_event_ref=str(row["follower_consent_event_ref"] or ""),
                        owner_user_id=str(owner_user_id or ""),
                        follower_id=str(row["follower_id"] or ""),
                        master_id=str(row["master_id"] or ""),
                        account_binding_ref=str(row["account_binding_ref"] or ""),
                        credential_binding_ref=str(
                            row["activation_credential_binding_ref"] or ""
                        ),
                        runtime_request_ref=str(row["runtime_request_ref"] or ""),
                        user_risk_choice_ref=str(row["user_risk_choice_ref"] or ""),
                        risk_profile_ref=str(row["risk_profile_ref"] or ""),
                        require_unexpired=False,
                    )
                except RiskConsentError:
                    return None
            return status
        finally:
            conn.close()

    def has_mainnet_binding_history(self) -> bool:
        conn = self._conn()
        try:
            return conn.execute(
                "SELECT 1 FROM ct_followers WHERE binance_network='mainnet' "
                "AND account_binding_ref!='' LIMIT 1"
            ).fetchone() is not None
        finally:
            conn.close()

    # =========== Signal ===========

    def publish_signal(
        self,
        master_id: str,
        user_id: str,
        *,
        symbol: str,
        side: Literal["buy", "sell"],
        quantity: float,
        price: float | None = None,
        order_type: Literal["market", "limit"] = "market",
        stop_loss: float | None = None,
        take_profit: float | None = None,
        leverage: float | None = None,
        strategy_book_qro_id: str = "",
        signal_validation_ref: str = "",
        market_data_use_validation_ref: str = "",
        instrument_ref: str = "",
        note: str = "",
    ) -> Signal:
        master = self.get_master(master_id)
        if master is None:
            raise CopyTradeError("master 不存在")
        if master.user_id != user_id:
            raise PermissionError("只能用自己的 master 发单")
        if side not in {"buy", "sell"}:
            raise CopyTradeError("side 必须 buy/sell")
        if order_type not in {"market", "limit"}:
            raise CopyTradeError("copy-trade 仅允许 market/limit；条件单需等待 algo 对账链")
        if not math.isfinite(float(quantity)) or quantity <= 0:
            raise CopyTradeError("quantity 必须 > 0")
        if order_type == "limit" and price is None:
            raise CopyTradeError("limit 单必须传 price")
        for field_name, value in (
            ("price", price),
            ("stop_loss", stop_loss),
            ("take_profit", take_profit),
        ):
            if value is not None and (not math.isfinite(float(value)) or float(value) <= 0):
                raise CopyTradeError(f"{field_name} 必须为有限正数")
        if not symbol or len(symbol) > 32:
            raise CopyTradeError("非法 symbol")
        if leverage is not None and (not math.isfinite(float(leverage)) or leverage <= 0):
            raise CopyTradeError("leverage 必须 > 0")
        now = _now()
        envelope = {
            "master_id": master_id,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "order_type": order_type,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "leverage": leverage,
            "strategy_book_qro_id": strategy_book_qro_id,
            "signal_validation_ref": signal_validation_ref,
            "market_data_use_validation_ref": market_data_use_validation_ref,
            "instrument_ref": instrument_ref,
            "status": "live",
            "published_at_utc": now,
        }
        sid = copy_trade_signal_id(envelope)
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO ct_signals (
                    signal_id, master_id, symbol, side, quantity, price, order_type,
                    stop_loss, take_profit, leverage, strategy_book_qro_id,
                    signal_validation_ref, market_data_use_validation_ref, instrument_ref,
                    note, status, published_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'live', ?)
                """,
                (sid, master_id, symbol, side, quantity, price, order_type,
                 stop_loss, take_profit, leverage, strategy_book_qro_id,
                 signal_validation_ref, market_data_use_validation_ref, instrument_ref, note, now),
            )
            conn.execute(
                "UPDATE ct_masters SET total_signals = total_signals + 1 WHERE master_id = ?",
                (master_id,),
            )
            return Signal(
                signal_id=sid, master_id=master_id, symbol=symbol, side=side,
                quantity=quantity, price=price, order_type=order_type,
                stop_loss=stop_loss, take_profit=take_profit, leverage=leverage, note=note,
                strategy_book_qro_id=strategy_book_qro_id,
                signal_validation_ref=signal_validation_ref,
                market_data_use_validation_ref=market_data_use_validation_ref,
                instrument_ref=instrument_ref,
                status="live", published_at_utc=now,
            )
        finally:
            conn.close()

    def cancel_signal(self, signal_id: str, user_id: str) -> bool:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT s.master_id, m.user_id FROM ct_signals s JOIN ct_masters m ON s.master_id = m.master_id WHERE s.signal_id = ?",
                (signal_id,),
            ).fetchone()
            if row is None:
                return False
            if row["user_id"] != user_id:
                raise PermissionError("不是该 signal 的 master")
            cur = conn.execute(
                "UPDATE ct_signals SET status = 'canceled' WHERE signal_id = ? AND status = 'live'",
                (signal_id,),
            )
            return cur.rowcount > 0
        finally:
            conn.close()

    def get_signal(self, signal_id: str) -> Signal | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT * FROM ct_signals WHERE signal_id = ?", (signal_id,)).fetchone()
            return _row_to_signal(row) if row else None
        finally:
            conn.close()

    def list_signals(
        self,
        *,
        master_id: str | None = None,
        status: SignalStatus | None = None,
        limit: int = 100,
    ) -> list[Signal]:
        sql = "SELECT * FROM ct_signals WHERE 1=1"
        params: list[Any] = []
        if master_id:
            sql += " AND master_id = ?"; params.append(master_id)
        if status:
            sql += " AND status = ?"; params.append(status)
        sql += " ORDER BY published_at_utc DESC LIMIT ?"
        params.append(limit)
        conn = self._conn()
        try:
            return [_row_to_signal(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    # =========== Execution 记账 ===========

    def record_execution(
        self,
        signal_id: str,
        follower_id: str,
        status: ExecutionStatus,
        *,
        venue_order_id: str | None = None,
        filled_qty: float = 0.0,
        fill_price: float | None = None,
        commission: float = 0.0,
        error: str | None = None,
    ) -> Execution:
        eid = _gen("exec")
        now = _now()
        finished = now if status in {"filled", "rejected", "failed", "skipped"} else None
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO ct_executions (
                    exec_id, signal_id, follower_id, status, venue_order_id,
                    filled_qty, fill_price, commission, error,
                    created_at_utc, finished_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (eid, signal_id, follower_id, status, venue_order_id,
                 filled_qty, fill_price, commission, error, now, finished),
            )
            return Execution(
                exec_id=eid, signal_id=signal_id, follower_id=follower_id, status=status,
                venue_order_id=venue_order_id, filled_qty=filled_qty, fill_price=fill_price,
                commission=commission, error=error, created_at_utc=now, finished_at_utc=finished,
            )
        finally:
            conn.close()

    def list_executions(
        self,
        *,
        signal_id: str | None = None,
        follower_id: str | None = None,
        limit: int = 200,
    ) -> list[Execution]:
        sql = "SELECT * FROM ct_executions WHERE 1=1"
        params: list[Any] = []
        if signal_id:
            sql += " AND signal_id = ?"; params.append(signal_id)
        if follower_id:
            sql += " AND follower_id = ?"; params.append(follower_id)
        sql += " ORDER BY created_at_utc DESC LIMIT ?"
        params.append(limit)
        conn = self._conn()
        try:
            return [_row_to_execution(r) for r in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def list_executions_for_user(
        self,
        user_id: str,
        *,
        signal_id: str | None = None,
        follower_id: str | None = None,
        limit: int = 200,
    ) -> list[Execution]:
        """Read legacy dispatch rows through the authoritative follower owner join."""

        owner = str(user_id or "").strip()
        if not owner:
            raise ValueError("execution owner user_id is required")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("execution limit must be an exact integer in [1, 200]")
        sql = (
            "SELECT e.* FROM ct_executions AS e "
            "JOIN ct_followers AS f ON f.follower_id=e.follower_id "
            "WHERE f.user_id=?"
        )
        params: list[Any] = [owner]
        if signal_id:
            sql += " AND e.signal_id=?"
            params.append(str(signal_id))
        if follower_id:
            sql += " AND e.follower_id=?"
            params.append(str(follower_id))
        sql += " ORDER BY e.created_at_utc DESC LIMIT ?"
        params.append(limit)
        conn = self._conn()
        try:
            return [_row_to_execution(row) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()


# ---- row → dataclass ----

def _row_to_master(row: sqlite3.Row | None) -> Master | None:  # type: ignore[return-value]
    if row is None:
        return None  # type: ignore[return-value]
    risk = {}
    try:
        risk = json.loads(row["risk_params"]) if row["risk_params"] else {}
    except Exception:  # noqa: BLE001
        risk = {}
    return Master(
        master_id=row["master_id"], user_id=row["user_id"],
        display_name=row["display_name"], description=row["description"] or "",
        asset_class=row["asset_class"] or "crypto_perp",
        profit_share_pct=row["profit_share_pct"] or 0.0,
        is_invite_only=bool(row["is_invite_only"]),
        invite_code=row["invite_code"] or "",
        follower_count=row["follower_count"] or 0,
        total_signals=row["total_signals"] or 0,
        metric_total_return=row["metric_total_return"],
        metric_sharpe=row["metric_sharpe"],
        metric_max_drawdown=row["metric_max_drawdown"],
        risk_params=risk,
        created_at_utc=row["created_at_utc"],
    )


def _row_to_follower(row: sqlite3.Row | None) -> Follower | None:  # type: ignore[return-value]
    if row is None:
        return None  # type: ignore[return-value]
    return Follower(
        follower_id=row["follower_id"], user_id=row["user_id"], master_id=row["master_id"],
        invest_amount=row["invest_amount"] or 0,
        per_order_max_usdt=row["per_order_max_usdt"] or 100,
        daily_loss_limit_pct=row["daily_loss_limit_pct"] or 0.05,
        max_positions=row["max_positions"] or 5,
        max_leverage=row["max_leverage"],
        binance_keystore_name=row["binance_keystore_name"] or "",
        binance_network=row["binance_network"] or "testnet",
        account_binding_ref=row["account_binding_ref"] or "",
        credential_binding_ref=row["credential_binding_ref"] or "",
        runtime_promotion_ref=row["runtime_promotion_ref"] or "",
        user_risk_choice_ref=row["user_risk_choice_ref"] or "",
        user_risk_consent_event_ref=row["user_risk_consent_event_ref"] or "",
        activation_ref=row["activation_ref"] or "",
        status=row["status"],  # type: ignore[arg-type]
        started_at_utc=row["started_at_utc"],
        pnl_realized=row["pnl_realized"] or 0,
    )


def _row_to_signal(row: sqlite3.Row | None) -> Signal | None:  # type: ignore[return-value]
    if row is None:
        return None  # type: ignore[return-value]
    return Signal(
        signal_id=row["signal_id"], master_id=row["master_id"],
        symbol=row["symbol"], side=row["side"],  # type: ignore[arg-type]
        quantity=row["quantity"], price=row["price"],
        order_type=row["order_type"] or "market",  # type: ignore[arg-type]
        stop_loss=row["stop_loss"], take_profit=row["take_profit"],
        leverage=row["leverage"],
        strategy_book_qro_id=row["strategy_book_qro_id"] or "",
        signal_validation_ref=row["signal_validation_ref"] or "",
        market_data_use_validation_ref=row["market_data_use_validation_ref"] or "",
        instrument_ref=row["instrument_ref"] or "",
        note=row["note"] or "", status=row["status"],  # type: ignore[arg-type]
        published_at_utc=row["published_at_utc"],
    )


def _row_to_execution(row: sqlite3.Row) -> Execution:
    return Execution(
        exec_id=row["exec_id"], signal_id=row["signal_id"], follower_id=row["follower_id"],
        status=row["status"],  # type: ignore[arg-type]
        venue_order_id=row["venue_order_id"],
        filled_qty=row["filled_qty"] or 0,
        fill_price=row["fill_price"],
        commission=row["commission"] or 0,
        error=row["error"],
        created_at_utc=row["created_at_utc"],
        finished_at_utc=row["finished_at_utc"],
    )
