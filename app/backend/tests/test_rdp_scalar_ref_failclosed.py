"""C-S17-RDP-SCALAR-FAILCLOSED · §17 RDP 门 scalar/coercion fail-open **系统性**收口 · 对抗测试。

起源（跨厂商 duet · 2026-07-15）：codex(GPT,xhigh) 两轮复审逮出并经本机独立复现——canonical §17 RDP
门在**多个输入面**把畸形标量/容器 char-split 或 str-coerce 成非空 → 门2(dataset/ingestion)、门3(residual)
whitewash 成 `validate_rdp ok=True`（假绿灯·违 RULES §3）。本文件守全部收口面：

  面1 `RDPManifest.__post_init__` 的 `_ref_sequence`：bare str/bytes/bytearray、非 list/tuple 容器
      （dict/generator/memoryview/set）、非 str 元素——全 fail-closed（原只挡 str/bytes → char-split）。
  面2 `aggregate_rdp`：`unverified_residual` / `known_limitations` 不再在构造前 `tuple()` 预拆，原样透传
      由 `__post_init__` 守卫（标量在此 fail-closed，绝不 char-split 洗白门3）。
  面3 `main._rdp_tuple`（HTTP `POST /api/research-os/rdp/manifests` 入口）：拒绝 bare scalar / 非 str 元素
      （原 `(str(value),)` / `str(v)` 把任意标量/映射 str-coerce 成伪造 ref）→ ValueError → 422。
  面4 `DatasetVersionRef.from_dict`：dataset_id/version/manifest_sha256 非 str 拒绝（原 `str(嵌套 dict)`
      → 伪造 `is_resolvable=True` → 洗白门2）。

★ mutation（RULES §2 种坏门必抓·已手验·见任务报告）：把 `_ref_sequence` 的容器/元素 guard 弱回内建
  `tuple(value)` → 下列 scalar/container/element/aggregator 用例转 RED → 还原 → GREEN。
"""

from __future__ import annotations

import pytest

# 冷导入预热（既有循环·非本卡引入）：与 test_section17_rdp_gate.py 同款顺序。
import app.agent.orchestrator  # noqa: F401

from app.delivery.aggregator import aggregate_rdp  # noqa: E402
from app.delivery.rdp import PromotionClaim, RDPManifest  # noqa: E402
from app.delivery.rdp_gate import (  # noqa: E402
    GATE_DATASET_LINEAGE,
    GATE_UNVERIFIED_RESIDUAL,
    gate_promotion_traceability,
    validate_rdp,
)
from app.research_os.rdp import (  # noqa: E402
    DatasetVersionRef,
    validate_rdp_manifest,
)
from app.research_os.spine import RuntimeStatus  # noqa: E402

# conftest 已设 QUANTBT_RUNTIME_MODE=test → 可导入 app.main（面3 的 HTTP payload 适配器 helper）。
from types import SimpleNamespace  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.auth import require_user_dependency  # noqa: E402
from app.main import _rdp_opt_str, _rdp_str, _rdp_tuple  # noqa: E402


# 全部 39 个 string-ref tuple 字段（= RDPManifest.__post_init__ 的 tuple_fields 减去 object 字段
# dataset_versions）。codex 指出旧测只覆盖 5 个——此处逐一覆盖，防"漏字段=漏门"。
_STRING_REF_FIELDS = (
    "graph_refs", "data_refs", "dataset_version_refs", "market_data_use_validation_refs",
    "ingestion_skill_refs", "mathematical_refs", "theory_binding_refs", "consistency_check_refs",
    "methodology_choice_refs", "responsibility_refs", "asset_refs", "code_refs", "test_refs",
    "run_refs", "honest_n_refs", "cost_and_execution_assumptions", "attribution_refs", "known_limits",
    "unverified_residuals", "compiler_artifact_refs", "mathematical_spine_chain_refs",
    "goal_entrypoint_coverage_refs", "deployment_refs", "monitor_refs", "llm_call_refs",
    "source_file_refs", "data_source_refs", "llm_call_record_refs", "math_artifact_refs",
    "theory_spec_refs", "responsibility_disclosure_refs", "asset_versions", "adversarial_test_refs",
    "backtest_run_refs", "training_run_refs", "validation_run_refs", "known_limitations",
    "verifier_verdict_refs", "approval_refs",
)


