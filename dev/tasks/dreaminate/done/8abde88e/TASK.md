---
uuid: 8abde88e406544e990d7cdf352740f23
title: CanonicalCommand 全栈——typed 命令通道 + 语义翻译 + 全栈校验 + provenance（全入口落同一 audit/lineage·A-CMD）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P0
area: canonical-command
source: goal
source_ref: GOAL §1(链 Typed Canvas/Command→QRO→Research Graph)·§2(user 手动画布/表单/IDE/API 改动都落 canonical command·与 Agent 动作进同一 audit/lineage/lifecycle·user 手动改动未落 canonical command→拒)；A-GRAPH-1 落最小命令信封+图写口·语义翻译/全栈校验/provenance 归本卡
depends_on: [76a611d3d26c42f495a7d7a29d5e5319]
branch: wave4/a-cmd
---

# CanonicalCommand 全栈（A-CMD·LINE-A 续·写 Research Graph 唯一治理通道）· 完成卡

## Scope（交付内容）
A-GRAPH-1（76a611d3）已落**命令最小信封**（`research_graph.CanonicalCommand`：四类 actor + 目标台 +
内容寻址 id + payload）与图写口 `ResearchGraph.apply(command)`。本卡在写口**之前**交付 GOAL §2「user 手动
画布/表单/IDE/API 改动都落 canonical command·与 Agent 动作进同一 audit/lineage/lifecycle」的 **CanonicalCommand
全栈**：① **typed 命令层**（`CommandBus`·写 Research Graph 的唯一通道·user 手动 + agent 同源）② **语义翻译/
解析**（intent/canvas action → typed command）③ **全栈校验**（actor 四类 / 目标台 / 内容寻址 id / **payload
schema**）④ **provenance**（来源面 canvas/form/ide/api/agent_runtime/scheduler + 同一本 audit/lineage 账·
user 手动与 agent 同链）。全部在 greenfield `app/backend/app/command/`，**收编只读**（不改 graph/qro/ids）。
**未建**：Governed Compiler（A-COMPILER 另卡·消费命令 → run）、前端 Canvas 交互。

## 新建文件（greenfield·只动 command/ + 自己的测试/done 卡）
- `app/backend/app/command/canonical_command.py` — 全栈：来源面 + actor↔来源面相容表 + 语义动作翻译表
  （import 期三张表全覆盖自检）+ `Provenance`/`CommandIntent`/`LedgerEntry`/`CommandReceipt` 数据类 +
  `validate_intent`/`translate_intent`/`assert_content_addressed`/`assert_actor_surface_coherent` 门 +
  `CommandLedger`（一本账）+ `CommandBus`（唯一写口 `submit` + 通道唯一探针 `assert_single_channel`）+ 异常族。
- `app/backend/app/command/__init__.py` — 公共 API 再导出。
- `app/backend/tests/test_canonical_command.py` — 57 条对抗式测试。

> **测试落点说明（透明·非偷碰）**：测试放 `app/backend/tests/`（**非** command/ 内）——直接依赖 A-GRAPH-1
> 同样把测试落在此（`tests/test_research_graph.py`）的 precedent，且 `pytest.ini testpaths=app/backend/tests`
> 决定**只有这里的测试会被中心全量套件收集**（落 command/ 内则中心全量跑不到我的命门探针，违「对抗测试种坏门
> 必抓」的目的）。新增文件、未改任何现有文件；不在「绝不碰」名单（state/log/board/DEVMAP/GOAL/pool/其他卡
> 目录/main.py/graph/qro）内。

## 实现要点

### ① typed 命令层 = 唯一写通道（`CommandBus`·GOAL §2 user 手动 + agent 同源）
- **唯一公共写口 = `CommandBus.submit(intent)`**：校验 → 翻译 → 内容寻址核验 → 图 `apply` → 落同一本命令账 →
  回执。`_graph`/`_ledger` 私有，无第二条公共写路径——这是「user 手动 + agent 同源进同一门」的结构兑现。
- typed command **就是** `research_graph.CanonicalCommand`（**收编只读·铸它落它·绝不另造第二套命令类型/身份**）。
- 诚实：Python 不能真隐藏 `_graph`；通道唯一 = 结构上 submit 是唯一公共写口 + **对账探针**（同 A-GRAPH-1 以
  `assert_commanded` 探针守裸写 `_nodes` 的范式）。

