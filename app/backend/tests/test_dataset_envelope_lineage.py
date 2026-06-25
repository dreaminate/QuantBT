"""W3 余 · B-VERSION-1 余 · 数据写门 scope 余项对抗验收。

承接 0430cd78（核心写时 block 门：缺 dataset_version/checksum/篡改 → 拒），本卡补 canonical
scope 余项并以可证伪测试钉死：

1. **provenance 必备门（拍板开关）**：`require_provenance=True` → 缺 ingestion_skill_version /
   secret_ref 即拒；secret_ref 必须是【引用】(scheme:…)，明文裸 key → 拒（红线：实盘 key/secret
   不落明文），且诊断不回显凭据原值。默认 False → 既有写入不受影响（不强加口径）。
2. **on-disk manifest 不可变门**：register 自动落 manifest（per-file sha256）+ 校验；同 version_id
   下磁盘内容漂移 / manifest 被篡改 → register 拒（DatasetIntegrityError），拒后不落账。
3. **data 级 lineage 可追溯 dataset→factor**：每个 DatasetVersion 恒带内容寻址 lineage_id；
   复用 FactorBinding 三元组 → trace_dataset_to_factors 连出 dataset_version→factor 边。
4. **向后兼容**：信封字段不进 version_id/checksum（身份不被扰动）；无/占位 file_paths → 无 manifest
   不炸；旧 registry 行（无信封键）经 from_dict 仍解析。

种坏门必抓：把任一门退回 advisory（删 register 接线 / 吞 DatasetIntegrityError / 放过缺凭据）→
对应用例必红。
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest

from app.connectors.base import (
    DatasetWriteIntegrityError,
    is_secret_reference,
    make_wide_fetch_result,
)
from app.data_hash.dataset_hash import DatasetIntegrityError, FactorBinding
from app.data_quality import DatasetRegistry, DatasetVersion, GERule
from app.lineage import (
    DatasetLineageNode,
    DataToFactorEdge,
    derive_dataset_lineage,
    trace_dataset_to_factors,
)


def _frame(n: int = 4) -> pl.DataFrame:
    base = datetime(2024, 1, 1, tzinfo=UTC)
    return pl.DataFrame(
        [
            {
                "ts": base + timedelta(days=i),
                "symbol": "000001.SZ",
                "market": "stocks_cn",
                "interval": "1d",
                "open": 10.0 + i,
                "high": 11.0 + i,
                "low": 9.5 + i,
                "close": 10.5 + i,
                "volume": 1000.0 + i,
            }
            for i in range(n)
        ]
    )


def _reg(tmp_path, name: str = "registry.jsonl") -> DatasetRegistry:
    return DatasetRegistry(tmp_path / name)


# ===================================================================== #
# 验收 1：provenance 必备门 + secret_ref 引用守门（明文不落库·拍板开关）
# ===================================================================== #
def test_require_provenance_rejects_missing_skill_and_secret(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="binance")  # 无 skill_version/secret_ref
    with pytest.raises(DatasetWriteIntegrityError):
        reg.register("ds", fr, require_provenance=True)
    assert reg.list_versions() == []  # 拒后不落账


def test_default_does_not_impose_provenance(tmp_path) -> None:
    """默认 require_provenance=False → 同一 FetchResult 合法落账（提供机制·不强加口径）。"""
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="binance")
    v = reg.register("ds", fr)  # 不传 require_provenance
    assert v.version_id and reg.latest("ds") is not None


def test_provenance_satisfied_with_reference_secret(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = dataclasses.replace(
        make_wide_fetch_result(_frame(), source_name="binance"),
        ingestion_skill_version="binance_klines@1.2.0",
        secret_ref="keyring://binance/apikey#1",
    )
    v = reg.register("ds", fr, require_provenance=True)
    assert v.ingestion_skill_version == "binance_klines@1.2.0"
    assert v.secret_ref == "keyring://binance/apikey#1"
    assert is_secret_reference(v.secret_ref)


def test_plaintext_secret_rejected_and_not_echoed(tmp_path) -> None:
    """红线：明文裸 key（无 scheme）→ 拒（提供即守门·与 require 无关）；诊断绝不回显凭据原值。"""
    reg = _reg(tmp_path)
    raw_key = "AKIAIOSFODNN7PLAINTEXTKEY1234567890"
    bad = dataclasses.replace(
        make_wide_fetch_result(_frame(), source_name="binance"),
        ingestion_skill_version="binance@1.0",
        secret_ref=raw_key,
    )
    with pytest.raises(DatasetWriteIntegrityError) as ei:
        reg.register("ds", bad)  # 注意：未开 require_provenance，secret_ref 提供即被守门
    assert raw_key not in str(ei.value)  # secret 不进诊断/日志
    assert reg.list_versions() == []


def test_is_secret_reference_contract() -> None:
    assert is_secret_reference("keyring://binance/key#1")
    assert is_secret_reference("ref:tushare-token")
    assert is_secret_reference("env:TUSHARE_TOKEN")
    assert is_secret_reference("vault:secret/data/binance")
    assert not is_secret_reference("AKIAIOSFODNN7EXAMPLE")  # 裸 key 无 scheme
    assert not is_secret_reference("")
    assert not is_secret_reference(None)


# ===================================================================== #
# 验收 2：on-disk manifest 不可变门（同 version 漂移 / 篡改 manifest → 拒）
# ===================================================================== #
def test_register_auto_writes_manifest(tmp_path) -> None:
    reg = _reg(tmp_path)
    lake = tmp_path / "lake"
    lake.mkdir()
    pq = lake / "d.parquet"
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    fr.frame.write_parquet(pq)
    v = reg.register("ds_m", fr, file_paths=[str(pq)])
    assert v.manifest_path is not None
    assert Path(v.manifest_path).exists()
    manifest = json.loads(Path(v.manifest_path).read_text(encoding="utf-8"))
    assert manifest["version"] == v.version_id
    assert manifest["files"] and manifest["files"][0]["relative_path"] == "d.parquet"


def test_ondisk_manifest_blocks_disk_tamper_same_version(tmp_path) -> None:
    """同 version_id 下磁盘文件字节漂移 → register 自动校验拒（接活已建不可变门）。"""
    reg = _reg(tmp_path)
    lake = tmp_path / "lake"
    lake.mkdir()
    pq = lake / "d.parquet"
    # 固定 fetched_at → 稳定 version_id（模拟同一逻辑版本被重复登记）
    fr = dataclasses.replace(
        make_wide_fetch_result(_frame(), source_name="tushare"),
        fetched_at_utc="2024-01-01T00:00:00+00:00",
    )
    fr.frame.write_parquet(pq)
    reg.register("ds_imm", fr, file_paths=[str(pq)])
    n_before = len(reg.list_versions())

    # 篡改磁盘数据文件（in-memory frame 不变 → version_id 不变；只有盘上字节漂移）
    fr.frame.with_columns(pl.col("close") + 1.0).write_parquet(pq)
    with pytest.raises(DatasetIntegrityError):
        reg.register("ds_imm", fr, file_paths=[str(pq)])
    assert len(reg.list_versions()) == n_before  # 拒后不落账


def test_ondisk_manifest_detects_manifest_file_tamper(tmp_path) -> None:
    """直接篡改已落 manifest.json 里记录的 sha256 → 再登记同 version → 不可变门拒。"""
    reg = _reg(tmp_path)
    lake = tmp_path / "lake"
    lake.mkdir()
    pq = lake / "d.parquet"
    fr = dataclasses.replace(
        make_wide_fetch_result(_frame(), source_name="tushare"),
        fetched_at_utc="2024-01-01T00:00:00+00:00",
    )
    fr.frame.write_parquet(pq)
    v = reg.register("ds_imm2", fr, file_paths=[str(pq)])

    mpath = Path(v.manifest_path)
    data = json.loads(mpath.read_text(encoding="utf-8"))
    data["files"][0]["sha256"] = "0" * 64  # 篡改记录的 sha
    mpath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(DatasetIntegrityError):
        reg.register("ds_imm2", fr, file_paths=[str(pq)])


# ===================================================================== #
# 验收 3：data 级 lineage 可追溯 dataset→factor
# ===================================================================== #
def test_register_attaches_content_addressed_lineage(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = dataclasses.replace(
        make_wide_fetch_result(_frame(), source_name="tushare"),
        source_ref="tushare://daily",
        ingestion_skill_version="tushare@2.1",
    )
    v = reg.register("btc_daily", fr)
    assert v.lineage_id and v.lineage_id.startswith("dlin_")
    # register 内派生 == 独立 derive（内容寻址一致·单一身份源 ids.content_hash）
    node = derive_dataset_lineage(
        dataset_id=v.dataset_id,
        dataset_version=v.version_id,
        checksum=v.sha256,
        source_ref=v.source_ref,
        ingestion_skill_version=v.ingestion_skill_version,
    )
    assert node.lineage_id == v.lineage_id


def test_lineage_traces_dataset_to_factor(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    v = reg.register("btc_daily", fr)
    node = derive_dataset_lineage(
        dataset_id=v.dataset_id, dataset_version=v.version_id, checksum=v.sha256
    )
    fb = FactorBinding(
        factor_id="mom20",
        expression="ts_pct_change(close, 20)",
        dataset_id=v.dataset_id,
        dataset_version=v.version_id,
    )
    edges = trace_dataset_to_factors(node, [fb])
    assert len(edges) == 1
    edge = edges[0]
    assert isinstance(edge, DataToFactorEdge)
    assert edge.factor_id == "mom20"
    assert edge.dataset_version == v.version_id
    assert edge.lineage_id == v.lineage_id  # dataset_version → factor 连通可追溯
    assert edge.edge_id.startswith("dfe_")


def test_lineage_does_not_misconnect_other_version(tmp_path) -> None:
    """换 dataset_version 的 binding 绝不误连（换数据集版本即另一个因子）。"""
    node = derive_dataset_lineage(dataset_id="d", dataset_version="v1__aaaa", checksum="a" * 64)
    fb_other = FactorBinding(
        factor_id="mom20",
        expression="x",
        dataset_id="d",
        dataset_version="v2__bbbb",  # 不同版本
    )
    assert trace_dataset_to_factors(node, [fb_other]) == []


def test_lineage_id_content_addressed_determinism() -> None:
    n1 = derive_dataset_lineage(dataset_id="d", dataset_version="v1", checksum="a" * 64, source_ref="s")
    n2 = derive_dataset_lineage(dataset_id="d", dataset_version="v1", checksum="a" * 64, source_ref="s")
    assert n1.lineage_id == n2.lineage_id  # 同身份 → 同 id
    n3 = derive_dataset_lineage(dataset_id="d", dataset_version="v2", checksum="a" * 64, source_ref="s")
    assert n3.lineage_id != n1.lineage_id  # 换 version → 换 id
    # 上游集合顺序无关（sorted），但集合本身入哈希
    a = derive_dataset_lineage(dataset_id="d", dataset_version="v1", checksum="a" * 64, upstream=("u2", "u1"))
    b = derive_dataset_lineage(dataset_id="d", dataset_version="v1", checksum="a" * 64, upstream=("u1", "u2"))
    assert a.lineage_id == b.lineage_id


def test_lineage_node_requires_identity() -> None:
    with pytest.raises(ValueError):
        DatasetLineageNode(dataset_id="", dataset_version="v", checksum="a" * 64)
    with pytest.raises(ValueError):
        DatasetLineageNode(dataset_id="d", dataset_version="", checksum="a" * 64)


# ===================================================================== #
# 验收 4：向后兼容（身份不被信封扰动 · 无 manifest 不炸 · 旧行可解析）
# ===================================================================== #
def test_envelope_does_not_perturb_version_id(tmp_path) -> None:
    """信封字段绝不进 version_id/checksum：带不带信封，同 frame+fetched_at → 同 version_id。"""
    frame = _frame()
    base = dataclasses.replace(
        make_wide_fetch_result(frame, source_name="tushare"),
        fetched_at_utc="2024-01-01T00:00:00+00:00",
    )
    v_plain = _reg(tmp_path, "a.jsonl").register("ds_a", base)
    enriched = dataclasses.replace(
        base, source_ref="x://y", ingestion_skill_version="s@1", secret_ref="ref:z"
    )
    v_env = _reg(tmp_path, "b.jsonl").register("ds_a", enriched)
    assert v_plain.version_id == v_env.version_id
    assert v_plain.sha256 == v_env.sha256


def test_envelope_persists_and_roundtrips(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = dataclasses.replace(
        make_wide_fetch_result(_frame(), source_name="tushare"),
        source_ref="tushare://daily",
        ingestion_skill_version="tushare@2.1",
        secret_ref="keyring://tushare/token#1",
        known_at_utc="2024-01-02T00:00:00+00:00",
        effective_at_utc="2024-01-01T00:00:00+00:00",
    )
    v = reg.register("ds_env", fr, rules=[GERule(column="close", rule_type="not_null")])
    assert v.quality_verdict == "pass"
    assert v.source_ref == "tushare://daily"
    assert v.known_at_utc and v.effective_at_utc
    # 持久化 round-trip（含信封字段）
    line = (tmp_path / "registry.jsonl").read_text(encoding="utf-8").strip()
    rt = DatasetVersion.from_dict(json.loads(line))
    assert rt.secret_ref == "keyring://tushare/token#1"
    assert rt.lineage_id == v.lineage_id
    assert rt.ingestion_skill_version == "tushare@2.1"


def test_quality_verdict_fail_on_dirty_rules(tmp_path) -> None:
    reg = _reg(tmp_path)
    fr = make_wide_fetch_result(_frame(), source_name="tushare")
    # close 全非空 → not_null 过；构造一个必失败规则（value_range 上限极小）
    v = reg.register(
        "ds_q",
        fr,
        rules=[GERule(column="close", rule_type="value_range", params={"max": -1})],
    )
    assert v.quality_verdict == "fail"


def test_backward_compat_no_or_placeholder_file_paths(tmp_path) -> None:
    reg = _reg(tmp_path)
    v1 = reg.register("ds", make_wide_fetch_result(_frame(), source_name="t"))
    assert v1.manifest_path is None  # 无 file_paths → 无 manifest
    v2 = reg.register(
        "ds2", make_wide_fetch_result(_frame(), source_name="t"), file_paths=["nope.parquet"]
    )
    assert v2.manifest_path is None  # 占位/不存在路径 → no-op·不炸


def test_old_registry_row_without_envelope_parses() -> None:
    old = {
        "dataset_id": "d",
        "version_id": "20240101__abcdef12",
        "source_name": "s",
        "fetched_at_utc": "2024-01-01T00:00:00+00:00",
        "row_count": 1,
        "coverage_start_utc": None,
        "coverage_end_utc": None,
        "sha256": "a" * 64,
        "file_paths": [],
        "ge_results": [],
        "metadata": {},
    }
    dv = DatasetVersion.from_dict(old)  # 旧行缺信封键 → 默认补
    assert dv.lineage_id is None and dv.secret_ref is None and dv.quality_verdict is None
    # 未知键也不炸（向前兼容）
    dv2 = DatasetVersion.from_dict({**old, "future_field": "x"})
    assert dv2.dataset_id == "d"
