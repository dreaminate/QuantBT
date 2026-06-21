import { type ReactElement } from "react";
import { render, type RenderResult } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/**
 * G0 对抗测试公共 harness（e2de3d32）。
 * 供整套台前端卡复用，把「种已知 bug 门必抓」做成可调用工具。
 */

/** 在路由壳内渲染（MemoryRouter 包裹），供各台卡组件测试复用。 */
export function renderWithDesk(
  ui: ReactElement,
  opts?: { route?: string },
): RenderResult {
  return render(
    <MemoryRouter initialEntries={[opts?.route ?? "/"]}>{ui}</MemoryRouter>,
  );
}

/** R7 措辞门禁词：裁决/确认类 UI 绝不可出现这些绝对化措辞。 */
export const FORBIDDEN_VERDICT_WORDS = [
  "可信",
  "安全",
  "保证",
  "排除过拟合",
  "可复现",
  "组织独立",
] as const;

/** 扫描文本中的治理禁词，返回命中列表（供 R1/R2 裁决卡测试复用）。 */
export function scanForbiddenWords(text: string): string[] {
  return FORBIDDEN_VERDICT_WORDS.filter((w) => text.includes(w));
}

/** 断言文本不含禁词，命中即抛（R7：文案须走后端 _verdict_note）。 */
export function assertNoForbiddenWords(text: string): void {
  const hits = scanForbiddenWords(text);
  if (hits.length > 0) {
    throw new Error(
      `R7 措辞门：检出禁词 ${hits.join("、")} —— 裁决文案须走后端 _verdict_note，不可前端杜撰`,
    );
  }
}

/** 冻结页 import 守卫：断言源码未引用 frontend-run-detail 的冻结 RunDetailPage。 */
export function assertNoFrozenPageImport(moduleSource: string): void {
  if (/frontend-run-detail[^"']*RunDetailPage/.test(moduleSource)) {
    throw new Error(
      "冻结红线：禁止 import frontend-run-detail 的冻结 RunDetailPage（裁决卡须新建旁挂，不嵌冻结页）",
    );
  }
}
