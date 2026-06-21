import { type SideEffect } from "../../../components/desk";
import { type PermissionMode } from "../../../components/desk";

/**
 * 权限门治理逻辑（D-PERM 核心：权限轴 ⟂ 治理轴）。
 *
 * 不变量（违一条即 D-PERM 失守）：
 *  ① side_effect ∈ {realmoney, external} → 任何权限模式（含 bypass/auto）**仍须确认**。
 *     权限轴（ask/auto/bypass）只放宽 side_effect=none 的工具；治理轴独立、bypass 不跳门。
 *  ② side_effect=none → 仅 ask 模式需确认；auto/bypass 自跑（不违反治理）。
 *  ③ side_effect 是后端 tool_status 真值入参，**绝不前端伪造**——本函数不读 DOM/不造默认 none。
 *
 * 这是纯函数：同一入参恒同出，供页面与对抗测试共用一份真相。
 */
export function gateNeedsConfirm(
  mode: PermissionMode,
  sideEffect: SideEffect,
): boolean {
  // 治理轴优先：动钱/外部副作用恒拦，与权限模式无关（D-PERM 反例的可见证据）。
  if (sideEffect === "realmoney" || sideEffect === "external") return true;
  // none 类工具：仅 ask 先问，auto/bypass 自跑。
  return mode === "ask";
}

/** 是否治理弱点（强制常驻展开、不可折叠藏起——R25）。 */
export function isGovernanceWeakness(
  sideEffect: SideEffect,
  explicit?: boolean,
): boolean {
  return (
    explicit === true ||
    sideEffect === "realmoney" ||
    sideEffect === "external"
  );
}

/** self-approve（批准且不再问 → auto）须经二次确认步（T-030）。 */
export type SelfApprovePhase = "idle" | "confirming";
