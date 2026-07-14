---
uuid: 39d08df8cb9f4890bfd7c5a89eb904f8  # 全 32 位 hex 无连字符;生成:python -c "import uuid;print(uuid.uuid4().hex)"(或直接 os.py mint 全自动)
title: Tushare 真实 10 年 HS300 日频数据管线全链条——真 panel+DatasetVersion+manifest+签名 receipt/universe snapshot+dual-model 审查+perf harness 合法转绿
status: in_progress  # todo | in_progress | done
owner: dreaminate  # wait(在 pool) | <developer_id>;须 == 所在文件夹(validate 校验一致;os.py assign 两处同改)
assigned_by: dreaminate  # 分配者 developer_id(leader/admin);pool 中留空
review_status: 1 # 被分配者 self-review:0 未过目 | 1 已过目/确认
priority: P0  # P0 最高 … P3 最低
area: backtest  # 功能域 slug,须已在 ../_areas.md 注册(语法 ^[a-z0-9_-]+(/[a-z0-9_-]+)?$;validate 校验)
source: goal  # research | goal | interaction(三晋升源出身)
source_ref: /loop 20260714 授权契约(Tushare 链条本地可收口)  # 溯源句柄:finding 路径 / GOAL §x / 对话
goal_section: §11  # 服务 GOAL 哪个子系统节(如 §3);build_trace.py 据此聚合覆盖,可空
done_at:         # 落档日期 YYYY-MM-DD(os.py done 自动填;归档按它分季)
depends_on: []   # 上游卡 uuid 列表(全 32 位)= DAG 的边;os.py mint --depends-on 可用 uuid8 前缀自动解析
---

# Tushare 真实 10 年 HS300 日频数据管线全链条——真 panel+DatasetVersion+manifest+签名 receipt/universe snapshot+dual-model 审查+perf harness 合法转绿

## Scope [必填]
用真实 Tushare 数据把 §11/§16 的 HS300 性能门证据链走全(真 panel + DatasetVersion/manifest + 签名 receipt/universe snapshot + dual-model 独立审查 + authority root pin,harness `perf:hs300_10y_daily_read` measured PASS <3s);不做:实盘/testnet、执行接线、前端 UI、Run first-screen 门、非 HS300 市场扩展。

## 上下文 / 动机 [按需]
GOAL §16 性能基线「沪深300×10年日频读取<3s」现为诚实 KNOWN_RUN_GAP(perf_harness 设计如此:非真数据+完整签名链不许绿)。这是 GOAL 收口的最大缺口,/loop 契约列为最高杠杆切片①,且真实数据链已被授权为本地可收口。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/tests/benchmark/perf_harness.py | :429 `_HS300_PINNED_AUTHORITY_ROOTS` | 唯一代码改动点:pin 经审查 operator_attested root(**dual-model 审查证据落账之后才动**) |
| app/backend/tests/benchmark/perf_harness.py | :1650-1805 probe / :432 config | 零改动,按契约喂 dataset/registry/receipt/universe/key-env 六输入 |
| app/backend/app/data_quality.py | :206 `DatasetRegistry.register` | 复用,require_provenance=True,≥5 distinct GE tests,metadata 按 :838-867 契约 |
| app/backend/app/connectors/tushare_connector.py | :40-59 `_TUSHARE_SPEC` | 复用 daily/adj_factor/index_daily;universe 走 index_weight(码 000300.SH 实跑验证,空则 399300.SZ) |
| examples/run_a_share_real_demo.py | :31-40 token bootstrap | 复用 load_secrets→env 模式;token 绝不入码/日志 |
| scripts/(新增 fetch CLI) | argparse+SystemExit(main) 惯例 | 新增回填脚本:ts_code 轴批量(2 码/次)、200 次/分令牌桶、msg 子串退避、增量缓存幂等 |
| app/backend/app/factor_factory/panel_source.py | 复权唯一改动点(docstring :3-10) | 本卡只落 raw+adj_factor 分离存储;读侧 hfq/qfq 接线归后续卡,不在本卡改 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 篡改 panel:改 parquet 一字节 → `verify_manifest`/manifest 快照重放必 GAP(harness :666-709 参数化已守,不许删)
2. 伪签名:receipt 签名清零或换 key → "signature mismatch"/"pinned authority fingerprint" GAP
3. universe 篡改:300 只中换/删 1 只 → "membership snapshot" GAP
4. synthetic 冒充:合成数据+caller key → "out-of-band production authority root" GAP(test:384-391 已守)
5. 质量测试凑数:5 条重复 (column,rule_type) → registry contract 拒(test:845-883 已守)
6. look-ahead 种子:adj_factor 日期前移一天 → 新增 PIT 探针必抓(known_at 违约)
7. 停牌伪 bar:给停牌日造价格 → 新增 calendar/missingness 数据测试必抓(官方语义:停牌无 bar)

## 复用 [按需]
TushareConnector/_TUSHARE_SPEC、DatasetRegistry+DatasetManifest(data_hash/dataset_hash.py)、load_secrets bootstrap、hs300_proof_fixture(test_perf_benchmark_harness.py:48-182 = real-path 逐字段模板)、tushare_quant1 TokenPool 限流思路、market_data_contract 记录族(SemanticsRecord/InstrumentSpec/CapabilityMatrix/UseValidation)、research_design_assets UniverseDefinitionRecord。

## 红线 [按需]
A股永不实盘(本卡 research/backtest-only,capability live=False);token 绝不入代码/配置/日志/commit/汇报;KNOWN_RUN_GAP 不许 synthetic 转绿;测试对共享 data/audit 零写入(conftest 会话守卫);dual-model 审查 builder(anthropic)≠verifier(openai),approver≠creator。

## 非目标 [按需]
Run first-screen 门(harness 第二 gap,另卡);复权读侧接线(panel_source 改动另卡);CPCV/eval-methodology 三卡;执行边界;前端。

## Open Questions [按需]
- 覆盖率门风险(非拍板 hook):`_HS300_MIN_SYMBOL_COVERAGE_RATIO=0.80` 对 as-of 成分里 2019 后上市股可能天然不可满足——真数据量出实际分布后,若确不可满足,带证据+对抗测试修门(显式 missingness model),log 标 Inference 可翻案;若可满足则零改动。
- universe 码(非拍板 hook):index_weight 用 000300.SH 实跑验证,空返回则 399300.SZ 拉数、receipt 如实记录实际 source 参数。

## 验收一句话 [必填]
七个已知坏(篡 panel/伪签名/篡 universe/synthetic 冒充/凑数质量测试/look-ahead 因子/停牌伪 bar)各被对应门抓住;真实 10 年 HS300 panel 走完签名链+dual-model 审查后 harness HS300 探针 measured PASS(<3s);后端全量基线不破。
