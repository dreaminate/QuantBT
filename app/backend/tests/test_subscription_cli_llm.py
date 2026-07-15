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


def test_auth_detect_claude_logged_in_json(monkeypatch):
    monkeypatch.setattr(
        scl.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(0, '{"loggedIn": true, "authMethod": "claude.ai"}'),
    )
    authed, note = scl.subscription_auth_status("anthropic")
    assert authed is True and "claude.ai" in note


def test_auth_detect_claude_logged_out(monkeypatch):
    monkeypatch.setattr(
        scl.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(0, '{"loggedIn": false}'),
    )
    authed, _ = scl.subscription_auth_status("anthropic")
    assert authed is False


def test_auth_detect_codex_logged_in_text(monkeypatch):
    monkeypatch.setattr(
        scl.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(0, "Logged in using ChatGPT\n"),
    )
    authed, note = scl.subscription_auth_status("openai")
    assert authed is True and "ChatGPT" in note


def test_auth_detect_cli_missing(monkeypatch):
    monkeypatch.setattr(scl.shutil, "which", lambda name: None)
    authed, note = scl.subscription_auth_status("openai")
    assert authed is False and "未安装" in note


def test_anthropic_console_login_not_reported_as_subscription(monkeypatch):
    # §3 false-green 防护:console(--console)=按量计费,loggedIn=true 但**绝不能**标「订阅·无按量费」。
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        scl.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(0, '{"loggedIn": true, "authMethod": "console", "apiProvider": "console"}'),
    )
    authed, note = scl.subscription_auth_status("anthropic")
    assert authed is False
    assert "非订阅" in note or "Console" in note


def test_anthropic_real_subscription_format_is_authed(monkeypatch):
    # 真实 `claude auth status --json` 订阅输出(claude.ai / firstParty / max)→ 认订阅。
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        scl.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(
            0,
            '{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty", "subscriptionType": "max"}',
        ),
    )
    authed, note = scl.subscription_auth_status("anthropic")
    assert authed is True and "claude.ai" in note and "max" in note


def test_report_console_login_not_ready_as_subscription(monkeypatch, tmp_path):
    # 报告层(UI/端点消费):console 登录 + 无 api key → subscription_authed=False 且 ready=False(不误报免费可用)。
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(
        scl.subprocess, "run",
        lambda cmd, **kw: _FakeCompleted(0, '{"loggedIn": true, "authMethod": "console"}'),
    )
    rep = scl.provider_auth_report("anthropic", secrets_path=tmp_path / "none.yaml")
    assert rep["subscription_authed"] is False
    assert rep["ready"] is False


def test_codex_note_does_not_echo_raw_cli_output(monkeypatch):
    # 防御纵深:codex status 原始 stdout 绝不回显进 note(未来版本首行可能打账号/敏感串)。
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")
    leak = "Logged in using ChatGPT (token=sk-secret-LEAK)"
    monkeypatch.setattr(scl.subprocess, "run", lambda cmd, **kw: _FakeCompleted(0, leak + "\n"))
    authed, note = scl.subscription_auth_status("openai")
    assert authed is True
    assert "sk-secret-LEAK" not in note and "token=" not in note
    assert note == "已登录（ChatGPT 订阅）"


def test_onboarding_cli_login_uses_clean_argv_not_setup_token(monkeypatch):
    # K4 回归门(覆盖 scripts/llm_auth.py 调用点):onboarding CLI 的 login 必须走 _CLI_META login_cmd
    # (claude auth login --claudeai),**绝不** setup-token——否则用户终端会被打出长效 token。
    import sys
    from pathlib import Path

    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    import llm_auth  # noqa: E402

    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")
    captured: dict = {}

    def _fake_run(cmd, **kw):
        captured["cmd"] = cmd
        return _FakeCompleted(0)

    monkeypatch.setattr(llm_auth.subprocess, "run", _fake_run)
    llm_auth._login("anthropic")
    assert captured["cmd"] == ["claude", "auth", "login", "--claudeai"]
    assert "setup-token" not in " ".join(captured["cmd"])


def test_report_fresh_user_gets_install_and_login_steps(monkeypatch, tmp_path):
    # 陌生用户:CLI 没装 + 无 api key → next_action 必含安装+登录+api-key 三条路
    monkeypatch.setattr(scl.shutil, "which", lambda name: None)
    rep = scl.provider_auth_report("anthropic", secrets_path=tmp_path / "none.yaml")
    assert rep["ready"] is False and rep["cli_installed"] is False
    assert "install" in rep["next_action"] or "装 CLI" in rep["next_action"]
    # K4 修正:引导走 `claude auth login`(浏览器→keychain,后端不碰 token),
    # 不再推 `claude setup-token`——后者把长效 token 打到 stdout,后端一旦读即泄漏面。
    assert "auth login" in rep["next_action"]
    assert "setup-token" not in rep["next_action"]
    assert "api_key" in rep["next_action"]


def test_report_api_key_only_is_ready(monkeypatch, tmp_path):
    # 只配了 api key(没装 CLI)也算就绪
    monkeypatch.setattr(scl.shutil, "which", lambda name: None)
    sec = tmp_path / "secrets.yaml"
    sec.write_text("llm:\n  openai:\n    api_key: sk-test-xyz\n", encoding="utf-8")
    rep = scl.provider_auth_report("openai", secrets_path=sec)
    assert rep["ready"] is True and rep["api_key_configured"] is True


