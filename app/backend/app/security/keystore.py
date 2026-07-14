"""M9.3 · 加密密钥存储。

GOAL 致命错误清单：「Binance API key / secret 明文落 YAML / 数据库 / 日志」
→ 必须用 keyring 加密。

我们提供三档 backend，并要求显式、不可降级地选择：
1. **keyring**：macOS Keychain / Win Credential Manager / Linux libsecret —— 首选
2. **fernet_file**：本地加密文件（cryptography Fernet + 用户主密码 PBKDF2）
3. **memory**：纯内存，仅在显式测试/开发配置下使用；进程结束即丢

无论哪档，API key / secret **从未** 走 YAML / DB / 日志，所有访问点统一 `SecureKeystore.get`。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
import fcntl
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator


class KeystoreError(RuntimeError):
    pass


@dataclass
class KeystoreRecord:
    name: str          # 例如 "binance_mainnet" / "binance_testnet" / "user_dex"
    api_key: str
    api_secret: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KeystoreBackend(ABC):
    backend_name: str

    @abstractmethod
    def store(self, record: KeystoreRecord) -> None: ...

    @abstractmethod
    def fetch(self, name: str) -> KeystoreRecord: ...

    @abstractmethod
    def delete(self, name: str) -> None: ...

    @abstractmethod
    def list_names(self) -> list[str]: ...


class InMemoryKeystore(KeystoreBackend):
    backend_name = "memory"

    def __init__(self) -> None:
        self._records: dict[str, KeystoreRecord] = {}

    def store(self, record: KeystoreRecord) -> None:
        self._records[record.name] = record

    def fetch(self, name: str) -> KeystoreRecord:
        if name not in self._records:
            raise KeystoreError(f"keystore 无记录：{name}")
        return self._records[name]

    def delete(self, name: str) -> None:
        self._records.pop(name, None)

    def list_names(self) -> list[str]:
        return sorted(self._records.keys())


def _require_private_directory(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise KeystoreError(f"keystore directory must not be a symlink: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise KeystoreError(f"keystore directory is not owned by the current user: {path}")
    mode = stat.S_IMODE(info.st_mode)
    if mode != 0o700:
        raise KeystoreError(f"keystore directory must have mode 0700: {path}")


def _require_private_regular_file(path: Path, *, allow_missing: bool = False) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if allow_missing:
            return
        raise KeystoreError(f"keystore file is missing: {path}") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise KeystoreError(f"keystore path must be a regular non-symlink file: {path}")
    if info.st_uid != os.getuid():
        raise KeystoreError(f"keystore file is not owned by the current user: {path}")
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise KeystoreError(f"keystore file must have mode 0600: {path}")


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_private_write(path: Path, payload: bytes) -> None:
    _require_private_directory(path.parent)
    _require_private_regular_file(path, allow_missing=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short keystore write")
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp, path)
        _require_private_regular_file(path)
        _fsync_directory(path.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


@contextmanager
def _locked_file(path: Path, *, exclusive: bool) -> Iterator[None]:
    _require_private_directory(path.parent)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(fd, 0o600)
        _require_private_regular_file(path)
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class KeyringBackend(KeystoreBackend):
    backend_name = "keyring"

    def __init__(
        self,
        service_namespace: str = "quantbt",
        *,
        index_path: Path | None = None,
    ) -> None:
        import keyring  # type: ignore[import-not-found]

        self._keyring = keyring
        self._namespace = service_namespace
        backend = keyring.get_keyring()
        if float(getattr(backend, "priority", 0) or 0) <= 0:
            raise KeystoreError("no usable system keyring backend is available")
        self._index_path = Path(
            index_path
            or os.environ.get(
                "QUANTBT_KEYSTORE_INDEX",
                Path.home() / ".quantbt" / "keystore_index.json",
            )
        )
        self._lock_path = self._index_path.with_name(self._index_path.name + ".lock")
        _require_private_directory(self._index_path.parent)
        if not self._index_path.exists():
            _atomic_private_write(self._index_path, b"[]")
        _require_private_regular_file(self._index_path)

    def _read_index(self) -> list[str]:
        try:
            raw = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise KeystoreError("keyring index is unreadable or corrupt") from exc
        if not isinstance(raw, list) or not all(isinstance(item, str) and item for item in raw):
            raise KeystoreError("keyring index has an invalid schema")
        if raw != sorted(set(raw)):
            raise KeystoreError("keyring index is not canonical")
        return raw

    def _write_index(self, names: list[str]) -> None:
        payload = json.dumps(sorted(set(names)), separators=(",", ":")).encode("utf-8")
        _atomic_private_write(self._index_path, payload)

    def store(self, record: KeystoreRecord) -> None:
        if not record.name or not record.api_key or not record.api_secret:
            raise KeystoreError("keyring record requires name, API key, and API secret")
        encoded = json.dumps(record.to_dict(), separators=(",", ":"), ensure_ascii=False)
        with _locked_file(self._lock_path, exclusive=True):
            names = self._read_index()
            key_name = f"{record.name}::record:v2"
            previous = self._keyring.get_password(self._namespace, key_name)
            self._keyring.set_password(self._namespace, key_name, encoded)
            try:
                self._write_index([*names, record.name])
            except Exception:
                if previous is None:
                    try:
                        self._keyring.delete_password(self._namespace, key_name)
                    except Exception:  # noqa: BLE001
                        pass
                else:
                    self._keyring.set_password(self._namespace, key_name, previous)
                raise

    def fetch(self, name: str) -> KeystoreRecord:
        with _locked_file(self._lock_path, exclusive=False):
            encoded = self._keyring.get_password(self._namespace, f"{name}::record:v2")
        if not encoded:
            raise KeystoreError(f"keyring 未找到 {name}")
        try:
            payload = json.loads(encoded)
            record = KeystoreRecord(**payload)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise KeystoreError(f"keyring record is corrupt: {name}") from exc
        if record.name != name or not record.api_key or not record.api_secret:
            raise KeystoreError(f"keyring record identity is invalid: {name}")
        return record

    def delete(self, name: str) -> None:
        with _locked_file(self._lock_path, exclusive=True):
            names = self._read_index()
            key_name = f"{name}::record:v2"
            if self._keyring.get_password(self._namespace, key_name) is not None:
                self._keyring.delete_password(self._namespace, key_name)
            self._write_index([item for item in names if item != name])

    def list_names(self) -> list[str]:
        with _locked_file(self._lock_path, exclusive=False):
            return self._read_index()


class FernetFileBackend(KeystoreBackend):
    backend_name = "fernet_file"

    def __init__(self, path: Path, master_password: str) -> None:
        from cryptography.fernet import Fernet  # type: ignore[import-not-found]

        if not str(master_password or ""):
            raise KeystoreError("fernet_file backend requires a nonempty master password")
        self._path = Path(path)
        self._lock_path = self._path.with_name(self._path.name + ".lock")
        _require_private_directory(self._path.parent)
        _require_private_regular_file(self._path, allow_missing=True)
        self._key = derive_key_from_password(master_password, b"quantbt-keystore")
        self._fernet = Fernet(base64.urlsafe_b64encode(self._key))
        self._records: dict[str, KeystoreRecord] = {}
        with _locked_file(self._lock_path, exclusive=False):
            self._records = self._read_records_locked()

    def store(self, record: KeystoreRecord) -> None:
        if not record.name or not record.api_key or not record.api_secret:
            raise KeystoreError("fernet record requires name, API key, and API secret")
        with _locked_file(self._lock_path, exclusive=True):
            current = self._read_records_locked()
            updated = dict(current)
            updated[record.name] = KeystoreRecord(**record.to_dict())
            self._persist_records_locked(updated)
            self._records = updated

    def fetch(self, name: str) -> KeystoreRecord:
        with _locked_file(self._lock_path, exclusive=False):
            current = self._read_records_locked()
        self._records = current
        if name not in current:
            raise KeystoreError(f"fernet 文件无记录：{name}")
        return KeystoreRecord(**current[name].to_dict())

    def delete(self, name: str) -> None:
        with _locked_file(self._lock_path, exclusive=True):
            current = self._read_records_locked()
            updated = dict(current)
            updated.pop(name, None)
            self._persist_records_locked(updated)
            self._records = updated

    def list_names(self) -> list[str]:
        with _locked_file(self._lock_path, exclusive=False):
            current = self._read_records_locked()
        self._records = current
        return sorted(current)

    def _persist_records_locked(self, records: dict[str, KeystoreRecord]) -> None:
        payload = json.dumps(
            {name: records[name].to_dict() for name in sorted(records)},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        token = self._fernet.encrypt(payload)
        _atomic_private_write(self._path, token)

    def _read_records_locked(self) -> dict[str, KeystoreRecord]:
        if not self._path.exists():
            return {}
        _require_private_regular_file(self._path)
        token = self._path.read_bytes()
        if not token:
            raise KeystoreError("fernet keystore file is empty")
        try:
            data = json.loads(self._fernet.decrypt(token).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - cryptography uses backend-specific error classes.
            raise KeystoreError("fernet keystore cannot be decrypted or is corrupt") from exc
        if not isinstance(data, dict):
            raise KeystoreError("fernet keystore has an invalid schema")
        records: dict[str, KeystoreRecord] = {}
        try:
            for name, payload in data.items():
                if not isinstance(name, str) or not isinstance(payload, dict):
                    raise TypeError("invalid record")
                record = KeystoreRecord(**payload)
                if record.name != name or not record.api_key or not record.api_secret:
                    raise ValueError("invalid record identity")
                records[name] = record
        except (TypeError, ValueError) as exc:
            raise KeystoreError("fernet keystore contains an invalid record") from exc
        return records


def derive_key_from_password(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 derive 32 字节 key（Fernet 期望 32 字节 url-safe base64）。"""

    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=200_000, dklen=32)


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class SecureKeystore:
    """对外门面：backend selection is explicit and never silently degrades."""

    def __init__(self, backend: KeystoreBackend) -> None:
        self._backend = backend

    @classmethod
    def open(
        cls,
        prefer: str = "keyring",
        fernet_path: Path | None = None,
        master_password: str | None = None,
    ) -> "SecureKeystore":
        if prefer == "memory":
            return cls(InMemoryKeystore())
        if prefer == "fernet_file":
            if fernet_path is None or master_password is None:
                raise KeystoreError("fernet_file backend 必须提供 path 与 master_password")
            return cls(FernetFileBackend(fernet_path, master_password))
        if prefer != "keyring":
            raise KeystoreError(f"unsupported keystore backend: {prefer}")
        try:
            return cls(KeyringBackend())
        except Exception as exc:  # noqa: BLE001 - normalize optional backend failures.
            raise KeystoreError("system keyring backend is unavailable") from exc

    @property
    def backend_name(self) -> str:
        return self._backend.backend_name

    @property
    def is_durable(self) -> bool:
        return self.backend_name in {"keyring", "fernet_file"}

    def store(self, record: KeystoreRecord) -> None:
        self._backend.store(record)

    def fetch(self, name: str) -> KeystoreRecord:
        return self._backend.fetch(name)

    def delete(self, name: str) -> None:
        self._backend.delete(name)

    def list_names(self) -> list[str]:
        return self._backend.list_names()

    def rotate_secret(self, name: str, new_secret: str) -> None:
        rec = self.fetch(name)
        rec.api_secret = new_secret
        self._backend.store(rec)


