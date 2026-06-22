I now have complete coverage of the design file, the backend surface, the existing frontend, and the GOAL milestones. Here is the structured analysis.

---

# Model台 设计稿全量解析（`/tmp/qbt-handoff/quantbt-claude/project/Model台.dc.html`，1931 行）

源文件绝对路径：`/tmp/qbt-handoff/quantbt-claude/project/Model台.dc.html`
运行时编译器：`/tmp/qbt-handoff/quantbt-claude/project/support.js`（DC → React）

---

## ① 整体布局骨架（区域树 + 尺寸）

这是一个**四子台单页 SPA**（不是多路由），用 `state.view` 在 `jobs / registry / build / research` 之间切换。全屏 flex column 布局，固定 viewport 高度。

```
<body bg=#1c1b19>  font=JetBrains Mono  text=#e6e1d6  base 13.5px / lh1.5
└─ 根 flex-col height:100vh
   ├─ TITLE BAR  (flex:none · height 42px · padding 0 14px · bg #201f1c · border-bottom #302d29)
   │   ├─ 三个 ●红绿灯(11×11圆 #3a3733) · ✳(#d97757) · "QuantBT"(600)
   │   ├─ 台 SWITCHER (4 链接, bg #1a1916, border #302d29, radius 8, pad 3)
   │   │     因子台 / [Model台 当前态] / 策略台 / 模拟台
   │   │     · 链接态 color #a39a8a · hover bg #2a2723
   │   │     · 当前态 bg #6f9bd1(蓝) color #16202c font700  ← 注意:Model台主色用蓝,非橙
   │   └─ 右: "算力 · 1×A100 80G · 本地" (#5f5b53 11px)
   │
   ├─ SUB-TAB BAR (flex:none · padding 8px 16px · bg #1a1916 · border-bottom #302d29)
   │   ├─ ⊟作业台 / ▣模型库 / ⌨构建台 / ⚗研究台  (tabStyle: on→bg#2a2723,off→透明)
   │   ├─ {{subHint}} 右对齐提示语 (#6f6a61 11px)
   │   └─ ＋新建训练 (仅 jobs 视图显示 · bg #6f9bd1 · color #16202c · radius 7)
   │
   └─ BODY (flex:1 · min-height:0 · display flex) —— 四视图互斥 sc-if
       │
       ├─[A] JOBS VIEW (作业台 · 三栏)
       │   ├─ 左:训练队列 (flex:none w296px · border-right #302d29 · 可折叠→34px 竖排)
       │   │     头:训练队列 + {{jobCountLabel}} + ‹折叠
       │   │     列表:job 卡 (pad 9/11 · radius 9 · sel边框#4a5666/bg#222630)
       │   │           ● dot · name · family 胶囊(右上) · task · 状态文本
       │   ├─ 中:dashboard (flex:1 · overflow-y · padding 18/22 · bg #191815)
       │   │     内容 max-width 760px:
       │   │       · header (name17px700 + family胶囊 + arch + 右:状态/耗时)
       │   │       · TensorBoard 折叠条 (橙系 #e6883a/#5a4326 · ml/dl通用 · :6006)
       │   │           展开:tab条(SCALARS/HISTOGRAMS/DISTRIBUTIONS/GRAPHS/HPARAMS)
       │   │                SCALARS→3列 sparkline 卡 grid; 其余→斜纹占位
       │   │       · RUNNING/DONE 仪表盘 (d_hasCurves):
       │   │           - epoch 进度条 (7px · 蓝渐变 #6f9bd1→#82aadb)
       │   │           - charts row:loss双线卡 + val指标面积卡 (各 radius10 bg#1d1c19)
       │   │           - 算力卡 (GPU util黄条/VRAM蓝条/throughput/torch子进程✓)
       │   │           - CV folds 卡 (Purged k-fold·embargo1% · 5格)
       │   │           - 动机与设计卡 (✎ · why引用块橙左边框 + 2列网格元数据
       │   │               + 输入/输出数据规格(可展开字段) + 设计细节逐项)
       │   │           - actions (运行→⏸暂停; 完成→发布按钮 + 查看完整回测详情↗外链)
       │   │       · QUEUED 占位 / FAILED 错误卡(红系 #523630 · 错误堆栈 + 助手建议)
       │   └─ 右:训练助手 (flex:none w296px · border-left · 可折叠→34px)
       │         ✦头 + 实时诊断块 + 追问 chips + chat thread + 输入框
       │
       ├─[B] REGISTRY VIEW (模型库 · 单栏 max-width 980px · bg #191815)
       │   ├─ 说明行:dev→staging→production→archived(须审批门,不可裸翻)
       │   ├─ 2列 grid 模型卡 (gap14 · radius11 · border#34302a):
       │   │     头(可点open):▣ id · v版本 · family胶囊 · stage胶囊(右)
       │   │     体:gist引用 · 架构/IO/CV-NDCG/walk-forward/lineage 元数据行
       │   │        + 晋级按钮(canPromote) + 查看详情› + note(右)
       │   └─ promote gate 面板 (黄系 #6a5230/#23201a · max-width560 · realmoney不可裸翻徽章)
       │         from→to · checks 清单 · ✓批准晋级(#d9b25f) / 取消
       │
       ├─[C] BUILD VIEW (构建台 · draw.io 式图编辑器 · 多面板可拖拽分栏)
       │   ├─ 左:构建助手 chat (w {{bdChatW}}=312px · 可折叠 · 220–560 拖拽)
       │   ├─ splitter (5px col-resize · hover#6f9bd1)
       │   ├─ 中:graph canvas (flex:1 · bg #17191c · 点阵网格背景 18×18)
       │   │     toolbar:工具(Markup/Comments/Edit/100%/Share)+⧉注册模块+⊞整理+‹代码
       │   │     surface:SVG 连线层 + 绝对定位 node 卡(w158px) + 端口(13×13圆)
       │   │       node 卡:头(dot+label+模块展开+✕) + 体(param·shape+dtype+io规格
       │   │              +LLM试一条+编辑参数+内部子图+flag红/warn黄/markup)
       │   │       module 进入态:面包屑 Model›模块名 + 输入/输出端口提示
       │   │     右:组件库 palette (w170px · 可折叠→30px):
       │   │       我的模块(紫#b89cd8) / 机制模块(青#6fb0c8开箱即用) /
       │   │       原子分组(io/数据源/预处理/LLM/层级/张量/归一/激活/后处理/输出) /
       │   │       训练优化器·损失·调度(绿#9bbd5a, 带ⓘ+＋注册) /
       │   │       训练超参数(lr/batch/epochs/wd/seed) / 多模型组合参数作用域
       │   └─ 右:code 面板 (w {{bdCodeW}}=344px · 可折叠 · 248–620 拖拽)
       │         file tab(model.py/config.yaml) + ▷跑训练 + ⟳刷新代码(深度)
       │         代码逐行渲染 + bdGateOpen 提交确认 + bdSubmitted 成功条
       │     (3 个 modal:注册自定义训练组件 / atom信息卡 / 注册模块命名)
       │
       └─[D] RESEARCH VIEW (研究台 · 理论判定 + 论文 · 两栏)
           ├─ 左:研究助手 chat (w340px · ⚗紫#c08adb · 导入论文/文章按钮 + 输入)
           └─ 右:workspace (flex:1):
                 tab:∑公式工作台 / ▤论文 + 右:架构带去构建台→
                 公式工作台:导入架构卡 + 数学可行性判定卡 + 可行性结论卡
                            + FactorVAE forward 推导(候选) + 理论判定结论
                 论文:前沿架构卡列表(title/venue/arxiv/gist/可迁移)
           (1 个全局 modal:IMPORT SOURCE PICKER 选研究对象 · fixed)
       (1 个全局 modal:DRILL-IN 模型详情浮窗 · fixed · w620px)
```

