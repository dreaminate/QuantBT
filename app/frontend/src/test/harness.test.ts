import { describe, it, expect } from "vitest";
import {
  scanForbiddenWords,
  assertNoForbiddenWords,
  assertNoFrozenPageImport,
} from "./harness";

// G0 自证：对抗 harness 真的会抓坏（非空跑绿）
describe("G0 对抗测试 harness", () => {
  it("禁词扫描：含「可信/排除过拟合」必被抓", () => {
    expect(scanForbiddenWords("本策略可信，已排除过拟合")).toEqual([
      "可信",
      "排除过拟合",
    ]);
    expect(() => assertNoForbiddenWords("PBO 0.18 排除过拟合")).toThrow(/禁词/);
  });

  it("禁词扫描：合规文案（一致/存疑）放行", () => {
    expect(scanForbiddenWords("证据一致，适用域有限，未验证项 3")).toEqual([]);
    expect(() => assertNoForbiddenWords("证据存疑，样本不足")).not.toThrow();
  });

  it("冻结页 import 守卫：引用冻结 RunDetailPage 必被抓", () => {
    expect(() =>
      assertNoFrozenPageImport(
        'import X from "../../frontend-run-detail/src/pages/RunDetailPage";',
      ),
    ).toThrow(/冻结红线/);
    expect(() =>
      assertNoFrozenPageImport('import { RunVerdictCard } from "./RunVerdictCard";'),
    ).not.toThrow();
  });
});
