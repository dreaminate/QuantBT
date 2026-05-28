from __future__ import annotations

from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .agent import (
    AgentRuntime,
    CodeReplicator,
    DevLocalLLM,
    StrategyGoalSlotFiller,
    TOOL_SCHEMA,
    list_llm_status,
    make_llm_client,
)
from .connectors import registry as connector_registry
from .data_center_services import (
    get_data_files_response,
    get_data_kinds_response,
    get_data_overview_response,
    get_data_pools_response,
    get_data_preview_response,
    get_markets_response,
)
from .data_export import estimate_export_size, export_tar_gz_stream
from .data_quality import DatasetRegistry, compute_freshness
from .experiments import ExperimentStore, ModelRegistry, RunStore
from .factor_factory import FactorRegistry, list_operators, register_alpha_lite
from .observability import get_reporter, init_error_reporting
from .jobs import InMemoryJobStore
from .paths import DATA_ROOT, ensure_runtime_dirs
from .risk import KillSwitch, RiskLimits, RiskMonitor
from .security import InMemoryKeystore, KeystoreRecord, SecureKeystore, load_secrets
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
DATASET_REGISTRY = DatasetRegistry(DATA_ROOT / "datasets" / "registry.jsonl")
FACTOR_REGISTRY = FactorRegistry(DATA_ROOT / "factors" / "registry.json")
if not FACTOR_REGISTRY.list():
    register_alpha_lite(FACTOR_REGISTRY)
EXPERIMENT_STORE = ExperimentStore(DATA_ROOT / "experiments")
RUN_STORE = RunStore(DATA_ROOT / "experiments")
MODEL_REGISTRY = ModelRegistry(DATA_ROOT / "experiments")
ERROR_REPORTER = init_error_reporting(DATA_ROOT / "audit" / "errors.jsonl")

# 安全：开发环境用内存 keystore；上线时切换到 keyring/fernet（由 settings 控制）
KEYSTORE = SecureKeystore(InMemoryKeystore())
# 启动时自动读 ~/.quantbt/secrets.yaml（如有），把字段注入 keystore + env
_SECRETS_REPORT = load_secrets(KEYSTORE)
RISK_LIMITS = RiskLimits()
RISK_MONITOR = RiskMonitor(RISK_LIMITS)
KILL_SWITCH = KillSwitch([])  # 实盘 venue 启用时由 settings 注入

AGENT_LLM = DevLocalLLM()
AGENT_SLOT_FILLER = StrategyGoalSlotFiller()
CODE_REPLICATOR = CodeReplicator()


def _agent_runtime() -> AgentRuntime:
    runtime = AgentRuntime(AGENT_LLM)
    # 注册若干 tool handler；正式的 backend 调用由前端继续派发
    runtime.register_tool("strategy_goal.create", lambda _n, args: {"strategy_goal": args})
    runtime.register_tool("factor.run_ic", lambda _n, args: {"queued": True, "args": args})
    runtime.register_tool("code.replicate", lambda _n, args: CODE_REPLICATOR.replicate(args.get("code", ""), args.get("source_dialect", "pandas")).__dict__)
    return runtime


@app.on_event("startup")
def startup_event() -> None:
    ensure_runtime_dirs()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/connectors")
def list_connectors() -> list[dict]:
    """所有已注册的数据 connector（内置 + DIY YAML + 用户上传）。"""
    return connector_registry.describe_all()


@app.get("/api/connectors/health")
def connectors_health() -> list[dict]:
    """对每个 connector 跑一次健康检查；freshness 板用。"""
    return connector_registry.health_all()


@app.get("/api/datasets")
def list_datasets() -> list[dict]:
    """列出所有已注册 dataset_id 与各自最新 version。"""
    out: list[dict] = []
    for did in DATASET_REGISTRY.list_dataset_ids():
        latest = DATASET_REGISTRY.latest(did)
        out.append({"dataset_id": did, "latest_version": latest.to_dict() if latest else None})
    return out


