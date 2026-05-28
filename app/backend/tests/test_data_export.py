from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from app.data_export import estimate_export_size, export_tar_gz_stream, iter_export_files


def _populate(root: Path) -> None:
    (root / "datasets").mkdir(parents=True)
    (root / "datasets" / "registry.jsonl").write_text("{}\n", encoding="utf-8")
    (root / "experiments").mkdir()
    (root / "experiments" / "runs.jsonl").write_text("{}\n", encoding="utf-8")
    # 模拟一个 run 目录
    run_dir = root / "artifacts" / "experiments" / "demo"
    run_dir.mkdir(parents=True)
    (run_dir / "run.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "portfolio.csv").write_text("ts,equity\n2024,1.0\n", encoding="utf-8")
    # 这个不该入 export
    (root / "raw").mkdir()
    (root / "raw" / "huge.bin").write_bytes(b"x" * 1000)
    # secrets 也不该入
    (root / "secrets.yaml").write_text("tushare: {token: secret}", encoding="utf-8")


def test_iter_export_files_includes_expected_excludes_sensitive(tmp_path: Path) -> None:
    _populate(tmp_path)
    files = list(iter_export_files(tmp_path))
    names = [arc for _, arc in files]
    assert any("datasets/registry.jsonl" in n for n in names)
    assert any("experiments/runs.jsonl" in n for n in names)
    assert any("artifacts/experiments/demo/run.json" in n for n in names)
    # raw / secrets 都不在
    assert not any("raw" in n.split("/") for n in names)
    assert not any(n.endswith("secrets.yaml") for n in names)


def test_estimate_export_size(tmp_path: Path) -> None:
    _populate(tmp_path)
    stats = estimate_export_size(tmp_path)
    assert stats["file_count"] >= 4
    assert stats["total_bytes"] > 0
    assert "datasets" in stats["by_section"]


def test_export_tar_gz_stream_produces_valid_tar(tmp_path: Path) -> None:
    _populate(tmp_path)
    chunks = b"".join(export_tar_gz_stream(tmp_path))
    assert chunks.startswith(b"\x1f\x8b")  # gzip magic
    bio = io.BytesIO(chunks)
    with tarfile.open(fileobj=bio, mode="r:gz") as tar:
        names = tar.getnames()
    assert any("MANIFEST.txt" in n for n in names)
    assert any("registry.jsonl" in n for n in names)
    # 敏感文件确认未入包
    assert not any(n.endswith("secrets.yaml") for n in names)
