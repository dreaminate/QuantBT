I now have a complete picture: the runtime semantics (support.js), the data/state model (`Component extends DCLogic`), the `renderVals()` view model, and concrete template usage of every directive. I have everything needed to produce the structured analysis.

---

# DC 模板 → React 转换分析：support.js 运行时 + 策略台.dc.html

## 0. 整体心智模型（先框架后细节）

DC 运行时**本身就是一个建在 React 18 之上的微型模板引擎**。`support.js` 干三件事：(1) 把 `<x-dc>` 里的类 HTML 模板**编译成一组 React `createElement` 调用的 builder 函数**；(2) 把 `<script data-dc-script>` 里的 `class Component extends DCLogic` `eval` 成一个**类 React.Component 的逻辑类**；(3) 用一个 `StreamableComponent`（真正的 `React.Component` 子类）把两者粘起来——模板渲染读的"扁平数据"来自 `logic.renderVals()` 与 props 的合并。

关键结论先行：**这不是静态 HTML。策略台是一个完整的、带 React state 的有状态应用**，只是它的 state 不放在模板里，而放在 JS 逻辑类的 `this.state` 里，`setState` 触发重渲染，模板每次重渲染调用 `renderVals()` 拿到新视图模型。转 React 时，逻辑类几乎可以**1:1 映射成一个 React class component 或 hooks 组件**——它本来就是按 React 心智写的。

---

## 1. DC 模板语义（support.js 如何解释每个语法点）

编译入口：`compileTemplate(html, host)`（support.js L418）。流程是 `encodeCase()` 预处理 → 塞进 `<template>` → 给每个元素打 `data-dc-tpl` 序号 → `walkChildren`/`walk` 递归把每个节点编译成一个 builder 函数 `(vals, ctx, key) => ReactElement`。`vals` 就是 `{...props, ...renderVals()}` 这个扁平对象。

### 1.1 `<x-dc>` —— 模板根容器
- `parseDcDocument`（L24）：`doc.querySelector("x-dc")`，取其 `innerHTML` 作为模板字符串；同文档里 `script[data-dc-script]` 的 `textContent` 作为逻辑源码，`data-props` 属性 JSON 作为初始 props / `$preview` 元数据。
- `boot()`（L147）把 `<x-dc>` 替换成 `<div id="dc-root">`，在其上 `ReactDOM.createRoot(...).render()`。`x-dc{display:none}` 先隐藏原始模板（L1428）。
- **渲染规则**：`<x-dc>` 自身不产出 DOM，只是模板源载体。页面文件名（去掉 `.dc.html`）即根组件名（`dcNameFromPath`，L75），这里是 `策略台`。

### 1.2 `<helmet>` —— 注入 `<head>`
- `encodeCase` 先把 `<helmet>` 重写成 `<sc-helmet>`（L326），`walk` 命中后交给 `host.helmet(el)`（`createHelmetManager`，L1163）。
- **渲染规则**：helmet 的 builder **返回 `null`（不在 body 渲染）**，副作用是把子元素搬进 `document.head`：
  - `<script>`：按 `src`/`textContent` 去重（`mounted` Set），克隆属性后 `head.appendChild` —— **真正执行**。
  - `<link>`/`<meta>`：按 href/outerHTML 去重，`cloneNode(true)` 进 head。
  - 其它标签（如 `<style>`、`<title>`）：用 `live` Map 按 `name|index` 维护一个**可更新的活节点**，文本/属性变了就改。
- 策略台用它注入 JetBrains Mono 字体 `<link>` 和一大块全局 `<style>`（`*{box-sizing}`、`@keyframes sbpulse/sbring/sbdash`、scrollbar 样式等，L10–26）。

### 1.3 `<sc-for>` —— 列表渲染
- `walkFor`（L498）。属性：`list`（`{{ }}` 表达式，编译成 `listGet`）、`as`（项变量名，默认 `item`）、`hint-placeholder-count`（流式占位数，转 React 后可忽略）。
- **渲染规则**：求值 `list`，对每项构造 `sub = { ...vals, [asName]: item, $index: i }`，用这个**扩展作用域**渲染所有子 builder，包成 `React.Fragment`（key=i）。
- 非数组时：非流式则渲染空（并对非 null 的非数组 `console.warn`）。所以列表项里既能访问循环变量（`n`/`p`/`t`），也能访问外层所有 `renderVals` 字段，还有 `$index`。
- 策略台用例：`<sc-for list="{{ nodes }}" as="n">`（画布 16 节点），内部**再嵌套** `<sc-for list="{{ n.inPorts }}" as="p">`、`<sc-for list="{{ n.lines }}">`——多层嵌套循环正常工作，因为作用域是逐层 `...vals` 累积的。

