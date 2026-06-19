# 开发 OS（dev/）· OS 规约 · 团队并发版

<!-- 【开发os级别】勿改 · clone 自 Multi-Dev-Os。本文件是 OS 规约/方法,跨项目一致。 -->

这里是「**怎么建**」——身份 + 五台 + 并发 Goal Loop。本文件随骨架走,任何用本 OS 的项目都带一份。
产品本身的手册/运行数据放项目自己的 `docs/` 等处。

> **团队并发**:多 developer 协作。**有主的过程内容全 folder 化**(`{type}/{developer_id}/`)→ 各写各文件、并发零冲突;**读任何一类 = 遍历 `{type}/*/` 聚合**,靠生成式导航 map(`DEVMAP.md` / 各 `_NAV.md`)快定位,但**导航只定位、实时依据永远是原文 + 对应代码**。

## 身份 + 布局

| 件 | 文件/目录 | 职责 | 归属 |
|---|---|---|---|
| 身份 | `.identity` | 本机 developer_id | **本地·gitignore** |
| 花名册 | `TEAM.md` | 全员 developer_id + role(leader×1/admin×N/developer) | 全局单·committed |
| 目标台 | `GOAL.md` | 终态契约(慢变,所有 gap 对照它) | 全局单 |
| — | `RULES.md` / `RULES.project.md` | OS 通用铁律 / 本项目红线 | 框架 / 项目 |
| — | `CODEMAP.md` | 项目代码结构图(不含 dev/) | 全局单 |
| 状态(per-dev) | `state/{id}/state.md` | 现状 gap(从本地代码来;🟡≠✅) | per-dev·committed |
| — | `board/{id}/board.md` | 本人活跃卡(**生成视图**) | per-dev·生成 |
| — | `log/{id}/log.md` | 滚动记录 | per-dev |
| — | `experience/{id}/experience.md` | 技术坑经验库 | per-dev |
| 决策/问题 | `decisions/{id}/` · `issues/{id}/` | 一决策/问题一文件;**canonical 归 leader** | per-dev·committed |
| 任务台 | `tasks/` | `pool/{uuid8}/`(待分配) + `{id}/{uuid8}/`(已分配) + `{id}/done/` + `_templates/` | 结构框架·卡 committed |
| 研究台 | `research/` | `ideas/active/findings/{id}/` + `INDEX`/`TRACE`(全局聚合) + `WORKFLOW`(方法) + `archive` | 结构框架·内容 per-dev |
| 执行台 | `exec/` | `HANDOFF.md`(入口) + `archive/` | 框架 |
| 闸+脚本 | `scripts/` | `validate_dev` `validate_project` `build_{board,dev_map,ledger,card_counters,log_index}` | framework |

> 导航 map(**生成、勿手维护**):`DEVMAP.md`(全员→卡,按 area 功能查)+ 各 folder `_NAV.md`。跑 `build_dev_map.py` 刷新。

## 并发 Goal Loop

```
认身份(.identity/TEAM) → git pull main + 看 DEVMAP/diff(代码动了先刷理解)
  → 取卡(developer:自己 tasks/{我}/ 名下; leader/admin:从 pool 分配)
  → 写实现 + 对抗测试(测试跑绿,不破基线) → 落档 tasks/{我}/done/
  → 刷自己 state/ + 生成 board/(build_board) → validate_dev
  → land(仅 leader/admin 合并进 main) → 他人 pull 同步
```

## 任务卡 id + 分配

- id = `{developer_id|wait}-{uuid4}`:**文件名 = uuid 前 8 位**;内容 + 依赖 = 全 32 位;**依赖锚 uuid**(前缀 = 所在文件夹、可变;uuid 不变)。冻结历史卡保 legacy id。
- **三晋升源**(研究台 / GOAL gap / dev×claude)→ mint uuid 入 `tasks/pool/`;leader/admin 分配(pool→`{developer_id}`,改归属文件夹)与 land。
- 全任务 `depends_on` 构成 **DAG**(validate 校验无环 + 无悬空);连通分量拆分 / 分配算法 = 后续 skill(留空)。

## 研究 → 任务（方法 · 通用,所有项目一样）

