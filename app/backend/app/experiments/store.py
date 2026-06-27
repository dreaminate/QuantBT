"""M12 · 实验/Run/Model 注册表 (JSONL append-only)。

为什么不用 MLflow：MLflow 体积大、自带 web UI 与本项目设计冲突。我们要的功能
其实只是：
- 给每次 backtest run 注册条目
- 记录 lineage (parent_run_id / forked_from)
- 模型版本 + stage promotion (dev → staging → production → archived)

写入 `data/experiments/{store,runs,models}.jsonl` 三个文件。
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal


ModelStage = Literal["dev", "staging", "production", "archived"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _gen_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


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
    def __init__(self, root: Path, *, gate_service: Any = None, model_governance_registry: Any = None) -> None:
        self._root = Path(root)
        self._store = _JsonlStore(self._root / "models.jsonl")
        # T-019：注入审批门服务。None = dev/archived 直翻（向后兼容）；staging/production 在 None 时 raise（禁裸翻）。
        self._gate_service = gate_service
        self._model_governance_registry = model_governance_registry

    def register_version(
        self,
        model_id: str,
        artifact_path: str | None = None,
        source_run_id: str | None = None,
        metrics: dict[str, float] | None = None,
        model_passport_ref: str | None = None,
        validation_dossier_ref: str | None = None,
        note: str = "",
    ) -> ModelVersion:
        versions = [v.version for v in self.list_versions(model_id)]
        next_v = (max(versions) + 1) if versions else 1
        mv = ModelVersion(
            model_id=model_id,
            version=next_v,
            stage="dev",
            created_at_utc=_now(),
            metrics=metrics or {},
            artifact_path=artifact_path,
            source_run_id=source_run_id,
            model_passport_ref=model_passport_ref,
            validation_dossier_ref=validation_dossier_ref,
            note=note,
        )
        self._store.append(mv.to_dict())
        return mv

    def apply_stage(self, model_id: str, version: int, stage: ModelStage) -> ModelVersion:
        """公开翻 stage：仅限 dev/archived（探索通道直翻）。staging/production 须经 promote()→审批门→
        approve_promotion（防 #2/#15 侧门：公开方法不得直翻进 production）。"""

        if stage in ("staging", "production"):
            from ..approval.schema import GateStateError
            raise GateStateError(
                f"apply_stage 不可直翻到 {stage}（须 promote()→审批门→approve_promotion；防侧门 bare-flip）"
            )
        return self._apply_stage_unchecked(model_id, version, stage)

    def _apply_stage_unchecked(self, model_id: str, version: int, stage: ModelStage) -> ModelVersion:
        """实际翻转（私有）：dev/archived 经 apply_stage、staging/production 仅经审批门 execute_fn 到达。"""

        for v in self.list_versions(model_id):
            if v.version == version:
                v.stage = stage
                self._store.append(v.to_dict())
                return v
        raise KeyError(f"model={model_id} version={version} 未注册")

    def approve_promotion(self, gate_id: str, *, approver: str, reason: str,
                          risk_restated: str | None = None) -> Any:
        """批准一个 pending promote 门并【真翻 stage】（绑 execute_fn=_apply_stage_unchecked，复核 #2b）。"""

        from ..approval.schema import GateStateError
        if self._gate_service is None:
            raise GateStateError("无 gate_service，无法 approve_promotion")

        def _exec(gate: Any) -> str:
            self._apply_stage_unchecked(gate.model_id, gate.version, gate.to_stage)
            return f"stage:{gate.model_id}:v{gate.version}:{gate.to_stage}"

        return self._gate_service.approve(gate_id, approver=approver, reason=reason,
                                          risk_restated=risk_restated, execute_fn=_exec)

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
    ) -> Any:
        """T-019：dev/archived 直翻（探索通道，向后兼容）；staging/production 走审批门。

        晋升 staging/production 返 `ApprovalGate`（pending，待 approve）或 `GateRejection`（缺要件+缺口清单），
        **不裸翻 stage**。实际翻转在 `gate_service.approve(gate_id, execute_fn=apply_stage)` 时发生。
        """

        if stage in ("dev", "archived"):
            return self.apply_stage(model_id, version, stage)   # 探索通道直翻

        from ..approval.schema import GateRejection, GateStateError
        if self._gate_service is None:
            raise GateStateError(
                f"promote 到 {stage} 必须接 ApprovalGateService（裸翻已禁用，T-019）"
            )
        cur = next((v for v in self.list_versions(model_id) if v.version == version), None)
        if cur is None:
            raise KeyError(f"model={model_id} version={version} 未注册")
        passport_metadata = self._validated_model_passport_metadata(
            cur,
            stage=stage,
            model_passport_ref=model_passport_ref,
        )
        governed_evidence = dict(evidence or {})
        governed_evidence.update(passport_metadata)
        gate = self._gate_service.open_gate(
            model_id=model_id, version=version, from_stage=cur.stage, to_stage=stage,
            action_kind=("promote_production" if stage == "production" else "promote_staging"),
            created_by=created_by or "unknown", verification_record_id=verification_record_id,
            evidence=governed_evidence, strategy_goal_ref=strategy_goal_ref,
        )
        if gate.decision == "rejected":
            return GateRejection(gate_id=gate.gate_id, model_id=model_id, version=version,
                                 to_stage=stage, gap_list=gate.gap_list, verdict_text=gate.verdict_text)
        return gate   # pending：caller 另行 approve（approver≠creator）

    def list_versions(self, model_id: str) -> list[ModelVersion]:
        latest: dict[tuple[str, int], dict[str, Any]] = {}
        for row in self._store.read_all():
            if row["model_id"] == model_id:
                latest[(row["model_id"], row["version"])] = row
        return [ModelVersion(**v) for v in latest.values()]

    def list_models(self) -> list[str]:
        return sorted({row["model_id"] for row in self._store.read_all()})

    def _validated_model_passport_metadata(
        self,
        model_version: ModelVersion,
        *,
        stage: ModelStage,
        model_passport_ref: str | None,
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
            passport = self._model_governance_registry.passport(ref)
        except KeyError as exc:
            raise GateStateError(f"model_passport_ref 未登记: {ref}") from exc

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
        return {
            "model_passport_ref": passport.passport_id,
            "validation_dossier_ref": passport.validation_dossier_ref,
        }


__all__ = [
    "Experiment",
    "ExperimentStore",
    "ModelRegistry",
    "ModelStage",
    "ModelVersion",
    "Run",
    "RunStore",
]
