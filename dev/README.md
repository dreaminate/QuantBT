# 开发 OS（dev/）· OS 规约 · 团队并发版

<!-- 【开发os级别】勿改 · clone 自 Multi-Dev-Os。本文件是 OS 规约/方法,跨项目一致。 -->

这里是「**怎么建**」——身份 + 五台 + 并发 Goal Loop。本文件随骨架走,任何用本 OS 的项目都带一份。
产品本身的手册/运行数据放项目自己的 `docs/` 等处。

> **团队并发**:多 developer 协作。**有主的过程内容全 folder 化**(`{type}/{developer_id}/`)→ 各写各文件、per-dev 内容零冲突(全局少数单文件 land 时由 leader 合);**读任何一类 = 遍历 `{type}/*/` 聚合**,靠生成式导航 map(`DEVMAP.md` / 各 `_NAV.md`)快定位,但**导航只定位、实时依据永远是原文 + 对应代码**。

## 身份 + 布局

| 件 | 文件/目录 | 职责 | 归属 |
|---|---|---|---|
| 身份 | `.identity` | 本机 developer_id | **本地·gitignore** |
| 花名册 | `TEAM.md` | 全员 developer_id + role(leader×1/admin×N/developer) | 全局单·committed |
| 目标台 | `GOAL.md` | 终态契约(慢变,所有 gap 对照它) | 全局单 |
| — | `RULES.md` / `RULES.project.md` | OS 通用铁律 / 本项目红线 | 框架 / 项目 |
| — | `CODEMAP.md` | 项目代码结构图(不含 dev/) | 全局单 |
| 状态(per-dev) | `state/{id}/state.md` | 现状 gap 表(**重生型**:land 后整篇重写;从本地代码来;🟡≠✅) | per-dev·committed |
| — | `state/{id}/frontier.md` | 跨会话续接现场(**重生型**:每 loop 整篇覆写;续接块禁进 state.md) | per-dev·committed |
| — | `board/{id}/board.md` | 本人活跃卡(**派生视图·不入库**) | per-dev·生成 |
| — | `log/{id}/log.md` | 滚动日志(当月;`os.py log` 自动按月滚到 `archive/YYYY-MM.md`) | per-dev |
| — | `experience/{id}/experience.md` | 技术坑经验库 | per-dev |
| 决策/问题 | `decisions/{id}/` · `issues/{id}/` | append-only;账本或一决策一文件皆可,**锚 D-####/ADR-***;**canonical 归 leader** | per-dev·committed |
| 任务台 | `tasks/` | `pool/{uuid8}/`(待分配) + `{id}/{uuid8}/`(已分配) + `{id}/done/`(+`done/archive/YYYY-QN/` 季度归档) + `_templates/` + `_areas.md`(功能域词表) | 结构框架·卡 committed |
| 研究台 | `research/` | `ideas/active/findings/{id}/` + `findings/_shared/`(共享槽) + `INDEX`/`TRACE`(手填溯源) + `WORKFLOW`(方法) + `archive` | 结构框架·内容 per-dev |
| 执行台 | `exec/` | `HANDOFF.md`(入口) | 框架 |
| 闸+脚本 | `scripts/` | `os`(卡生命周期 CLI) `_oslib` `validate_dev` `validate_project` `build_{board,dev_map,ledger,trace,log_index}` | framework |

> 导航 map(**生成、勿手维护、不入库**):`DEVMAP.md`(活跃面:全员 active+pool,按 area 词表分组;done 只计数、全量看 ledger)+ 各 folder `_NAV.md`。派生视图全部被 `dev/.gitignore` 挡在库外——现用现生成(`os.py refresh`),没有「新鲜度」要守、多分支 land 零冲突。

## 并发 Goal Loop

