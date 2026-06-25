"""IDE · 沙箱 + 策略 CRUD + 运行 落地测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ide.sandbox import run_user_strategy
from app.ide.service import IDEError, IDEService


# ============================================================
# sandbox 单元测试
# ============================================================


def test_sandbox_emit_result():
    r = run_user_strategy("print('hi'); quantbt.emit_result({'a': 1, 'b': 'x'})")
    assert r.exit_code == 0
    assert r.user_result == {"a": 1, "b": "x"}
    assert "hi" in r.stdout


def test_sandbox_blocks_socket():
    r = run_user_strategy(
        "import socket\n"
        "try:\n    socket.socket()\nexcept PermissionError as e:\n    print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_blocks_subprocess():
    r = run_user_strategy(
        "import subprocess\n"
        "try:\n    subprocess.run(['ls'])\nexcept PermissionError:\n    print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_blocks_os_system():
    r = run_user_strategy(
        "import os\n"
        "try:\n    os.system('ls')\nexcept PermissionError:\n    print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_blocks_chdir():
    r = run_user_strategy(
        "import os\n"
        "try:\n    os.chdir('/')\nexcept PermissionError:\n    print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_wallclock_timeout():
    r = run_user_strategy("while True: pass", timeout_s=2.0)
    assert r.timed_out is True
    assert r.duration_s < 5.0


def test_sandbox_nonzero_exit_collected():
    r = run_user_strategy("raise ValueError('oops')")
    assert r.exit_code != 0
    assert "ValueError" in r.stderr
    assert r.error is not None


def test_sandbox_passes_data_dir_env(tmp_path):
    r = run_user_strategy(
        "import os; quantbt.emit_result({'dd': os.environ.get('DATA_DIR')})",
        extra_env={"DATA_DIR": "/tmp/x", "SECRET_KEY": "nope"},
    )
    # DATA_DIR 透传 / SECRET_KEY 不透传
    assert r.user_result == {"dd": "/tmp/x"}


# ============================================================
# IDEService CRUD
# ============================================================


@pytest.fixture
def svc(tmp_path: Path) -> IDEService:
    return IDEService(tmp_path / "ide.db", run_root=tmp_path / "runs")


def test_save_and_get_strategy(svc):
    s = svc.save_strategy("alice", "momentum_v1", "print(1)")
    assert s.owner_username == "alice"
    assert s.name == "momentum_v1"
    fetched = svc.get_strategy("alice", "momentum_v1")
    assert fetched.code == "print(1)"


def test_save_strategy_validates_name(svc):
    with pytest.raises(IDEError):
        svc.save_strategy("alice", "bad name with spaces", "print(1)")


def test_save_strategy_validates_asset_class(svc):
    with pytest.raises(IDEError):
        svc.save_strategy("alice", "x", "print(1)", asset_class="forex")


def test_save_strategy_update_in_place(svc):
    s1 = svc.save_strategy("alice", "v1", "print(1)")
    s2 = svc.save_strategy("alice", "v1", "print(2)")
    assert s1.strategy_id == s2.strategy_id
    assert s2.code == "print(2)"


def test_save_strategy_owner_namespace(svc):
    # 两个用户可以同名
    a = svc.save_strategy("alice", "v1", "print('a')")
    b = svc.save_strategy("bob", "v1", "print('b')")
    assert a.strategy_id != b.strategy_id


def test_list_strategies_only_own(svc):
    svc.save_strategy("alice", "a1", "print(1)")
    svc.save_strategy("alice", "a2", "print(2)")
    svc.save_strategy("bob", "b1", "print(3)")
    assert {x.name for x in svc.list_strategies("alice")} == {"a1", "a2"}
    assert [x.name for x in svc.list_strategies("bob")] == ["b1"]


def test_delete_strategy(svc):
    svc.save_strategy("alice", "v1", "print(1)")
    svc.delete_strategy("alice", "v1")
    with pytest.raises(IDEError):
        svc.get_strategy("alice", "v1")


def test_delete_strategy_missing_404(svc):
    with pytest.raises(IDEError):
        svc.delete_strategy("alice", "nope")


# ============================================================
# IDE run
# ============================================================


def test_run_strategy_emit_result(svc):
    svc.save_strategy("alice", "good", "quantbt.emit_result({'sharpe': 1.5})")
    run = svc.run_strategy("alice", "good")
    assert run.status == "ok"
    assert run.exit_code == 0
    assert "sharpe" in run.result_keys


def test_run_strategy_failure(svc):
    svc.save_strategy("alice", "bad", "raise RuntimeError('boom')")
    run = svc.run_strategy("alice", "bad")
    assert run.status == "failed"
    assert run.error is not None
    assert "RuntimeError" in run.stderr_excerpt or "boom" in run.stderr_excerpt


def test_run_strategy_lists_recent(svc):
    svc.save_strategy("alice", "good", "quantbt.emit_result({'x': 1})")
    svc.run_strategy("alice", "good")
    svc.run_strategy("alice", "good")
    runs = svc.list_runs("alice")
    assert len(runs) == 2
    assert all(r.status == "ok" for r in runs)


def test_get_run_artifact_result(svc):
    svc.save_strategy("alice", "x", "quantbt.emit_result({'ret': 0.1})")
    run = svc.run_strategy("alice", "x")
    art = svc.get_run_artifact(run.run_id, "result")
    assert art["body"] == {"ret": 0.1}


def test_get_run_artifact_stdout(svc):
    svc.save_strategy("alice", "x", "print('hello world'); quantbt.emit_result({})")
    run = svc.run_strategy("alice", "x")
    art = svc.get_run_artifact(run.run_id, "stdout")
    assert "hello world" in art["body"]


def test_get_run_artifact_invalid_kind(svc):
    svc.save_strategy("alice", "x", "quantbt.emit_result({})")
    run = svc.run_strategy("alice", "x")
    with pytest.raises(IDEError):
        svc.get_run_artifact(run.run_id, "binary")


# ============================================================
# 安全审计 pass3 #1 止血：posix_spawn/ctypes 逃逸向量（defense-in-depth·非 hardened）
# ============================================================


def test_sandbox_blocks_posix_spawn():
    """审计实测逃逸向量 os.posix_spawn → prelude 补封（CAUGHT）。MUT（prelude 删 posix_spawn 封禁）→ 真 spawn 无 CAUGHT，红。"""
    r = run_user_strategy(
        "import os\n"
        "try:\n    os.posix_spawn('/bin/echo', ['/bin/echo', 'x'], {})\nexcept PermissionError:\n    print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_blocks_posix_fork():
    """os.posix_fork（若平台有）补封。"""
    r = run_user_strategy(
        "import os\n"
        "if not hasattr(os, 'posix_fork'):\n    print('CAUGHT')\n"
        "else:\n    try:\n        os.posix_fork()\n    except PermissionError:\n        print('CAUGHT')\n",
    )
    assert "CAUGHT" in r.stdout


def test_sandbox_rejects_ctypes_import_via_ast():
    """审计实测逃逸向量 import ctypes → 入口 AST 预检拒（不进子进程）。MUT（去 _scan_forbidden_imports 调用）→ 不拒，红。"""
    r = run_user_strategy("import ctypes\nctypes.CDLL(None)\n")
    assert r.error is not None and "ctypes" in r.error
    assert r.exit_code != 0


def test_sandbox_rejects_ctypes_dunder_import():
    """__import__('ctypes') 字符串形式也被 AST 预检拒（封绕过）。"""
    r = run_user_strategy("m = __import__('ctypes')\n")
    assert r.error is not None and "ctypes" in r.error


def test_sandbox_allows_normal_imports_not_overblocked():
    """不误伤：普通 import（json/math）正常跑（AST 预检只拒 FFI·不影响合法策略）。"""
    r = run_user_strategy("import json, math\nquantbt.emit_result({'ok': math.floor(1.5)})")
    assert r.exit_code == 0 and r.user_result == {"ok": 1}
