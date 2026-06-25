"""LLM Gateway · 调用账（LLMCallRecord）+ 三道治理门（GOAL §1 / §7）。

LLMCallRecord 是 GOAL §1 的对象之一：每次模型调用落一条可审计账，进 RDP。
本模块只放「账 + 门」，不碰路由 / 凭据 / provider（那些在 routing / credential_pool / gateway）。

三道门（每道配「种坏门必抓」的变异测试，见 tests/test_llm_gateway.py）：
1. `assert_record_admissible`  —— 缺 provider/model/auth_ref/replay_state → 拒（§1 可证伪验收）。
2. `assert_no_plaintext_secret` —— 任一已知明文 secret 出现在 record 的序列化/导出面 → 拒
   （致命红线：实盘 key/secret 不进 LLM/RAG/日志/导出·只 SecretRef 引用）。
3. `seal_record` / `verify_record_seal` —— gateway 给每条账盖 HMAC 封印：下游准入只认
   gateway 亲手出的账，绕过 Gateway 自造的账验不过封 → 拒（§7「AgentLLMCall 绕过 LLM Gateway → 拒」）。

诚实限界（不会再改的设计极限）：
- 封印 = **治理 provenance 证据**（证明这条账确由本 gateway 实例铸出），**不是**密码学意义上
  对「同进程内恶意构造者」的防御——Python 进程里没人能真正禁止 `import requests` 直打 API。
  能做、且 GOAL 真正要求的是：**绕过 gateway 产出的 LLM 结果对 Research Graph 不可准入**。
- secret 扫描按「已知明文逐字匹配」——它抓「真把某条在册 secret 写进了账/prompt」，
  不号称能识别任意未在册的高熵串（那是另一层启发式，不在此门的诚实承诺内）。
"""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from ..lineage.ids import canonical_json, content_hash

# —— 复用单一身份源（RULES.project：身份源 lineage/ids.py，不另造）——
# call_id / prompt_digest 都走 ids.content_hash 哈希族，不自立第二套。

SEAL_LEN = 32                 # HMAC-SHA256 hexdigest 取前 32 位（128-bit provenance 标签）
MIN_SECRET_SCAN_LEN = 8       # 短于此的「secret」不参与逐字扫描，避免把 "abc" 这类误报成泄露


class ReplayState(str, Enum):
    """这条调用的 record/replay 处境（LLMCallRecord 必填四要素之一）。"""

    LIVE = "live"               # 真打 provider，未经 record/replay 装置
    RECORDED = "recorded"       # record 模式 miss → 真打 + 落不可变 fixture
    REPLAYED = "replayed"       # 命中 fixture → 零真调用（R11：replay miss 绝不回退打真 API）
    PASSTHROUGH = "passthrough"  # passthrough 模式：真打、不落账


_VALID_REPLAY_STATES = frozenset(s.value for s in ReplayState)


class CallStatus(str, Enum):
    OK = "ok"
    ERROR = "error"          # provider 报错 / 全 fallback 用尽
    REFUSED = "refused"      # 被安全门拒（prompt 含明文 secret / 难任务强制降质拒绝）


