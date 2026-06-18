# T-020 · 验证官（部件12，异模型一致性，产 verdict_id）——脊柱最后一块

- **状态**：✅ done（2026-06-18，含生产接线 + 3 处消费方绑定修复）· **review_status**：0
- **来源**：spine 04 §3.3 ConsistencyReview + 00 §1.2-G(C9) + 06 §7-4 + R7 · **依赖**：T-013（一本账）、T-016（record/replay）
- **优先级**：P1（脊柱收口）

## 做了什么

新建 `app/verification/`（schema/verifier/store），实现"生成≠验证"(R7) 的真分离器：以**异模型/异种子/异切片**
对生成方自报值做挑战式重算，产**权威 `verdict_id`**（content-addressed），喂 T-017 假设卡 + T-019 审批门。

- **异模型不一致即 BLOCK**（不取均值，T9）：任一数值符号翻转/超容差 → `verdict=blocked`；保留两原值不平均。
- **未验证 ≠ pass**：声明缺对应重算 → `unverified` → 至少 `concern`。
- **独立性【度量】非假定**（06 §7-4）：`model_differs` 为假 → 独立性未确立 → 即便数值全合也降 `concern`
  （验证官与生成方共用同一模型可能共享低困惑度盲点，self-preference 是熟悉度非身份）。
- **裁决措辞铁律**（R7 / 00 §1.2-G / T-DET-10）：DISCLOSURE + 动态 notes 禁「组织独立 / independent
  validation / 可信 / 安全 / 保证 / 可复现 / reproducible」，仅许「非组织独立」（负向）。
- **content-addressed**：`verdict_id = vd_ + sha256(target_ref+双模型+裁决+逐项对账+独立性+replay_ref)`；
  同输入同 id、可复算；`target_ref` 入哈希 → 裁决与被审工件绑定。
- **生产接线**：main.py 注入 `VERIFIER`/`VERDICT_STORE` + 端点 `POST/GET /api/verification/verdicts`；
  审批门 `verdict_lookup=VERDICT_STORE.record_for`（接上裁决闸门，闭合 T-019 的 `[集成必补]` 缝）。

## 验收（31 对抗测试 + 10 变异全杀 + 5-lens 复核 18→5 真发现全修）

`tests/test_verification_verdict.py`（31）：T1 不一致→blocked(不取均值) / T2 容差内一致 / T3 符号翻转 /
T4 同模型→concern / T5 未复算→concern / T6 措辞守门 / T7 verdict_id content-addressed / T8 NaN /
T9 决策级 / T10 store 幂等+verdict_for / T11 集成 T-017(blocked 拒/concern 放行带 needs_review/张冠李戴拒) /
T12-13 集成 T-019(consistent 过/blocked 拒/concern 拒/未知拒) / T14 独立性轴 / T15 非法输入 / T16 to_review。
全量 **974 passed / 13 skipped**（基线 943 未破）。变异（10 个全杀）：blocked 降 concern / 独立性降级删除 /
闸门放过 concern / unverified 不触发 / store 不幂等 / 闸门去 target_ref 绑定 / store 去完整性重算 /
模型归一删除 / NaN 前置检查删除 / T-017 去 target_ref 绑定。

## 5-lens 对抗复核：18 raw → 5 真发现全修（每条独立验证）

- **#1 HIGH 验证授权旁路（verdict_id 未绑定被审工件）**：`verdict_id` 把 `target_ref` 入哈希以绑定，但消费方
  （审批门 + freeze）只读 verdict 字符串、从不校验 target_ref 匹配被晋升/冻结对象 → 拿无关/trivial 的 consistent
  裁决可授权任意晋升。**修**：(a) `verdict_lookup` 改返完整记录(`record_for`)，闸门校验 `verdict.target_ref ==
  evidence.config_hash`（缺/不符 fail-closed）；(b) `to_review()` 带 target_ref，freeze 校验 `== card_id`。
- **#2 HIGH 独立性可被伪装（同模型靠大小写/空白/Unicode 伪装成异模型）**：`model_differs` 裸串比较 → 'gpt-4'
  vs 'GPT-4 ' 判异模型 → 假 consistent。**修**：`_norm_model`（NFC+strip+casefold），与 approval/gate.py 的
  approver≠creator 自审防护一致。（#4 MEDIUM NFC/NFD 同根，一并修。）
- **#3 HIGH store 读路径无完整性校验（篡改的 blocked 静默放行）**：verdict_id content-addressed 但读时不重算 →
  手改 blocked→consistent 流入闸门。**修**：`record_for`/`get`/`verdict_for`/`list_all` 重算 verdict_id 比对，
  不符 raise `VerdictTamperError`（读路径==被核验路径，同 T-013 verify_chain / T-016 HMAC 不变量）；闸门 catch→
  fail-closed 缺口。
- **#5 MEDIUM NaN 非对称漏判**：自报 NaN/Inf + 缺对侧重算时先命中 None 短路 → 落 concern 非 blocked。**修**：
  存在侧 NaN/Inf 前置检查先于 None 判断 → mismatch/blocking。
- 单一 id 计算口径：mint 与 store 完整性校验共用 `compute_verdict_id`（schema.py），杜绝两处口径漂移自证。

## 诚实标注 / 残余

- 单用户场景：验证官是"第二双眼睛"，**非组织独立**验证（裁决文案明示）；独立性按 `independence` 字段度量。
- 跨模型相关偏差（06 open-Q#4）：异模型仍可能共享盲点；本实现度量轴数（model/seed/slice），未度量语义相关性
  ——长期可接困惑度/embedding 相关性度量，当前以轴数 + 同模型强制降级兜底。
- LLM 驱动的验证官（真异模型 agent 调用）走 T-016 record/replay，`replay_ref` 指 fixture；本部件提供数值/
  决策对账内核，agent 编排是上层组装。

## 脊柱收口

第0层 T-012/013/014 → 第1层 T-015 → 第2层 T-016/017 → 第3层 T-018(gate 组件，生产接线→T-021)/019/**020**。
**8 块全建并验证**（T-018 生产接线诚实 deferred→T-021）。验证官闭合 T-017/T-019 的 `[集成必补]` 缝：
假设卡冻结与模型晋升现在都受异模型一致性裁决守门，且裁决与被审工件绑定、防篡改、concern≠pass。
