# T-017 · 可证伪假设卡（P2 不挡探索）

- **状态**：✅ done（2026-06-18）
- **review_status**：1（用户 2026-06-19 确认） · **来源**：spine 04 + R1/R5/R7/P2 + 00 §1.2-D/H · **依赖**：T-013（一本账）
- **优先级**：P1

## 做了什么

`strategy_goal.py` 加 `EconomicMechanism`/`FalsifiableTriplet`（可空 `falsifiable` 字段，P2 探索不挡）；
新建 `app/hypothesis/`：
- `falsifiability.py`：**真语义检测非字数门**——套套逻辑(自指标 CN+EN) / 无前置 X / 无阈值(CN+EN) / 噪声。
- `card.py`：`HypothesisCard` + content_hash（复用 ids，NFC/键序天然不变量）+ **冻结只读**（粘性
  `_frozen_core`，deviated/retired 仍锁）+ `CardTamperError`。
- `store.py`：freeze（强制 confirmatory + 三必填过启发式 + **honest-N 实读 T-013 一本账**写 `card_freeze`
  条目 + 绑 frozen_oos + OOS 污染再校验 + 幂等 + 并发锁）/ fork / promote（探索污染 BLOCK）/ deviation / retire；
  **读路径 content_hash 对账**抓篡改。
- `gate.py`：`can_touch_final_oos`（三结构性 BLOCK：非 confirmatory / 未冻结 / OOS 已消费；软护栏 + 措辞守门）。
- `lineage_hook.py`：状态跃迁发 PROV 事件（sink 失败落 pending 不静默丢）。

## 验收（29 对抗测试 + 变异全杀 + 5-lens 复核 15 真发现全修）

`tests/test_hypothesis_card.py` → **29 passed**；全量 **903 passed / 13 skipped**（基线未破）。
变异：自指标套套逻辑检测 / honest-N 实读 / 冻结只读(含 deviated 重载) / 篡改对账 → 全杀。

## 对抗复核（ultracode 5-lens）确认 15 真发现全修

- **#1/#2/#14 HIGH（命门）**：可证伪检测退化成中文-P&L-字词门——自指标(净值/累计收益/夏普/回撤)、
  英文、领域词包装的循环判据全判 high 静默冻结。修：rule1 检测「自身输出」自指(CN+EN _SELF_RESULT)、
  rule4 要求 fc 自身含独立可观测量（机制不能洗白空判据）、阈值/前置补英文。
- **#6 HIGH**：deviation 翻状态重开 hashed 字段。修：粘性 `_frozen_core`（冻结过即锁，跨 deviated/重载）。
- **#7 HIGH**：content_hash 篡改读路径不检。修：get() 对冻结卡重算对账 → CardTamperError。
- **#9/#10/#11 HIGH/MED（P2 边界）**：freeze 重绑探索污染 OOS / secondary 可冻结过闸 / frozen_oos=None 死码 consumed 门。
  修：freeze 沿父链查 touched_versions、只许 confirmatory、强制 frozen_oos.dataset_version。
- **#3/#4/#5/#8/#12/#13/#15 + 4 低**：英文阈值误杀、机制洗白噪声、low 静音复核、sink 失败丢事件、
  测试 banlist 漏词、lineage 无测试、ledger 缺省静默——均修 + 补回归。

## 诚实 deferred（[集成必补]）

验证官 verdict_id（部件12=T-020 未建）；Run.hypothesis_card_id 连接 + 阶梯对账（T13）；部件06 `consumed`/
`touched_versions` 真写回。当前在 mock/约定下绿，标注未经真系统验证。

## 下一步：T-018 安全门 deny-by-default + 交易所侧硬墙。
