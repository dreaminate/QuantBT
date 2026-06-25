"""Artifact 完整信任门 —— GOAL §15「producer-run + hash binding / allowlist / safe tensors」。

lib.py 的止血(`_RestrictedUnpickler` blocklist + `torch.load(weights_only=True)`)只降攻击面、
堵直球 RCE。本模块把它补成【完整信任门】(扩展不替换,止血代码一行不删),三件事:

  ① `ArtifactTrustStore` —— append-only JSONL 信任登记(content-addressed,prev_hash 链防事后篡改)。
     绑定【完整 256-bit sha256 → producer-run】:只有【系统自产并经 register() 登记】的 artifact 的
     full-sha256 命中才放行;外来 / 未登记 / 被改一个字节 → full-sha256 不命中 → 拒(验收 #1)。
     身份 id 复用 `ids.content_hash`(单一身份源红线);安全【绑定键】用完整 256-bit sha256,
     **不**用 content_hash 的 16 位截断(64-bit 抗碰撞不足以当安全白名单键)。

  ② `TrustPolicy` —— 把信任门接到 load 路径。**默认 `enforce=False`(向后兼容)**:产出侧 producer
     的 `register()` 接线在本卡领地外(`app/models/training.py` / `app/models/dl/trainer.py`),
     默认硬开会误伤所有现存 artifact、破基线。**致命红线「不安全反序列化」由 lib.py 的 always-on
     safe-loader 无条件守住**;信任门是其上的【来源】门,enforce 时才查登记。

  ③ DL 安全加载 —— `load_dl_checkpoint`:safe tensors(+ JSON config)优先(零 pickle、构造上无代码
     执行);`.pt` 走 `weights_only=True` 且【绝不静默回落 `weights_only=False`】(验收 #3),失败显式
     raise;safetensors 缺包【绝不回落 pickle/.pt】,显式 raise。

诚实边界(裁决说「证据/边界」,不说「绝对安全」):
- full-sha256 命中是【来源下界】:能写 artifact【且】能写本登记文件的攻击者仍可自登记(与 ledger 的
  末尾截断同源的单机局限,需外部公证根除,超出本模块)。本门拦的是【外来 / 未登记 artifact 直接喂
  load】—— 那才是 §15 命门。
- 默认 `enforce=False`:本卡只在领地内(lib.py + 本文件)兑现【机制 + 对抗验证】。把产出侧 producer 接
  `register()`、把 load 默认翻成 enforce、安装 safetensors 依赖,是明确标注的 follow-on(产出侧在领地外)。

**为何不写进 honest-N `Ledger`**:那本账按 (config_hash, strategy_goal_ref) 计 honest_n;artifact
登记若混进去会让每次 register 污染试验计数(honest-N 虚高)。故信任登记自有 append-only 存储,
只复用 `ids.content_hash` 身份函数 + 沿用 ledger 的「append-only JSONL + prev_hash 链」设计。
"""

from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# 单一身份源红线:复用 ids.content_hash / HASH_LEN,绝不另造哈希族。
from ..lineage.ids import HASH_LEN, content_hash

# ── 落盘 / 常量 ──────────────────────────────────────────────────────────────
_TRUST_SCHEMA = "artifact-trust-v1"
TRUST_JSONL_FILENAME = "artifact_trust.jsonl"
GENESIS_HASH = "0" * HASH_LEN  # prev_hash 链创世(16 位全零,与全库 HASH_LEN 对齐)


