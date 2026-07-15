# OpenClaw 式 agent 层 — 对齐记录（待用户拍板 forks 1-5）2026-07-15

> **状态：待对齐 / 待拍板。不建 until 用户拍 forks 1-5。** 本篇是用户口述愿景 + 我的理解 + 开放岔路，
> 供跨 tick/会话不丢。用户原话见会话（「openclaw式的agent+我们的流程图…workspace…skill…本地 claude
> code/codex 作模型供应…还有一层对应配置…我们自己配置也要有…内置能操作无边画布…先和我对齐」）。

## 用户愿景（我的复述，待用户确认）
把一个 **OpenClaw 式 agent 层**装进 QuantBT：
- 真能干活的 agent：操作 **workspace**、跑 **skill**、能操作**无边画布**。
- 模型供应 = 用户**本地电脑上的 claude code / codex**（订阅）。因为后端是厂商 CLI，就有**两层配置**：
  厂商 CLI 自己的配置（`~/.claude` / `~/.codex`——模型/权限/MCP）在下，**我们自己的一层配置**在上。
- 大体 OpenClaw 那套，内置驱动我们的画布。

## K3 反转（这把先前 K3 掀翻）
先前 K3 =「订阅 CLI 拒绝**我们的** tool_schema」。OpenClaw 式**不塞工具给纯文本调用**——它**把 claude
code / codex 当完整 agent 跑**（它们**自带**读写文件/bash/MCP 工具，在 workspace 里干活），我们只做
编排 + 绑定 workspace↔画布/数据 + 叠 skill。所以 K3 不再是 blocker，是架构换法。这正是 GOAL §北极星.5
（画布表意 + 编译可执行 + agent 全程辅助）落成真 agent。

## 已有（别重造）
- **无边画布已存在**：`app/frontend/src/components/desk/canvas/{GraphCanvas,MiniMap,geometry}.tsx`
  （pan/zoom 研究图，factor/corr/research/paper/strategy/run 视图都用）。→ 无边画布现成底子。
- agent runtime + chat + RAG（§5）、QRO 研究图 + governed compiler（§1/§7/§8）、`sandbox.py`。
- 订阅 CLI adapter（`claude -p` / `codex exec`，S6 已 land）——但**现为一次性纯文本**，OpenClaw 式要**agentic 模式**。

## 新建（平台级 epic，非单切片）
workspace · agent skill（OpenClaw/Claude-Code 式，≠现有数据摄入 ingestion_skill）· agent↔画布绑定 ·
两层配置 · 把 claude code/codex 当 agent 编排跑（非一次性）。

## 待拍板岔路（我的推荐，等用户拍）
1. **通用 agent vs 量化专用**——推荐**量化专用**（北极星是量化），底层仍用通用 workspace/bash。
2. **安全命门（最关键）**——agent 带 workspace+bash+文件 = 巨大攻击面 vs 硬红线（不动真钱/A股永不实盘/
   无真实 venue/sandbox 逃逸已止血）。推荐**受限 sandbox workspace + 红线守卫永不可绕**（agent 再「想」
   动钱/真实 venue 也照拒）。⚠️ 这条属安全不变量，落地前必须钉死、不可让步。
3. **无边画布 = 现有 GraphCanvas vs 新自由白板**——推荐**扩现有 GraphCanvas**（已是范式载体），不另起第二块。
4. **本地优先 vs 也托管**——推荐**本地优先**（用户本地 claude code/codex），VPS-aware 以后。
5. **ToS**——坚持 **CLI 驱动**（经厂商 CLI 跑 agent，ToS 干净），**不**走 OpenClaw 指纹直连（先前特意避开的灰区）。

## 开源融合 license（见 [[model-switch-reference-impls-20260715]]）
- OpenClaw `github.com/openclaw/openclaw`：MIT（+THIRD_PARTY_NOTICES）→ ✅ 可融合。
- `openclaw-plugin-claude-code`：Apache-2.0 → ✅（留 NOTICE）。
- `simple10/openclaw-stack`：**BSL 1.1**（2030 前禁生产）→ ⛔ 只读 docs、代码不入库。

## 落地路径（拍板后）
用户拍 forks → duet 设计（deep-opus ‖ codex，各读全局+项目+dev 规则）→ **薄纵切先行**：
agent 操作画布 + 一个 skill + 受限 workspace + 接本地 claude code → 对抗验证 → 再铺全量。
**不在用户拍 fork 2（安全命门）前落任何 agent-workspace 执行代码。**
