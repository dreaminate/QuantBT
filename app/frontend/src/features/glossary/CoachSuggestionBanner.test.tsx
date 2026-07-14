import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as auth from "../../lib/auth";
import { CoachSuggestionBanner } from "./CoachSuggestionBanner";


afterEach(() => {
  vi.restoreAllMocks();
});


describe("CoachSuggestionBanner authentication", () => {
  it("loads the run-scoped suggestion through authFetch", async () => {
    const authFetchSpy = vi.spyOn(auth, "authFetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          suggestion: {
            severity: "warning",
            headline: "Review drawdown",
            detail: "Inspect the largest drawdown window.",
            suggested_chat_query: "Explain this drawdown",
            related_glossary: [],
            one_variable_hint: null,
          },
          risk_summary: {},
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );

    render(
      <MemoryRouter>
        <CoachSuggestionBanner runId="demo/run" />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(authFetchSpy).toHaveBeenCalledWith("/api/runs/demo%2Frun/coach_suggestion");
    });
    expect(await screen.findByText("Review drawdown")).toBeInTheDocument();
    expect(
      document.querySelector('[data-run-coach-ready="true"][data-run-id="demo/run"]'),
    ).toBeInTheDocument();
  });

  it("marks a valid no-suggestion response ready only after client parsing", async () => {
    vi.spyOn(auth, "authFetch").mockResolvedValue(
      new Response(JSON.stringify({ suggestion: null, risk_summary: {} }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    render(
      <MemoryRouter>
        <CoachSuggestionBanner runId="no-suggestion" />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(
        document.querySelector(
          '[data-run-coach-ready="true"][data-run-id="no-suggestion"]',
        ),
      ).toBeInTheDocument();
    });
  });

  it("does not publish the ready marker for a malformed payload", async () => {
    vi.spyOn(auth, "authFetch").mockResolvedValue(
      new Response(JSON.stringify({ suggestion: null }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    render(
      <MemoryRouter>
        <CoachSuggestionBanner runId="malformed" />
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(auth.authFetch).toHaveBeenCalled();
    });
    expect(
      document.querySelector('[data-run-coach-ready="true"]'),
    ).not.toBeInTheDocument();
  });
});
