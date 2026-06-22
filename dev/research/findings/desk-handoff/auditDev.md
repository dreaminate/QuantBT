I now have everything needed for the structured audit. The "策略台" is the user's design-draft name for the same governance UI that the dev/ tracks under the agent-window epic (T-035 / 3f5ed0b8) and the M15 "治理新页面". No card is literally titled "策略台/StrategyConsole", but four active cards cover its elements, plus the M15 evidence-drilldown page is an open GOAL §6 gap.

---

# 流程审查报告 · 策略台 / agent 治理窗口实装

## 1. 我是谁

- **developer_id**：`dreaminate`（`dev/.identity`，本机不入库）。
- **role**：**leader**（`dev/TEAM.md` 唯一一行，role=leader，说明"项目发起人；唯一 leader；可分配 + 可 land"）。
- **能不能自己 land？** **能。** 按 `RULES.md §8` 与 `TEAM.md` 权限语义：只有 leader/admin 能 ① 分配（卡从 `tasks/pool/` 移到 `tasks/{developer_id}/`）② **land（合并进 main + 合并 decisions/issues 全局账）**。你是唯一 leader，分配权与 land 权都在你手上——这是个单人团队，你既是开卡人也是 land 人。

## 2. 有没有"策略台"的卡

**结论**：没有任何卡的标题字面是"策略台 / StrategyConsole / 治理页"（grep `dev/tasks/` 0 命中）。但"策略台设计稿"描述的治理 UI 元素，dev/ 是用**另一套命名**追踪的——agent 窗口 epic（仿 Claude Code）+ M15 治理新页面。命中的卡如下：

**A. agent 窗口 epic（活跃，覆盖对话流/工具可视化/权限模式/审批弹窗）**

| uuid8 | 标题 | status | area | 依赖 |
|---|---|---|---|---|
| 3f5ed0b8 | agent 客户端窗口 epic（仿 Claude Code）——权限模式切换 + 工具可视化 + 审批弹窗 | **done**（epic 占位，已拆子卡）| frontend-epic | — |
| 82120b9c (T-040) | agent 窗口前端核心（Web）——对话流 + 工具可视化 + 权限模式切换 | **todo** | frontend | edc1e326 |
| 3d95e0f6 (T-041) | agent 窗口弹窗 + 教学文案（审批/血统警告/red 裁决 + 知情确认）| **todo** | frontend | 82120b9c |
| bc21c7c1 (T-042) | agent 窗口 Tauri 桌面挂载（一套组件两处挂载）| **todo** | desktop | 82120b9c |
| 3bb62d7d (T-043) | 无副作用业务工具接真引擎（agent 一句话真跑回测）——T-027 残余 | **todo** | agent | edc1e326 |
| edc1e326 | 主对话入口接 AgentRuntime + 无副作用工具 + 权限三态(ask/auto/bypass) | **done** | agent | — |

**B. M15 治理新页面（证据下钻 L1–L4）——这是与"策略台"最贴近的、尚无专卡的 GOAL gap**
- `state.md` 子系统表 M15 行："层1 ✅ RunDetailPage 冻结 / 层2 ⬜ **治理新页面（证据下钻 L1–L4）未加** → 信任层 §6"。
- 这一条**目前没有对应任务卡**（不在 dreaminate active、不在 pool）。"策略台"设计稿若含 Live 只读/版本/runtime 的证据下钻面板，落到这一格上是**空的**。

**C. pool 待分配卡**：4 张（3a8b2360 双时态 / 46f1cb3c 组合三角 / 87ad21fc stacking OOF / d0e5d208 监控闭环），**与策略台前端无关**，全是层2 治理后端 gap。

## 3. GOAL 对应（设计稿治理元素 → 验收点）

策略台设计稿的治理元素逐一钉到 GOAL / DECISIONS：

