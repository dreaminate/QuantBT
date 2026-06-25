"""Artifact 完整信任门的【对抗式】测试（GOAL §15·C-MODELGOV-1-full·致命红线第二刀）。

把 artifact 安全从「止血」(blocklist + weights_only)做成「完整信任门」后,本测对四条可证伪验收
逐条种【已知坏门】证明拦得住,且正路径不误伤:

  #1 非系统自产(producer-run 未登记 / full-sha256 不命中)→ 拒加载。
  #2 pickle 类白名单【非黑名单】:不在白名单的【良性新类】仍被拒(证明非靠 blocklist 漏新 gadget)。
  #3 DL 走 safe tensors + JSON config;.pt 含非安全类型【绝不静默回落 weights_only=False】,显式 raise。
  #4 系统自产且 hash 命中 → 正常加载(向后兼容·不误伤真实 sklearn/lightgbm/DL 模型)。

注:止血层(_RestrictedUnpickler blocklist + weights_only)的对抗测在 test_model_artifact_safety.py,
本文件测【其上】的信任门;两者并存(扩展不替换)。
"""

from __future__ import annotations

import os

# 必须在任何 torch 链路 import 前设(主进程零 torch 约定;_predict_dl 同样这么做防 OMP 崩溃)。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import json  # noqa: E402
import pickle  # noqa: E402
import sys  # noqa: E402
from decimal import Decimal  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app.lineage.ids import content_hash  # noqa: E402
from app.training import artifact_trust  # noqa: E402
from app.training.artifact_trust import (  # noqa: E402
    ArtifactTrustError,
    ArtifactTrustStore,
    TrustPolicy,
)
from app.training.lib import (  # noqa: E402
    _AllowlistUnpickler,
    _allowlist_pickle_load,
    _RestrictedUnpickler,
    load_model,
    predict_with,
)


# ── 测试夹具 / 辅助 ──────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _reset_global_trust():
    """每个用例前后复位进程级默认策略,避免全局信任态跨用例泄漏(防 configure_default_trust 污染基线)。"""
    artifact_trust.reset_default_trust()
    yield
    artifact_trust.reset_default_trust()


def _dump_pickle(obj, path: Path) -> Path:
    with open(path, "wb") as fh:
        pickle.dump(obj, fh)
    return path


def _store(tmp_path: Path) -> ArtifactTrustStore:
    return ArtifactTrustStore(tmp_path / "trust")


def _fit_linreg():
    from sklearn.linear_model import LinearRegression

    X = np.arange(20, dtype=float).reshape(10, 2)
    y = X[:, 0] * 2.0 + X[:, 1]
    return LinearRegression().fit(X, y)


def _make_pt_ckpt(path: Path, *, lookback: int = 4) -> Path:
    """造一个最小但【合法】的 DL .pt（与 trainer.py 产出 shape 一致），供正/负路径用。"""
    import torch

    from app.models.dl.architectures import build_network

    feats = ["f1", "f2"]
    net_hp = {"hidden_size": 8}
    net = build_network("lstm", len(feats), 1, **net_hp)
    ckpt = {
        "arch": "lstm",
        "state_dict": net.state_dict(),
        "config": {
            "feature_cols": feats,
            "label_col": "label",
            "task": "regression",
            "n_outputs": 1,
            "lookback": lookback,
            "net_hp": net_hp,
            "classes": None,
            "symbol_col": "symbol",
        },
    }
    torch.save(ckpt, path)
    return path


def _panel(n_syms: int = 2, n_days: int = 12) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []
    for s in range(n_syms):
        for t in range(n_days):
            rows.append({"symbol": f"s{s}", "ts": t, "f1": rng.normal(), "f2": rng.normal()})
    return pd.DataFrame(rows)


# 模块级良性类（test #7 用）：weights_only=True 不认（非安全全局）→ torch 拒；weights_only=False 可重建。
class _NonSafeForWeightsOnly:
    def __init__(self) -> None:
        self.flag = "reconstructed"


# ══ 验收 #1 · 非系统自产 / 未登记 / 被改 → 拒加载 ════════════════════════════
def test_unregistered_pickle_refused_under_enforce(tmp_path: Path):
    """种坏门:伪造一个【未登记】artifact 喂 load_model（enforce）→ 必 raise。"""
    store = _store(tmp_path)
    p = _dump_pickle({"coef": np.array([1.0, 2.0]), "name": "x"}, tmp_path / "forged.pkl")
    with pytest.raises(ArtifactTrustError):
        load_model(p, trust=store)  # 未 register → full-sha256 不命中 → 拒


