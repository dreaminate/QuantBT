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
import os
import re
import threading
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from ..cross_process_lock import acquire_exclusive_fd
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
    document_id: str = ""

    def __post_init__(self) -> None:
        if not self.source_id or not self.version:
            raise AssetRAGError("RAG hit requires source_id and version")
        if self.context_role != "candidate_context":
            raise AssetRAGError("RAG hit must remain candidate_context, not system conclusion")


@dataclass(frozen=True)
class RAGUsageDocumentRef:
    document_id: str
    source_id: str
    version: str
    asset_ref: str
    projection: str
    permission: dict[str, tuple[str, ...]]
    context_role: str = "candidate_context"

    def __post_init__(self) -> None:
        for field_name in ("document_id", "source_id", "version", "asset_ref", "projection"):
            if not str(getattr(self, field_name) or "").strip():
                raise AssetRAGError(f"RAG usage document {field_name} is required")
        if self.context_role != "candidate_context":
            raise AssetRAGError("RAG usage documents must remain candidate_context")
        permission = self.permission
        if not isinstance(permission, dict):
            raise AssetRAGError("RAG usage document permission snapshot is required")
        object.__setattr__(
            self,
            "permission",
            {
                "allowed_users": _tuple(permission.get("allowed_users")),
                "allowed_desks": _tuple(permission.get("allowed_desks")),
                "allowed_assets": _tuple(permission.get("allowed_assets")),
                "permission_tags": _tuple(permission.get("permission_tags")),
            },
        )


@dataclass(frozen=True)
class StrictAgentRAGUsage:
    usage_id: str
    owner_user_id: str
    agent_id: str
    workflow_ref: str
    tool_call_ref: str
    purpose: str
    query_digest: str
    context_digest: str
    desk: str
    actor: str
    visible_asset_refs: tuple[str, ...]
    permission_tags: tuple[str, ...]
    returned_documents: tuple[RAGUsageDocumentRef, ...]
    candidate_context_only: bool
    plaintext_secret_free: bool
    timestamp: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        for field_name in (
            "usage_id",
            "owner_user_id",
            "agent_id",
            "workflow_ref",
            "tool_call_ref",
            "purpose",
            "query_digest",
            "context_digest",
            "desk",
            "actor",
        ):
            if not str(getattr(self, field_name) or "").strip():
                raise AssetRAGError(f"strict RAG usage {field_name} is required")
        object.__setattr__(self, "visible_asset_refs", _tuple(self.visible_asset_refs))
        object.__setattr__(self, "permission_tags", _tuple(self.permission_tags))
        object.__setattr__(self, "returned_documents", tuple(self.returned_documents))
        if not self.returned_documents:
            raise AssetRAGError("strict RAG usage requires returned documents")
        if not self.candidate_context_only:
            raise AssetRAGError("strict RAG usage must remain candidate_context only")
        if not self.plaintext_secret_free:
            raise AssetRAGError("strict RAG usage cannot contain plaintext secrets")


@dataclass(frozen=True)
class RAGConformanceReceipt:
    usage_id: str
    owner_user_id: str
    workflow_ref: str
    tool_call_ref: str
    query_digest: str
    context_digest: str
    returned_document_ids: tuple[str, ...]
    visible_asset_refs: tuple[str, ...]
    candidate_context_only: bool
    plaintext_secret_free: bool
    accepted: bool
    violations: tuple[str, ...] = ()


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


def _document_identity_payload(document: AssetRAGDocument) -> dict[str, Any]:
    return {
        "source_id": document.source_id,
        "version": document.version,
        "title": document.title,
        "asset_ref": document.asset_ref,
        "projection": document.projection_value,
        "body": document.body,
        "permission": document.permission.snapshot(),
        "applicability": document.applicability,
        "source_kind": document.source_kind,
        "metadata": document.metadata,
        "evidence_label": document.evidence_label,
        "methodology_path": document.methodology_path,
    }


def _expected_document_id(document: AssetRAGDocument) -> str:
    return "ragdoc_" + content_hash(
        {
            "source_id": document.source_id,
            "version": document.version,
            "asset_ref": document.asset_ref,
            "projection": document.projection_value,
            "body": document.body,
        }
    )


def _same_document_semantics(left: AssetRAGDocument, right: AssetRAGDocument) -> bool:
    return _document_identity_payload(left) == _document_identity_payload(right)


def _vector_identity_payload(vector: AssetRAGDenseVector) -> dict[str, Any]:
    return {
        "vector_ref": vector.vector_ref,
        "document_id": vector.document_id,
        "source_id": vector.source_id,
        "version": vector.version,
        "embedding_model_ref": vector.embedding_model_ref,
        "dimensions": vector.dimensions,
        "vector": vector.vector,
        "source_hash": vector.source_hash,
    }


def _same_vector_semantics(left: AssetRAGDenseVector, right: AssetRAGDenseVector) -> bool:
    return _vector_identity_payload(left) == _vector_identity_payload(right)


def _strict_usage_to_json(usage: StrictAgentRAGUsage) -> dict[str, Any]:
    return _json_value(usage)


def _strict_usage_from_json(value: dict[str, Any]) -> StrictAgentRAGUsage:
    raw = dict(value)
    returned = raw.get("returned_documents")
    if not isinstance(returned, list):
        raise AssetRAGError("strict persisted RAG usage missing returned_documents")
    if any(not isinstance(item, dict) for item in returned):
        raise AssetRAGError("strict persisted RAG usage has invalid document refs")
    raw["returned_documents"] = tuple(
        RAGUsageDocumentRef(**dict(item)) for item in returned
    )
    return StrictAgentRAGUsage(**raw)


def _document_family(document: AssetRAGDocument) -> tuple[str, str, str]:
    return (document.source_id, document.asset_ref, document.projection_value)


def _context_payload(*, owner_user_id: str, context: RAGQueryContext) -> dict[str, Any]:
    return {
        "owner_user_id": owner_user_id,
        "user_id": context.user_id,
        "desk": context.desk,
        "visible_asset_refs": context.visible_asset_refs,
        "permission_tags": context.permission_tags,
        "actor": context.actor,
    }


def _strict_usage_identity_payload(usage: StrictAgentRAGUsage) -> dict[str, Any]:
    return {
        "owner_user_id": usage.owner_user_id,
        "agent_id": usage.agent_id,
        "workflow_ref": usage.workflow_ref,
        "tool_call_ref": usage.tool_call_ref,
        "purpose": usage.purpose,
        "query_digest": usage.query_digest,
        "context_digest": usage.context_digest,
        "desk": usage.desk,
        "actor": usage.actor,
        "visible_asset_refs": usage.visible_asset_refs,
        "permission_tags": usage.permission_tags,
        "returned_documents": tuple(_json_value(item) for item in usage.returned_documents),
        "candidate_context_only": usage.candidate_context_only,
        "plaintext_secret_free": usage.plaintext_secret_free,
    }


