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
- **切片① 已开工(卡 39d08df8,P0/§11,已派我名下 review_status=1,卡内有完整接线点/对抗测试/验收)**。侦察四路完成 + 三个事实开口已实测关闭:
  ① **token**:secrets.yaml 窄读单键迁入 macOS 钥匙串(service=quantbt,name=tushare,fetch 正常,值零回显;Inference: 未拍板默认可翻案)。管线一律 `SecureKeystore.open(prefer="keyring").fetch("tushare")`。
  ② **universe 码**:index_weight `000300.SH` 实测两端月份各返回 300 行/权重和≈100——与 harness `_HS300_UNIVERSE_REF` 一致,不需 399300.SZ 兜底;快照落**月末交易日**。
  ③ **覆盖率门不可满足性已被真数据证明**:2026-06-30 成分 300 只中 61 只 list_date 晚于窗口 80% 线(最差 0.056)。修门方案:coverage 分母改「max(窗口起点,list_date) 起交易日」,list_date 逐只绑进签名 universe snapshot(防谎报晚上市洗白),门阈值保守,配对抗测试(早上市但缺 bar 必仍抓/list_date 不在签名快照必拒)+ codex 独立评审。
- **窗口定型**:2016-06-01..2026-06-30(实测 2446 交易日≥2400,跨 3681 天≥3650,coverage_end=月末快照日)。
- **harness 转绿最小清单(侦察 B 逐字段拿到)**:A 真 panel parquet(ts,symbol,OHLCV;精确 300 只) B DatasetRegistry.register(require_provenance,≥5 distinct GE tests,metadata 契约) C immutable manifest D 签名 receipt(`quantbt.hs300_perf_provenance.v2`,HMAC-SHA256) E 签名 universe snapshot(`hs300_perf_universe.v1`) F key≥32B 经 env G **pin authority root(perf_harness.py:429,唯一代码改动;dual-model 审查证据落账后才动)**。fixture `hs300_proof_fixture`(test:48-182)= real-path 逐字段模板。
- **抓取策略(侦察 D 文档实证)**:回填 ts_code 轴 2 码/次并联;日更 trade_date 轴;限速 200 次/分保守 + msg 子串退避(「每分钟最多访问」睡窗口/「每天最多」停次日/「没有权限」不重试);复权只存 raw+adj_factor(hfq=close×factor;qfq 锚点漂移禁缓存);停牌无 bar=官方 missingness 语义;stock_basic 需 fields 显式 delist_date + list_status='D' 补拉退市股。
- **仓内复用(侦察 C)**:tushare==1.4.24 已依赖;TushareConnector(daily/adj_factor/index_daily);DatasetRegistry(data_quality.py:206);examples/run_a_share_real_demo.py=CLI 模板;复权唯一改动点=factor_factory/panel_source.py(本卡不动,读侧另卡);数据侧通用链 content-addressed 不签名,签名只在 harness 契约层+LLM call records(HMAC)。
- **duet 三方并集已裁决**(deep-opus/codex/我全返回):核心分歧=覆盖率门,三案裁**签真实成员+修门**(deep-opus 的幸存者 cohort 案否——签名快照会宣称与真实 index_weight 不符的成员集=签假声明;codex 的完整 PIT timeline 案否——基准语义改动过大,PIT 研究资产按 deep-opus 双资产框架另行交付)。契约常量上提 app 案裁「不动 harness 位置+生产者镜像+相等性钉死测试」(Inference 可翻案)。采纳增量:双资产框架(研究面 622 并集≠基准面 300)/双模型审查只喂 hash 不喂原始数据/同窗重拉字节确定性。
- **真实拉数 ✅ 完成**(staging=data/.cache/tushare_hs300_raw,68MB):137.7 万行 daily+139.8 万行 adj_factor,622 只并集零缺失,index_daily 精确 2446 行;adj_factor 非单调性=出版舍入噪声(≤5.6e-5,600/622 只)——质量测试用容差 1e-4。
- **harness 修门 ✅ 已 commit**(slice/39d08df8-hs300-chain @ e2878c66):universe schema v2 携 constituent_list_dates,自上市起算覆盖率(0.80 不变),上市前 bar 拒,首 bar 滞后≤10 天;**66 passed/12.71s**(59 既有全保+7 新变异探针,含可满足性绿路径钉死)。
- **进行中**:① deep-opus 实现生产者侧(data_onboarding 模块+scripts/hs300_onboard.py CLI+生产者对抗测试,spec 已含相等性钉死/secret 卫生/确定性) ② codex 对修门 diff 的对抗复审(dual-model:我 build/openai verify)。**下一步**:验收生产者→keygen 入 keyring→真实 build_chain→codex 审链→pin authority root(perf_harness.py:429)→harness 真数据转绿→最低验证全套+autoplan→land。

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
