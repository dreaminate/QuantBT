from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _format_from_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".safetensors":
        return "safe_tensors"
    if suffix in {".pkl", ".pickle"}:
        return "pickle"
    if suffix == ".joblib":
        return "joblib"
    if suffix in {".pt", ".pth"}:
        return "torch"
    if suffix == ".json":
        return "json"
    if suffix == ".onnx":
        return "onnx"
    return "other"


def inspect_artifact_in_subprocess(
    artifact_path: str | Path,
    *,
    expected_hash: str,
    artifact_format: str | None = None,
    timeout: float = 15.0,
) -> dict[str, Any]:
    path = Path(artifact_path)
    payload = {
        "artifact_path": str(path),
        "expected_hash": expected_hash,
        "artifact_format": artifact_format or _format_from_path(path),
    }
    backend_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(backend_root)
        if not env.get("PYTHONPATH")
        else str(backend_root) + os.pathsep + env["PYTHONPATH"]
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.training.artifact_inspection_worker"],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"artifact inspection timed out after {timeout}s: {path}") from exc
    try:
        result = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"artifact inspection returned malformed JSON: {proc.stdout!r}") from exc
    if proc.returncode != 0 or not result.get("accepted"):
        detail = result.get("error") or proc.stderr or "unknown artifact inspection rejection"
        raise ValueError(f"artifact inspection rejected: {detail}")
    return result


__all__ = ["inspect_artifact_in_subprocess"]
