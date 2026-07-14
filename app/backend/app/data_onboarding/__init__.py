"""数据接入编排（GOAL §4/§11/§16）——HS300 真数据证据链生产者。"""

from .hs300_pipeline import (
    CANONICAL_COLUMNS,
    assemble_panel,
    build_chain,
    load_list_dates,
    load_members,
    preflight_report,
    register_panel,
)
from .hs300_provenance import (
    RECEIPT_PAYLOAD_FIELDS,
    RECEIPT_SCHEMA,
    UNIVERSE_PAYLOAD_FIELDS,
    UNIVERSE_REF,
    UNIVERSE_SCHEMA,
    build_receipt_payload,
    build_universe_payload,
    canonical_payload_bytes,
    loaded_panel_sha256,
    sign_payload,
    write_signed_json,
)

__all__ = [
    "CANONICAL_COLUMNS",
    "assemble_panel",
    "build_chain",
    "load_list_dates",
    "load_members",
    "preflight_report",
    "register_panel",
    "RECEIPT_PAYLOAD_FIELDS",
    "RECEIPT_SCHEMA",
    "UNIVERSE_PAYLOAD_FIELDS",
    "UNIVERSE_REF",
    "UNIVERSE_SCHEMA",
    "build_receipt_payload",
    "build_universe_payload",
    "canonical_payload_bytes",
    "loaded_panel_sha256",
    "sign_payload",
    "write_signed_json",
]
