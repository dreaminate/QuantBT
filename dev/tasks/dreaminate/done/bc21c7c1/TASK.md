---
uuid: bc21c7c169c243cb95d7380b5a6006a6
title: agent 窗口 Tauri 桌面挂载（一套组件两处挂载）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P3
area: desktop
source: interaction
source_ref: 2026-06-20 T-035 拆分（形态①一套两挂）
depends_on: [82120b9c60814566beea2d6b210ef31e]
---

# agent 窗口 Tauri 桌面挂载

## Scope [必填]
把 T-040 的 agent 窗口组件挂成 Tauri 桌面窗口（一套 React 组件两处挂载 = Web + 桌面，复用不重造）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/desktop/(src-tauri) | 桌面壳 | 挂载 T-040 窗口组件 |
| app/frontend/ | T-040 组件 | 复用（勿重造） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 桌面窗口与 Web 同组件、同行为：种"桌面路径绕治理门" → 必抓（沿用 T-029）。

## 验收一句话 [必填]
桌面窗口与 Web 行为一致、不绕治理门；不破基线。

## 实装说明 + 残余（epic cfb0fea9）
- 一套组件两挂：AgentWorkbenchPage 经 tauri.conf.json `index.html?view=agent-workbench` + main.tsx 桌面入口门改写路由复用同组件（同 router/权限三态/治理门，桌面不另起旁路）。前端半边全验证（tsc + 215 vitest + build + 对抗门真抓防开放重定向）。
- **残余（诚实，待工具链）**：`tauri dev`/`tauri build` 未跑——① `@tauri-apps/cli` 未装（需 npm install）② pre-existing `Cargo.toml [lib] name 无 src/lib.rs` 缺陷拦死构建（非本卡引入，已 spawn 修复任务）。装好工具链 + 修 Cargo 缺陷后真跑验证。leader 2026-06-22 self-review 置 1 + 落档（前端半边完成）。

## 残余已清（2026-06-22）
- T-042 桌面 tauri build 真跑通：cargo check ✅ + tauri build --debug ✅(47.76s)，产物落盘 quantbt-desktop(Mach-O arm64 34MB)+QuantBT.app+QuantBT_1.0.0_aarch64.dmg(10MB)；连环修 4 个 pre-existing Cargo/Tauri 缺陷(缺 lib.rs/feature 不匹配/缺图标/借用错误)。诚实：仅 aarch64-apple-darwin 本机原生，跨平台目标未产。
