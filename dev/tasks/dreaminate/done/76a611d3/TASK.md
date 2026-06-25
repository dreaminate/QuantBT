---
uuid: 76a611d3d26c42f495a7d7a29d5e5319
title: ResearchGraph IR——QRO 节点 typed 图 + 各台 typed projection + 单一真相源（A-GRAPH-1）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: research-graph
source: goal
source_ref: GOAL §1 统一对象链(Quant Intent→Canvas→QRO→Research Graph→Compiler)·§2 多台工作系统(每台 Canvas=同一 Research Graph 的 typed projection·单一真相源)；施工图 LINE-A 续(QRO 已出契约)
depends_on: [f19c5c192f4a44cc95fd159ea04d94e5]
branch: wave3/line-a-graph-1
---

# Research Graph IR（A-GRAPH-1·LINE-A 续·阻塞 Compiler/Command/各台）· 完成卡

## Scope（交付内容）
A-QRO-1（f19c5c19）已出 QRO 统一信封。本卡交付 GOAL §1 链里 **QRO → Compiler 之间的 IR**：
一张 typed 图，**只读收编** QRO 节点（`qro/envelope`）+ 边（lineage/dependency/DeskHandoff）+
**各台 typed projection**（§2「每台 Canvas = 同一 Research Graph 的 typed projection」）+ **单一真相源
不变量**（§2「任一台维护独立真相状态 → 拒」）+ **canonical command 落点**（§2「user 手动改动未落
canonical command → 拒」）。全部在 greenfield `app/backend/app/graph/`，**收编只读**（不改 qro/ids/spine）。
**未建**：Governed Compiler（A-COMPILER 另卡）、CanonicalCommand 全栈翻译（A-CMD 另卡）、前端 Canvas。

## 新建文件（greenfield·只动 graph/ + 自己的测试/done 卡）
- `app/backend/app/graph/research_graph.py` — Research Graph IR：台/边/交接/命令词汇 + `HOME_DESK_OF`
  写权限单一源（import 期自检全覆盖 OBJECT_TYPES）+ `DeskHandoff`/`GraphNode`/`GraphEdge`/`CanonicalCommand`
  数据类 + `ResearchGraph`（单写路径 `apply` + 单一真相源门 + 各台投影）+ 七门 + 异常族。
- `app/backend/app/graph/__init__.py` — 公共 API 再导出。
- `app/backend/tests/test_research_graph.py` — 60 条对抗式测试。

## 实现要点

### 1. IR 图结构（持有信封·不另存状态·内容寻址身份单一源）
- **节点 = QRO**：`GraphNode` 持有 `qro/envelope.QualifiedResearchObject`（frozen·只读收编），
  `node_id == qro.identity`（复用信封身份·**绝不另造**）。真相态（六轴）只存图里一份。
- **边**：`GraphEdge`（lineage/dependency/desk_handoff），`edge_id = "edge_"+content_hash({src,dst,edge_type})`。
- **交接**：`DeskHandoff`（§2 字段 verbatim：from/to_desk·requested_asset·blocking_dependency·status·
  produced_ref·evidence_refs·created_by·resolved_by），`handoff_id = "handoff_"+content_hash(...)`。
- **命令**：`CanonicalCommand`（command_type·actor·target_desk·payload·origin），
  `command_id = "cmd_"+content_hash(...)`。**全部走单一源 `lineage.ids.content_hash`**，前缀 `edge_`/
  `handoff_`/`cmd_` 同 spine.py `math_`/`tib_`/`cc_` 与 qro `qro_` 范式——**绝不另造哈希算法**。

### 2. 单一真相源（命门 #1·GOAL §2）
- 结构性保证：真相态唯一份存图节点；`node_state(node_id)` 是计算真相态的**唯一**函数（投影与单一源门
  共用它·绝不两处各算一套）；`DeskProjection`/`NodeView` 是**派生只读视图**·不持独立可写副本 → 结构上
  不可能与图漂移。
