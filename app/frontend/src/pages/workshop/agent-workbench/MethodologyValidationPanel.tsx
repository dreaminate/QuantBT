import { useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { Pill } from "../../../components/desk";
import { authFetch } from "../../../lib/auth";

interface CPCVSummary {
  cpcv_ref: string;
  claim_ref: string;
  fold_count: number;
  embargo_observations: number;
  sample_count: number;
  mean_metric: number;
  min_metric: number;
  max_metric: number;
  source_hash: string;
  evidence_refs: string[];
  validation_result_refs: string[];
}

interface ConformalSummary {
  conformal_ref: string;
  claim_ref: string;
  alpha: number;
  calibration_count: number;
  nonconformity_threshold: number;
  coverage_estimate: number;
  source_hash: string;
  evidence_refs: string[];
  validation_result_refs: string[];
  abstain_policy_ref?: string | null;
}

interface TCASummary {
  tca_ref: string;
  claim_ref: string;
  sample_count: number;
  gross_mean_bps: number;
  total_cost_bps: number;
  net_mean_bps: number;
  cost_component_refs: string[];
  cost_model_refs: string[];
  source_hash: string;
  evidence_refs: string[];
  validation_result_refs: string[];
}

interface ValidationDepthSummary {
  depth_ref: string;
  claim_ref: string;
  claim_label: string;
  target_environment: string;
  cpcv_ref?: string | null;
  walk_forward_ref?: string | null;
  conformal_ref?: string | null;
  abstain_policy_ref?: string | null;
  tca_ref?: string | null;
  cost_model_refs: string[];
  feature_leakage_probe_refs: string[];
  feature_leakage_verdict: string;
  fault_injection_refs: string[];
  fault_injection_verdict: string;
  recovery_drill_refs: string[];
  recovery_drill_verdict: string;
  evidence_refs: string[];
  validation_result_refs: string[];
  methodology_choice_ref?: string | null;
  responsibility_boundary_ref?: string | null;
  user_waived_path: boolean;
  silent_mock_fallback_used: boolean;
}

interface RuntimeDrillSummary {
  runtime_drill_ref: string;
  claim_ref: string;
  target_environment: string;
  drill_mode: string;
  venue_ref: string;
  fault_scenario: string;
  expected_guard_ref: string;
  observed_guard_ref: string;
  recovery_action_ref: string;
  fault_injection_ref: string;
  recovery_drill_ref: string;
  fault_injection_verdict: string;
  recovery_drill_verdict: string;
  source_hash: string;
  evidence_refs: string[];
  validation_result_refs: string[];
}

interface MethodologySummary {
  user: string;
  validation_depth_total: number;
  validation_depths: ValidationDepthSummary[];
  runtime_drill_total: number;
  runtime_drills: RuntimeDrillSummary[];
  calculator_totals: { cpcv: number; conformal: number; tca: number };
  cpcv_calculations: CPCVSummary[];
  conformal_calculations: ConformalSummary[];
  tca_calculations: TCASummary[];
}

type AsyncStatus<T> =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; value: T };

interface CPCVDraft {
  claim_ref: string;
  fold_metric_values: string;
  embargo_observations: string;
  evidence_refs: string;
  validation_result_refs: string;
  cpcv_ref: string;
}

interface ConformalDraft {
  claim_ref: string;
  calibration_scores: string;
  alpha: string;
  evidence_refs: string;
  validation_result_refs: string;
  abstain_policy_ref: string;
  conformal_ref: string;
}

interface TCADraft {
  claim_ref: string;
  gross_return_bps: string;
  cost_components_bps: string;
  cost_model_refs: string;
  evidence_refs: string;
  validation_result_refs: string;
  tca_ref: string;
}

interface DepthDraft {
  depth_ref: string;
  claim_ref: string;
  claim_label: string;
  target_environment: string;
  cpcv_ref: string;
  walk_forward_ref: string;
  conformal_ref: string;
  abstain_policy_ref: string;
  tca_ref: string;
  cost_model_refs: string;
  feature_leakage_probe_refs: string;
  feature_leakage_verdict: string;
  fault_injection_refs: string;
  fault_injection_verdict: string;
  recovery_drill_refs: string;
  recovery_drill_verdict: string;
  evidence_refs: string;
  validation_result_refs: string;
  methodology_choice_ref: string;
  responsibility_boundary_ref: string;
  user_waived_path: boolean;
}

interface RuntimeDrillDraft {
  claim_ref: string;
  target_environment: string;
  drill_mode: string;
  venue_ref: string;
  fault_scenario: string;
  expected_guard_ref: string;
  observed_guard_ref: string;
  recovery_action_ref: string;
  evidence_refs: string;
  validation_result_refs: string;
  runtime_drill_ref: string;
  fault_injection_ref: string;
  recovery_drill_ref: string;
}

