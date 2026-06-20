"""T-029 · 入口×必经门覆盖矩阵 —— 把「不可绕过」从架构推断升级为结构性回归。

种坏门必抓：新增一个通往晋级/真钱的高危端点却漏接门/鉴权 → AST 审计必抓（+ 探针自检非 no-op）。
与 T-025 的 place_order 调用点扫描（venue 下单 ⊆ 门后路径）互补：本卡守「端点入口层」。
"""

from __future__ import annotations

import ast
from pathlib import Path

import app as app_pkg

MAIN = Path(app_pkg.__file__).resolve().parent / "main.py"

_HIGH_RISK_PATH = (
    "/signals", "/promote", "/approve", "/kill_switch", "/emergency",
    "/subscribe", "/redeem", "/mainnet/", "/place_order", "/upgrade",
)
_GATE_MARKERS = (
    "require_user_dependency", "current_user", "OrderGuard", "enforce_gate",
    "ApprovalGate", "GateRejection", "MAINNET_GUARDS", "check_ip", "KILL_SWITCH",
    ".promote(", "mainnet_guard", "COPY_TRADE_SERVICE", "MODEL_REGISTRY",
)


def _route_endpoints(src: str):
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) \
                    and dec.func.attr in ("post", "get", "put", "delete", "patch") and dec.args:
                a0 = dec.args[0]
                if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                    out.append((a0.value, node.name, ast.get_source_segment(src, node) or ""))
    return out


def test_high_risk_endpoints_have_gate():
    eps = _route_endpoints(MAIN.read_text(encoding="utf-8-sig"))
    assert eps, "未解析到任何端点，扫描失效（防空集假绿）"
    offenders = [
        (path, name) for path, name, body in eps
        if any(h in path for h in _HIGH_RISK_PATH) and not any(m in body for m in _GATE_MARKERS)
    ]
    assert not offenders, f"高危端点缺治理门/鉴权（入口×门覆盖缺口）：{offenders}"
    high = [p for p, _n, _b in eps if any(h in p for h in _HIGH_RISK_PATH)]
    assert len(high) >= 5, f"高危端点过少，疑扫描失效；high={high}"


def test_entrypoint_gate_probe():
    """探针：种一个无门高危端点 → AST 审计必抓（证明非 no-op）。"""
    rogue = (
        '@app.post("/api/copy_trade/signals_rogue")\n'
        'def rogue_publish(payload: dict):\n'
        '    return SignalRelayer().relay(payload)\n'
    )
    eps = _route_endpoints(rogue)
    off = [(p, n) for p, n, b in eps
           if any(h in p for h in _HIGH_RISK_PATH) and not any(m in b for m in _GATE_MARKERS)]
    assert off, "探针：无门高危端点应被抓"
