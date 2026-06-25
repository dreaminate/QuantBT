"""卡 554cdcf2 · 监控绩效轴真闭环 对抗测试（扩展不替换；接在 test_monitor_closure / test_drift_detectors 后）。

残余三层 + 治理红线（M-AUTHORITY=A1）的可证伪门（种已知坏门必抓）：
1. 断接线（残余①）：`run_weekly_monitor_pass` 不传 `perf_provider` → 绩效轴退役**不触发**；传了 → 触发
   （证 4 个绩效 drift 检测器接 `monitor_tick.perf_drift` 真生效，非套套逻辑）。
2. 范畴红线（A1·命门）：监控路径**绝不**把 gate/pbo/dsr verdict 喂进 `monitor_tick`（机器钉死）；
   特征轴 PSI 即便经 `perf_provider` 也被类型层拒（绝不退役）。
3. rolling-PSR **不暴露 n_trials**（种传 n_trials → 退化 DSR → 运行期红）。
4. 观测落盘（残余③）：写 2 周负观测 → 模拟重启（重载 manager）→ 第 2 周仍触发 RETIRED；
   反面 MUT：纯内存默认 → 重启丢观测 → 不退役（证持久化真 load-bearing）。
另：残余② 周度 IC 重算（复用 `compute_ic_report`）从真面板产观测、无面板=None（不伪造，诚实优先）。
"""

from __future__ import annotations

import inspect

import numpy as np
import polars as pl
import pytest

from app.factor_factory.lifecycle import (
    FactorObservation,
    JsonlObservationStore,
    LifecycleManager,
    LifecycleThresholds,
)
from app.factor_factory.registry import FactorRegistry
from app.monitor.drift import PerfDriftSignal, population_stability_index, rolling_psr_drift
from app.monitor.production import (
    build_ic_provider,
    build_returns_perf_drift_provider,
    run_weekly_monitor_pass,
)

# 零 edge 收益 → rolling-PSR 跌破 floor=0.90（实盘 edge 显著性流失），与既有 drift 测试同范式。
_BAD_RETURNS = np.random.default_rng(13).standard_normal(252) * 0.01
# 正 edge 收益 → PSR ok（不退役）。
_GOOD_RETURNS = np.random.default_rng(14).standard_normal(252) * 0.01 + 0.0015


def _warning_factor(tmp_path, fname="f.json", *, store=None):
    """种一个 WARNING 因子 + 绑定 manager（warning_persist_weeks=2：连续 2 周负观测即 RETIRED）。"""
    reg = FactorRegistry(tmp_path / fname)
    factor = reg.register("z", "close")
    reg.update_state("z", factor.version, "WARNING")
    mgr = LifecycleManager(reg, thresholds=LifecycleThresholds(warning_persist_weeks=2), store=store)
    return reg, mgr, factor.version


# ============================================================================
# 残余① + 验收①：绩效轴接线 + 断接线（perf 轴真接 monitor_tick.perf_drift）
# ============================================================================


def test_perf_provider_wired_drives_retire_single_prov(tmp_path):
    """绩效轴接线：perf_provider（崩溃收益 → rolling-PSR breach）连续 2 周 → 自动 RETIRED + 单一 PROV（A1）。"""
    reg, mgr, v = _warning_factor(tmp_path)
    perf_provider = build_returns_perf_drift_provider(lambda fid, ver: _BAD_RETURNS)

    a1 = run_weekly_monitor_pass(reg, mgr, [], perf_provider=perf_provider)  # 空 audit → 无成本轴
    assert a1[0].perf_drift_breach and a1[0].perf_drift_detector == "rolling_psr"
    assert reg.get("z").lifecycle_state == "WARNING"  # 差 1 周
    a2 = run_weekly_monitor_pass(reg, mgr, [], perf_provider=perf_provider)
    assert a2[0].lifecycle_event is not None and a2[0].lifecycle_event.to_state == "RETIRED"
    assert reg.get("z").lifecycle_state == "RETIRED"
    assert len(mgr.events("z")) == 1  # 单一 PROV（A1 权威单发）


