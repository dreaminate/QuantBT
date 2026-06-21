"""Auth service · sqlite users + sessions + PBKDF2 + bearer token。"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import Header, HTTPException


PBKDF2_ITER = 200_000
SESSION_DAYS = 30


class AuthError(RuntimeError):
    pass


@dataclass
class User:
    user_id: str
    username: str
    display_name: str
    bio: str = ""
    avatar_url: str = ""
    created_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "bio": self.bio,
            "avatar_url": self.avatar_url,
            "created_at_utc": self.created_at_utc,
        }


_INIT_LOCK = threading.Lock()
_INITIALIZED: set[str] = set()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_auth_db(db_path: Path) -> None:
    """建表（idempotent）+ 创建一个 'local' user 兜底 dev mode。"""

    db_path.parent.mkdir(parents=True, exist_ok=True)
    key = str(db_path.resolve())
    with _INIT_LOCK:
        if key in _INITIALIZED:
            return
        conn = _connect(db_path)
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                bio TEXT DEFAULT '',
                avatar_url TEXT DEFAULT '',
                created_at_utc TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at_utc TEXT NOT NULL,
                expires_at_utc TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            """
        )
        # 兜底 local user
        row = conn.execute("SELECT user_id FROM users WHERE username = ?", ("local",)).fetchone()
        if row is None:
            salt = secrets.token_hex(16)
            pwd_hash = _hash_pwd("local", salt)
            conn.execute(
                "INSERT INTO users (user_id, username, password_hash, password_salt, display_name, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("user-local", "local", pwd_hash, salt, "Local Dev", _now()),
            )
        conn.close()
        _INITIALIZED.add(key)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash_pwd(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITER
    ).hex()


