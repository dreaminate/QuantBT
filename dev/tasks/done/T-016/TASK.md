# T-016 · LLM record/replay + 受控翻译层

- **状态**：done
- **review_status**：1（用户 2026-06-19 确认）
- **来源**：spine-designs 02（§4 接线 + §5 A1–A6/B1–B3/C1/D1–D4/E1）+ R11/R7/R12 + 00 §1.2-E（fixture_key=node_id）
- **优先级**：P1 · **依赖**：T-013（一本账 honest-N）

## Scope（单一能力单元）

把「裸调真实 API、输出无凭证、不可重放」的 `AgentRuntime→LLMClient.chat()` 链路，改造成
**受控翻译层（LLM 只产受 schema 约束对象、不持决策权）+ 不可变 fixture record/replay（HMAC 完整性
+ 内容寻址 cache key）**。LLM 是触手、确定性脊柱是骨架，本部件是二者间防伪/可回放硬接口。

## 做了什么

新建 `app/agent/replay/` 包（复用 `ids.fixture_key`/`canonical_json`/`content_hash`）：
- `fixture.py`：`ModelPin`（别名检测）+ `FixtureKey`（内容寻址 `llmfx-`，编码 node_pos+prompt+model_pin+
  upstream+run_index，**fingerprint 不入 key**）+ `LLMFixture` + HMAC（**只签内容/身份、不签可变 provenance**）。
- `store.py`：`FixtureStore` append-only + HMAC + fingerprint 漂移事件 + 别名事件 + tombstone 不减 distinct +
  内容寻址幂等 put + **get 回退到最近有效行**（伪造追加行不锁死好 fixture）+ 坏行发事件不静默。
- `recording_client.py`：`RecordingLLMClient`（record/replay/passthrough）。**replay 未命中 raise ReplayMiss、
  绝不打真 API（R11 命门）**。
- `translation.py`：`ControlledTranslator`（schema 校验 + 语义不变量：杠杆超注入上限 → human_confirm；
  鲁棒于字符串/列表/camelCase/加词变体杠杆，排除 bool/relevance 误伤）。
- `repro.py`：`ReproLevel`（bitwise/decision/semantic）+ pass^k 严口径 + 「高确定性≠高正确性」披露。
- 接线：`LLMResponse` 扩展（model_id/fingerprint/fixture_key/repro_level/translation_status，全默认）；
  `AgentRuntime` 可选翻译门（**任何非 ok 状态都不派发**）；`main.py` opt-in（`LLM_REPLAY_MODE`，默认
  passthrough=行为不变）+ **每 turn 唯一 run_id** + 武装翻译门。

## 验收（30 对抗测试 + 变异全杀 + 5-lens 复核 14 真发现全修）

`tests/test_llm_record_replay.py`：A1 replay 调真 API=0 / A2 篡改→IntegrityError / A3 key 不碰撞 /
A4 确定地错→human_confirm + 不派发 / A5 fingerprint 漂移事件 / A6 别名告警 / B1 逐字节重放 / B3 三级度量
解耦 / C1 key 独立重算 / D1 幂等+冲突 / D2/D13 tombstone 不减 N（含 rebuild 路径）/ D3 崩溃恢复 / D4 一次性
消费 / E1 措辞 + 复核回归（字符串/列表/变体杠杆绕过、schema_invalid 不派发、tombstone/consume 后 get 可读、
伪造追加行回退、坏行发事件、不同 run_id 不复用陈旧答案）。
`python -m pytest tests/test_llm_record_replay.py -v` → **30 passed**。
全量 **874 passed / 13 skipped**（860 基线未破）。变异：replay 回退 / HMAC 失效 / tombstone 减 N /
字符串杠杆绕过 / schema_invalid 派发 / get 无回退 → 全杀。

## 对抗复核（ultracode 5-lens workflow）确认 14 真发现全修

- **#1/#7 HIGH（现场复现）**：main.py 用常量 run_id="run-agent" + 每 turn 新 client（_step 归 0）→ 同 prompt
  跨 turn 撞同一 fixture_key → record 模式静默复用陈旧答案（"PNL +5%" 顶替 "PNL -90% LIQUIDATED"，真 LLM 调 0 次）。
  修：每 turn 唯一 run_id。
- **#4 HIGH**：tombstone/consume 改签名字段不重签 → get() 误报 IntegrityError、fixture 锁死。修：**HMAC 只签内容**
  （tombstoned/consumed/created_at_utc 不签）——一并修了 #6/#14 幂等。
- **#8/#9/#10/#11 HIGH（翻译门绕过）**：字符串"30"/列表[10,30]/camelCase/加词变体杠杆全绕过；schema_invalid 仍派发。
  修：鲁棒杠杆采集 + 任何非 ok 不派发。
- **#5/#12 MED-HIGH**：伪造追加行锁死好 fixture / 坏行静默缩水 distinct。修：get 回退最近有效行 + 坏行发事件。
- **#3 MED**：翻译门接了没武装（生产无 translator）。修：main.py 武装 ControlledTranslator(cap=3.0)。
- **#2/#13 MED 测试剧场**：A3 只测 FixtureKey 原语、未测生产 wiring；rebuild 路径 tombstone 守卫零覆盖。补回归。
- 注：复核期间 `store.py` 的 tombstone/consume 重签 + 测试文件有外部协同修改，已整合（与内容寻址签名兼容）。

## 诚实 deferred（已记录，非阻断）

- 受控解码（seed/top_p/response_format 传真 API + provider 抽 system_fingerprint）：providers 层未改，
  fixture 现record供应商回传的 fingerprint（有则记、无则诚实标 None）。
- replay 命中后 agent_runtime 重跑翻译（确定性、行为一致）；可改为信任 fixture.translation_status。
- 翻译门杠杆检查现扫所有 tool_call；可收窄到执行类 tool（schema 驱动）。

## 下一步

T-017 04 假设卡（P2 不挡探索）。
