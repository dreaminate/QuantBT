---
uuid: ca3ab3eca0be4ae48b864251d1753f9d
title: Agent 窗口里程碑进度线 + 跨台台 switcher
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P3
area: frontend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [d11d1426c2a14372a12e655fcd459871, 82120b9c60814566beea2d6b210ef31e]
---

# Agent 窗口里程碑进度线 + 跨台台 switcher

## Scope [必填]
做：Agent 窗口顶栏的两件治理可见性部件——(1) 里程碑进度线（7 节点 立题→市场→因子集→模型→信号→风控→回测，reached 节点可点跳对应 cowork 产物卡 + 滚动定位对话锚点）；(2) 跨台台 switcher（4 台导航 pill 组：因子台/Model台/策略台/模拟台）。不做：里程碑节点背后的 cowork 产物卡渲染本体（T-044 产物工作区）、对话流/工具可视化/权限三态（T-040）、未建台（因子台/模拟台）的页面本身（本卡只给灰占位防死链）。

## 上下文 / 动机 [按需]
设计稿 `QuantBT Agent.dc.html` L29-66 的「TITLE BAR + 台 SWITCHER」与「MILESTONE LADDER」两区是策略台 agent 窗口独有的强结构，T-040（对话流核心）scope 未覆盖（见审计 /tmp/qbt-agentDeck.md §5/§7「需补 3 张卡」之 T-045）。里程碑进度线把 agent 当前推进到哪一步（立题/市场/因子集/模型/信号/风控/回测）做成顶栏常驻可视，节点态三分（active 橙脉冲 / reached 绿 / 未达空心）；台 switcher 让用户在四台间导航，且把「跨台血统」做成第一类导航（呼应因子集/模型卡的 ←因子台/←Model台 蓝胶囊）。本卡是 epic cfb0fea9（整套台前端实装）的一片，依赖 G1 暗色台地基（壳件/tokens/路由边界）。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/frontend/src/components/shell/Shell.tsx | `SIDEBAR_BY_AREA` L18-45 / `AREA_LABEL` L47-52 | 扩展 desk 元数据：为台 switcher 提供 4 台的 to/label/建台状态（已建=可跳 link / 未建=「敬请」灰占位）。新增不删除现有项。 |
| app/frontend/src/components/shell/Shell.tsx | `areaOf()` L381-405（workshop 分支含 `/agent` L392） | 复用台→area 映射定位 active 台；台 switcher active 态以 `areaOf(location.pathname)` 判定，扩展不改判定逻辑。 |
| app/frontend/src/App.tsx | 路由表 L55-86（`/agent` L64，未建台路由缺席） | 因子台/模拟台路由未建：switcher 对未建台渲染灰占位（非 NavLink、不带 to），绝不渲染指向未注册路由的链接。已建台（`/agent` 策略台、`/training` Model台 area L71-72）走真 NavLink。 |
| app/frontend/src/pages/workshop/（新建 agent 窗口组件，T-040 落点） | agent 窗口顶栏宿主 | 里程碑进度线 + 台 switcher 作为顶栏组件挂入；里程碑 reached 节点 onClick → `_gotoMs(key)`：切 coworkOverride 到该里程碑 cowork + 滚动定位 `_msAnchor[key]` 对话锚点。未达节点不绑 onClick、不可点。 |
| app/frontend/src/pages/workshop/Mode2ChatPage.tsx | 现有 SSE/authFetch 复用源 | 里程碑 reachedMs[]/activeMs 状态来源接 agent 窗口 state（T-040 提供）；本卡只消费、不定义对话流 state。 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「台 switcher 对未建台（因子台/模拟台）渲染真 NavLink/可点链接指向未注册路由」→ 门必抓：点击未建台导致死链（路由 404 / 空白页 / 落到 fallback），断言未建台只渲染灰「敬请」占位、无 to 属性、点击不触发 navigate。变异要杀：把占位偷改成 `<NavLink to="/factors-desk">` 或给占位绑 onClick navigate → 测试必红。
2. 种「里程碑未达节点（未在 reachedMs[]）也绑 onClick 可点跳」→ 门必抓：点击未达节点触发了 `_gotoMs`/滚动/coworkOverride 切换，断言仅 `reachedMs.includes(key)` 的节点可点、未达节点无 onClick 且 aria-disabled。变异要杀：把可点条件从 `reached` 改成 `reached || active` 之外的恒真、或对全节点统一绑 handler → 测试必红。
3. 种「active 里程碑节点被当 reached 之外的不可点，或 reached 判定用了节点索引 < activeIndex 的硬编码而非 reachedMs[] 真值」→ 门必抓：断言可点性数据源是 reachedMs[]（治理真值），不是前端推断的序位，防止伪造「已达」绕过产物卡尚未生成的现实。

