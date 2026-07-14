from __future__ import annotations

from app.agent.orchestrator.roles import LIVE_CANONICAL_ROLE_TOOLS, ROLE_AGENTS
from app.agent.tool_schema import TOOL_SCHEMA


def _schema_names() -> set[str]:
    return {
        str(item.get("name") or item.get("function", {}).get("name") or "")
        for item in TOOL_SCHEMA
    }


def test_live_canonical_role_tools_are_declared_and_permitted_without_stubs():
    schema_names = _schema_names()
    live_tools = set().union(*LIVE_CANONICAL_ROLE_TOOLS.values())

    assert live_tools
    assert live_tools <= schema_names
    assert "factor.run_ic" not in live_tools
    for role_name, tools in LIVE_CANONICAL_ROLE_TOOLS.items():
        assert tools <= ROLE_AGENTS[role_name].permitted_tools


def test_role_permissions_never_include_money_or_promotion_tools():
    forbidden_markers = ("place_order", "submit_order", "promote", "mainnet", "live_order")
    for role in ROLE_AGENTS.values():
        assert not {
            tool
            for tool in role.permitted_tools
            if any(marker in tool.lower() for marker in forbidden_markers)
        }
