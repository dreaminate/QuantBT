from __future__ import annotations

import logging
from pathlib import Path
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
from .ide import IDEError, IDEService, PromoteError, build_ai_context, promote_ide_run
from .ide.service import run_to_dict, strategy_to_dict
from .agent.conversations import (
    ChatError,
    ChatService,
    VALID_MARKET_MODES,
    message_to_dict,
    thread_to_dict,
)
from .agent.coach import classify_response_mode, suggest_from_risk_summary
from .agent.prompts import build_mode2_prompt
from .agent.rag import format_rag_context, format_run_context, retrieve
from .events import EventService, EventTrackError
from .glossary import GlossaryError, GlossaryRegistry, load_glossary_dir
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
from .datasets import get_template as get_strategy_template, list_samples, list_templates as list_strategy_templates, load_sample
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
EVENT_SERVICE = EventService(_COMMUNITY_DB)  # 复用 community.db，单文件好查
CHAT_SERVICE = ChatService(_COMMUNITY_DB)  # v0.8.6 · Mode 2 多轮对话
from .trading import SafetyService, SafetyServiceError  # noqa: E402
SAFETY_SERVICE = SafetyService(_COMMUNITY_DB)  # v0.8.8 · 实盘安全阶梯
from .community.compliance import ComplianceService, check_content_for_forbidden  # noqa: E402
COMPLIANCE_SERVICE = ComplianceService(_COMMUNITY_DB)  # v0.8.8.1 · 帖子合规
from .copy_trade.beta import CopyTradeBetaService  # noqa: E402
CT_BETA_SERVICE = CopyTradeBetaService(_COMMUNITY_DB)  # v0.8.9 · 跟单灰度

_main_logger = logging.getLogger(__name__)

# v0.8.4 · Glossary 词条仓库（启动时从 docs/glossary/ 加载，加载失败不阻断启动）
# main.py 在 app/backend/app/main.py → 仓库根是 parents[3]
_GLOSSARY_DIR = Path(__file__).resolve().parents[3] / "docs" / "glossary"
try:
    GLOSSARY = load_glossary_dir(_GLOSSARY_DIR) if _GLOSSARY_DIR.exists() else GlossaryRegistry()
except GlossaryError as exc:
    _main_logger.warning("Glossary 加载失败: %s（启动继续，词条 endpoint 返空）", exc)
    GLOSSARY = GlossaryRegistry()


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
        # v0.9.x · funnel 埋点 (patch2 §H.b)
        try:
            EVENT_SERVICE.track(
                "user_registered",
                user_id=user.user_id,
                properties={
                    "auth_method": "password",
                    "persona_hint": payload.get("persona_hint", "unknown"),
                    "referrer": payload.get("referrer"),
                    "client_tz": payload.get("client_tz"),
                },
            )
        except Exception:  # noqa: BLE001 - 埋点失败不阻塞注册
            pass
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
        resp = get_run_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    # v0.8.4 Day 4 · 计算 risk_summary 挂到响应（不改 run.json on-disk schema）
    from .eval.risk_summary import compute_risk_summary
    combined: dict[str, Any] = {}
    combined.update(resp.get("metrics") or {})
    combined.update(resp.get("jq_overview_metrics") or {})
    resp["risk_summary"] = compute_risk_summary(combined).to_dict()
    return resp


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
    base_prompt = system_prompts.get(mode, system_prompts["write"])
    # 喂给 LLM 完整的写策略上下文（connector / factor / operator / 沙箱规则 / emit_result schema）
    ctx = build_ai_context(
        connectors=connector_registry.describe_all(),
        factors=[f.to_dict() for f in FACTOR_REGISTRY.list()],
        operators=list_operators(),
    )
    sys_prompt = base_prompt + "\n\n" + ctx.to_system_prompt_block()
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


@app.get("/api/ide/ai_context")
def ide_ai_context(user=Depends(require_user_dependency)) -> dict[str, Any]:
    """UI 透明展示 LLM 拿到的上下文（connector / factor / operator / 沙箱规则）。"""

    _ = user
    ctx = build_ai_context(
        connectors=connector_registry.describe_all(),
        factors=[f.to_dict() for f in FACTOR_REGISTRY.list()],
        operators=list_operators(),
    )
    return ctx.to_dict()


