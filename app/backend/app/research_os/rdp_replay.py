"""Executable, fixed-argv replay worker for IDE-backed RDP evidence.

The free-form ``RDPManifest.reproducibility_command`` is never executed here.
Trusted callers invoke this repository module with two private files: a strict
request containing strategy source, and an exclusive output path.  The worker
runs the source through :func:`app.ide.sandbox.run_user_strategy` and emits only
observed hashes and bounded execution metadata.  It never emits strategy,
result, stdout, or stderr plaintext, and it accepts no caller-declared verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ide.sandbox import SandboxResult, cleanup_workdir, run_user_strategy
from ..lineage.ids import canonical_json, content_hash


REPLAY_MODULE = "app.research_os.rdp_replay"
REPOSITORY_REPRODUCTION_COMMAND = f"python -m {REPLAY_MODULE}"
REPOSITORY_REPRODUCTION_WORKDIR = "app/backend"
REPOSITORY_REPRODUCTION_RUNNER_REF = "backend_runner:rdp_replay:v1"
# Compatibility names kept local to the new module.  Integration code should
# prefer the explicit REPOSITORY_* constants above.
REPRODUCIBILITY_COMMAND = REPOSITORY_REPRODUCTION_COMMAND
REPLAY_RUNNER_REF = REPOSITORY_REPRODUCTION_RUNNER_REF
REPLAY_REQUEST_VERSION = "rdp.replay_request.v1"
REPLAY_OBSERVATION_VERSION = "rdp.replay_observation.v1"
REPLAY_FAILURE_VERSION = "rdp.replay_failure.v1"
REPLAY_ARTIFACT_VERSION = "rdp.replay_artifact.v1"
REPLAY_OBSERVATION_PREFIX = "rdp_replay_observation:"

SANDBOX_TIMEOUT_SECONDS = 30.0
PROCESS_TIMEOUT_SECONDS = SANDBOX_TIMEOUT_SECONDS + 10.0
MAX_STRATEGY_BYTES = 1 * 1024 * 1024
MAX_REQUEST_BYTES = MAX_STRATEGY_BYTES + 4096
MAX_RESULT_BYTES = 1 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_HASH16 = re.compile(r"[0-9a-f]{16}\Z")
_FAILURE_CODES = frozenset(
    {
        "invalid_cli_paths",
        "request_not_private",
        "request_too_large",
        "request_malformed",
        "request_fields_invalid",
        "strategy_code_invalid",
        "sandbox_timeout",
        "sandbox_nonzero_exit",
        "sandbox_result_missing_or_malformed",
        "sandbox_result_not_canonical_json",
        "sandbox_internal_error",
        "replay_output_invalid",
        "replay_process_timeout",
        "replay_process_failed",
        "replay_process_emitted_plaintext",
    }
)


def _sha256_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256_json(payload: Any) -> str:
    return _sha256_bytes(canonical_json(payload).encode("utf-8"))


def _strategy_hash(strategy_code: str) -> str:
    return _sha256_bytes(strategy_code.encode("utf-8"))


def _request_payload(strategy_code: str) -> dict[str, Any]:
    return {
        "schema_version": REPLAY_REQUEST_VERSION,
        "strategy_code": strategy_code,
    }


def _request_bytes(strategy_code: str) -> bytes:
    return canonical_json(_request_payload(strategy_code)).encode("utf-8")


def _reject_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _strict_json_loads(payload: bytes) -> Any:
    return json.loads(
        payload.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_object,
        parse_constant=_reject_json_constant,
    )


def reproduction_artifact_hash(emitted_result: Mapping[str, Any]) -> str:
    """Return the full digest derived from the actual emitted result.

    This is deliberately independent of caller expectations.  The result body
    participates in the digest but is never copied into the observation file.
    """

    return _sha256_json(
        {
            "artifact_version": REPLAY_ARTIFACT_VERSION,
            "emitted_result": dict(emitted_result),
        }
    )


def replay_argv(request_path: str | Path, output_path: str | Path) -> tuple[str, ...]:
    """Build the only supported executable argv; no command string is accepted."""

    request = Path(request_path).absolute()
    output = Path(output_path).absolute()
    return (
        sys.executable,
        "-m",
        REPLAY_MODULE,
        "--request",
        str(request),
        "--output",
        str(output),
    )


class ReplayExecutionError(RuntimeError):
    """A controlled replay rejection containing no strategy/result plaintext."""

    def __init__(self, code: str) -> None:
        normalized = str(code or "replay_process_failed").strip()
        if normalized not in _FAILURE_CODES:
            normalized = "replay_process_failed"
        self.code = normalized
        super().__init__(normalized)


@dataclass(frozen=True)
class ReplayObservation:
    """Successful observations.  Absence of this object means replay failed."""

    request_sha256: str
    observed_strategy_sha256: str
    observed_source_result_content_hash: str
    observed_result_sha256: str
    observed_artifact_hash: str
    stdout_sha256: str
    stderr_sha256: str
    sandbox_artifact_set_sha256: str
    sandbox_artifact_count: int
    exit_code: int
    timed_out: bool
    duration_ms: int
    evidence_refs: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    residuals: tuple[str, ...] = ()
    observation_ref: str = ""
    runner_ref: str = REPLAY_RUNNER_REF
    schema_version: str = REPLAY_OBSERVATION_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != REPLAY_OBSERVATION_VERSION:
            raise ValueError("unsupported replay observation schema")
        if self.runner_ref != REPLAY_RUNNER_REF:
            raise ValueError("unexpected replay runner")
        for field_name in (
            "request_sha256",
            "observed_strategy_sha256",
            "observed_result_sha256",
            "observed_artifact_hash",
            "stdout_sha256",
            "stderr_sha256",
            "sandbox_artifact_set_sha256",
        ):
            if not _SHA256.fullmatch(str(getattr(self, field_name) or "")):
                raise ValueError(f"{field_name} must be a full SHA-256 digest")
        if not _HASH16.fullmatch(str(self.observed_source_result_content_hash or "")):
            raise ValueError(
                "observed_source_result_content_hash must be the canonical 16-hex content hash"
            )
        if type(self.sandbox_artifact_count) is not int or self.sandbox_artifact_count < 0:
            raise ValueError("sandbox_artifact_count must be a non-negative integer")
        if type(self.exit_code) is not int or self.exit_code != 0:
            raise ValueError("successful replay observation requires exit_code=0")
        if self.timed_out is not False:
            raise ValueError("successful replay observation cannot be timed out")
        if type(self.duration_ms) is not int or self.duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer")
        evidence_refs = tuple(str(item or "").strip() for item in self.evidence_refs)
        expected_evidence_refs = (
            f"rdp_replay_request:{self.request_sha256}",
            f"rdp_replay_strategy:{self.observed_strategy_sha256}",
            f"rdp_replay_result:{self.observed_result_sha256}",
            f"rdp_replay_artifact:{self.observed_artifact_hash}",
            f"rdp_replay_stdout:{self.stdout_sha256}",
            f"rdp_replay_stderr:{self.stderr_sha256}",
            f"rdp_replay_sandbox_artifacts:{self.sandbox_artifact_set_sha256}",
        )
        if evidence_refs and evidence_refs != expected_evidence_refs:
            raise ValueError("replay evidence_refs mismatch")
        object.__setattr__(self, "evidence_refs", expected_evidence_refs)
        if tuple(self.errors):
            raise ValueError("successful replay observation cannot contain errors")
        object.__setattr__(self, "errors", ())
        residuals = tuple(str(item or "").strip() for item in self.residuals)
        expected_residuals = ("local_best_effort_sandbox_not_hardened",)
        if residuals and residuals != expected_residuals:
            raise ValueError("replay residuals mismatch")
        object.__setattr__(self, "residuals", expected_residuals)
        supplied = str(self.observation_ref or "").strip()
        expected = REPLAY_OBSERVATION_PREFIX + _sha256_json(self._identity_payload())
        if supplied and supplied != expected:
            raise ValueError("replay observation_ref mismatch")
        object.__setattr__(self, "observation_ref", expected)

    def _identity_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("observation_ref", None)
        return payload

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ReplayObservation":
        expected = {
            "request_sha256",
            "observed_strategy_sha256",
            "observed_source_result_content_hash",
            "observed_result_sha256",
            "observed_artifact_hash",
            "stdout_sha256",
            "stderr_sha256",
            "sandbox_artifact_set_sha256",
            "sandbox_artifact_count",
            "exit_code",
            "timed_out",
            "duration_ms",
            "evidence_refs",
            "errors",
            "residuals",
            "observation_ref",
            "runner_ref",
            "schema_version",
        }
        if not isinstance(raw, Mapping) or set(raw) != expected:
            raise ValueError("replay observation fields are not exact")
        return cls(**{key: raw[key] for key in expected})


def _validate_json_value(value: Any, *, depth: int = 0) -> None:
    if depth > 100:
        raise ReplayExecutionError("sandbox_result_not_canonical_json")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ReplayExecutionError("sandbox_result_not_canonical_json")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ReplayExecutionError("sandbox_result_not_canonical_json")
        for item in value.values():
            _validate_json_value(item, depth=depth + 1)
        return
    raise ReplayExecutionError("sandbox_result_not_canonical_json")


def _sandbox_artifact_set_hash(result: SandboxResult) -> str:
    # Names can contain user text, so only their aggregate digest leaves the worker.
    return _sha256_json(sorted(str(name) for name in result.artifacts))


def _observe_strategy(
    strategy_code: str,
    *,
    request_sha256: str,
) -> ReplayObservation:
    """Run one strategy in the existing sandbox and derive observation hashes."""

    sandbox_result: SandboxResult | None = None
    try:
        sandbox_result = run_user_strategy(
            strategy_code,
            timeout_s=SANDBOX_TIMEOUT_SECONDS,
        )
        if sandbox_result.timed_out:
            raise ReplayExecutionError("sandbox_timeout")
        if sandbox_result.exit_code != 0 or sandbox_result.error:
            raise ReplayExecutionError("sandbox_nonzero_exit")
        if not isinstance(sandbox_result.user_result, dict):
            raise ReplayExecutionError("sandbox_result_missing_or_malformed")
        _validate_json_value(sandbox_result.user_result)
        result_bytes = canonical_json(sandbox_result.user_result).encode("utf-8")
        if len(result_bytes) > MAX_RESULT_BYTES:
            raise ReplayExecutionError("sandbox_result_not_canonical_json")
        return ReplayObservation(
            request_sha256=request_sha256,
            observed_strategy_sha256=_strategy_hash(strategy_code),
            observed_source_result_content_hash=content_hash(
                sandbox_result.user_result
            ),
            observed_result_sha256=_sha256_bytes(result_bytes),
            observed_artifact_hash=reproduction_artifact_hash(
                sandbox_result.user_result
            ),
            stdout_sha256=_sha256_bytes(sandbox_result.stdout.encode("utf-8")),
            stderr_sha256=_sha256_bytes(sandbox_result.stderr.encode("utf-8")),
            sandbox_artifact_set_sha256=_sandbox_artifact_set_hash(sandbox_result),
            sandbox_artifact_count=len(sandbox_result.artifacts),
            exit_code=sandbox_result.exit_code,
            timed_out=sandbox_result.timed_out,
            duration_ms=max(0, round(sandbox_result.duration_s * 1000)),
        )
    except ReplayExecutionError:
        raise
    except Exception as exc:  # noqa: BLE001 - worker internals fail closed.
        raise ReplayExecutionError("sandbox_internal_error") from exc
    finally:
        if sandbox_result is not None and sandbox_result.workdir:
            cleanup_workdir(sandbox_result.workdir)


def _load_request(request_path: Path) -> tuple[str, str]:
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(request_path, flags)
    except OSError as exc:
        raise ReplayExecutionError("request_malformed") from exc
    try:
        opened_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_uid != os.getuid()
            or opened_stat.st_nlink != 1
            or opened_stat.st_mode & 0o077
        ):
            raise ReplayExecutionError("request_not_private")
        if opened_stat.st_size > MAX_REQUEST_BYTES:
            raise ReplayExecutionError("request_too_large")
        with os.fdopen(fd, "rb", closefd=False) as handle:
            request_bytes = handle.read(MAX_REQUEST_BYTES + 1)
    finally:
        os.close(fd)
    if len(request_bytes) > MAX_REQUEST_BYTES:
        raise ReplayExecutionError("request_too_large")
    request_sha256 = _sha256_bytes(request_bytes)
    try:
        raw = _strict_json_loads(request_bytes)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ReplayExecutionError("request_malformed") from exc
    expected_fields = {"schema_version", "strategy_code"}
    if not isinstance(raw, dict) or set(raw) != expected_fields:
        raise ReplayExecutionError("request_fields_invalid")
    if raw.get("schema_version") != REPLAY_REQUEST_VERSION:
        raise ReplayExecutionError("request_fields_invalid")
    strategy_code = raw.get("strategy_code")
    if not isinstance(strategy_code, str) or not strategy_code.strip():
        raise ReplayExecutionError("strategy_code_invalid")
    if len(strategy_code.encode("utf-8")) > MAX_STRATEGY_BYTES:
        raise ReplayExecutionError("strategy_code_invalid")
    return strategy_code, request_sha256


def _validate_cli_paths(request_path: Path, output_path: Path) -> None:
    if not request_path.is_absolute() or not output_path.is_absolute():
        raise ReplayExecutionError("invalid_cli_paths")
    if request_path.parent.resolve() != output_path.parent.resolve():
        raise ReplayExecutionError("invalid_cli_paths")
    try:
        parent_stat = request_path.parent.stat()
    except OSError as exc:
        raise ReplayExecutionError("invalid_cli_paths") from exc
    if (
        not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or parent_stat.st_mode & 0o077
    ):
        raise ReplayExecutionError("request_not_private")
    try:
        request_stat = request_path.lstat()
    except OSError as exc:
        raise ReplayExecutionError("invalid_cli_paths") from exc
    if not stat.S_ISREG(request_stat.st_mode) or request_path.is_symlink():
        raise ReplayExecutionError("invalid_cli_paths")
    if request_stat.st_mode & 0o077:
        raise ReplayExecutionError("request_not_private")
    if output_path.exists() or output_path.is_symlink():
        raise ReplayExecutionError("invalid_cli_paths")


def _safe_request_digest(request_path: Path) -> str:
    fd: int | None = None
    try:
        parent_stat = request_path.parent.stat()
        if (
            not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_uid != os.getuid()
            or parent_stat.st_mode & 0o077
        ):
            return ""
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(request_path, flags)
        opened_stat = os.fstat(fd)
        if (
            not stat.S_ISREG(opened_stat.st_mode)
            or opened_stat.st_uid != os.getuid()
            or opened_stat.st_nlink != 1
            or opened_stat.st_mode & 0o077
            or opened_stat.st_size > MAX_REQUEST_BYTES
        ):
            return ""
        with os.fdopen(fd, "rb", closefd=False) as handle:
            payload = handle.read(MAX_REQUEST_BYTES + 1)
        return _sha256_bytes(payload) if len(payload) <= MAX_REQUEST_BYTES else ""
    except OSError:
        return ""
    finally:
        if fd is not None:
            os.close(fd)


def _failure_document(code: str, request_path: Path) -> dict[str, Any]:
    request_sha256 = _safe_request_digest(request_path)
    return {
        "schema_version": REPLAY_FAILURE_VERSION,
        "runner_ref": REPLAY_RUNNER_REF,
        "failure_code": code if code in _FAILURE_CODES else "replay_process_failed",
        "request_sha256": request_sha256,
        "evidence_refs": (
            [f"rdp_replay_request:{request_sha256}"] if request_sha256 else []
        ),
        "errors": [code if code in _FAILURE_CODES else "replay_process_failed"],
        "residuals": ["local_best_effort_sandbox_not_hardened"],
    }


def _write_exclusive_json(output_path: Path, payload: Mapping[str, Any]) -> None:
    encoded = canonical_json(dict(payload)).encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise ReplayExecutionError("replay_output_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(output_path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def _run_cli(request_path: Path, output_path: Path) -> int:
    try:
        _validate_cli_paths(request_path, output_path)
        strategy_code, request_sha256 = _load_request(request_path)
        observation = _observe_strategy(
            strategy_code,
            request_sha256=request_sha256,
        )
        _write_exclusive_json(output_path, observation.to_dict())
        return 0
    except ReplayExecutionError as exc:
        # A path rejection can make output unsafe/unavailable.  Never fall back
        # to stdout/stderr because either stream could cross a secret boundary.
        try:
            if (
                request_path.is_absolute()
                and output_path.is_absolute()
                and request_path.parent.resolve() == output_path.parent.resolve()
                and not output_path.exists()
                and not output_path.is_symlink()
            ):
                _write_exclusive_json(
                    output_path,
                    _failure_document(exc.code, request_path),
                )
        except Exception:  # noqa: BLE001 - original rejection remains authoritative.
            pass
        return 2
    except Exception:  # noqa: BLE001 - no traceback/plaintext may escape the worker.
        return 3


def _private_write(path: Path, payload: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def _load_output(path: Path) -> Mapping[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ReplayExecutionError("replay_output_invalid") from exc
    if len(payload) > MAX_OUTPUT_BYTES:
        raise ReplayExecutionError("replay_output_invalid")
    try:
        raw = _strict_json_loads(payload)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ReplayExecutionError("replay_output_invalid") from exc
    if not isinstance(raw, Mapping):
        raise ReplayExecutionError("replay_output_invalid")
    return raw


def run_replay_subprocess(strategy_code: str) -> ReplayObservation:
    """Execute the fixed repository replay command in a private temp directory."""

    if not isinstance(strategy_code, str) or not strategy_code.strip():
        raise ReplayExecutionError("strategy_code_invalid")
    request_bytes = _request_bytes(strategy_code)
    if len(request_bytes) > MAX_REQUEST_BYTES:
        raise ReplayExecutionError("strategy_code_invalid")

    with tempfile.TemporaryDirectory(prefix="qbt-rdp-replay-") as temp_name:
        temp_root = Path(temp_name)
        request_path = temp_root / "request.json"
        output_path = temp_root / "observation.json"
        _private_write(request_path, request_bytes)
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(temp_root),
            "TMPDIR": str(temp_root),
            "LANG": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8",
        }
        try:
            completed = subprocess.run(
                replay_argv(request_path, output_path),
                cwd=str(_BACKEND_ROOT),
                env=env,
                capture_output=True,
                text=False,
                timeout=PROCESS_TIMEOUT_SECONDS,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReplayExecutionError("replay_process_timeout") from exc
        if completed.stdout or completed.stderr:
            raise ReplayExecutionError("replay_process_emitted_plaintext")
        raw = _load_output(output_path)
        if completed.returncode != 0:
            failure_code = str(raw.get("failure_code") or "")
            raise ReplayExecutionError(failure_code)
        try:
            observation = ReplayObservation.from_dict(raw)
        except (TypeError, ValueError) as exc:
            raise ReplayExecutionError("replay_output_invalid") from exc
        if observation.request_sha256 != _sha256_bytes(request_bytes):
            raise ReplayExecutionError("replay_output_invalid")
        if observation.observed_strategy_sha256 != _strategy_hash(strategy_code):
            raise ReplayExecutionError("replay_output_invalid")
        return observation


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    return _run_cli(Path(args.request), Path(args.output))


if __name__ == "__main__":  # pragma: no cover - exercised by subprocess tests.
    raise SystemExit(main())


__all__ = [
    "PROCESS_TIMEOUT_SECONDS",
    "REPLAY_ARTIFACT_VERSION",
    "REPLAY_MODULE",
    "REPLAY_OBSERVATION_VERSION",
    "REPLAY_REQUEST_VERSION",
    "REPLAY_RUNNER_REF",
    "REPOSITORY_REPRODUCTION_COMMAND",
    "REPOSITORY_REPRODUCTION_RUNNER_REF",
    "REPOSITORY_REPRODUCTION_WORKDIR",
    "REPRODUCIBILITY_COMMAND",
    "ReplayExecutionError",
    "ReplayObservation",
    "replay_argv",
    "reproduction_artifact_hash",
    "run_replay_subprocess",
]
