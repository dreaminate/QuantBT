"""数据平台 v2 · 官方数据更新通道（打包/manifest/增量）测试。"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from app.data_packages import apply_package, build_package_zip, official_manifest, plan_update, pull_and_apply


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


def test_apply_package_extracts_official_and_merges_fields(tmp_path: Path) -> None:
    src = tmp_path / "server"
    files = _make_files(src)
    manifest = official_manifest(files, src)
    manifest["official_fields"] = [
        {"field_id": "official_close", "market": "stocks_cn", "canonical_id": "close", "is_freeform": False,
         "is_official": True, "source": "tushare", "data_kind": "ohlcv", "raw_column": "close", "unit": "", "description": "收盘价"}
    ]
    pkg = tmp_path / "pkg.zip"
    build_package_zip(files, src, pkg, manifest=manifest)

    dest = tmp_path / "client"
    report = apply_package(pkg, dest)
    assert any("stocks_cn/ohlcv/latest" in f for f in report["applied_files"])
    assert (dest / report["applied_files"][0]).exists()           # 文件真解压进客户端数据湖
    assert not any("user_myapi" in f for f in report["applied_files"])  # 用户源不在包里
    assert report["official_fields"][0]["field_id"] == "official_close"  # 官方字段定义随包带来供合并


def test_apply_package_blocks_zip_slip(tmp_path: Path) -> None:
    mal = tmp_path / "mal.zip"
    with zipfile.ZipFile(mal, "w") as z:
        z.writestr("manifest.json", json.dumps({"data_version": "x"}))
        z.writestr("../../evil.txt", "pwned")
    dest = tmp_path / "client"
    report = apply_package(mal, dest)
    assert "../../evil.txt" in report["skipped"]
    assert not (tmp_path / "evil.txt").exists()      # 没逃逸出 data_root
    assert not (dest.parent / "evil.txt").exists()


def test_plan_update_diff() -> None:
    local = [{"path": "data/market/stocks_cn/ohlcv/latest/symbol=X/d.csv", "fingerprint": "2024-01-01T00:00:00Z|1"}]
    upstream = {
        "data_version": "v2",
        "files": [
            {"path": "data/market/stocks_cn/ohlcv/latest/symbol=X/d.csv", "fingerprint": "2024-01-02T00:00:00Z|2"},
            {"path": "data/market/stocks_cn/ohlcv/latest/symbol=Y/d.csv", "fingerprint": "z|1"},
        ],
    }
    plan = plan_update(local, upstream)
    assert plan["needs_update"] and plan["changed_count"] == 2 and plan["upstream_version"] == "v2"


def test_pull_and_apply_with_fake_http(tmp_path: Path) -> None:
    src = tmp_path / "server"
    files = _make_files(src)
    pkg = tmp_path / "pkg.zip"
    build_package_zip(files, src, pkg)

    class _FakeResp:
        content = pkg.read_bytes()

        def raise_for_status(self) -> None:
            pass

    class _FakeHttp:
        def get(self, url, params=None, timeout=None):  # noqa: ANN001
            return _FakeResp()

    dest = tmp_path / "client"
    report = pull_and_apply("https://up.example", dest, http=_FakeHttp())
    assert any("stocks_cn/ohlcv/latest" in f for f in report["applied_files"])
    assert (dest / report["applied_files"][0]).exists()