def test_tampered_after_register_refused(tmp_path: Path):
    """种坏门:登记后篡改一个字节 → full-sha256 变 → 拒（tamper-evident，绑定的是内容不是路径）。"""
    store = _store(tmp_path)
    p = _dump_pickle({"w": np.array([1.0])}, tmp_path / "m.pkl")
    store.register(p, producer_run="run-1", producer_kind="ml_train")
    load_model(p, trust=store)  # 登记后正常（基线对照）
    with p.open("ab") as fh:  # 篡改:追加一字节
        fh.write(b"\x00")
    with pytest.raises(ArtifactTrustError):
        load_model(p, trust=store)


def test_unregistered_pt_refused_under_enforce(tmp_path: Path):
    """DL 分支同样过门:未登记 .pt 喂 predict_with（enforce）→ 在加载前就 raise。"""
    store = _store(tmp_path)
    p = _make_pt_ckpt(tmp_path / "forged.pt")
    panel = _panel()
    with pytest.raises(ArtifactTrustError):
        predict_with(p, panel, ["f1", "f2"], trust=store)


def test_enforce_without_store_refuses(tmp_path: Path):
    """enforce=True 但无 store（无登记面可查）→ 拒（no silent pass，绝不在该开门时静默放行）。"""
    p = _dump_pickle({"w": 1}, tmp_path / "x.pkl")
    with pytest.raises(ArtifactTrustError):
        load_model(p, trust=TrustPolicy(store=None, enforce=True))


# ══ 验收 #2 · 白名单【非黑名单】:不在白名单的良性新类 → 拒 ════════════════════
def test_allowlist_refuses_unlisted_benign_class(tmp_path: Path):
    """命门:decimal.Decimal 是【良性】类（blocklist 抓不到它）,但 root 'decimal' 不在白名单 → 仍拒。

    这证明拦截【非】靠 blocklist 漏新 gadget,而是真·白名单（新类默认拒）。
    """
    p = _dump_pickle(Decimal("1.5"), tmp_path / "dec.pkl")
    # 止血 blocklist 放行 Decimal（证明它良性、blocklist 抓不到）：
    with p.open("rb") as fh:
        assert _RestrictedUnpickler(fh).load() == Decimal("1.5")
    # 白名单 unpickler 拒之（root 不在白名单）：
    with pytest.raises(pickle.UnpicklingError):
        with p.open("rb") as fh:
            _allowlist_pickle_load(fh)


def test_allowlist_admits_listed_library_class(tmp_path: Path):
    """白名单放行可信库根（numpy/dict）—— 不过度拦截。"""
    p = _dump_pickle({"coef": np.array([1.0, 2.0, 3.0]), "intercept": 0.5}, tmp_path / "ok.pkl")
    with p.open("rb") as fh:
        out = _allowlist_pickle_load(fh)
    assert list(out["coef"]) == [1.0, 2.0, 3.0]
    assert out["intercept"] == 0.5


def test_enforce_load_applies_allowlist_even_when_hash_registered(tmp_path: Path):
    """两道门正交:即便 full-sha256 已登记（过 #1），含未白名单类的内容仍被类白名单拒（#2）。"""
    store = _store(tmp_path)
    p = _dump_pickle(Decimal("2.0"), tmp_path / "dec_registered.pkl")
    store.register(p, producer_run="run-x", producer_kind="ml_train")  # hash 门放行
    with pytest.raises(pickle.UnpicklingError):
        load_model(p, trust=store)  # 类白名单仍拒 Decimal


def test_allowlist_unpickler_subclasses_blocklist():
    """结构断言:白名单 unpickler 继承止血 blocklist（两道并存·扩展不替换）。"""
    assert issubclass(_AllowlistUnpickler, _RestrictedUnpickler)


def test_allowlist_still_blocks_known_rce_gadget(tmp_path: Path):
    """白名单路径仍堵直球 RCE（继承的 blocklist 兜底，防御纵深）。"""

    class _EvilSystem:
        def __reduce__(self):
            return (os.system, ("echo x > /dev/null",))

    p = _dump_pickle(_EvilSystem(), tmp_path / "evil.pkl")
    with pytest.raises(pickle.UnpicklingError):
        with p.open("rb") as fh:
            _allowlist_pickle_load(fh)