- 可证伪探针：`assert_single_source(desk, claimed_states)` —— 某台呈上的私有真相态若 ≠ 图（唯一源）即拒；
  `assert_single_source_across_desks(...)` 多台版 = 卡对抗规格 verbatim「构造两台不同状态 → 必抓矛盾」
  （图为仲裁者，任一台漂离即拒）。

### 3. canonical command 落点（命门 #3·GOAL §2·非 A-CMD 全栈）
- **唯一公共写口 = `ResearchGraph.apply(command)`**——`_nodes/_edges/_handoffs` 私有、无第二条裸写路径；
  落任何元素都 stamp `command_ref = command.command_id` 并 append 进 append-only 命令账。
- 可证伪探针：`assert_commanded()` —— 每个图元素 command_ref 必须 ∈ 命令账；绕 apply 裸插节点（维护图外
  状态/未落命令）即被抓。`CanonicalCommand` 仅定**落点最小信封**（actor∈四类·内容寻址 id），语义翻译/解析
  归 A-CMD。

### 4. typed contract 进图门（命门 #2·GOAL §1）
- `_admit_qro`：图是 §1 链 chokepoint，**独立 re-assert** 信封不变量（不盲信上游）——非 QRO 对象（裸
  dict/duck）进图即拒；signal/forecast 缺 typed contract 即拒（复用信封 `CONTRACT_REQUIRING_TYPES`·单一源·
  不另定一套）。`_payload_digest` 鲁棒化（畸形 payload 退化 repr·不让 command id 计算崩在构造期，准入拒绝
  归 `_admit_qro` 出诚实文案）。

### 5. 各台 typed projection + 写权限隔离（命门 #5/#6/#7·GOAL §2）
- **写权限单一源 `HOME_DESK_OF`**：对象类型 → 唯一 home（写权限）台，覆盖全 41 类 OBJECT_TYPES
  （import 期自检·漂一类即 fail-fast）。命门 #5：`apply` 写某对象时 `target_desk` 必须 == home 台 →
  策略台直接写 Factor → `WriteAuthorityViolation`（§2 verbatim）。边形态：加 src 出边 = 写 src 依赖/血统
  → 按 src 的 home 台判（放行「策略台加 strategy→factor 依赖引用」·拦「策略台改 factor 出边」）。
- **投影**：`project(desk)` 派生只读视图，当前台决定可见节点/边/交接 + **可编辑类型**（editable = home 台·
  由 HOME_DESK_OF 派生）；六轴 + theory/consistency/mathematical_refs/tib 恒从 QRO 投进 `NodeView`（单一源）。
- 命门 #6：`project(claims_institutional=True)` / `assert_institutional_projection` —— 声称机构级方法的投影
  缺 math/consistency 轴 → `ProjectionError`；未声称机构级的台可精简视图（**不误伤**·§2 当前台决定可见内容）。

### 6. DeskHandoff 完成完整性（命门 #4·GOAL §2）
- `DeskHandoff.__post_init__`：status=resolved 缺 produced_ref → `HandoffIncompleteError`（构造期即拦·无法绕）；
  rejected 态无需 produced_ref（不误伤）；created_by/resolved_by 非空必 ∈ 四类 actor。交接经 open/resolve
  命令落图（命门 #3 凭证），resolve 走 `replace` 产新 resolved 实例（frozen·不原地改）。

## 对抗测试（种坏门必抓·mutation 定点验证·RULES §2）
真测试汇总行：**`60 passed in 0.05s`**（`tests/test_research_graph.py`）。
基线（本 worktree·origin/main 基）：`pytest --collect-only` **1900 → 1960（+60，纯增量，零 collection error）**
（与卡所述「当前 main collect ~1900」吻合）。import `app.graph` = 0.022s（零重依赖·不拖 polars/sklearn/torch）。