| 设计稿元素 | GOAL 验收锚点 | 决策锚点 |
|---|---|---|
| **Live 只读**（实盘态不可在台上随手动钱）| §2 治理脊柱"安全 deny-by-default + 交易所侧硬墙"；§5"A股 live 下单永远拒、加密 live 须 SafeKey+testnet+ladder+killswitch" | **D-PERM**"默认止于模拟盘，实盘是郑重显式独立确认，agent 绝不把直接实盘作默认"；`RULES.project` 下单唯一入口经 OrderGuard |
| **Fork**（从某 run/checkpoint 派生）| §2"durable checkpoint / replay / **fork** / rollback"；§7 M13 确定性内核 | 脊柱 01 内核（T-014/T-023 已建并接线，state 脊柱表 ✅）|
| **kill（急停）**| §5"kill switch 分级"；§7 M9 killswitch | **D-T025**"平仓本体 fail-open（门坏也要能救命平仓）+ trigger 端点 IP+密码二次鉴权"（T-025 已建）|
| **validate（独立验证 / 三角门）**| §2"异模型验证官（R7）"；§4"多证据三角 DSR/PBO/bootstrap 同向才放行"；§6"闸门对所有人一套最严" | R7 / R2；T-012 验证官 + T-015 三角 gate（已接进 run）|
| **version（实验/模型版本 + 谱系）**| §2"PROV 谱系总线 + honest-N 一本账"；§7 M12"append-only + lineage + promote 审批门" | R8/R9；`lineage/ids.py` 单一身份源（`RULES.project` 锚点）；T-019 promote 审批门 |
| **runtime（权限三态 + 工具可视化）**| §2"LLM 永在节点内绝不当控制器（R11）"；§7 M14 受控 LLM 触手 | **D-PERM**"权限轴⟂治理轴：三态只调 agent 停不停下问你，绝不调治理门执不执行；bypass 只跳确认 UI、不跳治理门、真钱命门 bypass 也拦" |
| **弱点/血统/red 一等呈现**（设计稿默认展开） | §6 信任层"L1–L4 渐进披露、闸门一套最严、**弱点风险一律一等呈现绝不淡化**（R25）" | R25 / R27（个性化只动呈现层）；**D-PROVENANCE** 实盘因子血统门=警告+知情确认（T-034 残余在 3d95e0f6）|

**核心对应**：策略台 ≈ GOAL **§7 M15"治理新页面"** 的落地形态 + **§6 信任层**的呈现规约，runtime/权限部分落在 **§2 + D-PERM**。它不是新治理逻辑，而是把已建的脊柱（验证官/三角门/审批门/血统门/killswitch/内核 fork）**呈现到一个面板上**——治理逻辑全在后端、台只是 UI 投影。

## 4. 流程判定：先开卡，还是已授权直接实装？

**判定：(a) 大部分已经有卡、必须走卡流程；但"策略台"作为一个统合面板若超出现有四卡 scope，需要先补卡 / 确认归属——不能直接动手实装一个无卡的新页面。**

依据：
- `RULES.md §4`（工程红线）："改现有文件**扩展不替换**"、"按模板/格式骨架填"、"**不擅自 commit/push——用户明说才提交**"。
- `HANDOFF.md` 第 4–6 步：取卡 → 进实现的硬前置是"**review_status=1 且 待拍=0**"；干完要落档 `tasks/{你}/done/<uuid8>/` + 刷 state + log + 跑 build/validate 脚本。
- **当前四张前端/agent 卡 `review_status` 全是 0**（82120b9c / 3d95e0f6 / bc21c7c1 / 3bb62d7d frontmatter 均 `review_status: 0`）。按 HANDOFF"进实现须 review_status=1"，**这四卡此刻都还卡在前置闸门、不能进实现**——需要你（leader）先 self-review 把 0→1。
- `RULES.md §7`（拍板纪律）：epic 3f5ed0b8 已记"3 形态项已决"，但**工程取舍四面**（一套组件两挂的技术路线、台 vs 窗口的边界）若设计稿引入新岔路，须逐一详解后停下等拍板，清零才进实现。

**就"把 handoff 设计稿实装成前端页面"这个动作**：
- 若设计稿 = 现有四卡 scope 内（对话流 + 工具可视化 + 权限切换 + 审批/血统/red 弹窗 + Tauri 挂载）→ **不需新开卡**，但需 ①self-review review_status 0→1 ②确认无新工程取舍待拍。
- 若设计稿含 **M15 证据下钻 L1–L4 治理面板**（state 标 ⬜ 未加、无卡）→ 这是**新 scope，必须先 mint uuid 开卡**（三晋升源之一 = developer×claude 交互 → 入 `tasks/pool/` 或直接 leader 自分配到 `tasks/dreaminate/`），不能无卡实装。
- **"用户已明确授权直接实装"在 dev/ 里没有书面凭据**——我没有看到任何 decision / state 记录授权跳过开卡流程。除非你在本次对话里明确说"授权直接实装"，否则默认走卡流程。这是 §7 前置闸门 + §4"不擅自"的合流。

**land 由谁做**：**你自己**（leader 是唯一有 land 权的人）。实装完成、对抗测试绿、不破基线后，由你执行 land（合并 main + 合并全局账）。

## 5. 风险 / 红线

实装策略台前端，**可能踩到的 `RULES.project` 红线 + 致命错误清单**：

1. **RunDetailPage 冻结（项目红线第 1 条）**：`frontend-run-detail/src/pages/RunDetailPage.tsx`「收益概述」页**冻结，只可排版/显示逻辑/加字段**。也是 GOAL §0"唯一原硬约束"。
   - 风险：策略台若复用或嵌入 RunDetailPage 的证据下钻，**绝不能改其交互/逻辑**，只能加字段/排版。M15"治理新页面"明确是**新页面**而非改冻结页——实装时必须新建组件，不动 RunDetailPage。

