"""Exact row router for server-owned GOAL section 14 lineage policies.

The router is intentionally boring: production must provide one resolver for
every canonical M row, and a row can never fall through to a neighbouring
policy family.  Domain resolution and semantic validation remain in the
row-family policies; this module only enforces complete, exact dispatch.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .platform_coverage import REQUIRED_PLATFORM_ROWS, PlatformCapabilityRecord
from .platform_source_lineage_core import (
    PlatformSourceLineagePolicyResolution,
    PlatformSourceLineagePolicyResolver,
)


def _row(value: Any) -> str:
    raw = str(getattr(value, "value", value) or "")
    row = raw.strip()
    if raw != row or row not in REQUIRED_PLATFORM_ROWS:
        raise ValueError("m_row is not a canonical exact platform row")
    return row


class PlatformSourceLineagePolicyRouter:
    """Dispatch one exact canonical row to its server-owned policy resolver."""

    def __init__(
        self,
        resolvers: Mapping[str, PlatformSourceLineagePolicyResolver],
    ) -> None:
        normalized: dict[str, PlatformSourceLineagePolicyResolver] = {}
        for raw_row, resolver in resolvers.items():
            row = _row(raw_row)
            if row in normalized:
                raise ValueError(f"duplicate platform policy resolver for {row}")
            if not callable(getattr(resolver, "resolve", None)) or not callable(
                getattr(resolver, "semantic_violations", None)
            ):
                raise TypeError(
                    f"platform policy resolver for {row} lacks the required methods"
                )
            normalized[row] = resolver
        missing = tuple(row for row in REQUIRED_PLATFORM_ROWS if row not in normalized)
        extra = tuple(sorted(set(normalized) - set(REQUIRED_PLATFORM_ROWS)))
        if missing or extra:
            raise ValueError(
                "platform policy router requires the exact canonical row set: "
                f"missing={list(missing)}, extra={list(extra)}"
            )
        self._resolvers = normalized

    @property
    def registered_rows(self) -> tuple[str, ...]:
        return tuple(row for row in REQUIRED_PLATFORM_ROWS if row in self._resolvers)

    def resolve(
        self,
        *,
        owner_user_id: str,
        m_row: str,
        anchor_ref: str,
    ) -> PlatformSourceLineagePolicyResolution:
        row = _row(m_row)
        resolution = self._resolvers[row].resolve(
            owner_user_id=owner_user_id,
            m_row=row,
            anchor_ref=anchor_ref,
        )
        if not isinstance(resolution, PlatformSourceLineagePolicyResolution):
            raise TypeError(f"platform policy resolver for {row} returned an invalid result")
        if _row(resolution.m_row) != row:
            raise ValueError(f"platform policy resolver for {row} returned a different row")
        return resolution

    def semantic_violations(
        self,
        resolution: PlatformSourceLineagePolicyResolution,
        *,
        owner_user_id: str,
        business_coverage: Any,
        capability_record: PlatformCapabilityRecord,
        rag_document: Any,
    ) -> tuple[str, ...]:
        if not isinstance(resolution, PlatformSourceLineagePolicyResolution):
            raise TypeError("platform policy resolution is invalid")
        row = _row(resolution.m_row)
        capability_row = _row(capability_record.m_row)
        if capability_row != row:
            raise ValueError("platform policy capability row mismatch")
        return tuple(
            self._resolvers[row].semantic_violations(
                resolution,
                owner_user_id=owner_user_id,
                business_coverage=business_coverage,
                capability_record=capability_record,
                rag_document=rag_document,
            )
            or ()
        )


__all__ = ["PlatformSourceLineagePolicyRouter"]
