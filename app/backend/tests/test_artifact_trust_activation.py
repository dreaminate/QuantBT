"""Artifact 信任门【生产激活】的对抗测试（C-MODELGOV-1 activate · GOAL §15）。

wave-1（test_artifact_trust_gate.py）证了【机制】：store/lib/loader 在 store 单测层拦得住。
本文件证【生产激活】这一层（producer 落盘接 register + service 组合消费侧翻 enforce），**端到端**
（经真 TrainingService / 真 train_model / 真 train_dl，非仅 store 单测）逐条种坏门：

  ① producer 落盘即登记：train_model（ML·.pkl）/ train_dl（DL·.pt·子进程）落盘后 artifact 真进信任账。
  ②（verify#2）enforce 默认 ON 下，组合【系统自产·已登记】模型 → 全链不破（正常加载预测）。
  ③（verify#1/#4·端到端）组合【外来/未登记】artifact → 在 predict_with 的 load 处被拒，job 落 failed。
  ④ opt-in 回退：trust_enforce=False → 外来 artifact 经止血 blocklist 照常加载（向后兼容·中心可回退）。
  ⑤ store_under 落点单一源：producer(artifact_dir.parent) 与消费侧(self._root) 解析到同一 on-disk 账。

注：本卡只跑 scoped；enforce-默认-翻开的【全量】验证由中心在整合点跑（见 done TASK.md 诚实标注）。
"""

from __future__ import annotations

import os

# 必须在任何 torch 链路 import 前设（主进程零 torch 约定；与 _predict_dl / wave-1 测试同策防 OMP 崩溃）。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import pickle  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app.training import TrainingRequest, TrainingService, artifact_trust  # noqa: E402
from app.training.artifact_trust import ArtifactTrustError  # noqa: E402


_OWNER_USER_ID = "test-owner"


@pytest.fixture(autouse=True)
def _reset_global_trust():
    """复位进程级默认策略（本卡不用 configure_default_trust，纯防跨文件全局态泄漏污染基线）。"""
    artifact_trust.reset_default_trust()
    yield
    artifact_trust.reset_default_trust()


def _panel(n_syms: int = 2, n_days: int = 60, *, label: bool = True) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows: list[dict] = []
    for s in range(n_syms):
        for t in range(n_days):
            row = {"symbol": f"s{s}", "ts": t, "f1": rng.normal(), "f2": rng.normal()}
            if label:
                row["label"] = rng.normal()
            rows.append(row)
    return pd.DataFrame(rows)


def _req(name: str, model: str = "lgbm", **kw) -> TrainingRequest:
    base = dict(name=name, model=model, task="regression", feature_cols=["f1", "f2"], n_splits=4)
    base.update(kw)
    return TrainingRequest(**base)  # type: ignore[arg-type]


# ══ ① producer 落盘即登记（地基：① 不彻底则 enforce 破基线） ════════════════════
def test_ml_producer_registers_artifact_on_save(tmp_path: Path):
    """种坏门反面：train_model 落盘 model.pkl 后，artifact 必已登记进 store_under(artifact_dir.parent)。"""
    from app.models.training import ModelSpec, train_model

    job_dir = tmp_path / "job_ml"
    train_model(
        ModelSpec(task="regression", model="lgbm", feature_cols=["f1", "f2"], n_splits=4),
        _panel(),
        artifact_dir=job_dir,
    )
    pkl = job_dir / "model.pkl"
    assert pkl.exists()
    store = artifact_trust.store_under(job_dir.parent)  # = tmp_path/_artifact_trust（与消费侧同源）
    rec = store.verify(pkl)
    assert rec is not None, "ML producer 落盘后未登记 → enforce 会拒掉合法自产 artifact（破基线）"
    assert rec.producer_kind == "ml_train"
    assert rec.artifact_kind == "pickle"
    ok, issues = store.verify_chain()
    assert ok, issues


def test_dl_producer_registers_artifact_on_save(tmp_path: Path):
    """种坏门反面：train_dl（直调·in-process）落盘 model.pt 后，artifact 必已登记（DL 路 ① 不漏）。"""
    pytest.importorskip("torch")
    os.environ.setdefault("QUANTBT_FORCE_DEVICE", "cpu")
    from app.models.dl.trainer import train_dl

    job_dir = tmp_path / "job_dl"
    res = train_dl(
        _panel(),
        arch="lstm",
        feature_cols=["f1", "f2"],
        label_col="label",
        job_dir=job_dir,
        task="regression",
        hyperparams={"max_epochs": 2, "lookback": 10, "hidden_size": 8, "batch_size": 32},
    )
    pt = Path(res["artifact_path"])
    assert pt.name == "model.pt" and pt.exists()
    store = artifact_trust.store_under(job_dir.parent)
    rec = store.verify(pt)
    assert rec is not None, "DL producer 落盘后未登记 → enforce 会拒掉合法自产 .pt（破基线）"
    assert rec.producer_kind == "dl_train"
    assert rec.artifact_kind == "torch"


