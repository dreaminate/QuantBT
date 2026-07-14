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
if "BACKTEST_DATA_ROOT" not in os.environ:  # 不用 setdefault:实参会先求值,平白遗留空目录
    os.environ["BACKTEST_DATA_ROOT"] = tempfile.mkdtemp(prefix="hs300-onboard-")


def _keystore():
    from app.security.keystore import SecureKeystore

    try:
        return SecureKeystore.open(prefer="keyring")
    except Exception as exc:
        raise SystemExit(
            f"系统 keyring 不可用({type(exc).__name__})。macOS 自带 Keychain;"
            "Linux 需 libsecret(apt install libsecret-1-0 gnome-keyring)或改用图形会话;"
            "headless/CI 环境暂不支持本 CLI 的 keyring 流"
        ) from None


def _fetch_key(name: str) -> str:
    record = _keystore().fetch(name)
    if record is None or not record.api_key:
        if name == "hs300_provenance" or "provenance" in name:
            hint = f"python scripts/hs300_onboard.py keygen --key-name {name}(生成新签名 key)"
        else:
            hint = (
                f"python scripts/hs300_onboard.py store-token --token-name {name}"
                "(交互式录入外部 token;绝不要用 keygen——那会生成随机串顶替真 token)"
            )
        raise SystemExit(f"keyring 无 {name!r},先跑: {hint}")
    return record.api_key


def cmd_keygen(args: argparse.Namespace) -> int:
    from app.security.keystore import KeystoreRecord

    ks = _keystore()
    try:
        existing = ks.fetch(args.key_name)
    except Exception as exc:
        # fail-closed:keyring 读取失败 ≠ key 不存在。此时生成新 key 可能无授权覆盖
        # 信任锚,旧签名链将永久不可验证——宁可中止。
        raise SystemExit(
            f"keyring 读取失败({type(exc).__name__}),无法确认 {args.key_name!r} 是否已存在,"
            "拒绝生成新 key(防覆盖信任锚);修复 keyring 后重试"
        ) from None
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


def cmd_store_token(args: argparse.Namespace) -> int:
    import getpass

    from app.security.keystore import KeystoreRecord

    ks = _keystore()
    try:
        existing = ks.fetch(args.token_name)
    except Exception:
        existing = None
    if existing is not None and not args.overwrite:
        raise SystemExit(
            f"{args.token_name!r} 已存在(len={len(existing.api_key)});"
            "确认要替换加 --overwrite"
        )
    token = getpass.getpass(f"粘贴 {args.token_name} token(输入不回显): ").strip()
    if len(token) < 10:
        raise SystemExit("token 过短,疑似粘贴失败,未保存")
    ks.store(
        KeystoreRecord(
            name=args.token_name, api_key=token, api_secret=token,
            note="external data-source token (store-token)",
        )
    )
    print(f"token stored: name={args.token_name} len={len(token)}(值不回显)")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    import tushare as ts

    from app.data_onboarding.hs300_fetch import fetch_raw_hs300

    token = _fetch_key(args.token_name)
    pro = ts.pro_api(token)
    try:
        result = fetch_raw_hs300(
            args.staging_dir,
            pro=pro,
            start_compact=args.start.replace("-", ""),
            end_compact=args.end.replace("-", ""),
            progress=print,
        )
    except Exception as exc:
        from app.data_onboarding.hs300_fetch import classify_tushare_error

        advice = {
            "rate_limit": "限流:等 1 分钟重跑,幂等续拉不丢进度",
            "daily_limit": "当日接口上限耗尽:明天重跑同一命令续拉",
            "permission": "积分档不够:确认 tushare.pro 账户 ≥2000 积分",
            "transient": "网络/服务暂态:直接重跑,已完成单元自动跳过",
        }[classify_tushare_error(str(exc))]
        # 不打印 traceback:pro 对象/调用栈可能间接携带 token 上下文
        raise SystemExit(
            f"pull 失败({type(exc).__name__}): {str(exc)[:200]}\n修复建议: {advice}"
        ) from None
    if token in str(result):  # 不用 assert:python -O 会剥离断言
        raise SystemExit("内部错误:token 泄入输出,拒绝打印")
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

    # snapshot/end/as-of 三参数一致性校验(独立可改=无声漂移雷,fail-closed)
    if args.as_of != args.end:
        raise SystemExit(
            f"--as-of({args.as_of}) 必须等于 --end({args.end}):签名快照 as-of 日=面板 coverage_end"
        )
    end_month = args.end[:7].replace("-", "")
    if args.snapshot != end_month:
        raise SystemExit(
            f"--snapshot({args.snapshot}) 必须是 --end 所在月({end_month}):universe 取窗口终点当月快照"
        )
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
    if key in text:  # 不用 assert:python -O 会剥离断言,secret 卫生必须无条件生效
        raise SystemExit("内部错误:key 泄入输出,拒绝打印")
    print(text)
    print(
        "\n# 下一步(直接复制运行):\n"
        f"python scripts/hs300_onboard.py bench \\\n"
        f"  --panel-path {result['panel_path']} \\\n"
        f"  --registry-path {result['registry_path']} \\\n"
        f"  --dataset-version-ref {result['dataset_version_ref']} \\\n"
        f"  --receipt-path {result['receipt_path']} \\\n"
        f"  --universe-path {result['universe_path']}"
    )
    return 0