### ② 语义翻译/解析（`translate_intent`·GOAL §2 intent/canvas action → typed command）
- 面向台面的 5 个**语义动作**（create_asset / update_asset / link_assets / request_handoff / fulfill_handoff）
  经**单一翻译表** `ACTION_TO_COMMAND` 翻成图的 5 个 typed command（CMD_CREATE_NODE…·import 期自检恰好覆盖）。
- args 按动作**解析**成 typed payload：create/update→{qro}；link→{src,dst,edge_type}；request_handoff→现建
  `DeskHandoff`（缺省 created_by=provenance.actor）；fulfill_handoff→{handoff_id,produced_ref,resolved_by,evidence_refs}。
- `provenance.actor` 注入 `command.actor`、`provenance.token()` 注入 `command.origin`——图命令账亦带来源（可对账）。

### ③ 全栈校验（`validate_intent` + `assert_content_addressed`·A-GRAPH-1 信封未做的那层）
- **actor 四类 + 目标台 + 动作合法 + payload schema**：除 A-GRAPH-1 信封已守的 actor/台/内容寻址外，**逐命令
  类型校验载荷形状**（命门 #5）——create/update 缺真 QRO（裸 dict/duck 拒）、link 缺 src/dst/非法 edge_type、
  handoff 缺必填（fulfill 缺 produced_ref 早拦 = §2「完成后缺 produced_ref→拒」命令层防御纵深）。
- **内容寻址完整性**（命门 #4）：`assert_content_addressed` 用图命令**自身单一源派生**（构同字段孪生·比对
  command_id）抓伪造/篡改的 id——**不另写一套哈希**（不引第二源）。
- 诚实边界：**不**重算写权限（home 台）——那是图的门（单一源），图在 `apply` 独立 re-assert（分层防御·不双源）。

### ④ provenance（`Provenance` + `CommandLedger`·GOAL §2 来源面 + 同一 audit/lineage）
- **来源面 typed 化**：A-GRAPH-1 把 `origin` 留作自由串，本卡细化为门——`ORIGIN_SURFACES`（canvas/form/ide/
  api/agent_runtime/scheduler）。
- **actor↔来源面相容**（命门 #6·`ACTOR_SURFACE_ALLOWED`·import 期自检恰好覆盖四类 actor）：§2「user 手动
  画布/表单/IDE/API」+ §0 四类 actor 的**结构编码**——user_manual 只能来自人手面、纯 agent/scheduled 不冒充
  人手画布/表单/IDE、api 为共享边界（对全类放行·诚实承认这一面歧义）。抓 provenance 洗白（手动伪称 agent
  面 / agent 冒充人手画布）。
- **同一本账**（`CommandLedger`·append-only）：user 手动与 agent 命令进**同一条链**（provenance 区分·`entries_by_actor`/
  `entries_by_surface` 可切片·**不分账**）——§2「同一 audit/lineage」的结构兑现。`command_ids()` 供通道唯一对账。

### 命门 #1 通道唯一（`assert_single_channel`·GOAL §2「user 手动改动未落 canonical command→拒」通道形态）
- 可证伪探针：对账「图命令账 vs 通道账」——任一图命令不在通道账 = 绕 bus 直接 `graph.apply`（user 手动改动
  未落 canonical command 通道）→ `ChannelBypassViolation`。正路径 submit 恒「落图 + 记账」成对，此门恒过。

## 对抗测试（种坏门必抓·mutation 定点验证·RULES §2）
真测试汇总行：**`57 passed in 0.05s`**（`tests/test_canonical_command.py`）。
基线（本 worktree·origin/main 基·前四波已 land）：`pytest --collect-only` **2010 → 2067（+57·纯增量·零
collection error）**（与卡所述「当前 main collect ~2010」吻合）。import `app.command` = **0.020s**（零重依赖·
polars/sklearn/torch 均未加载）。

**12 次定点变异**（monkeypatch 关门→必红、还原→必绿，**全程脚本内存改写+还原·绝不 git checkout**，还原后
真门复跑 4/4 复活）：

