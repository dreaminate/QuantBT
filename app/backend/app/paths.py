from __future__ import annotations

import os
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = Path(os.getenv("BACKTEST_DATA_ROOT") or (PROJECT_ROOT / "data")).resolve()
RUN_ROOT = DATA_ROOT / "artifacts" / "experiments"
SYMBOL_POOLS_DIR = DATA_ROOT / "_symbol_pools"


def ensure_runtime_dirs() -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    SYMBOL_POOLS_DIR.mkdir(parents=True, exist_ok=True)
