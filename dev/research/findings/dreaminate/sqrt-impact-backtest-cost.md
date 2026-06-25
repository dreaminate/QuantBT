# FINDING · R18 平方根市场冲击 回测成本项（size-aware impact）

- **蒸馏自**:GOAL §4「成本/TCA（平方根冲击 δ=0.5 窄带 + funding/borrow/印花税，R18）」+ 现状审计：`execution/backtest_venue.py` `BacktestCostModel` 已有 commission/slippage(平 bps)/stamp/transfer/funding，但 **slippage 是常数 bps、无随单量缩放的平方根冲击**。
- **证据强度**:强 —— 平方根冲击律是机构标准（Almgren et al. 2005 / Kyle / BARRA），R18 明列 δ=0.5；与已交付的 §3 容量切片（`strategy_capacity`）**同一 sqrt-impact 物理**，互为交叉校验。
- **适用域**:中低频、有 volume（估 ADV）+ close（估 σ）的回测。**不成立的边界**：合理参与率区间内可信（极大单/极薄流动性外推不可靠）；无 volume 时不可估 ADV → 冲击启用即 raise（绝不静默当 0）。

## 核心主张（可证伪）[必填]

**如果**单笔成交量 qty 相对 ADV 的参与率 = qty/ADV，**则**平方根冲击成本（占成交名义比）=
**Y·σ·(qty/ADV)^δ**（δ=0.5 锁定 R18），随单量**凹增**（总冲击成本 ∝ Q^1.5）；**而**平 slippage_bps 与单量无关、
系统性低估大单成本 → 大资金回测过优。**命门交叉校验**：策略在 §3 容量 C 处交易，单期冲击成本（占 AUM 比）
**恒等于毛 alpha α**（容量定义：净 alpha=0），把回测冲击模型钉死在已验证的 `strategy_capacity` 上。

### 数学（公式 + 理论）

**平方根冲击律**（per 单笔，占成交名义比例）：
$$\text{impact\_frac} = Y\cdot\sigma\cdot\Big(\frac{Q}{ADV}\Big)^{\delta},\quad \delta=0.5\ (\text{R18 锁定})$$
- Q=本笔成交量（shares）、ADV=日均成交量（shares）、σ=日收益波动、Y=冲击系数（无量纲）。冲击成本(金额)=notional·impact_frac。
- **理论为何成立**：Kyle-λ / propagator 模型与海量实证给出冲击对单量**凹**（指数 δ≈0.5）；总冲击 ∝ Q·(Q/ADV)^0.5=Q^1.5 ⇒ 边际成本随单量升 ⇒ 大单被惩罚（容量约束的微观来源）。平 bps（δ=0）= 单量无关、错。
- **与 §3 容量交叉校验（命门）**：容量切片 cost(AUM)=τ·Y·σ·(τ·AUM/ADV)^δ，C 处 = α。单期交易 τ·C 名义、participation=τ·C/ADV ⇒ 冲击占 AUM 比 = τ·impact\_frac(participation) = τ·Y·σ·(τC/ADV)^0.5 = α。**两路同一 Y/σ/δ 物理、必吻合** → 单一公式源 `square_root_impact_fraction` + 交叉校验测试。

