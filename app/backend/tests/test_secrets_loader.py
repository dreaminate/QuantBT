from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.security import InMemoryKeystore, KeystoreError, SecureKeystore, load_secrets


SAMPLE_YAML = """
tushare:
  token: my-tushare-token
llm:
  anthropic:
    api_key: sk-ant-mock
  openai:
    api_key: ""
sentry:
  dsn: https://abc@sentry.example/1
"""


def _ks() -> SecureKeystore:
    return SecureKeystore(InMemoryKeystore())


def test_load_secrets_writes_keystore_and_env(tmp_path: Path, monkeypatch) -> None:
    for var in ("TUSHARE_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY", "SENTRY_DSN"):
        monkeypatch.delenv(var, raising=False)
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text(SAMPLE_YAML, encoding="utf-8")
    secrets.chmod(0o600)
    ks = _ks()
    report = load_secrets(ks, path=secrets)
    assert report.file_existed
    assert report.permission_secure
    assert set(report.loaded) >= {"tushare", "llm_anthropic", "sentry_dsn"}
    assert set(report.skipped) >= {"llm_openai", "llm_qwen", "binance_mainnet"}
    # keystore
    assert ks.fetch("tushare").api_key == "my-tushare-token"
    assert ks.fetch("llm_anthropic").api_key == "sk-ant-mock"
    # env
    assert os.environ["TUSHARE_TOKEN"] == "my-tushare-token"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-mock"
    assert os.environ["SENTRY_DSN"] == "https://abc@sentry.example/1"


def test_load_secrets_missing_file_returns_warning(tmp_path: Path) -> None:
    ks = _ks()
    report = load_secrets(ks, path=tmp_path / "absent.yaml")
    assert not report.file_existed
    assert any("未找到" in w for w in report.warnings)
    assert report.loaded == []


def test_load_secrets_loose_permission_fails_closed(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text(SAMPLE_YAML, encoding="utf-8")
    secrets.chmod(0o644)
    with pytest.raises(KeystoreError, match="mode 0600"):
        load_secrets(_ks(), path=secrets)


@pytest.mark.parametrize(
    "binance_yaml",
    [
        "binance:\n  testnet:\n    api_key: key\n    api_secret: secret\n",
        "binance:\n  mainnet:\n    api_key: key-only\n",
        "binance: not-a-mapping\n",
    ],
)
def test_load_secrets_rejects_any_binance_material_before_partial_writes(
    tmp_path: Path,
    monkeypatch,
    binance_yaml: str,
) -> None:
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("tushare:\n  token: must-not-load\n" + binance_yaml, encoding="utf-8")
    secrets.chmod(0o600)
    keystore = _ks()

    with pytest.raises(KeystoreError, match="forbidden"):
        load_secrets(keystore, path=secrets)

    assert keystore.list_names() == []
    assert "TUSHARE_TOKEN" not in os.environ


def test_load_secrets_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "actual.yaml"
    target.write_text("tushare:\n  token: t1\n", encoding="utf-8")
    target.chmod(0o600)
    link = tmp_path / "secrets.yaml"
    link.symlink_to(target)
    with pytest.raises(KeystoreError, match="non-symlink"):
        load_secrets(_ks(), path=link)


def test_load_secrets_invalid_yaml_does_not_raise(tmp_path: Path) -> None:
    secrets = tmp_path / "secrets.yaml"
    secrets.write_text("not: [valid: yaml:::", encoding="utf-8")
    secrets.chmod(0o600)
    report = load_secrets(_ks(), path=secrets)
    assert any("yaml" in w.lower() for w in report.warnings)


def test_load_secrets_explicit_env_var_path(tmp_path: Path, monkeypatch) -> None:
    secrets = tmp_path / "elsewhere.yaml"
    secrets.write_text("tushare:\n  token: t1\n", encoding="utf-8")
    secrets.chmod(0o600)
    monkeypatch.setenv("QUANTBT_SECRETS_PATH", str(secrets))
    report = load_secrets(_ks())
    assert "tushare" in report.loaded


def test_main_app_imports_after_loader_added() -> None:
    # 烟雾测试：main.py 启动时 load_secrets 不能因 ~/.quantbt 不存在而崩
    from app.main import app, _SECRETS_REPORT

    assert app is not None
    assert "loaded" in _SECRETS_REPORT.to_dict()
