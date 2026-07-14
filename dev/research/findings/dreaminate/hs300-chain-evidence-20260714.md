# HS300 真数据证据链 · dual-model 审查证据包（2026-07-14）

> 对应任务卡 39d08df8 / authority root `quantbt-hs300-operator-root-v1`（perf_harness.py pin）。
> builder = claude(anthropic,主上下文) / verifier = gpt-5.6-sol(openai,经 codex CLI,reasoning=ultra)。
> approver ≠ creator:pin 由 operator(dreaminate)基于 verifier verdict 执行。
> 本文件 = verdict 可下钻存证(CEO 评审 codex 声道指出 in-repo 无审查记录——本文件即回应)。

## 制品身份（最终,重建后）

| 项 | 值 |
|---|---|
| dataset_id | `hs300_daily_10y_readbench_cohort`（语义化;metadata 携 panel_semantics=benchmark_only_current_cohort / survivorship=biased_as_of_cohort / research_use=forbidden_confirmatory / volume_unit=lot_100_shares） |
| dataset_version_ref | `20260714T201056_370595_0000__856b67b1` |
| loaded_panel_sha256 = frame sha | `856b67b10efb9656273f5aa4de1c222a1fdbfaed0d37badf24ddba0e198be455`（与首建制品逐字节同——确定性生产证明） |
| universe_snapshot_sha256 | `501105ace1986d6c585f3f69008944f53f2888090212786961faffb8ee6e0516`（300 成分+签名 list_dates,v2 schema） |
| manifest_sha256 | `a7a03d5ecb6b9fc1eb296e4c68a54220eed29897290fd1c93642e53301ee1dd3` |
| verification_key_sha256 | `79d1a7b7de1cea7238bea85d5440a1a428490e573e09b1781ba6dca461791653`（key 本体在 keyring name=hs300_provenance,永不入仓） |
| bench 实测 | measured=True,observed≈0.0185-0.0188s / 阈值 3.0s |
| panel 规模 | 653,655 行 / 300 symbols / 2,446 交易日 / 跨 3,681 天 |

## 审查轮次

### 轮 1:修门对抗审（verifier 审 builder 的 e2878c66）——verdict: REJECT(带修复清单)
verifier 内存构造两个可通过面板证伪:①「恰好 80%+连续缺一年」②「谎报末日上市+单 bar」;
并指出正向测试(index 300)不判别新旧分母、v1 拆分缺失、边界对缺失。
处置(d34a1300):判别性正向(index 600,回退分母必死)/v1 双拆分/coverage±1 天与 lag 9-10 边界对/
早上市等价回归全部落地;②定性为 operator-trust 边界(签名者撒谎由跨厂商重推导兜,见轮 2);
①以真实证据裁定(现成分最长真实无 bar 连段=311 交易日[000792.SZ],有牙缺口门必误杀真数据)
→ 0.80 明文纯计数契约。措辞按 verifier 公允性意见修正。复验:benchmark 72 passed。

### 轮 2:pre-pin 链核真（verifier 独立重推导,不持 HMAC key）——verdict: `approve_pin`
verdict 原文范围声明:「仅批准当前 version_ref=20260714T194817_915479_0000__856b67b1 的
raw、operator_attested 制品进入 pin。它不是 HMAC 验证结论、不是未来同 key 所有制品的
blanket approval,也不代表整张任务卡已完成。」
独立复算结果(verifier 自己的实现,非抄 harness):
- 成员重推导:staging index_weight/202606 vs universe.json,双向 diff=0(300/300)
- 上市日重推导:stock_basic L(5,528)+D(337) vs 签名 list_dates,逐值 mismatch=0
- 哈希绑定:universe 文件字节/manifest 字节/registry canonical JSON/canonical panel frame
  四项独立重算全匹配(panel hash 同时匹配 loaded_panel/frame/registry 三处)
- 覆盖率数学(分母用 staging trade_cal,非 panel 自身):300/300 过 0.80;最低 000792.SZ
  2,127/2,446=0.8696;上市前 bar=0;79 只窗口内上市首 bar lag 全=0
- 数据真实性:seed=20260714 抽 3 股×3 日 45/45 字段与 staging 原始响应相等;
  全量双向 key diff=0,五字段 mismatch=0;确认 raw-only(无复权列)、vol 未乘 100

### 轮 3:重建 delta 核真（dataset_id 语义化+metadata 四键,panel/universe 字节不变）——verdict: `delta_verdict = approve`
verifier 独立重算六项:registry canonical record SHA `117b99b5…d16ef5` 一致;manifest SHA
`a7a03d5e…e1dd3` 一致;新旧 panel 文件 SHA 均 `0c68de17…eeb13d`(cmp exit 0,字节级同一);
loaded panel 语义 SHA `856b67b1…8be455` 三处一致;新旧 universe cmp exit 0;metadata 四键
(benchmark_only_current_cohort/biased_as_of_cohort/forbidden_confirmatory/lot_100_shares)已入 record。
附带 Eng 对抗审 3 高+若干中:高3(keygen 异常吞→无授权覆盖信任锚)已修 fail-closed;
中(.partial 后缀防 glob 撞)已修;高1(发布非事务)/高2(幂等无 sidecar)失效模式均 fail-closed
到 harness 门(半链无 receipt 必拒/错窗口必撞规模门),记卡残余不重构。

## 诚实残余（verifier 列明,operator 接受,不粉饰）

1. verifier 不持 key,未验 HMAC(签名有效性由 harness 机器验证——职责分离设计)。
2. staging 之上无 Tushare 官方签名/联网二次核对——operator_attested 是本机完整性背书,
   不是 vendor 签名或第三方审计;对机构买家的外部可信需非对称签名+透明日志(后续卡)。
3. authority root 只 pin key 指纹,不绑具体 dataset version——未来同 key 制品必须逐制品复核,
   本 verdict 不可复用放行。
4. 纯计数覆盖率允许结构化长缺口;311 日无 bar 的真实原因未由 suspension 制品(suspend_d)证明。
5. 卡 39d08df8 的对抗测试 #6(adj_factor look-ahead 探针)#7(停牌伪 bar 探针)未实现——
   属研究面资产(622 并集+adj_factor)工作,阻断卡 done,不阻断本 pin。
6. 对称 HMAC 无轮换/撤销/时间戳机制;<3s 证据无硬件上下文;frame hash 依赖 polars IPC 编码稳定性
   (本轮环境 Python 3.13.13 / polars 1.40.1[verifier 侧读数])。

## 全套验证快照（本切片 land 时点）

后端全量 6288 passed/13 skipped/0 failed(508-512s,两轮);benchmark 72 passed;
data_onboarding 21 passed;前端 423 passed+build PASS(本切片前端零 diff,主 checkout 等价跑);
compileall PASS;validate_dev PASS;data/audit 基线四项全程不变(61/20,339/26,209,663/1c1788b0bbe2)。
