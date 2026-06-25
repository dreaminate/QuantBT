"""训练台标准库 —— agent/用户生成的训练代码 import 它来跑。

设计：训练台"本质是跑代码"。生成的脚本顶上写
    from app.training.lib import emit, pick_device, predict_with
就能：选设备、把已训练模型的输出当特征（模型组合）、最后 emit 结果回吐给 runner。

**模块级零 torch 导入**：本文件被主进程也会 import（service 用 predict_with）；
torch 只在 `pick_device` 等函数内惰性 import，确保主进程永不加载 torch（避 OMP）。
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .emit import format_emit
# 完整信任门(producer-run + hash binding / 白名单 / safe tensors)。artifact_trust 模块级零 torch
# (torch 只在其 DL loader 内惰性 import),故主进程 import lib 仍不加载 torch。
from . import artifact_trust


# ── Artifact 安全加载（GOAL §15「外来 pickle 默认 block / torch weights_only」· 致命红线）──
# 裸 pickle.load / torch.load(weights_only=False) = 反序列化任意代码执行（外来 artifact 可 RCE）。
# 本次止血：① pickle 经 RestrictedUnpickler 拦已知 RCE gadget 模块 ② torch weights_only=True。
#
# **诚实边界（codex xhigh 复核确认·写硬）**：blocklist【根本不是 safe-pickle】——它只拦一批全局符号
# 解析，拦不住「允许模块内部再 import/exec」「__setstate__/BUILD 状态恢复逻辑」「operator/functools/
# copyreg 组合 gadget」「允许模块的 import-time 副作用」。**唯一可证安全 = 不反序列化外来 artifact**：
# producer-run + artifact hash 命中的【系统自产】artifact 才许加载 + allowlist（非 blocklist）+ DL 走
# safetensors + JSON config。这套（外来默认拒 / hash 信任门 / allowlist / safetensors）= C-MODELGOV-1
# 全卡（已 mint 进 pool）。本止血只降攻击面、堵直球 RCE，绝不声称已完整兑现 §15。绝不静默回落 weights_only=False。
_PICKLE_DANGER_MODULES = frozenset({
    # 直接 RCE / 进程 / 文件 / 动态导入
    "os", "posix", "nt", "subprocess", "sys", "socket", "_socket", "_posixsubprocess",
    "shutil", "importlib", "ctypes", "pty", "commands", "popen2", "platform",
    "runpy", "multiprocessing", "signal", "asyncio", "threading",
    # 传字符串内部 compile/exec 的解释/调试/计时 gadget（codex 补）
    "pydoc", "_pyrepl", "bdb", "pdb", "code", "codeop", "trace", "profile",
    "cProfile", "timeit", "doctest", "webbrowser", "antigravity",
    # marshal=反序列化 code object → 绕模块 blocklist 的码对象 gadget（codex 补·legit 极罕用）
    "marshal",
    # 刻意【不】拦 operator/functools/types/io/codecs：legit sklearn/numpy pickle 会用、误伤面大；
    # 且它们要造成 RCE 仍须经被拦的危险模块/marshal——残余风险由信任门（C-MODELGOV-1）兜，不靠 blocklist。
})
_PICKLE_DANGER_BUILTINS = frozenset({
    "eval", "exec", "compile", "__import__", "open", "input", "breakpoint",
    "getattr", "setattr", "delattr", "globals", "vars", "memoryview",
})


class _RestrictedUnpickler(pickle.Unpickler):
    """阻断外来 pickle 的代码执行向量（os.system / subprocess / eval / exec …）。

    合法模型类（sklearn/numpy/pandas/lightgbm/xgboost/scipy）照常放行；危险模块/内建一律拒。
    """

    def find_class(self, module: str, name: str) -> Any:  # noqa: D401
        root = module.split(".")[0]
        if root in _PICKLE_DANGER_MODULES:
            raise pickle.UnpicklingError(
                f"artifact 安全门:禁止反序列化 {module}.{name}(外来 pickle 代码执行风险·§15)"
            )
        if module == "builtins" and name in _PICKLE_DANGER_BUILTINS:
            raise pickle.UnpicklingError(f"artifact 安全门:禁止 builtins.{name}(代码执行风险·§15)")
        return super().find_class(module, name)


def _safe_pickle_load(fh: Any) -> Any:
    """受限反序列化（替代裸 pickle.load）——堵外来 artifact 的 RCE。"""
    return _RestrictedUnpickler(fh).load()


# ── 完整信任门·pickle 类【白名单】(C-MODELGOV-1 验收 #2:白名单非黑名单) ──────────
# 止血的 _RestrictedUnpickler 是 blocklist(拦【已知坏】,漏【未知新 gadget】);信任门要白名单
# (只放【已知好】可信库根,新类一律默认拒)。**扩展不替换**:_AllowlistUnpickler 继承
# _RestrictedUnpickler → 先过白名单、再过 blocklist(防御纵深,两道并存,止血一行不删)。
# root 粒度【可信库根】白名单;经验探针(真实 sklearn/lightgbm/numpy/scipy 模型 pickle)确证所需 root。
_PICKLE_ALLOWED_MODULE_ROOTS = frozenset({
    "numpy", "scipy", "pandas", "sklearn", "lightgbm", "xgboost",
    "joblib", "collections", "copyreg",
})
# builtins 里【安全】的容器/标量重建符(危险 builtins 仍由继承的 blocklist 拦,见 _PICKLE_DANGER_BUILTINS)。
_PICKLE_ALLOWED_BUILTINS = frozenset({
    "object", "list", "dict", "tuple", "set", "frozenset",
    "bytearray", "bytes", "complex", "int", "float", "str", "bool",
    "type", "slice", "range",
})


class _AllowlistUnpickler(_RestrictedUnpickler):
    """白名单受限反序列化(信任门 enforce 路径)——只放可信库根的类,不在白名单的新类一律拒。

    证明【非靠 blocklist 漏新 gadget】:即便某个类不在 blocklist(blocklist 抓不到),只要它的
    module root 不在白名单 → 仍被拒。继承 _RestrictedUnpickler:白名单放行后仍过 blocklist
    (两道并存·扩展不替换)。
    """

    def find_class(self, module: str, name: str) -> Any:  # noqa: D401
        root = module.split(".")[0]
        permitted = (root in _PICKLE_ALLOWED_MODULE_ROOTS) or (
            module == "builtins" and name in _PICKLE_ALLOWED_BUILTINS
        )
        if not permitted:
            raise pickle.UnpicklingError(
                f"artifact 信任门·白名单未收录 {module}.{name} → 拒(§15·白名单非黑名单,新类默认拒)"
            )
        return super().find_class(module, name)  # 再过 _RestrictedUnpickler blocklist(防御纵深)


def _allowlist_pickle_load(fh: Any) -> Any:
    """白名单反序列化(信任门 enforce 时用)——堵外来 + 只放可信库类。"""
    return _AllowlistUnpickler(fh).load()


def emit(payload: dict[str, Any]) -> None:
    """训练脚本最后一行调用：把结构化结果打到 stdout，runner 解析。"""
    print(format_emit(payload), flush=True)


def pick_device(prefer: str | None = None) -> str:
    """自动选最好的设备：cuda(NVIDIA) → mps(Apple 芯片) → cpu。

    - 环境变量 `QUANTBT_FORCE_DEVICE` 优先（测试/调试用，如强制 cpu）。
    - `prefer` 次之。
    - 仅在此惰性 import torch（本函数只该被 DL 代码在子进程里调用）。
    """
    forced = os.environ.get("QUANTBT_FORCE_DEVICE")
    if forced:
        return forced
    if prefer:
        return prefer
    import torch

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def load_model(artifact_path: str | Path, *, trust: Any = None) -> Any:
    """加载训练好的 ML artifact（`.pkl`/`.joblib` → pickle，树/线性模型）。

    DL 的 `.pt` 不在此加载（需重建网络）；走 `predict_with` 的 DL 分支。

    `trust`（完整信任门，C-MODELGOV-1）：
    - None（默认·向后兼容）→ 只过止血 `_RestrictedUnpickler`（blocklist），不查登记；
    - `ArtifactTrustStore` / `TrustPolicy(enforce=True)` → 来源门开：先 `assert_ok`（未登记 artifact
      直接 raise·验收 #1），再走 `_AllowlistUnpickler`（白名单·验收 #2）。
    """
    p = Path(artifact_path)
    if p.suffix in (".pkl", ".joblib"):
        policy = artifact_trust.resolve_policy(trust)
        policy.assert_ok(p)  # enforce：未登记 / sha256 不命中 → raise（验收 #1）
        loader = _allowlist_pickle_load if policy.enforce else _safe_pickle_load
        with p.open("rb") as fh:
            # enforce → 白名单（#2，新类默认拒）；默认 → 止血 blocklist（向后兼容，行为不变）。
            return loader(fh)   # 受限反序列化·堵外来 pickle RCE（§15·原 pickle.load 是致命洞）
    raise ValueError(f"load_model 仅支持 .pkl/.joblib（DL .pt 请用 predict_with）: {p.suffix}（{p}）")


def predict_with(
    artifact_path: str | Path,
    panel: pd.DataFrame,
    feature_cols: list[str],
    *,
    trust: Any = None,
) -> np.ndarray:
    """**模型组合原语**：拿一个已训练模型对 panel 推理，输出可作为新模型的输入特征。

    支持任意 ML（.pkl）与 DL（.pt / .safetensors）模型，兑现"已训练 ml/dl 模型输出可作新训练输入"：
        panel["model_a_pred"] = predict_with(a_artifact, panel, a_features)

    返回长度恒等于 len(panel)、与 panel 行对齐的一维数组：
    - ML：逐行 predict。
    - DL：按 ckpt 内保存的 lookback/symbol_col 逐标的滑窗预测，每个标的的前 lookback 行
      （无完整窗口）填 NaN，其余按窗口末步对齐到该行。

    `trust`：见 `load_model`（DL 分支同样过信任门：enforce 时未登记 artifact 直接 raise）。
    """
    p = Path(artifact_path)
    if p.suffix in (".pt", ".safetensors"):
        return _predict_dl(p, panel, feature_cols, trust=trust)
    model = load_model(p, trust=trust)
    X = panel[feature_cols]
    return np.asarray(model.predict(X))


def _predict_dl(
    artifact_path: Path, panel: pd.DataFrame, feature_cols: list[str], *, trust: Any = None
) -> np.ndarray:
    """DL .pt/.safetensors 推理，输出对齐到 panel 行（warmup 行 NaN）。

    惰性 import torch（只在真遇到 DL 时）；先设 KMP_DUPLICATE_LIB_OK 防御 OMP 冲突。
    """
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    import torch

    from ..models.dl.architectures import build_network

    artifact_trust.resolve_policy(trust).assert_ok(artifact_path)  # enforce：未登记 → raise（验收 #1·DL）
    # DL 安全加载（验收 #3）：safe tensors(+JSON config) 优先；.pt 走 weights_only=True 且
    # **绝不静默回落 weights_only=False**（含非安全类型 → 显式 raise，见 artifact_trust.load_torch_checkpoint）。
    # ckpt 仅 config(dict)/arch(str)/state_dict(tensors)，均 weights_only 安全类型。
    ckpt = artifact_trust.load_dl_checkpoint(artifact_path)
    cfg = ckpt["config"]
    arch = ckpt["arch"]
    lookback = int(cfg["lookback"])
    n_out = int(cfg["n_outputs"])
    symbol_col = cfg.get("symbol_col", "symbol")
    classes = cfg.get("classes")
    feats = feature_cols or cfg["feature_cols"]

    net = build_network(arch, len(feats), n_out, **(cfg.get("net_hp") or {}))
    net.load_state_dict(ckpt["state_dict"])
    net.eval()

    out = np.full(len(panel), np.nan, dtype=float)
    # 与 trainer._build_sequences 同样的分组规则，但要保留每个窗口对应的 panel 行号
    pos = np.arange(len(panel))

    def _infer_group(idx_rows: np.ndarray) -> None:
        g = panel.iloc[idx_rows]
        if "ts" in g.columns:
            order = np.argsort(g["ts"].to_numpy(), kind="stable")
            idx_rows = idx_rows[order]
            g = panel.iloc[idx_rows]
        arr = g[feats].to_numpy(dtype=np.float32)
        if len(arr) <= lookback:
            return
        windows = np.stack([arr[i - lookback : i] for i in range(lookback, len(arr))])
        with torch.no_grad():
            logits = net(torch.tensor(windows, dtype=torch.float32)).cpu().numpy()
        if classes is not None:  # 分类 → 映射回原始类别标签
            preds = np.asarray(classes, dtype=float)[logits.argmax(axis=1)]
        else:
            preds = logits.reshape(-1)
        out[idx_rows[lookback:]] = preds

    if symbol_col and symbol_col in panel.columns:
        for _, sub in pd.DataFrame({"_g": panel[symbol_col].to_numpy(), "_pos": pos}).groupby("_g", sort=False):
            _infer_group(sub["_pos"].to_numpy())
    else:
        _infer_group(pos)
    return out


__all__ = ["emit", "load_model", "pick_device", "predict_with"]
