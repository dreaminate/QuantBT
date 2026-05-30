"""TensorBoard 进程管理 —— DL 训练过程可视化。

本地优先：为某个训练 job 的 tb logdir 起一个 `tensorboard` 子进程(独立端口)，
前端直接 iframe / 打开 `http://127.0.0.1:<port>`（同机直连，避开脆弱的全量反代）。

- 端口动态分配（bind :0 取空闲端口）
- 每 job 一个实例，重复 start 复用
- launcher 可注入，便于无 tensorboard 单测
"""

from __future__ import annotations

import socket
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# launcher(logdir, port) -> Popen-like(有 .poll()/.terminate())
Launcher = Callable[[str, int], object]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _default_launcher(logdir: str, port: int) -> subprocess.Popen:
    import os
    import sys

    env = os.environ.copy()
    env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # 与 torch/conda OpenMP 共存
    return subprocess.Popen(
        [sys.executable, "-m", "tensorboard.main", "--logdir", logdir, "--port", str(port), "--host", "127.0.0.1"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@dataclass
class TBInstance:
    job_id: str
    logdir: str
    port: int
    proc: object

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def alive(self) -> bool:
        poll = getattr(self.proc, "poll", None)
        return poll is None or poll() is None


class TensorBoardManager:
    def __init__(self, launcher: Launcher | None = None) -> None:
        self._launcher = launcher or _default_launcher
        self._instances: dict[str, TBInstance] = {}
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        import importlib.util

        return importlib.util.find_spec("tensorboard") is not None

    def start(self, job_id: str, logdir: str | Path) -> TBInstance:
        logdir = str(logdir)
        if not Path(logdir).exists():
            raise FileNotFoundError(f"TensorBoard logdir 不存在: {logdir}")
        with self._lock:
            inst = self._instances.get(job_id)
            if inst is not None and inst.alive():
                return inst
            port = _free_port()
            proc = self._launcher(logdir, port)
            inst = TBInstance(job_id=job_id, logdir=logdir, port=port, proc=proc)
            self._instances[job_id] = inst
            return inst

    def get(self, job_id: str) -> TBInstance | None:
        with self._lock:  # 与 start()/stop() 共用锁，避免并发 pop/赋值竞态
            inst = self._instances.get(job_id)
            if inst and not inst.alive():
                self._instances.pop(job_id, None)
                return None
            return inst

    def stop(self, job_id: str) -> bool:
        with self._lock:
            inst = self._instances.pop(job_id, None)
        if inst is None:
            return False
        term = getattr(inst.proc, "terminate", None)
        if callable(term):
            term()
        return True

    def list(self) -> list[TBInstance]:
        with self._lock:  # 快照后再判活，避免迭代时被 start()/stop() 改变 size
            snapshot = list(self._instances.values())
        return [i for i in snapshot if i.alive()]


__all__ = ["TBInstance", "TensorBoardManager"]
