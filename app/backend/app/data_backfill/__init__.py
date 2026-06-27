"""数据补充（backfill）· 把全量历史拉到本地，统一读取接口。

- binance：Binance Vision 月 zip(全历史) + 日 zip(近月) → 解压 → 拼接连续序列 → parquet → 统一读取
- tushare：全 A股接口 × 全标的，走现有 TokenPool 限流，断点续传

下载/拉取均可注入（fetch/call 回调），便于无网络单测。
"""

from __future__ import annotations

__all__ = ["binance", "tushare"]