### 向后兼容（correctness · 不破回测基线）
`impact_coef` 默认 **0.0 = 关** → 冲击项恒 0 → 现有回测 commission+slippage+stamp+transfer **字节不变**（所有现有回测测试不动）。
opt-in 启用（impact_coef>0）时：**须 volume 列**（估 ADV），无则 **init raise**（绝不静默当 0 冲击=假绿灯）；σ 由 close 收益估。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/execution/impact.py` | 新建 | `square_root_impact_fraction(participation, volatility, impact_coef, delta=0.5)` 单一公式源 + δ 锁定 |
| `app/execution/backtest_venue.py` | `BacktestCostModel` +impact_coef/impact_delta；`__init__` 预算 per-symbol ADV/σ；`_cost_for_trade` +impact 项 | additive，默认关字节不变 |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. **向后兼容**：impact_coef=0（默认）→ 成本与改前逐位相等（现有回测不破）。
2. **平方根标度**：participation 翻 4 倍 → impact_frac 翻 2 倍（√，δ=0.5）；写成 δ=1（线性）或常数 → 抓。
3. **大单惩罚**：大单（高 participation）单位成本 > 小单（种小单/大单断言 impact_frac 单调升）。
4. **命门交叉校验**：容量 C 处单期冲击占 AUM 比 == 毛 alpha α（绑 `strategy_capacity`，口径漂移则崩）。
5. **不假绿灯**：impact_coef>0 但无 volume 列 → init raise（绝不静默 0 冲击）；participation<0/σ≤0/coef≤0 退化安全。
6. **δ 锁定**：impact_delta 默认 0.5（R18），改离 0.5 须显式（窄带，文档标）。

## 扩张窗 as-of 无泄露自估（resolves P2 0f696e56 · 数学先行）
**问题**：原自估用**全样本** ADV/σ（`mean(全部 volume)` / `std(全部 close 收益)`）作每笔成交的流动性输入 → 早期成交的参与率 `Q/ADV` 被**未来** bar 的流动性稀释、σ 含未来波动 = **前视泄露**，回测冲击偏乐观。

**修正（扩张窗 as-of 估计）**：设信息流 `F_{t⁻}` = 严格早于 `t` 的全部已实现数据。成交在 bar `t`（市价单于 `t` 开盘成交，故 `t` 当根的量/收益在成交时**尚未实现**）。定义仅依赖 `F_{t⁻}` 的估计：

$$\widehat{\mathrm{ADV}}_{t^-}=\frac{1}{|D_{<t}|}\sum_{d\in D_{<t}}V_d,\quad D_{<t}=\{\text{严格早于 }t\text{ 所在日的已完成日}\};\qquad \widehat{\sigma}_{t^-}=\operatorname{std}_{\text{ddof}=1}\{r_i: r_i\text{ 于 }<t\text{ 实现}\}$$

其中日内 datetime 按**日**聚合量（当日不计入，避免 √(bars/日) 抬升），收益 `r_i=C_i/C_{i-1}-1` 于 bar `i` 收盘实现、故 bar `t` 只用 `r_1..r_{t-1}`。

**无泄露性（证）**：每个被求和的 `V_d` / `r_i` 都在 `<t` 时刻实现 ⇒ 估计量是 `F_{t⁻}`-可测的确定函数 ⇒ 成交冲击只依赖 `F_{t⁻}`，**不可能**依赖 `≥t` 的数据 ∎。判别性命门：向序列**追加任意未来 bar**（量/σ 任意放大）**不得**改变任一早期成交的冲击——全样本估计会变（泄露）、扩张窗 as-of 不变（leak-free 的牙）。

**warmup（诚实处置·不假绿灯·裁决纯由 F_{t⁻} 驱动）**：`|D_{<t}|=0`（首日）或 prior 收益 <2（`t<3`）⇒ 估计在 `F_{t⁻}` 上未定义。**绝不**偷看未来补估，也**不**对该笔静默假装 0 成本——该笔**不计冲击但计数+披露**（`venue._impact_warmup_fills` + 一次性 warning）。**关键（评审 PROBE H 修正）**：warmup-vs-charge 的裁决**只看成交 ts 的 as-of 估计（F_{t⁻}）**，**绝不**用「全样本 `max(volume)>0`」之类含未来的信号判定——否则早期成交的 skip/charge 离散决策会被**未来 bar** 翻转（构成残余前视、且让缺流动性成交伪装成 warmup 静默放过=假绿灯）。「symbol 全样本无 volume」的硬 fail-fast 只保留在 **ts=None 终端路径**（汇总/直接调用，序列末无未来⇒非泄露）；replay 每笔成交一律走 F_{t⁻} as-of，估不出即 warmup-披露。一致性：随历史增长 `\widehat{\cdot}_{t^-}→` 全样本值（LLN），早期估计方差大（披露）；扩张窗剔除的正是全样本估计的乐观偏向。

**ts=None 回退**：直接调用（非 replay、无成交 ts）退化到**终端全样本**标量（序列末无「未来」⇒ 末端点估计用全样本非泄露），供单测/汇总；replay 路径恒传 ts → 走 as-of。

## 成本逐成分诚实归因（e2afc5c2 #1 · honesty）
fill 报告原 `commission` 字段实装的是**总成本**（commission+slippage+stamp+transfer+impact），下游做成本拆解/TCA 会把市场冲击误读成手续费。**修**：抽 `_cost_breakdown` 返 `{commission, slippage, stamp_duty, transfer, impact, total}`（impact **单列、绝不并入 commission**，各成分非负、求和==total）；fill 报告 **additive** 加 `cost_breakdown`，顶层 `commission` 保留=`total` 仅向后兼容（`cost_drift` 取总实现成本不破）。`_cost_for_trade` 变薄壳返 `total`；`step` 一次算 breakdown（避免重算令 warmup 计数双增）。種坏门：impact 并入 commission 成分→commission 虚高被抓（MUT-C 验证有牙）。
**e2afc5c2 #2（三档预设默认 size-aware）= 用户方法学决策**：启用 impact 仍需冲击系数 Y（无万能默认、须用户/校准给），选 Y 是用户那摊；seam 已就绪（任何预设 caller 可传 `impact_coef` + 无泄露自估/显式 ADV），生产默认保持关直到用户给 Y——不替拍板。

## 复用 [按需]
- `app/execution/backtest_venue.py`：现有 `_cost_for_trade`（commission/slippage/stamp/transfer），冲击项**加**不替换。
- `app/factor_factory/lifecycle_metrics.py` `strategy_capacity`：同 sqrt-impact 物理，交叉校验测试绑定（不跨模块产依赖，靠测试守一致）。

## 未验证残余（诚实）[必填]
- ~~**ADV/σ 估计**：用回测面板内 volume 均值 / close 收益 std（样本内估计）；真实生产应用滚动/前视无泄露~~ → **已解决**（上「扩张窗 as-of 无泄露自估」节，P2 0f696e56 闭环）：replay 每笔成交用 `F_{t⁻}` as-of ADV/σ、warmup 计数披露、追加未来 bar 不改早期冲击（leak-free 判别测试守）。显式点位 ADV/σ 仍是稳态推荐口径。
- **日内 σ 量纲**：扩张窗 σ 用 close 收益 std（与原口径一致）；日内 datetime 下 ADV 按日聚合、σ 仍是 per-bar 收益 vol → 与 daily-ADV 参与率存在量纲不齐（高频下偏小），与 leak-free 正交、属原口径残余（中低频日频不触发）。
- **同 symbol 重复 ts**：as-of map 按 ts 建键，同 symbol 同 ts 多行 last-write-wins（评审 low）；`_timestamps` 去重 + 日频唯一 ts 假设下 replay 不触发；如喂重复 ts 面板需上游去重。
- **Y 冲击系数**：须用户/校准提供（同容量切片），无万能默认；启用时由调用方给。
- **参与率适用域**：sqrt 律仅合理参与率可信，极大单未加 participation cap（docstring 披露）。
- **接线**：默认关、opt-in；接进交付门回测预设（三档成本）的生产默认属后续（建议 mint）。

## → 拆成的任务（mint uuid 入 tasks/pool/）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | 平方根冲击成本项数学对齐 R18、向后兼容默认关字节不变、容量交叉校验、无 volume raise、δ 锁定 | P1 | — |
| (建议后续) | 三档成本预设接 sqrt-impact 默认（生产回测 size-aware） + 滚动无泄露 ADV/σ | P2 | 本切片 |