def test_severing_perf_provider_leaves_warning(tmp_path):
    """**断接线（核心牙）**：不传 perf_provider + 空 audit → 绩效轴退役永不触发 → 停 WARNING。

    与上一测对照证明：退役**只能**由接上的 perf 轴信号驱动（去掉接线即不退役，非套套逻辑）。
    若把 perf_drift 硬编进 run_weekly_monitor_pass（绕过 provider），本测会误退役 → 红，故 MUT 有牙。
    """
    reg, mgr, v = _warning_factor(tmp_path)
    run_weekly_monitor_pass(reg, mgr, [])  # 无 perf_provider、无成本漂移
    run_weekly_monitor_pass(reg, mgr, [])
    assert mgr.history("z", v) == []  # 零观测
    assert reg.get("z").lifecycle_state == "WARNING"  # 断接线 → 不退役


def test_perf_drift_passed_to_tick_only_when_provider_present(tmp_path, monkeypatch):
    """接线证伪：有 perf_provider 时 monitor_tick 实参才含 perf_drift；无则不含（语义=无真源不喂）。"""
    import app.monitor.production as prod

    captured: list[dict] = []
    real_tick = prod.monitor_tick

    def _spy(manager, fid, ver, **kwargs):
        captured.append(dict(kwargs))
        return real_tick(manager, fid, ver, **kwargs)

    monkeypatch.setattr(prod, "monitor_tick", _spy)

    reg, mgr, v = _warning_factor(tmp_path)
    run_weekly_monitor_pass(reg, mgr, [])  # 无 provider
    assert captured and all("perf_drift" not in kw for kw in captured)

    captured.clear()
    perf_provider = build_returns_perf_drift_provider(lambda fid, ver: _BAD_RETURNS)
    run_weekly_monitor_pass(reg, mgr, [], perf_provider=perf_provider)
    assert captured and all("perf_drift" in kw for kw in captured)
    assert all(kw["perf_drift"].axis == "performance" for kw in captured)


# ============================================================================
# 验收②：范畴红线 M-AUTHORITY=A1（绝不喂 gate/pbo/dsr，特征轴 PSI 也进不来）
# ============================================================================


def test_weekly_pass_with_perf_provider_never_feeds_gate_verdict(tmp_path, monkeypatch):
    """范畴红线（运行时·机器钉死）：接上 perf_provider 后，monitor_tick 实参仍只在绩效/成本轴白名单内。"""
    import app.monitor.production as prod

    captured: list[dict] = []
    real_tick = prod.monitor_tick

    def _spy(manager, fid, ver, **kwargs):
        captured.append(dict(kwargs))
        return real_tick(manager, fid, ver, **kwargs)

    monkeypatch.setattr(prod, "monitor_tick", _spy)
    reg, mgr, v = _warning_factor(tmp_path)
    perf_provider = build_returns_perf_drift_provider(lambda fid, ver: _BAD_RETURNS)
    run_weekly_monitor_pass(reg, mgr, [], perf_provider=perf_provider)
    assert captured
    for kw in captured:
        for forbidden in ("verdict", "gate_verdict", "pbo", "dsr", "gate", "overfit"):
            assert forbidden not in kw, f"传给 monitor_tick 的实参含禁项 {forbidden}（晋级闸→退役=范畴错误）"
        # 白名单：仅绩效/成本轴（observation 周期 IC / drift_pct 成本 / perf_drift 绩效漂移）。
        assert set(kw).issubset({"observation", "drift_pct", "drift_threshold", "perf_drift"})


def test_perf_provider_and_builders_forbid_gate_verdict_params():
    """签名回归：接线全链路（run_weekly_monitor_pass + 两个 builder）绝不接 gate verdict。"""
    for fn in (run_weekly_monitor_pass, build_returns_perf_drift_provider, build_ic_provider):
        params = set(inspect.signature(fn).parameters)
        for forbidden in ("verdict", "gate_verdict", "pbo", "dsr", "gate", "overfit"):
            assert forbidden not in params, f"{fn.__name__} 不得接 {forbidden}"


