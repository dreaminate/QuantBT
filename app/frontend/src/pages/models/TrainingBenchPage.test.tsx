import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithDesk } from "../../test/harness";
import { TrainingBenchPage } from "./TrainingBenchPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const modelCards = [
  {
    key: "xgboost",
    family: "ml",
    display_name: "XGBoost",
    tasks: ["regression"],
    description: "tree model",
    pros: [],
    cons: [],
    tuning_tip: "",
    param_schema: {
      n_estimators: { type: "int", default: 100, min: 1, max: 1000 },
    },
    needs_dl: false,
    tensorboard: false,
    available: true,
  },
];

const datasets = [
  {
    dataset_id: "demo_ashare_xsec",
    label: "Demo AShare",
    asset_class: "equity_cn",
    feature_cols: ["factor_a", "factor_b"],
    label_col: "label",
    rows: 128,
  },
  {
    dataset_id: "demo_crypto_ts",
    label: "Demo Crypto",
    asset_class: "crypto",
    feature_cols: ["factor_a", "factor_b"],
    label_col: "label",
    rows: 96,
  },
];

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/training/models") return Promise.resolve(jsonResponse(modelCards));
      if (url === "/api/training/datasets") return Promise.resolve(jsonResponse(datasets));
      if (url === "/api/training/codegen") return Promise.resolve(jsonResponse({ code: "train()" }));
      if (url === "/api/training/jobs" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({ job_id: "trn-1", status: "queued" }));
      }
      if (url === "/api/training/jobs") return Promise.resolve(jsonResponse([]));
      return Promise.resolve(jsonResponse({ detail: `unexpected ${url}` }, 500));
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TrainingBenchPage", () => {
  it("提交训练时带 MarketDataUseValidation refs", async () => {
    renderWithDesk(<TrainingBenchPage />, { route: "/models" });

    const refs = await screen.findByTestId("training-market-data-use-validation-refs");
    fireEvent.change(refs, {
      target: {
        value:
          "market_data_use:demo_ashare_xsec:accepted\nmarket_data_use:demo_ashare_xsec:pit, market_data_use:demo_ashare_xsec:accepted",
      },
    });

    const submit = screen.getByRole("button", { name: /开始训练/ }) as HTMLButtonElement;
    await waitFor(() => expect(submit.disabled).toBe(false));
    fireEvent.click(submit);

    await waitFor(() => {
      const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
      const submitCall = calls.find(
        ([url, init]) => String(url) === "/api/training/jobs" && (init as RequestInit | undefined)?.method === "POST",
      );
      expect(submitCall).toBeDefined();
      const payload = JSON.parse(String((submitCall![1] as RequestInit).body));
      expect(payload.dataset_id).toBe("demo_ashare_xsec");
      expect(payload.market_data_use_validation_refs).toEqual([
        "market_data_use:demo_ashare_xsec:accepted",
        "market_data_use:demo_ashare_xsec:pit",
      ]);
    });
  });

  it("回测时带显式 MarketDataUseValidation refs", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/training/models") return Promise.resolve(jsonResponse(modelCards));
      if (url === "/api/training/datasets") return Promise.resolve(jsonResponse(datasets));
      if (url === "/api/training/codegen") return Promise.resolve(jsonResponse({ code: "train()" }));
      if (url === "/api/training/jobs") {
        return Promise.resolve(
          jsonResponse([
            {
              job_id: "trn-succeeded",
              name: "done job",
              model: "xgboost",
              family: "ml",
              task: "regression",
              status: "succeeded",
              metrics: { r2: 0.12 },
              elapsed_seconds: 3,
              tensorboard: false,
              error: null,
            },
          ]),
        );
      }
      if (url === "/api/training/jobs/trn-succeeded/eval") {
        return Promise.resolve(jsonResponse({ charts: [] }));
      }
      if (url === "/api/training/jobs/trn-succeeded/backtest" && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({
            metrics: { sharpe: 1.1 },
            equity_curve: [1, 1.02],
            is_oos: true,
            is_cross_dataset: true,
            strict_oos: false,
            dataset_id: "demo_crypto_ts",
            n_days: 2,
          }),
        );
      }
      return Promise.resolve(jsonResponse({ detail: `unexpected ${url}` }, 500));
    });

    renderWithDesk(<TrainingBenchPage />, { route: "/models" });

    fireEvent.click(await screen.findByText(/done job/));
    fireEvent.change(screen.getByTitle(/跨数据集样本外/), { target: { value: "demo_crypto_ts" } });
    fireEvent.change(screen.getByTestId("training-backtest-market-data-use-validation-refs"), {
      target: { value: "market_data_use:demo_crypto_ts:accepted, market_data_use:demo_crypto_ts:accepted" },
    });
    fireEvent.click(screen.getByRole("button", { name: /回测/ }));

    await waitFor(() => {
      const calls = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls;
      const backtestCall = calls.find(
        ([url, init]) =>
          String(url) === "/api/training/jobs/trn-succeeded/backtest" &&
          (init as RequestInit | undefined)?.method === "POST",
      );
      expect(backtestCall).toBeDefined();
      const payload = JSON.parse(String((backtestCall![1] as RequestInit).body));
      expect(payload.dataset_id).toBe("demo_crypto_ts");
      expect(payload.market_data_use_validation_refs).toEqual(["market_data_use:demo_crypto_ts:accepted"]);
    });
  });
});
