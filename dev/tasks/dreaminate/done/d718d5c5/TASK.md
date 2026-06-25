---
uuid: d718d5c54ee54ba39d35b17166aea0c3
title: §5 生产期漂移检测器（rolling-PSR/CUSUM/Page-Hinkley/PSI）+ 理论不变量命门
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: monitor
source: goal-gap
source_ref: GOAL §5「漂移监控 rolling-PSR/CUSUM/Page-Hinkley/PSI · 绩效轴主告警 / 特征漂移仅根因」+ state.md「新生残余建议 mint 卡：§5 漂移检测器 PSR/CUSUM/PSI」
depends_on: []
---

# §5 生产期漂移检测器 + 理论不变量命门

## Scope [必填]
补齐 GOAL §5 缺失的**统计漂移检测器**（现有 monitor 只有粗粒度成本漂移阈值）：
① rolling-PSR（绩效轴**主告警**）② CUSUM（冻结基准双侧）③ Page-Hinkley（frozen-baseline）
④ PSI（特征轴**仅根因**）。每个**数学先行**（公式+推导+理论为何成立），实现对齐理论，
并把「论文公式直接蕴含的理论不变量」写成跨 seed property 守门（北极星#4 命门：机器可校验
「实现↔理论一致」的持久化形态）。绩效轴 additive 接进 `monitor_tick`；PSI 类型层隔离禁入退役。

## 上下文 / 动机 [按需]
北极星：数学贯穿全流程（#1）+ 理论先证明（#2）+ 监管对齐命门（#4）。本切片把 §5「能信」推进一格。
设计/推导全文：`dev/research/findings/dreaminate/drift-detectors.md`。
并行双脑（deep-opus ‖ codex）三脑复核公式 + 治理红线；deep-opus 实证抓到教科书 Page-Hinkley
全局 running-mean 的 √t 假告警致命陷阱（平稳噪声 FPR→1）→ 改 frozen-baseline 变体并配 sentinel。

## 治理红线（命门·结构钉死）[必填]
- **M-AUTHORITY=A1**：rolling-PSR/CUSUM/PH 是绩效轴信号，可喂退役矩阵；**rolling-PSR 签名刻意不暴露
  n_trials/var_sr_hat**——否则把 SR* 设成 E[max SR over N] 即变回 DSR（多重检验通缩、晋级期过拟合闸）=
  范畴错误（GOAL §5「绝不把 DSR 搬实盘单策略」）。
- **PSI 特征轴仅根因**：`FeatureDriftDiagnosis` 无 breach 字段、无 to_lifecycle_observation、是独立类型 →
  退役矩阵签名收不下它（类型层 + monitor_tick 运行期 axis 防伪双拦）。
- **三态铁律**：ok / breach / **insufficient_evidence**——非有限值(NaN)/短样本/σ≈0 绝不当 ok（不假绿灯）。
- **冻结基准（E2）**：CUSUM/PH 的 μ0/σ0 须晋级期 OOS 冻结、绝不用监控窗自身均值（否则缓降免疫）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/eval/dsr.py | +`probabilistic_sharpe_ratio` | PSR 构件，复用 _skew/_kurt_excess/σ阈；与 DSR V-path 互为 1e-12 交叉校验 |
| app/backend/app/monitor/drift.py | 新建 | 4 检测器 + 三态 + 绩效/特征轴类型隔离 + 有限性守门 |
| app/backend/app/monitor/closure.py | monitor_tick +perf_drift | 绩效轴漂移 additive 喂 lifecycle 权威（PSI 类型层拒入）|
| app/backend/app/monitor/__init__.py | 导出 | — |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. PSR 量纲误年化 → PSR↔DSR V-path 恒等(<1e-12)崩；denom 不钳制 → sqrt(负)=NaN 被 `psr∈[0,1]` 抓。
2. CUSUM 去反射壁 → `S±≥0` 抓；用监控窗自身均值当 μ0 → 温水煮青蛙缓降不告警（种缓降序列断言 S⁻破 h）。
3. CUSUM 方向搞反 → step-down 断言 S⁻>S⁺、step-up 不退役。
4. PH sentinel：弃用全局 running-mean 变体平稳噪声 ~100% 假告警、frozen-baseline 0 假告警（门有牙）。
5. PSI 实现成非对称 KL → `PSI(a,e)==PSI(e,a)` 抓；负值 → `PSI≥0` 抓。
6. **PSI 范畴红线**：PSI=∞ 剧烈漂移但绩效 ok → 绝不退役（喂 monitor_tick 类型层 raise）；绩效崩 → 照常退役。
7. **NaN 静默假绿灯**（评审 high 发现）：种 NaN（喂数缺口）→ 4 检测器全判 insufficient_evidence、绝不 ok。

## 验收一句话 [必填]
4 漂移检测器数学对齐理论、PSR↔DSR 交叉校验锚住、PH 陷阱 sentinel 门有牙、PSI 范畴隔离不可绕过、
NaN 不假绿灯；理论不变量层 +19 条守门；全量后端绿、基线不破。

## 完成记录（2026-06-24 · autonomous-loop / D-DRIFT-§5）
- **数学先行**：落 `findings/dreaminate/drift-detectors.md`（4 检测器公式+推导+治理 voice+可证伪验收）；
  并行双脑 deep-opus‖codex 复核，修正 Page-Hinkley √t 假告警陷阱。
- **实现（扩展不替换）**：`dsr.py` +`probabilistic_sharpe_ratio`（PSR↔DSR V-path 恒等实测 0.0 偏差）；
  新建 `monitor/drift.py`（rolling-PSR/CUSUM/Page-Hinkley/PSI + 三态 + 绩效/特征轴类型隔离 + `_all_finite` 守门）；
  `monitor_tick` additive `perf_drift` 入参（axis 防伪 + PSI 类型层拒入）。
- **对抗测试 + 命门**：`test_drift_detectors.py` 31 passed（含温水煮青蛙/方向/PH sentinel/PSI 范畴红线/NaN）；
  `test_methodology_invariants.py` 19→38 passed（+19 漂移理论不变量：PSR↔DSR 恒等含中段判别力、PSI 对称/非负/置换、
  CUSUM 平移/尺度等变 + sentinel 门有牙、PH FPR 受控）。
- **多透镜评审**（autoplan 等价：correctness/governance/CEO/eng 4 透镜并行 + 对抗复核）：5 条 confirmed 全修——
  **4 条 NaN 静默假绿灯（high·正中本模块自钉命门）**+ 1 条 CEO 阈值代价诚实披露；eng 4 清理全做。
- **验证**：全量后端 **1426 passed / 13 skipped / 0 failed**（167s），基线（1357）未破。
- **诚实残余（非假绿，明确边界）**：冻结基准 μ0/σ0 跨重启持久化依赖上游观测管道（建议 mint 后续卡）；
  PSR 自相关高估有效 n（docstring 披露）；阈值标定（PSR_FLOOR=0.90 代价已诚实标注）属用户方法学旋钮。
- **land main 待用户授权**（不擅自 commit/push）。
