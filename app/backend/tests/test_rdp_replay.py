from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.ide.sandbox import SandboxResult
from app.lineage.ids import canonical_json, content_hash
from app.research_os import rdp_replay
from app.research_os.rdp_replay import (
    REPLAY_MODULE,
    REPLAY_REQUEST_VERSION,
    REPLAY_RUNNER_REF,
    REPOSITORY_REPRODUCTION_COMMAND,
    REPOSITORY_REPRODUCTION_RUNNER_REF,
    REPOSITORY_REPRODUCTION_WORKDIR,
    REPRODUCIBILITY_COMMAND,
    ReplayExecutionError,
    ReplayObservation,
    replay_argv,
    reproduction_artifact_hash,
    run_replay_subprocess,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def _private_request(path: Path, payload: dict) -> None:
    path.write_text(canonical_json(payload), encoding="utf-8")
    path.chmod(0o600)


def _invoke(tmp_path: Path, strategy_code: str, **extra_request):
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "observation.json"
    payload = {
        "schema_version": REPLAY_REQUEST_VERSION,
        "strategy_code": strategy_code,
        **extra_request,
    }
    _private_request(request_path, payload)
    completed = subprocess.run(
        replay_argv(request_path, output_path),
        cwd=BACKEND_ROOT,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path),
            "TMPDIR": str(tmp_path),
            "LANG": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8",
        },
        capture_output=True,
        text=False,
        timeout=45,
        check=False,
        shell=False,
    )
    output = (
        json.loads(output_path.read_text(encoding="utf-8"))
        if output_path.exists()
        else None
    )
    return completed, output, output_path


def test_repository_replay_command_executes_and_emits_hash_only_evidence(tmp_path):
    strategy_secret = "STRATEGY_SOURCE_MUST_NOT_LEAK"
    result_secret = "EMITTED_RESULT_MUST_NOT_LEAK"
    emitted_result = {
        "equity_curve": [
            {"t": "2026-01-01", "equity": 1.0},
            {"t": "2026-01-02", "equity": 1.1},
        ],
        "private_note": result_secret,
    }
    strategy_code = (
        f"source_marker = {strategy_secret!r}\n"
        f"quantbt.emit_result({emitted_result!r})\n"
    )

    completed, raw, output_path = _invoke(tmp_path, strategy_code)

    assert completed.returncode == 0
    assert completed.stdout == b""
    assert completed.stderr == b""
    assert raw is not None
    observation = ReplayObservation.from_dict(raw)
    rendered = output_path.read_text(encoding="utf-8")
    assert strategy_secret not in rendered
    assert result_secret not in rendered
    assert strategy_code not in rendered
    assert canonical_json(emitted_result) not in rendered
    assert observation.runner_ref == REPLAY_RUNNER_REF
    assert observation.observed_source_result_content_hash == content_hash(emitted_result)
    assert observation.observed_artifact_hash == reproduction_artifact_hash(emitted_result)
    assert observation.observed_artifact_hash.startswith("sha256:")
    assert len(observation.observed_artifact_hash) == len("sha256:") + 64
    assert observation.errors == ()
    assert observation.residuals == ("local_best_effort_sandbox_not_hardened",)
    assert all(strategy_secret not in ref for ref in observation.evidence_refs)
    assert all(result_secret not in ref for ref in observation.evidence_refs)
    assert output_path.stat().st_mode & 0o077 == 0


def test_replay_argv_is_fixed_module_command_and_wrapper_uses_real_subprocess(tmp_path):
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "output.json"
    argv = replay_argv(request_path, output_path)

    assert REPRODUCIBILITY_COMMAND == f"python -m {REPLAY_MODULE}"
    assert REPOSITORY_REPRODUCTION_COMMAND == REPRODUCIBILITY_COMMAND
    assert REPOSITORY_REPRODUCTION_RUNNER_REF == REPLAY_RUNNER_REF
    assert REPOSITORY_REPRODUCTION_WORKDIR == "app/backend"
    assert argv == (
        sys.executable,
        "-m",
        REPLAY_MODULE,
        "--request",
        str(request_path.absolute()),
        "--output",
        str(output_path.absolute()),
    )

    observation = run_replay_subprocess("quantbt.emit_result({'observed': 1})")
    assert observation.observed_source_result_content_hash == content_hash({"observed": 1})
    assert observation.exit_code == 0
    assert observation.timed_out is False


def test_strategy_and_result_mutation_changes_observed_hashes():
    first_code = "quantbt.emit_result({'value': 1})"
    second_code = "quantbt.emit_result({'value': 2})"

    first = run_replay_subprocess(first_code)
    second = run_replay_subprocess(second_code)

    assert first.observed_strategy_sha256 != second.observed_strategy_sha256
    assert (
        first.observed_source_result_content_hash
        != second.observed_source_result_content_hash
    )
    assert first.observed_result_sha256 != second.observed_result_sha256
    assert first.observed_artifact_hash != second.observed_artifact_hash
    assert first.observation_ref != second.observation_ref


