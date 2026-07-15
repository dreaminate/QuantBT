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
异常路径同样收口:yaml 解析错误整体抑制(原文可能含 key)、preflight 诊断对全部
已加载 key 脱敏、evidence 落盘前全文扫描拒泄。

诚实边界(不装成机制能证明的):脚本能证明的只有三件——①两个配置槽的 key 字面量
不同(同 key 即拒;不同 key 仍可指向同一实际后端,单侧不可证伪)②gateway 调用前
记账的 verifier prompt digest 与 binding 派生 instruction 一致(adapter/中继之后
provider 实收什么,本机不可证)③在 seal key 可信前提下,evidence 内层的未重签修改
可被检出(不防持 key 重签/删除/整包回滚)。provider 身份来自配置槽声明(model_identity
按模型名判族);两槽 base_url 指向同一 relay 端点(scheme+host+port 相同,不看 path/
query)时,在 evidence 里落机器可读 caveat 如实披露——完备性优先(宁多披露不漏),
DNS 别名等更深同源单侧不可判。机制层加固(实发 payload 回带/身份可验证升级)另立卡
tasks/pool/8be0e547。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
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

    secrets_path = Path.home() / ".quantbt" / "secrets.yaml"
    try:
        raw = yaml.safe_load(secrets_path.read_text()) or {}
    except FileNotFoundError:
        raise SystemExit("~/.quantbt/secrets.yaml 不存在,双厂商审查无法进行") from None
    except Exception:  # noqa: BLE001 — yaml/IO 错误消息会回显文件原文(可能含 key),整体抑制
        raise SystemExit(
            "secrets.yaml 读取/解析失败(为防 key 回显,原始错误已抑制):检查文件权限与 YAML 语法"
        ) from None
    llm = raw.get("llm", {}) or {}
    out = {}
    for provider in ("anthropic", "openai"):
        entry = llm.get(provider, {}) or {}
        key = entry.get("api_key", "")
        # 类型门:非字符串(如误配成数值)的 key 进 requests header 会在异常链里
        # 原样回显;这里 fail-closed 且值不回显(误配字面量也可能是敏感材料)
        if not isinstance(key, str) or not key.strip():
            raise SystemExit(
                f"secrets.yaml 的 llm.{provider}.api_key 缺失或不是非空字符串,"
                "双厂商审查无法进行(值不回显)"
            )
        # 只把「缺失/None」当空串;0/False/[] 这类 falsy 非字符串是误配,必须拒
        # (`or ""` 会把它们静默吞掉),值不回显
        base_url = entry.get("base_url")
        base_url = "" if base_url is None else base_url
        model = entry.get("model")
        model = "" if model is None else model
        if not isinstance(base_url, str) or not isinstance(model, str):
            raise SystemExit(
                f"secrets.yaml 的 llm.{provider}.base_url/model 必须是字符串(值不回显)"
            )
        out[provider] = {"api_key": key, "base_url": base_url, "model": model}
    return out


def _key_variants(key: str) -> tuple[str, ...]:
    """key 的字面量 + 常见转义表示(JSON 转义/repr 转义)。

    响应体或异常文本里的 key 可能已经是 JSON-escaped(引号→\\",反斜杠→\\\\)或
    repr-escaped 形态——只匹配 raw 字面量会漏掉可逆还原的泄漏。
    """
    variants = {key}
    variants.add(json.dumps(key, ensure_ascii=False)[1:-1])  # JSON 转义形态
    variants.add(json.dumps(key)[1:-1])                       # ASCII JSON 转义形态
    variants.add(repr(key)[1:-1])                             # repr 转义形态
    # JSON 语法还允许 "\/"(转义斜杠):json.dumps 自己不产,但对端序列化器可能产
    for v in tuple(variants):
        if "/" in v:
            variants.add(v.replace("/", "\\/"))
    return tuple(v for v in variants if v)


