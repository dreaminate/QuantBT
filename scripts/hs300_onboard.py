#!/usr/bin/env python3
"""HS300 十年真数据证据链 CLI（research/backtest-only；A股永不实盘）。

子命令:
    keygen     生成 provenance HMAC key 存 keyring(只打印 sha256 指纹,绝不打印 key)
    pull       Tushare 全量回填 staging(token 走 keyring;限流+退避+幂等续拉)
    preflight  staging → 面板逐项自检报告(不签名、不落库)
    build      staging → preflight → DatasetVersion+manifest → 签名 universe+receipt
    bench      按证据链跑 perf-harness HS300 探针(key 从 keyring 取,不进 argv/stdout)

密钥红线:Tushare token 与 provenance key 均只经 keyring;本 CLI 任何输出不含明文。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets as _secrets
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

# 隔离默认 DATA_ROOT 绑定(app.paths 在 import 时解析);build/bench 均显式传路径。
os.environ.setdefault("BACKTEST_DATA_ROOT", tempfile.mkdtemp(prefix="hs300-onboard-"))


def _keystore():
    from app.security.keystore import SecureKeystore

    return SecureKeystore.open(prefer="keyring")


def _fetch_key(name: str) -> str:
    record = _keystore().fetch(name)
    if record is None or not record.api_key:
        raise SystemExit(f"keyring 无 {name!r},先跑: hs300_onboard.py keygen --key-name {name}")
    return record.api_key


def cmd_keygen(args: argparse.Namespace) -> int:
    from app.security.keystore import KeystoreRecord

    ks = _keystore()
    existing = None
    try:
        existing = ks.fetch(args.key_name)
    except Exception:
        existing = None
    if existing is not None and not args.rotate:
        print(
            f"{args.key_name} 已存在(拒绝覆盖,--rotate 才轮换); "
            f"fingerprint={hashlib.sha256(existing.api_key.encode('utf-8')).hexdigest()}"
        )
        return 0
    key = _secrets.token_urlsafe(48)
    ks.store(
        KeystoreRecord(
            name=args.key_name,
            api_key=key,
            api_secret=key,
            note="HS300 perf provenance HMAC key (operator_attested)",
        )
    )
    print(
        f"key stored to keyring name={args.key_name}; "
        f"verification_key_sha256={hashlib.sha256(key.encode('utf-8')).hexdigest()}"
    )
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    import tushare as ts

    from app.data_onboarding.hs300_fetch import fetch_raw_hs300

    token = _fetch_key(args.token_name)
    pro = ts.pro_api(token)
    result = fetch_raw_hs300(
        args.staging_dir,
        pro=pro,
        start_compact=args.start.replace("-", ""),
        end_compact=args.end.replace("-", ""),
        progress=print,
    )
    assert token not in str(result), "内部错误:token 泄入输出,拒绝打印"
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_preflight(args: argparse.Namespace) -> int:
    from app.data_onboarding import assemble_panel, load_list_dates, load_members
    from app.data_onboarding import preflight_report

    members = load_members(args.staging_dir, args.snapshot)
    list_dates = load_list_dates(args.staging_dir, members)
    frame = assemble_panel(
        args.staging_dir, members=members, start_date=args.start, end_date=args.end
    )
    report = preflight_report(frame, list_dates)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0 if report["ok"] else 2


def cmd_build(args: argparse.Namespace) -> int:
    from app.data_onboarding import build_chain

    key = _fetch_key(args.key_name)
    result = build_chain(
        args.staging_dir,
        registry_path=args.registry_path,
        panel_path=args.panel_path,
        out_dir=args.out_dir,
        key=key,
        root_id=args.root_id,
        key_id=args.key_id,
        snapshot_yyyymm=args.snapshot,
        start_date=args.start,
        end_date=args.end,
        as_of_date=args.as_of,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    assert key not in text, "内部错误:key 泄入输出,拒绝打印"
    print(text)
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(BACKEND / "tests" / "benchmark"))
    import perf_harness as ph

    key = _fetch_key(args.key_name)
    measurement = ph.measure_hs300_10y_daily_read(
        dataset_path=args.panel_path,
        registry_path=args.registry_path,
        dataset_version_ref=args.dataset_version_ref,
        provenance_receipt_path=args.receipt_path,
        universe_snapshot_path=args.universe_path,
        provenance_key=key,
    )
    payload = {
        "measured": measurement.measured,
        "observed_seconds": measurement.observed_seconds,
        "threshold_seconds": measurement.threshold_seconds,
        "unavailable_reason": measurement.unavailable_reason,
        "detail": measurement.detail,
        "evidence_ref": measurement.evidence_ref,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    assert key not in text, "内部错误:key 泄入输出,拒绝打印"
    print(text)
    return 0 if measurement.measured else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_key = sub.add_parser("keygen", help="生成 provenance key 入 keyring")
    p_key.add_argument("--key-name", default="hs300_provenance")
    p_key.add_argument("--rotate", action="store_true")
    p_key.set_defaults(fn=cmd_keygen)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--staging-dir", required=True)
    common.add_argument("--snapshot", default="202606")
    common.add_argument("--start", default="2016-06-01")
    common.add_argument("--end", default="2026-06-30")

    p_pull = sub.add_parser("pull", parents=[common], help="Tushare 回填 staging")
    p_pull.add_argument("--token-name", default="tushare")
    p_pull.set_defaults(fn=cmd_pull)

    p_pre = sub.add_parser("preflight", parents=[common], help="面板自检(不签名)")
    p_pre.set_defaults(fn=cmd_preflight)

    p_build = sub.add_parser("build", parents=[common], help="组链+签名")
    p_build.add_argument("--registry-path", required=True)
    p_build.add_argument("--panel-path", required=True)
    p_build.add_argument("--out-dir", required=True)
    p_build.add_argument("--as-of", default="2026-06-30")
    p_build.add_argument("--key-name", default="hs300_provenance")
    p_build.add_argument("--root-id", default="quantbt-hs300-operator-root-v1")
    p_build.add_argument("--key-id", default="hs300-provenance-2026-07")
    p_build.set_defaults(fn=cmd_build)

    p_bench = sub.add_parser("bench", help="跑 harness HS300 探针")
    p_bench.add_argument("--panel-path", required=True)
    p_bench.add_argument("--registry-path", required=True)
    p_bench.add_argument("--dataset-version-ref", required=True)
    p_bench.add_argument("--receipt-path", required=True)
    p_bench.add_argument("--universe-path", required=True)
    p_bench.add_argument("--key-name", default="hs300_provenance")
    p_bench.set_defaults(fn=cmd_bench)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
