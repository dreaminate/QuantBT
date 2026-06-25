---
uuid: 69e1cb16765a4326a11252a1d598574e
title: R23 不确定性预测区间（split conformal/CQR/ACI）+ abstain + 覆盖定理命门
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: eval-methodology
source: goal-gap
source_ref: GOAL §4「conformal/CQR/ACI 区间 + abstain（R23）」+ 决策 R23=A（合理区间防呆、不锁 α）
depends_on: []
---

# R23 不确定性预测区间 + abstain + 覆盖定理命门

## Scope [必填]
补 GOAL §4 缺失的不确定性量化层（此前完全未实现）：① **split conformal**（分布无关有限样本边际覆盖）
② **CQR**（自适应宽度，模型无关接已算好分位预测）③ **ACI**（时序/漂移在线调 α 保长程覆盖）
④ **abstain**（样本不足/非有限/空集 → 诚实不给区间，绝不假区间）。**数学先行**（覆盖定理 + 推导），
覆盖率写成跨分布 MC 不变量（命门：覆盖掉到 1−α 以下即实现跑偏）。**不锁 α**（R23）。

## 治理（命门·结构钉死）[必填]
- **不锁 α（R23）**：alpha/target_alpha 全是调用方传参、**内部绝不硬编** 0.1/0.05（方法学松紧是用户那摊）。
- **abstain 不假绿灯**：ConformalInterval `__post_init__` 构造期拒矛盾态（未 abstain 却 NaN 边界 / abstain 却藏数值）；
  covers() 对 abstain/非有限 y 恒 False；**非 1D 输入亦 abstain**（防畸形数组「区间」逃出网）。
- **exchangeability 诚实披露**：split/CQR 覆盖依赖可交换、只保边际非条件覆盖；时序违反 → ACI/abstain（docstring + 残余）。
- **ACI 工程变体诚实标注**：raw α_t 递推 + clipped-level；长程覆盖**实测收敛**、不空引论文界。
- **披露面≤实现面**：abstain 触发清单收窄到已实现四类；相对宽/OOD 阈标 P2 消费侧旋钮（RULES §3）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/eval/conformal.py | 新建 | SplitConformalCalibrator + cqr_interval + AdaptiveConformalInference + ConformalInterval + _conformal_rank_quantile(手写秩) |
| app/eval/__init__.py | 导出 | additive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 秩 +1 校正写成 ⌈n(1−α)⌉ → 小 n 欠覆盖（sentinel：correct−buggy>0.02）。
2. **边际覆盖（命门）**：正态/重尾 t/偏态/异方差 多 seed MC → ≥1−α（分布无关）。
3. k>n 不 abstain → 欠覆盖 + 假区间（断言 n<⌈1/α⌉−1 必 abstain）。
4. CQR 符号反/取绝对值/max(·,0) → Q̂ 翻号 → 覆盖/自适应崩（mutant 三种全有牙）。
5. ACI 方向反 → 漏覆盖继续收窄（断言 err=1→α_t↓）；漂移下长程覆盖→1−α vs 固定 split 崩。
6. **非 1D 绕过 abstain 网**（评审 medium）→ 畸形数组区间；断言 2D 输入必 abstain。
7. abstain/非有限/空集/端点交叉 → 绝不返回数值区间冒充 ok（三态不假绿灯）。

## 验收一句话 [必填]
split/CQR/ACI + abstain 数学对齐覆盖定理、覆盖率 MC ≥1−α 跨分布、+1 校正 sentinel 有牙、ACI 漂移长程覆盖收敛、
非 1D/不可判定全 abstain、不锁 α；理论不变量 +9 守门；全量后端绿、基线不破。

## 完成记录（2026-06-24 · autonomous-loop / D-CONFORMAL-R23）
- **数学先行 + 并行思考**：落 `findings/dreaminate/conformal-intervals.md`（三法公式+覆盖定理+可证伪不变量）；
  codex(xhigh) 独立复核，修正 **ACI 长程界 (max{α₁,1−α₁}+γ)/(Tγ)** + **CQR Q̂ 可负/端点交叉 abstain** + **手写秩分位非 np.quantile**。
- **实现（扩展不替换）**：新建 `eval/conformal.py`——模型无关（接残差/分位预测）；abstain 三态；不锁 α；手写 conformal 秩。
- **对抗测试 + 命门**：`test_conformal_intervals.py` **25 passed** + 方法学不变量 **+9**（分布无关覆盖、+1 校正 sentinel、
  ACI 漂移长程覆盖收敛、单调嵌套、CQR 覆盖、ACI 递推恒等、不锁 α）。
- **实证亮点**：split 覆盖 normal/重尾/偏态/异方差全 ≈0.90 分布无关；**ACI 漂移下长程覆盖 0.901 vs 固定 split 0.542**；CQR Q̂ 可负收窄。
- **多透镜评审（autoplan 等价）**：confirmed_real 空（数学经 CEO/governance 独立复验全真、四命门达标）；
  修 1 条 correctness medium（**非 1D 绕过 abstain 网**）+ 低优清理全做（CQR max_width 对称旋钮 / `__post_init__` 拒矛盾态 /
  `to_dict` / 披露面收窄 / `_min_calib_for` 单一源 / docstring 措辞）。
- **验证**：全量后端 **1460 passed / 13 skipped / 0 failed**，基线 1453 未破。
- **诚实残余 → mint 卡 92a2182f**（应 CEO「未接线的另一半当 live 债追」）：消费侧接线（模型台/信号层预测附校准区间 + abstain UI 呈现，信任层 §6）。
- **land main 待用户授权**（不擅自 push/land）。