def open_runtime_keystore(data_root: str | Path) -> SecureKeystore:
    """Open the configured process keystore without fallback.

    ``memory`` is available only when explicitly selected.  An unset backend
    chooses Fernet when a master key exists and otherwise requires a usable
    operating-system keyring.
    """

    root = Path(data_root)
    configured = str(os.environ.get("QUANTBT_KEYSTORE_BACKEND") or "").strip().lower()
    master_password = os.environ.get("QUANTBT_MASTER_KEY")
    backend = configured or ("fernet_file" if master_password else "keyring")
    if backend == "memory":
        runtime_mode = str(os.environ.get("QUANTBT_RUNTIME_MODE") or "").strip().lower()
        if runtime_mode not in {"test", "development"}:
            raise KeystoreError(
                "memory keystore is allowed only in explicit test or development runtime mode"
            )
        return SecureKeystore.open(prefer="memory")
    if backend == "fernet_file":
        if not master_password:
            raise KeystoreError("QUANTBT_MASTER_KEY is required for fernet_file keystore")
        configured_path = os.environ.get("QUANTBT_KEYSTORE_PATH")
        path = Path(configured_path) if configured_path else root / "security" / "trading_keystore.enc"
        return SecureKeystore.open(
            prefer="fernet_file",
            fernet_path=path,
            master_password=master_password,
        )
    if backend == "keyring":
        index_path = root / "security" / "keyring_index.json"
        try:
            return SecureKeystore(KeyringBackend(index_path=index_path))
        except Exception as exc:  # noqa: BLE001
            raise KeystoreError("configured keyring backend is unavailable") from exc
    raise KeystoreError(f"unsupported QUANTBT_KEYSTORE_BACKEND: {backend}")


def random_secret(n_bytes: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(n_bytes)).decode("ascii")


__all__ = [
    "FernetFileBackend",
    "InMemoryKeystore",
    "KeyringBackend",
    "KeystoreBackend",
    "KeystoreError",
    "KeystoreRecord",
    "SecureKeystore",
    "constant_time_compare",
    "derive_key_from_password",
    "open_runtime_keystore",
    "random_secret",
]
