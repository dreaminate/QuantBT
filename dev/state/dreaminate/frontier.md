<!-- 重生型:每个 loop/session 收尾整篇覆写,永远只有最新一份(历史在 git)。模板 state/_TEMPLATE.frontier.md -->
# FRONTIER · dreaminate 前沿快照（重生型 · 每次整篇覆写）

> 给下一个 session/loop 的续接现场。**覆写,不追加**——旧快照不保留(要历史看 git log 本文件)。
> 与 `state.md` 分工:state = 对照 GOAL 的 gap 表(慢变) + 顶部刷新块(本轮值);frontier = 正在进行的战役现场(每 loop 全刷)。

## 现在打到哪了
- **/loop 5m 自主循环运行中**（cron 本 session 内·prompt 含「效率优先·多 agent 并行·放权」）。
- **【最新·2026-07-16】M6b 已 land main（产品 `a8549fa8`）= 内嵌 agent epic (M1→M6b) 整条闭环收官。**
  - 本轮 loop 唤醒先做 **recovery**：本地 main 曾落后 origin/main 86 commit（皆前序已 land 工作）→ `git merge --ff-only` 到 `7aa19eed`（HEAD 为 origin 祖先双证·干净 FF·GOAL 零 diff）。recovery checkpoint = `dd5c1800`（dev/ state·随 M6b 一起 push）。
  - **M6b 内容**（app/agent/backends + main.py + 4 新测·扩展不替换）：SSE liveness 守卫——A1 idle+total timeout（reader 线程+bounded queue·抗慢消费者背压）、A2 orchestrator 显式 close backend.run 确定性 cancel、A2.5 EOF-but-alive bounded `proc.wait(eof_grace)`、A2.6 EOF 无 terminal→honest BackendError（非假 stream_ended）、A3 `_agent_workspace_for_owner` --add-dir 路径穿越守、B4 opt-in 真 claude 冒烟经 SSE orchestrator（CI 诚实 KNOWN_RUN_GAP skip）+ `SessionStarted.mcp_servers`。
  - **跨厂商 codex floor 5 轮**（approver≠creator·GPT-5.6-sol）逮 **3 真 correctness/honesty 洞**（EOF sentinel 满队列丢弃 · A2 双 regression〔eager-run 抛错逃逸+close 异常泄漏〕· EOF-no-terminal 假绿）+ 多处 honesty 过强描述 → 逐条修 + RED-then-revert 钉 → R5 **FLOOR-HOLD**。诚实教训：cancel 重构一移就悄悄收窄了 honest-error 保证；同厂商复读易放过，跨厂商逮住。
  - **诚实 residual（登记·非阻塞·pre-existing）**：HTTP 断连若 ASGI server 不 close 生成器 → 显式 close 不触发、idle/total 也不推进（消费者停拉冻结 deadline 检查）→ child 靠 GC 回收、无全局 CPU/进程上界、L-C/L-D 仍守、非安全边界。→ **route-level `request.is_disconnected` 硬化 = follow-up**。