class ArtifactTrustError(Exception):
    """artifact 未过信任门:未登记 / full-sha256 不命中 / DL 拒静默降级 / safetensors 缺包拒回落。"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _artifact_kind_of(path: Path) -> str:
    s = path.suffix.lower()
    if s in (".pkl", ".joblib"):
        return "pickle"
    if s == ".pt":
        return "torch"
    if s == ".safetensors":
        return "safetensors"
    return "unknown"


def artifact_fingerprint(path: str | Path) -> tuple[str, str]:
    """返回 (full_sha256, content_id)。

    - `full_sha256`：完整 256-bit sha256(hex),= 信任门的【安全绑定键】(抗碰撞)。
    - `content_id`：`ids.content_hash` 产出(16 位,单一身份源),= 索引/展示 id,不当安全键。
    """
    data = Path(path).read_bytes()
    full = hashlib.sha256(data).hexdigest()
    content_id = content_hash({"artifact_sha256": full, "schema": _TRUST_SCHEMA})
    return full, content_id


@dataclass
class TrustRecord:
    """一条 artifact 信任登记 = (full-sha256 ↔ producer-run) 绑定。"""

    artifact_sha256: str   # 完整 256-bit(安全绑定键)
    content_id: str        # ids.content_hash(单一身份源,索引)
    producer_run: str      # 产出此 artifact 的 run/job 身份(provenance,不可为空)
    producer_kind: str     # "ml_train" | "dl_train" | ...(谁产的)
    artifact_kind: str     # pickle | torch | safetensors
    created_at_utc: str = field(default_factory=_now)
    note: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


class ArtifactTrustStore:
    """append-only JSONL 信任登记(prev_hash 链防事后篡改;content-addressed)。

    硬约束:无 unregister/delete API(append-only);信任 ⇔ 文件当前 full-sha256 命中某条已登记记录。
    artifact 被改一个字节 → sha256 变 → 不命中 → 拒(tamper-evident)。
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / TRUST_JSONL_FILENAME
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()
        self._next_seq, self._last_hash = self._scan_tail()

    # —— 内部:读 / 哈希链 ——
    def _read_records(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # 容忍崩溃中途写坏的(通常末尾)行,与 ledger 同策,不让一行炸全库
        return out

    def _scan_tail(self) -> tuple[int, str]:
        last_hash, next_seq = GENESIS_HASH, 0
        for rec in self._read_records():
            last_hash, next_seq = rec["row_hash"], rec["seq"] + 1
        return next_seq, last_hash

    @staticmethod
    def _row_hash(seq: int, prev_hash: str, record: dict[str, Any]) -> str:
        # 复用 ids.content_hash 算行指纹(同哈希族,无另造)。
        return content_hash({"seq": seq, "prev_hash": prev_hash, "record": record})

    # —— 写:登记(append-only) ——
    def register(
        self,
        path: str | Path,
        *,
        producer_run: str,
        producer_kind: str,
        note: str = "",
    ) -> TrustRecord:
        """把【系统自产】artifact 登记进白名单(绑定 full-sha256 → producer-run)。append-only。

        生产侧(`app/models/training.py` / `app/models/dl/trainer.py`,领地外)在 `torch.save` /
        `pickle.dump` 落盘后应调用本函数;本卡的对抗测试直接调它【模拟 producer】。
        """
        if not producer_run:
            raise ValueError("producer_run 不可为空(信任门要求 artifact 绑定到产出 run·provenance)")
        p = Path(path)
        full, content_id = artifact_fingerprint(p)
        rec = TrustRecord(
            artifact_sha256=full,
            content_id=content_id,
            producer_run=producer_run,
            producer_kind=producer_kind,
            artifact_kind=_artifact_kind_of(p),
            note=note,
        )
        payload = rec.to_payload()
        with self._lock:
            seq = self._next_seq
            prev = self._last_hash
            row_hash = self._row_hash(seq, prev, payload)
            line = {"seq": seq, "prev_hash": prev, "row_hash": row_hash, "record": payload}
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                fh.flush()
            self._next_seq, self._last_hash = seq + 1, row_hash
        return rec

    # —— 读:验证(读路径即被核验路径) ——
    def verify(self, path: str | Path) -> TrustRecord | None:
        """文件当前 full-sha256 命中已登记记录 → 返回该记录(取最新一条);否则 None。"""
        full, _ = artifact_fingerprint(path)
        latest: dict[str, Any] | None = None
        for rec in self._read_records():
            r = rec.get("record")
            if isinstance(r, dict) and r.get("artifact_sha256") == full:
                latest = r
        return TrustRecord(**latest) if latest is not None else None

    def is_trusted(self, path: str | Path) -> bool:
        return self.verify(path) is not None

    def assert_trusted(self, path: str | Path) -> TrustRecord:
        """未登记 / sha256 不命中 → raise ArtifactTrustError(验收 #1 的硬拒点)。"""
        rec = self.verify(path)
        if rec is None:
            full, _ = artifact_fingerprint(path)
            raise ArtifactTrustError(
                f"artifact 信任门:{Path(path).name} 的 full-sha256={full[:16]}… 未登记"
                "(非系统自产 / 被改 / 外来)→ 拒加载(§15)。"
                "只有经 producer-run register() 登记的系统自产 artifact 才许加载。"
            )
        return rec

    def verify_chain(self) -> tuple[bool, list[str]]:
        """重算 prev_hash 链,检出对登记文件的事后篡改/链断。返回 (intact, issues)。"""
        issues: list[str] = []
        prev, expect_seq = GENESIS_HASH, 0
        for rec in self._read_records():
            if rec.get("seq") != expect_seq:
                issues.append(f"seq 跳号:期望 {expect_seq} 实得 {rec.get('seq')} → 检出链不连续")
                return False, issues
            if rec.get("prev_hash") != prev:
                issues.append(f"seq={rec.get('seq')} prev_hash 断裂 → 检出哈希链不连续")
                return False, issues
            recomputed = self._row_hash(rec["seq"], rec["prev_hash"], rec["record"])
            if recomputed != rec.get("row_hash"):
                issues.append(f"seq={rec['seq']} row_hash 与内容不符 → 检出该行被篡改")
                return False, issues
            prev, expect_seq = rec["row_hash"], expect_seq + 1
        return True, issues


# ── 信任策略:把门接到 load 路径 ──────────────────────────────────────────────
@dataclass
class TrustPolicy:
    """`enforce=False`(默认)= 向后兼容(只过 always-on safe-loader,不查登记);
    `enforce=True` = 来源门开:未登记 artifact 在 load 处被 `assert_ok` 硬拒。
    """

    store: ArtifactTrustStore | None = None
    enforce: bool = False

    def assert_ok(self, path: str | Path) -> None:
        if not self.enforce:
            return
        if self.store is None:
            # enforce 但无登记面可查 → 拒(no silent pass:绝不在该开门时静默放行)。
            raise ArtifactTrustError("TrustPolicy.enforce=True 但未提供 store(无登记面可查)→ 拒")
        self.store.assert_trusted(path)


# 进程级默认策略(默认 OFF,向后兼容)。follow-on 可经 configure_default_trust 全局翻 enforce。
_DEFAULT_POLICY = TrustPolicy(enforce=False)


def configure_default_trust(policy: TrustPolicy) -> None:
    """全局翻开/设置默认信任策略(给 follow-on 在产出侧接线后启用 enforce 用)。"""
    global _DEFAULT_POLICY
    _DEFAULT_POLICY = policy


def reset_default_trust() -> None:
    """复位默认策略为 OFF(测试 teardown 用,避免全局态跨用例泄漏)。"""
    global _DEFAULT_POLICY
    _DEFAULT_POLICY = TrustPolicy(enforce=False)


def resolve_policy(trust: Any) -> TrustPolicy:
    """把 load 的 `trust` 入参归一为 TrustPolicy:
    None → 进程默认策略;TrustPolicy → 原样;ArtifactTrustStore → 视为 enforce=True。
    """
    if trust is None:
        return _DEFAULT_POLICY
    if isinstance(trust, TrustPolicy):
        return trust
    if isinstance(trust, ArtifactTrustStore):
        return TrustPolicy(store=trust, enforce=True)
    raise TypeError(f"trust 须是 TrustPolicy/ArtifactTrustStore/None,得 {type(trust)!r}")


# ── DL 安全加载:safe tensors 优先 + weights_only 绝不回落 ─────────────────────
def load_torch_checkpoint(path: str | Path, *, map_location: str = "cpu") -> Any:
    """`.pt` 安全加载:`weights_only=True`;**绝不静默回落 `weights_only=False`**(§15 红线)。

    weights_only=True 只许 tensor/标量/容器等安全类型;若 ckpt 含非安全类型(被篡改 / 外来),
    torch 会 raise —— 本函数显式包成 ArtifactTrustError 再抛,**绝不**改 False 重试。
    """
    import torch  # 惰性 import(主进程零 torch)

    try:
        return torch.load(path, map_location=map_location, weights_only=True)
    except Exception as e:  # noqa: BLE001 —— 任何失败都不回落,显式 raise
        raise ArtifactTrustError(
            f"DL .pt 安全加载失败:{Path(path).name} 含 weights_only 不安全类型(被篡改 / 外来)。"
            "绝不回落 weights_only=False(§15·.pt 反序列化 = 任意代码执行);"
            "可信系统自产 ckpt 请改存 safetensors,或经审定 torch.serialization.add_safe_globals 后再载。"
            f"原因:{e}"
        ) from e


def load_safetensors_artifact(path: str | Path) -> dict[str, Any]:
    """safe tensors(+ 同名 `.json` config)安全加载 —— 零 pickle、构造上无代码执行(§15 preferred)。

    safetensors 未安装 → 显式 raise,**绝不回落到 pickle/.pt 不安全路径**。
    返回 {"arch", "state_dict", "config"}(与 trainer.py 的 .pt ckpt shape 一致)。
    """
    p = Path(path)
    try:
        from safetensors.torch import load_file as _load_st  # 惰性 optional import
    except ImportError as e:
        raise ArtifactTrustError(
            f"加载 {p.name} 需要 safetensors(§15 preferred 安全张量格式),但未安装;"
            "绝不回落到 pickle/.pt 不安全路径。请 `pip install safetensors`。"
        ) from e

    state_dict = _load_st(str(p))
    sidecar = p.with_suffix(".json")
    if not sidecar.exists():
        raise ArtifactTrustError(
            f"safetensors artifact {p.name} 缺同名 .json config(arch/config 必须 JSON 旁车,非 pickle)"
        )
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    if "arch" not in meta or "config" not in meta:
        raise ArtifactTrustError(f"{sidecar.name} 缺 arch/config 字段(JSON config 不完整)")
    return {"arch": meta["arch"], "state_dict": state_dict, "config": meta["config"]}


def load_dl_checkpoint(path: str | Path) -> dict[str, Any]:
    """DL ckpt 安全加载路由:`.safetensors` → safe tensors + JSON(preferred);
    `.pt` → `weights_only=True` 且绝不回落。返回 {"arch", "state_dict", "config"}。
    """
    p = Path(path)
    s = p.suffix.lower()
    if s == ".safetensors":
        return load_safetensors_artifact(p)
    if s == ".pt":
        return load_torch_checkpoint(p)
    raise ArtifactTrustError(f"DL 安全加载仅支持 .safetensors(preferred)/.pt:得 {s}({p})")


__all__ = [
    "ArtifactTrustError",
    "ArtifactTrustStore",
    "TrustPolicy",
    "TrustRecord",
    "artifact_fingerprint",
    "configure_default_trust",
    "load_dl_checkpoint",
    "load_safetensors_artifact",
    "load_torch_checkpoint",
    "reset_default_trust",
    "resolve_policy",
]
