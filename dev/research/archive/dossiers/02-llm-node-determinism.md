# 02 · LLM 节点的确定性与可复现

> 机构级 Agent OS 成品环节深挖 · 全程 Opus 4.8 · 对抗式核查已降权 · 重心=前沿研究+概念级推荐 · 不含 file:line 代码接线
> 簇 A

## 1. 一句话定位

数值回测里「同代码 + 同 seed → 结果 ±1e-6 可复现」的承诺，会被工作流中的 LLM 节点**结构性打破**——不是因为忘了固定 seed/temperature，而是因为推理服务端的 batch 大小随负载变化、跨硬件/驱动/张量并行度的浮点非结合性、以及托管 API 只承诺 best-effort 复现且模型可被静默更新；因此「temperature=0 = 确定性」是被一手实测反复证伪的迷思，正确的工程姿态是**用确定性脚手架（确定性脊柱）把不确定的 LLM 节点包住，并按环节把可复现目标分级（bitwise / 决策级 / 语义级），决策级可复现 + 可回放轨迹才是中低频、资产无关流程的现实目标**。

---

## 2. 前沿 SOTA 与代表系统

本环节存在两条互补路线：**工程线**（让 LLM 推理本身更确定）与**架构线**（接受 LLM 不确定、用确定性外壳包住）。

### 工程线 —— 让 LLM 本身可复现

- **Thinking Machines Lab — Batch-Invariant Kernels（批不变内核 / `batch-invariant-ops`）**
  确认 LLM 推理非确定性的根因**不是**「并发 + 浮点」这一常见误解，**而是**「batch 大小随负载非确定性变化 → RMSNorm/matmul/attention 的浮点归约顺序改变」。其实测：Qwen3-235B 在 temperature=0 下 1000 次相同请求产生 80 种不同补全，首次分歧出现在第 103 个 token。提供批不变的 RMSNorm/matmul/attention 实现，使 1000 次相同请求 bitwise 完全一致（基线 80 种）。**代价（已核对一手）：** vLLM 默认 26s → 未优化确定性内核 55s（约 +112%，约 2×）→ 改进 attention 内核 42s（约 +62%）。已开源 vLLM 集成。是「让 LLM 本身可复现」的当前 SOTA 参考实现，但 attention 依赖**尚未上游化**的 FlexAttention 改动。
  <https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/>

- **LLM-42 — Determinism via Verified Speculation（预印本，未经同行评审）**
  不改内核，在现有推理引擎（vLLM/SGLang）上加一层验证性投机解码，把强制确定性的延迟开销压到接近可忽略。相对批不变内核，是更易跨硬件/软件栈落地的方向。
  <https://arxiv.org/pdf/2601.17768>

- **Deterministic Inference across Tensor Parallel Sizes（张量并行不变内核，预印本）**
  用批不变内核把确定性扩展到不同张量并行度，消除「训练用一种并行、推理用另一种」导致的数值失配，使部署可换硬件而不改输出。批不变路线的工程延伸。
  <https://arxiv.org/pdf/2511.17826>

- **RepDL — Bit-level Reproducible Deep Learning（预印本）**
  面向 bit 级可复现训练/推理（跨 batch / 张量并行 / 框架的 bitwise 一致）的实现思路；可作「若要给某些关键环节做 bitwise 复现」的工程参考。
  <https://arxiv.org/pdf/2510.09180>

### 架构线 —— 用确定性脚手架包住不确定的 LLM

- **DFAH — Determinism-Faithfulness Assurance Harness（可回放金融 Agent，预印本，未经同行评审）**
  专为金融 tool-using LLM agent 的录制/回放 + 评测 harness：Task Runner + Trajectory Store + Grader Suite + Aggregator；区分 action / signature / decision 三级确定性；合规口径采用 **pass^k（k 次全同）而非 pass@k（平均命中）**；对比 Unconstrained 与 Schema-First（确定性代码包 LLM）两种架构。**可作我们回放 / 审计层的蓝图。**
  **【对抗核查重要更正，见 §7】** 研究发现初稿对该论文的关键数字与因果方向引用**严重失实**，已按一手核对结果在 §7 全部更正；引用其结论前必须以更正版为准。
  <https://arxiv.org/html/2601.15322>

