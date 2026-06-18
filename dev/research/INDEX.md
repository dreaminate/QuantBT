# 研究台 · INDEX（指针，read-on-demand）

研究归研究。重资料归档在 `archive/`，**按需读、不默认加载**（瘦身：活跃面不背它们）。

## 溯源总表
- `TRACE.md` · **GOAL 每节 ↔ 文献(dossier) ↔ 结论(finding) ↔ 决策(R) ↔ 任务(T)** 单一视图 + 收口覆盖率体检。

## 当前权威研究
- `archive/dossiers/01-36` · **36 环节前沿研究 dossier**（读时**先看 §7 对抗核查**，§5 乐观推荐按 §7 打折）— 见 `dossiers/README.md`
- `findings/spine-designs/00-07` · **脊柱 7 部件 build-ready 设计** + `00` 跨部件契约/测试真实性复核
- `../DECISIONS.md` · 由研究产出并经用户拍板的 R1–R29 / S1–S4

## 历史（已被上面取代，仅留档）
- `archive/blueprint/` · 早期 40-agent 研究蓝图（01-08, 99）—— 被 dossiers + DECISIONS 取代
- `archive/plans/` · agent-os 技术架构早期设计（已被 dossiers + spine-designs 取代，仅留档）
  - 注：v2 数据平台 / v3 训练台等**项目设计文档**（被项目代码引用为设计规格）已归位 `../../docs/plans/`——项目侧，非开发脚手架
- `archive/survey/` · 早期平台调研 + 全栈量化平台研究报告
- `archive/codex/` · 旧 Codex 协作知识/规则（要点已并入 `../RULES.md`）
- `archive/roadmap/` · 旧路线图（被 `../STATE.md` + `../tasks/BOARD.md` 取代）
- `archive/QuantBT-GOAL.original.md` · 原始 1680 行 GOAL（被蒸馏的 `../GOAL.md` 取代）

## 在研 / 创新入口（探索自由区）
- `ideas/` · 论文研读笔记 / 原创架构 RFC / 猜想——**还没成熟到能录任务**的先落这里（不挡、不计 honest-N）。
- `active/<topic>/` · 正在深挖的研究线程（镜像 `../tasks/active`），带工作日志。

## 研究生命周期 → 任务
`ideas/`（灵感·RFC·论文笔记）→ `active/<topic>/`（在研深挖）→ `findings/`（build-ready 设计 §4 接线 + §5 对抗）→ `../tasks/BOARD.md`（T-xxx）。
一旦要「下注」（影响产品 / 治理）才进治理漏斗（假设卡 / 三角 gate）；探索期自由（如 spine-designs → T-013..T-020）。
