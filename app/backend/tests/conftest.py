"""Make `from app.<module>` work when pytest runs from repo root.

附加：自动隔离 SENTRY_DSN，避免开发机配过的 DSN 让每次跑 pytest 时
sentry-sdk 在结束阶段去发 2 个 pending events、阻塞退出 ~2 秒。
真实想测 sentry 集成的 case 自己 setenv 即可。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 默认 unset SENTRY_DSN —— 单测不该真发数据到 Sentry
os.environ.pop("SENTRY_DSN", None)
