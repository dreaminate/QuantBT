"""W2 · B-PIT-1 activate 守卫：TrainingService 全链消费 R28 双时态 PIT、堵 look-ahead。

第一波 e01bf12f 已通 codegen→生成脚本→``load_pit_panel`` 全链（``test_training_pit_wiring.py``）。
本卡接 **service 层全链**：``TrainingRequest`` 加 additive ``as_of_known`` 字段 + ``to_dict()`` 透传，
使 ``train_now/submit`` 全链走 PIT——

- DL/脚本路：``spec_to_code(request.to_dict())`` 见 ``as_of_known`` → 生成脚本走 ``load_pit_panel``。
- ML 进程内路（``_train_ml``，不渲染脚本）：经 ``_pit_view`` 把 panel 落 parquet → 同一单一源
  ``load_pit_panel`` 折叠点查 → 再 ``train_model``。

可证伪验收（种坏门必抓）：
1. train_now/submit 带 as_of_known → 训练只见「截至该 known_at 已知」的行；未来重述/未来行必被挡。
   MUT：``_pit_view`` 不透传 as_of_known / 退回原 panel → 未来行泄露进训练 → 本套件红。
2. as_of_known=None → 逐字现状不变（向后兼容·additive·既有 ML 训练一字不改）。
3. _train_ml 进程内路同样无前视（panel 经单一源 PIT 折叠；无 known_at 列 → 原样返回不假装过滤）。
4. service 进程内路折叠 == 单一源 ``load_pit_panel`` 点查（不另造平行 PIT 逻辑）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.training import TrainingRequest, TrainingService
from app.training.codegen import load_pit_panel, spec_to_code

# ── 含未来重述 + 纯未来泄露行的双时态 panel（镜像 test_training_pit_wiring 语义） ──
#
# Row1: ts=2023-12-31 f1=1.0 known_at=2024-01-30 → as_of 2024-02-01 时已知（应见）
# Row2: ts=2023-12-31 f1=1.5 known_at=2024-04-15 → 重述，as_of 2024-02-01 时未知（应挡）
# Row3: ts=2024-06-30 f1=9.0 known_at=2024-09-01 → 纯未来泄露行（应挡）
_AS_OF = "2024-02-01"
_OWNER_USER_ID = "test-owner"


def _bitemporal_panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "f1": 1.0, "f2": 2.0,
             "label": 0.1, "known_at": datetime(2024, 1, 30, tzinfo=UTC)},
            {"ts": datetime(2023, 12, 31, tzinfo=UTC), "symbol": "X", "f1": 1.5, "f2": 2.5,
             "label": 0.2, "known_at": datetime(2024, 4, 15, tzinfo=UTC)},
            {"ts": datetime(2024, 6, 30, tzinfo=UTC), "symbol": "X", "f1": 9.0, "f2": 9.0,
             "label": 9.9, "known_at": datetime(2024, 9, 1, tzinfo=UTC)},
        ]
    )


class _StubResult:
    """train_model 替身返回值：只暴露 _execute 消费的 .to_dict()（无产物→不触 ModelRegistry）。"""

    def __init__(self, n: int) -> None:
        self._n = n

    def to_dict(self) -> dict[str, Any]:
        return {"oos_metrics": {"rows": float(self._n)}, "artifact_path": None}


def _spy_train_model(captured: dict[str, Any]):
    """打桩 train_model：录下它**真正看见的 panel**（= 训练实际消费的数据），不真训练。

    这是最贴泄露面的探针——断言「训练只见 PIT 行」直接验 train_model 收到的 panel，
    不依赖任何 train_model 内部行为；MUT（_pit_view 退回原 panel）必让录到的 panel 含未来行。
    """

    def _spy(spec: Any, panel: pd.DataFrame, *, artifact_dir: Any) -> _StubResult:
        captured["panel"] = panel.copy()
        captured["spec"] = spec
        return _StubResult(len(panel))

    return _spy


def _req(**kw: Any) -> TrainingRequest:
    base: dict[str, Any] = dict(
        name="pit", model="xgboost", task="regression",
        feature_cols=["f1", "f2"], label_col="label",
    )
    base.update(kw)
    return TrainingRequest(**base)


def test_confirmatory_train_requires_as_of_known(tmp_path: Path) -> None:
    svc = TrainingService(root=tmp_path / "training_runs")

    job = svc.train_now(
        _req(use_context="confirmatory_validation"),
        _bitemporal_panel(),
        owner_user_id=_OWNER_USER_ID,
    )

    assert job.status == "failed"
    assert "confirmatory" in (job.error or "")
    assert "as_of_known" in (job.error or "")


def test_confirmatory_train_requires_known_at_axis(tmp_path: Path) -> None:
    svc = TrainingService(root=tmp_path / "training_runs")

    job = svc.train_now(
        _req(
            use_context="confirmatory_validation",
            as_of_known=_AS_OF,
        ),
        _bitemporal_panel().drop(columns=["known_at"]),
        owner_user_id=_OWNER_USER_ID,
    )

    assert job.status == "failed"
    assert "known_at" in (job.error or "")


def test_confirmatory_train_uses_pit_view(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr("app.training.service.train_model", _spy_train_model(captured))
    svc = TrainingService(root=tmp_path / "training_runs")

    job = svc.train_now(
        _req(
            use_context="confirmatory_validation",
            as_of_known=_AS_OF,
        ),
        _bitemporal_panel(),
        owner_user_id=_OWNER_USER_ID,
    )

    assert job.status == "succeeded", job.error
    assert captured["panel"]["f1"].tolist() == [1.0]


# ═══════════ 准则1：train_now ML 进程内路——未来 known_at 行必被挡（look-ahead 守卫） ═══════════


def test_train_now_ml_inprocess_blocks_future_known_at(tmp_path: Path, monkeypatch) -> None:
    """train_now 带 as_of_known → _train_ml 真正训练的 panel 只剩首披 1.0；未来重述/未来行都被挡。

    种坏门（MUT）：若 _pit_view 不透传 as_of_known / 退回原 panel → 9.0、1.5 泄露进训练 → 下面红。
    """
    captured: dict[str, Any] = {}
    monkeypatch.setattr("app.training.service.train_model", _spy_train_model(captured))
    svc = TrainingService(root=tmp_path / "training_runs")

    job = svc.train_now(
        _req(as_of_known=_AS_OF),
        _bitemporal_panel(),
        owner_user_id=_OWNER_USER_ID,
    )

    assert job.status == "succeeded", job.error
    seen = captured["panel"]
    assert sorted(seen["f1"].tolist()) == [1.0]      # 仅截至 2024-02-01 已知的首披
    assert 9.0 not in seen["f1"].tolist()            # 纯未来泄露行被挡
    assert 1.5 not in seen["f1"].tolist()            # 未来重述被挡
    assert "known_at" not in seen.columns            # 折叠后 known_at 不外泄为因子


def test_submit_ml_inprocess_blocks_future_known_at(tmp_path: Path, monkeypatch) -> None:
    """异步 submit 同样全链 PIT（与 train_now 共用 _execute→_train_ml→_pit_view）。"""
    captured: dict[str, Any] = {}
    monkeypatch.setattr("app.training.service.train_model", _spy_train_model(captured))
    svc = TrainingService(root=tmp_path / "training_runs")

    job = svc.submit(
        _req(as_of_known=_AS_OF),
        _bitemporal_panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    svc.wait_all(timeout=60)

    assert svc.get_job(job.job_id).status == "succeeded"
    assert sorted(captured["panel"]["f1"].tolist()) == [1.0]
    assert 9.0 not in captured["panel"]["f1"].tolist()


def test_train_now_ml_inprocess_latest_known_restatement(tmp_path: Path, monkeypatch) -> None:
    """as_of_known 推进到 2024-05-01 → 见修正重述 1.5（取截至该时点最新已知）；未来行 9.0 仍挡。"""
    captured: dict[str, Any] = {}
    monkeypatch.setattr("app.training.service.train_model", _spy_train_model(captured))
    svc = TrainingService(root=tmp_path / "training_runs")

    svc.train_now(
        _req(as_of_known="2024-05-01"),
        _bitemporal_panel(),
        owner_user_id=_OWNER_USER_ID,
    )

    assert sorted(captured["panel"]["f1"].tolist()) == [1.5]
    assert 9.0 not in captured["panel"]["f1"].tolist()


# ═══════════ 准则2：as_of_known=None → 逐字现状不变（向后兼容·additive） ═══════════


def test_train_now_ml_inprocess_none_is_verbatim(tmp_path: Path, monkeypatch) -> None:
    """as_of_known 默认 None → _train_ml 看见逐字原 panel（全 3 行含未来、known_at 列保留）。

    证 additive：新字段缺省时既有 ML 训练一字不改（无折叠、无 round-trip、无丢列）。
    """
    captured: dict[str, Any] = {}
    monkeypatch.setattr("app.training.service.train_model", _spy_train_model(captured))
    svc = TrainingService(root=tmp_path / "training_runs")

    job = svc.train_now(
        _req(),
        _bitemporal_panel(),
        owner_user_id=_OWNER_USER_ID,
    )  # as_of_known 缺省

    assert job.status == "succeeded"
    seen = captured["panel"]
    assert len(seen) == 3                                  # 逐字原 panel：全 3 行
    assert sorted(seen["f1"].tolist()) == [1.0, 1.5, 9.0]  # 含未来行（None=全知视图）
    assert "known_at" in seen.columns                      # 不折叠、不丢列（None 路逐字原 panel）


def test_train_now_ml_inprocess_explicit_none_is_verbatim(tmp_path: Path, monkeypatch) -> None:
    """显式 as_of_known=None 同样逐字（与缺省等价）。"""
    captured: dict[str, Any] = {}
    monkeypatch.setattr("app.training.service.train_model", _spy_train_model(captured))
    svc = TrainingService(root=tmp_path / "training_runs")

    svc.train_now(
        _req(as_of_known=None),
        _bitemporal_panel(),
        owner_user_id=_OWNER_USER_ID,
    )

    assert len(captured["panel"]) == 3


# ═══════════ 准则3：无 known_at 列 → 原样返回（mirror _materialize_sub·不假装过滤·不报错） ═══════════


def test_train_now_ml_inprocess_missing_known_at_is_noop(tmp_path: Path, monkeypatch) -> None:
    """as_of_known 给定但 panel 无 known_at 列 → 无知识轴可过滤 → 全保留（不假装过滤、不崩）。"""
    captured: dict[str, Any] = {}
    monkeypatch.setattr("app.training.service.train_model", _spy_train_model(captured))
    svc = TrainingService(root=tmp_path / "training_runs")
    panel = _bitemporal_panel().drop(columns=["known_at"])

    job = svc.train_now(
        _req(as_of_known=_AS_OF),
        panel,
        owner_user_id=_OWNER_USER_ID,
    )

    assert job.status == "succeeded"
    assert len(captured["panel"]) == 3
    assert sorted(captured["panel"]["f1"].tolist()) == [1.0, 1.5, 9.0]


# ═══════════ 准则4：service 进程内路折叠 == 单一源 load_pit_panel（不另造） ═══════════


def test_train_now_ml_pit_reuses_single_source(tmp_path: Path, monkeypatch) -> None:
    """service 进程内路 train_model 看见的 panel == 直接走 load_pit_panel 单一源点查，逐条一致。

    证训练 service 复用单一 as-of 源（as_of_bound + 折叠语义），不另造平行 PIT 逻辑。
    """
    captured: dict[str, Any] = {}
    monkeypatch.setattr("app.training.service.train_model", _spy_train_model(captured))
    svc = TrainingService(root=tmp_path / "training_runs")
    panel = _bitemporal_panel()

    for aok, expect in [("2024-02-01", [1.0]), ("2024-05-01", [1.5])]:
        captured.clear()
        svc.train_now(
            _req(as_of_known=aok),
            panel,
            owner_user_id=_OWNER_USER_ID,
        )
        via_service = sorted(captured["panel"]["f1"].dropna().tolist())

        ref_path = tmp_path / f"ref_{aok}.parquet"
        panel.to_parquet(ref_path)
        via_single_source = sorted(load_pit_panel(str(ref_path), as_of_known=aok)["f1"].dropna().tolist())

        assert via_service == via_single_source, f"as_of_known={aok}: service≠单一源"
        assert via_service == expect


# ═══════════ TrainingRequest additive 字段 + to_dict 透传（DL/codegen 路的接线） ═══════════


def test_training_request_as_of_known_additive_default_none() -> None:
    """新字段 additive：默认 None；既有构造（不传 as_of_known）逐字不破；to_dict 含该键。"""
    req = TrainingRequest(name="t", model="xgboost", task="regression", feature_cols=["f1"])
    assert req.as_of_known is None
    assert req.to_dict()["as_of_known"] is None

    req2 = TrainingRequest(
        name="t", model="xgboost", task="regression", feature_cols=["f1"], as_of_known=_AS_OF
    )
    assert req2.to_dict()["as_of_known"] == _AS_OF  # 透传到 spec


def test_to_dict_threads_as_of_known_into_dl_codegen() -> None:
    """service 的 DL 路 = spec_to_code(request.to_dict())；证 to_dict 透传后 DL 脚本走 load_pit_panel。

    种坏门：若 to_dict 不透传 as_of_known → 生成脚本退回裸 read_parquet → 旁路守卫 → 下面红。
    """
    req = TrainingRequest(
        name="t", model="lstm", task="regression",
        feature_cols=["f1", "f2"], as_of_known=_AS_OF,
    )
    code = spec_to_code(req.to_dict())
    assert "from app.training.codegen import load_pit_panel" in code
    assert "as_of_known='2024-02-01'" in code
    assert 'pd.read_parquet(os.environ["QUANTBT_PANEL_PATH"])' not in code

    # None → 逐字裸读（向后兼容，DL 脚本不变）
    req_none = TrainingRequest(name="t", model="lstm", task="regression", feature_cols=["f1", "f2"])
    code_none = spec_to_code(req_none.to_dict())
    assert "load_pit_panel" not in code_none
    assert 'pd.read_parquet(os.environ["QUANTBT_PANEL_PATH"])' in code_none


# ═══════════ 端到端真训练（不打桩）：round-trip parquet + load_pit_panel + train_model 全链通 ═══════════


def _big_bitemporal_panel(n_good: int = 200, n_future: int = 20, seed: int = 0) -> pd.DataFrame:
    """足够行数训得动 xgboost 的双时态 panel：n_good 行 known 在 as_of 前、n_future 行 known 在远未来。

    as_of_known=2024-06-01 时：n_good 全留（known_at=2024-01-01）、n_future 全挡（known_at=2025+）。
    """
    rng = np.random.default_rng(seed)
    n = n_good + n_future
    f1 = rng.normal(size=n)
    f2 = rng.normal(size=n)
    y = 0.6 * f1 - 0.4 * f2 + rng.normal(size=n, scale=0.3)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    ts = [base + timedelta(days=i) for i in range(n)]  # 全 distinct（单 symbol 时序）
    early = datetime(2024, 1, 1, tzinfo=UTC)
    far = datetime(2025, 1, 1, tzinfo=UTC)
    known_at = [early if i < n_good else far for i in range(n)]
    return pd.DataFrame({"ts": ts, "f1": f1, "f2": f2, "label": y, "known_at": known_at})


def test_train_now_ml_pit_real_chain_succeeds(tmp_path: Path) -> None:
    """不打桩·真 xgboost：as_of_known 在场 → round-trip 临时 parquet + load_pit_panel + train_model 全链通。

    证 _pit_view 折叠出的 panel 喂真训练器跑得通（产 model.pkl + r2）。折叠内容的精确正确性
    由上面打桩套件守（直验 train_model 看见的 panel）；本测专证三段真链集成不崩。
    """
    svc = TrainingService(root=tmp_path / "training_runs")
    job = svc.train_now(
        _req(n_splits=3, as_of_known="2024-06-01"),
        _big_bitemporal_panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert job.status == "succeeded", job.error
    assert "r2" in job.metrics
    assert (Path(job.artifact_dir) / "model.pkl").exists()


def test_train_now_ml_pit_real_chain_filters_poison(tmp_path: Path) -> None:
    """不打桩·真 xgboost·泄露敏感：未来行带毒(label=NaN)，as_of_known 把它们挡在训练外 → 真训练成功。

    种坏门（MUT·独立于打桩探针）：若 _pit_view 不过滤 → 带毒未来行泄露 → NaN label 喂训练器 →
    job 落 failed → 本测红。证真链上 PIT 过滤确实发生（不只是不崩）。
    """
    panel = _big_bitemporal_panel()
    panel.loc[panel["known_at"] == datetime(2025, 1, 1, tzinfo=UTC), "label"] = np.nan  # 未来行带毒
    svc = TrainingService(root=tmp_path / "training_runs")
    job = svc.train_now(
        _req(n_splits=3, as_of_known="2024-06-01"),
        panel,
        owner_user_id=_OWNER_USER_ID,
    )
    assert job.status == "succeeded", job.error  # 带毒未来行被 PIT 挡 → 训练干净


def test_train_now_ml_real_no_as_of_known_unchanged(tmp_path: Path) -> None:
    """不打桩·真 xgboost·无 as_of_known：既有训练逐字不破（向后兼容·新字段缺省零侵入）。"""
    svc = TrainingService(root=tmp_path / "training_runs")
    job = svc.train_now(
        _req(n_splits=3),
        _big_bitemporal_panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert job.status == "succeeded", job.error
    assert (Path(job.artifact_dir) / "model.pkl").exists()