_JSON_SURROGATE_PAIR_RE = re.compile(
    r"\\u([dD][89abAB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})"
)
_JSON_ESCAPE_RE = re.compile(r'\\u([0-9a-fA-F]{4})|\\(["\\/bfnrt])')
_JSON_ESCAPE_MAP = {'"': '"', "\\": "\\", "/": "/",
                    "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}


def _json_unescape(text: str) -> str:
    """把文本里的标准 JSON 转义序列统一还原(容忍混合/部分/多层转义)。

    - UTF-16 代理对(\\ud83d\\ude00 → 非 BMP 字符)先合并再处理单个转义,
      否则 chr(高位)+chr(低位) 两个孤立代理拼不出原字符。
    - 迭代到不动点:对端可能多层 JSON 编码(每层只还原一级,如 \\\\ud83d 需先
      \\\\→\\ 再合并代理对)。每轮严格减少转义反斜杠/合并代理,必收敛;上限防病理输入。
    - 过度还原只会导致脱敏侧多遮蔽(安全方向),不会漏。
    """
    def _pair(match: re.Match) -> str:
        hi, lo = int(match.group(1), 16), int(match.group(2), 16)
        return chr(0x10000 + ((hi - 0xD800) << 10) + (lo - 0xDC00))

    def _sub(match: re.Match) -> str:
        if match.group(1) is not None:
            return chr(int(match.group(1), 16))
        return _JSON_ESCAPE_MAP[match.group(2)]

    prev, cur = None, text
    for _ in range(16):
        if cur == prev:
            break
        prev = cur
        cur = _JSON_ESCAPE_RE.sub(_sub, _JSON_SURROGATE_PAIR_RE.sub(_pair, cur))
    return cur


def _contains_key(text: str, key: str) -> bool:
    # 变体枚举打不完混合转义(如仅第一个 / 被转义):先枚举常见形态,
    # 再把文本整体反转义还原后按 raw 扫——任意混合形态还原后都会现出 raw key
    if any(v in text for v in _key_variants(key)):
        return True
    return key in _json_unescape(text)


def preflight(keys: dict[str, dict[str, str]]) -> list[str]:
    """逐 provider 最小连通探测,输出脱敏诊断(key 绝不入输出)。返回失败清单。"""
    import requests

    all_keys = [e["api_key"] for e in keys.values() if e.get("api_key")]

    def _redact(text: str) -> str:
        # 对全部已加载 key 的全部转义形态脱敏:中继/网关可能在任一 provider 的
        # 响应体/异常文本里回显另一个 key(且可能已被 JSON/repr 转义)
        for k in all_keys:
            for v in _key_variants(k):
                text = text.replace(v, "[REDACTED]")
        # 兜底(fail-closed):混合/奇异转义形态定位不了具体片段时,整体遮蔽——
        # 宁可丢诊断信息也不泄 key
        if any(_contains_key(text, k) for k in all_keys):
            return "[REDACTED-UNSAFE-DIAGNOSTIC:响应含无法定位的 key 转义形态,已全文遮蔽]"
        return text

    failures: list[str] = []
    for provider, entry in keys.items():
        key, base, model = entry["api_key"], entry["base_url"], entry["model"]
        try:
            # 探测协议必须与 gateway 实调协议一致,否则探测通过≠真实调用能通:
            # gateway 对 anthropic 槽构造 AnthropicLLM(原生 /messages),对 openai 槽
            # 构造 OpenAI 兼容 /chat/completions——preflight 按同样的分派探测。
            if provider == "anthropic":
                resp = requests.post(
                    f"{(base or 'https://api.anthropic.com/v1').rstrip('/')}/messages",
                    headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                    json={"model": model or "claude-sonnet-4-5", "max_tokens": 8,
                          "messages": [{"role": "user", "content": "ping"}]},
                    timeout=30,
                )
            else:
                resp = requests.post(
                    f"{(base or 'https://api.openai.com/v1').rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    json={"model": model or "gpt-4o", "max_tokens": 8,
                          "messages": [{"role": "user", "content": "ping"}]},
                    timeout=30,
                )
            if resp.status_code != 200:
                body = _redact(resp.text)[:160]
                advice = {
                    401: "key 无效/过期:更新 secrets.yaml 对应 api_key",
                    403: "key 权限不足:检查中继账户",
                    404: "端点路径不匹配:anthropic 槽走原生 /messages(与 gateway 实调"
                         "同协议)——base_url 若是 OpenAI 兼容中继形态(含 /openai),"
                         "AnthropicLLM 打不通,需改配原生 anthropic 端点",
                }.get(resp.status_code, "检查 base_url/model 配置")
                failures.append(f"{provider}: HTTP {resp.status_code} {body} → {advice}")
        except Exception as exc:  # noqa: BLE001
            failures.append(
                f"{provider}: {type(exc).__name__} "
                f"{_redact(str(exc))[:120]} → 网络/端点不可达"
            )
    return failures


