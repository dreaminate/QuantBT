import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { renderWithDesk } from "../test/harness";
import { HomePage } from "./HomePage";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: string) => {
      const url = String(input);
      if (url.includes("/api/security/network")) {
        return Promise.resolve(
          new Response(JSON.stringify({ binance_network: "testnet", mode: "paper" }), {
            status: 200,
          }),
        );
      }
      return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("HomePage quick start honesty", () => {
  it("does not present stale demo metrics as a successful current run", async () => {
    const { container } = renderWithDesk(<HomePage />);

    await waitFor(() => {
      expect(container.textContent).toContain("结果以本次生成的 run.json 为准");
    });
    expect(container.textContent).toContain("未绑定 DatasetVersion/source provenance");
    expect(container.textContent).toContain("不能作为真 Tushare 验证证据");
    expect(container.textContent).not.toContain("sharpe=5.84");
    expect(container.textContent).not.toContain("a_share_real_demo done");
  });
});
