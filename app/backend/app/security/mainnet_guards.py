"""v1.0 · 网站存 mainnet key 的 7 项防御层（user 决策"网站+桌面都支持 mainnet"必需）。

威胁模型: 服务器被攻破时 user 资金不应被洗劫。即便攻击者拿到加密 keystore 文件，
也需要拿到:
  (1) 主密钥 (走环境变量 QUANTBT_MASTER_KEY，不入 db/file)
  (2) 用户当前 trusted IP
  (3) 用户 2FA TOTP secret
  (4) 用户 mainnet 密码（即便登录密码泄漏也需重新输）
四样齐全才能下 mainnet 单。

7 项防御：
  1. Per-user Fernet 加密 key (主密钥派生，每用户独立)
  2. trusted_ips 白名单 (mainnet endpoint 强制校验来源 IP)
  3. 2FA TOTP (mainnet operation 前必输 6 位)
  4. Per-order 二次密码确认 (mainnet 下单前再输登录密码)
  5. Emergency close all 一键 (cancel_all_open + close_position 全 symbol)
  6. Audit log append-only (任何 mainnet operation 落日志，不可删)
  7. Rate limit + 单日额度 (per-user mainnet operations 每日上限)
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..lineage.ids import canonical_json


class MainnetGuardError(Exception):
    """mainnet 防御层错误（IP / TOTP / rate limit / 密码再校验）。"""


# 主密钥从环境变量读，不入代码/db
_MASTER_KEY_ENV = "QUANTBT_MASTER_KEY"


def _get_master_key_bytes() -> bytes:
    raw = os.environ.get(_MASTER_KEY_ENV, "")
    runtime_mode = str(os.environ.get("QUANTBT_RUNTIME_MODE") or "").strip().lower()
    if not raw:
        if runtime_mode not in {"test", "development"}:
            raise MainnetGuardError("QUANTBT_MASTER_KEY is required outside test/development")
        raw = "QUANTBT_DEV_MASTER_KEY_DO_NOT_USE_IN_PROD_xxxxxxxxxxxxxx"
    encoded = raw.encode("utf-8")
    if runtime_mode not in {"test", "development"} and len(encoded) < 32:
        raise MainnetGuardError("QUANTBT_MASTER_KEY must contain at least 32 bytes")
    return encoded


def derive_user_key(user_id: str) -> bytes:
    """HKDF 派生 per-user 32 字节加密 key。"""
    return hashlib.pbkdf2_hmac("sha256", _get_master_key_bytes(), user_id.encode("utf-8"), 100_000, dklen=32)


def _fernet_encrypt(plaintext: str, key: bytes) -> str:
    """Encrypt a TOTP secret with versioned cryptography.Fernet."""

    from cryptography.fernet import Fernet

    fernet_key = base64.urlsafe_b64encode(key)
    token = Fernet(fernet_key).encrypt(plaintext.encode("utf-8")).decode("ascii")
    return "v2:" + token


def _legacy_decrypt(ciphertext: str, key: bytes) -> str:
    """Read-only compatibility for pre-v2 XOR+HMAC TOTP records."""

    try:
        blob = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    except Exception as exc:  # noqa: BLE001
        raise MainnetGuardError("legacy TOTP ciphertext is malformed") from exc
    if len(blob) < 32:
        raise MainnetGuardError("legacy TOTP ciphertext is too short")
    stored_nonce, rest = blob[:16], blob[16:]
    ct, tag = rest[:-16], rest[-16:]
    expected_tag = hmac.new(key, stored_nonce + ct, hashlib.sha256).digest()[:16]
    if not hmac.compare_digest(tag, expected_tag):
        raise MainnetGuardError("legacy TOTP ciphertext authentication failed")
    keystream = hashlib.pbkdf2_hmac("sha256", key, stored_nonce, 10_000, dklen=len(ct))
    pt = bytes(c ^ k for c, k in zip(ct, keystream))
    try:
        return pt.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MainnetGuardError("legacy TOTP ciphertext plaintext is invalid") from exc


def _fernet_decrypt(ciphertext: str, key: bytes) -> str:
    if not str(ciphertext or "").startswith("v2:"):
        return _legacy_decrypt(ciphertext, key)
    from cryptography.fernet import Fernet, InvalidToken

    try:
        return Fernet(base64.urlsafe_b64encode(key)).decrypt(
            ciphertext[3:].encode("ascii")
        ).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise MainnetGuardError("TOTP ciphertext authentication failed") from exc


# TOTP (RFC 6238)
def totp_generate_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _b32_pad(secret_b32: str) -> str:
    """补 b32 padding（length 须是 8 的倍数；20 bytes secret 已是 32 chars 无需补）。"""
    rem = len(secret_b32) % 8
    return secret_b32 + ("=" * (8 - rem) if rem else "")


def totp_verify(secret_b32: str, code: str, *, window: int = 1) -> bool:
    """6 位 TOTP 校验，30s window，允许 ±1 timestep 漂移。"""
    if not code or not code.isdigit() or len(code) != 6:
        return False
    try:
        secret = base64.b32decode(_b32_pad(secret_b32))
    except Exception:
        return False
    now = int(time.time()) // 30
    for offset in range(-window, window + 1):
        ts = now + offset
        ts_bytes = ts.to_bytes(8, "big")
        h = hmac.new(secret, ts_bytes, hashlib.sha1).digest()
        o = h[-1] & 0x0F
        token = (int.from_bytes(h[o:o + 4], "big") & 0x7FFFFFFF) % 1_000_000
        if f"{token:06d}" == code:
            return True
    return False


def totp_otpauth_uri(secret_b32: str, *, account: str, issuer: str = "QuantBT") -> str:
    """生成 otpauth:// URI 供 QR code（user 用 Google Authenticator 扫）。"""
    from urllib.parse import quote
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}&issuer={quote(issuer)}&digits=6&period=30"


