"""Agent Orchestrator · user 可见工作流事件投影（GOAL §7「可见事件类型」+「可见性边界」）。

GOAL §7 把 AgentOS 内部执行**投影**为 user 可见工作流：user 看到执行到哪一步、哪个 role agent、
调了哪些工具、读了哪些 RAG/source、产了哪些资产/diff、触发哪些验证、遇到什么失败、下一步是什么。

诚实点名（GOAL-FIRST·与卡面措辞的差异）：GOAL §7「可见事件类型」**逐条列了 24 个**事件名
（AgentPlanCreated … RunVerdictProduced）。卡面摘要写「23 可见事件」——按 GOAL-FIRST 以 GOAL 原文
为契约，这里**实现 24 个全集**（少实现一个 = 自造契约）。计数差异作为诚实残余上报中心。

LLM 相关那 5 枚（LLMRouteSelected / CredentialPoolSelected / LLMCallStarted / LLMCallFinished /
ProviderFallbackUsed）**不另造**——直接复用 LLM Gateway（A-AGENT-GW 已建）`gateway.py` 里的同名
常量与其 `LLMGatewayEvent` 数据，由本投影层 adopt 进统一事件流（单一源·防漂）。

可见性边界（GOAL §7）落地为两道结构门：
- secret plaintext 边界：投影事件序列化面若夹带在册明文 secret → 拒（复用 call_record 的扫描）。
- provider hidden chain-of-thought 边界：事件 data 禁带 `chain_of_thought` / `reasoning_raw` /
  `hidden_reasoning` / 明文 `api_key` 等键——只投影可审计的结构化元数据，绝不投影 provider 内部思维链。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from ...cross_process_lock import acquire_exclusive_fd
from ...lineage.ids import canonical_json, content_hash
from ...llm.call_record import scan_messages_for_secret
from ...llm.gateway import (
    EV_CALL_FINISHED,
    EV_CALL_STARTED,
    EV_CREDENTIAL_SELECTED,
    EV_FALLBACK_USED,
    EV_ROUTE_SELECTED,
    LLMGatewayEvent,
)

# ── GOAL §7「可见事件类型」全 24 枚（顺序照 GOAL 原文）──────────────────────────
EV_AGENT_PLAN_CREATED = "AgentPlanCreated"
EV_TODO_UPDATED = "TodoUpdated"
EV_ROLE_AGENT_DISPATCHED = "RoleAgentDispatched"
# —— 下 5 枚 = LLM Gateway 同名常量复用（单一源，import 自 gateway.py，不另立字符串）——
EV_LLM_ROUTE_SELECTED = EV_ROUTE_SELECTED
EV_LLM_CALL_STARTED = EV_CALL_STARTED
EV_LLM_CALL_FINISHED = EV_CALL_FINISHED
EV_CREDENTIAL_POOL_SELECTED = EV_CREDENTIAL_SELECTED
EV_PROVIDER_FALLBACK_USED = EV_FALLBACK_USED
# —— 工具 / 资产 / RAG ——
EV_TOOL_CALL_STARTED = "ToolCallStarted"
EV_TOOL_CALL_FINISHED = "ToolCallFinished"
EV_RAG_HIT_USED = "RagHitUsed"
EV_ASSET_READ = "AssetRead"
EV_ASSET_DIFF_CREATED = "AssetDiffCreated"
# —— canonical command / 图写入 ——
EV_CANONICAL_COMMAND_PROPOSED = "CanonicalCommandProposed"
EV_CANONICAL_COMMAND_APPLIED = "CanonicalCommandApplied"
# —— 验证 / 挑战 ——
EV_VALIDATION_STARTED = "ValidationStarted"
EV_VALIDATION_FINISHED = "ValidationFinished"
EV_VERIFIER_CHALLENGE_RAISED = "VerifierChallengeRaised"
# —— 交接 / 审批 ——
EV_DESK_HANDOFF_CREATED = "DeskHandoffCreated"
EV_APPROVAL_REQUESTED = "ApprovalRequested"
# —— 失败 / 修复 ——
EV_FAILURE_DETECTED = "FailureDetected"
EV_REPAIR_ATTEMPTED = "RepairAttempted"
# —— 产物 / 裁决 ——
EV_ARTIFACT_PRODUCED = "ArtifactProduced"
EV_RUN_VERDICT_PRODUCED = "RunVerdictProduced"

# GOAL §7 全集（24）——顺序与 GOAL 原文逐行对应；count == 24 是 import 期不变量（见下）。
VISIBLE_EVENT_KINDS: tuple[str, ...] = (
    EV_AGENT_PLAN_CREATED,
    EV_TODO_UPDATED,
    EV_ROLE_AGENT_DISPATCHED,
    EV_LLM_ROUTE_SELECTED,
    EV_LLM_CALL_STARTED,
    EV_LLM_CALL_FINISHED,
    EV_CREDENTIAL_POOL_SELECTED,
    EV_PROVIDER_FALLBACK_USED,
    EV_TOOL_CALL_STARTED,
    EV_TOOL_CALL_FINISHED,
    EV_RAG_HIT_USED,
    EV_ASSET_READ,
    EV_ASSET_DIFF_CREATED,
    EV_CANONICAL_COMMAND_PROPOSED,
    EV_CANONICAL_COMMAND_APPLIED,
    EV_VALIDATION_STARTED,
    EV_VALIDATION_FINISHED,
    EV_VERIFIER_CHALLENGE_RAISED,
    EV_DESK_HANDOFF_CREATED,
    EV_APPROVAL_REQUESTED,
    EV_FAILURE_DETECTED,
    EV_REPAIR_ATTEMPTED,
    EV_ARTIFACT_PRODUCED,
    EV_RUN_VERDICT_PRODUCED,
)
VISIBLE_EVENT_SET: frozenset[str] = frozenset(VISIBLE_EVENT_KINDS)

# import 期自检（fail-fast·非 assert·-O 不剥）：GOAL §7 列 24 枚，去重后必须仍是 24
# （任何复制粘贴重复 / 漏一枚都在此响亮失败，防「投影了 23 个就当全」）。
if len(VISIBLE_EVENT_SET) != 24 or len(VISIBLE_EVENT_KINDS) != 24:
    raise RuntimeError(
        f"VISIBLE_EVENT_KINDS 必须恰好覆盖 GOAL §7 列举的 24 枚可见事件"
        f"（实得 kinds={len(VISIBLE_EVENT_KINDS)} unique={len(VISIBLE_EVENT_SET)}）"
    )

# LLM Gateway 已产的 5 枚（投影层 adopt·不重造）。
GATEWAY_EVENT_KINDS: frozenset[str] = frozenset(
    {
        EV_LLM_ROUTE_SELECTED,
        EV_LLM_CALL_STARTED,
        EV_LLM_CALL_FINISHED,
        EV_CREDENTIAL_POOL_SELECTED,
        EV_PROVIDER_FALLBACK_USED,
    }
)

# 可见性边界（GOAL §7）：事件 data 绝不允许出现的键（provider 隐藏思维链 / 明文凭据面）。
FORBIDDEN_EVENT_KEYS: frozenset[str] = frozenset(
    {
        "chain_of_thought",
        "reasoning_raw",
        "hidden_reasoning",
        "raw_prompt",
        "prompt_plaintext",
        "api_key",
        "secret",
        "secret_plaintext",
        "token_plaintext",
    }
)


class EventProjectionError(RuntimeError):
    """事件投影撞可见性边界（夹带明文 secret / 投影了 provider 隐藏思维链）→ 拒（GOAL §7）。"""


class WorkflowEventIntegrityError(RuntimeError):
    """Durable workflow-event history is malformed, non-canonical, or tampered."""


@dataclass
class WorkflowEvent:
    """投影到 user 工作流的一枚可见事件（GOAL §7）。

    `data` 只装**可审计结构化元数据**（call_id / provider / model / tool 名 / verdict …），
    绝不装原始 prompt、provider 隐藏思维链、明文 secret——可见性边界由 `assert_event_clean` 兜底。
    """

    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    role: str = ""
    desk: str = ""
    node_id: str = ""
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_id: str = ""
    owner_user_id: str = ""
    workflow_id: str = ""
    sequence: int = 0
    idempotency_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "data": self.data,
            "role": self.role,
            "desk": self.desk,
            "node_id": self.node_id,
            "at": self.at,
            "event_id": self.event_id,
            "owner_user_id": self.owner_user_id,
            "workflow_id": self.workflow_id,
            "sequence": self.sequence,
            "idempotency_key": self.idempotency_key,
        }


def _walk_keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_keys(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_keys(v)


def _serialize(data: dict[str, Any]) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, default=str, sort_keys=True)


def assert_event_clean(event: WorkflowEvent, secret_values: Iterable[str] = ()) -> None:
    """可见性边界落地门（GOAL §7）：

    1. provider 隐藏思维链 / 明文凭据键边界：event.data 任一层 key ∈ FORBIDDEN_EVENT_KEYS → 拒。
    2. secret plaintext 边界：序列化面夹带在册明文 secret → 拒（绝不回显 secret）。

    种坏门必抓：把 `chain_of_thought` 或在册明文 key 塞进 event.data → 此门必抛。
    """

    serialized_event = event.to_dict()
    bad = [k for k in _walk_keys(serialized_event) if k in FORBIDDEN_EVENT_KEYS]
    if bad:
        raise EventProjectionError(
            f"投影事件 {event.kind!r} 夹带禁投影键 {sorted(set(bad))}——"
            "保留 provider 隐藏思维链 / secret 明文边界（GOAL §7 可见性边界）"
        )
    secret_list = [s for s in secret_values if s]
    if secret_list:
        hit = scan_messages_for_secret(_serialize(serialized_event), secret_list)
        if hit is not None:
            raise EventProjectionError(
                f"投影事件 {event.kind!r} 序列化面夹带在册明文 secret（len={len(hit)}）——"
                "致命可见性边界：secret plaintext 绝不投影（GOAL §7）"
            )


_WORKFLOW_EVENT_SCHEMA_VERSION = 3
_WORKFLOW_EVENT_ROW_KEYS = frozenset(
    {
        "schema_version",
        "event_id",
        "owner_user_id",
        "workflow_id",
        "sequence",
        "idempotency_key",
        "kind",
        "data",
        "role",
        "desk",
        "node_id",
        "at",
        "previous_hmac",
        "row_hmac",
    }
)
_WORKFLOW_EVENT_GENESIS = "0" * 64
_WORKFLOW_EVENT_KEY_BYTES = 32
_WORKFLOW_EVENT_HEAD_SCHEMA_VERSION = 1
_WORKFLOW_EVENT_HEAD_KEYS = frozenset(
    {
        "schema_version",
        "row_count",
        "last_row_hmac",
        "ledger_size",
        "checkpoint_hmac",
    }
)


def _required_scope(value: str, field_name: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} is required for durable workflow events")
    return normalized


def _event_identity(
    *,
    owner_user_id: str,
    workflow_id: str,
    sequence: int,
    event: WorkflowEvent,
) -> str:
    if event.idempotency_key:
        return "workflow_event:" + content_hash(
            {
                "owner_user_id": owner_user_id,
                "workflow_id": workflow_id,
                "idempotency_key": event.idempotency_key,
            }
        )
    return "workflow_event:" + content_hash(
        {
            "owner_user_id": owner_user_id,
            "workflow_id": workflow_id,
            "sequence": sequence,
            "kind": event.kind,
            "data": event.data,
            "role": event.role,
            "desk": event.desk,
            "node_id": event.node_id,
            "at": event.at,
            "idempotency_key": "",
        }
    )


class WorkflowEventIdempotencyError(WorkflowEventIntegrityError):
    """A stable event idempotency key collided with different caller intent."""


class PersistentWorkflowEventLedger:
    """Owner-scoped, HMAC-chained JSONL ledger for visible Agent OS events.

    The journal and its protected head are authenticated by a persisted 0600
    key. This detects public re-hashing, prefix/tail rollback, and checkpoint
    tampering across restarts. The boundary is same-machine integrity against
    accidental corruption and principals that cannot read the runtime user's
    private key; a fully compromised runtime account can read that key.

    Every append reloads and validates the complete journal and checkpoint under
    the same OS lock. Journal fsync and atomic checkpoint replacement are treated
    as one operation: any reported failure restores the prior journal bytes and
    protected head before the event can enter the in-memory projection.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_suffix(self._path.suffix + ".lock")
        self._key_path = self._path.with_suffix(self._path.suffix + ".hmac.key")
        self._head_path = self._path.with_suffix(self._path.suffix + ".head")
        self._lock = threading.RLock()
        with self._process_lock():
            self._prepare_ledger_file()
            if not os.path.lexists(self._key_path) and self._path.stat().st_size:
                raise WorkflowEventIntegrityError(
                    "durable workflow-event HMAC key is missing for a nonempty ledger"
                )
            self._key = self._load_or_create_key()
            if not os.path.lexists(self._head_path):
                if self._path.stat().st_size:
                    raise WorkflowEventIntegrityError(
                        "durable workflow-event checkpoint is missing for a nonempty ledger"
                    )
                self._write_checkpoint([], ledger_size=0)
            self._read_rows()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def key_path(self) -> Path:
        return self._key_path

    @property
    def head_path(self) -> Path:
        return self._head_path

    @contextmanager
    def _process_lock(self) -> Iterator[None]:
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self._lock_path, flags, 0o600)
        held = None
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise WorkflowEventIntegrityError(
                    "durable workflow-event lock must be a regular non-symlink file"
                )
            if hasattr(os, "getuid") and info.st_uid != os.getuid():
                raise WorkflowEventIntegrityError(
                    "durable workflow-event lock is owned by a different runtime user"
                )
            os.fchmod(fd, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=10.0)
            yield
        finally:
            if held is not None:
                held.release()
            os.close(fd)

    @staticmethod
    def _fsync_parent(path: Path) -> None:
        fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _assert_private_regular(path: Path, *, label: str) -> os.stat_result:
        try:
            info = path.lstat()
        except FileNotFoundError:
            raise WorkflowEventIntegrityError(f"{label} is missing: {path}") from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise WorkflowEventIntegrityError(f"{label} must be a regular non-symlink file")
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise WorkflowEventIntegrityError(f"{label} is owned by a different runtime user")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise WorkflowEventIntegrityError(f"{label} must have mode 0600")
        return info

    @classmethod
    def _read_private_bytes(cls, path: Path, *, label: str) -> bytes:
        before = cls._assert_private_regular(path, label=label)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
                or stat.S_IMODE(opened.st_mode) != 0o600
            ):
                raise WorkflowEventIntegrityError(f"{label} changed during secure open")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(fd)

    @classmethod
    def _create_private_file(cls, path: Path, payload: bytes, *, label: str) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags, 0o600)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(f"short write creating {label}")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        cls._fsync_parent(path)
        cls._assert_private_regular(path, label=label)

    def _prepare_ledger_file(self) -> None:
        if not os.path.lexists(self._path):
            self._create_private_file(
                self._path, b"", label="durable workflow-event journal"
            )
            return
        try:
            info = self._path.lstat()
        except FileNotFoundError:
            self._prepare_ledger_file()
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise WorkflowEventIntegrityError(
                "durable workflow-event journal must be a regular non-symlink file"
            )
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise WorkflowEventIntegrityError(
                "durable workflow-event journal is owned by a different runtime user"
            )
        os.chmod(self._path, 0o600)

    def _load_or_create_key(self) -> bytes:
        label = "durable workflow-event HMAC key"
        if not os.path.lexists(self._key_path):
            self._create_private_file(
                self._key_path, os.urandom(_WORKFLOW_EVENT_KEY_BYTES), label=label
            )
        key = self._read_private_bytes(self._key_path, label=label)
        if len(key) != _WORKFLOW_EVENT_KEY_BYTES:
            raise WorkflowEventIntegrityError(f"{label} must contain exactly 32 bytes")
        return key

    def _hmac(self, domain: bytes, payload: dict[str, Any]) -> str:
        message = b"quantbt:workflow-event:v3\x00" + domain + b"\x00" + canonical_json(payload).encode(
            "utf-8"
        )
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()

    def _row_hmac(self, row_without_hmac: dict[str, Any]) -> str:
        return self._hmac(b"row", row_without_hmac)

    def _checkpoint_payload(
        self, rows: list[dict[str, Any]], *, ledger_size: int
    ) -> dict[str, Any]:
        return {
            "schema_version": _WORKFLOW_EVENT_HEAD_SCHEMA_VERSION,
            "row_count": len(rows),
            "last_row_hmac": rows[-1]["row_hmac"] if rows else _WORKFLOW_EVENT_GENESIS,
            "ledger_size": ledger_size,
        }

    def _atomic_private_write(self, path: Path, payload: bytes, *, label: str) -> None:
        if os.path.lexists(path):
            self._assert_private_regular(path, label=label)
        fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        tmp = Path(raw_tmp)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(f"short atomic write for {label}")
                view = view[written:]
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.replace(tmp, path)
            self._assert_private_regular(path, label=label)
            self._fsync_parent(path)
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass

    def _write_checkpoint(self, rows: list[dict[str, Any]], *, ledger_size: int) -> None:
        body = self._checkpoint_payload(rows, ledger_size=ledger_size)
        head = {**body, "checkpoint_hmac": self._hmac(b"checkpoint", body)}
        self._atomic_private_write(
            self._head_path,
            (canonical_json(head) + "\n").encode("utf-8"),
            label="durable workflow-event checkpoint",
        )

    def _read_checkpoint(self) -> dict[str, Any]:
        raw = self._read_private_bytes(
            self._head_path, label="durable workflow-event checkpoint"
        )
        if not raw.endswith(b"\n") or raw.count(b"\n") != 1:
            raise WorkflowEventIntegrityError(
                "durable workflow-event checkpoint must be one canonical JSON line"
            )
        try:
            text = raw[:-1].decode("utf-8")
            head = json.loads(text)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowEventIntegrityError(
                "durable workflow-event checkpoint is malformed"
            ) from exc
        if not isinstance(head, dict) or set(head) != _WORKFLOW_EVENT_HEAD_KEYS:
            raise WorkflowEventIntegrityError(
                "durable workflow-event checkpoint has unknown or missing fields"
            )
        if text != canonical_json(head):
            raise WorkflowEventIntegrityError(
                "durable workflow-event checkpoint is non-canonical"
            )
        body = {key: value for key, value in head.items() if key != "checkpoint_hmac"}
        if body.get("schema_version") != _WORKFLOW_EVENT_HEAD_SCHEMA_VERSION:
            raise WorkflowEventIntegrityError(
                "unsupported durable workflow-event checkpoint schema"
            )
        row_count = body.get("row_count")
        ledger_size = body.get("ledger_size")
        last = body.get("last_row_hmac")
        if (
            type(row_count) is not int
            or row_count < 0
            or type(ledger_size) is not int
            or ledger_size < 0
            or not isinstance(last, str)
            or len(last) != 64
        ):
            raise WorkflowEventIntegrityError(
                "durable workflow-event checkpoint values are invalid"
            )
        expected = self._hmac(b"checkpoint", body)
        if not hmac.compare_digest(str(head.get("checkpoint_hmac") or ""), expected):
            raise WorkflowEventIntegrityError(
                "durable workflow-event checkpoint HMAC mismatch"
            )
        return body

    def _restore_checkpoint(self, payload: bytes) -> None:
        self._atomic_private_write(
            self._head_path,
            payload,
            label="durable workflow-event checkpoint",
        )

    def _read_rows(self) -> list[dict[str, Any]]:
        persisted_key = self._read_private_bytes(
            self._key_path, label="durable workflow-event HMAC key"
        )
        if len(persisted_key) != _WORKFLOW_EVENT_KEY_BYTES or not hmac.compare_digest(
            persisted_key, self._key
        ):
            raise WorkflowEventIntegrityError(
                "durable workflow-event HMAC key changed after ledger initialization"
            )
        raw = self._read_private_bytes(
            self._path, label="durable workflow-event journal"
        )
        if raw and not raw.endswith(b"\n"):
            raise WorkflowEventIntegrityError(
                f"torn or unterminated durable workflow-event tail at {self._path}"
            )
        rows: list[dict[str, Any]] = []
        previous_hmac = _WORKFLOW_EVENT_GENESIS
        next_sequence: dict[tuple[str, str], int] = {}
        seen_ids: set[str] = set()
        seen_idempotency: set[tuple[str, str, str]] = set()
        for line_no, raw_line in enumerate(raw.splitlines(), start=1):
            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise WorkflowEventIntegrityError(
                    f"invalid durable workflow-event UTF-8 at {self._path}:{line_no}"
                ) from exc
            if not line.strip():
                raise WorkflowEventIntegrityError(
                    f"blank durable workflow-event row at {self._path}:{line_no}"
                )
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise WorkflowEventIntegrityError(
                    f"invalid durable workflow-event JSON at {self._path}:{line_no}"
                ) from exc
            if not isinstance(row, dict) or set(row) != _WORKFLOW_EVENT_ROW_KEYS:
                raise WorkflowEventIntegrityError(
                    f"unknown or missing durable workflow-event fields at {self._path}:{line_no}"
                )
            if line != canonical_json(row):
                raise WorkflowEventIntegrityError(
                    f"non-canonical durable workflow-event row at {self._path}:{line_no}"
                )
            if row.get("schema_version") != _WORKFLOW_EVENT_SCHEMA_VERSION:
                raise WorkflowEventIntegrityError(
                    f"unsupported durable workflow-event schema at {self._path}:{line_no}"
                )
            try:
                owner = _required_scope(
                    str(row.get("owner_user_id") or ""), "owner_user_id"
                )
                workflow = _required_scope(
                    str(row.get("workflow_id") or ""), "workflow_id"
                )
            except ValueError as exc:
                raise WorkflowEventIntegrityError(
                    f"invalid durable workflow-event scope at {self._path}:{line_no}"
                ) from exc
            idempotency_key = str(row.get("idempotency_key") or "").strip()
            sequence = row.get("sequence")
            if type(sequence) is not int or sequence < 1:
                raise WorkflowEventIntegrityError(
                    f"invalid durable workflow-event sequence at {self._path}:{line_no}"
                )
            scope = (owner, workflow)
            expected_sequence = next_sequence.get(scope, 1)
            if sequence != expected_sequence:
                raise WorkflowEventIntegrityError(
                    f"non-contiguous durable workflow-event sequence at {self._path}:{line_no}"
                )
            if not isinstance(row.get("data"), dict):
                raise WorkflowEventIntegrityError(
                    f"invalid durable workflow-event data at {self._path}:{line_no}"
                )
            event = WorkflowEvent(
                kind=str(row.get("kind") or ""),
                data=dict(row.get("data") or {}),
                role=str(row.get("role") or ""),
                desk=str(row.get("desk") or ""),
                node_id=str(row.get("node_id") or ""),
                at=str(row.get("at") or ""),
                idempotency_key=idempotency_key,
            )
            if event.kind not in VISIBLE_EVENT_SET or not event.at:
                raise WorkflowEventIntegrityError(
                    f"invalid durable workflow-event payload at {self._path}:{line_no}"
                )
            expected_id = _event_identity(
                owner_user_id=owner,
                workflow_id=workflow,
                sequence=sequence,
                event=event,
            )
            event_id = str(row.get("event_id") or "")
            if event_id != expected_id or event_id in seen_ids:
                raise WorkflowEventIntegrityError(
                    f"durable workflow-event identity mismatch at {self._path}:{line_no}"
                )
            idempotency_identity = (owner, workflow, idempotency_key)
            if idempotency_key and idempotency_identity in seen_idempotency:
                raise WorkflowEventIntegrityError(
                    f"duplicate durable workflow-event idempotency key at {self._path}:{line_no}"
                )
            if row.get("previous_hmac") != previous_hmac:
                raise WorkflowEventIntegrityError(
                    f"durable workflow-event HMAC-chain discontinuity at {self._path}:{line_no}"
                )
            without_hmac = {key: value for key, value in row.items() if key != "row_hmac"}
            expected_hmac = self._row_hmac(without_hmac)
            if not hmac.compare_digest(str(row.get("row_hmac") or ""), expected_hmac):
                raise WorkflowEventIntegrityError(
                    f"durable workflow-event row HMAC mismatch at {self._path}:{line_no}"
                )
            rows.append(row)
            seen_ids.add(event_id)
            if idempotency_key:
                seen_idempotency.add(idempotency_identity)
            next_sequence[scope] = sequence + 1
            previous_hmac = expected_hmac
        checkpoint = self._read_checkpoint()
        expected_last = rows[-1]["row_hmac"] if rows else _WORKFLOW_EVENT_GENESIS
        if (
            checkpoint["row_count"] != len(rows)
            or checkpoint["last_row_hmac"] != expected_last
            or checkpoint["ledger_size"] != len(raw)
        ):
            raise WorkflowEventIntegrityError(
                "durable workflow-event checkpoint does not match the complete journal"
            )
        return rows

    def append(
        self,
        event: WorkflowEvent,
        *,
        owner_user_id: str,
        workflow_id: str,
        secret_values: Iterable[str] = (),
    ) -> WorkflowEvent:
        owner = _required_scope(owner_user_id, "owner_user_id")
        workflow = _required_scope(workflow_id, "workflow_id")
        idempotency_key = str(event.idempotency_key or "").strip()
        scoped_event = replace(
            event,
            owner_user_id=owner,
            workflow_id=workflow,
            idempotency_key=idempotency_key,
        )
        assert_event_clean(scoped_event, secret_values)
        with self._lock, self._process_lock():
            rows = self._read_rows()
            if idempotency_key:
                for row in rows:
                    if (
                        row["owner_user_id"] == owner
                        and row["workflow_id"] == workflow
                        and row["idempotency_key"] == idempotency_key
                    ):
                        existing = self._event_from_row(row)
                        if self._same_caller_intent(existing, scoped_event):
                            return existing
                        raise WorkflowEventIdempotencyError(
                            "durable workflow-event idempotency collision differs from persisted intent"
                        )
            sequence = 1 + sum(
                1
                for row in rows
                if row["owner_user_id"] == owner and row["workflow_id"] == workflow
            )
            enriched = replace(
                scoped_event,
                sequence=sequence,
                event_id=_event_identity(
                    owner_user_id=owner,
                    workflow_id=workflow,
                    sequence=sequence,
                    event=scoped_event,
                ),
            )
            if any(row["event_id"] == enriched.event_id for row in rows):
                raise WorkflowEventIntegrityError(
                    "durable workflow-event event_id collision differs from persisted identity"
                )
            previous_hmac = rows[-1]["row_hmac"] if rows else _WORKFLOW_EVENT_GENESIS
            row_without_hmac = {
                "schema_version": _WORKFLOW_EVENT_SCHEMA_VERSION,
                **enriched.to_dict(),
                "previous_hmac": previous_hmac,
            }
            row = {**row_without_hmac, "row_hmac": self._row_hmac(row_without_hmac)}
            encoded = canonical_json(row) + "\n"
            original_size = self._path.stat().st_size
            old_checkpoint = self._read_private_bytes(
                self._head_path, label="durable workflow-event checkpoint"
            )
            checkpoint_started = False
            try:
                flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(self._path, flags)
                try:
                    payload = encoded.encode("utf-8")
                    view = memoryview(payload)
                    while view:
                        written = os.write(fd, view)
                        if written <= 0:
                            raise OSError("short durable workflow-event append")
                        view = view[written:]
                    os.fsync(fd)
                finally:
                    os.close(fd)
                checkpoint_started = True
                self._write_checkpoint(
                    [*rows, row], ledger_size=original_size + len(encoded.encode("utf-8"))
                )
            except Exception as exc:
                recovery_errors: list[BaseException] = []
                with self._path.open("r+b") as rollback:
                    rollback.truncate(original_size)
                    rollback.flush()
                    try:
                        os.fsync(rollback.fileno())
                    except OSError as rollback_exc:
                        recovery_errors.append(rollback_exc)
                if checkpoint_started:
                    try:
                        self._restore_checkpoint(old_checkpoint)
                    except Exception as checkpoint_exc:  # noqa: BLE001 - fail closed below.
                        recovery_errors.append(checkpoint_exc)
                if recovery_errors:
                    raise WorkflowEventIntegrityError(
                        "durable workflow-event append failed and rollback durability could not be proven"
                    ) from exc
                raise
            return enriched

    @staticmethod
    def _same_caller_intent(existing: WorkflowEvent, candidate: WorkflowEvent) -> bool:
        return (
            existing.kind == candidate.kind
            and existing.data == candidate.data
            and existing.role == candidate.role
            and existing.desk == candidate.desk
            and existing.node_id == candidate.node_id
            and existing.owner_user_id == candidate.owner_user_id
            and existing.workflow_id == candidate.workflow_id
            and existing.idempotency_key == candidate.idempotency_key
        )

    @staticmethod
    def _event_from_row(row: dict[str, Any]) -> WorkflowEvent:
        return WorkflowEvent(
            kind=row["kind"],
            data=dict(row["data"]),
            role=row["role"],
            desk=row["desk"],
            node_id=row["node_id"],
            at=row["at"],
            event_id=row["event_id"],
            owner_user_id=row["owner_user_id"],
            workflow_id=row["workflow_id"],
            sequence=row["sequence"],
            idempotency_key=row["idempotency_key"],
        )

    def events(
        self,
        *,
        owner_user_id: str,
        workflow_id: str | None = None,
    ) -> tuple[WorkflowEvent, ...]:
        owner = _required_scope(owner_user_id, "owner_user_id")
        workflow = str(workflow_id or "").strip()
        with self._lock, self._process_lock():
            rows = self._read_rows()
        return tuple(
            self._event_from_row(row)
            for row in rows
            if row["owner_user_id"] == owner
            and (not workflow or row["workflow_id"] == workflow)
        )


