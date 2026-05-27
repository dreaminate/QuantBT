"""M9.3 · 加密密钥存储。

GOAL 致命错误清单：「Binance API key / secret 明文落 YAML / 数据库 / 日志」
→ 必须用 keyring 加密。

我们提供三档 backend，按可用性自动选：
1. **keyring**：macOS Keychain / Win Credential Manager / Linux libsecret —— 首选
2. **fernet_file**：本地加密文件（cryptography Fernet + 用户主密码 PBKDF2）
3. **memory**：纯内存，仅用于测试/CI；进程结束即丢

无论哪档，API key / secret **从未** 走 YAML / DB / 日志，所有访问点统一 `SecureKeystore.get`。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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


class KeyringBackend(KeystoreBackend):
    backend_name = "keyring"

    def __init__(self, service_namespace: str = "quantbt") -> None:
        import keyring  # type: ignore[import-not-found]

        self._keyring = keyring
        self._namespace = service_namespace
        self._index_path = Path(os.environ.get("QUANTBT_KEYSTORE_INDEX", Path.home() / ".quantbt" / "keystore_index.json"))
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.touch(exist_ok=True)

    def _read_index(self) -> list[str]:
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8") or "[]")
        except Exception:  # noqa: BLE001
            return []

    def _write_index(self, names: list[str]) -> None:
        self._index_path.write_text(json.dumps(sorted(set(names))), encoding="utf-8")

    def store(self, record: KeystoreRecord) -> None:
        self._keyring.set_password(self._namespace, f"{record.name}::api_key", record.api_key)
        self._keyring.set_password(self._namespace, f"{record.name}::api_secret", record.api_secret)
        if record.note:
            self._keyring.set_password(self._namespace, f"{record.name}::note", record.note)
        names = self._read_index()
        names.append(record.name)
        self._write_index(names)

    def fetch(self, name: str) -> KeystoreRecord:
        api_key = self._keyring.get_password(self._namespace, f"{name}::api_key")
        api_secret = self._keyring.get_password(self._namespace, f"{name}::api_secret")
        note = self._keyring.get_password(self._namespace, f"{name}::note") or ""
        if not api_key or not api_secret:
            raise KeystoreError(f"keyring 未找到 {name}")
        return KeystoreRecord(name=name, api_key=api_key, api_secret=api_secret, note=note)

    def delete(self, name: str) -> None:
        for suffix in ("api_key", "api_secret", "note"):
            try:
                self._keyring.delete_password(self._namespace, f"{name}::{suffix}")
            except Exception:  # noqa: BLE001
                pass
        names = [n for n in self._read_index() if n != name]
        self._write_index(names)

    def list_names(self) -> list[str]:
        return self._read_index()


class FernetFileBackend(KeystoreBackend):
    backend_name = "fernet_file"

    def __init__(self, path: Path, master_password: str) -> None:
        from cryptography.fernet import Fernet  # type: ignore[import-not-found]

        self._fernet_cls = Fernet
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._key = derive_key_from_password(master_password, b"quantbt-keystore")
        self._fernet = Fernet(base64.urlsafe_b64encode(self._key))
        self._records: dict[str, KeystoreRecord] = {}
        if self._path.exists() and self._path.stat().st_size > 0:
            self._load()

    def store(self, record: KeystoreRecord) -> None:
        self._records[record.name] = record
        self._persist()

    def fetch(self, name: str) -> KeystoreRecord:
        if name not in self._records:
            raise KeystoreError(f"fernet 文件无记录：{name}")
        return self._records[name]

    def delete(self, name: str) -> None:
        self._records.pop(name, None)
        self._persist()

    def list_names(self) -> list[str]:
        return sorted(self._records.keys())

    def _persist(self) -> None:
        payload = json.dumps({n: r.to_dict() for n, r in self._records.items()}).encode("utf-8")
        token = self._fernet.encrypt(payload)
        self._path.write_bytes(token)

    def _load(self) -> None:
        token = self._path.read_bytes()
        data = json.loads(self._fernet.decrypt(token).decode("utf-8"))
        self._records = {n: KeystoreRecord(**r) for n, r in data.items()}


def derive_key_from_password(password: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 derive 32 字节 key（Fernet 期望 32 字节 url-safe base64）。"""

    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations=200_000, dklen=32)


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class SecureKeystore:
    """对外门面：自动选 backend；调用方永远只看到这层。"""

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
        # 默认 keyring；失败回退到 fernet 或 memory
        try:
            return cls(KeyringBackend())
        except Exception:  # noqa: BLE001
            if fernet_path and master_password:
                return cls(FernetFileBackend(fernet_path, master_password))
            return cls(InMemoryKeystore())

    @property
    def backend_name(self) -> str:
        return self._backend.backend_name

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
    "random_secret",
]
