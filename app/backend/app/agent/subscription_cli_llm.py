"""订阅账号 LLM adapter——经厂商官方 CLI(claude / codex)用订阅账号调用模型。

为什么走 CLI 子进程而非 HTTP token 重放:
- Claude 的 `sk-ant-oat` OAuth token 直连 Messages API 会被拒;要程序化用必须模仿
  Claude Code 的请求签名(anthropic-beta oauth header + 系统提示),脆弱且 undocumented。
- CLI 自己处理 OAuth 登录 / token 刷新 / 请求签名,且**本就为脚本/CI 设计**
  (Claude Code 文档明列 CLAUDE_CODE_OAUTH_TOKEN 供 CI/脚本)——比 token 重放稳、受支持、
  ToS 灰度低。
- 跨厂商真独立:builder=claude(claude CLI) / verifier=gpt(codex CLI)是两个不同厂商的
  官方客户端 → dual-model 独立性主张更强。

交互 auth(用户在终端做一次,本 adapter 不碰凭据):
- Anthropic 订阅:`claude setup-token`(或已登录的 Claude Code)。
- OpenAI/ChatGPT 订阅:`codex login`(Sign in with ChatGPT)。

诚实边界:
- 仅文本 chat,**不支持 tools**(CLI 自己做 tool use,不经本 adapter)。
- temperature 不经 CLI 统一暴露 → 忽略(记录在 raw,不假装可控)。
- 凭据在 CLI 自己的安全存储里,本 adapter 从不读取/传递/记录 token(env 原样透传)。
- ToS:用订阅账号做官方 app/CLI 之外的自动化,是否合规由用户自担(个人本地使用)。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .llm_client import LLMClient, LLMMessage, LLMResponse, NoLLMConfigured


class SubscriptionCLIError(RuntimeError):
    """订阅 CLI 调用失败(非零退出 / 超时 / 空输出)。不含凭据。"""


def _flatten_messages(messages: list[LLMMessage]) -> str:
    """多轮 messages 摊平为单 prompt(CLI 是单 prompt in / text out)。"""
    parts: list[str] = []
    for m in messages:
        content = (m.content or "").strip()
        if not content:
            continue
        if m.role == "system":
            parts.append(f"[System instructions]\n{content}")
        elif m.role == "assistant":
            parts.append(f"[Assistant]\n{content}")
        else:  # user / tool → 直接并入
            parts.append(content)
    return "\n\n".join(parts)


class ClaudeSubscriptionLLM(LLMClient):
    """经 `claude -p`(Claude Code 非交互模式)用 Anthropic 订阅账号调用。"""

    provider = "anthropic"

    def __init__(self, *, model: str, cli_path: str = "claude", timeout_s: float = 300.0) -> None:
        if not model:
            raise NoLLMConfigured("ClaudeSubscriptionLLM 需要 model(如 claude-sonnet-4-5)")
        if not shutil.which(cli_path):
            raise NoLLMConfigured(
                f"未找到 claude CLI({cli_path})——订阅调用需安装 Claude Code 并 `claude setup-token`"
            )
        self._cli = cli_path
        self._model = model
        self._timeout = float(timeout_s)

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        if tools:
            raise NoLLMConfigured("订阅 CLI adapter 不支持 tools(CLI 自理 tool use)")
        used_model = model or self._model
        prompt = _flatten_messages(messages)
        cmd = [self._cli, "-p", prompt, "--output-format", "text", "--model", used_model]
        try:
            r = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self._timeout, env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            raise SubscriptionCLIError(f"claude CLI 超时({self._timeout}s)") from exc
        if r.returncode != 0:
            raise SubscriptionCLIError(
                f"claude CLI 调用失败(exit {r.returncode}): {(r.stderr or '').strip()[:200]}"
            )
        content = (r.stdout or "").strip()
        if not content:
            raise SubscriptionCLIError("claude CLI 返回空输出")
        return LLMResponse(
            content=content, tool_calls=[],
            raw={"cli": "claude", "model": used_model, "auth": "subscription", "temperature": temperature},
        )

    def stream_chat(self, messages, *, model=None, temperature=0.2):  # noqa: ANN001
        yield self.chat(messages, model=model, temperature=temperature).content


class CodexSubscriptionLLM(LLMClient):
    """经 `codex exec`(Codex 非交互模式)用 OpenAI/ChatGPT 订阅账号调用。"""

    provider = "openai"

    def __init__(self, *, model: str, cli_path: str = "codex", timeout_s: float = 600.0) -> None:
        if not model:
            raise NoLLMConfigured("CodexSubscriptionLLM 需要 model(如 gpt-5.6-sol)")
        if not shutil.which(cli_path):
            raise NoLLMConfigured(
                f"未找到 codex CLI({cli_path})——订阅调用需安装 Codex 并 `codex login`(Sign in with ChatGPT)"
            )
        self._cli = cli_path
        self._model = model
        self._timeout = float(timeout_s)

    def chat(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
    ) -> LLMResponse:
        if tools:
            raise NoLLMConfigured("订阅 CLI adapter 不支持 tools(CLI 自理 tool use)")
        used_model = model or self._model
        prompt = _flatten_messages(messages)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", prefix="codex-last-", delete=False,
        ) as fh:
            last_path = Path(fh.name)
        try:
            cmd = [
                self._cli, "exec", prompt, "-m", used_model,
                "--sandbox", "read-only", "-o", str(last_path),
            ]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=self._timeout)
            except subprocess.TimeoutExpired as exc:
                raise SubscriptionCLIError(f"codex CLI 超时({self._timeout}s)") from exc
            if r.returncode != 0:
                raise SubscriptionCLIError(
                    f"codex CLI 调用失败(exit {r.returncode}): {(r.stderr or '').strip()[:200]}"
                )
            content = last_path.read_text(encoding="utf-8").strip() if last_path.exists() else ""
            if not content:
                raise SubscriptionCLIError("codex CLI 返回空输出")
            return LLMResponse(
                content=content, tool_calls=[],
                raw={"cli": "codex", "model": used_model, "auth": "subscription", "temperature": temperature},
            )
        finally:
            last_path.unlink(missing_ok=True)

    def stream_chat(self, messages, *, model=None, temperature=0.2):  # noqa: ANN001
        yield self.chat(messages, model=model, temperature=temperature).content


# provider → (adapter class, 默认模型)。model 切换 = 换 model 参数即可。
_SUBSCRIPTION_ADAPTERS = {
    "anthropic": (ClaudeSubscriptionLLM, "claude-sonnet-4-5"),
    "claude": (ClaudeSubscriptionLLM, "claude-sonnet-4-5"),
    "openai": (CodexSubscriptionLLM, "gpt-5.6-sol"),
    "codex": (CodexSubscriptionLLM, "gpt-5.6-sol"),
    "gpt": (CodexSubscriptionLLM, "gpt-5.6-sol"),
}


def make_subscription_cli_client(provider: str, *, model: str | None = None, **kwargs: Any) -> LLMClient:
    """按 provider 造订阅 CLI adapter(model 切换 = 传 model)。

    provider ∈ {anthropic/claude, openai/codex/gpt}。未知 provider → NoLLMConfigured。
    """
    key = (provider or "").strip().lower()
    if key not in _SUBSCRIPTION_ADAPTERS:
        raise NoLLMConfigured(
            f"订阅 CLI adapter 不支持 provider={provider!r}(支持:anthropic/claude, openai/codex/gpt)"
        )
    cls, default_model = _SUBSCRIPTION_ADAPTERS[key]
    return cls(model=model or default_model, **kwargs)


__all__ = [
    "ClaudeSubscriptionLLM",
    "CodexSubscriptionLLM",
    "SubscriptionCLIError",
    "make_subscription_cli_client",
]
