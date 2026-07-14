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

### 轮 4:研究面资产增量审（ef6115fc）——verdict: `reject` → 修复(72f48d41) → 确认审进行中
verifier 四反例(全部实跑复现):①「|r|>3.5 单边门」——r 恒>-1,factor 下崩不可达(÷10 得 r=-0.9 照过);
②单日 ×4 产生 +3.0/-0.75 双尖峰,单腿过硬门;③供应商用「09:30-09:30」退化窗编码全天停牌
(对照上交所公告实证 688005.SH 20260116),伪 bar 被当半日放行;④null close 在比较式中被 sum 吞=fail-open。
修复:对称比率门 max(q,1/q)>5.5(band 按双向真实极值:上行 4.06 盐湖复牌/下行 4.75 必康退市整理
——4.5 初版被真实必康事件打回重校准);成对回转检测(反号>0.30 且乘积回 1±5%,真实数据零此模式);
退化窗/未知格式保守判全天;bars 七列 null 门。四反例全部钉死为回归测试;检测下限显式成文
(带内互换/常数缩放[收益语义中性]/混叠区)。
**口径修正(operator 认错)**:此前「532 处 factor 回撤全在无 bar 日」表述错误——verifier 复算:
523 处在 bar 日(量级带内,hfq 影响可忽略),仅 8 处大回撤(>0.1%)无 bar;评估结论不变,表述已改。
另:研究面 registry sha 只绑 bars frame(manifest 三文件哈希单独成立,非密码学总绑定)——记录性边界。

### 轮 5-7:研究面质量门四轮对抗(codex 全 reject → 数学收敛 + scope 裁定)
- 轮5 reject:q·q' 成对判据被价格漂移洗白(中间 factor 精确相消)+首尾删失盲区+带空格退化窗
  → 修:factor 比率判据/边界规则/去空格;根因修复(__fq 曾在 drop_nulls 后算,首腿失明)。
- 轮6 reject:浮点端点(1.05 溢出容差)+隔腿双尖峰逃逸紧邻判据
  → 数学收敛:废弃成对/边界两检测器,换单一不变量「|fq-1|>0.30 ∧ |r|>0.30 同现即违规」
  (合法公司行动被价格补偿,r 落常带)。合成基底修诚实(旧基底自身违反不变量被新规则照出)。
  检测下限对抗后收窄:近除权日错置会解耦补偿被抓;仅平坦区带内小幅伪造不可检。
- 轮7 reject(最终):①NaN 注入 fail-open(finite 门缺失)——已修+回归测试;
  ②canonical floor 构造:真实暴跌日(002411 20230619 -78.95%,fq=1 纯价格事件)反向伪造
  ×4.75 后缀 factor 使 q≈1——单源自洽、与价格精确耦合,质量门层数学上不可分辨。
  codex 同轮确认:历史全部反例(轮4×4/轮5×3/轮6×2)重放全死;39 tests passed;
  真实制品 10/10 PASS 不变量零触发。
- **operator scope 裁定(Inference,可翻案,登记待用户复核)**:质量门威胁模型=「无意损坏」
  (管线错误/错位/删失/vendor 错误/NaN);对抗性防篡改由签名链+确定性重拉比对+跨源事件表+
  factor vintage(后续卡)承担。codex 轮7 reject 的依据是对抗性标准,超出本层承诺——
  裁定不再迭代本层,floor 构造以 documented-miss 测试入档,全部 verdict 轨迹留档不洗白。
  研究面资产不携带 independence claim(与基准面 approve_pin 性质不同)。

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