def test_strategy_mutation_with_same_result_preserves_result_derived_artifact_hash():
    first = run_replay_subprocess("quantbt.emit_result({'value': 1})")
    second = run_replay_subprocess("marker = 'different source'; quantbt.emit_result({'value': 1})")

    assert first.observed_strategy_sha256 != second.observed_strategy_sha256
    assert (
        first.observed_source_result_content_hash
        == second.observed_source_result_content_hash
    )
    assert first.observed_result_sha256 == second.observed_result_sha256
    assert first.observed_artifact_hash == second.observed_artifact_hash


def test_caller_declared_pass_field_is_rejected_without_execution(tmp_path):
    marker = tmp_path / "must-not-exist"
    strategy_code = f"open({str(marker)!r}, 'w').write('ran')"

    completed, raw, output_path = _invoke(
        tmp_path,
        strategy_code,
        passed=True,
    )

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == b""
    assert raw["failure_code"] == "request_fields_invalid"
    assert raw["schema_version"] == "rdp.replay_failure.v1"
    assert raw["errors"] == ["request_fields_invalid"]
    assert raw["residuals"] == ["local_best_effort_sandbox_not_hardened"]
    assert "passed" not in output_path.read_text(encoding="utf-8")
    assert not marker.exists()


@pytest.mark.parametrize(
    ("strategy_code", "expected_failure", "secret"),
    [
        (
            "raise RuntimeError('NONZERO_SECRET_MUST_NOT_LEAK')",
            "sandbox_nonzero_exit",
            "NONZERO_SECRET_MUST_NOT_LEAK",
        ),
        (
            "print('__QUANTBT_RESULT__not-json-MALFORMED_SECRET')",
            "sandbox_result_missing_or_malformed",
            "MALFORMED_SECRET",
        ),
    ],
)
def test_nonzero_and_malformed_result_fail_without_plaintext(
    tmp_path,
    strategy_code,
    expected_failure,
    secret,
):
    completed, raw, output_path = _invoke(tmp_path, strategy_code)

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == b""
    assert raw["failure_code"] == expected_failure
    assert raw["errors"] == [expected_failure]
    assert raw["residuals"] == ["local_best_effort_sandbox_not_hardened"]
    assert secret not in output_path.read_text(encoding="utf-8")
    assert "strategy_code" not in raw
    assert "result" not in raw


def test_timeout_fails_and_cleans_sandbox_workdir(monkeypatch, tmp_path):
    sandbox_dir = tmp_path / "sandbox-workdir"
    sandbox_dir.mkdir()

    def timed_out(*_args, **_kwargs):
        return SandboxResult(
            exit_code=-9,
            stdout="TIMEOUT_STDOUT_SECRET",
            stderr="TIMEOUT_STDERR_SECRET",
            duration_s=30.0,
            timed_out=True,
            user_result=None,
            error="timeout",
            workdir=str(sandbox_dir),
        )

    monkeypatch.setattr(rdp_replay, "run_user_strategy", timed_out)

    with pytest.raises(ReplayExecutionError, match="sandbox_timeout") as caught:
        rdp_replay._observe_strategy(
            "while True: pass",
            request_sha256="sha256:" + "0" * 64,
        )

    assert caught.value.code == "sandbox_timeout"
    assert not sandbox_dir.exists()
    assert "TIMEOUT_STDOUT_SECRET" not in str(caught.value)
    assert "TIMEOUT_STDERR_SECRET" not in str(caught.value)


def test_outer_replay_process_timeout_fails_closed(monkeypatch):
    def process_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(rdp_replay.subprocess, "run", process_timeout)

    with pytest.raises(ReplayExecutionError, match="replay_process_timeout") as caught:
        run_replay_subprocess("quantbt.emit_result({'value': 1})")

    assert caught.value.code == "replay_process_timeout"


def test_mutated_observation_is_rejected_by_content_reference():
    observation = run_replay_subprocess("quantbt.emit_result({'value': 1})")
    tampered = observation.to_dict()
    tampered["observed_artifact_hash"] = "sha256:" + "f" * 64

    with pytest.raises(ValueError, match="mismatch"):
        ReplayObservation.from_dict(tampered)


def test_request_must_be_private_and_output_is_never_overwritten(tmp_path):
    request_path = tmp_path / "request.json"
    output_path = tmp_path / "observation.json"
    request_path.write_text(
        canonical_json(
            {
                "schema_version": REPLAY_REQUEST_VERSION,
                "strategy_code": "quantbt.emit_result({'value': 1})",
            }
        ),
        encoding="utf-8",
    )
    request_path.chmod(0o644)
    output_path.write_text("existing", encoding="utf-8")

    completed = subprocess.run(
        replay_argv(request_path, output_path),
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=False,
        timeout=10,
        check=False,
        shell=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == b""
    assert completed.stderr == b""
    assert output_path.read_text(encoding="utf-8") == "existing"
