# QuantBT v0.9 用户 Quickstart（5 分钟跑通 + 30 分钟看懂）

> 这份文档假设你是 P0 用户："会 Python 的宽客，从聚宽/BigQuant 毕业，想用本地工具跑研究"。
> 如果你想直接 Binance live，先把这份文档第 1-4 节读完，再去 SafeKey wizard。

## 0. 整体画面

从注册到看懂第一个回测，应该 < 15 分钟。

v0.9 提供 4 个核心闭环：

1. `/runs` 看已有 run → `/runs/<id>` 看证据状态 + 字段解释
2. `/ide` 写自己的策略 → 沙箱跑 → promote 进正式 Run
3. `/chat` 诊断台读指标、指出问题，并引导一次最小实验
4. `/trading` SafeKey → testnet matrix → live ladder（实盘前）

## 1. 5 分钟启动

```bash
git checkout fullstack
git pull

# 后端（建议 --reload）
python -m uvicorn --app-dir app/backend app.main:app --port 8000 --reload

# 前端（另开 terminal）
cd app/frontend && npm run dev

# 访问 http://localhost:5173
```

## 2. 注册 + 跑第一个 demo

1. 点右上角"登录" → 切到"注册" → 任意 username + 8 位以上 password
2. Home 顶 5 步 onboarding banner（不喜欢可关）
3. 顶 nav → Workshop · **策略模板** → 选 "BTC 20 日动量" → "↪ Fork 到我的 IDE"
4. 自动跳 `/ide`，左侧能看到刚 fork 的策略
5. 点 "▶ 运行" → 沙箱 1-3 秒跑完
6. 右侧"运行输出"看 status OK + **风险预览 chip**（证据一致/存疑/高风险/信息不足）
7. 点"⤴ 提升为正式 Run" → 自动跳 `/runs/<id>` 三联图

## 3. 看懂证据状态（核心教学）

`/runs/<id>` 顶部"收益概述"旁的彩色 chip 4 档：

- 🟢 证据一致（PBO/DSR/MaxDD 全过）
- 🟡 存疑（中等风险）
- 🔴 高风险（PBO>0.6 / DSR<0.2 / MaxDD>25%）
- ⚪ 信息不足（缺 PBO/DSR）

🔴/🟡 时下方会有 **诊断入口** 横幅，点了跳 `/chat?run=<id>&q=<问题>` 自动开对话 + 预填问题。

## 4. 字段不懂就点 ⓘ（渐进披露）

收益概述的每个指标旁有 **ⓘ** 按钮：

- **L1**（5-15 字）：一句话定义
- **L2**（popover）：公式 + 算例
- **L3**（"查看 L3/L4 ↓"）：业界阈值 + 常见误区（**防破产层**）
- **L4**：延伸阅读 + 相关词条
- **📖 打开专页 →**：跳 `/glossary/<slug>` 全文页

baseline 30 条已索引，3 条样例完整（sharpe_ratio / pbo / deflated_sharpe），其余 27 条等 GPT Pro。

## 5. 诊断台

`/chat` 三栏：左历史 thread / 中消息流 / 底输入框。

- **market_mode**：A股研究 / 加密 paper / Binance testnet / Binance live
- 每个新 thread 可绑 `active_run_id`，诊断台会把指标带入上下文
- **拒答红线**：A股实盘下单 / 推荐买卖点 / 绕 SafeKey / 保证收益
- **回答 4 段**：证据状态（证据一致/存疑/高风险/信息不足）+ 证据 + 下一步实验 + Binance 安全状态

## 6. 用自己的数据

**A股**：填 `~/.quantbt/secrets.yaml`：

```yaml
tushare:
  token: "你的 2000 积分 token"
```

**加密**：内置 BTC/ETH/A股 ETF sample 立刻可用，不需要外部 token。

**自定义 connector**：YAML 配置（参 `docs/data-connector-guide.md`），无需写代码。

## 7. Binance 实盘安全阶梯（Live Pro 才用）

