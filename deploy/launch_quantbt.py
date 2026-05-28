"""PyInstaller entry · launch QuantBT backend on http://127.0.0.1:8000。

PyInstaller 把 main.py 当作 module 收，但 uvicorn 需要 "app.main:app" 字符串路径，
所以再写一个明确的 entrypoint：用 import_module + uvicorn.run。
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    import uvicorn
    from app.main import app  # noqa: F401  确保 app 被收

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
