"""数据平台 v2 · 官方数据集统一接入口。

「官方加密数据库」≠ Binance —— 它是一个**可增长的官方源集合**。团队爬虫
（链上 / 衍生品聚合 / 情绪 / 新闻 …）爬来的数据，通过 ``register_official_dataset``
落进数据湖（宽字段 parquet）+ 注册进 ``DatasetRegistry``（带 source_name），
与 connector 同构地被 ``FieldCatalog`` 收编、被源开关（P3）治理。

真实爬虫只需：① 产出一个 ``ts × symbol`` 的 polars 宽表 ② 调一次 register_official_dataset。
"""

from __future__ import annotations

import re
from pathlib import Path

import polars as pl

from ..connectors.base import make_wide_fetch_result
from ..data_quality import DatasetRegistry, DatasetVersion

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(value: str) -> str:
    return _SAFE.sub("_", str(value).strip()).strip("._") or "x"


def register_official_dataset(
    registry: DatasetRegistry,
    *,
    source_name: str,
    market: str,
    data_kind: str,
    frame: pl.DataFrame,
    data_root: Path | str,
    interval: str | None = None,
    dataset_id: str | None = None,
    symbols: list[str] | None = None,
) -> DatasetVersion:
    """把一份宽表注册为官方数据集：落 parquet + 写 DatasetRegistry（含 source_name + 列清单）。

    与 connector 拉取等价的"官方源"接入路径，爬虫源即走这里。返回不可变 DatasetVersion。
    """

    did = dataset_id or "__".join([_slug(source_name), _slug(market), _slug(data_kind)] + ([_slug(interval)] if interval else []))
    out_dir = Path(data_root) / "market" / _slug(market) / _slug(source_name) / _slug(data_kind)
    if interval:
        out_dir = out_dir / _slug(interval)
    out_dir.mkdir(parents=True, exist_ok=True)

    fr = make_wide_fetch_result(frame, source_name=source_name)  # 保留全部宽字段，不投影
    path = out_dir / f"{fr.sha256[:12]}.parquet"
    frame.write_parquet(path)

    meta: dict = {"market": market, "data_kind": data_kind}
    if interval:
        meta["interval"] = interval
    if symbols:
        meta["symbols"] = list(symbols)
    # register 会自动把 frame.columns 落进 metadata["columns"]
    return registry.register(did, fr, file_paths=[str(path)], metadata=meta)


def example_onchain_crawler_intake(registry: DatasetRegistry, *, data_root: Path | str) -> DatasetVersion:
    """示例（stub）：把一份链上指标爬取结果接入官方加密库。

    真实爬虫把下面的占位 frame 换成真正爬下来的数据即可——其余接入逻辑完全复用。
    """

    frame = pl.DataFrame(
        {
            "ts": [],
            "symbol": [],
            "market": [],
            "interval": [],
            "mvrv": [],
            "sopr": [],
            "active_addresses": [],
        }
    )
    return register_official_dataset(
        registry,
        source_name="crawler_onchain",
        market="binanceusdm",
        data_kind="onchain_metrics",
        frame=frame,
        interval="1d",
        data_root=data_root,
    )


__all__ = ["register_official_dataset", "example_onchain_crawler_intake"]