6 次定点变异（反向 edit→必红、还原→必绿，**全程脚本内存改写+还原·不碰 git checkout**，还原后源与原始逐字节一致）：
| MUT | 关掉的门 | 命中测试 | 结果 |
|---|---|---|---|
| #1 | **单一真相源轴比对**（`if divergent:`→`if False`） | `test_desk_divergent_state_rejected` + `test_two_desks_conflicting_state_caught` | 2 RED → 还原 GREEN |
| #2 | typed-contract 进图门 | `test_signal_node_without_typed_contract_rejected` | 1 RED → 还原 GREEN |
| #3 | **落命令凭证完整性**（`assert_commanded` 节点检查） | `test_smuggled_node_caught_by_assert_commanded` | 1 RED → 还原 GREEN |
| #4 | DeskHandoff produced_ref 门 | `test_resolved_handoff_without_produced_ref_rejected` + `..._command_without_produced_ref_rejected` | 2 RED → 还原 GREEN |
| #5 | **写权限按台隔离**（`if target_desk != home`） | `test_strategy_desk_cannot_write_factor` + `test_non_home_desk_write_rejected`×5 + 边/update 越界 | 8 RED → 还原 GREEN |
| #6 | 机构级投影 math/consistency 门 | `test_institutional_projection_missing_math_axis_rejected` | 1 RED → 还原 GREEN |

**六门对应卡四命门 + §2 两门**：#1 单一真相源（卡①）/ #2 typed contract 进图（卡②）/ #3 canonical command
落点 + #4 handoff produced_ref（卡③）/ #5 写权限隔离（§2「策略台写 Factor→拒」）/ #6 机构级投影
（§2「Canvas 无 math/consistency projection→拒」）。卡④（投影正确·不误伤）由 happy-path 测试群守
（editable 仅 home 类型·六轴如实投影·跨台引用放行·非机构级精简放行·收编只读不改 QRO）。

## 红线合规（逐条）
- **单一身份源 ids.py 不另造**：node_id = qro.identity（复用信封）；edge/handoff/command id 全走
  `content_hash` + 前缀（同 spine/qro 哈希族）。✅（测 `test_node_id_is_qro_identity` / `..._edge_id_content_addressed` / `..._handoff_id_content_addressed`）
- **扩展不替换（收编 qro 不改）**：qro/envelope/ids/spine **一字未改**；只新增 graph/ + 测试。收编走只读
  import + duck 准入。图存的就是原 QRO 对象、frozen 未被改写（测 `test_graph_does_not_mutate_incorporated_qro`）。✅
- **单一真相源（任一台独立状态→拒）**：结构性（派生只读投影）+ 探针（`assert_single_source*`）双保险；
  MUT #1 证门非纸。✅
- **不破基线**：纯增量 1900→1960、0.022s import 不拖重依赖、不触 main.py / qro/ / 其他在飞线领地。✅
- **不碰共享单文件**：未动 state/log/board/DEVMAP/GOAL/pool/其他卡目录/main.py/qro。git status 仅
  `app/graph/`（新）+ `tests/test_research_graph.py`（新）。✅
- **先读 GOAL §1/§2 再动手**：动手前 grep+读 GOAL §1（行 60-191）+§2（行 192-263）+ RULES + RULES.project
  + qro/envelope + ids + spine + 施工图 + 相关 decisions（D-PERM/D-SCOPE-CONSERVATIVE）。✅