@app.get("/api/datasets/{dataset_id}/versions")
def list_dataset_versions(dataset_id: str) -> list[dict]:
    return [v.to_dict() for v in DATASET_REGISTRY.list_versions(dataset_id)]


@app.get("/api/data/freshness")
def data_freshness(dataset_id: str | None = Query(None), market_kind: str = Query("stocks_cn")) -> list[dict]:
    """对单个 dataset_id 或所有 dataset 给出 green/yellow/red 报告。"""
    ids = [dataset_id] if dataset_id else DATASET_REGISTRY.list_dataset_ids()
    return [compute_freshness(did, market_kind, DATASET_REGISTRY).to_dict() for did in ids]


@app.get("/api/factors/operators")
def list_factor_operators() -> list[dict]:
    """前端因子表达式编辑器 / Agent tool 的算子目录。"""
    return list_operators()


@app.get("/api/factors")
def list_factors() -> list[dict]:
    """全部已注册因子（含 alpha_lite 默认 30 个）。"""
    return [f.to_dict() for f in FACTOR_REGISTRY.list()]


@app.get("/api/factors/{factor_id}")
def get_factor(factor_id: str, version: int | None = Query(None)) -> dict:
    try:
        return FACTOR_REGISTRY.get(factor_id, version).to_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# -------- M12 实验追踪 --------

@app.get("/api/experiments")
def list_experiments() -> list[dict]:
    return [e.to_dict() for e in EXPERIMENT_STORE.list_experiments()]


@app.post("/api/experiments")
def create_experiment(payload: dict = Body(...)) -> dict:
    return EXPERIMENT_STORE.create_experiment(
        name=payload["name"],
        asset_class=payload.get("asset_class", "mixed"),
        description=payload.get("description", ""),
    ).to_dict()


@app.get("/api/experiments/{experiment_id}/runs")
def list_experiment_runs(experiment_id: str) -> list[dict]:
    return [r.to_dict() for r in RUN_STORE.list_runs(experiment_id)]


@app.get("/api/experiment_runs/{run_id}/lineage")
def run_lineage(run_id: str) -> list[dict]:
    try:
        return [r.to_dict() for r in RUN_STORE.lineage(run_id)]
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/models")
def list_models() -> list[str]:
    return MODEL_REGISTRY.list_models()


@app.get("/api/models/{model_id}/versions")
def list_model_versions(model_id: str) -> list[dict]:
    return [v.to_dict() for v in MODEL_REGISTRY.list_versions(model_id)]


@app.post("/api/models/{model_id}/promote")
def promote_model(model_id: str, payload: dict = Body(...)) -> dict:
    try:
        return MODEL_REGISTRY.promote(model_id, int(payload["version"]), payload["stage"]).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# -------- M9.3 安全 / 风控 --------

@app.get("/api/security/keystore")
def list_keystore_names() -> dict[str, Any]:
    return {"backend": KEYSTORE.backend_name, "names": KEYSTORE.list_names()}


@app.post("/api/security/keystore")
def store_keystore_record(payload: dict = Body(...)) -> dict:
    KEYSTORE.store(
        KeystoreRecord(
            name=payload["name"],
            api_key=payload["api_key"],
            api_secret=payload["api_secret"],
            note=payload.get("note", ""),
        )
    )
    return {"stored": payload["name"], "backend": KEYSTORE.backend_name}


@app.get("/api/security/secrets")
def secrets_status() -> dict[str, Any]:
    """返回最近一次 secrets.yaml 加载状态（不回显 key）。"""
    return _SECRETS_REPORT.to_dict()


# ---- mainnet/testnet 网络切换 + 二次确认 ----

_NETWORK_STATE: dict[str, str] = {"binance_network": "testnet", "confirmed_at_utc": ""}


@app.get("/api/security/network")
def get_network() -> dict[str, Any]:
    return {**_NETWORK_STATE, "mode": "live_crypto" if _NETWORK_STATE["binance_network"] == "mainnet" else "paper"}


