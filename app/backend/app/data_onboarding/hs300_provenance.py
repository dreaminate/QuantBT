"""HS300 真数据证据链 —— provenance/universe payload 构造 + 签名 + canonical 哈希。

本模块是 GOAL §16 沪深300×10年日频读取基线的【生产侧】证据生产者：把一个真实
``DatasetVersion`` + 其不可变 manifest + 一份分离签名的 000300.SH 成分快照，绑成
perf-harness (``app/backend/tests/benchmark/perf_harness.py``) 能逐字节验收的
detached HMAC 收据。

诚实边界（与 harness 文档一致）：
- ``operator_attested`` = 运营方对源/成分契约的背书，**不是** Tushare 数字签名。
- 本模块只负责把内容按 harness 契约 canonical 化 + HMAC 签名；能否闭 GAP 还取决于
  harness 侧是否 pin 了对应 authority root（那是独立复审步骤，不由数据方自铸）。

【契约镜像·非导入】：harness 在 tests/ 下，app 代码禁止 import tests。这里的 canonical
字节序、列序、字段集、schema 串都是对 harness 私有实现的**语义复刻**；两侧的逐字节等价
由 ``tests/data_onboarding/test_hs300_pipeline.py`` 直接对拍 harness 符号钉死。

【密钥红线】：HMAC key 只在 ``sign_payload`` 内部用于计算签名，**绝不**写入任何 payload、
文件、返回值或异常文本；落地的只有 HMAC 十六进制签名与 sha256 指纹，永不含 key 明文。
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import polars as pl

# ── schema / ref 常量镜像（值与 harness 相同；相等性由测试钉死）──────────────────
RECEIPT_SCHEMA = "quantbt.hs300_perf_provenance.v2"
UNIVERSE_SCHEMA = "quantbt.hs300_perf_universe.v2"
UNIVERSE_REF = "tushare://index_weight/000300.SH"

# harness ``_HS300_RECEIPT_PAYLOAD_FIELDS`` 的镜像（21 字段，缺一多一 harness 即拒）。
RECEIPT_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "authority_root_id",
        "key_id",
        "dataset_id",
        "dataset_version",
        "dataset_record_sha256",
        "dataset_frame_sha256",
        "manifest_sha256",
        "source_name",
        "source_ref",
        "ingestion_skill_version",
        "market",
        "interval",
        "data_kind",
        "universe_ref",
        "universe_snapshot_sha256",
        "loaded_panel_sha256",
        "row_count",
        "coverage_start_utc",
        "coverage_end_utc",
        "attested_at_utc",
    }
)

# harness ``_HS300_UNIVERSE_PAYLOAD_FIELDS`` 的镜像（7 字段）。
UNIVERSE_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "authority_root_id",
        "key_id",
        "universe_ref",
        "as_of_date",
        "constituent_symbols",
        "constituent_list_dates",
    }
)


def canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Canonical 签名字节：与 harness ``_canonical_json_bytes`` / fixture 逐字节一致。

    ``json.dumps(ensure_ascii=False, sort_keys=True, separators=(",", ":"))`` 后 utf-8。
    """

    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sign_payload(payload: dict[str, Any], key: str) -> dict[str, Any]:
    """在 payload 上附加 ``signature_hmac_sha256`` = HMAC-SHA256(key, canonical(payload))。

    返回新 dict（不原地改），签名覆盖 canonical 化的 payload（不含签名字段本身）——
    与 harness ``_verify_hs300_hmac`` 的验证口径完全对齐。key 不落入返回值。
    """

    signature = hmac.new(
        key.encode("utf-8"),
        canonical_payload_bytes(payload),
        hashlib.sha256,
    ).hexdigest()
    return {**payload, "signature_hmac_sha256": signature}