- **LangGraph checkpoint / time-travel replay**
  每个节点自动落盘完整 state（`get_state_history` / `update_state` / 从任一 checkpoint resume），把不确定的 LLM 执行包进确定性、可调试、可审计的工作流脚手架。代表「LLM 仍是概率的，但 workflow 是确定的」这一工程范式。
  <https://dev.to/sreeni5018/debugging-non-deterministic-llm-agents-implementing-checkpoint-based-state-replay-with-langgraph-5171>

- **Constrained / structured decoding 框架（Outlines / XGrammar / Guidance / llama.cpp grammar）**
  把 JSON Schema / CFG 编译成 grammar，解码时屏蔽非法 token，**构造性保证 100% schema 合规**。消除「结构层」非确定性与解析失败，是 LLM → 确定性下游的硬接口（JSONSchemaBench 为严谨基准）。注意：schema 合规 ≠ 语义/数值正确。
  <https://github.com/Saibo-creator/Awesome-LLM-Constrained-Decoding>

- **Lean-Agent Protocol — Type-Checked Compliance（Lean 4 形式验证护栏，预印本）**
  把每个 agent 拟执行动作当作数学猜想，只有 Lean 4 内核证明其满足监管公理才放行。代表「确定性阈值/规则门控」的**最强形态**——用形式验证夹逼 LLM 自由度，而非靠概率分类器。
  <https://arxiv.org/pdf/2604.01483>

---

## 3. 关键论文（每条带 URL）

- **Defeating Nondeterminism in LLM Inference (Thinking Machines Lab, 2025-09)**
  非确定性根因是 batch-size 依赖的归约策略而非并发浮点；批不变内核可达成 1000/1000 bitwise 一致（基线 80 种），代价约 +60%（改进 attention 档）至约 +112%（未优化档）延迟。直接证伪「temperature=0 = 确定」。
  <https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/>

- **From Accuracy to Auditability: A Survey of Determinism in Financial AI Systems (arXiv 2605.23955)**
  提出 **bitwise → reproducibility → auditability 三层 taxonomy**（reproducibility = 独立执行产出「足以支撑同一下游决策」的一致结果，是 auditability 的**前置条件 / prerequisite**；注：「监管最低线 regulatory floor」是研究发现自加的规范性标签，原文无此措辞，见 §7）。一手实测：LLM AML 流程改张量并行度即 >4% 准确率方差、exact-match 掉到 0.82–0.85；信贷 KernelSHAP 特征排名跨运行漂移达 25 个位次（German Credit Jaccard@3 仅 0.71–0.76）；Elliptic 欺诈图 22.8% 节点跨 seed 翻标签。核心结论：单一概率深度模型无法同时高推理 + 严格数学确定，必须**架构分离（neuro-symbolic gateway：LLM 只做语义翻译，数学/打分/决策交确定性符号引擎）**，并把可复现做成**基础设施级一等设计约束**。
  <https://arxiv.org/html/2605.23955>

- **Replayable Financial Agents: A Determinism-Faithfulness Assurance Harness for Tool-Using LLM Agents (DFAH, arXiv 2601.15322)**
  **【经一手核对，与研究发现初稿严重不符——见 §7 critical 级降权】** 一手论文实际报告：determinism 与 **faithfulness（不是 accuracy）** 之间为**正相关 r = +0.45, p<0.01, n=51**，并明确写道这「与假设的可靠性—能力权衡相反」；论点是「高确定性 + 中等准确率 优于 高准确率 + 不可预测方差」，即**支持**追求确定性。实验规模为 12 模型 / 74 配置 × 8–24 runs（约 592–1776 run）；小模型准确率约 30–70%。研究发现初稿引用的「r = −0.11 / 决策确定性与准确率无相关 / 4705 run / 7 模型 / 20–42%」**在原文中不存在或被反转**，须剔除或更正后方可采信。
  <https://arxiv.org/html/2601.15322>

- **Self-Preference Bias in LLM-as-a-Judge (Wataoka et al., NeurIPS 2024 Safe GenAI WS, arXiv 2410.21819)**
  定义自偏好偏差量化指标；核心发现是 LLM 系统性高估**低困惑度 / 更熟悉的文本**（无论是否自产），即偏差本质是 perplexity / familiarity 而非真实质量；GPT-4 自偏好显著。含义：LLM 评判 LLM 的环节必须被确定性阈值/规则夹逼或替代。**（此条经一手核实无误。）**
  <https://arxiv.org/abs/2410.21819>

