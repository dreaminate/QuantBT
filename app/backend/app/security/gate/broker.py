"""CapabilityToken（agent 持令牌、非 key）+ KeyBroker（JIT 短时 lease）（T-018 / spine 06，INV-3）。

密钥永不进 LLM/agent：agent 只拿 capability 令牌引用（结构上装不下 key），真实 key 只在 KeyBroker
发 lease 的那一刻在后端内存里。KeyBroker 是【唯一】持 SecureKeystore 句柄、能 fetch 真 key 的地方。
诚实边界（开放问题5）：broker 仍在属主机内存，被攻破时短时 lease 也能被截——只抬高代价、非干净修复。
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import os
import secrets
import stat
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field

from ...lineage.ids import canonical_json
from .account_halt import PersistentAccountHaltBarrier

CapAction = Literal[
    "request_live_order",
    "emergency_reduce_risk",
    "verify_account_identity",
    "read_dataset",
    "write_run",
    "withdraw",
]


class CapabilityToken(BaseModel):
    """agent 持这个、不持 key。注意：**无 api_key / api_secret 字段**（INV-3：结构上装不下 key）。"""

    cap_id: str
    action: CapAction
    gate_ref: str                       # 指向哪个冻结的 PolicyGate
    keystore_name: str                  # 引用名，非 key 本体
    expires_at_utc: str
    account_identity_ref: str | None = None
    owner_user_id: str | None = None
    credential_binding_ref: str | None = None
    requires_halt_fence: bool = False
    account_halt_epoch: int | None = None
    sig: str = Field(default="", repr=False)  # HMAC 签（防伪造）。防明文：repr/str 永不渲染；model_dump 仍暴露——verify_capability 需 sig 校验（功能边界·勿排除）

    model_config = ConfigDict(frozen=True)

    def signing_payload(self) -> dict[str, Any]:
        return {
            "cap_id": self.cap_id,
            "action": self.action,
            "gate_ref": self.gate_ref,
            "keystore_name": self.keystore_name,
            "expires_at_utc": self.expires_at_utc,
            "account_identity_ref": self.account_identity_ref,
            "owner_user_id": self.owner_user_id,
            "credential_binding_ref": self.credential_binding_ref,
            "requires_halt_fence": self.requires_halt_fence,
            "account_halt_epoch": self.account_halt_epoch,
        }


class Lease:
    """短时凭证句柄。real_key 只在 broker 内存里活到 revoke；用完即焚。"""

    __slots__ = ("lease_id", "_record", "_revoked", "_on_revoke", "_revoke_lock")

    def __init__(
        self,
        lease_id: str,
        record: Any,
        *,
        on_revoke: Callable[[], None] | None = None,
    ) -> None:
        self.lease_id = lease_id
        self._record = record
        self._revoked = False
        self._on_revoke = on_revoke
        self._revoke_lock = threading.Lock()

    @property
    def record(self) -> Any:
        if self._revoked:
            raise PermissionError(f"lease {self.lease_id} 已 revoke，凭证不可再用")
        return self._record

    def revoke(self) -> None:
        callback = None
        with self._revoke_lock:
            if self._revoked:
                return
            self._record = None
            self._revoked = True
            callback = self._on_revoke
            self._on_revoke = None
        if callback is not None:
            callback()


class KeyBroker:
    """唯一持 keystore 句柄者。issue/verify capability，按需发 JIT lease。"""

    def __init__(
        self,
        keystore: Any,
        *,
        hmac_key: bytes | None = None,
        hmac_key_path: str | Path | None = None,
        ttl_seconds: int = 60,
        active_account_validator: Callable[[CapabilityToken], bool] | None = None,
        credential_owner_validator: Callable[[str, str], bool] | None = None,
        credential_binding_resolver: Callable[[str, str], str | None] | None = None,
        account_halt_barrier: PersistentAccountHaltBarrier | None = None,
    ) -> None:
        if hmac_key is not None and hmac_key_path is not None:
            raise ValueError("hmac_key and hmac_key_path are mutually exclusive")
        self._keystore = keystore
        self._key = hmac_key or (
            self._load_or_create_hmac_key(Path(hmac_key_path))
            if hmac_key_path is not None
            else secrets.token_bytes(32)
        )
        if len(self._key) < 32:
            raise ValueError("KeyBroker HMAC key must contain at least 32 bytes")
        self._ttl = ttl_seconds
        self._active_account_validator = active_account_validator
        self._credential_owner_validator = credential_owner_validator
        self._credential_binding_resolver = credential_binding_resolver
        self._account_halt_barrier = account_halt_barrier
        self._leases: dict[str, Lease] = {}

    def _owner_allows(self, owner_user_id: str | None, keystore_name: str) -> bool:
        if self._credential_owner_validator is None:
            return True
        owner = str(owner_user_id or "").strip()
        return bool(owner and self._credential_owner_validator(owner, keystore_name))

    @staticmethod
    def _load_or_create_hmac_key(path: Path) -> bytes:
        """Load one process-stable broker key, creating it with mode 0600 once.

        The same key protects capability signatures and derives opaque account
        bindings.  Persisting it is required so an exchange account cannot gain
        a new identity merely by restarting the backend.
        """

        if path.parent.exists() and path.parent.is_symlink():
            raise ValueError(f"KeyBroker key directory must not be a symlink: {path.parent}")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        parent_info = path.parent.stat()
        if not stat.S_ISDIR(parent_info.st_mode) or parent_info.st_uid != os.getuid():
            raise ValueError(f"KeyBroker key directory is not privately owned: {path.parent}")
        path.parent.chmod(0o700)
        if path.exists():
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise ValueError(f"KeyBroker HMAC key must be a regular non-symlink file: {path}")
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError(f"KeyBroker HMAC key must be owner-only mode 0600: {path}")
        try:
            key = path.read_bytes()
        except FileNotFoundError:
            candidate = secrets.token_bytes(32)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                key = path.read_bytes()
            else:
                try:
                    os.write(fd, candidate)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                parent_fd = os.open(path.parent, os.O_RDONLY)
                try:
                    os.fsync(parent_fd)
                finally:
                    os.close(parent_fd)
                key = candidate
        if len(key) < 32:
            raise ValueError(f"invalid KeyBroker HMAC key at {path}")
        info = path.lstat()
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise ValueError(f"KeyBroker HMAC key is not private: {path}")
        return key

    def _sign(self, payload: dict[str, Any]) -> str:
        capability_key = _hmac.new(self._key, b"quantbt:key-broker:capability:v1", hashlib.sha256).digest()
        return _hmac.new(capability_key, canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()

    def issue_capability(
        self,
        *,
        action: CapAction,
        gate_ref: str,
        keystore_name: str,
        account_identity_ref: str | None = None,
        owner_user_id: str | None = None,
        requires_halt_fence: bool = False,
    ) -> CapabilityToken:
        if type(requires_halt_fence) is not bool:
            raise TypeError("requires_halt_fence must be an exact boolean")
        if requires_halt_fence and action != "request_live_order":
            raise ValueError("only a live-order capability may require an account HALT fence")
        if not self._owner_allows(owner_user_id, keystore_name):
            raise PermissionError("keystore credential is not owned by the capability principal")
        credential_binding_ref = None
        if self._credential_binding_resolver is not None:
            credential_binding_ref = self._credential_binding_resolver(
                str(owner_user_id or ""),
                keystore_name,
            )
            if not credential_binding_ref:
                raise PermissionError("keystore credential has no active immutable binding")
        account_halt_epoch = None
        if requires_halt_fence:
            if self._account_halt_barrier is None:
                raise PermissionError("live-order capability requires an available account HALT barrier")
            account_ref = str(account_identity_ref or "").strip()
            owner = str(owner_user_id or "").strip()
            if not account_ref or not owner:
                raise PermissionError("live-order capability requires an owned account HALT identity")
            account_halt_epoch = self._account_halt_barrier.running_epoch(account_ref, owner)
        cap_id = "cap-" + secrets.token_hex(8)
        exp = (datetime.now(UTC) + timedelta(seconds=self._ttl)).isoformat()
        base = {
            "cap_id": cap_id,
            "action": action,
            "gate_ref": gate_ref,
            "keystore_name": keystore_name,
            "expires_at_utc": exp,
            "account_identity_ref": account_identity_ref,
            "owner_user_id": owner_user_id,
            "credential_binding_ref": credential_binding_ref,
            "requires_halt_fence": requires_halt_fence,
            "account_halt_epoch": account_halt_epoch,
        }
        return CapabilityToken(**base, sig=self._sign(base))

    def verify_capability(self, cap: CapabilityToken) -> bool:
        if not _hmac.compare_digest(self._sign(cap.signing_payload()), cap.sig or ""):
            return False
        try:
            return datetime.fromisoformat(cap.expires_at_utc) >= datetime.now(UTC)
        except ValueError:
            return False

    def issue(self, cap: CapabilityToken) -> Lease:
        """凭有效 capability 发 JIT lease（此刻才 fetch 真 key 到后端内存）。无效 cap → PermissionError。"""

        if not self.verify_capability(cap):
            raise PermissionError("capability 无效/过期/签名不符——拒发 lease")
        if cap.action not in ("request_live_order", "emergency_reduce_risk", "verify_account_identity"):
            raise PermissionError(f"capability action={cap.action} 无权发交易 lease")
        execution_fence = None
        try:
            if type(cap.requires_halt_fence) is not bool:
                raise PermissionError("capability HALT-fence flag is malformed")
            if cap.requires_halt_fence:
                if cap.action != "request_live_order" or self._account_halt_barrier is None:
                    raise PermissionError("live-order capability HALT barrier is unavailable")
                if type(cap.account_halt_epoch) is not int or cap.account_halt_epoch <= 0:
                    raise PermissionError("live-order capability lacks an exact account HALT epoch")
                execution_fence = self._account_halt_barrier.acquire_execution_fence(
                    str(cap.account_identity_ref or ""),
                    str(cap.owner_user_id or ""),
                    cap.account_halt_epoch,
                )
            elif cap.account_halt_epoch is not None:
                raise PermissionError("unfenced capability must not carry an account HALT epoch")
            if not self._owner_allows(cap.owner_user_id, cap.keystore_name):
                raise PermissionError("keystore credential ownership no longer permits this capability")
            if self._credential_binding_resolver is not None:
                current_binding = self._credential_binding_resolver(
                    str(cap.owner_user_id or ""),
                    cap.keystore_name,
                )
                if not current_binding or current_binding != cap.credential_binding_ref:
                    raise PermissionError("keystore credential version binding changed")
            if (
                cap.action != "verify_account_identity"
                and cap.account_identity_ref
                and self._active_account_validator is not None
            ):
                if not self._active_account_validator(cap):
                    raise PermissionError("account lifecycle no longer permits this capability action")
            record = self._keystore.fetch(cap.keystore_name)   # 唯一 fetch 真 key 处
            if cap.credential_binding_ref:
                observed_binding = self._credential_binding_from_record(record)
                if not _hmac.compare_digest(observed_binding, cap.credential_binding_ref):
                    raise PermissionError("keystore credential material does not match its immutable binding")
            lease = Lease(
                "lease-" + secrets.token_hex(8),
                record,
                on_revoke=(execution_fence.release if execution_fence is not None else None),
            )
            execution_fence = None
            self._leases[lease.lease_id] = lease
            return lease
        finally:
            if execution_fence is not None:
                execution_fence.release()

    def revoke(self, lease: Lease) -> None:
        try:
            lease.revoke()
        finally:
            self._leases.pop(lease.lease_id, None)

    def has_key(self, keystore_name: str, *, owner_user_id: str | None = None) -> bool:
        """key 是否已配置——**仅查名字、不 fetch 本体**（INV-3：存在性预检绝不物化 key 到内存）。

        供 relayer 做存在性预检；真 key 仍只在 issue() 发 lease 那一刻 fetch。
        """

        if not keystore_name:
            return False
        if not self._owner_allows(owner_user_id, keystore_name):
            return False
        try:
            return keystore_name in self._keystore.list_names()
        except Exception:  # noqa: BLE001  后端错 → 视为未配置（fail-safe）
            return False

    def credential_binding_ref(
        self,
        keystore_name: str,
        *,
        owner_user_id: str | None = None,
    ) -> str:
        """Return an opaque identity for one credential, not for its venue account.

        Both credential fields are materialized only inside the broker and are
        never returned.  Binding the full pair detects a secret-only swap.
        """

        if not keystore_name:
            raise PermissionError("keystore_name 为空——无法建立账户绑定")
        if not self._owner_allows(owner_user_id, keystore_name):
            raise PermissionError("keystore credential is not owned by this principal")
        record = self._keystore.fetch(keystore_name)
        return self._credential_binding_from_record(record)

    def _credential_binding_from_record(self, record: Any) -> str:
        api_key = str(
            getattr(record, "api_key", "")
            or (record.get("api_key") if isinstance(record, dict) else "")
            or ""
        )
        api_secret = str(
            getattr(record, "api_secret", "")
            or (record.get("api_secret") if isinstance(record, dict) else "")
            or ""
        )
        if not api_key or not api_secret:
            raise PermissionError("keystore record requires both API key and API secret")
        material = canonical_json({"api_key": api_key, "api_secret": api_secret})
        key = _hmac.new(
            self._key,
            b"quantbt:key-broker:credential-material:v2",
            hashlib.sha256,
        ).digest()
        digest = _hmac.new(key, material.encode("utf-8"), hashlib.sha256).hexdigest()
        return "exchange_credential_v2_" + digest

    def account_binding_ref(
        self,
        keystore_name: str,
        *,
        owner_user_id: str | None = None,
    ) -> str:
        """Compatibility alias for credential identity; live code must attest a venue UID."""

        return self.credential_binding_ref(keystore_name, owner_user_id=owner_user_id)

    def account_identity_ref(
        self,
        *,
        venue: str,
        network: str,
        product: str,
        venue_account_uid: str,
    ) -> str:
        """Derive stable account identity only from an authenticated venue-issued UID."""

        uid = str(venue_account_uid or "").strip()
        if not uid:
            raise PermissionError("venue-issued account UID is required for mainnet identity")
        payload = canonical_json(
            {
                "venue": str(venue or "").strip().lower(),
                "network": str(network or "").strip().lower(),
                "product": str(product or "").strip().lower(),
                "venue_account_uid": uid,
            }
        )
        key = _hmac.new(self._key, b"quantbt:key-broker:account-identity:v1", hashlib.sha256).digest()
        digest = _hmac.new(key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return "exchange_account_uid_" + digest


__all__ = ["CapAction", "CapabilityToken", "KeyBroker", "Lease"]
