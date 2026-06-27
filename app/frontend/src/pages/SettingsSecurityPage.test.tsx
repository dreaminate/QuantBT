import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, waitFor } from "@testing-library/react";
import { renderWithDesk } from "../test/harness";
import { SettingsSecurityPage } from "./SettingsSecurityPage";

function login() {
  localStorage.setItem("qb-auth-token", "tok");
  localStorage.setItem(
    "qb-auth-user",
    JSON.stringify({ user_id: "u1", username: "tester", display_name: "T" }),
  );
}

beforeEach(() => {
  login();
});

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

describe("SettingsSecurityPage · data connector settings", () => {
  it("renders Settings-managed DataSource/IngestionSkill summary and tests connector by skill_id", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const textUrl = String(url);
      if (textUrl.includes("/api/security/mainnet/config")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user_id: "u1",
              trusted_ips: [],
              totp_enabled: false,
              daily_operation_limit: 50,
              daily_notional_limit_usdt: 1000,
              require_password_per_order: true,
              updated_at_utc: "2026-06-27T00:00:00Z",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/security/mainnet/usage")) {
        return Promise.resolve(
          new Response(JSON.stringify({ date: "2026-06-27", operations_today: 0, notional_today_usdt: 0 }), {
            status: 200,
          }),
        );
      }
      if (textUrl.includes("/api/security/mainnet/audit_log")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (textUrl.includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      if (textUrl.includes("/api/research-os/settings/data_connector_onboarding_runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              run_ref: "data_connector_onboarding_run:tushare:ok",
              skill_id: "ingest:tushare:daily",
              completed_steps: [
                "connection_check",
                "ingestion_run",
                "field_mapping",
                "pit_bitemporal_rule",
                "dataset_semantics",
                "instrument_spec",
                "capability_matrix",
                "market_data_use",
                "compiler_coverage",
              ],
              connector_check_ref: "connector_check:tushare:ok",
              dataset_version_ref: "dataset_version:dataset:cn_equity_daily:v3",
              update_ref: "ingestion_update:tushare:daily:003",
              schema_probe_ref: "schema_probe:tushare:daily:run",
              mapping_ref: "schema_map:tushare:daily",
              mapping_method: "agent_suggested",
              pit_bitemporal_rules_ref: "pit:tushare:daily",
              dataset_ref: "dataset_version:dataset:cn_equity_daily:v3",
              instrument_ref: "instrument:ingest:tushare:daily:cn_equity:equity",
              capability_matrix_ref: "capability:ingest:tushare:daily:cn_equity:equity",
              market_data_use_validation_ref: "market_data_use:settings:onboarding:ok",
              accepted: true,
              connector_called: true,
              dataset_file_written: true,
              strategy_builder_called: false,
              venue_called: false,
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/ingestion_skill_runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              skill_id: "ingest:tushare:daily",
              source_ref: "datasource:tushare",
              connector_check_ref: "connector_check:tushare:ok",
              dataset_id: "dataset:cn_equity_daily",
              dataset_version_ref: "dataset_version:dataset:cn_equity_daily:v2",
              version_id: "v2",
              checksum: "sha256:dataset-v2",
              row_count: 3,
              file_paths: ["/tmp/datasets/ingestion/cn/v2.parquet"],
              schema_probe_ref: "schema_probe:tushare:daily:run",
              update_ref: "ingestion_update:tushare:daily:002",
              quality_verdict_ref: "quality:tushare:daily:pass",
              known_at_ref: "known_at:ingest_time",
              effective_at_ref: "effective_at:trade_date",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/data_connector_field_mappings")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              mapping_ref: "schema_map:tushare:daily",
              skill_id: "ingest:tushare:daily",
              source_ref: "datasource:tushare",
              schema_probe_ref: "schema_probe:tushare:daily:run",
              mapped_at: "2026-06-27T00:02:00Z",
              schema_signature_hash: "schema_signature:ohlcv-v1",
              source_to_canonical: {
                ts: "event_time",
                symbol: "instrument_id",
                close: "close",
              },
              event_time_column: "ts",
              known_at_column: "ts",
              effective_at_column: "ts",
              symbol_column: "symbol",
              unmapped_columns: [],
              mapping_hash: "field_mapping:ok",
              mapping_method: "settings_default_column_names",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/pit_bitemporal_rules")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              rule_ref: "pit:tushare:daily",
              skill_id: "ingest:tushare:daily",
              source_ref: "datasource:tushare",
              field_mapping_ref: "schema_map:tushare:daily",
              schema_probe_ref: "schema_probe:tushare:daily:run",
              generated_at: "2026-06-27T00:03:00Z",
              event_time_column: "ts",
              known_at_column: "ts",
              effective_at_column: "ts",
              known_at_policy: "source_column",
              effective_at_policy: "source_column",
              asof_join_policy: "known_at_lte_decision_time_latest",
              timezone: "UTC",
              calendar_ref: "calendar:datasource:tushare:default",
              lookahead_guard_ref: "lookahead_guard:ingest:tushare:daily:pit",
              monotonicity_check_ref: "monotonicity:schema_map:tushare:daily:event_known",
              restatement_policy: "latest_known_at_before_decision_time",
              rule_hash: "pit_bitemporal_rule:ok",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/dataset_semantics")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              dataset_ref: "dataset_version:dataset:cn_equity_daily:v1",
              dataset_version_ref: "dataset_version:dataset:cn_equity_daily:v1",
              update_ref: "ingestion_update:tushare:daily:001",
              pit_bitemporal_rules_ref: "pit:tushare:daily",
              use_context: "confirmatory_validation",
              recorded_by: "tester",
              raw_data_stored: false,
              connector_called: false,
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/instrument_specs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              instrument_ref: "instrument:ingest:tushare:daily:cn_equity:equity",
              dataset_ref: "dataset_version:dataset:cn_equity_daily:v1",
              asset_class: "cn_equity",
              instrument_type: "equity",
              currency: "CNY",
              recorded_by: "tester",
              raw_data_stored: false,
              connector_called: false,
              venue_called: false,
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/capability_matrices")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              matrix_ref: "capability:ingest:tushare:daily:cn_equity:equity",
              dataset_ref: "dataset_version:dataset:cn_equity_daily:v1",
              instrument_ref: "instrument:ingest:tushare:daily:cn_equity:equity",
              use_context: "confirmatory_validation",
              recorded_by: "tester",
              raw_data_stored: false,
              connector_called: false,
              venue_called: false,
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/market_data_use_validations")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              validation_ref: "market_data_use:settings:ok",
              request_ref: "market_data_use_request:settings:ok",
              use_context: "confirmatory_validation",
              accepted: true,
              recorded_by: "tester",
              raw_data_stored: false,
              connector_called: false,
              strategy_builder_called: false,
              venue_called: false,
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/secret_values")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              secret_ref: "secretref:tushare:read",
              scope: "market_data:read",
              status: "active",
              keystore_ref: "tushare",
              keystore_backend: "memory",
              secret_value_stored: true,
              recorded_by: "tester",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/data_connector_checks")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ok: true,
              check_ref: "connector_check:tushare:ok",
              skill_id: "ingest:tushare:daily",
              source_ref: "datasource:tushare",
              status: "ok",
              health_status: "ok",
              quota_status: "ok",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              secret_ref_total: 1,
              data_source_total: 1,
              ingestion_skill_total: 1,
              data_connector_check_total: 1,
              data_connector_schema_probe_total: 1,
              data_connector_field_mapping_total: 1,
              data_connector_pit_bitemporal_rule_total: 1,
              ingestion_skill_update_total: 1,
              market_data_dataset_total: 1,
              market_data_instrument_total: 1,
              market_data_capability_matrix_total: 1,
              market_data_use_validation_total: 1,
              secret_refs: [
                {
                  secret_ref: "secretref:tushare:read",
                  scope: "market_data:read",
                  status: "active",
                  affected_skills: ["ingest:tushare:daily"],
                  keystore_refs: [],
                  secret_value_stored: false,
                  keystore_backend: null,
                },
              ],
              data_sources: [
                {
                  source_ref: "datasource:tushare",
                  license: "commercial:user-provided",
                  rate_limit: "500/min",
                  retention_policy: "retain:research-cache",
                  export_allowed: true,
                  share_allowed: true,
                  warning_codes: [],
                },
              ],
              ingestion_skills: [
                {
                  skill_id: "ingest:tushare:daily",
                  source_ref: "datasource:tushare",
                  source_type: "third_party_api",
                  schema_mapping_ref: "schema_map:tushare:daily",
                  secret_refs: ["secretref:tushare:read"],
                  lifecycle_state: "active",
                  freshness_status: "fresh",
                  permission_scope: "market_data:read",
                  output_dataset_id: "dataset:cn_equity_daily",
                  schema_drift_status: "none",
                },
              ],
              data_connector_checks: [
                {
                  check_ref: "connector_check:tushare:ok",
                  skill_id: "ingest:tushare:daily",
                  source_ref: "datasource:tushare",
                  checked_at: "2026-06-27T00:00:00Z",
                  checker_ref: "fake_data_connector_checker",
                  status: "ok",
                  health_status: "ok",
                  quota_status: "ok",
                  schema_probe_ref: "schema_probe:tushare:daily:001",
                },
              ],
              data_connector_schema_probes: [
                {
                  probe_ref: "schema_probe:tushare:daily:run",
                  skill_id: "ingest:tushare:daily",
                  source_ref: "datasource:tushare",
                  connector_check_ref: "connector_check:tushare:ok",
                  probed_at: "2026-06-27T00:01:00Z",
                  schema_signature_hash: "schema_signature:ohlcv-v1",
                  columns: ["ts", "symbol", "close"],
                  row_count: 2,
                  dataset_version_ref: "dataset_version:dataset:cn_equity_daily:v1",
                  drift_status: "none",
                },
              ],
              data_connector_field_mappings: [
                {
                  mapping_ref: "schema_map:tushare:daily",
                  skill_id: "ingest:tushare:daily",
                  source_ref: "datasource:tushare",
                  schema_probe_ref: "schema_probe:tushare:daily:run",
                  mapped_at: "2026-06-27T00:02:00Z",
                  schema_signature_hash: "schema_signature:ohlcv-v1",
                  source_to_canonical: {
                    ts: "event_time",
                    symbol: "instrument_id",
                    close: "close",
                  },
                  event_time_column: "ts",
                  known_at_column: "ts",
                  effective_at_column: "ts",
                  symbol_column: "symbol",
                  unmapped_columns: [],
                  mapping_hash: "field_mapping:ok",
                  mapping_method: "manual",
                },
              ],
              data_connector_pit_bitemporal_rules: [
                {
                  rule_ref: "pit:tushare:daily",
                  skill_id: "ingest:tushare:daily",
                  source_ref: "datasource:tushare",
                  field_mapping_ref: "schema_map:tushare:daily",
                  schema_probe_ref: "schema_probe:tushare:daily:run",
                  generated_at: "2026-06-27T00:03:00Z",
                  event_time_column: "ts",
                  known_at_column: "ts",
                  effective_at_column: "ts",
                  known_at_policy: "source_column",
                  effective_at_policy: "source_column",
                  asof_join_policy: "known_at_lte_decision_time_latest",
                  timezone: "UTC",
                  calendar_ref: "calendar:datasource:tushare:default",
                  lookahead_guard_ref: "lookahead_guard:ingest:tushare:daily:pit",
                  monotonicity_check_ref: "monotonicity:schema_map:tushare:daily:event_known",
                  restatement_policy: "latest_known_at_before_decision_time",
                  rule_hash: "pit_bitemporal_rule:ok",
                },
              ],
              ingestion_skill_updates: [
                {
                  update_ref: "ingestion_update:tushare:daily:001",
                  skill_ref: "ingest:tushare:daily",
                  skill_version: "1",
                  source_ref: "datasource:tushare",
                  secret_ref: "secretref:tushare:read",
                  dataset_version_ref: "dataset_version:dataset:cn_equity_daily:v1",
                  checksum: "sha256:dataset-ok",
                  lineage_ref: "lineage:tushare:daily:001",
                  quality_verdict_ref: "quality:tushare:daily:pass",
                  known_at_ref: "known_at:ingest_time",
                  effective_at_ref: "effective_at:trade_date",
                  freshness_status: "fresh",
                  schema_drift_status: "none",
                  row_count: 2,
                },
              ],
              market_data_datasets: [
                {
                  dataset_ref: "dataset_version:dataset:cn_equity_daily:v1",
                  source_ref: "datasource:tushare",
                  version: "v1",
                  known_at_ref: "known_at:ingest_time",
                  effective_at_ref: "effective_at:trade_date",
                  pit_bitemporal_rules_ref: "pit:tushare:daily",
                  quality_status: "passed",
                  freshness_status: "fresh",
                  checksum: "sha256:dataset-ok",
                },
              ],
              market_data_instruments: [
                {
                  instrument_ref: "instrument:ingest:tushare:daily:cn_equity:equity",
                  asset_class: "cn_equity",
                  instrument_type: "equity",
                  currency: "CNY",
                  exchange_calendar_ref: "calendar:datasource:tushare:default",
                  symbol_mapping_ref: "schema_map:tushare:daily",
                },
              ],
              market_data_capability_matrices: [
                {
                  matrix_ref: "capability:ingest:tushare:daily:cn_equity:equity",
                  asset_class: "cn_equity",
                  instrument_type: "equity",
                  research: true,
                  backtest: true,
                  paper: true,
                  testnet: false,
                  live: false,
                  data_availability: "dataset_version:dataset:cn_equity_daily:v1",
                  permission_requirement: "market_data:read",
                },
              ],
              market_data_use_validations: [
                {
                  validation_ref: "market_data_use:settings:ok",
                  request_ref: "market_data_use_request:settings:ok",
                  use_context: "confirmatory_validation",
                  dataset_refs: ["dataset_version:dataset:cn_equity_daily:v1"],
                  instrument_refs: ["instrument:ingest:tushare:daily:cn_equity:equity"],
                  capability_matrix_ref: "capability:ingest:tushare:daily:cn_equity:equity",
                  accepted: true,
                  violation_codes: [],
                },
              ],
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<SettingsSecurityPage />);

    await waitFor(() => {
      expect(container.querySelector("[data-data-connectors-panel]")).not.toBeNull();
      expect(container.textContent).toContain("ingest:tushare:daily");
      expect(container.textContent).toContain("secretref:tushare:read");
      expect(container.textContent).toContain("connector_check:tushare:ok");
      expect(container.textContent).toContain("schema_probe:tushare:daily:run");
      expect(container.textContent).toContain("schema probes: 1");
      expect(container.textContent).toContain("field mappings: 1");
      expect(container.textContent).toContain("PIT rules: 1");
      expect(container.textContent).toContain("secrets: 1");
      expect(container.textContent).toContain("secret values: 0");
      expect(container.textContent).toContain("value: missing");
      expect(container.textContent).toContain("dataset semantics: 1");
      expect(container.textContent).toContain("instruments: 1");
      expect(container.textContent).toContain("capabilities: 1");
      expect(container.textContent).toContain("use validations: 1");
      expect(container.textContent).toContain("schema_map:tushare:daily");
      expect(container.textContent).toContain("event time:");
      expect(container.textContent).toContain("pit:tushare:daily");
      expect(container.textContent).toContain("known_at_lte_decision_time_latest");
      expect(container.textContent).toContain("dataset_version:dataset:cn_equity_daily:v1");
      expect(container.textContent).toContain("dataset_version:dataset:cn_equity_daily:v1");
      expect(container.textContent).toContain("quality:tushare:daily:pass");
      expect(container.textContent).toContain("instrument:ingest:tushare:daily:cn_equity:equity");
      expect(container.textContent).toContain("capability:ingest:tushare:daily:cn_equity:equity");
      expect(container.textContent).toContain("market_data_use:settings:ok");
      expect(container.textContent).not.toContain("sk-live");
    });

    fireEvent.change(container.querySelector("[data-secret-value-input='secretref:tushare:read']") as HTMLElement, {
      target: { value: "sk-live-connector-token" },
    });
    fireEvent.click(container.querySelector("[data-store-secret-value='secretref:tushare:read']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/secret_values"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.secret_ref).toBe("secretref:tushare:read");
      expect(body.scope).toBe("market_data:read");
      expect(body.secret_value).toBe("sk-live-connector-token");
      expect(body.affected_skills).toEqual(["ingest:tushare:daily"]);
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "stored in tushare",
      );
      expect(container.textContent).not.toContain("sk-live-connector-token");
    });

    fireEvent.click(container.querySelector("[data-record-dataset-semantics='ingest:tushare:daily']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/dataset_semantics"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:tushare:daily");
      expect(body.update_ref).toBe("ingestion_update:tushare:daily:001");
      expect(body.pit_bitemporal_rules_ref).toBe("pit:tushare:daily");
      expect(body.use_context).toBe("confirmatory_validation");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "dataset_version:dataset:cn_equity_daily:v1",
      );
    });

    fireEvent.click(container.querySelector("[data-record-instrument-spec='ingest:tushare:daily']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/instrument_specs"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:tushare:daily");
      expect(body.dataset_ref).toBe("dataset_version:dataset:cn_equity_daily:v1");
      expect(body.asset_class).toBe("cn_equity");
      expect(body.instrument_type).toBe("equity");
      expect(body.currency).toBe("CNY");
      expect(body.symbol_mapping_ref).toBe("schema_map:tushare:daily");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "instrument:ingest:tushare:daily:cn_equity:equity",
      );
    });

    fireEvent.click(container.querySelector("[data-record-capability-matrix='ingest:tushare:daily']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/capability_matrices"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:tushare:daily");
      expect(body.dataset_ref).toBe("dataset_version:dataset:cn_equity_daily:v1");
      expect(body.instrument_ref).toBe("instrument:ingest:tushare:daily:cn_equity:equity");
      expect(body.use_context).toBe("confirmatory_validation");
      expect(body.live).toBe(false);
      expect(body.data_availability).toBe("dataset_version:dataset:cn_equity_daily:v1");
      expect(body.permission_requirement).toBe("market_data:read");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "capability:ingest:tushare:daily:cn_equity:equity",
      );
    });

    fireEvent.click(container.querySelector("[data-record-market-data-use='ingest:tushare:daily']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/market_data_use_validations"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:tushare:daily");
      expect(body.dataset_ref).toBe("dataset_version:dataset:cn_equity_daily:v1");
      expect(body.instrument_ref).toBe("instrument:ingest:tushare:daily:cn_equity:equity");
      expect(body.capability_matrix_ref).toBe("capability:ingest:tushare:daily:cn_equity:equity");
      expect(body.use_context).toBe("confirmatory_validation");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "market_data_use:settings:ok",
      );
    });

    fireEvent.click(container.querySelector("[data-run-onboarding-skill='ingest:tushare:daily']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/data_connector_onboarding_runs"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:tushare:daily");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "data_connector_onboarding_run:tushare:ok",
      );
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "market_data_use:settings:onboarding:ok",
      );
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "steps 9",
      );
    });

    fireEvent.click(container.querySelector("[data-record-pit-rule='ingest:tushare:daily']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/pit_bitemporal_rules"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:tushare:daily");
      expect(body.field_mapping_ref).toBe("schema_map:tushare:daily");
      expect(body.schema_probe_ref).toBe("schema_probe:tushare:daily:run");
      expect(body.event_time_column).toBe("ts");
      expect(body.known_at_policy).toBe("source_column");
      expect(body.effective_at_policy).toBe("source_column");
      expect(body.asof_join_policy).toBe("known_at_lte_decision_time_latest");
      expect(body.evidence_refs).toEqual(["schema_map:tushare:daily", "schema_probe:tushare:daily:run"]);
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "pit:tushare:daily",
      );
    });

    fireEvent.click(container.querySelector("[data-record-field-mapping='ingest:tushare:daily']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/data_connector_field_mappings"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:tushare:daily");
      expect(body.mapping_ref).toBe("schema_map:tushare:daily");
      expect(body.schema_probe_ref).toBe("schema_probe:tushare:daily:run");
      expect(body.source_to_canonical).toEqual({
        ts: "event_time",
        symbol: "instrument_id",
        close: "close",
      });
      expect(body.event_time_column).toBe("ts");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "schema_map:tushare:daily",
      );
    });

    fireEvent.click(container.querySelector("[data-test-data-connector='ingest:tushare:daily']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/data_connector_checks"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:tushare:daily");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "connector_check:tushare:ok",
      );
    });

    fireEvent.click(container.querySelector("[data-run-ingestion-skill='ingest:tushare:daily']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/ingestion_skill_runs"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:tushare:daily");
      expect(body.connector_check_ref).toBe("connector_check:tushare:ok");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "dataset_version:dataset:cn_equity_daily:v2",
      );
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "ingestion_update:tushare:daily:002",
      );
    });

    expect(container.textContent).not.toContain("sk-live");
  });

  it("registers Generic REST YAML DataSource and IngestionSkill through existing Settings endpoints", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const textUrl = String(url);
      if (textUrl.includes("/api/security/mainnet/config")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user_id: "u1",
              trusted_ips: [],
              totp_enabled: false,
              daily_operation_limit: 50,
              daily_notional_limit_usdt: 1000,
              require_password_per_order: true,
              updated_at_utc: "2026-06-27T00:00:00Z",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/security/mainnet/usage")) {
        return Promise.resolve(
          new Response(JSON.stringify({ date: "2026-06-27", operations_today: 0, notional_today_usdt: 0 }), {
            status: 200,
          }),
        );
      }
      if (textUrl.includes("/api/security/mainnet/audit_log")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (textUrl.includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      if (textUrl.includes("/api/research-os/settings/data_sources")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              source_ref: "datasource:vendor:bars",
              export_allowed: true,
              share_allowed: false,
              warning_codes: [],
              recorded_by: "tester",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/ingestion_skills")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              skill_id: "ingest:vendor:bars",
              source_ref: "datasource:vendor:bars",
              secret_refs: [],
              lifecycle_state: "active",
              recorded_by: "tester",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              secret_ref_total: 0,
              data_source_total: 0,
              ingestion_skill_total: 0,
              data_connector_check_total: 0,
              data_connector_schema_probe_total: 0,
              data_connector_field_mapping_total: 0,
              data_connector_pit_bitemporal_rule_total: 0,
              ingestion_skill_update_total: 0,
              market_data_dataset_total: 0,
              market_data_instrument_total: 0,
              market_data_capability_matrix_total: 0,
              market_data_use_validation_total: 0,
              secret_refs: [],
              data_sources: [],
              ingestion_skills: [],
              data_connector_checks: [],
              data_connector_schema_probes: [],
              data_connector_field_mappings: [],
              data_connector_pit_bitemporal_rules: [],
              ingestion_skill_updates: [],
              market_data_datasets: [],
              market_data_instruments: [],
              market_data_capability_matrices: [],
              market_data_use_validations: [],
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<SettingsSecurityPage />);

    await waitFor(() => {
      expect(container.querySelector("[data-generic-rest-draft]")).not.toBeNull();
    });

    fireEvent.change(container.querySelector("[data-generic-rest-source-ref]") as HTMLElement, {
      target: { value: "datasource:vendor:bars" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-skill-id]") as HTMLElement, {
      target: { value: "ingest:vendor:bars" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-source-url]") as HTMLElement, {
      target: { value: "https://data.vendor.invalid" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-output-dataset]") as HTMLElement, {
      target: { value: "dataset:vendor_bars" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-schema-map]") as HTMLElement, {
      target: { value: "schema_map:vendor:bars" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-pit-ref]") as HTMLElement, {
      target: { value: "pit:vendor:bars" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-symbol]") as HTMLElement, {
      target: { value: "VENDOR" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-market]") as HTMLElement, {
      target: { value: "vendor_market" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-interval]") as HTMLElement, {
      target: { value: "5m" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-start]") as HTMLElement, {
      target: { value: "2026-06-26" },
    });
    fireEvent.change(container.querySelector("[data-generic-rest-yaml]") as HTMLElement, {
      target: {
        value: [
          "connector_name: vendor_bars",
          "label: Vendor Bars",
          "asset_class: custom",
          "base_url: https://data.vendor.invalid",
          "supported_markets: [vendor_market]",
          "supported_intervals: [5m]",
          "auth:",
          "  mode: none",
          "endpoints:",
          "  ohlcv:",
          "    method: GET",
          "    path: /bars/{symbol}",
          "    response_mapping:",
          "      records: $.data[*]",
          "      fields:",
          "        ts: t",
          "        close: c",
          "      ts_unit: ms",
          "schema_target: ohlcv",
        ].join("\n"),
      },
    });
    fireEvent.click(container.querySelector("[data-register-generic-rest]") as HTMLElement);

    await waitFor(() => {
      const sourceCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/data_sources"),
      );
      const skillCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/ingestion_skills"),
      );
      expect(sourceCall).toBeDefined();
      expect(skillCall).toBeDefined();
      const sourceBody = JSON.parse(String((sourceCall![1] as RequestInit).body));
      const skillBody = JSON.parse(String((skillCall![1] as RequestInit).body));
      expect(sourceBody.source_ref).toBe("datasource:vendor:bars");
      expect(sourceBody.source_url_or_path).toBe("https://data.vendor.invalid");
      expect(sourceBody.license).toBe("user_provided");
      expect(skillBody.skill_id).toBe("ingest:vendor:bars");
      expect(skillBody.source_type).toBe("generic_rest_api");
      expect(skillBody.source_ref).toBe("datasource:vendor:bars");
      expect(skillBody.secret_refs).toEqual([]);
      expect(skillBody.connector_config.connector_name).toBe("generic_rest");
      expect(skillBody.connector_config.auth_mode).toBe("none");
      expect(skillBody.connector_config.generic_rest_yaml).toContain("connector_name: vendor_bars");
      expect(skillBody.connector_config.symbol).toBe("VENDOR");
      expect(skillBody.connector_config.interval).toBe("5m");
      expect(skillBody.connector_config.market).toBe("vendor_market");
      expect(skillBody.connector_config.start).toBe("2026-06-26");
      expect(skillBody.output_dataset_id).toBe("dataset:vendor_bars");
      expect(skillBody.schema_mapping_ref).toBe("schema_map:vendor:bars");
      expect(skillBody.pit_bitemporal_rules_ref).toBe("pit:vendor:bars");
      expect(skillBody.permission_scope).toBe("market_data:read");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "Generic REST metadata registered",
      );
      expect(container.textContent).not.toContain("sk-live");
    });

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/research-os/settings/data_connector_checks")),
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/research-os/settings/ingestion_skill_runs")),
    ).toBe(false);
  });

  it("registers Stooq public daily bars metadata without secrets, check, or ingestion run", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const textUrl = String(url);
      if (textUrl.includes("/api/security/mainnet/config")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user_id: "u1",
              trusted_ips: [],
              totp_enabled: false,
              daily_operation_limit: 50,
              daily_notional_limit_usdt: 1000,
              require_password_per_order: true,
              updated_at_utc: "2026-06-27T00:00:00Z",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/security/mainnet/usage")) {
        return Promise.resolve(
          new Response(JSON.stringify({ date: "2026-06-27", operations_today: 0, notional_today_usdt: 0 }), {
            status: 200,
          }),
        );
      }
      if (textUrl.includes("/api/security/mainnet/audit_log")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (textUrl.includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      if (textUrl.includes("/api/research-os/settings/data_sources")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              source_ref: "datasource:stooq:public",
              export_allowed: true,
              share_allowed: false,
              warning_codes: [],
              recorded_by: "tester",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/ingestion_skills")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              skill_id: "ingest:stooq:msft:daily",
              source_ref: "datasource:stooq:public",
              secret_refs: [],
              lifecycle_state: "active",
              recorded_by: "tester",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              secret_ref_total: 0,
              data_source_total: 0,
              ingestion_skill_total: 0,
              data_connector_check_total: 0,
              data_connector_schema_probe_total: 0,
              data_connector_field_mapping_total: 0,
              data_connector_pit_bitemporal_rule_total: 0,
              ingestion_skill_update_total: 0,
              market_data_dataset_total: 0,
              market_data_instrument_total: 0,
              market_data_capability_matrix_total: 0,
              market_data_use_validation_total: 0,
              secret_refs: [],
              data_sources: [],
              ingestion_skills: [],
              data_connector_checks: [],
              data_connector_schema_probes: [],
              data_connector_field_mappings: [],
              data_connector_pit_bitemporal_rules: [],
              ingestion_skill_updates: [],
              market_data_datasets: [],
              market_data_instruments: [],
              market_data_capability_matrices: [],
              market_data_use_validations: [],
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<SettingsSecurityPage />);

    await waitFor(() => {
      expect(container.querySelector("[data-stooq-draft]")).not.toBeNull();
    });

    fireEvent.change(container.querySelector("[data-stooq-source-ref]") as HTMLElement, {
      target: { value: "datasource:stooq:public" },
    });
    fireEvent.change(container.querySelector("[data-stooq-skill-id]") as HTMLElement, {
      target: { value: "ingest:stooq:msft:daily" },
    });
    fireEvent.change(container.querySelector("[data-stooq-symbol]") as HTMLElement, {
      target: { value: "MSFT.US" },
    });
    fireEvent.change(container.querySelector("[data-stooq-output-dataset]") as HTMLElement, {
      target: { value: "dataset:stooq_msft_daily" },
    });
    fireEvent.change(container.querySelector("[data-stooq-schema-map]") as HTMLElement, {
      target: { value: "schema_map:stooq:msft:daily" },
    });
    fireEvent.change(container.querySelector("[data-stooq-pit-ref]") as HTMLElement, {
      target: { value: "pit:stooq:msft:daily" },
    });
    fireEvent.change(container.querySelector("[data-stooq-source-url]") as HTMLElement, {
      target: { value: "https://stooq.com/q/d/l/" },
    });
    fireEvent.change(container.querySelector("[data-stooq-start]") as HTMLElement, {
      target: { value: "2026-01-02" },
    });
    fireEvent.change(container.querySelector("[data-stooq-end]") as HTMLElement, {
      target: { value: "2026-06-26" },
    });
    fireEvent.click(container.querySelector("[data-register-stooq]") as HTMLElement);

    await waitFor(() => {
      const sourceCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/data_sources"),
      );
      const skillCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/ingestion_skills"),
      );
      expect(sourceCall).toBeDefined();
      expect(skillCall).toBeDefined();
      const sourceBody = JSON.parse(String((sourceCall![1] as RequestInit).body));
      const skillBody = JSON.parse(String((skillCall![1] as RequestInit).body));
      expect(sourceBody.source_ref).toBe("datasource:stooq:public");
      expect(sourceBody.source_url_or_path).toBe("https://stooq.com/q/d/l/");
      expect(sourceBody.license).toBe("stooq_public_terms");
      expect(sourceBody.redistribution_rights).toBe("restricted:public_terms");
      expect(skillBody.skill_id).toBe("ingest:stooq:msft:daily");
      expect(skillBody.source_type).toBe("public_csv");
      expect(skillBody.source_ref).toBe("datasource:stooq:public");
      expect(skillBody.secret_refs).toEqual([]);
      expect(skillBody.connector_config.connector_name).toBe("stooq");
      expect(skillBody.connector_config.auth_mode).toBe("none");
      expect(skillBody.connector_config.symbol).toBe("MSFT.US");
      expect(skillBody.connector_config.interval).toBe("1d");
      expect(skillBody.connector_config.market).toBe("stooq");
      expect(skillBody.connector_config.start).toBe("2026-01-02");
      expect(skillBody.connector_config.end).toBe("2026-06-26");
      expect(skillBody.output_dataset_id).toBe("dataset:stooq_msft_daily");
      expect(skillBody.schema_mapping_ref).toBe("schema_map:stooq:msft:daily");
      expect(skillBody.pit_bitemporal_rules_ref).toBe("pit:stooq:msft:daily");
      expect(skillBody.permission_scope).toBe("market_data:read");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "Stooq metadata registered",
      );
      expect(container.textContent).not.toContain("api_key");
      expect(container.textContent).not.toContain("sk-live");
    });

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/research-os/settings/data_connector_checks")),
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/research-os/settings/ingestion_skill_runs")),
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some((c) => String((c[1] as RequestInit | undefined)?.body ?? "").includes("api_key")),
    ).toBe(false);
  });

  it("registers Binance public REST metadata without secrets, check, or ingestion run", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const textUrl = String(url);
      if (textUrl.includes("/api/security/mainnet/config")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user_id: "u1",
              trusted_ips: [],
              totp_enabled: false,
              daily_operation_limit: 50,
              daily_notional_limit_usdt: 1000,
              require_password_per_order: true,
              updated_at_utc: "2026-06-27T00:00:00Z",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/security/mainnet/usage")) {
        return Promise.resolve(
          new Response(JSON.stringify({ date: "2026-06-27", operations_today: 0, notional_today_usdt: 0 }), {
            status: 200,
          }),
        );
      }
      if (textUrl.includes("/api/security/mainnet/audit_log")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (textUrl.includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      if (textUrl.includes("/api/research-os/settings/data_sources")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              source_ref: "datasource:binance:public",
              export_allowed: true,
              share_allowed: false,
              warning_codes: [],
              recorded_by: "tester",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/ingestion_skills")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              skill_id: "ingest:binance:ethusdt:5m",
              source_ref: "datasource:binance:public",
              secret_refs: [],
              lifecycle_state: "active",
              recorded_by: "tester",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              secret_ref_total: 0,
              data_source_total: 0,
              ingestion_skill_total: 0,
              data_connector_check_total: 0,
              data_connector_schema_probe_total: 0,
              data_connector_field_mapping_total: 0,
              data_connector_pit_bitemporal_rule_total: 0,
              ingestion_skill_update_total: 0,
              market_data_dataset_total: 0,
              market_data_instrument_total: 0,
              market_data_capability_matrix_total: 0,
              market_data_use_validation_total: 0,
              secret_refs: [],
              data_sources: [],
              ingestion_skills: [],
              data_connector_checks: [],
              data_connector_schema_probes: [],
              data_connector_field_mappings: [],
              data_connector_pit_bitemporal_rules: [],
              ingestion_skill_updates: [],
              market_data_datasets: [],
              market_data_instruments: [],
              market_data_capability_matrices: [],
              market_data_use_validations: [],
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<SettingsSecurityPage />);

    await waitFor(() => {
      expect(container.querySelector("[data-binance-public-draft]")).not.toBeNull();
    });

    fireEvent.change(container.querySelector("[data-binance-source-ref]") as HTMLElement, {
      target: { value: "datasource:binance:public" },
    });
    fireEvent.change(container.querySelector("[data-binance-skill-id]") as HTMLElement, {
      target: { value: "ingest:binance:ethusdt:5m" },
    });
    fireEvent.change(container.querySelector("[data-binance-symbol]") as HTMLElement, {
      target: { value: "ethusdt" },
    });
    fireEvent.change(container.querySelector("[data-binance-market]") as HTMLElement, {
      target: { value: "binanceusdm" },
    });
    fireEvent.change(container.querySelector("[data-binance-interval]") as HTMLElement, {
      target: { value: "5m" },
    });
    fireEvent.change(container.querySelector("[data-binance-output-dataset]") as HTMLElement, {
      target: { value: "dataset:binance_usdm_ethusdt_5m" },
    });
    fireEvent.change(container.querySelector("[data-binance-schema-map]") as HTMLElement, {
      target: { value: "schema_map:binance:ethusdt:5m" },
    });
    fireEvent.change(container.querySelector("[data-binance-pit-ref]") as HTMLElement, {
      target: { value: "pit:binance:ethusdt:5m" },
    });
    fireEvent.change(container.querySelector("[data-binance-source-url]") as HTMLElement, {
      target: { value: "https://fapi.binance.com/fapi/v1/klines" },
    });
    fireEvent.change(container.querySelector("[data-binance-start]") as HTMLElement, {
      target: { value: "2026-01-02" },
    });
    fireEvent.change(container.querySelector("[data-binance-end]") as HTMLElement, {
      target: { value: "2026-06-26" },
    });
    fireEvent.click(container.querySelector("[data-register-binance-public]") as HTMLElement);

    await waitFor(() => {
      const sourceCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/data_sources"),
      );
      const skillCall = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/ingestion_skills"),
      );
      expect(sourceCall).toBeDefined();
      expect(skillCall).toBeDefined();
      const sourceBody = JSON.parse(String((sourceCall![1] as RequestInit).body));
      const skillBody = JSON.parse(String((skillCall![1] as RequestInit).body));
      expect(sourceBody.source_ref).toBe("datasource:binance:public");
      expect(sourceBody.source_url_or_path).toBe("https://fapi.binance.com/fapi/v1/klines");
      expect(sourceBody.license).toBe("binance_public_api_terms");
      expect(sourceBody.redistribution_rights).toBe("restricted:public_terms");
      expect(skillBody.skill_id).toBe("ingest:binance:ethusdt:5m");
      expect(skillBody.source_type).toBe("public_api");
      expect(skillBody.source_ref).toBe("datasource:binance:public");
      expect(skillBody.secret_refs).toEqual([]);
      expect(skillBody.connector_config.connector_name).toBe("binance_rest_usdm");
      expect(skillBody.connector_config.auth_mode).toBe("none");
      expect(skillBody.connector_config.symbol).toBe("ETHUSDT");
      expect(skillBody.connector_config.interval).toBe("5m");
      expect(skillBody.connector_config.market).toBe("binanceusdm");
      expect(skillBody.connector_config.start).toBe("2026-01-02");
      expect(skillBody.connector_config.end).toBe("2026-06-26");
      expect(skillBody.output_dataset_id).toBe("dataset:binance_usdm_ethusdt_5m");
      expect(skillBody.schema_mapping_ref).toBe("schema_map:binance:ethusdt:5m");
      expect(skillBody.pit_bitemporal_rules_ref).toBe("pit:binance:ethusdt:5m");
      expect(skillBody.permission_scope).toBe("market_data:read");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "Binance public metadata registered",
      );
      expect(container.textContent).not.toContain("api_key");
      expect(container.textContent).not.toContain("sk-live");
    });

    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/research-os/settings/data_connector_checks")),
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/research-os/settings/ingestion_skill_runs")),
    ).toBe(false);
    expect(
      fetchMock.mock.calls.some((c) => String((c[1] as RequestInit | undefined)?.body ?? "").includes("api_key")),
    ).toBe(false);
  });

  it("keeps no-auth public connector actions enabled and renders one-shot failed_step", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => {
      const textUrl = String(url);
      if (textUrl.includes("/api/security/mainnet/config")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user_id: "u1",
              trusted_ips: [],
              totp_enabled: false,
              daily_operation_limit: 50,
              daily_notional_limit_usdt: 1000,
              require_password_per_order: true,
              updated_at_utc: "2026-06-27T00:00:00Z",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/security/mainnet/usage")) {
        return Promise.resolve(
          new Response(JSON.stringify({ date: "2026-06-27", operations_today: 0, notional_today_usdt: 0 }), {
            status: 200,
          }),
        );
      }
      if (textUrl.includes("/api/security/mainnet/audit_log")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (textUrl.includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      if (textUrl.includes("/api/research-os/settings/data_connector_onboarding_runs")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              detail: {
                failed_step: "field_mapping",
                completed_steps: ["connection_check", "ingestion_run"],
                error: "field_mapping_unknown_source_column",
              },
            }),
            { status: 422 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              secret_ref_total: 0,
              data_source_total: 1,
              ingestion_skill_total: 1,
              data_connector_check_total: 1,
              data_connector_schema_probe_total: 1,
              data_connector_field_mapping_total: 0,
              data_connector_pit_bitemporal_rule_total: 0,
              ingestion_skill_update_total: 1,
              market_data_dataset_total: 0,
              market_data_instrument_total: 0,
              market_data_capability_matrix_total: 0,
              market_data_use_validation_total: 0,
              secret_refs: [],
              data_sources: [
                {
                  source_ref: "datasource:binance:public",
                  license: "public_api_terms",
                  rate_limit: "1200/min",
                  retention_policy: "retain:research-cache",
                  export_allowed: true,
                  share_allowed: true,
                  warning_codes: [],
                },
              ],
              ingestion_skills: [
                {
                  skill_id: "ingest:binance:btcusdt:1m",
                  source_ref: "datasource:binance:public",
                  source_type: "public_api",
                  schema_mapping_ref: "schema_map:binance:ohlcv",
                  secret_refs: [],
                  lifecycle_state: "active",
                  freshness_status: "fresh",
                  permission_scope: "market_data:read",
                  output_dataset_id: "dataset:binance_spot_btcusdt_1m",
                  schema_drift_status: "none",
                },
              ],
              data_connector_checks: [
                {
                  check_ref: "connector_check:binance:ok",
                  skill_id: "ingest:binance:btcusdt:1m",
                  source_ref: "datasource:binance:public",
                  checked_at: "2026-06-27T00:00:00Z",
                  checker_ref: "settings_connector_registry_checker",
                  status: "ok",
                  health_status: "ok",
                  quota_status: "unknown",
                  schema_probe_ref: "schema_probe:binance:run",
                },
              ],
              data_connector_schema_probes: [
                {
                  probe_ref: "schema_probe:binance:run",
                  skill_id: "ingest:binance:btcusdt:1m",
                  source_ref: "datasource:binance:public",
                  connector_check_ref: "connector_check:binance:ok",
                  probed_at: "2026-06-27T00:01:00Z",
                  schema_signature_hash: "schema_signature:binance-v1",
                  columns: ["ts", "symbol", "close"],
                  row_count: 2,
                  dataset_version_ref: "dataset_version:dataset:binance_spot_btcusdt_1m:v1",
                  drift_status: "none",
                },
              ],
              ingestion_skill_updates: [
                {
                  update_ref: "ingestion_update:binance:001",
                  skill_ref: "ingest:binance:btcusdt:1m",
                  skill_version: "1",
                  source_ref: "datasource:binance:public",
                  secret_ref: "secret:none:binance_rest_spot",
                  dataset_version_ref: "dataset_version:dataset:binance_spot_btcusdt_1m:v1",
                  checksum: "sha256:binance",
                  quality_verdict_ref: "quality:binance:pass",
                  known_at_ref: "known_at:ingest_time",
                  effective_at_ref: "effective_at:ts",
                  freshness_status: "fresh",
                  schema_drift_status: "none",
                  row_count: 2,
                },
              ],
              data_connector_field_mappings: [],
              data_connector_pit_bitemporal_rules: [],
              market_data_datasets: [],
              market_data_instruments: [],
              market_data_capability_matrices: [],
              market_data_use_validations: [],
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<SettingsSecurityPage />);

    await waitFor(() => {
      expect(container.textContent).toContain("ingest:binance:btcusdt:1m");
      expect(container.textContent).toContain("secrets: —");
      expect(container.textContent).toContain("secret values: 0");
    });

    expect(container.querySelector("[data-test-data-connector='ingest:binance:btcusdt:1m']")).not.toBeDisabled();
    expect(container.querySelector("[data-run-ingestion-skill='ingest:binance:btcusdt:1m']")).not.toBeDisabled();

    fireEvent.click(container.querySelector("[data-run-onboarding-skill='ingest:binance:btcusdt:1m']") as HTMLElement);

    await waitFor(() => {
      const result = (container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent || "";
      expect(result).toContain("field_mapping failed");
      expect(result).toContain("connection_check");
      expect(result).toContain("ingestion_run");
      expect(result).toContain("field_mapping_unknown_source_column");
      expect(container.textContent).not.toContain("sk-live");
    });
  });

  it("submits editable field mapping and PIT policy drafts through existing Settings endpoints", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      const textUrl = String(url);
      if (textUrl.includes("/api/security/mainnet/config")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              user_id: "u1",
              trusted_ips: [],
              totp_enabled: false,
              daily_operation_limit: 50,
              daily_notional_limit_usdt: 1000,
              require_password_per_order: true,
              updated_at_utc: "2026-06-27T00:00:00Z",
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/security/mainnet/usage")) {
        return Promise.resolve(
          new Response(JSON.stringify({ date: "2026-06-27", operations_today: 0, notional_today_usdt: 0 }), {
            status: 200,
          }),
        );
      }
      if (textUrl.includes("/api/security/mainnet/audit_log")) {
        return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      }
      if (textUrl.includes("/api/llm/status")) {
        return Promise.resolve(new Response(JSON.stringify({ providers: [] }), { status: 200 }));
      }
      if (textUrl.includes("/api/research-os/settings/data_connector_field_mappings")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              mapping_ref: "schema_map:custom:bars",
              skill_id: "ingest:custom:bars",
              source_ref: "datasource:custom",
              schema_probe_ref: "schema_probe:custom:bars",
              source_to_canonical: { bar_start: "event_time", asset: "instrument_id", px_last: "vwap" },
            }),
            { status: 200 },
          ),
        );
      }
      if (textUrl.includes("/api/research-os/settings/pit_bitemporal_rules")) {
        return Promise.resolve(new Response(JSON.stringify({ detail: "pit_rule_asof_policy_not_pit_safe" }), { status: 422 }));
      }
      if (textUrl.includes("/api/research-os/settings/summary")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              secret_ref_total: 0,
              data_source_total: 1,
              ingestion_skill_total: 1,
              data_connector_check_total: 1,
              data_connector_schema_probe_total: 1,
              data_connector_field_mapping_total: 1,
              data_connector_pit_bitemporal_rule_total: 0,
              ingestion_skill_update_total: 0,
              market_data_dataset_total: 0,
              market_data_instrument_total: 0,
              market_data_capability_matrix_total: 0,
              market_data_use_validation_total: 0,
              secret_refs: [],
              data_sources: [
                {
                  source_ref: "datasource:custom",
                  license: "user_provided",
                  rate_limit: "manual",
                  retention_policy: "retain:research-cache",
                  export_allowed: true,
                  share_allowed: false,
                  warning_codes: [],
                },
              ],
              ingestion_skills: [
                {
                  skill_id: "ingest:custom:bars",
                  source_ref: "datasource:custom",
                  source_type: "uploaded_api",
                  schema_mapping_ref: "schema_map:custom:bars",
                  secret_refs: [],
                  lifecycle_state: "active",
                  freshness_status: "fresh",
                  permission_scope: "market_data:read",
                  output_dataset_id: "dataset:custom_bars",
                  schema_drift_status: "none",
                },
              ],
              data_connector_checks: [
                {
                  check_ref: "connector_check:custom:ok",
                  skill_id: "ingest:custom:bars",
                  source_ref: "datasource:custom",
                  checked_at: "2026-06-27T00:00:00Z",
                  checker_ref: "settings_connector_registry_checker",
                  status: "ok",
                  health_status: "ok",
                  quota_status: "unknown",
                  schema_probe_ref: "schema_probe:custom:bars",
                },
              ],
              data_connector_schema_probes: [
                {
                  probe_ref: "schema_probe:custom:bars",
                  skill_id: "ingest:custom:bars",
                  source_ref: "datasource:custom",
                  connector_check_ref: "connector_check:custom:ok",
                  probed_at: "2026-06-27T00:01:00Z",
                  schema_signature_hash: "schema_signature:custom-bars",
                  columns: ["bar_start", "asset", "px_last", "vendor_note"],
                  row_count: 2,
                  dataset_version_ref: "dataset_version:dataset:custom_bars:v1",
                  drift_status: "none",
                },
              ],
              data_connector_field_mappings: [
                {
                  mapping_ref: "schema_map:custom:bars",
                  skill_id: "ingest:custom:bars",
                  source_ref: "datasource:custom",
                  schema_probe_ref: "schema_probe:custom:bars",
                  mapped_at: "2026-06-27T00:02:00Z",
                  schema_signature_hash: "schema_signature:custom-bars",
                  source_to_canonical: {
                    bar_start: "event_time",
                    asset: "instrument_id",
                    px_last: "close",
                  },
                  event_time_column: "bar_start",
                  known_at_column: "bar_start",
                  effective_at_column: "bar_start",
                  symbol_column: "asset",
                  unmapped_columns: ["vendor_note"],
                  mapping_hash: "field_mapping:custom",
                  mapping_method: "manual",
                },
              ],
              data_connector_pit_bitemporal_rules: [],
              ingestion_skill_updates: [],
              market_data_datasets: [],
              market_data_instruments: [],
              market_data_capability_matrices: [],
              market_data_use_validations: [],
            }),
            { status: 200 },
          ),
        );
      }
      return Promise.resolve(new Response("{}", { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);

    const { container } = renderWithDesk(<SettingsSecurityPage />);

    await waitFor(() => {
      expect(container.querySelector("[data-field-mapping-wizard='ingest:custom:bars']")).not.toBeNull();
      expect(container.querySelector("[data-pit-rule-wizard='ingest:custom:bars']")).not.toBeNull();
    });

    fireEvent.change(
      container.querySelector("[data-field-mapping-role='ingest:custom:bars:px_last']") as HTMLElement,
      { target: { value: "vwap" } },
    );
    fireEvent.change(
      container.querySelector("[data-field-mapping-role='ingest:custom:bars:vendor_note']") as HTMLElement,
      { target: { value: "market" } },
    );
    fireEvent.change(container.querySelector("[data-field-mapping-effective-at='ingest:custom:bars']") as HTMLElement, {
      target: { value: "" },
    });
    fireEvent.click(container.querySelector("[data-record-field-mapping='ingest:custom:bars']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/data_connector_field_mappings"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:custom:bars");
      expect(body.schema_probe_ref).toBe("schema_probe:custom:bars");
      expect(body.source_to_canonical).toEqual({
        bar_start: "event_time",
        asset: "instrument_id",
        px_last: "vwap",
        vendor_note: "market",
      });
      expect(body.event_time_column).toBe("bar_start");
      expect(body.known_at_column).toBe("bar_start");
      expect(body.effective_at_column).toBeNull();
      expect(body.symbol_column).toBe("asset");
      expect(body.unmapped_columns).toEqual([]);
      expect(body.mapping_method).toBe("manual");
    });

    fireEvent.change(container.querySelector("[data-pit-asof-policy='ingest:custom:bars']") as HTMLElement, {
      target: { value: "current_snapshot" },
    });
    fireEvent.change(container.querySelector("[data-pit-timezone='ingest:custom:bars']") as HTMLElement, {
      target: { value: "Asia/Shanghai" },
    });
    fireEvent.click(container.querySelector("[data-record-pit-rule='ingest:custom:bars']") as HTMLElement);

    await waitFor(() => {
      const call = fetchMock.mock.calls.find((c) =>
        String(c[0]).includes("/api/research-os/settings/pit_bitemporal_rules"),
      );
      expect(call).toBeDefined();
      const body = JSON.parse(String((call![1] as RequestInit).body));
      expect(body.skill_id).toBe("ingest:custom:bars");
      expect(body.field_mapping_ref).toBe("schema_map:custom:bars");
      expect(body.asof_join_policy).toBe("current_snapshot");
      expect(body.timezone).toBe("Asia/Shanghai");
      expect((container.querySelector("[data-data-connector-test-result]") as HTMLElement).textContent).toContain(
        "pit_rule_asof_policy_not_pit_safe",
      );
      expect(container.textContent).not.toContain("sk-live");
    });
  });
});