class EventProjector:
    """统一事件流投影器（GOAL §7）——收集 orchestrator 各步事件 + adopt LLM Gateway 事件。

    单一源：LLM 相关 5 枚直接从 `LLMGatewayEvent` adopt（kind 同名），不在 orchestrator 侧重造。
    每枚 emit 都过 `assert_event_clean`（可见性边界）——夹带 secret/隐藏思维链当场拒。
    """

    def __init__(
        self,
        *,
        secret_values: Iterable[str] = (),
        ledger: PersistentWorkflowEventLedger | None = None,
        owner_user_id: str = "",
        workflow_id: str = "",
    ) -> None:
        self._events: list[WorkflowEvent] = []
        self._secret_values = tuple(s for s in secret_values if s)
        self._ledger = ledger
        self._owner_user_id = str(owner_user_id or "").strip()
        self._workflow_id = str(workflow_id or "").strip()
        self._lock = threading.RLock()
        if ledger is not None:
            _required_scope(self._owner_user_id, "owner_user_id")
            _required_scope(self._workflow_id, "workflow_id")

    def emit(
        self,
        kind: str,
        data: dict[str, Any] | None = None,
        *,
        role: str = "",
        desk: str = "",
        node_id: str = "",
        idempotency_key: str = "",
    ) -> WorkflowEvent:
        with self._lock:
            if kind not in VISIBLE_EVENT_SET:
                raise EventProjectionError(
                    f"未知事件类型 {kind!r} ∉ GOAL §7 可见事件 24 枚（不投影库外事件·防伪可见性）"
                )
            ev = WorkflowEvent(
                kind=kind,
                data=dict(data or {}),
                role=role,
                desk=desk,
                node_id=node_id,
                idempotency_key=str(idempotency_key or "").strip(),
            )
            assert_event_clean(ev, self._secret_values)
            if self._ledger is not None:
                ev = self._ledger.append(
                    ev,
                    owner_user_id=self._owner_user_id,
                    workflow_id=self._workflow_id,
                    secret_values=self._secret_values,
                )
                if ev.idempotency_key:
                    for existing in self._events:
                        if existing.event_id == ev.event_id:
                            return existing
            self._events.append(ev)
        return ev

    def adopt_gateway_events(
        self,
        gw_events: Iterable[LLMGatewayEvent],
        *,
        role: str = "",
        desk: str = "",
        node_id: str = "",
    ) -> list[WorkflowEvent]:
        """把 LLM Gateway 产的 `LLMGatewayEvent`（5 枚之一）adopt 进统一流（单一源·不重造 kind）。"""

        out: list[WorkflowEvent] = []
        for ge in gw_events:
            if ge.kind not in GATEWAY_EVENT_KINDS:
                raise EventProjectionError(
                    f"非 LLM Gateway 事件 {ge.kind!r} 不应经 adopt_gateway_events 进流"
                )
            out.append(self.emit(ge.kind, dict(ge.data), role=role, desk=desk, node_id=node_id))
        return out

    @property
    def events(self) -> tuple[WorkflowEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def kinds(self) -> list[str]:
        return [e.kind for e in self.events]

    def of_kind(self, kind: str) -> list[WorkflowEvent]:
        return [e for e in self.events if e.kind == kind]

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self.events]


