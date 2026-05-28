from __future__ import annotations

from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query
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
from .auth import AuthError, AuthService, current_user_dependency, require_user_dependency
from .auth.service import set_service as set_auth_service
from .community import CommunityService
from .connectors import registry as connector_registry
from .copy_trade import CopyTradeError, CopyTradeService, SignalRelayer
from .ide import IDEError, IDEService
from .ide.service import run_to_dict, strategy_to_dict
from .sharing import SharingService
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

# 社区 / Auth / Sharing 共享同一 sqlite
_COMMUNITY_DB = DATA_ROOT / "community.db"
AUTH_SERVICE = AuthService(_COMMUNITY_DB)
set_auth_service(AUTH_SERVICE)
COMMUNITY_SERVICE = CommunityService(_COMMUNITY_DB)
SHARING_SERVICE = SharingService(_COMMUNITY_DB, DATA_ROOT / "artifacts" / "experiments")
COPY_TRADE_SERVICE = CopyTradeService(_COMMUNITY_DB)
IDE_SERVICE = IDEService(DATA_ROOT / "ide_strategies.db", run_root=DATA_ROOT / "ide_runs")


def _binance_venue_for_follower(follower, keystore):
    """生产 venue factory：follower 自己 keystore 名字 → BinanceSpot/UMFuturesVenue。

    实际生产用；测试中由 mock factory 替代。
    """
    from .execution.binance_client import BinanceClient, BinanceCredentials
    try:
        record = keystore.fetch(follower.binance_keystore_name)
    except Exception:  # noqa: BLE001
        return None
    network = follower.binance_network if follower.binance_network in {"testnet", "mainnet"} else "testnet"
    cred = BinanceCredentials(api_key=record.api_key, api_secret=record.api_secret, network=network)
    # crypto_perp → USDM；crypto_spot → spot；equity_cn 不联实盘
    master = COPY_TRADE_SERVICE.get_master(follower.master_id)
    if master is None:
        return None
    if master.asset_class == "crypto_perp":
        from .execution.binance_um_futures import BinanceUMFuturesVenue
        client = BinanceClient(cred, product="usdm_futures")
        venue = BinanceUMFuturesVenue(client)
        return venue
    if master.asset_class == "crypto_spot":
        from .execution.binance_spot import BinanceSpotVenue
        client = BinanceClient(cred, product="spot")
        venue = BinanceSpotVenue(client)
        return venue
    return None  # equity_cn 等不联实盘

# 安全：开发环境用内存 keystore；上线时切换到 keyring/fernet（由 settings 控制）
KEYSTORE = SecureKeystore(InMemoryKeystore())
# 启动时自动读 ~/.quantbt/secrets.yaml（如有），把字段注入 keystore + env
_SECRETS_REPORT = load_secrets(KEYSTORE)
RISK_LIMITS = RiskLimits()
RISK_MONITOR = RiskMonitor(RISK_LIMITS)
KILL_SWITCH = KillSwitch([])  # 实盘 venue 启用时由 settings 注入

AGENT_SLOT_FILLER = StrategyGoalSlotFiller()
CODE_REPLICATOR = CodeReplicator()


def _current_agent_llm():
    """按 keystore + env 选最优 provider；都失败 fallback DevLocalLLM。
    不缓存 client，让 secrets 热加载立即生效。"""
    return make_llm_client(keystore=KEYSTORE)


# 启动时探一次，仅用于 /api/agent/tools status 显示
AGENT_LLM = _current_agent_llm()


def _agent_runtime() -> AgentRuntime:
    runtime = AgentRuntime(_current_agent_llm())
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


# =============== AUTH ===============

@app.post("/api/auth/register")
def auth_register(payload: dict = Body(...)) -> dict[str, Any]:
    try:
        user = AUTH_SERVICE.register(
            username=payload["username"],
            password=payload["password"],
            display_name=payload.get("display_name", ""),
        )
        _u, token = AUTH_SERVICE.login(payload["username"], payload["password"])
        return {"user": user.to_dict(), "token": token}
    except AuthError as exc:
        raise HTTPException(400, str(exc))
    except KeyError as exc:
        raise HTTPException(400, f"缺少字段: {exc}")


@app.post("/api/auth/login")
def auth_login(payload: dict = Body(...)) -> dict[str, Any]:
    try:
        user, token = AUTH_SERVICE.login(payload.get("username", ""), payload.get("password", ""))
        return {"user": user.to_dict(), "token": token}
    except AuthError as exc:
        raise HTTPException(401, str(exc))