### 1.4 `<sc-if>` —— 条件渲染
- `walkIf`（L533）。属性：`value`（`{{ }}` 表达式）、`hint-placeholder-val`（仅流式用）。
- **渲染规则**：`v = valGet(vals)`，**JS 真值判断**（`v ? <children> : null`）。无 `else`/`else-if` —— 互斥分支靠 `renderVals` 预先算好布尔字段（如 `dockPreview`/`dockSchema`/`dockEmpty` 各一个 `sc-if`）。
- 注意真值语义：空串 `""`、`0`、`null`、`false` 都视为假。策略台大量利用这点——`<sc-if value="{{ n.badge }}">` 直接拿字符串当条件，`renderVals` 里 `badge: n.badge || ""` 保证空时不渲染。

### 1.5 `{{ 表达式 }}` —— 插值
两个编译位置，语义一致（都走 `resolve()`）：
- **文本节点**（`walkText`，L456）：`txt.split(/\{\{(...)\}\}/)`，奇数段求值。值是 React 元素/数组→直接渲染；`null`/`boolean`→渲染空；其它→包进 `<span class="sc-interp">String(v)</span>`。未解析（`undefined`）→编辑器模式显示 `{{ x }}` 占位，否则渲染空并 warn 一次。
- **属性值**（`compileAttr`，L353）：
  - 整属性即单表达式 `attr="{{ x }}"` → `(vals) => resolve(vals, "x")`，**保留原始类型**（函数、对象、数组都能传，不会被 String 化）。这是事件 handler 和 style 对象能工作的根本。
  - 混合 `attr="a {{ x }} b"` → 各段求值后 `.join("")`，结果是字符串。

### 1.6 `onClick` 等事件属性
- `encodeCase` 不动它；`collectProps`（L367）对非组件元素把 `on*` 属性名映射成 React 驼峰名：内置 `EVENT_MAP`（L298，`onclick→onClick`、`onpointerdown→onPointerDown`…），未命中的 `on*` 走通用 `"on"+大写`。
- **HTML 源里其实写的就是驼峰** `onClick="{{ verToggle }}"`，但 `CAMEL_ATTR_RE`（L320）会先把驼峰属性编码成 `sc-camel-on-click`，再在 `collectProps` 里 `kebabToCamel` 还原成 `onClick`——绕一圈是为了过 HTML parser 的小写化。
- **值必须是单 `{{ }}`**，这样 `compileAttr` 返回原始函数引用。策略台所有 handler 都是 `renderVals` 里返回的箭头函数：`onClick="{{ verToggle }}"`、`onClick="{{ r.on }}"`（循环项里的函数）、`onPointerDown="{{ p.down }}"`、`onInput="{{ p.onInput }}"`、`onKeyDown="{{ onKey }}"`。还用到 `onPointerUp/onPointerEnter/onPointerLeave`（端口连线）。

### 1.7 `style-hover`（及 `style-*` 伪类）
- `collectProps`（L380）：`key.startsWith("style-")` → `host.pseudoClass(key.slice(6), value)`。`createPseudoSheet`（L1215）动态生成一个 class（如 `scp3`）并 `insertRule`（`.scp3:hover{...}` 或 `::before`/`::after`），把 class 名拼进元素 `className`。
- **渲染规则**：`style-hover="background:#2a2723;"` → 注入一条真正的 CSS `:hover` 规则。**纯 CSS、零 JS、零 state**。支持任意伪类（`style-focus`、`style-active`、`style-before`、`style-after`…），但策略台**只用了 `style-hover`**（27 处，全是导航/按钮/链接的悬停反馈）。

### 1.8 `style`（普通样式属性）
- `walkElement`（L638）：`if (k === "style" && typeof v === "string") v = cssToObj(v)`。`cssToObj`（L343）把 `"a:b; c:d"` 拆成 React style 对象（kebab→camel，`--var` 保留）。
- **两种写法都支持**：字面量 `style="display:flex; gap:10px;"`（编译期就是字符串→对象）；动态 `style="{{ n.cardStyle }}"`（`renderVals` 返回**整条 CSS 字符串**，运行期 `cssToObj` 转对象）。策略台**大量**用后者——节点定位、连线、各种状态色全是 `renderVals` 里拼好的 CSS 字符串（`wrapStyle`/`cardStyle`/`frameStyle`/`gridStyle`/`killStyle`…）。