def test_feature_axis_psi_cannot_enter_via_perf_provider(tmp_path):
    """命门 D2（最关键）：即便 perf_provider 试图返回特征轴 PSI 诊断，monitor_tick 类型层 raise → 绝不退役。

    种「PSI 剧烈漂移」的 FeatureDriftDiagnosis 当 perf_provider 输出 → run_weekly_monitor_pass 必 TypeError，
    因 monitor_tick 只认 axis=="performance"。证明新接缝不会成为特征轴绕过退役矩阵的后门。
    """
    reg, mgr, v = _warning_factor(tmp_path)
    psi_diag = population_stability_index(
        np.random.default_rng(15).standard_normal(500),
        np.random.default_rng(16).standard_normal(500) + 3.0,
    )
    assert psi_diag.severity == "major" and psi_diag.axis == "feature"

    def _smuggle_feature_axis(fid, ver):  # type: ignore[return-value]
        return psi_diag  # 故意违反 PerfDriftProvider 契约（应只返 PerfDriftSignal）

    with pytest.raises(TypeError, match="特征轴|performance"):
        run_weekly_monitor_pass(reg, mgr, [], perf_provider=_smuggle_feature_axis)  # type: ignore[arg-type]
    assert reg.get("z").lifecycle_state == "WARNING"  # 绝未因特征漂移退役
    assert mgr.history("z", v) == []


# ============================================================================
# 验收③：rolling-PSR 不暴露 n_trials（暴露即退化 DSR=晋级闸，违 A1）
# ============================================================================


def test_rolling_psr_runtime_rejects_n_trials_kwarg():
    """运行期 MUT：种「传 n_trials」→ rolling-PSR 必拒（不接 DSR 多重检验通缩参数）。"""
    with pytest.raises(TypeError):
        rolling_psr_drift(_BAD_RETURNS, n_trials=10)  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        rolling_psr_drift(_BAD_RETURNS, var_sr_hat=0.5)  # type: ignore[call-arg]


def test_perf_provider_builder_forbids_dsr_deflation_params():
    """builder 签名亦绝不暴露 n_trials/var_sr_hat（不给 DSR 通缩开后门）。"""
    params = set(inspect.signature(build_returns_perf_drift_provider).parameters)
    for forbidden in ("n_trials", "var_sr_hat", "trials", "n_trial"):
        assert forbidden not in params


def test_perf_provider_emits_only_performance_axis(tmp_path):
    """provider 输出（breach / ok）恒 axis=="performance" 且 detector="rolling_psr"（主告警）。"""
    breach_provider = build_returns_perf_drift_provider(lambda fid, ver: _BAD_RETURNS)
    ok_provider = build_returns_perf_drift_provider(lambda fid, ver: _GOOD_RETURNS)
    bad = breach_provider("z", 1)
    good = ok_provider("z", 1)
    assert bad is not None and bad.axis == "performance" and bad.detector == "rolling_psr" and bad.breach
    assert good is not None and good.axis == "performance" and not good.breach


def test_perf_provider_confirmation_mode_is_load_bearing():
    """确证模式（用户方法学旋钮）：PSR breach 但 CUSUM/PH 不确证 → require_confirmation=True 时不 breach。

    收益=零均值噪声（PSR breach：edge 不显著）但与冻结基准 μ0=0 无下移 → CUSUM/PH 不 breach。
    默认（require_confirmation=False）= PSR 主告警单独触发；开确证 → 须 CUSUM/PH 任一附议。
    """
    returns = lambda fid, ver: _BAD_RETURNS  # noqa: E731
    baseline = lambda fid, ver: (0.0, float(np.std(_BAD_RETURNS, ddof=1)))  # noqa: E731  μ0≈样本均值→无下移

    primary = build_returns_perf_drift_provider(returns, baseline)("z", 1)
    confirmed = build_returns_perf_drift_provider(returns, baseline, require_confirmation=True)("z", 1)
    assert primary is not None and primary.breach  # 默认：PSR 主告警单独触发
    assert confirmed is not None and not confirmed.breach  # 确证模式：CUSUM/PH 未附议 → 不 breach
    assert confirmed.detail.get("psr_breach_unconfirmed") is True
    # 确证信息确实被求值并落 detail（4 个检测器真在生产被求值）。
    assert "cusum" in confirmed.detail["confirmatory"] and "page_hinkley" in confirmed.detail["confirmatory"]


# ============================================================================
# 验收④：观测落盘跨重启（残余③）
# ============================================================================