- **Quantifying and Mitigating Self-Preference Bias of LLM Judges (arXiv 2604.22891)**
  **【经一手核对，两处与原文冲突——见 §7 high 级降权】** 实际报告的是回归系数 β 从 −0.229（Claude-Sonnet-4.5）到 +0.307（LongCat-Flash-Chat），**不是**研究发现初稿所写的「−38% ~ +90%」百分比区间（该区间疑似杜撰/张冠李戴）；且该论文**明确拒绝**使用 gold judgments，改用「等质量对（equal-quality pairs，由两个参考 LLM 构造）」做无需人工金标的统计去偏——初稿「提出用 gold judgments 纠偏」说反了方法。结论方向（LLM 自打分需外部确定性锚点）本身没错，但所引数字与方法不可靠。
  <https://arxiv.org/abs/2604.22891>

- **Understanding and Mitigating Numerical Sources of Nondeterminism in LLM Inference (arXiv 2506.09501)**
  系统化归因到浮点非结合性、硬件执行路径、matmul/归约顺序；在 DeepSeek/Qwen/Llama 上即使确定性设置仍显著分歧。为数值层非确定性提供机制级证据。**（一手核实无误。）**
  <https://arxiv.org/pdf/2506.09501>

- **Impacts of floating-point non-associativity on reproducibility for HPC and deep learning (arXiv 2408.05148)**
  cuDNN 不保证跨 GPU 版本/架构 bitwise 一致；CPU vs GPU、不同驱动/编译器/库都会改归约顺序。佐证「跨硬件 bitwise 复现工程上常不可行」——正是 ±1e-6 数值回测承诺被 LLM 破坏的物理根源。**（一手核实无误。）**
  <https://arxiv.org/abs/2408.05148>

- **Stochastic CHAOS: Why Deterministic Inference Kills, and Distributional Variability Is the Heartbeat of Artificial Cognition（批判/反方，arXiv 2601.07239，预印本）**
  明确**反对**追求确定性推理，主张分布变异是认知能力来源、强行 bitwise 确定会损害模型能力（emergent abilities 消失、推理受损、对齐变脆）。代表本环节真实争议面：确定性不是免费、也未必每个环节都该追求——**支持按环节分级而非全局 bitwise**。
  <https://arxiv.org/pdf/2601.07239>

---

## 4. 机构最佳实践 / 标准

- **SR 11-7（美联储/OCC 模型风险管理指引，2011）**
  要求所有模型代码、配置、训练数据快照、超参数版本化且可追溯以支撑复现与审计。**【降权提示，见 §7】** 研究发现初稿所述「SR 11-7 需新增 prompt-variance 测试与语义一致性检查」**属第三方/厂商（含 modelop.com）对 SR 11-7 在 GenAI 时代的解释性外推，并非 SR 11-7 监管原文条款**；引用时应明确区分「监管硬性义务」与「行业解读」。可保留的有效映射：模型工件版本化 + 可追溯 → 对应我们的 prompt+model 版本钉死 + 可回放。
  <https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7>

- **EU AI Act Article 12（记录保存）**
  高风险 AI 必须在全生命周期自动记录事件日志，支持事后可追溯重建与上市后监测，日志须以可分析格式留存——把「可回放审计」上升为法定义务。**【精度降权，见 §7】** Art.12 正文只列通用事件类别（识别风险情形、支持上市后监测、监控运行）；初稿列举的细粒度字段（尤其「输入数据 / 核验人员」）实际是 Art.12(3) 对**远程生物识别系统**的专门要求，被泛化到所有高风险系统。方向合理但精度被夸大，引用时须区分通用义务与生物识别专属义务。
  <https://artificialintelligenceact.eu/article/12/>

- **NIST AI RMF + Generative AI Profile (NIST-AI-600-1)**
  围绕 Governance / Content Provenance / Pre-deployment Testing / Incident Disclosure 组织，映射 GOVERN/MAP/MEASURE/MANAGE；provenance 在 GenAI Profile 出现 151 次，强调把红队 run、失败、缓解、回归结果作为 MEASURE/MANAGE 的可追溯证据。
  <https://www.nist.gov/itl/ai-risk-management-framework>