@dataclass
class IndependenceRecord:
    """Verifier/Critic 独立性边界（GOAL §7：独立挑战须把独立性写进 LLMCallRecord）。"""

    required: bool = False
    satisfied: bool = False
    distinct_provider: bool = False
    distinct_model: bool = False
    builder_call_id: str | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class LLMCallRecord:
    """一次 LLM 调用的可审计账（GOAL §1 对象 · 进 RDP）。

    必填四要素（缺一即 `assert_record_admissible` 拒）：provider / model / auth_ref / replay_state。
    `auth_ref` 永远是 SecretRef 引用串（如 `secretref://anthropic/llm_anthropic`），**绝非明文 key**。
    原始 prompt 不入账（只存 `prompt_digest` 内容哈希）——既防明文 secret 顺 prompt 落账，也省体积。
    """

    # —— 必填四要素（§1）——
    provider: str
    model: str
    auth_ref: str
    replay_state: str

    # —— 路由账（D-LLM-ROUTING：记每次实际路由的模型 + 档位，可审计）——
    role: str = ""
    task_difficulty: str = ""
    risk_level: str = ""
    tier_requested: str = ""
    tier_resolved: str = ""
    degraded: bool = False                 # 难任务被降到不适配轻模型 → True（绝不静默）
    degrade_reason: str = ""

    # —— 独立性（§7 Verifier/Critic）——
    independence: IndependenceRecord = field(default_factory=IndependenceRecord)

    # —— provider 健康 / 配额 / fallback ——
    provider_health: str = "unknown"       # healthy / degraded / down / unknown
    quota_state: str = "unknown"           # ok / exhausted / unknown
    fallback_used: bool = False
    fallback_chain: list[str] = field(default_factory=list)

    # —— 调用元数据（无明文 secret · 无原始 prompt 明文）——
    call_id: str = ""                      # 内容寻址身份（复用 ids.content_hash）
    session_id: str = ""
    prompt_digest: str = ""                # content_hash(messages) —— 只存指纹，不存原文
    base_url_redacted: str = ""
    fixture_key: str | None = None
    started_at: str = ""
    finished_at: str = ""
    latency_ms: float | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    status: str = CallStatus.OK.value
    error_kind: str = ""
    repro_level: str = "decision"

    # —— gateway 封印（治理 provenance；不是密码学防御，见模块 docstring）——
    seal: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def sealable_payload(self) -> dict[str, Any]:
        """除 `seal` 外全部字段——封印 / secret 扫描都对它做。"""

        data = asdict(self)
        data.pop("seal", None)
        return data


# ============ 门 1：必填四要素 ============

class LLMRecordError(RuntimeError):
    pass


REQUIRED_FIELDS: tuple[str, ...] = ("provider", "model", "auth_ref", "replay_state")


def assert_record_admissible(record: LLMCallRecord) -> None:
    """缺 provider/model/auth_ref/replay_state → 拒（§1 可证伪验收）。

    种坏门必抓：把任一必填置空 → 此门必抛（tests::test_gate_missing_field_*）。
    """

    missing = [f for f in REQUIRED_FIELDS if not str(getattr(record, f, "") or "").strip()]
    if missing:
        raise LLMRecordError(
            f"LLMCallRecord 缺必填字段 {missing}——§1：缺 provider/model/auth_ref/replay_state → 拒"
        )
    if record.replay_state not in _VALID_REPLAY_STATES:
        raise LLMRecordError(
            f"replay_state={record.replay_state!r} 非法（须 ∈ {sorted(_VALID_REPLAY_STATES)}）"
        )


# ============ 门 2：明文 secret 绝不进账 / 导出 ============

class SecretLeakError(RuntimeError):
    """致命红线：实盘 key/secret 进 LLM/RAG/日志/导出。出现即停工级。"""


def _scan_blob_for_secret(blob: str, secret_values: Iterable[str]) -> str | None:
    for val in secret_values:
        if val and len(val) >= MIN_SECRET_SCAN_LEN and val in blob:
            return val
    return None


def assert_no_plaintext_secret(
    record: LLMCallRecord,
    secret_values: Iterable[str],
    *,
    extra_text: str = "",
) -> None:
    """断言任一已知明文 secret 绝不出现在 record 的序列化形态（落账 / 导出 / 日志面）。

    这是「实盘 key/secret 不进日志/导出」红线的落地门：gateway 持有调用时真用的明文，
    于是能逐字断言它没漏进账的任何字段。报错信息**绝不回显** secret 本身。

    种坏门必抓：把明文 key 塞进 record 任一字段 → 此门必抛（tests::test_gate_secret_in_record_*）。
    """

    blob = canonical_json(record.sealable_payload())
    if extra_text:
        blob = blob + "\x00" + extra_text
    hit = _scan_blob_for_secret(blob, secret_values)
    if hit is not None:
        # 只报「哪个字段族泄露 + 长度」，绝不打印 secret。
        raise SecretLeakError(
            f"明文 secret（len={len(hit)}）进入 LLMCallRecord 序列化面——"
            "致命红线：实盘 key/secret 不进 LLM/RAG/日志/导出，只允许 SecretRef 引用"
        )


