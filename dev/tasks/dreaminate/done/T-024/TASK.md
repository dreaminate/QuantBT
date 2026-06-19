# T-024 · 可证伪假设卡接进 Run 生命周期（P2 不挡探索）

- **状态**：done · **review_status**：1（用户 2026-06-19 过目通过，同 T-023）
- **来源**：spine-designs 04（§4 接线 / §5 对抗）+ P2/R1 + R5/R7 措辞 + D-T024/D-T024-OOS/D-T024-FALS · **依赖**：T-017/T-013/T-020 · **优先级**：P1

## 做了什么（向后兼容、扩展不替换）

把已建的假设卡组件（T-017）接进 Run→promote 流：

- **`Run` 字段**（`experiments/store.py`）：加可空 `hypothesis_card_id: str|None`、`layer:
  Literal['exploratory','secondary','confirmatory']|None`。store 不强制校验；`get_run` 对缺字段旧行默认兜底（向后兼容）。
- **`HYPOTHESIS_STORE`**（`main.py`）：`HypothesisCardStore(DATA_ROOT/"experiments")` 实例化。
- **6 个端点**：`POST /api/hypothesis_cards`（create，探索可空 falsifiable）·`GET /{id}`·`POST /{id}/promote`
  （探索→确认，污染拒 409）·`POST /{id}/freeze`（honest-N 实读自 LEDGER）·`GET /{id}/gate`·`POST /{id}/deviation`。
- **promote_model 假设卡闸门**（`main.py`，传 `hypothesis_card_id` 才启用，不破坏既有 promote）：confirmatory 卡先过
  `can_touch_final_oos`（探索层/未冻结/OOS 已消费 → 409）；非 confirmatory 卡走真钱（production/live_crypto/paper）
  → 409 拒，**绝不自动晋级**（晋级是用户显式动作，D-T024）；纯探索（无真钱意图）不挡（**P2**）。
- **D-T024-FALS（低可证伪性 = 硬透明 + 软决定）**：`hypothesis/store.py` `freeze()` 加 `override_note` 参——
  confidence=low + `human_reviewed=False` → 拒（不静默冻结=硬透明）；`human_reviewed=True` 显式 override 后仍可冻结，
  **override 留痕进卡**（`multiplicity.falsifiability_override`，进 content_hash 防篡改）+ needs_human_review 永不静音 +
  可证伪裁决仍记 low（绝不渲染绿）。启发式**绝不自动硬挡晋级**；结构空机制（三必填空白）与验证官 blocked 仍硬拒，不被 override 放过。

## 验收（对抗测试 + 措辞黑名单）

`tests/test_hypothesis_run_wiring.py` 16 passed（组件内部行为已由 `test_hypothesis_card.py` 35 钉死，本卡测接线）：
Run 字段可空 + 旧行兼容；D-T024-FALS 低可证伪 409→override 200+留痕、结构空机制 override 仍硬拒、验证官 blocked
override 仍硬拒、override 记录冻结只读不可抹；P2 探索 create 放行；freeze 端点 low 409→ack 200+留痕；gate 端点探索层
BLOCK；promote 污染 409；deviation；promote_model 闸门（confirmatory 未冻结→409、exploratory+真钱→409、无 card_id
不挡=向后兼容、exploratory+staging 不挡）；措辞黑名单（可信/安全/保证/已验证/trustworthy/proven/组织独立）0 hit。
全量 **1046 passed / 13 skipped**（基线未破）。

**5-lens 对抗复核**：honest-n-p2 / wording-honesty 等 lens 无真发现（exploratory 不挡、低可证伪不自动硬挡、空机制硬拒、
honest-N 无谎报口均经异模型核实）。

## 诚实残余 [集成必补]

T-023 内核 / 验证官 / regime 真落地后补端到端集成测试；当前接线层在 mock/真组件混合下绿，**绝不渲染成「已验证安全」**。
前端 Card 管理页归 E 簇信任层（不碰冻结的 RunDetailPage），本卡只做后端契约 + 端点。