- **OWASP GenAI Security（LLM Top 10 + Agentic Top 10 / ASI01-10, MAESTRO）**
  将概率性非确定行为、Excessive Agency（功能/权限/自治过度）列为核心风险；缓解 = 最小权限、对高影响动作强制人工审批、强身份与访问控制。为 Agent OS「高后果动作需确定性门控 + 人类确认」提供框架。
  <https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/>

- **OpenAI / Azure 托管 API 实践**
  `seed` 仅 best-effort 确定性；必须把 `system_fingerprint` 与所有参数记入 run metadata，fingerprint **一年会变几次**（模型/基础设施静默更新）。运营层面应监控 fingerprint 变化、用**不可变模型版本标识而非别名**，版本经 change-control 更新。OpenAI 官方明说即便 seed + params + system_fingerprint 全匹配仍有「small chance」输出不同。
  <https://cookbook.openai.com/examples/reproducible_outputs_with_the_seed_parameter>

- **独立加密回执门控（厂商博客，二手映射，谨慎引用）**
  每个动作执行前由独立 gate 写入不可被模型影响的密码学回执，形成模型无法篡改的审计链；厂商主张可同时满足 ISO 42001 A.6.1.6 / EU AI Act Art.12 / NIST Measure 2.5。**此为厂商博客的合规映射，属二手解读，落地引用前需核对原条款。**
  <https://agenticrail.nz/blog/ai-agent-audit-log-best-practices/>

---

## 5. 对 QuantBT 这套架构的推荐方向（概念级）

> 仅概念级方向；不点 file:line、不排实施计划。

1. **双层架构定为第一性原则：确定性脊柱 + 受控 LLM 触手。** 把流程编排、数值计算、风险打分、阈值判断、最终下单决策全部放在 bitwise 可复现的确定性引擎里（沿用现有数值回测的 seed / ±1e-6 契约）；LLM 节点只承担「意图 → 结构化参数 / 语义翻译 / 草拟」，输出必须穿过 structured decoding 落成受 schema 约束的结构化对象后才进入确定性层。与金融 AI 综述的 neuro-symbolic gateway 共识一致。

2. **把可复现按环节分级，而非全局 bitwise。** 对每个 LLM 节点显式声明其目标层级（bitwise / decision-level / semantic-level）。中低频、资产无关的多数环节取「决策级确定性 + 可回放轨迹」为现实目标；只有极少数关键判定（如最终风控门）才考虑自托管批不变内核换 bitwise。既贴合 SR 11-7 / EU AI Act 的可复现/可审计精神，又不付全局 +60%~+112% 延迟。

3. **Record/replay 作为信任的物理载体。** 每个 LLM 调用落盘不可变 fixture（完整 prompt、model 版本标识 + system_fingerprint、seed/temperature/top_p、tool 调用与返回、时间戳），cache key 必须编码「图中位置 + 上游依赖 + run index」（否则 best-of-N / 并行分支 / 流程改序会键碰撞）。回放时绕过真实 API、用录制结果重放，使流程可被第三方独立重建。**配套要求（缺口补强，见 §8）：** fixture 含敏感数据与投毒/越权面，需有完整性保护 / 防篡改 / 防投毒设计，而非裸落盘。

4. **把 prompt 与 model 版本钉死成不可变工件并纳入 change-control。** 禁止用供应商别名，强制记录 fingerprint，监控其变化并在变化时触发重新验证/回归。任何 prompt 改动走版本化 + 审批，使「是我改了措辞，还是供应商换了模型」永远可区分。

5. **用确定性阈值/规则门控剥离 LLM 的自评与自由裁量。** 凡涉及评判/打分/放行的环节，最终判定交给 hard-coded 规则、数值阈值乃至形式验证（type-checked / Lean 风格 axioms），LLM 只产出候选与理由、不持有决策权。从结构上消解 LLM-as-judge 自偏好偏差（偏好低困惑度/熟悉文本，与质量无关），也让非技术用户面对的是可解释的规则而非模型自说自话。

6. **三级确定性度量进面板，且与准确性/稳健性解耦呈现。** 对每个 LLM 节点常态化测 action / signature / decision 三级确定性（pass^k 口径）+ faithfulness（证据接地），并明确告诉用户「确定性高 ≠ 正确」。**关键区隔（缺口补强，见 §8）：** 这套 LLM 层指标须与本项目既有的数值层统计严谨工具（CSCV / PBO / DSR / walk-forward）在面板上明确分区呈现，避免 pass^k 被非技术用户误读为「模型质量分」。

