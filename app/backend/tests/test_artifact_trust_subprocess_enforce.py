"""自由代码 / DL【子进程】路 artifact 信任门 enforce 的对抗测试（C-MODELGOV-1 残余① · GOAL §15）。

W1（6144bd61·test_artifact_trust_activation.py）证了【主进程】组合消费侧（service._apply_input_models）
在 enforce 下拦外来 artifact；但留下诚实残余①：**自由代码训练子进程**（submit_code / train_now_code，
codegen 渲染 → runner 子进程跑）内若用户代码【自调】predict_with / load_model（trust 默认=None），
子进程进程级默认策略未被 configure → enforce=False → §15「外来 pickle 默认 block」该路未兑现。

本文件证残余① 的兑现（runner trust-bootstrap 启动钩子 + service 透传信任根），**端到端经真
TrainingService.train_now_code → runner 子进程**逐条种坏门：

  直证   子进程进程级默认策略被 launcher 翻成 enforce（且绑同源 store）；opt-out 时继承回退。
  ① 验收#1 子进程加载【外来 / 未登记】.pkl（enforce 下）→ 在 predict_with load 处被拒、job failed。
  MUT    trust_enforce=False → 同一外来 .pkl 子进程内经止血 blocklist 照常加载 → job succeeded
         （证 enforce 是【载入门是否拒】的唯一变量：若 launcher 不 configure，验收#1 会退化成本例 → 红）。
  ② 验收#2 子进程加载【系统自产·已登记】artifact → 正常预测、不误伤（producer 已接·正路径）。
  ③ 验收#3 子进程 store_under(QUANTBT_TRUST_ROOT) 与主进程 store_under(self._root) 同源——
         子进程能看见主进程 producer 登记（跨进程 on-disk JSONL 共享）。

注：本卡只跑 scoped；enforce-默认-翻开的【全量】验证由中心在整合点跑。
"""

from __future__ import annotations

import os

# 主进程零 torch 约定 + 防 OMP 崩溃（与 _predict_dl / wave-1 测试同策）。子进程经 env 继承。
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import pickle  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from app.training import TrainingRequest, TrainingService, artifact_trust  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_global_trust():
    """复位【主进程】进程级默认策略——本卡的 configure 只发生在【子进程】（隔离·随进程消亡），
    主进程默认策略一字不该被翻；此 fixture 纯防跨文件全局态泄漏污染基线（与 W1 同策·防御纵深）。
    """
    artifact_trust.reset_default_trust()
    yield
    artifact_trust.reset_default_trust()