def _expected_strict_usage_id(usage: StrictAgentRAGUsage) -> str:
    return "raguse_v2_" + content_hash(_strict_usage_identity_payload(usage))


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
        self._owned_documents: dict[tuple[str, str], AssetRAGDocument] = {}
        self._owned_vectors: dict[tuple[str, str], AssetRAGDenseVector] = {}
        self._owned_current: dict[tuple[str, str, str, str], str] = {}
        self._owned_source_versions: dict[tuple[str, str, str], str] = {}
        self._strict_usage: dict[tuple[str, str], StrictAgentRAGUsage] = {}

    @staticmethod
    def _owner(value: Any) -> str:
        owner = str(value or "").strip()
        if not owner:
            raise AssetRAGError("RAG owner_user_id is required")
        return owner

    def add(self, document: AssetRAGDocument) -> None:
        self._docs.append(document)
        self._dense_vectors[document.document_id] = _dense_vector_for_document(document)

    def _apply_owned_document(
        self,
        document: AssetRAGDocument,
        *,
        owner_user_id: str,
        supersedes_document_id: str | None,
        load_compatibility: bool,
    ) -> AssetRAGDocument:
        owner = self._owner(owner_user_id)
        if document.document_id != _expected_document_id(document):
            raise AssetRAGError("owner-scoped RAG document_id does not match canonical content")
        if owner not in document.permission.allowed_users:
            raise AssetRAGError(
                "owner-scoped RAG permission must explicitly include owner_user_id"
            )
        key = (owner, document.document_id)
        family_key = (owner, *_document_family(document))
        version_key = (owner, document.source_id, document.version)
        current_id = self._owned_current.get(family_key)
        existing = self._owned_documents.get(key)
        if existing is not None:
            if not _same_document_semantics(existing, document):
                raise AssetRAGError("owner/document identity collision with different content")
            if current_id != document.document_id:
                raise AssetRAGError("superseded RAG document version cannot become current again")
            return existing
        version_document_id = self._owned_source_versions.get(version_key)
        if version_document_id is not None and version_document_id != document.document_id:
            raise AssetRAGError("owner/source/version identity collision")
        supersedes = str(supersedes_document_id or "").strip()
        if current_id is None:
            if supersedes:
                raise AssetRAGError("first owner-scoped RAG document cannot supersede an unknown version")
        elif supersedes != current_id:
            raise AssetRAGError("RAG document update must supersede the exact current document_id")
        vector = _dense_vector_for_document(document)
        self._owned_documents[key] = document
        self._owned_vectors[key] = vector
        self._owned_current[family_key] = document.document_id
        self._owned_source_versions[version_key] = document.document_id
        if load_compatibility and not any(
            existing_document.document_id == document.document_id
            for existing_document in self._docs
        ):
            ResearchAssetRAGIndex.add(self, document)
        return document

    def add_for_owner(
        self,
        document: AssetRAGDocument,
        *,
        owner_user_id: str,
        supersedes_document_id: str | None = None,
    ) -> AssetRAGDocument:
        """Add one schema-v2-capable owner version to the in-memory index.

        Ownership is an explicit envelope. ``permission.allowed_users`` remains
        a visibility list and is never treated as the ownership source.
        """

        return self._apply_owned_document(
            document,
            owner_user_id=owner_user_id,
            supersedes_document_id=supersedes_document_id,
            load_compatibility=True,
        )

    def document_for_owner(
        self,
        document_id: str,
        *,
        owner_user_id: str,
        require_current: bool = False,
    ) -> AssetRAGDocument:
        owner = self._owner(owner_user_id)
        document = self._owned_documents[(owner, str(document_id or ""))]
        if require_current:
            current_id = self._owned_current[(owner, *_document_family(document))]
            if current_id != document.document_id:
                raise AssetRAGError("RAG document is superseded")
        return document

    def dense_vector_for_owner(
        self,
        document_id: str,
        *,
        owner_user_id: str,
        require_current: bool = False,
    ) -> AssetRAGDenseVector:
        document = self.document_for_owner(
            document_id,
            owner_user_id=owner_user_id,
            require_current=require_current,
        )
        return self._owned_vectors[(self._owner(owner_user_id), document.document_id)]

    def current_document_for_owner(
        self,
        *,
        owner_user_id: str,
        source_id: str,
        asset_ref: str,
        projection: RAGProjection | str,
    ) -> AssetRAGDocument:
        owner = self._owner(owner_user_id)
        projection_value = str(projection.value if isinstance(projection, Enum) else projection)
        document_id = self._owned_current[(owner, str(source_id), str(asset_ref), projection_value)]
        return self._owned_documents[(owner, document_id)]

    def owned_documents(self, *, owner_user_id: str, current_only: bool = False) -> list[AssetRAGDocument]:
        owner = self._owner(owner_user_id)
        documents = [
            document
            for (record_owner, _document_id), document in self._owned_documents.items()
            if record_owner == owner
        ]
        if current_only:
            current_ids = {
                document_id
                for (record_owner, *_family), document_id in self._owned_current.items()
                if record_owner == owner
            }
            documents = [document for document in documents if document.document_id in current_ids]
        return sorted(documents, key=lambda item: (item.source_id, item.version, item.document_id))

    def _strict_context(self, *, owner_user_id: str, context: RAGQueryContext) -> str:
        owner = self._owner(owner_user_id)
        if context.user_id != owner:
            raise AssetRAGError("RAG query context user_id must match stable owner_user_id")
        return owner

    def _current_owned_documents(self, owner: str) -> list[AssetRAGDocument]:
        current_ids = {
            document_id
            for (record_owner, *_family), document_id in self._owned_current.items()
            if record_owner == owner
        }
        return [
            document
            for (record_owner, document_id), document in self._owned_documents.items()
            if record_owner == owner and document_id in current_ids
        ]

    def _search_for_owner(
        self,
        query: str,
        *,
        owner_user_id: str,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...],
        top_k: int,
        mode: str,
    ) -> list[AssetRAGHit]:
        owner = self._strict_context(owner_user_id=owner_user_id, context=context)
        _reject_plaintext_secret(query, {})
        if top_k <= 0:
            return []
        projection_filter = {
            str(projection.value if isinstance(projection, Enum) else projection)
            for projection in projections
        }
        query_tokens = _tokens(query)
        query_counts = _token_counts(query)
        query_dense = _dense_embedding(query)
        if mode == "lexical" and not query_tokens:
            return []
        if mode == "sparse" and not query_counts:
            return []
        if mode == "dense" and not any(value != 0.0 for value in query_dense):
            return []
        scored: list[tuple[float, AssetRAGDocument]] = []
        for document in self._current_owned_documents(owner):
            if projection_filter and document.projection_value not in projection_filter:
                continue
            if not _visible(document, context):
                continue
            text = " ".join(
                [
                    document.title,
                    document.body,
                    document.applicability,
                    document.asset_ref,
                    document.source_kind,
                ]
            )
            if mode == "lexical":
                overlap = len(query_tokens & _tokens(text))
                score = overlap / max(len(query_tokens), 1)
            elif mode == "sparse":
                score = _cosine_similarity(query_counts, _token_counts(text))
            elif mode == "dense":
                vector = self._owned_vectors.get((owner, document.document_id))
                if vector is None or not _same_vector_semantics(
                    vector, _dense_vector_for_document(document)
                ):
                    raise AssetRAGError("owner-scoped RAG vector/document mismatch")
                score = _dense_cosine_similarity(query_dense, vector.vector)
            else:  # pragma: no cover - private caller pins the three modes.
                raise AssetRAGError(f"unsupported strict RAG search mode: {mode}")
            if score > 0:
                scored.append((score, document))
        scored.sort(key=lambda item: (-item[0], item[1].source_id, item[1].version))
        return [_hit(document, score) for score, document in scored[:top_k]]

    def retrieve_for_owner(
        self,
        query: str,
        *,
        owner_user_id: str,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...] = (),
        top_k: int = 5,
    ) -> list[AssetRAGHit]:
        return self._search_for_owner(
            query,
            owner_user_id=owner_user_id,
            context=context,
            projections=projections,
            top_k=top_k,
            mode="lexical",
        )

    def vector_search_for_owner(
        self,
        query: str,
        *,
        owner_user_id: str,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...] = (),
        top_k: int = 5,
    ) -> list[AssetRAGHit]:
        return self._search_for_owner(
            query,
            owner_user_id=owner_user_id,
            context=context,
            projections=projections,
            top_k=top_k,
            mode="sparse",
        )

    def dense_vector_search_for_owner(
        self,
        query: str,
        *,
        owner_user_id: str,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...] = (),
        top_k: int = 5,
    ) -> list[AssetRAGHit]:
        return self._search_for_owner(
            query,
            owner_user_id=owner_user_id,
            context=context,
            projections=projections,
            top_k=top_k,
            mode="dense",
        )

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

    def _apply_strict_usage(
        self,
        usage: StrictAgentRAGUsage,
        *,
        owner_user_id: str,
    ) -> StrictAgentRAGUsage:
        owner = self._owner(owner_user_id)
        if usage.owner_user_id != owner:
            raise AssetRAGError("strict RAG usage owner envelope mismatch")
        if usage.usage_id != _expected_strict_usage_id(usage):
            raise AssetRAGError("strict RAG usage_id does not match canonical content")
        key = (owner, usage.usage_id)
        existing = self._strict_usage.get(key)
        if existing is not None:
            if _strict_usage_identity_payload(existing) != _strict_usage_identity_payload(usage):
                raise AssetRAGError("owner/usage identity collision with different content")
            return existing
        self._strict_usage[key] = usage
        return usage

    def record_usage_for_owner(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        workflow_ref: str,
        tool_call_ref: str,
        query: str,
        context: RAGQueryContext,
        hits: tuple[AssetRAGHit, ...] | list[AssetRAGHit],
        purpose: str,
    ) -> StrictAgentRAGUsage:
        owner = self._strict_context(owner_user_id=owner_user_id, context=context)
        if context.actor != "agent":
            raise AssetRAGError("strict RAG usage requires actor='agent'")
        for value in (agent_id, workflow_ref, tool_call_ref, purpose, query):
            _reject_plaintext_secret(str(value or ""), {})
        returned_documents: list[RAGUsageDocumentRef] = []
        seen_document_ids: set[str] = set()
        for hit in tuple(hits):
            if not hit.document_id:
                raise AssetRAGError("strict RAG usage hit requires document_id")
            if hit.document_id in seen_document_ids:
                raise AssetRAGError("strict RAG usage contains duplicate document_id")
            seen_document_ids.add(hit.document_id)
            document = self.document_for_owner(
                hit.document_id,
                owner_user_id=owner,
                require_current=True,
            )
            expected_hit = _hit(document, hit.score)
            if (
                hit.source_id != expected_hit.source_id
                or hit.version != expected_hit.version
                or hit.asset_ref != expected_hit.asset_ref
                or hit.projection != expected_hit.projection
                or hit.permission != expected_hit.permission
                or hit.context_role != "candidate_context"
            ):
                raise AssetRAGError("strict RAG usage hit does not match current owner document")
            if not _visible(document, context):
                raise AssetRAGError("strict RAG usage hit is not visible in the exact query context")
            vector = self._owned_vectors.get((owner, document.document_id))
            if vector is None or not _same_vector_semantics(
                vector, _dense_vector_for_document(document)
            ):
                raise AssetRAGError("owner-scoped RAG vector/document mismatch")
            _reject_plaintext_secret(document.body, document.metadata)
            returned_documents.append(
                RAGUsageDocumentRef(
                    document_id=document.document_id,
                    source_id=document.source_id,
                    version=document.version,
                    asset_ref=document.asset_ref,
                    projection=document.projection_value,
                    permission=document.permission.snapshot(),
                )
            )
        if not returned_documents:
            raise AssetRAGError("strict RAG usage requires at least one hit")
        query_digest = "ragquery_" + content_hash({"query": query})
        context_digest = "ragctx_" + content_hash(
            _context_payload(owner_user_id=owner, context=context)
        )
        provisional = StrictAgentRAGUsage(
            usage_id="pending",
            owner_user_id=owner,
            agent_id=str(agent_id or "").strip(),
            workflow_ref=str(workflow_ref or "").strip(),
            tool_call_ref=str(tool_call_ref or "").strip(),
            purpose=str(purpose or "").strip(),
            query_digest=query_digest,
            context_digest=context_digest,
            desk=context.desk,
            actor=context.actor,
            visible_asset_refs=context.visible_asset_refs,
            permission_tags=context.permission_tags,
            returned_documents=tuple(returned_documents),
            candidate_context_only=True,
            plaintext_secret_free=True,
        )
        usage = StrictAgentRAGUsage(
            **{
                **asdict(provisional),
                "usage_id": _expected_strict_usage_id(provisional),
                "returned_documents": provisional.returned_documents,
            }
        )
        return self._apply_strict_usage(usage, owner_user_id=owner)

    def strict_usage_for_owner(
        self,
        usage_id: str,
        *,
        owner_user_id: str,
    ) -> StrictAgentRAGUsage:
        return self._strict_usage[(self._owner(owner_user_id), str(usage_id or ""))]

    def strict_usage_records(self, *, owner_user_id: str) -> list[StrictAgentRAGUsage]:
        owner = self._owner(owner_user_id)
        return sorted(
            (
                usage
                for (record_owner, _usage_id), usage in self._strict_usage.items()
                if record_owner == owner
            ),
            key=lambda item: (item.timestamp, item.usage_id),
        )

    def validate_current_usage(
        self,
        usage_id: str,
        *,
        owner_user_id: str,
    ) -> RAGConformanceReceipt:
        owner = self._owner(owner_user_id)
        usage = self.strict_usage_for_owner(usage_id, owner_user_id=owner)
        violations: list[str] = []
        if usage.owner_user_id != owner:
            violations.append("rag_usage_owner_mismatch")
        if usage.usage_id != _expected_strict_usage_id(usage):
            violations.append("rag_usage_identity_mismatch")
        context = RAGQueryContext(
            user_id=owner,
            desk=usage.desk,
            visible_asset_refs=usage.visible_asset_refs,
            permission_tags=usage.permission_tags,
            actor=usage.actor,
        )
        if usage.context_digest != "ragctx_" + content_hash(
            _context_payload(owner_user_id=owner, context=context)
        ):
            violations.append("rag_usage_context_digest_mismatch")
        if not usage.query_digest.startswith("ragquery_"):
            violations.append("rag_usage_query_digest_missing")
        if usage.actor != "agent":
            violations.append("rag_usage_actor_not_agent")
        if not usage.candidate_context_only:
            violations.append("rag_usage_not_candidate_context")
        if not usage.plaintext_secret_free:
            violations.append("rag_usage_plaintext_secret_flag")
        try:
            _reject_plaintext_secret(
                " ".join(
                    [usage.agent_id, usage.workflow_ref, usage.tool_call_ref, usage.purpose]
                ),
                {},
            )
        except AssetRAGError:
            violations.append("rag_usage_plaintext_secret")
        for returned in usage.returned_documents:
            try:
                document = self.document_for_owner(
                    returned.document_id,
                    owner_user_id=owner,
                    require_current=True,
                )
            except (KeyError, AssetRAGError):
                violations.append(f"rag_usage_document_not_current:{returned.document_id}")
                continue
            if (
                returned.source_id != document.source_id
                or returned.version != document.version
                or returned.asset_ref != document.asset_ref
                or returned.projection != document.projection_value
                or returned.permission != document.permission.snapshot()
            ):
                violations.append(f"rag_usage_document_mismatch:{returned.document_id}")
            if returned.context_role != "candidate_context":
                violations.append(f"rag_usage_context_role_mismatch:{returned.document_id}")
            if not _visible(document, context):
                violations.append(f"rag_usage_permission_drift:{returned.document_id}")
            vector = self._owned_vectors.get((owner, document.document_id))
            if vector is None or not _same_vector_semantics(
                vector, _dense_vector_for_document(document)
            ):
                violations.append(f"rag_usage_vector_mismatch:{returned.document_id}")
            try:
                _reject_plaintext_secret(document.body, document.metadata)
            except AssetRAGError:
                violations.append(f"rag_usage_document_plaintext_secret:{returned.document_id}")
        deduped = tuple(dict.fromkeys(violations))
        return RAGConformanceReceipt(
            usage_id=usage.usage_id,
            owner_user_id=owner,
            workflow_ref=usage.workflow_ref,
            tool_call_ref=usage.tool_call_ref,
            query_digest=usage.query_digest,
            context_digest=usage.context_digest,
            returned_document_ids=tuple(
                returned.document_id for returned in usage.returned_documents
            ),
            visible_asset_refs=usage.visible_asset_refs,
            candidate_context_only=usage.candidate_context_only,
            plaintext_secret_free=usage.plaintext_secret_free,
            accepted=not deduped,
            violations=deduped,
        )


