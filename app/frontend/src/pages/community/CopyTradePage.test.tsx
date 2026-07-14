import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import * as auth from "../../lib/auth";
import { CopyTradeFillLedger, CopyTradePage, SubscribeModal, type FillEconomics } from "./CopyTradePage";


function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}


const fill: FillEconomics = {
  event_ref: "fill-event-1",
  signal_ref: "signal-1",
  follower_ref: "alice::master-1",
  symbol: "BTCUSDT",
  side: "buy",
  fill_status: "filled",
  filled_qty: 0.01,
  cumulative_filled_qty: 0.01,
  fill_price: 10_000,
  commission: 0.04,
  commission_asset: "USDT",
  normalized_cost_usdt: 0.04,
  cost_complete: true,
  realized_pnl_delta: -1.25,
  realized_pnl_complete: true,
  fill_economics_complete: true,
  holding_cost_complete: false,
  total_economics_complete: false,
  occurred_at_utc: "2026-07-12T00:00:00+00:00",
};


afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
});


describe("CopyTrade fill economics", () => {
  it("loads the owner-scoped formal fill endpoint and keeps holding costs visibly incomplete", async () => {
    localStorage.setItem(
      "qb-auth-user",
      JSON.stringify({ user_id: "alice", username: "alice", display_name: "Alice" }),
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response([])),
    );
    const authFetch = vi.spyOn(auth, "authFetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/copy_trade/me/master") return response(null);
      if (url === "/api/copy_trade/me/subscriptions") return response([]);
      if (url === "/api/copy_trade/fills?limit=50") return response([fill]);
      throw new Error(`unexpected auth request: ${url}`);
    });

    render(
      <MemoryRouter>
        <CopyTradePage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("-1.2500")).toBeInTheDocument();
    expect(screen.getByText("逐笔完整")).toBeInTheDocument();
    expect(screen.getByText("持仓成本未归因")).toBeInTheDocument();
    await waitFor(() => {
      expect(authFetch).toHaveBeenCalledWith("/api/copy_trade/fills?limit=50");
    });
  });

  it("shows ledger failure instead of turning it into a successful empty state", () => {
    render(<CopyTradeFillLedger fills={[]} error="authority unavailable" />);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "成交账本不可用：authority unavailable",
    );
    expect(screen.queryByText("暂无经正式账本确认的成交。")).not.toBeInTheDocument();
  });
});


describe("CopyTrade formal mainnet subscription", () => {
  it("binds explicit risk consent, real external refs, and second factor before subscribing", async () => {
    const onClose = vi.fn();
    const profile = {
      profile_ref: "risk-profile-1",
      required_acknowledgement_refs: ["disclosure-1", "failure-1", "recommendation-1", "boundary-1"],
      disclosures: { cost: { ref: "disclosure-1", text: "Costs can exceed estimates." } },
      failure_modes: { outage: { ref: "failure-1", text: "The venue can be unavailable." } },
      recommendation: { ref: "recommendation-1", text: "Remain on testnet unless you accept the capped loss." },
      responsibility_boundary: {
        ref: "boundary-1",
        parties: { user: "You choose the loss budget.", platform: "No fill or profit guarantee." },
      },
    };
    const authFetch = vi.spyOn(auth, "authFetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/risk_consent/challenges")) {
        return response({ challenge_ref: "challenge-1", expires_at_utc: "2026-07-14T00:00:00Z", risk_profile: profile });
      }
      if (url.endsWith("/risk_consents")) {
        return response({
          consent_event_ref: "consent-1",
          user_risk_choice_ref: "choice-1",
          activation_deadline_utc: "2026-07-14T00:05:00Z",
          runtime_promotion: {
            request_ref: "runtime-request-1",
            subject_ref: "subject-1",
            asset_class: "crypto_perp",
            source_runtime: "testnet",
            target_runtime: "live",
            permission_gate_ref: "permission-1",
            order_guard_ref: "guard-1",
            idempotency_key: "idem-1",
            audit_record_ref: "audit-1",
            kill_switch_ref: "kill-1",
            secret_ref: "secret-1",
            responsibility_boundary_ref: "boundary-1",
            mock_profile: "none",
            required_evidence_refs: ["choice-1", "consent-1"],
          },
        });
      }
      if (url === "/api/research-os/execution/runtime_promotions") {
        return response({ runtime_promotion_ref: "promotion-1" });
      }
      if (url.endsWith("/subscribe")) return response({ follower_id: "alice::master-1" });
      throw new Error(`unexpected auth request: ${url}`);
    });

    render(
      <SubscribeModal
        master={{
          master_id: "master-1",
          user_id: "master-owner",
          display_name: "Formal BTC",
          description: "",
          asset_class: "crypto_perp",
          profit_share_pct: 0.1,
          is_invite_only: false,
          follower_count: 0,
          total_signals: 0,
          created_at_utc: "2026-07-13T00:00:00Z",
        }}
        onClose={onClose}
      />,
    );

    fireEvent.change(screen.getByLabelText("network"), { target: { value: "mainnet" } });
    fireEvent.click(screen.getByRole("button", { name: "获取正式风险披露 →" }));

    expect(await screen.findByTestId("copy-trade-risk-consent")).toBeInTheDocument();
    screen.getAllByRole("checkbox").forEach((checkbox) => fireEvent.click(checkbox));
    fireEvent.change(screen.getByLabelText("password"), { target: { value: "local-password" } });
    fireEvent.click(screen.getByRole("button", { name: "持久化风险选择与同意 →" }));

    expect(await screen.findByTestId("copy-trade-runtime-promotion")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("testnet_run_ref"), { target: { value: "execution_reconcile_v2_terminal" } });
    fireEvent.change(screen.getByLabelText("approval_ref"), { target: { value: "approval-live-order-1" } });
    fireEvent.click(screen.getByRole("button", { name: "记录 testnet → live 晋级 →" }));

    expect(await screen.findByTestId("copy-trade-mainnet-ready")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "确认真钱跟单" }));
    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));

    const requestBody = (url: string) => {
      const call = authFetch.mock.calls.find(([input]) => String(input) === url);
      expect(call).toBeDefined();
      return JSON.parse(String((call?.[1] as RequestInit).body));
    };
    expect(requestBody("/api/copy_trade/masters/master-1/risk_consents")).toMatchObject({
      challenge_ref: "challenge-1",
      acknowledged_item_refs: profile.required_acknowledgement_refs,
      password: "local-password",
    });
    expect(requestBody("/api/research-os/execution/runtime_promotions")).toMatchObject({
      subject_ref: "subject-1",
      testnet_run_ref: "execution_reconcile_v2_terminal",
      approval_ref: "approval-live-order-1",
      evidence_refs: ["choice-1", "consent-1", "execution_reconcile_v2_terminal", "approval-live-order-1"],
    });
    expect(requestBody("/api/copy_trade/masters/master-1/subscribe")).toMatchObject({
      binance_network: "mainnet",
      binance_keystore_name: "binance_mainnet",
      runtime_promotion_ref: "promotion-1",
      user_risk_choice_ref: "choice-1",
      user_risk_consent_event_ref: "consent-1",
      password: "local-password",
    });
  });
});
