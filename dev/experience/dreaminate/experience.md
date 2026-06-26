# experience · 技术坑 + 正确处理（经验库）

> **干嘛**：踩过的技术坑 + 正解,给后来者避坑。
> **怎么更新**：append-only,最新加到下方注释第一位;**遇坑、修好后立即记一条**;某条通用到不分项目 → 升进 Multi-Dev-Os 的 `experience` 模板(给所有项目)。
> **什么进**：① 真踩过且**已解决**的坑 ② 会**再咬人**(有复用价值) ③ 一句话讲得清"坑→正解"。
> **什么不进**：决策(→`DECISIONS`,"为什么选 X"不是坑)· 未决风险(→`ISSUES`,没解决的不算经验)· 研究取舍(→`research/TRACE`)· 进度/现状(→`STATE`)· 一次性、不会再遇的琐事。

<!-- 格式·防跑偏 | 追加型：新坑追加到本注释下方第一位。每条照此：
## <领域> · <一句话坑>
- **坑**：<现象 / 为什么咬人>  - **正解**：<正确处理>  - **出处**：<task / commit / 文件> -->

## dev/OS 卡操作 · validate 四连坑（status / 视图过期 / depends_on / 字面量）
- **坑**：① 卡 `status: doing` 非法（只认 `todo|in_progress|done`）→ validate FAIL；② mint/move 卡后没跑 `build_*.py` → "生成视图过期(DEVMAP/board)" FAIL；③ done 卡 `depends_on` 手写 32-hex uuid 抄错尾巴（抄成别张卡的尾）→ 悬空依赖 FAIL；④ 卡散文写 `[需拍板` 方括号字面量 → validate `_pending` 子串计数误报成待拍。
- **正解**：status 用 `in_progress`；加/动卡后必跑 `build_card_counters/build_board/build_dev_map/build_log_index/build_ledger` 重建视图再 validate；`depends_on` 从依赖卡 `grep ^uuid:` 复制核对（别凭记忆抄尾）；散文写"需拍板项"不带方括号。**push 必门控 `validate_dev PASS && push`**（别让 push 跑在 validate 之后无门控·否则会推出 FAIL 的树）。
- **出处**：中心整合多波 + Stop-hook codex 复核（抓出 status doing / 视图过期 / depends_on 悬空）。

## 接生产路径 · 能力超前于数据源时硬接=空壳/假绿灯
- **坑**：库建好但生产侧无对应数据源（`build_factor_attribution_report` 无 per-run 因子收益矩阵 / `evaluate_release` 无填满的 ReleaseCandidate / synth 走确定性模板本就无 LLM·dataset）→ 硬接 GET 路由变"永远 available:False"空壳，或要大改输入管线却产假证据。
- **正解**：**不建空壳**；缺即诚实记缺口（如 KNOWN_RUN_GAPS）；大活拆「opus 建孤立输入管线 lib（**producer 写 consumer 读的键**·字段名端到端核对，曾把组装器 `_block_from_dict` 误记成 `_execution_block_from_dict`）+ 中心串行接生产路径」两步；门接生产路径用 **advisory-first**（evaluate→attach verdict 到 run.json·**只记录不 reject**·enforce 留后续显式决策）→ 改 `promote_ide_run`（众多 promote 测试共用）零回归；MUT 把 advisory 改洗白（恒 `ok=True` 不真跑门）验门真在跑非桩（模板基线测试转红）。
- **出处**：promote 证据组装器 / 执行诚实落账 / §16 发版门 advisory 接 promote（链：八门聚合→组装器→执行诚实→advisory）。

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
