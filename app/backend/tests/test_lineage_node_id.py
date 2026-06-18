"""脊柱第 0 层 · node_id 单一身份源的【对抗式】测试。

验收标准（决策记录 §0.1 / 复核 §任务2）：不是「测函数跑通」，而是「种一个已知的坏，
门必须抓住，否则门是纸做的」。每条都种一个会让 honest-N 失真/身份口径裂开的坏，断言被抓。
"""

from __future__ import annotations

import pytest

from app.lineage import ids as nid


# ── T-NID-1 内容寻址不变量：装饰字段不改 id、真实输入改 id ──────────────────
def test_decorative_fields_excluded_real_inputs_change_hash():
    base = dict(factor="rank(close)", params={"win": 5}, universe="csi300", dataset_version="ds_a", freq="1d", label="ret1")
    h0 = nid.config_hash(**base)

    # 种坏①：只加 name/desc/tags（纯装饰）—— 若它们入哈希，改名会被误算成新试验、honest-N 虚高
    h_decor = nid.config_hash(**{**base, "params": {"win": 5, "name": "我的动量", "tags": ["v2"], "note": "试试"}})
    assert h_decor == h0, "装饰字段改变了 config_hash → honest-N 会被改名刷高（门坏）"

    # 种坏②：换数据集是真实差异 —— 若不入哈希，换数据集反复试不计 N（刷 N 漏洞）
    h_ds = nid.config_hash(**{**base, "dataset_version": "ds_b"})
    assert h_ds != h0, "换 dataset_version 没改 config_hash → 可换数据集刷 N（门坏）"

    # 真实参数变 → 必变
    assert nid.config_hash(**{**base, "params": {"win": 10}}) != h0


# ── T-NID-2 键序 + Unicode(NFC/NFD) 不变量：视觉相同必同 hash ────────────────
def test_key_order_and_unicode_nfc_invariant():
    # 键序不同、逻辑相同 → 必同 hash（否则同一想法被数两次）
    a = nid.canonical_json({"b": 1, "a": 2, "c": {"y": 1, "x": 2}})
    b = nid.canonical_json({"a": 2, "c": {"x": 2, "y": 1}, "b": 1})
    assert a == b, "键序敏感 → honest-N 高估（门坏）"

    # NFC vs NFD：'é' 的合成码点 vs 分解码点，视觉相同 → 必同 hash
    nfc = "café"                      # U+00E9
    nfd = "café"               # 'e' + U+0301 组合重音
    assert nfc != nfd                # 字节不同
    assert nid.content_hash({"x": nfc}) == nid.content_hash({"x": nfd}), "Unicode 未归一 → 同名两 hash（门坏）"


# ── T-NID-3 全库 16 位截断不变量：堵 05 的 [:24] 回退 ───────────────────────
def test_hash_length_invariant_blocks_24bit_regression():
    h = nid.config_hash(factor="a+b", dataset_version="ds")
    body = h[len(nid.CONFIG_HASH_PREFIX):]      # 去前缀后的哈希体
    assert len(body) == nid.HASH_LEN == 16, "config_hash 哈希体不是 16 位 → 复核 §1.2-B 硬错复活"
    assert len(nid.content_hash({"x": 1})) == 16
    assert len(nid.node_id(structure="bt", inputs={"a": 1})) == 16


# ── T-NID-4 config_hash 带版本前缀（决策 S1：版本化口径上移进权威定义）─────────
def test_config_hash_versioned_prefix():
    h = nid.config_hash(factor="a", dataset_version="ds")
    assert h.startswith("cfg_v1_"), "config_hash 缺版本前缀 → 口径升级时无法区分世代"


# ── T-NID-5 诚实边界：语法级同义【应】同 hash，语义级同义【不】同 hash ──────────
def test_syntactic_synonyms_collapse_semantic_do_not():
    # 语法级：空格/括号差异 → ast 归一后必同 hash
    h1 = nid.config_hash(factor="a * 2 + b", dataset_version="ds")
    h2 = nid.config_hash(factor="(a*2)+b", dataset_version="ds")
    assert h1 == h2, "ast 归一没消掉空格/括号级差异（normalize_factor_ast 坏）"

    # 语义级：a*2 vs a+a —— 本模块【诚实地】识别不了，必产生不同 hash
    h_mul = nid.config_hash(factor="a*2", dataset_version="ds")
    h_add = nid.config_hash(factor="a+a", dataset_version="ds")
    assert h_mul != h_add, (
        "若 a*2 与 a+a 同 hash，说明声称了它做不到的语义去重——"
        "语义同义必须留给下游 N_eff 收益聚类，本层不得假装能抓"
    )


# ── T-NID-6 退化分支：非表达式策略仍确定性可哈希 ───────────────────────────
def test_non_expression_factor_degrades_deterministically():
    cfg = {"kind": "lgbm", "features": ["mom", "vol"]}
    h_a = nid.config_hash(factor=cfg, dataset_version="ds")
    h_b = nid.config_hash(factor={"features": ["mom", "vol"], "kind": "lgbm"}, dataset_version="ds")  # 键序不同
    assert h_a == h_b, "非表达式策略退化分支不稳定 → 同配置两 hash"
    # 语法垃圾串也不该抛异常、要确定性退化
    assert nid.normalize_factor_ast("!!! not python @#$").startswith("__raw__:")


# ── T-NID-7 fixture_key 是 node_id 带前缀别名，strip 后可比对（复核 §1.2-E）──────
def test_fixture_key_is_prefixed_alias_of_node_id():
    n = nid.node_id(structure="llm_translate", inputs={"intent": "买动量"})
    fk = nid.fixture_key(n)
    assert fk == "llmfx-" + n
    assert nid.strip_fixture_prefix(fk) == n, "strip 后对不回 node_id → 03 当 Activity id 比对会断"
    assert nid.strip_fixture_prefix(n) == n   # 无前缀幂等


# ── T-NID-8 node_id 内容寻址：上游变则 id 变、上游序无关 ─────────────────────
def test_node_id_upstream_content_addressed():
    a = nid.node_id(structure="bt", inputs={"x": 1}, upstream=["n1", "n2"])
    b = nid.node_id(structure="bt", inputs={"x": 1}, upstream=["n2", "n1"])   # 序不同
    assert a == b, "upstream 顺序影响 node_id → 内容寻址不稳定"
    c = nid.node_id(structure="bt", inputs={"x": 1}, upstream=["n1", "n3"])   # 上游变
    assert c != a, "上游变了 node_id 没变 → durable 缓存不会正确失效（门坏）"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
