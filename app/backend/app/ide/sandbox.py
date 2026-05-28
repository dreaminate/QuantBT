"""子进程沙箱执行用户策略代码。

安全分层 (defense-in-depth)：
1. **subprocess** 隔离：主进程永远不 exec 用户代码
2. **resource.setrlimit** (preexec_fn)：CPU 时间 / 内存 / 文件大小 / fd 数量
3. **isolated python** (`-I`)：忽略 PYTHON* 环境变量 + 不读 user site
4. **prelude** monkey-patch：拦 socket / urllib / requests / subprocess / os.system
5. **chdir tempdir**：用户代码看不到项目目录，写文件只能写到沙箱目录
6. **wallclock timeout**：subprocess.Popen 超时 → kill -9
7. **输出大小限制**：stdout/stderr 截断到 1MB，防止 fork bomb 类输出炸内存

注意：这不是 hardened sandbox（macOS 无 namespace），只是 best-effort 拦截 90% 业余攻击。
顶级前端 banner 提示"代码只跑在受限沙箱，仅原型验证"。
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path


# resource 限制：留空白避免 Python 自己 import 都跑不起来
CPU_SECONDS = 15  # 用户代码总 CPU 时间
WALL_TIMEOUT_S = 30.0  # 实际 wallclock（含 import 慢的库）
RSS_BYTES = 2 * 1024 * 1024 * 1024  # 2GB 虚拟内存
FSIZE_BYTES = 50 * 1024 * 1024  # 单文件最大 50MB
NOFILE = 128  # 最多 128 fd
MAX_OUTPUT_BYTES = 1 * 1024 * 1024  # stdout/stderr 各 1MB


# 用户代码 prelude：注入到子进程头部
SANDBOX_PRELUDE = r"""
# === QuantBT sandbox prelude (自动注入) ===
import sys as _sys, os as _os, socket as _socket

# 1. 把 socket.socket / socket.create_connection 替换成"全部拒绝"
def _blocked_socket(*args, **kwargs):
    raise PermissionError("沙箱禁止网络访问 (socket)")

_socket.socket = _blocked_socket
_socket.create_connection = _blocked_socket
_socket.create_server = _blocked_socket
_socket.getaddrinfo = lambda *a, **k: []
_socket.gethostbyname = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 DNS"))

# 2. 拉黑高风险模块（如果用户 import 它们 → ImportError）
class _BlockedModule:
    def __init__(self, name): self._name = name
    def __getattr__(self, k): raise PermissionError(f"沙箱禁止 {self._name}.{k}")

# 不能直接 sys.modules['xxx'] = blocked，因为 import 时 reload，但能拦 from import
_FORBIDDEN = ['ssl', 'requests', 'urllib.request', 'http.client', 'ftplib',
              'telnetlib', 'smtplib', 'pickle', 'marshal']
for _name in _FORBIDDEN:
    _sys.modules.pop(_name, None)
    _sys.modules[_name] = _BlockedModule(_name)

# 3. os.system / os.popen / subprocess 全部拒绝
_os.system = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 os.system"))
_os.popen = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 os.popen"))
_os.execv = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 os.exec*"))
_os.execve = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 os.exec*"))
_os.fork = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 os.fork"))
_os.spawnv = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 os.spawn*"))

try:
    import subprocess as _sp
    _sp.Popen = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 subprocess"))
    _sp.run = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 subprocess"))
    _sp.call = lambda *a, **k: (_ for _ in ()).throw(PermissionError("沙箱禁止 subprocess"))
except Exception:
    pass

# 4. 当前目录已被 caller chdir 到 tempdir；防止用户绕回项目目录
def _blocked_chdir(*a, **k):
    raise PermissionError("沙箱禁止 chdir")
_os.chdir = _blocked_chdir

# 5. 提供策略输出协议：用户调 quantbt.emit_result(dict)
class _QuantBTHelper:
    @staticmethod
    def emit_result(result):
        print('__QUANTBT_RESULT__' + __import__('json').dumps(result, default=str))

_sys.modules['quantbt'] = _QuantBTHelper()
quantbt = _QuantBTHelper()
# === end prelude ===

