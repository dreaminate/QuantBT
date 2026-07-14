from __future__ import annotations

from .run_detail_core import (
    artifact_download_path,
    compare_runs,
    delete_run,
    export_path,
    get_run_attribution,
    get_run_detail,
    get_run_logs,
    get_run_source,
    list_runs,
    load_compare_series_response,
    load_series_response,
    load_table_response,
    query_runs,
)


def list_runs_response() -> list[dict]:
    return list_runs()


def get_run_response(run_id: str) -> dict:
    return get_run_detail(run_id)


def get_run_series_response(run_id: str, series: str, segment: str = "overall") -> dict:
    return load_series_response(run_id, series, segment)


def query_runs_response(
    payload: dict,
    *,
    allowed_run_ids: set[str] | None = None,
    source_rows: list[dict] | None = None,
) -> dict:
    return query_runs(
        payload,
        allowed_run_ids=allowed_run_ids,
        source_rows=source_rows,
    )


def delete_run_response(
    run_id: str,
    *,
    expected_file_hashes: dict[str, str] | None = None,
    expected_directory_identity: tuple[int, int] | None = None,
) -> None:
    delete_run(
        run_id,
        expected_file_hashes=expected_file_hashes,
        expected_directory_identity=expected_directory_identity,
    )


def compare_runs_response(run_ids: list[str]) -> dict:
    return compare_runs(run_ids)


def get_compare_series_response(run_ids: list[str], series: str, segment: str = "overall") -> dict:
    return load_compare_series_response(run_ids, series, segment)


def get_run_table_response(
    run_id: str,
    table_name: str,
    *,
    limit: int = 200,
    offset: int = 0,
    sort: str | None = None,
    order: str = "desc",
    start_ts: str | None = None,
    end_ts: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
) -> dict:
    return load_table_response(
        run_id,
        table_name,
        limit=limit,
        offset=offset,
        sort=sort,
        order=order,
        start_ts=start_ts,
        end_ts=end_ts,
        symbol=symbol,
        side=side,
    )


def get_run_logs_response(run_id: str, limit: int = 500, offset: int = 0) -> dict:
    return get_run_logs(run_id, limit=limit, offset=offset)


def get_run_source_response(run_id: str) -> dict:
    return get_run_source(run_id)


def get_run_attribution_response(run_id: str) -> dict:
    return get_run_attribution(run_id)


__all__ = [
    "artifact_download_path",
    "compare_runs_response",
    "delete_run_response",
    "export_path",
    "get_compare_series_response",
    "get_run_attribution_response",
    "get_run_logs_response",
    "get_run_response",
    "get_run_series_response",
    "get_run_source_response",
    "get_run_table_response",
    "list_runs_response",
    "query_runs_response",
]