# 本仓 scalar/coercion guard 抛出的错误短语（_rdp_tuple / _rdp_str / _rdp_opt_str / _ref_sequence）。
# POST 断言用它 attribute 422 = 来自 guard，而非畸形 payload 缺其它必填字段的 422（防假绿）。
_GUARD_ERROR_PHRASES = (
    "must be a JSON array of strings",
    "elements must be strings",
    "must be a string",
    "must be a sequence of strings",
    "must be a list/tuple of strings",
    "blank/whitespace",
    "must be a string, not",
)


def _base_kwargs(**overrides):
    kwargs = dict(
        asset_ref="factor::alpha_x",
        asset_kind="factor",
        artifact_hash="sha256:abc123",
        reproducibility_command="documentation only; not executable authority",
    )
    kwargs.update(overrides)
    return kwargs


def _promo(rdp):
    return PromotionClaim(asset_ref="factor::alpha_x", asset_kind="factor", rdp_ref=rdp.rdp_id)


# ════════════════════════════════════════════════════════════════════════════
# 面1 · _ref_sequence — bare str / 非 list-tuple 容器 / 非 str 元素 全 fail-closed
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("field_name", _STRING_REF_FIELDS)
def test_scalar_string_in_every_ref_field_raises(field_name):
    """标量 str 入**任一** §17 string-ref 字段 → TypeError（非 char-split 成假多重）。"""

    with pytest.raises(TypeError, match="must be a sequence of strings"):
        RDPManifest(**_base_kwargs(**{field_name: "skill::tushare_daily"}))


def test_singular_unverified_residual_scalar_raises():
    """singular unverified_residual（不在 tuple_fields 循环里·单独归一）标量 → TypeError。"""

    with pytest.raises(TypeError, match="must be a sequence of strings"):
        RDPManifest(**_base_kwargs(unverified_residual="执行成本未在 live 验证"))


def test_scalar_bytes_and_bytearray_raise():
    with pytest.raises(TypeError, match="must be a sequence of strings"):
        RDPManifest(**_base_kwargs(ingestion_skill_refs=b"skill::x"))
    with pytest.raises(TypeError, match="must be a sequence of strings"):
        RDPManifest(**_base_kwargs(unverified_residual=bytearray(b"residual")))


@pytest.mark.parametrize(
    "bad_container",
    [
        {"skill::x": 1},                 # dict → tuple(dict)=keys 假多重
        (c for c in "skill"),            # generator → 逐产出假多重
        memoryview(b"skill"),            # memoryview → ints
        {"skill::x", "skill::y"},        # set → 无序假多重
    ],
    ids=["dict", "generator", "memoryview", "set"],
)
def test_nonlist_container_ref_field_raises(bad_container):
    """非 list/tuple 容器入 string-ref 字段 → TypeError（不 mis-expand 成非空 tuple）。"""

    with pytest.raises(TypeError, match="list/tuple of strings"):
        RDPManifest(**_base_kwargs(ingestion_skill_refs=bad_container))


@pytest.mark.parametrize("bad_elem", [123, None, {"a": 1}, ["nested"]], ids=["int", "None", "dict", "list"])
def test_nonstr_element_in_ref_field_raises(bad_elem):
    """list/tuple 里混入非 str 元素 → TypeError（防非 str 元素绕过门的 isinstance-str 过滤）。"""

    with pytest.raises(TypeError, match="elements must be strings"):
        RDPManifest(**_base_kwargs(ingestion_skill_refs=[bad_elem]))


# ════════════════════════════════════════════════════════════════════════════
# 面2 · aggregate_rdp — 标量 residual / known_limitations 不再构造前 char-split
# ════════════════════════════════════════════════════════════════════════════
def test_aggregator_scalar_residual_rejected():
    """★ 面2 核心：aggregate_rdp(unverified_residual=标量) → fail-closed（原在构造前 tuple() 洗白门3）。"""

    with pytest.raises(TypeError, match="must be a sequence of strings"):
        aggregate_rdp(
            asset_ref="factor::alpha_x", asset_kind="factor",
            artifact_hash="sha256:abc", reproducibility_command="doc",
            unverified_residual="执行成本未在 live 验证",
        )


