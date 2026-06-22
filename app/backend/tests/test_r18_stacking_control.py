"""R18 stacking 控制项 · 诚实两面守卫（S 卡 87ad21fc / DECISIONS D-WAVE1A）。

R18（DECISIONS §5「= 确认」）= 信号层模型集成强制 OOF+purge+embargo 防 stacking 泄露。
本控制项状态必须诚实切**两面**——绝不整体标 N/A，也绝不假装已全验证（RULES §3 不假绿灯）：

  面 (a) 声明门 = ✅ 已建并验证
      SignalContractRegistry.register 强制 LeakageDeclaration(OOF+purge+embargo 自报齐全)
      才准信号入因子库；已对抗测试 test_adv4_signal_contract_leakage_declaration_gate /
      _unit_gate（五变体）。本面是「拒未声明」的活控制，不证明无泄露。

  面 (b) stacking meta-learner 实证 OOF 强制 = N/A until 实现
      代码当前**无** stacking / 集成 meta-model 对象（无被测主体），故实证强制无从谈起。
      本测试钉死这个 N/A 是**诚实的**（确无对象、非遗忘的 gap），并钉死**单一 CV 源 =
      models/purged_cv.py**。一旦将来加 stacking，meta-learner 必须消费该单一源的 purged
      OOF（OOF+purge+embargo）——届时 test_face_b_no_stacking_meta_model_object_yet 会自然
      失败，强制实现者补 R18 实证守卫，不让 N/A 悄悄变成假绿。

门必抓（种已知坏，门必抓）：
- 种第二个 CV 实现（另写一个 purged_kfold/walk_forward）→ test_single_cv_source_is_purged_cv 红。
- 种 stacking meta-model 对象 → test_face_b_no_stacking_meta_model_object_yet 红，强制接 R18 实证 OOF。
"""

from __future__ import annotations

from pathlib import Path

from app.factor_factory.signal_contract import (
    LeakageDeclaration,
    SignalContractError,
    SignalContractRegistry,
)

# 扫描范围 = 后端产品代码包（tests/ 不在 app/ 下，本测试自身的标志串字面量不会被扫到）。
APP_DIR = Path(__file__).resolve().parents[1] / "app"


def _iter_py_sources():
    for p in sorted(APP_DIR.rglob("*.py")):
        yield p, p.read_text(encoding="utf-8")


def test_face_a_declaration_gate_is_live():
    """面 (a)：泄露声明门是活控制——缺任一项即拒入库（R18 声明侧 = ✅）。"""
    assert LeakageDeclaration().is_complete() is False
    assert LeakageDeclaration(oof=True, purge=True, embargo=True).is_complete() is True
    assert LeakageDeclaration(oof=True, purge=False, embargo=True).missing() == ["purge"]

    reg = SignalContractRegistry()
    raised = False
    try:
        reg.register(
            name="x", source_lib="ml", model_ref="gbdt.pkl", output_kind="xs_score",
            horizon=1, leakage={"oof": True, "purge": False, "embargo": True},
        )
    except SignalContractError as exc:
        raised = True
        msg = str(exc)
        assert "R18" in msg or "OOF" in msg or "purge" in msg
    assert raised, "声明门必须拒未声明齐全 OOF+purge+embargo 的信号入库"

    # 声明齐全则准入（活控制不是死挡）。
    ok = reg.register(
        name="ok", source_lib="ml", model_ref="gbdt.pkl", output_kind="xs_score",
        horizon=1, leakage={"oof": True, "purge": True, "embargo": True},
    )
    assert ok.leakage.is_complete()


# 真实 stacking / 集成 meta-model 对象的标志（出现即意味 R18 实证强制不再 N/A）。
_STACKING_OBJECT_MARKERS = (
    "StackingClassifier",
    "StackingRegressor",
    "StackingCVClassifier",
    "meta_model",
    "meta_learner",
    "MetaLearner",
    "class Stacking",
    "class Blender",
)


def test_face_b_no_stacking_meta_model_object_yet():
    """面 (b)：当前无 stacking 对象 → 实证 OOF 强制 = N/A（诚实，非遗忘的 gap）。

    门必抓：一旦引入 stacking meta-model 对象，本测试红，强制实现者把 meta-learner
    接上 purged_cv 的 purged OOF（R18 实证守卫），不让 N/A 悄悄变成假绿。
    """
    hits: list[str] = []
    for path, text in _iter_py_sources():
        for marker in _STACKING_OBJECT_MARKERS:
            if marker in text:
                hits.append(f"{path.relative_to(APP_DIR)} :: {marker}")
    assert not hits, (
        "检出疑似 stacking/集成 meta-model 对象，R18 实证 OOF 强制不再是 N/A——"
        "须为 meta-learner 接上 purged_cv 的 purged OOF 并补 in-sample-基预测泄露版对抗测试：\n"
        + "\n".join(hits)
    )


def test_single_cv_source_is_purged_cv():
    """单一 CV 源（RULES §1 复用单一源）：purged k-fold / walk-forward 切分器只在 purged_cv.py。

    门必抓：另写第二个 purged_kfold/walk_forward 实现 → 本测试红。
    （eval/model_eval.py 的 walk_forward_windows 是结果加工、非 CV 切分器，标志带 '(' 不误命中。）
    """
    cv_def_markers = ("def purged_kfold(", "def walk_forward(")
    owners: dict[str, list[str]] = {m: [] for m in cv_def_markers}
    for path, text in _iter_py_sources():
        rel = str(path.relative_to(APP_DIR))
        for marker in cv_def_markers:
            if marker in text:
                owners[marker].append(rel)
    for marker, files in owners.items():
        assert files == ["models/purged_cv.py"], (
            f"CV 切分器 {marker!r} 应只定义在 models/purged_cv.py（单一源，§1），实得：{files}"
        )
