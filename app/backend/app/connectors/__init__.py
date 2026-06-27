"""DataConnector framework — 统一抽象 + 内置 connector + DIY YAML connector + 用户上传。

参见 QuantBT-GOAL.md §M3 与 §5。Connector 是数据接入的"独立单元"，前端 +
Agent + Job 编排都通过同一个 `registry` 拿 connector，新增数据源不改主流程。
"""

from __future__ import annotations

from .base import (
    UNIFIED_OHLCV_COLUMNS,
    UNIFIED_OHLCV_SCHEMA,
    ConnectorCapability,
    ConnectorHealth,
    ConnectorRegistry,
    DataConnector,
    FetchRequest,
    FetchResult,
    enforce_unified_schema,
    make_fetch_result,
    registry,
)
from .binance_rest_connector import BinanceRESTConnector
from .binance_vision_connector import BinanceVisionConnector
from .generic_rest import GenericRESTConfig, GenericRESTConnector
from .stooq_connector import StooqConnector
from .tushare_connector import TushareConnector
from .user_upload import (
    UploadDatasetRegistration,
    UploadFieldMapping,
    UserUploadConnector,
    load_registration,
    write_registration,
)


def _bootstrap_default_registry() -> ConnectorRegistry:
    """注册内置 connector singletons；用户自定义 connector 由 API 动态注册。"""

    registry.register_instance("tushare", TushareConnector())
    registry.register_instance("binance_vision_usdm", BinanceVisionConnector("binanceusdm"))
    registry.register_instance("binance_vision_spot", BinanceVisionConnector("binance_spot"))
    registry.register_instance("binance_rest_usdm", BinanceRESTConnector("binanceusdm"))
    registry.register_instance("binance_rest_spot", BinanceRESTConnector("binance_spot"))
    registry.register_instance("stooq", StooqConnector())
    return registry


_bootstrap_default_registry()


__all__ = [
    "BinanceRESTConnector",
    "BinanceVisionConnector",
    "ConnectorCapability",
    "ConnectorHealth",
    "ConnectorRegistry",
    "DataConnector",
    "FetchRequest",
    "FetchResult",
    "GenericRESTConfig",
    "GenericRESTConnector",
    "StooqConnector",
    "TushareConnector",
    "UNIFIED_OHLCV_COLUMNS",
    "UNIFIED_OHLCV_SCHEMA",
    "UploadDatasetRegistration",
    "UploadFieldMapping",
    "UserUploadConnector",
    "enforce_unified_schema",
    "load_registration",
    "make_fetch_result",
    "registry",
    "write_registration",
]