def cmd_build_research(args: argparse.Namespace) -> int:
    from app.data_onboarding import build_research_asset

    result = build_research_asset(
        args.staging_dir,
        registry_path=args.registry_path,
        out_dir=args.out_dir,
        snapshot_yyyymm=args.snapshot,
        start_date=args.start,
        end_date=args.end,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
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
    if key in text:  # 不用 assert:python -O 会剥离断言
        raise SystemExit("内部错误:key 泄入输出,拒绝打印")
    print(text)
    return 0 if measurement.measured else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_key = sub.add_parser("keygen", help="生成随机 provenance HMAC key 入 keyring(不是录入外部 token——那用 store-token)")
    p_key.add_argument("--key-name", default="hs300_provenance", help="keyring 条目名")
    p_key.add_argument("--rotate", action="store_true", help="已存在时显式轮换(旧链将不可验证)")
    p_key.set_defaults(fn=cmd_keygen)

    p_token = sub.add_parser("store-token", help="交互式录入外部 token 存 keyring(不走 argv)")
    p_token.add_argument("--token-name", default="tushare", help="keyring 条目名(默认 tushare)")
    p_token.add_argument("--overwrite", action="store_true", help="已存在时确认替换")
    p_token.set_defaults(fn=cmd_store_token)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--staging-dir", required=True,
                        help="staging 缓存目录(pull 的输出=后续命令的输入;一个目录绑定一个拉取窗口,换 --start/--end 必须换新目录)")
    common.add_argument("--snapshot", default="202606",
                        help="universe 取哪个月的 index_weight 快照(YYYYMM,须与 --end 同月)")
    common.add_argument("--start", default="2016-06-01", help="窗口起点(ISO 日期)")
    common.add_argument("--end", default="2026-06-30",
                        help="窗口终点(ISO;须为交易日且=签名快照的 as-of 日)")

    p_pull = sub.add_parser("pull", parents=[common], help="Tushare 回填 staging")
    p_pull.add_argument("--token-name", default="tushare",
                        help="keyring 里 Tushare token 的条目名(先 store-token 录入)")
    p_pull.set_defaults(fn=cmd_pull)

    p_pre = sub.add_parser("preflight", parents=[common], help="面板自检(不签名)")
    p_pre.set_defaults(fn=cmd_preflight)

    p_build = sub.add_parser("build", parents=[common], help="组链+签名")
    p_build.add_argument("--registry-path", required=True,
                         help="DatasetRegistry JSONL(建议 <repo>/data/datasets/registry.jsonl)")
    p_build.add_argument("--panel-path", required=True,
                         help="canonical panel parquet 输出路径(新建,建议 <repo>/data/datasets/lake/<dataset_id>/panel.parquet)")
    p_build.add_argument("--out-dir", required=True,
                         help="签名件输出目录(universe.json+provenance.json,建议 <repo>/data/datasets/provenance/<dataset_id>)")
    p_build.add_argument("--as-of", default="2026-06-30",
                         help="签名快照 as-of 日(必须=面板 coverage_end 的日期=--end)")
    p_build.add_argument("--key-name", default="hs300_provenance",
                         help="provenance HMAC key 的 keyring 条目名(keygen 生成)")
    p_build.add_argument("--root-id", default="quantbt-hs300-operator-root-v1",
                         help="authority root id(须与 harness pin 一致)")
    p_build.add_argument("--key-id", default="hs300-provenance-2026-07",
                         help="key id(须与 harness pin 一致)")
    p_build.set_defaults(fn=cmd_build)

    p_research = sub.add_parser(
        "build-research", parents=[common],
        help="研究面资产:622 并集(含退市)三表+质量门(探针#6/#7)→DatasetVersion(无签名,非基准面)",
    )
    p_research.add_argument("--registry-path", required=True,
                            help="DatasetRegistry JSONL(与基准面同一本账)")
    p_research.add_argument("--out-dir", required=True,
                            help="三表 parquet 输出目录(bars/adj_factors/suspensions)")
    p_research.set_defaults(fn=cmd_build_research)

    p_bench = sub.add_parser("bench", help="跑 harness HS300 探针")
    p_bench.add_argument("--panel-path", required=True, help="build 输出的 panel parquet")
    p_bench.add_argument("--registry-path", required=True, help="build 用的 registry JSONL")
    p_bench.add_argument("--dataset-version-ref", required=True,
                         help="build 输出 JSON 的 dataset_version_ref(build 尾部已打印整条 bench 命令,直接复制)")
    p_bench.add_argument("--receipt-path", required=True, help="build 输出的 provenance.json")
    p_bench.add_argument("--universe-path", required=True, help="build 输出的 universe.json")
    p_bench.add_argument("--key-name", default="hs300_provenance",
                         help="provenance key 的 keyring 条目名")
    p_bench.set_defaults(fn=cmd_bench)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