class PersistentResearchAssetRAGIndex(ResearchAssetRAGIndex):
    """JSONL-backed Research Asset RAG event log.

    Schema-v1 rows remain structurally readable for compatibility, but are
    counted as quarantined and never enter owner-scoped proof maps. Schema-v2
    rows carry an explicit stable owner envelope and atomically bind each
    document to its dense vector or each retrieval to its strict usage record.
    """

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._state_lock = threading.RLock()
        self._legacy_quarantined_count = 0
        self._load_existing()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def legacy_quarantined_count(self) -> int:
        return self._legacy_quarantined_count

    def refresh(self) -> None:
        with self._state_lock:
            ResearchAssetRAGIndex.__init__(self)
            self._legacy_quarantined_count = 0
            self._load_existing()

    def _apply_persisted_v2_row(self, row: dict[str, Any]) -> None:
        owner = self._owner(row.get("owner_user_id"))
        event_type = row.get("event_type")
        if event_type == "owner_document_version_recorded":
            raw_document = row.get("document")
            raw_vector = row.get("dense_vector")
            if not isinstance(raw_document, dict) or not isinstance(raw_vector, dict):
                raise AssetRAGError("schema-v2 RAG document event requires document and vector")
            document = _document_from_json(raw_document)
            vector = _dense_vector_from_json(raw_vector)
            expected_vector = _dense_vector_for_document(document)
            if not _same_vector_semantics(vector, expected_vector):
                raise AssetRAGError("persisted owner-scoped RAG vector/document mismatch")
            stored = self._apply_owned_document(
                document,
                owner_user_id=owner,
                supersedes_document_id=row.get("supersedes_document_id"),
                load_compatibility=True,
            )
            self._owned_vectors[(owner, stored.document_id)] = vector
            return
        if event_type == "owner_usage_recorded":
            raw_usage = row.get("usage")
            if not isinstance(raw_usage, dict):
                raise AssetRAGError("schema-v2 RAG usage event requires usage")
            usage = self._apply_strict_usage(
                _strict_usage_from_json(raw_usage),
                owner_user_id=owner,
            )
            receipt = ResearchAssetRAGIndex.validate_current_usage(
                self,
                usage.usage_id,
                owner_user_id=owner,
            )
            if not receipt.accepted:
                raise AssetRAGError(
                    "persisted strict RAG usage is not conformant: "
                    + ",".join(receipt.violations)
                )
            return
        raise AssetRAGError(f"unknown schema-v2 RAG event_type={event_type!r}")

    def _apply_legacy_row(self, row: dict[str, Any]) -> None:
        event_type = row.get("event_type")
        if event_type == "document_added":
            ResearchAssetRAGIndex.add(self, _document_from_json(row.get("document") or {}))
        elif event_type == "agent_usage_recorded":
            self._usage.append(_usage_from_json(row.get("usage") or {}))
        elif event_type == "dense_embedding_indexed":
            vector = _dense_vector_from_json(row.get("dense_vector") or {})
            self._dense_vectors[vector.document_id] = vector
        else:
            raise AssetRAGError(f"unknown legacy RAG index event_type={event_type!r}")

    def _load_existing(self) -> None:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            self._load_existing_unlocked()
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    def _load_existing_unlocked(self) -> None:
        if not self._path.exists():
            return
        with self._path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    schema_version = row.get("schema_version")
                    if schema_version == 1:
                        self._legacy_quarantined_count += 1
                        self._apply_legacy_row(row)
                    elif schema_version == 2:
                        self._apply_persisted_v2_row(row)
                    else:
                        raise AssetRAGError("unsupported RAG index schema_version")
                except Exception as exc:  # noqa: BLE001 - startup must expose the bad row location.
                    raise AssetRAGError(f"invalid persisted Research Asset RAG row at {self._path}:{line_no}") from exc

    @staticmethod
    def _v2_identity(row: dict[str, Any]) -> tuple[str, str, str] | None:
        if row.get("schema_version") != 2:
            return None
        owner = str(row.get("owner_user_id") or "")
        if row.get("event_type") == "owner_document_version_recorded":
            document = row.get("document")
            if isinstance(document, dict):
                return (owner, "document", str(document.get("document_id") or ""))
        if row.get("event_type") == "owner_usage_recorded":
            usage = row.get("usage")
            if isinstance(usage, dict):
                return (owner, "usage", str(usage.get("usage_id") or ""))
        return None

    @staticmethod
    def _same_v2_identity_semantics(left: dict[str, Any], right: dict[str, Any]) -> bool:
        event_type = left.get("event_type")
        if event_type != right.get("event_type"):
            return False
        if event_type == "owner_document_version_recorded":
            left_document = _document_from_json(left.get("document") or {})
            right_document = _document_from_json(right.get("document") or {})
            left_vector = _dense_vector_from_json(left.get("dense_vector") or {})
            right_vector = _dense_vector_from_json(right.get("dense_vector") or {})
            return (
                _same_document_semantics(left_document, right_document)
                and _same_vector_semantics(left_vector, right_vector)
                and str(left.get("supersedes_document_id") or "")
                == str(right.get("supersedes_document_id") or "")
            )
        if event_type == "owner_usage_recorded":
            left_usage = _strict_usage_from_json(left.get("usage") or {})
            right_usage = _strict_usage_from_json(right.get("usage") or {})
            return _strict_usage_identity_payload(left_usage) == _strict_usage_identity_payload(
                right_usage
            )
        return False

    def _strict_shadow_from_disk(self, rows: list[dict[str, Any]]) -> ResearchAssetRAGIndex:
        shadow = ResearchAssetRAGIndex()
        for row in rows:
            if row.get("schema_version") != 2:
                continue
            owner = shadow._owner(row.get("owner_user_id"))
            if row.get("event_type") == "owner_document_version_recorded":
                document = _document_from_json(row.get("document") or {})
                vector = _dense_vector_from_json(row.get("dense_vector") or {})
                if not _same_vector_semantics(vector, _dense_vector_for_document(document)):
                    raise AssetRAGError("persisted owner-scoped RAG vector/document mismatch")
                shadow._apply_owned_document(
                    document,
                    owner_user_id=owner,
                    supersedes_document_id=row.get("supersedes_document_id"),
                    load_compatibility=False,
                )
                shadow._owned_vectors[(owner, document.document_id)] = vector
            elif row.get("event_type") == "owner_usage_recorded":
                usage = shadow._apply_strict_usage(
                    _strict_usage_from_json(row.get("usage") or {}),
                    owner_user_id=owner,
                )
                receipt = shadow.validate_current_usage(usage.usage_id, owner_user_id=owner)
                if not receipt.accepted:
                    raise AssetRAGError(
                        "persisted strict RAG usage is not conformant: "
                        + ",".join(receipt.violations)
                    )
            else:
                raise AssetRAGError("unsupported schema-v2 RAG event")
        return shadow

    def _append_event(self, row: dict[str, Any]) -> bool:
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        held = None
        try:
            os.chmod(self._lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
            rows: list[dict[str, Any]] = []
            if self._path.exists():
                for line_no, line in enumerate(
                    self._path.read_text(encoding="utf-8").splitlines(),
                    start=1,
                ):
                    if not line.strip():
                        continue
                    try:
                        parsed = json.loads(line)
                    except Exception as exc:  # noqa: BLE001
                        raise AssetRAGError(
                            f"invalid persisted Research Asset RAG row at {self._path}:{line_no}"
                        ) from exc
                    rows.append(parsed)
            incoming_identity = self._v2_identity(row)
            if incoming_identity is not None:
                shadow = self._strict_shadow_from_disk(rows)
                owner = self._owner(row.get("owner_user_id"))
                if row.get("event_type") == "owner_document_version_recorded":
                    shadow._apply_owned_document(
                        _document_from_json(row.get("document") or {}),
                        owner_user_id=owner,
                        supersedes_document_id=row.get("supersedes_document_id"),
                        load_compatibility=False,
                    )
                else:
                    usage = shadow._apply_strict_usage(
                        _strict_usage_from_json(row.get("usage") or {}),
                        owner_user_id=owner,
                    )
                    receipt = shadow.validate_current_usage(
                        usage.usage_id,
                        owner_user_id=owner,
                    )
                    if not receipt.accepted:
                        raise AssetRAGError(
                            "strict RAG usage is not current: "
                            + ",".join(receipt.violations)
                        )
                for line_no, existing in enumerate(rows, start=1):
                    if self._v2_identity(existing) != incoming_identity:
                        continue
                    if self._same_v2_identity_semantics(existing, row):
                        return False
                    raise AssetRAGError(
                        f"RAG {incoming_identity[1]} identity collision at {self._path}:{line_no}"
                    )
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    + "\n"
                )
                fh.flush()
                os.fsync(fh.fileno())
            directory_fd = os.open(self._path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return True
        finally:
            if held is not None:
                held.release()
            os.close(fd)

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

    def add_for_owner(
        self,
        document: AssetRAGDocument,
        *,
        owner_user_id: str,
        supersedes_document_id: str | None = None,
    ) -> AssetRAGDocument:
        owner = self._owner(owner_user_id)
        vector = _dense_vector_for_document(document)
        row = {
            "schema_version": 2,
            "event_type": "owner_document_version_recorded",
            "owner_user_id": owner,
            "supersedes_document_id": str(supersedes_document_id or ""),
            "document": _document_to_json(document),
            "dense_vector": _dense_vector_to_json(vector),
        }
        with self._state_lock:
            appended = self._append_event(row)
            self.refresh()
            stored = self.document_for_owner(document.document_id, owner_user_id=owner)
            if appended and not _same_document_semantics(stored, document):
                raise AssetRAGError("persisted owner-scoped RAG document changed after append")
            return stored

    def retrieve_for_owner(
        self,
        query: str,
        *,
        owner_user_id: str,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...] = (),
        top_k: int = 5,
    ) -> list[AssetRAGHit]:
        with self._state_lock:
            self.refresh()
            return ResearchAssetRAGIndex.retrieve_for_owner(
                self,
                query,
                owner_user_id=owner_user_id,
                context=context,
                projections=projections,
                top_k=top_k,
            )

    def vector_search_for_owner(
        self,
        query: str,
        *,
        owner_user_id: str,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...] = (),
        top_k: int = 5,
    ) -> list[AssetRAGHit]:
        with self._state_lock:
            self.refresh()
            return ResearchAssetRAGIndex.vector_search_for_owner(
                self,
                query,
                owner_user_id=owner_user_id,
                context=context,
                projections=projections,
                top_k=top_k,
            )

    def dense_vector_search_for_owner(
        self,
        query: str,
        *,
        owner_user_id: str,
        context: RAGQueryContext,
        projections: tuple[RAGProjection | str, ...] = (),
        top_k: int = 5,
    ) -> list[AssetRAGHit]:
        with self._state_lock:
            self.refresh()
            return ResearchAssetRAGIndex.dense_vector_search_for_owner(
                self,
                query,
                owner_user_id=owner_user_id,
                context=context,
                projections=projections,
                top_k=top_k,
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

    def record_usage_for_owner(
        self,
        *,
        owner_user_id: str,
        agent_id: str,
        workflow_ref: str,
        tool_call_ref: str,
        query: str,
        context: RAGQueryContext,
        hits: tuple[AssetRAGHit, ...] | list[AssetRAGHit],
        purpose: str,
    ) -> StrictAgentRAGUsage:
        owner = self._owner(owner_user_id)
        with self._state_lock:
            usage = ResearchAssetRAGIndex.record_usage_for_owner(
                self,
                owner_user_id=owner,
                agent_id=agent_id,
                workflow_ref=workflow_ref,
                tool_call_ref=tool_call_ref,
                query=query,
                context=context,
                hits=hits,
                purpose=purpose,
            )
            row = {
                "schema_version": 2,
                "event_type": "owner_usage_recorded",
                "owner_user_id": owner,
                "usage": _strict_usage_to_json(usage),
            }
            try:
                appended = self._append_event(row)
            except Exception:
                self.refresh()
                raise
            if not appended:
                self.refresh()
            return self.strict_usage_for_owner(usage.usage_id, owner_user_id=owner)

    def validate_current_usage(
        self,
        usage_id: str,
        *,
        owner_user_id: str,
    ) -> RAGConformanceReceipt:
        with self._state_lock:
            self.refresh()
            return ResearchAssetRAGIndex.validate_current_usage(
                self,
                usage_id,
                owner_user_id=owner_user_id,
            )


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
        document_id=doc.document_id,
    )


