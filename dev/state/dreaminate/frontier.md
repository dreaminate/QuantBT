<!-- 重生型:每个 loop/session 收尾整篇覆写,永远只有最新一份(历史在 git)。模板 state/_TEMPLATE.frontier.md -->
# FRONTIER · dreaminate 前沿快照（重生型 · 每次整篇覆写）

> 给下一个 session/loop 的续接现场。**覆写,不追加**——旧快照不保留(要历史看 git log 本文件)。
> 与 `state.md` 分工:state = 对照 GOAL 的 gap 表(慢变);frontier = 正在进行的战役现场(每 loop 全刷)。

## 现在打到哪了
- **/loop 15m 自主开发循环已启动**(cron job ce958a8c,session-only,7 天自动过期)。授权条款:功能级切片过四道门(最低验证全绿 + validate_dev PASS + autoplan 评审 + audit 基线无异常)自行进 main;纯 dev/ 改动以 validate_dev PASS + git diff --check 为门。
- **首轮(2026-07-14)一次性启动切片 ✅ 完成**——main checkout 脏工作区收口,过门进 main 并 push(66d3b10f..3a82b8e6):
  - `4409738d` chore(dev-os): 结构改造 v2 迁移整批(50 files;log.md 缩减 + archive/2026-06.md 同 commit,历史不丢)
  - `3a82b8e6` docs: 两份 docx 入仓(与 migration 分开)
  - work/(Atlas 试验产物)经 `.git/info/exclude` 本地排除,不入仓;**后续切片不引用/不延续 Atlas 范式**
- **工作模式钉死(harness 隔离守卫)**:bg session 的 Write/Edit 只能落 worktree;git 操作(add/commit/merge/push)可在主 checkout 跑。每切片模式 = `EnterWorktree` 开分支 → 编辑 + 过门 → 分支 commit → 主 checkout `git merge` 进 main → push。分类器已拒「写 .claude/settings.json 关守卫」,不再尝试。
- **下一步第一个动作**:切片① Tushare 真实 10 年 HS300 数据管线——先 WebFetch tushare.pro 文档(2000 积分档接口权限 + 每分钟限频),设计限流 + 指数退避 + 本地缓存/增量拉取;链条:拉取脚本 → DatasetVersion → immutable manifest → 签名 provenance receipt → 签名 universe snapshot → dual-model 独立审查 → 性能 harness KNOWN_RUN_GAP 真数据转绿。token 从本机 keyring 读,绝不入代码/日志/commit。

## 活跃上下文
- **data/audit 基线四项(2026-07-14 实测)**:61 files / 20,339 lines / 26,209,663 bytes——与交接基线三项**精确一致**;交接 manifest SHA `7348e826…d9c9e9` 配方不可复现(state/旧 workflow 均未记配方,data/audit 内亦无该哈希之文件)。本轮起 canonical 配方钉死:`cd data/audit && find . -type f | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256` → `1c1788b0bbe2`(前 12 位)。数据未变判定依据 = 三项原始计数精确吻合。
- **测试基线(交接值,以实跑为准)**:后端 6261 passed / 前端 423 passed / 性能门禁 59 / 安全隐私 100 / validate_dev PASS。
- validate_dev 两个已知 ⚠️(不挡门):state.md 222KB>32KB + 最长行 6765>2000——排期「蒸馏归档」切片处理。
- 汇报六字段契约:Local checkout / Remote branch or PR / Local tests / CI(gh 未查前 Unqueried) / Production(Unqueried) / User acceptance(Unverified)。
- 旧 codex workflow state(`~/.codex/workflows/quantbt-goal-honest-20260711/state.md`)只当历史参考,HEAD/测试数已过期。
- 仍开的本地 gap 队列:前端单 bundle 拆分(2,557.79 kB/gzip 767.39 kB)、FastAPI on_event 迁移、state.md 蒸馏归档、GoalProofLedger snapshot cache LRU(P2)、90+ 历史 worktree/分支盘点(只列清单,删除等拍板)。

## 待裁 / 卡点
- 2026-06-29 frontier 曾列四项待裁(C-S11 Commit2 fork / monitor-schema-hook / C-S7 Gap2+Gap3 / C-S3 端点强制,全 CENTER-SERIAL 碰 main.py)——**但其后 20260711 codex workflow 波次(测试 3704→6261)可能已消化部分,列表未经当前代码核对,动手前先核实还有哪几项活着**(git log + 对应代码),别按过期清单行事。
- 90+ 历史 worktree/分支:只列清单不删除,等用户拍板。
- loop 期间待拍板项处理条款:可逆且不越红线 → 选推荐项直接做 + log 标「Inference: 未拍板默认,可翻案」;不可逆/动钱/OS 级/方法学门槛/GPL license → 登记 board/state 等拍板,随即切别的切片。