7. **正视并向用户披露残余不确定性。** 在产品语义里区分「数值层 bitwise 可复现」与「LLM 层决策级可复现」，对后者给出可接受方差区间与回放凭证，而非假装做到了 ±1e-6。**额外披露（缺口补强，见 §8）：** 若产品依赖托管 API，「可回放凭证」在供应商换模型后只能重放录制结果、无法重放真实模型——这一供应商依赖须对用户/合规明说。

8. **为「确定地放大翻译错误」设计兜底。** neuro-symbolic gateway 的「LLM → 结构化参数」一步本身可能语义错误（schema 合规 ≠ 语义正确）；一旦翻译错，确定性引擎会把错误输入**确定性地、可复现地**放大成错误决策。需为翻译层设错误率监控、人工确认阈值与回滚兜底（见 §8）。

---

## 6. 架构级参考（少量伪代码 / schema 草图，非代码接线）

> 示意性草图，刻画概念边界，**不接线到现有代码**。

### 6.1 LLM 节点的可复现声明（按环节分级）

```yaml
# 每个 LLM 节点声明其可复现目标层级与门控方式
llm_node:
  id: intent_to_universe_filter
  repro_level: decision        # bitwise | decision | semantic
  decision_authority: none     # LLM 不持有最终决策权
  output_contract:
    type: structured           # 必经 constrained decoding
    schema_ref: "schemas/universe_filter.json"
  model_pin:
    provider: "<vendor>"
    model_id: "<immutable-version-id>"   # 禁用别名
    system_fingerprint: "<recorded>"
    params: { temperature: 0, top_p: 1, seed: 12345 }
  fallback:
    on_schema_invalid: reject_and_retry
    on_semantic_doubt: human_confirm     # 翻译层兜底
```

### 6.2 不可变 fixture / cache key（避免碰撞）

```python
# 概念示意：cache key 必须编码图中位置 + 上游依赖 + run index
def fixture_key(node_id, prompt, model_pin, upstream_digest, run_index):
    return sha256_canonical({
        "node": node_id,                 # 图中位置
        "prompt": prompt,
        "model": model_pin,              # 含 immutable id + fingerprint
        "upstream": upstream_digest,     # 上游依赖摘要，防 best-of-N / 分支碰撞
        "run_index": run_index,          # best-of-N / 并行分支区分
    })

# fixture 落盘需带完整性保护，而非裸存（防篡改/防投毒）
fixture = {
    "key": ..., "prompt": ..., "tool_calls": ..., "output": ...,
    "model_pin": ..., "timestamp": ...,
    "integrity": hmac_signature(...),   # 审计链一等公民
}
```

### 6.3 双层：受控 LLM 触手 → 确定性脊柱

```
intent ──► [LLM 触手]                ──► [确定性脊柱]
            意图→结构化参数/语义翻译        数值计算 / 打分 / 阈值 / 决策 / 下单
            constrained decoding 强制      bitwise 可复现 (seed, ±1e-6)
            ↓ 受 schema 约束的结构化对象     ↓ 决策由 hard-coded 规则 / 形式验证门控
            （LLM 不持决策权）              （评判权不交给 LLM，消解自偏好）
```

### 6.4 三级确定性度量（与准确性解耦）

```yaml
node_repro_report:
  node_id: intent_to_universe_filter
  pass_caret_k:                # pass^k：k 次全同（合规口径，非 pass@k）
    action_level: 0.96
    signature_level: 0.88
    decision_level: 0.74
  faithfulness:                # 证据接地，独立于确定性
    evidence_grounding: 0.81
  # 面板上须与数值层 CSCV/PBO/DSR/walk-forward 明确分区，避免误读为质量分
  caveat: "高确定性 != 高正确性"
```

---

## 7. 降权 / 争议 / 陷阱（对抗核查结论）

> 以下**原样保留**对抗核查的降权词（造数/反向引用/夸大/过度归因/二手/不可外推等限定）。

### 7.1 必须降级后才能采信（critical / high）