# ══ ② verify#2 · enforce 默认 ON 组合【已登记】模型 → 全链不破 ════════════════════
def test_service_compose_registered_under_enforce_default_on(tmp_path: Path):
    """正路径（默认 enforce ON）：A 系统自产→登记；B 组合 A 的输出当特征 → 加载放行、B 训练成功。"""
    svc = TrainingService(root=tmp_path / "tr", timeout=300)  # enforce 默认 ON
    assert svc._trust_enforce is True  # 默认翻开（生产激活）
    a = svc.train_now(
        _req("A", model="xgboost", hyperparams={"n_estimators": 30}),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert a.status == "succeeded", a.error
    artifact = str(Path(a.artifact_dir) / "model.pkl")
    b = svc.train_now(
        _req("B", model="lgbm", input_models=[
            {"artifact_path": artifact, "feature_cols": ["f1", "f2"], "as_col": "a_pred"}
        ]),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert b.status == "succeeded", b.error  # enforce ON 不误伤【已登记】自产模型（含 xgboost 走白名单）


def test_service_compose_registered_dl_under_enforce(tmp_path: Path):
    """正路径（DL·跨进程）：train_dl 子进程登记 .pt；主进程组合消费侧 enforce 读同账放行 → B 成功。"""
    pytest.importorskip("torch")
    os.environ.setdefault("QUANTBT_FORCE_DEVICE", "cpu")
    svc = TrainingService(root=tmp_path / "tr", timeout=600)  # enforce 默认 ON
    dl = svc.train_now(
        _req("dl", model="lstm", label_col="label",
             hyperparams={"max_epochs": 2, "lookback": 10, "hidden_size": 8, "batch_size": 32}),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert dl.status == "succeeded", dl.error
    pt = str(Path(dl.artifact_dir) / "model.pt")
    # 主进程消费侧读子进程登记的记录（跨进程 on-disk 账）→ 放行
    assert artifact_trust.store_under(svc._root).is_trusted(pt)
    b = svc.train_now(
        _req("compose-dl", model="lgbm", input_models=[
            {"artifact_path": pt, "feature_cols": ["f1", "f2"], "as_col": "lstm_pred"}
        ]),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert b.status == "succeeded", b.error


# ══ ③ verify#1/#4 · 外来/未登记 artifact 端到端被拒（非仅 store 单测） ═══════════════
def test_service_compose_external_pkl_refused_end_to_end(tmp_path: Path):
    """种坏门：把【外来·未登记】.pkl 当 input_model 喂真 service（enforce ON）→ job failed·ArtifactTrustError。

    端到端证据：拒发生在 service→predict_with→load_model 的真实组合链路里，不是 store 单测自说自话。
    """
    svc = TrainingService(root=tmp_path / "tr", timeout=300)  # enforce 默认 ON
    from sklearn.linear_model import LinearRegression

    ext = tmp_path / "external_model.pkl"  # 非本系统 producer 产出 → 从未 register
    with ext.open("wb") as fh:
        pickle.dump(LinearRegression().fit(np.zeros((4, 2)), np.zeros(4)), fh)
    b = svc.train_now(
        _req("evil", model="lgbm", input_models=[
            {"artifact_path": str(ext), "feature_cols": ["f1", "f2"], "as_col": "x"}
        ]),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert b.status == "failed"
    assert "ArtifactTrust" in (b.error or ""), b.error  # 未登记 full-sha256 不命中 → 拒


def test_service_compose_tampered_registered_refused(tmp_path: Path):
    """种坏门（tamper-evident·端到端）：自产模型登记后被改一字节 → full-sha256 变 → 组合时被拒。"""
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    a = svc.train_now(_req("A"), _panel(), owner_user_id=_OWNER_USER_ID)
    assert a.status == "succeeded", a.error
    pkl = Path(a.artifact_dir) / "model.pkl"
    with pkl.open("ab") as fh:  # 篡改：追加一字节（绑定的是内容 hash，不是路径）
        fh.write(b"\x00")
    b = svc.train_now(
        _req("B", input_models=[
            {"artifact_path": str(pkl), "feature_cols": ["f1", "f2"], "as_col": "a_pred"}
        ]),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert b.status == "failed"
    assert "ArtifactTrust" in (b.error or ""), b.error


# ══ ④ opt-in 回退：trust_enforce=False → 外来 artifact 经止血 blocklist 照常加载 ═══════
def test_service_optin_off_loads_external_backward_compat(tmp_path: Path):
    """中心可回退点：trust_enforce=False（opt-in）→ 外来 .pkl 经止血 blocklist 加载，组合成功（向后兼容）。

    证明 enforce 是【可逆开关】，不是写死：默认 ON 给安全，回退 OFF 给向后兼容（profile 松紧由中心/用户拍）。
    """
    svc = TrainingService(root=tmp_path / "tr", timeout=300, trust_enforce=False)
    assert svc._trust_enforce is False
    from sklearn.linear_model import LinearRegression

    ext = tmp_path / "external_model.pkl"
    with ext.open("wb") as fh:
        pickle.dump(LinearRegression().fit(np.zeros((4, 2)), np.arange(4.0)), fh)
    b = svc.train_now(
        _req("optin", model="lgbm", input_models=[
            {"artifact_path": str(ext), "feature_cols": ["f1", "f2"], "as_col": "x"}
        ]),
        _panel(),
        owner_user_id=_OWNER_USER_ID,
    )
    assert b.status == "succeeded", b.error  # opt-in：外来仍经 blocklist 加载（不查登记）


# ══ ⑤ store_under 落点单一源（producer 与消费侧解析到同一账） ═════════════════════
def test_store_under_single_source_path_convention(tmp_path: Path):
    """producer 的 store_under(artifact_dir.parent) 与消费侧 store_under(root) 落到【同一】 JSONL。"""
    root = tmp_path / "tr"
    job_dir = root / "job-xyz"  # = service job_dir(<root>/<job_id>) 布局
    producer_store = artifact_trust.store_under(job_dir.parent)
    consumer_store = artifact_trust.store_under(root)
    assert producer_store._path == consumer_store._path
    assert producer_store._path == root / "_artifact_trust" / "artifact_trust.jsonl"
    # 落点目录名 = 约定常量（单一源）
    assert artifact_trust.TRUST_STORE_DIRNAME == "_artifact_trust"
