"""脊柱 · Mathematical Spine 账本——artifact/binding/check/choice 的 append-only 记录。

决策 D-MATH-SPINE「后续按 Mathematical Spine、Consistency Gate、MethodologyChoice ledger 拆分」。
复用 `ledger._ChainStore` 的 prev_hash 哈希链（同一身份/完整性范式，绝不另造），单文件 JSONL。

诚实不变量（= honest-N 同款防自欺）：
- **无** `set_label / force_promote / promote / update / delete / set_status` 等「改小/伪造」API。
  产物升级与否由 `spine_gate.evaluate_promotion` 实时裁定，账本只如实记录，不缓存可被篡改的结论。
- 「刷新 binding」= append 新版本，不原地改旧条目；`latest_binding(theory_ref)` 取最近一版。
  这样 staleness 永远可被重算（旧 code_content_hash 仍在链上），改实现绕不过门。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .ids import content_hash
from .ledger import _ChainStore
from .spine import (
    ConsistencyCheck,
    MathematicalArtifact,
    MethodologyChoiceRecord,
    TheoryImplementationBinding,
)

OP_ARTIFACT = "math_artifact"
OP_BINDING = "theory_impl_binding"
OP_CHECK = "consistency_check"
OP_CHOICE = "methodology_choice"


def _artifact_payload(a: MathematicalArtifact) -> dict[str, Any]:
    return {
        "artifact_id": a.artifact_id,
        "artifact_type": a.artifact_type,
        "statement": a.statement,
        "definition": a.definition,
        "proof_status": a.proof_status,
        "assumptions": list(a.assumptions),
        "applicability": a.applicability,
        "failure_conditions": list(a.failure_conditions),
        "test_ref": a.test_ref,
        "validation_ref": a.validation_ref,
    }


def _binding_payload(b: TheoryImplementationBinding) -> dict[str, Any]:
    return {
        "binding_id": b.binding_id,
        "theory_ref": b.theory_ref,
        "code_ref": b.code_ref,
        "code_content_hash": b.code_content_hash,
        "config_ref": b.config_ref,
        "data_contract_ref": b.data_contract_ref,
        "test_refs": list(b.test_refs),
        "waiver_ref": b.waiver_ref,
        "consistency_verdict": b.consistency_verdict,
    }


def _check_payload(c: ConsistencyCheck) -> dict[str, Any]:
    return {
        "check_id": c.check_id,
        "binding_id": c.binding_id,
        "check_type": c.check_type,
        "result": c.result,
        "expected_property": c.expected_property,
        "observed_property": c.observed_property,
        "failure_reason": c.failure_reason,
        "affected_assets": list(c.affected_assets),
    }


def _choice_payload(m: MethodologyChoiceRecord) -> dict[str, Any]:
    return {
        "choice_id": m.choice_id,
        "chosen_path": m.chosen_path,
        "asset_ref": m.asset_ref,
        "run_ref": m.run_ref,
        "responsibility_boundary": m.responsibility_boundary,
        "allowed_environment": m.allowed_environment,
        "actor": m.actor,
        "skipped_steps": list(m.skipped_steps),
    }


class SpineLedger:
    """Mathematical Spine 的 append-only 一本账（复用 _ChainStore 哈希链）。

    刻意**不**暴露任何改小/伪造结论的方法——升级裁定永远走 `spine_gate` 实时算，账本只记录。
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._store = _ChainStore(self._root / "spine_ledger.jsonl")

    # ── 记录（append-only）──────────────────────────────────────────────
    def record_artifact(self, a: MathematicalArtifact) -> str:
        self._store.append(OP_ARTIFACT, _artifact_payload(a))
        return a.artifact_id

    def record_binding(self, b: TheoryImplementationBinding) -> str:
        self._store.append(OP_BINDING, _binding_payload(b))
        return b.binding_id

    def record_check(self, c: ConsistencyCheck) -> str:
        self._store.append(OP_CHECK, _check_payload(c))
        return c.check_id

    def record_choice(self, m: MethodologyChoiceRecord) -> str:
        self._store.append(OP_CHOICE, _choice_payload(m))
        return m.choice_id

    # ── 读取/重算 ───────────────────────────────────────────────────────
    def _records(self, op: str) -> list[dict[str, Any]]:
        return [r["payload"] for r in self._store.read_records() if r.get("op") == op]

    def list_bindings(self, theory_ref: str | None = None) -> list[dict[str, Any]]:
        rows = self._records(OP_BINDING)
        if theory_ref is None:
            return rows
        return [r for r in rows if r.get("theory_ref") == theory_ref]

    def latest_binding(self, theory_ref: str) -> dict[str, Any] | None:
        """取某理论最近一版 binding（链上顺序 = append 顺序，最后的即最新）。"""

        rows = self.list_bindings(theory_ref)
        return rows[-1] if rows else None

    def checks_for(self, binding_id: str) -> list[dict[str, Any]]:
        return [r for r in self._records(OP_CHECK) if r.get("binding_id") == binding_id]

    def choices_for(self, asset_ref: str) -> list[dict[str, Any]]:
        return [r for r in self._records(OP_CHOICE) if r.get("asset_ref") == asset_ref]

    def is_stale(self, theory_ref: str, current_code_source: Any) -> bool | None:
        """实现源是否已漂离最近 binding 冻结的指纹（staleness 重算）。

        返回 None = 该理论无 binding（无从判定）；True = 已漂移（门必拒升级）。
        用 `content_hash` 单一身份源重算，旧指纹在链上，改实现绕不过。
        """

        b = self.latest_binding(theory_ref)
        if b is None:
            return None
        return content_hash(current_code_source) != b.get("code_content_hash")

    def verify_chain(self) -> tuple[bool, list[str]]:
        """重算哈希链查篡改/链断（委派 _ChainStore，与一本账同款完整性证据）。"""

        return self._store.verify_chain()
