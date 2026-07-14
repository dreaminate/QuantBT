<!-- 重生型:每个 loop/session 收尾整篇覆写,永远只有最新一份(历史在 git)。模板 state/_TEMPLATE.frontier.md -->
# FRONTIER · dreaminate 前沿快照（重生型 · 每次整篇覆写）

> 给下一个 session/loop 的续接现场。**覆写,不追加**——旧快照不保留(要历史看 git log 本文件)。
> 与 `state.md` 分工:state = 对照 GOAL 的 gap 表(慢变);frontier = 正在进行的战役现场(每 loop 全刷)。

## 现在打到哪了
- **/loop 15m 自主循环运行中**(cron ce958a8c)。首轮启动切片 ✅(脏区收口 land `f41789dc`)。
- **切片① 39d08df8 · HS300 真数据证据链:核心目标已达成,本批已 land**——
  **GOAL §16「沪深300×10年日频读取<3s」以完整诚实链真数据转绿:measured=True / 0.0185s**。
  链条全走:pull(产线化,180/分限流+退避+幂等)→ preflight(12 项镜像门)→ DatasetVersion
  `hs300_daily_10y_readbench_cohort@20260714T201056_370595_0000__856b67b1`(65.4 万行,
  metadata 携 benchmark_only/survivorship/forbidden_confirmatory/volume_unit 四键)→
  不可变 manifest → HMAC 签名 universe(v2 携 300 成员 list_dates)+receipt → **跨厂商
  dual-model 三轮审查**(修门 REJECT→修复→chain approve_pin→delta approve)→ operator pin
  `quantbt-hs300-operator-root-v1`(指纹 79d1a7b7…1653;key 在 keyring 永不入仓)。
  证据包在仓可下钻:`dev/research/findings/dreaminate/hs300-chain-evidence-20260714.md`。
- **harness 修门已 land**:覆盖率「自上市起算」(0.80 纯计数契约,311 天真实停牌实证)+签名
  list_dates(universe v2)+上市前 bar 拒+首 bar 滞后≤10 天;72 benchmark 测试(59 保+13 新)。
- **autoplan 四相评审已跑完**(CEO/Eng/DX 各双声道+我=三方;Design 跳过=前端零 diff):
  三声道收敛必修项全落——fetch 产线化/README 漂移修正/语义化 dataset_id+metadata 入签名制品/
  store-token 子命令/keygen 死路纠偏/quickstart 一页/assert→raise/keygen fail-closed/
  .partial 防 glob 撞/monotonic 限速/三参数一致性校验。评审产物:autoplan restore point +
  本 frontier + 证据包。
- **卡 39d08df8 仍 in_progress**(核心已达,验收未全):余项=对抗测试 #6(adj_factor look-ahead
  探针)#7(停牌伪 bar 探针)+研究面资产注册(622 并集含退市+adj_factor,独立 dataset_id)。

## 活跃上下文
- **audit 基线四项全程不变**:61/20,339/26,209,663/`1c1788b0bbe2`(canonical 配方:
  `cd data/audit && find . -type f | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256`)。
- **测试基线(实跑)**:后端全量 **6288→(终验以最新实跑为准)** passed/0 failed;benchmark 72;
  data_onboarding 24;前端 423+build PASS(本切片前端零 diff);validate_dev PASS(两个已知 ⚠️:
  state.md 蒸馏归档=后续切片)。
- **本机制品(gitignored,不入仓)**:staging=data/.cache/tushare_hs300_raw(68MB);
  链产物=data/datasets/{registry.jsonl,lake/,provenance/,manifests/};keyring:tushare token+
  hs300_provenance key。fetch 脚本已产线化(scripts/hs300_onboard.py pull),tmp 脚本弃用。
- **工作模式**:EnterWorktree 编辑→过门→主 checkout merge main→push;codex(gpt-5.6-sol ultra)
  =跨厂商 verifier(builder≠verifier);分类器拒改 .claude/settings.json(不再试)。
- **诚实残余(证据包详列)**:operator_attested≠vendor 签名/第三方审计;对称 HMAC 无轮换撤销;
  root 只 pin key 指纹不绑 version(未来制品逐个复核);纯计数覆盖率不建模停牌结构(suspend_d
  制品=后续);_sha256_of_frame 依赖 polars IPC 编码稳定(共享基建,勿单方动);
  DatasetVersion.to_dict schema 演化会破旧 receipt 重算(共享基建,记录待改);
  build 非版本寻址目录(重跑覆盖旧产物,门会拦但旧证毁);Run first-screen 门=harness 第二 gap(另卡)。
- **下一步(优先序)**:① 卡 39d08df8 收口:研究面资产注册+探针 #6/#7 ② 切片③ CI 接入
  (GitHub Actions+gh 真查,CI 字段才能脱离 Unqueried) ③ 切片② dual-model gate 应用内跨厂商接线
  ④ state.md 蒸馏归档(validate 两 ⚠️) ⑤ pool 三张 eval 卡。CEO 声道战略提示已记:下一波优先
  用户可感知面(Run 首屏/前端 bundle),数据溯源线到此为止别继续递归加固。

## 待裁 / 卡点
- 无阻塞性待拍板。已按「可逆+不越线」自决并 log 标 Inference 的:token 迁 keyring/覆盖率门
  0.80 纯计数契约/契约常量留 harness 原位(生产者镜像+相等性钉死)/幸存者 cohort 案否决。
- 等用户拍板(非阻塞,registered):90+ 历史 worktree/分支清单(只列不删);DVC vs 自建数据版本化
  的 ADR 补记;非对称签名(Ed25519+轮换撤销)升级时机;2026-06-29 四项旧待裁(核实存活性后再摆)。