# ══ 验收 #3 · DL safe tensors + JSON config + 绝不静默回落 weights_only=False ══
def test_dl_pt_nonsafe_type_refused_no_silent_fallback(tmp_path: Path):
    """种坏门:.pt 含 weights_only 不安全类型 → 显式 raise,【绝不】回落 weights_only=False。

    强证据:同一文件 weights_only=False【本可】加载（故非文件损坏）—— 我方刻意拒,证明无静默降级。
    """
    import torch

    p = tmp_path / "nonsafe.pt"
    torch.save({"arch": "lstm", "state_dict": {}, "config": _NonSafeForWeightsOnly()}, p)
    with pytest.raises(ArtifactTrustError):
        artifact_trust.load_dl_checkpoint(p)  # weights_only=True 拒 → 我方显式 raise,不回落
    # 证明【不是】文件本身坏:weights_only=False 本可加载（我方刻意拒，非被迫）
    loaded = torch.load(p, map_location="cpu", weights_only=False)
    assert isinstance(loaded["config"], _NonSafeForWeightsOnly)


def test_dl_safetensors_preferred_happy_path(tmp_path: Path):
    """safe tensors(+ JSON config) 优先路径:零 pickle 加载权重 + JSON 读 arch/config。"""
    pytest.importorskip("safetensors")
    import torch
    from safetensors.torch import save_file

    sd = {"w": torch.zeros(2, 3), "b": torch.ones(3)}
    p = tmp_path / "model.safetensors"
    save_file(sd, str(p))
    (tmp_path / "model.json").write_text(
        json.dumps({"arch": "lstm", "config": {"lookback": 4, "n_outputs": 1, "feature_cols": ["f1", "f2"]}})
    )
    ck = artifact_trust.load_dl_checkpoint(p)
    assert ck["arch"] == "lstm"
    assert ck["config"]["lookback"] == 4
    assert set(ck["state_dict"].keys()) == {"w", "b"}
    assert float(ck["state_dict"]["b"].sum().item()) == 3.0


def test_dl_safetensors_missing_lib_no_fallback_to_pickle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """safetensors 缺包 → 显式 raise,【绝不】回落 pickle/.pt 不安全路径（模拟未装：屏蔽模块）。"""
    p = tmp_path / "x.safetensors"
    p.write_bytes(b"\x00\x01")
    monkeypatch.setitem(sys.modules, "safetensors", None)
    monkeypatch.setitem(sys.modules, "safetensors.torch", None)
    with pytest.raises(ArtifactTrustError) as ei:
        artifact_trust.load_safetensors_artifact(p)
    assert "safetensors" in str(ei.value)


def test_dl_safetensors_missing_json_sidecar_refused(tmp_path: Path):
    """safetensors 缺同名 .json config（arch/config 必须 JSON 旁车，非 pickle）→ 拒。"""
    pytest.importorskip("safetensors")
    import torch
    from safetensors.torch import save_file

    p = tmp_path / "no_sidecar.safetensors"
    save_file({"w": torch.zeros(1)}, str(p))
    with pytest.raises(ArtifactTrustError):
        artifact_trust.load_dl_checkpoint(p)


# ══ 验收 #4 · 系统自产且 hash 命中 → 正常加载（向后兼容·不误伤） ═══════════════
def test_registered_sklearn_loads_under_enforce(tmp_path: Path):
    """正路径:真实 sklearn 模型 → 登记 → enforce 加载成功且能预测（白名单覆盖 sklearn/numpy）。"""
    store = _store(tmp_path)
    model = _fit_linreg()
    p = _dump_pickle(model, tmp_path / "linreg.pkl")
    store.register(p, producer_run="run-ml-1", producer_kind="ml_train")
    loaded = load_model(p, trust=store)
    pred = loaded.predict(np.array([[0.0, 1.0], [2.0, 3.0]]))
    assert pred.shape == (2,)
    assert np.isfinite(pred).all()


def test_registered_lightgbm_loads_under_enforce(tmp_path: Path):
    """正路径:真实 lightgbm 模型 → 登记 → enforce 加载（白名单覆盖 lightgbm/collections）。"""
    lgb = pytest.importorskip("lightgbm")
    store = _store(tmp_path)
    X = np.arange(40, dtype=float).reshape(20, 2)
    y = X[:, 0] - X[:, 1]
    model = lgb.LGBMRegressor(n_estimators=3, max_depth=2, verbose=-1).fit(X, y)
    p = _dump_pickle(model, tmp_path / "lgbm.pkl")
    store.register(p, producer_run="run-ml-2", producer_kind="ml_train")
    loaded = load_model(p, trust=store)
    assert loaded.predict(X[:3]).shape == (3,)


