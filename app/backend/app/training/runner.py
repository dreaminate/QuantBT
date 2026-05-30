"""代码 runner —— 训练台的心脏：把(生成的)训练脚本当**全功率本地进程**跑。

用户选定"本机全权(Jupyter 式)"：不设资源/import/网络限制，能用 GPU(CUDA/MPS)、
联网下预训练权重、读写本地数据湖。runner 只负责：
- 把代码落成脚本、用当前解释器另起进程跑（与 web 主进程隔离 → 能 kill、不卡服务、
  顺带躲开 torch 的 OpenMP 崩溃）；
- 注入 PYTHONPATH（让脚本能 `import app.*`）+ torch/OMP/MPS 安全环境；
- 抓 stdout 里的 emit_train 回吐。

这不是沙箱牢笼——是"把脚本跑起来"，且正是独立进程才能真正吃满 GPU。
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .emit import parse_emit

# app/backend —— 放进子进程 PYTHONPATH，让生成代码能 import app.*
_BACKEND_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class RunnerResult:
    returncode: int
    stdout: str
    stderr: str
    emit: dict[str, Any] | None
    script_path: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and self.emit is not None


def run_code(
    code: str,
    job_dir: Path,
    *,
    env_extra: dict[str, str] | None = None,
    timeout: float | None = None,
) -> RunnerResult:
    """落盘 → 全功率子进程执行 → 解析 emit。"""
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    script = job_dir / "train_script.py"
    script.write_text(code, encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_BACKEND_ROOT), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    # torch 与 conda MKL 的 OpenMP 共存兜底 + MPS 不支持的算子回落 CPU。
    env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    env.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    env["QUANTBT_JOB_DIR"] = str(job_dir)
    if env_extra:
        env.update(env_extra)

    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(job_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return RunnerResult(
            returncode=-1,
            stdout=exc.stdout or "",
            stderr=f"训练超时({timeout}s)被终止",
            emit=None,
            script_path=str(script),
        )
    return RunnerResult(
        returncode=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        emit=parse_emit(proc.stdout),
        script_path=str(script),
    )


__all__ = ["RunnerResult", "run_code"]
