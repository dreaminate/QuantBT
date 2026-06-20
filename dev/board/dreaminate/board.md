# BOARD · dreaminate 的工作板（生成 · 勿手改 · 跑 build_board.py 刷新）

> 只含 **dreaminate** 名下 active 卡（从 tasks/dreaminate/ 现生成）。**导航 only，实时依据看卡原文 + 对应代码。**

| uuid8 | 标题 | status | area | 优先级 | 依赖(uuid8) |
|---|---|---|---|---|---|
| 05d6f511 | 单人 self-approve 仅非真钱通道(冷却+留痕)，真钱硬双人 | todo | approval | P2 | - |
| 180a341e | 核验 agent tool_call 前端派发是否旁路受控翻译门（R11 前端缺口审计） | todo | verification | P1 | - |
| 381b6c18 | 实盘因子血统门——未过检验因子上真钱线 → 警告+知情确认 | todo | security-invariant | P1 | - |
| 3f5ed0b8 | agent 客户端窗口 epic(仿 Claude Code)——权限模式切换 + 工具可视化 + 审批弹窗 | todo | frontend-epic | P2 | edc1e326 |
| 6403b9bf | 诚实残余核验——监控尾部闭环 + 组合层三角 + D2 四残余 | todo | verification | P1 | - |
| 6e4eee54 | 入口×必经门覆盖矩阵回归 + 所有 venue 经 OrderGuard.wrap 的 CI 静态检查 | todo | security-invariant | P1 | - |
| 8ab894cd | 审批 SLA 与 leverage_cap 可配置；杠杆不设硬上限；真钱超时永远 default_reject | todo | config | P2 | - |
| c631817e | 防绿灯错觉——三角裁决按权限模式分层呈现 + 工具真实状态标注 | todo | governance-ui | P1 | - |
| ecbd0eab | GOAL §7 文档对齐(M10 已接 run 闸门)+ 可证伪性/模式 教学文案 | todo | docs | P2 | - |
| edc1e326 | 主对话入口接 AgentRuntime + 无副作用工具 + 权限三态(ask/auto/bypass) | todo | agent | P1 | 180a341e |
