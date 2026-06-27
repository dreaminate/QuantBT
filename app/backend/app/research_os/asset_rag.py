"""Research Asset RAG runtime contract.

GOAL §5 requires RAG to serve both the user and resident agents without turning
retrieval into a verdict or leaking secrets. This module is a small in-memory
index with the invariants that later persistent stores must keep:
- retrieval respects user, desk, asset, and permission-tag visibility;
- every hit carries source_id, version, timestamp, permission, and applicability;
- agent-used hits are recorded for user inspection;
- SecretRef metadata is searchable, plaintext credentials are rejected;
- user-waived methodology cannot be displayed as strong system evidence.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..lineage.ids import content_hash


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, tuple):
        return tuple(str(v) for v in value)
    if isinstance(value, list | set):
        return tuple(str(v) for v in value)
    return (str(value),)


def _token_stream(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", text or "")]


def _tokens(text: str) -> set[str]:
    return set(_token_stream(text))


def _token_counts(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for token in _token_stream(text):
        counts[token] = counts.get(token, 0) + 1
    return counts


def _cosine_similarity(left: dict[str, int], right: dict[str, int]) -> float:
    dot = sum(value * right.get(token, 0) for token, value in left.items())
    if dot <= 0:
        return 0.0
    left_norm = sum(value * value for value in left.values()) ** 0.5
    right_norm = sum(value * value for value in right.values()) ** 0.5
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


DENSE_EMBEDDING_MODEL_REF = "local_hash_dense_v1"
DENSE_EMBEDDING_DIMENSIONS = 64


def _dense_embedding(text: str, *, dimensions: int = DENSE_EMBEDDING_DIMENSIONS) -> tuple[float, ...]:
    counts = _token_counts(text)
    if not counts:
        return tuple(0.0 for _ in range(dimensions))
    vector = [0.0 for _ in range(dimensions)]
    for token, count in counts.items():
        idx = int(content_hash({"token": token, "slot": "idx"}), 16) % dimensions
        sign = 1.0 if int(content_hash({"token": token, "slot": "sign"}), 16) % 2 == 0 else -1.0
        vector[idx] += sign * float(count)
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0.0:
        return tuple(0.0 for _ in range(dimensions))
    return tuple(value / norm for value in vector)


def _dense_cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True))


def _dense_text_for_document(document: "AssetRAGDocument") -> str:
    return " ".join([document.title, document.body, document.applicability, document.asset_ref, document.source_kind])


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


class AssetRAGError(ValueError):
    """Research Asset RAG rejected a document, query, or usage record."""


class RAGProjection(str, Enum):
    DATA = "DataRAG"
    FACTOR = "FactorRAG"
    MODEL = "ModelRAG"
    SIGNAL = "SignalRAG"
    STRATEGY = "StrategyRAG"
    RESEARCH = "ResearchRAG"
    RUN = "RunRAG"
    MATH = "MathRAG"
    CONSISTENCY = "ConsistencyRAG"


STRONG_EVIDENCE_LABELS = frozenset({"proof_backed", "evidence_sufficient", "production_ready"})
WAIVED_LABELS = frozenset({"user_waived", "user_waived_theory", "user_waived_validation"})

_FORBIDDEN_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "password",
    "private_key",
    "plaintext",
    "oauth_token",
    "access_token",
    "refresh_token",
    "credential_value",
)
_ALLOWED_REF_KEY_PARTS = (
    "secret_ref",
    "token_ref",
    "auth_ref",
    "credential_pool_ref",
    "scope",
    "status",
    "last_test",
    "last_used",
    "quota_status",
    "health_status",
)
_SECRET_VALUE_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(api[_-]?key|password|oauth[_-]?token)\s*[:=]\s*['\"]?[^,\s'\"]{6,}"),
)


@dataclass(frozen=True)
class RAGPermission:
    allowed_users: tuple[str, ...] = ()
    allowed_desks: tuple[str, ...] = ()
    allowed_assets: tuple[str, ...] = ()
    permission_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "allowed_users", _tuple(self.allowed_users))
        object.__setattr__(self, "allowed_desks", _tuple(self.allowed_desks))
        object.__setattr__(self, "allowed_assets", _tuple(self.allowed_assets))
        object.__setattr__(self, "permission_tags", _tuple(self.permission_tags))

    def snapshot(self) -> dict[str, tuple[str, ...]]:
        return {
            "allowed_users": self.allowed_users,
            "allowed_desks": self.allowed_desks,
            "allowed_assets": self.allowed_assets,
            "permission_tags": self.permission_tags,
        }


@dataclass(frozen=True)
class RAGQueryContext:
    user_id: str
    desk: str
    visible_asset_refs: tuple[str, ...]
    permission_tags: tuple[str, ...] = ()
    actor: str = "user"

    def __post_init__(self) -> None:
        object.__setattr__(self, "visible_asset_refs", _tuple(self.visible_asset_refs))
        object.__setattr__(self, "permission_tags", _tuple(self.permission_tags))
        if not self.user_id:
            raise AssetRAGError("user_id is required")
        if not self.desk:
            raise AssetRAGError("desk is required")


@dataclass(frozen=True)
class AssetRAGDocument:
    source_id: str
    version: str
    title: str
    body: str
    projection: RAGProjection | str
    asset_ref: str
    permission: RAGPermission
    applicability: str
    source_kind: str
    timestamp: str = field(default_factory=_now)
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence_label: str = "candidate_context"
    methodology_path: str | None = None
    document_id: str = ""

    def __post_init__(self) -> None:
        for name in ("source_id", "version", "title", "body", "asset_ref", "applicability", "source_kind"):
            if not str(getattr(self, name) or "").strip():
                raise AssetRAGError(f"{name} is required")
        _reject_plaintext_secret(self.body, self.metadata)
        label = str(self.evidence_label or "")
        method = str(self.methodology_path or "")
        if method in WAIVED_LABELS and label in STRONG_EVIDENCE_LABELS:
            raise AssetRAGError("user-waived methodology cannot be indexed as strong system evidence")
        if not self.document_id:
            object.__setattr__(
                self,
                "document_id",
                "ragdoc_" + content_hash(
                    {
                        "source_id": self.source_id,
                        "version": self.version,
                        "asset_ref": self.asset_ref,
                        "projection": str(self.projection.value if isinstance(self.projection, Enum) else self.projection),
                        "body": self.body,
                    }
                ),
            )

    @property
    def projection_value(self) -> str:
        return str(self.projection.value if isinstance(self.projection, Enum) else self.projection)


@dataclass(frozen=True)
class AssetRAGHit:
    source_id: str
    version: str
    timestamp: str
    permission: dict[str, tuple[str, ...]]
    applicability: str
    projection: str
    asset_ref: str
    title: str
    snippet: str
    score: float
    evidence_label: str
    context_role: str = "candidate_context"

    def __post_init__(self) -> None:
        if not self.source_id or not self.version:
            raise AssetRAGError("RAG hit requires source_id and version")
        if self.context_role != "candidate_context":
            raise AssetRAGError("RAG hit must remain candidate_context, not system conclusion")


@dataclass(frozen=True)
class AgentRAGUsage:
    usage_id: str
    agent_id: str
    user_id: str
    source_id: str
    version: str
    asset_ref: str
    projection: str
    purpose: str
    timestamp: str


@dataclass(frozen=True)
class AssetRAGDenseVector:
    vector_ref: str
    document_id: str
    source_id: str
    version: str
    embedding_model_ref: str
    dimensions: int
    vector: tuple[float, ...]
    source_hash: str
    timestamp: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if not self.document_id:
            raise AssetRAGError("dense vector requires document_id")
        if not self.source_id or not self.version:
            raise AssetRAGError("dense vector requires source_id and version")
        if self.embedding_model_ref != DENSE_EMBEDDING_MODEL_REF:
            raise AssetRAGError("unsupported dense embedding model")
        object.__setattr__(self, "vector", tuple(float(v) for v in self.vector))
        if self.dimensions != DENSE_EMBEDDING_DIMENSIONS or len(self.vector) != self.dimensions:
            raise AssetRAGError("dense vector dimensions mismatch")
        if not self.source_hash:
            raise AssetRAGError("dense vector requires source_hash")


def _dense_vector_for_document(document: AssetRAGDocument) -> AssetRAGDenseVector:
    text = _dense_text_for_document(document)
    source_hash = content_hash(
        {
            "document_id": document.document_id,
            "source_id": document.source_id,
            "version": document.version,
            "projection": document.projection_value,
            "asset_ref": document.asset_ref,
            "text": text,
        }
    )
    vector = _dense_embedding(text)
    return AssetRAGDenseVector(
        vector_ref="ragvec_" + content_hash(
            {
                "document_id": document.document_id,
                "source_hash": source_hash,
                "embedding_model_ref": DENSE_EMBEDDING_MODEL_REF,
                "dimensions": DENSE_EMBEDDING_DIMENSIONS,
            }
        ),
        document_id=document.document_id,
        source_id=document.source_id,
        version=document.version,
        embedding_model_ref=DENSE_EMBEDDING_MODEL_REF,
        dimensions=DENSE_EMBEDDING_DIMENSIONS,
        vector=vector,
        source_hash=source_hash,
    )


def _document_to_json(document: AssetRAGDocument) -> dict[str, Any]:
    return _json_value(document)


def _document_from_json(value: dict[str, Any]) -> AssetRAGDocument:
    raw = dict(value)
    permission = raw.get("permission")
    if not isinstance(permission, dict):
        raise AssetRAGError("persisted RAG document missing permission")
    raw["permission"] = RAGPermission(**permission)
    return AssetRAGDocument(**raw)


def _usage_to_json(usage: AgentRAGUsage) -> dict[str, Any]:
    return _json_value(usage)


def _usage_from_json(value: dict[str, Any]) -> AgentRAGUsage:
    raw = dict(value)
    raw.setdefault("user_id", "")
    return AgentRAGUsage(**raw)


def _dense_vector_to_json(vector: AssetRAGDenseVector) -> dict[str, Any]:
    return _json_value(vector)


def _dense_vector_from_json(value: dict[str, Any]) -> AssetRAGDenseVector:
    return AssetRAGDenseVector(**dict(value))


def _reject_plaintext_secret(body: str, metadata: dict[str, Any]) -> None:
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.search(body or ""):
            raise AssetRAGError("RAG document body appears to contain plaintext secret material")

    def visit(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for raw_key, value in obj.items():
                key = str(raw_key).lower()
                child_path = f"{path}.{key}" if path else key
                allowed_ref = any(part in key for part in _ALLOWED_REF_KEY_PARTS)
                forbidden = any(part in key for part in _FORBIDDEN_SECRET_KEY_PARTS)
                if forbidden and not allowed_ref and value not in (None, "", [], {}):
                    raise AssetRAGError(f"RAG metadata key {child_path!r} appears to contain plaintext credential")
                visit(value, child_path)
        elif isinstance(obj, list | tuple):
            for i, item in enumerate(obj):
                visit(item, f"{path}[{i}]")
        elif isinstance(obj, str):
            for pattern in _SECRET_VALUE_PATTERNS:
                if pattern.search(obj):
                    raise AssetRAGError("RAG metadata appears to contain plaintext secret material")

    visit(metadata or {})


class ResearchAssetRAGIndex:
    def __init__(self) -> None:
        self._docs: list[AssetRAGDocument] = []
        self._usage: list[AgentRAGUsage] = []
        self._dense_vectors: dict[str, AssetRAGDenseVector] = {}

    def add(self, document: AssetRAGDocument) -> None:
        self._docs.append(document)
        self._dense_vectors[document.document_id] = _dense_vector_for_document(document)

    def retrieve(
        self,
        query: str,
        *,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...] = (),
        top_k: int = 5,
    ) -> list[AssetRAGHit]:
        q = _tokens(query)
        if not q:
            return []
        projection_filter = {
            str(p.value if isinstance(p, Enum) else p)
            for p in projections
        }
        scored: list[tuple[float, AssetRAGDocument]] = []
        for doc in self._docs:
            if projection_filter and doc.projection_value not in projection_filter:
                continue
            if not _visible(doc, context):
                continue
            d_tokens = _tokens(" ".join([doc.title, doc.body, doc.applicability, doc.asset_ref]))
            overlap = len(q & d_tokens)
            if overlap == 0:
                continue
            score = overlap / max(len(q), 1)
            scored.append((score, doc))
        scored.sort(key=lambda item: (-item[0], item[1].source_id, item[1].version))
        return [_hit(doc, score) for score, doc in scored[:top_k]]

    def vector_search(
        self,
        query: str,
        *,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...] = (),
        top_k: int = 5,
    ) -> list[AssetRAGHit]:
        q = _token_counts(query)
        if not q:
            return []
        projection_filter = {
            str(p.value if isinstance(p, Enum) else p)
            for p in projections
        }
        scored: list[tuple[float, AssetRAGDocument]] = []
        for doc in self._docs:
            if projection_filter and doc.projection_value not in projection_filter:
                continue
            if not _visible(doc, context):
                continue
            text = " ".join([doc.title, doc.body, doc.applicability, doc.asset_ref, doc.source_kind])
            score = _cosine_similarity(q, _token_counts(text))
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda item: (-item[0], item[1].source_id, item[1].version))
        return [_hit(doc, score) for score, doc in scored[:top_k]]

    def dense_vector_search(
        self,
        query: str,
        *,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...] = (),
        top_k: int = 5,
    ) -> list[AssetRAGHit]:
        q = _dense_embedding(query)
        if not any(value != 0.0 for value in q):
            return []
        projection_filter = {
            str(p.value if isinstance(p, Enum) else p)
            for p in projections
        }
        scored: list[tuple[float, AssetRAGDocument]] = []
        for doc in self._docs:
            if projection_filter and doc.projection_value not in projection_filter:
                continue
            if not _visible(doc, context):
                continue
            vector = self._dense_vectors.get(doc.document_id)
            if vector is None:
                vector = _dense_vector_for_document(doc)
                self._dense_vectors[doc.document_id] = vector
            score = _dense_cosine_similarity(q, vector.vector)
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda item: (-item[0], item[1].source_id, item[1].version))
        return [_hit(doc, score) for score, doc in scored[:top_k]]

    def dense_vectors(self) -> list[AssetRAGDenseVector]:
        return list(self._dense_vectors.values())

    def record_agent_usage(
        self,
        *,
        agent_id: str,
        hit: AssetRAGHit,
        purpose: str,
        user_id: str = "",
    ) -> AgentRAGUsage:
        if not agent_id:
            raise AssetRAGError("agent_id is required")
        if not purpose:
            raise AssetRAGError("purpose is required")
        if not hit.source_id or not hit.version:
            raise AssetRAGError("agent usage requires hit source_id/version")
        usage = AgentRAGUsage(
            usage_id="raguse_" + content_hash(
                {
                    "agent_id": agent_id,
                    "user_id": user_id,
                    "source_id": hit.source_id,
                    "version": hit.version,
                    "asset_ref": hit.asset_ref,
                    "purpose": purpose,
                }
            ),
            agent_id=agent_id,
            user_id=user_id,
            source_id=hit.source_id,
            version=hit.version,
            asset_ref=hit.asset_ref,
            projection=hit.projection,
            purpose=purpose,
            timestamp=_now(),
        )
        self._usage.append(usage)
        return usage

    def agent_usage(
        self,
        *,
        source_id: str | None = None,
        asset_ref: str | None = None,
        user_id: str | None = None,
    ) -> list[AgentRAGUsage]:
        out = list(self._usage)
        if source_id is not None:
            out = [u for u in out if u.source_id == source_id]
        if asset_ref is not None:
            out = [u for u in out if u.asset_ref == asset_ref]
        if user_id is not None:
            out = [u for u in out if u.user_id == user_id]
        return out


class PersistentResearchAssetRAGIndex(ResearchAssetRAGIndex):
    """JSONL-backed Research Asset RAG event log.

    This keeps the contract deliberately simple: documents and agent usage are
    replayed from an append-only event file. Malformed persisted history raises
    instead of silently dropping context or usage evidence.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    def _load_existing(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    schema_version = row.get("schema_version")
                    event_type = row.get("event_type")
                    if schema_version != 1:
                        raise AssetRAGError("unsupported RAG index schema_version")
                    if event_type == "document_added":
                        super().add(_document_from_json(row.get("document") or {}))
                    elif event_type == "agent_usage_recorded":
                        self._usage.append(_usage_from_json(row.get("usage") or {}))
                    elif event_type == "dense_embedding_indexed":
                        vector = _dense_vector_from_json(row.get("dense_vector") or {})
                        self._dense_vectors[vector.document_id] = vector
                    else:
                        raise AssetRAGError(f"unknown RAG index event_type={event_type!r}")
                except Exception as exc:  # noqa: BLE001 - startup must expose the bad row location.
                    raise AssetRAGError(f"invalid persisted Research Asset RAG row at {self._path}:{line_no}") from exc

    def _append_event(self, row: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    def add(self, document: AssetRAGDocument) -> None:
        vector = _dense_vector_for_document(document)
        row = {
            "schema_version": 1,
            "event_type": "document_added",
            "document": _document_to_json(document),
        }
        super().add(document)
        self._dense_vectors[document.document_id] = vector
        self._append_event(row)
        self._append_event(
            {
                "schema_version": 1,
                "event_type": "dense_embedding_indexed",
                "dense_vector": _dense_vector_to_json(vector),
            }
        )

    def record_agent_usage(
        self,
        *,
        agent_id: str,
        hit: AssetRAGHit,
        purpose: str,
        user_id: str = "",
    ) -> AgentRAGUsage:
        usage = super().record_agent_usage(agent_id=agent_id, hit=hit, purpose=purpose, user_id=user_id)
        self._append_event(
            {
                "schema_version": 1,
                "event_type": "agent_usage_recorded",
                "usage": _usage_to_json(usage),
            }
        )
        return usage


def _visible(doc: AssetRAGDocument, ctx: RAGQueryContext) -> bool:
    perm = doc.permission
    if perm.allowed_users and ctx.user_id not in perm.allowed_users:
        return False
    if perm.allowed_desks and ctx.desk not in perm.allowed_desks:
        return False
    if doc.asset_ref not in ctx.visible_asset_refs:
        return False
    if perm.allowed_assets and doc.asset_ref not in perm.allowed_assets:
        return False
    if perm.permission_tags and not set(perm.permission_tags).issubset(set(ctx.permission_tags)):
        return False
    return True


def _hit(doc: AssetRAGDocument, score: float) -> AssetRAGHit:
    snippet = doc.body.strip().replace("\n", " ")
    if len(snippet) > 320:
        snippet = snippet[:317] + "..."
    return AssetRAGHit(
        source_id=doc.source_id,
        version=doc.version,
        timestamp=doc.timestamp,
        permission=doc.permission.snapshot(),
        applicability=doc.applicability,
        projection=doc.projection_value,
        asset_ref=doc.asset_ref,
        title=doc.title,
        snippet=snippet,
        score=score,
        evidence_label=doc.evidence_label,
    )


__all__ = [
    "AgentRAGUsage",
    "AssetRAGDocument",
    "AssetRAGDenseVector",
    "AssetRAGError",
    "AssetRAGHit",
    "DENSE_EMBEDDING_MODEL_REF",
    "RAGPermission",
    "RAGProjection",
    "RAGQueryContext",
    "PersistentResearchAssetRAGIndex",
    "ResearchAssetRAGIndex",
]