**绝对不要直接 mainnet**。流程：

1. **SafeKey wizard**：必须 `enableWithdrawals/internalTransfer/universalTransfer=false`，推荐 `ipRestrict=true`
2. **Testnet Order Matrix** 12 cell（6 order_type × 2 side），每格 4 子指标
3. **Live Ladder** 5 级，必须逐级晋级（level_0 paper → ... → level_5 自定义）
4. **Kill switch** 触发 → 自动降级 + 阻断 24h 再晋级

## 8. 私域带单（Beta）

`/copy-trade`：

- Master 上限 **5** / Follower 上限 **50**
- Master 发 signal → SignalRelayer → 每个 follower 走**自己 keystore + 自己 Binance venue**
- Master 永远拿不到 follower 凭证
- **Dispatch idempotency**：signal_id + follower_id UNIQUE 防重复
- **Follower override**：master 10x leverage → follower cap 2x → 强制截到 2x

## 9. 一次 run 看什么（顺序）

| Step | 看什么 | 在哪 |
|---|---|---|
| 1 | trust_level chip | RunDetail 顶部 |
| 2 | Sharpe + ⓘ | 收益概述 metric block |
| 3 | PBO/DSR（如有）| 风险卡详情 |
| 4 | 三联图（equity / drawdown / 收益对比）| RunDetail 主区 |
| 5 | 归因 / 持仓 / 交易 | RunDetail 各 tab |
| 6 | 诊断建议 | RunDetail 顶部 banner |
| 7 | 改一个变量 | `/ide` |
| 8 | Compare | `/compare` 2-3 个 run trust_level 对比 |

## 10. 完整命令

```bash
python -m pytest app/backend/tests -q                          # 508+ passed
python scripts/validate_glossary.py docs/glossary --min-count 3 # PASS
python scripts/query_first_run_time.py --db data/community.db
cd app/frontend && npx tsc --noEmit && npx vite build
python scripts/release_check.py --tag v0.9.4
```

## 11. 重要文件

| 路径 | 是什么 |
|---|---|
| `QuantBT-GOAL.md` | 总目标 + M1-M21 模块 + §13 上线 checklist |
| `docs/releases/v0.9.0.md` | v0.9.0 完整 release notes (24h sprint 11 tag) |
| `docs/glossary/_PROMPT_FOR_GPT_PRO.md` | 给 GPT Pro 出 30 条词条的批量 prompt |
| `docs/strategy/_NEW_PRO_HANDOFF.md` | 给新 GPT Pro 的完整 handoff (briefing + V1 + patch1) |
| `docs/roadmap/open_items_v085_v086.md` | v0.8.5/v0.8.6 不合并项 + v0.9.x 路线 |

## 12. 路线图位置

参 `QuantBT-GOAL.md` §7：

- P1-P3.5: ✅ 数据 / 因子 / 模型 / 加密实盘准备 / 可上线门槛
- P4: ✅ 实验 / 调度 / 监控
- P5: ✅ 研究执行台
- P6: 多策略组合管理（待）
- **P7-P11: ✅ v0.8.0-v0.9.0 全落地**
- P12: 实盘 e2e + 第一批用户（等 testnet key + 内测）

## 13. 出问题

- **后端启不来**：单跑 `pytest app/backend/tests/test_health.py`
- **前端 build 失败**：`rm -rf node_modules && npm install && npm run build`
- **沙箱报 PermissionError**：正常，安全设计
- **SafeKey 反复失败**：Binance API 管理 → 编辑限制 → 关 withdraw 所有相关权限
- **glossary 词条 404**：27 条还没出，正常；3 条 baseline 必定可用

## 14. 待 user 做的事

1. ⏳ 给 testnet API key（明天）→ 跑 task 36 Binance testnet 全订单 e2e
2. ⏳ 用 GPT Pro 出 27 条剩余 glossary 词条
3. ⏳ Mainnet 100USDT 一周（user 自决）
4. ⏳ 招 5 个种子内测用户（看 funnel SQL 数据）