**研究生命周期**:`research/ideas/{id}/` → `research/active/{id}/<topic>/` → `research/findings/{id}/`(build-ready 设计) → mint `tasks/pool/`。**研究台也 per-dev,但从研究提取到任务池这一步看所有人的研究**(遍历 `findings/*/`)。立成任务才进 Goal Loop;在研阶段 informal。原料归 `research/archive/`(共享),蒸馏成 finding、拍板进 `decisions/`。

**蒸馏 6 步**(把又长又乐观的研究变成可落地任务,AI 照此走;不是死流程,是手艺骨架):
1. **先读怀疑面再读结论** — 先看研究自己的对抗核查/反方,把乐观推荐打折。
2. **抽承重的可证伪主张** — 剥掉 hype,留一句「如果 X 则 Y」+ 适用域 + 证据强度。
3. **诚实标未验证残余** — 研究没建立的明写出来,绝不带进 finding 当真。
4. **落成可落地设计** — 接到本项目 `file:line` + 复用现有模块 + 设计对抗测试。落 `research/findings/{id}/`(模板 `findings/_TEMPLATE.md`)。
5. **拆成任务** — 一个 finding 拆成 pool 卡,每张一个验收一句话 + 优先级 + 依赖。
6. **溯源回填** — finding↔研究↔任务 写进 `research/TRACE.md`(全局聚合)。

> 硬不变量(对抗测试门必抓 / 诚实标未验证)见 `RULES.md` §2/§3——蒸馏**继承**,不在此重复。

## 核心纪律（全文 RULES.md）

- **诚实**:🟡 声称 ≠ ✅ 验证,状态文件不假绿灯。
- **对抗测试**:「种一个已知的坏,门必须抓住,否则门是纸做的」。
- **防漂**:易变的东西(测试数/进度/当前任务)**绝不写进慢变文件**(GOAL/RULES/CLAUDE),只在各人 state/board。
- **审计先立框架**:大结构→小结构→细节;框架是假设、可被细节推翻。
- **不擅自 commit/push**;改现有文件「扩展不替换」。
- **团队并发**(§8):身份/分配-land 仅 leader-admin/遍历聚合读/pull-before-work/生成视图不手编。

## 导航头 + 导航 map（可查 + 防漂）

长引用文件(`GOAL.md` / `RULES.md` / `DECISIONS` 类)顶部放一句**导航 + 查法**:本文件怎么组织 + 怎么 grep 找一条。
**铁律一:索引/导航头/导航 map 只为定位,不是原文的替代品** —— 据它 grep/跳到位后**必须读对应原文 + 对应代码再行事**(RULES 顶部索引、§ 标题、`DEVMAP`/`_NAV`、卡计数器同理)。
**铁律二:只描述结构与查法,绝不枚举每条内容**——枚举=和正文双份必漂。要"每条都列"只能靠脚本从正文/目录自动生成(`build_ledger`/`build_dev_map`/`build_log_index`),**绝不手维护**。
同理:任务卡 `## Open Questions` 标题用**计数器 `已决/总`**(满格=全决、可进实现),不写"含 N 个需拍板"这种会 stale 的散文。
**folder 层导航**:folder 全 per-dev 化后,读要遍历——`DEVMAP.md`(任务,按 developer + area)、各 `_NAV.md`(decisions/issues/state/log/experience/research) 是这层的导航,生成、只定位。

## 强制查 LOG（per-dev）

`log/{developer_id}/log.md` 是各人滚动日志(最新在上)。查过去某 session 干了啥:**别手翻**——跑 `python dev/scripts/build_log_index.py` 看**全员 log 统一索引**(脚本生成、从正文重生、不手维护),据 `dev/文件:行` 定位原文(索引仅定位、必读原文)。**别因自己 log 没有就当没发生过——别人可能记了。**

## 自检

`python dev/scripts/validate_dev.py` —— harness 不靠手工纪律,自检:身份∈TEAM / leader 唯一 / 卡 owner==所在文件夹 / 文件名==uuid8 / **依赖无悬空 + DAG 无环** / state 不假绿灯 / 目录骨架齐。挂 CI 或 pre-commit 即防漂。

## 新 session 怎么开始

读 `.identity`(你是谁)+ `TEAM.md`(全员/role)+ `GOAL.md` + 你的 `state/{你}/state.md` + `board/{你}/board.md`,拿 `exec/HANDOFF.md` 当入口提示词。decisions/issues 等遍历聚合读(先看 `DEVMAP`/各 `_NAV` 定位再读原文)。重资料 `research/archive/` read-on-demand。