def test_registered_pt_loads_and_predicts_under_enforce(tmp_path: Path):
    """正路径:登记的 .pt → predict_with（enforce）输出对齐 panel 行（warmup NaN）。"""
    store = _store(tmp_path)
    lookback = 4
    p = _make_pt_ckpt(tmp_path / "dl.pt", lookback=lookback)
    store.register(p, producer_run="run-dl-1", producer_kind="dl_train")
    panel = _panel(n_syms=2, n_days=12)
    preds = predict_with(p, panel, ["f1", "f2"], trust=store)
    assert len(preds) == len(panel)
    assert int(np.isnan(preds).sum()) == 2 * lookback  # 2 标的 × lookback warmup
    assert np.isfinite(preds[~np.isnan(preds)]).all()


def test_backward_compat_default_off_loads_legit_and_blocks_rce(tmp_path: Path):
    """默认（无 trust）= 向后兼容:合法 pickle 照常加载，已知 RCE 仍被止血 blocklist 拦。"""
    p = _dump_pickle({"coef": np.array([1.0, 2.0]), "name": "linreg"}, tmp_path / "legit.pkl")
    out = load_model(p)  # 默认 enforce=False
    assert out["name"] == "linreg"

    class _Evil:
        def __reduce__(self):
            return (os.system, ("echo x > /dev/null",))

    e = _dump_pickle(_Evil(), tmp_path / "evil.pkl")
    with pytest.raises(pickle.UnpicklingError):
        load_model(e)  # 默认路径仍堵 RCE


# ══ 登记账 / 身份源机制 ═══════════════════════════════════════════════════════
def test_fingerprint_reuses_content_hash_single_source(tmp_path: Path):
    """单一身份源红线:content_id 必由 ids.content_hash 产（不另造）；安全键用完整 256-bit sha256。"""
    import hashlib

    p = _dump_pickle({"a": 1}, tmp_path / "fp.pkl")
    full, content_id = artifact_trust.artifact_fingerprint(p)
    assert full == hashlib.sha256(p.read_bytes()).hexdigest()  # 完整 256-bit
    assert len(full) == 64
    assert content_id == content_hash({"artifact_sha256": full, "schema": "artifact-trust-v1"})  # 复用 ids
    assert len(content_id) == 16  # ids HASH_LEN


def test_trust_store_append_only_chain_intact_and_tamper_detected(tmp_path: Path):
    """登记账 prev_hash 链:正常 → intact；篡改某行 → 检出（防对登记文件的事后篡改）。"""
    store = _store(tmp_path)
    a = _dump_pickle({"x": 1}, tmp_path / "a.pkl")
    b = _dump_pickle({"x": 2}, tmp_path / "b.pkl")
    store.register(a, producer_run="r1", producer_kind="ml_train")
    store.register(b, producer_run="r2", producer_kind="ml_train")
    ok, issues = store.verify_chain()
    assert ok, issues

    # 篡改登记文件第一行的 record（改 producer_run）→ row_hash 对不上 → 检出
    jsonl = tmp_path / "trust" / "artifact_trust.jsonl"
    lines = jsonl.read_text().splitlines()
    rec0 = json.loads(lines[0])
    rec0["record"]["producer_run"] = "TAMPERED"
    lines[0] = json.dumps(rec0, ensure_ascii=False)
    jsonl.write_text("\n".join(lines) + "\n")
    ok2, issues2 = ArtifactTrustStore(tmp_path / "trust").verify_chain()
    assert not ok2
    assert issues2


def test_configure_default_trust_enforces_globally(tmp_path: Path):
    """全局默认策略机制（follow-on 接线点）:configure → 未登记被拒；reset → 复位向后兼容。"""
    store = _store(tmp_path)
    p = _dump_pickle({"w": np.array([1.0])}, tmp_path / "g.pkl")
    # 默认 OFF：无 trust 参数也照常加载
    assert load_model(p)["w"][0] == 1.0
    # 全局翻 enforce → 无 trust 参数也走信任门 → 未登记被拒
    artifact_trust.configure_default_trust(TrustPolicy(store=store, enforce=True))
    with pytest.raises(ArtifactTrustError):
        load_model(p)
    # 登记后正常
    store.register(p, producer_run="rg", producer_kind="ml_train")
    assert load_model(p)["w"][0] == 1.0
    # 复位（autouse fixture 也会复位，这里显式验证机制）
    artifact_trust.reset_default_trust()
    assert load_model(_dump_pickle({"w": np.array([9.0])}, tmp_path / "g2.pkl"))["w"][0] == 9.0