@app.post("/api/auth/logout")
def auth_logout(authorization: str | None = None) -> dict[str, str]:
    if authorization and authorization.lower().startswith("bearer "):
        AUTH_SERVICE.logout(authorization[7:].strip())
    return {"status": "ok"}


@app.get("/api/auth/me")
def auth_me(user=Depends(current_user_dependency)) -> dict[str, Any]:
    if user is None:
        return {"user": None, "anonymous": True}
    return {"user": user.to_dict(), "anonymous": False}


@app.get("/api/auth/users/{username}")
def auth_user_profile(username: str, current=Depends(current_user_dependency)) -> dict[str, Any]:
    u = AUTH_SERVICE.get_user_by_username(username)
    if u is None:
        raise HTTPException(404, "用户不存在")
    stats = COMMUNITY_SERVICE.follow_stats(u.user_id, current.user_id if current else None)
    return {"user": u.to_dict(), **stats}


# =============== COMMUNITY ===============

@app.get("/api/community/feed")
def community_feed(
    feed_type: str = "recent",
    author: str | None = None,
    limit: int = 50,
    offset: int = 0,
    current=Depends(current_user_dependency),
) -> list[dict[str, Any]]:
    author_id = None
    if author:
        u = AUTH_SERVICE.get_user_by_username(author)
        if u:
            author_id = u.user_id
    items = COMMUNITY_SERVICE.feed(
        feed_type=feed_type,
        current_user_id=current.user_id if current else None,
        author_id=author_id,
        limit=limit,
        offset=offset,
    )
    return [it.to_dict() for it in items]