# ---------------------------------------------------------------------------
# Autosync producer helpers (GOAL §5 · C-S5-RAG-AUTOSYNC)
#
# These build the correct ``AssetRAGDocument`` projection from a factor / model
# / signal / strategy registry object so the registry write paths can index
# assets into the Research Asset RAG without hand-rolling document construction
# at every call site. main.py wires them at the registry write points
# (CENTER-SERIAL); the helpers themselves are pure and PARALLEL-SAFE — they do
# not touch the global index, only return a document for the caller to ``add``.
#
# Invariants kept (GOAL §5 / RULES.project safety):
# - every produced doc carries source_id / version / permission / applicability
#   (AssetRAGDocument.__post_init__ also stamps timestamp);
# - the projection tag is pinned per asset type (FactorRAG / ModelRAG /
#   SignalRAG / StrategyRAG); a wrong mapping is a correctness bug and is what
#   the autosync adversarial test sentinels;
# - the default permission is owner-scoped (allowed_users=(owner,)); retrieval
#   isolation can never silently widen, and an empty owner is rejected so a
#   document can never become world-readable by accident;
# - raw model artifact bytes and raw strategy source code are NOT copied into
#   the body — only refs/hashes — mirroring the QRO contracts that deliberately
#   keep those as hashes;
# - applicability marks every doc as candidate context, never a system verdict;
# - plaintext credentials are rejected by AssetRAGDocument.__post_init__.
# ---------------------------------------------------------------------------