def test_report_cli_installed_not_logged_in(monkeypatch, tmp_path):
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(scl.subprocess, "run", lambda cmd, **kw: _FakeCompleted(0, "Not logged in"))
    rep = scl.provider_auth_report("openai", secrets_path=tmp_path / "none.yaml")
    assert rep["ready"] is False and rep["cli_installed"] is True
    assert "登录" in rep["next_action"]


_CREDENTIAL_MARKERS = ("token", "secret", "api_key", "apikey", "password", "sk-", "bearer")


def _has_credential_leak(obj) -> bool:
    """返回体里是否混进了凭据味的 key/value(login relay 绝不该回显任何凭据)。"""
    for k, v in obj.items():
        key = str(k).lower()
        if any(m in key for m in _CREDENTIAL_MARKERS):
            return True
        if isinstance(v, str) and any(m in v.lower() for m in ("token=", "secret=", "sk-ant-", "sk-proj-")):
            return True
    return False


def test_login_cmd_uses_auth_login_not_setup_token():
    # K4:登录走 `claude auth login --claudeai`(浏览器→keychain,后端不碰 token)。
    # 绝不用 `claude setup-token`(把长效 token 打到 stdout=泄漏面)。
    assert scl._CLI_META["anthropic"]["login_cmd"] == ["claude", "auth", "login", "--claudeai"]
    assert "setup-token" not in " ".join(scl._CLI_META["anthropic"]["login_cmd"])
    assert "setup-token" not in scl._CLI_META["anthropic"]["login"]
    assert scl._CLI_META["openai"]["login_cmd"] == ["codex", "login"]


def test_begin_login_unknown_provider_not_launched():
    spawned = []
    r = scl.begin_subscription_login("gemini", spawn=lambda cmd: spawned.append(cmd))
    assert r["launched"] is False and "未知 provider" in r["error"]
    assert spawned == []  # 未知 provider 绝不 spawn 任何进程


def test_begin_login_cli_not_installed_returns_install_no_spawn(monkeypatch):
    monkeypatch.setattr(scl.shutil, "which", lambda name: None)
    spawned = []
    r = scl.begin_subscription_login("anthropic", spawn=lambda cmd: spawned.append(cmd))
    assert r["launched"] is False and r["cli_installed"] is False
    assert r["install_command"] and "未安装" in r["error"]
    assert r["guided_command"] == "claude auth login --claudeai"
    assert spawned == []  # 没装 CLI 不 spawn


def test_begin_login_installed_spawns_correct_argv(monkeypatch):
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")
    spawned = []
    ra = scl.begin_subscription_login("anthropic", spawn=lambda cmd: spawned.append(cmd))
    ro = scl.begin_subscription_login("openai", spawn=lambda cmd: spawned.append(cmd))
    assert ra["launched"] is True and ro["launched"] is True
    assert spawned[0] == ["claude", "auth", "login", "--claudeai"]
    assert spawned[1] == ["codex", "login"]
    # 返回体绝无凭据字段
    assert not _has_credential_leak(ra) and not _has_credential_leak(ro)


def test_begin_login_spawn_oserror_returns_guided(monkeypatch):
    monkeypatch.setattr(scl.shutil, "which", lambda name: f"/usr/bin/{name}")

    def _boom(cmd):
        raise OSError("no display")

    r = scl.begin_subscription_login("openai", spawn=_boom)
    assert r["launched"] is False and "启动登录失败" in r["error"]
    assert r["guided_command"] == "codex login"  # 降级:终端可直接跑的命令仍给出


def test_spawn_detached_never_captures_output(monkeypatch):
    # 承重安全门:登录子进程 stdout/stderr/stdin 必须全 DEVNULL——后端绝不捕获(不碰 token)。
    # 把任一改成 PIPE 的变异必须打红本测试。
    captured = {}

    class _FakePopen:
        def __init__(self, cmd, **kw):
            captured["cmd"] = cmd
            captured["kw"] = kw

    monkeypatch.setattr(scl.subprocess, "Popen", _FakePopen)
    scl._spawn_detached_login(["claude", "auth", "login", "--claudeai"])
    assert captured["cmd"] == ["claude", "auth", "login", "--claudeai"]
    assert captured["kw"]["stdout"] == scl.subprocess.DEVNULL
    assert captured["kw"]["stderr"] == scl.subprocess.DEVNULL
    assert captured["kw"]["stdin"] == scl.subprocess.DEVNULL
    # 不 wait:分离会话(start_new_session)防登录挂住后端
    assert captured["kw"].get("start_new_session") is True


def test_flatten_messages_preserves_order_and_roles():
    txt = scl._flatten_messages([
        LLMMessage(role="system", content="be terse"),
        LLMMessage(role="user", content="q1"),
        LLMMessage(role="assistant", content="a1"),
        LLMMessage(role="user", content="q2"),
    ])
    assert "System instructions" in txt and "be terse" in txt
    assert txt.index("q1") < txt.index("a1") < txt.index("q2")