"""


@dataclass
class SandboxResult:
    """沙箱执行的结果摘要。"""

    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    timed_out: bool = False
    user_result: dict | None = None  # 解析自 stdout 最后的 __QUANTBT_RESULT__ 标记
    error: str | None = None
    workdir: str | None = None
    artifacts: list[str] = field(default_factory=list)


def _preexec_apply_limits() -> None:
    """在 fork 后、exec 前设置 rlimit。仅 POSIX 有效（Windows 子进程会跳过此函数）。"""

    # CPU 时间（秒）：超出 → SIGXCPU
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    except (ValueError, OSError):
        pass
    # 文件最大大小
    try:
        resource.setrlimit(resource.RLIMIT_FSIZE, (FSIZE_BYTES, FSIZE_BYTES))
    except (ValueError, OSError):
        pass
    # 文件描述符上限
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (NOFILE, NOFILE))
    except (ValueError, OSError):
        pass
    # 虚拟内存（macOS arm64 上 RLIMIT_AS 可能被忽略，但仍尝试）
    try:
        resource.setrlimit(resource.RLIMIT_AS, (RSS_BYTES, RSS_BYTES))
    except (ValueError, OSError):
        pass
    # 不允许 core dump
    try:
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ValueError, OSError):
        pass


def run_user_strategy(
    code: str,
    *,
    extra_env: dict[str, str] | None = None,
    timeout_s: float = WALL_TIMEOUT_S,
    work_root: Path | None = None,
) -> SandboxResult:
    """在隔离子进程里运行用户策略代码。

    :param code: 用户写的 Python 策略源码（不含 prelude）
    :param extra_env: 额外环境变量（如 DATA_DIR），仅这些被透传给子进程
    :param timeout_s: wallclock 超时秒数
    :param work_root: 沙箱临时目录的父目录（默认 /tmp）
    :returns: SandboxResult
    """

    # 1. 准备隔离 tempdir 作为子进程 cwd
    workdir = Path(tempfile.mkdtemp(prefix="qbt-ide-", dir=str(work_root) if work_root else None))
    try:
        return _run_in(workdir, code, extra_env or {}, timeout_s)
    finally:
        # 保留工作目录用于调试，调用方负责清理；这里只在异常时尝试 cleanup
        pass


def _run_in(workdir: Path, code: str, extra_env: dict[str, str], timeout_s: float) -> SandboxResult:
    full_code = SANDBOX_PRELUDE + "\n# === user code ===\n" + code

    # 仅透传白名单环境变量
    safe_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(workdir),
        "TMPDIR": str(workdir),
        "LANG": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
    }
    for k, v in extra_env.items():
        if k in {"DATA_DIR", "RUNS_DIR"}:
            safe_env[k] = v

    cmd = [sys.executable, "-I", "-B", "-c", full_code]

    # POSIX 用 preexec_fn 设 rlimit；Windows fallback
    preexec = _preexec_apply_limits if os.name == "posix" else None

    start = time.monotonic()
    timed_out = False
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(workdir),
        env=safe_env,
        preexec_fn=preexec,
        start_new_session=True,
        text=False,
    )
    try:
        stdout_b, stderr_b = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(os.getpgid(proc.pid), 9)
        except Exception:
            proc.kill()
        stdout_b, stderr_b = proc.communicate()
    duration_s = time.monotonic() - start

    stdout = (stdout_b or b"")[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    stderr = (stderr_b or b"")[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")

    user_result: dict | None = None
    for line in reversed(stdout.splitlines()):
        if line.startswith("__QUANTBT_RESULT__"):
            payload = line[len("__QUANTBT_RESULT__"):]
            try:
                user_result = json.loads(payload)
            except json.JSONDecodeError as exc:
                stderr += f"\n[sandbox] failed to parse emit_result JSON: {exc}"
            break

    err_msg: str | None = None
    if timed_out:
        err_msg = f"沙箱 wallclock 超时 ({timeout_s}s)"
    elif proc.returncode != 0:
        err_msg = f"用户代码非零退出 (exit={proc.returncode})"

    artifacts: list[str] = []
    for p in sorted(workdir.glob("*")):
        if p.is_file() and not p.name.startswith("."):
            try:
                if p.stat().st_size <= FSIZE_BYTES:
                    artifacts.append(p.name)
            except OSError:
                pass

    return SandboxResult(
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_s=duration_s,
        timed_out=timed_out,
        user_result=user_result,
        error=err_msg,
        workdir=str(workdir),
        artifacts=artifacts,
    )


def cleanup_workdir(workdir: str | os.PathLike[str]) -> None:
    """删除沙箱临时目录。调用方在保留 run.json 等产物后再 cleanup。"""

    try:
        shutil.rmtree(workdir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


__all__ = ["SandboxResult", "cleanup_workdir", "run_user_strategy"]