- **【critical · 造数 / 反向引用】DFAH（arXiv 2601.15322）的「决策确定性与准确率无相关 r = −0.11（95%CI[−0.49,0.31]）/ 4705 run / 7 模型 / 小模型 20–42%」与一手论文直接冲突且方向被反转。** 实际论文报告的是 determinism 与 **faithfulness（不是 accuracy）** 之间的**正相关 r = +0.45, p<0.01, n=51**，并明确写道这「与假设的可靠性—能力权衡相反」；论文核心论点恰恰是「高确定性 + 中等准确率 优于 高准确率 + 不可预测方差」，即**支持**追求确定性——与研究发现初稿拿它当「确定性 ≠ 质量」的反例**完全相反**。配套数字也错：是 12 模型（非 7）、74 配置 × 8–24 runs（约 592–1776 run，非 4705）、小模型准确率 30–70%（非 20–42%）。r = −0.11 与该 CI 在原文中不存在。**这是整份发现里最严重的造数/反向引用**，且它原本支撑了多条 pitfalls 与 design_directions。**处置：把 DFAH 的因果方向与数字全部剔除或更正后方可引用；它非但不支撑、反而反对「确定性 ≠ 质量」的论点。**

- **【high · 数字杜撰 + 方法说反】第二篇自偏好论文（arXiv 2604.22891）的「跨数据集自偏好 −38% ~ +90%」与「提出用 gold judgments 纠偏」两点均与一手论文冲突。** (1) 实际报告的是回归系数 β 从 −0.229（Claude-Sonnet-4.5）到 +0.307（LongCat-Flash-Chat），**不是**「−38% ~ +90%」这种百分比区间（疑似杜撰或张冠李戴）。(2) 该论文**明确拒绝**使用 gold judgments，改用「等质量对（equal-quality pairs，由两个参考 LLM 构造）」做无需人工金标的统计去偏——初稿说它「提出用 gold judgments 纠偏」**正好说反了方法**。结论方向（LLM 自打分需外部锚点）本身没错，但所引数字与方法均不可靠。

### 7.2 口径夸大 / 过度归因（medium / low）

- **【medium · favorable 方向口径选择】批不变内核「约 +60% 延迟（26s→42–55s）」把两个不同档位混成一个区间，且用偏低数字当头条。** 一手 Thinking Machines blog 实测：vLLM 默认 26s → 未优化确定性内核 55s（= +112%，约 2×）→ 改进 attention 内核 42s（= +62%）。所以 +60% 只适用于「改进 attention」那一档，「26s→55s」那一档是 +112%。把 26s→42–55s 笼统标成「约 +60%」**低估了未优化路径的真实开销近一倍**。

- **【medium · 过度归因 / 行业解读冒充监管】「SR 11-7 需新增 prompt-variance 测试与语义一致性检查」属第三方外推，非监管原文。** SR 11-7 是 2011 年美联储/OCC 模型风险管理指引，本身**不含** prompt-variance 测试或语义一致性这类 GenAI 专门要求；这些是近期第三方论文/厂商（含所引 modelop.com）对 SR 11-7 在 GenAI 时代的**解释性外推**。把它写成 SR 11-7「需新增」的要求，**把行业解读冒充监管硬性义务，属过度归因**。

- **【low · 措辞拔高】可审计性分层中把 reproducibility 称为「监管最低线 / regulatory floor」是研究发现自加的规范性标签。** 原综述（2605.23955）把 reproducibility 定义为「独立执行产出足以支撑同一下游决策的一致结果」并把它定位为 **auditability 的前置条件（prerequisite）**，**并未称其为「监管最低线」**。结论可用但措辞被拔高，易被当成「合规可直接引用的权威定性」。

- **【low · 精度夸大 / 不可泛化】EU AI Act Art.12 的细粒度字段被从生物识别专属义务泛化到所有高风险系统。** Art.12 正文只列通用事件类别；初稿列举的细粒度字段（尤其「输入数据 / 核验人员」）实际是 Art.12(3) 对**远程生物识别系统**的专门要求。方向合理但精度被夸大，引用时需区分通用义务与生物识别专属义务。

### 7.3 陷阱清单（经一手核实，保留为落地警戒）

