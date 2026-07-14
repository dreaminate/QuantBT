"""Read non-trading secrets from ``~/.quantbt/secrets.yaml``.

设计：
- 文件路径默认 `~/.quantbt/secrets.yaml`，可被 `QUANTBT_SECRETS_PATH` 覆盖
- 文件必须是当前用户拥有、非 symlink、权限精确 0600，否则拒绝
- 任何 secret 永远不打印到日志；只回报字段名 + 状态
- 支持热加载：`POST /api/security/reload_secrets`
- yaml 缺失 / 任何字段空 → 不抛错，跳过对应 provider
- Binance key/secret 禁止进入 YAML，只能走认证 keystore API
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

from .keystore import KeystoreError, KeystoreRecord, SecureKeystore


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
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return False, "secrets file must be a regular non-symlink file"
    if info.st_uid != os.getuid():
        return False, "secrets file must be owned by the current user"
    mode = stat.S_IMODE(info.st_mode)
    if mode != 0o600:
        return False, f"secrets file must have mode 0600, found {oct(mode)}"
    return True, None


def load_secrets(
    keystore: SecureKeystore,
    *,
    path: str | os.PathLike[str] | None = None,
    set_env: bool = True,
) -> SecretsLoadReport:
    """Load non-trading YAML entries into the keystore/environment."""

    target = _resolve_path(path)
    report = SecretsLoadReport(path=str(target))
    if not target.exists():
        report.warnings.append(f"未找到 {target}（可选；不会阻塞启动）")
        return report
    report.file_existed = True
    ok, warn = _check_permissions(target)
    report.permission_secure = ok
    if warn:
        raise KeystoreError(warn)
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(target, flags)
        try:
            stream = os.fdopen(fd, "r", encoding="utf-8")
            fd = -1
            with stream:
                raw = yaml.safe_load(stream) or {}
        finally:
            if fd >= 0:
                os.close(fd)
    except yaml.YAMLError:
        report.warnings.append("yaml 解析失败")
        return report
    if not isinstance(raw, dict):
        report.warnings.append("yaml 根必须是 mapping，跳过")
        return report

    binance = raw.get("binance")
    if binance not in (None, {}):
        raise KeystoreError(
            "Binance credentials are forbidden in secrets.yaml; use the authenticated keystore API"
        )

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

    report.skipped.extend(("binance_testnet", "binance_mainnet"))

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
