# agent 红线 floor — 跨厂商 codex 复审判 NOT SOUND（fork2 收紧要求）2026-07-15

> deep-opus 设计 [[claude-code-agent-foundation-design-20260715]] 的红线 floor（fork2 提案）经 **codex 跨厂商复审判
> HONESTY/SAFETY NOT SOUND for fork-2 ratification**（3×P0 + 4×P1，逐条挂 file:line）。**未拿去请用户批**。本 session
> 第三次跨厂商复审守住安全/诚实边界（同厂商设计+我复审都漏）。floor 须按下方收紧到 v2 + 再跨厂商复审，才可请用户批 fork2。

## codex 确认的洞（fork2 批准前必闭）
- **P0-1 · spawn 契约漏了 agent 自带 bash 那条主道**：`--allowedTools mcp__quantbt__canvas_read` + `--strict-mcp-config` +
  无 `--dangerously` + `--permission-mode default` **仍**可能被 user/project/managed 权限规则放行 Bash → agent 读继承的凭据
  直连 venue，**完全绕过 L0-L2**。**修**：`--tools ""`(禁内置工具)+中和 user/project/local 定制源+`--safe-mode`+保 strict-mcp-config，
  且**必须 OS 沙箱**：专用 UID、空 HOME、不挂 repo/keychain/keystore、read-only projection FD、网络出口只允许 model 端点·封 venue 域名。
- **P0-2 · L0 无钥一旦 canvas_read import main.py 即塌**：`_graph_canvas_projection` 在 `main.py`，而 `main.py` 模块级 import
  执行层 client（place_order/KeyBroker/ORDER_BROKER，:287）→ `from app.main import ...` 把 keystore+broker 对象放进「无钥」进程 →
  L0 崩。**修**：抽纯 projector 进**不 import main/agent.__init__/research_os broad __init__** 的轻包；注入不可变只读视图（父进程产出
  owner-filtered snapshot 经 read-only FD 传）；import 测试断言禁 module 不在 sys.modules。
- **P0-3 · env/key 洗刷不够**：复用的 adapter `os.environ.copy()`(subscription_cli_llm.py:191/301) → denylist 漏
  QUANTBT_MASTER_KEY/云凭据/credential-helper/未来 venue var → Bash 开 keystore/keychain。**修**：env 从 `{}` 白名单构造
  （外 CLI + MCP spawn 两处）；用独立 OS 身份 + auth proxy，agent 永不拿到 host HOME/keychain/master key/secrets 路径/venue 凭据。
- **P1-4 · canvas_read 现非 owner-safe 也非严格只读**：镜的路由**无鉴权依赖**、收 optional `owner`（省略=通配 → 跨租户全读）；
  `read_only:true` 只是响应元数据。**修**：owner 只从鉴权+audience-bound capability 取（非 tool args/env），强制 owner=cap.subject，
  逐 node/edge owner 后校，拒省略/伪造 owner，真只读 parser（不建目录/不追日志）。
- **P1-5 · L1 是约定非封存注册表**：「hardcoded allowlist」未指定 sealing；注册面动态可变 → init/扩展码可注册善名 `canvas_export`
  达 venue client，`tools/list` 就广告它。**修**：无 public post-start 注册 API；不可变 `{canvas_read: handler}` dispatch；
  启动时 `tools/list != singleton` 即 fail；测晚注册/import 副作用注册/handler 替换。
- **P1-6 · L2 关键词查挡不住语义意图**：无 canonical schema/归一化/递归 → `{"network_id":1}`/`{"endpoint":"https://api.binance.com"}`/
  别名字段/嵌套/编码 blob 绕关键词。**修**：不把关键词当 floor；薄片只收**闭合 canvas_read schema**（拒未知/嵌套可执行字段/URL/代码/命令），
  安全绑到不可变 handler capability；NFKC 归一化+递归限深是次级防御。
- **P1-7 · 诚实限界仍越界 + GOAL/RULES 矛盾**：设计承认 L0-L2 只覆盖「经我方工具」，但 fork claim 问的是「所有真实 venue 动作是否不可达」——
  两个不同 claim。**且发现治理矛盾**：`RULES.project.md:11`「A股永不实盘」vs `GOAL.md:1787`「未来治理后可 live」——**须用户澄清**
  （我不碰 GOAL/RULES）。**修**：claim 收窄成「QuantBT MCP dispatch 只暴露一个 owner-scoped 读操作、零执行能力」——直到内置工具禁掉 +
  OS/网络沙箱证明独立 CLI 道够不到凭据/venue 为止。

## 收紧后的 fork2 要求（v2 须全闭再请用户批）
1. **OS/网络沙箱**（不是 CLI flag 就够）：专用 UID·空 HOME·不挂 keychain/keystore/repo·网络出口白名单只 model 端点·封 venue 域名。
2. **纯 projector 包**：canvas_read 不 import main.py（不把 order/key 拖进进程）；父产 owner-filtered 只读 snapshot。
3. **env 白名单 + OS 身份隔离**（非 denylist）。
4. **owner 从鉴权 capability**（非 tool args）。5. **封存单例注册表**（启动断言 tools/list==singleton）。6. **闭合 schema 替关键词 L2**。
7. **claim 收窄** + **A股 live 永久禁 vs 未来可 live 矛盾请用户拍**（GOAL/RULES 我不动）。

## 状态
设计 v1 floor **NOT SOUND·未批·零执行码**。v2 须闭上 3P0+4P1 + **再跨厂商复审** 才可请用户批 fork2。
**注意 P0-1 把范围抬高**：真封 agent 自带工具道要 **OS 级沙箱基建**——这本身可能是更大工程/待拍板（建多少沙箱）。
薄片可先更保守：在 OS 沙箱就绪前，连读-only 薄片都不落 spawn 执行码（fork2 未批 + floor 未 sound）。