# ============================================================
# Service
# ============================================================


@dataclass
class MainnetGuardConfig:
    user_id: str
    trusted_ips: list[str] = field(default_factory=list)
    totp_enabled: bool = False
    totp_secret_encrypted: str | None = None
    daily_operation_limit: int = 50          # 单日 mainnet operations 上限
    daily_notional_limit_usdt: float = 10000  # 单日累计名义价值上限
    require_password_per_order: bool = True
    updated_at_utc: str = ""


@dataclass(frozen=True)
class MainnetOperationReservation:
    reservation_ref: str
    user_id: str
    operation: str
    notional_usdt: float
    created_at_utc: str


@dataclass(frozen=True)
class MainnetAuditRecord:
    audit_ref: str
    operation_ref: str
    user_id: str
    operation: str
    venue: str | None
    symbol: str | None
    side: str | None
    notional_usdt: float | None
    source_ip: str | None
    totp_verified: bool
    password_verified: bool
    result: str
    error: str | None
    occurred_at_utc: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS mainnet_guards (
        user_id TEXT PRIMARY KEY,
        trusted_ips TEXT NOT NULL DEFAULT '[]',
        totp_enabled INTEGER NOT NULL DEFAULT 0,
        totp_secret_encrypted TEXT,
        daily_operation_limit INTEGER NOT NULL DEFAULT 50,
        daily_notional_limit_usdt REAL NOT NULL DEFAULT 10000,
        require_password_per_order INTEGER NOT NULL DEFAULT 1,
        updated_at_utc TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mainnet_audit_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        venue TEXT,
        symbol TEXT,
        side TEXT,
        notional_usdt REAL,
        source_ip TEXT,
        totp_verified INTEGER NOT NULL DEFAULT 0,
        password_verified INTEGER NOT NULL DEFAULT 0,
        result TEXT NOT NULL,
        error TEXT,
        audit_ref TEXT NOT NULL DEFAULT '',
        operation_ref TEXT NOT NULL DEFAULT '',
        integrity_key_version TEXT NOT NULL DEFAULT '',
        integrity_seal TEXT NOT NULL DEFAULT '',
        occurred_at_utc TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_user_time ON mainnet_audit_log(user_id, occurred_at_utc DESC)",
    """
    CREATE TABLE IF NOT EXISTS mainnet_operation_reservations (
        reservation_ref TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        notional_usdt REAL NOT NULL CHECK(notional_usdt >= 0),
        status TEXT NOT NULL CHECK(status IN ('reserved','settled','released')),
        created_at_utc TEXT NOT NULL,
        finished_at_utc TEXT,
        result TEXT,
        error TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_mainnet_reservation_user_status ON mainnet_operation_reservations(user_id, status, created_at_utc)",
]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


_AUDIT_KEY_VERSION = "mainnet-audit-hmac-v1"


def _audit_identity(
    *,
    operation_ref: str,
    user_id: str,
    operation: str,
    venue: str | None,
    symbol: str | None,
    side: str | None,
    notional_usdt: float | None,
    source_ip: str | None,
    totp_verified: bool,
    password_verified: bool,
    result: str,
    error: str | None,
    occurred_at_utc: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "record_type": "mainnet_audit_record",
        "operation_ref": operation_ref,
        "user_id": user_id,
        "operation": operation,
        "venue": venue,
        "symbol": symbol,
        "side": side,
        "notional_usdt": notional_usdt,
        "source_ip": source_ip,
        "totp_verified": bool(totp_verified),
        "password_verified": bool(password_verified),
        "result": result,
        "error": error,
        "occurred_at_utc": occurred_at_utc,
    }


def _audit_ref(identity: dict[str, Any]) -> str:
    return "mainnet_audit_v1_" + hashlib.sha256(
        canonical_json(identity).encode("utf-8")
    ).hexdigest()


def _audit_seal(user_id: str, audit_ref: str, identity: dict[str, Any]) -> str:
    key = hmac.new(
        derive_user_key(user_id),
        b"QuantBT/mainnet-audit/v1",
        hashlib.sha256,
    ).digest()
    return hmac.new(
        key,
        canonical_json(
            {
                "audit_ref": audit_ref,
                "identity": identity,
                "integrity_key_version": _AUDIT_KEY_VERSION,
            }
        ).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def mainnet_audit_record_from_row(row: sqlite3.Row | dict[str, Any]) -> MainnetAuditRecord:
    values = dict(row)
    identity = _audit_identity(
        operation_ref=str(values.get("operation_ref") or ""),
        user_id=str(values.get("user_id") or ""),
        operation=str(values.get("operation") or ""),
        venue=values.get("venue"),
        symbol=values.get("symbol"),
        side=values.get("side"),
        notional_usdt=(
            float(values["notional_usdt"])
            if values.get("notional_usdt") is not None
            else None
        ),
        source_ip=values.get("source_ip"),
        totp_verified=bool(values.get("totp_verified")),
        password_verified=bool(values.get("password_verified")),
        result=str(values.get("result") or ""),
        error=values.get("error"),
        occurred_at_utc=str(values.get("occurred_at_utc") or ""),
    )
    if not identity["user_id"] or not identity["operation"] or not identity["result"]:
        raise MainnetGuardError("mainnet audit record is structurally incomplete")
    try:
        parsed_at = datetime.fromisoformat(identity["occurred_at_utc"])
    except ValueError as exc:
        raise MainnetGuardError("mainnet audit record timestamp is malformed") from exc
    if parsed_at.tzinfo is None:
        raise MainnetGuardError("mainnet audit record timestamp must be timezone-aware")
    expected_ref = _audit_ref(identity)
    if not hmac.compare_digest(str(values.get("audit_ref") or ""), expected_ref):
        raise MainnetGuardError("mainnet audit record content identity mismatch")
    if str(values.get("integrity_key_version") or "") != _AUDIT_KEY_VERSION:
        raise MainnetGuardError("mainnet audit record integrity key version is unsupported")
    expected_seal = _audit_seal(identity["user_id"], expected_ref, identity)
    if not hmac.compare_digest(str(values.get("integrity_seal") or ""), expected_seal):
        raise MainnetGuardError("mainnet audit record integrity seal mismatch")
    return MainnetAuditRecord(
        audit_ref=expected_ref,
        operation_ref=identity["operation_ref"],
        user_id=identity["user_id"],
        operation=identity["operation"],
        venue=identity["venue"],
        symbol=identity["symbol"],
        side=identity["side"],
        notional_usdt=identity["notional_usdt"],
        source_ip=identity["source_ip"],
        totp_verified=identity["totp_verified"],
        password_verified=identity["password_verified"],
        result=identity["result"],
        error=identity["error"],
        occurred_at_utc=identity["occurred_at_utc"],
    )


def init_mainnet_guards_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as c:
        for stmt in _SCHEMA:
            c.execute(stmt)
        columns = {row[1] for row in c.execute("PRAGMA table_info(mainnet_audit_log)")}
        for column, declaration in (
            ("audit_ref", "TEXT NOT NULL DEFAULT ''"),
            ("operation_ref", "TEXT NOT NULL DEFAULT ''"),
            ("integrity_key_version", "TEXT NOT NULL DEFAULT ''"),
            ("integrity_seal", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in columns:
                c.execute(f"ALTER TABLE mainnet_audit_log ADD COLUMN {column} {declaration}")
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_mainnet_audit_ref "
            "ON mainnet_audit_log(audit_ref) WHERE audit_ref!=''"
        )
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_mainnet_audit_operation_result "
            "ON mainnet_audit_log(user_id,operation,operation_ref,result) "
            "WHERE operation_ref!=''"
        )
        c.commit()


class MainnetGuardsService:
    def __init__(self, db_path: Path) -> None:
        self._db = db_path
        init_mainnet_guards_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self._db)
        c.row_factory = sqlite3.Row
        return c

    # ----- config CRUD -----

    def get_config(self, user_id: str) -> MainnetGuardConfig:
        with self._conn() as c:
            row = c.execute("SELECT * FROM mainnet_guards WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return MainnetGuardConfig(user_id=user_id)
        return MainnetGuardConfig(
            user_id=row["user_id"],
            trusted_ips=json.loads(row["trusted_ips"] or "[]"),
            totp_enabled=bool(row["totp_enabled"]),
            totp_secret_encrypted=row["totp_secret_encrypted"],
            daily_operation_limit=row["daily_operation_limit"],
            daily_notional_limit_usdt=row["daily_notional_limit_usdt"],
            require_password_per_order=bool(row["require_password_per_order"]),
            updated_at_utc=row["updated_at_utc"],
        )

    def upsert_config(self, cfg: MainnetGuardConfig) -> None:
        now = _utc_now()
        cfg.updated_at_utc = now
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO mainnet_guards "
                "(user_id, trusted_ips, totp_enabled, totp_secret_encrypted, "
                "daily_operation_limit, daily_notional_limit_usdt, "
                "require_password_per_order, updated_at_utc) VALUES (?,?,?,?,?,?,?,?)",
                (
                    cfg.user_id,
                    json.dumps(cfg.trusted_ips, ensure_ascii=False),
                    int(cfg.totp_enabled),
                    cfg.totp_secret_encrypted,
                    cfg.daily_operation_limit,
                    cfg.daily_notional_limit_usdt,
                    int(cfg.require_password_per_order),
                    now,
                ),
            )
            c.commit()

    # ----- 2FA -----

    def enable_totp(self, user_id: str) -> tuple[str, str]:
        """生成 TOTP secret 并加密入 db；返回 (raw_secret, otpauth_uri)。"""
        secret_b32 = totp_generate_secret()
        key = derive_user_key(user_id)
        encrypted = _fernet_encrypt(secret_b32, key)
        cfg = self.get_config(user_id)
        cfg.totp_enabled = True
        cfg.totp_secret_encrypted = encrypted
        self.upsert_config(cfg)
        return secret_b32, totp_otpauth_uri(secret_b32, account=user_id)

    def verify_totp(self, user_id: str, code: str) -> bool:
        cfg = self.get_config(user_id)
        if not cfg.totp_enabled or not cfg.totp_secret_encrypted:
            return False
        try:
            key = derive_user_key(user_id)
            secret_b32 = _fernet_decrypt(cfg.totp_secret_encrypted, key)
        except MainnetGuardError:
            return False
        return totp_verify(secret_b32, code)

    # ----- IP whitelist -----

    def check_ip(self, user_id: str, source_ip: str) -> bool:
        cfg = self.get_config(user_id)
        if not cfg.trusted_ips:
            return False  # 没设白名单 → mainnet 一律拒绝
        return source_ip in cfg.trusted_ips or any(
            source_ip.startswith(prefix.rstrip("*")) for prefix in cfg.trusted_ips if prefix.endswith("*")
        )

    # ----- 单日额度 -----

    def get_today_usage(self, user_id: str) -> dict[str, Any]:
        today = time.strftime("%Y-%m-%d", time.gmtime())
        with self._conn() as c:
            rows = c.execute(
                "SELECT COUNT(*) as ops, COALESCE(SUM(notional_usdt), 0) as notional "
                "FROM mainnet_audit_log "
                "WHERE user_id=? AND date(occurred_at_utc)=? "
                "AND result IN ('ok','submitted','outcome_unknown')",
                (user_id, today),
            ).fetchone()
            reserved = c.execute(
                "SELECT COUNT(*) as ops, COALESCE(SUM(notional_usdt), 0) as notional "
                "FROM mainnet_operation_reservations "
                "WHERE user_id=? AND date(created_at_utc)=? AND status='reserved'",
                (user_id, today),
            ).fetchone()
        return {
            "date": today,
            "operations_today": (rows["ops"] if rows else 0) + (reserved["ops"] if reserved else 0),
            "notional_today_usdt": float(rows["notional"] if rows else 0.0)
            + float(reserved["notional"] if reserved else 0.0),
        }

    def reserve_operation(
        self,
        user_id: str,
        operation: str,
        *,
        reservation_ref: str,
        notional_usdt: float,
    ) -> str:
        """Atomically reserve daily operation/notional quota before venue access."""

        ref = str(reservation_ref or "").strip()
        requested = float(notional_usdt)
        if not ref or not operation:
            raise MainnetGuardError("reservation_ref and operation are required")
        if not math.isfinite(requested) or requested < 0:
            raise MainnetGuardError("mainnet operation notional must be finite and non-negative")
        cfg = self.get_config(user_id)
        today = time.strftime("%Y-%m-%d", time.gmtime())
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            existing = c.execute(
                "SELECT * FROM mainnet_operation_reservations WHERE reservation_ref=?",
                (ref,),
            ).fetchone()
            if existing is not None:
                same = (
                    existing["user_id"] == user_id
                    and existing["operation"] == operation
                    and float(existing["notional_usdt"]) == requested
                )
                if not same or existing["status"] != "reserved":
                    raise MainnetGuardError("mainnet quota reservation ref was already consumed or conflicts")
                return ref
            audited = c.execute(
                "SELECT COUNT(*) AS ops, COALESCE(SUM(notional_usdt),0) AS notional "
                "FROM mainnet_audit_log WHERE user_id=? AND date(occurred_at_utc)=? "
                "AND result IN ('ok','submitted','outcome_unknown')",
                (user_id, today),
            ).fetchone()
            pending = c.execute(
                "SELECT COUNT(*) AS ops, COALESCE(SUM(notional_usdt),0) AS notional "
                "FROM mainnet_operation_reservations WHERE user_id=? "
                "AND date(created_at_utc)=? AND status='reserved'",
                (user_id, today),
            ).fetchone()
            operations = int(audited["ops"] or 0) + int(pending["ops"] or 0)
            notional = float(audited["notional"] or 0.0) + float(pending["notional"] or 0.0)
            if operations >= cfg.daily_operation_limit:
                raise MainnetGuardError(
                    f"今日已 {operations} 次 mainnet 操作 (上限 {cfg.daily_operation_limit})"
                )
            if notional + requested > cfg.daily_notional_limit_usdt:
                raise MainnetGuardError(
                    f"今日累计名义价值将达 {notional + requested:.2f} 超 limit {cfg.daily_notional_limit_usdt}"
                )
            c.execute(
                """
                INSERT INTO mainnet_operation_reservations(
                    reservation_ref,user_id,operation,notional_usdt,status,created_at_utc
                ) VALUES(?,?,?,?,?,?)
                """,
                (ref, user_id, operation, requested, "reserved", _utc_now()),
            )
            c.commit()
        return ref

    def reserved_operations(
        self,
        *,
        operation: str | None = None,
    ) -> tuple[MainnetOperationReservation, ...]:
        """Return durable unfinished quota reservations for crash recovery."""

        with self._conn() as c:
            if operation is None:
                rows = c.execute(
                    "SELECT * FROM mainnet_operation_reservations "
                    "WHERE status='reserved' ORDER BY created_at_utc, reservation_ref"
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM mainnet_operation_reservations "
                    "WHERE status='reserved' AND operation=? "
                    "ORDER BY created_at_utc, reservation_ref",
                    (str(operation),),
                ).fetchall()
        reservations: list[MainnetOperationReservation] = []
        for row in rows:
            notional = float(row["notional_usdt"])
            if not math.isfinite(notional) or notional < 0:
                raise MainnetGuardError("persisted mainnet quota reservation has invalid notional")
            values = {
                field: str(row[field] or "").strip()
                for field in ("reservation_ref", "user_id", "operation", "created_at_utc")
            }
            if not all(values.values()):
                raise MainnetGuardError("persisted mainnet quota reservation is incomplete")
            reservations.append(
                MainnetOperationReservation(
                    reservation_ref=values["reservation_ref"],
                    user_id=values["user_id"],
                    operation=values["operation"],
                    notional_usdt=notional,
                    created_at_utc=values["created_at_utc"],
                )
            )
        return tuple(reservations)

    def settle_operation(
        self,
        reservation_ref: str,
        *,
        venue: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        result: str = "submitted",
        error: str | None = None,
    ) -> None:
        self._finish_operation(
            reservation_ref,
            status="settled",
            venue=venue,
            symbol=symbol,
            side=side,
            result=result,
            error=error,
        )

    def release_operation(self, reservation_ref: str, *, error: str) -> None:
        self._finish_operation(
            reservation_ref,
            status="released",
            result="rejected",
            error=error,
        )

    def _finish_operation(
        self,
        reservation_ref: str,
        *,
        status: str,
        result: str,
        error: str | None,
        venue: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
    ) -> None:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT * FROM mainnet_operation_reservations WHERE reservation_ref=?",
                (str(reservation_ref),),
            ).fetchone()
            if row is None:
                raise MainnetGuardError("unknown mainnet quota reservation")
            if row["status"] == status:
                return
            if row["status"] != "reserved":
                raise MainnetGuardError("mainnet quota reservation is already terminal")
            self._insert_audit(
                c,
                user_id=str(row["user_id"]),
                operation=str(row["operation"]),
                operation_ref=str(reservation_ref),
                venue=venue,
                symbol=symbol,
                side=side,
                notional_usdt=float(row["notional_usdt"]),
                source_ip=None,
                totp_verified=False,
                password_verified=False,
                result=result,
                error=error,
            )
            c.execute(
                "UPDATE mainnet_operation_reservations "
                "SET status=?,finished_at_utc=?,result=?,error=? WHERE reservation_ref=?",
                (status, _utc_now(), result, error, str(reservation_ref)),
            )
            c.commit()

    def check_within_daily_limit(
        self, user_id: str, requested_notional_usdt: float,
    ) -> tuple[bool, str]:
        cfg = self.get_config(user_id)
        usage = self.get_today_usage(user_id)
        if usage["operations_today"] >= cfg.daily_operation_limit:
            return False, f"今日已 {usage['operations_today']} 次 mainnet 操作 (上限 {cfg.daily_operation_limit})"
        if usage["notional_today_usdt"] + requested_notional_usdt > cfg.daily_notional_limit_usdt:
            return False, (
                f"今日累计名义价值将达 {usage['notional_today_usdt'] + requested_notional_usdt:.2f}"
                f" 超 limit {cfg.daily_notional_limit_usdt}"
            )
        return True, "ok"

    # ----- 综合校验：mainnet operation 前必过 -----

    def assert_mainnet_allowed(
        self,
        user_id: str,
        *,
        source_ip: str,
        totp_code: str | None,
        password_verified: bool,
        operation: str,
        notional_usdt: float = 0.0,
    ) -> None:
        """任何 mainnet 操作前调；不满足任一条件 raise MainnetGuardError。"""
        cfg = self.get_config(user_id)

        # 1. IP 白名单
        if not self.check_ip(user_id, source_ip):
            self.log_operation(user_id, operation, source_ip=source_ip, result="rejected",
                                error="ip_not_whitelisted")
            raise MainnetGuardError(f"IP {source_ip} 不在 trusted_ips 白名单")

        # 2. TOTP
        if cfg.totp_enabled:
            if not totp_code or not self.verify_totp(user_id, totp_code):
                self.log_operation(user_id, operation, source_ip=source_ip, result="rejected",
                                    error="totp_failed")
                raise MainnetGuardError("2FA TOTP 校验失败")

        # 3. Per-order 密码二次确认
        if cfg.require_password_per_order and not password_verified:
            self.log_operation(user_id, operation, source_ip=source_ip, result="rejected",
                                error="password_not_verified")
            raise MainnetGuardError("mainnet 下单前必须重新输入登录密码")

        # 4. 单日额度
        ok, reason = self.check_within_daily_limit(user_id, notional_usdt)
        if not ok:
            self.log_operation(user_id, operation, source_ip=source_ip, result="rejected", error=reason)
            raise MainnetGuardError(reason)

    # ----- audit log -----

    def _insert_audit(
        self,
        conn: sqlite3.Connection,
        *,
        user_id: str,
        operation: str,
        operation_ref: str,
        venue: str | None,
        symbol: str | None,
        side: str | None,
        notional_usdt: float | None,
        source_ip: str | None,
        totp_verified: bool,
        password_verified: bool,
        result: str,
        error: str | None,
    ) -> str:
        owner = str(user_id or "").strip()
        action = str(operation or "").strip()
        outcome = str(result or "").strip()
        exact_operation_ref = str(operation_ref or "").strip()
        if not owner or not action or not outcome:
            raise MainnetGuardError("mainnet audit requires user, operation, and result")
        if notional_usdt is not None and not math.isfinite(float(notional_usdt)):
            raise MainnetGuardError("mainnet audit notional must be finite")
        if exact_operation_ref:
            existing = conn.execute(
                "SELECT * FROM mainnet_audit_log "
                "WHERE user_id=? AND operation=? AND operation_ref=? AND result=?",
                (owner, action, exact_operation_ref, outcome),
            ).fetchone()
            if existing is not None:
                record = mainnet_audit_record_from_row(existing)
                expected = {
                    "venue": venue,
                    "symbol": symbol,
                    "side": side,
                    "notional_usdt": (
                        float(notional_usdt) if notional_usdt is not None else None
                    ),
                    "source_ip": source_ip,
                    "totp_verified": bool(totp_verified),
                    "password_verified": bool(password_verified),
                    "error": error,
                }
                if any(getattr(record, key) != value for key, value in expected.items()):
                    raise MainnetGuardError("mainnet audit operation identity collision")
                return record.audit_ref
        occurred_at = _utc_now()
        identity = _audit_identity(
            operation_ref=exact_operation_ref,
            user_id=owner,
            operation=action,
            venue=venue,
            symbol=symbol,
            side=side,
            notional_usdt=(float(notional_usdt) if notional_usdt is not None else None),
            source_ip=source_ip,
            totp_verified=bool(totp_verified),
            password_verified=bool(password_verified),
            result=outcome,
            error=error,
            occurred_at_utc=occurred_at,
        )
        audit_ref = _audit_ref(identity)
        seal = _audit_seal(owner, audit_ref, identity)
        conn.execute(
            "INSERT INTO mainnet_audit_log "
            "(user_id,operation,venue,symbol,side,notional_usdt,source_ip,"
            "totp_verified,password_verified,result,error,audit_ref,operation_ref,"
            "integrity_key_version,integrity_seal,occurred_at_utc) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                owner,
                action,
                venue,
                symbol,
                side,
                identity["notional_usdt"],
                source_ip,
                int(bool(totp_verified)),
                int(bool(password_verified)),
                outcome,
                error,
                audit_ref,
                exact_operation_ref,
                _AUDIT_KEY_VERSION,
                seal,
                occurred_at,
            ),
        )
        return audit_ref

    def log_operation(
        self,
        user_id: str,
        operation: str,
        *,
        venue: str | None = None,
        symbol: str | None = None,
        side: str | None = None,
        notional_usdt: float | None = None,
        source_ip: str | None = None,
        totp_verified: bool = False,
        password_verified: bool = False,
        result: str = "ok",
        error: str | None = None,
        operation_ref: str = "",
    ) -> str:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            audit_ref = self._insert_audit(
                c,
                user_id=user_id,
                operation=operation,
                operation_ref=operation_ref,
                venue=venue,
                symbol=symbol,
                side=side,
                notional_usdt=notional_usdt,
                source_ip=source_ip,
                totp_verified=totp_verified,
                password_verified=password_verified,
                result=result,
                error=error,
            )
            c.commit()
        return audit_ref

    def audit_record(self, audit_ref: str) -> MainnetAuditRecord:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM mainnet_audit_log WHERE audit_ref=?",
                (str(audit_ref or ""),),
            ).fetchone()
        if row is None:
            raise MainnetGuardError("mainnet audit record is unknown")
        return mainnet_audit_record_from_row(row)

    def list_audit_log(self, user_id: str, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM mainnet_audit_log WHERE user_id=? ORDER BY occurred_at_utc DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        projected: list[dict[str, Any]] = []
        for row in rows:
            if not str(row["audit_ref"] or ""):
                legacy = {
                    key: row[key]
                    for key in (
                        "user_id",
                        "operation",
                        "venue",
                        "symbol",
                        "side",
                        "notional_usdt",
                        "source_ip",
                        "totp_verified",
                        "password_verified",
                        "result",
                        "error",
                        "occurred_at_utc",
                    )
                }
                projected.append({**legacy, "integrity_status": "legacy_unverified"})
                continue
            record = mainnet_audit_record_from_row(row)
            projected.append({**record.to_dict(), "integrity_status": "verified"})
        return projected


__all__ = [
    "MainnetGuardConfig",
    "MainnetGuardError",
    "MainnetGuardsService",
    "MainnetAuditRecord",
    "MainnetOperationReservation",
    "derive_user_key",
    "init_mainnet_guards_db",
    "mainnet_audit_record_from_row",
    "totp_generate_secret",
    "totp_otpauth_uri",
    "totp_verify",
]