def _panel(n_syms: int = 2, n_days: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows: list[dict] = []
    for s in range(n_syms):
        for t in range(n_days):
            rows.append(
                {"symbol": f"s{s}", "ts": t, "f1": rng.normal(), "f2": rng.normal(), "label": rng.normal()}
            )
    return pd.DataFrame(rows)


def _req(name: str, model: str = "lgbm", **kw) -> TrainingRequest:
    base = dict(name=name, model=model, task="regression", feature_cols=["f1", "f2"], n_splits=4)
    base.update(kw)
    return TrainingRequest(**base)  # type: ignore[arg-type]


def _probe_default_policy_code() -> str:
    """子进程探针：emit 子进程进程级默认策略的 (enforce, 是否绑 store)。"""
    return (
        "from app.training import artifact_trust\n"
        "from app.training.lib import emit\n"
        "pol = artifact_trust.resolve_policy(None)  # = 子进程进程级默认策略\n"
        "emit({'oos_metrics': {'enforce': 1.0 if pol.enforce else 0.0, "
        "'has_store': 1.0 if pol.store is not None else 0.0}, 'artifact_path': None})\n"
    )


def _predict_with_code(artifact_path: str) -> str:
    """子进程自由代码：自调 predict_with 加载 artifact（trust 默认=None → 取子进程默认策略）。"""
    return (
        "import os\n"
        "import pandas as pd\n"
        "from app.training.lib import emit, predict_with\n"
        "panel = pd.read_parquet(os.environ['QUANTBT_PANEL_PATH'])\n"
        f"preds = predict_with({artifact_path!r}, panel, ['f1', 'f2'])\n"
        "emit({'oos_metrics': {'n': float(len(preds))}, 'artifact_path': None})\n"
    )


# ══ 直证：子进程进程级默认策略被 launcher 翻成 enforce（残余① 的核心兑现点） ══════════
def test_subprocess_default_policy_is_enforced(tmp_path: Path):
    """种坏门反向锚：自由代码子进程的进程级默认策略 = enforce=True 且绑【同源 store】。

    若 runner trust-bootstrap 未 configure（或 service 未透传 QUANTBT_TRUST_ROOT）→ 子进程默认
    enforce=False / store=None → 本断言红。这是「子进程不 configure → 漏过」的直接探针（MUT 锚）。
    """
    svc = TrainingService(root=tmp_path / "tr", timeout=300)  # enforce 默认 ON
    job = svc.train_now_code("probe-default-policy", _probe_default_policy_code(), _panel())
    assert job.status == "succeeded", job.error
    assert job.metrics["enforce"] == 1.0, "子进程进程级默认策略未 enforce（残余① 未兑现 → 外来 pickle 漏过）"
    assert job.metrics["has_store"] == 1.0, "子进程默认策略未绑 store（enforce 无登记面可查 → 退化）"


def test_subprocess_default_policy_inherits_optout(tmp_path: Path):
    """trust_enforce=False → 子进程默认策略 enforce=False（继承主进程 opt-out·W1 单点可逆开关）。"""
    svc = TrainingService(root=tmp_path / "tr", timeout=300, trust_enforce=False)
    job = svc.train_now_code("probe-optout", _probe_default_policy_code(), _panel())
    assert job.status == "succeeded", job.error
    assert job.metrics["enforce"] == 0.0, "opt-out 未透传到子进程（trust_enforce=False 应继承回退）"


# ══ ① 验收#1（端到端）：子进程加载【外来 / 未登记】.pkl（enforce 下）→ 拒 ════════════════
def test_subprocess_freecode_external_pkl_refused(tmp_path: Path):
    """种坏门：自由代码子进程内 predict_with 一个【外来·从未 register】.pkl（enforce ON）→ job failed。

    端到端证据：拒发生在【子进程】 predict_with→load_model→assert_ok 真实链路里——正是 W1 残余①
    指出、主进程 _apply_input_models 覆盖不到的自由代码自调路径。
    """
    svc = TrainingService(root=tmp_path / "tr", timeout=300)  # enforce 默认 ON
    from sklearn.linear_model import LinearRegression

    ext = tmp_path / "external_model.pkl"  # 非本系统 producer 产出 → full-sha256 从不命中登记
    with ext.open("wb") as fh:
        pickle.dump(LinearRegression().fit(np.zeros((4, 2)), np.zeros(4)), fh)
    job = svc.train_now_code("evil-subprocess", _predict_with_code(str(ext)), _panel())
    assert job.status == "failed", "外来未登记 artifact 在 enforce 子进程内未被拒（残余① 漏洞）"
    assert "ArtifactTrust" in (job.error or ""), job.error  # 子进程 ArtifactTrustError 经 stderr 冒泡


def test_subprocess_freecode_external_loads_when_optout(tmp_path: Path):
    """MUT 配对（证 enforce 有齿且可逆）：trust_enforce=False → 同一外来 .pkl 子进程内照常加载 → succeeded。

    与上一例【唯一差别 = enforce 透传值】：enforce ON 拒、OFF 放行。故若 launcher 根本不 configure，
    上一例会退化成本例（外来 artifact 被加载、job succeeded）→ 上一例的 `assert failed` 红 = 坏门被抓。
    """
    svc = TrainingService(root=tmp_path / "tr", timeout=300, trust_enforce=False)
    assert svc._trust_enforce is False
    from sklearn.linear_model import LinearRegression

    ext = tmp_path / "external_model.pkl"
    with ext.open("wb") as fh:
        pickle.dump(LinearRegression().fit(np.zeros((4, 2)), np.arange(4.0)), fh)
    job = svc.train_now_code("optout-subprocess", _predict_with_code(str(ext)), _panel())
    assert job.status == "succeeded", job.error  # opt-out：外来经止血 blocklist 加载（不查登记·向后兼容）
    assert job.metrics["n"] == 120.0  # 2 syms × 60 days


# ══ ② 验收#2（端到端）：子进程加载【系统自产·已登记】artifact → 不误伤 ═══════════════════
def test_subprocess_freecode_loads_registered_artifact(tmp_path: Path):
    """正路径（enforce ON）：A 系统自产 → producer 登记；自由代码子进程 predict_with A → 放行、成功。

    证 enforce 默认 ON 不误伤【已登记】自产 artifact（producer 已接·验收#2），且子进程读到的就是
    主进程 producer 写入的【同一】登记账（跨进程一致）。
    """
    svc = TrainingService(root=tmp_path / "tr", timeout=300)  # enforce 默认 ON
    a = svc.train_now(_req("A", model="xgboost", hyperparams={"n_estimators": 30}), _panel())
    assert a.status == "succeeded", a.error
    artifact = str(Path(a.artifact_dir) / "model.pkl")
    job = svc.train_now_code("compose-in-subprocess", _predict_with_code(artifact), _panel())
    assert job.status == "succeeded", job.error  # 已登记自产 artifact 子进程 enforce 下放行（无误伤）
    assert job.metrics["n"] == 120.0


# ══ ③ 验收#3（端到端）：子进程信任 store 与主进程同源（跨进程 JSONL 共享） ════════════════
def test_subprocess_store_same_source_as_main(tmp_path: Path):
    """子进程 store_under(QUANTBT_TRUST_ROOT) 与主进程 store_under(self._root) 解析到同一 on-disk 账：
    主进程 producer 登记的 artifact，子进程内 is_trusted 立即可见（跨进程登记可见·验收#3）。
    """
    svc = TrainingService(root=tmp_path / "tr", timeout=300)
    a = svc.train_now(_req("A", model="xgboost", hyperparams={"n_estimators": 30}), _panel())
    assert a.status == "succeeded", a.error
    artifact = str(Path(a.artifact_dir) / "model.pkl")
    # 主进程侧确认已登记（producer 落盘即 register）
    assert artifact_trust.store_under(svc._root).is_trusted(artifact)
    # 子进程经 QUANTBT_TRUST_ROOT 解析同源账 → 看见同一登记
    code = (
        "import os\n"
        "from app.training.artifact_trust import store_under\n"
        "from app.training.lib import emit\n"
        f"trusted = store_under(os.environ['QUANTBT_TRUST_ROOT']).is_trusted({artifact!r})\n"
        "emit({'oos_metrics': {'trusted': 1.0 if trusted else 0.0}, 'artifact_path': None})\n"
    )
    job = svc.train_now_code("same-source-probe", code, _panel())
    assert job.status == "succeeded", job.error
    assert job.metrics["trusted"] == 1.0, "子进程信任账与主进程不同源（跨进程登记不可见 → 误伤自产）"
