# 开发 OS（dev/）· OS 规约

<!-- 【开发os级别】勿改 · clone 自 dev-os。本文件是 OS 规约/方法,跨项目一致。 -->

这里是「**怎么建**」——四台 + Goal Loop。本文件随骨架走,任何用本 OS 的项目都带一份。
产品本身的手册/运行数据放项目自己的 `docs/` 等处(app 运行时读的留在项目侧)。

## 四台 + 两本账 + 一道闸

| 件 | 文件/目录 | 职责 | 级别 |
|---|---|---|---|
| 目标台 | `GOAL.md` | 项目**完整最终形态**(终态契约,慢变,所有 gap 对照它) | 【项目级别】填 |
| — | `STATE.md` | **诚实 gap 陈述器**输出:现状 vs GOAL(每 loop 重生;🟡未验证 ≠ ✅) | 【项目级别】填 |
| — | `DECISIONS.md` | 决策账本(**append-only**,锁定后不改既往) | 【项目级别】填 |
| — | `RULES.md` | **OS 通用铁律**(诚实/对抗测试/扩展不替换/防漂/审计纪律) | **【开发os级别】** |
| — | `RULES.project.md` | **本项目铁律**(冻结文件/范围/安全不变量) | 【项目级别】填 |
| — | `ISSUES.md` | **跨任务问题/风险登记册**(未决 Open Q 不掉地) | 【项目级别】填 |
| — | `experience.md` | **技术坑经验库**(已学教训:坑 + 正解;append) | 【项目级别】填 |
| — | `CODEMAP.md` | **项目代码结构图**(不含 dev/,给 agent 导航) | 【项目级别】填 |
| 任务台 | `tasks/` | `BOARD.md`(活跃板) + `active/<id>/` + `done/<id>/` + `_templates/` | 结构/模板【开发os级别】· 内容【项目级别】 |
| 研究台 | `research/` | `INDEX` + `TRACE`(溯源+取舍) + `WORKFLOW`(研究方法) + `ideas/active/findings/archive` | 结构/模板/方法【开发os级别】· 内容【项目级别】 |
| 执行台 | `exec/` | `LOG.md`(滚动记录台) + `HANDOFF.md`(新 session 入口) | 格式【开发os级别】· 内容【项目级别】 |
| 闸 | `scripts/` | `validate_dev.py`(OS 结构自检) + `validate_project.py`(项目锚点/旧路径) + `build_ledger.py`(全含量账本) | validate_dev/build_ledger【开发os级别】· validate_project【项目级别】 |

## Goal Loop（开发循环）

```
诚实查现状(STATE gap) → gap 变任务(BOARD) → 执行(active/<id> 写实现 + 对抗测试,测试跑绿)
   → 完成落档(active→done, BOARD 刷新) → 重跑 gap 陈述器(STATE) → 再循环
```

## 研究 → 任务（方法 · 通用,所有项目一样）

**研究生命周期**:`research/ideas/`(灵感·RFC·论文笔记) → `research/active/<topic>/`(在研深挖) → `research/findings/`(build-ready 设计) → `tasks/BOARD.md`(T-xxx)。**立成任务(开始建 + 对抗测试)才进 Goal Loop**;在研阶段 informal,不要求严格验收。原料归 `research/archive/`,蒸馏成 finding、拍板进 `DECISIONS.md`。

**蒸馏 6 步**(把又长又乐观的研究变成可落地任务,AI 照此走;不是死流程,是手艺骨架):
1. **先读怀疑面再读结论** — 先看研究自己的对抗核查/反方,把乐观推荐打折。
2. **抽承重的可证伪主张** — 剥掉 hype,留一句「如果 X 则 Y」+ 适用域 + 证据强度。
3. **诚实标未验证残余** — 研究没建立的明写出来,绝不带进 finding 当真。
4. **落成可落地设计** — 接到本项目 `file:line` + 复用现有模块 + 设计对抗测试。落 `research/findings/`(模板 `findings/_TEMPLATE.md`)。
5. **拆成任务** — 一个 finding 拆成 BOARD 行,每行一个验收一句话 + 优先级 + 依赖。
6. **溯源回填** — finding↔研究↔任务 写进 `research/TRACE.md`。

> 硬不变量(对抗测试门必抓 / 诚实标未验证)见 `RULES.md` §2/§3——蒸馏**继承**,不在此重复。
> `research/INDEX.md` 只放**本项目**的研究指针(内容),方法看这里(README)。

## 核心纪律（全文 RULES.md）

- **诚实**:🟡 声称 ≠ ✅ 验证,状态文件不假绿灯。
- **对抗测试**:「种一个已知的坏,门必须抓住,否则门是纸做的」。
- **防漂**:易变的东西(测试数/进度/当前任务)**绝不写进慢变文件**(GOAL/RULES/CLAUDE),只在 STATE/BOARD。
- **审计先立框架**:大结构→小结构→细节;框架是假设、可被细节推翻(防过度审计 + 防漏审)。
- **不擅自 commit/push**;改现有文件「扩展不替换」。

## 长引用文件导航头（可查 + 防漂）

长的 read-on-demand 引用文件(`DECISIONS.md` / `GOAL.md` / `RULES.md` 这类)顶部放一句**导航 + 查法**:本文件怎么组织 + 怎么 grep 找一条,方便 agent 定位。
**铁律一:索引/导航头只为定位,不是原文的替代品** —— agent 据它 grep 到位后**必须读对应原文条款再行事,不得只凭索引/摘要下结论**(RULES 顶部索引、§ 标题、卡计数器同理)。
**铁律二:只描述结构与查法,绝不枚举每条内容**——枚举=和正文双份必漂(append 一条就得回头更新顶部,十有八九忘)。要"每条都列"只能靠脚本从正文自动生成(像 `build_ledger.py`),绝不手维护。
同理:任务卡 `## Open Questions` 标题用**计数器 `待拍/总`**(0/N=全闭、可进实现),不写"含 N 个需拍板"这种会 stale 的散文。

## LOG 归档 + 强制查 LOG

`exec/LOG.md` 是活跃滚动日志(最新在上)。长了把**旧条目挪进 `exec/LOG.archive.md`**(归档,read-on-demand)。
**强制查 LOG 逻辑**:要查过去某 session 干了啥,先看活跃 `LOG.md`;**没查到必查归档**——跑 `python dev/scripts/build_log_index.py` 看**活跃+归档的统一索引**(脚本生成、从正文重生、不手维护 = 防漂),据 `文件:行` 定位 `LOG.archive.md` 原文(索引仅定位、必读原文)。**别因活跃没有就当没发生过。**

## 自检

`python dev/scripts/validate_dev.py` —— harness 不靠手工纪律,能自检(四台文件齐全 / BOARD ✅done ↔ `done/<id>/` 一一对应 / 目录齐全 / 项目锚点在)。挂 CI 或 pre-commit 即防漂。

## 新 session 怎么开始

读 `GOAL.md`(终态) + `STATE.md`(现状) + `tasks/BOARD.md`(下一步),拿 `exec/HANDOFF.md` 当入口提示词。重资料在 `research/archive/`,**read-on-demand,不默认加载**——活跃面只 4 个小文件。