@app.post("/api/security/network")
def set_network(payload: dict = Body(...)) -> dict[str, Any]:
    """切换 binance_network。mainnet 必须传 acknowledged=true（二次确认）。"""
    import datetime as _dt

    network = payload.get("binance_network", "testnet")
    if network not in {"testnet", "mainnet"}:
        raise HTTPException(400, "binance_network 必须是 testnet 或 mainnet")
    if network == "mainnet" and not payload.get("acknowledged"):
        raise HTTPException(
            400,
            "切到 mainnet 必须传 acknowledged=true 且文案需含 '我已阅读 Binance 安全指南'",
        )
    if network == "mainnet":
        statement = (payload.get("statement") or "").strip()
        if "我已阅读" not in statement and "I have read" not in statement:
            raise HTTPException(400, "statement 必须包含「我已阅读」字样")
    _NETWORK_STATE["binance_network"] = network
    _NETWORK_STATE["confirmed_at_utc"] = _dt.datetime.now(_dt.UTC).isoformat()
    ERROR_REPORTER.report(  # 用 error reporter 顺道写 audit
        Exception(f"network_switch:{network}"),
        {"network": network, "confirmed_at_utc": _NETWORK_STATE["confirmed_at_utc"]},
    ) if False else None  # 不发 sentry；仅留位
    return _NETWORK_STATE


@app.post("/api/security/reload_secrets")
def reload_secrets() -> dict[str, Any]:
    """热加载 ~/.quantbt/secrets.yaml。"""
    global _SECRETS_REPORT
    _SECRETS_REPORT = load_secrets(KEYSTORE)
    return _SECRETS_REPORT.to_dict()


# -------- LLM 配置（UI 直填用） --------

@app.get("/api/llm/status")
def llm_status() -> list[dict]:
    """列出每个 provider 的配置状态（不回显 api_key）。"""
    return list_llm_status(KEYSTORE)


@app.post("/api/llm/configure")
def llm_configure(payload: dict = Body(...)) -> dict[str, Any]:
    """从前端表单接收：provider + api_key + base_url + model，写入 keystore。

    payload 形如：
        {"provider": "anthropic", "api_key": "sk-ant-...", "base_url": "", "model": ""}
    或：
        {"provider": "custom", "api_key": "ollama", "base_url": "http://localhost:11434/v1", "model": "qwen2.5:32b"}
    """
    import json as _json

    provider = payload.get("provider")
    if provider not in {"anthropic", "openai", "qwen", "custom"}:
        raise HTTPException(400, f"unknown provider: {provider}")
    api_key = (payload.get("api_key") or "").strip()
    base_url = (payload.get("base_url") or "").strip()
    model = (payload.get("model") or "").strip()
    if provider == "custom" and not (base_url and model):
        raise HTTPException(400, "custom 必须同时填 base_url 和 model")
    if not api_key and provider != "custom":
        raise HTTPException(400, f"{provider} 必须填 api_key")
    KEYSTORE.store(
        KeystoreRecord(
            name=f"llm_{provider}",
            api_key=api_key or "no-key",
            api_secret=api_key or "no-key",
            note=_json.dumps({"base_url": base_url, "model": model}, ensure_ascii=False),
        )
    )
    return {"configured": provider, "base_url": base_url, "model": model}


@app.get("/api/observability/errors")
def observability_errors() -> dict:
    return ERROR_REPORTER.info_snapshot()


@app.get("/api/jobs/{job_id}/stream")
def stream_job_events(job_id: str):
    """SSE：连上后立即收到 snapshot，每次 progress 改动 push 一条事件，终态自动关闭。"""

    def _sse():
        import json as _json
        for evt in JOB_STORE.stream_job(job_id):
            line = (
                f"event: {evt['event']}\n"
                f"data: {_json.dumps(evt['data'], ensure_ascii=False, default=str)}\n\n"
            )
            yield line.encode("utf-8")
            if evt["event"] in {"done", "error"}:
                return

    return StreamingResponse(_sse(), media_type="text/event-stream")


@app.get("/api/data/export/size")
def data_export_size() -> dict:
    return estimate_export_size(DATA_ROOT)


