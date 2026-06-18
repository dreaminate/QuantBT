"""脊柱第 0 层 · honest-N 试验账本【一本账】(SQLite WAL 索引 + JSONL 哈希链审计镜像)。

为什么是「一本账」(决策 R8/R1 + 复核 00 §1.2-I)：
- memoize 缓存键与 honest-N 计数单元【物理同源】——同一个 (config_hash, strategy_goal_ref)
  既是「命中即返不重跑」的缓存键，又是「这是该主题第几次试同一个想法」的计数单元。绝不存在
  「缓存命中但不计 N」或「计 N 但不缓存」的分裂。
- 复核 00 §1.2-I 裁定：账本存储 + config_hash + honest_n 计数归本部件，**05 的 N_eff 收益
  相关聚类 + 多证据三角 gate 只读本账、不自存第二本**。本模块因此【不实现】N_eff 聚类与
  DSR/PBO gate（那是 T-015），只存它需要的字段（returns_ref / returns_corr_cluster_id 留位）。

为什么计数键是【(config_hash, strategy_goal_ref) 复合键】(对抗复核 wf_ada4a4e4 #1/#2)：
- `config_hash` 是【主题无关】的内容寻址身份（ids.py 单一源，刻意排除 strategy_goal_ref——它
  回答「这是哪个想法」，与归在哪个研究主题无关）。
- 但 honest_n 是【按主题累计】的：同一个想法在主题 A 与主题 B 各试一次，是两个主题各自的一次
  多重检验，各计一次。若只用 config_hash 当主键，主题 B 的试验会撞上主题 A 的行被静默吞掉
  （honest-N 洗白）。故账本唯一性/计数键 = (config_hash, strategy_goal_ref) 复合键。

为什么双存储 (决策 S4 / RULES §1，**升级**了 spine 设计 03/05 的「纯 JSONL」)：
- **append-only JSONL + sha256 哈希链** = 防篡改、可重建的【持久真相】(durable ground truth)。
- **SQLite(WAL) 索引** = 从 JSONL 同步出的【快查询面】：honest_n / get 走 O(log n)。
- 二者是同一本账的两个投影：SQLite 丢了可从 JSONL 全量重建；任一被篡改对账揪出。
- 【读路径 == 被核验路径】(对抗复核 #7/#9)：get/list 一律从【被 verify_integrity 核验的列】
  重建条目，绝不读未核验的冗余 blob——杜绝「改 blob 绕过对账」。

诚实边界（裁决永远说「证据充分/不足」，绝不说「可信/安全」，见 RULES §3）：
- honest_n 是**真值下界**：agent 单次推理内的隐式试验无法埋点计入。
- 哈希链只防**事后篡改**，不防**写入时 garbage-in**；`verify_integrity` 措辞写「检出哈希链
  不连续/对账不符」，**绝不**写「保证内容真实」。
- **末尾截断的固有局限（对抗复核 #6，诚实标注）**：单机 append-only 日志，若攻击者同时删掉
  JSONL 末尾行【且】删除所有水位见证（SQLite 高水位 + `ledger.hwm` 文件），则该截断不可检出
  ——这是 append-only 日志的已知极限，需外部公证（notarization）方能根除，超出本模块范围。
  本模块用「SQLite 高水位 + 独立 hwm 文件」双见证抬高门槛，并对仍删得掉的残余风险诚实标注。
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal

from .ids import HASH_LEN, canonical_json, config_hash as _id_config_hash, content_hash

# ── 落盘文件名 ──────────────────────────────────────────────────────────────
LEDGER_JSONL_FILENAME = "ledger.jsonl"   # 防篡改审计镜像 = 持久真相
LEDGER_DB_FILENAME = "ledger.sqlite"     # 快查询索引 = 从 JSONL 同步
LEDGER_HWM_FILENAME = "ledger.hwm"       # 独立高水位见证（防 JSONL 末尾截断）

# 哈希链创世 prev_hash（16 位全零，与全库 HASH_LEN 对齐）。
GENESIS_HASH = "0" * HASH_LEN

# 账本条目维度白名单（00 §1.2-H / C10 权威 schema 口径）。
LedgerKind = Literal["backtest", "train", "card_freeze", "factor_eval"]
LedgerStage = Literal["exploratory", "confirmatory"]
ALLOWED_KINDS = frozenset({"backtest", "train", "card_freeze", "factor_eval"})
ALLOWED_STAGES = frozenset({"exploratory", "confirmatory"})

# 条目【定义性字段】= SQLite 列 = 读路径与对账路径共用的唯一真相（无 payload_json 旁路）。
# 顺序固定：(config_hash, strategy_goal_ref) 在前（复合键），其余按 schema。
_ENTRY_COLUMNS = (
    "config_hash", "strategy_goal_ref", "dataset_version", "kind", "stage",
    "asset_class", "created_by", "created_at_utc", "result_ref", "returns_ref",
    "returns_corr_cluster_id", "tombstone", "superseded_by", "audit_reason",
    "n_observed_is_lower_bound",
)
# UPSERT 冲突时【可变投影字段】——只有这些能被后续 append 更新；其余（内容/创建定义字段）
# 一律【不可变】(对抗复核 #2)：篡改它们会让 SQLite 与 JSONL latest 背离、被 verify 揪出。
_MUTABLE_ON_CONFLICT = (
    "result_ref", "returns_ref", "returns_corr_cluster_id",
    "tombstone", "superseded_by", "audit_reason",
)
_BOOL_COLUMNS = frozenset({"tombstone", "n_observed_is_lower_bound"})

# honest_n 的诚实免责（R2/R5）——它是下界，不是精确计数。措辞守门测试会断言此处用词
# （子串黑名单连「可信/安全」这类词的否定式都禁，故此处完全不出现这些词）。
HONEST_N_DISCLOSURE = (
    "honest_n 是名义 distinct config 计数，为真值【下界】：agent 单次推理内的隐式试验"
    "无法埋点计入；去等价公式后的有效独立 N 由下游 n_eff 收益相关聚类给出区间（非本账职责）。"
    "本计数只回答「显式提交了几次不同配置」，不对结论下任何定性判断。"
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


# ── 账本条目 schema (00 §1.2-H / C10 权威；字段名按 00 §1.2-I 裁定收敛) ───────
@dataclass
class LedgerEntry:
    """一条试验账本记录。唯一性键 = (config_hash, strategy_goal_ref)。

    字段命名收敛（复核 00 §1.2-I 裁定）：`strategy_goal_ref`（非 05 的 `research_theme_id`）；
    `result_ref`（memoize 命中即返指针）；软删用 `tombstone`+`superseded_by`（**不减 N**）。
    `entry_id == config_hash`（内容寻址，主题无关——同一想法跨主题共享同一 config_hash）。
    """

    entry_id: str            # = config_hash（内容寻址，主题无关）
    config_hash: str         # ids.config_hash(...) 产出（cfg_v1_ 前缀，16 位）——单一身份源
    strategy_goal_ref: str   # 主题/卡家族外键；与 config_hash 一起构成唯一性/计数键
    dataset_version: str
    kind: LedgerKind
    stage: LedgerStage
    asset_class: str = "unknown"
    created_by: Literal["human", "agent"] = "human"
    created_at_utc: str = field(default_factory=_now)
    result_ref: str | None = None
    returns_ref: str | None = None
    returns_corr_cluster_id: str | None = None
    tombstone: bool = False
    superseded_by: str | None = None
    audit_reason: str = ""
    n_observed_is_lower_bound: bool = True

    def __post_init__(self) -> None:
        if self.entry_id != self.config_hash:
            raise ValueError(
                f"entry_id({self.entry_id}) != config_hash({self.config_hash})；"
                "主键必须是内容寻址的 config_hash，不可自造"
            )
        if self.kind not in ALLOWED_KINDS:
            raise ValueError(f"非法 kind={self.kind!r}，须 ∈ {sorted(ALLOWED_KINDS)}")
        if self.stage not in ALLOWED_STAGES:
            raise ValueError(f"非法 stage={self.stage!r}，须 ∈ {sorted(ALLOWED_STAGES)}")
        if not self.strategy_goal_ref:
            raise ValueError("strategy_goal_ref 不可为空（它是 honest_n 的累计维度）")

    @property
    def key(self) -> tuple[str, str]:
        return (self.config_hash, self.strategy_goal_ref)

    @classmethod
    def create(
        cls,
        *,
        factor: Any,
        params: Any = None,
        universe: Any = None,
        dataset_version: str | None = None,
        freq: str | None = None,
        label: Any = None,
        strategy_goal_ref: str,
        kind: LedgerKind,
        stage: LedgerStage,
        asset_class: str = "unknown",
        created_by: Literal["human", "agent"] = "human",
        result_ref: str | None = None,
        returns_ref: str | None = None,
    ) -> "LedgerEntry":
        """从试验配置簇【经 ids.config_hash 唯一算法】构造条目（堵死 §1.2-A 双产方回潮）。"""

        chash = _id_config_hash(
            factor=factor, params=params, universe=universe,
            dataset_version=dataset_version, freq=freq, label=label,
        )
        return cls(
            entry_id=chash, config_hash=chash, strategy_goal_ref=strategy_goal_ref,
            dataset_version=dataset_version or "", kind=kind, stage=stage,
            asset_class=asset_class, created_by=created_by,
            result_ref=result_ref, returns_ref=returns_ref,
        )

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "LedgerEntry":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})

    @classmethod
    def from_columns(cls, row: tuple) -> "LedgerEntry":
        """从 SQLite 的 `_ENTRY_COLUMNS` 行重建条目（读路径 == 被核验路径，#7/#9）。"""

        d = dict(zip(_ENTRY_COLUMNS, row))
        for b in _BOOL_COLUMNS:
            d[b] = bool(d[b])
        d["entry_id"] = d["config_hash"]
        return cls(**d)


