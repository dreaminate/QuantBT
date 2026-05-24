from __future__ import annotations

from .data_pull import (
    build_data_overview,
    list_data_kind_options,
    list_markets,
    preview_data_file,
    scan_data_files,
)
from .symbol_pools import list_symbol_pools


def get_markets_response() -> list[dict]:
    return list_markets()


def get_data_kinds_response(market: str | None = None) -> list[dict]:
    return list_data_kind_options(market)


def get_data_pools_response(market: str | None = None) -> list[dict]:
    return list_symbol_pools(market)


def get_data_overview_response() -> list[dict]:
    return build_data_overview(scan_data_files())


def get_data_files_response(
    *,
    market: str | None = None,
    interval: str | None = None,
    data_kind: str | None = None,
) -> list[dict]:
    files = scan_data_files()
    if market:
        files = [item for item in files if item["market"] == market]
    if interval:
        files = [item for item in files if item["interval"] == interval]
    if data_kind:
        files = [item for item in files if item["data_kind"] == data_kind]
    return files


def get_data_preview_response(
    *,
    file_id: str | None = None,
    market: str | None = None,
    interval: str | None = None,
    symbol: str | None = None,
    data_kind: str | None = None,
    limit: int = 20,
) -> dict:
    return preview_data_file(
        file_id=file_id,
        market=market,
        interval=interval,
        symbol=symbol,
        data_kind=data_kind,
        limit=limit,
    )
