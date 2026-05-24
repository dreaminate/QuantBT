from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


DEFAULT_MARKET_INTERVALS_BY_MARKET = {
    "binanceusdm": ("1m", "5m", "15m", "1h", "4h", "1d"),
    "stocks_us": ("15m", "1h", "1d"),
    "stocks_cn": ("15m", "1h", "1d"),
    "stocks_hk": ("15m", "1h", "1d"),
}


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @property
    def models(self) -> Path:
        return self.root / "models"

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @property
    def docs_architecture(self) -> Path:
        return self.docs / "architecture"

    @property
    def docs_guides(self) -> Path:
        return self.docs / "guides"

    @property
    def docs_operations(self) -> Path:
        return self.docs / "operations"

    @property
    def docs_reference(self) -> Path:
        return self.docs / "reference"

    @property
    def config(self) -> Path:
        return self.root / "config"

    @property
    def config_stock_pools(self) -> Path:
        return self.config / "stock_pools"

    @property
    def config_stock_pools_official(self) -> Path:
        return self.config_stock_pools / "official"

    @property
    def data(self) -> Path:
        return self.root / "data"

    @property
    def data_csv(self) -> Path:
        return self.data / "csv"

    @property
    def data_market(self) -> Path:
        return self.data / "market"

    @property
    def data_catalog(self) -> Path:
        return self.data / "catalog"

    @property
    def data_catalog_presets(self) -> Path:
        return self.data_catalog / "presets"

    @property
    def data_catalog_stock_pools(self) -> Path:
        return self.data_catalog / "stock_pools"

    @property
    def data_catalog_stock_pools_custom(self) -> Path:
        return self.data_catalog_stock_pools / "custom"

    @property
    def data_catalog_stock_pools_compat_marker(self) -> Path:
        return self.data_catalog_stock_pools / ".legacy_migrated"

    @property
    def data_catalog_inventory_file(self) -> Path:
        return self.data_catalog / "inventory.json"

    @property
    def market_binanceusdm(self) -> Path:
        return self.data_market / "binanceusdm"

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def bronze(self) -> Path:
        return self.data / "bronze"

    @property
    def curated(self) -> Path:
        return self.data / "curated"

    @property
    def artifacts(self) -> Path:
        return self.data / "artifacts"

    @property
    def strategy_outputs(self) -> Path:
        return self.data / "strategy_outputs"

    @property
    def model_outputs(self) -> Path:
        return self.data_csv / "model_outputs"

    @property
    def model_artifacts(self) -> Path:
        return self.data / "model_artifacts"

    @property
    def var(self) -> Path:
        return self.root / "var"

    @property
    def research_db(self) -> Path:
        return self.var / "research.duckdb"

    @property
    def frontend(self) -> Path:
        return self.root / "frontend"

    @property
    def frontend_dist(self) -> Path:
        return self.frontend / "dist"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def workspace_python(self) -> Path:
        return self.workspace / "python"

    @property
    def workspace_python_user(self) -> Path:
        return self.workspace_python / "quant1_user"

    @property
    def workspace_python_model(self) -> Path:
        return self.workspace_python / "model"

    @property
    def workspace_python_user_strategies(self) -> Path:
        return self.workspace_python_user / "strategies"

    @property
    def workspace_python_user_pipelines(self) -> Path:
        return self.workspace_python_user / "pipelines"

    @property
    def workspace_notebooks(self) -> Path:
        return self.workspace / "notebooks"

    @property
    def workspace_csv(self) -> Path:
        return self.data_csv

    @property
    def workspace_csv_raw(self) -> Path:
        return self.workspace_csv / "raw_inputs"

    @property
    def workspace_csv_features(self) -> Path:
        return self.workspace_csv / "feature_frames"

    @property
    def workspace_csv_model_outputs(self) -> Path:
        return self.workspace_csv / "model_outputs"

    @property
    def workspace_notebook_strategies(self) -> Path:
        return self.workspace_notebooks / "strategies"

    @property
    def workspace_notebook_pipelines(self) -> Path:
        return self.workspace_notebooks / "pipelines"

    @property
    def pipeline_artifacts(self) -> Path:
        return self.artifacts / "pipeline_runs"

    def ensure(self) -> None:
        for path in [
            self.docs,
            self.docs_architecture,
            self.docs_guides,
            self.docs_operations,
            self.docs_reference,
            self.config,
            self.config_stock_pools,
            self.config_stock_pools_official,
            self.models,
            self.data_market,
            self.data_catalog,
            self.data_catalog_presets,
            self.data_catalog_stock_pools,
            self.data_catalog_stock_pools_custom,
            self.market_binanceusdm,
            self.raw,
            self.bronze,
            self.curated,
            self.model_outputs,
            self.model_artifacts,
            self.artifacts,
            self.strategy_outputs,
            self.pipeline_artifacts,
            self.var,
            self.workspace_python_user_strategies,
            self.workspace_python_user_pipelines,
            self.workspace_csv_raw,
            self.workspace_csv_features,
            self.workspace_csv_model_outputs,
            self.workspace_notebook_strategies,
            self.workspace_notebook_pipelines,
        ]:
            path.mkdir(parents=True, exist_ok=True)
        for market, intervals in DEFAULT_MARKET_INTERVALS_BY_MARKET.items():
            for interval in intervals:
                self.market_data_dir(market, interval).mkdir(parents=True, exist_ok=True)
        self._ensure_workspace_packages()

    def dataset_latest_dir(self, layer: str, dataset: str) -> Path:
        return getattr(self, layer) / dataset / "latest"

    def dataset_version_dir(self, layer: str, dataset: str, version_id: str) -> Path:
        return getattr(self, layer) / dataset / version_id

    def universe_dir(self, name: str) -> Path:
        return self.artifacts / "universe" / name

    def universe_latest_file(self, name: str) -> Path:
        return self.universe_dir(name) / "latest.parquet"

    def universe_snapshot_file(self, name: str, snapshot_id: str) -> Path:
        return self.universe_dir(name) / f"{snapshot_id}.parquet"

    def prescreen_dir(self, name: str) -> Path:
        return self.artifacts / "prescreens" / name

    def prescreen_latest_file(self, name: str) -> Path:
        return self.prescreen_dir(name) / "latest.parquet"

    def prescreen_snapshot_file(self, name: str, prescreen_id: str) -> Path:
        return self.prescreen_dir(name) / f"{prescreen_id}.parquet"

    def experiment_dir(self, run_id: str) -> Path:
        return self.artifacts / "experiments" / run_id

    def pipeline_run_dir(self, run_id: str) -> Path:
        return self.pipeline_artifacts / run_id

    def model_output_model_dir(self, model_name: str) -> Path:
        return self.model_outputs / model_name

    def model_output_version_dir(self, model_name: str, version: str) -> Path:
        return self.model_output_model_dir(model_name) / version

    def model_artifact_model_dir(self, model_name: str) -> Path:
        return self.model_artifacts / model_name

    def model_artifact_name_dir(self, model_name: str, artifact_name: str) -> Path:
        return self.model_artifact_model_dir(model_name) / artifact_name

    def model_artifact_version_dir(self, model_name: str, artifact_name: str, version: str) -> Path:
        return self.model_artifact_name_dir(model_name, artifact_name) / version

    def market_data_dir(self, market: str, interval: str) -> Path:
        return self.data_market / market / interval

    def market_dataset_dir(self, market: str, data_kind: str) -> Path:
        return self.data_market / market / data_kind

    def market_dataset_latest_dir(self, market: str, data_kind: str) -> Path:
        return self.market_dataset_dir(market, data_kind) / "latest"

    def market_dataset_partition_dir(self, market: str, data_kind: str, *partition_parts: str) -> Path:
        target = self.market_dataset_latest_dir(market, data_kind)
        for part in partition_parts:
            target = target / part
        return target

    def market_dataset_partition_file(
        self,
        market: str,
        data_kind: str,
        *partition_parts: str,
        file_name: str = "data.csv",
    ) -> Path:
        return self.market_dataset_partition_dir(market, data_kind, *partition_parts) / file_name

    def market_data_file(
        self,
        market: str,
        interval: str,
        symbol_key: str,
        *,
        file_format: str = "csv",
    ) -> Path:
        return self.market_data_dir(market, interval) / f"{symbol_key}.{file_format}"

    def reset_latest_dir(self, target: Path, source: Path) -> None:
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

    def _ensure_workspace_packages(self) -> None:
        for package_dir in [
            self.workspace_python_model,
            self.workspace_python_user,
            self.workspace_python_user_strategies,
            self.workspace_python_user_pipelines,
        ]:
            package_dir.mkdir(parents=True, exist_ok=True)
            init_file = package_dir / "__init__.py"
            if not init_file.exists():
                init_file.write_text("", encoding="utf-8")


def project_paths(root: Path | None = None) -> ProjectPaths:
    base = Path(root or os.getenv("QUANT1_ROOT") or Path.cwd()).resolve()
    return ProjectPaths(root=base)


def qb_project_paths() -> ProjectPaths:
    """qb / 1Backtest：数据根目录为项目下的 ``data``（与 BACKTEST_DATA_ROOT 一致）。"""
    from ..paths import PROJECT_ROOT

    return ProjectPaths(root=PROJECT_ROOT)