def test_aggregator_scalar_known_limitations_rejected():
    with pytest.raises(TypeError, match="must be a sequence of strings"):
        aggregate_rdp(
            asset_ref="factor::alpha_x", asset_kind="factor",
            artifact_hash="sha256:abc", reproducibility_command="doc",
            known_limitations="仅样本内",
        )


def test_aggregator_honest_tuple_residual_ok():
    """诚实 tuple residual → aggregate_rdp 照常组装（不误伤真路径）。"""

    assembly = aggregate_rdp(
        asset_ref="factor::alpha_x", asset_kind="factor",
        artifact_hash="sha256:abc", reproducibility_command="doc",
        unverified_residual=("执行成本未在 live 验证",),
        known_limitations=("仅样本内",),
    )
    assert assembly.rdp.rdp_id
    assert assembly.rdp.unverified_residual == ("执行成本未在 live 验证",)


# ════════════════════════════════════════════════════════════════════════════
# 面3 · main._rdp_tuple — HTTP payload 序列字段拒绝标量/映射/非 str 元素
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "bad_payload",
    ["skill::x", 123, {"a": 1}, [{"nested": 1}], [123], b"x"],
    ids=["scalar-str", "int", "dict", "list-of-dict", "list-of-int", "bytes"],
)
def test_rdp_tuple_rejects_scalar_and_nonstr(bad_payload):
    """HTTP `_rdp_tuple` 拒绝标量/映射/非 str 元素 → ValueError（→ 端点 422，非伪造 ref）。"""

    with pytest.raises(ValueError):
        _rdp_tuple(bad_payload)


def test_rdp_tuple_empty_and_proper_ok():
    """空值 → ()；真 str 数组 → 原样 tuple（不误伤合法 payload）。"""

    assert _rdp_tuple(None) == ()
    assert _rdp_tuple("") == ()
    assert _rdp_tuple([]) == ()
    assert _rdp_tuple(["skill::a", "skill::b"]) == ("skill::a", "skill::b")


# ════════════════════════════════════════════════════════════════════════════
# 面4 · DatasetVersionRef.from_dict — 非 str 字段拒绝（原 str(嵌套)→伪造 is_resolvable）
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "bad_field",
    [
        {"dataset_id": {"nested": "x"}, "version": "v1"},
        {"dataset_id": ["a", "b"], "version": "v1"},
        {"dataset_id": "ds", "version": {"n": 1}},
        {"dataset_id": "ds", "version": "v1", "manifest_sha256": ["h"]},
    ],
    ids=["id-dict", "id-list", "version-dict", "sha-list"],
)
def test_datasetversionref_nonstr_field_rejected(bad_field):
    """DatasetVersionRef.from_dict 非 str 字段 → TypeError（不 str-coerce 成伪造 truthy ref）。"""

    with pytest.raises(TypeError, match="must be a string"):
        DatasetVersionRef.from_dict(bad_field)


def test_malformed_datasetversion_in_manifest_rejected():
    """畸形 DatasetVersion dict 经 manifest 构造路 → 同样 fail-closed（非 is_resolvable=True 洗白门2）。"""

    with pytest.raises(TypeError, match="must be a string"):
        RDPManifest(**_base_kwargs(dataset_versions=[{"dataset_id": {"nested": "x"}, "version": "v1"}]))


def test_datasetversionref_honest_str_ok():
    """诚实 str 字段 → 照常构造 + is_resolvable（不误伤）。"""

    ref = DatasetVersionRef.from_dict({"dataset_id": "ds_csi300", "version": "v1", "manifest_sha256": "h1"})
    assert ref.dataset_id == "ds_csi300" and ref.is_resolvable is True


# ════════════════════════════════════════════════════════════════════════════
# 精确门断言（codex 指出旧测只断整体 False·门3 坏也能靠门2 缺红）——逐门隔离
# ════════════════════════════════════════════════════════════════════════════
def _outcome_by_gate(res):
    return {o.gate_id: o for o in res.outcomes}


