"""脊柱第 0 层 · 内容寻址身份的【唯一】定义源。

为什么只有这一个文件（决策 S1/S2 + 复用原则 S4）：
- 复核 `00-contracts-and-coherence.md` §1.2-A 抓出 config_hash 双产方（03 `[:16]` vs
  05 `cfg_+[:24]`）——同一策略两个 hash，R8「同一本账」当场裂开。裁定：**权威归此处，
  05 复用不自立、截断回 16 位、保留 `cfg_v1_` 版本前缀**。
- 01 内核的 `node_id`、03 谱系的 `content_hash`/Entity id、05 的 `config_hash`、02 的
  `fixture_key` 全部出自这里，同 `sha256(...)[:16]` 哈希族。

哈希长度 16 位是全库不变量（沿用 `data_packages.py:70` 既有约定 `sha256(...)[:16]`）。

诚实边界：`config_hash` 只能识别「同一公式的语法级同义」（空格/括号/键序/Unicode），
**识别不了语义级同义**（如 `a*2` ≡ `a+a`）——那一层靠下游 N_eff 收益序列相关聚类
（05 算法层）兜底。本模块绝不声称能去语义重。
"""

from __future__ import annotations

import ast
import hashlib
import unicodedata
from typing import Any


# 全库哈希长度不变量（= data_packages.py:70 的 sha256(...)[:16]）。
# 复核 §1.2-B：05 的 [:24] 是硬错，全库一律 16。改这里 = 改全脊柱身份口径，须慎。
HASH_LEN = 16

# config_hash 的版本化命名空间前缀（决策 S1：保留 05 的版本化思想，上移进权威定义）。
# 口径若变（如归一化算法升级），把 v1 → v2，旧账本条目仍可凭前缀区分世代。
CONFIG_HASH_PREFIX = "cfg_v1_"

# fixture_key 是 node_id 的带前缀别名（复核 §1.2-E）：02 的 LLM fixture 用它，
# 03 把它当 PROV Activity id 时一律先 strip 前缀再比对，保证「fixture_key 即 node_id」。
FIXTURE_PREFIX = "llmfx-"

# 纯装饰字段——它们不改变「这是第几次试同一个想法」/「这是不是同一个节点」。
# 复核 C2：name/desc/tags 入哈希会让「改个名字」被误算成新试验，honest-N 虚高。
# 单一源（决策 S1 / 复核开放问题 #1）：config_hash 与内核 node_id 的 _io_normalize 共用这一份
# 排除集，否则两边「同一想法 / 同一节点」的判定会分叉。
DECORATIVE_KEYS = frozenset({"name", "description", "desc", "tags", "note", "comment"})
_CONFIG_EXCLUDED_KEYS = DECORATIVE_KEYS  # 向后兼容的私有别名


def _nfc(value: Any) -> Any:
    """递归把所有字符串归一到 Unicode NFC。

    没有这一步，视觉相同但码点不同的字符串（NFC vs NFD）会产生两个 config_hash，
    honest-N 被悄悄高估——复核 §2.3 T5 点名的真实失效模式。
    """

    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {_nfc(k): _nfc(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_nfc(v) for v in value]
    return value


def canonical_json(obj: Any) -> str:
    """确定性 JSON：键序无关 + NFC 归一 + 无空白歧义。

    `sort_keys=True` 消键序、`_nfc` 消 Unicode 歧义、`separators` 去多余空白。
    这是所有内容寻址哈希的唯一入口——两份逻辑相同的输入必产生逐字节相同的串。
    """

    import json

    return json.dumps(_nfc(obj), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:HASH_LEN]


def content_hash(obj: Any) -> str:
    """工件/卡冻结内容指纹（复核 C4）。16 位，无前缀。"""

    return _sha16(canonical_json(obj))


def node_id(*, structure: Any, inputs: Any, upstream: list[str] | tuple[str, ...] | None = None) -> str:
    """内核 DAG 节点的内容寻址身份（复核 C7）。

    node_id = sha256(canonical_json({structure, inputs, sorted(upstream)}))[:16]。
    - 上游身份进哈希 → 内容寻址（上游变则本节点 id 变 → durable execution 正确失效缓存）。
    - 与 content_hash 同哈希族；checkpoint_id == node_id（复核 §1.2-C）。
    - durable ≠ reproducible：node_id 稳定让重放复用工件，不等于重跑能逐位重现（R11）。
    """

    payload = {
        "structure": structure,
        "inputs": inputs,
        "upstream": sorted(upstream or []),
    }
    return _sha16(canonical_json(payload))


def normalize_factor_ast(factor: Any) -> str:
    """把因子归一到「语法无关」的规范串，作为 config_hash 的因子输入预处理（决策 S1）。

    - 字符串公式：`ast.parse(mode="eval")` 后 `ast.dump` → 消掉空格/括号/写法级差异
      （`a * 2` ≡ `a*2` ≡ `(a*2)`）。
    - 解析不了的（非表达式策略、dict 配置等）：退化为 `__raw__:<canonical_json>`，
      仍确定性、仍可哈希（复用 05 的退化分支思想，对非公式策略更鲁棒）。

    明确不做的事：识别语义同义（`a*2` ≡ `a+a`）——交给下游 N_eff 收益聚类。
    """

    if isinstance(factor, str):
        try:
            tree = ast.parse(factor, mode="eval")
            return "ast:" + ast.dump(tree, annotate_fields=False)
        except SyntaxError:
            return "__raw__:" + canonical_json(factor)
    return "__raw__:" + canonical_json(factor)


def config_hash(
    *,
    factor: Any,
    params: Any = None,
    universe: Any = None,
    dataset_version: str | None = None,
    freq: str | None = None,
    label: Any = None,
) -> str:
    """试验配置簇的去重/计数键——honest-N 的最小单元（复核 C2，决策 S1 权威定义）。

    带 `cfg_v1_` 前缀 + 16 位哈希。回答「这是第几次试同一个想法」：
    - 因子经 `normalize_factor_ast` 消语法级差异；
    - `dataset_version`/`freq`/`universe` 入哈希 → 换数据集/频率/票池反复试都算新 trial
      （防换数据集刷 N）；
    - 纯装饰字段（name/desc/tags...）被排除，改名不算新试验。

    05、03、04、07 一律 import 此函数，禁止任何部件重写第二套算法。
    """

    payload: dict[str, Any] = {
        "factor": normalize_factor_ast(factor),
        "params": _strip_decorative(params),
        "universe": universe,
        "dataset_version": dataset_version,
        "freq": freq,
        "label": label,
    }
    return CONFIG_HASH_PREFIX + _sha16(canonical_json(payload))


def _strip_decorative(params: Any) -> Any:
    """从 params 里剔除纯装饰键（递归一层）——它们不改变「试的是哪个想法」。"""

    if isinstance(params, dict):
        return {k: v for k, v in params.items() if k not in _CONFIG_EXCLUDED_KEYS}
    return params


def fixture_key(nid: str) -> str:
    """LLM record/replay fixture 的键 = node_id 的带前缀别名（复核 §1.2-E）。"""

    return FIXTURE_PREFIX + nid


def strip_fixture_prefix(key: str) -> str:
    """把 fixture_key 还原成裸 node_id（03 当 PROV Activity id 比对前必调）。"""

    return key[len(FIXTURE_PREFIX):] if key.startswith(FIXTURE_PREFIX) else key
