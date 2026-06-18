"""VerdictStore · 验证官裁决记录 append-only JSONL（按 verdict_id 取，供下游 join）。

content-addressed：同输入→同 verdict_id，重复 record 幂等（不重复落盘）。
`verdict_for(verdict_id)` 给 T-019 审批门做闸门查询（blocked/concern → 晋升缺口）。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .schema import VerdictRecord, VerdictTamperError, verdict_id_of


class VerdictStore:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._path = self._root / "verdicts.jsonl"
        if not self._path.exists():
            self._path.write_text("")
        self._lock = threading.Lock()

    def record(self, record: VerdictRecord) -> VerdictRecord:
        """落盘（content-addressed 幂等：已存在同 verdict_id 则不重复写）。"""

        with self._lock:
            if self._get_locked(record.verdict_id) is not None:
                return record
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
        return record

    def record_for(self, verdict_id: str | None) -> VerdictRecord | None:
        """返回完整 VerdictRecord（含 target_ref，供闸门绑定校验），缺失返回 None。

        复核 #3：读路径==被核验路径——重算 verdict_id 与存量不符即 raise VerdictTamperError，
        **绝不返回脏数据**（与 T-013 一本账 verify_chain / T-016 fixture HMAC 同一不变量）。
        verdict_id 是 content-addressed（覆盖 verdict/target_ref/对账/独立性），改任一字段即被抓。
        """

        if not verdict_id:
            return None
        with self._lock:
            row = self._get_locked(verdict_id)
        if row is None:
            return None
        rec = VerdictRecord.from_dict(row)
        recomputed = verdict_id_of(rec)
        if recomputed != rec.verdict_id:
            raise VerdictTamperError(
                f"裁决 {verdict_id} 落盘被篡改：重算 {recomputed} ≠ 存量 {rec.verdict_id}（拒返脏数据）"
            )
        return rec

    def get(self, verdict_id: str) -> VerdictRecord:
        rec = self.record_for(verdict_id)
        if rec is None:
            raise KeyError(f"verdict 不存在: {verdict_id}")
        return rec

    def verdict_for(self, verdict_id: str | None) -> str | None:
        """返回该 verdict_id 的裁决值（consistent/concern/blocked），缺失返回 None；篡改 raise。"""

        rec = self.record_for(verdict_id)
        return rec.verdict if rec else None

    def _get_locked(self, verdict_id: str) -> dict[str, Any] | None:
        if not verdict_id:
            return None
        found: dict[str, Any] | None = None
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("verdict_id") == verdict_id:
                found = row              # 取最后一条（append-only，理论上唯一）
        return found

    def list_all(self, *, verify: bool = True) -> list[VerdictRecord]:
        with self._lock:
            rows: list[dict[str, Any]] = []
            for line in self._path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        out: list[VerdictRecord] = []
        for r in rows:
            rec = VerdictRecord.from_dict(r)
            if verify and verdict_id_of(rec) != rec.verdict_id:
                raise VerdictTamperError(f"裁决 {rec.verdict_id} 落盘被篡改（list_all 拒返脏数据）")
            out.append(rec)
        return out


__all__ = ["VerdictStore"]
