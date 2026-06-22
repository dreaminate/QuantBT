---
uuid: b106177f560746f7b88f79bfee4bf70d
title: 因子台后端接线 — 暴露已有 compute + 相关性/分层回测 + alpha审查
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: backend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [5e47b82f3ba847938f4000fadf9c2fb7]
---

# 因子台后端接线 — 暴露已有 compute + 相关性/分层回测 + alpha审查

## Scope [必填]
做：把 factor_factory 已实现但未 HTTP 暴露的 compute 接成 FastAPI 端点（IC 日度序列 / IC 衰减 / lifecycle event log / 表达式 validate / POST 注册因子），新建相关性矩阵+去冗余、分层回测两个评测端点，并把已存在的 `app/eval/` 审计原语（DSR/PBO/N_eff/bootstrap）接成因子级 audit 端点；统一打通"按因子+市场取 panel"的数据源前置层。不做：前端 React 实装（属同 epic 其它卡）、Claude Code agent/chat 端点（R20 LLM 引导生成暂缓）、三纯库 ML/DL 分库与暴力遍历挖掘（设计稿缺、需补设计）、factor_family 字段落库（前端可从 formula 推断，本卡不改 Factor model schema）。

## 上下文 / 动机 [按需]
设计稿 5 个 view（因子库/相关性/评测台/构建台/研究台）当前全是纯前端 mock（无任何 fetch）。理解材料 §⑦ 已枚举缺口：低成本类（计算已存在、只缺路由）= `ic`/`ic_decay`/`lifecycle/events`/`validate`/`POST factors`；中成本类（需新建计算）= `layered_backtest`/`correlation`；高成本/机构级硬骨头 = `audit`。

关键发现（graphify query 已证实）：审计数学**并非零实现**——`app/eval/` 已有 `cscv_pbo()`(pbo.py L58)、`deflated_sharpe_ratio()`(dsr.py L58)、`n_eff_from_matrix()`(n_eff.py L66)、`bootstrap_sharpe_ci()`(bootstrap.py L39)、`run_overfit_gate()`(overfit_gate.py L130)、`evaluate_overfit_gate()`(gate_runner.py L89)。因此 audit 端点的本质是**复用已有 eval 原语做多证据三角组装 + 因子级接线**，不是从头写统计学。但方法学口径（honest-N 三档预注册阈值、Newey-West 自相关调整是否纳入、verdict 措辞经 R7）仍需先拍板再实装——这是本卡唯一待拍板项（见 Open Questions）。

panel 前置：所有 IC/回测/audit 端点都吃 polars panel 入参（symbol/ts/close/volume…）。现有 `load_sample()`(datasets/samples.py L170) / `load_training_panel()`(training/datasets.py L50) 可作数据源，需一个"按 factor + market 取 panel"的接线 helper 作为评测类端点共同前置（依赖 F1 5e47b82f 已建的数据面）。

## 接线点（file:line，实现时复核）[必填]

| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/main.py` | L422-436（现 3 个 factor 路由 `operators`/`list_factors`/`get factor`） | 在其后**追加**新路由，不动现有 3 个；保持 `FACTOR_REGISTRY`(L91) 单例 |
| `app/backend/app/main.py` | L428 `list_factors()` 附近 | 新增 `GET /api/factors/{id}/ic?horizon=` → `compute_ic_report().by_period`（含日度 IC 柱来源） |
| `app/backend/app/main.py` | 同区 | 新增 `GET /api/factors/{id}/ic_decay` → `compute_ic_decay()`(ic.py L112) |
| `app/backend/app/main.py` | 同区 | 新增 `GET /api/factors/{id}/lifecycle/events` → `LifecycleManager.events()`(lifecycle.py L142)/`.history()`(L139) |
| `app/backend/app/main.py` | 同区 | 新增 `POST /api/factors/validate` → `compile_expression`(expression.py L63)+`parse_expression`(L55)+前视审计+`evaluate_on_panel`(L109) 即时 IC |
| `app/backend/app/main.py` | L434 后 | 新增 `POST /api/factors` → `FACTOR_REGISTRY.register()`(registry.py L58)，**必须先过 LifecycleManager 入库（初始 NEW）+ 编译/前视/无重名三检查**，绝不裸写 registry |
| `app/backend/app/main.py` | 同区 | 新增 `GET /api/factors/correlation?market=` → Spearman rank-corr 矩阵 + 去冗余簇（新建计算，建议落 `factor_factory/correlation.py` 新模块） |
| `app/backend/app/main.py` | 同区 | 新增 `GET /api/factors/{id}/layered_backtest?horizon=` → 五分位 quantile 回测（新建计算，建议落 `factor_factory/layered.py` 新模块） |
| `app/backend/app/main.py` | 同区 | 新增 `POST /api/factors/{id}/audit` → 组装 `deflated_sharpe_ratio`(dsr.py L58)+`cscv_pbo`(pbo.py L58)+`n_eff_from_matrix`(n_eff.py L66)+`bootstrap_sharpe_ci`(bootstrap.py L39)，verdict 文案走 `_verdict_note`（R7） |
| `app/backend/app/factor_factory/` | 新文件 `panel_source.py`（或 main.py helper） | 新增"按 factor_id+market 取 panel"接线层，调 `load_sample`(datasets/samples.py L170)/`load_training_panel`(training/datasets.py L50)；评测类端点共同前置 |
| `app/backend/app/eval/` | `pbo.py`/`dsr.py`/`n_eff.py`/`bootstrap.py`/`overfit_gate.py` | **只调用不改写**——audit 复用已有原语，禁止在 main.py 内联重写统计 |
| `app/backend/tests/` | `test_academic_audit.py`(已存在)、`test_alpha_lite_and_lifecycle.py`(已存在) | **扩展**：新增因子级 audit 端点测试 + 注册绕门测试，不替换现有用例 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种<注册因子直写 `FACTOR_REGISTRY.register()` 绕过 LifecycleManager（不经初始 NEW、跳过编译/前视/无重名三检查）> → 门必<抓：注册路由必须经生命周期入库，未过门的 POST 被拒/状态非 NEW 即 fail>。变异要杀的点：把 `POST /api/factors` 改成裸调 registry.register、或把初始 state 写成 QUALIFIED 跳过 NEW，门必红。
2. 种<audit 用单点红线下结论——只看 IC 显著（单证据）就出 verdict="真alpha"，不做 DSR/PBO/N_eff 多证据三角> → 门必<抓：audit 缺任一证据维度（DSR/PBO/honest-N）即不得给正向 verdict，缺证据必降级为"存疑"/"未通过"，绝不"真alpha">（R2 多证据三角）。变异要杀的点：删掉 audit 里 `cscv_pbo`/`deflated_sharpe_ratio`/`n_eff_from_matrix` 任一调用，门必红。
3. 种<IC/IC衰减/分层回测端点喂未复权或前视（用了未来标签/未 shift forward return）的 panel> → 门必<抓：panel 数据源层强制复权 + forward return 用 `attach_forward_returns`(ic.py L52) 正确滞后，前视/未复权数据进端点必报错或被审计标红>。变异要杀的点：把 `attach_forward_returns` 的 horizon 滞后改成 shift(0)（前视穿越），门必红。
4. 种<audit verdict 文案出现"可信/安全/排除过拟合/保证"等禁词，或不走 `_verdict_note`> → 门必<抓：R7 措辞门扫到禁词即 fail；裁决文案必须由后端 `_verdict_note` 产出>。变异要杀的点：在 verdict 串里硬编"已排除过拟合"，门必红。

## 复用 [按需]
- IC 系：`compute_ic_report`(ic.py L67) / `compute_ic_decay`(ic.py L112) / `attach_forward_returns`(ic.py L52) / `ICReport.to_dict`(ic.py L19)。
- 表达式：`compile_expression`(expression.py L63) / `parse_expression`(expression.py L55) / `evaluate_on_panel`(expression.py L109) / `ExpressionError`(expression.py L51)。
- 生命周期：`LifecycleManager`(lifecycle.py L122) 的 `.events()`(L142)/`.history()`(L139)/`.evaluate()`(L147)/`.record_observation()`(L135)；`LifecycleThresholds`(lifecycle.py L27)；`LifecycleEvent.to_dict`(lifecycle.py L66)。
- 注册：`FactorRegistry.register`(registry.py L58) / `.list`(registry.py L98) / `.get`(registry.py L88) / `Factor.to_dict`(registry.py L38)。
- 审计原语（**关键复用，禁重写**）：`deflated_sharpe_ratio`(dsr.py L58) / `cscv_pbo`(pbo.py L58) / `n_eff_from_matrix`(n_eff.py L66) / `bootstrap_sharpe_ci`(bootstrap.py L39) / `run_overfit_gate`(overfit_gate.py L130) / `evaluate_overfit_gate`(gate_runner.py L89)。
- 数据源：`load_sample`(datasets/samples.py L170) / `load_training_panel`(training/datasets.py L50) / `datasets_sample_preview`(main.py L2717) 接线范式。

## 红线 [按需]
- 注册因子唯一入库路径经 LifecycleManager（初始 NEW）+ 编译/前视/无重名三检查；绝不裸写 registry（权限轴⟂治理轴，bypass 不跳过拟合门/血统门/生命周期门）。
- audit verdict 禁词「可信/安全/排除过拟合/保证」(R7)，裁决文案走后端 `_verdict_note`；弱点一等呈现——PBO/DSR/honest-N 默认不染绿、不折叠(R25)。
- audit 必走多证据三角(R2)，单点红线不得出正向结论；honest-N N_eff 必抓(GOAL §3)。
- 复用 `app/eval/` 原语，不在 main.py 内联重写统计；不削弱已有过拟合门基线。
- panel 数据源强制复权 + 正确 forward-return 滞后，绝不前视穿越（GOAL §3/§4 防泄露）。
- 主进程不碰 torch(M6)——本卡纯算术/统计接线，不引入 DL 依赖。

## 非目标 [按需]
- 前端 React 实装（同 epic cfb0fea9 其它卡）。
- Claude Code 因子 Agent / 学术审查 chat 端点（R20 暂缓）。
- 三纯库 ML/DL 分库 + 信号契约、暴力遍历挖掘 view（设计稿缺、需补设计再立卡）。
- factor_family 字段落库 / market 分区改 registry schema（前端可推断；本卡不改 Factor model）。

## Open Questions（已决 D/总）[已决 0/总 1]
1. [已决] audit 方法学口径 2026-06-21 用户拍板「全采纳 + 数值可调」(D-F2-AUDIT)：(a) honest-N 三档(谨慎/标准/宽松,R3)——标准档=DSR 诚实 N_eff 通缩后 t>3,用文献默认(Bailey-López de Prado);(b) IC 显著性纳 Newey-West 自相关调整;(c) verdict 降级 全达标 consistent/任一不达标 concern/多个严重 blocked(对齐 R2 多证据三角);(d) 文案走 verifier._verdict_note,禁 R7 词,模板「证据[一致/存疑/不一致]+适用域+未验证项 N」。**阈值数值研究侧可调**(§0.1)——用户可配不锁,调整计入 honest-N(门槛随之抬高)+显示通缩真相+防呆,不硬编死值。

## 验收一句话 [必填]
种"注册绕生命周期门 / audit 单点红线下正向结论 / IC 端点喂前视未复权数据 / verdict 含 R7 禁词"四类坏 → 对应门必全抓（注册必经 NEW+三检查、audit 必多证据三角且缺证降级、panel 必复权+正确滞后、文案走 `_verdict_note` 无禁词），且不破现有 `test_academic_audit.py` / `test_alpha_lite_and_lifecycle.py` / 过拟合门测试基线。
