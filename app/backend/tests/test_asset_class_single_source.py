"""单一身份源不变量：strategy_goal.AssetClass（窄·成本派发）⊆ research_os.asset_class.AssetClass（§0 全资产目录）。

`research_os/asset_class.py` 声明窄枚举与广目录「token 兼容且为其超集」（扩展不替换·不改既有窄枚举）。
本测试把这条**文档声明**变成**机器可证不变量**：防止两个 AssetClass 静默漂移——窄枚举若新增一个
不在 §0 全目录里的 token，就是单一身份源被破坏（双枚举漂移），CI 必抓。

GOAL §0 行 5（全资产目录：股票/债券/外汇/期货/期权/加密…）+ §11 数据层 typed 本体。
注：C-S11 把广目录从 orphan instruments/spec.py 上移 research_os.asset_class 作单一源（spec.py 已删）；
「下游回填到广目录」是作者刻意 deferred 的更大 ripple 重构（守扩展不替换），不在本不变量 scope。
"""

from typing import get_args

from app.research_os.asset_class import AssetClass as BroadAssetClass
from app.strategy_goal import AssetClass as NarrowAssetClass


def _vals(literal) -> set[str]:
    return set(get_args(literal))


def test_narrow_asset_class_is_subset_of_broad_catalog() -> None:
    """窄枚举（成本派发）必须是广 §0 全目录的子集——否则单一身份源被破坏。"""
    narrow = _vals(NarrowAssetClass)
    broad = _vals(BroadAssetClass)
    assert narrow, "窄 AssetClass 不应为空"
    assert broad, "广 §0 全目录 AssetClass 不应为空"
    missing = narrow - broad
    assert not missing, (
        f"单一身份源破坏：strategy_goal.AssetClass 含 §0 全目录之外的 token {sorted(missing)} —— "
        "窄枚举必须是 research_os.asset_class.AssetClass 的子集（token 兼容超集单一源 @ research_os/asset_class.py）"
    )


def test_broad_catalog_is_strict_superset() -> None:
    """广目录是真超集（§0 覆盖全公开二级市场 + Observable + custom），不退化成与窄枚举等同。"""
    narrow = _vals(NarrowAssetClass)
    broad = _vals(BroadAssetClass)
    assert broad - narrow, "广目录应严格大于窄枚举（§0 全资产目录 ≠ 4 类成本派发子集）"


def test_documented_narrow_tokens_present_in_broad() -> None:
    """文档声明的 4 个窄 token 逐一在广目录在场（防广目录改名漂移）。"""
    broad = _vals(BroadAssetClass)
    for tok in ("equity_cn", "crypto_spot", "crypto_perp", "mixed"):
        assert tok in broad, f"§0 全目录缺成本派发 token {tok!r}（窄↔广 token 漂移）"