def test_gate3_precisely_rejects_none_residual_with_valid_lineage():
    """门3 单独发力：血统齐全（门2 过）但 residual=None → **仅门3** 拒（unverified_residual ∈ missing）。"""

    m = RDPManifest(**_base_kwargs(
        dataset_version_refs=("dataset_version:ds:v1:h1",),
        ingestion_skill_refs=("skill::tushare",),
        unverified_residual=None,   # 未声明残余
    ))
    res = validate_rdp(m, promotion=_promo(m))
    by_gate = _outcome_by_gate(res)
    assert by_gate[GATE_DATASET_LINEAGE].passed is True, "血统齐全时门2 应过（隔离出门3）"
    assert by_gate[GATE_UNVERIFIED_RESIDUAL].passed is False
    assert "unverified_residual" in by_gate[GATE_UNVERIFIED_RESIDUAL].missing


def test_gate2_precisely_rejects_missing_lineage_with_valid_residual():
    """门2 单独发力：residual 齐（门3 过）但无血统 → **仅门2** 拒（dataset_versions/ingestion ∈ missing）。"""

    m = RDPManifest(**_base_kwargs(unverified_residual=("成本未验证",)))
    res = validate_rdp(m, promotion=_promo(m))
    by_gate = _outcome_by_gate(res)
    assert by_gate[GATE_UNVERIFIED_RESIDUAL].passed is True, "residual 已声明时门3 应过（隔离出门2）"
    assert by_gate[GATE_DATASET_LINEAGE].passed is False
    assert "dataset_versions" in by_gate[GATE_DATASET_LINEAGE].missing
    assert "ingestion_skill_refs" in by_gate[GATE_DATASET_LINEAGE].missing


# ════════════════════════════════════════════════════════════════════════════
# 诚实路径不被误伤（打码不过头把功能打坏）
# ════════════════════════════════════════════════════════════════════════════
def test_proper_tuple_refs_construct_and_validate_ok():
    m = RDPManifest(**_base_kwargs(
        dataset_version_refs=("dataset_version:ds:v1:h1",),
        ingestion_skill_refs=["skill::tushare"],       # list 也 OK
        unverified_residual=("执行成本未在 live 验证",),
        dataset_versions=[{"dataset_id": "ds_csi300", "version": "v1", "manifest_sha256": "h1"}],
    ))
    assert m.ingestion_skill_refs == ("skill::tushare",)
    res = validate_rdp(m, promotion=_promo(m))
    assert res.ok is True


def test_empty_sequence_still_honestly_rejected():
    """空 tuple 仍诚实被拒（门2 缺血统 / 门3 零残余无署名）——非 whitewash。"""

    m = RDPManifest(**_base_kwargs(unverified_residual=()))
    res = validate_rdp(m, promotion=_promo(m))
    assert res.ok is False


def test_none_ref_fields_unchanged():
    """None（未声明）保持 None 语义——不被 _ref_sequence 误伤成 ()（门3 靠 None 区分未声明）。"""

    m = RDPManifest(**_base_kwargs())
    assert m.unverified_residual is None
    res = validate_rdp(m, promotion=_promo(m))
    assert res.ok is False  # 未声明 residual → 门3 拒


# ════════════════════════════════════════════════════════════════════════════
# ROUND-2b 补收（codex 第二轮 REFUTED）：空白元素 / DatasetVersionRef 普通构造器 /
# HTTP 标量文本字段 str() 洗白 / 真实 POST 422（非只直调 _rdp_tuple）
# ════════════════════════════════════════════════════════════════════════════
# 面A：合法类型但**空白内容**的元素（`("",)` / `("   ",)`）—— 门3 只看 len() 会把它当"已声明
#   残余"洗白（well-typed but empty）。_ref_sequence 拒空白元素；零内容只用空 tuple 表达。
@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n"], ids=["empty", "spaces", "tab", "newline"])
def test_blank_element_in_residual_rejected(blank):
    with pytest.raises(TypeError, match="blank/whitespace"):
        RDPManifest(**_base_kwargs(unverified_residual=(blank,)))


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
def test_blank_element_in_ref_field_rejected(blank):
    with pytest.raises(TypeError, match="blank/whitespace"):
        RDPManifest(**_base_kwargs(ingestion_skill_refs=(blank,)))