布局尺寸常量速查：队列/助手栏 296px，折叠后 34px；build chat 312px(220–560)，code 344px(248–620)，palette 170px(折叠30px)；research chat 340px；node 卡 w158/h60；canvas 网格 18×18px；dashboard 内容 max-width 760，registry 980，research 公式 680/论文 760。

---

## ② 每个面板/区块职责 + 关键视觉（具体值）

### 通用色板（全稿一致）
- 画布底 `#1c1b19`，面板底 `#191815`/`#1a1916`/`#1d1c19`，输入底 `#211f1c`/`#161512`
- 边框 `#302d29`(主) `#2a2723`(软) `#34302a`(卡)；文字 `#e6e1d6`(主) `#cfc8ba`/`#c4bdaf`(次) `#8f897c`/`#7d7668`(dim) `#6f6a61`/`#5f5b53`(更暗)
- 圆角谱：胶囊 10–20px，卡 9–13px，按钮 6–8px，输入 5–8px
- 字号谱：17(title) 13.5(base) 12.5/12/11.5/11/10.5/10/9.5/9/8.5/8（高密度信息台，极小字号多）

### 子台主题色（关键!每个子台一个标识色）
| 子台 | 主色 | 应用 |
|---|---|---|
| Model台整体 | **蓝 `#6f9bd1`**（family dl 也是蓝） | 台切换器当前态、新建按钮、链接、端口高亮 |
| family ml | 绿 `#9bbd5a` (bg rgba(127,166,80,.15)) | 胶囊、指标 |
| family dl | 蓝 `#6f9bd1` | 胶囊 |
| family code | 黄 `#d9b25f` | 自由脚本 |
| TensorBoard | 橙 `#e6883a` / border `#5a4326` | TB 条专属橙系 |
| 构建台/原子 | 张量算子橙 `#d98c6f` · 层级蓝 `#3a4654` · 模块紫 `#b89cd8` · 机制青 `#6fb0c8` · 训练组件绿 `#9bbd5a` |
| 研究台 | 紫 `#c08adb`（助手/判定）；论文 venue 紫 |
| stage | dev灰`#8f897c` · staging黄`#d9b25f` · production绿`#9bbd5a` · archived暗`#6f6a61` |
| 判定 icon | ✓绿`#9bbd5a` · ○黄`#d9b25f`(隐患) · ✗/⚠红`#d97066` |

