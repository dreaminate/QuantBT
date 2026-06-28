"""C-S11-PIT-ENFORCE【对抗式】测试：真数据层 confirmatory PIT 强制（GOAL §11 line1759）。

GOAL §11 可证伪验收：「无 PIT 语义的数据进入 confirmatory validation → 拒」。本卡在真数据路径
三处 fail-closed 接 PIT 硬门（各复用既有校验器，绝不重造 PIT 规则）：
  A. data_pull.execute_data_pull —— 拉取入口（复用 market_data_contract.validate_dataset_semantics）。
  B. field_catalog.load_panel    —— 取数物化（堵 _materialize_sub 的「无 known_at 轴 → 静默落现行视图」前视面）。
  C. training.codegen.load_pit_panel + _panel_load_header —— 训练取数（堵 _HEADER 裸 read_parquet 旁路）。

种已知坏门必抓（RULES §2）：非 PIT 数据进 confirmatory → 必拒；放过即红。每处配 enforce-off /
confirmatory-off 的「单点可逆」kill-switch 用例：关门 → 坏数据放行（坐实拒绝来自这道门、非别处副作用）。

诚实边界：A 校验【声明的 PIT ref 在场】（ref→真 schema 解析是 SA-1 另卡）；B/C 强制【物理 known_at 轴】，
两层互补。非 confirmatory（research/backtest/None）逐字现状不变（向后兼容·不误伤探索）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from app import data_pull
from app.data_pull import ConfirmatoryPITRejected, enforce_confirmatory_pit, execute_data_pull
from app.connectors.base import make_wide_fetch_result
from app.data_quality import DatasetRegistry
from app.field_catalog import ConfirmatoryPanelRejected, FieldCatalog, FieldRequirement
from app.field_catalog import catalog as fc_catalog
from app.research_os.market_data_contract import DatasetSemanticsRecord, ValidationUseContext
from app.schemas import DataPullRequest
from app.training import codegen as cg
from app.training.codegen import _HEADER, _panel_load_header, load_pit_panel

_CONFIRMATORY = ValidationUseContext.CONFIRMATORY_VALIDATION


def _semantics(*, pit: bool, dataset_ref: str = "dataset:btc_daily:v1") -> DatasetSemanticsRecord:
    """一条数据集语义；pit=False → known_at/effective_at/PIT 规则三 ref 全空（其余字段齐，violation 专指 PIT）。"""
    return DatasetSemanticsRecord(
        dataset_ref=dataset_ref,
        source_ref="source:binance_vision",
        version="v1",
        known_at_ref="known_at:ingest_time" if pit else None,
        effective_at_ref="effective_at:bar_close" if pit else None,
        pit_bitemporal_rules_ref="pit:bars:v1" if pit else None,
        quality_status="passed",
        lineage_refs=("lineage:btc_daily:v1",),
        freshness_status="fresh",
        checksum="sha256:abc",
    )


# =================================================================== #
# A · data_pull —— 拉取入口 confirmatory PIT 硬门
# =================================================================== #


def test_a1_gate_rejects_nonpit_confirmatory():
    """验收①：confirmatory + 缺 known_at/effective_at/PIT → ConfirmatoryPITRejected（带 PIT violation code）。"""
    with pytest.raises(ConfirmatoryPITRejected) as exc:
        enforce_confirmatory_pit(_CONFIRMATORY, [_semantics(pit=False)])
    assert "dataset_missing_pit_semantics" in str(exc.value)


def test_a2_gate_rejects_zero_dataset_confirmatory():
    """fail-closed：confirmatory 但零声明数据集 → 拒（无可核验·绝不放行不可核验数据）。"""
    with pytest.raises(ConfirmatoryPITRejected):
        enforce_confirmatory_pit(_CONFIRMATORY, [])
    with pytest.raises(ConfirmatoryPITRejected):
        enforce_confirmatory_pit(_CONFIRMATORY, None)


def test_a3_gate_allows_pit_confirmatory():
    """验收④：confirmatory + 带 PIT 语义 → 放行（返各数据集 decision 均 accepted·不误伤正路径）。"""
    decisions = enforce_confirmatory_pit(_CONFIRMATORY, [_semantics(pit=True)])
    assert len(decisions) == 1 and all(d.accepted for d in decisions)


def test_a3b_gate_accepts_dict_form_pit():
    """数据集语义可为 to_dict() 形态（经 dataset_semantics_record_from_dict 解析）→ 同样放行。"""
    decisions = enforce_confirmatory_pit(_CONFIRMATORY, [_semantics(pit=True).to_dict()])
    assert len(decisions) == 1 and decisions[0].accepted


@pytest.mark.parametrize("ctx", [None, "research", ValidationUseContext.BACKTEST, ValidationUseContext.PAPER])
def test_a4_gate_noop_for_nonconfirmatory(ctx):
    """向后兼容：非 confirmatory（None/research/backtest/paper）→ advisory no-op（即便非 PIT 也不拒）。"""
    assert enforce_confirmatory_pit(ctx, [_semantics(pit=False)]) == []
    assert enforce_confirmatory_pit(ctx, []) == []


def test_a5_execute_data_pull_rejects_before_pull(monkeypatch):
    """门在【任何拉取之前】拒：confirmatory + 非 PIT → raise，pull 函数绝不被触达（无落盘副作用）。"""
    def _must_not_pull(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("PIT 门未拦住 → 拉取被触达（门是纸做的）")

    monkeypatch.setattr(data_pull, "pull_binance_dataset", _must_not_pull)
    monkeypatch.setattr(data_pull, "pull_tushare_dataset", _must_not_pull)
    payload = DataPullRequest(market="binanceusdm", data_kind="klines", interval="1h")
    with pytest.raises(ConfirmatoryPITRejected):
        execute_data_pull(payload, use_context=_CONFIRMATORY, dataset_semantics=[_semantics(pit=False)])


def test_a6_execute_data_pull_allows_pit_confirmatory(monkeypatch):
    """confirmatory + 带 PIT → 过门，照常进入拉取（返 pull 结果·不误伤正路径）。"""
    monkeypatch.setattr(data_pull, "validate_data_pull_request", lambda payload: None)
    monkeypatch.setattr(data_pull, "pull_binance_dataset", lambda *a, **k: {"written_files": ["sentinel"]})
    payload = DataPullRequest(market="binanceusdm", data_kind="klines", interval="1h")
    out = execute_data_pull(payload, use_context=_CONFIRMATORY, dataset_semantics=[_semantics(pit=True)])
    assert out == {"written_files": ["sentinel"]}


def test_a7_execute_data_pull_backward_compatible(monkeypatch):
    """向后兼容基线：既有调用方不传 use_context → 门 no-op，照常拉取（jobs.py 等口径逐字不变）。"""
    monkeypatch.setattr(data_pull, "validate_data_pull_request", lambda payload: None)
    monkeypatch.setattr(data_pull, "pull_binance_dataset", lambda *a, **k: {"written_files": ["ok"]})
    payload = DataPullRequest(market="binanceusdm", data_kind="klines", interval="1h")
    assert execute_data_pull(payload) == {"written_files": ["ok"]}


def test_a8_mut_killswitch_enforce_off_lets_nonpit_through():
    """单点可逆 MUT：enforce=False → 同输入从 raise 变放行（坐实拒绝来自这道门）。"""
    assert enforce_confirmatory_pit(_CONFIRMATORY, [_semantics(pit=False)], enforce=False) == []


# =================================================================== #
# B · field_catalog.load_panel —— 取数物化 confirmatory PIT 硬门
# =================================================================== #


def _register(reg: DatasetRegistry, tmp_path: Path, dataset_id: str, frame: pl.DataFrame, *, interval: str = "1q") -> None:
    p = tmp_path / f"{dataset_id}.parquet"
    frame.write_parquet(p)
    reg.register(
        dataset_id,
        make_wide_fetch_result(frame, "user_x"),
        file_paths=[str(p)],
        metadata={"market": "stocks_cn", "interval": interval, "data_kind": "fina_indicator"},
    )


def _frame_with_known_at() -> pl.DataFrame:
    """同 (ts,symbol) 两条重述：known_at 2024-01-30(roe10.0) / 2024-04-15(roe10.5)（镜像 test_data_contract）。"""
    return pl.DataFrame(
        [
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "market": "stocks_cn",
             "interval": "1q", "roe": 10.0, "known_at": date(2024, 1, 30)},
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "market": "stocks_cn",
             "interval": "1q", "roe": 10.5, "known_at": date(2024, 4, 15)},
        ]
    )


def _frame_without_known_at() -> pl.DataFrame:
    """无 known_at 轴的日频 close/volume（as_of_known 在此无可过滤 → 真前视面）。"""
    return pl.DataFrame(
        [
            {"ts": datetime(2024, 1, d, tzinfo=UTC), "symbol": "X", "market": "stocks_cn",
             "interval": "1d", "close": 10.0 + d, "volume": 100.0 + d}
            for d in (1, 2, 3)
        ]
    )


def test_b1_confirmatory_rejects_no_known_at_axis(tmp_path):
    """验收（核心前视面）：as_of_known 给定但数据集无 known_at 轴 + confirmatory → 拒静默落现行视图。"""
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, "px", _frame_without_known_at(), interval="1d")
    req = FieldRequirement(canonical_ids=["close", "volume"], market="stocks_cn", interval="1d")
    with pytest.raises(ConfirmatoryPanelRejected, match="known_at"):
        FieldCatalog(reg).load_panel(req, as_of_known="2024-02-01", use_context=_CONFIRMATORY)


def test_b2_confirmatory_allows_pit_panel_and_filters(tmp_path):
    """验收④：有 known_at 轴 + as_of_known + confirmatory → 不拒、真按 known_at 折叠、pit_filter_applied=True。"""
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, "fina", _frame_with_known_at())
    req = FieldRequirement(canonical_ids=["roe"], market="stocks_cn", interval="1q")
    res = FieldCatalog(reg).load_panel(req, as_of_known="2024-02-01", use_context=_CONFIRMATORY)
    assert res.panel.get_column("roe").to_list() == [10.0]   # 那时只知首披（晚于知识时点的 10.5 被挡）
    assert res.pit_filter_applied is True
    assert res.pit_missing_known_at == ()


def test_b3_confirmatory_rejects_unpinned_as_of(tmp_path):
    """confirmatory 必须 pin as_of_known（无知识时点=全知视图=前视）→ 拒。"""
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, "fina", _frame_with_known_at())
    req = FieldRequirement(canonical_ids=["roe"], market="stocks_cn", interval="1q")
    with pytest.raises(ConfirmatoryPanelRejected, match="as_of_known"):
        FieldCatalog(reg).load_panel(req, as_of_known=None, use_context=_CONFIRMATORY)


def test_b4_confirmatory_rejects_zero_dataset(tmp_path):
    """confirmatory + 解析到零数据集（请求字段不存在）→ 拒（无可核验 PIT·fail-closed）。"""
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, "px", _frame_without_known_at(), interval="1d")
    req = FieldRequirement(canonical_ids=["roe"], market="stocks_cn", interval="1d")  # roe 不在该集 → 零贡献
    with pytest.raises(ConfirmatoryPanelRejected, match="零数据集"):
        FieldCatalog(reg).load_panel(req, as_of_known="2024-02-01", use_context=_CONFIRMATORY)


def test_b5_backward_compatible_no_known_at_not_gated(tmp_path):
    """向后兼容：无 known_at 轴 + as_of_known + use_context=None（既有口径）→ 不拒，pit_missing_known_at 诚实标缺。"""
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, "px", _frame_without_known_at(), interval="1d")
    req = FieldRequirement(canonical_ids=["close", "volume"], market="stocks_cn", interval="1d")
    res = FieldCatalog(reg).load_panel(req, as_of_known="2024-02-01")  # use_context 缺省 None
    assert res.row_count == 3                       # 现行视图原样返回（不假装过滤）
    assert res.pit_filter_applied is False
    assert res.pit_missing_known_at == ("px",)      # 诚实标：该数据集 as_of_known 静默落空


def test_b6_mut_killswitch_enforce_off_lets_nonpit_through(tmp_path, monkeypatch):
    """单点可逆 MUT：ENFORCE_CONFIRMATORY_PANEL_PIT=False → B1 同输入从 raise 变放行（坐实门是当事机制）。"""
    monkeypatch.setattr(fc_catalog, "ENFORCE_CONFIRMATORY_PANEL_PIT", False)
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    _register(reg, tmp_path, "px", _frame_without_known_at(), interval="1d")
    req = FieldRequirement(canonical_ids=["close", "volume"], market="stocks_cn", interval="1d")
    res = FieldCatalog(reg).load_panel(req, as_of_known="2024-02-01", use_context=_CONFIRMATORY)
    assert res.pit_filter_applied is False and res.pit_missing_known_at == ("px",)  # 放行了坏数据


# =================================================================== #
# C · training.codegen —— 训练取数 confirmatory PIT 硬门（堵 _HEADER 旁路）
# =================================================================== #


def _parquet_with_known_at(tmp_path: Path) -> str:
    p = tmp_path / "panel_kn.parquet"
    _frame_with_known_at().write_parquet(p)
    return str(p)


def _parquet_without_known_at(tmp_path: Path) -> str:
    p = tmp_path / "panel_nokn.parquet"
    _frame_without_known_at().write_parquet(p)
    return str(p)


def test_c1_load_pit_panel_confirmatory_requires_as_of(tmp_path):
    """confirmatory 训练取数缺 as_of_known → ValueError（拒裸全量读·先于读盘）。"""
    with pytest.raises(ValueError, match="as_of_known"):
        load_pit_panel("/nonexistent.parquet", as_of_known=None, confirmatory=True)


def test_c2_load_pit_panel_confirmatory_rejects_no_known_at(tmp_path):
    """confirmatory + panel 无 known_at 轴 → ValueError（堵静默落空前视面）。"""
    with pytest.raises(ValueError, match="known_at"):
        load_pit_panel(_parquet_without_known_at(tmp_path), as_of_known="2024-02-01", confirmatory=True)


def test_c3_load_pit_panel_confirmatory_filters_future_known_at(tmp_path):
    """confirmatory + 有 known_at 轴 → 不拒、真折叠（晚于 as_of_known 的未来重述被挡在训练之外）。"""
    out = load_pit_panel(_parquet_with_known_at(tmp_path), as_of_known="2024-02-01", confirmatory=True)
    assert list(out["roe"]) == [10.0]   # 10.5（known_at 2024-04-15）被挡


def test_c4_load_pit_panel_backward_compatible_no_known_at(tmp_path):
    """向后兼容：confirmatory=False + 无 known_at → 现行视图原样返回（既有训练逐字不变·不假装过滤）。"""
    out = load_pit_panel(_parquet_without_known_at(tmp_path), as_of_known="2024-02-01", confirmatory=False)
    assert len(out) == 3


def test_c5_header_confirmatory_without_as_of_raises():
    """堵 codex 抓的 _HEADER 旁路：confirmatory spec 缺 as_of_known → 拒（绝不回落裸 read_parquet）。"""
    with pytest.raises(ValueError, match="as_of_known"):
        _panel_load_header({"confirmatory": True})
    with pytest.raises(ValueError, match="as_of_known"):
        _panel_load_header({"use_context": "confirmatory_validation"})


def test_c6_header_confirmatory_emits_confirmatory_true():
    """confirmatory spec + as_of_known → 生成脚本走 load_pit_panel 且带 confirmatory=True（运行期再 fail-closed）。"""
    header = _panel_load_header({"confirmatory": True, "as_of_known": "2024-01-05"})
    assert "load_pit_panel(" in header
    assert "confirmatory=True" in header


def test_c7_header_non_confirmatory_unchanged():
    """向后兼容：非 confirmatory + 无 as_of_known → 逐字 _HEADER（裸 read_parquet·既有训练不变）。"""
    assert _panel_load_header({}) == _HEADER
    assert _panel_load_header({"model": "x"}) == _HEADER


def test_c8_spec_to_code_confirmatory_closes_header_bypass():
    """公开路径端到端：confirmatory ml spec 缺 as_of_known 经 spec_to_code → 拒（_HEADER 旁路确被堵）。"""
    spec = {
        "model": "xgboost", "task": "regression", "feature_cols": ["close"],
        "label_col": "label", "confirmatory": True,
    }
    with pytest.raises(ValueError, match="as_of_known"):
        cg.spec_to_code(spec)
    # 同 spec 带 as_of_known → 生成脚本含 confirmatory=True（不误伤正路径）
    spec_ok = {**spec, "as_of_known": "2024-01-05"}
    code = cg.spec_to_code(spec_ok)
    assert "load_pit_panel(" in code and "confirmatory=True" in code