def write_signed_json(path: str | Path, payload: dict[str, Any], key: str) -> Path:
    """把 signed payload 写文件（sort_keys=True, ensure_ascii=False），返回路径。

    harness ``_read_hs300_json_object`` 只做 ``json.loads`` + dict 校验（与键序无关），
    签名验证时再对 payload 子 dict 重新 canonical 化，故文件键序不影响验收。
    """

    signed = sign_payload(payload, key)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(signed, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return out


def loaded_panel_sha256(frame: pl.DataFrame) -> str:
    """语义复刻 harness ``_hs300_loaded_panel_sha256``：canonical reader 输出哈希。

    canonical 列序 ``[ts, symbol, open, high, low, close, volume]``，OHLCV 转 Float64，
    按 ``(symbol, ts)`` 排序、rechunk 后走 ``app.connectors.base._sha256_of_frame``
    （与 harness 同一单源哈希函数）。等价性由测试对拍 harness 钉死。
    """

    from app.connectors.base import _sha256_of_frame

    canonical_columns = [
        "ts",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]
    canonical = (
        frame.select(canonical_columns)
        .with_columns(
            [
                pl.col(column).cast(pl.Float64, strict=False).alias(column)
                for column in ("open", "high", "low", "close", "volume")
            ]
        )
        .sort(["symbol", "ts"])
        .rechunk()
    )
    return _sha256_of_frame(canonical)


def build_universe_payload(
    root_id: str,
    key_id: str,
    as_of_date: str,
    symbols: list[str],
    list_dates: dict[str, str],
) -> dict[str, Any]:
    """构造 universe payload（字段集 == fixture universe_payload，7 字段）。

    ``constituent_symbols`` 排序去重（harness 要求 sorted、unique）；
    ``constituent_list_dates`` 键必须恰好覆盖 symbols（harness 要求 set 相等）。
    """

    ordered = sorted(set(symbols))
    missing = [symbol for symbol in ordered if symbol not in list_dates]
    if missing:
        raise KeyError(
            f"constituent_list_dates 缺 {len(missing)} 个成员的上市日（如 {missing[:3]}）"
        )
    return {
        "schema_version": UNIVERSE_SCHEMA,
        "authority_root_id": root_id,
        "key_id": key_id,
        "universe_ref": UNIVERSE_REF,
        "as_of_date": as_of_date,
        "constituent_symbols": ordered,
        "constituent_list_dates": {symbol: list_dates[symbol] for symbol in ordered},
    }


def build_receipt_payload(
    *,
    root_id: str,
    key_id: str,
    dataset_id: str,
    dataset_version: str,
    dataset_record_sha256: str,
    dataset_frame_sha256: str,
    manifest_sha256: str,
    source_name: str,
    source_ref: str,
    ingestion_skill_version: str,
    market: str,
    interval: str,
    data_kind: str,
    universe_snapshot_sha256: str,
    loaded_panel_sha256: str,
    row_count: int,
    coverage_start_utc: str,
    coverage_end_utc: str,
    attested_at_utc: str,
) -> dict[str, Any]:
    """构造 provenance receipt payload（字段集 == fixture payload，21 字段）。

    ``schema_version`` / ``universe_ref`` 为常量镜像；其余由调用方从真实
    ``DatasetVersion`` + manifest + universe 派生传入。缺一多一 harness 即拒。
    """

    return {
        "schema_version": RECEIPT_SCHEMA,
        "authority_root_id": root_id,
        "key_id": key_id,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "dataset_record_sha256": dataset_record_sha256,
        "dataset_frame_sha256": dataset_frame_sha256,
        "manifest_sha256": manifest_sha256,
        "source_name": source_name,
        "source_ref": source_ref,
        "ingestion_skill_version": ingestion_skill_version,
        "market": market,
        "interval": interval,
        "data_kind": data_kind,
        "universe_ref": UNIVERSE_REF,
        "universe_snapshot_sha256": universe_snapshot_sha256,
        "loaded_panel_sha256": loaded_panel_sha256,
        "row_count": row_count,
        "coverage_start_utc": coverage_start_utc,
        "coverage_end_utc": coverage_end_utc,
        "attested_at_utc": attested_at_utc,
    }


__all__ = [
    "RECEIPT_SCHEMA",
    "UNIVERSE_SCHEMA",
    "UNIVERSE_REF",
    "RECEIPT_PAYLOAD_FIELDS",
    "UNIVERSE_PAYLOAD_FIELDS",
    "canonical_payload_bytes",
    "sign_payload",
    "write_signed_json",
    "loaded_panel_sha256",
    "build_universe_payload",
    "build_receipt_payload",
]
