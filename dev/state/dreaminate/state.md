# STATE · dreaminate 现状（对照 GOAL 的 gap · 重生型）

> 现状 gap,对照 `../GOAL.md` 终态量。**🟡 未验证 ≠ ✅ 已验证** —— 只有挂得出可指认证据(file:line / 测试名 passed / 带口径的指标)的才标 ✅,空泛即假绿灯。
> 重生型:land 后整篇重写为当前快照;会话叙事进 `log/`,续接现场进 `frontier.md`,都别堆在这。
> 本版 2026-07-14 整篇重写(蒸馏此前 2026-06 全部追加块——原文在 git 历史 `git log dev/state/dreaminate/state.md`)。

## 进行中
- 39d08df8 已 done(2026-07-14)。/loop 15m 自主循环运行中;下一切片=CI 接入,队列见 frontier。

## 状态表（确定的才标 ✅,证据必挂）
| 子系统/能力 | 状态 | 证据 |
|---|---|---|
| §16 性能门·HS300 十年读<3s | ✅ | perf_harness measured=True/0.0185s;链=真实 Tushare 65.4万行+签名 receipt/universe+跨厂商 approve_pin+pin(perf_harness.py `quantbt-hs300-operator-root-v1`);证据包 research/findings/dreaminate/hs300-chain-evidence-20260714.md |
| §16 性能门·标准回测<60s / 资产库<1s / RAG 首批<3s | ✅ | perf_harness 三基线 measured PASS(benchmark 套件 72 passed 内) |
| §16 性能门·Run 首屏<2s | ⬜ | 诚实 KNOWN_RUN_GAP(需 Playwright 实测,harness 第二 gap;另卡) |
| §11 数据层·基准面(readbench cohort) | ✅ | DatasetVersion hs300_daily_10y_readbench_cohort@…856b67b1(metadata 四键防误用);preflight 12/12 真数据 PASS |
| §11 数据层·研究面(union 含退市) | ✅ | hs300_research_universe_10y@…332bebc0(1.38M bars/622 只/19,200 停复牌);12 质量门真数据 PASS(含探针 #6 bar日因子完备/#7 停牌伪 bar含退化窗);质量门经 codex 四轮对抗收敛到 factor-价格补偿不变量,scope 裁定见 frontier 待复核 |
| §11 数据接入·Tushare 管线 | ✅ | scripts/hs300_onboard.py 六子命令(store-token/keygen/pull/preflight/build/build-research/bench);限流 180/分+退避+幂等;docs/hs300-quickstart.md;data_onboarding 测试 41 passed(含 codex 全部反例回归) |
| §11 PIT/复权读侧接线 | 🟡 | raw+adj_factor 分离已交付;panel_source 唯一复权落点未接(后续卡) |
| §6 数学链门(§6 gate) | ✅ | section6_mathchain_gate.py 委托 spine_gate 8 deny 子句;gate_registry 7 门(2026-06-29 land ad7b9d4e,原文 git 历史) |
| §5 Research Asset RAG | ✅ | /api/agent/chat+workbench+legacy Mode2 全接;test_agent_runtime_research_graph 等系列在当日后端全量 6313 passed/0 failed(2026-07-14 实跑)内全绿;建设明细见 git 历史 |
| §6 Document Intelligence | ✅ | text/MD/PDF(PyMuPDF+OCR fallback)/HTML snapshot parser+batch+upload+目录同步;test_document_intelligence_parser_rag 在当日全量 6313 passed(2026-07-14 实跑)内全绿;边界:非联网 crawler/非表格理解 |
| §1/§7 Research Graph+QRO | ✅ | projection/canvas 写回/edge+tombstone+patch/参数值记录全链;test_research_graph_persistence 等系列在当日全量 6313 passed(2026-07-14 实跑)内全绿;边界:非完整 graph database |
| §8 Governed Compiler | 🟡 | compile_qro+IR/pass+artifact manifest 审计层已建;完整 codegen 未做 |
| §15 模型治理 | ✅ | 训练→registry→promotion(pending/rejected/approved QRO)→sandboxed inspection→serving seam+SignalContract(test_model_governance 当时 31 passed 口径,原文 git 历史) |
| §12 执行边界 | ✅ | intent→promotion→venue events→reconciliation→guarded submission/materialization 全 refs-only,A股 live 恒拒;test_execution_boundary_contract 系列在当日全量 6313 passed(2026-07-14 实跑)内全绿;边界:无真实 venue 连通 |
| §4 Settings/LLM Gateway | 🟡 | provider registry+keystore+routing+UI 第一版已建;OAuth/device-code、全 connector 未做;gateway secret 泄漏向量已闭(C-S7 Gap1,2026-06-29) |
| §13/§17 RDP | 🟡 | manifest/store/materialize/publish 已建;本切片链产物未组 RDP(residual) |
| dual-model 独立审查(流程级) | ✅ | builder=claude(anthropic)/verifier=gpt-5.6-sol(openai) 跨厂商;本切片三轮 verdict 留档证据包;应用内 Gateway 接线=另卡(切片②) |
| CI(GitHub Actions) | ⬜ | 未建;gh 未查询——一切 CI 声明保持 Unqueried |
| 前端 bundle 拆分 / FastAPI on_event 迁移 | ⬜ | 已知本地 gap,排队中 |

## 下一步
- 切片③ CI 接入(gh 真查后 CI 字段才动)→ 切片② dual-model 应用内接线 → pool 三张 eval 卡。
- 详单与残余见 frontier.md;战略提示(转用户可感知面)已记。