def test_observation_persists_across_restart_triggers_retire(tmp_path):
    """**核心牙**：2 周负观测分跨「重启」→ 第 2 周仍 RETIRED（证持久化真生效）。"""
    obs_path = tmp_path / "obs.jsonl"
    reg_path = tmp_path / "factors.json"

    # —— 进程 1：种 WARNING + 第 1 周负观测（落盘）——
    reg1 = FactorRegistry(reg_path)
    f = reg1.register("z", "close")
    reg1.update_state("z", f.version, "WARNING")
    mgr1 = LifecycleManager(
        reg1, thresholds=LifecycleThresholds(warning_persist_weeks=2), store=JsonlObservationStore(obs_path)
    )
    perf_provider = build_returns_perf_drift_provider(lambda fid, ver: _BAD_RETURNS)
    run_weekly_monitor_pass(reg1, mgr1, [], perf_provider=perf_provider)
    assert reg1.get("z").lifecycle_state == "WARNING"  # 差 1 周
    assert obs_path.exists()

    # —— 模拟重启：全新 registry + manager 从同一落盘重建（内存清空）——
    reg2 = FactorRegistry(reg_path)  # 从 JSON 重载 WARNING 状态
    assert reg2.get("z").lifecycle_state == "WARNING"
    mgr2 = LifecycleManager(
        reg2, thresholds=LifecycleThresholds(warning_persist_weeks=2), store=JsonlObservationStore(obs_path)
    )
    assert len(mgr2.history("z", f.version)) == 1  # 第 1 周观测从落盘续上

    # —— 进程 2：第 2 周负观测 → 满 2 周连续负 → RETIRED ——
    a2 = run_weekly_monitor_pass(reg2, mgr2, [], perf_provider=perf_provider)
    assert a2[0].lifecycle_event is not None and a2[0].lifecycle_event.to_state == "RETIRED"
    assert reg2.get("z").lifecycle_state == "RETIRED"


def test_in_memory_default_loses_observations_across_restart(tmp_path):
    """反面 MUT：纯内存默认（无 store）→ 重启丢第 1 周观测 → 第 2 周不退役（证持久化是 load-bearing）。"""
    reg_path = tmp_path / "factors.json"
    reg1 = FactorRegistry(reg_path)
    f = reg1.register("z", "close")
    reg1.update_state("z", f.version, "WARNING")
    mgr1 = LifecycleManager(reg1, thresholds=LifecycleThresholds(warning_persist_weeks=2))  # 无 store
    perf_provider = build_returns_perf_drift_provider(lambda fid, ver: _BAD_RETURNS)
    run_weekly_monitor_pass(reg1, mgr1, [], perf_provider=perf_provider)

    reg2 = FactorRegistry(reg_path)
    mgr2 = LifecycleManager(reg2, thresholds=LifecycleThresholds(warning_persist_weeks=2))  # 重启：内存空
    assert mgr2.history("z", f.version) == []  # 第 1 周观测丢失（无落盘）
    a2 = run_weekly_monitor_pass(reg2, mgr2, [], perf_provider=perf_provider)
    assert a2[0].lifecycle_event is None  # 仅 1 周负观测 → 不满 2 周 → 不退役（bug 若无落盘则复发）
    assert reg2.get("z").lifecycle_state == "WARNING"


def test_env_var_enables_persistence_without_explicit_store(tmp_path, monkeypatch):
    """生产接缝：env `QUANTBT_LIFECYCLE_OBS_STORE` 置路径 → `LifecycleManager(reg)`（不显式传 store）自动落盘。

    生产单例 `main.FACTOR_LIFECYCLE = LifecycleManager(FACTOR_REGISTRY)` 不带 store 且本卡绝不碰 main.py——
    故落盘只能经此 env 接通；默认空=纯内存（不破基线）。
    """
    obs_path = tmp_path / "env_obs.jsonl"
    monkeypatch.setenv("QUANTBT_LIFECYCLE_OBS_STORE", str(obs_path))
    reg = FactorRegistry(tmp_path / "f.json")
    f = reg.register("z", "close")
    mgr = LifecycleManager(reg)  # 不显式传 store → 经 env 自动接 JsonlObservationStore
    mgr.record_observation(
        FactorObservation("z", f.version, "2026-06-26T00:00:00+00:00", 0, -1.0, -1.0, -1.0, 0.0)
    )
    assert obs_path.exists()
    # 同一落盘重建 → 观测续上（跨重启）。
    mgr2 = LifecycleManager(reg)
    assert len(mgr2.history("z", f.version)) == 1