2. **权限轴 ⟂ 治理轴（D-PERM 核心不变量）**：UI 的 ask/auto/bypass 切换**只能调 agent 停不停下问你，绝不能让 bypass 跳过任何治理门**（OrderGuard/审批门/过拟合门/血统门）。
   - 风险：前端实装权限切换时，若把"bypass"误接成"跳过后端治理校验"=**削弱安全不变量 → `RULES.md §5` 致命错误即停工**。四卡的对抗测试 1（"窗口直调真钱/晋级端点跳门 → 必抓"，沿用 T-029 入口×门矩阵）就是钉这个。

3. **默认止于模拟盘（D-PERM，用户 2026-06-20 纠正）**：台的默认路径**绝不能把"直接实盘"作默认或自动导向**，即便 bypass。Live 只读 + 实盘须独立郑重确认。
   - 风险：策略台"Live"面板若做成一键上实盘 = 违 D-PERM + GOAL §5 live ladder 不可跳级。卡 82120b9c 对抗测试 3"窗口默认建议直接上实盘 → 抓"守此。

4. **弱点一等呈现不淡化（R25 / D-PERM R25 呈现分层）**：red/真钱/血统治理弱点**默认展开、绝不渲染成绿/可信、绝不折叠藏起**。
   - 风险：UI 为"好看/简洁"把弱点折叠或染绿 = 违 R25（= 产品"不给小白假绿灯"原则掉枪口对准自己，也是 `state` 诚实纪律）。卡对抗测试 2 守此。

5. **下单唯一入口 / 安全不变量（RULES.project + §5 致命错误）**：实盘 key 不进 LLM、杠杆护栏接所有路径（含中继/桥 M17）、任何 `place_order` 必经 OrderGuard、新增端点/venue 禁裸调 place_order。
   - 风险：策略台 Tauri 桌面挂载（bc21c7c1）若**桌面路径绕治理门** = 致命。卡对抗测试明确"桌面路径绕治理门 → 必抓（沿用 T-029）"。

6. **文案不改后端行为（卡 3d95e0f6 对抗测试 2）**：教学文案（可证伪 409 引导句 / market_mode / paper 文案）**只动前端呈现层，不得误改后端 409 阈值或血统判定**（D-T024-FALS"硬透明+软决定"、falsifiability.py 88–101 软挡不动）。

**总判**：策略台是**纯呈现层投影**，治理逻辑全在已建后端脊柱——只要严守"权限轴⟂治理轴 + 弱点一等呈现 + 不动 RunDetailPage + 桌面不绕门 + 文案不改行为"，不触 §5 致命错误。最大的流程风险不是红线，而是**四卡 review_status 仍为 0（未过前置闸门）+ M15 证据下钻面板无卡**——直接实装会跳过 HANDOFF 第 4 步的硬前置。

---

**给 leader 的下一步（你拍板）**：
1. 确认"策略台" = 现有 agent 窗口四卡 scope，还是含 M15 证据下钻新面板？后者需**新开卡**。
2. 若走现有四卡：先 self-review 把 82120b9c→3d95e0f6→bc21c7c1→3bb62d7d 的 `review_status` 0→1（注意依赖序：先 82120b9c），确认无新工程取舍待拍，再进实现。
3. land 全程由你执行。

**关键文件**（绝对路径）：
- `/Users/wzy/Work/01_Projects/QuantBT/dev/tasks/dreaminate/82120b9c/TASK.md`（前端核心，P2，review_status=0）
- `/Users/wzy/Work/01_Projects/QuantBT/dev/tasks/dreaminate/3d95e0f6/TASK.md`（弹窗+文案）
- `/Users/wzy/Work/01_Projects/QuantBT/dev/tasks/dreaminate/bc21c7c1/TASK.md`（Tauri 桌面挂载）
- `/Users/wzy/Work/01_Projects/QuantBT/dev/tasks/dreaminate/3bb62d7d/TASK.md`（工具接真引擎，P1）
- `/Users/wzy/Work/01_Projects/QuantBT/dev/tasks/dreaminate/done/3f5ed0b8/TASK.md`（epic 母卡 + 子卡映射 T-040~T-043）
- `/Users/wzy/Work/01_Projects/QuantBT/dev/GOAL.md` §2/§6/§7（M15 治理新页面 = state 标 ⬜ 未加，无卡）
- `/Users/wzy/Work/01_Projects/QuantBT/dev/decisions/dreaminate/DECISIONS.md`（D-PERM 行 169-177 / D-PROVENANCE 192-195 / D-T025 136-140）
- `/Users/wzy/Work/01_Projects/QuantBT/dev/RULES.project.md`（红线：RunDetailPage 冻结 / 下单唯一入口 / 安全不变量）
- `/Users/wzy/Work/01_Projects/QuantBT/dev/RULES.md` §4/§5/§7/§8（扩展不替换 / 致命错误 / 前置闸门 / land 权限）