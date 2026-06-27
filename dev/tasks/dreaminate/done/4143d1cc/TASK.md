---
uuid: 4143d1ccce7546bdb70c7d7791baa43f
title: External expert identity and signed attestation verification
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: trust-layer-expert-signature
source: goal-gap
source_ref: GOAL §13 Trust Layer external expert account/signature system
depends_on: [a952f63e019644bcacd1c319dfbe4be4, acd267d19c9542c08700755ffc473ed9]
created_at: 2026-06-27
completed_at: 2026-06-28
---

# External expert identity and signed attestation verification

## Scope [必填]
新增 external reviewer identity registry 与 signed attestation verification record：外部专家身份登记 Ed25519 public key、public key fingerprint、identity provider ref、independence/evidence refs；签名验证记录引用已登记 ExternalExpertReview，验证 reviewer identity 与 detached signature 后写 `verified_signature_ref` / `verification_hash`。Trust summary 和 Trust UI 可查看/提交 identity 与 signature verification。

## 上下文 / 动机 [按需]
`a952f63e` 已有 ExternalExpertReview record，但 `signed_attestation_ref` 仍只是字符串。`acd267d1` release approval 可以引用 expert review，但没有一个可验证的签名对象。不能把“有 ref”说成“真实签名已验证”。本卡先把签名验证本地 runtime 面落地，不接外部身份平台、企业 SSO、KYC 或电子签服务。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 改什么 |
|---|---|
| `app/backend/app/research_os/trust_layer.py` | 新增 ExternalReviewerIdentityRecord、ExternalExpertSignatureRecord、validator/store/API helper |
| `app/backend/app/research_os/__init__.py` | 导出 identity/signature record/store/helper |
| `app/backend/app/main.py` | 新增 `/api/research-os/trust/expert_identities` 与 `/expert_signatures`，summary 回显 totals/records |
| `app/backend/tests/test_trust_layer.py` | 覆盖 identity success、bad public key、reviewer mismatch、bad signature、secret payload fail-closed |
| `app/frontend/src/pages/workshop/agent-workbench/TrustDisclosurePanel.tsx` | Trust tab 增加 expert identity/signature verification UI |
| `app/frontend/src/pages/workshop/agent-workbench/TrustDisclosurePanel.test.tsx` | 覆盖 payload、success summary、缺 signature 前端阻断 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. agent/system/self/user reviewer 不能登记 identity。
2. invalid public key PEM 必须拒绝，不写 identity。
3. signature reviewer 与 expert review reviewer 不一致必须拒绝。
4. bad signature 必须拒绝，不写 signature record。
5. signature payload/evidence/public key 中出现 plaintext secret 必须拒绝。
6. summary/UI 只显示 refs/fingerprint/verification hash，不泄露 private key 或 raw signed payload。

## 红线 [按需]
- 不保存 private key。
- 不把本地 signature verification 说成外部组织账号系统、KYC、SSO、电子签平台或线上审批。
- 不用 agent/system/self/generic user 伪装外部 reviewer。

## 非目标 [按需]
不实现外部身份平台、证书链、组织审批流、电子签 SaaS、CI release 或线上验收。

## 验收一句话 [必填]
Trust layer 能登记外部专家 public-key identity，并对已登记 expert review 的 detached Ed25519 signature 生成可 replay 的 verified signature record；坏身份、坏签名和 secret-bearing payload 都 fail-closed。

## 完成记录（2026-06-28）
- 新增 `ExternalReviewerIdentityRecord`、`ExternalExpertSignatureRecord` 与 `PersistentExternalExpertSignatureRegistry`，以 JSONL append-only 记录外部 reviewer identity 和 verified detached signature。
- identity validator 要求 Ed25519 public key、identity provider ref、reviewer independence ref 和 evidence refs；拒绝 agent/system/self/user reviewer、坏 public key、private-key/secret marker。
- signature validator 对已登记 `ExternalExpertReviewRecord` 构造 canonical payload，校验 reviewer/identity/public key/attestation/payload hash，并用登记 public key 验证 detached Ed25519 signature；坏签名不写 signature record。
- 新增 `/api/research-os/trust/expert_identities` 与 `/api/research-os/trust/expert_signatures`；trust summary 回显 identity/signature totals 和 refs/hash/fingerprint 摘要，不回显 private key、raw payload 或 `signature_b64`。
- Trust tab 新增 expert identity 与 expert signature verification 表单，可提交 identity public key PEM 和 detached signature；缺 required field 时前端阻断，不打后端。
- 本地验证：
  - `python -m compileall -q app/backend/app` -> PASS。
  - `python -m pytest app/backend/tests/test_trust_layer.py app/backend/tests/test_research_os_rdp_publish.py app/backend/tests/test_goal_coverage.py -q` -> 63 passed / 2 warnings。
  - `cd app/frontend && npm test -- TrustDisclosurePanel.test.tsx --run` -> 1 file / 4 tests passed。
  - `cd app/frontend && npm test -- agentWorkbench.test.tsx MethodologyValidationPanel.test.tsx RDPExportPanel.test.tsx ResearchRAGPanel.test.tsx TrustDisclosurePanel.test.tsx --run` -> 5 files / 76 tests passed。
  - `cd app/frontend && npm test -- --run` -> 30 files / 330 tests passed。
  - `cd app/frontend && npm run build` -> PASS（保留既有 Vite chunk-size warning）。
  - `python -m pytest app/backend/tests -q` -> 1867 passed / 13 skipped / 283 warnings。
  - `python dev/scripts/validate_dev.py` -> PASS（49 ✅ / 0 ❌ / 0 ⚠️；248 cards）。
  - assigned-vs-done duplicate task id check -> no output。
  - `git diff --check` -> PASS。

## 边界
这是本地 external reviewer identity registry 与 detached Ed25519 signature verification 记录面，不是外部身份平台、KYC、SSO、电子签 SaaS、组织审批流、CI、线上发布或用户验收。