@dataclass
class IntegrityReport:
    """`verify_integrity` 输出。措辞诚实：检出「哈希链不连续/对账不符/截断」，非「内容真实」。"""

    ok: bool
    chain_intact: bool
    store_consistent: bool
    not_truncated: bool          # JSONL 长度 >= 高水位见证（无末尾截断）
    tampered: bool
    issues: list[str]
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── JSONL 哈希链存储（防篡改审计镜像；崩溃容错跳坏尾行） ──────────────────────
class _ChainStore:
    """append-only JSONL，每行 `{seq, prev_hash, row_hash, op, payload}`，prev_hash 链。"""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()
        self._next_seq, self._last_hash = self._scan_tail()

    def _scan_tail(self) -> tuple[int, str]:
        last_hash = GENESIS_HASH
        next_seq = 0
        for rec in self._read_records_unlocked():
            last_hash = rec["row_hash"]
            next_seq = rec["seq"] + 1
        return next_seq, last_hash

    @property
    def next_seq(self) -> int:
        return self._next_seq

    @staticmethod
    def _compute_row_hash(seq: int, prev_hash: str, op: str, payload: dict[str, Any]) -> str:
        return content_hash({"seq": seq, "prev_hash": prev_hash, "op": op, "payload": payload})

    def append(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            seq = self._next_seq
            prev = self._last_hash
            row_hash = self._compute_row_hash(seq, prev, op, payload)
            line = {"seq": seq, "prev_hash": prev, "row_hash": row_hash, "op": op, "payload": payload}
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(line, ensure_ascii=False) + "\n")
                fh.flush()
            self._next_seq = seq + 1
            self._last_hash = row_hash
            return line

    def _read_records_unlocked(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                # 容忍崩溃中途写坏的（通常是末尾）行；不让一个坏行炸全库（复用 store.py:98-102）。
                continue
        return out

    def read_records(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._read_records_unlocked()

    def verify_chain(self) -> tuple[bool, list[str]]:
        """重算哈希链，检出篡改/链断。返回 (intact, issues)。"""

        issues: list[str] = []
        with self._lock:
            raw_lines = [ln for ln in self._path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        prev = GENESIS_HASH
        expect_seq = 0
        n = len(raw_lines)
        for i, line in enumerate(raw_lines):
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                if i == n - 1:
                    issues.append(f"末尾残尾行(seq~{expect_seq})不可解析：判为崩溃残尾，非篡改")
                    continue
                issues.append(f"第 {i} 行不可解析且非末尾 → 检出哈希链不连续(防自欺)")
                return False, issues
            if rec.get("seq") != expect_seq:
                issues.append(f"seq 跳号：期望 {expect_seq} 实得 {rec.get('seq')} → 检出链不连续")
                return False, issues
            if rec.get("prev_hash") != prev:
                issues.append(f"seq={rec.get('seq')} prev_hash 断裂 → 检出哈希链不连续(防自欺)")
                return False, issues
            recomputed = self._compute_row_hash(rec["seq"], rec["prev_hash"], rec.get("op", ""), rec["payload"])
            if recomputed != rec.get("row_hash"):
                issues.append(f"seq={rec['seq']} row_hash 与内容不符 → 检出该行被篡改(防自欺)")
                return False, issues
            prev = rec["row_hash"]
            expect_seq += 1
        return True, issues


# ── 一本账门面 ──────────────────────────────────────────────────────────────
class Ledger:
    """honest-N + memoize 一本账。SQLite 快查 + JSONL 链审计，二者同步为同一本。

    硬约束（RULES §3，防作弊）：无 `set_n`/`delete` API；tombstone 不减 honest_n；
    memoize 命中即返不重跑、不重复计 N（R8）。并发下 memoize 对同一键 compute 至多一次。
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._chain = _ChainStore(self._root / LEDGER_JSONL_FILENAME)
        self._lock = threading.Lock()                 # 写串行化（保护 SQLite/链/hwm）
        self._key_locks_guard = threading.Lock()
        self._key_locks: dict[tuple[str, str], threading.Lock] = {}  # 按键串行化 compute
        self._hwm_path = self._root / LEDGER_HWM_FILENAME
        self._db_path = self._root / LEDGER_DB_FILENAME
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()
        self._malformed_seqs: list[int] = []          # 重建时跳过的坏 payload 行（verify 据此标）
        self._sync_from_jsonl()                        # 前向恢复/重建（崩溃/丢库自愈）
        self._hwm = self._load_hwm()                   # 高水位见证（防截断）

    # —— schema ——
    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                config_hash TEXT NOT NULL,
                strategy_goal_ref TEXT NOT NULL,
                dataset_version TEXT,
                kind TEXT,
                stage TEXT,
                asset_class TEXT,
                created_by TEXT,
                created_at_utc TEXT,
                result_ref TEXT,
                returns_ref TEXT,
                returns_corr_cluster_id TEXT,
                tombstone INTEGER DEFAULT 0,
                superseded_by TEXT,
                audit_reason TEXT,
                n_observed_is_lower_bound INTEGER DEFAULT 1,
                created_seq INTEGER,
                seq INTEGER,
                PRIMARY KEY (config_hash, strategy_goal_ref)
            )
            """
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_goal ON ledger(strategy_goal_ref)")
        self._conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER)")
        self._conn.commit()

    # —— 高水位见证（防 JSONL 末尾截断） ——
    def _load_hwm(self) -> int:
        file_hwm = 0
        try:
            file_hwm = int(self._hwm_path.read_text().strip() or "0")
        except (OSError, ValueError):
            file_hwm = 0
        row = self._conn.execute("SELECT v FROM meta WHERE k='hwm_seq'").fetchone()
        sqlite_hwm = int(row[0]) if row and row[0] is not None else 0
        return max(file_hwm, sqlite_hwm, self._chain.next_seq)

    def _persist_hwm(self, value: int) -> None:
        self._hwm = max(self._hwm, value)
        try:
            self._hwm_path.write_text(str(self._hwm))
        except OSError:
            pass
        self._conn.execute(
            "INSERT INTO meta(k,v) VALUES('hwm_seq',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (self._hwm,),
        )

    def _key_lock(self, key: tuple[str, str]) -> threading.Lock:
        with self._key_locks_guard:
            lk = self._key_locks.get(key)
            if lk is None:
                lk = threading.Lock()
                self._key_locks[key] = lk
            return lk

    def _sqlite_max_seq(self) -> int:
        row = self._conn.execute("SELECT MAX(seq) FROM ledger").fetchone()
        return -1 if row is None or row[0] is None else int(row[0])

    def _sync_from_jsonl(self) -> None:
        """前向恢复：replay seq 大于 SQLite 当前最大 seq 的 JSONL 行（丢库→全量重建）。

        坏/缺键 payload 行【跳过并记录】(对抗复核 #8)，绝不让单条坏行炸 __init__；
        verify_integrity 会据 `_malformed_seqs` 标 tampered。
        """

        with self._lock:
            max_seq = self._sqlite_max_seq()
            for rec in self._chain.read_records():
                if rec.get("seq", -1) <= max_seq:
                    continue
                payload = rec.get("payload")
                if not isinstance(payload, dict) or not payload.get("config_hash") or not payload.get("strategy_goal_ref"):
                    self._malformed_seqs.append(rec.get("seq", -1))
                    continue
                self._apply_to_sqlite(payload, rec["seq"])
            self._conn.commit()

    def _apply_to_sqlite(self, payload: dict[str, Any], seq: int) -> None:
        p = payload
        cols = list(_ENTRY_COLUMNS) + ["created_seq", "seq"]
        vals = [
            p["config_hash"], p["strategy_goal_ref"], p.get("dataset_version"), p.get("kind"),
            p.get("stage"), p.get("asset_class"), p.get("created_by"), p.get("created_at_utc"),
            p.get("result_ref"), p.get("returns_ref"), p.get("returns_corr_cluster_id"),
            1 if p.get("tombstone") else 0, p.get("superseded_by"), p.get("audit_reason", ""),
            1 if p.get("n_observed_is_lower_bound", True) else 0,
            seq, seq,
        ]
        placeholders = ",".join("?" * len(cols))
        # ON CONFLICT 只更新可变投影字段 + seq；内容/创建定义字段【不可变】(#2)。
        set_clause = ", ".join(f"{c}=excluded.{c}" for c in _MUTABLE_ON_CONFLICT) + ", seq=excluded.seq"
        self._conn.execute(
            f"INSERT INTO ledger ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(config_hash, strategy_goal_ref) DO UPDATE SET {set_clause}",
            vals,
        )

    # —— 读（一律从被核验的列重建；无 payload_json 旁路） ——
    def _get_locked(self, config_hash: str, strategy_goal_ref: str) -> LedgerEntry | None:
        row = self._conn.execute(
            f"SELECT {', '.join(_ENTRY_COLUMNS)} FROM ledger WHERE config_hash=? AND strategy_goal_ref=?",
            (config_hash, strategy_goal_ref),
        ).fetchone()
        return LedgerEntry.from_columns(row) if row else None

    def get(self, config_hash: str, strategy_goal_ref: str) -> LedgerEntry | None:
        """O(log n) 复合键查；返回当前态条目或 None。"""

        with self._lock:
            return self._get_locked(config_hash, strategy_goal_ref)

    def honest_n(self, strategy_goal_ref: str) -> int:
        """该主题的 distinct config_hash 计数 = honest-N 名义计数（真值下界）。

        实时从 SQLite 索引数（O(log n)）。**无任何 API 能改小**；tombstone 的行仍计入。
        """

        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM ledger WHERE strategy_goal_ref=?", (strategy_goal_ref,)
            ).fetchone()
        return int(row[0]) if row else 0

    def list_entries(self, strategy_goal_ref: str | None = None) -> list[LedgerEntry]:
        sel = f"SELECT {', '.join(_ENTRY_COLUMNS)} FROM ledger"
        with self._lock:
            if strategy_goal_ref is None:
                rows = self._conn.execute(sel + " ORDER BY created_seq").fetchall()
            else:
                rows = self._conn.execute(
                    sel + " WHERE strategy_goal_ref=? ORDER BY created_seq", (strategy_goal_ref,)
                ).fetchall()
        return [LedgerEntry.from_columns(r) for r in rows]

    # —— 写（append-only；JSONL 先落=持久真相，SQLite 后同步=快查询；全程持 self._lock） ——
    def _append_locked(self, entry: LedgerEntry, op: str) -> LedgerEntry:
        payload = entry.to_payload()
        line = self._chain.append(op, payload)         # 1) 先落持久审计（含哈希链）
        self._apply_to_sqlite(payload, line["seq"])    # 2) 同步快查索引
        self._persist_hwm(line["seq"] + 1)             # 3) 推高水位见证
        self._conn.commit()
        return entry

    def record_or_hit(self, entry: LedgerEntry) -> tuple[LedgerEntry, bool]:
        """幂等入账：同 (config_hash, goal) 已存在 → 返存量 + hit=True（不 append）；否则落账。"""

        with self._key_lock(entry.key):
            with self._lock:
                existing = self._get_locked(*entry.key)
                if existing is not None:
                    return existing, True
                return self._append_locked(entry, op="record"), False

    def memoize(self, entry: LedgerEntry, compute: Callable[[], Any]) -> tuple[LedgerEntry, bool]:
        """memoized 记账（R8 命中即返不重跑），并发对同键 compute 至多一次（#3）：

        - 干净命中（存在、未软删、result_ref 已填）→ 返存量，compute 不被调用，honest_n 不 +1。
        - 未命中 → compute()，落账（result_ref 回填）→ +1。
        - 存在但 result_ref 为空（曾 record_or_hit 占位，#4）→ compute() 回填，**不重复计 N**。
        - 存在但已软删（#5）→ 不返回陈旧结果：compute() 刷新并复活（清 tombstone），不重复计 N。
        """

        with self._key_lock(entry.key):               # 按键串行化 → compute 至多一次
            existing = self.get(*entry.key)
            if existing is not None and not existing.tombstone and existing.result_ref is not None:
                return existing, True
            result_ref = compute()
            with self._lock:
                cur = self._get_locked(*entry.key)
                if cur is None:
                    if isinstance(result_ref, str) and entry.result_ref is None:
                        entry.result_ref = result_ref
                    return self._append_locked(entry, op="record"), False
                # 存在但需回填/复活：只动可变字段，内容字段保持原值。
                if isinstance(result_ref, str):
                    cur.result_ref = result_ref
                cur.tombstone = False
                cur.superseded_by = None
                return self._append_locked(cur, op="update"), False

    def tombstone(
        self, config_hash: str, strategy_goal_ref: str, *, reason: str, superseded_by: str | None = None
    ) -> LedgerEntry:
        """软删（弃用/被替代）。append 软删行 + 更新 SQLite。**不减 honest_n**（行数只增）。"""

        with self._key_lock((config_hash, strategy_goal_ref)):
            with self._lock:
                existing = self._get_locked(config_hash, strategy_goal_ref)
                if existing is None:
                    raise KeyError(f"条目不存在，无法 tombstone: ({config_hash}, {strategy_goal_ref})")
                existing.tombstone = True
                existing.superseded_by = superseded_by
                existing.audit_reason = reason
                return self._append_locked(existing, op="tombstone")

    def update_fields(
        self,
        config_hash: str,
        strategy_goal_ref: str,
        *,
        result_ref: str | None = None,
        returns_ref: str | None = None,
        returns_corr_cluster_id: str | None = None,
    ) -> LedgerEntry:
        """回填可变投影字段（如 T-015 异步算出的收益聚类簇 id）。append 审计行，不减 N。"""

        with self._key_lock((config_hash, strategy_goal_ref)):
            with self._lock:
                existing = self._get_locked(config_hash, strategy_goal_ref)
                if existing is None:
                    raise KeyError(f"条目不存在: ({config_hash}, {strategy_goal_ref})")
                if result_ref is not None:
                    existing.result_ref = result_ref
                if returns_ref is not None:
                    existing.returns_ref = returns_ref
                if returns_corr_cluster_id is not None:
                    existing.returns_corr_cluster_id = returns_corr_cluster_id
                return self._append_locked(existing, op="update")

    # —— 对账 / 完整性 ——
    def verify_integrity(self) -> IntegrityReport:
        """重算 JSONL 哈希链 + SQLite↔JSONL 列对账 + 高水位截断检测。

        诚实措辞：检出「哈希链不连续 / 索引与审计不符 / 末尾截断 / 坏 payload 行」（防自欺），
        **不**声称「保证内容真实/可信/安全」。
        """

        issues: list[str] = []
        chain_intact, chain_issues = self._chain.verify_chain()
        issues.extend(chain_issues)

        records = self._chain.read_records()

        # 1) 坏/缺键 payload 行（重建时已跳过）→ 标 tampered，绝不静默。
        malformed = list(self._malformed_seqs)
        for rec in records:
            payload = rec.get("payload")
            if not isinstance(payload, dict) or not payload.get("config_hash") or not payload.get("strategy_goal_ref"):
                seq = rec.get("seq", -1)
                if seq not in malformed:
                    malformed.append(seq)
        if malformed:
            issues.append(f"检出 {len(malformed)} 条坏/缺键 payload 行(seq={sorted(set(malformed))}) → 防自欺")

        # 2) 末尾截断检测（高水位见证）：JSONL 当前行数 < 历史高水位 → 截断。
        not_truncated = self._chain.next_seq >= self._hwm
        if not not_truncated:
            issues.append(
                f"JSONL 当前序号 {self._chain.next_seq} < 历史高水位 {self._hwm} "
                f"→ 检出末尾截断(防自欺；注：若水位见证亦被删则不可检出，见模块诚实边界)"
            )

        # 3) SQLite↔JSONL latest-state 列对账（键 = 复合键；只比被读用的定义性列）。
        jsonl_latest: dict[tuple[str, str], dict[str, Any]] = {}
        for rec in records:
            payload = rec.get("payload")
            if isinstance(payload, dict) and payload.get("config_hash") and payload.get("strategy_goal_ref"):
                jsonl_latest[(payload["config_hash"], payload["strategy_goal_ref"])] = payload
        with self._lock:
            sqlite_rows = {
                (r[0], r[1]): self._columns_to_compare_dict(r)
                for r in self._conn.execute(
                    f"SELECT {', '.join(_ENTRY_COLUMNS)} FROM ledger"
                ).fetchall()
            }
        store_consistent = True
        if set(jsonl_latest) != set(sqlite_rows):
            store_consistent = False
            issues.append("SQLite 与 JSONL 的 (config_hash,goal) 集合不一致 → 检出索引/审计对账不符(防自欺)")
        else:
            for key, jp in jsonl_latest.items():
                if canonical_json(self._payload_to_compare_dict(jp)) != canonical_json(sqlite_rows[key]):
                    store_consistent = False
                    issues.append(f"键={key} 的 SQLite 列与 JSONL latest 不一致 → 检出对账不符")
                    break

        tampered = (not chain_intact) or (not store_consistent) or (not not_truncated) or bool(malformed)
        ok = not tampered
        message = (
            "哈希链连续、索引与审计镜像一致、无末尾截断迹象（仅防篡改证据，不保证内容真实）。"
            if ok else
            "检出哈希链不连续/索引对账不符/末尾截断/坏行（防自欺）；" + "；".join(issues)
        )
        return IntegrityReport(
            ok=ok, chain_intact=chain_intact, store_consistent=store_consistent,
            not_truncated=not_truncated, tampered=tampered, issues=issues, message=message,
        )

    @staticmethod
    def _columns_to_compare_dict(row: tuple) -> dict[str, Any]:
        d = dict(zip(_ENTRY_COLUMNS, row))
        for b in _BOOL_COLUMNS:
            d[b] = bool(d[b])
        return d

    @staticmethod
    def _payload_to_compare_dict(payload: dict[str, Any]) -> dict[str, Any]:
        d = {k: payload.get(k) for k in _ENTRY_COLUMNS}
        d["audit_reason"] = payload.get("audit_reason", "")
        d["tombstone"] = bool(payload.get("tombstone"))
        d["n_observed_is_lower_bound"] = bool(payload.get("n_observed_is_lower_bound", True))
        return d

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = [
    "ALLOWED_KINDS",
    "ALLOWED_STAGES",
    "GENESIS_HASH",
    "HONEST_N_DISCLOSURE",
    "IntegrityReport",
    "Ledger",
    "LedgerEntry",
    "LedgerKind",
    "LedgerStage",
    "LEDGER_DB_FILENAME",
    "LEDGER_HWM_FILENAME",
    "LEDGER_JSONL_FILENAME",
]
