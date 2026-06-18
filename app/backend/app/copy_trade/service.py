"""Copy trade service · sqlite + signal relay。

表前缀 `ct_` 避免与 auth/community/sharing 冲突。
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Literal


class CopyTradeError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gen(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(8)}"


SignalStatus = Literal["live", "canceled", "filled", "expired"]
FollowerStatus = Literal["active", "paused", "stopped"]
ExecutionStatus = Literal["queued", "placed", "filled", "rejected", "failed", "skipped"]


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
    status: FollowerStatus = "active"
    started_at_utc: str = ""
    pnl_realized: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
                status TEXT DEFAULT 'active',
                started_at_utc TEXT NOT NULL,
                pnl_realized REAL DEFAULT 0,
                UNIQUE(user_id, master_id)
            );
            CREATE INDEX IF NOT EXISTS idx_ct_followers_master ON ct_followers(master_id);
            CREATE INDEX IF NOT EXISTS idx_ct_followers_user ON ct_followers(user_id);

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
        ):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
            except sqlite3.OperationalError:
                pass  # 列已存在
        conn.commit()
        conn.close()
        _INITIALIZED.add(key)


class CopyTradeService:
    """所有 copy-trade 业务逻辑。Signal relay 由 SignalRelayer (executor.py) 异步触发。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        init_copy_trade_db(db_path)

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
    ) -> Follower:
        if invest_amount <= 0:
            raise CopyTradeError("invest_amount 必须 > 0")
        if max_leverage is not None and max_leverage <= 0:
            raise CopyTradeError("max_leverage 必须 > 0")
        if not binance_keystore_name:
            raise CopyTradeError("必须填 binance_keystore_name (follower 自己的 keystore 引用)")
        master = self.get_master(master_id)
        if master is None:
            raise CopyTradeError("master 不存在")
        if master.user_id == user_id:
            raise CopyTradeError("不能跟单自己")
        if master.is_invite_only and not self.has_redeemed(user_id, master_id):
            raise CopyTradeError("此 master 为私域，请先用 invite_code redeem")
        conn = self._conn()
        try:
            fid = f"{user_id}::{master_id}"
            now = _now()
            try:
                conn.execute(
                    """
                    INSERT INTO ct_followers (
                        follower_id, user_id, master_id, invest_amount, per_order_max_usdt,
                        daily_loss_limit_pct, max_positions, max_leverage, binance_keystore_name, binance_network,
                        status, started_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fid, user_id, master_id, invest_amount, per_order_max_usdt,
                        daily_loss_limit_pct, max_positions, max_leverage, binance_keystore_name, binance_network,
                        "active", now,
                    ),
                )
            except sqlite3.IntegrityError:
                # 已订阅过 → 改成 active 并更新参数
                conn.execute(
                    """
                    UPDATE ct_followers SET
                        invest_amount = ?, per_order_max_usdt = ?, daily_loss_limit_pct = ?,
                        max_positions = ?, max_leverage = ?, binance_keystore_name = ?, binance_network = ?,
                        status = 'active'
                    WHERE user_id = ? AND master_id = ?
                    """,
                    (invest_amount, per_order_max_usdt, daily_loss_limit_pct,
                     max_positions, max_leverage, binance_keystore_name, binance_network, user_id, master_id),
                )
            conn.execute(
                "UPDATE ct_masters SET follower_count = (SELECT COUNT(*) FROM ct_followers WHERE master_id = ? AND status = 'active') WHERE master_id = ?",
                (master_id, master_id),
            )
            return self.get_follower(fid)  # type: ignore[return-value]
        finally:
            conn.close()

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

    def pause_subscription(self, user_id: str, master_id: str, paused: bool = True) -> bool:
        conn = self._conn()
        try:
            target = "paused" if paused else "active"
            cur = conn.execute(
                "UPDATE ct_followers SET status = ? WHERE user_id = ? AND master_id = ? AND status != 'stopped'",
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
        note: str = "",
    ) -> Signal:
        master = self.get_master(master_id)
        if master is None:
            raise CopyTradeError("master 不存在")
        if master.user_id != user_id:
            raise PermissionError("只能用自己的 master 发单")
        if side not in {"buy", "sell"}:
            raise CopyTradeError("side 必须 buy/sell")
        if quantity <= 0:
            raise CopyTradeError("quantity 必须 > 0")
        if order_type == "limit" and price is None:
            raise CopyTradeError("limit 单必须传 price")
        if not symbol or len(symbol) > 32:
            raise CopyTradeError("非法 symbol")
        if leverage is not None and leverage <= 0:
            raise CopyTradeError("leverage 必须 > 0")
        sid = _gen("signal")
        now = _now()
        conn = self._conn()
        try:
            conn.execute(
                """
                INSERT INTO ct_signals (
                    signal_id, master_id, symbol, side, quantity, price, order_type,
                    stop_loss, take_profit, leverage, note, status, published_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'live', ?)
                """,
                (sid, master_id, symbol, side, quantity, price, order_type,
                 stop_loss, take_profit, leverage, note, now),
            )
            conn.execute(
                "UPDATE ct_masters SET total_signals = total_signals + 1 WHERE master_id = ?",
                (master_id,),
            )
            return Signal(
                signal_id=sid, master_id=master_id, symbol=symbol, side=side,
                quantity=quantity, price=price, order_type=order_type,
                stop_loss=stop_loss, take_profit=take_profit, leverage=leverage, note=note,
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
