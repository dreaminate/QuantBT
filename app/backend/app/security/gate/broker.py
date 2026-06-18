"""CapabilityToken（agent 持令牌、非 key）+ KeyBroker（JIT 短时 lease）（T-018 / spine 06，INV-3）。

密钥永不进 LLM/agent：agent 只拿 capability 令牌引用（结构上装不下 key），真实 key 只在 KeyBroker
发 lease 的那一刻在后端内存里。KeyBroker 是【唯一】持 SecureKeystore 句柄、能 fetch 真 key 的地方。
诚实边界（开放问题5）：broker 仍在属主机内存，被攻破时短时 lease 也能被截——只抬高代价、非干净修复。
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from ...lineage.ids import canonical_json

CapAction = Literal["request_live_order", "read_dataset", "write_run", "withdraw"]


class CapabilityToken(BaseModel):
    """agent 持这个、不持 key。注意：**无 api_key / api_secret 字段**（INV-3：结构上装不下 key）。"""

    cap_id: str
    action: CapAction
    gate_ref: str                       # 指向哪个冻结的 PolicyGate
    keystore_name: str                  # 引用名，非 key 本体
    expires_at_utc: str
    sig: str = ""                        # HMAC 签（防伪造）

    model_config = ConfigDict(frozen=True)

    def signing_payload(self) -> dict[str, Any]:
        return {"cap_id": self.cap_id, "action": self.action, "gate_ref": self.gate_ref,
                "keystore_name": self.keystore_name, "expires_at_utc": self.expires_at_utc}


class Lease:
    """短时凭证句柄。real_key 只在 broker 内存里活到 revoke；用完即焚。"""

    __slots__ = ("lease_id", "_record", "_revoked")

    def __init__(self, lease_id: str, record: Any) -> None:
        self.lease_id = lease_id
        self._record = record
        self._revoked = False

    @property
    def record(self) -> Any:
        if self._revoked:
            raise PermissionError(f"lease {self.lease_id} 已 revoke，凭证不可再用")
        return self._record

    def revoke(self) -> None:
        self._record = None
        self._revoked = True


class KeyBroker:
    """唯一持 keystore 句柄者。issue/verify capability，按需发 JIT lease。"""

    def __init__(self, keystore: Any, *, hmac_key: bytes | None = None, ttl_seconds: int = 60) -> None:
        self._keystore = keystore
        self._key = hmac_key or secrets.token_bytes(32)
        self._ttl = ttl_seconds
        self._leases: dict[str, Lease] = {}

    def _sign(self, payload: dict[str, Any]) -> str:
        return _hmac.new(self._key, canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()

    def issue_capability(self, *, action: CapAction, gate_ref: str, keystore_name: str) -> CapabilityToken:
        cap_id = "cap-" + secrets.token_hex(8)
        exp = (datetime.now(UTC) + timedelta(seconds=self._ttl)).isoformat()
        base = {"cap_id": cap_id, "action": action, "gate_ref": gate_ref,
                "keystore_name": keystore_name, "expires_at_utc": exp}
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
        if cap.action not in ("request_live_order",):
            raise PermissionError(f"capability action={cap.action} 无权发交易 lease")
        record = self._keystore.fetch(cap.keystore_name)   # 唯一 fetch 真 key 处
        lease = Lease("lease-" + secrets.token_hex(8), record)
        self._leases[lease.lease_id] = lease
        return lease

    def revoke(self, lease: Lease) -> None:
        lease.revoke()
        self._leases.pop(lease.lease_id, None)

    def has_key(self, keystore_name: str) -> bool:
        """key 是否已配置——**仅查名字、不 fetch 本体**（INV-3：存在性预检绝不物化 key 到内存）。

        供 relayer 做存在性预检；真 key 仍只在 issue() 发 lease 那一刻 fetch。
        """

        if not keystore_name:
            return False
        try:
            return keystore_name in self._keystore.list_names()
        except Exception:  # noqa: BLE001  后端错 → 视为未配置（fail-safe）
            return False


__all__ = ["CapAction", "CapabilityToken", "KeyBroker", "Lease"]
