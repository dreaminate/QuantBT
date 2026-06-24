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

## 复用 [按需]
- `app/execution/backtest_venue.py`：现有 `_cost_for_trade`（commission/slippage/stamp/transfer），冲击项**加**不替换。
- `app/factor_factory/lifecycle_metrics.py` `strategy_capacity`：同 sqrt-impact 物理，交叉校验测试绑定（不跨模块产依赖，靠测试守一致）。

## 未验证残余（诚实）[必填]
- **ADV/σ 估计**：用回测面板内 volume 均值 / close 收益 std（样本内估计）；真实生产应用滚动/前视无泄露的 ADV/σ（本切片估计口径 docstring 标，未做滚动）。
- **Y 冲击系数**：须用户/校准提供（同容量切片），无万能默认；启用时由调用方给。
- **参与率适用域**：sqrt 律仅合理参与率可信，极大单未加 participation cap（docstring 披露）。
- **接线**：默认关、opt-in；接进交付门回测预设（三档成本）的生产默认属后续（建议 mint）。

## → 拆成的任务（mint uuid 入 tasks/pool/）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | 平方根冲击成本项数学对齐 R18、向后兼容默认关字节不变、容量交叉校验、无 volume raise、δ 锁定 | P1 | — |
| (建议后续) | 三档成本预设接 sqrt-impact 默认（生产回测 size-aware） + 滚动无泄露 ADV/σ | P2 | 本切片 |