def run_review(out_dir: Path, *, task: str = BUILDER_TASK,
               criteria: str = REVIEW_CRITERIA,
               keys: dict[str, dict[str, str]] | None = None,
               client_factory=None,
               _verifier_prompt_override: str | None = None) -> dict:
    """keys/client_factory 注入口仅供测试(桩);生产路径 = secrets 窄读 + 真 adapter。

    _verifier_prompt_override 是对抗测试专用种坏缝:模拟「实发 prompt 被偷换」的
    坏实现,digest 互证门必须抓住它(种已知坏门必被抓)。生产路径永远为 None。
    """
    from app.agent.llm_client import LLMMessage
    from app.lineage.ids import canonical_json
    from app.llm.call_record import (
        bind_review_verifier_record,
        evaluate_independence,
        make_review_subject_binding,
        validate_review_subject_binding,
    )
    from app.llm.call_record_store import LLMCallRecordStore
    from app.llm.gateway import LLMGateway, LLMRequest, build_agent_llm_gateway
    from app.llm.routing import RoleCapabilityRequest
    from app.security.keystore import InMemoryKeystore, KeystoreRecord, SecureKeystore

    if keys is None:
        # 生产路径(直接编程调用也一样):载入即探测,fail-closed。main() 载入一次后
        # 显式传入同一份 keys,消除「探测的凭据 ≠ 实调的凭据」的双载 TOCTOU。
        keys = _load_llm_keys()
        failures = preflight(keys)
        if failures:
            for line in failures:
                print(f"preflight FAIL — {line}", file=sys.stderr)
            raise SystemExit("双厂商连通探测未过:修复凭据/端点后重跑")
    missing = [p for p in ("anthropic", "openai") if not (keys.get(p) or {}).get("api_key")]
    if missing:
        raise SystemExit(
            f"缺 {'/'.join('llm.' + p for p in missing)} 凭据——跨厂商审查 fail-closed"
            " 拒绝运行(单厂商换 prompt 不构成第二意见,不产出任何 evidence)"
        )
    if keys["anthropic"]["api_key"] == keys["openai"]["api_key"]:
        raise SystemExit(
            "llm.anthropic 与 llm.openai 配置了同一个 api_key——可证同源,"
            "独立性主张不成立,拒绝运行"
        )
    def _relay_endpoint(url: str):
        # relay-operator 身份 = (scheme, host, port)。同 → 视为可能同一中继,披露。
        # 只认端点身份,不比 path/query/fragment:同一中继下不同 path/tenant/参数
        # 仍是同一操作方控制两侧响应,独立性主张不成立——所以用 path/query 区分是
        # 错的方向(会漏报 relay/anthropic 与 relay/openai 这类同中继)。
        # 完备性优先(宁多披露不漏报);字符串归一无法穷举 URL 变体,故不做整串归一。
        # DNS 别名/IP↔域名等价属 DNS 层,单侧不可判,机制层收口归卡 8be0e547。
        from urllib.parse import urlsplit

        u = url.strip()
        if not u:  # 空 base = 用各自厂商默认原生端点(不同 host),不算同中继
            return None
        parts = urlsplit(u)
        scheme = parts.scheme.lower()
        try:
            port = parts.port  # 数值解析(0443→443)
        except ValueError:
            return (scheme, parts.netloc.lower(), "invalid-port")
        host = (parts.hostname or parts.netloc).lower()
        if port == {"https": 443, "http": 80}.get(scheme):
            port = None
        return (scheme, host, port)

    _relay_a = _relay_endpoint(keys["anthropic"]["base_url"])
    same_base_relay = _relay_a is not None and (
        _relay_a == _relay_endpoint(keys["openai"]["base_url"])
    )
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
    verifier_capability = RoleCapabilityRequest(
        role="verifier", difficulty="hard", independence_required=True,
    )
    sent_text = (
        verifier_instruction if _verifier_prompt_override is None
        else _verifier_prompt_override
    )
    verifier_result = gateway.complete(
        LLMRequest(
            messages=[LLMMessage(role="user", content=sent_text)],
            capability=verifier_capability,
            invocation_id="inv-verifier", **common,
        ),
        record_sink=store.append,
    )
    verifier_record = verifier_result.record

    # digest 互证:record 里的 prompt_digest(实发)必须等于 binding 派生 instruction
    # 的 digest(应发)。复用 gateway 同一哈希族(ids.content_hash),不自立第二套——
    # 堵「验证器实际收到的 prompt 与 binding 哈希的 instruction 是两码事」的偷换洞。
    expected_digest = LLMGateway._prompt_digest(LLMRequest(
        messages=[LLMMessage(role="user", content=verifier_instruction)],
        capability=verifier_capability,
        invocation_id="inv-verifier", **common,
    ))
    if verifier_record.prompt_digest != expected_digest:
        raise SystemExit(
            "verifier 实发 prompt 与 binding 派生 instruction 的 digest 不一致——"
            "审查对象被偷换,拒绝产出 evidence"
        )

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
            "verifier_prompt_digest_expected": expected_digest,
        },
        # 机器可读的主张边界:independent=True 的含义是「按配置槽声明的跨厂商」,
        # provider 身份由槽名+模型名判族(model_identity),不是远端后端的同源性证明
        "independence_claim_scope": "cross_vendor_as_configured",
        "caveats": (["same_base_url_relay"] if same_base_relay else []),
        "transport_disclosure": (
            "双 provider 经同一 base_url 中继:上游厂商独立性不可由本脚本证明,"
            "依赖中继诚实路由(如实披露,用户自判是否可信)"
            if same_base_relay else "各 provider 独立端点配置(归一化比较,best-effort)"
        ),
        "records_path": str(out_dir / "llm_call_records.jsonl"),
        "builder_output_excerpt": builder_output[:200],
        "verifier_output_excerpt": verifier_result.response.content[:200],
    }
    # 密封边界(如实):在「seal key 可信」前提下,检出对内层 evidence+seal_algo 的
    # 未重签修改;不防持 key 者重签、文件删除或整包回滚——那属外部审计/多副本层。
    # key 与 LLMCallRecord 同一把,evidence 与密封 JSONL 之间无可信度落差。
    seal_algo = "hmac-sha256/sorted-compact-json"
    seal = hmac.new(
        store.seal_secret,
        _canonical_evidence_bytes({"seal_algo": seal_algo, "evidence": evidence}),
        hashlib.sha256,
    ).hexdigest()
    doc = {"evidence": evidence, "evidence_seal": seal, "seal_algo": seal_algo}
    text = json.dumps(doc, ensure_ascii=False, indent=2)
    for provider, entry in keys.items():
        # 双扫 × 全转义形态:序列化文本 + 对象逐字符串,每处都匹配 raw/JSON 转义/
        # repr 转义形态——模型输出里已被转义的 key 同样可逆还原,必须拒。
        # 不用 assert:-O 剥断言。
        if _contains_key(text, entry["api_key"]) or any(
            _contains_key(s, entry["api_key"]) for s in _iter_strings(doc)
        ):
            raise SystemExit("内部错误:key 泄入证据输出,拒绝落盘")
    (out_dir / "review_evidence.json").write_text(text, encoding="utf-8")
    return evidence