class AuthService:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        init_auth_db(db_path)

    def _conn(self) -> sqlite3.Connection:
        return _connect(self._db_path)

    # ---- registration / login ----

    def register(self, username: str, password: str, display_name: str = "") -> User:
        username = (username or "").strip().lower()
        if not username or not username.replace("_", "").replace("-", "").isalnum():
            raise AuthError("username 必须为字母数字下划线短横线（>=3 字符）")
        if len(username) < 3 or len(username) > 32:
            raise AuthError("username 长度需在 3-32 之间")
        if not password or len(password) < 6:
            raise AuthError("密码长度至少 6 位")
        conn = self._conn()
        try:
            row = conn.execute("SELECT user_id FROM users WHERE username = ?", (username,)).fetchone()
            if row:
                raise AuthError(f"用户名已被占用: {username}")
            salt = secrets.token_hex(16)
            pwd_hash = _hash_pwd(password, salt)
            user_id = f"user-{secrets.token_hex(8)}"
            now = _now()
            conn.execute(
                "INSERT INTO users (user_id, username, password_hash, password_salt, display_name, created_at_utc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, username, pwd_hash, salt, display_name or username, now),
            )
            return User(user_id=user_id, username=username, display_name=display_name or username, created_at_utc=now)
        finally:
            conn.close()

    def login(self, username: str, password: str) -> tuple[User, str]:
        username = (username or "").strip().lower()
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT user_id, username, password_hash, password_salt, display_name, bio, avatar_url, created_at_utc "
                "FROM users WHERE username = ?",
                (username,),
            ).fetchone()
            if row is None:
                raise AuthError("用户名或密码错误")
            if _hash_pwd(password, row["password_salt"]) != row["password_hash"]:
                raise AuthError("用户名或密码错误")
            user = User(
                user_id=row["user_id"],
                username=row["username"],
                display_name=row["display_name"],
                bio=row["bio"] or "",
                avatar_url=row["avatar_url"] or "",
                created_at_utc=row["created_at_utc"],
            )
            token = self._create_session(conn, user.user_id)
            return user, token
        finally:
            conn.close()

    def verify_password(self, user_id: str, password: str) -> bool:
        """服务端按 user_id 真校验账户密码（PBKDF2）。

        动钱端点 per-request 二次鉴权用：纯校验，绝不创建会话 / 不返回 token（避免被当登录旁路）。
        与 login() 同一 PBKDF2 口径，但按 user_id 查（调用方已持鉴权后的 user）。
        """
        if not password:
            return False
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT password_hash, password_salt FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return False
            return _hash_pwd(password, row["password_salt"]) == row["password_hash"]
        finally:
            conn.close()

    def _create_session(self, conn: sqlite3.Connection, user_id: str) -> str:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires = now + timedelta(days=SESSION_DAYS)
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at_utc, expires_at_utc) VALUES (?, ?, ?, ?)",
            (token, user_id, now.isoformat(), expires.isoformat()),
        )
        return token

    def logout(self, token: str) -> None:
        conn = self._conn()
        try:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        finally:
            conn.close()

    def user_by_token(self, token: str | None) -> User | None:
        if not token:
            return None
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT s.user_id, s.expires_at_utc, u.username, u.display_name, u.bio, u.avatar_url, u.created_at_utc "
                "FROM sessions s JOIN users u ON s.user_id = u.user_id WHERE s.token = ?",
                (token,),
            ).fetchone()
            if row is None:
                return None
            # 过期
            if datetime.fromisoformat(row["expires_at_utc"]) < datetime.now(UTC):
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
                return None
            return User(
                user_id=row["user_id"],
                username=row["username"],
                display_name=row["display_name"],
                bio=row["bio"] or "",
                avatar_url=row["avatar_url"] or "",
                created_at_utc=row["created_at_utc"],
            )
        finally:
            conn.close()

    # ---- profile ----

    def get_user_by_id(self, user_id: str) -> User | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT user_id, username, display_name, bio, avatar_url, created_at_utc FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            if row is None:
                return None
            return User(**{k: row[k] for k in row.keys()})
        finally:
            conn.close()

    def get_user_by_username(self, username: str) -> User | None:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT user_id, username, display_name, bio, avatar_url, created_at_utc FROM users WHERE username = ?",
                ((username or "").lower(),),
            ).fetchone()
            if row is None:
                return None
            return User(**{k: row[k] for k in row.keys()})
        finally:
            conn.close()

    def list_users(self, limit: int = 50) -> list[User]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT user_id, username, display_name, bio, avatar_url, created_at_utc FROM users LIMIT ?",
                (limit,),
            ).fetchall()
            return [User(**{k: row[k] for k in row.keys()}) for row in rows]
        finally:
            conn.close()

    def update_profile(self, user_id: str, *, display_name: str | None = None, bio: str | None = None, avatar_url: str | None = None) -> User:
        conn = self._conn()
        try:
            sets: list[str] = []
            args: list[Any] = []
            if display_name is not None:
                sets.append("display_name = ?")
                args.append(display_name)
            if bio is not None:
                sets.append("bio = ?")
                args.append(bio)
            if avatar_url is not None:
                sets.append("avatar_url = ?")
                args.append(avatar_url)
            if sets:
                args.append(user_id)
                conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id = ?", args)
            u = self.get_user_by_id(user_id)
            assert u is not None
            return u
        finally:
            conn.close()


# ---- FastAPI dependencies ----

_SERVICE: AuthService | None = None


def set_service(service: AuthService) -> None:
    global _SERVICE
    _SERVICE = service


def _extract_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return authorization.strip()


def current_user_dependency(authorization: str | None = Header(default=None)) -> User | None:
    """请求级当前 user；未登录返回 None（dev 友好）。"""

    if _SERVICE is None:
        return None
    token = _extract_token(authorization)
    return _SERVICE.user_by_token(token)


def require_user_dependency(authorization: str | None = Header(default=None)) -> User:
    """要求登录；未登录 → 401。"""

    user = current_user_dependency(authorization)
    if user is None:
        # 兜底允许 dev mode 'local' user 在 dev mode（如果显式启用）
        if os.environ.get("QUANTBT_DEV_AS_LOCAL", "").lower() in {"1", "true", "yes"} and _SERVICE:
            return _SERVICE.get_user_by_username("local") or _raise_401()
        return _raise_401()
    return user


def _raise_401() -> User:
    raise HTTPException(status_code=401, detail="未登录")
