---
uuid: 51271d38be32499a9ec2c65cde53815a
title: 因子台三纯库+挖掘 后端 — 信号契约 + ML/DL 登记 + 暴力遍历守门引擎
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: backend
source: interaction
source_ref: 2026-06-21 F1=B 走 (b) 的后端支撑（R16/R17 实装）
depends_on: [a11e2aa5ea0143c5bfca9204a921e516]
---

# 因子台三纯库+挖掘 后端 — 信号契约 + ML/DL 登记 + 暴力遍历守门引擎

## Scope [必填]
F3 前端两骨干的后端支撑：① 信号契约（R17 两层解耦：DL/ML 本体进模型注册表、输出登记为「信号」进因子库的契约 schema + 端点）；② 三纯库分库注册端点（算术/ML/DL 纯净）；③ 暴力遍历挖掘引擎（R16：生成器/守门器严格解耦，守门指标绝不进生成 fitness，诚实-N 守门，复用 lineage 一本账）。复用现有 `factor_factory`（算术库已建）+ `lineage/ledger.py`（T-013 诚实-N）。**不做**：ML/DL 真训练（Model台）、前端（F3）。

## 上下文 / 动机 [按需]
GOAL §3 因子轨终态：三纯库纯净 + DL/ML 输出经信号契约进因子库（R17，锚 Qlib/MLflow/Feast 概念）+ 暴力遍历=诚实-N 守门人（R16，生成/守门解耦）。现状（factorDeck 勘查）：factor_factory 算术库已建，ML/DL→信号契约、挖掘引擎守门均未建。本卡补这层后端，F3 前端从 mock 切真。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/factor_factory/signal_contract.py | 新建 | ML/DL 输出→信号契约登记（两层解耦，本体不入因子库）|
| app/backend/app/factor_factory/mining.py | 新建 | 暴力遍历挖掘引擎：生成器/守门器解耦，守门指标不进 fitness |
| app/backend/app/main.py | factor 端点群（~L422-440） | 加 三纯库注册 / 信号契约登记 / 挖掘任务 端点（扩展不替换现有 3 个 factor 路由）|
| app/backend/app/lineage/ledger.py | append/list_entries | 挖掘候选诚实-N 计数复用一本账（不重造）|

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「POST 把 .pt 模型本体注册进因子库」→ 端点必拒（范畴错误，R17：本体进模型注册表，只信号入库）。变异要杀：因子注册端点接受 model blob。
2. 种「挖掘引擎把守门指标（IC/DSR/PBO）传入生成器 fitness」→ 必抓：生成器接口不得见守门指标（架构隔离，R16）。变异要杀：生成器函数签名混入守门 score。
3. 种「等价公式批量挖掘绕诚实-N 计数」→ 必抓：N_eff 经 ledger 一本账、收益聚类去重（沿用 T-015），不可手动改小。
4. 种「信号契约登记跳过血统/泄露门」→ 必抓（不削弱治理）。

## 复用 [按需]
现有 `factor_factory`（算术库 + operators + lifecycle）；`lineage/ledger.py`（T-013 诚实-N 一本账）；T-015 等价写法收益聚类；现有 factor 路由范式。

## 红线 [按需]
守门指标不进生成 fitness（生成/守门解耦=架构红线，R16）；.pt 本体不入因子库（R17 范畴红线）；诚实-N 一本账复用不重造、不可手动改小；信号契约不削弱泄露/血统门。

## 非目标 [按需]
ML/DL 真训练（Model台 M1/M2）；前端（F3）；audit 方法学（F2 待拍）。

## Open Questions（已决 2/2）[按需]
- [已决] 信号契约 schema 由 leader 走 (b) 设计：概念锚 Qlib/MLflow/Feast，落地为本项目 factor_factory 内两层（模型注册表本体 ↔ 因子库信号），不强绑某框架。
- [已决] 挖掘引擎生成器/守门器可同进程，但守门指标接口隔离（生成器签名不得见守门 score），诚实-N 复用 T-013 ledger。

## 验收一句话 [必填]
种「.pt 入因子库 / 守门指标进 fitness / 等价公式绕诚实-N / 信号契约跳门」四类坏 → 端点门必抓；不破现有 factor_factory 与 lineage 测试基线。