### 1.9 其它（策略台未用但运行时支持，转 React 时会遇到）
- `<dc-import name="X">` / `<x-import from="url" component="Y">`：嵌入别的 DC 组件或外部 JS/JSX 模块（`walkComponent`/`walkXImport`）。**策略台没用**——它是单文件自包含组件。
- 元素属性归一化（`walkElement`）：`class→className`、`for→htmlFor`、`value`/`checked` 为 `undefined` 时兜底成 `""`/`false`（受控输入）。

---

## 2. 数据与状态来源（策略台里的 `{{}}` 变量 / 列表 / handler 在哪定义、怎么初始化、响应式）

**单一真相源 = `class Component extends DCLogic` 的 `this.state`（L488–502）。** 模板里的 `{{ }}` 字段**没有一个**是直接读 state 的——全部经过 `renderVals()`（L996–1245）这一层"视图模型投影"。

### 2.1 状态定义与初始化
- **`state = {...}`（L488）**：类字段，约 30 个键。节点字典 `nodes`、连线 `edges`、选中 `sel`、画布 `panX/panY/zoom`、交互态 `marquee/linking/hoverPort`、撤销栈 `undoStack/redoStack`、`agentMode`、`runtime`、各面板开合 `leftOpen/rightOpen/dockOpen`、各标签 `inspTab/dockTab/codeTab`、Agent `draft/agentBlocks/proposal`、回测 `running/runLog`、`trace/diffBase/publishOpen/killArmed/lifecycle/ver` 等。
- **`componentDidMount()`（L505）**：调 `_build()` 建初始图；挂载**全局 DOM 监听**（`document` 上的 `pointermove`/`pointerup`/`keydown`，画布元素上的 `wheel`）；解析 URL `?trace=`/`?node=` 做 deep-link。`componentWillUnmount()` 全部解绑、清 `setTimeout` 定时器。
- **`_build()`（L536，跑一次）**：硬编码构造 16 个节点（`defs[]`）+ 19 条连线（`edges[]`），以及挂在实例上的 mock 夹具 `this._trades`/`this._runs`/`this._versions`/`this._diff`/`this._contribution`/`this._varProposal`（**不是 state，是实例字段**，作为不可变 fixture），最后 `setState({nodes, edges, agentBlocks, proposal})`。

### 2.2 `{{}}` 变量、列表、handler 的来源
**全部来自 `renderVals()` 的 return 对象（L1200–1244）。** 它把 `this.state` + 实例 fixtures 投影成一个**扁平视图模型**，包含三类字段：
1. **标量/字符串**：`versionLabel`、`zoomPct`、`errLabel`、`canvasHint`、各种拼好的 CSS 字符串（`gridStyle`/`killStyle`/`undoStyle`…）、各种布尔开关（`leftOpen`/`dockPreview`/`hasSel`/`traceOn`…）。
2. **数组（喂 `sc-for`）**：`nodes`、`edges`、`stages`、`miniNodes`、`runtimeBtns`、`modeBtns`、`inspTabs`、`dockTabs`、`tradeRows`、`runCells`、`agentBlocks`、`versionRows`、`lifecycleSteps`、`codeLines`、`pipeline`、`insp.params/ins/outs` 等。每个数组项是预算好的对象，**连同它的事件 handler**（如 `tradeRows` 每项有 `go: () => this._setTrace(t.id)`）。
3. **函数（喂 `onClick` 等）**：`verToggle`、`runClick`、`undo`/`redo`、`fork`、`kill`、`acceptProposal`、`onDraft`、`onKey`、`send`、各 tab 的 `on: () => this.setState({...})`。**这些是 `renderVals` 每次渲染新建的箭头闭包**，捕获 `this`/循环项。