def test_blank_residual_whitewash_closed_at_construction():
    """★ 面A 核心：`("",)` 血统齐全也无法构造 → 门3 无从被 len()==1 骗成 ok=True。"""

    with pytest.raises(TypeError, match="blank/whitespace"):
        RDPManifest(**_base_kwargs(
            dataset_version_refs=("dataset_version:ds:v1:h1",),
            ingestion_skill_refs=("skill::tushare",),
            unverified_residual=("",),   # 空白残余
        ))


# 面B：`DatasetVersionRef` **普通构造器**（非 from_dict）——原无 __post_init__，dict/list 字段可构造，
#   随后门2 `dv.dataset_id.strip()` 崩 AttributeError / 伪造 is_resolvable=True。
@pytest.mark.parametrize(
    "kwargs",
    [
        {"dataset_id": {"n": "x"}, "version": "v1"},
        {"dataset_id": "ds", "version": ["v"]},
        {"dataset_id": "ds", "version": "v1", "manifest_sha256": {"h": 1}},
        {"dataset_id": 123, "version": "v1"},
    ],
    ids=["id-dict", "version-list", "sha-dict", "id-int"],
)
def test_datasetversionref_plain_constructor_nonstr_rejected(kwargs):
    with pytest.raises(TypeError, match="must be a string"):
        DatasetVersionRef(**kwargs)


def test_datasetversionref_plain_constructor_honest_str_ok():
    dv = DatasetVersionRef(dataset_id="ds_csi300", version="v1", manifest_sha256="h1")
    assert dv.is_resolvable is True


# 面C-helper：`_rdp_str` 拒非 str（原 `str(raw.get(x) or "")` 把 dict/list str-coerce 成伪造文本）。
@pytest.mark.parametrize("bad", [{"a": 1}, ["a"], 123, True, 1.5], ids=["dict", "list", "int", "bool", "float"])
def test_rdp_str_rejects_nonstr(bad):
    with pytest.raises(ValueError):
        _rdp_str(bad)


def test_rdp_str_none_and_str_ok():
    assert _rdp_str(None) == ""
    assert _rdp_str(None, "rdp.v3") == "rdp.v3"
    assert _rdp_str("", "rdp.v3") == "rdp.v3"
    assert _rdp_str("real") == "real"


# 面3 真实端点：POST 畸形 payload → 422（不 str/char-split 洗白·raise 在 record_manifest 之前=不落盘）。
@pytest.fixture
def _rdp_client():
    main.app.dependency_overrides[require_user_dependency] = lambda: SimpleNamespace(
        username="u1", user_id="u1"
    )
    try:
        yield TestClient(main.app, raise_server_exceptions=False)
    finally:
        main.app.dependency_overrides.pop(require_user_dependency, None)


@pytest.mark.parametrize(
    "payload",
    [
        {"dataset_version_refs": "dataset_version:ds:v1:h"},   # 序列字段 = 标量
        {"ingestion_skill_refs": {"skill::x": 1}},             # 序列字段 = mapping
        {"ingestion_skill_refs": [123]},                       # 序列字段 = 非 str 元素
        {"ingestion_skill_refs": [""]},                        # 序列字段 = 空白元素
        {"unverified_residuals": [""]},                        # 残余 = 空白元素
        {"artifact_hash": {"nested": "x"}},                    # 标量文本字段 = dict
        {"reproducibility_command": ["cmd"]},                  # 标量文本字段 = list
        {"residual_attestation": {"a": 1}},                    # 标量文本字段 = dict
    ],
    ids=["scalar-seq", "mapping-seq", "nonstr-elem", "blank-seq-elem", "blank-residual", "dict-text", "list-text", "dict-attest"],
)
def test_real_post_rejects_malformed_payload_422(_rdp_client, payload):
    """★ 真实端点对全部畸形形态返回 422（非伪造 ref/文本溜进落盘）。"""

    resp = _rdp_client.post("/api/research-os/rdp/manifests", json=payload)
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
    # ★ attribution（codex R4·防假绿）：422 必须来自本 scalar/coercion guard（错误短语在 detail 里），
    #   而非畸形 payload 缺其它必填字段——否则 neuter guard 后仍会因缺字段 422（测试无牙）。
    assert any(p in resp.text for p in _GUARD_ERROR_PHRASES), (
        f"422 未归因到 scalar/coercion guard（可能是缺字段 422·假绿）：{resp.text[:200]}"
    )


