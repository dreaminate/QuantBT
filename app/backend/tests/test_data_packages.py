"""数据平台 v2 · 官方数据更新通道（打包/manifest/增量）测试。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.data_packages import build_package_zip, official_manifest


def _make_files(root: Path) -> list[dict]:
    off = root / "data" / "market" / "stocks_cn" / "ohlcv" / "latest" / "symbol=X" / "d.csv"
    off.parent.mkdir(parents=True, exist_ok=True)
    off.write_text("ts,close\n2024-01-01,10\n", encoding="utf-8")
    usr = root / "data" / "market" / "stocks_cn" / "user_myapi" / "ohlcv" / "u.csv"
    usr.parent.mkdir(parents=True, exist_ok=True)
    usr.write_text("ts,close\n2024-01-01,9\n", encoding="utf-8")
    return [
        {"market": "stocks_cn", "data_kind": "ohlcv", "interval": "1d", "symbol_key": "X",
         "file_path": str(off), "columns": ["ts", "close"], "row_count": 1, "updated_at": "2024-01-01T00:00:00Z"},
        {"market": "stocks_cn", "data_kind": "ohlcv", "interval": "1d", "symbol_key": "U",
         "file_path": str(usr), "columns": ["ts", "close"], "row_count": 1, "updated_at": "2024-01-01T00:00:00Z"},
    ]


def test_manifest_official_only_and_versioned(tmp_path: Path) -> None:
    files = _make_files(tmp_path)
    m = official_manifest(files, tmp_path)
    assert m["channel"] == "official-data"
    paths = {f["path"] for f in m["files"]}
    assert any("stocks_cn/ohlcv/latest" in p for p in paths)   # 官方文件入包
    assert not any("user_myapi" in p for p in paths)            # 用户源文件不下发
    assert m["file_count"] == 1
    assert len(m["data_version"]) == 16
    # 指纹不变 → 数据版本号稳定（客户端据此判断"有无更新"）
    assert official_manifest(files, tmp_path)["data_version"] == m["data_version"]


def test_build_zip_full_and_incremental(tmp_path: Path) -> None:
    files = _make_files(tmp_path)
    full = tmp_path / "full.zip"
    build_package_zip(files, tmp_path, full)
    with zipfile.ZipFile(full) as z:
        names = z.namelist()
        assert "manifest.json" in names
        assert any("stocks_cn/ohlcv/latest" in n for n in names)
        assert not any("user_myapi" in n for n in names)

    sub = build_package_zip(files, tmp_path, full)
    off_rel = sub["files"][0]["path"]
    inc = tmp_path / "inc.zip"
    sub2 = build_package_zip(files, tmp_path, inc, rel_paths=[off_rel])
    assert sub2["partial"] is True and len(sub2["files"]) == 1
    with zipfile.ZipFile(inc) as z:
        assert off_rel in z.namelist()
