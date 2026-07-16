"""Embedded-agent backends: build the spawn contract for a real headless CLI agent.

This package is the ORCHESTRATOR side (runs in the API process). It builds the
argv + spawn env + MCP config that launch an external agent CLI (claude v2.1.210)
whose entire MCP tool reach is the no-key ``app.agent_mcp`` server.

The safety-critical invariant lives in ``claude_backend.build_spawn_env`` (L-C):
the spawned agent's environment is an explicit minimal ALLOWLIST — it never
carries ``QUANTBT_MASTER_KEY`` or any venue/keystore secret. See
dev/research/findings/dreaminate/claude-code-agent-impl-plan-duet-20260716.md §3.
"""