# ════════════════════════════════════════════════════════════════════════════
# ROUND-4 补收（codex 第四轮·安全相邻）：target_runtime 只做类型检查、不做枚举闭集——
# "LIVE"/"live " 非精确匹配跳过 live 必填门，原值却继续进 deployment runner（门↔执行分歧）
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("bad_runtime", ["LIVE", "live ", " live", "Live", "LIVE_ENV", "prod"], ids=["upper", "trail-sp", "lead-sp", "title", "suffix", "alias"])
def test_noncanonical_target_runtime_flagged_invalid(bad_runtime):
    """★ 安全相邻：非精确 RuntimeStatus 值 → invalid_target_runtime（不静默当非 live 跳门）。"""

    m = RDPManifest(
        asset_ref="f::x", asset_kind="factor", artifact_hash="h", reproducibility_command="d",
        target_runtime=bad_runtime,
    )
    codes = {v.code for v in validate_rdp_manifest(m)}
    assert "invalid_target_runtime" in codes, f"{bad_runtime!r} 应判 invalid_target_runtime"


@pytest.mark.parametrize(
    "good_runtime",
    [RuntimeStatus.OFFLINE, RuntimeStatus.PAPER, RuntimeStatus.TESTNET, RuntimeStatus.LIVE, "offline", "live"],
    ids=["enum-offline", "enum-paper", "enum-testnet", "enum-live", "str-offline", "str-live"],
)
def test_canonical_target_runtime_not_flagged(good_runtime):
    """精确 RuntimeStatus 值（enum 或其 .value 字符串）→ 不误判 invalid_target_runtime。"""

    m = RDPManifest(
        asset_ref="f::x", asset_kind="factor", artifact_hash="h", reproducibility_command="d",
        target_runtime=good_runtime,
    )
    codes = {v.code for v in validate_rdp_manifest(m)}
    assert "invalid_target_runtime" not in codes


# ════════════════════════════════════════════════════════════════════════════
# ROUND-3 补收（codex 第三轮候选第 4 类·安全相邻）：validate_rdp_manifest 的
# required_text `str(value)` 洗白 live-部署安全字段（approval/rollback/retire）+
# HTTP 原样送 approval_ref/rollback/retire/target_runtime（未走 helper）
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "field", ["approval_ref", "rollback_plan_ref", "retire_plan_ref"], ids=["approval", "rollback", "retire"]
)
def test_live_rdp_dict_safety_field_no_longer_whitewashes(field):
    """★ 安全相邻：LIVE RDP 的 approval/rollback/retire 传 dict → required_text 必判 missing_*
    （原 `str(dict)` 非空洗白掉 live-部署必填门）。"""

    m = RDPManifest(
        asset_ref="f::x", asset_kind="factor", artifact_hash="h", reproducibility_command="d",
        target_runtime=RuntimeStatus.LIVE, **{field: {"fake": "ref"}},
    )
    codes = {v.code for v in validate_rdp_manifest(m)}
    assert f"missing_{field}" in codes, f"dict {field} 应判 missing（非 str-coerce 洗白）"


def test_live_rdp_real_safety_fields_pass():
    """诚实 str live 安全字段 → 不误判 missing（真路径保真）。"""

    m = RDPManifest(
        asset_ref="f::x", asset_kind="factor", artifact_hash="h", reproducibility_command="d",
        target_runtime=RuntimeStatus.LIVE,
        approval_ref="gate::approved", rollback_plan_ref="plan::rb", retire_plan_ref="plan::rt",
    )
    codes = {v.code for v in validate_rdp_manifest(m)}
    for f in ("approval_ref", "rollback_plan_ref", "retire_plan_ref"):
        assert f"missing_{f}" not in codes


def test_dict_residual_attestation_no_longer_whitewashes_zero_residual():
    """零残余（空 tuple）+ dict residual_attestation → 必判 missing_residual_attestation（非 str 洗白）。"""

    m = RDPManifest(
        asset_ref="f::x", asset_kind="factor", artifact_hash="h", reproducibility_command="d",
        unverified_residuals=(), residual_attestation={"signed": "by-nobody"},
    )
    codes = {v.code for v in validate_rdp_manifest(m)}
    assert "missing_residual_attestation" in codes