- **`temperature=0 ⇒ 确定性` 是被一手实测反复证伪的迷思。** greedy 只让采样确定，归约顺序仍随 batch/硬件变。绝不能用它当复现保证。
- **把「同代码 + seed → ±1e-6」的数值回测心智模型直接套到 LLM 节点会失败。** LLM 非确定性来自服务端 batch / 张量并行 / 驱动，连 bitwise 跨 GPU 都不保证——必须显式区分数值层（可严格控）与 LLM 层（只能控到决策级/语义级）。
- **依赖托管 API 的 seed：仅 best-effort，且 system_fingerprint / 模型可被静默更新。** 不锁不可变版本 + 不记 fingerprint，等于复现承诺随时被供应商单方面作废。
- **用确定性当质量代理是陷阱。** 复现性必须与准确性 / faithfulness 分开度量。（注：原本支撑此条的 DFAH「r=−0.11」已被证伪，见 §7.1；但「确定性 ≠ 质量、二者须分开度量」这一**警戒本身仍成立**——它现在由 DFAH 三级确定性区分本身、以及综述的架构分离论点支撑，而非由被造的负相关数字支撑。）
- **追求全局 bitwise 既昂贵（~+60%~+112% 延迟、需特制内核、未上游化）又有反方学者认为有害（Stochastic CHAOS）。** 中低频流程多数环节用决策级/语义级复现即可，盲目 bitwise 是过度工程。
- **LLM-as-judge 自评有已证实的自偏好偏差（偏好低困惑度/熟悉文本，与质量无关）。** 任何 LLM 给自己/同族输出打分并据此决策的环节都可能自我强化偏差，必须用外部确定性阈值 / gold 标准夹逼。
- **缓存 / record-replay 的 cache key 若只按 prompt+params 哈希、不编码图中位置/上游依赖/run index，会在 best-of-N、并行分支、流程改序时产生碰撞或错误命中（AI21 实证）。**
- **结构化解码保证 schema 合规但不保证语义正确：100% JSON 有效 ≠ 数值/逻辑正确，仍需把数学/打分卸载到确定性引擎。**
- **合规口径用 pass@k（平均命中）会高估稳健性；审计应用应用 pass^k（k 次全同）这种更严的 case-level 口径。**

---

## 8. 开放问题

> 以下为对抗核查标记的「漏点 / missing angles」，作为本环节落地前必须先回答的开放问题。

1. **record/replay 的安全面被研究发现忽略。** fixture 完整存储 prompt + tool 返回 + model 输出，本身是敏感数据 / 越权 / 投毒面；且 LLM 语义缓存存在已被证实的**键碰撞攻击**（arXiv 2601.23088 "Key Collision Attack on LLM Semantic Caching"，locality 与抗碰撞 avalanche 本质冲突）。把 replay 当审计基石却不谈 fixture 的完整性保护 / 防篡改 / 防投毒，是缺口——需明确 fixture 的加密落盘、HMAC/签名、访问控制方案。

2. **成本—收益与采用现实缺失。** 批不变内核要求自托管推理（放弃托管 API）、attention 依赖未上游化的 FlexAttention 改动、+60%~+112% 延迟。对一个「A股到 paper、加密到 Binance」的中低频系统，自建确定性推理栈的工程与算力成本可能远超收益——需给出**盈亏平衡 / 何时不值得做**的判据，而非只给方向。

3. **托管 API 路线下 bitwise 根本不可达，连决策级复现都受供应商静默更新制约。** OpenAI 官方明说即便 seed + params + system_fingerprint 全匹配仍有「small chance」输出不同，且 fingerprint 一年变几次。结构性后果：若产品依赖托管 API，「可回放凭证」在供应商换模型后无法重放真实模型、只能重放录制结果，**监管意义上的「可独立重建」被削弱**——这点应对用户/合规明说，并定义供应商换模型时的重新验证流程。

4. **neuro-symbolic gateway 的已知失败模式未讨论：「确定地错」。** 「LLM → 结构化参数」这一步本身可能语义错误（schema 合规 ≠ 语义正确）；一旦翻译错，确定性引擎会把错误输入**确定性地放大成错误决策且全程可复现**。缺少对翻译层错误率 / 兜底 / 人工确认阈值的设计——需定义翻译层的语义校验与人工确认门槛。

5. **确定性度量（pass^k、三级确定性）进面板会与本项目既有的统计严谨工具（CSCV / PBO / DSR / walk-forward）产生口径竞争与误用风险。** pass^k 是 case-level 全同口径，若被非技术用户误读为「模型质量分」恰好踩中陷阱。需明确这些 LLM 层指标如何与数值层的回测稳健性指标在同一面板上**区隔呈现**，避免用户混淆两套完全不同语义的「可复现性」。