## 拍板项命中（语义岔路·诚实点名·未停工·留痕供中心）
- **infra 类对象 home 台切分（integration_config / data_source_asset / secret_ref / token_ref）**：GOAL §2
  数据台与设置台**都**列 Integrations / Data Sources（能力面重叠），但未明定这几类的**写 home 台**。
  **裁定（未停工·照建·可逆）**：按**主责**切分——连接/凭据/Provider 配置层（integration_config/secret_ref/
  token_ref/llm_*）归**设置台**、数据语义/质量/版本层（dataset/observable/data_source_asset/ingestion_skill/
  dataset_version/...）归**数据台**。依据：§2 设置台明列「Integrations/Secrets/LLM Providers/Credential
  Pools/Routing」=连接凭据配置面；§1「SecretRef 明文只存 Settings/Secrets 安全后端」=凭据归设置台。
  **为何未升级为停工拍板**：① 卡 §2 **明确命名**的写隔离门（「策略台写 Factor→拒」）无歧义、已实现并过
  MUT；② 此项仅 `HOME_DESK_OF` 一条 dict 项、**完全可逆**、下游只读不破坏；③ 同 A-QRO-1「4 vs 6 轴」
  precedent（GOAL 已定主体·残余是可逆细节→flag 不 stop）。**中心若有不同读法，改一条 dict 项即可重 pin。**

## 诚实残余（会变任务·非设计极限·A-COMPILER/A-CMD 接续）
- **A-COMPILER 接续**：本卡是 QRO→Compiler 之间的 **IR 图**；Governed Compiler（消费 IR → Deterministic
  Run → Evidence Verdict）**未建**。IR 只承载信封状态 + 单一真相源/单写路径/typed projection 结构，**不判**
  evidence 是否真充分 / 理论是否真证明 / 一致性是否真成立（归 verification / spine_gate / Compiler）。
- **A-CMD 接续**：`CanonicalCommand` 仅是**落点最小信封**（actor∈四类 + 目标台 + 内容寻址 id + payload）；
  canonical command 的**语义翻译 / 解析 / 全栈校验 / 来源面（canvas/form/IDE/API）细化**归 A-CMD。
- **写权限是对象定义级·轴级权限待下游**：本卡实现「哪个台能创建/编辑某类对象本体」（命门 #5）。**轴级**写
  权限（执行台推 runtime ladder、回测台动 evidence、审批台动 governance——一个非 home 台合法地迁移另一台
  所有节点的某轴）是治理/各台的活，归 A-COMPILER / 执行·治理台卡，**本卡未做**（per-object 足以守 §2 命名
  的「策略台写 Factor formula→拒」definitional 写隔离）。
- **infra 类 home 台切分**：见上「拍板项」——defensible 默认已落，待中心确认/重 pin（可逆）。
- **produced_ref 引用完整性**：命门 #4 守「resolved 必带非空 produced_ref」（§2 verbatim）；未强制 produced_ref
  必为图内已存节点（避免管太宽·D-SCOPE-CONSERVATIVE·produced_ref 可为外部资产 ref）。图内引用校验待下游需求。
- **graphify 图未刷**：按任务线纪律不跑 /skill；图谱更新归中心整合期（graphify-out/ 本就 gitignore）。

## 诚实限界（设计极限·不会再改）
- IR 是「持有信封 + 单写路径 + typed 投影 + 不变量门」的结构容器。它**不**判语义真值（证据/理论/一致性的
  真伪），**不**替代 Compiler / spine_gate / verification。单一真相源门保证「无台持图外可写真相」，**不**保证
  图里的状态本身正确（那是上游写命令 + 下游验证的责任）。
- 单一真相源以**图为仲裁者**：不存在「两台都对、图错」的合法态——图就是真相定义。台只能呈与图一致的派生
  视图，或经命令改图（改后仍单一源）。

## 验证状态（🟡≠✅）
- ✅ 已验证（本地实跑）：scoped 60 测试绿、6 次 mutation 全红再还原绿（源逐字节还原）、import 隔离 0.022s、
  collect 1900→1960 零 error、HOME_DESK_OF import 期自检全覆盖 OBJECT_TYPES。
- 🟡 未验证（归中心）：全量套件未跑（任务线纪律·只跑 scoped）；与下游 A-COMPILER（Compiler 消费 IR）/
  A-CMD（命令翻译）/ 各台前端 Canvas 投影的集成未接线（本卡是 IR 地基·下游卡接续）。中心负责整合 + 全量 + land。
