"""读 ~/.quantbt/secrets.yaml 并安全注入到 SecureKeystore + 进程内 env。

设计：
- 文件路径默认 `~/.quantbt/secrets.yaml`，可被 `QUANTBT_SECRETS_PATH` 覆盖
- 文件权限自动收紧为 0600（仅当前用户读写），否则启动 warning
- 任何 secret 永远不打印到日志；只回报字段名 + 状态
- 支持热加载：`POST /api/security/reload_secrets`
- yaml 缺失 / 任何字段空 → 不抛错，跳过对应 provider
"""

from __future__ import annotations

import json
import logging
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .keystore import KeystoreRecord, SecureKeystore


logger = logging.getLogger(__name__)


DEFAULT_SECRETS_PATH = Path.home() / ".quantbt" / "secrets.yaml"


@dataclass
class SecretsLoadReport:
    path: str
    loaded: list[str] = field(default_factory=list)   # ["tushare", "llm_anthropic", "binance_testnet"]
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    file_existed: bool = False
    permission_secure: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "loaded": list(self.loaded),
            "skipped": list(self.skipped),
            "warnings": list(self.warnings),
            "file_existed": self.file_existed,
            "permission_secure": self.permission_secure,
        }


def _resolve_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env_path = os.environ.get("QUANTBT_SECRETS_PATH")
    return Path(env_path).expanduser() if env_path else DEFAULT_SECRETS_PATH


def _check_permissions(path: Path) -> tuple[bool, str | None]:
    if not path.exists():
        return False, None
    mode = stat.S_IMODE(path.stat().st_mode)
    # 期望 0600；任何 group / other 位置位都告警
    if mode & 0o077:
        return False, f"权限过宽 {oct(mode)}，建议 chmod 600 {path}"
    return True, None


def load_secrets(
    keystore: SecureKeystore,
    *,
    path: str | os.PathLike[str] | None = None,
    set_env: bool = True,
) -> SecretsLoadReport:
    """读取 secrets.yaml 并把每条非空字段写入 keystore + （可选）env。"""

    target = _resolve_path(path)
    report = SecretsLoadReport(path=str(target))
    if not target.exists():
        report.warnings.append(f"未找到 {target}（可选；不会阻塞启动）")
        return report
    report.file_existed = True
    ok, warn = _check_permissions(target)
    report.permission_secure = ok
    if warn:
        report.warnings.append(warn)
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        report.warnings.append(f"yaml 解析失败：{exc}")
        return report
    if not isinstance(raw, dict):
        report.warnings.append("yaml 根必须是 mapping，跳过")
        return report

    # Tushare
    tushare = (raw.get("tushare") or {}).get("token")
    if tushare:
        keystore.store(KeystoreRecord(name="tushare", api_key=tushare, api_secret=tushare, note="from secrets.yaml"))
        if set_env:
            os.environ["TUSHARE_TOKEN"] = str(tushare)
        report.loaded.append("tushare")
    else:
        report.skipped.append("tushare")

    # LLM —— 每个 provider 可同时配 api_key + base_url + model
    # 这三项一起塞进 keystore.note (json string)，make_llm_client 取出来用
    llm = raw.get("llm") or {}
    for provider in ("anthropic", "openai", "qwen", "custom"):
        info = llm.get(provider) or {}
        key = info.get("api_key")
        base_url = (info.get("base_url") or "").strip()
        model = (info.get("model") or "").strip()
        if not key:
            report.skipped.append(f"llm_{provider}")
            continue
        if provider == "custom" and not base_url:
            report.warnings.append("llm.custom 必须填 base_url，已跳过")
            report.skipped.append(f"llm_{provider}")
            continue
        note_payload = json.dumps({"base_url": base_url, "model": model}, ensure_ascii=False)
        keystore.store(KeystoreRecord(name=f"llm_{provider}", api_key=key, api_secret=key, note=note_payload))
        if set_env and provider != "custom":
            env_var = {
                "anthropic": "ANTHROPIC_API_KEY",
                "openai": "OPENAI_API_KEY",
                "qwen": "DASHSCOPE_API_KEY",
            }[provider]
            os.environ[env_var] = str(key)
            # base_url / model 也透传到 env（make_llm_client 读 keystore 为主）
            if base_url:
                os.environ[f"LLM_{provider.upper()}_BASE_URL"] = base_url
            if model:
                os.environ[f"LLM_{provider.upper()}_MODEL"] = model
        report.loaded.append(f"llm_{provider}")

    # Binance
    binance = raw.get("binance") or {}
    for network in ("testnet", "mainnet"):
        info = binance.get(network) or {}
        key = info.get("api_key")
        secret = info.get("api_secret")
        if not key or not secret:
            report.skipped.append(f"binance_{network}")
            continue
        keystore.store(KeystoreRecord(name=f"binance_{network}", api_key=key, api_secret=secret, note=network))
        report.loaded.append(f"binance_{network}")

    # Sentry
    sentry_dsn = (raw.get("sentry") or {}).get("dsn")
    if sentry_dsn:
        if set_env:
            os.environ["SENTRY_DSN"] = str(sentry_dsn)
        report.loaded.append("sentry_dsn")
    else:
        report.skipped.append("sentry_dsn")

    safe_summary = {"loaded": report.loaded, "skipped": report.skipped, "warnings": report.warnings}
    logger.info("secrets.yaml 加载完成：%s", safe_summary)
    return report


__all__ = ["DEFAULT_SECRETS_PATH", "SecretsLoadReport", "load_secrets"]