6. **反方证据（Stochastic CHAOS）的主张比「支持分级」更激进——确定化可能降智。** 它主张确定性推理会让 emergent abilities 消失、推理能力受损、安全对齐变脆。若某些 LLM 节点（语义翻译/意图理解）真因强制低温/确定化而降智，本环节的双层架构（LLM 只做翻译、被 schema 夹死）可能在不知不觉中牺牲翻译质量——「把 LLM 夹得越死、翻译越可能失真」这一与确定性目标直接冲突的张力尚未评估。

7. **所引前沿多为 2026 年新预印本（DFAH 2601.15322、LLM-42 2601.17768、Type-Checked Compliance 2604.01483、第二篇自偏好 2604.22891、批不变张量并行 2511.17826），普遍未经同行评审、无独立复现。** 研究发现把它们当成可直接落地的 SOTA 蓝图，缺少对「单篇未复现预印本」的不确定性折扣——尤其 DFAH 在被实际核对后已发现与发现描述严重不符（见 §7.1），更说明**这批新 arXiv 需逐一回到原文核对而非二手转述**。

---

## 9. 参考文献（URL）

- Thinking Machines Lab — Defeating Nondeterminism in LLM Inference / batch-invariant-ops：<https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/>
- LLM-42 — Determinism via Verified Speculation（预印本）：<https://arxiv.org/pdf/2601.17768>
- Deterministic Inference across Tensor Parallel Sizes（预印本）：<https://arxiv.org/pdf/2511.17826>
- RepDL — Bit-level Reproducible Deep Learning（预印本）：<https://arxiv.org/pdf/2510.09180>
- DFAH — Replayable Financial Agents（arXiv 2601.15322，预印本，引用前以 §7.1 更正为准）：<https://arxiv.org/html/2601.15322>
- LangGraph checkpoint / time-travel replay：<https://dev.to/sreeni5018/debugging-non-deterministic-llm-agents-implementing-checkpoint-based-state-replay-with-langgraph-5171>
- Awesome-LLM-Constrained-Decoding（Outlines / XGrammar / Guidance / llama.cpp grammar）：<https://github.com/Saibo-creator/Awesome-LLM-Constrained-Decoding>
- Lean-Agent Protocol — Type-Checked Compliance（arXiv 2604.01483，预印本）：<https://arxiv.org/pdf/2604.01483>
- From Accuracy to Auditability: A Survey of Determinism in Financial AI Systems（arXiv 2605.23955）：<https://arxiv.org/html/2605.23955>
- Self-Preference Bias in LLM-as-a-Judge（arXiv 2410.21819）：<https://arxiv.org/abs/2410.21819>
- Quantifying and Mitigating Self-Preference Bias of LLM Judges（arXiv 2604.22891，引用前以 §7.1 更正为准）：<https://arxiv.org/abs/2604.22891>
- Understanding and Mitigating Numerical Sources of Nondeterminism in LLM Inference（arXiv 2506.09501）：<https://arxiv.org/pdf/2506.09501>
- Impacts of floating-point non-associativity on reproducibility（arXiv 2408.05148）：<https://arxiv.org/abs/2408.05148>
- Stochastic CHAOS（批判/反方，arXiv 2601.07239，预印本）：<https://arxiv.org/pdf/2601.07239>
- Key Collision Attack on LLM Semantic Caching（arXiv 2601.23088，安全缺口参考）：<https://arxiv.org/abs/2601.23088>
- Fed/OCC SR 11-7（及 modelop.com GenAI 适用性解读，注意区分监管原文与厂商解读）：<https://www.modelop.com/ai-governance/ai-regulations-standards/sr-11-7>
- EU AI Act Article 12 — Record-keeping：<https://artificialintelligenceact.eu/article/12/>
- NIST AI RMF & Generative AI Profile：<https://www.nist.gov/itl/ai-risk-management-framework>
- OWASP Top 10 for Agentic Applications 2026：<https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/>
- OpenAI Cookbook — Reproducible outputs with the seed parameter：<https://cookbook.openai.com/examples/reproducible_outputs_with_the_seed_parameter>
- AgenticRail — AI Agent Audit Log Best Practices（厂商博客，二手映射，谨慎引用）：<https://agenticrail.nz/blog/ai-agent-audit-log-best-practices/>