| MUT | 关掉的门 | 命中测试 | 结果 |
|---|---|---|---|
| #1 ★ | **通道唯一对账**（`assert_single_channel`→no-op·绕过 canonical command 通道） | `test_direct_graph_apply_bypass_caught` + `test_single_channel_discriminates_clean_vs_bypass` | 2 RED → 还原 GREEN |
| #2/#6 ★ | **actor 四类 + 来源面相容**（`assert_actor_surface_coherent`→no-op） | `test_provenance_rejects_non_four_class_actor` + `test_validate_intent_reasserts_forged_actor` + `test_user_manual_from_agent_runtime_rejected` + `test_agent_from_human_canvas_rejected` | 4 RED → 还原 GREEN |
| #3 | **目标台门**（`DESKS` 含 ghost） | `test_validate_intent_rejects_unknown_desk` | 1 RED → 还原 GREEN |
| #4 | **内容寻址完整性**（`assert_content_addressed`→no-op·伪造 command_id） | `test_forged_command_id_caught` + `test_missing_or_malformed_command_id_caught` | 2 RED → 还原 GREEN |
| #5 | **payload schema**（`_validate_payload_schema`→no-op） | `test_create_without_real_qro_rejected` + `test_fulfill_handoff_missing_produced_ref_rejected` + `test_link_desk_handoff_edge_type_rejected` | 3 RED → 还原 GREEN |

★ = 卡明确要求的两个 headline MUT（**绕过 canonical command MUT** + **actor 四类 MUT**），均逐点验证必抓。

**六门对应卡四条可证伪验收**：
- 验收①「手动改动未落 canonical command→拒」= 命门 #1（绕 bus 直写图被对账探针抓）。
- 验收②「actor 非四类 / 缺目标台 / 缺内容寻址 id→拒」= 命门 #2（actor·ProvenanceError）/ #3（目标台）/ #4（内容寻址）。
- 验收③「agent 与 user 手动落同一 audit/lineage」= 命门 #6 同链（`test_user_manual_and_agent_share_one_ledger`：
  两源命令同进一本账·seq 连续·provenance 区分但不分账）。
- 验收④「合法 typed command 落图正确·不误伤」= happy-path 测试群（`test_full_flow_create_link_handoff_fulfill`
  五动作端到端落图正确 + 翻译表逐动作正确 + 幂等 + 写权限仍由图守 + 回执 lineage）。

## 红线合规（逐条）
- **单一身份源 ids.py 不另造**：command_id/qro.identity/handoff_id 全沿用 `research_graph.CanonicalCommand`
  的单一源派生（`lineage.ids.content_hash`）；`Provenance.token()` = `prov_`+content_hash（同哈希族·测
  `test_provenance_token_is_content_addressed_single_source`）；actor 四类常量**从 qro.envelope 导入**（不另造·
  import 期自检 `ACTOR_SURFACE_ALLOWED` key 恰 == `ACTOR_CLASSES`）。✅
- **扩展不替换（graph/qro 只读不改）**：graph/research_graph、qro/envelope、lineage/ids **一字未改**；本层
  收编 `CanonicalCommand`（铸它落它·不改它）、复用 ACTOR_CLASSES/DESKS/EDGE_*/DeskHandoff。git status 仅
  `app/command/`（新）+ `tests/test_canonical_command.py`（新）。✅
- **所有写入经 canonical command（绕过→拒）**：`CommandBus.submit` 唯一公共写口 + `assert_single_channel`
  对账探针；MUT #1 证门非纸。✅
- **不破基线**：纯增量 2010→2067、0.020s import 不拖重依赖、不触 main.py/graph/qro/其他在飞线领地；graph+qro
  +command 三测合跑 166 passed（109 既有 + 57 新·零交叉污染·无循环 import）。✅
- **先读 GOAL §1/§2 再动手**：动手前 grep+读 GOAL §1（行 60-191）+§2（行 192-263）+ RULES + RULES.project +
  实证 research_graph.py（A-GRAPH-1 落点）+ qro/envelope + ids + A-GRAPH-1 done 卡。✅
- **无新公式→不强造 MathematicalArtifact**：本层是命令通道·无数学产物，未造 MathematicalArtifact。✅

## 拍板项命中（语义岔路·诚实点名·未停工·留痕供中心）
- **actor↔来源面相容表 `ACTOR_SURFACE_ALLOWED`（命门 #6）**：GOAL §2 **明定** user_manual 来源面 = 画布/表单/
  IDE/API（人手面·verbatim），§0 明定四类 actor；但**未逐一明定** agent / scheduled_agent / user_confirmed_agent
  的精确来源面允许集，也未明定 **api 是否人/agent 共享边界**。**裁定（未停工·照建·可逆）**：① user_manual→
  {canvas,form,ide,api}（§2 verbatim）；② user_confirmed_agent→人手面 ∪ {agent_runtime}（人经手面确认·agent
  执行）；③ agent→{agent_runtime,api}；④ scheduled_agent→{scheduler,agent_runtime,api}；**api 对全类放行**
  （诚实承认人/agent 皆可程控 API 这一面歧义）。**为何未升级为停工拍板**：① §2 明命名的核心门「user 手动改动
  未落 canonical command→拒」「同一 audit/lineage」无歧义、已实现并过 MUT；② 此表仅一处 dict、**完全可逆**、
  下游只读不破坏；③ 同 A-GRAPH-1「infra home 台切分」precedent（GOAL 已定主体·残余是可逆细节→flag 不 stop）。
  **中心若有不同读法（如收紧 api、或允许 agent 经 ide），改一处 dict 即可重 pin。**
