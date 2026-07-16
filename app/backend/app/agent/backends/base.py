"""Backend-agnostic types for the embedded-agent spawn contract (agent M3).

``PermissionTier`` is deliberately user-configurable (核心原则: 放权给 user). The
tiers map onto the CLI's own permission modes; widening a tier only widens the
agent's *CLI* tool latitude (e.g. Bash). It never widens the agent's MCP tool
reach — that is fixed at the no-key server (``app.agent_mcp`` registers exactly
``canvas_read``) and pinned by ``--strict-mcp-config``. So the money/venue
red-line holds structurally across every tier, not by tier restriction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionTier(str, Enum):
    """User-selectable autonomy level → claude ``--permission-mode`` value.

    Values are exactly the CLI's valid choices (claude v2.1.210):
    acceptEdits / auto / bypassPermissions / manual / dontAsk / plan.
    """

    PLAN = "plan"                    # read-only planning; no edits
    STANDARD = "acceptEdits"         # default: edit the workspace, read the canvas
    AUTO = "auto"                    # auto-approve within the sandbox
    AUTONOMOUS = "bypassPermissions"  # user opts into full autonomy (放权)

    @classmethod
    def default(cls) -> "PermissionTier":
        return cls.STANDARD


@dataclass(frozen=True)
class BackendReadiness:
    """Result of a backend ``preflight()`` — is the CLI installed and authed?

    ``ready`` gates a real run. When not ready, ``next_action`` is the exact,
    honest onboarding step (never a silent fallback to an internal agent).
    """

    provider: str
    cli: str
    cli_installed: bool
    authed: bool
    ready: bool
    detail: str

    @property
    def blocking_reason(self) -> str | None:
        return None if self.ready else self.detail