REGISTRY_AUTOSYNC_DESKS: dict[RAGProjection, str] = {
    RAGProjection.FACTOR: "factor",
    RAGProjection.MODEL: "model",
    RAGProjection.SIGNAL: "signal",
    RAGProjection.STRATEGY: "strategy",
}

_CANDIDATE_CONTEXT = "candidate_context"


def _coerce_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _resolve_owner(obj: Any, owner: str | None, owner_attrs: tuple[str, ...]) -> str:
    """Owner used for permission scope; empty owner is a permission hole -> reject."""
    if owner is not None and str(owner).strip():
        return str(owner).strip()
    for attr in owner_attrs:
        candidate = _coerce_str(getattr(obj, attr, "")).strip()
        if candidate:
            return candidate
    raise AssetRAGError("registry RAG autosync requires a non-empty owner for permission scope")


def _registry_permission(
    *,
    owner: str,
    desk: str,
    asset_ref: str,
    permission: RAGPermission | None,
    permission_tags: tuple[str, ...],
) -> RAGPermission:
    if permission is not None:
        return permission
    return RAGPermission(
        allowed_users=(owner,),
        allowed_desks=(desk,),
        allowed_assets=(asset_ref,),
        permission_tags=permission_tags,
    )


def _build_registry_document(
    *,
    projection: RAGProjection,
    source_id: str,
    version: str,
    asset_ref: str,
    title: str,
    body: str,
    applicability: str,
    source_kind: str,
    owner: str,
    desk: str,
    permission: RAGPermission | None,
    permission_tags: tuple[str, ...],
    metadata: dict[str, Any],
    evidence_label: str,
    methodology_path: str | None,
) -> AssetRAGDocument:
    return AssetRAGDocument(
        source_id=source_id,
        version=version,
        title=title,
        body=body,
        projection=projection,
        asset_ref=asset_ref,
        permission=_registry_permission(
            owner=owner,
            desk=desk,
            asset_ref=asset_ref,
            permission=permission,
            permission_tags=permission_tags,
        ),
        applicability=applicability,
        source_kind=source_kind,
        metadata=metadata,
        evidence_label=evidence_label,
        methodology_path=methodology_path,
    )


