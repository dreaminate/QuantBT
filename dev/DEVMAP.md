# DEVMAP · 全局任务导航（生成 · 勿手改 · 跑 build_dev_map.py 刷新）

> 谁拿了哪些卡 + 在哪步 + 什么功能。**只定位；实时依据永远是卡原文 + 对应代码。**

## dreaminate · leader

| uuid8 | 标题 | status | area | 位置 |
|---|---|---|---|---|
| 3f5ed0b8 | agent 客户端窗口 epic(仿 Claude Code)——权限模式切换 + 工具可视化 + 审批弹窗 | todo | frontend-epic | active |
| 05d6f511 | 单人 self-approve 仅非真钱通道(冷却+留痕)，真钱硬双人 | done | approval | done |
| 180a341e | 核验 agent tool_call 前端派发是否旁路受控翻译门（R11 前端缺口审计） | done | verification | done |
| 381b6c18 | 实盘因子血统门——未过检验因子上真钱线 → 警告+知情确认 | done | security-invariant | done |
| 6403b9bf | 诚实残余核验——监控尾部闭环 + 组合层三角 + D2 四残余 | done | verification | done |
| 6e4eee54 | 入口×必经门覆盖矩阵回归 + 所有 venue 经 OrderGuard.wrap 的 CI 静态检查 | done | security-invariant | done |
| 8ab894cd | 审批 SLA 与 leverage_cap 可配置；杠杆不设硬上限；真钱超时永远 default_reject | done | config | done |
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
| c631817e | 防绿灯错觉——三角裁决按权限模式分层呈现 + 工具真实状态标注 | done | governance-ui | done |
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
| agent | edc1e326 · done | dreaminate |
| approval | 05d6f511 · done | dreaminate |
| config | 8ab894cd · done | dreaminate |
| docs | ecbd0eab · done | dreaminate |
| frontend-epic | 3f5ed0b8 · todo | dreaminate |
| governance-ui | c631817e · done | dreaminate |
| security-invariant | 381b6c18 · done | dreaminate |
| security-invariant | 6e4eee54 · done | dreaminate |
| verification | 180a341e · done | dreaminate |
| verification | 6403b9bf · done | dreaminate |
