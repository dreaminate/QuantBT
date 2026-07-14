import { useState, useEffect } from "react";
import { Pill, MockBadge } from "../../../components/desk";
import { fetchWalkForward, type BackendWfWindow } from "./modelApi";
import {
  REGISTRY,
  FAMILY_TONE,
  FAMILY_LABEL,
  STAGE_TONE,
  STAGE_LABEL,
  WALK_FORWARD,
  IO_SPEC,
  buildGate,
  validateApprove,
  type RegistryModel,
  type Stage,
  type PromoteGate,
  type ApproveForm,
} from "./modelMock";

/**
 * 模型库注册表（registry · DC §B）：2 列富卡 + stage 胶囊 + 晋级门 + DRILL-IN modal。
 * 晋级门只做 DEMO 表单校验；当前无后端提交端点，任何状态都不报告已提交。
 * Purged-CV / embargo / OOS 切片诚实标注，不渲染成假绿。
 */

/** dev→staging→production 下一级（archived 不在裸翻路径）。 */
const NEXT_STAGE: Partial<Record<Stage, Stage>> = {
  dev: "staging",
  staging: "production",
};

export interface RegistryDeckProps {
  /** mock：当前操作者 = creator（self-approve 校验用）。 */
  creator: string;
}

export function RegistryDeck({ creator }: RegistryDeckProps) {
  const [gate, setGate] = useState<PromoteGate | null>(null);
  const [drill, setDrill] = useState<RegistryModel | null>(null);

  function openGate(m: RegistryModel): void {
    const to = m.stage ? NEXT_STAGE[m.stage] : undefined;
    if (!m.stage || !to) return;
    setGate(buildGate(m.id, m.stage, to));
  }

  return (
    <main style={{ flex: 1, minWidth: 0, overflowY: "auto", background: "var(--desk-canvas)" }}>
      <div style={{ maxWidth: 980, margin: "0 auto", padding: "18px 22px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
          <span style={{ fontSize: 12, color: "var(--desk-text-dim)" }}>
            dev → staging → production → archived（staging / production 须审批门，不可裸翻）
          </span>
          <span style={{ marginLeft: "auto" }}>
            <MockBadge />
          </span>
        </div>

        {gate && (
          <PromoteGatePanel
            gate={gate}
            creator={creator}
            onCancel={() => setGate(null)}
          />
        )}

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 14,
            marginTop: 14,
          }}
        >
          {REGISTRY.map((m) => (
            <ModelCard
              key={m.id}
              model={m}
              onOpen={() => setDrill(m)}
              onPromote={() => openGate(m)}
            />
          ))}
        </div>
      </div>

      {drill && <DrillInModal model={drill} onClose={() => setDrill(null)} />}
    </main>
  );
}

function ModelCard({
  model,
  onOpen,
  onPromote,
}: {
  model: RegistryModel;
  onOpen: () => void;
  onPromote: () => void;
}) {
  const rows: [string, string, string][] = [
    ["架构", model.archGist, "var(--desk-text-soft)"],
    ["IO", model.ioGist, "var(--desk-text-soft)"],
    ["CV · NDCG", model.ndcg, "var(--desk-success)"],
    ["walk-forward", model.wf, "var(--desk-success)"],
    ["lineage", model.lineage, "var(--desk-text-dim)"],
    ["trained", model.trained, "var(--desk-text-dim)"],
  ];
  return (
    <div
      data-model-card={model.id}
      style={{
        borderRadius: "var(--desk-radius-lg)",
        border: "1px solid var(--desk-node-border)",
        background: "var(--desk-card)",
        overflow: "hidden",
      }}
    >
      <button
        onClick={onOpen}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          textAlign: "left",
          padding: "10px 13px",
          background: "var(--desk-node-head)",
          border: "none",
          borderBottom: "1px solid var(--desk-border)",
          cursor: "pointer",
          fontFamily: "inherit",
        }}
      >
        <span style={{ color: "var(--desk-info)" }}>▣</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--desk-text)" }}>{model.id}</span>
        <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>v{model.version}</span>
        <Pill tone={FAMILY_TONE[model.family]}>{FAMILY_LABEL[model.family]}</Pill>
        <span style={{ marginLeft: "auto" }}>
          {model.stage ? (
            <Pill tone={STAGE_TONE[model.stage]}>{STAGE_LABEL[model.stage]}</Pill>
          ) : (
            <Pill tone="ghost">未注册</Pill>
          )}
        </span>
      </button>
      <div style={{ padding: "11px 13px" }}>
        <div
          style={{
            borderLeft: "2px solid var(--desk-accent)",
            paddingLeft: 9,
            fontSize: 11.5,
            color: "var(--desk-text-soft)",
            marginBottom: 10,
            lineHeight: 1.5,
          }}
        >
          {model.gist}
        </div>
        {rows.map(([k, v, c]) => (
          <div key={k} style={{ display: "flex", gap: 10, marginBottom: 4, fontSize: 11 }}>
            <span style={{ minWidth: 96, color: "var(--desk-text-muted)" }}>{k}</span>
            <span style={{ color: c }}>{v}</span>
          </div>
        ))}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 10 }}>
          {model.canPromote && model.stage && NEXT_STAGE[model.stage] && (
            <button
              onClick={onPromote}
              data-promote={model.id}
              style={{
                fontFamily: "inherit",
                fontSize: 11.5,
                padding: "5px 12px",
                borderRadius: "var(--desk-radius-sm)",
                border: "1px solid var(--desk-warning)",
                background: "transparent",
                color: "var(--desk-warning)",
                cursor: "pointer",
              }}
            >
              晋级 → {STAGE_LABEL[NEXT_STAGE[model.stage]!]}
            </button>
          )}
          <button
            onClick={onOpen}
            style={{
              fontFamily: "inherit",
              fontSize: 11.5,
              padding: "5px 10px",
              borderRadius: "var(--desk-radius-sm)",
              border: "none",
              background: "transparent",
              color: "var(--desk-info)",
              cursor: "pointer",
            }}
          >
            查看详情 ›
          </button>
          <span style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--desk-text-faint)" }}>
            {model.note}
          </span>
        </div>
      </div>
    </div>
  );
}