@pytest.mark.parametrize("bad", [{"a": 1}, ["a"], 123, True], ids=["dict", "list", "int", "bool"])
def test_rdp_opt_str_rejects_nonstr(bad):
    with pytest.raises(ValueError):
        _rdp_opt_str(bad)


def test_rdp_opt_str_none_preserved_and_str_ok():
    assert _rdp_opt_str(None) is None       # 保 None（未供给哨兵·validator 区分）
    assert _rdp_opt_str("ref::x") == "ref::x"


@pytest.mark.parametrize(
    "payload",
    [
        {"approval_ref": {"fake": "approval"}},        # 安全字段 = dict
        {"rollback_plan_ref": ["plan"]},               # 安全字段 = list
        {"retire_plan_ref": {"a": 1}},                 # 安全字段 = dict
        {"target_runtime": {"x": 1}},                  # runtime = dict（伪装非 live 跳门）
        {"target_runtime": ["live"]},                  # runtime = list
    ],
    ids=["approval-dict", "rollback-list", "retire-dict", "runtime-dict", "runtime-list"],
)
def test_real_post_rejects_malformed_safety_and_runtime_422(_rdp_client, payload):
    """★ 真实端点：安全字段/runtime 畸形 → 422（不 str 洗白进落盘）。"""

    resp = _rdp_client.post("/api/research-os/rdp/manifests", json=payload)
    assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
    # ★ attribution（codex R4·防假绿）：422 必须来自本 scalar/coercion guard（错误短语在 detail 里），
    #   而非畸形 payload 缺其它必填字段——否则 neuter guard 后仍会因缺字段 422（测试无牙）。
    assert any(p in resp.text for p in _GUARD_ERROR_PHRASES), (
        f"422 未归因到 scalar/coercion guard（可能是缺字段 422·假绿）：{resp.text[:200]}"
    )


# ════════════════════════════════════════════════════════════════════════════
# ROUND-5 补收（codex 第五轮·2 safety-adjacent blocker）：
#  ① target_runtime allowlist 派生自全 RuntimeStatus 枚举 → 含 suspended/retired 生命周期末态
#     → 跳过 live 必填门且进 deployment runner。改为独立四值 {offline,paper,testnet,live} 常量。
#  ② PromotionClaim.asset_kind 无下游 fail-closed（无 __post_init__·_build_promotion str-coerce 不校验·
#     gate4 不查 asset_kind）→ dict/list asset_kind 洗白 §17 晋级追溯门。gate4 补 asset_kind==rdp.asset_kind。
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("lifecycle", ["suspended", "retired"], ids=["suspended", "retired"])
def test_lifecycle_end_state_runtime_flagged_invalid(lifecycle):
    """★ blocker①：生命周期末态（suspended/retired）不是合法部署目标 → invalid_target_runtime
    （原从全枚举派生 allowlist 会放行 → 跳 live 门 + 进 runner）。"""

    m = RDPManifest(
        asset_ref="f::x", asset_kind="factor", artifact_hash="h", reproducibility_command="d",
        target_runtime=lifecycle,
    )
    codes = {v.code for v in validate_rdp_manifest(m)}
    assert "invalid_target_runtime" in codes, f"{lifecycle!r} 应判 invalid_target_runtime（非合法部署目标）"


def _rdp_for_gate4(asset_kind="factor"):
    return RDPManifest(
        asset_ref="factor::x", asset_kind=asset_kind, artifact_hash="h", reproducibility_command="d",
        dataset_version_refs=("dataset_version:ds:v1:h1",), ingestion_skill_refs=("skill::x",),
        unverified_residual=("r",),
    )