```
认身份(.identity/TEAM) → git pull main + os.py refresh + 看 DEVMAP/diff(代码动了先刷理解)
  → 取卡(developer:自己 tasks/{我}/ 名下; leader/admin:os.py assign 从 pool 分配)
  → 写实现 + 对抗测试(测试跑绿,不破基线) → os.py done(落档/盖 done_at 原子)
  → 整篇重写 state/(gap 表) + 覆写 frontier(续接现场) + os.py log → os.py validate
  → land(仅 leader/admin 合并进 main) → 他人 pull 同步
```

## 任务卡 id + 分配

- **逻辑 id = `{owner}-{uuid}`**(owner = `wait`(在 pool)或 `developer_id`);**物理:文件夹名 = uuid 前 8 位 hex,归属由所在父文件夹(`pool`/`{developer_id}`)编码、名字不带前缀**;内容 + 依赖 = 全 32 位 uuid;**依赖锚 uuid**(前缀可变、uuid 不变)。冻结历史卡保 legacy id。
- **三晋升源**(研究台 / GOAL gap / dev×claude)→ mint uuid 入 `tasks/pool/`;leader/admin 分配(pool→`{developer_id}`,改归属文件夹)与 land。
- 全任务 `depends_on` 构成 **DAG**(validate 校验无环 + 无悬空);package-level 拆包 / 分配推荐由 `dev/skills/assign-tasks/` 落地：先切 shared trunk 的 foundation 包,分叉后再发 branch 包,汇合点留到后续 join 包。

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

## 核心纪律

铁律全文在 `RULES.md` §0–§8(哲学 / 单一源 / 对抗测试 / 诚实 / 工程红线 / 致命错误即停工 / 审计 / 拍板 / 团队并发);常驻**硬不变量摘要**在 `CLAUDE.md`。本规约**只指路、不复述**(复述 = 双份必漂)。

## 导航头 + 导航 map（可查 + 防漂）

长引用文件(`GOAL.md` / `RULES.md` / `decisions/` 类)顶部放一句**导航 + 查法**:本文件怎么组织 + 怎么 grep 找一条。
**铁律一:索引/导航头/导航 map 只为定位,不是原文的替代品** —— 据它 grep/跳到位后**必须读对应原文 + 对应代码再行事**(RULES 顶部索引、§ 标题、`DEVMAP`/`_NAV`、卡计数器同理)。
**铁律二:只描述结构与查法,绝不枚举每条内容**——枚举=和正文双份必漂。要"每条都列"只能靠脚本从正文/目录自动生成(`build_ledger`/`build_dev_map`/`build_log_index`),**绝不手维护**。
同理:任务卡 `## Open Questions` 的「已决 D/总」是**派生量**——board/DEVMAP 展示时从标签现算,**不落盘进卡**(落盘=第二份必漂),更不写"含 N 个需拍板"这种会 stale 的散文。
**folder 层导航**:folder 全 per-dev 化后,读要遍历——`DEVMAP.md`(任务,按 developer + area)、各 `_NAV.md`(decisions/issues/state/log/experience/research) 是这层的导航,生成、只定位。

## 查 LOG

各人滚动日志 `log/{developer_id}/log.md`(最新在上,当月;历史在 `log/{id}/archive/YYYY-MM.md`)。**查历史别手翻**——跑 `python dev/scripts/build_log_index.py` 看全员统一索引(含归档;脚本生成、不手维护)定位再读原文。纪律(每 session 落一条 / 别因自己没记就当没发生)见 `RULES.md` §8。

## 自检

`python dev/scripts/validate_dev.py`(= `os.py validate`) —— harness 不靠手工纪律,自检:身份∈TEAM / leader 唯一 / 卡 owner==所在文件夹 / 文件名==uuid8 / **依赖无悬空 + DAG 无环**(归档卡在册) / 派生视图未被 track / state 不假绿灯 + 无续接堆叠 + 体积行长 lint / area slug 合法 / 研究台归属合法 / 目录骨架齐。挂 CI 或 pre-commit 即防漂。

## 新 session 怎么开始

入口脚本 = `exec/HANDOFF.md`(复制即接上);读序见 `CLAUDE.md`「动手前按顺序读」。**单一源,不在此复述。**
