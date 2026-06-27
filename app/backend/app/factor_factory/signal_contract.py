"""F4 · R17 信号契约登记（ML/DL 输出 → 信号 → 才进因子库；本体绝不入库）。

为什么这一层存在（dev/decisions §R17=B + GOAL §3「三库纯净」）：
- 三纯库（算术 / ML / DL）保持**范畴纯净**：
  - 算术表达式 = 信号本身（factor_factory.expression 编译即可），直接进因子库。
  - ML/DL 模型「本体」(.pt/.pkl/.onnx…) 是**模型**，不是因子 —— 把它塞进因子库是
    范畴错误（§26）。本体只进【模型注册表】(experiments.ModelRegistry / models/)。
  - ML/DL 模型「输出」(预测序列 / 截面打分) 经**信号契约**登记后，才作为信号进因子库。
- 本模块只做「输出→信号契约」这一层登记 + 准入门，不重造模型注册表，也不重造因子库。

诚实边界（RULES §3）：
- 准入门是**范畴门 + 血统门 + 泄露声明门**，不对信号「是不是真 alpha」下任何定性判断
  （那是评测/审查台的事）。措辞绝不出现「可信 / 安全 / 排除过拟合」。
- 身份单一源：信号契约 id 走 `lineage.ids.content_hash`（同 16 位哈希族），不自造哈希。
- 泄露门只检「契约**自报**是否声明了 OOF + purge + embargo」——这是**声明检查**，不是
  「证明无泄露」。实际防泄露在策略层 OOF 训练流程，本门只拒「未声明就想入库」。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..lineage.ids import content_hash

# 模型「本体」文件后缀——这些是模型，不是信号；出现在 ref/source 里即范畴错误。
# 与前端 factorLabData.MODEL_BODY_EXTS 同口径（单一真相在两端镜像，测试钉死）。
MODEL_BODY_EXTS: tuple[str, ...] = (".pt", ".pth", ".onnx", ".pkl", ".joblib", ".h5", ".ckpt")

# 信号契约 id 的命名空间前缀（与裸 content_hash 区分；前端 ref 形如 sig::xxx 也接受）。
SIGNAL_REF_PREFIX = "sig::"

SignalSourceLib = Literal["ml", "dl"]


class SignalContractError(ValueError):
    """信号契约登记/准入被拒（范畴门 / 血统门 / 泄露声明门）。"""


def looks_like_model_body(ref: str) -> bool:
    """ref/source 看起来是不是「模型本体文件」（用于拦截把 .pt 直接塞因子库）。

    与前端 looksLikeModelBody 同算法（后缀匹配，大小写无关）。
    """

    lower = (ref or "").strip().lower()
    return any(lower.endswith(ext) for ext in MODEL_BODY_EXTS)


@dataclass
class LeakageDeclaration:
    """信号契约的泄露防护**自报声明**（R18：信号层集成强制 OOF+purge+embargo）。

    这是**声明门**：契约必须自报这三项已就位才允许入库；本门不证明无泄露，只拒「未声明」。
    """

    oof: bool = False               # 是否用 out-of-fold 预测（防训练集泄露）
    purge: bool = False             # 是否做 purge（剔除标签窗重叠样本）
    embargo: bool = False           # 是否做 embargo（隔离邻近样本）
    embargo_days: int | None = None

    def is_complete(self) -> bool:
        return bool(self.oof and self.purge and self.embargo)

    def missing(self) -> list[str]:
        miss: list[str] = []
        if not self.oof:
            miss.append("OOF")
        if not self.purge:
            miss.append("purge")
        if not self.embargo:
            miss.append("embargo")
        return miss

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "LeakageDeclaration":
        data = data or {}
        return cls(
            oof=bool(data.get("oof", False)),
            purge=bool(data.get("purge", False)),
            embargo=bool(data.get("embargo", False)),
            embargo_days=data.get("embargo_days"),
        )


@dataclass
class SignalContract:
    """一条 ML/DL 输出 → 信号 的契约记录。

    身份 = `signal_id`（content_hash，内容寻址；输出口径变则 id 变）。它**回指**模型本体在
    模型注册表里的引用 `model_ref`（血统门：缺本体引用 = 孤儿信号，拒）。
    """

    signal_id: str               # = content_hash(规范化输出口径)；内容寻址，单一身份源
    name: str                    # 人读名（装饰，不入身份）
    source_lib: SignalSourceLib  # ml | dl（算术不走契约，直接表达式入库）
    model_ref: str               # 模型本体在模型注册表里的引用（如 gbdt_xs_rank_v3.pkl）
    output_kind: str             # 输出口径：xs_score / seq_pred / prob …（入身份）
    horizon: int                 # 预测视野（天）（入身份）
    leakage: LeakageDeclaration  # 泄露防护自报声明
    author: str = "system"
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    description: str = ""

    @property
    def signal_ref(self) -> str:
        """因子库里引用本信号的 ref（sig:: 前缀；可直接当 Factor.formula 占位）。"""

        return SIGNAL_REF_PREFIX + self.signal_id

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["signal_ref"] = self.signal_ref
        return d


def compute_signal_id(
    *, source_lib: str, model_ref: str, output_kind: str, horizon: int
) -> str:
    """信号契约的内容寻址身份（lineage 单一哈希族；输出口径同则 id 同 → 不刷重）。

    刻意**不**把 name/description 入身份（装饰字段，改名不算新信号）。
    """

    return content_hash(
        {
            "source_lib": source_lib,
            "model_ref": model_ref,
            "output_kind": output_kind,
            "horizon": int(horizon),
        }
    )


def admit_artifact_to_factor_lib(kind: str, ref: str) -> tuple[bool, str]:
    """R17 单一入库守卫（与前端 admitToFactorLib 同口径，两端镜像、测试钉死）。

    判定某产物能否进**因子库**：
    - kind == "model_body" → 拒（范畴错误：本体只进模型注册表）。
    - kind != "signal_contract" 但 ref 看起来是本体文件（.pt/.pkl…）→ 拒（双保险）。
    - kind ∈ {"expression", "signal_contract"} 且 ref 不是本体文件 → 准入。

    返回 (admitted, reason)；admitted=False 时 reason 为诚实拒绝文案（绝不染绿）。
    """

    if kind == "model_body":
        return (
            False,
            "范畴错误：模型本体（.pt/.pkl…）只能进模型注册表，不能当因子塞因子库（R17）",
        )
    if kind != "signal_contract" and looks_like_model_body(ref):
        return (
            False,
            "ref 指向模型本体文件，须先经『信号契约』登记输出，才能进因子库（R17）",
        )
    if kind not in ("expression", "signal_contract"):
        return (False, f"未知产物范畴 {kind!r}，无法判定入库资格")
    return (True, "")


class SignalContractRegistry:
    """信号契约登记表（内存级）。本期不落盘（与 mining 一致；主存活在请求周期 + 测试）。

    入库门（register 时强制，违一条即 SignalContractError）：
    - 范畴门：source_lib 必须是 ml/dl；model_ref 必须非空（孤儿信号拒）。
    - 血统门：model_ref 必须**看起来像本体文件**（回指模型注册表的本体），否则拒
      —— 防「假装有模型却没本体」的悬空信号。
    - 泄露声明门：leakage 三项（OOF/purge/embargo）须自报齐全，否则拒（R18）。
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._items: dict[str, SignalContract] = {}
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._load_existing()

    def _load_existing(self) -> None:
        assert self._path is not None
        if not self._path.exists():
            return
        for line_no, line in enumerate(self._path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if row.get("schema_version") != 1:
                    raise ValueError("unsupported signal contract schema_version")
                payload = row.get("signal_contract")
                if not isinstance(payload, dict):
                    raise ValueError("missing signal_contract")
                signal_id = str(payload.get("signal_id") or "")
                contract = SignalContract(
                    signal_id=signal_id,
                    name=str(payload.get("name") or ""),
                    source_lib=str(payload.get("source_lib") or "ml"),  # type: ignore[arg-type]
                    model_ref=str(payload.get("model_ref") or ""),
                    output_kind=str(payload.get("output_kind") or ""),
                    horizon=int(payload.get("horizon") or 0),
                    leakage=LeakageDeclaration.from_dict(payload.get("leakage")),
                    author=str(payload.get("author") or "system"),
                    created_at_utc=str(payload.get("created_at_utc") or datetime.now(UTC).isoformat()),
                    description=str(payload.get("description") or ""),
                )
                if not signal_id:
                    raise ValueError("signal_contract missing signal_id")
                self._items[signal_id] = contract
            except Exception as exc:  # noqa: BLE001 - corrupt governance history must be visible.
                raise ValueError(f"invalid persisted signal contract row at {self._path}:{line_no}") from exc

    def _append(self, contract: SignalContract) -> None:
        if self._path is None:
            return
        row = {
            "schema_version": 1,
            "event_type": "signal_contract_registered",
            "signal_contract": contract.to_dict(),
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")

    def register(
        self,
        *,
        name: str,
        source_lib: str,
        model_ref: str,
        output_kind: str,
        horizon: int,
        leakage: LeakageDeclaration | dict[str, Any] | None,
        author: str = "system",
        description: str = "",
    ) -> SignalContract:
        if source_lib not in ("ml", "dl"):
            raise SignalContractError(
                f"信号契约 source_lib 须 ∈ {{ml, dl}}（算术表达式不走契约，直接入库），实得 {source_lib!r}"
            )
        if not model_ref or not str(model_ref).strip():
            raise SignalContractError("血统门：model_ref 不可为空——信号必须回指模型注册表里的本体")
        # 血统门：model_ref 必须指向一个**本体文件**（.pt/.pkl…）。若它本身又是 sig::/裸串，
        # 说明没有真本体回指 → 孤儿信号，拒。
        if not looks_like_model_body(model_ref):
            raise SignalContractError(
                f"血统门：model_ref={model_ref!r} 不像模型本体文件（须 ∈ {list(MODEL_BODY_EXTS)}），"
                "信号契约必须回指真实本体，禁止悬空"
            )
        decl = (
            leakage if isinstance(leakage, LeakageDeclaration)
            else LeakageDeclaration.from_dict(leakage)
        )
        if not decl.is_complete():
            raise SignalContractError(
                f"泄露声明门：信号入因子库须自报 OOF+purge+embargo 齐全（R18），缺：{decl.missing()}"
            )
        sid = compute_signal_id(
            source_lib=source_lib, model_ref=model_ref, output_kind=output_kind, horizon=horizon
        )
        contract = SignalContract(
            signal_id=sid,
            name=name,
            source_lib=source_lib,  # type: ignore[arg-type]
            model_ref=model_ref,
            output_kind=output_kind,
            horizon=int(horizon),
            leakage=decl,
            author=author,
            description=description,
        )
        self._items[sid] = contract
        self._append(contract)
        return contract

    def get(self, signal_id: str) -> SignalContract:
        sid = signal_id[len(SIGNAL_REF_PREFIX):] if signal_id.startswith(SIGNAL_REF_PREFIX) else signal_id
        if sid not in self._items:
            raise KeyError(f"未登记的信号契约: {signal_id}")
        return self._items[sid]

    def list(self) -> list[SignalContract]:
        return sorted(self._items.values(), key=lambda c: (c.source_lib, c.created_at_utc))


__all__ = [
    "MODEL_BODY_EXTS",
    "SIGNAL_REF_PREFIX",
    "LeakageDeclaration",
    "SignalContract",
    "SignalContractError",
    "SignalContractRegistry",
    "admit_artifact_to_factor_lib",
    "compute_signal_id",
    "looks_like_model_body",
]
