# 用订阅额度跑 QuantBT（Hermes 本地 OAuth 代理）

如果你已经有 **Claude Code** 或 **Codex** 这类带订阅额度的工具，可以不另外买 API key——
运行一个**本地 OAuth 代理**（如 Hermes），把订阅额度暴露成一个 OpenAI 兼容端点，
再让 QuantBT 指向它。整条链路里：

- OAuth 登录 + token 刷新**全程在代理侧**，QuantBT 既不实现 OAuth、也不接触你的订阅 token；
- QuantBT 只把它当成一个普通的 **custom（OpenAI 兼容）provider**——和接 Ollama、本地 vLLM 一个路径，复用同一个 `POST /api/llm/configure` 端点，没有任何特例代码。

> 说明：本文是接通工具的操作指南，不是投资建议。能不能用某订阅额度跑第三方应用，请自己核对该订阅的服务条款；额度、限流、可用模型都以代理与上游为准。

---

## 1. 运行一个本地 OAuth 代理（Hermes 等）

任选一个把订阅额度转成 OpenAI 兼容 API 的本地代理。以一个监听在 `8787` 端口的代理为例，
它启动后应能提供形如下面的端点：

```
http://localhost:8787/v1/chat/completions
```

- 按该代理自己的文档完成一次性 OAuth 登录（浏览器授权 → 代理保存 refresh token）。
- 记下两件事：**端口**（这里是 `8787`）和**模型别名**（代理把订阅模型映射成的名字，
  常见如 `claude-sonnet-4.5`；以代理输出为准）。
- 自检：代理在线时，`curl http://localhost:8787/v1/models` 应能列出可用模型。

代理不在线时，QuantBT 的真实流对话会**如实报连接失败**（不会假装成功）——
这是预期行为，把代理拉起来再试即可。

---

## 2. 让 QuantBT 指向代理

打开 **设置 · LLM 配置**（顶栏 `◇ LLM`，或访问 `/settings/llm`）：

1. 点 **「套用 Hermes 预设」**——会自动把 provider 切成 `custom` 并预填
   `http://localhost:8787/v1`。
2. 按你的实际情况改：
   - **Base URL**：代理的 `/v1` 地址（端口对上）。
   - **Model**：代理给出的模型别名。
   - **API key**：custom 下后端不强制校验，留默认占位（如 `hermes`）即可——
     真正的鉴权在代理侧，不在这把 key。
3. 点 **保存配置**。成功后页面只声明「配置已写入 keystore」——
   这**不等于已连通真模型**。

### 等价的命令行 / secrets 写法

预设走的就是标准 custom provider，等价于直接调端点：

```bash
curl -X POST http://127.0.0.1:8000/api/llm/configure \
  -H 'content-type: application/json' \
  -d '{"provider":"custom","api_key":"hermes",
       "base_url":"http://localhost:8787/v1","model":"claude-sonnet-4.5"}'
```

或写进 `~/.quantbt/secrets.yaml` 的 `llm.custom`（见 [secrets-guide.md](secrets-guide.md)）。

---

## 3. 验证真连通（不靠绿灯靠实测）

「配置已写入」只代表端点存进了 keystore。要确认真能用：

1. 去 **设置 · 安全设置** 底部的 **「LLM Providers · 连接测试」**，对 `custom` 点 **测试连接**——
   它会真发一条 ping，把回包预览如实贴出来（失败也照实显示报错）。
2. 回 **研究执行台**，确认右上是 **● LIVE · 真实流**（默认就是实时流），
   发一句「组装一个 A股周频多因子策略」。走真流时不会挂 `MOCK` 角标；
   想看脚本演示再点 **▶ 看演示（mock）**，演示态会全程挂 `MOCK` 角标，两者不会混淆。

---

## 4. 常见问题

| 现象 | 多半原因 | 处理 |
|---|---|---|
| 真实流对话报「流启动失败 / 连接失败」 | 代理没起 / 端口或 `/v1` 路径不对 | 先 `curl .../v1/models` 自检，再核对 Base URL |
| 测试连接报 401 / 鉴权失败 | 代理侧 OAuth 过期或没登录 | 在代理侧重新登录授权 |
| 回的内容明显是占位/兜底 | 没配任何 provider，落到了 DevLocalLLM | 确认 `/settings/llm` 状态里 `custom` 显示「已配置」 |
| 模型名报不存在 | Model 别名和代理给的不一致 | 用 `/v1/models` 列出的名字 |

代理本身的安装、OAuth、限流以其官方文档为准；QuantBT 这侧只负责把它当 OpenAI 兼容端点接进来。
