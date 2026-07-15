"""FastAPI on_event→lifespan 迁移接线牙(种坏必抓)。

原 @app.on_event("startup"/"shutdown") 已弃用,迁移到 _app_lifespan 上下文管理器。
本测锁死:①lifespan 真按 startup→serving→shutdown 顺序驱动两 handler;
②不残留 legacy on_event 注册(MUT:任一 handler 从 lifespan 漏掉、或退回 on_event
装饰器 → 本测红)。
"""

from __future__ import annotations

import asyncio

import app.main as main


def test_app_lifespan_runs_startup_then_shutdown(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(main, "startup_event", lambda: calls.append("startup"))
    monkeypatch.setattr(main, "shutdown_event", lambda: calls.append("shutdown"))

    async def _drive() -> None:
        async with main._app_lifespan(main.app):
            calls.append("serving")

    asyncio.run(_drive())
    # startup 必在进入时、shutdown 必在退出时,顺序钉死
    assert calls == ["startup", "serving", "shutdown"]


def test_no_legacy_on_event_handlers_remain():
    # 迁移到 lifespan 后,Starlette router 的 on_startup/on_shutdown 列表必须为空
    # ——残留任一 @app.on_event 装饰器都会往这两个列表塞回调,本断言红。
    assert main.app.router.on_startup == []
    assert main.app.router.on_shutdown == []


def test_lifespan_is_actually_wired_to_app():
    # 接线牙:app 真的用 _app_lifespan 作 lifespan_context(MUT:构造处删 lifespan=
    # 参数 → router 退回 _DefaultLifespan、app 变无 startup 静默态 → 本断言红)。
    assert main.app.router.lifespan_context is main._app_lifespan


def test_lifespan_runs_shutdown_even_on_serving_error(monkeypatch):
    # serving 阶段异常穿过 → shutdown 仍必须跑(严格等价旧 on_event 无条件 shutdown;
    # MUT:_app_lifespan 去掉 try/finally → shutdown 被跳过、线程泄漏 → 本测红)。
    calls: list[str] = []
    monkeypatch.setattr(main, "startup_event", lambda: calls.append("startup"))
    monkeypatch.setattr(main, "shutdown_event", lambda: calls.append("shutdown"))

    async def _drive() -> None:
        async with main._app_lifespan(main.app):
            raise RuntimeError("serving boom")

    try:
        asyncio.run(_drive())
    except RuntimeError as exc:
        assert "serving boom" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("serving 异常未外传")
    assert calls == ["startup", "shutdown"]  # shutdown 未被跳过


def test_lifespan_propagates_startup_failure(monkeypatch):
    # startup 抛错必须外传(不被 lifespan 吞),否则 boot 失败会被静默成"已启动"假绿。
    def _boom() -> None:
        raise RuntimeError("startup boom")

    monkeypatch.setattr(main, "startup_event", _boom)

    async def _drive() -> None:
        async with main._app_lifespan(main.app):
            pass

    try:
        asyncio.run(_drive())
    except RuntimeError as exc:
        assert "startup boom" in str(exc)
    else:  # pragma: no cover - 只在回归时触发
        raise AssertionError("startup 异常被 lifespan 吞掉 → boot 假绿")