### 2.3 响应式更新机制（核心）
**有真正的响应式，机制 = React state + 订阅重渲染：**
- `DCLogic.setState(update, cb)`（support.js L669）→ `__host.__setLogicState`（L811）→ 合并进 `logic.state` 后调真正的 `React.Component.setState((s)=>({__v:s.__v+1}))`，**触发 `StreamableComponent.render()`**。
- `render()`（L873）里 `vals = {...userProps, ...this.logic.renderVals()}`，再 `r.tpl(vals, this)` 重跑所有 builder。**所以每次 `setState` → renderVals 重算 → 模板重渲染**，和原生 React 完全一致。
- 额外有一套 registry 订阅（`entry.subs`）用于流式/热替换场景；对"运行中的纯前端应用"而言可忽略——关键就是 `setState` 驱动。
- 异步更新也走这条路：`_runGraph()` 用一串 `setTimeout` 反复 `setState` 推进节点状态/日志，UI 流式刷新；`_sendAgent()`、各种 mock 都是 `setState`。

**没有后端**：注释明说"所有回测/运行都是前端 MOCK 模拟，不真跑后端"（L467）。唯一的真实导航是 `window.location.href = "回测详情.dc.html?..."`（跳到另一个 DC 页面）。

---

## 3. `{{}}` 表达式能力（`resolve()`，support.js L191）

这是一个**刻意做小的安全求值器，不是 JS eval**。它把表达式字符串递归下降解析，支持：

| 能力 | 支持？ | 例子（策略台/通用） |
|---|---|---|
| 标识符 / 属性链 | ✅ | `versionLabel`、`n.title`、`insp.params`、`p.onInput` |
| 多级点访问 | ✅ | `trace.symbol`、`proposal.patchId` |
| 方括号索引 | ✅ | `arr[0]`、`obj[key]`、`obj[expr]`（key 也递归求值，L272） |
| 字面量 | ✅ | 数字 `NUMBER_RE`、字符串 `'x'`/`"x"`、`true`/`false`/`null`/`undefined` |
| 取反 `!` | ✅ | `!leftOpen` |
| 相等比较 `=== !== == !=` | ✅ | `inspTab === 'params'`（顶层相等，`findTopLevelEquality` L234） |
| 括号分组 | ✅ | `(a)`（`parensWrapWhole`） |
| **函数调用** `f()` | ❌ | 不支持——`resolvePath` 遇到 `(` 直接 `return undefined`（L275） |
| 算术 `+ - * /` | ❌ | 没有 |
| 三元 `?:` | ❌ | 没有 |
| `&& \|\|` | ❌ | 没有 |
| 取数组长度/方法 | ❌ | `.length` 能作为属性读，但 `.map()` 不行 |

**设计后果（极重要）**：因为表达式能力这么弱，**所有派生逻辑必须前移到 `renderVals()` 里用真 JS 算好**。这就是为什么 `renderVals` 有 250 行——三元、循环、字符串拼接、条件颜色、CSS 字符串全在 JS 里完成，模板只做"取字段 + sc-for + sc-if"。**这恰恰让转 React 极其顺畅**：JSX 里直接写 `{vm.field}`，逻辑天然已经在 JS 侧。

事件 handler 作为"裸标识符"传递（`onClick="{{ verToggle }}"` → `resolve` 返回函数引用本身，不调用）——靠的就是 `compileAttr` 整属性单表达式分支保留原始类型。

---

## 4. 转 React 的映射表