@pytest.mark.parametrize(
    "coerced_asset_kind",
    [str({"x": 1}), str(["a"]), str(123), "model", "not_a_kind"],
    ids=["dict-coerced", "list-coerced", "int-coerced", "wrong-legit-kind", "garbage"],
)
def test_gate4_malformed_or_mismatched_asset_kind_rejected(coerced_asset_kind):
    """★ blocker②：晋级 asset_kind ≠ RDP asset_kind（畸形 str-coerce 或张冠李戴）→ gate4 拒（不洗白追溯门）。"""

    rdp = _rdp_for_gate4(asset_kind="factor")
    pc = PromotionClaim(asset_ref="factor::x", asset_kind=coerced_asset_kind, rdp_ref=rdp.rdp_id)
    out = gate_promotion_traceability(pc, rdp)
    assert out.passed is False and "asset_kind" in out.missing, (
        f"asset_kind={coerced_asset_kind!r} 应被 gate4 拒（passed={out.passed} missing={out.missing}）"
    )


def test_gate4_matching_asset_kind_passes():
    """诚实路径：晋级 asset_kind == RDP asset_kind → gate4 不因 asset_kind 拒。"""

    rdp = _rdp_for_gate4(asset_kind="factor")
    pc = PromotionClaim(asset_ref="factor::x", asset_kind="factor", rdp_ref=rdp.rdp_id)
    out = gate_promotion_traceability(pc, rdp)
    assert out.passed is True, f"匹配 asset_kind 不应被拒（missing={out.missing}）"


# ════════════════════════════════════════════════════════════════════════════
# ROUND-6 补收（codex 第六轮·2 safety-adjacent blocker）：
#  ① merge() 别名投影层（rdp.py:339）在 tuple 守卫后对 legacy scalar alias 做 str()——
#     dict deployment_plan/monitor_plan/research_graph_ref → 伪造非空 ref 洗白 live 门 + 进 runner。
#  ② _build_promotion 仍对 asset_ref str()——asset_ref 无 RDP 侧 allowlist，畸形输入 str-repr 恰等于
#     合法 asset_ref 即洗白晋级追溯门。改 exact-str + section17 捕获 fail-closed。
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "alias_field", ["deployment_plan", "monitor_plan", "research_graph_ref"], ids=["deploy", "monitor", "graph"]
)
@pytest.mark.parametrize("bad", [{"fake": "x"}, ["x"], 123], ids=["dict", "list", "int"])
def test_merge_alias_scalar_coercion_rejected(alias_field, bad):
    """★ blocker①：merge 别名源非 str → 构造即拒（不 str-coerce 成伪造 canonical ref 洗白 live 门）。"""

    with pytest.raises(TypeError, match="alias source must be a string"):
        RDPManifest(**_base_kwargs(**{alias_field: bad}))


def test_merge_alias_honest_str_projects_ok():
    """诚实 str 别名 → 照常投影成 canonical ref（不误伤）。"""

    m = RDPManifest(**_base_kwargs(deployment_plan="deploy::p", monitor_plan="mon::p"))
    assert m.deployment_refs == ("deploy::p",) and m.monitor_refs == ("mon::p",)


def _section17_manifest_with_promotion_asset_ref(raw_asset_ref):
    from app.release_gate.section17_rdp_gate import SECTION17_RDP_MANIFEST_KEY
    base_rdp = {
        "asset_ref": "123", "asset_kind": "factor", "artifact_hash": "sha256:a",
        "reproducibility_command": "c",
        "dataset_versions": [{"dataset_id": "ds", "version": "v1", "manifest_sha256": "h"}],
        "ingestion_skill_refs": ["s"], "unverified_residual": ["r"],
    }
    return {"run_id": "r", "status": "completed", SECTION17_RDP_MANIFEST_KEY: {
        "rdp": base_rdp,
        "promotion": {"asset_ref": raw_asset_ref, "asset_kind": "factor", "rdp_ref": "placeholder"},
    }}


@pytest.mark.parametrize("raw", [123, {"x": 1}, ["123"]], ids=["int", "dict", "list"])
def test_promotion_asset_ref_str_laundering_closed(raw):
    """★ blocker②：非 str promotion.asset_ref（str-repr 恰匹配合法 asset_ref）→ section17 fail-closed
    （malformed·不洗白追溯门·不 uncaught 崩）。"""

    from app.release_gate.section17_rdp_gate import section17_rdp_check
    res = section17_rdp_check(_section17_manifest_with_promotion_asset_ref(raw))
    assert res.ok is False and "section17_rdp_promotion_malformed" in res.missing