def build_factor_rag_document(
    factor: Any,
    *,
    owner: str | None = None,
    version: str | None = None,
    asset_ref: str | None = None,
    desk: str | None = None,
    permission: RAGPermission | None = None,
    permission_tags: tuple[str, ...] = (),
    evidence_label: str = _CANDIDATE_CONTEXT,
    extra_metadata: dict[str, Any] | None = None,
) -> AssetRAGDocument:
    """FactorRAG projection from a factor registry object (e.g. factor_factory.registry.Factor).

    Reads (duck-typed) factor_id, version, formula, params, lifecycle_state,
    author, description. ``owner`` defaults to ``factor.author``. The formula is
    the searchable factor definition (GOAL §5 资产定义); params are stored as
    key names + a params_hash, never raw values (mirrors the factor QRO).
    """
    factor_id = _coerce_str(getattr(factor, "factor_id", "")).strip()
    if not factor_id:
        raise AssetRAGError("factor RAG autosync requires factor_id")
    resolved_version = _coerce_str(
        version if version is not None else getattr(factor, "version", "")
    ).strip()
    if not resolved_version:
        raise AssetRAGError("factor RAG autosync requires a version")
    formula = _coerce_str(getattr(factor, "formula", ""))
    description = _coerce_str(getattr(factor, "description", ""))
    lifecycle_state = _coerce_str(getattr(factor, "lifecycle_state", ""))
    params = getattr(factor, "params", {})
    params = params if isinstance(params, dict) else {}
    param_keys = sorted(str(k) for k in params)
    resolved_owner = _resolve_owner(factor, owner, ("author",))
    resolved_desk = desk or REGISTRY_AUTOSYNC_DESKS[RAGProjection.FACTOR]
    resolved_asset_ref = _coerce_str(asset_ref).strip() or f"factor:{factor_id}"
    body_bits = [f"Factor {factor_id} v{resolved_version}."]
    if formula:
        body_bits.append(f"Formula: {formula}.")
    if lifecycle_state:
        body_bits.append(f"Lifecycle: {lifecycle_state}.")
    if param_keys:
        body_bits.append("Params: " + ", ".join(param_keys) + ".")
    if description:
        body_bits.append(description)
    metadata: dict[str, Any] = {
        "factor_id": factor_id,
        "version": resolved_version,
        "lifecycle_state": lifecycle_state,
        "formula_hash": content_hash({"formula": formula}),
        "params_hash": content_hash({"params": params}),
        "param_keys": param_keys,
        "author": _coerce_str(getattr(factor, "author", "")),
        "created_at_utc": _coerce_str(getattr(factor, "created_at_utc", "")),
        "registry_source": "factor_registry",
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return _build_registry_document(
        projection=RAGProjection.FACTOR,
        source_id=f"factor:{factor_id}:v{resolved_version}",
        version=resolved_version,
        asset_ref=resolved_asset_ref,
        title=f"Factor {factor_id} v{resolved_version}",
        body=" ".join(body_bits).strip(),
        applicability="candidate factor definition; registration record, not alpha validation or a system verdict",
        source_kind="FactorRegistryEntry",
        owner=resolved_owner,
        desk=resolved_desk,
        permission=permission,
        permission_tags=permission_tags,
        metadata=metadata,
        evidence_label=evidence_label,
        methodology_path=None,
    )


def build_signal_rag_document(
    contract: Any,
    *,
    owner: str | None = None,
    version: str | None = None,
    asset_ref: str | None = None,
    desk: str | None = None,
    permission: RAGPermission | None = None,
    permission_tags: tuple[str, ...] = (),
    evidence_label: str = _CANDIDATE_CONTEXT,
    extra_metadata: dict[str, Any] | None = None,
) -> AssetRAGDocument:
    """SignalRAG projection from a signal contract object (factor_factory.signal_contract.SignalContract).

    Reads (duck-typed) signal_id, signal_ref, name, source_lib, model_ref,
    output_kind, horizon, leakage, author, description. The signal contract is
    content-addressed, so ``version`` defaults to its signal_id identity. The
    model body is referenced by model_ref only — it is never copied in.
    """
    signal_id = _coerce_str(getattr(contract, "signal_id", "")).strip()
    if not signal_id:
        raise AssetRAGError("signal RAG autosync requires signal_id")
    signal_ref = _coerce_str(getattr(contract, "signal_ref", "")).strip() or f"sig::{signal_id}"
    name = _coerce_str(getattr(contract, "name", ""))
    source_lib = _coerce_str(getattr(contract, "source_lib", ""))
    model_ref = _coerce_str(getattr(contract, "model_ref", ""))
    output_kind = _coerce_str(getattr(contract, "output_kind", ""))
    horizon = _coerce_str(getattr(contract, "horizon", ""))
    description = _coerce_str(getattr(contract, "description", ""))
    leakage = getattr(contract, "leakage", None)
    leakage_dict = leakage.to_dict() if hasattr(leakage, "to_dict") else {}
    leakage_declared = bool(
        leakage_dict.get("oof") and leakage_dict.get("purge") and leakage_dict.get("embargo")
    )
    resolved_version = _coerce_str(
        version if version is not None else getattr(contract, "version", "")
    ).strip() or signal_id
    resolved_owner = _resolve_owner(contract, owner, ("author",))
    resolved_desk = desk or REGISTRY_AUTOSYNC_DESKS[RAGProjection.SIGNAL]
    resolved_asset_ref = _coerce_str(asset_ref).strip() or signal_ref
    body_bits = [f"Signal contract {name or signal_id} [{source_lib or 'unspecified'}]."]
    if output_kind:
        body_bits.append(f"Output kind: {output_kind}.")
    if horizon:
        body_bits.append(f"Horizon: {horizon}.")
    if model_ref:
        body_bits.append(f"Model ref: {model_ref}.")
    if leakage_dict:
        body_bits.append(f"Leakage declared (oof/purge/embargo): {leakage_declared}.")
    if description:
        body_bits.append(description)
    metadata: dict[str, Any] = {
        "signal_id": signal_id,
        "signal_ref": signal_ref,
        "source_lib": source_lib,
        "model_ref": model_ref,
        "model_ref_hash": content_hash({"model_ref": model_ref}),
        "output_kind": output_kind,
        "horizon": horizon,
        "leakage": leakage_dict,
        "leakage_declared": leakage_declared,
        "author": _coerce_str(getattr(contract, "author", "")),
        "registry_source": "signal_contract_registry",
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return _build_registry_document(
        projection=RAGProjection.SIGNAL,
        source_id=signal_ref,
        version=resolved_version,
        asset_ref=resolved_asset_ref,
        title=f"Signal contract {name or signal_id}",
        body=" ".join(body_bits).strip(),
        applicability="candidate signal output contract; declares output kind only, not alpha proof or a system verdict",
        source_kind="SignalContract",
        owner=resolved_owner,
        desk=resolved_desk,
        permission=permission,
        permission_tags=permission_tags,
        metadata=metadata,
        evidence_label=evidence_label,
        methodology_path=None,
    )


def build_model_rag_document(
    passport: Any,
    *,
    owner: str | None = None,
    version: str | None = None,
    asset_ref: str | None = None,
    desk: str | None = None,
    permission: RAGPermission | None = None,
    permission_tags: tuple[str, ...] = (),
    evidence_label: str = _CANDIDATE_CONTEXT,
    extra_metadata: dict[str, Any] | None = None,
) -> AssetRAGDocument:
    """ModelRAG projection from a model governance passport (research_os.model_governance.ModelGovernancePassport).

    Reads (duck-typed) model_version_ref, passport_id, model_risk_tier,
    materiality, intended_use, prohibited_use, dataset_refs, feature_refs,
    label_refs, training_code_hash, validation_dossier_ref, target_runtime. The
    passport carries no owner field, so ``owner`` (the recording actor) MUST be
    supplied by the caller. Only refs/hashes are indexed — no artifact bytes.
    ``version`` defaults to the content-addressed passport_id.
    """
    model_version_ref = _coerce_str(getattr(passport, "model_version_ref", "")).strip()
    if not model_version_ref:
        raise AssetRAGError("model RAG autosync requires model_version_ref")
    passport_id = _coerce_str(getattr(passport, "passport_id", "")).strip()
    risk_tier = _coerce_str(getattr(passport, "model_risk_tier", ""))
    materiality = _coerce_str(getattr(passport, "materiality", ""))
    intended_use = _tuple(getattr(passport, "intended_use", ()))
    prohibited_use = _tuple(getattr(passport, "prohibited_use", ()))
    dataset_refs = _tuple(getattr(passport, "dataset_refs", ()))
    feature_refs = _tuple(getattr(passport, "feature_refs", ()))
    label_refs = _tuple(getattr(passport, "label_refs", ()))
    training_code_hash = _coerce_str(getattr(passport, "training_code_hash", ""))
    validation_dossier_ref = _coerce_str(getattr(passport, "validation_dossier_ref", ""))
    target_runtime = _coerce_str(getattr(passport, "target_runtime", ""))
    resolved_version = _coerce_str(version).strip() or passport_id or model_version_ref
    resolved_owner = _resolve_owner(passport, owner, ("owner",))
    resolved_desk = desk or REGISTRY_AUTOSYNC_DESKS[RAGProjection.MODEL]
    resolved_asset_ref = _coerce_str(asset_ref).strip() or model_version_ref
    body_bits = [f"Model governance passport for {model_version_ref}."]
    if risk_tier:
        body_bits.append(f"Risk tier: {risk_tier}.")
    if materiality:
        body_bits.append(f"Materiality: {materiality}.")
    if intended_use:
        body_bits.append("Intended use: " + "; ".join(intended_use) + ".")
    if prohibited_use:
        body_bits.append("Prohibited use: " + "; ".join(prohibited_use) + ".")
    if dataset_refs:
        body_bits.append("Datasets: " + ", ".join(dataset_refs) + ".")
    metadata: dict[str, Any] = {
        "model_version_ref": model_version_ref,
        "passport_id": passport_id,
        "model_risk_tier": risk_tier,
        "materiality": materiality,
        "intended_use": list(intended_use),
        "prohibited_use": list(prohibited_use),
        "dataset_refs": list(dataset_refs),
        "feature_refs": list(feature_refs),
        "label_refs": list(label_refs),
        "training_code_hash": training_code_hash,
        "validation_dossier_ref": validation_dossier_ref,
        "target_runtime": target_runtime,
        "registry_source": "model_governance_registry",
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return _build_registry_document(
        projection=RAGProjection.MODEL,
        source_id=model_version_ref,
        version=resolved_version,
        asset_ref=resolved_asset_ref,
        title=f"Model passport {model_version_ref}",
        body=" ".join(body_bits).strip(),
        applicability="candidate model governance passport; registration record, not validation sign-off or a system verdict",
        source_kind="ModelGovernancePassport",
        owner=resolved_owner,
        desk=resolved_desk,
        permission=permission,
        permission_tags=permission_tags,
        metadata=metadata,
        evidence_label=evidence_label,
        methodology_path=None,
    )


def build_strategy_rag_document(
    strategy: Any,
    *,
    owner: str | None = None,
    version: str | None = None,
    asset_ref: str | None = None,
    desk: str | None = None,
    permission: RAGPermission | None = None,
    permission_tags: tuple[str, ...] = (),
    evidence_label: str = _CANDIDATE_CONTEXT,
    extra_metadata: dict[str, Any] | None = None,
) -> AssetRAGDocument:
    """StrategyRAG projection from an IDE strategy draft (ide.service.StrategyFile).

    Reads (duck-typed) strategy_id, owner_username, name, asset_class,
    description, code, updated_at_utc, market_data_use_validation_refs. ``owner``
    defaults to ``strategy.owner_username``. Raw strategy source code is NEVER
    copied into the body — only a code_hash in metadata — mirroring the
    StrategyBook QRO. The human description/rationale IS indexed (GOAL §5).
    ``version`` defaults to updated_at_utc, then the code_hash.
    """
    strategy_id = _coerce_str(getattr(strategy, "strategy_id", "")).strip()
    if not strategy_id:
        raise AssetRAGError("strategy RAG autosync requires strategy_id")
    name = _coerce_str(getattr(strategy, "name", ""))
    asset_class = _coerce_str(getattr(strategy, "asset_class", ""))
    description = _coerce_str(getattr(strategy, "description", ""))
    code = _coerce_str(getattr(strategy, "code", ""))
    updated_at = _coerce_str(getattr(strategy, "updated_at_utc", ""))
    code_hash = content_hash({"code": code})
    resolved_version = _coerce_str(
        version if version is not None else getattr(strategy, "version", "")
    ).strip() or updated_at or code_hash
    resolved_owner = _resolve_owner(strategy, owner, ("owner_username", "owner", "author"))
    resolved_desk = desk or REGISTRY_AUTOSYNC_DESKS[RAGProjection.STRATEGY]
    resolved_asset_ref = _coerce_str(asset_ref).strip() or f"strategy:{strategy_id}"
    body_bits = [f"Strategy {name or strategy_id} ({asset_class or 'unspecified asset class'})."]
    if description:
        body_bits.append(description)
    metadata: dict[str, Any] = {
        "strategy_id": strategy_id,
        "asset_class": asset_class,
        "code_hash": code_hash,
        "description_hash": content_hash({"description": description}),
        "owner_username": _coerce_str(getattr(strategy, "owner_username", "")),
        "updated_at_utc": updated_at,
        "market_data_use_validation_refs": list(
            _tuple(getattr(strategy, "market_data_use_validation_refs", ()))
        ),
        "registry_source": "ide_strategy_registry",
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return _build_registry_document(
        projection=RAGProjection.STRATEGY,
        source_id=f"strategy:{strategy_id}",
        version=resolved_version,
        asset_ref=resolved_asset_ref,
        title=f"Strategy {name or strategy_id}",
        body=" ".join(body_bits).strip(),
        applicability="candidate strategy draft; saved registration record, not backtest evidence or a system verdict",
        source_kind="StrategyBookDraft",
        owner=resolved_owner,
        desk=resolved_desk,
        permission=permission,
        permission_tags=permission_tags,
        metadata=metadata,
        evidence_label=evidence_label,
        methodology_path=None,
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
    "RAGConformanceReceipt",
    "RAGUsageDocumentRef",
    "PersistentResearchAssetRAGIndex",
    "ResearchAssetRAGIndex",
    "StrictAgentRAGUsage",
    "REGISTRY_AUTOSYNC_DESKS",
    "build_factor_rag_document",
    "build_model_rag_document",
    "build_signal_rag_document",
    "build_strategy_rag_document",
]