@app.post("/api/community/posts")
def community_create_post(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        post = COMMUNITY_SERVICE.create_post(
            author_id=user.user_id,
            content=payload.get("content", ""),
            tags=payload.get("tags") or [],
            attached_run_id=payload.get("attached_run_id"),
            attached_factor_id=payload.get("attached_factor_id"),
            repost_of=payload.get("repost_of"),
        )
        return post.to_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/community/posts/{post_id}")
def community_get_post(post_id: str, current=Depends(current_user_dependency)) -> dict[str, Any]:
    item = COMMUNITY_SERVICE.get_post(post_id, current.user_id if current else None)
    if item is None:
        raise HTTPException(404, "帖子不存在")
    return item.to_dict()


@app.delete("/api/community/posts/{post_id}")
def community_delete_post(post_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        return {"deleted": COMMUNITY_SERVICE.delete_post(post_id, user.user_id)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.post("/api/community/posts/{post_id}/like")
def community_like(post_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"liked": COMMUNITY_SERVICE.like(user.user_id, post_id)}


@app.delete("/api/community/posts/{post_id}/like")
def community_unlike(post_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"unliked": COMMUNITY_SERVICE.unlike(user.user_id, post_id)}


@app.get("/api/community/posts/{post_id}/comments")
def community_comments(post_id: str) -> list[dict[str, Any]]:
    return COMMUNITY_SERVICE.list_comments(post_id)


@app.post("/api/community/posts/{post_id}/comments")
def community_add_comment(post_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        c = COMMUNITY_SERVICE.add_comment(post_id, user.user_id, payload.get("content", ""), payload.get("reply_to"))
        return c.to_dict()
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/community/users/{target_username}/follow")
def community_follow(target_username: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    target = AUTH_SERVICE.get_user_by_username(target_username)
    if target is None:
        raise HTTPException(404, "目标用户不存在")
    try:
        return {"followed": COMMUNITY_SERVICE.follow(user.user_id, target.user_id)}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.delete("/api/community/users/{target_username}/follow")
def community_unfollow(target_username: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    target = AUTH_SERVICE.get_user_by_username(target_username)
    if target is None:
        raise HTTPException(404, "目标用户不存在")
    return {"unfollowed": COMMUNITY_SERVICE.unfollow(user.user_id, target.user_id)}


# =============== STRATEGY SHARING ===============

@app.post("/api/sharing/publish")
def sharing_publish(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        s = SHARING_SERVICE.publish_strategy(
            run_id=payload["run_id"],
            author_id=user.user_id,
            title=payload.get("title") or payload["run_id"],
            description=payload.get("description", ""),
            tags=payload.get("tags") or [],
            asset_class=payload.get("asset_class", ""),
            public=bool(payload.get("public", True)),
        )
        return s.to_dict()
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/sharing/feed")
def sharing_feed(
    asset_class: str | None = None,
    author: str | None = None,
    sort_by: str = "recent",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    author_id = None
    if author:
        u = AUTH_SERVICE.get_user_by_username(author)
        if u:
            author_id = u.user_id
    items = SHARING_SERVICE.list_strategies(
        asset_class=asset_class,
        author_id=author_id,
        sort_by=sort_by,
        limit=limit,
        offset=offset,
    )
    cache: dict[str, dict[str, str]] = {}
    out: list[dict[str, Any]] = []
    for s in items:
        if s.author_id not in cache:
            u = AUTH_SERVICE.get_user_by_id(s.author_id)
            cache[s.author_id] = (
                {"author_username": u.username, "author_display_name": u.display_name}
                if u else {"author_username": "unknown", "author_display_name": "unknown"}
            )
        d = s.to_dict()
        d.update(cache[s.author_id])
        out.append(d)
    return out


@app.get("/api/sharing/{share_id}")
def sharing_get(share_id: str) -> dict[str, Any]:
    s = SHARING_SERVICE.get_strategy(share_id)
    if s is None:
        raise HTTPException(404, "share 不存在")
    return s.to_dict()


@app.post("/api/sharing/{share_id}/fork")
def sharing_fork(share_id: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        s = SHARING_SERVICE.fork_strategy(share_id, user.user_id, title=payload.get("title"))
        return s.to_dict()
    except ValueError as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/sharing/{share_id}/like")
def sharing_like(share_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"liked": SHARING_SERVICE.like(user.user_id, share_id)}


@app.delete("/api/sharing/{share_id}/like")
def sharing_unlike(share_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"unliked": SHARING_SERVICE.unlike(user.user_id, share_id)}


@app.delete("/api/sharing/{share_id}")
def sharing_delete(share_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        return {"deleted": SHARING_SERVICE.delete_strategy(share_id, user.user_id)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


# ============ COPY TRADE ============

@app.get("/api/copy_trade/masters")
def ct_list_masters(
    asset_class: str | None = None,
    sort_by: str = "followers",
    invite_only: bool | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    masters = COPY_TRADE_SERVICE.list_masters(
        asset_class=asset_class, sort_by=sort_by,
        invite_only=invite_only, limit=limit,
    )
    cache: dict[str, dict[str, str]] = {}
    out: list[dict[str, Any]] = []
    for m in masters:
        if m.user_id not in cache:
            u = AUTH_SERVICE.get_user_by_id(m.user_id)
            cache[m.user_id] = (
                {"author_username": u.username, "author_display_name": u.display_name}
                if u else {"author_username": "unknown", "author_display_name": "unknown"}
            )
        d = m.to_dict()
        d.update(cache[m.user_id])
        # 私域不回显 invite_code（仅 owner 看得到，走单独 endpoint）
        if d.get("is_invite_only"):
            d["invite_code"] = ""
        out.append(d)
    return out


@app.get("/api/copy_trade/masters/{master_id}")
def ct_get_master(master_id: str, current=Depends(current_user_dependency)) -> dict[str, Any]:
    m = COPY_TRADE_SERVICE.get_master(master_id)
    if m is None:
        raise HTTPException(404, "master 不存在")
    d = m.to_dict()
    # 私域：非 owner 看不到 invite_code
    if d.get("is_invite_only") and (current is None or current.user_id != m.user_id):
        d["invite_code"] = ""
    u = AUTH_SERVICE.get_user_by_id(m.user_id)
    if u:
        d["author_username"] = u.username
        d["author_display_name"] = u.display_name
    return d


@app.post("/api/copy_trade/masters")
def ct_register_master(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        m = COPY_TRADE_SERVICE.register_master(
            user_id=user.user_id,
            display_name=payload.get("display_name") or user.display_name,
            description=payload.get("description", ""),
            asset_class=payload.get("asset_class", "crypto_perp"),
            profit_share_pct=float(payload.get("profit_share_pct", 0.10)),
            is_invite_only=bool(payload.get("is_invite_only", False)),
            risk_params=payload.get("risk_params") or {},
        )
        return m.to_dict()
    except CopyTradeError as exc:
        raise HTTPException(400, str(exc))


@app.patch("/api/copy_trade/masters/{master_id}")
def ct_update_master(master_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        m = COPY_TRADE_SERVICE.update_master(
            master_id, user.user_id,
            description=payload.get("description"),
            profit_share_pct=payload.get("profit_share_pct"),
            is_invite_only=payload.get("is_invite_only"),
            risk_params=payload.get("risk_params"),
        )
        return m.to_dict()
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except CopyTradeError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/copy_trade/masters/{master_id}/rotate_invite")
def ct_rotate_invite(master_id: str, user=Depends(require_user_dependency)) -> dict[str, str]:
    try:
        code = COPY_TRADE_SERVICE.rotate_invite_code(master_id, user.user_id)
        return {"invite_code": code}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except CopyTradeError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/copy_trade/masters/{master_id}/redeem")
def ct_redeem(master_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        ok = COPY_TRADE_SERVICE.redeem_invite(user.user_id, master_id, payload.get("invite_code", ""))
        return {"redeemed": ok}
    except CopyTradeError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/copy_trade/masters/{master_id}/subscribe")
def ct_subscribe(master_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        f = COPY_TRADE_SERVICE.subscribe(
            user_id=user.user_id,
            master_id=master_id,
            invest_amount=float(payload.get("invest_amount", 0)),
            binance_keystore_name=payload.get("binance_keystore_name", ""),
            binance_network=payload.get("binance_network", "testnet"),
            per_order_max_usdt=float(payload.get("per_order_max_usdt", 100)),
            daily_loss_limit_pct=float(payload.get("daily_loss_limit_pct", 0.05)),
            max_positions=int(payload.get("max_positions", 5)),
        )
        return f.to_dict()
    except CopyTradeError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/copy_trade/masters/{master_id}/unsubscribe")
def ct_unsubscribe(master_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    return {"unsubscribed": COPY_TRADE_SERVICE.unsubscribe(user.user_id, master_id)}


@app.post("/api/copy_trade/masters/{master_id}/pause")
def ct_pause(master_id: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)) -> dict[str, bool]:
    paused = bool(payload.get("paused", True))
    return {"updated": COPY_TRADE_SERVICE.pause_subscription(user.user_id, master_id, paused=paused)}


@app.get("/api/copy_trade/me/subscriptions")
def ct_my_subscriptions(user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    subs = COPY_TRADE_SERVICE.list_subscriptions(user.user_id)
    out: list[dict[str, Any]] = []
    for s in subs:
        d = s.to_dict()
        m = COPY_TRADE_SERVICE.get_master(s.master_id)
        if m:
            d["master_display_name"] = m.display_name
            d["master_asset_class"] = m.asset_class
        out.append(d)
    return out


@app.get("/api/copy_trade/me/master")
def ct_my_master(user=Depends(require_user_dependency)) -> dict[str, Any] | None:
    m = COPY_TRADE_SERVICE.get_master_by_user(user.user_id)
    return m.to_dict() if m else None


@app.get("/api/copy_trade/masters/{master_id}/followers")
def ct_master_followers(master_id: str, user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    m = COPY_TRADE_SERVICE.get_master(master_id)
    if m is None:
        raise HTTPException(404)
    if m.user_id != user.user_id:
        raise HTTPException(403, "只有 master 自己看得到 follower 列表")
    followers = COPY_TRADE_SERVICE.list_followers(master_id, active_only=False)
    out: list[dict[str, Any]] = []
    for f in followers:
        d = f.to_dict()
        # 隐藏 keystore 名字（敏感引用）
        d["binance_keystore_name"] = "***"
        u = AUTH_SERVICE.get_user_by_id(f.user_id)
        if u:
            d["username"] = u.username
        out.append(d)
    return out


@app.post("/api/copy_trade/signals")
def ct_publish_signal(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    master = COPY_TRADE_SERVICE.get_master_by_user(user.user_id)
    if master is None:
        raise HTTPException(400, "请先注册成 master")
    try:
        sig = COPY_TRADE_SERVICE.publish_signal(
            master_id=master.master_id,
            user_id=user.user_id,
            symbol=payload["symbol"],
            side=payload["side"],
            quantity=float(payload["quantity"]),
            price=payload.get("price"),
            order_type=payload.get("order_type", "market"),
            stop_loss=payload.get("stop_loss"),
            take_profit=payload.get("take_profit"),
            note=payload.get("note", ""),
        )
    except (CopyTradeError, KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    # relay → 所有 active follower 真下单
    relayer = SignalRelayer(COPY_TRADE_SERVICE, KEYSTORE, _binance_venue_for_follower)
    relay_results = relayer.relay(sig)
    return {"signal": sig.to_dict(), "relay": relay_results}


@app.delete("/api/copy_trade/signals/{signal_id}")
def ct_cancel_signal(signal_id: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        return {"canceled": COPY_TRADE_SERVICE.cancel_signal(signal_id, user.user_id)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))


@app.get("/api/copy_trade/signals")
def ct_list_signals(master_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    return [s.to_dict() for s in COPY_TRADE_SERVICE.list_signals(master_id=master_id, limit=limit)]


@app.get("/api/copy_trade/executions")
def ct_list_executions(signal_id: str | None = None, follower_id: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return [
        e.to_dict()
        for e in COPY_TRADE_SERVICE.list_executions(signal_id=signal_id, follower_id=follower_id, limit=limit)
    ]


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


# ============================================================
# v0.8.2 · 聚宽风 IDE：策略 CRUD + 沙箱运行 + AI 辅助
# ============================================================


@app.get("/api/ide/strategies")
def ide_list_strategies(user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return [strategy_to_dict(s) for s in IDE_SERVICE.list_strategies(user.username)]


@app.get("/api/ide/strategies/{name}")
def ide_get_strategy(name: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        return strategy_to_dict(IDE_SERVICE.get_strategy(user.username, name))
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/ide/strategies")
def ide_save_strategy(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        s = IDE_SERVICE.save_strategy(
            user.username,
            payload.get("name", ""),
            payload.get("code", ""),
            asset_class=payload.get("asset_class", "crypto_perp"),
            description=payload.get("description", ""),
        )
    except IDEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return strategy_to_dict(s)


@app.delete("/api/ide/strategies/{name}")
def ide_delete_strategy(name: str, user=Depends(require_user_dependency)) -> dict[str, bool]:
    try:
        IDE_SERVICE.delete_strategy(user.username, name)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/ide/strategies/{name}/run")
def ide_run_strategy(name: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        run = IDE_SERVICE.run_strategy(user.username, name)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return run_to_dict(run)


@app.get("/api/ide/runs")
def ide_list_runs(limit: int = Query(50, ge=1, le=200), user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return [run_to_dict(r) for r in IDE_SERVICE.list_runs(user.username, limit=limit)]


@app.get("/api/ide/runs/{run_id}")
def ide_get_run(run_id: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        run = IDE_SERVICE.get_run(run_id)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.owner_username != user.username:
        raise HTTPException(status_code=403, detail="无权访问该 run")
    return run_to_dict(run)


@app.get("/api/ide/runs/{run_id}/{kind}")
def ide_get_run_artifact(run_id: str, kind: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        run = IDE_SERVICE.get_run(run_id)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if run.owner_username != user.username:
        raise HTTPException(status_code=403, detail="无权访问该 run")
    try:
        return IDE_SERVICE.get_run_artifact(run_id, kind)
    except IDEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ide/ai_complete")
def ide_ai_complete(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """BigQuant 风 AI 辅助：让 LLM 帮写 / 解释 / 修复 策略代码。

    payload: {prompt: str, context_code?: str, mode?: 'write'|'explain'|'fix'}
    """
    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 必填")
    mode = payload.get("mode", "write")
    context_code = (payload.get("context_code") or "")[:8000]
    system_prompts = {
        "write": (
            "你是 QuantBT 的策略代码助手。用户在浏览器 IDE 里写 Python 策略。"
            "约束：(1) 输出必须是纯 Python 代码片段，不要 markdown 围栏；"
            "(2) 用 `quantbt.emit_result({...})` 在结尾发出回测结果；"
            "(3) 禁止 socket/subprocess/os.system；"
            "(4) 可用 numpy/pandas/polars/math。"
            "保持简短可读。"
        ),
        "explain": (
            "你是 QuantBT 的策略代码助手。逐段解释下面这段策略代码的意图、"
            "因子逻辑、潜在风险（过拟合 / 前视偏差 / 流动性假设）。"
            "用中文，分条列出，不要返回代码。"
        ),
        "fix": (
            "你是 QuantBT 的策略代码助手。下面的代码运行报错。"
            "请定位 bug 并给出修复后的完整 Python 代码片段（不要 markdown）。"
        ),
    }
    sys_prompt = system_prompts.get(mode, system_prompts["write"])
    user_text = f"{prompt}\n\n# 当前编辑器内容（context）:\n{context_code}" if context_code else prompt
    from .agent.llm_client import LLMMessage
    try:
        client = _current_agent_llm()
        reply = client.chat([
            LLMMessage(role="system", content=sys_prompt),
            LLMMessage(role="user", content=user_text),
        ])
        text = reply.content or ""
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM 调用失败: {exc}") from exc
    return {"mode": mode, "code": text.strip(), "provider": getattr(client, "provider", "unknown")}
