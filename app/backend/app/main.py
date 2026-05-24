from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .data_center_services import (
    get_data_files_response,
    get_data_kinds_response,
    get_data_overview_response,
    get_data_pools_response,
    get_data_preview_response,
    get_markets_response,
)
from .jobs import InMemoryJobStore
from .paths import ensure_runtime_dirs
from .run_detail_services import (
    artifact_download_path,
    compare_runs_response,
    delete_run_response,
    export_path,
    get_compare_series_response,
    get_run_attribution_response,
    get_run_logs_response,
    get_run_response,
    get_run_series_response,
    get_run_source_response,
    get_run_table_response,
    list_runs_response,
    query_runs_response,
)
from .schemas import BinanceFullPullRequest, DataPullRequest, RunQueryRequest


app = FastAPI(title="1Backtest API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

JOB_STORE = InMemoryJobStore()


@app.on_event("startup")
def startup_event() -> None:
    ensure_runtime_dirs()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/data/markets")
def get_markets() -> list[dict]:
    return get_markets_response()


@app.get("/api/data/kinds")
def get_data_kinds(market: str | None = Query(None)) -> list[dict]:
    return get_data_kinds_response(market)


@app.get("/api/data/pools")
def get_data_pools(market: str | None = Query(None)) -> list[dict]:
    return get_data_pools_response(market)


@app.get("/api/data/overview")
def get_data_overview() -> list[dict]:
    return get_data_overview_response()


@app.get("/api/data/files")
def get_data_files(
    market: str | None = Query(None),
    interval: str | None = Query(None),
    data_kind: str | None = Query(None),
) -> list[dict]:
    return get_data_files_response(market=market, interval=interval, data_kind=data_kind)


@app.get("/api/data/preview")
def get_data_preview(
    file_id: str | None = Query(None),
    market: str | None = Query(None),
    interval: str | None = Query(None),
    symbol: str | None = Query(None),
    data_kind: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
) -> dict:
    try:
        return get_data_preview_response(
            file_id=file_id,
            market=market,
            interval=interval,
            symbol=symbol,
            data_kind=data_kind,
            limit=limit,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/jobs")
def list_jobs(
    limit: int = Query(50, ge=1, le=500),
    status: str | None = Query(None),
    job_type: str | None = Query(None),
) -> list[dict]:
    return [job.to_dict() for job in JOB_STORE.list_jobs(limit=limit, status=status, job_type=job_type)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return JOB_STORE.get_job(job_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}") from exc


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict:
    try:
        return JOB_STORE.retry_job(job_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    try:
        return JOB_STORE.cancel_job(job_id).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}") from exc


@app.post("/api/jobs/data/pull")
def create_data_pull_job(request: DataPullRequest) -> dict:
    try:
        return JOB_STORE.create_data_pull_job(request).to_dict()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/data/pull-binance-full")
def create_binance_full_pull_job(request: BinanceFullPullRequest = BinanceFullPullRequest()) -> dict:
    try:
        return JOB_STORE.create_binance_full_pull_job(request).to_dict()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs")
def list_runs() -> list[dict]:
    return list_runs_response()


@app.post("/api/runs/query")
def query_runs(request: RunQueryRequest) -> dict:
    return query_runs_response(request.model_dump())


@app.get("/api/runs/compare")
def compare_runs(run_ids: list[str] = Query(...)) -> dict:
    return compare_runs_response(run_ids)


@app.get("/api/runs/compare/series")
def get_compare_series(
    run_ids: list[str] = Query(...),
    series: str = Query(...),
    segment: str = Query("overall"),
) -> dict:
    return get_compare_series_response(run_ids, series, segment)


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str) -> dict[str, str]:
    try:
        delete_run_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": run_id}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict:
    try:
        return get_run_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/series")
def get_run_series(run_id: str, series: str = Query(...), segment: str = Query("overall")) -> dict:
    try:
        return get_run_series_response(run_id, series, segment)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/tables/{table_name}")
def get_run_table(
    run_id: str,
    table_name: str,
    limit: int = Query(200, ge=1, le=100000),
    offset: int = Query(0, ge=0),
    sort: str | None = Query(None),
    order: str = Query("desc"),
    start_ts: str | None = Query(None),
    end_ts: str | None = Query(None),
    symbol: str | None = Query(None),
    side: str | None = Query(None),
) -> dict:
    try:
        return get_run_table_response(
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
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/logs")
def get_run_logs(run_id: str, limit: int = Query(500, ge=1, le=100000), offset: int = Query(0, ge=0)) -> dict:
    try:
        return get_run_logs_response(run_id, limit=limit, offset=offset)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/source")
def get_run_source(run_id: str) -> dict:
    try:
        return get_run_source_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/attribution")
def get_run_attribution(run_id: str) -> dict:
    try:
        return get_run_attribution_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}/artifacts/{artifact_name}/download")
def download_artifact(run_id: str, artifact_name: str):
    try:
        path = artifact_download_path(run_id, artifact_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path.name}")
    return FileResponse(path, filename=path.name)


@app.get("/api/runs/{run_id}/export/{export_type}")
def export_run(run_id: str, export_type: str):
    try:
        path = export_path(run_id, export_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path.name}")
    return FileResponse(path, filename=f"{run_id}_{path.name}")
