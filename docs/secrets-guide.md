# QuantBT 密钥配置指南

QuantBT 把所有外部凭证统一走 `~/.quantbt/secrets.yaml`（在你 home 目录，不在仓库），
启动时自动加载到 `SecureKeystore` + 进程内环境变量。本文件**永远不会**进 git。

---

## 1. 一次性设置

```bash
mkdir -p ~/.quantbt
cp deploy/secrets.yaml.example ~/.quantbt/secrets.yaml
chmod 600 ~/.quantbt/secrets.yaml
```

然后编辑 `~/.quantbt/secrets.yaml`，按需填字段。**全部可选**，空字段自动
fallback 到 stub（LLM → DevLocalLLM；其它 → 报 warning 但不阻塞）。

---

## 2. 字段说明

| 段 | 字段 | 必填？ | 怎么拿 |
|---|---|---|---|
| `tushare.token` | A股数据源 | 跑 A股真数据 demo 时必填 | <https://tushare.pro> → 个人中心 → 接口 token（至少 2000 积分） |
| `llm.anthropic.api_key` | Claude | 任填一个 LLM 即可 | <https://console.anthropic.com> → API Keys |
| `llm.openai.api_key` | GPT-4 | 同上 | <https://platform.openai.com/api-keys> |
| `llm.qwen.api_key` | 通义千问 | 同上（国内可用） | <https://dashscope.console.aliyun.com> → API-KEY 管理 |
| `binance.testnet.api_key` / `api_secret` | 测试网 | 跑 Binance 全订单类型 e2e 必填 | <https://testnet.binance.vision> (spot) / <https://testnet.binancefuture.com> (futures) |
| `binance.mainnet.api_key` / `api_secret` | 主网真钱 | 仅在你准备真上线时填 | Binance 网页 API 管理 |
| `sentry.dsn` | 错误上报 | 可选 | <https://sentry.io> → Project → Settings → Client Keys (DSN) |

LLM provider 优先级：**anthropic > openai > qwen**。任填一个即可。

---

## 3. 致命安全约束（GOAL §12）

**Binance API key 必须满足以下全部**：
1. ✅ 启用读取 (Reading)
2. ✅ 启用现货 & 杠杆交易（如要做现货）
3. ✅ 启用合约（如要做 USDM Futures）
4. ❌ **必须关闭 提现 (Enable Withdrawals)** — QuantBT 启动时会调
   `GET /sapi/v1/account/apiRestrictions` 校验，有 withdraw 权限直接抛
   `BinanceWithdrawPermissionError` 拒绝运行
5. ❌ 关闭 万能划转 (Universal Transfer)
6. ✅ 强烈建议开启 **IP 白名单**

如果你不确定，请先只填 `testnet`，跑通后再决定要不要 `mainnet`。

---

## 4. 验证

```bash
# 启动后端
cd app/backend && python -m uvicorn app.main:app --port 8000 &

# 看 secrets 加载状态（不回显 key）
curl http://127.0.0.1:8000/api/security/secrets
# {"path": "/Users/you/.quantbt/secrets.yaml", "loaded": ["tushare","llm_anthropic","binance_testnet"], "skipped": [...], "warnings": [], "permission_secure": true}
```

填错或漏字段后：

```bash
# 编辑 secrets.yaml，然后热加载（无需重启）
curl -X POST http://127.0.0.1:8000/api/security/reload_secrets
```

---

## 5. 我的 key 安全吗？

| 风险 | 缓解 |
|---|---|
| 文件被其它用户读 | 启动时检查权限，非 0600 在 `report.warnings` 里出 |
| 密钥进 git | 文件在 `~/`，不在仓库；example 模板入仓但所有字段空 |
| 密钥进日志 | `secrets_loader` 只打印字段名 + 状态，绝不回显原值 |
| 密钥进 audit log | `ExecutionAuditLog` 只记录 clientOrderId / 时间 / 决策，不记 key |
| Binance 资产被转走 | 启动时强校验无 withdraw 权限；mainnet 切换二次确认 |
| 进程被攻破 | 默认走 `InMemoryKeystore`（进程结束即丢）；如需持久走 keyring/Fernet |

---

## 6. 上层 keystore 选择

`SecureKeystore.open(prefer=...)` 有三档：

- `keyring`（默认上线）：写入系统 keychain (macOS Keychain / Win Credential Manager / Linux libsecret)
- `fernet_file`：本地 AES 加密文件 + 用户主密码（PBKDF2 200k 迭代）
- `memory`：纯内存（开发期、CI、当前默认）

`secrets.yaml` 是引导入口 — 它本身**不会**被持久化到 keystore 之外的地方；启动时
读出 → 注入 → secrets.yaml 文件本身只在你 home 目录留一份明文（你自己保管）。
