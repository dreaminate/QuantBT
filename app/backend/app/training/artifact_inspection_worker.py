from __future__ import annotations

import hashlib
import json
import pickletools
import struct
import sys
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def _pickle_metadata(path: Path) -> tuple[list[str], list[str]]:
    checks = ["serialized_deserialize_skipped"]
    limitations = ["pickle/joblib opcodes are metadata only; object code was not executed"]
    try:
        with path.open("rb") as fh:
            op_count = 0
            for op, _arg, _pos in pickletools.genops(fh):
                op_count += 1
                if op.name in {"GLOBAL", "STACK_GLOBAL", "REDUCE", "BUILD"}:
                    checks.append(f"pickle_opcode:{op.name.lower()}")
                if op_count >= 512:
                    limitations.append("pickle opcode scan truncated at 512 operations")
                    break
        checks.append("pickle_metadata_scan_ok")
    except Exception as exc:  # noqa: BLE001 - joblib and protocol variants can be partially opaque.
        limitations.append(f"pickle metadata scan incomplete: {type(exc).__name__}")
    return checks, limitations


def _safe_tensors_header(path: Path) -> tuple[list[str], list[str]]:
    checks = []
    limitations = []
    with path.open("rb") as fh:
        header_len_raw = fh.read(8)
        if len(header_len_raw) != 8:
            raise ValueError("safe_tensors header length missing")
        header_len = struct.unpack("<Q", header_len_raw)[0]
        if header_len > 1_000_000:
            raise ValueError("safe_tensors header too large for inspection")
        header = json.loads(fh.read(header_len).decode("utf-8"))
    checks.append("safe_tensors_header_json_ok")
    checks.append(f"safe_tensors_tensor_count:{len([k for k in header if k != '__metadata__'])}")
    return checks, limitations


def _torch_weights_only(path: Path) -> tuple[list[str], list[str]]:
    import torch

    torch.load(path, map_location="cpu", weights_only=True)
    return ["torch_weights_only_load_ok"], ["torch weights_only load executed in inspector subprocess"]


def inspect(payload: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(payload.get("artifact_path") or "")).expanduser()
    expected_hash = str(payload.get("expected_hash") or "")
    artifact_format = str(payload.get("artifact_format") or "") or _format_from_path(path)
    if not path.exists() or not path.is_file():
        raise ValueError(f"artifact_path is not a regular file: {path}")
    if path.is_symlink():
        raise ValueError(f"artifact_path cannot be a symlink: {path}")
    actual_hash = _sha256_file(path)
    if expected_hash and expected_hash != actual_hash:
        raise ValueError(f"artifact hash mismatch: {expected_hash} != {actual_hash}")

    checks = ["regular_file", "sha256_match"]
    limitations: list[str] = []
    mode = "metadata_only"
    deserialize_executed = False

    if artifact_format in {"pickle", "joblib"}:
        mode = "metadata_only_no_deserialize"
        extra_checks, extra_limits = _pickle_metadata(path)
        checks.extend(extra_checks)
        limitations.extend(extra_limits)
    elif artifact_format == "safe_tensors":
        mode = "safe_tensors_header"
        extra_checks, extra_limits = _safe_tensors_header(path)
        checks.extend(extra_checks)
        limitations.extend(extra_limits)
    elif artifact_format == "torch":
        mode = "torch_weights_only_dry_load"
        extra_checks, extra_limits = _torch_weights_only(path)
        checks.extend(extra_checks)
        limitations.extend(extra_limits)
        deserialize_executed = True
    elif artifact_format == "json":
        json.loads(path.read_text(encoding="utf-8"))
        checks.append("json_parse_ok")
    else:
        limitations.append("format-specific parser unavailable; hash and file checks only")

    identity = {
        "artifact_hash": actual_hash,
        "artifact_format": artifact_format,
        "inspection_mode": mode,
        "checks": checks,
    }
    return {
        "accepted": True,
        "artifact_path": str(path.resolve()),
        "artifact_hash": actual_hash,
        "artifact_format": artifact_format,
        "inspection_ref": "artifact_inspection:" + _stable_hash(identity),
        "inspection_mode": mode,
        "inspector_ref": "training.artifact_inspection_worker:v1",
        "process_isolation": "subprocess",
        "deserialize_executed": deserialize_executed,
        "checks": checks,
        "limitations": limitations,
    }


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        print(json.dumps(inspect(payload), ensure_ascii=False, sort_keys=True), flush=True)
        return 0
    except Exception as exc:  # noqa: BLE001 - caller needs a structured rejection.
        print(
            json.dumps(
                {
                    "accepted": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "inspector_ref": "training.artifact_inspection_worker:v1",
                    "process_isolation": "subprocess",
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
