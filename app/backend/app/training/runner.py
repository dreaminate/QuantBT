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


# ── §15 子进程 artifact 信任门启动钩子（C-MODELGOV-1·自由代码 / DL 子进程路）─────────────
# W1（6144bd61）只在【主进程】组合消费侧（service._apply_input_models）显式传 trust= enforce；
# 自由代码 / DL 子进程内用户代码若【自调】 predict_with / load_model（trust 默认=None），子进程的
# 进程级默认策略未被 configure → enforce=False → §15「外来 pickle 默认 block」该路未兑现（残余①）。
#
# 修法（扩展不替换·零改门语义）：上游（service）注入 QUANTBT_TRUST_ROOT 时，不直接跑用户脚本，
# 而经本 launcher 起子进程——启动期先 `configure_default_trust(同源 store + enforce 继承自主进程)`，
# 再用 `runpy` 把【真训练脚本】当 __main__ 跑。于是子进程内 `predict_with(trust=None)` 取到的进程默认
# 策略已 enforce，加载未登记 / 外来 artifact 在 load 处被硬拒（§15）。
#
# 诚实边界：
# - **未注入 QUANTBT_TRUST_ROOT → 不写 launcher、逐字原行为**（直接跑 train_script.py·向后兼容，
#   既有 run_code 直接调用方一字不受影响）。
# - `runpy.run_path(run_name="__main__")`：用户脚本仍作顶层 __main__ 跑——`from __future__` 必须置顶、
#   `if __name__ == "__main__"` 守卫、`sys.argv[0]` 均保持原义（runpy 临时改 argv[0] 为脚本路径后复原），
#   **不前插 / 不改写一字用户代码**（避免 prepend 破 `from __future__` 置顶约束）。
# - 这【不是沙箱牢笼】：子进程仍全功率（GPU / 网络 / 本地数据湖）。本钩子只设【artifact 加载来源默认】，
#   不限制算力——与 runner「把脚本跑起来」的定位一致；信任门语义全在 artifact_trust（本文件零改门语义）。
_TRUST_BOOTSTRAP = '''import os
import runpy

from app.training.artifact_trust import (
    TrustPolicy,
    configure_default_trust,
    store_under,
)

# 启动期翻开子进程进程级默认信任策略：同源 store（跨进程 JSONL 共享）+ enforce 继承自主进程。
# QUANTBT_TRUST_ROOT 由 service 注入（= TrainingService._root），与主进程消费侧 store_under(self._root)
# 解析到【同一】 on-disk 信任账 → producer 登记的系统自产 artifact 子进程可见、外来未登记被拒。
_trust_root = os.environ.get("QUANTBT_TRUST_ROOT")
if _trust_root:
    _enforce = os.environ.get("QUANTBT_TRUST_ENFORCE", "1") == "1"
    configure_default_trust(TrustPolicy(store=store_under(_trust_root), enforce=_enforce))

# 把【真训练脚本】当 __main__ 跑（用户/生成代码一字不改；from __future__ / __main__ 守卫保持原义）。
runpy.run_path(os.environ["QUANTBT_USER_SCRIPT"], run_name="__main__")
'''


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
    """落盘 → 全功率子进程执行 → 解析 emit。

    §15 子进程信任门钩子：上游（service）注入 ``QUANTBT_TRUST_ROOT`` 时，经 trust-bootstrap
    launcher 起子进程（启动期 configure_default_trust·同源 store + enforce 继承），再 runpy 真脚本，
    使子进程内 ``predict_with`` / ``load_model``（trust 默认）也过信任门；未注入 → 逐字原行为（向后兼容）。
    """
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

    # §15 子进程信任门启动钩子：上游注入信任根 → 经 trust-bootstrap launcher 起子进程（启动期
    # configure enforce·同源 store 后 runpy 真脚本）；未注入 → entry 仍是 train_script.py（逐字原行为）。
    entry = script
    if env.get("QUANTBT_TRUST_ROOT"):
        launcher = job_dir / "_run_with_trust.py"
        launcher.write_text(_TRUST_BOOTSTRAP, encoding="utf-8")
        env["QUANTBT_USER_SCRIPT"] = str(script)
        entry = launcher

    try:
        proc = subprocess.run(
            [sys.executable, str(entry)],
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