const emptyCPCV: CPCVDraft = {
  claim_ref: "",
  fold_metric_values: "",
  embargo_observations: "0",
  evidence_refs: "",
  validation_result_refs: "",
  cpcv_ref: "",
};

const emptyConformal: ConformalDraft = {
  claim_ref: "",
  calibration_scores: "",
  alpha: "0.1",
  evidence_refs: "",
  validation_result_refs: "",
  abstain_policy_ref: "",
  conformal_ref: "",
};

const emptyTCA: TCADraft = {
  claim_ref: "",
  gross_return_bps: "",
  cost_components_bps: "",
  cost_model_refs: "",
  evidence_refs: "",
  validation_result_refs: "",
  tca_ref: "",
};

const emptyDepth: DepthDraft = {
  depth_ref: "",
  claim_ref: "",
  claim_label: "evidence_sufficient",
  target_environment: "paper",
  cpcv_ref: "",
  walk_forward_ref: "",
  conformal_ref: "",
  abstain_policy_ref: "",
  tca_ref: "",
  cost_model_refs: "",
  feature_leakage_probe_refs: "",
  feature_leakage_verdict: "accepted",
  fault_injection_refs: "",
  fault_injection_verdict: "accepted",
  recovery_drill_refs: "",
  recovery_drill_verdict: "accepted",
  evidence_refs: "",
  validation_result_refs: "",
  methodology_choice_ref: "",
  responsibility_boundary_ref: "",
  user_waived_path: false,
};

const emptyRuntimeDrill: RuntimeDrillDraft = {
  claim_ref: "",
  target_environment: "paper",
  drill_mode: "simulation",
  venue_ref: "",
  fault_scenario: "venue_timeout",
  expected_guard_ref: "",
  observed_guard_ref: "",
  recovery_action_ref: "",
  evidence_refs: "",
  validation_result_refs: "",
  runtime_drill_ref: "",
  fault_injection_ref: "",
  recovery_drill_ref: "",
};

function apiErrorMessage(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) return detail;
  if (typeof detail === "object" && detail && "detail" in detail) {
    return String((detail as { detail: unknown }).detail);
  }
  return fallback;
}

async function readError(response: Response): Promise<string> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    const detail = await response.json().catch(() => ({}));
    return apiErrorMessage(detail, `HTTP ${response.status}`);
  }
  const text = await response.text().catch(() => "");
  return text || `HTTP ${response.status}`;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authFetch(path, init);
  if (!response.ok) throw new Error(await readError(response));
  return response.json() as Promise<T>;
}

