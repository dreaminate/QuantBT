---
uuid: 62fdfebdbd764c8f84ce527fed458e71
title: Governed Compiler IR persistent store and backend API
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: research-os-compiler
source: goal-gap
source_ref: dev/GOAL.md §1/§7/§8 + dev/state/dreaminate/state.md 头号 gap #1
depends_on: [1d16328c71914babb772fa899b753c07, 5bb5d9da2f75469580ebbc74edf456fd]
---

# Governed Compiler IR persistent store and backend API

## Scope [必填]
Add the first Governed Compiler IR runtime surface behind the existing QRO /
Research Graph spine. The store must persist compiler IR records and compiler
pass records through JSONL replay, reject IR that lacks QRO, Research Graph
command, canonical command, permission, evidence, validation, deterministic run
plan, or rollback refs, and reject compiler passes that try to bypass
permissions, directly mutate the graph, or embed raw LLM output as IR.

This is not a full compiler implementation, canvas mutation engine, projection
index, scheduler, or production execution compiler. It creates the durable IR
audit layer those later paths must use.

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/compiler.py` | Add compiler IR/pass contracts and persistent JSONL store |
| `app/backend/app/research_os/__init__.py` | Export compiler records/store/validators |
| `app/backend/app/main.py` | Add app-level compiler store and `/api/research-os/compiler/*` endpoints |
| `app/backend/tests/test_governed_compiler.py` | Prove validation and persistence |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. Valid compiler IR + pass persists across store restart.
2. IR missing QRO / graph command / canonical command / evidence / validation refs returns 422 and does not write JSONL.
3. Compiler pass with direct graph mutation, permission bypass, or raw LLM output embedded as IR is rejected.
4. Compiler pass referencing unknown output IR is rejected.
5. Malformed persisted history fails closed at startup.

## 验收一句话 [必填]
Governed Compiler has a durable IR/pass audit store and backend API; full
compiler passes, projection index, canvas mutation, and all-entrypoint compiler
wiring remain explicitly separate.

## 完成记录
- Runtime: added `CompilerIRRecord`, `CompilerPassRecord`, compiler validators, and `PersistentCompilerIRStore` in `app/backend/app/research_os/compiler.py`. Records append/replay through JSONL and malformed history fails closed.
- API: `app/backend/app/main.py` now owns `COMPILER_IR_STORE` at `DATA_ROOT/audit/compiler_ir.jsonl` and exposes `POST /api/research-os/compiler/ir`, `POST /api/research-os/compiler/passes`, and `GET /api/research-os/compiler/summary`.
- Tests: added `app/backend/tests/test_governed_compiler.py` for IR required refs, unsafe compiler pass rejection, unknown IR rejection, restart replay, malformed history, API write/list, and no-write rejection cases.
- Validation: `python -m pytest tests/test_governed_compiler.py -q` -> `8 passed, 2 warnings`.
- Validation: Research OS scoped group -> `65 passed, 2 warnings`.
- Validation: full backend `python -m pytest -q` -> `1457 passed, 13 skipped, 278 warnings`.
- Boundary: this does not implement full compiler passes, projection index, canvas mutation engine, scheduler, or all-entrypoint compiler wiring.
