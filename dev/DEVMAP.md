# DEVMAP · 全局任务导航（生成 · 勿手改 · 跑 build_dev_map.py 刷新）

> 谁拿了哪些卡 + 在哪步 + 什么功能。**只定位；实时依据永远是卡原文 + 对应代码。**

## dreaminate · leader

| uuid8 | 标题 | status | area | 位置 |
|---|---|---|---|---|
| 05d6f511 | 单人 self-approve 仅非真钱通道(冷却+留痕)，真钱硬双人 | done | approval | done |
| 180a341e | 核验 agent tool_call 前端派发是否旁路受控翻译门（R11 前端缺口审计） | done | verification | done |
| 381b6c18 | 实盘因子血统门——未过检验因子上真钱线 → 警告+知情确认 | done | security-invariant | done |
| 3bb62d7d | 无副作用业务工具接真引擎（agent 一句话真跑回测）——T-027 残余 | done | agent | done |
| 3d95e0f6 | agent 窗口弹窗 + 教学文案（整合 T-028/T-032/T-034 前端残余） | done | frontend | done |
| 3f5ed0b8 | agent 客户端窗口 epic(仿 Claude Code)——权限模式切换 + 工具可视化 + 审批弹窗 | done | frontend-epic | done |
| 4562d903 | Model台后端接线 — JobDetail/IoSpec/walkforward/promote字段/图codegen/研究判定 | done | backend | done |
| 51271d38 | 因子台三纯库+挖掘 后端 — 信号契约 + ML/DL 登记 + 暴力遍历守门引擎 | done | backend | done |
| 5e47b82f | 因子台前端 P0 — 5 视图像素还原 + mock(库/相关/评测/构建DSL/研究) | done | frontend | done |
| 6403b9bf | 诚实残余核验——监控尾部闭环 + 组合层三角 + D2 四残余 | done | verification | done |
| 6e4eee54 | 入口×必经门覆盖矩阵回归 + 所有 venue 经 OrderGuard.wrap 的 CI 静态检查 | done | security-invariant | done |
| 79ebe273 | 模拟台后端接线 — /api/paper/* 整层 + 晋级审批门 + 风险门冻结哈希链 | done | backend | done |
| 82120b9c | agent 窗口前端核心（Web）——对话流 + 工具可视化 + 权限模式切换 | done | frontend | done |
| 8ab894cd | 审批 SLA 与 leverage_cap 可配置；杠杆不设硬上限；真钱超时永远 default_reject | done | config | done |
| 9d5405ce | 模拟台前端 P0 — 5 视图 + PaperBoardCard(运行/持仓成交/风险门/复盘/晋升) | done | frontend | done |
| 9fd4f1a6 | 策略台后端接线 — validate/版本/策略级fork/Live只读 端点 + 前端接真 | done | backend | done |
| T-001 | T-001 | ? | - | done |
| T-012 | T-012 | ? | - | done |
| T-013 | T-013 | ? | - | done |
| T-014 | T-014 | ? | - | done |
| T-015 | T-015 | ? | - | done |
| T-016 | T-016 | ? | - | done |
| T-017 | T-017 | ? | - | done |
| T-018 | T-018 | ? | - | done |
| T-019 | T-019 | ? | - | done |
| T-020 | T-020 | ? | - | done |
| T-021 | T-021 | ? | - | done |
| T-022 | T-022 | ? | - | done |
| T-023 | T-023 | ? | - | done |
| T-024 | T-024 | ? | - | done |
| T-025 | T-025 | ? | - | done |
| a11e2aa5 | 因子台三纯库 + 暴力遍历挖掘 — 前端设计+实装（GOAL §3，无 handoff 稿，D-DESK-EPIC F1=B 路 b） | done | frontend | done |
| a75c4beb | Agent 窗口产物工作区 — 8 产物卡 + Strategy.yaml + Report.md | done | frontend | done |
| b106177f | 因子台后端接线 — 暴露已有 compute + 相关性/分层回测 + alpha审查 | done | backend | done |
| b2682edc | Model台前端 P0 — 4 子台像素还原 + mock(作业/注册表/构建draw.io/研究) | done | frontend | done |
| b961f08b | Agent 后端工具补全 — 4 schema+handler + stream 结构化事件 + handoff | done | agent | done |
| b9af7c82 | 共享画布引擎 — GraphCanvas / NodeCard / EdgeLayer / MiniMap（pan·zoom·连线·框选） | done | frontend-foundation | done |
| bc21c7c1 | agent 窗口 Tauri 桌面挂载（一套组件两处挂载） | done | desktop | done |
| be3dc598 | 策略台前端 P0 — DAG 编排工作台像素还原 + mock 交互 | done | frontend | done |
| c631817e | 防绿灯错觉——三角裁决按权限模式分层呈现 + 工具真实状态标注 | done | governance-ui | done |
| ca3ab3ec | Agent 窗口里程碑进度线 + 跨台台 switcher | done | frontend | done |
| cfb0fea9 | 整套台前端实装 epic（Claude Design handoff → React，DC→React 治理界面投影） | done | frontend-epic | done |
| d11d1426 | 暗色台地基 — desk 壳件 + design tokens + per-desk accent + 路由边界 | done | frontend-foundation | done |
| d41b167d | Agent 窗口 D-PERM 反例 UI + self-approve 二次确认 | done | frontend | done |
| d5ea778c | 共享 Agent 对话 + Inspector + Dock 组件 | done | frontend-foundation | done |
| d93dc5a0 | 裁决卡 RunVerdictCard + 回测详情顶栏/血缘入口（非冻结） | done | frontend | done |
| e069d820 | 裁决卡后端接线 — verdict/overfit/cost-sensitivity/promote/热力 端点 + 措辞合规 | done | backend | done |
| e2de3d32 | 前端测试设施基建 — vitest + React Testing Library + 对抗测试 harness | done | frontend-foundation | done |
| ecbd0eab | GOAL §7 文档对齐(M10 已接 run 闸门)+ 可证伪性/模式 教学文案 | done | docs | done |
| edc1e326 | 主对话入口接 AgentRuntime + 无副作用工具 + 权限三态(ask/auto/bypass) | done | agent | done |

## pool · 待分配

| uuid8 | 标题 | status | area |
|---|---|---|---|
| 3a8b2360 | R28 全库双时态（known_at 轴 + as-of 重述基本面）（T-033 核验 gap） | todo | 数据 |
| 46f1cb3c | 组合层 M8 多证据三角守门（T-033 核验 gap 升级） | todo | portfolio |
| 87ad21fc | R18 stacking 控制项 N/A 标注 + 实现时 OOF 约束（T-033 核验 gap） | todo | signals |
| d0e5d208 | 监控→自动降级/退役/问责 尾部闭环接线（T-033 核验 gap 升级） | todo | monitor |

## 按 area 功能索引

| area | 卡(uuid8 · status) | developer |
|---|---|---|
| - | T-001 · ? | dreaminate |
| - | T-012 · ? | dreaminate |
| - | T-013 · ? | dreaminate |
| - | T-014 · ? | dreaminate |
| - | T-015 · ? | dreaminate |
| - | T-016 · ? | dreaminate |
| - | T-017 · ? | dreaminate |
| - | T-018 · ? | dreaminate |
| - | T-019 · ? | dreaminate |
| - | T-020 · ? | dreaminate |
| - | T-021 · ? | dreaminate |
| - | T-022 · ? | dreaminate |
| - | T-023 · ? | dreaminate |
| - | T-024 · ? | dreaminate |
| - | T-025 · ? | dreaminate |
| agent | 3bb62d7d · done | dreaminate |
| agent | b961f08b · done | dreaminate |
| agent | edc1e326 · done | dreaminate |
| approval | 05d6f511 · done | dreaminate |
| backend | 4562d903 · done | dreaminate |
| backend | 51271d38 · done | dreaminate |
| backend | 79ebe273 · done | dreaminate |
| backend | 9fd4f1a6 · done | dreaminate |
| backend | b106177f · done | dreaminate |
| backend | e069d820 · done | dreaminate |
| config | 8ab894cd · done | dreaminate |
| desktop | bc21c7c1 · done | dreaminate |
| docs | ecbd0eab · done | dreaminate |
| frontend | 3d95e0f6 · done | dreaminate |
| frontend | 5e47b82f · done | dreaminate |
| frontend | 82120b9c · done | dreaminate |
| frontend | 9d5405ce · done | dreaminate |
| frontend | a11e2aa5 · done | dreaminate |
| frontend | a75c4beb · done | dreaminate |
| frontend | b2682edc · done | dreaminate |
| frontend | be3dc598 · done | dreaminate |
| frontend | ca3ab3ec · done | dreaminate |
| frontend | d41b167d · done | dreaminate |
| frontend | d93dc5a0 · done | dreaminate |
| frontend-epic | 3f5ed0b8 · done | dreaminate |
| frontend-epic | cfb0fea9 · done | dreaminate |
| frontend-foundation | b9af7c82 · done | dreaminate |
| frontend-foundation | d11d1426 · done | dreaminate |
| frontend-foundation | d5ea778c · done | dreaminate |
| frontend-foundation | e2de3d32 · done | dreaminate |
| governance-ui | c631817e · done | dreaminate |
| security-invariant | 381b6c18 · done | dreaminate |
| security-invariant | 6e4eee54 · done | dreaminate |
| verification | 180a341e · done | dreaminate |
| verification | 6403b9bf · done | dreaminate |