| DC 语法 | React 等价 | 推荐做法 |
|---|---|---|
| `<x-dc>` + `<script data-dc-script>` | 一个组件文件 | `class Component extends DCLogic` → **直接改成 `class StrategyBoard extends React.Component`**（见 §5.4）。改动极小。 |
| `{{ x }}`（文本） | `{vm.x}` | 视图模型字段直接花括号插入。React 元素/数组/字符串都原样工作。 |
| `{{ x }}`（属性，单表达式） | `attr={vm.x}` | 函数/对象/字符串直传。 |
| `attr="a {{ x }} b"`（混合） | `attr={\`a ${vm.x} b\`}` | 模板字符串。 |
| `<sc-for list="{{ items }}" as="n">…</sc-for>` | `{vm.items.map((n, $index) => (<React.Fragment key={$index}>…</React.Fragment>))}` | **用 `.map`，key 用 `$index`**（运行时本就用数组下标做 key）。循环内可继续访问外层 `vm` 字段。注意：嵌套 sc-for → 嵌套 map。`hint-placeholder-count` **丢弃**（流式专用）。 |
| `<sc-if value="{{ c }}">…</sc-if>` | `{vm.c && (<>…</>)}` | 短路渲染。**保留 JS 真值语义**（空串/0/null 都是假）——直接 `&&` 即可，行为一致。无 else，互斥用多个 `&&`（视图模型已备好互斥布尔）。 |
| `onClick="{{ fn }}"` | `onClick={vm.fn}` | 内置事件名（`EVENT_MAP`）已是 React 驼峰，1:1。`onInput→onChange` 见下。 |
| `onInput="{{ fn }}"` | `onChange={fn}`（React 受控输入惯例） | DC 用 `onInput`；React 里 `<input>/<textarea>` 受控通常用 `onChange`（React 的 onChange 行为≈DOM input 事件）。handler 签名 `(e)=>...e.target.value` 不变。 |
| `value="{{ v }}" {{ p.disabled }}` | `value={v} disabled={p.disabled}` | DC 里 `disabled` 是 `"disabled"`/`""` 字符串；React 用布尔，需把 `(readonly\|\|locked) ? "disabled" : ""` 改成布尔。 |
| `style="display:flex;"`（字面量） | `style={{display:'flex'}}` 或保留 CSS-in-JS | 字面量可转 style 对象；量大时建议保留**字符串→对象的小工具**（等价 `cssToObj`）避免手翻几百条。 |
| `style="{{ n.cardStyle }}"`（动态 CSS 字符串） | `style={cssToObj(vm.n.cardStyle)}` | **保留 `renderVals` 拼 CSS 字符串的写法 + 一个 `cssToObj` helper**，改动最小（见 §5.2）。或重构成 style 对象由 vm 直接返回。 |
| `style-hover="background:#2a2723;"` | **CSS Module / styled `:hover`** | **推荐 CSS（`:hover` 伪类），不要 `onMouseEnter/Leave`+state**。27 处全是静态悬停反馈，纯展示，用 CSS class 最省、无重渲染。可写一个 `useHoverStyle`/CSS module，或干脆把这些元素提成带 `:hover` 的 className。 |
| `<helmet><link>/<style></helmet>` | `<head>` 注入 | 字体 `<link>`→放进 `index.html` 或 `react-helmet`；全局 `<style>`/`@keyframes`→**移到全局 CSS / CSS module**（`sbpulse`/`sbring`/`sbdash`、scrollbar、`::selection`）。 |
| `data-props` JSON | 组件默认 props | `$preview` 是设计器画布尺寸元数据，转 React 时丢弃；`props` 作为默认 props 合并。策略台只有 `$preview`，无业务 props。 |
| `this.setState(update, cb)` | `this.setState`（class）/ `setX`（hooks） | DCLogic 的 setState 语义与 React 一致（支持 updater 函数 + callback）。**class 版几乎零改**。 |
| `renderVals()` | 一个 `buildViewModel()` 方法 / `useMemo` | 直接保留为 `const vm = this.buildVM()`（class 的 `render` 里调用）或 `useMemo(()=>buildVM(state), [state])`。 |
| `componentDidMount/WillUnmount` | 同名（class）/ `useEffect`（hooks） | 全局 `document` 监听、`setTimeout` 清理逻辑 1:1 搬。`this._surf = getElementById("sb-graph")` → **改用 `useRef`/`createRef`**（更 React 化，见 §5.3）。 |
| `window.location.href = "回测详情.dc.html?..."` | router 跳转 | 多页 DC → React Router 路由。保留 query string（`?trace=`/`?node=`/`?from=`）做 deep-link。 |

---

## 5. 判定：纯静态 / 需 React state / 需后端 API

### 5.1 需要真实 React state（绝大部分）
**整个策略台是一个有状态交互应用，逻辑类的 `this.state`（~30 键）必须成为真实 React state。** 凡是用户能改的都需要：
- **画布交互**：节点拖拽（`nodes[id].x/y`）、平移缩放（`panX/panY/zoom`）、框选（`marquee`）、连线（`linking/hoverPort/edges`）、选中（`sel`）。
- **编辑**：参数输入 `_setParam`、撤销/重做栈 `undoStack/redoStack`、删除 `_delSel`、自动布局。
- **面板/标签开合**：`leftOpen/rightOpen/dockOpen`、`inspTab/dockTab/codeTab`、版本菜单 `verMenuOpen`、发布抽屉 `publishOpen`、代码抽屉 `codeOpen`。
- **Agent 流**：`draft/agentBlocks/proposal`，接受/拒绝/撤回 patch。
- **运行态机**：`runtime`(backtest/paper/live)、`agentMode`(ask/auto/bypass)、`running/runLog`、`lifecycle`、`killArmed`、`trace`、`diffBase`。

