"""M12 · 实验/Run/Model 注册表 (JSONL append-only)。

为什么不用 MLflow：MLflow 体积大、自带 web UI 与本项目设计冲突。我们要的功能
其实只是：
- 给每次 backtest run 注册条目
- 记录 lineage (parent_run_id / forked_from)
- 模型版本 + stage promotion (dev → staging → production → archived)

写入 `data/experiments/{store,runs,models}.jsonl` 三个文件。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..cross_process_lock import acquire_exclusive_fd
from .reviewer_grants import (
    ModelReviewerGrant,
    PersistentModelReviewerGrantRegistry,
    ReviewerGrantAuthorizationError,
    ReviewerGrantPermission,
)


ModelStage = Literal["dev", "staging", "production", "archived"]
_MODEL_VERSION_SCHEMA_VERSION = 2


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _normalized_text(value: Any) -> str:
    return str(value or "").strip()


def _model_asset_ref(owner_user_id: str, model_id: str) -> str:
    material = json.dumps(
        {
            "owner_user_id": _normalized_text(owner_user_id),
            "model_id": _normalized_text(model_id),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "model_asset_" + hashlib.sha256(material).hexdigest()


@dataclass
class Experiment:
    experiment_id: str
    name: str
    asset_class: str
    created_at_utc: str = field(default_factory=_now)
    tags: dict[str, str] = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Run:
    run_id: str
    experiment_id: str
    started_at_utc: str
    finished_at_utc: str | None
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    inputs: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    artifact_paths: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    parent_run_id: str | None = None
    forked_from: str | None = None
    # 假设卡接进 Run 生命周期（T-024 / D-T024，向后兼容可空）：
    # layer = 用户在 StrategyGoal 显式声明/晋级（exploratory→confirmatory；系统绝不自动晋级）。
    # hypothesis_card_id = 该 run 绑定的可证伪假设卡。store 层不强制校验（不破坏既有 Run）。
    hypothesis_card_id: str | None = None
    layer: Literal["exploratory", "secondary", "confirmatory"] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ModelVersion:
    model_id: str
    version: int
    stage: ModelStage
    created_at_utc: str
    metrics: dict[str, float] = field(default_factory=dict)
    artifact_path: str | None = None
    source_run_id: str | None = None
    model_passport_ref: str | None = None
    validation_dossier_ref: str | None = None
    note: str = ""
    owner_user_id: str = ""
    model_asset_ref: str = ""
    schema_version: int = _MODEL_VERSION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self.owner_user_id = _normalized_text(self.owner_user_id)
        self.model_id = _normalized_text(self.model_id)
        self.model_asset_ref = _normalized_text(self.model_asset_ref)
        if self.schema_version != _MODEL_VERSION_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported model version schema_version={self.schema_version!r}"
            )
        if not self.owner_user_id:
            raise ValueError("model version owner_user_id is required")
        if not self.model_id:
            raise ValueError("model version model_id is required")
        if type(self.version) is not int or self.version <= 0:
            raise ValueError("model version must be a positive integer")
        if self.stage not in {"dev", "staging", "production", "archived"}:
            raise ValueError(f"unsupported model stage={self.stage!r}")
        expected_asset_ref = _model_asset_ref(self.owner_user_id, self.model_id)
        if self.model_asset_ref and self.model_asset_ref != expected_asset_ref:
            raise ValueError("model version model_asset_ref does not match owner and model_id")
        self.model_asset_ref = expected_asset_ref

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _JsonlStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()

    def append(self, payload: dict[str, Any]) -> None:
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def append_durable(self, payload: dict[str, Any]) -> None:
        with self._lock, self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def read_all(self) -> list[dict[str, Any]]:
        with self._lock:
            out: list[dict[str, Any]] = []
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # 容忍崩溃中途写坏的（通常是末尾）行，避免整个 store 永久不可读
                    continue
            return out


class ExperimentStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._exp_store = _JsonlStore(self._root / "experiments.jsonl")

    def create_experiment(self, name: str, asset_class: str, description: str = "", tags: dict[str, str] | None = None) -> Experiment:
        exp = Experiment(experiment_id=_gen_id("exp"), name=name, asset_class=asset_class, description=description, tags=tags or {})
        self._exp_store.append(exp.to_dict())
        return exp

    def list_experiments(self) -> list[Experiment]:
        # 最后一次出现的即为最新（允许后续追加状态变更）
        latest: dict[str, dict[str, Any]] = {}
        for row in self._exp_store.read_all():
            latest[row["experiment_id"]] = row
        return [Experiment(**v) for v in latest.values()]


class RunStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._store = _JsonlStore(self._root / "runs.jsonl")

    def create_run(
        self,
        experiment_id: str,
        inputs: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
        parent_run_id: str | None = None,
        forked_from: str | None = None,
    ) -> Run:
        run = Run(
            run_id=_gen_id("run"),
            experiment_id=experiment_id,
            started_at_utc=_now(),
            finished_at_utc=None,
            status="running",
            inputs=inputs or {},
            tags=tags or {},
            parent_run_id=parent_run_id,
            forked_from=forked_from,
        )
        self._store.append(run.to_dict())
        return run

    def update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        metrics: dict[str, float] | None = None,
        artifact_paths: list[str] | None = None,
        finished: bool = False,
    ) -> Run:
        current = self.get_run(run_id)
        if status is not None:
            current.status = status  # type: ignore[assignment]
        if metrics:
            current.metrics.update(metrics)
        if artifact_paths:
            current.artifact_paths = list({*current.artifact_paths, *artifact_paths})
        if finished:
            current.finished_at_utc = _now()
        self._store.append(current.to_dict())
        return current

    def get_run(self, run_id: str) -> Run:
        for row in reversed(self._store.read_all()):
            if row["run_id"] == run_id:
                return Run(**row)
        raise KeyError(f"run 不存在: {run_id}")

    def list_runs(self, experiment_id: str | None = None) -> list[Run]:
        latest: dict[str, dict[str, Any]] = {}
        for row in self._store.read_all():
            latest[row["run_id"]] = row
        items = [Run(**v) for v in latest.values()]
        if experiment_id:
            items = [r for r in items if r.experiment_id == experiment_id]
        return items

    def lineage(self, run_id: str) -> list[Run]:
        """返回 run + 所有祖先（parent_run_id 链 + forked_from）。"""

        chain: list[Run] = []
        seen: set[str] = set()
        cur_id: str | None = run_id
        while cur_id and cur_id not in seen:
            try:
                run = self.get_run(cur_id)
            except KeyError:
                break
            chain.append(run)
            seen.add(cur_id)
            cur_id = run.parent_run_id or run.forked_from
        return chain


class ModelRegistry:
    def __init__(
        self,
        root: Path,
        *,
        gate_service: Any = None,
        model_governance_registry: Any = None,
        reviewer_grant_registry: PersistentModelReviewerGrantRegistry | None = None,
    ) -> None:
        self._root = Path(root)
        self._store = _JsonlStore(self._root / "models.jsonl")
        self._lock = threading.RLock()
        self._file_lock_path = self._root / ".models.jsonl.lock"
        self._legacy_quarantined_count = 0
        # T-019：注入审批门服务。None = dev/archived 直翻（向后兼容）；staging/production 在 None 时 raise（禁裸翻）。
        self._gate_service = gate_service
        self._model_governance_registry = model_governance_registry
        self._model_recertification_event_registry: Any = None
        self._model_recertification_training_jobs: Any = None
        if model_governance_registry is not None:
            # The model registry is constructed before TrainingService in the
            # production composition root.  Bind the canonical sibling stores
            # now; TrainingService replaces the TrainingJobStore object with its
            # exact instance after construction (the paths must match).
            from ..research_os.model_recertification_events import (
                PersistentModelRecertificationEventRegistry,
            )
            from ..research_os.model_recertification_evidence import (
                PersistentModelRecertificationEvidenceRegistry,
            )
            from ..training.store import TrainingJobStore

            evidence_registry = PersistentModelRecertificationEvidenceRegistry(
                self._root.parent
                / "audit"
                / "model_recertification_evidence.jsonl"
            )
            self._model_recertification_event_registry = (
                PersistentModelRecertificationEventRegistry(
                    self._root.parent
                    / "audit"
                    / "model_recertification_events.jsonl",
                    evidence_registry=evidence_registry,
                    model_registry=self,
                )
            )
            self._model_recertification_training_jobs = TrainingJobStore(
                self._root.parent / "training_runs"
            )
        self._reviewer_grant_registry = reviewer_grant_registry or (
            PersistentModelReviewerGrantRegistry(
                self._root / "model_reviewer_grants.jsonl"
            )
        )

    def _acquire_file_lock(self) -> tuple[int, Any]:
        fd = os.open(self._file_lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            os.chmod(self._file_lock_path, 0o600)
            held = acquire_exclusive_fd(fd, timeout_seconds=30.0)
        except Exception:
            os.close(fd)
            raise
        return fd, held

    @property
    def legacy_quarantined_count(self) -> int:
        self._current_versions()
        return self._legacy_quarantined_count

    @property
    def reviewer_grant_registry(self) -> PersistentModelReviewerGrantRegistry:
        return self._reviewer_grant_registry

    @property
    def model_recertification_event_registry(self) -> Any:
        return self._model_recertification_event_registry

    @property
    def model_recertification_evidence_registry(self) -> Any:
        registry = self._model_recertification_event_registry
        return getattr(registry, "evidence_registry", None)

    def bind_model_recertification_events(
        self,
        event_registry: Any,
        training_jobs: Any,
    ) -> None:
        """Bind the exact TrainingService stores used by promotion validation."""

        from ..research_os.model_recertification_events import (
            PersistentModelRecertificationEventRegistry,
        )
        from ..training.store import TrainingJobStore

        if not isinstance(event_registry, PersistentModelRecertificationEventRegistry):
            raise ValueError(
                "model registry requires a persistent model recertification event registry"
            )
        if not isinstance(training_jobs, TrainingJobStore):
            raise ValueError("model registry requires a persistent TrainingJobStore")
        existing = self._model_recertification_event_registry
        if existing is not None and Path(existing.path) != Path(event_registry.path):
            raise ValueError("model recertification event registry path identity mismatch")
        existing_jobs = self._model_recertification_training_jobs
        if existing_jobs is not None and Path(existing_jobs._path) != Path(training_jobs._path):
            raise ValueError("model recertification TrainingJobStore path identity mismatch")
        attached_evidence = self.model_recertification_evidence_registry
        incoming_evidence = getattr(event_registry, "evidence_registry", None)
        if (
            attached_evidence is not None
            and incoming_evidence is not None
            and Path(attached_evidence.path) != Path(incoming_evidence.path)
        ):
            raise ValueError("model recertification evidence registry path identity mismatch")
        if attached_evidence is not None and incoming_evidence is None:
            bind_sources = getattr(event_registry, "bind_sources", None)
            if not callable(bind_sources):
                raise ValueError("model recertification event registry lacks source binding")
            bind_sources(evidence_registry=attached_evidence, model_registry=self)
        elif incoming_evidence is not None:
            bind_sources = getattr(event_registry, "bind_sources", None)
            if callable(bind_sources):
                bind_sources(evidence_registry=incoming_evidence, model_registry=self)
        self._model_recertification_event_registry = event_registry
        self._model_recertification_training_jobs = training_jobs

    @staticmethod
    def _required_owner(owner_user_id: str | None) -> str:
        owner = _normalized_text(owner_user_id)
        if not owner:
            raise ValueError("model registry owner_user_id is required")
        return owner

    @staticmethod
    def _required_model_id(model_id: str) -> str:
        model = _normalized_text(model_id)
        if not model:
            raise ValueError("model registry model_id is required")
        return model

    @staticmethod
    def _required_stage(stage: ModelStage | str) -> ModelStage:
        if stage not in {"dev", "staging", "production", "archived"}:
            raise ValueError(f"unsupported model stage={stage!r}")
        return stage  # type: ignore[return-value]

    def stage_history(
        self,
        model_id: str,
        version: int,
        *,
        owner_user_id: str,
    ) -> tuple[ModelVersion, ...]:
        """Return the exact durable stage history for one owner/model version.

        This intentionally does not use ``_JsonlStore.read_all`` because that
        compatibility reader skips malformed JSON.  Stage-only recertification
        evidence must fail closed on a corrupt row rather than silently deriving
        a transition from an incomplete history.
        """

        owner = self._required_owner(owner_user_id)
        model = self._required_model_id(model_id)
        if type(version) is not int or version <= 0:
            raise ValueError("model version must be a positive integer")
        try:
            lines = self._store._path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            raise ValueError("model stage history cannot be read") from exc
        history: list[ModelVersion] = []
        for line_no, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("model row must be an object")
                item = ModelVersion(**row)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"invalid model stage history row at {self._store._path}:{line_no}"
                ) from exc
            if (
                item.owner_user_id == owner
                and item.model_id == model
                and item.version == version
            ):
                history.append(item)
        if not history:
            raise KeyError(
                f"owner={owner} model={model} version={version} 未注册"
            )
        return tuple(history)

    def _current_versions(self) -> dict[tuple[str, str, int], ModelVersion]:
        latest: dict[tuple[str, str, int], ModelVersion] = {}
        legacy_quarantined_count = 0
        for row in self._store.read_all():
            schema_version = row.get("schema_version")
            if schema_version in {None, 1}:
                legacy_quarantined_count += 1
                continue
            if schema_version != _MODEL_VERSION_SCHEMA_VERSION:
                raise ValueError(
                    f"unsupported persisted model version schema_version={schema_version!r}"
                )
            try:
                version = ModelVersion(**row)
            except (TypeError, ValueError) as exc:
                raise ValueError("invalid persisted owner-scoped model version row") from exc
            key = (version.owner_user_id, version.model_id, version.version)
            latest[key] = version
        self._legacy_quarantined_count = legacy_quarantined_count
        return latest

    def _read_owner(self, owner_user_id: str | None) -> str | None:
        explicit = _normalized_text(owner_user_id)
        if explicit:
            return explicit
        owners = {key[0] for key in self._current_versions()}
        if len(owners) > 1:
            raise ValueError(
                "model registry owner_user_id is required for an ambiguous lookup"
            )
        return next(iter(owners), None)

    def _version_for_owner(
        self,
        model_id: str,
        version: int,
        *,
        owner_user_id: str,
    ) -> ModelVersion:
        model = self._required_model_id(model_id)
        try:
            return self._current_versions()[(owner_user_id, model, int(version))]
        except KeyError as exc:
            raise KeyError(
                f"owner={owner_user_id} model={model} version={version} 未注册"
            ) from exc

    def register_version(
        self,
        model_id: str,
        artifact_path: str | None = None,
        source_run_id: str | None = None,
        metrics: dict[str, float] | None = None,
        model_passport_ref: str | None = None,
        validation_dossier_ref: str | None = None,
        note: str = "",
        *,
        owner_user_id: str | None = None,
    ) -> ModelVersion:
        owner = self._required_owner(owner_user_id)
        model = self._required_model_id(model_id)
        with self._lock:
            fd, held = self._acquire_file_lock()
            try:
                versions = [
                    value.version
                    for value in self.list_versions(model, owner_user_id=owner)
                ]
                next_v = (max(versions) + 1) if versions else 1
                validation_dossier_ref = self._validate_registration_passport(
                    model,
                    next_v,
                    owner_user_id=owner,
                    model_passport_ref=model_passport_ref,
                    validation_dossier_ref=validation_dossier_ref,
                )
                mv = ModelVersion(
                    model_id=model,
                    version=next_v,
                    stage="dev",
                    created_at_utc=_now(),
                    metrics=metrics or {},
                    artifact_path=artifact_path,
                    source_run_id=source_run_id,
                    model_passport_ref=model_passport_ref,
                    validation_dossier_ref=validation_dossier_ref,
                    note=note,
                    owner_user_id=owner,
                    model_asset_ref=_model_asset_ref(owner, model),
                )
                self._store.append_durable(mv.to_dict())
                return mv
            finally:
                held.release()
                os.close(fd)

    def _validate_registration_passport(
        self,
        model_id: str,
        version: int,
        *,
        owner_user_id: str,
        model_passport_ref: str | None,
        validation_dossier_ref: str | None,
    ) -> str | None:
        ref = _normalized_text(model_passport_ref)
        if not ref:
            return validation_dossier_ref
        if self._model_governance_registry is None:
            raise ValueError(
                "model_passport_ref requires an owner-scoped model_governance_registry"
            )
        try:
            passport = self._model_governance_registry.passport(
                ref,
                owner_user_id=owner_user_id,
            )
        except KeyError as exc:
            raise ValueError(
                f"model_passport_ref is not recorded for owner={owner_user_id}: {ref}"
            ) from exc
        expected_refs = {
            f"{model_id}:v{version}",
            f"{model_id}:{version}",
            f"model_version:{model_id}:v{version}",
            f"model_version:{model_id}:{version}",
        }
        if str(passport.model_version_ref) not in expected_refs:
            raise ValueError(
                "model_passport_ref does not match registered model version: "
                f"{passport.model_version_ref!r} not in {sorted(expected_refs)!r}"
            )
        passport_dossier = _normalized_text(passport.validation_dossier_ref)
        supplied_dossier = _normalized_text(validation_dossier_ref)
        if supplied_dossier and supplied_dossier != passport_dossier:
            raise ValueError(
                "validation_dossier_ref does not match owner-scoped model passport"
            )
        return passport_dossier or None

    def apply_stage(
        self,
        model_id: str,
        version: int,
        stage: ModelStage,
        *,
        owner_user_id: str | None = None,
    ) -> ModelVersion:
        """公开翻 stage：仅限 dev/archived（探索通道直翻）。staging/production 须经 promote()→审批门→
        approve_promotion（防 #2/#15 侧门：公开方法不得直翻进 production）。"""

        owner = self._required_owner(owner_user_id)
        stage = self._required_stage(stage)
        if stage in ("staging", "production"):
            from ..approval.schema import GateStateError
            raise GateStateError(
                f"apply_stage 不可直翻到 {stage}（须 promote()→审批门→approve_promotion；防侧门 bare-flip）"
            )
        return self._apply_stage_unchecked(
            model_id,
            version,
            stage,
            owner_user_id=owner,
        )

    def _apply_stage_unchecked(
        self,
        model_id: str,
        version: int,
        stage: ModelStage,
        *,
        owner_user_id: str,
    ) -> ModelVersion:
        """实际翻转（私有）：dev/archived 经 apply_stage、staging/production 仅经审批门 execute_fn 到达。"""

        owner = self._required_owner(owner_user_id)
        stage = self._required_stage(stage)
        with self._lock:
            fd, held = self._acquire_file_lock()
            try:
                current = self._version_for_owner(
                    model_id,
                    version,
                    owner_user_id=owner,
                )
                current.stage = stage
                self._store.append_durable(current.to_dict())
                return current
            finally:
                held.release()
                os.close(fd)

    def approve_promotion(
        self,
        gate_id: str,
        *,
        model_id: str,
        owner_user_id: str | None = None,
        approver: str,
        reason: str,
        risk_restated: str | None = None,
    ) -> Any:
        """批准一个 pending promote 门并【真翻 stage】（绑 execute_fn=_apply_stage_unchecked，复核 #2b）。"""

        from ..approval.schema import GateStateError
        if self._gate_service is None:
            raise GateStateError("无 gate_service，无法 approve_promotion")

        owner = self._required_owner(owner_user_id)
        model = self._required_model_id(model_id)
        self._promotion_gate_for_owner(gate_id, model, owner_user_id=owner)

        def _exec(gate: Any) -> str:
            self._validate_promotion_gate_identity(
                gate,
                model,
                owner_user_id=owner,
            )
            self._apply_stage_unchecked(
                model,
                gate.version,
                gate.to_stage,
                owner_user_id=owner,
            )
            return f"stage:{owner}:{model}:v{gate.version}:{gate.to_stage}"

        return self._gate_service.approve(gate_id, approver=approver, reason=reason,
                                          risk_restated=risk_restated, execute_fn=_exec)

    def reject_promotion(
        self,
        gate_id: str,
        *,
        model_id: str,
        owner_user_id: str | None = None,
        approver: str,
        reason: str,
    ) -> Any:
        from ..approval.schema import GateStateError

        if self._gate_service is None:
            raise GateStateError("无 gate_service，无法 reject_promotion")
        owner = self._required_owner(owner_user_id)
        model = self._required_model_id(model_id)
        self._promotion_gate_for_owner(gate_id, model, owner_user_id=owner)
        return self._gate_service.reject(
            gate_id,
            approver=approver,
            reason=reason,
        )

    def grant_promotion_reviewer(
        self,
        gate_id: str,
        *,
        model_id: str,
        owner_user_id: str | None = None,
        reviewer_user_id: str,
        permissions: tuple[ReviewerGrantPermission, ...],
        expires_at_utc: str,
        issued_by: str,
        expected_record_hash: str | None = None,
    ) -> ModelReviewerGrant:
        """Owner-issue an exact-gate grant after revalidating the gate binding."""

        owner = self._required_owner(owner_user_id)
        model = self._required_model_id(model_id)
        gate = self._promotion_gate_for_owner(
            gate_id,
            model,
            owner_user_id=owner,
        )
        return self._reviewer_grant_registry.issue_grant(
            gate_id=gate.gate_id,
            owner_user_id=owner,
            model_id=model,
            model_asset_ref=gate.model_id,
            model_version=gate.version,
            reviewer_user_id=reviewer_user_id,
            permissions=permissions,
            expires_at_utc=expires_at_utc,
            issued_by=issued_by,
            expected_record_hash=expected_record_hash,
        )

    def revoke_promotion_reviewer(
        self,
        grant_id: str,
        *,
        owner_user_id: str | None = None,
        revoked_by: str,
        expected_record_hash: str,
    ) -> ModelReviewerGrant:
        owner = self._required_owner(owner_user_id)
        return self._reviewer_grant_registry.revoke_grant(
            grant_id,
            owner_user_id=owner,
            revoked_by=revoked_by,
            expected_record_hash=expected_record_hash,
        )

    def promotion_gate_for_reviewer(
        self,
        gate_id: str,
        *,
        reviewer_user_id: str,
    ) -> Any:
        """Return a gate only when the current reviewer has exact ``view`` access."""

        return self._promotion_gate_for_reviewer(
            gate_id,
            reviewer_user_id=reviewer_user_id,
            permission="view",
        )

    def promotion_reviewer_authorization(
        self,
        gate_id: str,
        *,
        model_id: str,
        reviewer_user_id: str,
        permission: ReviewerGrantPermission,
    ) -> ModelReviewerGrant:
        """Return the exact current grant backing a reviewer operation."""

        gate, owner, logical_model, reviewer = (
            self._promotion_gate_material_for_reviewer(
                gate_id,
                reviewer_user_id=reviewer_user_id,
                model_id=model_id,
            )
        )
        try:
            return self._reviewer_grant_registry.authorize(
                gate_id=gate.gate_id,
                owner_user_id=owner,
                model_id=logical_model,
                model_asset_ref=gate.model_id,
                model_version=gate.version,
                reviewer_user_id=reviewer,
                permission=permission,
            )
        except ReviewerGrantAuthorizationError as exc:
            from ..approval.schema import GateStateError

            raise GateStateError(
                "promotion gate not found or reviewer not authorized"
            ) from exc

    def promotion_reviewer_authority_evidence(
        self,
        gate_id: str,
        *,
        model_id: str,
        reviewer_user_id: str,
        grant_id: str,
        grant_record_hash: str,
        permission: ReviewerGrantPermission,
    ) -> ModelReviewerGrant:
        """Validate the exact grant recorded on a completed gate decision.

        A later revocation does not rewrite history: its previous_record_hash
        must point to the active grant hash used by the serialized decision.
        """

        from ..approval.schema import GateStateError

        gate, owner, logical_model, reviewer = (
            self._promotion_gate_material_for_reviewer(
                gate_id,
                reviewer_user_id=reviewer_user_id,
                model_id=model_id,
            )
        )
        try:
            grant = self._reviewer_grant_registry.get_for_owner(
                grant_id,
                owner_user_id=owner,
            )
            evidence = gate.evidence if isinstance(gate.evidence, dict) else {}
            decided_at = datetime.fromisoformat(str(gate.decided_at_utc or ""))
            expires_at = datetime.fromisoformat(grant.expires_at_utc)
            issued_at = datetime.fromisoformat(grant.issued_at_utc)
            exact_hash = grant.record_hash == grant_record_hash and grant.status == "active"
            revoked_after = (
                grant.status == "revoked"
                and grant.previous_record_hash == grant_record_hash
                and datetime.fromisoformat(str(grant.revoked_at_utc or "")) >= decided_at
            )
            valid = bool(
                gate.decision in {"approved", "rejected"}
                and gate.approver == reviewer
                and evidence.get("reviewer_grant_id") == grant_id
                and evidence.get("reviewer_grant_record_hash") == grant_record_hash
                and evidence.get("reviewer_user_id") == reviewer
                and grant.gate_id == gate.gate_id
                and grant.owner_user_id == owner
                and grant.model_id == logical_model
                and grant.model_asset_ref == gate.model_id
                and grant.model_version == gate.version
                and grant.reviewer_user_id == reviewer
                and permission in grant.permissions
                and issued_at <= decided_at < expires_at
                and (exact_hash or revoked_after)
            )
        except (KeyError, TypeError, ValueError):
            valid = False
        if not valid:
            raise GateStateError(
                "promotion gate reviewer authority evidence is invalid"
            )
        return grant

    def approve_promotion_as_reviewer(
        self,
        gate_id: str,
        *,
        model_id: str,
        reviewer_user_id: str,
        reason: str,
        risk_restated: str | None = None,
    ) -> Any:
        """Approve using only the authenticated reviewer identity and a live grant."""

        from ..approval.schema import GateStateError

        model = self._required_model_id(model_id)
        gate, owner, logical_model, reviewer = (
            self._promotion_gate_material_for_reviewer(
                gate_id,
                reviewer_user_id=reviewer_user_id,
                model_id=model,
            )
        )

        def _exec(current_gate: Any) -> str:
            self._validate_promotion_gate_identity(
                current_gate,
                model,
                owner_user_id=owner,
            )
            self._apply_stage_unchecked(
                model,
                current_gate.version,
                current_gate.to_stage,
                owner_user_id=owner,
            )
            return (
                f"stage:{owner}:{model}:v{current_gate.version}:"
                f"{current_gate.to_stage}"
            )

        try:
            with self._reviewer_grant_registry.authorization(
                gate_id=gate.gate_id,
                owner_user_id=owner,
                model_id=logical_model,
                model_asset_ref=gate.model_id,
                model_version=gate.version,
                reviewer_user_id=reviewer,
                permission="approve",
            ) as reviewer_grant:
                # The grant lock remains held through the decision and stage
                # side effect, so a concurrent revocation cannot win between
                # authorization and use. ApprovalGateService independently
                # rechecks reviewer != creator.
                return self._gate_service.approve(
                    gate.gate_id,
                    approver=reviewer,
                    reason=reason,
                    risk_restated=risk_restated,
                    execute_fn=_exec,
                    authorization_evidence={
                        "reviewer_grant_id": reviewer_grant.grant_id,
                        "reviewer_grant_record_hash": reviewer_grant.record_hash,
                        "reviewer_user_id": reviewer,
                    },
                )
        except ReviewerGrantAuthorizationError as exc:
            raise GateStateError(
                "promotion gate not found or reviewer not authorized"
            ) from exc

    def reject_promotion_as_reviewer(
        self,
        gate_id: str,
        *,
        model_id: str,
        reviewer_user_id: str,
        reason: str,
    ) -> Any:
        """Reject using only the authenticated reviewer identity and a live grant."""

        from ..approval.schema import GateStateError

        model = self._required_model_id(model_id)
        gate, owner, logical_model, reviewer = (
            self._promotion_gate_material_for_reviewer(
                gate_id,
                reviewer_user_id=reviewer_user_id,
                model_id=model,
            )
        )
        try:
            with self._reviewer_grant_registry.authorization(
                gate_id=gate.gate_id,
                owner_user_id=owner,
                model_id=logical_model,
                model_asset_ref=gate.model_id,
                model_version=gate.version,
                reviewer_user_id=reviewer,
                permission="reject",
            ):
                return self._gate_service.reject(
                    gate.gate_id,
                    approver=reviewer,
                    reason=reason,
                )
        except ReviewerGrantAuthorizationError as exc:
            raise GateStateError(
                "promotion gate not found or reviewer not authorized"
            ) from exc

    def promotion_gate(
        self,
        gate_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> Any:
        """Return a promotion gate only after its durable owner binding matches."""

        from ..approval.schema import GateStateError

        if self._gate_service is None:
            raise GateStateError("无 gate_service，无法查询 promotion gate")
        owner = self._required_owner(owner_user_id)
        store = getattr(self._gate_service, "_store", None)
        get_gate = getattr(store, "get", None)
        if not callable(get_gate):
            raise GateStateError(
                "gate_service does not expose durable gate lookup for owner verification"
            )
        try:
            gate = get_gate(gate_id)
        except KeyError as exc:
            raise GateStateError(f"promotion gate not found: {gate_id}") from exc
        evidence = gate.evidence if isinstance(gate.evidence, dict) else {}
        model_id = _normalized_text(evidence.get("logical_model_id"))
        if not model_id:
            raise GateStateError("promotion gate missing logical_model_id owner binding")
        self._validate_promotion_gate_identity(
            gate,
            model_id,
            owner_user_id=owner,
        )
        return gate

    def promote(
        self,
        model_id: str,
        version: int,
        stage: ModelStage,
        *,
        created_by: str | None = None,
        verification_record_id: str | None = None,
        evidence: dict[str, Any] | None = None,
        strategy_goal_ref: str | None = None,
        model_passport_ref: str | None = None,
        owner_user_id: str | None = None,
    ) -> Any:
        """T-019：dev/archived 直翻（探索通道，向后兼容）；staging/production 走审批门。

        晋升 staging/production 返 `ApprovalGate`（pending，待 approve）或 `GateRejection`（缺要件+缺口清单），
        **不裸翻 stage**。实际翻转在 `gate_service.approve(gate_id, execute_fn=apply_stage)` 时发生。
        """

        owner = self._required_owner(owner_user_id)
        model = self._required_model_id(model_id)
        stage = self._required_stage(stage)
        if stage in ("dev", "archived"):
            return self.apply_stage(
                model,
                version,
                stage,
                owner_user_id=owner,
            )   # 探索通道直翻

        from ..approval.schema import GateRejection, GateStateError
        if self._gate_service is None:
            raise GateStateError(
                f"promote 到 {stage} 必须接 ApprovalGateService（裸翻已禁用，T-019）"
            )
        cur = self._version_for_owner(model, version, owner_user_id=owner)
        passport_metadata = self._validated_model_passport_metadata(
            cur,
            stage=stage,
            model_passport_ref=model_passport_ref,
            owner_user_id=owner,
        )
        governed_evidence = dict(evidence or {})
        governed_evidence.update(passport_metadata)
        governed_evidence.update(
            {
                "owner_user_id": owner,
                "logical_model_id": model,
                "model_asset_ref": cur.model_asset_ref,
            }
        )
        gate = self._gate_service.open_gate(
            model_id=cur.model_asset_ref, version=version, from_stage=cur.stage, to_stage=stage,
            action_kind=("promote_production" if stage == "production" else "promote_staging"),
            created_by=created_by or "unknown", verification_record_id=verification_record_id,
            evidence=governed_evidence, strategy_goal_ref=strategy_goal_ref,
        )
        if gate.decision == "rejected":
            return GateRejection(gate_id=gate.gate_id, model_id=model, version=version,
                                 to_stage=stage, gap_list=gate.gap_list, verdict_text=gate.verdict_text)
        return gate   # pending：caller 另行 approve（approver≠creator）

    def list_versions(
        self,
        model_id: str,
        *,
        owner_user_id: str | None = None,
    ) -> list[ModelVersion]:
        model = self._required_model_id(model_id)
        owner = self._read_owner(owner_user_id)
        if owner is None:
            return []
        return [
            value
            for (record_owner, record_model, _version), value in self._current_versions().items()
            if record_owner == owner and record_model == model
        ]

    def list_models(self, *, owner_user_id: str | None = None) -> list[str]:
        owner = self._read_owner(owner_user_id)
        if owner is None:
            return []
        return sorted(
            {
                model_id
                for record_owner, model_id, _version in self._current_versions()
                if record_owner == owner
            }
        )

    def _validated_model_passport_metadata(
        self,
        model_version: ModelVersion,
        *,
        stage: ModelStage,
        model_passport_ref: str | None,
        owner_user_id: str,
    ) -> dict[str, Any]:
        from ..approval.schema import GateStateError

        ref = model_passport_ref or model_version.model_passport_ref
        if not ref:
            raise GateStateError(
                f"promote 到 {stage} 必须提供已记录的 model_passport_ref（GOAL §15 ModelPassport 门）"
            )
        if self._model_governance_registry is None:
            raise GateStateError(
                "ModelRegistry 缺 model_governance_registry，无法校验 model_passport_ref（fail-closed）"
            )
        try:
            passport = self._model_governance_registry.passport(
                ref,
                owner_user_id=owner_user_id,
            )
        except KeyError as exc:
            raise GateStateError(
                f"model_passport_ref 未为 owner={owner_user_id} 登记: {ref}"
            ) from exc

        expected_refs = {
            f"{model_version.model_id}:v{model_version.version}",
            f"{model_version.model_id}:{model_version.version}",
            f"model_version:{model_version.model_id}:v{model_version.version}",
            f"model_version:{model_version.model_id}:{model_version.version}",
        }
        if str(passport.model_version_ref) not in expected_refs:
            raise GateStateError(
                "model_passport_ref 与晋级模型版本不匹配: "
                f"passport.model_version_ref={passport.model_version_ref!r}, "
                f"expected one of {sorted(expected_refs)!r}"
            )
        from ..research_os.model_governance import ModelRiskTier, validate_model_promotion
        from ..research_os.model_recertification_events import (
            resolve_current_recertification_requirements,
        )

        base_decision = validate_model_promotion(passport)
        if not base_decision.accepted:
            raise GateStateError(
                "model passport fails base §15 policy: "
                + ",".join(item.code for item in base_decision.violations)
            )
        evidence_registry = self.model_recertification_evidence_registry
        if evidence_registry is None:
            raise GateStateError(
                "model promotion lacks the durable recertification evidence producer"
            )
        from ..research_os.model_recertification_evidence import (
            DependencyKind,
            ModelEvidenceError,
        )

        challenger_metadata: dict[str, Any] = {}
        risk_tier = str(
            getattr(passport.model_risk_tier, "value", passport.model_risk_tier)
        )
        if risk_tier in {ModelRiskTier.HIGH.value, ModelRiskTier.CRITICAL.value}:
            challenger_ref = _normalized_text(passport.challenger_result)
            try:
                challenger = evidence_registry.challenger_result(
                    challenger_ref,
                    owner_user_id=owner_user_id,
                )
            except (KeyError, ModelEvidenceError) as exc:
                raise GateStateError(
                    "high-risk model promotion requires a durable challenger-result producer"
                ) from exc
            if self._model_recertification_training_jobs is None:
                raise GateStateError(
                    "high-risk model promotion lacks the canonical training-job registry"
                )
            succeeded_jobs = {
                f"training_run:{job.run_id}": job
                for job in self._model_recertification_training_jobs.list()
                if _normalized_text(getattr(job, "owner_user_id", "")) == owner_user_id
                and getattr(job, "model", None) == model_version.model_id
                and getattr(job, "status", None) == "succeeded"
                and _normalized_text(getattr(job, "run_id", ""))
            }
            bound_refs = {
                challenger.baseline_run_ref,
                challenger.challenger_run_ref,
            }
            metric_values: dict[str, float] = {}
            try:
                run_store = RunStore(self._root)
                for run_ref in bound_refs:
                    job = succeeded_jobs[run_ref]
                    run = run_store.get_run(_normalized_text(job.run_id))
                    if run.status != "succeeded":
                        raise ValueError("challenger run is not succeeded")
                    value = run.metrics[challenger.metric_ref]
                    if isinstance(value, bool):
                        raise ValueError("challenger metric is not numeric")
                    metric_values[run_ref] = float(value)
            except (KeyError, TypeError, ValueError) as exc:
                raise GateStateError(
                    "high-risk challenger result does not resolve two succeeded model runs"
                ) from exc
            if (
                challenger.model_type_card_ref != passport.model_type_card_ref
                or challenger.model_version_ref != passport.model_version_ref
                or challenger.model_passport_ref != passport.passport_id
                or challenger.challenger_run_ref != passport.training_run_ref
                or not challenger.passed
                or bound_refs - set(succeeded_jobs)
                or getattr(
                    succeeded_jobs.get(challenger.challenger_run_ref),
                    "model_passport_ref",
                    None,
                )
                != passport.passport_id
                or getattr(
                    succeeded_jobs.get(challenger.challenger_run_ref),
                    "model_version",
                    None,
                )
                != model_version.version
                or getattr(
                    succeeded_jobs.get(challenger.challenger_run_ref),
                    "validation_dossier_ref",
                    None,
                )
                != passport.validation_dossier_ref
                or metric_values[challenger.baseline_run_ref]
                != challenger.baseline_value
                or metric_values[challenger.challenger_run_ref]
                != challenger.challenger_value
            ):
                raise GateStateError(
                    "high-risk challenger result does not bind the promoted owner/model/passport"
                )
            challenger_metadata = {
                "model_challenger_result_ref": challenger.result_ref,
                "model_challenger_result_record_hash": (
                    evidence_registry.current_record_hash(
                        challenger.result_ref,
                        owner_user_id=owner_user_id,
                    )
                ),
            }

        try:
            evidence_registry.resolve_dependencies(
                passport.vendor_dependency_refs,
                owner_user_id=owner_user_id,
                dependency_kind=DependencyKind.VENDOR,
            )
            evidence_registry.resolve_dependencies(
                passport.foundation_model_dependency_refs,
                owner_user_id=owner_user_id,
                dependency_kind=DependencyKind.FOUNDATION_MODEL,
            )
        except (KeyError, ModelEvidenceError) as exc:
            raise GateStateError(
                "model promotion lacks current content-bound dependency evidence"
            ) from exc
        if (
            self._model_recertification_event_registry is None
            or self._model_recertification_training_jobs is None
        ):
            raise GateStateError(
                "model promotion lacks the automatic recertification event producer"
            )
        try:
            resolution = resolve_current_recertification_requirements(
                governance=self._model_governance_registry,
                event_registry=self._model_recertification_event_registry,
                training_jobs=self._model_recertification_training_jobs,
                owner_user_id=owner_user_id,
                current_passport_ref=passport.passport_id,
                proposed_execution_stage=stage,
            )
            recertification_metadata = resolution.gate_metadata(
                self._model_governance_registry,
                owner_user_id=owner_user_id,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise GateStateError(
                f"model recertification requirements are not cleared: {exc}"
            ) from exc
        return {
            "model_passport_ref": passport.passport_id,
            "validation_dossier_ref": passport.validation_dossier_ref,
            **challenger_metadata,
            **recertification_metadata,
        }

    def _validate_promotion_gate_identity(
        self,
        gate: Any,
        model_id: str,
        *,
        owner_user_id: str,
    ) -> None:
        from ..approval.schema import GateStateError

        expected_asset_ref = _model_asset_ref(owner_user_id, model_id)
        evidence = gate.evidence if isinstance(gate.evidence, dict) else {}
        if gate.model_id != expected_asset_ref:
            raise GateStateError("promotion gate model asset does not match owner and model_id")
        if evidence.get("owner_user_id") != owner_user_id:
            raise GateStateError("promotion gate owner_user_id does not match caller")
        if evidence.get("logical_model_id") != model_id:
            raise GateStateError("promotion gate logical_model_id does not match caller")
        if evidence.get("model_asset_ref") != expected_asset_ref:
            raise GateStateError("promotion gate model_asset_ref does not match caller")
        current = self._version_for_owner(
            model_id,
            gate.version,
            owner_user_id=owner_user_id,
        )
        completed_stage = (
            gate.to_stage
            if getattr(gate, "decision", None) == "approved"
            and bool(getattr(gate, "side_effect_executed", False))
            and bool(_normalized_text(getattr(gate, "side_effect_ref", "")))
            else gate.from_stage
        )
        if current.stage != completed_stage:
            raise GateStateError(
                "promotion gate stage no longer matches current model stage"
            )
        current_metadata = self._validated_model_passport_metadata(
            current,
            stage=gate.to_stage,
            model_passport_ref=evidence.get("model_passport_ref"),
            owner_user_id=owner_user_id,
        )
        for key, value in current_metadata.items():
            if evidence.get(key) != value:
                raise GateStateError(
                    f"promotion gate {key} no longer matches current governance state"
                )

    def _promotion_gate_for_owner(
        self,
        gate_id: str,
        model_id: str,
        *,
        owner_user_id: str,
    ) -> Any:
        from ..approval.schema import GateStateError

        store = getattr(self._gate_service, "_store", None)
        get_gate = getattr(store, "get", None)
        if not callable(get_gate):
            raise GateStateError(
                "gate_service does not expose durable gate lookup for owner verification"
            )
        try:
            gate = get_gate(gate_id)
        except KeyError as exc:
            raise GateStateError(f"promotion gate not found: {gate_id}") from exc
        self._validate_promotion_gate_identity(
            gate,
            model_id,
            owner_user_id=owner_user_id,
        )
        return gate

    def _promotion_gate_for_reviewer(
        self,
        gate_id: str,
        *,
        reviewer_user_id: str,
        permission: ReviewerGrantPermission,
        model_id: str | None = None,
    ) -> Any:
        """Resolve and authorize without disclosing whether the gate exists."""

        from ..approval.schema import GateStateError

        gate, owner, logical_model, reviewer = (
            self._promotion_gate_material_for_reviewer(
                gate_id,
                reviewer_user_id=reviewer_user_id,
                model_id=model_id,
            )
        )
        try:
            self._reviewer_grant_registry.authorize(
                gate_id=gate.gate_id,
                owner_user_id=owner,
                model_id=logical_model,
                model_asset_ref=gate.model_id,
                model_version=gate.version,
                reviewer_user_id=reviewer,
                permission=permission,
            )
        except ReviewerGrantAuthorizationError as exc:
            raise GateStateError(
                "promotion gate not found or reviewer not authorized"
            ) from exc
        return gate

    def _promotion_gate_material_for_reviewer(
        self,
        gate_id: str,
        *,
        reviewer_user_id: str,
        model_id: str | None = None,
    ) -> tuple[Any, str, str, str]:
        """Resolve immutable gate material without authorizing a permission."""

        from ..approval.schema import GateStateError

        if self._gate_service is None:
            raise GateStateError("无 gate_service，无法查询 promotion gate")
        reviewer = _normalized_text(reviewer_user_id)
        if not reviewer:
            raise GateStateError("promotion gate not found or reviewer not authorized")
        store = getattr(self._gate_service, "_store", None)
        get_gate = getattr(store, "get", None)
        if not callable(get_gate):
            raise GateStateError(
                "gate_service does not expose durable gate lookup for reviewer authorization"
            )
        try:
            gate = get_gate(gate_id)
            evidence = gate.evidence if isinstance(gate.evidence, dict) else {}
            owner = _normalized_text(evidence.get("owner_user_id"))
            logical_model = _normalized_text(evidence.get("logical_model_id"))
            requested_model = _normalized_text(model_id)
            if not owner or not logical_model:
                raise ReviewerGrantAuthorizationError
            if requested_model and requested_model != logical_model:
                raise ReviewerGrantAuthorizationError
            self._validate_promotion_gate_identity(
                gate,
                logical_model,
                owner_user_id=owner,
            )
        except (KeyError, ReviewerGrantAuthorizationError, GateStateError) as exc:
            raise GateStateError(
                "promotion gate not found or reviewer not authorized"
            ) from exc
        return gate, owner, logical_model, reviewer


__all__ = [
    "Experiment",
    "ExperimentStore",
    "ModelRegistry",
    "ModelStage",
    "ModelVersion",
    "Run",
    "RunStore",
]