@app.get("/api/data/export")
def data_export():
    fname = f"quantbt-export-{__import__('datetime').datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz"
    return StreamingResponse(
        export_tar_gz_stream(DATA_ROOT),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.middleware("http")
async def _report_unhandled_exceptions(request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:  # noqa: BLE001
        ERROR_REPORTER.report(exc, {"path": str(request.url.path), "method": request.method})
        raise


@app.post("/api/llm/test")
def llm_test(payload: dict = Body(default_factory=dict)) -> dict[str, Any]:
    """让前端"测试连接"按钮一键 ping LLM provider。"""
    provider = payload.get("provider")
    try:
        client = make_llm_client(provider=provider, keystore=KEYSTORE)
        from .agent import LLMMessage
        resp = client.chat(
            [LLMMessage(role="user", content=payload.get("ping", "回我一句 ok"))],
            tools=None,
            temperature=0.0,
        )
        return {
            "provider": client.provider,
            "ok": True,
            "reply_preview": (resp.content or "")[:200],
        }
    except Exception as exc:  # noqa: BLE001
        return {"provider": provider, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.get("/api/risk/alerts")
def risk_alerts() -> dict[str, Any]:
    return {
        "paused": RISK_MONITOR.paused,
        "alerts": RISK_MONITOR.alerts(),
        "limits": {
            "per_order_max_usdt": RISK_LIMITS.per_order_max_usdt,
            "daily_loss_limit_pct": RISK_LIMITS.daily_loss_limit_pct,
            "daily_order_count_max": RISK_LIMITS.daily_order_count_max,
        },
    }


@app.post("/api/risk/kill_switch")
def trigger_kill_switch(payload: dict = Body(default_factory=dict)) -> dict:
    close = bool(payload.get("close_positions", True))
    return KILL_SWITCH.trigger(close_positions=close)


# -------- M14 Agent --------

@app.get("/api/agent/tools")
def agent_tools() -> dict[str, Any]:
    return {"functions": TOOL_SCHEMA, "llm_provider": AGENT_LLM.provider}


@app.post("/api/agent/chat")
def agent_chat(payload: dict = Body(...)) -> dict[str, Any]:
    user_input = str(payload.get("message", "")).strip()
    if not user_input:
        raise HTTPException(400, "message 不能为空")
    runtime = _agent_runtime()
    turn = runtime.run(user_input)
    return {
        "final_message": turn.final_message,
        "succeeded": turn.succeeded,
        "steps": [s.to_dict() for s in turn.steps],
    }


@app.post("/api/agent/slot_fill")
def agent_slot_fill(payload: dict = Body(...)) -> dict[str, Any]:
    text = str(payload.get("text", ""))
    name = payload.get("name")
    goal = AGENT_SLOT_FILLER.fill(text, name=name)
    return goal.model_dump(mode="json")


@app.post("/api/agent/replicate")
def agent_replicate(payload: dict = Body(...)) -> dict[str, Any]:
    dialect = payload.get("source_dialect", "pandas")
    code = payload.get("code", "")
    report = CODE_REPLICATOR.replicate(code, dialect=dialect)
    return {"dialect": report.dialect, "target_code": report.target_code, "notes": report.notes}


# -------- P3.5 setup 向导状态 --------

@app.get("/api/setup/status")
def setup_status() -> dict[str, Any]:
    """引导式 setup 向导用：告诉前端哪几步还没完成。"""
    import os
    tushare_ok = bool(os.environ.get("TUSHARE_TOKEN"))
    keystore_names = KEYSTORE.list_names()
    demo_run_exists = (DATA_ROOT / "artifacts" / "experiments" / "quant1-demo").exists()
    return {
        "tushare_token_configured": tushare_ok,
        "binance_keystore_configured": any("binance" in n.lower() for n in keystore_names),
        "demo_run_exists": demo_run_exists,
        "factors_count": len(FACTOR_REGISTRY.list()),
        "connectors_count": len(connector_registry.names()),
        "next_step": (
            "configure_tushare" if not tushare_ok
            else "configure_binance" if not keystore_names
            else "run_demo" if not demo_run_exists
            else "ready"
        ),
    }


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
