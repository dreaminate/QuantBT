# T-019 · 审批门 + promote 改带审批门状态机

- **状态**：✅ done（2026-06-18，含生产接线）· **review_status**：0
- **来源**：spine 07 + R1/R2/R5/R6/R7/P2 + M17 · **依赖**：T-013（一本账）、T-018（安全门）
- **优先级**：P1

## 做了什么

新建 `app/approval/`（schema/channels/store/gate/hard_limits），把 `ModelRegistry.promote` 的「3 行裸翻转」
升级成带审批门的状态机：
- **三要件**（晋升 staging/production 缺任一即拒 + 缺口清单，绝不进 pending）：(a) 独立验证记录
  verification_record_id（部件12=T-020 产）、(b) approver≠creator、(c) 多证据三角（DSR≥档 ∧ PBO≤档 ∧
  bootstrap CI 下界>0，**重算非信调用方自报**）。
- **双通道**：探索（dev/archived/非高影响）零门（P2）；确证走 durable interrupt 可挂数天。
- **honest-N 不可改小**：实读 T-013 一本账，比【名义 n_trials_raw】vs 账本 distinct（n_eff 聚类后下界不拿来比）。
- **approver≠creator** 归一比较（大小写/空白不绕过）；confirmatory 理由反套话。
- **幂等门后副作用**：意图先落盘再执行 → 崩溃 resume 不重复动钱；跨 gate 同 idempotency_key 去重。
- **门后硬限额**（审批≠授权）：真钱订单 fail-closed（缺 safety/缺 notional/超 cap 一律拒）。
- **SLA 超时**：未到截止不提前放行；到期按 action_kind 分流（止损放行/动钱拒）。
- **生产接线**：`apply_stage` 公开方法禁直翻 staging/production（防侧门）；`_apply_stage_unchecked` 仅经审批门
  execute_fn 到达；`approve_promotion` 真翻 stage；main.py 注入 GATE_SERVICE + 改 promote_model（422+缺口清单）+
  新增 approve/reject/get gate 端点。

## 验收（22 对抗测试 + 5 变异全杀 + 5-lens 复核 17 真发现全修）

`tests/test_approval_gates.py`（22）+ `test_experiments.py`（向后兼容 dev/archived 直翻 + production 无 gate raise）。
全量 **943 passed / 13 skipped**（基线未破）。变异：approver 归一 / SLA 截止 / 意图先落盘 / apply_stage 侧门 /
honest-N 比对字段 → 全杀。

## 5-lens 对抗复核：17 真发现全修

- **#1/#8/#16 HIGH 生产接线**：门从未接进 live promote（production→未捕获 500、无 approve 端点）→ 已接
  （注入 GATE_SERVICE 晚绑定 + 改端点 + 加 approve/reject/get）。
- **#2/#15 HIGH apply_stage 侧门 + 执行断链**：公开 apply_stage 可直翻 production；approve 不真翻 stage →
  apply_stage 禁 staging/production + approve_promotion 绑 _apply_stage_unchecked 真翻。
- **#3 MEDIUM honest-N 比错字段**：拿聚类后 n_eff 比账本 distinct 会误杀合法晋级 → 改比名义 n_trials_raw。
- **#4/#14 honest-N 静默跳过**：缺账本/缺 goal 时不核 → confirmatory 强制核验、缺即 gap（不豁免）。
- **#6 HIGH 崩溃双发**：execute 后才标 executed → 改意图先落盘（宁漏勿重，venue 级对账→T-021）。
- **#7 HIGH approver 绕过**：大小写/空白 → 归一比较。
- **#10 HIGH SLA 提前放行**：on_sla_expire 不查截止 → 加截止检查。
- **#11/#12/#13 硬限额**：绑 to_stage 而非动作 / safety=None 静默放过 / 缺 notional fail-open → 绑真钱订单动作 +
  fail-closed（缺 safety/notional/cap 一律拒）。
- **#5 坏 evidence TypeError**：转缺口不抛。**#9 跨 gate 幂等**：按 idempotency_key 去重。**#17 + 低**：补正路测试/措辞刷新。

## 诚实 deferred / 残余（[集成]）

- verification_record_id 仅查存在（真验证官 verdict 由 T-020 产 + 验签）→ T-020 接。
- venue 级崩溃对账（已 ack 未落 ref）→ T-021（执行接线）。
- `_is_substantive` 反套话是粗判（§7 open Q#5）；单用户 approver≠creator 是防自欺约定非组织独立（诚实标注）。

## 下一步：T-020 验证官（产 verdict_id，异模型一致性，喂 T-017/T-019）——脊柱最后一块。
