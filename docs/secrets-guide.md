# QuantBT 密钥配置指南

QuantBT 只允许非交易凭证走 `~/.quantbt/secrets.yaml`（在你 home 目录，不在仓库），
启动时加载到 `SecureKeystore` 或进程环境。**Binance key/secret 禁止进入 YAML**，只能经登录后的
Binance 交易台或 `/api/security/keystore` 写入持久加密 keystore。本文件**永远不会**进 git。

---

## 1. 一次性设置

```bash
mkdir -p ~/.quantbt
cp deploy/secrets.yaml.example ~/.quantbt/secrets.yaml
chmod 600 ~/.quantbt/secrets.yaml
```

然后编辑 `~/.quantbt/secrets.yaml`，按需填写下表中的非交易字段。字段可以留空，但依赖该
凭证的能力不会伪装可用：真实 LLM 流在没有 Settings 管理的 provider、model、SecretRef 与
路由时明确报 `NoLLMConfigured`；`DevLocalLLM` 只允许由测试或显式演示路径构造，不能作为生产兜底。

---

## 2. 字段说明

| 段 | 字段 | 必填？ | 怎么拿 |
|---|---|---|---|
| `tushare.token` | A股数据源 | 跑 A股真数据 demo 时必填 | <https://tushare.pro> → 个人中心 → 接口 token（至少 2000 积分） |
| `llm.anthropic.api_key` | Claude | 任填一个 LLM 即可 | <https://console.anthropic.com> → API Keys |
| `llm.openai.api_key` | GPT-4 | 同上 | <https://platform.openai.com/api-keys> |
| `llm.qwen.api_key` | 通义千问 | 同上（国内可用） | <https://dashscope.console.aliyun.com> → API-KEY 管理 |
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

testnet 与 mainnet 凭证都在登录后通过 UI 或 keystore API 录入；不要把任一网络的凭证写进 YAML。

---

## 4. 验证

```bash
# 启动后端
cd app/backend && python -m uvicorn app.main:app --port 8000 &

# 看 secrets 加载状态（不回显 key）
curl http://127.0.0.1:8000/api/security/secrets
# {"path": "/Users/you/.quantbt/secrets.yaml", "loaded": ["tushare","llm_anthropic"], "skipped": [...], "warnings": [], "permission_secure": true}
```

填错或漏字段后：

```bash
# 编辑非交易字段后热加载（无需重启）；此接口不会加载 Binance 凭证
curl -X POST http://127.0.0.1:8000/api/security/reload_secrets
```

---

## 5. 我的 key 安全吗？

| 风险 | 缓解 |
|---|---|
| 文件被其它用户读 | 启动时要求当前用户拥有的普通文件且权限精确为 0600；不满足即拒绝加载 |
| 密钥进 git | 文件在 `~/`，不在仓库；example 模板入仓但所有字段空 |
| 密钥进日志 | `secrets_loader` 只打印字段名 + 状态，绝不回显原值 |
| 密钥进 audit log | `ExecutionAuditLog` 只记录 clientOrderId / 时间 / 决策，不记 key |
| Binance 资产被转走 | 启动时强校验无 withdraw 权限；mainnet 切换二次确认 |
| 进程被攻破 | 交易凭证使用显式持久 backend；生产不允许自动降级到内存 |

---

## 6. 上层 keystore 选择

运行时通过 `QUANTBT_KEYSTORE_BACKEND` 明确选择三档之一：

- `keyring`：系统 keychain（macOS Keychain / Win Credential Manager / Linux libsecret）；不可用即启动失败
- `fernet_file`：`DATA_ROOT/security/trading_keystore.enc` 加密文件；必须提供 `QUANTBT_MASTER_KEY`
- `memory`：只允许显式 `QUANTBT_RUNTIME_MODE=test|development`，生产与真钱凭证写入均拒绝

未设置 backend 时，有 `QUANTBT_MASTER_KEY` 才选择 `fernet_file`，否则要求可用的系统 keyring；
两者都不会静默回退。`secrets.yaml` 只承载非交易引导配置，出现任何非空或残缺的 `binance` 段都会拒绝加载。

## 7. Paper 晋级验证人信任根

Paper 晋级默认关闭。机器运维必须在启动进程前显式配置允许承担验证责任的稳定 user ID：

```bash
export QUANTBT_PAPER_VERIFIER_USER_IDS="user-id-a,user-id-b"
```

这个值不是请求参数，也不能由普通账号通过 API 扩充。只有 run owner 能开晋级门；owner 给另一个认证主体签发
exact-gate reviewer grant 后，该主体还必须命中这份机器 allowlist，才能提交绑定当前 gate nonce、run、五门快照和
typed verdict 的审批。allowlist 为空、身份不匹配、grant 过期、背书错绑或数据源漂移都会保持 `pending`。

这是一条运维指定的责任边界，不等于组织独立，也不证明模型调用真的来自两个外部 provider。真正的双 provider
Review 仍须 Settings 管理的两条不同 provider/model 调用记录和完整 replay 证据；未配置时必须继续报告 GAP。
