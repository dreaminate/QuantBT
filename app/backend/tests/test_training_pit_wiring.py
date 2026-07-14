"""W2 · B-PIT-1 守卫：训练管线消费 R28 双时态 PIT 点查、堵 look-ahead。

死接线现状：codegen 生成的训练脚本裸 ``pd.read_parquet`` 全量读盘，不经任何 known_at
as-of 边界——panel 里若带未来重述（known_at 晚于训练知识时点）会直接泄露进训练（前视）。
本卡把 ``as_of_known`` 沿 codegen → 生成脚本 → ``load_pit_panel`` 串通：

可证伪验收（种坏门必抓）：
1. 给定 as_of_known，训练只见「截至该 known_at 已知」的行；未来 known_at 行必被挡
   （MUT：load_pit_panel 退回裸 read_parquet / 忽略 as_of_known → 未来行泄露 → 本套件红）。
2. as_of_known=None / known_at 列缺失 → 逐字现状不变（向后兼容·additive·绝不改既有训练行为）。
3. 绝不留全量 read_parquet 无 as-of 守卫旁路（断言生成脚本走 as-of 点查 + 与 field_catalog
   单一源折叠语义等价证明）。
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import polars as pl
import pytest

from app.training import run_code
from app.training.codegen import (
    _HEADER,
    _panel_load_header,
    load_pit_panel,
    spec_to_code,
)

# ── 公共构造：含未来重述 + 纯未来泄露行的双时态 panel ────────────────────────
#
# Row1: ts=2023-12-31 roe=10.0 known_at=2024-01-30  → as_of 2024-02-01 时已知（应见）
# Row2: ts=2023-12-31 roe=10.5 known_at=2024-04-15  → 重述，as_of 2024-02-01 时未知（应挡）
# Row3: ts=2024-06-30 roe=99.0 known_at=2024-09-01  → 纯未来泄露行（应挡）
_AS_OF = "2024-02-01"


def _bitemporal_pandas() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "roe": 10.0,
             "known_at": datetime(2024, 1, 30, tzinfo=UTC)},
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "roe": 10.5,
             "known_at": datetime(2024, 4, 15, tzinfo=UTC)},
            {"ts": datetime(2024, 6, 30, tzinfo=UTC), "symbol": "X", "roe": 99.0,
             "known_at": datetime(2024, 9, 1, tzinfo=UTC)},
        ]
    )


def _write(tmp_path: Path, df: pd.DataFrame, name: str = "panel.parquet") -> str:
    p = tmp_path / name
    df.to_parquet(p)
    return str(p)


_ML_SPEC = {
    "model": "xgboost", "task": "regression",
    "feature_cols": ["f1", "f2"], "label_col": "label", "hyperparams": {},
}
_DL_SPEC = {
    "model": "lstm", "task": "regression",
    "feature_cols": ["f1", "f2"], "label_col": "label", "hyperparams": {},
}


# ═══════════════ 准则3：生成脚本走 as-of 点查、无裸读旁路 ═══════════════


def test_codegen_threads_as_of_known_no_naked_read_bypass() -> None:
    """as_of_known 给定 → ML 脚本走 load_pit_panel，绝不留裸 read_parquet 旁路。"""
    code = spec_to_code({**_ML_SPEC, "as_of_known": _AS_OF})
    assert "from app.training.codegen import load_pit_panel" in code
    assert "load_pit_panel(os.environ[\"QUANTBT_PANEL_PATH\"], as_of_known='2024-02-01')" in code
    # 旁路守卫：as_of_known 在场时，绝不能再有不过守卫的全量 read_parquet
    assert 'pd.read_parquet(os.environ["QUANTBT_PANEL_PATH"])' not in code


def test_codegen_dl_also_threads_as_of_known() -> None:
    """DL 脚本同样透传 as_of_known（两条生成路径都堵）。"""
    code = spec_to_code({**_DL_SPEC, "as_of_known": _AS_OF})
    assert "load_pit_panel" in code and "as_of_known='2024-02-01'" in code
    assert 'pd.read_parquet(os.environ["QUANTBT_PANEL_PATH"])' not in code


def test_codegen_as_of_known_literal_is_injection_safe() -> None:
    """as_of_known 烘成字面量必经 repr（注入安全）；date/datetime → ISO 字符串。"""
    import ast

    payload = "'; import os; os.system('x')"
    code = spec_to_code({**_ML_SPEC, "as_of_known": payload})
    # 烘进去的恰是 repr(payload)（一个普通字符串字面量；repr 自动选安全引号）
    assert f"as_of_known={payload!r}" in code
    # 严格证明：解析生成的 load_pit_panel(...) 调用，as_of_known 实参必是字面 Constant
    # （= 纯数据；若注入成功会是 Call/表达式节点 → 断言红），且 eval 回来恒等原 payload。
    line = next(ln for ln in code.splitlines() if "load_pit_panel(" in ln)
    call = ast.parse(line.split("=", 1)[1].strip(), mode="eval").body
    kw = {k.arg: k.value for k in call.keywords}
    assert isinstance(kw["as_of_known"], ast.Constant)
    assert kw["as_of_known"].value == payload
    # date/datetime → ISO 字符串字面量
    assert "as_of_known='2024-02-01'" in spec_to_code({**_ML_SPEC, "as_of_known": date(2024, 2, 1)})


# ═══════════════ 准则2：as_of_known=None / 列缺失 → 逐字现状不变 ═══════════════


def test_codegen_no_as_of_known_is_byte_identical() -> None:
    """无 as_of_known → header 逐字 == _HEADER（裸 read_parquet 保留，绝不改既有训练）。"""
    code_ml = spec_to_code(_ML_SPEC)
    assert code_ml.startswith(_HEADER)
    assert 'pd.read_parquet(os.environ["QUANTBT_PANEL_PATH"])' in code_ml
    assert "load_pit_panel" not in code_ml
    # 显式 None 同样回退
    assert spec_to_code({**_ML_SPEC, "as_of_known": None}).startswith(_HEADER)
    # _panel_load_header 直证：缺键 / None 都返回 _HEADER 本体
    assert _panel_load_header(_ML_SPEC) == _HEADER
    assert _panel_load_header({"as_of_known": None}) == _HEADER


def test_load_pit_panel_none_is_verbatim_read(tmp_path: Path) -> None:
    """as_of_known=None → load_pit_panel == pd.read_parquet 逐字（含未来行、known_at 列保留）。"""
    p = _write(tmp_path, _bitemporal_pandas())
    out = load_pit_panel(p, as_of_known=None)
    assert out.equals(pd.read_parquet(p))
    assert len(out) == 3 and "known_at" in out.columns  # 不折叠、不丢列


def test_load_pit_panel_missing_known_at_is_noop(tmp_path: Path) -> None:
    """as_of_known 给定但无 known_at 列 → 原样返回（mirror _materialize_sub：不假装过滤、不报错）。"""
    df = _bitemporal_pandas().drop(columns=["known_at"])
    p = _write(tmp_path, df, "nok.parquet")
    out = load_pit_panel(p, as_of_known=_AS_OF)
    assert len(out) == 3  # 无知识轴可过滤 → 全保留
    assert out["roe"].tolist() == [10.0, 10.5, 99.0]


# ═══════════════ 准则1：未来 known_at 行必被挡（look-ahead 守卫） ═══════════════


def test_load_pit_panel_blocks_future_known_at_row(tmp_path: Path) -> None:
    """as_of_known=2024-02-01 → 只见首披 10.0；未来重述 10.5 + 纯未来行 99.0 都被挡。

    种坏门：若 load_pit_panel 退回裸 read_parquet / 忽略 as_of_known → 99.0 泄露进训练 → 红。
    """
    p = _write(tmp_path, _bitemporal_pandas())
    out = load_pit_panel(p, as_of_known=_AS_OF)
    assert sorted(out["roe"].tolist()) == [10.0]          # 仅截至 2024-02-01 已知
    assert 99.0 not in out["roe"].tolist()                # 未来泄露行被挡
    assert 10.5 not in out["roe"].tolist()                # 未来重述被挡
    assert "known_at" not in out.columns                  # 折叠后 known_at 不外泄为因子


def test_load_pit_panel_blocks_future_row_without_symbol(tmp_path: Path) -> None:
    """无 symbol 列（_panel 形态：ts-only 折叠键）→ 仍按 ts 折叠、挡未来 known_at。"""
    df = _bitemporal_pandas().drop(columns=["symbol"])
    p = _write(tmp_path, df, "nosym.parquet")
    out = load_pit_panel(p, as_of_known=_AS_OF)
    assert sorted(out["roe"].tolist()) == [10.0]
    assert 99.0 not in out["roe"].tolist()


def test_load_pit_panel_latest_known_restatement(tmp_path: Path) -> None:
    """as_of_known 推进到 2024-05-01 → 见修正 10.5（取截至该时点最新已知重述）；未来行仍挡。"""
    p = _write(tmp_path, _bitemporal_pandas())
    out = load_pit_panel(p, as_of_known="2024-05-01")
    assert sorted(out["roe"].tolist()) == [10.5]
    assert 99.0 not in out["roe"].tolist()


# ═══════════════ 复用单一源·等价证明（不另造） ═══════════════


def test_load_pit_panel_collapse_equals_field_catalog_single_source(tmp_path: Path) -> None:
    """as_of_known 给定时，load_pit_panel 折叠 == field_catalog.load_panel(as_of_known) 单一源。

    同一份双时态数据：经 FieldCatalog 单一源点查 与 经训练 PIT loader 点查，解析值逐条一致
    → 证明训练管线复用单一 as-of 源（as_of_bound + 折叠语义），不另造平行 PIT 逻辑。
    None 路径**不**纳入等价（训练 None=逐字读·向后兼容；catalog None=本层折叠，两层语义本就不同）。
    """
    from app.connectors.base import make_wide_fetch_result
    from app.data_quality import DatasetRegistry
    from app.field_catalog import FieldCatalog, FieldRequirement

    f = pl.DataFrame(
        [
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "market": "stocks_cn",
             "interval": "1q", "roe": 10.0, "known_at": date(2024, 1, 30)},
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "market": "stocks_cn",
             "interval": "1q", "roe": 10.5, "known_at": date(2024, 4, 15)},
        ]
    )
    pa = tmp_path / "fina.parquet"
    f.write_parquet(pa)
    reg = DatasetRegistry(tmp_path / "r.jsonl")
    reg.register("fina", make_wide_fetch_result(f, "user_x"), file_paths=[str(pa)],
                 metadata={"market": "stocks_cn", "interval": "1q", "data_kind": "fina_indicator"})
    cat = FieldCatalog(reg)
    req = FieldRequirement(canonical_ids=["roe"], market="stocks_cn", interval="1q")

    pb = tmp_path / "panel_b.parquet"
    f.to_pandas().to_parquet(pb)

    for aok in ["2024-02-01", "2024-05-01"]:
        single = sorted(cat.load_panel(req, as_of_known=aok).panel.get_column("roe").to_list())
        loader = sorted(load_pit_panel(str(pb), as_of_known=aok)["roe"].dropna().tolist())
        assert single == loader, f"as_of_known={aok}: catalog={single} != pit_loader={loader}"


# ═══════════════ 端到端：生成 header 在真 runner 子进程里挡泄露 ═══════════════


def test_generated_pit_header_blocks_leak_in_subprocess(tmp_path: Path) -> None:
    """生成脚本（PIT header）在真子进程跑：as_of_known 在场只见 1 行(roe=10.0)、未来行被挡；
    去掉 as_of_known（逐字 _HEADER 裸读）则全 3 行可见。证明 codegen→脚本→load_pit_panel 全链通。

    种坏门：若 header 退回裸 read_parquet（旁路守卫）→ rows/roe_max 含未来 99.0 → 红。
    """
    panel_path = _write(tmp_path, _bitemporal_pandas())
    body = (
        "emit({'oos_metrics': {'rows': float(len(panel)), "
        "'roe_max': float(panel['roe'].max())}, 'artifact_path': None})\n"
    )
    env = {"QUANTBT_PANEL_PATH": panel_path}

    # PIT 守卫在场：未来重述 + 未来行都被挡
    pit_code = _panel_load_header({"as_of_known": _AS_OF}) + body
    res = run_code(pit_code, tmp_path / "job_pit", env_extra=env, timeout=300)  # CI 2vCPU 满载时 120s 边际(run6 实证)
    assert res.ok, res.stderr[-800:]
    assert res.emit["oos_metrics"]["rows"] == 1.0
    assert res.emit["oos_metrics"]["roe_max"] == 10.0  # 99.0/10.5 都被挡

    # 无 as_of_known（逐字 _HEADER 裸读）：现状全量可见（向后兼容对照）
    raw_code = _panel_load_header({}) + body
    assert raw_code.startswith(_HEADER)  # 确实走的是原 header
    res2 = run_code(raw_code, tmp_path / "job_raw", env_extra=env, timeout=300)
    assert res2.ok, res2.stderr[-800:]
    assert res2.emit["oos_metrics"]["rows"] == 3.0
    assert res2.emit["oos_metrics"]["roe_max"] == 99.0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
