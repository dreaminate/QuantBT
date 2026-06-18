# 分优先级路线图

> 北极星：让小白/经济学者走完最严谨、资产无关、中低频的策略闭环。原则：**先建脊柱，再回填方法学纵深，最后做翻译层**。高杠杆 + 低工程量优先。
>
> 每项标 `[effort / leverage]`，并注明**源码证据**与**核查降权**。⚠️ 标记是完备性复核对原路线图的修正——**这些必须在动工前纳入**。

---

## P0 · 信任脊柱（最高杠杆、低工程量，先做）

| 项 | 说明 | eff/lev | 依赖 |
|---|---|---|---|
| **`HypothesisSpec` 可证伪假设卡** | `StrategyGoal` 增三个必填字段 `economic_mechanism` / `falsification_condition` / `stop_rule` + 一句话因果链（赌哪个风险溢价/行为偏差）；澄清未填满前不许进回测；登记后不可变、带时间戳、打 `confirmatory`/`exploratory` 标记、进谱系 | low / **high** | 无（`strategy_goal.py` 加字段+冻结校验） |
| **`promote()` 改造成带审批门的状态机** | 晋升 staging/production 必须附 (a) 独立验证记录 id (b) `approver≠creator` (c) 过拟合证据快照(DSR+N/PBO/Bootstrap CI) 与 champion/challenger 结论，缺任一则拒绝并返回缺口清单。改 `store.py:232` + `main.py:405` | low / **high** | HypothesisSpec |
| **三件套接进真实 run + honest-N** | 在 `main.py` 的 backtest/训练 run 完成处自动调用 DSR/PBO/Bootstrap 写入 `run.metrics`；N 从用户手填（`tool_schema.py:170`）改为沿 `parent_run_id`/`forked_from` 谱系自动累加（先做相关聚类估 N_eff），自动注入 | medium / **high** | ExperimentStore lineage（已存在） |
| **修复 DSR 标度** | 给 `deflated_sharpe_ratio` 增可选入参 `var_sr_hat`，按 False Strategy Theorem 实现；保留 `sqrt(2lnN)` 仅作"方差未知退化近似"并在 docstring 标注、修正 `dsr.py:33-38` 自相矛盾注释；加单测对照论文数值例 | low / medium | honest-N |
| **反谄媚护栏 + 现实检验前移** | `coach.py` system prompt 与决策状态机写入"拒绝顺着用户优化、每次再调参显式提示 N 上升与门槛抬高、为什么这在经济上该有效=继续优化前必答闸口"；新增"澄清阶段 reality-check 规则" | low / **high** | HypothesisSpec |

> ⚠️ **完备性复核：P0 必须补两项前置**（否则脊柱建成即暴露下一批"洞"）：
> - **(P0-新) 自身信任论断的预注册 + 仪表化**："流程即信任"是整个愿景的承重前提却证据最弱。在它上面建 5 个阶段之前，**先给它一个可证伪指标 / 用户研究代理**（违反了它自己的纪律就不要建）。
> - **(P0-新) 数据可信度闸门**：GE-lite/dbt 列测试目前只在参考表里，漏斗在因子工作前**没有 data-trust gate** → garbage-in 能通过所有下游统计闸门。把它做成漏斗的**第一个一等节点**。

---

## P1 · 编排骨架

| 项 | 说明 | eff/lev | 依赖 |
|---|---|---|---|
| **确定性工作流图骨架** | 把"假设→数据→因子→标签→模型→信号→组合→独立验证→审批→上线→监控"固化为图节点，LLM 自主性收敛节点内；节点间 checkpoint 持久化、可恢复、时间旅行；给 `dag` 加 approve/interrupt | high / high | HypothesisSpec + 审批门 promote |
| **PROV-AGENT 谱系总线 + 预注册留痕 + GovernanceFunnel 看板** | W3C PROV schema 把 prompt/产出/dataset_version/下游指标接成可审计 DAG；记录"念头→澄清→HypothesisSpec→预注册时间戳"不可变链；可点击状态条看板（**新页面**，`RunDetailPage` 已冻结）；披露深度**用户自选**（OS 承载小白→quant 全谱、非身份门控） | high / high | 工作流图骨架 + HypothesisSpec |
| **独立 Verifier/Critic Agent + 证伪协议引擎 + 留出集硬隔离** | 异模型/异种子/异数据切片/CPCV 独立重跑，一次固化 N/PBO/DSR/PSR/MinBTL/purge-embargo/种子/hash 为不可篡改报告，有权 block；锁定 OOS 集探索期不可访问、审批门揭盲；配红队回归套件 | high / high | 工作流图骨架 + 谱系总线 + 三件套接线 |