## 复用 [按需]
- 复用 Shell.tsx 的 `areaOf()`（L381）做台 active 判定、`AREA_LABEL`（L47）做台名，不另起一套路由→台映射（防双源漂移）。
- 复用 G1（d11d1426）暗色台地基的 desk 壳件 + per-desk accent token + 路由边界；台 switcher 三态样式（active 橙底 #d97757 / link 可跳 / plain+soon「敬请」灰胶囊 #6f6a61）走 G1 的 `cc-*` CSS 变量，勿内联十六进制（审计 §6）。
- 里程碑 `_gotoMs` 的滚动锚点 `_msAnchor{}` 与 cowork 产物卡 id 对齐 T-044 的卡 id 契约（CoworkKind: hypothesis/market/factorSet/model/signal/portfolio/run）。

## 红线 [按需]
- 跨台导航绝不绕治理：台 switcher 只是导航 pill，不携带任何下单/晋级动作；切到模拟台仍止于模拟盘默认（不导向直接实盘）。
- 弱点一等呈现不受本卡影响：里程碑/switcher 不得折叠或染绿掩盖下游产物卡的 red/PBO/DSR/血统弱点（R25），进度线绿点≠裁决可信。
- RunDetailPage 冻结：本卡不触碰 RunDetailPage（App.tsx L46 wide layout 分支）交互逻辑。
- 未建台一律灰占位，绝不造死链；建台状态以 App.tsx 路由表实际注册为准，不写死「已建」假设。

## 非目标 [按需]
- 不实装因子台/模拟台页面本体（仅占位）。
- 不实装 cowork 产物卡渲染、Strategy.yaml/Report.md tab（T-044）。
- 不实装对话流 7 种 block、权限三态状态行、gate 弹窗（T-040/T-041）。
- 不实装 backtest.run/eval.pbo 等后端工具 handler（T-043）。

## Open Questions（已决 D/总）[按需]
1. [已决] 台 switcher 四台命名/顺序固定为 因子台/Model台/策略台/模拟台（设计稿 L58 顺序），active=策略台。
2. [已决] 未建台（因子台/模拟台）渲染「敬请」灰占位、非链接，建台后再换 NavLink（防死链红线）。
3. [已决] 里程碑可点性数据源 = reachedMs[]（治理真值），非前端序位推断（对抗 #3）。
4. [已决] 里程碑节点点击同时切 wsTab→cowork(对齐设计稿 _gotoMs + A1 工作区语义)，仅 reached 节点可点。— leader 2026-06-21

## 验收一句话 [必填]
种「未建台 switcher 造死链」+「里程碑未达节点可点跳」两类坏门必抓（未建台只灰占位无链接、仅 reachedMs[] 节点可点），且不破现有 Shell/App 路由与 Mode2ChatPage 基线。

---

接线点已用 graphify 定位并复核到 file:line：Shell.tsx `SIDEBAR_BY_AREA` L18-45 / `AREA_LABEL` L47-52 / `areaOf()` L381-405（workshop 分支含 `/agent` L392）；App.tsx 路由表 L55-86（`/agent` L64，因子台/模拟台路由未建）。依赖卡确认：G1 = d11d1426c2a14372a12e655fcd459871「暗色台地基」；关联 T-040 = 82120b9c60814566beea2d6b210ef31e（其 scope 确未覆盖里程碑/switcher，本卡正补 §7 之 T-045）。
