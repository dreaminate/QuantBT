#!/usr/bin/env python3
"""LLM 认证 onboarding —— 陌生用户从零把 OpenAI + Anthropic 账号接上 QuantBT。

两种认证方式，任选其一(或混用):
- 订阅(推荐,无按量费):用你的 Claude Pro/Max + ChatGPT Plus/Pro 订阅账号,经厂商官方
  CLI(claude / codex)登录。CLI 自理 OAuth / token 刷新 / 请求签名。
- API key:在 ~/.quantbt/secrets.yaml 填 llm.<provider>.api_key(按 token 计费)。

用法:
  python scripts/llm_auth.py status         # 看两家认证状态 + 缺口的确切下一步
  python scripts/llm_auth.py login <p>       # 交互登录订阅(弹浏览器;p=anthropic|openai)
  python scripts/llm_auth.py verify [<p>]     # 真调一句验活(默认两家都验)

本脚本从不读取/输出/记录任何凭据 token —— 登录由厂商 CLI 完成、token 存 CLI 自己的
安全存储;本脚本只检测「是否已登录」并给指引。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "backend"))

# 登录命令的单一源 = subscription_cli_llm._CLI_META[...]["login_cmd"]（in-app relay 与本 CLI 同一份，
# 不重复维护、不漂移）。anthropic 走 `claude auth login --claudeai`（浏览器→keychain），
# 刻意不用 `claude setup-token`（会把长效 token 打到 stdout=泄漏面，K4）。


def _print_status() -> int:
    from app.agent.subscription_cli_llm import auth_status_all

    reports = auth_status_all()
    print("LLM 认证状态（QuantBT）:\n")
    all_ready = True
    for r in reports:
        mark = "✅ 就绪" if r["ready"] else "❌ 未就绪"
        print(f"  {r['label']}  [{r['provider']}]  {mark}")
        print(f"    CLI({r['cli']})已装: {'是' if r['cli_installed'] else '否'}"
              f" | 订阅登录: {'是' if r['subscription_authed'] else '否'}"
              f"（{r['subscription_note']}）"
              f" | API key: {'已配' if r['api_key_configured'] else '未配'}")
        if not r["ready"]:
            all_ready = False
            print(f"    → 下一步: {r['next_action']}")
        print()
    if all_ready:
        print("两家都就绪。可跑 dual-model 跨厂商审查(builder=claude / verifier=gpt)。")
    else:
        print("按上面「下一步」把未就绪的接上;订阅方式登录一次即可长期用。")
    return 0 if all_ready else 1


def _login(provider: str) -> int:
    key = (provider or "").strip().lower()
    from app.agent.subscription_cli_llm import cli_installed, _CLI_META

    if key not in _CLI_META:
        raise SystemExit(f"login 只支持 anthropic / openai，收到 {provider!r}")
    meta = _CLI_META[key]
    if not cli_installed(key):
        raise SystemExit(
            f"{meta['cli']} CLI 未安装 —— 先装: {meta['install']}\n然后重跑本命令。"
        )
    cmd = list(meta.get("login_cmd") or [])
    if not cmd:
        raise SystemExit(f"{key} 未配置 login_cmd")
    print(f"启动交互登录（{key}）: {' '.join(cmd)}\n"
          "按提示在浏览器完成登录，回来后跑 `python scripts/llm_auth.py verify` 验活。\n")
    # 交互式登录：不捕获输出，让 CLI 直接接管终端/浏览器流（token 存 CLI keychain，本脚本不碰）。
    return subprocess.run(cmd).returncode


def _verify(provider: str | None) -> int:
    from app.agent.subscription_cli_llm import make_subscription_cli_client, provider_auth_report
    from app.agent.llm_client import LLMMessage

    targets = [provider.strip().lower()] if provider else ["anthropic", "openai"]
    ok = True
    for key in targets:
        rep = provider_auth_report(key)
        if not rep["subscription_authed"]:
            print(f"  {key}: 订阅未登录，跳过验活（{rep['next_action']}）")
            ok = False
            continue
        try:
            client = make_subscription_cli_client(key, timeout_s=120)
            resp = client.chat([LLMMessage(role="user", content="Reply with exactly: pong")])
            got = (resp.content or "").strip()[:40]
            print(f"  {key}: ✅ 订阅调通 → {got!r}（model {resp.raw.get('model')}）")
        except Exception as exc:  # noqa: BLE001
            print(f"  {key}: ❌ 验活失败 {type(exc).__name__}: {str(exc)[:120]}")
            ok = False
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="看两家认证状态 + 下一步")
    p_login = sub.add_parser("login", help="交互登录订阅")
    p_login.add_argument("provider", choices=["anthropic", "openai"])
    p_verify = sub.add_parser("verify", help="真调一句验活")
    p_verify.add_argument("provider", nargs="?", choices=["anthropic", "openai"])
    args = parser.parse_args(argv)
    if args.cmd == "status":
        return _print_status()
    if args.cmd == "login":
        return _login(args.provider)
    if args.cmd == "verify":
        return _verify(args.provider)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