function parseList(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseNumbers(value: string, field: string): number[] {
  const parts = parseList(value);
  if (parts.length === 0) throw new Error(`${field} required`);
  return parts.map((item) => {
    const next = Number(item);
    if (!Number.isFinite(next)) throw new Error(`${field} must be finite numbers`);
    return next;
  });
}

function parseCostComponents(value: string): Record<string, number> {
  const entries = parseList(value);
  if (entries.length === 0) throw new Error("cost_components_bps required");
  return Object.fromEntries(
    entries.map((entry) => {
      const [rawKey, rawValue] = entry.split(":");
      const key = rawKey?.trim();
      const next = Number(rawValue);
      if (!key || !Number.isFinite(next)) throw new Error("cost_components_bps must use key:value pairs");
      return [key, next];
    }),
  );
}

function requireText(value: string, field: string): string {
  const next = value.trim();
  if (!next) throw new Error(`${field} required`);
  return next;
}

function optionalText(value: string): string | undefined {
  const next = value.trim();
  return next || undefined;
}

function fmtNumber(value: number, digits = 4): string {
  if (!Number.isFinite(value)) return "n/a";
  return String(Number(value.toFixed(digits)));
}

function ellipsis(value: string, size = 28): string {
  if (value.length <= size) return value;
  return `${value.slice(0, size)}...`;
}

export function MethodologyValidationPanel() {
  const [summaryStatus, setSummaryStatus] = useState<AsyncStatus<MethodologySummary>>({ state: "loading" });
  const [cpcvDraft, setCpcvDraft] = useState<CPCVDraft>(emptyCPCV);
  const [conformalDraft, setConformalDraft] = useState<ConformalDraft>(emptyConformal);
  const [tcaDraft, setTcaDraft] = useState<TCADraft>(emptyTCA);
  const [runtimeDrillDraft, setRuntimeDrillDraft] = useState<RuntimeDrillDraft>(emptyRuntimeDrill);
  const [depthDraft, setDepthDraft] = useState<DepthDraft>(emptyDepth);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastRecordedRef, setLastRecordedRef] = useState<string | null>(null);

  async function refreshSummary() {
    setSummaryStatus({ state: "loading" });
    try {
      const payload = await requestJson<MethodologySummary>("/api/research-os/methodology/summary");
      setSummaryStatus({ state: "ready", value: payload });
    } catch (exc) {
      setSummaryStatus({ state: "error", message: (exc as Error).message });
    }
  }

  useEffect(() => {
    void refreshSummary();
  }, []);

  async function recordCPCV() {
    setBusy("cpcv");
    setError(null);
    try {
      const payload = {
        claim_ref: requireText(cpcvDraft.claim_ref, "claim_ref"),
        fold_metric_values: parseNumbers(cpcvDraft.fold_metric_values, "fold_metric_values"),
        embargo_observations: Number(cpcvDraft.embargo_observations || 0),
        evidence_refs: parseList(cpcvDraft.evidence_refs),
        validation_result_refs: parseList(cpcvDraft.validation_result_refs),
        cpcv_ref: optionalText(cpcvDraft.cpcv_ref),
      };
      if (payload.evidence_refs.length === 0) throw new Error("evidence_refs required");
      if (payload.validation_result_refs.length === 0) throw new Error("validation_result_refs required");
      const result = await requestJson<CPCVSummary & { recorded_by: string }>("/api/research-os/methodology/cpcv", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setLastRecordedRef(result.cpcv_ref);
      setCpcvDraft(emptyCPCV);
      await refreshSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordConformal() {
    setBusy("conformal");
    setError(null);
    try {
      const payload = {
        claim_ref: requireText(conformalDraft.claim_ref, "claim_ref"),
        calibration_scores: parseNumbers(conformalDraft.calibration_scores, "calibration_scores"),
        alpha: Number(conformalDraft.alpha),
        evidence_refs: parseList(conformalDraft.evidence_refs),
        validation_result_refs: parseList(conformalDraft.validation_result_refs),
        abstain_policy_ref: optionalText(conformalDraft.abstain_policy_ref),
        conformal_ref: optionalText(conformalDraft.conformal_ref),
      };
      if (!Number.isFinite(payload.alpha)) throw new Error("alpha must be finite");
      if (payload.evidence_refs.length === 0) throw new Error("evidence_refs required");
      if (payload.validation_result_refs.length === 0) throw new Error("validation_result_refs required");
      const result = await requestJson<ConformalSummary & { recorded_by: string }>(
        "/api/research-os/methodology/conformal",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      setLastRecordedRef(result.conformal_ref);
      setConformalDraft(emptyConformal);
      await refreshSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordTCA() {
    setBusy("tca");
    setError(null);
    try {
      const payload = {
        claim_ref: requireText(tcaDraft.claim_ref, "claim_ref"),
        gross_return_bps: parseNumbers(tcaDraft.gross_return_bps, "gross_return_bps"),
        cost_components_bps: parseCostComponents(tcaDraft.cost_components_bps),
        cost_model_refs: parseList(tcaDraft.cost_model_refs),
        evidence_refs: parseList(tcaDraft.evidence_refs),
        validation_result_refs: parseList(tcaDraft.validation_result_refs),
        tca_ref: optionalText(tcaDraft.tca_ref),
      };
      if (payload.cost_model_refs.length === 0) throw new Error("cost_model_refs required");
      if (payload.evidence_refs.length === 0) throw new Error("evidence_refs required");
      if (payload.validation_result_refs.length === 0) throw new Error("validation_result_refs required");
      const result = await requestJson<TCASummary & { recorded_by: string }>("/api/research-os/methodology/tca", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setLastRecordedRef(result.tca_ref);
      setTcaDraft(emptyTCA);
      await refreshSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordRuntimeDrill() {
    setBusy("runtime drill");
    setError(null);
    try {
      const payload = {
        claim_ref: requireText(runtimeDrillDraft.claim_ref, "claim_ref"),
        target_environment: requireText(runtimeDrillDraft.target_environment, "target_environment"),
        drill_mode: requireText(runtimeDrillDraft.drill_mode, "drill_mode"),
        venue_ref: requireText(runtimeDrillDraft.venue_ref, "venue_ref"),
        fault_scenario: requireText(runtimeDrillDraft.fault_scenario, "fault_scenario"),
        expected_guard_ref: requireText(runtimeDrillDraft.expected_guard_ref, "expected_guard_ref"),
        observed_guard_ref: requireText(runtimeDrillDraft.observed_guard_ref, "observed_guard_ref"),
        recovery_action_ref: requireText(runtimeDrillDraft.recovery_action_ref, "recovery_action_ref"),
        evidence_refs: parseList(runtimeDrillDraft.evidence_refs),
        validation_result_refs: parseList(runtimeDrillDraft.validation_result_refs),
        runtime_drill_ref: optionalText(runtimeDrillDraft.runtime_drill_ref),
        fault_injection_ref: optionalText(runtimeDrillDraft.fault_injection_ref),
        recovery_drill_ref: optionalText(runtimeDrillDraft.recovery_drill_ref),
      };
      if (payload.evidence_refs.length === 0) throw new Error("evidence_refs required");
      if (payload.validation_result_refs.length === 0) throw new Error("validation_result_refs required");
      const result = await requestJson<RuntimeDrillSummary & { recorded_by: string }>(
        "/api/research-os/methodology/runtime_drills",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      setLastRecordedRef(result.runtime_drill_ref);
      setDepthDraft((current) => ({
        ...current,
        claim_ref: current.claim_ref || result.claim_ref,
        target_environment: current.target_environment || result.target_environment,
        fault_injection_refs: result.fault_injection_ref,
        fault_injection_verdict: result.fault_injection_verdict,
        recovery_drill_refs: result.recovery_drill_ref,
        recovery_drill_verdict: result.recovery_drill_verdict,
      }));
      setRuntimeDrillDraft(emptyRuntimeDrill);
      await refreshSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function recordValidationDepth() {
    setBusy("validation depth");
    setError(null);
    try {
      const payload = {
        validation_depth: {
          depth_ref: requireText(depthDraft.depth_ref, "depth_ref"),
          claim_ref: requireText(depthDraft.claim_ref, "claim_ref"),
          claim_label: requireText(depthDraft.claim_label, "claim_label"),
          target_environment: requireText(depthDraft.target_environment, "target_environment"),
          cpcv_ref: optionalText(depthDraft.cpcv_ref),
          walk_forward_ref: optionalText(depthDraft.walk_forward_ref),
          conformal_ref: optionalText(depthDraft.conformal_ref),
          abstain_policy_ref: optionalText(depthDraft.abstain_policy_ref),
          tca_ref: optionalText(depthDraft.tca_ref),
          cost_model_refs: parseList(depthDraft.cost_model_refs),
          feature_leakage_probe_refs: parseList(depthDraft.feature_leakage_probe_refs),
          feature_leakage_verdict: depthDraft.feature_leakage_verdict.trim(),
          fault_injection_refs: parseList(depthDraft.fault_injection_refs),
          fault_injection_verdict: depthDraft.fault_injection_verdict.trim(),
          recovery_drill_refs: parseList(depthDraft.recovery_drill_refs),
          recovery_drill_verdict: depthDraft.recovery_drill_verdict.trim(),
          evidence_refs: parseList(depthDraft.evidence_refs),
          validation_result_refs: parseList(depthDraft.validation_result_refs),
          methodology_choice_ref: optionalText(depthDraft.methodology_choice_ref),
          responsibility_boundary_ref: optionalText(depthDraft.responsibility_boundary_ref),
          user_waived_path: depthDraft.user_waived_path,
          silent_mock_fallback_used: false,
        },
      };
      if (payload.validation_depth.evidence_refs.length === 0) throw new Error("evidence_refs required");
      if (payload.validation_depth.validation_result_refs.length === 0) {
        throw new Error("validation_result_refs required");
      }
      const result = await requestJson<{ depth_ref: string; claim_ref: string; target_environment: string }>(
        "/api/research-os/methodology/validation_depth_records",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      setLastRecordedRef(result.depth_ref);
      setDepthDraft(emptyDepth);
      await refreshSummary();
    } catch (exc) {
      setError((exc as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const summary = summaryStatus.state === "ready" ? summaryStatus.value : null;

  return (
    <div data-testid="methodology-validation-panel" style={{ display: "grid", gap: 14 }}>
      <section style={sectionStyle}>
        <PanelHeader title="Methodology validation">
          {summary && (
            <>
              <Pill tone="info">depth {summary.validation_depth_total}</Pill>
              <Pill tone="ghost">cpcv {summary.calculator_totals.cpcv}</Pill>
              <Pill tone="ghost">conformal {summary.calculator_totals.conformal}</Pill>
              <Pill tone="ghost">tca {summary.calculator_totals.tca}</Pill>
              <Pill tone="ghost">runtime drills {summary.runtime_drill_total}</Pill>
            </>
          )}
          <ActionButton testId="methodology-refresh" onClick={refreshSummary} disabled={Boolean(busy)}>
            Refresh
          </ActionButton>
        </PanelHeader>
        <div style={sectionBodyStyle}>
          {summaryStatus.state === "loading" && <p style={mutedTextStyle}>Loading methodology summary...</p>}
          {summaryStatus.state === "error" && (
            <p data-testid="methodology-summary-error" role="alert" style={errorTextStyle}>
              {summaryStatus.message}
            </p>
          )}
          {summary && (
            <div style={{ display: "grid", gap: 12 }}>
              <SummaryStrip label="validation depth" items={summary.validation_depths.map((item) => item.depth_ref)} />
              <SummaryStrip label="cpcv" items={summary.cpcv_calculations.map((item) => item.cpcv_ref)} />
              <SummaryStrip label="conformal" items={summary.conformal_calculations.map((item) => item.conformal_ref)} />
              <SummaryStrip label="tca" items={summary.tca_calculations.map((item) => item.tca_ref)} />
              <SummaryStrip label="runtime drills" items={summary.runtime_drills.map((item) => item.runtime_drill_ref)} />
              <ResultGrid>
                {summary.cpcv_calculations.slice(-3).map((item) => (
                  <MetricRow
                    key={item.cpcv_ref}
                    label={item.cpcv_ref}
                    value={`mean ${fmtNumber(item.mean_metric)} · folds ${item.fold_count}`}
                  />
                ))}
                {summary.conformal_calculations.slice(-3).map((item) => (
                  <MetricRow
                    key={item.conformal_ref}
                    label={item.conformal_ref}
                    value={`threshold ${fmtNumber(item.nonconformity_threshold)} · coverage ${fmtNumber(item.coverage_estimate)}`}
                  />
                ))}
                {summary.tca_calculations.slice(-3).map((item) => (
                  <MetricRow
                    key={item.tca_ref}
                    label={item.tca_ref}
                    value={`net ${fmtNumber(item.net_mean_bps)} bps · cost ${fmtNumber(item.total_cost_bps)} bps`}
                  />
                ))}
                {summary.validation_depths.slice(-3).map((item) => (
                  <MetricRow
                    key={item.depth_ref}
                    label={item.depth_ref}
                    value={`${item.claim_label} · ${item.target_environment}`}
                  />
                ))}
                {summary.runtime_drills.slice(-3).map((item) => (
                  <MetricRow
                    key={item.runtime_drill_ref}
                    label={item.runtime_drill_ref}
                    value={`${item.fault_scenario} · ${item.drill_mode} · ${item.fault_injection_verdict}/${item.recovery_drill_verdict}`}
                  />
                ))}
              </ResultGrid>
            </div>
          )}
        </div>
      </section>

      <section style={sectionStyle}>
        <PanelHeader title="Calculators">
          {busy && <span style={mutedTextStyle}>Running {busy}...</span>}
          {lastRecordedRef && <Pill tone="success">{ellipsis(lastRecordedRef, 34)}</Pill>}
        </PanelHeader>
        <div style={{ ...sectionBodyStyle, display: "grid", gap: 14 }}>
          {error && (
            <p data-testid="methodology-error" role="alert" style={errorTextStyle}>
              {error}
            </p>
          )}
          <div style={formGridStyle}>
            <CalculatorForm title="CPCV" action="Record CPCV" onAction={recordCPCV} disabled={Boolean(busy)}>
              <TextInput id="methodology-cpcv-claim-ref" label="claim_ref" value={cpcvDraft.claim_ref} onChange={(value) => setCpcvDraft((current) => ({ ...current, claim_ref: value }))} />
              <TextInput id="methodology-cpcv-values" label="fold_metric_values" value={cpcvDraft.fold_metric_values} onChange={(value) => setCpcvDraft((current) => ({ ...current, fold_metric_values: value }))} />
              <TextInput id="methodology-cpcv-embargo" label="embargo_observations" value={cpcvDraft.embargo_observations} onChange={(value) => setCpcvDraft((current) => ({ ...current, embargo_observations: value }))} />
              <TextInput id="methodology-cpcv-evidence-refs" label="evidence_refs" value={cpcvDraft.evidence_refs} onChange={(value) => setCpcvDraft((current) => ({ ...current, evidence_refs: value }))} />
              <TextInput id="methodology-cpcv-validation-refs" label="validation_result_refs" value={cpcvDraft.validation_result_refs} onChange={(value) => setCpcvDraft((current) => ({ ...current, validation_result_refs: value }))} />
              <TextInput id="methodology-cpcv-ref" label="cpcv_ref" value={cpcvDraft.cpcv_ref} onChange={(value) => setCpcvDraft((current) => ({ ...current, cpcv_ref: value }))} />
            </CalculatorForm>

            <CalculatorForm title="Conformal" action="Record conformal" onAction={recordConformal} disabled={Boolean(busy)}>
              <TextInput id="methodology-conformal-claim-ref" label="claim_ref" value={conformalDraft.claim_ref} onChange={(value) => setConformalDraft((current) => ({ ...current, claim_ref: value }))} />
              <TextInput id="methodology-conformal-scores" label="calibration_scores" value={conformalDraft.calibration_scores} onChange={(value) => setConformalDraft((current) => ({ ...current, calibration_scores: value }))} />
              <TextInput id="methodology-conformal-alpha" label="alpha" value={conformalDraft.alpha} onChange={(value) => setConformalDraft((current) => ({ ...current, alpha: value }))} />
              <TextInput id="methodology-conformal-evidence-refs" label="evidence_refs" value={conformalDraft.evidence_refs} onChange={(value) => setConformalDraft((current) => ({ ...current, evidence_refs: value }))} />
              <TextInput id="methodology-conformal-validation-refs" label="validation_result_refs" value={conformalDraft.validation_result_refs} onChange={(value) => setConformalDraft((current) => ({ ...current, validation_result_refs: value }))} />
              <TextInput id="methodology-conformal-abstain-ref" label="abstain_policy_ref" value={conformalDraft.abstain_policy_ref} onChange={(value) => setConformalDraft((current) => ({ ...current, abstain_policy_ref: value }))} />
              <TextInput id="methodology-conformal-ref" label="conformal_ref" value={conformalDraft.conformal_ref} onChange={(value) => setConformalDraft((current) => ({ ...current, conformal_ref: value }))} />
            </CalculatorForm>

            <CalculatorForm title="TCA" action="Record TCA" onAction={recordTCA} disabled={Boolean(busy)}>
              <TextInput id="methodology-tca-claim-ref" label="claim_ref" value={tcaDraft.claim_ref} onChange={(value) => setTcaDraft((current) => ({ ...current, claim_ref: value }))} />
              <TextInput id="methodology-tca-gross" label="gross_return_bps" value={tcaDraft.gross_return_bps} onChange={(value) => setTcaDraft((current) => ({ ...current, gross_return_bps: value }))} />
              <TextInput id="methodology-tca-components" label="cost_components_bps" value={tcaDraft.cost_components_bps} onChange={(value) => setTcaDraft((current) => ({ ...current, cost_components_bps: value }))} />
              <TextInput id="methodology-tca-cost-model-refs" label="cost_model_refs" value={tcaDraft.cost_model_refs} onChange={(value) => setTcaDraft((current) => ({ ...current, cost_model_refs: value }))} />
              <TextInput id="methodology-tca-evidence-refs" label="evidence_refs" value={tcaDraft.evidence_refs} onChange={(value) => setTcaDraft((current) => ({ ...current, evidence_refs: value }))} />
              <TextInput id="methodology-tca-validation-refs" label="validation_result_refs" value={tcaDraft.validation_result_refs} onChange={(value) => setTcaDraft((current) => ({ ...current, validation_result_refs: value }))} />
              <TextInput id="methodology-tca-ref" label="tca_ref" value={tcaDraft.tca_ref} onChange={(value) => setTcaDraft((current) => ({ ...current, tca_ref: value }))} />
            </CalculatorForm>
          </div>
        </div>
      </section>

      <section style={sectionStyle}>
        <PanelHeader title="Runtime drills">
          <Pill tone="ghost">simulation / paper / testnet only</Pill>
        </PanelHeader>
        <div style={{ ...sectionBodyStyle, display: "grid", gap: 10 }}>
          <div style={depthGridStyle}>
            <TextInput id="methodology-drill-claim-ref" label="claim_ref" value={runtimeDrillDraft.claim_ref} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, claim_ref: value }))} />
            <TextInput id="methodology-drill-target-env" label="target_environment" value={runtimeDrillDraft.target_environment} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, target_environment: value }))} />
            <TextInput id="methodology-drill-mode" label="drill_mode" value={runtimeDrillDraft.drill_mode} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, drill_mode: value }))} />
            <TextInput id="methodology-drill-venue-ref" label="venue_ref" value={runtimeDrillDraft.venue_ref} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, venue_ref: value }))} />
            <TextInput id="methodology-drill-fault-scenario" label="fault_scenario" value={runtimeDrillDraft.fault_scenario} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, fault_scenario: value }))} />
            <TextInput id="methodology-drill-expected-guard-ref" label="expected_guard_ref" value={runtimeDrillDraft.expected_guard_ref} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, expected_guard_ref: value }))} />
            <TextInput id="methodology-drill-observed-guard-ref" label="observed_guard_ref" value={runtimeDrillDraft.observed_guard_ref} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, observed_guard_ref: value }))} />
            <TextInput id="methodology-drill-recovery-action-ref" label="recovery_action_ref" value={runtimeDrillDraft.recovery_action_ref} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, recovery_action_ref: value }))} />
            <TextInput id="methodology-drill-evidence-refs" label="evidence_refs" value={runtimeDrillDraft.evidence_refs} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, evidence_refs: value }))} />
            <TextInput id="methodology-drill-validation-refs" label="validation_result_refs" value={runtimeDrillDraft.validation_result_refs} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, validation_result_refs: value }))} />
            <TextInput id="methodology-drill-runtime-ref" label="runtime_drill_ref" value={runtimeDrillDraft.runtime_drill_ref} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, runtime_drill_ref: value }))} />
            <TextInput id="methodology-drill-fault-ref" label="fault_injection_ref" value={runtimeDrillDraft.fault_injection_ref} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, fault_injection_ref: value }))} />
            <TextInput id="methodology-drill-recovery-ref" label="recovery_drill_ref" value={runtimeDrillDraft.recovery_drill_ref} onChange={(value) => setRuntimeDrillDraft((current) => ({ ...current, recovery_drill_ref: value }))} />
          </div>
          <ActionButton
            testId="methodology-record-runtime-drill"
            onClick={recordRuntimeDrill}
            disabled={Boolean(busy)}
            tone="accent"
          >
            Record runtime drill
          </ActionButton>
        </div>
      </section>

      <section style={sectionStyle}>
        <PanelHeader title="Validation depth" />
        <div style={{ ...sectionBodyStyle, display: "grid", gap: 10 }}>
          <div style={depthGridStyle}>
            <TextInput id="methodology-depth-ref" label="depth_ref" value={depthDraft.depth_ref} onChange={(value) => setDepthDraft((current) => ({ ...current, depth_ref: value }))} />
            <TextInput id="methodology-depth-claim-ref" label="claim_ref" value={depthDraft.claim_ref} onChange={(value) => setDepthDraft((current) => ({ ...current, claim_ref: value }))} />
            <TextInput id="methodology-depth-claim-label" label="claim_label" value={depthDraft.claim_label} onChange={(value) => setDepthDraft((current) => ({ ...current, claim_label: value }))} />
            <TextInput id="methodology-depth-target-env" label="target_environment" value={depthDraft.target_environment} onChange={(value) => setDepthDraft((current) => ({ ...current, target_environment: value }))} />
            <TextInput id="methodology-depth-cpcv-ref" label="cpcv_ref" value={depthDraft.cpcv_ref} onChange={(value) => setDepthDraft((current) => ({ ...current, cpcv_ref: value }))} />
            <TextInput id="methodology-depth-walk-forward-ref" label="walk_forward_ref" value={depthDraft.walk_forward_ref} onChange={(value) => setDepthDraft((current) => ({ ...current, walk_forward_ref: value }))} />
            <TextInput id="methodology-depth-conformal-ref" label="conformal_ref" value={depthDraft.conformal_ref} onChange={(value) => setDepthDraft((current) => ({ ...current, conformal_ref: value }))} />
            <TextInput id="methodology-depth-abstain-ref" label="abstain_policy_ref" value={depthDraft.abstain_policy_ref} onChange={(value) => setDepthDraft((current) => ({ ...current, abstain_policy_ref: value }))} />
            <TextInput id="methodology-depth-tca-ref" label="tca_ref" value={depthDraft.tca_ref} onChange={(value) => setDepthDraft((current) => ({ ...current, tca_ref: value }))} />
            <TextInput id="methodology-depth-cost-model-refs" label="cost_model_refs" value={depthDraft.cost_model_refs} onChange={(value) => setDepthDraft((current) => ({ ...current, cost_model_refs: value }))} />
            <TextInput id="methodology-depth-leakage-refs" label="feature_leakage_probe_refs" value={depthDraft.feature_leakage_probe_refs} onChange={(value) => setDepthDraft((current) => ({ ...current, feature_leakage_probe_refs: value }))} />
            <TextInput id="methodology-depth-leakage-verdict" label="feature_leakage_verdict" value={depthDraft.feature_leakage_verdict} onChange={(value) => setDepthDraft((current) => ({ ...current, feature_leakage_verdict: value }))} />
            <TextInput id="methodology-depth-fault-refs" label="fault_injection_refs" value={depthDraft.fault_injection_refs} onChange={(value) => setDepthDraft((current) => ({ ...current, fault_injection_refs: value }))} />
            <TextInput id="methodology-depth-fault-verdict" label="fault_injection_verdict" value={depthDraft.fault_injection_verdict} onChange={(value) => setDepthDraft((current) => ({ ...current, fault_injection_verdict: value }))} />
            <TextInput id="methodology-depth-recovery-refs" label="recovery_drill_refs" value={depthDraft.recovery_drill_refs} onChange={(value) => setDepthDraft((current) => ({ ...current, recovery_drill_refs: value }))} />
            <TextInput id="methodology-depth-recovery-verdict" label="recovery_drill_verdict" value={depthDraft.recovery_drill_verdict} onChange={(value) => setDepthDraft((current) => ({ ...current, recovery_drill_verdict: value }))} />
            <TextInput id="methodology-depth-evidence-refs" label="evidence_refs" value={depthDraft.evidence_refs} onChange={(value) => setDepthDraft((current) => ({ ...current, evidence_refs: value }))} />
            <TextInput id="methodology-depth-validation-refs" label="validation_result_refs" value={depthDraft.validation_result_refs} onChange={(value) => setDepthDraft((current) => ({ ...current, validation_result_refs: value }))} />
            <TextInput id="methodology-depth-choice-ref" label="methodology_choice_ref" value={depthDraft.methodology_choice_ref} onChange={(value) => setDepthDraft((current) => ({ ...current, methodology_choice_ref: value }))} />
            <TextInput id="methodology-depth-responsibility-ref" label="responsibility_boundary_ref" value={depthDraft.responsibility_boundary_ref} onChange={(value) => setDepthDraft((current) => ({ ...current, responsibility_boundary_ref: value }))} />
          </div>
          <label style={{ ...labelStyle, display: "flex", alignItems: "center", gap: 8 }}>
            <input
              data-testid="methodology-depth-user-waived"
              type="checkbox"
              checked={depthDraft.user_waived_path}
              onChange={(event) => setDepthDraft((current) => ({ ...current, user_waived_path: event.target.checked }))}
            />
            <span>user_waived_path</span>
          </label>
          <ActionButton
            testId="methodology-record-depth"
            onClick={recordValidationDepth}
            disabled={Boolean(busy)}
            tone="accent"
          >
            Record validation depth
          </ActionButton>
        </div>
      </section>
    </div>
  );
}

function PanelHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div style={headerStyle}>
      <strong>{title}</strong>
      <div style={{ flex: 1 }} />
      {children}
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  disabled,
  tone = "neutral",
  testId,
}: {
  children: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: "neutral" | "accent";
  testId?: string;
}) {
  return (
    <button
      data-testid={testId}
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        background: disabled ? "var(--desk-soft-btn)" : tone === "accent" ? "var(--desk-accent)" : "transparent",
        border: "1px solid var(--desk-border)",
        color: disabled ? "var(--desk-text-faint)" : tone === "accent" ? "var(--desk-accent-ink)" : "var(--desk-text-muted)",
        borderRadius: "var(--desk-radius-sm)",
        fontFamily: "inherit",
        fontSize: 11,
        fontWeight: tone === "accent" ? 700 : 500,
        padding: "7px 10px",
        cursor: disabled ? "not-allowed" : "pointer",
      }}
    >
      {children}
    </button>
  );
}

function TextInput({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label style={labelStyle}>
      <span>{label}</span>
      <input data-testid={id} value={value} onChange={(event) => onChange(event.target.value)} style={inputStyle} />
    </label>
  );
}

function CalculatorForm({
  title,
  action,
  onAction,
  disabled,
  children,
}: {
  title: string;
  action: string;
  onAction: () => void;
  disabled?: boolean;
  children: ReactNode;
}) {
  return (
    <div style={{ display: "grid", alignContent: "start", gap: 8, minWidth: 0 }}>
      <strong style={{ color: "var(--desk-text)", fontSize: 12 }}>{title}</strong>
      {children}
      <ActionButton testId={`methodology-${title.toLowerCase()}-submit`} onClick={onAction} disabled={disabled} tone="accent">
        {action}
      </ActionButton>
    </div>
  );
}