### 5.2 纯静态展示（不需 state、但当前由 mock 数据驱动）
- **Helmet 里的字体/全局样式/keyframes** —— 纯静态，移到 CSS。
- **图例**（兼容/可适配/需转换/不兼容四个胶囊，L225–228）—— 写死的静态 DOM。
- **拓扑栏品牌、导航链接**（因子台/Model台/模拟台/蓝本，L31–38）—— 静态，只 `style-hover` 用 CSS。
- **mock fixtures**（`_trades`/`_runs`/`_versions`/`_diff`/`_contribution`/`PREVIEW`/`PARAM_META`/各 `*_META`/`CAT`/`STATE`/`STG` 常量表）—— 当前是硬编码常量。**展示是静态的，但内容应来自后端**（见 5.3）。它们不需要 state（不可变），但需要数据源切换。

### 5.3 需要接后端 API（目前全是 MOCK，注释已点名真实端点）
代码注释明确标注了未来对接的真实服务，转产品时这些 mock 要换成 API：
- **建图初始数据 `_build()`** → 真实 `StrategyRepository` / `StrategyGraph` 加载（现在硬编码 16 节点）。
- **跑回测 `_runGraph()`/`_compileLog()`** → 真实回测引擎（注释 L467 "不真跑后端"、L837 "mock"、L965 "后端执行（前端不跑）"）。日志流要换成 WebSocket/SSE。
- **输出预览 `PREVIEW`** → 注释 L1129 `RunRepository.previewIO`。
- **运行历史 `_runs`、成交 `_trades`、血缘 `trace.path`** → `RunRepository` / 成交明细 API。
- **版本/回滚 `_pickVersion`/`_rollback`** → 注释 L867 `StrategyRepository.rollback`。
- **因子/Model 引用**（`fs_core3`、`lgbm_rank_6f@v2`）→ 因子台 / Model Registry（B3/B4 治理边界），现在是写死的引用名。
- **代码生成 `_genYaml/_genPy`** → 当前前端拼字符串（codegen 预览）；真实应由后端 serialize StrategyGraph。
- **发布/生命周期 `_advance`** → 真实治理审批工作流。

### 5.4 转 React 的总体建议
1. **逻辑类几乎零改**：`class Component extends DCLogic` → `class StrategyBoard extends React.Component`，`state`/`setState`/`componentDidMount`/`componentWillUnmount` 全部直接复用（DCLogic 的 API 本就是 React.Component 的子集）。`renderVals()` → 在 `render()` 里 `const vm = this.renderVals()`，JSX 读 `vm.*`。
2. **`render()` = 把模板 HTML 翻成 JSX**：`{{x}}`→`{vm.x}`、`sc-for`→`.map`、`sc-if`→`&&`、`style="{{s}}"`→`style={cssToObj(vm.s)}`（保留 `cssToObj` 这一个 helper 即可，避免手翻几百条内联 CSS）。
3. **`style-hover` 全部转 CSS `:hover`**（CSS module 或全局类），不要 state。
4. **DOM 直查改 ref**：`document.getElementById("sb-graph")` / `"sb-agentscroll"` → `React.createRef`；但 `document`-level 的 `pointermove/up/keydown` 监听保持手动 `addEventListener`（画布拖拽需要全局捕获，这是合理的 React 用法）。
5. **`onInput`→`onChange`**、字符串 `disabled`→布尔。
6. **多页跳转**（`location.href = "X.dc.html"`）→ React Router，保留 query 做 deep-link。
7. **数据分层**：先用现有 mock 常量驱动跑通 UI（纯静态/state 部分），再按 §5.3 逐个端点接后端。

---

### 关键文件/行号速查
- 运行时表达式求值器：`/tmp/qbt-handoff/quantbt-claude/project/support.js` `resolve()` L191、`compileAttr()` L353。
- 指令编译：`walkFor` L498 / `walkIf` L533 / `walkText` L456 / `walkElement` L638 / helmet L1163 / `style-*` 伪类 L380+L1215 / 事件映射 `EVENT_MAP` L298。
- setState→重渲染链路：`DCLogic.setState` L669 → `__setLogicState` L811 → `StreamableComponent.render` L873。
- 策略台逻辑：`/tmp/qbt-handoff/quantbt-claude/project/策略台.dc.html` `state` L488、`_build` L536、`renderVals` L996、return 视图模型 L1200。
- 模板用例：helmet L10、节点嵌套 `sc-for` L194、`sc-if` L206、`style-hover` L34、受控输入 L129/L259。