__all__ = [
    "EV_AGENT_PLAN_CREATED",
    "EV_TODO_UPDATED",
    "EV_ROLE_AGENT_DISPATCHED",
    "EV_LLM_ROUTE_SELECTED",
    "EV_LLM_CALL_STARTED",
    "EV_LLM_CALL_FINISHED",
    "EV_CREDENTIAL_POOL_SELECTED",
    "EV_PROVIDER_FALLBACK_USED",
    "EV_TOOL_CALL_STARTED",
    "EV_TOOL_CALL_FINISHED",
    "EV_RAG_HIT_USED",
    "EV_ASSET_READ",
    "EV_ASSET_DIFF_CREATED",
    "EV_CANONICAL_COMMAND_PROPOSED",
    "EV_CANONICAL_COMMAND_APPLIED",
    "EV_VALIDATION_STARTED",
    "EV_VALIDATION_FINISHED",
    "EV_VERIFIER_CHALLENGE_RAISED",
    "EV_DESK_HANDOFF_CREATED",
    "EV_APPROVAL_REQUESTED",
    "EV_FAILURE_DETECTED",
    "EV_REPAIR_ATTEMPTED",
    "EV_ARTIFACT_PRODUCED",
    "EV_RUN_VERDICT_PRODUCED",
    "VISIBLE_EVENT_KINDS",
    "VISIBLE_EVENT_SET",
    "GATEWAY_EVENT_KINDS",
    "FORBIDDEN_EVENT_KEYS",
    "EventProjectionError",
    "EventProjector",
    "PersistentWorkflowEventLedger",
    "WorkflowEvent",
    "WorkflowEventIntegrityError",
    "WorkflowEventIdempotencyError",
    "assert_event_clean",
]
