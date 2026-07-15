"""订阅账号 LLM adapter——经厂商官方 CLI(claude / codex)用订阅账号调用模型。

为什么走 CLI 子进程而非 HTTP token 重放:
- Claude 的 `sk-ant-oat` OAuth token 直连 Messages API 会被拒;要程序化用必须模仿
  Claude Code 的请求签名(anthropic-beta oauth header + 系统提示),脆弱且 undocumented。
- CLI 自己处理 OAuth 登录 / token 刷新 / 请求签名,且**本就为脚本/CI 设计**
  (Claude Code 文档明列 CLAUDE_CODE_OAUTH_TOKEN 供 CI/脚本)——比 token 重放稳、受支持、
  ToS 灰度低。
- 跨厂商真独立:builder=claude(claude CLI) / verifier=gpt(codex CLI)是两个不同厂商的
  官方客户端 → dual-model 独立性主张更强。

交互 auth(用户在终端/浏览器做一次,本 adapter 不碰凭据):
- Anthropic 订阅:`claude auth login --claudeai`(弹浏览器登 claude.ai,凭据存 CLI keychain)。
  刻意**不用** `claude setup-token`——它把长效 token 打到 stdout,一旦被程序读到即泄漏面(K4)。
- OpenAI/ChatGPT 订阅:`codex login`(Sign in with ChatGPT)。

诚实边界:
- 仅文本 chat,**不支持 tools**(CLI 自己做 tool use,不经本 adapter)。
- temperature 不经 CLI 统一暴露 → 忽略(记录在 raw,不假装可控)。
- 凭据在 CLI 自己的安全存储里,本 adapter 从不读取/传递/记录 token(env 原样透传)。
- ToS:用订阅账号做官方 app/CLI 之外的自动化,是否合规由用户自担(个人本地使用)。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .llm_client import LLMClient, LLMMessage, LLMResponse, NoLLMConfigured

# provider → 厂商 CLI onboarding 元数据(陌生用户从零 auth 用)。
_CLI_META: dict[str, dict[str, Any]] = {
    "anthropic": {
        "cli": "claude",
        "label": "Claude 订阅 (Pro/Max)",
        "install": "npm install -g @anthropic-ai/claude-code",
        # 交互登录：弹浏览器登 claude.ai，凭据存进 claude CLI 自己的 keychain——后端全程不碰 token。
        # 刻意**不用** `claude setup-token`：它把长效 token 打到 stdout，后端一旦读就构成泄漏面（K4 红线）。
        "login": "claude auth login --claudeai",
        "login_cmd": ["claude", "auth", "login", "--claudeai"],
        "status_cmd": ["claude", "auth", "status"],
    },
    "openai": {
        "cli": "codex",
        "label": "ChatGPT 订阅 (Plus/Pro)",
        "install": "npm install -g @openai/codex",
        # Sign in with ChatGPT，弹浏览器；token 存进 codex CLI 自己的 ~/.codex——后端不碰。
        "login": "codex login",
        "login_cmd": ["codex", "login"],
        "status_cmd": ["codex", "login", "status"],
    },
}


def cli_installed(provider: str) -> bool:
    meta = _CLI_META.get((provider or "").strip().lower())
    return bool(meta) and shutil.which(meta["cli"]) is not None


def subscription_auth_status(provider: str, *, timeout_s: float = 20.0) -> tuple[bool, str]:
    """检测某 provider 的订阅 CLI 是否已登录。返回 (authed, 人读说明)。

    不暴露账号细节、不烧 token(用 CLI 自带的 status 命令,零真实模型调用)。
    - claude auth status → JSON {"loggedIn": bool, "authMethod": ...}
    - codex login status → "Logged in using ChatGPT" / not-logged-in
    """
    key = (provider or "").strip().lower()
    meta = _CLI_META.get(key)
    if not meta:
        return False, f"未知 provider={provider!r}"
    if shutil.which(meta["cli"]) is None:
        return False, f"{meta['cli']} CLI 未安装"
    try:
        r = subprocess.run(
            meta["status_cmd"], capture_output=True, text=True, timeout=timeout_s,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False, f"{meta['cli']} 状态检测失败"
    out = (r.stdout or "") + (r.stderr or "")
    if key == "anthropic":
        try:
            data = json.loads(r.stdout or "{}")
        except (json.JSONDecodeError, AttributeError):
            # JSON 解析失败 → 保守 fail-safe:仅当原始输出明确含订阅信号才认订阅(不认 console/按量计费)。
            low = out.lower()
            authed = r.returncode == 0 and ("claude.ai" in low or "firstparty" in low)
            return authed, "状态未知"
        if not bool(data.get("loggedIn")):
            return False, "未登录"
        # `claude auth login` 有两条:--claudeai(订阅·免按量费) 与 --console(Anthropic Console·按量计费)。
        # console 登录也 loggedIn=true,但**绝不能**冒充「订阅·无按量费」(§3 诚实,否则用户以为免费实则按量扣费)。
        # 订阅正信号:authMethod=claude.ai / apiProvider=firstParty / 有 subscriptionType;console 负信号:含 console。
        method = str(data.get("authMethod") or "").strip().lower()
        api_provider = str(data.get("apiProvider") or "").strip().lower()
        sub_type = str(data.get("subscriptionType") or "").strip()
        is_console = "console" in method or "console" in api_provider
        is_subscription = (not is_console) and (
            method == "claude.ai" or api_provider == "firstparty" or bool(sub_type)
        )
        if is_subscription:
            bits = "·".join(b for b in (method, sub_type) if b)
            return True, "已登录（订阅" + (f"·{bits}" if bits else "") + "）"
        # 登录了但不是订阅(console/按量计费,或方式未知)→ 不认订阅(免按量费的承诺不成立)。
        return False, "已登录但非订阅（Console/按量计费）——免按量费请用订阅登录 claude auth login --claudeai，或走 API key 线"
    # openai / codex：文本 "Logged in using ChatGPT"。不回显 CLI 原始 stdout(固定状态串,
    # 防未来 codex 版本在首行打出账号/敏感信息经本 note 泄漏 → 防御纵深)。
    logged = r.returncode == 0 and "logged in" in out.lower() and "not logged" not in out.lower()
    return logged, ("已登录（ChatGPT 订阅）" if logged else "未登录")


def _api_key_configured(provider: str, secrets_path: Path | None = None) -> bool:
    """secrets.yaml 里该 provider 有没有 api_key(不读值,只看存在性)。"""
    path = secrets_path or (Path.home() / ".quantbt" / "secrets.yaml")
    if not path.exists():
        return False
    try:
        import yaml

        raw = yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001
        return False
    entry = ((raw.get("llm") or {}).get(provider) or {})
    return isinstance(entry, dict) and bool(str(entry.get("api_key") or "").strip())


def provider_auth_report(
    provider: str, *, secrets_path: Path | None = None, timeout_s: float = 20.0
) -> dict[str, Any]:
    """一个 provider 的完整认证画像 + 缺口的确切下一步(陌生用户 onboarding)。

    timeout_s 传给订阅登录探测子进程——轮询端点可传较短值,避免挂死的 status 命令长时间占 FastAPI 线程。
    """
    key = (provider or "").strip().lower()
    meta = _CLI_META.get(key, {})
    installed = cli_installed(key)
    sub_authed, sub_note = (
        subscription_auth_status(key, timeout_s=timeout_s) if installed
        else (False, f"{meta.get('cli', key)} CLI 未安装")
    )
    api_key = _api_key_configured(key, secrets_path)
    ready = sub_authed or api_key
    if ready:
        method = "订阅" if sub_authed else "API key"
        next_action = f"就绪（{method}）——无需操作"
    elif not installed:
        next_action = (
            f"方式A(订阅·推荐·无按量费): 1) 装 CLI: {meta.get('install', '?')}  "
            f"2) 登录: {meta.get('login', '?')}   |   "
            f"方式B(API key): 编辑 ~/.quantbt/secrets.yaml 填 llm.{key}.api_key"
        )
    else:
        next_action = (
            f"CLI 已装但未登录 → 交互登录一次: {meta.get('login', '?')}   |   "
            f"或用 API key: 编辑 ~/.quantbt/secrets.yaml 填 llm.{key}.api_key"
        )
    return {
        "provider": key,
        "label": meta.get("label", key),
        "cli": meta.get("cli", ""),
        "cli_installed": installed,
        "subscription_authed": sub_authed,
        "subscription_note": sub_note,
        "api_key_configured": api_key,
        "ready": ready,
        "next_action": next_action,
    }


def auth_status_all(
    *, secrets_path: Path | None = None, timeout_s: float = 20.0
) -> list[dict[str, Any]]:
    return [
        provider_auth_report(p, secrets_path=secrets_path, timeout_s=timeout_s)
        for p in ("anthropic", "openai")
    ]


def _spawn_detached_login(cmd: list[str]) -> None:
    """把厂商 CLI 的交互登录作为**分离子进程**拉起：CLI 自己开浏览器、等 OAuth 回调、把凭据
    存进它自己的 keychain/config。后端刻意：
    - stdin=DEVNULL —— 不喂键盘输入（也防它等 TTY 挂死本进程）；
    - stdout/stderr=DEVNULL —— **绝不捕获**（token/URL 一旦经 stdout 就可能被后端读到 → 泄漏面）；
    - 不 wait —— 登录可能耗时几十秒，挂住 HTTP 请求不可接受；进程完成后自行退出。
    这就是「后端不碰 token」边界的落点：把 stdout 换成 PIPE 的变异必须被测试打红。
    """
    subprocess.Popen(  # noqa: S603 —— cmd 来自 _CLI_META 固定 argv，非用户输入，无 shell 注入面
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=os.environ.copy(),
    )


def begin_subscription_login(provider: str, *, spawn: Any = None) -> dict[str, Any]:
    """发起某 provider 的订阅账号交互登录（in-app relay）。

    机制：拉起厂商 CLI 的浏览器登录（本地机上弹用户自己的浏览器）；后端全程不读/不存/不返回
    token——凭据只落进 CLI 自己的 keychain。返回体**只含**流程信息（launched / cli / 引导命令），
    绝不含任何凭据字段。登录后由 subscription_auth_status（另起 `... status` 子进程读 keychain）
    检测到已登录，前端轮询即可转绿；不需要重启后端。

    诚实降级：detached-spawn 是**便利**（本地能弹浏览器时一键），若浏览器没弹（如 headless），
    guided_command 始终给出可在终端直接跑的命令——承重的是「状态检测 + 轮询」，不是这个 spawn。
    """
    key = (provider or "").strip().lower()
    meta = _CLI_META.get(key)
    if not meta:
        return {"launched": False, "provider": key, "error": f"未知 provider={provider!r}"}
    guided = " ".join(meta.get("login_cmd") or []) or str(meta.get("login") or "")
    base = {
        "launched": False,
        "provider": key,
        "cli": meta.get("cli", ""),
        "guided_command": guided,
    }
    if shutil.which(meta["cli"]) is None:
        return {
            **base,
            "cli_installed": False,
            "install_command": meta.get("install", ""),
            "error": f"{meta['cli']} CLI 未安装——先安装再登录",
        }
    login_cmd = list(meta.get("login_cmd") or [])
    if not login_cmd:
        return {**base, "cli_installed": True, "error": f"{key} 未配置 login_cmd"}
    runner = spawn or _spawn_detached_login
    try:
        runner(login_cmd)
    except OSError as exc:
        return {**base, "cli_installed": True, "error": f"启动登录失败：{exc}"}
    return {
        "launched": True,
        "provider": key,
        "cli": meta.get("cli", ""),
        "cli_installed": True,
        "guided_command": guided,
        "hint": (
            "已尝试打开浏览器完成登录；请在浏览器里登入你的订阅账号。完成后本页会自动检测到已登录。"
            "若浏览器未弹出（如远程/无桌面环境），在终端直接运行上面的命令即可。"
        ),
    }


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
                f"未找到 claude CLI({cli_path})——订阅调用需安装 Claude Code 并 `claude auth login --claudeai`"
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
    "cli_installed",
    "subscription_auth_status",
    "provider_auth_report",
    "auth_status_all",
    "begin_subscription_login",
]
