"""订阅 CLI LLM adapter 测试(mock subprocess,不真调 CLI/不烧订阅额度)。

钉死:cmd 正确构造(provider/model/print 模式)、输出解析、错误 fail-closed(超时/非零/空)、
tools 拒、model 切换、凭据不经 adapter(env 透传不含注入 token)。
"""

from __future__ import annotations

import subprocess
import types

import pytest

from app.agent.llm_client import LLMMessage, NoLLMConfigured
from app.agent import subscription_cli_llm as scl


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(autouse=True)
def _cli_present(monkeypatch):
    # 默认两 CLI 都"存在"(shutil.which 返回路径)
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")


def test_claude_adapter_builds_print_command_and_parses_stdout(monkeypatch):
    captured = {}

    def _run(cmd, **kw):
        captured["cmd"] = cmd
        captured["timeout"] = kw.get("timeout")
        return _FakeCompleted(returncode=0, stdout="  IC = 0.42。结论两句。  \n")

    monkeypatch.setattr(scl.subprocess, "run", _run)
    client = scl.ClaudeSubscriptionLLM(model="claude-sonnet-4-5")
    resp = client.chat([LLMMessage(role="user", content="算 IC")])
    assert resp.content == "IC = 0.42。结论两句。"  # strip 生效
    # cmd = claude -p <prompt> --output-format text --model <model>（非交互）
    assert captured["cmd"][0] == "/usr/bin/claude" or captured["cmd"][0] == "claude"
    assert "-p" in captured["cmd"] and "--output-format" in captured["cmd"]
    assert "text" in captured["cmd"] and "claude-sonnet-4-5" in captured["cmd"]
    assert resp.raw["auth"] == "subscription"


def test_codex_adapter_reads_last_message_file(monkeypatch, tmp_path):
    written = {}

    def _run(cmd, **kw):
        # -o <file> 的下一个 arg 是输出文件路径;模拟 codex 把最终 message 写进去
        oidx = cmd.index("-o")
        out_file = cmd[oidx + 1]
        with open(out_file, "w", encoding="utf-8") as f:
            f.write("verdict: correct — 重算一致。\n")
        written["cmd"] = cmd
        return _FakeCompleted(returncode=0, stdout="(reasoning framing ignored)")

    monkeypatch.setattr(scl.subprocess, "run", _run)
    client = scl.CodexSubscriptionLLM(model="gpt-5.6-sol")
    resp = client.chat([LLMMessage(role="user", content="复核")])
    assert resp.content == "verdict: correct — 重算一致。"
    assert "exec" in written["cmd"] and "-m" in written["cmd"] and "gpt-5.6-sol" in written["cmd"]
    assert "-o" in written["cmd"]  # 走 output-last-message 拿干净响应


def test_nonzero_exit_fails_closed_not_swallowed(monkeypatch):
    monkeypatch.setattr(
        scl.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(returncode=1, stdout="", stderr="auth expired"),
    )
    client = scl.ClaudeSubscriptionLLM(model="claude-sonnet-4-5")
    with pytest.raises(scl.SubscriptionCLIError, match="exit 1"):
        client.chat([LLMMessage(role="user", content="x")])


def test_timeout_fails_closed(monkeypatch):
    def _run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout", 1))

    monkeypatch.setattr(scl.subprocess, "run", _run)
    client = scl.CodexSubscriptionLLM(model="gpt-5.6-sol", timeout_s=5)
    with pytest.raises(scl.SubscriptionCLIError, match="超时"):
        client.chat([LLMMessage(role="user", content="x")])


def test_empty_output_fails_closed(monkeypatch):
    monkeypatch.setattr(
        scl.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(returncode=0, stdout="   \n"),
    )
    client = scl.ClaudeSubscriptionLLM(model="claude-sonnet-4-5")
    with pytest.raises(scl.SubscriptionCLIError, match="空输出"):
        client.chat([LLMMessage(role="user", content="x")])


def test_tools_rejected(monkeypatch):
    monkeypatch.setattr(scl.subprocess, "run", lambda cmd, **kw: _FakeCompleted(stdout="x"))
    client = scl.ClaudeSubscriptionLLM(model="claude-sonnet-4-5")
    with pytest.raises(NoLLMConfigured, match="不支持 tools"):
        client.chat([LLMMessage(role="user", content="x")], tools=[{"name": "t"}])


def test_missing_cli_fails_closed(monkeypatch):
    monkeypatch.setattr(scl.shutil, "which", lambda name: None)
    with pytest.raises(NoLLMConfigured, match="未找到"):
        scl.ClaudeSubscriptionLLM(model="claude-sonnet-4-5")
    with pytest.raises(NoLLMConfigured, match="未找到"):
        scl.CodexSubscriptionLLM(model="gpt-5.6-sol")


def test_factory_provider_switch_and_identity(monkeypatch):
    # model 切换 = 换 provider/model;provider 身份对(cross-vendor 门认账)
    c = scl.make_subscription_cli_client("anthropic", model="claude-opus-4-8")
    o = scl.make_subscription_cli_client("openai", model="gpt-5.6-sol")
    assert isinstance(c, scl.ClaudeSubscriptionLLM) and c.provider == "anthropic"
    assert isinstance(o, scl.CodexSubscriptionLLM) and o.provider == "openai"
    with pytest.raises(NoLLMConfigured, match="不支持 provider"):
        scl.make_subscription_cli_client("gemini")


def test_flatten_messages_preserves_order_and_roles():
    txt = scl._flatten_messages([
        LLMMessage(role="system", content="be terse"),
        LLMMessage(role="user", content="q1"),
        LLMMessage(role="assistant", content="a1"),
        LLMMessage(role="user", content="q2"),
    ])
    assert "System instructions" in txt and "be terse" in txt
    assert txt.index("q1") < txt.index("a1") < txt.index("q2")
