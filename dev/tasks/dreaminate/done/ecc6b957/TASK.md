---
uuid: ecc6b95746104fd987599e5ac387f536
title: Mathematical Spine full-chain registry and API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: research-os-mathematical-spine
source: goal-gap
source_ref: GOAL §6 Mathematical Research Layer; GOAL §9 factor/model/signal/strategy boundary; GOAL §15 model governance; GOAL §16 theory-to-implementation consistency
depends_on: []
completed_at: 2026-06-27
---

# Mathematical Spine full-chain registry and API

## Scope [必填]
新增 data→factor→model→forecast→signal→strategy→portfolio→risk→execution→backtest→attribution→monitor 的 Mathematical Spine full-chain record、append-only registry 和 API summary，强制绑定 TheoryImplementationBinding refs、ConsistencyCheck refs、evidence refs、validation refs、methodology/responsibility refs。

## 上下文 / 动机 [按需]
`TheoryImplementationBinding` 和 `ConsistencyCheck` 已存在，但 `state.md` 明确说 Mathematical Spine 还没有贯穿 data→factor→model→signal→portfolio→execution→backtest→attribution→monitor。本卡补一条全链 refs 记录面，不声称每个生产者已自动写入，只让完整链路可以被统一登记、验证和 replay。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/spine.py` | 新增 `MathematicalSpineChainRecord`、validator、JSONL registry 和 dict parser |
| `app/backend/app/research_os/__init__.py` | 导出 full-chain spine record/registry/validator |
| `app/backend/app/main.py` | 新增 `MATHEMATICAL_SPINE_CHAIN_REGISTRY`、`POST /api/research-os/spine/mathematical_chains`、summary endpoint |
| `app/backend/tests/test_research_os_spine.py` | 覆盖缺段/一致性失败/silent mock、registry replay、API actor override |
| `dev/state/dreaminate/state.md` / `dev/research/TRACE.md` / `dev/log/dreaminate/log.md` | 落档 §6/§9/§15/§16 推进和剩余边界 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. full-chain record 缺 model、forecast、execution、monitor 等任一关键 ref 必须拒绝。
2. 缺 TheoryImplementationBinding refs、ConsistencyCheck refs、evidence refs 或 validation refs 必须拒绝。
3. `consistency_verdict` 非 checked/accepted 必须拒绝。
4. `silent_mock_fallback_used=true` 必须拒绝。
5. API 写入必须用当前 user 覆盖 payload 里的 `recorded_by`，避免客户端伪造 actor。

## 红线 [按需]
- 不声称所有生产者已自动写 full-chain record。
- 不把 refs registry 说成数学证明或生产 readiness。
- 不允许 silent mock fallback 进入 full-chain record。

## 非目标 [按需]
不实现自动 compiler pass、strategy code generator、全入口 producer wiring、完整 graph database、前端 inspector UI、CI/线上验证或用户验收。

## 验收一句话 [必填]
完整 Mathematical Spine 链路现在可以作为 append-only refs record 写入/replay；缺关键段、缺绑定/一致性/证据/验证或 silent mock 时 fail-closed。

## 完成记录
- 新增 `MathematicalSpineChainRecord`，覆盖 data semantics、factor、model、forecast、signal contract、StrategyBook、portfolio/risk/execution policies、backtest、attribution、monitor refs。
- 新增 `validate_mathematical_spine_chain()`，拒绝缺关键段、缺 theory/consistency/evidence/validation refs、consistency 未 checked/accepted、silent mock fallback。
- 新增 `PersistentMathematicalSpineChainRegistry`，以 JSONL append-only 记录 `mathematical_spine_chain_recorded` event，可 replay；无效记录不写文件。
- 新增 `/api/research-os/spine/mathematical_chains` 和 `/api/research-os/spine/mathematical_chains/summary`；API 以当前 user 覆盖 `recorded_by`。
- 验证：`pytest app/backend/tests/test_research_os_spine.py -q` → **13 passed / 2 warnings**；spine/methodology/trust/goal/compiler/factor/execution adjacent → **154 passed / 2 warnings**；`python -m compileall -q app/backend/app` → PASS。