def scan_messages_for_secret(messages_text: str, secret_values: Iterable[str]) -> str | None:
    """扫出向 provider 发出的 prompt 文本里夹带的在册明文 secret（返回命中值供门判断，调用方不得打印）。"""

    return _scan_blob_for_secret(messages_text, secret_values)


# ============ 门 3：gateway 封印（绕过 Gateway 的账验不过 → 不可准入）============

def seal_record(record: LLMCallRecord, secret: bytes) -> str:
    """对 record（除 seal 外全字段的规范 JSON）做 HMAC-SHA256，取前 SEAL_LEN 位。"""

    msg = canonical_json(record.sealable_payload()).encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:SEAL_LEN]


def verify_record_seal(record: LLMCallRecord, secret: bytes) -> bool:
    """常数时间校验封印——只有用同一 gateway 实例 nonce 才能复算出同一封印。"""

    if not record.seal:
        return False
    expected = seal_record(record, secret)
    return hmac.compare_digest(expected, record.seal)


# ============ §7 Verifier 独立性裁决 ============

@dataclass
class IndependenceVerdict:
    independent: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_independence(builder: LLMCallRecord, verifier: LLMCallRecord) -> IndependenceVerdict:
    """裁定 verifier 对 builder 的挑战是否独立（GOAL §7）。

    规则：
    - verifier 缺 provider/model/上下文记录 → 独立性不足（无从证明独立）。
    - verifier 与 builder 同 provider+model 且**声称已满足独立**（satisfied=True）→ 假独立，拒。
    - verifier 与 builder 同源但**诚实标注** satisfied=False → 不独立但未撒谎（reason 说明）。
    - provider 或 model 不同源 → 独立成立。

    种坏门必抓：让 gateway 在同源时仍把 satisfied 置 True → 此裁决判 `independent=False`
    且点出「假独立」（tests::test_gate_verifier_independence_*）。
    """

    if not (verifier.provider and verifier.model and verifier.prompt_digest):
        return IndependenceVerdict(False, "verifier 缺 provider/model/context 记录——独立性不足（§7）")

    same_provider = builder.provider == verifier.provider
    same_model = builder.model == verifier.model
    if same_provider and same_model:
        if verifier.independence.satisfied:
            return IndependenceVerdict(
                False,
                "verifier 与 builder 同 provider+model 却声称独立——假独立，标独立性不足（§7）",
            )
        return IndependenceVerdict(
            False,
            "verifier 与 builder 同源（已诚实标 satisfied=False）——独立性不足",
        )
    return IndependenceVerdict(True, "verifier 与 builder provider/model 不同源——独立性成立")


def make_call_id(*, prompt_digest: str, provider: str, model: str, role: str, session_id: str, seq: int) -> str:
    """调用账身份 = 内容寻址（复用 ids.content_hash，不另造）。"""

    return content_hash(
        {
            "prompt_digest": prompt_digest,
            "provider": provider,
            "model": model,
            "role": role,
            "session_id": session_id,
            "seq": seq,
        }
    )


__all__ = [
    "CallStatus",
    "IndependenceRecord",
    "IndependenceVerdict",
    "LLMCallRecord",
    "LLMRecordError",
    "MIN_SECRET_SCAN_LEN",
    "REQUIRED_FIELDS",
    "ReplayState",
    "SEAL_LEN",
    "SecretLeakError",
    "assert_no_plaintext_secret",
    "assert_record_admissible",
    "evaluate_independence",
    "make_call_id",
    "scan_messages_for_secret",
    "seal_record",
    "verify_record_seal",
]