def test_in_memory_default_when_env_unset(tmp_path, monkeypatch):
    """默认关：env 未置 → 纯内存、不写任何文件（历史行为逐位一致，不破基线）。"""
    monkeypatch.delenv("QUANTBT_LIFECYCLE_OBS_STORE", raising=False)
    reg = FactorRegistry(tmp_path / "f.json")
    f = reg.register("z", "close")
    mgr = LifecycleManager(reg)
    mgr.record_observation(
        FactorObservation("z", f.version, "2026-06-26T00:00:00+00:00", 0, -1.0, -1.0, -1.0, 0.0)
    )
    assert not any(tmp_path.glob("*.jsonl"))  # 无落盘文件


def test_jsonl_store_roundtrip_fidelity(tmp_path):
    """JsonlObservationStore append→load_all 保真（factor_id/version/ic_mean/extra 逐字段还原）。"""
    store = JsonlObservationStore(tmp_path / "rt.jsonl")
    obs = FactorObservation("z", 2, "2026-06-26T00:00:00+00:00", 5, -0.7, -1.0, -0.6, 0.0,
                            extra={"source": "drift:rolling_psr", "statistic": 0.42})
    store.append(obs)
    loaded = store.load_all()
    assert list(loaded.keys()) == [("z", 2)]
    got = loaded[("z", 2)][0]
    assert got.ic_mean == -0.7 and got.horizon == 5
    assert got.extra["source"] == "drift:rolling_psr" and got.extra["statistic"] == 0.42


# ============================================================================
# 残余②：周度 IC 重算真源（复用 compute_ic_report）+ 诚实（无真源=None，绝不伪造）
# ============================================================================


def _ic_panel() -> pl.DataFrame:
    """造一份正 IC 因子面板：10 截面 × 8 标的，forward_return ≈ 0.5·factor_value + 噪声（强正 IC）。"""
    rng = np.random.default_rng(7)
    rows = []
    for t in range(10):
        for s in range(8):
            fval = float(s - 3.5 + 0.1 * t)  # 截面内随标的变化（corr 可算）
            fwd = 0.5 * fval + float(rng.standard_normal()) * 0.05
            rows.append({"ts": f"2026-06-{t + 1:02d}", "symbol": f"s{s}",
                         "factor_value": fval, "forward_return_h5": fwd})
    return pl.DataFrame(rows)


def test_ic_provider_builds_observation_from_panel_reusing_compute_ic_report():
    """残余②：build_ic_provider 从真面板产周期观测（复用 compute_ic_report·不另造），ic_mean 与口径一致。"""
    from app.factor_factory.ic import compute_ic_report

    panel = _ic_panel()
    expected = compute_ic_report(panel, "factor_value", horizon=5)
    provider = build_ic_provider(lambda fid, ver: panel)
    obs = provider("z", 1)
    assert obs is not None
    assert obs.ic_mean == pytest.approx(expected.ic_mean)
    assert obs.rank_ic_mean == pytest.approx(expected.rank_ic_mean)
    assert obs.ic_mean > 0.5  # 强正 IC
    assert obs.extra["source"] == "weekly_ic_recompute"
    assert obs.extra["sample_count"] == expected.sample_count
    # sample_t = Newey-West HAC t（诚实显著性口径），None→0.0、绝不虚高。
    assert obs.sample_t == (expected.ic_tstat_nw if expected.ic_tstat_nw is not None else 0.0)


def test_ic_provider_none_when_no_panel_no_fabrication():
    """诚实：panel_source 返回 None（生产无真实周期面板）→ provider 返回 None（绝不伪造 IC）。"""
    provider = build_ic_provider(lambda fid, ver: None)
    assert provider("z", 1) is None


def test_weekly_pass_default_fabricates_no_perf_or_ic(tmp_path):
    """诚实总闸：默认（无 ic_provider / 无 perf_provider / 空 audit）→ 零观测、不喂 perf_drift、不误退役。"""
    reg, mgr, v = _warning_factor(tmp_path)
    actions = run_weekly_monitor_pass(reg, mgr, [])
    assert len(actions) == 1
    assert not actions[0].drift_breach and not actions[0].perf_drift_breach
    assert mgr.history("z", v) == []  # 无真源 → 不造任何观测
    assert reg.get("z").lifecycle_state == "WARNING"