/**
 * 晋级审批门面板（黄系）。表单可演示 approver≠creator + reason + risk_restated 校验；
 * 当前没有晋级提交端点，因此按钮始终 fail closed。agent 永不自动。
 */
function PromoteGatePanel({
  gate,
  creator,
  onCancel,
}: {
  gate: PromoteGate;
  creator: string;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<ApproveForm>({
    approver: "",
    reason: "",
    riskRestated: false,
  });
  const blockers = validateApprove(form, creator);
  const formValid = blockers.length === 0;

  return (
    <div
      data-promote-gate
      style={{
        maxWidth: 560,
        marginTop: 12,
        padding: "13px 15px",
        borderRadius: "var(--desk-radius-lg)",
        border: "1px solid var(--desk-stage-frame-gap)",
        background: "var(--desk-card)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--desk-warning)" }}>
          晋级审批门 · {gate.modelId}
        </span>
        <span style={{ fontSize: 11, color: "var(--desk-text-dim)" }}>
          {STAGE_LABEL[gate.from]} → {STAGE_LABEL[gate.to]}
        </span>
        {gate.approvalRequired && (
          <span style={{ marginLeft: "auto" }}>
            <Pill tone="danger" title="须人工审批 + 验证背书（INV-5），agent 永不自动">
              realmoney · 不可裸翻
            </Pill>
          </span>
        )}
      </div>

      <div style={{ marginBottom: 10, display: "flex", flexDirection: "column", gap: 4 }}>
        {gate.checks.map((c, i) => (
          <div key={i} style={{ fontSize: 11.5, color: `var(--desk-${c.tone})` }}>
            {c.icon} {c.text}
          </div>
        ))}
      </div>

      {/* 审批表单（对齐后端 ApproverEqualsCreator / EmptyReason / risk_restated） */}
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <Field label={`approver（不可 = creator「${creator}」）`}>
          <input
            value={form.approver}
            onChange={(e) => setForm((f) => ({ ...f, approver: e.target.value }))}
            placeholder="审批人（须 ≠ 提交人）"
            aria-label="approver"
            style={inputStyle}
          />
        </Field>
        <Field label="reason（审批理由，必填）">
          <input
            value={form.reason}
            onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
            placeholder="为什么可以晋级？"
            aria-label="reason"
            style={inputStyle}
          />
        </Field>
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: 7,
            fontSize: 11.5,
            color: "var(--desk-text-soft)",
            cursor: "pointer",
          }}
        >
          <input
            type="checkbox"
            checked={form.riskRestated}
            onChange={(e) => setForm((f) => ({ ...f, riskRestated: e.target.checked }))}
            aria-label="risk_restated"
          />
          risk_restated — 我已复述本次晋级的风险（过拟合 / OOS 衰减 / 真钱敞口）
        </label>
      </div>

      {/* 阻止原因（诚实展示为什么不能提交） */}
      {!formValid && (
        <ul
          data-gate-blockers
          style={{
            margin: "8px 0 0",
            paddingLeft: 18,
            fontSize: 11,
            color: "var(--desk-danger)",
            lineHeight: 1.6,
          }}
        >
          {blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
      {formValid && (
        <div
          data-testid="promote-demo-only"
          style={{ marginTop: 8, fontSize: 11, color: "var(--desk-warning)", lineHeight: 1.6 }}
        >
          DEMO 表单校验通过，但未调用后端晋级端点；registry 状态不会改变。
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <button
          data-gate-approve
          disabled
          title="后端晋级提交端点未连接"
          style={{
            fontFamily: "inherit",
            fontSize: 11.5,
            fontWeight: 700,
            padding: "6px 14px",
            borderRadius: "var(--desk-radius-sm)",
            border: "none",
            background: "var(--desk-warning)",
            color: "var(--desk-accent-ink)",
            cursor: "not-allowed",
            opacity: 0.45,
          }}
        >
          DEMO · 未提交后端
        </button>
        <button
          onClick={onCancel}
          style={{
            fontFamily: "inherit",
            fontSize: 11.5,
            padding: "6px 14px",
            borderRadius: "var(--desk-radius-sm)",
            border: "1px solid var(--desk-border)",
            background: "transparent",
            color: "var(--desk-text-dim)",
            cursor: "pointer",
          }}
        >
          取消
        </button>
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  width: "100%",
  background: "var(--desk-input)",
  border: "1px solid var(--desk-border)",
  borderRadius: "var(--desk-radius-sm)",
  color: "var(--desk-text-soft)",
  padding: "5px 8px",
  fontFamily: "inherit",
  fontSize: 11.5,
  outline: "none",
};

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{ fontSize: 10.5, color: "var(--desk-text-muted)", marginBottom: 3 }}>{label}</div>
      {children}
    </div>
  );
}

/** 真 walk-forward 拉取状态（mock 回退 / 真数据 / 诚实待跑）。 */
type WfState =
  | { kind: "mock" }
  | { kind: "real"; ran: boolean; windows: BackendWfWindow[] };

/** DRILL-IN 模型详情浮窗（walk-forward 逐窗 + IO；OOS 诚实标注，真 mock 双源）。 */
function DrillInModal({ model, onClose }: { model: RegistryModel; onClose: () => void }) {
  const mockWindows = WALK_FORWARD[model.id] ?? [];
  // 真 walk-forward：有 jobId 才拉；fetch 失败/无 → 回退 mock（保留 MockBadge，不假绿）。
  const [wf, setWf] = useState<WfState>({ kind: "mock" });
  useEffect(() => {
    if (!model.jobId) {
      setWf({ kind: "mock" });
      return;
    }
    let cancelled = false;
    fetchWalkForward(model.jobId)
      .then((res) => {
        if (cancelled) return;
        setWf({ kind: "real", ran: res.ran, windows: res.windows });
      })
      .catch(() => {
        if (!cancelled) setWf({ kind: "mock" });
      });
    return () => {
      cancelled = true;
    };
  }, [model.jobId]);

  const isReal = wf.kind === "real";
  // 真数据：ran=false → 视作未跑（不渲染逐窗）；ran=true 用真窗。否则回退 mock。
  const realWindows = isReal && wf.ran ? wf.windows : [];
  const showReal = isReal && wf.ran && realWindows.length > 0;
  const showMock = !isReal && mockWindows.length > 0;
  const emptyHonest = (isReal && !wf.ran) || (!isReal && mockWindows.length === 0);

  return (
    <div
      data-drillin
      role="dialog"
      aria-label={`模型详情 ${model.id}`}
      style={{
        position: "fixed",
        inset: 0,
        background: "var(--desk-minimap-bg)",
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "center",
        paddingTop: 60,
        zIndex: 50,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 620,
          maxHeight: "80vh",
          overflowY: "auto",
          background: "var(--desk-panel)",
          border: "1px solid var(--desk-border-strong)",
          borderRadius: "var(--desk-radius-lg)",
          boxShadow: "var(--desk-node-shadow)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "12px 16px",
            borderBottom: "1px solid var(--desk-border)",
          }}
        >
          <span style={{ fontSize: 14, fontWeight: 600, color: "var(--desk-text)" }}>{model.id}</span>
          <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>v{model.version}</span>
          {model.stage ? (
            <Pill tone={STAGE_TONE[model.stage]}>{STAGE_LABEL[model.stage]}</Pill>
          ) : (
            <Pill tone="ghost">未注册</Pill>
          )}
          <span style={{ marginLeft: "auto" }}>
            {isReal ? (
              <Pill tone="info" title="walk-forward 来自后端 result.json 逐窗">
                walk-forward 真实数据
              </Pill>
            ) : (
              <MockBadge />
            )}
          </span>
          <button
            onClick={onClose}
            aria-label="关闭"
            style={{
              fontFamily: "inherit",
              fontSize: 14,
              border: "none",
              background: "transparent",
              color: "var(--desk-text-dim)",
              cursor: "pointer",
              marginLeft: 8,
            }}
          >
            ✕
          </button>
        </div>
        <div style={{ padding: "14px 16px" }}>
          <div style={{ fontSize: 12, color: "var(--desk-text-soft)", marginBottom: 12 }}>
            {model.gist} · lineage {model.lineage}
          </div>

          {/* walk-forward 逐窗 */}
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--desk-text)", marginBottom: 6 }}>
            walk-forward 逐窗（每窗真·样本外，OOS 切片未被探索期触碰）
          </div>
          {emptyHonest ? (
            <div
              style={{
                fontSize: 11.5,
                color: "var(--desk-warning)",
                padding: "8px 10px",
                border: "1px solid var(--desk-stage-frame-gap)",
                borderRadius: "var(--desk-radius-sm)",
                background: "var(--desk-input)",
              }}
            >
              ○ walk-forward 待跑 — 训练未完成，不展示为已通过（不假绿灯）
            </div>
          ) : showReal ? (
            // 真逐窗（后端 walk_forward_windows）：metric 按正负诚实上色，负窗不洗成绿。
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ color: "var(--desk-text-muted)", textAlign: "left" }}>
                  <th style={thStyle}>窗口</th>
                  <th style={thStyle}>训练/测试样本</th>
                  <th style={thStyle}>OOS 指标</th>
                </tr>
              </thead>
              <tbody>
                {realWindows.map((w) => {
                  const neg = w.metric != null && w.metric < 0;
                  return (
                    <tr key={w.w} style={{ borderTop: "1px solid var(--desk-border-soft)" }}>
                      <td style={tdStyle}>{w.w}</td>
                      <td style={{ ...tdStyle, color: "var(--desk-text-dim)" }}>
                        {w.n_train} → {w.n_test}
                      </td>
                      <td style={{ ...tdStyle, color: neg ? "var(--desk-danger)" : "var(--desk-success)" }}>
                        {w.metric != null ? `${w.metric_key ?? "metric"} ${w.metric.toFixed(3)}` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : showMock ? (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ color: "var(--desk-text-muted)", textAlign: "left" }}>
                  <th style={thStyle}>窗口</th>
                  <th style={thStyle}>训练段 → 测试段</th>
                  <th style={thStyle}>OOS 超额</th>
                  <th style={thStyle}>NDCG</th>
                </tr>
              </thead>
              <tbody>
                {mockWindows.map((w) => {
                  const neg = w.oosExcess.startsWith("-");
                  return (
                    <tr key={w.w} style={{ borderTop: "1px solid var(--desk-border-soft)" }}>
                      <td style={tdStyle}>{w.w}</td>
                      <td style={{ ...tdStyle, color: "var(--desk-text-dim)" }}>{w.seg}</td>
                      <td style={{ ...tdStyle, color: neg ? "var(--desk-danger)" : "var(--desk-success)" }}>
                        {w.oosExcess}
                      </td>
                      <td style={{ ...tdStyle, color: "var(--desk-text-soft)" }}>{w.ndcg}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          ) : (
            <div
              style={{
                fontSize: 11.5,
                color: "var(--desk-warning)",
                padding: "8px 10px",
                border: "1px solid var(--desk-stage-frame-gap)",
                borderRadius: "var(--desk-radius-sm)",
                background: "var(--desk-input)",
              }}
            >
              ○ walk-forward 待跑 — 训练未完成，不展示为已通过（不假绿灯）
            </div>
          )}

          {/* IO 规格（单一来源） */}
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--desk-text)", margin: "14px 0 6px" }}>
            IO 数据规格
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <div style={{ flex: 1 }}>
              <Pill tone="info">输入 · {IO_SPEC.inCount} 字段</Pill>
              <div style={{ fontSize: 10.5, color: "var(--desk-text-dim)", marginTop: 5, lineHeight: 1.5 }}>
                {IO_SPEC.inGroups.map((g) => g.group).join(" · ")}
              </div>
            </div>
            <div style={{ flex: 1 }}>
              <Pill tone="success">输出 · {IO_SPEC.outCount} 字段</Pill>
              <div style={{ fontSize: 10.5, color: "var(--desk-text-dim)", marginTop: 5, lineHeight: 1.5 }}>
                {IO_SPEC.outGroups.map((g) => g.group).join(" · ")}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

const thStyle: React.CSSProperties = { padding: "5px 6px", fontWeight: 400 };
const tdStyle: React.CSSProperties = { padding: "5px 6px" };