## 下一步（NEXT · 最高杠杆）
- **金融数学 kernel P0**（北极星① 数学贯穿·最大缺口）：agent epic 闭环后，转「数据→因子→模型→信号→组合→执行→回测→归因→监控」链上机构级数学的**理论先证明 → 一致性校验门**主干。分解草案见 `research/findings/dreaminate/`（金融数学 P0-P3）。实质性切片走 duet（deep-opus ‖ codex），跨厂商 floor 复审。
  - **✅ P0-A #1 VaR/ES+Kupiec+spine 命门已 land**（产品 d8169028·2026-07-16·codex 17 轮 floor FLOOR-HOLD·CI 29544874836 success·见 [[decision D-MATH-P0A-VARES]]）。
  - **🔜 NEXT=P0-A #8 组合 correctness（已勘缝·map 完整·correctness-leverage 最高·零新运行时依赖 sklearn/scipy 已声明）**：seam 逮**理论↔实现 mismatch**——`risk_parity`(app/backend/app/portfolio/optimizers.py:70)实为 inverse-vol(`w∝1/σ`·只用对角·docstring 已自承「简化版」)、`ledoit_wolf_shrinkage`(hrp_audit.py:61)实为固定 α(默认0.2·live caller optimize_hrp_safe:134 用0.3·非真 LW 自动估)。**切片计划**：① 诚实改名 `risk_parity→inverse_volatility`+保 `risk_parity` alias 不破基线（1 真调用 business_tools.py:583·串 API "risk_parity" 在 tool_schema.py:148 enum/OptimizerKind/fallback label 保留）② **加真 ERC**（`equal_risk_contribution`·scipy.optimize·等边际风险贡献·**math-first+duet**·oracle=riskfolio/PyPortfolioOpt dev-only 或闭式对角退化核）③ 真 Ledoit-Wolf（sklearn.covariance.LedoitWolf·需 raw returns 非 cov·签名改·ripple 到 hrp_audit:134 + test_academic_audit_v2:287）④ **接 canonical 命门**（镜 spine_binding.py 模式·optimizers 现零 spine 绑定·新 artifact ARTIFACT_ESTIMATOR+独立 oracle 对账+evaluate_promotion）。**基线守**：test_portfolio.py(test_risk_parity_inverse_sigma:38 monotonic·dispatch loop "risk_parity") + test_academic_audit_v2.py(ledoit_wolf_shrinkage_improves_condition:287)必绿。**待用户拍（方法学·登记不停摆）**：改 "risk_parity" 串行为(inverse-vol→真ERC)会变 agent 工具语义→倾向保 alias+加新 "equal_risk_contribution" 选项(不改旧串)；真 LW 签名改口径。均可 Inference 默认可翻案。**下轮起做**：math-first ERC 骨架→duet(deep-opus‖codex)→实现+命门+oracle+对抗测试→codex floor→四门→land。
  - **P0-A 其余候选**（seam §86 top-6·三方一致）：EVT-POT 尾部引擎(#6/#7·additive·扩 VaR/ES·scipy.genpareto)、measure/process typed 层(#1/#2·架构地基)。
- 其余仍开本地 gap 与待拍板项见 **state 顶部刷新块「仍开·待拍板/外部依赖」全列**（§16 Run 首屏门 KNOWN_RUN_GAP、卡 8be0e547 dual-model binding 加固〔用户已授权重启〕、M6b route-level 断连硬化、前端 echarts lazy-load〔用户拍板面〕等）。

## 活跃上下文
- **audit 基线（配方已钉死）**：canonical 稳定基线（**排除可变运行时 DB `goal_proof_ledger/`**）= **61 files / 20,339 lines / 26,209,663 bytes / manifest SHA-256 `7348e826…d9c9e9`** 全程字节不变（=交接基线·完整性未破）。⚠️ 旧记 `1c1788b0bbe2` 是**非规范配方**（行序不同）非漂移。**规范配方**：`find data/audit -type f -not -path '*/goal_proof_ledger/*' -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256`。含 goal_proof_ledger 的全目录 manifest 可变、不作稳定基线。
- **测试基线（实跑·VaR/ES land 后）**：后端全量 **7019 passed / 14 skipped / 0 failed**（=6931 基线 + 88 risk-measures·隔离 DATA_ROOT·带 timeout·非并行叠跑·真汇总行·CI 29544874836 success）；validate_dev PASS。前端/benchmark 未受本切影响（纯后端 math）。
- **待用户复核（非阻塞）**：① 工作区 2 个 fib `.ipynb` 无记录删除在 `stash@{0}`（删/留待定）② data/audit spurious `goal_proof_ledger.sqlite`（删/留待定）。
- **工作模式**：实质性切片 duet（deep-opus ‖ codex gpt-5.6-sol）+ 跨厂商 codex floor 复审（approver≠creator·builder≠verifier）；codex 传 prompt 用 heredoc 文件避免 backtick 被 shell 解析；全量 pytest 隔离 DATA_ROOT + 带 timeout + 凭真汇总行判绿（非 exit code）；不 BLOCK 于前台长跑套件——后台跑 + 通知/tail。
