"""scripts/dual_model_review.py 接线对抗测试(无网络:桩 client 注入)。

真实跨厂商调用依赖有效 anthropic+openai 凭据(本机中继 key 已 401,登记待用户);
本文件钉死接线正确性:凭据有效时同一代码路径即产真实密封记录与独立性判定。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "dual_model_review",
    Path(__file__).resolve().parents[3] / "scripts" / "dual_model_review.py",
)
dmr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dmr)

FAKE_KEYS = {
    "anthropic": {"api_key": "test-anthropic-key-000000000000000000000000", "base_url": "", "model": ""},
    "openai": {"api_key": "test-openai-key-00000000000000000000000000", "base_url": "", "model": ""},
}


class _StubClient:
    def __init__(self, provider: str) -> None:
        self._provider = provider

    def chat(self, messages, *, model=None, tools=None, **_kw):
        from app.agent.llm_client import LLMResponse

        text = (
            "IC = 0.999。因子与次日收益近乎线性相关;样本极小,结论仅示例。"
            if self._provider == "anthropic"
            else "verdict: correct — 重算 Pearson 相关系数≈0.999,与 builder 一致。"
        )
        return LLMResponse(content=text, tool_calls=[])


def test_stubbed_cross_vendor_review_end_to_end(tmp_path):
    evidence = dmr.run_review(
        tmp_path / "out",
        keys=FAKE_KEYS,
        client_factory=lambda cred: _StubClient(cred.provider),
    )
    assert evidence["independent"] is True
    assert evidence["builder"]["provider"] == "anthropic"
    assert evidence["verifier"]["provider"] == "openai"
    records = [
        json.loads(line)
        for line in (tmp_path / "out" / "llm_call_records.jsonl")
        .read_text(encoding="utf-8").splitlines()
    ]
    assert len(records) >= 2  # builder+verifier 终态(含尝试记录则更多)
    text = (tmp_path / "out" / "review_evidence.json").read_text(encoding="utf-8")
    for entry in FAKE_KEYS.values():
        assert entry["api_key"] not in text
        assert not any(entry["api_key"] in json.dumps(r) for r in records)


def test_single_vendor_cannot_claim_independence(tmp_path):
    # 种坏:只配 openai(无跨族路由)→ 机制的诚实行为=完成但 independent=False
    # (evaluate_independence 单一源判定;main() 对非独立退出码 2)。
    # 绝不允许 independent=True——同厂商换 prompt 不构成第二意见。
    single = {"openai": FAKE_KEYS["openai"]}
    evidence = dmr.run_review(
        tmp_path / "out2",
        keys=single,
        client_factory=lambda cred: _StubClient(cred.provider),
    )
    assert evidence["independent"] is False
    assert evidence["builder"]["provider"] == evidence["verifier"]["provider"] == "openai"


def test_missing_secrets_exit_is_actionable(monkeypatch, tmp_path):
    def _empty():
        raise SystemExit("secrets.yaml 缺 llm.anthropic.api_key,双厂商审查无法进行")

    monkeypatch.setattr(dmr, "_load_llm_keys", _empty)
    with pytest.raises(SystemExit, match="api_key"):
        dmr.run_review(tmp_path / "out3")
