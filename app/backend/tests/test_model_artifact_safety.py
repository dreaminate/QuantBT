"""模型 artifact 安全加载的【对抗式】测试（GOAL §15·致命红线 C-MODELGOV-1 第一刀）。

种已知坏门必抓:外来 pickle / .pt 反序列化任意代码执行(RCE)是 §15「外来 pickle 直接加载→拒」
的命门。原 `load_model` 裸 `pickle.load` + `_predict_dl` `weights_only=False` 是已上线的 RCE 洞;
本测证明受限反序列化拦死 os.system/subprocess/eval 等向量,且不过度拦合法模型类。
"""

from __future__ import annotations

import os
import pickle

import numpy as np
import pytest

from app.training.lib import _safe_pickle_load, load_model


class _EvilSystem:
    def __reduce__(self):
        return (os.system, ("echo PWNED_ARTIFACT_RCE > /dev/null",))


class _EvilEval:
    def __reduce__(self):
        return (eval, ("__import__('os').system('echo x')",))


class _EvilSubprocess:
    def __reduce__(self):
        import subprocess
        return (subprocess.call, (["echo", "x"],))


def _dump(obj, path):
    with open(path, "wb") as fh:
        pickle.dump(obj, fh)


# ── 命门:恶意 pickle 的代码执行向量必被拦 ────────────────────────────────────
def test_malicious_pickle_os_system_blocked(tmp_path):
    p = tmp_path / "evil_os.pkl"
    _dump(_EvilSystem(), p)
    with pytest.raises(pickle.UnpicklingError):
        load_model(p)  # find_class('os'/'posix','system') 被安全门拦


def test_malicious_pickle_eval_blocked(tmp_path):
    p = tmp_path / "evil_eval.pkl"
    _dump(_EvilEval(), p)
    with pytest.raises(pickle.UnpicklingError):
        load_model(p)


def test_malicious_pickle_subprocess_blocked(tmp_path):
    p = tmp_path / "evil_sub.pkl"
    _dump(_EvilSubprocess(), p)
    with pytest.raises(pickle.UnpicklingError):
        load_model(p)


def test_restricted_unpickler_no_side_effect(tmp_path):
    """种坏门后断言无副作用:即使拦截,恶意代码也绝不执行(sentinel 文件不被创建)。"""
    sentinel = tmp_path / "pwned_sentinel"

    class _EvilTouch:
        def __reduce__(self):
            return (os.system, (f"touch {sentinel}",))

    p = tmp_path / "evil_touch.pkl"
    _dump(_EvilTouch(), p)
    with pytest.raises(pickle.UnpicklingError):
        load_model(p)
    assert not sentinel.exists(), "安全门被绕过:恶意 os.system 真执行了(RCE 洞未堵)"


# ── codex 复核补:解释器/调试 gadget 也拦（blocklist 强化）─────────────────────
def test_malicious_pickle_pydoc_gadget_blocked(tmp_path):
    class _EvilPydoc:
        def __reduce__(self):
            import pydoc
            return (pydoc.pipepager, ("x", "echo pwned"))

    p = tmp_path / "evil_pydoc.pkl"
    _dump(_EvilPydoc(), p)
    with pytest.raises(pickle.UnpicklingError):
        load_model(p)


def test_malicious_pickle_webbrowser_gadget_blocked(tmp_path):
    class _EvilWeb:
        def __reduce__(self):
            import webbrowser
            return (webbrowser.get, ("echo pwned %s",))

    p = tmp_path / "evil_web.pkl"
    _dump(_EvilWeb(), p)
    with pytest.raises(pickle.UnpicklingError):
        load_model(p)


# ── 不过度拦截:合法模型对象照常加载 ──────────────────────────────────────────
def test_legit_pickle_still_loads(tmp_path):
    obj = {"coef": np.array([1.0, 2.0, 3.0]), "name": "linreg", "intercept": 0.5}
    p = tmp_path / "ok.pkl"
    _dump(obj, p)
    out = load_model(p)
    assert out["name"] == "linreg"
    assert list(out["coef"]) == [1.0, 2.0, 3.0]
    assert out["intercept"] == 0.5


def test_safe_pickle_load_direct(tmp_path):
    p = tmp_path / "arr.pkl"
    _dump(np.array([1, 2, 3]), p)
    with p.open("rb") as fh:
        out = _safe_pickle_load(fh)
    assert list(out) == [1, 2, 3]