### 作业台核心区块
- **loss 卡**：双线 SVG（train 实线橙 `#d97757` 1.8px · val 虚线蓝 `#6f9bd1` 1.6px dash"3 2"），viewBox 300×120，高 108px。
- **val 指标卡**：面积图（fill rgba(127,166,80,.12) + 线 `#9bbd5a`），右上大数 13px700。
- **算力卡**：GPU util 黄条 `#d9b25f`、VRAM 蓝条 `#6f9bd1`（/80G）、throughput k/s、torch"子进程✓"。条高 6px radius3。
- **CV folds**：5 格 flex，run 态黄边框 `#5a4a2a`，done 绿值。
- **动机卡**：why 引用块 `border-left:3px #d97757` bg `#211f1c`；2 列 grid（数据/时间范围/标签/设计思路/架构跨列/超参跨列绿色）；IO 规格内嵌青蓝(输入 #6fb0c8/#13212a)+绿(输出 #9bbd5a/#1c2018)可展开字段；设计细节 6 段（设计思路/正则化/参数初始化/训练策略/防数据泄漏/风险权衡）。

### 模型库卡
头 bg `#221f1c`；元数据行 label min-width 96/color `#7d7668` + 值；CV/walk-forward 绿；lineage 灰；晋级按钮黄边透明底 `#5a4a2a`。

### 构建台 node 卡（最复杂）
158px 宽，头部 dot(7×7 radius2 按 cat 着色) + label + 模块"↳进入"/✕；选中态边框 `#6f9bd1` + 双重 shadow，多选态紫 `#b89cd8`。flag 红块 `#2a1d1b`/`#6a4030`，warn 黄块 `#262017`/`#5a4a2a`，markup 黄左边框。端口圆 13px(in 顶 -6px / out 底 -6px，left 71px 居中)。连线为 SVG 三次贝塞尔曲线 stroke `#5a6472` + 箭头 marker，中点标注 shape。

---

## ③ 状态模型（`{{}}` 变量清单 + TS interface 草拟）

### state 初始对象（L820–836，完整枚举）
顶层：`view("jobs")` · `selJob("trn-7c41")` · `epoch(0)` · `running(true)` · `published(false)` · `jobsOpen` · `mtOpen`
注册表：`regStage{lgbm_rank_6f:"staging",gbdt_baseline:"dev",tcn_alpha_v1:null}` · `gate(null)` · `regDetail(null)` · `wfOpen` · `ioFieldsOpen`
作业助手：`chat[]` · `chatDraft`
构建台：`bdChatW(312)` · `bdCodeW(344)` · `bdFile("model.py")` · `bdTool("edit")` · `bdChat[]` · `bdDraft` · `bdBusy` · `bdGateOpen` · `bdSubmitted` · `bdNodes[]` · `bdEdges[]` · `bdSel` · `bdLinkFrom` · `bdExpanded{}` · `bdCustom[]` · `bdCodeOpen` · `bdChatOpen` · `bdMark{}` · `bdMultiSel[]` · `bdRegOpen` · `bdRegName` · `bdInfo` · `bdEnter`(进入的模块id) · `bdMarquee` · `bdPaletteOpen` · `bdCodeSnap`(代码快照) · `bdGenSig` · `bdGenBusy` · `bdOptim("adamw")` · `bdLoss("lambdarank")` · `bdSched("cosine_warmup")` · `bdCustomTrain{optimizers,losses,scheds}` · `bdTrainRegOpen` · `bdTrainRegName/Math/When` · `bdLlmText/Out/Busy` · `bdPanX/Y(0)` · `bdZoom(1)` · `bdHparams{lr,batch,epochs,weight_decay,seed}` · `bdShareOpt(true)` · `bdModuleScope{tcn,xsec,head}`
TensorBoard：`d_tbOpen` · `d_tbTab("SCALARS")`
研究台：`rsTab("formula")` · `rsChat[]` · `rsDraft` · `rsBusy` · `rsImported(null)` · `rsPickerOpen`

绑定变量是 `renderVals()` 派生（数百个 `d_*`/`bd*`/`rs*`/`g_*`/`rd_*` 前缀），非裸 state——React 落地时应做成**派生 selector / view-model 层**，不要把每个 `{{}}` 都当 state。

### TS interface 草拟（落地建议）

```ts
type Family = "ml" | "dl" | "code" | "mixed";
type JobStatus = "queued" | "running" | "succeeded" | "failed";
type Stage = "dev" | "staging" | "production" | "archived";

interface TrainJob {                       // 作业台（扩展现有 Job）
  job_id: string; name: string; model: string; family: Family;
  task: string; status: JobStatus; arch: string;
  metrics: Record<string, number>; elapsed_seconds?: number|null;
  error?: string|null; tensorboard?: boolean;
  detail: JobDetail;                        // ← 设计新增:动机/设计富文档
}
interface JobDetail {                       // why/data/window/label/design/arch/hparams
  why: string; data: string; window: string; label: string;
  design: string; arch: string; hparams: string;
  sections?: [string,string][];             // 设计细节逐项
  io?: IoSpec;                              // 输入输出规格(单一来源)
}
interface IoSpec {
  inCount: number; outCount: number;
  inGroups: { group: string; type: string; fields: string }[];
  outGroups: { group: string; type: string; fields: string }[];
  inSrc?: string; inPre?: string; outNote?: string;
}
interface RegistryModel {                   // 模型库卡(扩展 ModelVersion)
  id: string; version: number; family: Family; task: string;
  stage: Stage | null; ndcg: string; wf: string;
  lineage: string; gist: string; archGist: string; ioGist: string;
  trained: string; canPromote: boolean; note: string;
}
interface PromoteGate {                     // 晋级审批门
  model: string; from: Stage; to: Stage;
  checks: { icon: string; color: string; t: string }[];
}
interface WfWindow { w: string; seg: string; ret: string; ndcg: string }

// ---- 构建台图编辑器 ----
interface GraphNode {
  id: string; type: AtomType | "module"; x: number; y: number;
  params: Record<string, number|string>;
  label?: string; mech?: string; inner?: string[];
  sub?: { nodes: GraphNode[]; edges: Edge[] };   // 模块内部子图(可嵌套)
}
type Edge = [string, string];
type AtomType = "input"|"linear"|"conv1d"|"lstm"|"gru"|"embedding"
  |"batchnorm"|"layernorm"|"dropout"|"matmul"|"transpose"|"scale"|"softmax"
  |"mask"|"add"|"mul"|"concat"|"split"|"pool"|"relu"|"gelu"|"silu"|"tanh"
  |"head"|"output"|"src_factor"|"src_series"|"src_text"|"src_alt"
  |"pre_zscore"|"pre_winsor"|"pre_fillna"|"pre_neutral"|"pre_rank"
  |"llm_feat"|"embed"|"post_rank"|"post_neutral"|"post_weight"|"post_topk";
interface AtomDef {                         // _NT() catalog
  label: string; cat: string; dot: string;
  params: Record<string, any>;
  info: { what:string; math:string; use:string; combo:string; scene:string };
  llm?: boolean;
}
interface Mechanism {                       // _mechanisms() 9 个机制模块
  key: string; label: string; params: Record<string,any>;
  info: AtomDef["info"]; sub: { nodes: any[]; chain: Edge[] };
}
interface TrainComponent {                  // optimizers/losses/scheds
  key: string; label: string; custom?: boolean; info: AtomDef["info"];
}
type ParamScope = "独立" | "共享" | "覆盖";

// ---- 研究台 ----
interface ImportedArch {
  layers: { label:string; expr:string; shape:string }[];
  checks: { icon:string; color:string; t:string }[];
  conclusion: string; ok: boolean;
  kind: "graph"|"module"|"mech"|"model"|"paper"|"article";
  name: string; source: string;
}
interface Paper { title:string; venue:string; arxiv:string; gist:string; transfer:string }
```

---

## ④ 交互清单（所有 handler 行为）

**全局/导航**
- `goJobs/goRegistry/goBuild/goResearch` → 切 `view`；`newJob` → 跳 jobs 视图 + 选 trn-5d18。
- `componentDidMount` 启 `setInterval(360ms)` 推 `epoch++` 直到 `_epochTotal=60`，到顶停 `running`（驱动 hero 作业 trn-7c41 的实时曲线 mock）。

**作业台**
- `jobsToggle/mtToggle` 折叠队列/助手栏。
- job `select` → setState selJob。
- `d_tbToggle` 开关 TensorBoard 嵌入；`d_tbTabs[].on` 切 TB tab；`↗新窗口`→`localhost:6006/?run={selJob}`。
- `d_ioToggle` 展开 IO 字段；`d_publish` → published=true（"发布到模型库 dev"）。
- "查看完整回测详情↗" → 外链 `回测详情.dc.html`。
- 助手 `_ask(q)` → 正则匹配 6 类问题（过拟合/early-stop/选型/超参/数据切分/OOM）本地应答；`onChatKey`(Enter 发送)；追问 chip `ask`。

**模型库**
- 卡 `open`/`查看详情›` → `regDetail`=id 打开 DRILL-IN 浮窗；`rd_close`/`rd_wfToggle`(逐窗明细)/`rd_ioToggle`。
- `promote` → 设 `gate{model,from,to}` 开审批门；`g_approve` → `regStage[model]=to` + 关门；`g_cancel`。

**构建台（交互最密集）**
- 画布：`_canvasDown`（空白拖拽平移 / ⇧框选 marquee）；`_wheel` 缩放 0.3–2.2；`_resetView`(100%)。
- node：`_nodeDown`(拖动) · `select`（Edit 选/Markup 标注/⇧多选）· `dbl`/`toggleExpand`（module 双击进入 `_enterModule`，atom 展开内部）· `remove`(✕) · `_setParam`(编辑参数实时联动 shape+code) · `portOut/portIn`(端口连线 `bdLinkFrom`)。
- module：`_enterModule`/`_exitModule`（进出子图编辑，面包屑）。
- palette：原子 `add`→`_addNode`；机制 `add`→`_addMechanism`；`showInfo`→`bdInfo` 信息卡；自定义模块 `add`(克隆 sub)/`remove`。
- 模块化：`_registerModule`(选中→命名 modal)→`_confirmRegister`（框选子图打包成可复用模块，保留内部子图）。
- 工具栏：`bdTool` 切 Markup/Comments/Edit/Share；`bdAutoLayout`(⊞整理:拓扑分层布局)；`bdRegisterModule`。
- 训练组件：`bdOptims/bdLosses/bdScheds[].pick` 选中（写 config.yaml）；`info`→信息卡；`bdRegOptim/Loss/Sched`→注册 modal→`_registerTrain`（**用数学公式定义即注册**）。
- 超参：`bdHparamRows[].onInput`→`_bdHp`；多模型作用域 `m.cycle`→`_bdScopeCycle`(独立↔共享↔覆盖)；`bdShareToggle`(全局共享 lr)。
- LLM 试一条：`n.llmTry`→`_llmTry` **真调** `window.claude.complete(prompt)`（文本→情感/事件/因子值 JSON）。
- 代码：`bdToggleCode`；`bdGenCode`/`_genCode`（5 步动画:解析图→拓扑→形状→生成 nn.Module→深度校验，产 `bdCodeSnap`）；`bdRunGate`→`bdGateOpen`→`bdGateYes`/`_bdSubmit`(落作业台 trn-8f30)。
- agent chat：`_bdAsk` 识别"刷新代码"→`_genCode`；识别"加X机制"→propose 确认→`_confirmAddMech`（自动接链+autoLayout）。
- 分栏拖拽：`bdSplitChat`/`bdSplitCode`（pointermove 调宽）。

**研究台**
- `_rsAsk`(理论判定本地应答)；`rsImport`→`rsPickerOpen` 选研究对象 picker。
- `_importSource(kind,key)`：canvas(当前画布提数学+可行性 `_extractGraph`) / module / mech / model(树模型改判 IC) / paper(LLM 提炼数学) / article(LLM 提炼可证伪假设) / blank。
- `_extractGraph`：拓扑排序→逐层 math+shape→可行性 checks（维度自洽/梯度可传/数值稳定 √d_k/形状 Transpose/复杂度）→结论 ok。
- `rsGoFormula/rsGoPapers` 切 tab；`rsToBuild`/`rsSendBack`→去构建台；`rsImpBad` 时"把修正建议发回构建台"。

---

## ⑤ 治理/业务元素专章（与硬不变量/GOAL 对齐）

设计稿对治理的呈现**与 dev/RULES + GOAL 高度一致**，是真正的 load-bearing 部分：

1. **晋级审批门（对齐 GOAL §7 M12 + §2 审批门 + INV-5）**
   - 文案显式："dev → staging → production → archived（staging/production 须审批门，不可裸翻）"。
   - 门头徽章 **"realmoney · 不可裸翻"**（红 `#d99a8e`/`#6a4030`）。
   - 正文："须人工审批 + 验证背书（INV-5），**agent 永不自动**"。
   - checks 清单含：walk-forward/Purged-CV 通过、OOS 切片未被探索期触碰、(→production)"缺：staging 实测 ≥2 周 + 验证背书"。
   - **对照后端**：`/api/models/{id}/promote` 已实现 dev/archived 直翻、staging/production 开门，approve 要求 `approver≠creator`(`ApproverEqualsCreator`)、`EmptyReason`、`risk_restated`，并叠加 T-024 假设卡血缘门（confirmatory `can_touch_final_oos`，非 confirmatory 走真钱 409 拒）。**设计稿的"批准晋级"按钮缺 approver≠creator / reason / risk_restated 字段——落地必须补，否则后端 422。**

2. **防数据泄露（对齐 GOAL §9 致命错误 + §4）**
   - Purged k-fold · embargo 1% 卡（标"防标签穿越"）；动机卡"防数据泄漏"段；助手解释"embargo 1%≈2-3 交易日，覆盖 fwd_ret_5 前视窗"。
   - 训练窗口 OOS：现有前端已有 `trainFraction`（严格无泄露 walk-forward），设计稿用 walk-forward 逐窗明细（每窗真·样本外）呼应。

3. **样本外诚实标注（对齐 GOAL §6 弱点一等呈现）**
   - 现有前端回测面板已区分 in-sample/OOS·跨数据集/严格无泄露/时间后段，黄绿徽章。设计稿 walk-forward "8/8 窗口正"、OOS 超额逐窗。

4. **lineage / append-only（对齐 GOAL §7 M12 + §8 S4）**
   - 每卡显式 lineage（trn-9a2f · 因子集 fs_core3）+ trained 日期；"发布即登记 dev → 接审批门可升 staging"。后端 `/api/experiment_runs/{id}/lineage` 已存在。

5. **agent 受控触手（对齐 GOAL §7 M14 + RULES agent 三态）**
   - 构建台 agent "先确认再动手"（propose→确认 `_confirmAddMech`）；研究台 LLM 只提炼/判定不下结论；文章观点强制"先在因子台做 IC+单调性+OOS 检验，QUALIFIED 后再入模型"——呼应 M11 因子生命周期门。
   - **后端已有** `/api/training/agent_context`（约束 agent 只能在模型卡内选）+ `/api/training/models`(POST 加卡 runnable=False)，与设计稿"agent 只能卡内做，除非用户让它搜新模型加卡"一致。

6. **主进程不碰 torch（对齐 GOAL §7 M6 硬约束）**
   - 设计稿明示"DL：隔离全功率子进程跑 torch，自动选 GPU(cuda/mps)/CPU"；算力卡"torch 子进程✓"。与现有 `training/lib.py pick_device()` + `runner.py run_code()` 子进程一致。

---

## ⑥ Design tokens 差异（与策略台 `#1c1b19/#d97757/JetBrains Mono` 对比）

| token | 策略台基准 | Model台 | 是否一致 |
|---|---|---|---|
| 画布底色 | `#1c1b19` | `#1c1b19` | ✅ 完全一致 |
| 强调橙 | `#d97757` | `#d97757`（保留:✳/loss train线/why左边框/user prompt`>`） | ✅ 保留但**降级为辅色** |
| 字体 | JetBrains Mono | JetBrains Mono(400-700) | ✅ 一致 |
| 选区 | rgba(217,119,87,.28) | 同 | ✅ |
| 滚动条 | `#3a3733` thumb | 同 | ✅ |
| **主强调色** | 橙 `#d97757` | **蓝 `#6f9bd1`**（台标识、按钮、链接、端口） | ⚠️ **差异:Model台改用蓝做主色** |
| 面板底 | `#191815`/`#1a1916` 系 | 同系 | ✅ |

**关键差异结论**：Model台**故意用蓝 `#6f9bd1` 作为台标识主色**（区别于策略台的橙），橙降为辅助强调。这是**有意的台级配色区分**（因子台/策略台/模拟台各有标识色），不是不一致。落地时前端的 `--cc-accent` 在 Model台路由下应有蓝色覆盖，或新增 `--cc-model-accent: #6f9bd1`。其余 token（底色/字体/边框/圆角谱/滚动条/选区）与现有 `cc-*` CSS 变量体系完全兼容——现有 `TrainingBenchPage.tsx` 已用 `var(--cc-accent)/var(--cc-info)/var(--cc-success)/var(--cc-danger)` 等，设计稿的硬编码色值需映射到这套变量（如 `#9bbd5a`→`--cc-success`、`#6f9bd1`→`--cc-info`、`#d9b25f`→`--cc-warning`、`#d97066`→`--cc-danger`）。

设计稿引入的**新增色语义**（现有 cc 体系未必有，需扩充）：机制青 `#6fb0c8`、模块紫 `#b89cd8`/`#c08adb`、TensorBoard 橙 `#e6883a`、张量算子橙 `#d98c6f`、stage 黄 `#d9b25f`。

---

## ⑦ 对应现有前端页面 + 落点建议 + 后端缺口

### 现有前端（graphify 定位）
- `app/frontend/src/pages/models/TrainingBenchPage.tsx`（route `/training`，App.tsx L13/L71）—— 三栏配置/代码预览/模型卡 + 底部任务表 + 评价图面板（`EvalCharts`）。
- `app/frontend/src/pages/models/ModelLibraryPage.tsx`（route `/models`，L14/L72）—— 极简：`/api/models` 列表 + 展开版本表（v/stage/指标/来源run/时间）。
- `app/frontend/src/pages/ExperimentTrackingPage.tsx`（route `/experiments`，L67）—— 实验追踪（M12 前端）。
- 共享组件 `app/frontend/src/components/charts/EvalCharts.tsx`。

### 设计稿四子台 vs 现有页面映射

| 设计子台 | 现有页面 | 落点建议 |
|---|---|---|
| **作业台 (jobs)** | `TrainingBenchPage.tsx` | **增强 + 部分重构**。现有页是"配置→提交"的输入台；设计稿作业台是"看板优先"的**监控台**（队列+实时曲线+算力+CV folds+动机文档+助手）。建议：把现有的左栏配置（数据/模型/特征/超参/OOS）保留为"新建训练" modal/抽屉（设计稿 ＋新建训练按钮）；主体重构为设计稿的三栏看板。现有 codegen 预览、回测面板、EvalCharts 可复用并入 dashboard。 |
| **模型库 (registry)** | `ModelLibraryPage.tsx` | **大幅增强**。现有仅列表+版本表；设计稿是 2 列富卡 + stage 胶囊 + 晋级门 + DRILL-IN 浮窗（动机/IO 规格/walk-forward 逐窗）。建议在 `ModelLibraryPage` 基础上扩展，接 `/api/models/{id}/promote` + gate approve/reject。 |
| **构建台 (build)** | **无对应页面** | **全新建** `pages/models/ModelBuildPage.tsx`。draw.io 式图编辑器（节点/连线/缩放/平移/框选/模块嵌套/代码双向）。这是设计稿最大的新增面（~800 行交互逻辑），工作量最大。 |
| **研究台 (research)** | **无对应页面**（`/agent`、`/factors` 部分相关） | **全新建** `pages/models/ModelResearchPage.tsx`。理论判定 + 论文调研 + 公式工作台。 |

**路由建议**：设计稿是单页四 tab。落地两种方案——(a) 单路由 `/training` 内 sub-tab（贴合设计稿，App.tsx 不动）；(b) 拆 4 路由 `/models/jobs|registry|build|research`（更 React-router 风）。推荐 (a) 子 tab，因为四子台共享 family/stage 配色、模型卡数据、台切换器，且设计稿状态机就是 view 切换。`/models` 旧路由可重定向到 registry tab。

### 后端端点缺口（设计稿需要 vs 已存在）

**已存在、可直接用**：
- `/api/training/models`(GET 目录) · `/api/training/models/{key}`(GET 详情 `to_detail` 含 body) · `/api/training/models`(POST 加卡) · `/api/training/agent_context` · `/api/training/datasets` · `/api/training/codegen`(POST) · `/api/training/jobs`(GET/POST) · `/api/training/jobs/{id}`(GET/eval/backtest/tensorboard GET+POST) · `/api/models`/`{id}/versions`/`{id}/promote` · `/api/models/{id}/gates/{gate_id}/approve`+`/reject` · `/api/experiments`(GET/POST)/`{id}/runs` · `/api/experiment_runs/{id}/lineage`。

**缺口（设计稿要、后端没有）**：
1. **作业台动机/设计富文档（`JobDetail`）**：设计稿每个 job 有 why/data/window/label/design/arch/hparams + 设计细节 6 段 + IO 规格。后端 `TrainingJob.to_dict()` 当前只有基础字段（status/metrics/elapsed/error/tensorboard）。**缺**：训练提交时持久化 motivation/design 文档，并在 `to_dict` 暴露。
2. **IO 数据规格（`IoSpec` 单一来源）**：设计稿 `_ioSpec()`（28 入/3 出、6 分组字段）在 dashboard/registry/canvas io 节点三处共用。后端 `ModelCard` 当前**无 input/output 字段规格**（只有 pros/cons/tuning/param_schema/persistence）。**缺**：模型卡 frontmatter 加 `io_spec`（in_groups/out_groups/in_pre/out_note），`card_loader.py` 解析 + `to_dict` 暴露。
3. **walk-forward 逐窗明细**：设计稿 DRILL-IN 有逐窗（训练段→测试段/OOS超额/NDCG）。后端有 lineage/eval/backtest 但**无 walk-forward 逐窗结果端点**。**缺** `/api/training/jobs/{id}/walkforward` 或 model version 的 wf 明细。
4. **构建台图→代码（最大缺口）**：`bdNodes/bdEdges`→`nn.Module` codegen、形状推断、注意力校验、提交训练。现有 `/api/training/codegen` 只接 `{model,task,feature_cols,...}` 结构化 spec（卡内模型），**不接任意图 JSON**。**缺**：①图 schema 持久化端点 ②图→代码 codegen（设计稿现在是纯前端 mock，真落地需后端或 WASM）③自定义模块/优化器/损失/调度注册（写 config.yaml）④图提交训练（落作业台）。**注意 GOAL §7 M6"主进程不碰 torch"——任意图编译训练仍须走子进程 harness。**
5. **研究台理论判定 / 论文调研 / LLM 提炼**：`_extractGraph`(维度自洽/梯度/√d_k/复杂度判定)、论文 LLM 提炼数学、文章提炼可证伪假设。现有**完全无后端**（前端 mock + `window.claude.complete`）。**缺**：①图理论可行性判定端点 ②论文/文章导入→LLM 提炼端点（且产出须导向因子台 IC 检验，对齐 M11）。
6. **TensorBoard 真实嵌入**：设计稿 SCALARS 为 mock 曲线，标注"后端写 event 到 logdir，前端按 run 嵌入 iframe"。后端 `/api/training/jobs/{id}/tensorboard`(POST 启动/GET url)已存在——**前端按 run 嵌入 :6006 iframe 需对接，HISTOGRAMS/GRAPHS/HPARAMS tab 当前是占位**。
7. **暂停训练**：设计稿运行态有 ⏸暂停按钮，后端**无 pause 端点**（只有提交/查询）。
8. **promote gate 字段补全**：设计稿"批准晋级"按钮须补 `approver`/`reason`/`risk_restated`（后端强制），否则 422。

### 落地优先级建议
1. **P0 增强**（复用后端、低风险）：作业台看板重构（队列+曲线+算力，对接现有 jobs/eval/tensorboard）、模型库富卡+晋级门（对接现有 promote/approve）。
2. **P1 后端补字段**：JobDetail 富文档、ModelCard IoSpec、walk-forward 逐窗。
3. **P2 全新大件**：构建台图编辑器（前端先做交互+前端 mock codegen，后端 harness 编译为后续里程碑）、研究台（前端 + LLM 提炼端点）。构建台/研究台落地须保 M6 子进程隔离 + M11 因子门 + M12 lineage 三条治理线。

---

**关键文件绝对路径汇总**
- 设计稿：`/tmp/qbt-handoff/quantbt-claude/project/Model台.dc.html`（运行时 `/tmp/qbt-handoff/quantbt-claude/project/support.js`）
- 现有前端：`/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/pages/models/TrainingBenchPage.tsx` · `.../ModelLibraryPage.tsx` · `.../ExperimentTrackingPage.tsx` · `/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/components/charts/EvalCharts.tsx` · 路由 `/Users/wzy/Work/01_Projects/QuantBT/app/frontend/src/App.tsx`(L13-14,L71-72)
- 后端：`/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/main.py`（training 路由 L714-893、experiments/models L444-551）· `/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/models/catalog.py` · `/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/models/card_loader.py`(ModelCard L32-118) · `/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/training/`(service/codegen/runner/lib/backtest_bridge) · `/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/experiments/store.py`(ExperimentStore/RunStore/ModelRegistry/ModelStage)
- GOAL：`/Users/wzy/Work/01_Projects/QuantBT/dev/GOAL.md`（§7 M6 L64 / M12 L69，§9 L80-86）