@app.get("/api/ide/runs/{run_id}/risk_preview")
def ide_run_risk_preview(run_id: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    """v0.9.2 · promote 前预算 risk_summary，让 IDE 前端实时展示可信度。"""
    try:
        ide_run = IDE_SERVICE.get_run(run_id)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if ide_run.owner_username != user.username:
        raise HTTPException(status_code=403, detail="无权访问该 run")
    if ide_run.status != "ok":
        return {"risk_summary": None, "reason": f"run status={ide_run.status}"}

    try:
        result = IDE_SERVICE.get_run_artifact(run_id, "result")["body"]
    except IDEError:
        return {"risk_summary": None, "reason": "no emit_result"}

    # 从 result.json 抽 metrics (兼容 emit_result 顶层直接给 metrics dict 或挂 metrics 字段)
    metrics_combined: dict[str, Any] = {}
    if isinstance(result, dict):
        if isinstance(result.get("metrics"), dict):
            metrics_combined.update(result["metrics"])
        # 平铺字段（用户也可能直接顶层放 sharpe）
        for k in ("sharpe", "sharpe_ratio", "pbo", "dsr", "deflated_sharpe",
                   "max_drawdown", "drawdown", "alpha", "beta", "ic_ir",
                   "turnover", "max_position_weight", "information_ratio"):
            if k in result and not isinstance(result[k], dict):
                metrics_combined.setdefault(k, result[k])

    from .eval.risk_summary import compute_risk_summary
    rs = compute_risk_summary(metrics_combined).to_dict()
    return {"risk_summary": rs, "metrics_used": metrics_combined}


@app.post("/api/ide/runs/{run_id}/promote")
def ide_promote_run(run_id: str, payload: dict = Body(default_factory=dict), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """把 IDE 沙箱 run 提升为正式 Run（落 runs/<new_id>/ 进 RunDetail pipeline）。"""

    try:
        ide_run = IDE_SERVICE.get_run(run_id)
    except IDEError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if ide_run.owner_username != user.username:
        raise HTTPException(status_code=403, detail="无权操作该 run")
    if ide_run.status != "ok":
        raise HTTPException(status_code=400, detail=f"only ok run can promote, got status={ide_run.status}")

    try:
        result = IDE_SERVICE.get_run_artifact(run_id, "result")["body"]
    except IDEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 拿对应 strategy 的源码（如果还在）
    strategy_code = ""
    strategy_name = "ide_strategy"
    try:
        strategies = IDE_SERVICE.list_strategies(user.username)
        match = next((s for s in strategies if s.strategy_id == ide_run.strategy_id), None)
        if match is not None:
            strategy_code = match.code
            strategy_name = match.name
    except IDEError:
        pass

    try:
        promoted = promote_ide_run(
            ide_run_id=ide_run.run_id,
            owner_username=user.username,
            strategy_name=strategy_name,
            strategy_code=strategy_code,
            result=result,
            record_name=payload.get("record_name"),
        )
    except PromoteError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # v0.9.x · funnel 埋点 - run_completed
    try:
        sharpe = promoted.metrics.get("sharpe")
        EVENT_SERVICE.track(
            "run_completed",
            user_id=user.user_id,
            properties={
                "run_id": promoted.run_id,
                "strategy_id": ide_run.strategy_id,
                "market_mode": "ide_sandbox",
                "duration_ms": int(ide_run.duration_s * 1000),
                "status": "success",
                "sharpe": sharpe,
                "max_drawdown": promoted.metrics.get("max_drawdown"),
                "total_return": promoted.metrics.get("total_return"),
                "trigger": "promote_ide_run",
            },
        )
    except Exception:  # noqa: BLE001
        pass

    return {
        "run_id": promoted.run_id,
        "run_url": f"/runs/{promoted.run_id}",
        "metrics": promoted.metrics,
    }


# ============================================================
# v0.8.4 Day 2 · Glossary endpoints
# ============================================================


@app.get("/api/glossary")
def glossary_list(
    category: str | None = Query(None, description="按 category 过滤"),
    level: str | None = Query(None, description="按 level 过滤"),
) -> list[dict[str, Any]]:
    """列出全部词条 summary（用于 RunDetail ⓘ mapping 选词 + 词典页）。"""

    items = GLOSSARY.list_summary()
    if category:
        items = [x for x in items if x["category"] == category]
    if level:
        items = [x for x in items if x["level"] == level]
    return items


@app.get("/api/glossary/{term}")
def glossary_get(
    term: str,
    level: str | None = Query(None, description="渐进披露：'l1'/'l2'/'l3'/'l4'；省略=全部"),
) -> dict[str, Any]:
    """通过 slug 或 alias 拿单个词条。404 返 {error, term, suggestions}。"""

    t = GLOSSARY.lookup(term)
    if t is None:
        # 拼写相近建议：difflib 模糊匹配 slug + aliases
        import difflib
        q = term.strip().lower()
        candidates: list[tuple[str, str]] = []  # (key, slug)
        for x in GLOSSARY.list_summary():
            candidates.append((x["slug"].lower(), x["slug"]))
            for a in x["aliases"]:
                candidates.append((a.lower(), x["slug"]))
        keys = [k for k, _ in candidates]
        close = difflib.get_close_matches(q, keys, n=8, cutoff=0.4)
        # 去重 slug 保序
        seen: set[str] = set()
        suggestions: list[str] = []
        for k in close:
            for kk, slug in candidates:
                if kk == k and slug not in seen:
                    seen.add(slug)
                    suggestions.append(slug)
                    break
            if len(suggestions) >= 5:
                break
        raise HTTPException(
            status_code=404,
            detail={"error": "term_not_found", "term": term, "suggestions": suggestions},
        )
    return t.to_dict(level=level)


@app.get("/api/glossary/{term}/usage_in_runs")
def glossary_usage_in_runs(term: str, user_id: str | None = Query(None)) -> dict[str, Any]:
    """v0.8.5 · 该 metric 在用户历史 runs 的分布 (bucket histogram)。

    GlossaryDetailPage 侧栏用，让用户看到"我的 SR 落在第 X 分位"。
    """

    t = GLOSSARY.lookup(term)
    if t is None:
        return {"count": 0, "buckets": []}
    # 简化实现：扫 runs/<run_id>/run.json，找 metrics 中该 metric_name 值
    metric_name = t.slug
    # 别名映射
    alias_for_metric = {"sharpe_ratio": ["sharpe", "sharpe_ratio"], "max_drawdown": ["max_drawdown", "drawdown"]}
    candidates = alias_for_metric.get(metric_name, [metric_name])
    runs_root = DATA_ROOT / "artifacts" / "experiments"
    values: list[float] = []
    if runs_root.exists():
        for run_dir in runs_root.iterdir():
            manifest = run_dir / "run.json"
            if not manifest.exists():
                continue
            try:
                import json
                m = json.loads(manifest.read_text(encoding="utf-8-sig"))
                metrics = m.get("metrics") or {}
                for c in candidates:
                    if c in metrics and isinstance(metrics[c], (int, float)):
                        values.append(float(metrics[c]))
                        break
            except Exception:  # noqa: BLE001
                continue
    if not values:
        return {"count": 0, "buckets": []}
    # 5-bucket histogram
    lo, hi = min(values), max(values)
    if lo == hi:
        return {"count": len(values), "buckets": [{"range": f"{lo:.2f}", "users": len(values)}]}
    width = (hi - lo) / 5
    buckets = []
    for i in range(5):
        b_lo = lo + i * width
        b_hi = lo + (i + 1) * width
        cnt = sum(1 for v in values if b_lo <= v < (b_hi if i < 4 else b_hi + 1e-9))
        buckets.append({"range": f"{b_lo:.2f}~{b_hi:.2f}", "users": cnt})
    return {"count": len(values), "buckets": buckets}


@app.post("/api/events/track")
def events_track(payload: dict = Body(...), current=Depends(current_user_dependency)) -> dict[str, Any]:
    """前端埋点入口。fire-and-forget，不阻塞 UI。"""

    try:
        rec = EVENT_SERVICE.track(
            event_name=payload.get("event_name", ""),
            user_id=current.user_id if current else None,
            anonymous_id=payload.get("anonymous_id"),
            session_id=payload.get("session_id"),
            app_version=payload.get("app_version"),
            market_mode=payload.get("market_mode"),
            properties=payload.get("properties") or {},
        )
    except EventTrackError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"event_id": rec.event_id, "ok": True}


@app.get("/api/datasets/samples")
def datasets_samples() -> list[dict[str, Any]]:
    """v0.8.7 · 列出全部内置 sample。"""
    return list_samples()


@app.get("/api/datasets/samples/{sample_id}/preview")
def datasets_sample_preview(sample_id: str, rows: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    """sample 前 N 行预览 (前端表格用)。"""
    df = load_sample(sample_id)
    if df is None:
        raise HTTPException(status_code=404, detail=f"sample 不存在: {sample_id}")
    preview = df.head(rows)
    return {
        "sample_id": sample_id,
        "total_rows": df.height,
        "columns": preview.columns,
        "rows": preview.to_dicts(),
    }


@app.get("/api/strategies/templates")
def strategies_templates() -> list[dict[str, Any]]:
    """v0.8.7 · 列出 3 个策略模板 (BTC momentum / ETH funding / A股 ETF rotation)。"""
    items = list_strategy_templates()
    # 不返回完整 code，只返回 metadata + code 长度（前端按需 fetch detail）
    return [
        {**{k: v for k, v in t.items() if k != "code"}, "code_length": len(t["code"])}
        for t in items
    ]


@app.get("/api/strategies/templates/{template_id}")
def strategies_template_detail(template_id: str) -> dict[str, Any]:
    """单个模板完整代码 + metadata。"""
    t = get_strategy_template(template_id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"template 不存在: {template_id}")
    return t.to_dict()


@app.post("/api/strategies/templates/{template_id}/fork_to_ide")
def strategies_template_fork(
    template_id: str,
    payload: dict = Body(default_factory=dict),
    user=Depends(require_user_dependency),
) -> dict[str, Any]:
    """v0.9.3 · 把策略模板 fork 到用户 IDE 名下，可立刻在 /ide 改 + 跑。"""
    t = get_strategy_template(template_id)
    if t is None:
        raise HTTPException(status_code=404, detail=f"template 不存在: {template_id}")
    new_name = payload.get("name") or f"{t.template_id}_fork"
    description = payload.get("description") or f"forked from template {t.template_id}"
    try:
        strategy = IDE_SERVICE.save_strategy(
            user.username, new_name, t.code,
            asset_class=t.asset_class, description=description,
        )
    except IDEError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "strategy_id": strategy.strategy_id,
        "name": strategy.name,
        "ide_url": f"/ide?open={strategy.name}",
        "expected_metrics": t.expected_metrics,
    }


@app.get("/api/runs/{run_id}/coach_suggestion")
def runs_coach_suggestion(run_id: str) -> dict[str, Any]:
    """v0.8.6.1 · 基于 risk_summary 给出主动建议 (RunDetail 顶部浮卡片用)。"""
    try:
        resp = get_run_response(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    combined: dict[str, Any] = {}
    combined.update(resp.get("metrics") or {})
    combined.update(resp.get("jq_overview_metrics") or {})
    from .eval.risk_summary import compute_risk_summary
    rs = compute_risk_summary(combined).to_dict()
    sugg = suggest_from_risk_summary(rs)
    if sugg is None:
        return {"suggestion": None, "risk_summary": rs}
    return {"suggestion": sugg.to_dict(), "risk_summary": rs}


@app.post("/api/copy_trade/beta/apply")
def ct_beta_apply(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    role = payload.get("role", "follower")
    s = CT_BETA_SERVICE.apply_for_beta(user.user_id, role)
    return s.to_dict()


@app.get("/api/copy_trade/beta/status")
def ct_beta_status(role: str = Query("follower"), user=Depends(require_user_dependency)) -> dict[str, Any] | None:
    s = CT_BETA_SERVICE.get_beta_status(user.user_id, role)
    return s.to_dict() if s else None


@app.get("/api/copy_trade/beta/summary")
def ct_beta_summary() -> dict[str, Any]:
    return CT_BETA_SERVICE.waitlist_summary()


@app.get("/api/copy_trade/beta/dispatches")
def ct_beta_dispatches(user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return [d.to_dict() for d in CT_BETA_SERVICE.list_dispatches(user.user_id, limit=100)]


@app.post("/api/community/posts/{post_id}/check_compliance")
def community_post_compliance(post_id: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    """v0.8.8.1 · 复检帖子合规（含 risk_summary snapshot）。"""
    try:
        post = COMMUNITY_SERVICE.get_post(post_id, current_user_id=user.user_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    risk_summary = None
    if post.get("attached_run_id"):
        try:
            run_resp = get_run_response(post["attached_run_id"])
            combined: dict[str, Any] = {}
            combined.update(run_resp.get("metrics") or {})
            combined.update(run_resp.get("jq_overview_metrics") or {})
            from .eval.risk_summary import compute_risk_summary
            risk_summary = compute_risk_summary(combined).to_dict()
        except FileNotFoundError:
            pass
    result = COMPLIANCE_SERVICE.record_compliance(
        post_id,
        content=post.get("content", ""),
        attached_run_id=post.get("attached_run_id"),
        risk_summary=risk_summary,
    )
    return result.to_dict()


@app.get("/api/community/posts/{post_id}/compliance")
def community_post_compliance_get(post_id: str) -> dict[str, Any]:
    rec = COMPLIANCE_SERVICE.get_compliance(post_id)
    if rec is None:
        return {"post_id": post_id, "passed": True, "checked": False}
    return {**rec.to_dict(), "checked": True}


@app.post("/api/community/check_text")
def community_check_text(payload: dict = Body(...)) -> dict[str, Any]:
    """前端发帖时调，提前预检文本是否含禁词。"""
    content = payload.get("content", "")
    forbidden = check_content_for_forbidden(content)
    return {
        "passed": len(forbidden) == 0,
        "forbidden_phrases_found": forbidden,
    }


# ============================================================
# v0.8.8 · Binance 安全阶梯 (SafeKey wizard + testnet matrix + live ladder)
# ============================================================


@app.post("/api/trading/safety/safekey_check")
def safety_safekey_check(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """记录 SafeKey wizard 检查结果。"""
    rec = SAFETY_SERVICE.record_safekey_check(
        user_id=user.user_id,
        key_id_hash=payload.get("key_id_hash", ""),
        enable_withdrawals=bool(payload.get("enable_withdrawals", False)),
        enable_internal_transfer=bool(payload.get("enable_internal_transfer", False)),
        enable_universal_transfer=bool(payload.get("enable_universal_transfer", False)),
        enable_margin=bool(payload.get("enable_margin", False)),
        enable_futures=bool(payload.get("enable_futures", True)),
        ip_restricted=bool(payload.get("ip_restricted", True)),
    )
    # v0.9.x · funnel 埋点
    try:
        EVENT_SERVICE.track(
            "safekey_check_completed",
            user_id=user.user_id,
            properties={
                "venue": payload.get("venue", "binance_um_futures"),
                "key_id_hash": rec.key_id_hash,
                "passed": rec.passed,
                "enable_withdrawals": rec.enable_withdrawals,
                "enable_futures": rec.enable_futures,
                "enable_margin": rec.enable_margin,
                "ip_restricted": rec.ip_restricted,
                "failure_reason": (rec.failures[0] if rec.failures else None),
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return rec.to_dict()


@app.get("/api/trading/safety/safekey_latest")
def safety_safekey_latest(user=Depends(require_user_dependency)) -> dict[str, Any] | None:
    rec = SAFETY_SERVICE.get_latest_safekey(user.user_id)
    return rec.to_dict() if rec else None


@app.post("/api/trading/safety/matrix_attempt")
def safety_matrix_attempt(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    cell = SAFETY_SERVICE.record_matrix_attempt(
        user_id=user.user_id,
        order_type=payload.get("order_type", ""),
        side=payload.get("side", ""),
        place_ok=bool(payload.get("place_ok", False)),
        query_ok=bool(payload.get("query_ok", False)),
        cancel_ok=bool(payload.get("cancel_ok", False)),
        reconcile_ok=bool(payload.get("reconcile_ok", False)),
        error_code=payload.get("error_code"),
    )
    return cell.to_dict()


@app.get("/api/trading/safety/matrix")
def safety_matrix(user=Depends(require_user_dependency)) -> dict[str, Any]:
    return SAFETY_SERVICE.get_matrix(user.user_id).to_dict()


@app.get("/api/trading/safety/ladder")
def safety_ladder(user=Depends(require_user_dependency)) -> dict[str, Any]:
    return SAFETY_SERVICE.get_ladder(user.user_id).to_dict()


@app.post("/api/trading/safety/ladder/promote")
def safety_ladder_promote(user=Depends(require_user_dependency)) -> dict[str, Any]:
    try:
        return SAFETY_SERVICE.promote_level(user.user_id).to_dict()
    except SafetyServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/trading/safety/ladder/demote")
def safety_ladder_demote(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    reason = payload.get("reason", "manual demote")
    state = SAFETY_SERVICE.demote(user.user_id, reason)
    # v0.9.x · kill_switch_triggered 事件（降级通常由 kill switch 触发）
    try:
        EVENT_SERVICE.track(
            "kill_switch_triggered",
            user_id=user.user_id,
            properties={
                "venue": payload.get("venue", "binance_um_futures"),
                "trigger_type": reason,
                "severity": payload.get("severity", "critical"),
                "action_taken": "demote_ladder",
                "blocked_until": state.promotion_blocked_until_utc,
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return state.to_dict()


@app.post("/api/trading/safety/matrix_attempt_e2e")
def safety_matrix_attempt_e2e(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """v0.9.x · testnet matrix 完整 e2e 一次性记录（含埋点）。"""
    cell = SAFETY_SERVICE.record_matrix_attempt(
        user_id=user.user_id,
        order_type=payload.get("order_type", ""),
        side=payload.get("side", ""),
        place_ok=bool(payload.get("place_ok", False)),
        query_ok=bool(payload.get("query_ok", False)),
        cancel_ok=bool(payload.get("cancel_ok", False)),
        reconcile_ok=bool(payload.get("reconcile_ok", False)),
        error_code=payload.get("error_code"),
    )
    try:
        EVENT_SERVICE.track(
            "testnet_order_e2e_completed",
            user_id=user.user_id,
            properties={
                "venue": payload.get("venue", "binance_um_futures"),
                "symbol": payload.get("symbol", "BTC-USDT"),
                "order_type": cell.order_type,
                "side": cell.side,
                "place_ok": cell.place_ok,
                "query_ok": cell.query_ok,
                "cancel_ok": cell.cancel_ok,
                "reconcile_ok": cell.reconcile_ok,
                "latency_ms": payload.get("latency_ms"),
                "error_code": cell.error_code,
            },
        )
    except Exception:  # noqa: BLE001
        pass
    return cell.to_dict()


# ============================================================
# v0.8.6 · Mode 2 多轮对话 + SSE chat + RAG
# ============================================================


@app.post("/api/agent/chat/start")
def chat_start(payload: dict = Body(...), current=Depends(current_user_dependency)) -> dict[str, Any]:
    """创建 thread。market_mode / active_run_id / active_strategy_id 可选。"""
    try:
        t = CHAT_SERVICE.start_thread(
            user_id=current.user_id if current else None,
            market_mode=payload.get("market_mode", "ashare_research"),
            active_run_id=payload.get("active_run_id"),
            active_strategy_id=payload.get("active_strategy_id"),
            title=payload.get("title", ""),
        )
    except ChatError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return thread_to_dict(t)


@app.get("/api/agent/chat/threads")
def chat_list_threads(user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return [thread_to_dict(t) for t in CHAT_SERVICE.list_threads(user.user_id)]


@app.get("/api/agent/chat/{thread_id}")
def chat_get_thread(thread_id: str, current=Depends(current_user_dependency)) -> dict[str, Any]:
    try:
        t = CHAT_SERVICE.get_thread(thread_id)
    except ChatError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _ = current  # 简化访问控制：所有 thread 自己 user 可见，留 v0.8.6.1 加 ACL
    msgs = CHAT_SERVICE.list_messages(thread_id)
    return {"thread": thread_to_dict(t), "messages": [message_to_dict(m) for m in msgs]}


@app.post("/api/agent/chat/{thread_id}/message")
def chat_send_message(
    thread_id: str,
    payload: dict = Body(...),
    current=Depends(current_user_dependency),
) -> dict[str, Any]:
    """非流式：发用户消息 → 触发 RAG + LLM → 返回 assistant 完整回复。

    流式版在 /api/agent/chat/{thread_id}/stream（SSE）。
    """
    try:
        thread = CHAT_SERVICE.get_thread(thread_id)
    except ChatError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    user_text = (payload.get("content") or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="content 必填")

    CHAT_SERVICE.add_message(thread_id, "user", user_text)

    # 1. RAG
    run_data: dict[str, Any] | None = None
    if thread.active_run_id:
        try:
            run_resp = get_run_response(thread.active_run_id)
            run_data = {
                "run_id": thread.active_run_id,
                **(run_resp.get("metrics") or {}),
                **(run_resp.get("jq_overview_metrics") or {}),
                "trust_level": (run_resp.get("risk_summary") or {}).get("trust_level"),
            }
        except FileNotFoundError:
            pass
    hits = retrieve(user_text, glossary=GLOSSARY, run_context=run_data)
    rag_text = format_rag_context(hits)
    run_text = format_run_context(run_data)
    history_text = CHAT_SERVICE.compress_history(thread_id)
    sys_prompt = build_mode2_prompt(
        rag_context=rag_text,
        run_context=run_text,
        conversation_history=history_text,
    )

    # 2. LLM
    from .agent.llm_client import LLMMessage
    try:
        client = _current_agent_llm()
        reply = client.chat([
            LLMMessage(role="system", content=sys_prompt),
            LLMMessage(role="user", content=user_text),
        ])
        reply_text = reply.content or "(LLM 无内容)"
    except Exception as exc:  # noqa: BLE001
        reply_text = f"[LLM 错误] {exc}"

    # 3. 持久化 assistant 消息（含 RAG metadata 便于审计）
    msg = CHAT_SERVICE.add_message(
        thread_id,
        "assistant",
        reply_text,
        metadata={
            "rag_hits": [{"kind": h.kind, "slug": h.slug, "title": h.title, "score": h.score} for h in hits],
            "had_run_context": run_data is not None,
        },
    )
    CHAT_SERVICE.update_state(thread_id, "FOLLOW_UP_UPDATE")
    return message_to_dict(msg)


@app.get("/api/agent/chat/{thread_id}/stream")
def chat_stream(thread_id: str, q: str = Query(..., description="user message"), current=Depends(current_user_dependency)):
    """SSE：用户消息 → 流式输出 assistant tokens。

    简化版：LLM client 当前是同步整段返回，所以这里把整段分块输出模拟流式。
    v0.8.7 LLM client 升级支持真 streaming 后改成 token-by-token。
    """
    _ = current
    try:
        thread = CHAT_SERVICE.get_thread(thread_id)
    except ChatError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    def event_stream():
        import json as _json
        user_text = q.strip()
        if not user_text:
            yield f"data: {_json.dumps({'error': 'empty content'})}\n\n"
            return
        CHAT_SERVICE.add_message(thread_id, "user", user_text)
        # RAG + LLM
        run_data = None
        if thread.active_run_id:
            try:
                run_resp = get_run_response(thread.active_run_id)
                run_data = {
                    "run_id": thread.active_run_id,
                    **(run_resp.get("metrics") or {}),
                    **(run_resp.get("jq_overview_metrics") or {}),
                    "trust_level": (run_resp.get("risk_summary") or {}).get("trust_level"),
                }
            except FileNotFoundError:
                pass
        hits = retrieve(user_text, glossary=GLOSSARY, run_context=run_data)
        rag_text = format_rag_context(hits)
        run_text = format_run_context(run_data)
        history_text = CHAT_SERVICE.compress_history(thread_id)
        sys_prompt = build_mode2_prompt(rag_context=rag_text, run_context=run_text, conversation_history=history_text)
        # 给前端 RAG 命中预告
        yield f"event: rag\ndata: {_json.dumps({'hits': [{'kind': h.kind, 'slug': h.slug, 'title': h.title} for h in hits]})}\n\n"

        from .agent.llm_client import LLMMessage
        try:
            client = _current_agent_llm()
            reply = client.chat([
                LLMMessage(role="system", content=sys_prompt),
                LLMMessage(role="user", content=user_text),
            ])
            reply_text = reply.content or "(LLM 无内容)"
        except Exception as exc:  # noqa: BLE001
            reply_text = f"[LLM 错误] {exc}"

        # 分块输出模拟 streaming（每 30 字符）
        for i in range(0, len(reply_text), 30):
            chunk = reply_text[i:i + 30]
            yield f"data: {_json.dumps({'chunk': chunk})}\n\n"

        # 持久化 + done
        msg = CHAT_SERVICE.add_message(
            thread_id, "assistant", reply_text,
            metadata={"rag_hits": [{"kind": h.kind, "slug": h.slug} for h in hits], "streamed": True},
        )
        CHAT_SERVICE.update_state(thread_id, "FOLLOW_UP_UPDATE")
        yield f"event: done\ndata: {_json.dumps({'message_id': msg.message_id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/metrics/funnel")
def metrics_funnel() -> dict[str, Any]:
    """v0.8.5.1 · 漏斗 dashboard 用：事件总计 + 首次 run 耗时 bucket。"""

    import sqlite3
    db_path = _COMMUNITY_DB
    by_event: list[dict[str, Any]] = []
    first_run_buckets: list[dict[str, Any]] = []
    total = 0

    if db_path.exists():
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            try:
                rows = c.execute(
                    "SELECT event_name, COUNT(*) as cnt FROM events GROUP BY event_name ORDER BY cnt DESC"
                ).fetchall()
                by_event = [{"event_name": r["event_name"], "count": r["cnt"]} for r in rows]
                total = sum(x["count"] for x in by_event)
            except sqlite3.OperationalError:
                pass
            # 首次 run 耗时 bucket
            try:
                sql = """
                WITH registered AS (
                  SELECT user_id, MIN(datetime(occurred_at)) AS registered_at
                  FROM events WHERE event_name='user_registered' AND user_id IS NOT NULL GROUP BY user_id
                ),
                first_success_run AS (
                  SELECT user_id, MIN(datetime(occurred_at)) AS first_run_at
                  FROM events WHERE event_name='run_completed'
                  AND json_extract(properties,'$.status')='success'
                  AND user_id IS NOT NULL GROUP BY user_id
                ),
                delta AS (
                  SELECT r.user_id,
                         CAST((julianday(f.first_run_at)-julianday(r.registered_at))*24*60 AS INTEGER) AS minutes
                  FROM registered r JOIN first_success_run f ON r.user_id=f.user_id
                  WHERE f.first_run_at >= r.registered_at
                ),
                bucketed AS (
                  SELECT CASE
                    WHEN minutes < 5 THEN '00_<5min'
                    WHEN minutes < 15 THEN '01_5-15min'
                    WHEN minutes < 30 THEN '02_15-30min'
                    WHEN minutes < 60 THEN '03_30-60min'
                    WHEN minutes < 180 THEN '04_1-3h'
                    WHEN minutes < 1440 THEN '05_3-24h'
                    ELSE '06_>24h'
                  END AS bucket, COUNT(*) AS users FROM delta GROUP BY 1
                )
                SELECT bucket, users, ROUND(users*100.0/SUM(users) OVER (), 2) AS pct
                FROM bucketed ORDER BY bucket;
                """
                rows = c.execute(sql).fetchall()
                first_run_buckets = [
                    {"bucket": r["bucket"], "users": r["users"], "pct": r["pct"] or 0.0}
                    for r in rows
                ]
            except sqlite3.OperationalError:
                pass

    return {"total_events": total, "by_event": by_event, "first_run_buckets": first_run_buckets}


@app.get("/api/events/recent")
def events_recent(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
    """调试 / 监控用：拉最近事件。"""

    return EVENT_SERVICE.recent(limit=limit)


@app.get("/api/glossary_meta")
def glossary_meta() -> dict[str, Any]:
    """词典统计：用于 RunDetail 风险卡片判断 'glossary 是否就绪'。"""

    summary = GLOSSARY.list_summary()
    by_category: dict[str, int] = {}
    by_level: dict[str, int] = {}
    for x in summary:
        by_category[x["category"]] = by_category.get(x["category"], 0) + 1
        by_level[x["level"]] = by_level.get(x["level"], 0) + 1
    related_violations = GLOSSARY.validate_related_closure()
    return {
        "count": len(summary),
        "by_category": by_category,
        "by_level": by_level,
        "related_closure_ok": not related_violations,
        "related_violations": related_violations[:10],  # 前 10 条便于调试
    }
