# experience · 技术坑 + 正确处理（经验库）

> **干嘛**：踩过的技术坑 + 正解,给后来者避坑。
> **怎么更新**：append-only,最新加到下方注释第一位;**遇坑、修好后立即记一条**;某条通用到不分项目 → 升进 dev-os 的 `experience` 模板(给所有项目)。
> **什么进**：① 真踩过且**已解决**的坑 ② 会**再咬人**(有复用价值) ③ 一句话讲得清"坑→正解"。
> **什么不进**：决策(→`DECISIONS`,"为什么选 X"不是坑)· 未决风险(→`ISSUES`,没解决的不算经验)· 研究取舍(→`research/TRACE`)· 进度/现状(→`STATE`)· 一次性、不会再遇的琐事。

<!-- 格式·防跑偏 | 追加型：新坑追加到本注释下方第一位。每条照此：
## <领域> · <一句话坑>
- **坑**：<现象 / 为什么咬人>  - **正解**：<正确处理>  - **出处**：<task / commit / 文件> -->

## honest-N · 计数单键会把不同主题的同配置试验静默吞掉
- **坑**：试验账本计数键用 `config_hash` 单键 → 第二个主题里同 config 的试验撞行被吞 → honest-N 被洗白(漏报多重检验)。
- **正解**：复合键 `(config_hash, strategy_goal_ref)`;读路径 == 被核验路径,删 payload 旁路。
- **出处**：T-013 一本账。

## 确定性内核 · effectful（动钱）节点重放绝不能重发副作用
- **坑**：retry「整段重跑」会重发单(M17 雷);effectful 节点在 replay/fork/rollback 若不拦截 → 重复下单 / 撤单。
- **正解**：effectful 边界一律 **HALT**,发 `RECONCILE_REQUIRED` 交对账;恢复前先查 `EffectLedger.is_consumed` 幂等;**绝不重发 / 绝不撤单**。
- **出处**：T-014 内核 / T-021 / T-023。

## 幂等键 · effect_idempotency_key 绝不能由 LLM 生成
- **坑**：让调用方/LLM 给幂等键 → 可谎报、key 进 LLM(红线)。
- **正解**：内核**确定性派生**(`node_id` + 业务维度如 `client_order_id`),同一逻辑下单永远同 key、调用方无谎报口。
- **出处**：T-023 / `RULES.project` key 不进 LLM。

## 测试剧场 · 退化矩阵让变异测试假绿
- **坑**：N_eff 矩阵所有 `low==high` 退化 → low/high 互换的变异测试照样全绿(门是纸做的,假阴)。
- **正解**：补**跨相关带、严格非退化**的测试矩阵,让变异真能被抓。warning:种坏门必抓要验"门真会红"。
- **出处**：T-015。

## SQLite · 跨连接锁报错
- **坑**：多连接并发写 SQLite → database is locked。
- **正解**：开 `busy_timeout`;WAL 模式;读写路径同源。
- **出处**：T-014。

## Sentry · pytest 跑完在退出时假死
- **坑**：测试全过了,进程退出却阻塞在 Sentry flush,看着像"测试卡死 1 小时"。
- **正解**：`_under_pytest()` 下 `shutdown_timeout=0`(observability/errors.py)。
- **出处**：会话中 chip 任务。

## 真钱面审计 · 死代码 / 空壳控件别当成"已设防"
- **坑**：`GenericTradingVenue` 全 app 未实例化(死代码)、`emergency_close_all` 是空壳(只 log 不真平仓)、`kill_switch` 端点无鉴权——审计初稿曾过度报警"真钱可绕过",实则 live 下单面 100% 经门,真残余是急停控件不完整。
- **正解**：审计先 grep/读源**坐实调用点**再下结论;区分"能绕过下单"(假警)vs"急停控件缺"(真)。
- **出处**：T-025。

## dev-os 工具 · 这些是建 OS 本身踩的(任何项目通用)
- **zsh 数组**：`for f in $STR` 在 zsh 不按词分 → 用数组 `ARR=(...)`。
- **标签前缀计数**：数 `[已决]` 精确串数不到 `[已决 · 注]` → 用前缀 `[已决` 计数。
- **计数器方向**：`待拍/总`(0=完成)反直觉、坑人 → 改 `已决/总`(满格=完成)。
- **validator agent 别跑 pytest**：整套测试慢、会卡死后台 workflow;结构闸只跑 `validate_dev.py`(秒级)。
- **GitHub push 瞬时 SSL_ERROR_SYSCALL**:偶发 → 带重试推送(2~4 次)。
