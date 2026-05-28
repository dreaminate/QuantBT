# PyInstaller spec：把 QuantBT 后端（FastAPI + uvicorn + 全部模块）打成单 binary
#
# 用法：
#   pip install pyinstaller
#   cd <repo root>
#   pyinstaller --clean --noconfirm deploy/quantbt-backend.spec
#
# 产物：dist/quantbt-backend/quantbt-backend (macOS/Linux) 或 .exe (Windows)
#
# 说明：
# - lightgbm / cryptography / keyring / sentry_sdk 必须 collect-all 因为它们用动态加载
# - polars / pyarrow / pandas / sklearn 走 collect-submodules 自动捞
# - secrets.yaml.example 作 data 资源；运行时还是去 ~/.quantbt/ 找用户配置
# - 不打包 frontend；前端用户单独 docker / npm run dev 或访问 deploy/frontend.Dockerfile build 出来的 dist

import sys
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_all,
    collect_submodules,
    collect_data_files,
)

block_cipher = None

ROOT = Path(".").resolve()
BACKEND = ROOT / "app" / "backend"

# 关键依赖：动态加载或资源型，必须 collect-all
DYNAMIC_PACKAGES = ["lightgbm", "cryptography", "keyring", "sentry_sdk"]
hiddenimports: list[str] = []
datas: list = []
binaries: list = []

for pkg in DYNAMIC_PACKAGES:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] WARN collect_all({pkg}) failed: {exc}")

# 标准 ML 栈：submodules + data
for pkg in ("polars", "pyarrow", "pandas", "sklearn", "scipy", "yaml"):
    try:
        hiddenimports += collect_submodules(pkg)
        datas += collect_data_files(pkg)
    except Exception as exc:  # noqa: BLE001
        print(f"[spec] WARN collect_submodules({pkg}) failed: {exc}")

# 我们自己的 backend 包 + 资源
hiddenimports += collect_submodules("app")
datas += [
    (str(ROOT / "deploy" / "secrets.yaml.example"), "deploy"),
    (str(ROOT / "docs"), "docs"),
]

a = Analysis(
    [str(BACKEND / "app" / "main.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["uvicorn", "uvicorn.logging", "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan", "uvicorn.lifespan.on"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="quantbt-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="quantbt-backend",
)
