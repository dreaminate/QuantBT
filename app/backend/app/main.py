from __future__ import annotations

import logging
import os
import uuid
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
from .agent.replay import ControlledTranslator, FixtureStore, RecordingLLMClient
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

# 脊柱内核 01 接线（T-023）：JOB_STORE 携内核 store（ArtifactStore+EffectLedger 落 DATA_ROOT/kernel）。
# kernel_dag job 的 retry 即「从最近 checkpoint 恢复 + is_consumed 去重、绝不重发单」；既有数据拉取 job 零影响。
JOB_STORE = InMemoryJobStore(kernel_root=DATA_ROOT / "kernel")
DATASET_REGISTRY = DatasetRegistry(DATA_ROOT / "datasets" / "registry.jsonl")
FACTOR_REGISTRY = FactorRegistry(DATA_ROOT / "factors" / "registry.json")
if not FACTOR_REGISTRY.list():
    register_alpha_lite(FACTOR_REGISTRY)
EXPERIMENT_STORE = ExperimentStore(DATA_ROOT / "experiments")
RUN_STORE = RunStore(DATA_ROOT / "experiments")
MODEL_REGISTRY = ModelRegistry(DATA_ROOT / "experiments")
ERROR_REPORTER = init_error_reporting(DATA_ROOT / "audit" / "errors.jsonl")

# 脊柱第 0 层：honest-N 一本账（T-013）+ 收益快照内容寻址存储（T-014 ArtifactStore 复用），
# 供 T-015 多证据三角 gate 接进 promote/risk_preview（让 PBO/DSR 守门器从死接活）。
from .dag import ArtifactStore as _ArtifactStore  # noqa: E402
from .lineage import Ledger as _Ledger  # noqa: E402

LEDGER = _Ledger(DATA_ROOT / "lineage")
RETURNS_STORE = _ArtifactStore(DATA_ROOT / "lineage" / "returns")

# 脊柱 04：可证伪假设卡接进 Run 生命周期（T-024 / P2 不挡探索）。
# exploratory run 一律放行；仅晋级 confirmatory 可下注结论才强制冻结三必填 + 一次性 OOS 闸门。
from .hypothesis import (  # noqa: E402
    FreezeRejected as _FreezeRejected,
    HypothesisCardStore as _HypothesisCardStore,
    PromoteRejected as _PromoteRejected,
    can_touch_final_oos as _can_touch_final_oos,
)

HYPOTHESIS_STORE = _HypothesisCardStore(DATA_ROOT / "experiments")

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
# T-019 审批门：接进 MODEL_REGISTRY（晚绑定，避免重排 :94 实例化）；staging/production promote 必经门。
from .approval import (  # noqa: E402
    ApprovalGateService,
    ApprovalGateStore,
    ApproverEqualsCreator,
    EmptyReason,
    GateRejection,
    GateStateError,
)
APPROVAL_GATE_STORE = ApprovalGateStore(DATA_ROOT / "experiments")
# T-020 部件12 验证官：异模型一致性裁决（产 verdict_id，喂审批门/假设卡）。
from .verification import Verifier, VerdictStore  # noqa: E402
VERDICT_STORE = VerdictStore(DATA_ROOT / "verification")
VERIFIER = Verifier()
# verdict_lookup 接进闸门：晋升 staging/production 时，verification_record_id 不止要存在——
# 还要异模型一致（blocked/concern/查不到 → 晋升缺口；闭合 T-019 [集成必补] 缝）。
GATE_SERVICE = ApprovalGateService(APPROVAL_GATE_STORE, safety_service=SAFETY_SERVICE,
                                   ledger=LEDGER, verdict_lookup=VERDICT_STORE.record_for)
MODEL_REGISTRY._gate_service = GATE_SERVICE
from .community.compliance import ComplianceService, check_content_for_forbidden  # noqa: E402
COMPLIANCE_SERVICE = ComplianceService(_COMMUNITY_DB)  # v0.8.8.1 · 帖子合规
from .copy_trade.beta import CopyTradeBetaService  # noqa: E402
CT_BETA_SERVICE = CopyTradeBetaService(_COMMUNITY_DB)  # v0.8.9 · 跟单灰度
from .security.mainnet_guards import MainnetGuardError, MainnetGuardsService  # noqa: E402
MAINNET_GUARDS = MainnetGuardsService(_COMMUNITY_DB)  # v1.0 · mainnet 7 项防御
from .billing import BillingService, PLAN_IDS  # noqa: E402
from .billing.stripe_service import PLAN_INFO  # noqa: E402
BILLING_SERVICE = BillingService(_COMMUNITY_DB)  # v1.0.3 · Stripe scaffold

# v2 数据平台 · 字段目录（inventory 为主 + registry 为辅）+ 字段映射 + 字段宇宙持久化表；官方字段带 official_ 前缀，无源开关/隔离
from .field_catalog import FieldCatalog, FieldCatalogStore, FieldMappingStore, InventoryDatasetSource  # noqa: E402


from .tushare_quant1 import qb_project_paths as _qb_project_paths  # noqa: E402

# B5: inventory 读路径 = rebuild 写路径（都取自 qb_project_paths），避免 BACKTEST_DATA_ROOT 非默认时读写分叉、字段宇宙恒空。
_QB_PATHS = _qb_project_paths()


def _rebuild_inventory() -> None:
    from .tushare_quant1.data_catalog import rebuild_data_catalog

    rebuild_data_catalog(_QB_PATHS)


FIELD_MAPPING_STORE = FieldMappingStore(str(_COMMUNITY_DB))
FIELD_CATALOG = FieldCatalog(
    DATASET_REGISTRY,
    sources=[InventoryDatasetSource(_QB_PATHS.data_catalog_inventory_file, rebuild=_rebuild_inventory)],
    mapping=FIELD_MAPPING_STORE,
)
# 字段宇宙持久化表：Agent 拉取辅助/写策略 + 官方数据更新的合并目标
FIELD_CATALOG_STORE = FieldCatalogStore(str(_COMMUNITY_DB))


def _field_universe_for_prompt(market: str | None = None) -> dict[str, dict]:
    """给 IDE/Agent system prompt 用的当前可用字段宇宙（按市场，随启用的源动态变化）。"""
    markets = [market] if market else ["stocks_cn", "binanceusdm", "binance_spot"]
    out: dict[str, dict] = {}
    for mkt in markets:
        try:
            uni = FIELD_CATALOG.available_fields(mkt)
        except Exception:  # noqa: BLE001
            continue
        out[mkt] = {"canonical": list(uni.canonical.keys()), "freeform": list(uni.freeform.keys())}
    return out

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
    """生产 venue factory（T-022 lease-only）：构造时**不 self-fetch key**。

    返回 LeasedBinanceVenue——真 key 仅在 OrderGuard S4 发 JIT lease 那一刻现身（INV-3）。
    key 存在性预检在 relayer step-2 走 broker.has_key（不返回 key 本体）。测试中由 mock factory 替代。
    `keystore` 入参保留作 VenueFactory 协议兼容（本实现不再用它取 key）。
    """
    network = follower.binance_network if follower.binance_network in {"testnet", "mainnet"} else "testnet"
    master = COPY_TRADE_SERVICE.get_master(follower.master_id)
    if master is None:
        return None
    from .execution.leased_binance import LeasedBinanceVenue
    if master.asset_class == "crypto_perp":
        return LeasedBinanceVenue(product="usdm_futures", network=network)
    if master.asset_class == "crypto_spot":
        return LeasedBinanceVenue(product="spot", network=network)
    return None  # equity_cn 等不联实盘