> ⚠️ **完备性复核对 P1 的修正**：
> - **LLM 节点确定性必须先解决**（见 [01](01-agent-os-design.md)）：prompt/版本/seed/temperature 固定 + 响应缓存，否则"可回放/时间旅行/审计"承诺落空，连带谱系总线与 Verifier 的"可复现重跑"失效。
> - **安全模型前移到此处**（不要放 P5）：prompt-injection / tool-abuse / 数据投毒 / 特权混淆的红队，与 verifier 同期建。
> - **人类 RBAC 必须显式工程化**：`approver≠creator` 是器官划分假设，但多用户角色分离/权限模型未被规定——在单机本地优先下尤其要想清楚怎么"可强制"。
> - **Verifier 异模型依赖第二个 LLM 供应商/成本预算**；供应商单点或成本失控会使独立验证退化为同模型自评。

---

## P2 · 方法学纵深

| 项 | 说明 | eff/lev | 依赖 |
|---|---|---|---|
| **`impact_model` 接线进 `_cost_for_trade`** | 实现 sqrt 冲击 `cost=Y·σ·sqrt(Q/ADV)·notional`（Y~0.5 基线、δ∈[0.4,0.7] 敏感性、crypto Y~0.9），ADV 从面板估，linear/fixed 降级档；撮合计提 funding(8h)/borrow、A股卖出印花税；`cost_drift.py` 与 venue 共用同一 cost_model（消除 funding=3.0 双口径） | medium / **high** | 无（`backtest_venue.py` 局部改造） |
| **M8 优化器层接入回测 + 自适应 Ledoit-Wolf + 真 ERC** | `backtest_bridge` 可选 optimizer 而非仅 top-N 等权；`hrp_audit` 固定α升级为自适应收缩并让主入口共用；误命名的 `risk_parity`(∝1/σ) 升级为真 ERC 并保留旧逻辑为 `inverse_vol`；条件数/特征值诊断写进 run 元数据 | medium / **high** | 成本接线 |
| **信号层 conformal + abstain** | split/inductive conformal + CQR 包裹现有 LGBM 出预测区间；ACI 在线覆盖 + regime 偏离训练分布触发 abstain（不交易）接 KillSwitch/Live Ladder；前端把区间宽度画成误差棒接 L1 白话"把握度" | medium / **high** | 工作流图骨架 |
| **CPCV 喂 PBO/DSR** | `purged_cv.py` 已有 purge+embargo 基础上枚举 C(S,S/2) 组合产生多 OOS 路径，输出业绩分布与 10th-percentile（<100 路径告警），作为更强默认；与 walk-forward **双轨保留** | medium / medium | 证伪协议引擎 |

> ⚠️ 核查降权：平方根冲击律的 Y 默认值二手且 **AQR 有争议**——接线时标注不确定、做敏感性区间。CPCV 是"更强默认"非"唯一最优铁律"。
> ⚠️ **完备性复核：资产元数据依赖被排错序**——成本模型（funding/borrow/印花税/ADV）、回测撮合、universe 解析都**隐式依赖正确的合约规格与日历**，但 InstrumentSpec/日历被排到 P3/P4。考虑把 InstrumentSpec 的最小子集提前。

---

## P3 · 上线闭环与资产无关

| 项 | 说明 | eff/lev | 依赖 |
|---|---|---|---|
| **LiveMonitor 闭环 + 漂移→降级/退役** | 对每个 live/paper run 日收益/滚动IC/滑点做 CUSUM+Page-Hinkley（进阶 BOCPD）；用 live 净值持续重算 minTRL（须 Lo 式 AR/HAC effective-N 调整、报区间、用 SPRT/rolling-PSR 而非照抄 DSR 多重检验阈值），按 regime 条件化；触发降资本/暂停/移交 M11 `WARNING→RETIRED`→更新台账→通知；用 DAG cron 调度 | high / high | 工作流图骨架 + 谱系总线 + 三件套接线 |
| **策略层 `StrategyAllocator`（meta-allocation）** | 输入从 symbol×returns 升级为 strategy×PnL，先落地逆波动+HRP 两个稳健基线并与等权严格 walk-forward 对照；DSR 接成配资软门槛(>0.95 评分非硬否)；pod 级 kill/scale 阈值用户预注册可配（**不硬编码 5%/7.5%**）；copy_trade 加跨策略相关性/净额 | high / high | M8 优化器接线 + LiveMonitor |
| **一等 `InstrumentSpec` + 配置驱动资产注册表 + `app/calendar`** | 以不可变身份(stable_id/asset_class/currency/tick/lot/multiplier/上市退市/expiry)替代 `symbol(str)+market(str)`；封闭 `AssetClassTag` 改为注册表（每类注册日历/复权/roll/funding/借券/约束插件）；集成 exchange_calendars；连续合约/换月优先级靠后 | high / high | 工作流图骨架 |

