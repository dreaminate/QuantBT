"""DL 训练代码（纯 torch 自实现）。

只在隔离全功率子进程里被 import（torch 在此 OK）；torch 惰性加载，
本包被主进程 import 时不触发 torch。加架构见 architectures.py。
"""

from __future__ import annotations

__all__ = ["available_architectures", "build_network", "train_dl"]


def __getattr__(name: str):  # 惰性转发，避免 import 包时加载 torch
    if name == "train_dl":
        from .trainer import train_dl

        return train_dl
    if name in ("build_network", "available_architectures"):
        from . import architectures

        return getattr(architectures, name)
    raise AttributeError(name)