- **测试落 `app/backend/tests/`（非 command/ 内）**：见上「新建文件」说明——A-GRAPH-1 precedent + testpaths 决定
  中心全量只收这里。若中心要求严格落 command/ 内，可挪（但须同步 testpaths·那是 dev-os 级 pytest.ini·非本卡领地）。

## 诚实残余（会变任务·非设计极限·A-COMPILER 接续）
- **A-COMPILER 接续**：本卡止于「翻译 + 校验 + provenance + 落图」；Governed Compiler（消费命令/图 →
  Deterministic Run → Evidence Verdict → Promotion）**未建**。本通道**不**判 evidence 真伪 / 理论是否真证明 /
  一致性是否真成立（归 verification / spine_gate / A-COMPILER）。
- **写权限轴级 + home 台仍归图**：本层**不**重算写权限（home 台）——`CommandBus.submit` 把 well-formed 命令交
  图，图 `_assert_write_authority` 独立 re-assert（单一源·测 `test_write_authority_still_enforced_by_graph_through_bus`：
  策略台经合法通道写 Factor 仍被图拒）。轴级权限（执行台推 runtime、审批台动 governance）同 A-GRAPH-1 残余·待下游。
- **provenance 仅结构相容·非身份认证**：`assert_actor_surface_coherent` 只判「actor↔来源面结构相容」（§2 人手
  面 vs agent 面），**不**判动作是否真由该 actor 发起——运行时身份认证（谁真的按了键 / 哪个 agent 真的发起）
  是上游 Auth 的活，本卡未做（诚实残余）。`actor_id`/`session_ref`/`request_ref` 仅审计承载位、未接认证。
- **通道唯一是探针式·非物理强制**：`assert_single_channel` 抓「绕 bus 直接 graph.apply」（同 A-GRAPH-1
  `assert_commanded` 探针范式）；Python 不能物理禁止他人持图引用裸调 apply。系统级「单一通道」= 各调用方应经
  `CommandBus` + 探针对账的纪律，非语言级强制。
- **CommandLedger 在内存·未持久化**：账是 append-only 内存结构；落盘/对接既有 lineage.ledger 持久层归下游集成。
- **graphify 图未刷**：按任务线纪律不跑 /skill；图谱更新归中心整合期（graphify-out/ 本就 gitignore）。

## 诚实限界（设计极限·不会再改）
- 本层是「语义动作 → typed command → 校验 → provenance → 落图」的**治理通道 + 审计账**。它**不**判语义真值
  （证据/理论/一致性真伪），**不**替代 Compiler / spine_gate / verification / 图的写权限门。
- 通道唯一以**对账为据**：正路径 submit「落图 + 记账」成对，故图命令账 ⊆ 通道账；绕通道直写被探针抓。不存在
  「命令落了图却不在账、且探针放过」的合法态（探针即定义）。
- actor 四类 + 来源面相容是**结构门**：它保证「非四类 actor / 洗白来源面的命令进不了图」，**不**保证命令承载的
  内容本身正确（那是上游写命令 + 下游验证的责任）。

## 验证状态（🟡≠✅）
- ✅ 已验证（本地实跑）：scoped 57 测试绿、12 次 mutation 全红再还原绿（4/4 真门复活·monkeypatch 内存改写·
  绝不 git checkout）、graph+qro+command 三测合跑 166 绿（零交叉污染）、import 隔离 0.020s 无重依赖、
  collect 2010→2067 零 error、三张单一源表（翻译/相容/来源面）import 期自检全覆盖。
- 🟡 未验证（归中心）：全量套件未跑（任务线纪律·只跑 scoped）；与下游 A-COMPILER（消费命令/图跑 run）/ 各台
  前端 Canvas（语义动作来自真 UI）/ 上游 Auth（运行时身份认证）的集成未接线（本卡是命令通道·下游卡接续）。
  中心负责整合 + 全量 + land。
