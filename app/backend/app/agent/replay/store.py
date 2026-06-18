"""FixtureStore · append-only LLM fixture 落盘 + HMAC 完整性 + fingerprint 漂移检测（T-016）。

落 `DATA_ROOT/artifacts/llm_fixtures/`。append-only + tombstone（软删不减 distinct 计数=honest-N
不可改小，R8）。HMAC key 本地持久（0600）——诚实边界：防篡改/防自欺、**非防本机恶意**（R12）。
fingerprint 漂移【不静默】：同 (provider, model_id) 的 system_fingerprint 变了 → 发 `fingerprint_drift`
事件（C6），让「是我改了 prompt 还是供应商换了模型」可区分（dossier §5.4/§8.3）。
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any, Callable

from .fixture import LLMFixture, compute_hmac, is_alias_model_id, verify_hmac

FIXTURES_FILENAME = "fixtures.jsonl"
HMAC_KEY_FILENAME = "hmac.key"


class IntegrityError(Exception):
    """fixture HMAC 校验失败——内容被篡改 / key 不符（防自欺，不返回脏数据）。"""


class FixtureConflict(Exception):
    """同 fixture_key 落入【内容不同】的 fixture——append-only 不许静默覆盖。"""


class ReplayMiss(Exception):
    """replay 模式下 fixture 未命中——绝不回退打真 API（R11 命门）。"""


EventSink = Callable[[str, dict[str, Any]], None]


class FixtureStore:
    def __init__(self, root: Path | str, *, hmac_key: bytes | None = None, on_event: EventSink | None = None) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / FIXTURES_FILENAME
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()
        self._on_event = on_event
        self._key = hmac_key if hmac_key is not None else self._load_or_create_key()
        # 内存索引（从 JSONL 重建）：每 key 全部行（按序，供 get 回退）、distinct 集、fingerprint 史。
        self._rows_by_key: dict[str, list[dict[str, Any]]] = {}
        self._latest: dict[str, dict[str, Any]] = {}
        self._distinct: set[str] = set()
        self._consumed: set[str] = set()
        self._last_fp: dict[tuple[str, str], str | None] = {}
        self._corrupt_lines = 0
        self._replay_index()

    def _load_or_create_key(self) -> bytes:
        kp = self._root / HMAC_KEY_FILENAME
        if kp.exists():
            return bytes.fromhex(kp.read_text().strip())
        key = secrets.token_bytes(32)
        kp.write_text(key.hex())
        try:
            os.chmod(kp, 0o600)   # 防自欺：限制读权（非防 root/同进程恶意）
        except OSError:
            pass
        return key

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self._on_event is not None:
            self._on_event(event, payload)

    def _replay_index(self) -> None:
        lines = self._path.read_text(encoding="utf-8").splitlines()
        n = len(lines)
        for i, line in enumerate(lines):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                # 复核 #12：坏行【不静默】。末尾残尾行（崩溃）属良性；非末尾坏行可能吞掉一条 fixture
                # → 计数 + 发事件，绝不让 distinct（honest-N）静默缩水而无痕。
                self._corrupt_lines += 1
                self._emit("fixture_line_corrupt", {"line": i, "is_tail": i == n - 1})
                continue
            key = row.get("fixture_key")
            if not key:
                self._corrupt_lines += 1
                self._emit("fixture_line_corrupt", {"line": i, "reason": "no fixture_key"})
                continue
            self._rows_by_key.setdefault(key, []).append(row)
            self._latest[key] = row
            self._distinct.add(key)
            if row.get("consumed"):
                self._consumed.add(key)   # tombstone 不从 distinct 移除（honest-N 不可改小）

    # ── 写 ──
    def put(self, fixture: LLMFixture) -> LLMFixture:
        with self._lock:
            fixture.integrity = compute_hmac(fixture, self._key)
            existing = self._latest.get(fixture.fixture_key)
            if existing is not None:
                # 内容寻址幂等：同 key 同内容 → 返存量不重复落盘；同 key 异内容 → 拒（append-only）。
                ex = LLMFixture.from_dict(existing)
                if ex.signing_payload() == fixture.signing_payload():
                    return ex
                raise FixtureConflict(
                    f"fixture_key={fixture.fixture_key} 已存在且内容不同 → append-only 不许静默覆盖"
                )
            # fingerprint 漂移 + 别名检测（不静默）。
            pin = fixture.model_pin or {}
            prov, mid = str(pin.get("provider", "")), str(pin.get("model_id", ""))
            fp = pin.get("system_fingerprint")
            if is_alias_model_id(mid):
                self._emit("model_id_is_alias", {"fixture_key": fixture.fixture_key, "model_id": mid})
            mk = (prov, mid)
            if mk in self._last_fp and self._last_fp[mk] != fp:
                self._emit("fingerprint_drift", {
                    "fixture_key": fixture.fixture_key, "provider": prov, "model_id": mid,
                    "from": self._last_fp[mk], "to": fp,
                })
            self._last_fp[mk] = fp
            row = fixture.to_dict()
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
            self._rows_by_key.setdefault(fixture.fixture_key, []).append(row)
            self._latest[fixture.fixture_key] = row
            self._distinct.add(fixture.fixture_key)
            return fixture

    def tombstone(self, fixture_key: str) -> None:
        with self._lock:
            row = self._latest.get(fixture_key)
            if row is None:
                raise KeyError(f"fixture 不存在: {fixture_key}")
            # tombstoned 入 signing_payload → 必须重算 HMAC，否则新行过不了 get() 完整性门。
            fixture = LLMFixture.from_dict(row)
            fixture.tombstoned = True
            fixture.integrity = compute_hmac(fixture, self._key)
            row = fixture.to_dict()
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            self._rows_by_key.setdefault(fixture_key, []).append(row)
            self._latest[fixture_key] = row
            # distinct 不变（honest-N 不可改小）

    def consume(self, fixture_key: str) -> None:
        """一次性消费留痕（R12）：第二次消费产 consumed_again 告警事件（防自欺非防恶意）。"""

        with self._lock:
            if fixture_key in self._consumed:
                self._emit("consumed_again", {"fixture_key": fixture_key})
                return
            self._consumed.add(fixture_key)
            row = self._latest.get(fixture_key)
            if row is not None:
                # consumed 入 signing_payload → 必须重算 HMAC，否则新行过不了 get() 完整性门。
                fixture = LLMFixture.from_dict(row)
                fixture.consumed = True
                fixture.integrity = compute_hmac(fixture, self._key)
                row = fixture.to_dict()
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                self._rows_by_key.setdefault(fixture_key, []).append(row)
                self._latest[fixture_key] = row

    # ── 读 ──
    def get(self, fixture_key: str) -> LLMFixture:
        with self._lock:
            rows = list(self._rows_by_key.get(fixture_key, []))
        if not rows:
            raise KeyError(f"fixture 不存在: {fixture_key}")
        # 复核 #5：从最新行往回找第一条 HMAC 通过的——一条追加的伪造/坏行不能把好 fixture 锁死
        # （可用性兜底）。找到旧的有效行 → 发 integrity_violation 事件（不静默），返回它。
        latest_bad = False
        for row in reversed(rows):
            fx = LLMFixture.from_dict(row)
            if verify_hmac(fx, self._key):
                if latest_bad:
                    self._emit("integrity_violation", {
                        "fixture_key": fixture_key, "detail": "最新行 HMAC 失败，回退到上一有效行(防自欺)",
                    })
                return fx
            latest_bad = True
        # 没有任何有效行 → 抓篡改（A2：唯一行被改且无可回退）。
        raise IntegrityError(f"fixture_key={fixture_key} 无任何 HMAC 通过的行 → 内容被篡改(防自欺)")

    def get_optional(self, fixture_key: str) -> LLMFixture | None:
        with self._lock:
            present = fixture_key in self._latest
        return self.get(fixture_key) if present else None

    def distinct_count(self) -> int:
        """distinct fixture_key 数（tombstone 不减）——honest-N 视图，不可改小。"""

        with self._lock:
            return len(self._distinct)


__all__ = ["FIXTURES_FILENAME", "FixtureConflict", "FixtureStore", "IntegrityError", "ReplayMiss"]