# 安全：开发环境用内存 keystore；上线时切换到 keyring/fernet（由 settings 控制）
KEYSTORE = SecureKeystore(InMemoryKeystore())
# 启动时自动读 ~/.quantbt/secrets.yaml（如有），把字段注入 keystore + env
_SECRETS_REPORT = load_secrets(KEYSTORE)
RISK_LIMITS = RiskLimits()
# T-021 生产接线：relay 下单热路径的会话外硬墙依赖。RELAY_NONCE_LEDGER=防重放（INV-4，crypto_live 强制）。
# 生产 relayer enforce_gate=True → 所有 follower 下单必经 deny-by-default 策略门（INV-2/M17 命门）。
from .security.gate.nonce import NonceLedger as _NonceLedger  # noqa: E402
RELAY_NONCE_LEDGER = _NonceLedger(DATA_ROOT / "security" / "relay_nonce")
# T-022 INV-3：ORDER_BROKER = 唯一持 keystore 句柄、发 JIT lease 的地方；relay venue 改 lease-only
# （构造不持 key），真 key 仅在 OrderGuard S4 发 lease 那一刻现身后端内存。
from .security.gate.broker import KeyBroker as _KeyBroker  # noqa: E402
ORDER_BROKER = _KeyBroker(KEYSTORE)
RISK_MONITOR = RiskMonitor(RISK_LIMITS)
KILL_SWITCH = KillSwitch([])  # 实盘 venue 启用时由 settings 注入

AGENT_SLOT_FILLER = StrategyGoalSlotFiller()
CODE_REPLICATOR = CodeReplicator()


# T-016 · LLM record/replay fixture store（脊柱 02）。默认 passthrough（行为不变）；
# 运维用 LLM_REPLAY_MODE=record|replay 开启（record 落不可变 fixture，replay 只读、绝不打真 API）。
FIXTURE_STORE = FixtureStore(
    DATA_ROOT / "artifacts" / "llm_fixtures",
    on_event=lambda e, p: _main_logger.info("llm_fixture_event %s %s", e, p),
)
# 受控翻译门（脊柱 02）：LLM 输出 schema 合规但语义越界（如越权杠杆）→ 不自动派发、挂人工确认。
def _agent_leverage_cap() -> float:
    # T-031 / D-LEVERAGE：翻译门杠杆阈值可配（默认 3.0），不钉系统硬上限（用户风险偏好）。
    # 真钱门不受影响——OrderGuard/PolicyGate 在端点层独立管真钱杠杆（杠杆放开数值≠绕门）。
    import os
    try:
        return float(os.environ.get("QUANTBT_AGENT_LEVERAGE_CAP", "3.0"))
    except ValueError:
        return 3.0


AGENT_TRANSLATOR = ControlledTranslator(leverage_cap=_agent_leverage_cap())


def _current_agent_llm(run_id: str | None = None):
    """按 keystore + env 选最优 provider；都失败 fallback DevLocalLLM。
    不缓存 client，让 secrets 热加载立即生效。LLM_REPLAY_MODE!=passthrough 时套 record/replay 装饰器（R11）。

    复核 #1/#7：run_id 缺省时【每次生成唯一值】，绝不退化为进程级常量——否则同 prompt 跨 turn
    撞同一 fixture_key、record 模式静默复用陈旧答案、replay 跨 run 假命中。
    """
    inner = make_llm_client(keystore=KEYSTORE)
    mode = os.environ.get("LLM_REPLAY_MODE", "passthrough")
    if mode in ("record", "replay"):
        rid = run_id or f"agent-{uuid.uuid4().hex[:12]}"
        return RecordingLLMClient(inner, FIXTURE_STORE, mode=mode, run_id=rid, translator=AGENT_TRANSLATOR)
    return inner


# 启动时探一次，仅用于 /api/agent/tools status 显示
AGENT_LLM = _current_agent_llm()


def _agent_runtime(run_id: str | None = None, permission_mode: str = "auto", system_prompt: str | None = None) -> AgentRuntime:
    # 每次 agent turn 用唯一 run_id（复核 #1/#7）+ 武装受控翻译门（复核 #3）+ 权限三态（T-027/D-PERM）。
    runtime = AgentRuntime(
        _current_agent_llm(run_id=run_id or f"agent-{uuid.uuid4().hex[:12]}"),
        translator=AGENT_TRANSLATOR,
        permission_mode=permission_mode,
        **({"system_prompt": system_prompt} if system_prompt else {}),
    )
    # 注册【无副作用】工具（side_effect=none，auto/bypass 可自主执行）；
    # 动钱/晋级永不注册给 agent —— 治理门钉在端点层（D-PERM 权限轴⟂治理轴）。
    runtime.register_tool("strategy_goal.create", lambda _n, args: {"strategy_goal": args}, side_effect="none")
    runtime.register_tool("factor.run_ic", lambda _n, args: {"queued": True, "args": args}, side_effect="none")
    runtime.register_tool("code.replicate", lambda _n, args: CODE_REPLICATOR.replicate(args.get("code", ""), args.get("source_dialect", "pandas")).__dict__, side_effect="none")
    # v2 数据平台 · 字段对齐工具（list_sources / describe_fields / infer_mapping / apply_mapping / validate_columns）
    from .agent.tool_handlers import register_field_tools
    register_field_tools(
        runtime,
        field_catalog=FIELD_CATALOG,
        mapping_store=FIELD_MAPPING_STORE,
    )
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


@app.get("/api/fields")
def list_available_fields(
    market: str = Query(...), interval: str | None = Query(None), enabled_only: bool = Query(True)
) -> dict:
    """当前可用字段宇宙（canonical + freeform），按 enabled 源过滤——量化流程/Agent 的字段真相源。"""
    return FIELD_CATALOG.available_fields(market, interval=interval, enabled_only=enabled_only).to_dict()


@app.get("/api/fields/catalog")
def fields_catalog(market: str | None = Query(None), official: bool | None = Query(None)) -> list[dict]:
    """字段宇宙持久化表（含 canonical_id/单位/含义/来源/数据种类）。Agent 拉取辅助 + 写策略用。"""
    try:
        FIELD_CATALOG_STORE.sync_from_catalog(FIELD_CATALOG)
    except Exception:  # noqa: BLE001
        pass
    return FIELD_CATALOG_STORE.list(market=market, official=official)


from pydantic import BaseModel as _BaseModel  # noqa: E402


class _FieldInferRequest(_BaseModel):
    columns: list[str]
    market: str | None = None
    data_kind: str = "ohlcv"
    sample: dict | None = None


class _FieldMappingItem(_BaseModel):
    raw_column: str
    field_id: str
    is_freeform: bool = False


class _FieldMappingApplyRequest(_BaseModel):
    source: str
    data_kind: str = "ohlcv"
    mappings: list[_FieldMappingItem]


@app.post("/api/fields/infer-mapping")
def infer_field_mapping(req: _FieldInferRequest) -> dict:
    """字段映射向导：对一批原始列名给出对齐到 canonical 的建议（供前端/用户确认）。"""
    from .field_catalog.infer import infer_mapping_report

    return infer_mapping_report(req.columns, market=req.market, data_kind=req.data_kind, sample=req.sample)