> ⚠️ 核查降权：拥挤/动态缩量实证支柱（arXiv 2512.11913）**已撤稿** → 先做监控告警再议自动缩量。
> ⚠️ **完备性复核：P3 的隐藏交叉依赖**——LiveMonitor 依赖真实 live/paper run 持续产出日 PnL：A股仅 paper、crypto 依赖 Binance 实盘链路先可信。P3 实际门控于 P0-P2 **且** 门控于真实资本部署——线性 P0→P5 排序掩盖了这条依赖。**冷启动**：新用户第一个策略 N=1、无 challenger 历史，漏斗第一天的行为需单独定义。

---

## P4 · 治理深化与翻译层

| 项 | 说明 | eff/lev |
|---|---|---|
| **预注册去通胀层 + 多重检验校正族 + 跨资产复制/因子增量体检页** | 审批门对照实际 N 与登记上限超额亮红；归因→配置间加经验贝叶斯收缩 + OOS/post-pub 可配置折扣（用折扣后 Sharpe 进配置、前端并排展示样本内 vs 折扣后）；实现 BHY(FDR)+Romano-Wolf 封装；同一因子双 connector 复制对比 IC/方向、对现有因子族正交化取残差 alpha 的 t；**新增独立因子体检页**（勿动冻结的 `RunDetailPage`） | high / medium |
| **解释渲染器 (L1–L4，用户可自由上下钻、深度自选，非按人群门控) + 七宗罪按资产参数化 checklist + TCA/IS 瀑布与容量估计 + SR 11-7 live 模型风险看板** | 每策略一句话经济结论(成本是否吃光alpha+容量红黄绿灯)+渐进披露；回测前/审批门跑七宗罪体检（A股加涨跌停、加密加资金费率、期权加合约乘数）；implementation shortfall 分解 + 容量估计器（超容量 HITL go/no-go）；Brinson-Fachler（`brinson.py` **已实现**，仅扩到 live）+ 补因子(Barra-lite)归因；把 M11/M12/M13 拧成治理闭环看板 | high / medium |

> ⚠️ 核查降权：FDR 不"解决"发表偏误、t-hurdle 不可识别 → 辅助证据非唯一判据；拥挤监测仅作告警不触发自动降级；显式标注"平方根律/容量/真实成本高低估均有争议"。

---

## P5 · 可选增强

| 项 | 说明 | eff/lev |
|---|---|---|
| **MCP 式声明式工具注册（预留 A2A）** | 13 个 OpenAPI 工具与 `DataConnector`/`ExecutionVenue` 改造为 MCP 式声明式工具注册，使"资产无关靠填配置接入"更彻底；与现有 `SecureKeystore`/HMAC/withdraw-deny 护栏协同设计以控攻击面 | medium / medium |
| **Black-Litterman + CVaR + NCO 可选 objective** | 反向优化求均衡先验→接观点矩阵 P/Q/Ω→后验 μ 喂 `mean_variance`（经济学者只填"看多A相对B、置信度中"，τ/Ω 数据驱动缺省）；CVaR(Rockafellar-Uryasev LP)给"怕大跌"用户；NCO 复用 hrp 聚类与 HRP 并列 | medium / medium |

> ⚠️ **完备性复核强烈反对把安全放在 P5**：见 P1 修正。MCP/A2A 引入的新攻击面真实存在，且实盘 key + 能下单的 agent 自 P0 起在场——安全护栏**不是可选项**。

---

## 完备性复核的总裁定

> 接受诊断与"P0 脊柱优先"排序——代码现实支撑它。但在动工前，蓝图应：(a) 先**预注册并仪表化它自己的"信任论断"**再在其上建 5 阶；(b) 先**显式解决"确定性图里的 LLM 非确定性"**再声称可回放；(c) 把**安全/对抗模型与数据可信闸门从 P5/参考表前移进 P0/P1 脊柱**；(d) 加 **quant 逃生舱 + 探索通道 + 人类 RBAC + 闸门疲劳设计**，让脊柱"不可绕过"而不"不可用"；(e) 把 **honest-N 的 N_eff 与锁定 OOS 硬隔离重分类为深方法学/基建风险**，而非低工程量接线；(f) 补 **冷启动、成本/延迟预算、合规节点**覆盖。否则团队会装好一条漂亮的脊柱，然后恰好在这份蓝图停止观察的地方，发现下一批"已验证的洞"。
