---
uuid: 41ea6e357df24045ad4427f85afc1a7a
title: R4 CPCV（Combinatorial Purged CV）多路径回测 + 组合学/防泄露命门
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: eval-methodology
source: goal-gap
source_ref: GOAL §4「CPCV '更强默认' 双轨 walk-forward（R4）」+ 决策 R4=B
depends_on: []
---

# R4 CPCV 多路径回测 + 组合学/防泄露命门

## Scope [必填]
补 GOAL §4 R4 缺失的 CPCV（López de Prado AFML Ch.12），扩展 `models/purged_cv.py`（已有单路径 purged k-fold）：
N 个时间连续 group 每次选 k 个作 test（C(N,k) 组合，train 经 purge+embargo）→ 重组 **φ=C(N−1,k−1)** 条
「各覆盖全时间线一次」回测路径 → 单策略 OOS 性能**分布**（非单点），暴露过拟合方差。**数学先行**（φ 双计数证明 + path_matrix）。

## 治理（命门·结构钉死）[必填]
- **φ 路径 ≠ φ 策略**：单策略多路径分布**绝不**冒充策略数喂 PBO（单策略 PBO 恒 N/A）；多路径喂 DSR 取**保守分位** q05/min。
- **CPCV 真实市场未确立（R4=B）**：仅合成 Heston 占优 → 作 walk-forward 双轨稳健性证据、**绝不自动判赢**；
  `CPCV_REALWORLD_SUPERIORITY_ESTABLISHED=False` 常量 + 测试机器钉死（不仅 docstring 散文）。
- **purge 逐 test group 段判**（非全局 min..max，否则误删非连续 test group 中间合法 train）；embargo=AFML（test 后）。
- **不假绿灯**：饿死/未覆盖路径记 NaN 剔除 + n_paths_dropped **可见**，**绝不**伪造 0.0 污染保守分位；
  C(N,k) 爆炸预检 raise **绝不静默采样**；分布 dict 形状对称（insufficient 也带全 key=NaN）。
- **CPCV 只隔离索引**：preprocessing 须每折内 fit（R5 用法 caveat）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/models/cpcv.py | 新建 | cpcv_splits + build_path_matrix + assemble_cpcv_paths + cpcv_metric_distribution + n_cpcv_paths/n_cpcv_combinations + caveat 常量 |
| app/models/purged_cv.py | 复用 t1-purge 口径/FoldSplit | 不改 |
| app/models/__init__.py | 再导出（同 purged_cv 惯例） | additive |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 组合数≠C(N,k)/路径数≠C(N−1,k−1)/k·C(N,k)%N≠0（golden N=4,k=2 path_matrix 逐元素）。
2. 每路径覆盖每样本恰一次 + **来源==path_matrix[g,p]**（填组合 id，防 φ 路径坍缩成 path0）。
3. purge 无泄露 sentinel（不 purge 必泄露）+ 逐段 vs 全局（非连续 test group 中间合法 train 保留）。
4. embargo **AFML 单侧**（test 后剔、test 前保留；搞成两侧/置零必抓）。
5. 命门：单策略 φ 路径不产 PBO；饿死路径不伪造 0.0（记 NaN + n_paths_dropped 可见）；insufficient dict 形状对称。
6. C(N,k) 爆炸 raise（splits + build_path_matrix）；边界拒；负 embargo 拒；per_combo 长度错拒。

## 验收一句话 [必填]
CPCV splits+路径重建+分布数学对齐理论、φ/覆盖/逐段 purge/embargo 方向不变量守门、PBO 红线 + 饿死路径不假 0、
爆炸/边界拒、R4 caveat 机器钉死；全量后端绿、基线不破。

## 完成记录（2026-06-24 · autonomous-loop / D-CPCV-R4）
- **数学先行 + 并行思考**：落 `findings/dreaminate/cpcv.md`（φ=C(N−1,k−1) 双计数证明 + golden path_matrix + 命门）；
  codex(xhigh) 复核，确认 φ 恒等/路径重建，加固 **purge 逐段非全局** + **PBO 路径≠策略红线** + embargo 语义。
- **实现（扩展不替换）**：`models/cpcv.py` 复用 purged_cv t1-purge；爆炸预检 raise；多路径分布给保守分位。
- **对抗测试 + 命门**：`test_cpcv.py` **22 passed** + 方法学不变量 **+4**（φ 恒等/occurrence 双射/覆盖来源/逐段 purge sentinel）。
- **多透镜评审（autoplan 等价 4 透镜 + 对抗复核，14 agents）**：数学核心经 4 透镜独立复跑全真、对抗测试有真牙；
  修 confirmed：**饿死路径假 0.0 污染保守分位（medium·命门后门）** + insufficient dict 形状不对称 + 路径来源区分牙 +
  embargo 方向零测试 + low 清理（build_path_matrix 护栏/负 embargo/死 import/per_combo 长度/__init__ 再导出/caveat 机器钉死）。
- **实证亮点**：φ 恒等全对 N=3..12；golden path_matrix 精确；purge 0 泄露 vs 不 purge 120；饿死路径记 NaN 不污染 min。
- **验证**：全量后端 **1487 passed / 13 skipped / 0 failed**，基线 1478 未破。mint **P2 卡 861182e6**（接 promote/overfit gate + cv_scheme 双轨 report，应 CEO「价值闭环未合拢」）。
- **land main 待用户授权**（不擅自 push/land）。
