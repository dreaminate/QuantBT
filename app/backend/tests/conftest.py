"""Make `from app.<module>` work when pytest runs from repo root.

附加：自动隔离 SENTRY_DSN，避免开发机配过的 DSN 让每次跑 pytest 时
sentry-sdk 在结束阶段去发 2 个 pending events、阻塞退出 ~2 秒。
真实想测 sentry 集成的 case 自己 setenv 即可。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 默认 unset SENTRY_DSN —— 单测不该真发数据到 Sentry
os.environ.pop("SENTRY_DSN", None)


def pytest_collection_modifyitems(config, items):
    """默认 skip @pytest.mark.testnet（真打 Binance）；唯有显式 `-m testnet` 才跑。

    v0.9.10 引入 testnet e2e 后，CI/release_check 跑 pytest 不应该触发真发单
    （网络偶发 -2021 / -4183 让 release check flaky）。
    """
    marker_filter = config.getoption("-m", default="") or ""
    if "testnet" in marker_filter:
        return
    skip_testnet = pytest.mark.skip(reason="testnet 真发单测试默认 skip; 跑 pytest -m testnet 触发")
    for item in items:
        if "testnet" in item.keywords:
            item.add_marker(skip_testnet)
