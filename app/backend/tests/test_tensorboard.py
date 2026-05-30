"""TensorBoard 管理器 + REST 端点测试（注入 fake launcher，无需真 TB）。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.training.tensorboard import TensorBoardManager

client = TestClient(app)


class _FakeProc:
    def __init__(self) -> None:
        self._dead = False

    def poll(self):
        return 0 if self._dead else None

    def terminate(self) -> None:
        self._dead = True


def test_manager_start_reuse_stop(tmp_path: Path) -> None:
    launched: list[tuple[str, int]] = []

    def launcher(logdir: str, port: int):
        launched.append((logdir, port))
        return _FakeProc()

    mgr = TensorBoardManager(launcher=launcher)
    logdir = tmp_path / "tb"
    logdir.mkdir()

    inst = mgr.start("job1", logdir)
    assert inst.url.startswith("http://127.0.0.1:")
    assert inst.port > 0
    assert len(launched) == 1

    # 重复 start 复用，不再起新进程
    inst2 = mgr.start("job1", logdir)
    assert inst2.port == inst.port
    assert len(launched) == 1

    assert mgr.get("job1") is not None
    assert mgr.stop("job1") is True
    assert mgr.get("job1") is None
    assert mgr.stop("job1") is False


def test_manager_missing_logdir(tmp_path: Path) -> None:
    mgr = TensorBoardManager(launcher=lambda d, p: _FakeProc())
    try:
        mgr.start("j", tmp_path / "nope")
        assert False, "应抛 FileNotFoundError"
    except FileNotFoundError:
        pass


def test_manager_dead_proc_cleaned(tmp_path: Path) -> None:
    proc = _FakeProc()
    mgr = TensorBoardManager(launcher=lambda d, p: proc)
    (tmp_path / "tb").mkdir()
    mgr.start("j", tmp_path / "tb")
    proc.terminate()  # 模拟进程退出
    assert mgr.get("j") is None  # 自动清理


def test_endpoint_status_no_instance() -> None:
    body = client.get("/api/training/jobs/ghost/tensorboard").json()
    assert body["running"] is False
    assert "available" in body


def test_endpoint_start_unknown_job() -> None:
    r = client.post("/api/training/jobs/ghost/tensorboard")
    # 未装 tensorboard → 400；装了 → 404(job 不存在)。两者都非 200。
    assert r.status_code in (400, 404)
