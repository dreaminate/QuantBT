# LLM 认证快速上手（从零接上 OpenAI + Anthropic）

QuantBT 的 AI 能力（研究助手、dual-model 独立审查等）需要接上大模型。你有两种认证方式，
**任选其一，也可两家用不同方式**：

| 方式 | 成本 | 适合 | 要装啥 |
|---|---|---|---|
| **订阅**（推荐） | 无按量费，用你已有的 Claude Pro/Max + ChatGPT Plus/Pro 月费 | 已经订阅了两家的人 | 厂商官方 CLI（claude / codex）+ 登录一次 |
| **API key** | 按 token 计费 | 没订阅、或要跑量大 | 只需在配置文件填 key |

一条命令看你现在缺什么：

```bash
python scripts/llm_auth.py status
```

它会逐家告诉你「就绪 / 未就绪」和**确切的下一步**。

---

## 方式一：订阅账号（推荐，无按量费）

用你的订阅账号，经厂商官方 CLI 登录。CLI 自己处理 OAuth / token 刷新——**登录一次，长期用**。

### Anthropic（Claude Pro/Max）
```bash
# 1) 装 Claude Code CLI（若未装）
npm install -g @anthropic-ai/claude-code
# 2) 登录（弹浏览器登 claude.ai，登完把 code 贴回终端）
claude setup-token
```

### OpenAI（ChatGPT Plus/Pro）
```bash
# 1) 装 Codex CLI（若未装）
npm install -g @openai/codex
# 2) 登录（Sign in with ChatGPT，弹浏览器）
codex login
```

登完验活：
```bash
python scripts/llm_auth.py verify        # 真调一句，两家各返 pong 即通
```

**诚实边界**：订阅账号用于官方 app/CLI 之外的自动化，是否符合各厂商 ToS 由你自担
（个人本地使用）。凭据存在各 CLI 自己的安全存储里，QuantBT 从不读取/复制/记录你的 token。

---

## 方式二：API key（按量计费）

编辑 `~/.quantbt/secrets.yaml`：
```yaml
llm:
  anthropic:
    api_key: "sk-ant-..."      # console.anthropic.com 拿
    base_url: ""               # 留空=官方端点
    model: "claude-3-5-sonnet-20241022"
  openai:
    api_key: "sk-..."          # platform.openai.com 拿
    base_url: ""
    model: "gpt-4o"
```

---

## dual-model 跨厂商独立审查

两家都就绪后，dual-model gate 用 **builder=claude / verifier=gpt**（两个不同厂商）做独立审查——
比同厂商换 prompt 强得多。订阅方式下这是两个不同厂商的官方 CLI，**天然跨厂商真独立**。

```bash
python scripts/llm_auth.py status        # 确认两家就绪
# dual-model 真跑（订阅模式，无 key、无中继）见 scripts/dual_model_review.py
```

## 命令速查
```bash
python scripts/llm_auth.py status                 # 状态 + 缺口下一步
python scripts/llm_auth.py login anthropic        # 交互登录 Claude 订阅
python scripts/llm_auth.py login openai           # 交互登录 ChatGPT 订阅
python scripts/llm_auth.py verify                 # 真调验活（两家）
python scripts/llm_auth.py verify openai          # 只验一家
```

**token 过期了怎么办**：重跑对应的 `claude setup-token` / `codex login` 即可。
