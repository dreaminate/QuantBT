# v0.8.5 / v0.8.6 不合并项清单（v0.8.4 收尾时记录）

> **目的**：明确 v0.8.4 不做什么，避免 Claude / 用户在 Day 6 之后 scope creep 把 v0.8.5/v0.8.6 的工作偷塞进 v0.8.4。

## v0.8.4 已落地（review 检查清单）

| 项 | 状态 |
|---|---|
| 30 条 glossary baseline slug 索引 | ✅ `docs/glossary/_index.yaml` |
| Pydantic schema + 校验脚本 | ✅ `scripts/validate_glossary.py` |
| 3 条参考词条 (sharpe_ratio / pbo / deflated_sharpe) | ✅ |
| `/api/glossary` `/api/glossary/{term}` `/api/glossary_meta` | ✅ |
| 渐进披露 `?level=l1\|l2\|l3\|l4` | ✅ |
| RunDetail metrics ⓘ 按钮 + L1/L2 popover | ✅ |
| RunDetail 顶部 risk_summary chip | ✅ |
| 7 条风险规则纯函数 + 23 测试 | ✅ |
| 4 个事件埋点 (run_detail_viewed / risk_metric_expanded / glossary_term_viewed / risk_summary_shown) | ✅ |
| 事件 sqlite 表 + SQL smoke 脚本 | ✅ |
| Mode 2 system prompt 落库 + contract test | ✅ |
| tushare flake 还债 | ✅ |
| 27 条 baseline glossary 词条 .md 待 GPT Pro 补 | ⏳ 用户 |

## v0.8.5 范围（v0.8.4 不做）

| # | 项 | 说明 |
|---:|---|---|
| 1 | `/glossary/<slug>` 独立页 | 全文 markdown + KaTeX + related 侧栏 |
| 2 | 指标在用户历史 runs 的分布直方图 | "你的 SR 落在第 X 分位" |
| 3 | 新词条：win_rate / profit_loss_ratio | 暂时不在 baseline 30 条 |
| 4 | popover 内"打开专页"二级入口 | 仅 v0.8.5 加 |
| 5 | glossary 词条版本化 / changelog | 词条更新历史 |

## v0.8.6 范围（v0.8.4 不做）

| # | 项 | 说明 |
|---:|---|---|
| 1 | `conversations` sqlite 表 | thread_id / user_id / messages JSON |
| 2 | `POST /api/chat/start` `POST /api/chat/{id}/message` (SSE) | 流式多轮 |
| 3 | RAG: SQLite FTS5 + BM25 + 可选 embedding | hybrid score 0.55/0.35/0.10 |
| 4 | IDE 右侧 AI Panel mode toggle (执行/深度) | UI 入口 |
| 5 | RunOutput 顶部主动建议 hook | "你这次 SR 1.2 但 PBO 0.68..." |
| 6 | Token 缓存 (run_id + question_type + glossary_version → 24h) | 控成本 |
| 7 | 接入剩 6 个事件 (user_registered / run_started / run_completed / strategy_parameter_modified / safekey_check_completed / testnet_order_e2e_completed / kill_switch_triggered) | funnel 完整 |
| 8 | 5 步对话状态机 (ENTER_THREAD / RETRIEVE_CONTEXT / SOCRATIC_DECISION / ANSWER_OR_ACTION / FOLLOW_UP_UPDATE) | 编排逻辑 |
| 9 | conversations 侧边栏 (历史回顾) | 用户 UX |
| 10 | "我不确定 + 列出缺什么字段" 拒答路径 | 防 hallucination 兜底 |

## 关键不合并的"伪相邻"功能

下面这些看起来像 v0.8.4 范围但**显式排除**：

- **❌ 沙箱攻击向量修复** (G.a #13)：v0.9 云端 beta 前必须容器化；现在 sandbox 用 banner 提示即可
- **❌ PBO CSCV 组合数审计** (G.a #1)：单独 hotfix 提案，不绑定 v0.8.4
- **❌ DSR 偏度/峰度审计** (G.a #2)：同上
- **❌ Purged k-fold + Triple Barrier 时间跨度绑定** (G.a #3)：v0.8.5 / v0.9 工作
- **❌ HRP 协方差奇异性测试** (G.a #15)：v0.8.5 工作
- **❌ Agent tool_schema prompt injection 防御** (G.a #17)：v0.8.6 接 chat 时一起做
- **❌ promote_ide_run schema → RunDetail 对齐** (G.a #14)：v0.8.4 前两周 v0.8.3 已修，v0.8.4 不重复

## 推进顺序约束

1. v0.8.4 commit tag 必须先打（用户验收 + final regression）
2. GPT Pro 补完 27 条 glossary → 第 28-30 条到位 → strict_related 校验通过
3. 然后才开 v0.8.5（不能跳号）
4. v0.8.5 中验证字段 ⓘ 深入层 + 用户反馈
5. 最后 v0.8.6 才接 SSE 多轮 chat（最贵的工作）