@app.post("/api/fields/mapping")
def apply_field_mapping(req: _FieldMappingApplyRequest) -> dict:
    """把确认后的映射写入 (源, data_kind)。非法 field_id 返回 422。"""
    from .field_catalog import FieldMapping

    for m in req.mappings:
        try:
            FIELD_MAPPING_STORE.set(
                FieldMapping(
                    source=req.source,
                    data_kind=req.data_kind,
                    raw_column=m.raw_column,
                    field_id=m.field_id,
                    is_freeform=m.is_freeform,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"{m.raw_column}: {exc}") from exc
    return {"applied": len(req.mappings)}


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
def promote_model(model_id: str, payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict:
    """T-019：dev/archived 直翻；staging/production 开审批门（返 pending gate 或 422+缺口清单）。

    T-024 假设卡闸门（向后兼容，传 hypothesis_card_id 才启用，不破坏既有 promote）：
    - confirmatory 卡：先过 can_touch_final_oos（探索层/未冻结/OOS 已消费 → 409 BLOCK）。
    - 非 confirmatory 卡（exploratory/secondary）走真钱（production / live_crypto / paper）→ 409 拒：
      绝不自动晋级，晋级是用户显式动作（D-T024）。纯探索（无真钱意图）不挡（P2）。
    """
    hcid = payload.get("hypothesis_card_id")
    if hcid:
        try:
            _hcard = HYPOTHESIS_STORE.get(hcid)
        except KeyError as exc:
            raise HTTPException(404, f"假设卡不存在: {hcid}") from exc
        _real_money = (payload.get("stage") in {"production"}
                       or payload.get("execution_mode") in {"live_crypto", "paper"})
        if _hcard.layer == "confirmatory":
            _gate = _can_touch_final_oos(_hcard, honest_n_now=LEDGER.honest_n(_hcard.strategy_goal_ref))
            if not _gate.allow:
                raise HTTPException(409, detail={
                    "hypothesis_gate_blocked": True, "block_reason": _gate.block_reason,
                    "warnings": _gate.warnings, "disclaimer": _gate.disclaimer,
                })
        elif _real_money:
            raise HTTPException(409, detail={
                "hypothesis_gate_blocked": True,
                "block_reason": (f"假设卡 layer={_hcard.layer} 非 confirmatory，不得直接走真钱执行/晋级；"
                                 "先显式 promote 为 confirmatory 并冻结假设卡（P2/D-T024，晋级是用户显式动作）"),
            })
    try:
        result = MODEL_REGISTRY.promote(
            model_id, int(payload["version"]), payload["stage"],
            created_by=payload.get("created_by") or user.user_id,
            verification_record_id=payload.get("verification_record_id"),
            evidence=payload.get("evidence"),
            strategy_goal_ref=payload.get("strategy_goal_ref"),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except GateStateError as exc:
        raise HTTPException(422, str(exc)) from exc
    if isinstance(result, GateRejection):
        raise HTTPException(422, detail={"rejected": True, "gaps": result.gap_list,
                                         "gate_id": result.gate_id, "verdict_text": result.verdict_text})
    return result.to_dict()


@app.post("/api/models/{model_id}/gates/{gate_id}/approve")
def approve_promotion_gate(model_id: str, gate_id: str, payload: dict = Body(...),
                           user=Depends(require_user_dependency)) -> dict:
    """审批 pending promote 门并真翻 stage。approver≠creator / 缺要件 / 非 pending → 422。"""
    try:
        gate = MODEL_REGISTRY.approve_promotion(
            gate_id, approver=payload.get("approver") or user.user_id,
            reason=payload.get("reason", ""), risk_restated=payload.get("risk_restated"),
        )
    except (ApproverEqualsCreator, EmptyReason, GateStateError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return gate.to_dict()


@app.post("/api/models/{model_id}/gates/{gate_id}/reject")
def reject_promotion_gate(model_id: str, gate_id: str, payload: dict = Body(...),
                          user=Depends(require_user_dependency)) -> dict:
    try:
        return GATE_SERVICE.reject(gate_id, approver=payload.get("approver") or user.user_id,
                                   reason=payload.get("reason", "")).to_dict()
    except GateStateError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/approval/gates/{gate_id}")
def get_approval_gate(gate_id: str, user=Depends(require_user_dependency)) -> dict:
    """R2 一键下钻：暴露门状态/缺口清单/裁决文案。"""
    try:
        return APPROVAL_GATE_STORE.get(gate_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# -------- 部件12 · 验证官（异模型一致性，产 verdict_id；T-020）--------
@app.post("/api/verification/verdicts")
def create_verdict(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict:
    """对生成方自报值做异模型重算对账，产权威 verdict_id（落 VerdictStore，供审批门/假设卡引用）。

    body: {target_ref, generator_model, checker_model, claims:{k:v}, recomputed:{k:v},
           generator_seed?, checker_seed?, generator_slice?, checker_slice?, replay_ref?, notes?}
    异模型不一致即 verdict=blocked（不取均值）；同模型→独立性未确立降 concern。
    """
    from .verification import VerifierError
    try:
        rec = VERIFIER.reconcile(
            target_ref=payload.get("target_ref", ""),
            claims=payload.get("claims") or {},
            recomputed=payload.get("recomputed") or {},
            generator_model=payload.get("generator_model", ""),
            checker_model=payload.get("checker_model", ""),
            generator_seed=payload.get("generator_seed"),
            checker_seed=payload.get("checker_seed"),
            generator_slice=payload.get("generator_slice"),
            checker_slice=payload.get("checker_slice"),
            replay_ref=payload.get("replay_ref"),
            notes=payload.get("notes", ""),
            created_at_utc=_dt.datetime.now(_dt.UTC).isoformat(),
        )
    except VerifierError as exc:
        raise HTTPException(422, str(exc)) from exc
    VERDICT_STORE.record(rec)
    return rec.to_dict()


@app.get("/api/verification/verdicts/{verdict_id}")
def get_verdict(verdict_id: str, user=Depends(require_user_dependency)) -> dict:
    try:
        return VERDICT_STORE.get(verdict_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


# -------- 脊柱 04 · 可证伪假设卡端点（T-024，P2 不挡探索）--------
@app.post("/api/hypothesis_cards")
def create_hypothesis_card(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict:
    """建 draft 假设卡。P2：探索卡 falsifiable 可空，create 永不校验可证伪性。

    body: {strategy_goal_ref, layer, falsifiable?, touched_versions?, parent_card_id?}
    """
    try:
        card = HYPOTHESIS_STORE.create(
            strategy_goal_ref=payload["strategy_goal_ref"],
            layer=payload.get("layer", "exploratory"),
            falsifiable=payload.get("falsifiable"),
            touched_versions=payload.get("touched_versions"),
            parent_card_id=payload.get("parent_card_id"),
        )
    except KeyError as exc:
        raise HTTPException(422, f"缺字段: {exc}") from exc
    return card.to_dict()


@app.get("/api/hypothesis_cards/{card_id}")
def get_hypothesis_card(card_id: str, user=Depends(require_user_dependency)) -> dict:
    try:
        return HYPOTHESIS_STORE.get(card_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/hypothesis_cards/{card_id}/promote")
def promote_hypothesis_card(card_id: str, payload: dict = Body(...),
                            user=Depends(require_user_dependency)) -> dict:
    """探索→确认晋级（用户显式动作，D-T024）：校验新 OOS 切片未被源卡触碰过（防探索污染）。"""
    try:
        card = HYPOTHESIS_STORE.promote_to_confirmatory(card_id, payload["fresh_dataset_version"])
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except _PromoteRejected as exc:
        raise HTTPException(409, str(exc)) from exc
    return card.to_dict()


@app.post("/api/hypothesis_cards/{card_id}/freeze")
def freeze_hypothesis_card(card_id: str, payload: dict = Body(...),
                           user=Depends(require_user_dependency)) -> dict:
    """冻结 confirmatory 卡：三必填非空 + 可证伪性 + honest-N 实读（自 LEDGER，绝不收调用方传 N）。

    body: {frozen_oos:{dataset_version,...}, review?, human_reviewed?, override_note?}
    可证伪性 low + human_reviewed=False → 409（硬透明，不静默冻结）；human_reviewed=True 显式 override
    后仍可冻结，override 留痕进卡（D-T024-FALS，启发式绝不自动硬挡）。结构空机制 / 验证官 blocked 仍硬拒。
    """
    try:
        card = HYPOTHESIS_STORE.freeze(
            card_id,
            frozen_oos=payload.get("frozen_oos"),
            ledger=LEDGER,
            review=payload.get("review"),
            human_reviewed=bool(payload.get("human_reviewed", False)),
            override_note=payload.get("override_note"),
        )
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except _FreezeRejected as exc:
        raise HTTPException(409, str(exc)) from exc
    return card.to_dict()


@app.get("/api/hypothesis_cards/{card_id}/gate")
def hypothesis_card_gate(card_id: str, user=Depends(require_user_dependency)) -> dict:
    """can_touch_final_oos 软闸门：探索层/未冻结/OOS 已消费 → BLOCK；其余产风险提示 + needs_human_review。"""
    try:
        card = HYPOTHESIS_STORE.get(card_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    decision = _can_touch_final_oos(card, honest_n_now=LEDGER.honest_n(card.strategy_goal_ref))
    return decision.to_dict()


@app.post("/api/hypothesis_cards/{card_id}/deviation")
def hypothesis_card_deviation(card_id: str, payload: dict = Body(...),
                              user=Depends(require_user_dependency)) -> dict:
    """提交偏离：append + 自动降级标记 + 发 PROV 事件（deviations 非只读字段）。"""
    try:
        card = HYPOTHESIS_STORE.deviation(card_id, payload.get("deviation") or {})
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    return card.to_dict()


# -------- 模型中心 · 训练台 (v3) --------
# 训练台"本质是跑代码"：ML 进程内、DL/代码走全功率子进程。主进程不 import torch。
from .models.catalog import (  # noqa: E402
    add_model_card,
    get_model_card,
    model_catalog_summary,
)
from .models.card_loader import ModelCardError  # noqa: E402
from .training import TrainingRequest, TrainingService, spec_to_code  # noqa: E402
from .training.agent_context import training_system_prompt  # noqa: E402
from .training.datasets import list_training_datasets, load_training_panel  # noqa: E402

TRAINING_SERVICE = TrainingService(
    DATA_ROOT / "training_runs",
    experiment_store=EXPERIMENT_STORE,
    run_store=RUN_STORE,
    model_registry=MODEL_REGISTRY,
    timeout=1800,
)

from .training.tensorboard import TensorBoardManager  # noqa: E402

TENSORBOARD_MANAGER = TensorBoardManager()


@app.get("/api/training/models")
def training_models() -> list[dict]:
    """模型目录（类型卡：优缺点/调参 schema/算力/可用性）。"""
    return model_catalog_summary()


@app.get("/api/training/models/{key}")
def training_model_detail(key: str) -> dict:
    """单张模型卡详情（含 L1-L4 正文）。"""
    try:
        return get_model_card(key).to_detail()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/training/models")
def training_add_model(payload: dict = Body(...)) -> dict:
    """Agent/用户搜到新模型 → 补全信息加入模型卡（默认仅收录，runnable=False）。

    这是『agent 只能在卡内做，除非用户让它搜新模型加卡』的落点。
    """
    try:
        return add_model_card(payload).to_dict()
    except ModelCardError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/training/agent_context")
def training_agent_context() -> dict:
    """训练台对话 agent 的 system prompt（约束 agent 只能在模型卡内选）。"""
    return {"system_prompt": training_system_prompt()}


@app.get("/api/training/datasets")
def training_datasets() -> list[dict]:
    return list_training_datasets()


@app.post("/api/training/codegen")
def training_codegen(payload: dict = Body(...)) -> dict:
    """预览：把结构化 spec 渲染成将要跑的训练代码（让用户看到'本质是跑代码'）。"""
    try:
        return {"code": spec_to_code(payload)}
    except (KeyError, NotImplementedError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/training/jobs")
def training_jobs() -> list[dict]:
    return [j.to_dict() for j in TRAINING_SERVICE.list_jobs()]


@app.get("/api/training/jobs/{job_id}")
def training_job(job_id: str) -> dict:
    try:
        return TRAINING_SERVICE.get_job(job_id).to_dict()
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/training/jobs/{job_id}/eval")
def training_job_eval(job_id: str) -> dict:
    """训练结束的评价图（特征重要度/学习曲线/预测-实际/残差/ROC/分fold）。"""
    import json  # main.py 无模块级 json，函数内 import（与本文件其它端点一致）

    from .eval.model_eval import build_eval_charts, summarize_metrics

    try:
        job = TRAINING_SERVICE.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if not job.artifact_dir:
        return {"status": job.status, "charts": [], "metrics": {}}
    result_path = Path(job.artifact_dir) / "result.json"
    if not result_path.exists():
        return {"status": job.status, "charts": [], "metrics": job.metrics}
    result = json.loads(result_path.read_text(encoding="utf-8"))
    return {
        "status": job.status,
        "model": job.model,
        "family": job.family,
        "charts": build_eval_charts(result),
        "metrics": summarize_metrics(result),
    }


@app.post("/api/training/jobs/{job_id}/backtest")
def training_job_backtest(job_id: str, payload: dict = Body(default={})) -> dict:
    """用训练好的模型回测。支持样本外(OOS)：

    - `dataset_id`：在**另一个**数据集上回测（模型没训过的数据 → 真·样本外）。默认=训练数据集。
    - `oos_fraction`：只回测末尾这一比例的交易日（如 0.3 = 后 30%）。默认 None=全段。
    predict_with → 每日 top-N 权重(shift1 防前视) → 组合收益 → 指标 + 净值曲线。
    """
    from .training.backtest_bridge import backtest_job
    from .training.datasets import FEATURES

    try:
        job = TRAINING_SERVICE.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    if job.status != "succeeded" or not job.artifact_dir:
        raise HTTPException(400, f"任务未成功完成，无法回测（status={job.status}）")

    req = job.request or {}
    train_dataset = req.get("dataset_id") or "demo_ashare_xsec"
    # payload.dataset_id 优先（用户选的 OOS 数据集）；否则回训练集
    dataset_id = payload.get("dataset_id") or train_dataset
    feature_cols = req.get("feature_cols") or FEATURES
    oos_fraction = payload.get("oos_fraction")
    is_cross_dataset = dataset_id != train_dataset
    train_fraction = req.get("train_fraction")
    # 严格无泄露 walk-forward：若模型只用前 train_fraction 训练，且回测同一数据集、用户没显式指定
    # oos_fraction → 自动取互补的后段 (1 - train_fraction)，使回测窗口正好是训练未见过的那段。
    strict_oos = False
    if oos_fraction is None and train_fraction is not None and not is_cross_dataset:
        oos_fraction = 1.0 - float(train_fraction)
        strict_oos = True
    try:
        panel = load_training_panel(dataset_id)
    except KeyError as exc:
        raise HTTPException(400, f"未知数据集: {dataset_id}") from exc
    try:
        bt = backtest_job(
            job.artifact_dir,
            panel,
            feature_cols=feature_cols,
            symbol_col=req.get("symbol_col", "symbol"),
            top_n=int(payload.get("top_n", 5)),
            long_short=bool(payload.get("long_short", False)),
            oos_fraction=float(oos_fraction) if oos_fraction is not None else None,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc
    eq = bt["equity_curve"]
    return {
        "job_id": job_id,
        "model": job.model,
        "dataset_id": dataset_id,
        "train_dataset": train_dataset,
        "train_fraction": train_fraction,
        "is_oos": bool(is_cross_dataset or oos_fraction),
        "is_cross_dataset": is_cross_dataset,
        "strict_oos": strict_oos,  # True = 训练前段/回测后段严格互补、零泄露
        "oos_cutoff": bt.get("oos_cutoff"),
        "metrics": bt["metrics"],
        "equity_curve": [float(x) for x in eq.to_numpy()],
        "n_days": bt["n_days"],
        "n_symbols": bt["n_symbols"],
    }


@app.post("/api/training/jobs/{job_id}/tensorboard")
def training_tensorboard_start(job_id: str) -> dict:
    """为 DL 训练 job 启动 TensorBoard（独立端口），返回可直接打开的本机 URL。"""
    if not TENSORBOARD_MANAGER.is_available():
        raise HTTPException(400, "未安装 tensorboard")
    try:
        job = TRAINING_SERVICE.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    logdir = Path(job.artifact_dir) / "tb" if job.artifact_dir else None
    if not logdir or not logdir.exists():
        raise HTTPException(404, "该任务没有 TensorBoard 日志（仅 DL 训练产出）")
    try:
        inst = TENSORBOARD_MANAGER.start(job_id, logdir)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"url": inst.url, "port": inst.port, "job_id": job_id}


@app.get("/api/training/jobs/{job_id}/tensorboard")
def training_tensorboard_status(job_id: str) -> dict:
    inst = TENSORBOARD_MANAGER.get(job_id)
    if inst is None:
        return {"running": False, "available": TENSORBOARD_MANAGER.is_available()}
    return {"running": True, "url": inst.url, "port": inst.port}


@app.post("/api/training/jobs")
def training_submit(payload: dict = Body(...)) -> dict:
    """提交训练（异步，前端轮询 jobs/{id}）。dataset_id 选内置训练集。"""
    try:
        panel = load_training_panel(payload.get("dataset_id", ""))
    except KeyError as exc:
        raise HTTPException(400, f"未知数据集: {payload.get('dataset_id')}") from exc
    try:
        req = TrainingRequest(
            name=payload.get("name") or "训练任务",
            model=payload["model"],
            task=payload["task"],
            feature_cols=payload.get("feature_cols") or [],
            label_col=payload.get("label_col", "label"),
            asset_class=payload.get("asset_class", "a_share"),
            cv_scheme=payload.get("cv_scheme", "purged_kfold"),
            n_splits=int(payload.get("n_splits", 5)),
            group_col=payload.get("group_col"),
            symbol_col=payload.get("symbol_col", "symbol"),
            ts_col=payload.get("ts_col", "ts"),
            train_fraction=payload.get("train_fraction"),
            hyperparams=payload.get("hyperparams") or {},
            input_models=payload.get("input_models") or [],
        )
        job = TRAINING_SERVICE.submit(req, panel)
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return job.to_dict()


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
def llm_status() -> dict:
    """列出每个 provider 配置状态 + 当前 active provider。"""
    return {
        "providers": list_llm_status(KEYSTORE),
        "active_provider": os.environ.get("LLM_PROVIDER", "auto"),
    }


# ============================================================
# v1.0.3 · Stripe 订阅 endpoint (scaffold)
# ============================================================


@app.get("/api/billing/plans")
def billing_list_plans() -> list[dict[str, Any]]:
    return [
        {"id": p, **{k: v for k, v in PLAN_INFO[p].items() if not k.startswith("stripe_")}}
        for p in PLAN_IDS
    ]


@app.get("/api/billing/me")
def billing_me(user=Depends(require_user_dependency)) -> dict[str, Any]:
    return BILLING_SERVICE.get_subscription(user.user_id).to_dict()


@app.post("/api/billing/upgrade_request")
def billing_upgrade_request(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    plan = payload.get("plan", "")
    cycle = payload.get("billing_cycle", "monthly")
    if plan not in PLAN_IDS:
        raise HTTPException(400, f"plan must be one of {PLAN_IDS}")
    if plan == "community":
        from .billing.stripe_service import SubscriptionRecord as _SR
        import time as _t
        sub = BILLING_SERVICE.get_subscription(user.user_id)
        sub.plan = "community"
        sub.status = "active"
        BILLING_SERVICE.upsert_subscription(sub)
        return {"status": "downgraded", "plan": "community"}
    return {
        "status": "pending_payment",
        "plan": plan,
        "billing_cycle": cycle,
        "checkout_url": f"/stripe_checkout_stub?plan={plan}&cycle={cycle}&user_id={user.user_id}",
        "note": "scaffold - 接真 Stripe SDK 后此 URL 是 stripe.com/c/pay/cs_xxx",
    }


@app.post("/api/billing/webhook")
def billing_webhook(payload: dict = Body(...)) -> dict[str, Any]:
    try:
        result = BILLING_SERVICE.process_stripe_event(payload)
        return {"received": True, "result": result}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"webhook 处理失败: {exc}") from exc


@app.get("/api/billing/check_feature")
def billing_check_feature(feature: str = Query(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    ok = BILLING_SERVICE.user_can_access_feature(user.user_id, feature)
    return {"feature": feature, "allowed": ok}


# ============================================================
# v1.0 · mainnet 7 项防御 endpoint
# ============================================================


@app.get("/api/security/mainnet/config")
def mainnet_get_config(user=Depends(require_user_dependency)) -> dict[str, Any]:
    cfg = MAINNET_GUARDS.get_config(user.user_id)
    # 不回显加密 secret 给前端
    return {
        "user_id": cfg.user_id,
        "trusted_ips": cfg.trusted_ips,
        "totp_enabled": cfg.totp_enabled,
        "daily_operation_limit": cfg.daily_operation_limit,
        "daily_notional_limit_usdt": cfg.daily_notional_limit_usdt,
        "require_password_per_order": cfg.require_password_per_order,
        "updated_at_utc": cfg.updated_at_utc,
    }


@app.post("/api/security/mainnet/config")
def mainnet_update_config(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    cfg = MAINNET_GUARDS.get_config(user.user_id)
    if "trusted_ips" in payload:
        ips = payload["trusted_ips"]
        if not isinstance(ips, list):
            raise HTTPException(400, "trusted_ips 必须是 list")
        cfg.trusted_ips = [str(ip) for ip in ips]
    if "daily_operation_limit" in payload:
        cfg.daily_operation_limit = int(payload["daily_operation_limit"])
    if "daily_notional_limit_usdt" in payload:
        cfg.daily_notional_limit_usdt = float(payload["daily_notional_limit_usdt"])
    if "require_password_per_order" in payload:
        cfg.require_password_per_order = bool(payload["require_password_per_order"])
    MAINNET_GUARDS.upsert_config(cfg)
    return mainnet_get_config(user=user)


@app.post("/api/security/mainnet/2fa/enable")
def mainnet_2fa_enable(user=Depends(require_user_dependency)) -> dict[str, Any]:
    secret, uri = MAINNET_GUARDS.enable_totp(user.user_id)
    # 返回一次明文 secret + otpauth URI (前端展示 QR + 文字)
    return {"secret": secret, "otpauth_uri": uri, "enabled": True}


@app.post("/api/security/mainnet/2fa/verify")
def mainnet_2fa_verify(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    code = payload.get("code", "")
    ok = MAINNET_GUARDS.verify_totp(user.user_id, code)
    return {"ok": ok}


@app.get("/api/security/mainnet/usage")
def mainnet_today_usage(user=Depends(require_user_dependency)) -> dict[str, Any]:
    return MAINNET_GUARDS.get_today_usage(user.user_id)


@app.get("/api/security/mainnet/audit_log")
def mainnet_audit_log(limit: int = Query(100, ge=1, le=500), user=Depends(require_user_dependency)) -> list[dict[str, Any]]:
    return MAINNET_GUARDS.list_audit_log(user.user_id, limit=limit)


@app.post("/api/security/mainnet/emergency_close_all")
def mainnet_emergency_close_all(payload: dict = Body(...), user=Depends(require_user_dependency)) -> dict[str, Any]:
    """v1.0 · 紧急一键 cancel_all_open + close_position 全 symbol。

    不需要 TOTP（紧急情况），但必须 IP 白名单 + 密码再校验。
    """
    source_ip = payload.get("source_ip", "unknown")
    password_verified = bool(payload.get("password_verified", False))
    if not MAINNET_GUARDS.check_ip(user.user_id, source_ip):
        raise HTTPException(403, f"IP {source_ip} 不在白名单 - emergency 仍需 IP 校验")
    if not password_verified:
        raise HTTPException(403, "emergency_close_all 必须先验证密码")
    # T-025/D-T025：从空壳改为真执行——真调 KILL_SWITCH（cancel_all_open + close_position 全 symbol）。
    # 平仓本体 fail-open（门坏也要能平仓），护栏在上面的 IP+密码二次鉴权，不在「能不能平仓」。
    results = KILL_SWITCH.trigger(close_positions=True)
    # 含 venue 平仓失败 → 绝不报 ok:True（5-lens HIGH：操作者读 ok 会误信已平仓，真钱面不假绿灯）。
    ok, audit_result, err = _killswitch_status(results)
    MAINNET_GUARDS.log_operation(
        user.user_id, "emergency_close_all",
        source_ip=source_ip, password_verified=True, result=audit_result, error=err,
    )
    return {"ok": ok, "status": audit_result, "results": results}


@app.get("/api/security/binance/verify")
def security_binance_verify(network: str = Query("testnet")) -> dict[str, Any]:
    """v0.9.5+ · 真发签名请求验证 binance API key 是否真的是该 network。

    流程:
      1. 从 keystore 拿 binance_<network> record (绝不返回 key)
      2. 对 https://testnet.binancefuture.com/fapi/v1/apiKey/permissions 发签名 GET
         (或 mainnet 对应 url)
      3. 返回 {ok, is_correct_network, permissions, signed_url_base}
         · 签名通过 → key 真属于该 network
         · -2014/-2015 invalid api key → key 不属于该 network
         · 其他错误透传

    安全:
      - 整流程不暴露 api_key/secret 到响应或日志
      - 只返回 permission bool 字段（不返回 key/secret 自身）
      - 如果 key 验证为 mainnet 但 network=testnet（或反过来），明确警告
    """

    if network not in ("testnet", "mainnet"):
        raise HTTPException(400, "network must be testnet or mainnet")

    from .execution.binance_client import BinanceClient, BinanceCredentials
    from .security.keystore import KeystoreError

    try:
        record = KEYSTORE.fetch(f"binance_{network}")
    except KeystoreError:
        return {
            "ok": False,
            "error": "key_not_found",
            "detail": f"keystore 里没有 binance_{network}，secrets.yaml 是否填了 binance.{network}.api_key/api_secret？",
            "is_correct_network": None,
        }

    cred = BinanceCredentials(api_key=record.api_key, api_secret=record.api_secret, network=network)
    client = BinanceClient(cred, product="usdm_futures")

    base_url = client.base_url  # 已自动选 testnet/mainnet URL
    # 用 /fapi/v2/balance 验证 (testnet 必有 + 签名校验路径)
    try:
        payload = client._signed("GET", "/fapi/v2/balance", {})
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        if "-2014" in msg or "-2015" in msg or "API-key format invalid" in msg:
            err_kind = "invalid_api_key"
            detail = "API key 格式或权限有问题，大概率是把 mainnet key 填进了 testnet slot（反之同理）"
        elif "Signature" in msg or "-1022" in msg:
            err_kind = "bad_signature"
            detail = "签名校验失败 - api_secret 不匹配 api_key (复制时少了字符？)"
        elif "404" in msg:
            err_kind = "endpoint_not_found"
            detail = "endpoint 路径错；可能是 spot key 填进了 futures slot"
        else:
            err_kind = "unknown"
            detail = msg
        return {
            "ok": False,
            "error": err_kind,
            "detail": detail,
            "raw_error": msg,
            "signed_url_base": base_url,
            "is_correct_network": False,
            "remediation": (
                "1. 确认 https://testnet.binancefuture.com 的 API Key 和 Secret 完整复制（Secret 只显示一次，可能漏字符）\n"
                "2. testnet key 不定期失效，需要重新生成\n"
                "3. 不要把 testnet.binance.vision (spot) 的 key 填到 futures 这边"
            ),
        }

    # 签名通过 → key 真属于该 network；payload 是余额列表
    # Permission 信息走另一个 endpoint（如 /fapi/v1/account 或 testnet 直接根据下单结果推断）
    asset_count = len(payload) if isinstance(payload, list) else 0
    total_usdt = 0.0
    if isinstance(payload, list):
        for asset in payload:
            if asset.get("asset") == "USDT":
                try:
                    total_usdt = float(asset.get("balance", 0))
                except (TypeError, ValueError):
                    pass
                break

    return {
        "ok": True,
        "is_correct_network": True,
        "network": network,
        "signed_url_base": base_url,
        "assets_count": asset_count,
        "usdt_balance": total_usdt,
        "safekey_status": "PASS",
        "note": (
            f"✅ testnet key 验证通过。"
            f"账户有 {asset_count} 种资产，USDT 余额 {total_usdt:.2f}。"
            f"如果 USDT=0，去 testnet.binancefuture.com → Wallet → 领取 testnet 测试 USDT。"
            if network == "testnet"
            else f"⚠️ MAINNET key 验证通过。USDT 余额 {total_usdt:.2f}。请先确认 enableWithdrawals=False 再下单。"
        ),
    }


@app.post("/api/llm/active")
def llm_set_active(payload: dict = Body(...)) -> dict[str, Any]:
    """v0.9.5 · 进程内切 active LLM provider。不持久化到 secrets.yaml；重启回 auto。

    安全考虑：
    - 仅允许切到 already-configured 的 provider（防 enum injection）
    - 不接受 base_url/api_key 修改（那是 /api/llm/configure 的事）
    """

    provider = (payload.get("provider") or "").strip().lower()
    if provider not in ("auto", "anthropic", "openai", "qwen", "custom"):
        raise HTTPException(400, "provider must be auto/anthropic/openai/qwen/custom")
    if provider != "auto":
        # 校验该 provider 真已配置
        statuses = list_llm_status(KEYSTORE)
        match = next((s for s in statuses if s["provider"] == provider), None)
        if not match or not match.get("configured"):
            raise HTTPException(400, f"provider {provider} 未配置 (configured=False)，请先去 /api/llm/configure")
    if provider == "auto":
        os.environ.pop("LLM_PROVIDER", None)
    else:
        os.environ["LLM_PROVIDER"] = provider
    return {"active_provider": os.environ.get("LLM_PROVIDER", "auto")}


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


# --- 官方数据更新通道（与软件更新分两条线；客户端 Win/Mac 据此下载官方数据库更新）-----------

def _official_catalog_files() -> list[dict]:
    from .tushare_quant1.data_catalog import load_data_catalog

    return load_data_catalog(_QB_PATHS, rebuild_if_missing=True).get("files") or []


@app.get("/api/data-packages/manifest")
def data_package_manifest() -> dict:
    """官方数据清单 + 数据版本号 + 每文件指纹 + 官方字段定义。客户端据此算增量、并把 official_fields 合并进本地字段表。"""
    from .data_packages import official_manifest

    m = official_manifest(_official_catalog_files(), _QB_PATHS.root)
    try:
        FIELD_CATALOG_STORE.sync_from_catalog(FIELD_CATALOG)
    except Exception:  # noqa: BLE001
        pass
    m["official_fields"] = FIELD_CATALOG_STORE.list(official=True)  # 供客户端 merge_official 合并
    return m


@app.get("/api/data-packages/download")
def data_package_download(paths: str | None = Query(None)):
    """下载官方数据 zip（内含 manifest.json）。paths=逗号分隔相对路径→增量；省略→全量。

    按 data_version 缓存复用（避免每次重压 + 客户端断连导致临时文件泄漏）。
    """
    import hashlib as _hl

    from fastapi.responses import FileResponse

    from .data_packages import build_package_zip, official_manifest

    files = _official_catalog_files()
    manifest = official_manifest(files, _QB_PATHS.root)
    try:
        FIELD_CATALOG_STORE.sync_from_catalog(FIELD_CATALOG)
        manifest["official_fields"] = FIELD_CATALOG_STORE.list(official=True)  # 让 zip 内 manifest 带官方字段定义供客户端合并
    except Exception:  # noqa: BLE001
        pass
    version = manifest["data_version"]
    rel = [p for p in paths.split(",") if p.strip()] if paths else None
    key = version if rel is None else f"{version}-{_hl.sha256(','.join(sorted(rel)).encode()).hexdigest()[:10]}"
    cache_dir = DATA_ROOT / "_cache" / "data-packages"
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / f"quantbt-official-data-{key}.zip"
    if not out.exists():
        build_package_zip(files, _QB_PATHS.root, out, rel_paths=rel, manifest=manifest)
    return FileResponse(out, media_type="application/zip", filename=out.name)


class _DataPullUpstreamRequest(_BaseModel):
    upstream_url: str
    paths: list[str] | None = None


@app.post("/api/data-packages/pull")
def data_package_pull(req: _DataPullUpstreamRequest) -> dict:
    """客户端(Win/Mac 本地后端)从上游网站拉官方数据更新并应用：防 zip-slip 解压进本地数据湖 →
    重建 inventory → 把 official_fields 合并进字段宇宙表。与软件更新是两条独立通道。"""
    from .data_packages import pull_and_apply

    report = pull_and_apply(req.upstream_url, DATA_ROOT, paths=req.paths)
    try:
        _rebuild_inventory()
    except Exception:  # noqa: BLE001
        pass
    merged = 0
    try:
        merged = FIELD_CATALOG_STORE.merge_official(report.get("official_fields") or [])
        FIELD_CATALOG_STORE.sync_from_catalog(FIELD_CATALOG)
    except Exception:  # noqa: BLE001
        pass
    return {
        "applied_files": len(report.get("applied_files") or []),
        "skipped": len(report.get("skipped") or []),
        "data_version": report.get("data_version"),
        "merged_official_fields": merged,
    }


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


def _killswitch_status(results: dict[str, Any]) -> tuple[bool, str, str | None]:
    """据 KILL_SWITCH.trigger 的 per-venue results 派生【诚实】状态——绝不一律 ok（不假绿灯）。

    trigger 是 fail-open（cancel/close 抛错不上抛，塞 {error,stage,...} 进 results）：故含 error 项时
    顶层绝不能报 ok=True。全成功→ok/ok；部分失败→partial；全失败→failed。失败 symbol/error 透传供审计。
    （5-lens 复核 HIGH：真钱急停最不容假绿灯——含失败的平仓硬编码 ok:True = 🟡当✅。）
    """
    items = [it for v in (results or {}).values() for it in v if isinstance(it, dict)]
    errors = [it for it in items if it.get("error")]
    if not errors:
        return True, "ok", None
    audit = "failed" if len(errors) == len(items) else "partial"
    return False, audit, "; ".join(str(it.get("error")) for it in errors[:5])


@app.post("/api/risk/kill_switch")
def trigger_kill_switch(payload: dict = Body(default_factory=dict),
                        user=Depends(require_user_dependency)) -> dict:
    """急停红按钮：撤单 + 平仓全 symbol。

    D-T025：护栏放在「谁能按按钮」= 人在环 IP + 密码二次鉴权（复用 mainnet_guards）；平仓/撤单本体
    fail-open（风险降低动作永不被策略门挡——门坏也要能救命平仓，与「下新单 fail-closed」相反方向）。
    """
    source_ip = payload.get("source_ip", "unknown")
    if not MAINNET_GUARDS.check_ip(user.user_id, source_ip):
        raise HTTPException(403, f"IP {source_ip} 不在白名单 - kill_switch 需 IP 校验")
    if not bool(payload.get("password_verified", False)):
        raise HTTPException(403, "kill_switch 必须先验证密码")
    close = bool(payload.get("close_positions", True))
    results = KILL_SWITCH.trigger(close_positions=close)
    ok, audit_result, err = _killswitch_status(results)   # 含 venue 失败 → 绝不报 ok（不假绿灯）
    MAINNET_GUARDS.log_operation(user.user_id, "kill_switch", source_ip=source_ip,
                                 password_verified=True, result=audit_result, error=err)
    return {"ok": ok, "status": audit_result, "results": results}


# -------- M14 Agent --------

@app.get("/api/agent/tools")
def agent_tools() -> dict[str, Any]:
    # T-028：诚实暴露每个 schema 工具的真实可用状态（live/stub/unwired）+ 副作用级别——
    # 打击「能力名不副实」（schema 声明 N 个、实际只接通部分），符合 R25「弱点一等呈现」。
    rt = _agent_runtime()
    registered = set(rt._tools.keys())
    stub = {"factor.run_ic"}  # 已注册但未接真引擎（仅返回 queued）
    tool_status = []
    for fn in TOOL_SCHEMA:
        name = fn.get("name") or fn.get("function", {}).get("name", "")
        status = "unwired" if name not in registered else ("stub" if name in stub else "live")
        tool_status.append({"name": name, "status": status, "side_effect": rt._side_effects.get(name, "none")})
    return {"functions": TOOL_SCHEMA, "llm_provider": AGENT_LLM.provider, "tool_status": tool_status}


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
            max_leverage=(float(payload["max_leverage"]) if payload.get("max_leverage") is not None else None),
        )
        return f.to_dict()
    except (CopyTradeError, ValueError) as exc:
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
            leverage=(float(payload["leverage"]) if payload.get("leverage") is not None else None),
            note=payload.get("note", ""),
        )
    except (CopyTradeError, KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    # relay → 所有 active follower 真下单。T-021：enforce_gate=True → 必经会话外硬墙
    # （deny-by-default 策略门 + 防重放 + 真钱档 fail-closed），INV-2/M17 生产强制；beta=幂等+杠杆硬截断。
    relayer = SignalRelayer(
        COPY_TRADE_SERVICE, KEYSTORE, _binance_venue_for_follower, beta=CT_BETA_SERVICE,
        enforce_gate=True, nonce_ledger=RELAY_NONCE_LEDGER, broker=ORDER_BROKER,
    )
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


@app.get("/api/runs/compare")  # type: ignore[misc]
def _compare_runs_with_risk(run_ids: list[str] = Query(...)) -> dict:  # type: ignore[assignment]
    """v0.9.4 · 在 compare 响应每个 run 上追加 risk_summary，便于 ComparePage 显示信任色块。"""
    resp = compare_runs_response(run_ids)
    from .eval.risk_summary import compute_risk_summary
    runs = resp.get("runs") or []
    for r in runs:
        # 合并 metrics + jq_overview_metrics + overall (compare 用 overall snapshot)
        combined: dict[str, Any] = {}
        for src_key in ("metrics", "jq_overview_metrics", "overall", "out_of_sample"):
            v = r.get(src_key)
            if isinstance(v, dict):
                combined.update(v)
        r["risk_summary"] = compute_risk_summary(combined).to_dict()
    return resp


@app.get("/api/runs/compare_legacy")
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
        fields_by_market=_field_universe_for_prompt(payload.get("market")),
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
        fields_by_market=_field_universe_for_prompt(),
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

    # T-015：preview 也经多证据三角 gate（record=False，不刷 honest-N），把 dsr/pbo 注入
    # metrics → 让 risk_summary 的 _rule_dsr/_rule_pbo 从「永远拿 None」变真生效。
    gate_verdict = None
    eq = result.get("equity_curve") if isinstance(result, dict) else None
    if isinstance(eq, list) and len(eq) >= 2:
        try:
            from .eval.gate_runner import asset_class_of, evaluate_overfit_gate, freq_to_ppy
            from .ide.promote import _normalize_equity_curve
            rows = _normalize_equity_curve(eq)
            returns = [r["net_return"] or 0.0 for r in rows]
            meta = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
            market = str(meta.get("market") or "crypto_perp")
            freq = str(meta.get("frequency") or "1d")
            theme = str(meta.get("research_theme_id") or meta.get("strategy_name") or ide_run.strategy_id)
            if len(returns) >= 2:
                gr = evaluate_overfit_gate(
                    returns=returns, factor=meta.get("factor_formula") or ide_run.strategy_id,
                    params=meta.get("params") or {}, universe=market,
                    dataset_version=str(meta.get("dataset_version") or "unknown"),
                    freq=freq, label="net_return",
                    strategy_goal_ref=theme, asset_class=asset_class_of(market),
                    periods_per_year=freq_to_ppy(freq),
                    ledger=LEDGER, returns_store=RETURNS_STORE, record=False,
                )
                v = gr.verdict
                if v.color != "insufficient_evidence":
                    metrics_combined["dsr"] = v.dsr_conservative
                    if v.pbo is not None:
                        metrics_combined["pbo"] = v.pbo
                gate_verdict = v.to_dict()
                gate_verdict["honest_n"] = gr.honest_n
        except Exception as exc:  # noqa: BLE001  preview 不因 gate 失败而 500，但【不静默】——标错给前端
            _main_logger.warning("risk_preview gate 失败: %s", exc, exc_info=True)
            gate_verdict = {"error": type(exc).__name__}

    from .eval.risk_summary import compute_risk_summary
    rs = compute_risk_summary(metrics_combined).to_dict()
    return {"risk_summary": rs, "metrics_used": metrics_combined, "gate_verdict": gate_verdict}


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
            ledger=LEDGER,                 # T-015：记账 honest-N + 跑多证据三角 gate
            returns_store=RETURNS_STORE,
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
        "gate_verdict": promoted.gate_verdict,   # T-015 多证据三角裁决（前端下钻用）
    }


@app.get("/api/research/themes/{theme}/honest_n")
def research_theme_honest_n(theme: str, user=Depends(require_user_dependency)) -> dict[str, Any]:
    """R2 一键下钻：暴露某研究主题的 honest-N（名义 distinct config 计数）+ 诚实免责。

    只读、不可改小（T-013 一本账无 set_n/delete API）。N_eff 区间在各 run 的 gate_verdict 里。
    """

    from .lineage.ledger import HONEST_N_DISCLOSURE

    return {
        "strategy_goal_ref": theme,
        "honest_n": LEDGER.honest_n(theme),
        "disclaimer": HONEST_N_DISCLOSURE,
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

    # 2. Agent（T-027/D-PERM）：经 AgentRuntime 支持工具派发 + 权限三态（ask/auto/bypass），
    #    替代裸 client.chat。无副作用工具 auto/bypass 自主执行；动钱/晋级永不注册（治理门在端点层）。
    permission_mode = str(payload.get("permission_mode") or "auto")
    try:
        runtime = _agent_runtime(permission_mode=permission_mode, system_prompt=sys_prompt)
        turn = runtime.run(user_text)
        reply_text = turn.final_message or "(LLM 无内容)"
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
        full_text = ""
        try:
            client = _current_agent_llm()
            # v0.9.8 · 真 streaming - 调 stream_chat() iterator
            for token in client.stream_chat([
                LLMMessage(role="system", content=sys_prompt),
                LLMMessage(role="user", content=user_text),
            ]):
                full_text += token
                yield f"data: {_json.dumps({'chunk': token}, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            err_text = f"[LLM 错误] {exc}"
            full_text = full_text or err_text
            yield f"data: {_json.dumps({'chunk': err_text, 'error': True}, ensure_ascii=False)}\n\n"

        # 持久化 + done
        msg = CHAT_SERVICE.add_message(
            thread_id, "assistant", full_text,
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
