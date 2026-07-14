"""LLM fixture 不可变工件 + 内容寻址 cache key + HMAC 完整性（T-016 / spine 02 §3.2）。

- `FixtureKey` 与内核 `node_id` / 账本 `config_hash` 同哈希族（sha256[:16]，00 §1.2-E）：一个 LLM
  节点的 node_id 即其 fixture_key（带 `llmfx-` 前缀，复用 `ids.fixture_key`）。
- cache key 内容寻址（dossier §7.3）：编码【图中位置 + 上游依赖 + run_index】，防 best-of-N / 分支碰撞。
  **fingerprint 不入 key**（否则供应商静默换模型→key 漂移→缓存永失效）；fingerprint 漂移走事件（store）。
- HMAC 完整性诚实边界（R12）：HMAC key 与 fixture 同机 → 只【防篡改/防自欺、非防本机恶意】，
  不宣称密码学不可抵赖。
- ``LLMFixture`` 的运行时对象保留 request/response 以供重放，但 ``to_dict`` 只返回无明文
  metadata；敏感 payload 必须由 ``FixtureStore`` 按 owner 加密后才能持久化。
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from ...lineage.ids import canonical_json, fixture_key as _make_fixture_key

# 不可变版本 id 的标志：含 8 位日期 / YYYY-MM-DD / 明确快照后缀。否则视为会滚动的【别名】。
_DATE_RE = re.compile(r"\d{8}|\d{4}-\d{2}-\d{2}")
_ALIAS_MARKERS = ("latest", "preview")
_GATEWAY_AUDIT_FIELD = "gateway_audit"
_GATEWAY_AUDIT_KEYS = frozenset({"provider", "model", "auth_ref", "origin_call_ref"})
_PROVIDER_CHARS = frozenset("._-")
_MODEL_CHARS = frozenset("._:/+-")
_SECRET_REF_CHARS = frozenset("._-+")


def is_alias_model_id(model_id: str | None) -> bool:
    """model_id 是否为会滚动的别名（dossier §5.4 禁用别名当不可变 id）。"""

    if not model_id:
        return True
    m = model_id.lower()
    if any(k in m for k in _ALIAS_MARKERS):
        return True
    return _DATE_RE.search(model_id) is None


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def owner_scope_ref(owner_user_id: str) -> str:
    """不泄露 owner 明文的稳定 scope ref。

    这只是索引/隔离标签，不是授权凭据；授权仍由调用方传入的已认证 owner 承担。
    """

    owner = str(owner_user_id or "").strip()
    if not owner:
        raise ValueError("owner_user_id 不能为空：replay 持久化操作必须带 owner scope")
    digest = hashlib.sha256(owner.encode("utf-8")).hexdigest()
    return f"ownerref:{digest[:32]}"


def _safe_ascii_identifier(value: str, *, punctuation: frozenset[str], limit: int) -> bool:
    return bool(value) and len(value) <= limit and value.isascii() and all(
        ch.isalnum() or ch in punctuation for ch in value
    )


def _safe_secret_ref(value: str) -> bool:
    prefix = "secretref://"
    if not value.startswith(prefix) or len(value) > 256:
        return False
    parts = value[len(prefix):].split("/")
    return len(parts) == 2 and all(
        _safe_ascii_identifier(part, punctuation=_SECRET_REF_CHARS, limit=128)
        for part in parts
    )


def gateway_audit_metadata(
    *,
    provider: str,
    model: str,
    auth_ref: str,
    origin_call_ref: str,
) -> dict[str, str]:
    """Return the only gateway evidence allowed in fixture metadata.

    Prompt/output bodies, owner ids and credential material are deliberately
    outside this schema. ``auth_ref`` is a controlled SecretRef, never a key.
    """

    values = {
        "provider": str(provider or ""),
        "model": str(model or ""),
        "auth_ref": str(auth_ref or ""),
        "origin_call_ref": str(origin_call_ref or ""),
    }
    if not _safe_ascii_identifier(
        values["provider"], punctuation=_PROVIDER_CHARS, limit=128,
    ):
        raise ValueError("fixture gateway provider is not a controlled identifier")
    if (
        "://" in values["model"]
        or not _safe_ascii_identifier(values["model"], punctuation=_MODEL_CHARS, limit=256)
    ):
        raise ValueError("fixture gateway model is not a controlled identifier")
    if not _safe_secret_ref(values["auth_ref"]):
        raise ValueError("fixture gateway auth_ref must be a controlled SecretRef")
    origin = values["origin_call_ref"]
    if len(origin) != 16 or any(ch not in "0123456789abcdef" for ch in origin):
        raise ValueError("fixture gateway origin_call_ref must be a sha256/16 reference")
    return values


def attach_gateway_audit_metadata(
    model_pin: dict[str, Any],
    *,
    provider: str,
    model: str,
    auth_ref: str,
    origin_call_ref: str,
) -> dict[str, Any]:
    """Attach validated audit refs without widening encrypted fixture payloads."""

    pin = dict(model_pin)
    pin[_GATEWAY_AUDIT_FIELD] = gateway_audit_metadata(
        provider=provider,
        model=model,
        auth_ref=auth_ref,
        origin_call_ref=origin_call_ref,
    )
    return pin


def extract_gateway_audit_metadata(model_pin: dict[str, Any]) -> dict[str, str] | None:
    """Read a complete safe audit envelope; malformed/legacy metadata is absent."""

    raw = model_pin.get(_GATEWAY_AUDIT_FIELD) if isinstance(model_pin, dict) else None
    if not isinstance(raw, dict) or set(raw) != _GATEWAY_AUDIT_KEYS:
        return None
    try:
        return gateway_audit_metadata(
            provider=raw.get("provider", ""),
            model=raw.get("model", ""),
            auth_ref=raw.get("auth_ref", ""),
            origin_call_ref=raw.get("origin_call_ref", ""),
        )
    except ValueError:
        return None


@dataclass(frozen=True)
class ModelPin:
    provider: str
    model_id: str                    # 不可变版本 id；别名会被 store 标 model_id_is_alias 告警
    system_fingerprint: str | None    # 录制时供应商回传；None = 供应商未提供（诚实标注）
    params: dict[str, Any] = field(default_factory=dict)   # {temperature, top_p, seed, max_tokens}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def is_alias(self) -> bool:
        return is_alias_model_id(self.model_id)

    def requested_digest(self) -> str:
        """进 cache key 的【请求侧】摘要：不含 fingerprint（fingerprint 漂移走事件、不漂移 key）。"""

        return _sha16(canonical_json({"provider": self.provider, "model_id": self.model_id,
                                      "params": self.params}))


@dataclass(frozen=True)
class FixtureKey:
    node_pos: str          # 图中位置 f"{run_id}:{step_idx}"（agent loop 内稳定坐标）
    prompt_digest: str     # sha256(canonical(messages+tools))[:16]
    model_pin_digest: str  # ModelPin.requested_digest()
    upstream_digest: str   # 上游依赖摘要（上一 fixture_key + 注入工具返回摘要）——防分支碰撞
    run_index: int = 0     # best-of-N / 并行分支序号——防同坐标多采样碰撞

    def compute(self) -> str:
        """-> "llmfx-<sha256[:16]>"。与 node_id 同哈希族（00 §1.2-E）。"""

        payload = {
            "node_pos": self.node_pos, "prompt_digest": self.prompt_digest,
            "model_pin_digest": self.model_pin_digest, "upstream_digest": self.upstream_digest,
            "run_index": self.run_index,
        }
        return _make_fixture_key(_sha16(canonical_json(payload)))


def prompt_digest(messages: Any, tools: Any) -> str:
    return _sha16(canonical_json({"messages": messages, "tools": tools}))


@dataclass
class LLMFixture:
    fixture_key: str                 # = FixtureKey.compute()，亦即本 LLM 节点的 node_id
    run_id: str                      # C1，部件03 RunStore 句柄（uuid，非内容哈希）
    repro_level: str                 # ReproLevel
    model_pin: dict[str, Any]
    request: dict[str, Any]          # 只存内存；持久化由 FixtureStore 按 owner 加密
    response: dict[str, Any]         # 只存内存；不得进 metadata JSONL 明文
    tool_calls: list[dict[str, Any]] # 只存内存；arguments 可含私密输出
    translation_status: str          # ok | schema_invalid | human_confirm_required
    owner_ref: str = ""             # owner_user_id 的稳定摘要，绝不存 owner 明文
    schema_ref: str | None = None
    decision_authority: str = "none"  # 恒 none：LLM 不持决策权（R7）
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    integrity: str = ""              # HMAC-SHA256(canonical(除 integrity 外全字段), key)
    consumed: bool = False           # 一次性消费留痕（R12，对 frozen_oos 类）
    tombstoned: bool = False         # 软删；distinct 计数不因此减少（honest-N 不可改小）

    # HMAC 只签【内容/身份】字段，不签可变 provenance（复核 #4/#6/#14）：
    # - tombstoned/consumed 是事后可变状态（tombstone/consume 改它们），若签则改后 get() 误报篡改、fixture 被锁死。
    # - created_at_utc 是时间戳，若签则同内容不同时刻 record 触发假 FixtureConflict（破幂等）。
    # integrity 保护的是【LLM 真输出 response/tool_calls/model_pin】这些不可变内容（A2 篡改仍被抓）。
    _UNSIGNED_FIELDS = ("integrity", "created_at_utc", "consumed", "tombstoned")

    def signing_payload(self) -> dict[str, Any]:
        d = asdict(self)
        for k in self._UNSIGNED_FIELDS:
            d.pop(k, None)
        return d

    def sensitive_payload(self) -> dict[str, Any]:
        """只允许交给 owner-scoped 加密存储的敏感 payload。"""

        return {
            "run_id": self.run_id,
            "request": self.request,
            "response": self.response,
            "tool_calls": self.tool_calls,
        }

    def to_memory_dict(self) -> dict[str, Any]:
        """显式的运行时复制面；可含明文，不得直接落盘。"""

        return asdict(self)

    def to_dict(self) -> dict[str, Any]:
        """安全 metadata 序列化：不含 owner/run/prompt/output/tool-call 明文。"""

        if not self.owner_ref:
            raise ValueError("LLMFixture 缺 owner_ref，拒绝序列化 ownerless fixture metadata")
        model_pin = dict(self.model_pin)
        if _GATEWAY_AUDIT_FIELD in model_pin:
            audit = extract_gateway_audit_metadata(model_pin)
            if audit is None:
                raise ValueError("fixture gateway audit metadata is malformed or unsafe")
            model_pin[_GATEWAY_AUDIT_FIELD] = audit
        return {
            "fixture_key": self.fixture_key,
            "owner_ref": self.owner_ref,
            "run_ref": _sha256_json({"run_id": self.run_id}),
            "repro_level": self.repro_level,
            "model_pin": model_pin,
            "request_digest": _sha256_json(self.request),
            "response_digest": _sha256_json(self.response),
            "tool_calls_digest": _sha256_json(self.tool_calls),
            "translation_status": self.translation_status,
            "schema_ref": self.schema_ref,
            "decision_authority": self.decision_authority,
            "created_at_utc": self.created_at_utc,
            "integrity": self.integrity,
            "consumed": self.consumed,
            "tombstoned": self.tombstoned,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LLMFixture":
        """仅从显式的运行时 payload 恢复；安全 metadata 单独无法重建明文。"""

        required_sensitive = {"run_id", "request", "response", "tool_calls"}
        if not required_sensitive.issubset(d):
            raise ValueError("serialized fixture metadata 不含明文 payload；须先由 FixtureStore 按 owner 解密")
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def compute_hmac(fixture: LLMFixture, key: bytes) -> str:
    msg = canonical_json(fixture.signing_payload()).encode("utf-8")
    return _hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_hmac(fixture: LLMFixture, key: bytes) -> bool:
    expected = compute_hmac(fixture, key)
    return _hmac.compare_digest(expected, fixture.integrity or "")


__all__ = [
    "FixtureKey", "LLMFixture", "ModelPin", "attach_gateway_audit_metadata",
    "compute_hmac", "extract_gateway_audit_metadata", "gateway_audit_metadata",
    "is_alias_model_id", "owner_scope_ref", "prompt_digest", "verify_hmac",
]