def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v)


def _canonical_evidence_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def verify_evidence_file(path: Path, seal_secret: bytes) -> bool:
    """复验 evidence 密封。True=内层 evidence+seal_algo 未被(未重签地)修改。

    边界:前提是 seal key 可信且未泄;不检测持 key 重签、文件删除、旧包整体回滚。
    """
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    expected = hmac.new(
        seal_secret,
        _canonical_evidence_bytes(
            {"seal_algo": doc.get("seal_algo", ""), "evidence": doc["evidence"]}
        ),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, str(doc.get("evidence_seal", "")))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir", required=True,
        help="密封记录与证据输出目录(建议 <repo>/data/datasets/llm_reviews/<ts>,gitignored)",
    )
    args = parser.parse_args(argv)
    # 载入一次、探测与实调用同一份 keys(消双载 TOCTOU);preflight 无跳过口
    keys = _load_llm_keys()
    failures = preflight(keys)
    if failures:
        for line in failures:
            print(f"preflight FAIL — {line}", file=sys.stderr)
        raise SystemExit(
            "双厂商连通探测未过:修复上述凭据/端点后重跑。"
            "(应用内真实双模型审查依赖有效的 anthropic+openai 凭据)"
        )
    evidence = run_review(Path(args.out_dir), keys=keys)
    # 打印密封后的全文(与落盘一致),而非未密封内层——stdout 副本同样可复验
    print((Path(args.out_dir) / "review_evidence.json").read_text(encoding="utf-8"))
    return 0 if evidence["independent"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
