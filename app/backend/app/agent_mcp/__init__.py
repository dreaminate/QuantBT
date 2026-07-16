"""No-key MCP surface for the embedded Claude-Code agent (M1 red-line floor).

This package is a SIBLING of ``app.agent`` — deliberately NOT a child.
``app.agent.__init__`` eagerly imports the LLM provider stack, which
transitively loads ``app.security.keystore`` + ``app.security.trading_credentials``.
The embedded agent's MCP server must never carry key material, so it lives
here where the package ``__init__`` cascade stays key-free.

Red-line floor (L-A/L-B, see
dev/research/findings/dreaminate/claude-code-agent-impl-plan-duet-20260716.md §3):
- L-A: the server registers EXACTLY the tools it declares — no venue/key/order tool.
- L-B: importing this package (or ``.server``) must not load keystore / KeyBroker /
  place_order / any venue gateway. Enforced by tests/test_agent_mcp_redline_floor.py.

Keep this ``__init__`` BARE. Do not add convenience re-exports that would
cascade into the key-carrying layers.
"""