function SummaryStrip({ label, items }: { label: string; items: string[] }) {
  return (
    <div style={{ display: "grid", gap: 5 }}>
      <span style={{ color: "var(--desk-text-faint)", fontSize: 11 }}>{label}</span>
      {items.length === 0 ? (
        <span style={mutedTextStyle}>none</span>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
          {items.slice(-8).map((item) => (
            <Pill key={item} tone="ghost" title={item}>
              {ellipsis(item)}
            </Pill>
          ))}
        </div>
      )}
    </div>
  );
}

function ResultGrid({ children }: { children: ReactNode }) {
  return <div style={{ display: "grid", gap: 5 }}>{children}</div>;
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(140px, 220px) minmax(0, 1fr)", gap: 8, fontSize: 11.5 }}>
      <span style={{ color: "var(--desk-text-muted)", overflowWrap: "anywhere" }}>{label}</span>
      <span style={{ color: "var(--desk-text-faint)", overflowWrap: "anywhere" }}>{value}</span>
    </div>
  );
}

const sectionStyle: CSSProperties = {
  border: "1px solid var(--desk-border)",
  borderRadius: "var(--desk-radius-lg)",
  background: "var(--desk-card)",
  overflow: "hidden",
};

const headerStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 8,
  padding: "9px 12px",
  borderBottom: "1px solid var(--desk-border)",
  color: "var(--desk-text)",
  fontSize: 12,
};

const sectionBodyStyle: CSSProperties = {
  padding: 12,
};

const labelStyle: CSSProperties = {
  display: "grid",
  gap: 5,
  color: "var(--desk-text-muted)",
  fontSize: 11,
};

const inputStyle: CSSProperties = {
  width: "100%",
  boxSizing: "border-box",
  background: "var(--desk-input)",
  border: "1px solid var(--desk-border)",
  borderRadius: "var(--desk-radius-sm)",
  color: "var(--desk-text)",
  fontFamily: "inherit",
  fontSize: 12,
  padding: "7px 9px",
};

const mutedTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--desk-text-faint)",
  fontSize: 12,
};

const errorTextStyle: CSSProperties = {
  margin: 0,
  color: "var(--desk-danger)",
  fontSize: 12,
};

const formGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
  gap: 14,
};

const depthGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(190px, 1fr))",
  gap: 10,
};
