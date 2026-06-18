"""LLM fixture 不可变工件 + 内容寻址 cache key + HMAC 完整性（T-016 / spine 02 §3.2）。

- `FixtureKey` 与内核 `node_id` / 账本 `config_hash` 同哈希族（sha256[:16]，00 §1.2-E）：一个 LLM
  节点的 node_id 即其 fixture_key（带 `llmfx-` 前缀，复用 `ids.fixture_key`）。
- cache key 内容寻址（dossier §7.3）：编码【图中位置 + 上游依赖 + run_index】，防 best-of-N / 分支碰撞。
  **fingerprint 不入 key**（否则供应商静默换模型→key 漂移→缓存永失效）；fingerprint 漂移走事件（store）。
- HMAC 完整性诚实边界（R12）：HMAC key 与 fixture 同机 → 只【防篡改/防自欺、非防本机恶意】，
  不宣称密码学不可抵赖。
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
    request: dict[str, Any]          # 完整 messages + tools + 请求参数（敏感 → 调用方决定是否加密）
    response: dict[str, Any]         # content + tool_calls + raw
    tool_calls: list[dict[str, Any]]
    translation_status: str          # ok | schema_invalid | human_confirm_required
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LLMFixture":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def compute_hmac(fixture: LLMFixture, key: bytes) -> str:
    msg = canonical_json(fixture.signing_payload()).encode("utf-8")
    return _hmac.new(key, msg, hashlib.sha256).hexdigest()


def verify_hmac(fixture: LLMFixture, key: bytes) -> bool:
    expected = compute_hmac(fixture, key)
    return _hmac.compare_digest(expected, fixture.integrity or "")


__all__ = [
    "FixtureKey", "LLMFixture", "ModelPin", "compute_hmac", "is_alias_model_id",
    "prompt_digest", "verify_hmac",
]
