# T-015 · 试验账本算法层 + 多证据三角 gate（接 M10 守门进 run 闸门）

- **状态**：done
- **review_status**：1（用户 2026-06-19 确认）
- **来源**：spine-designs 05（§3.4 gate / §5 T1–T16）+ 复核 00 §1.2-I（只建算法层、读 T-013 一本账）+ R2/R5
- **优先级**：P0（**STATE 头号 gap**：M10 PBO/DSR 裸算不挡发布）· **依赖**：T-013（一本账）、T-014（内核）

## Scope（单一能力单元）

把【从不被调用】的 M10 守门器（`eval/dsr|pbo|bootstrap`）组装成**多证据三角 gate**，接进
promote 关卡 → 让 `risk_summary._rule_dsr/_rule_pbo` 从「永远拿 None 不触发」变真生效。
**不自建第二本账**（复核 00 §1.2-I）：读 T-013 `Ledger` 的 honest-N。

## 做了什么

- `eval/dsr.py`：+`var_sr_hat`（False Strategy Theorem V）；`_skew/_kurt_excess` 改**标准总体矩**
  （独立对账探针揪出旧混合估计量）；**None 分支改 studentized**（去掉 `/√ppy` 量纲 hack，复核 #2）。
- `eval/bootstrap.py`：+`block_size`（moving-block 保序列相关）+ method 字段；block≥T 钳到 T//2（防零宽 CI）。
- `eval/n_eff.py`：收益相关层次聚类 → N_eff 区间（等价写法 `a*2`/`a+a` 聚 1 簇）；口径锁版本防放水。
- `eval/overfit_gate.py`：多证据三角（`_decide` 纯裁决：三支同向才 green / 任一强负 red / 缺 PBO 至多
  yellow / 短样本 insufficient）+ 通缩区间 + R5 披露 + 措辞禁可信/安全/保证。**保守端通缩以 honest_n
  兜底**（复核 #1/#4 命门：聚类信用只在乐观端，绝不让矩阵拼不出时通缩归零）。
- `eval/gate_runner.py`：接 T-013 一本账 + 收益快照（**内容寻址**）+ 拼同主题同长矩阵 + 算 N_eff + 跑 gate。
- 接线：`ide/promote.py`（opt-in，传 ledger 才跑）注入 dsr/pbo/bootstrap 进 metrics + gate_verdict 进 run.json；
  `main.py` 实例化 `LEDGER`+`RETURNS_STORE`、promote/risk_preview 接线、新增 `/api/research/themes/{t}/honest_n` 下钻端点。

## 验收（24 对抗测试 + 变异全杀 + 两轮复核）

`tests/test_overfit_gate.py`（17）+ `tests/test_gate_wiring.py`（6）+ `test_eval.py`（向后兼容 8）：
噪声→不绿 / 真信号→绿 / 短样本→证据不足 / 泄露→N_eff<<N / 等价写法聚 1 / 独立试验不过聚 / 三支不同向→不绿 /
`_decide` 无单点 / PBO 缺→至多 yellow / 噪声填充不能绿弱策略 / block 比 iid 敏感 / DSR 独立重算对账 /
var_sr_hat 改 DSR / 措辞禁绝对化 / **通缩区间严格非退化+保守端用更大 N** / **honest_n 兜底通缩** /
**V 不可估披露** / 接线活性（gate 把 risk_summary 从 insufficient 接成真裁决）/ **gate→flag 回路闭合** /
preview 不记账 / promote 记账 + memoize。
`cd app/backend && python -m pytest tests/test_overfit_gate.py tests/test_gate_wiring.py -v` → **24 passed**。
全量 **844 passed / 13 skipped**（821 基线未破，additive）。变异：honest_n 兜底 / low-high 互换 / 单点裁决 /
噪声→绿 / n_eff 不聚 / block→iid / 短样本 / preview 记账 / promote 不注入 / var 披露 → 全杀。

## 对抗复核（ultracode 5-lens workflow）

确认 **10 真发现**全修（2 个 HIGH 由 verifier 现场复现）：
1. **#1/#4 HIGH（命门）**：gate 只用 N_eff 驱动通缩，honest_n 算了却没用 → 矩阵拼不出（首次 promote/异长）
   时 N_eff=1、**通缩归零**，12 个相关泄露试验直接过闸。修：honest_n 兜底保守端通缩。
2. **#2 MEDIUM**：None 分支 `/√ppy` 量纲不一致 + 频率失真 + ppy 硬编。修：studentized + 线程 ppy。
3. **#3 HIGH**：噪声填充解锁 PBO。修：honest_n DSR 兜底使其无法放行弱策略（+ T-OG-7c）。
4. **#5/#6 + 4 低**：config_hash 撞键 memoize（intended，文档化）/ preview 双计（去重）/ 收益内容寻址 /
   block 钳位 / preview 异常不静默（标 error 给前端）。
5. **#7/#8/#9/#10 测试剧场**：所有测试矩阵 N_eff.low==high 退化 → low/high 互换变异竟全绿 → 补跨相关带
   严格非退化测试 + var 披露测试 + gate→flag 闭环测试。

## 踩坑

- 所有测试矩阵都用独立噪声列 → N_eff 区间退化（low==high）→ 通缩区间/保守端用 high 这条命门【零覆盖】，
  low/high 互换变异存活。修：造跨 0.6–0.8 相关带的簇。
- 自家变异 harness 用 `git checkout` 还原被 mutate 的 tracked 文件 → 把未提交的 promote.py T-015 改动清空，
  重新应用。（教训：mutate tracked 文件用 cp 备份还原，勿 git checkout。）

## 下一步

脊柱第 1 层完成（M10 守门接进 run 闸门=头号 gap 闭合）。下一个 T-016 02 LLM record/replay + 受控翻译层。
gate_verdict→risk_summary 颜色映射、IDE config 粒度（params 入 metadata）为已记录的后续增强。
