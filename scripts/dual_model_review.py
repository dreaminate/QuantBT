#!/usr/bin/env python3
"""dual-model 跨厂商独立审查 · 脚本化真实端到端（卡 9c5e6975 · GOAL §7/§8）。

builder(anthropic 真调用) → ReviewSubjectBinding(服务端派生 verifier prompt) →
verifier(openai 真调用,independence_required) → bind/validate → IndependenceVerdict,
全程走应用内 LLMGateway(routing/密封/记录),HMAC 密封 LLMCallRecord 落盘到 --out-dir。

为什么是脚本而非起服务器:本机 secrets.yaml 含 Binance material,应用 boot 被
设计性阻断(预期,不修)——本脚本用与 /api/llm/configure 完全相同的 keystore 约定
(llm_<provider> + note JSON extras)在隔离内存 keystore 里装配同一个 LLMGateway,
代码路径与应用内一致(build_agent_llm_gateway 单一源)。

密钥红线:llm.anthropic/llm.openai 的 key 只做 secrets.yaml 窄读→内存 keystore→
gateway 材料化,绝不打印/落盘/入 record(store 持久化字段是 digest/id 白名单)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "app" / "backend"
sys.path.insert(0, str(BACKEND))

if "BACKTEST_DATA_ROOT" not in os.environ:  # 隔离 app.paths 的 import 期解析
    os.environ["BACKTEST_DATA_ROOT"] = tempfile.mkdtemp(prefix="dual-review-")

BUILDER_TASK = """你是量化研究员。给定日频对齐样本(同一资产,t 日因子值 x 与 t+1 日收益 r):
x=[0.8,-0.3,1.2,0.5,-0.9,0.1,1.5,-0.6,0.7,-0.2]
r=[0.012,-0.004,0.018,0.006,-0.011,0.001,0.020,-0.008,0.009,-0.003]
计算 Pearson 相关系数(IC),给出小数点后 3 位的数值与两句结论。只输出纯文本。"""

REVIEW_CRITERIA = (
    "独立重算 IC:验证 builder 给出的相关系数数值是否正确(允许 ±0.005),"
    "结论表述是否与数值一致、有无夸大。输出 verdict: correct/incorrect + 一句理由。"
)


def _load_llm_keys() -> dict[str, dict[str, str]]:
    import yaml

    raw = yaml.safe_load((Path.home() / ".quantbt" / "secrets.yaml").read_text()) or {}
    llm = raw.get("llm", {})
    out = {}
    for provider in ("anthropic", "openai"):
        entry = llm.get(provider, {}) or {}
        key = entry.get("api_key", "")
        if not key:
            raise SystemExit(f"secrets.yaml 缺 llm.{provider}.api_key,双厂商审查无法进行")
        out[provider] = {
            "api_key": key,
            "base_url": entry.get("base_url", "") or "",
            "model": entry.get("model", "") or "",
        }
    return out


def preflight(keys: dict[str, dict[str, str]]) -> list[str]:
    """逐 provider 最小连通探测,输出脱敏诊断(key 绝不入输出)。返回失败清单。"""
    import requests

    failures: list[str] = []
    for provider, entry in keys.items():
        key, base, model = entry["api_key"], entry["base_url"], entry["model"]
        try:
            if provider == "anthropic" and "/openai" not in base:
                resp = requests.post(
                    f"{(base or 'https://api.anthropic.com/v1').rstrip('/')}/messages",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                    json={"model": model or "claude-sonnet-4-5", "max_tokens": 8,
                          "messages": [{"role": "user", "content": "ping"}]},
                    timeout=30,
                )
            else:
                # OpenAI 兼容端点(含把 anthropic 挂在 OpenAI 兼容中继的情形)
                resp = requests.post(
                    f"{(base or 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model or "gpt-4o", "max_tokens": 8,
                          "messages": [{"role": "user", "content": "ping"}]},
                    timeout=30,
                )
            if resp.status_code != 200:
                body = resp.text.replace(key, "[REDACTED]")[:160]
                advice = {
                    401: "key 无效/过期:更新 secrets.yaml 对应 api_key",
                    403: "key 权限不足:检查中继账户",
                    404: "端点路径不匹配:anthropic 原生协议(/messages)打在 OpenAI 兼容"
                         "中继上会 404——中继场景应把该 provider 配成 OpenAI 兼容形态"
                         "(base_url 含 /openai 时本 preflight 已自动按兼容协议探测)",
                }.get(resp.status_code, "检查 base_url/model 配置")
                failures.append(f"{provider}: HTTP {resp.status_code} {body} → {advice}")
        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"{provider}: {type(exc).__name__} "
                f"{str(exc).replace(key, '[REDACTED]')[:120]} → 网络/端点不可达"
            )
    return failures


def run_review(out_dir: Path, *, task: str = BUILDER_TASK,
               criteria: str = REVIEW_CRITERIA,
               keys: dict[str, dict[str, str]] | None = None,
               client_factory=None) -> dict:
    """keys/client_factory 注入口仅供测试(桩);生产路径 = secrets 窄读 + 真 adapter。"""
    from app.agent.llm_client import LLMMessage
    from app.lineage.ids import canonical_json
    from app.llm.call_record import (
        bind_review_verifier_record,
        evaluate_independence,
        make_review_subject_binding,
        validate_review_subject_binding,
    )
    from app.llm.call_record_store import LLMCallRecordStore
    from app.llm.gateway import LLMRequest, build_agent_llm_gateway
    from app.llm.routing import RoleCapabilityRequest
    from app.security.keystore import InMemoryKeystore, KeystoreRecord, SecureKeystore

    keys = keys if keys is not None else _load_llm_keys()
    ks = SecureKeystore(InMemoryKeystore())
    for provider, entry in keys.items():
        ks.store(KeystoreRecord(
            name=f"llm_{provider}",
            api_key=entry["api_key"],
            api_secret=entry["api_key"],
            note=json.dumps({"base_url": entry["base_url"], "model": entry["model"]}),
        ))

    out_dir.mkdir(parents=True, exist_ok=True)
    store = LLMCallRecordStore(out_dir / "llm_call_records.jsonl")
    gateway = build_agent_llm_gateway(
        ks, seal_secret=store.seal_secret, client_factory=client_factory,
    )

    session_id = "dual-review-session"
    common = dict(session_id=session_id, owner_user_id="operator:dreaminate",
                  workflow_id="wf:dual-model-review")

    builder_result = gateway.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content=task)],
            capability=RoleCapabilityRequest(role="factor_engineer", difficulty="hard"),
            invocation_id="inv-builder", **common,
        ),
        record_sink=store.append,
    )
    builder_record = builder_result.record
    builder_output = builder_result.response.content

    binding, verifier_instruction = make_review_subject_binding(
        builder=builder_record,
        builder_artifact_ref="artifact:ic-claim:1",
        builder_artifact_output_ref=hashlib.sha256(
            canonical_json(builder_output).encode("utf-8")
        ).hexdigest(),
        builder_output=builder_output,
        review_criteria=criteria,
    )
    verifier_result = gateway.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content=verifier_instruction)],
            capability=RoleCapabilityRequest(
                role="verifier", difficulty="hard", independence_required=True,
            ),
            invocation_id="inv-verifier", **common,
        ),
        record_sink=store.append,
    )
    verifier_record = verifier_result.record

    binding = bind_review_verifier_record(binding, verifier_record)
    validate_review_subject_binding(
        builder=builder_record, verifier=verifier_record, binding=binding,
    )
    verdict = evaluate_independence(builder_record, verifier_record)

    evidence = {
        "independent": verdict.independent,
        "reason": verdict.reason,
        "builder": {
            "call_id": builder_record.call_id,
            "provider": builder_record.provider,
            "model": builder_record.model,
            "response_digest": builder_record.response_digest,
        },
        "verifier": {
            "call_id": verifier_record.call_id,
            "provider": verifier_record.provider,
            "model": verifier_record.model,
            "prompt_digest": verifier_record.prompt_digest,
        },
        "binding": {
            "builder_call_ref": binding.builder_call_ref,
            "review_subject_ref": binding.review_subject_ref,
            "verifier_context_ref": binding.verifier_context_ref,
        },
        "records_path": str(out_dir / "llm_call_records.jsonl"),
        "builder_output_excerpt": builder_output[:200],
        "verifier_output_excerpt": verifier_result.response.content[:200],
    }
    text = json.dumps(evidence, ensure_ascii=False, indent=2)
    for provider, entry in keys.items():
        if entry["api_key"] in text:  # 不用 assert:-O 剥断言
            raise SystemExit("内部错误:key 泄入证据输出,拒绝落盘")
    (out_dir / "review_evidence.json").write_text(text, encoding="utf-8")
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", required=True,
        help="密封记录与证据输出目录(建议 <repo>/data/datasets/llm_reviews/<ts>,gitignored)",
    )
    parser.add_argument("--skip-preflight", action="store_true",
                        help="跳过连通探测直接跑(默认先探测,失败即指路退出)")
    args = parser.parse_args(argv)
    if not args.skip_preflight:
        failures = preflight(_load_llm_keys())
        if failures:
            for line in failures:
                print(f"preflight FAIL — {line}", file=sys.stderr)
            raise SystemExit(
                "双厂商连通探测未过:修复上述凭据/端点后重跑。"
                "(应用内真实双模型审查依赖有效的 anthropic+openai 凭据)"
            )
    evidence = run_review(Path(args.out_dir))
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence["independent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
