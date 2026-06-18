# T-024 · 可证伪假设卡接进 Run 生命周期（P2 不挡探索）

- **状态**：todo（卡已过目，待 2 岔路点头后开工）
- **review_status**：0
- **来源**：spine-designs 04（§4 接线 / §5 对抗）+ P2/R1 + R5/R7 措辞
- **优先级**：P1（STATE 标 04「[集成必补]：Run 连接」——组件已建 T-017，但未接进 Run→promote 流）
- **依赖**：T-017（假设卡组件）、T-013（一本账 honest-N）、T-020（验证官，freeze 时消费裁决）
- **波次**：簇A 脊柱收尾（收口第一波）

## Scope（单一能力单元）

把已建的假设卡组件（`hypothesis/{card,gate,store,falsifiability,lineage_hook}`，T-017）接进 Run→promote 流：
- **exploratory run 一律放行**（标 `exploratory`，假设卡可留空）——**P2 铁律,不挡探索**。
- **晋级 confirmatory 可下注结论**才强制：冻结假设卡（三必填 `FalsifiableTriplet`）+ `can_touch_final_oos` 闸门（最终 OOS 一次性消费、探索污染拒绝）。
- 现状缺口：(1) `Run` dataclass 无 `hypothesis_card_id`/`layer` 字段；(2) `main.py` 未实例化 `HYPOTHESIS_STORE`；(3) 无 `/api/hypothesis_cards/*` 端点；(4) promote 端点无假设卡闸门接入。

## 侦察接线点（实现时复核行号）

| 文件 | 位置 | 接什么线（向后兼容、扩展不替换） |
|---|---|---|
| `experiments/store.py` | `class Run`(~L47) | 加两个可空字段 `hypothesis_card_id: str\|None=None`、`layer: Literal['exploratory','secondary','confirmatory']\|None=None`；store 层不强制校验（不破坏既有 Run） |
| `main.py` | import 块(~L54) | `from .hypothesis import HypothesisCardStore, can_touch_final_oos` |
| `main.py` | 实例化块(~L93) | `HYPOTHESIS_STORE = HypothesisCardStore(DATA_ROOT/'experiments')` |
| `main.py` | promote 端点(~L2365) | confirmatory 且 `execution_mode∈{paper,live_crypto}` → 先调 `can_touch_final_oos(card, honest_n_now=LEDGER.honest_n(...))`，block 则 `HTTPException(409,...)`；exploratory 跳过（P2 不挡） |
| `main.py` | 新端点块(~L411) | 5 个假设卡端点：`POST /api/hypothesis_cards`、`/{id}/freeze`、`/{id}/promote`、`GET /{id}/gate`、`POST /{id}/deviation`（不动既有 /api/models、/api/runs） |
| `ide/promote.py` | `promote_ide_run`(~L53) | 照 T-015/T-019 opt-in 范式（传账本才跑）增可选 `hypothesis_card_id`/`layer` 透传；或迟滞到真 backtest 执行体系一并加 |

## 对抗测试设计（种已知 bug，门必抓）

1. **不可证伪伪装**：套套逻辑/无前置/无阈值条件（含字数达标的套套逻辑）→ `assess_falsifiability` 判 low/medium、`FreezeRejected` + `needs_human_review`；**绝不退化为字数门**。反向：真机制判 high。
2. **空机制 BLOCK + 探索反向**：confirmatory 三必填任一空白 → freeze 拒；exploratory 留空 → 放行（P2）。
3. **OOS 探索污染 + 一次性消费**：promote 用已被源卡触碰的数据集 → 拒；`consumed=True` → `can_touch_final_oos` block。
4. **探索层越权**：`layer=exploratory` 调 `can_touch_final_oos` → block（P2 硬边界）。
5. **honest-N 不可改小 + 实读**：改冻结卡 N → `CardFrozenError`；`freeze()` 签名**无 N 入参**（调用方无谎报口），从 LEDGER 实读。
6. **content_hash 篡改对账**：改落盘受哈希字段 → `CardTamperError`；改 exclude 字段（deviations/review/status）→ hash 不变；NFC/键序归一不变量。
7. **冻结只读 + fork**：改 frozen 核心字段 → `CardFrozenError`；要改须 `fork_card` 开新 draft，原行 append-only 不覆写。
8. **晋级谱系**：exploratory→confirmatory→freeze，`parent_card_id` 指回源、两卡共存、`lineage_hook.emit` 被调。
9. **冻结幂等 + 并发**：同 `idempotency_key` 重复 freeze → 返存量不重跑验证官；并发双写 `_lock` 序列化只一条。
10. **措辞守门（R5/R7）**：`GateDecision` 文案禁 `可信/安全/保证/已验证/trustworthy/proven/...`；`needs_human_review` 永 True；用 `consistency_check` 不用 `independent/组织独立`。
- 标 **[集成必补]**：T-023 内核 / 验证官 / regime 真落地后补端到端（当前 mock 下绿,测试报告须分 mock 组 vs 集成组 [PENDING],**绝不渲染成"已验证安全"**）。

## 复用模块

`experiments/store.py:_JsonlStore`（append-only+Lock）· `lineage/ids.py:content_hash` · `strategy_goal.py:FalsifiableTriplet`（三必填，`strategy_goal.py:104-112`）· `lineage/ledger.py:Ledger`（honest-N 实读）· `verification/store.py:VerdictStore`（验证官裁决）。

## 红线（RULES §5 / DECISIONS）

- **P2 铁律**：exploratory run 必放行,绝不被假设卡挡——违反=探索自由破产、收不到反馈。
- **冻结只读硬拒**：frozen 核心字段改一字即 `CardFrozenError`（非 warning）。
- **honest-N 实读权威**：`freeze()` 从 LEDGER 直读 N，永不收调用方传入；`inspect.signature` 无 `honest_n` 参。
- **措辞绝对化清零**（R5/T12）：中英双语黑名单 grep → 0 hit。
- **谱系漏发**：状态跃迁必调 `lineage_hook.emit`，hook 未就绪走 pending 不静默吞。

## Open Questions（需关闭——含 1 个需用户拍板的新岔路）

- **[需拍板·新岔路]** **exploratory↔confirmatory 的判定信号从哪来?** DECISIONS 未覆盖。候选：(a) 用户显式点「晋级 confirmatory」；(b) 由 `execution_mode=paper/live` 自动判；(c) 在 `StrategyGoal` 里声明 `layer`。建议 **(a)+(c) 组合**（用户在 StrategyGoal 向导显式声明/晋级，execution_mode 仅作辅助校验），但需你定。
- 「晋级用一次性 OOS」与「运营滚动验证集」是否同一切片？建议**分两套**、文档钉死各自消费口径（避免把元科学范式生搬运营 walk-forward）。
- 可证伪启发式误判：`confidence=low` 放行是否强制「人工确认+验证官二次挑战」？建议是（T1/T5b 钉成门必抓）。
- 卡级 garden-of-forking-paths 计数：每冻结一张 confirmatory 卡向账本写 `kind=card_freeze`；该条目独立计数还是混入因子聚类？建议独立计数、并列展示。
- 前端 Card 管理页（独立 vs 内嵌 StrategyGoal）——**不碰冻结的 RunDetailPage**；归 E 簇信任层,本卡只做后端契约+端点。

## 验收一句话

空机制当 confirmatory→拒；探索 run 留空卡→放行；冻结卡改字段→拒；晋级后 OOS 二次消费→拒；措辞黑名单 0 hit；不破坏 1001 基线。
