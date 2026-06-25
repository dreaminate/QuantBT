import { useEffect, useMemo, useState } from "react";
import { MockBadge } from "../../../components/desk";
import { authFetch } from "../../../lib/auth";
import { PanelCard, SectionTitle } from "./parts";
import { famColorVar, famBgVar } from "./factorData";
import {
  type AdmitResult,
  type LibArtifact,
  type PureLib,
  LIB_ARTIFACTS,
  LIB_META,
  admitToFactorLib,
  canEnterFactorLib,
} from "./factorLabData";

/**
 * F3 · 三纯库视图（算术暴力遍历库 / ML 库 / DL 库 三库分区纯净）。
 *
 * R17 两层解耦（dev/decisions §R17=B）：
 *  - 算术表达式：本身即信号 → 直接入因子库。
 *  - ML/DL「本体」(.pt/.pkl…)：只进【模型注册表】，禁止当因子塞因子库（范畴错误）。
 *  - ML/DL「输出」：经【信号契约】登记后，才作为信号进因子库。
 *
 * 全 mock + MockBadge；紫 accent；零裸 hex。
 */

const LIBS: PureLib[] = ["arith", "ml", "dl"];

/** 范畴徽标文案 + 色（按 ArtifactKind）。 */
function kindBadge(a: LibArtifact): { text: string; color: string } {
  switch (a.kind) {
    case "expression":
      return { text: "表达式 · 信号", color: "var(--desk-success)" };
    case "model_body":
      return { text: "模型本体 · 仅注册表", color: "var(--desk-warning)" };
    case "signal_contract":
      return { text: "信号契约 · 入库", color: "var(--desk-info)" };
  }
}

export interface FactorPureLibsViewProps {
  /** 当前选中的尝试入库产物 id（用于演示 R17 入库门）。 */
  tryId: string | null;
  onTry: (id: string | null) => void;
}

export function FactorPureLibsView({ tryId, onTry }: FactorPureLibsViewProps) {
  const byLib = useMemo(() => {
    const m: Record<PureLib, LibArtifact[]> = { arith: [], ml: [], dl: [] };
    for (const a of LIB_ARTIFACTS) m[a.lib].push(a);
    return m;
  }, []);

  const trying = tryId ? LIB_ARTIFACTS.find((a) => a.id === tryId) ?? null : null;
  // 本地范畴门判定 = 渲染裁决的确定性来源（离线可用、测试稳定）。
  const localAdmit = trying ? admitToFactorLib(trying.kind, trying.ref) : null;

  // 真实后端 POST /api/factors/admit：后端范畴门复核（R17 单一守卫两端镜像）。
  // 后端裁决到达即覆盖本地（两端口径一致，仅做服务端权威确认）；离线/未登录回落本地。
  const [serverAdmit, setServerAdmit] = useState<AdmitResult | null>(null);
  const [admitLive, setAdmitLive] = useState(false);
  useEffect(() => {
    setServerAdmit(null);
    if (!trying) return;
    let cancelled = false;
    authFetch("/api/factors/admit", {
      method: "POST",
      body: JSON.stringify({ kind: trying.kind, ref: trying.ref }),
    })
      .then(async (r) => {
        const j = await r.json().catch(() => null);
        if (cancelled || !j) return;
        // 200 → {admitted:true}; 422 → {detail:{admitted:false, reason}}。
        const d = r.ok ? j : j.detail;
        if (d && typeof d.admitted === "boolean") {
          setServerAdmit({ admitted: d.admitted, reason: d.reason ?? "" });
          setAdmitLive(true);
        }
      })
      .catch(() => {
        if (!cancelled) setAdmitLive(false);
      });
    return () => {
      cancelled = true;
    };
  }, [trying]);

  const admit = serverAdmit ?? localAdmit;

  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        overflowY: "auto",
        padding: "16px 20px",
        background: "var(--desk-canvas)",
      }}
    >
      <div style={{ maxWidth: 1080, margin: "0 auto" }}>
        {/* 顶部说明：两层解耦原则 */}
        <PanelCard accentBorder style={{ marginBottom: 16 }}>
          <SectionTitle glyph="⛬" right={<MockBadge label="MOCK 库列表 · 入库范畴门已接入 /api/factors/admit 真实后端（R17）" />}>
            三纯库 · 两层解耦（算术 / ML / DL 互不混装）
          </SectionTitle>
          <div style={{ fontSize: 11.5, color: "var(--desk-text-dim)", lineHeight: 1.7 }}>
            <span style={{ color: "var(--desk-accent)" }}>本体层</span> → 模型注册表：
            ML/DL 的 .pt/.pkl 是「模型」，不是「因子」。
            <span style={{ color: "var(--desk-info)" }}> 信号层</span> → 因子库：
            只有「输出」经
            <span style={{ color: "var(--desk-info)", fontWeight: 600 }}> 信号契约 </span>
            登记后才进因子库。排列组合/集成上移到信号层 + 策略层（OOF + purge + embargo 防 stacking 泄露）。
          </div>
        </PanelCard>

        {/* 三库分区 */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, marginBottom: 16 }}>
          {LIBS.map((lib) => {
            const meta = LIB_META[lib];
            const items = byLib[lib];
            return (
              <PanelCard key={lib} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span style={{ color: "var(--desk-accent)", fontSize: 16 }}>{meta.glyph}</span>
                  <div>
                    <div style={{ fontSize: 12.5, fontWeight: 700, color: "var(--desk-text)" }}>{meta.name}</div>
                    <div style={{ fontSize: 9.5, color: "var(--desk-text-faint)" }}>{meta.sub}</div>
                  </div>
                </div>
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--desk-text-muted)",
                    lineHeight: 1.5,
                    padding: "6px 9px",
                    background: "var(--desk-soft-btn)",
                    border: "1px solid var(--desk-border)",
                    borderRadius: "var(--desk-radius-sm)",
                  }}
                >
                  入库方式：{meta.entry}
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
                  {items.map((a) => {
                    const badge = kindBadge(a);
                    const blocked = !canEnterFactorLib(a.kind);
                    return (
                      <div
                        key={a.id}
                        data-artifact={a.id}
                        data-kind={a.kind}
                        data-can-enter={canEnterFactorLib(a.kind) ? "true" : "false"}
                        style={{
                          border: "1px solid var(--desk-border)",
                          borderRadius: "var(--desk-radius)",
                          padding: "8px 10px",
                          background: "var(--desk-card)",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                          <span
                            style={{
                              fontSize: 9,
                              padding: "1px 6px",
                              borderRadius: "var(--desk-radius-pill)",
                              border: `1px solid ${famColorVar(a.fam)}`,
                              background: famBgVar(a.fam),
                              color: famColorVar(a.fam),
                            }}
                          >
                            {a.fam}
                          </span>
                          <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--desk-text-soft)" }}>{a.title}</span>
                        </div>
                        <code
                          style={{
                            display: "block",
                            fontSize: 10,
                            color: "var(--desk-info)",
                            wordBreak: "break-all",
                            marginBottom: 5,
                          }}
                        >
                          {a.ref}
                        </code>
                        {a.modelRef && (
                          <div style={{ fontSize: 9, color: "var(--desk-text-faint)", marginBottom: 5 }}>
                            ⇠ 本体：<span style={{ color: "var(--desk-warning)" }}>{a.modelRef}</span>（模型注册表）
                          </div>
                        )}
                        <div style={{ fontSize: 9.5, color: "var(--desk-text-muted)", lineHeight: 1.45, marginBottom: 6 }}>
                          {a.desc}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                          <span style={{ fontSize: 9, color: badge.color }}>● {badge.text}</span>
                          <div style={{ flex: 1 }} />
                          <button
                            data-try={a.id}
                            onClick={() => onTry(a.id)}
                            title={blocked ? "尝试入库（应被范畴门拒）" : "尝试入因子库"}
                            style={{
                              fontSize: 9.5,
                              fontFamily: "inherit",
                              padding: "3px 8px",
                              borderRadius: "var(--desk-radius-sm)",
                              cursor: "pointer",
                              border: `1px solid ${blocked ? "var(--desk-warning)" : "var(--desk-accent)"}`,
                              background: blocked
                                ? "color-mix(in srgb, var(--desk-warning) 12%, transparent)"
                                : "color-mix(in srgb, var(--desk-accent) 12%, transparent)",
                              color: blocked ? "var(--desk-warning)" : "var(--desk-ghost)",
                            }}
                          >
                            ⊕ 入因子库
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </PanelCard>
            );
          })}
        </div>

        {/* R17 入库门：选中产物的准入判定（范畴门，诚实拒绝） */}
        {trying && admit && (
          <PanelCard
            accentBorder
            style={{ borderColor: admit.admitted ? "var(--desk-success)" : "var(--desk-danger)" }}
          >
            <SectionTitle
              right={
                <button
                  aria-label="关闭入库判定"
                  onClick={() => onTry(null)}
                  style={{
                    background: "transparent",
                    border: "none",
                    color: "var(--desk-text-muted)",
                    cursor: "pointer",
                    fontSize: 13,
                    fontFamily: "inherit",
                  }}
                >
                  ✕
                </button>
              }
            >
              入因子库 · 范畴门判定（R17）
            </SectionTitle>
            <div style={{ fontSize: 11.5, color: "var(--desk-text-soft)", marginBottom: 8 }}>
              产物 <span style={{ color: "var(--desk-accent)" }}>{trying.title}</span>
              （<code style={{ color: "var(--desk-info)" }}>{trying.ref}</code>）
              <span
                data-admit-source={admitLive ? "server" : "local"}
                style={{ marginLeft: 8, fontSize: 9.5, color: admitLive ? "var(--desk-success)" : "var(--desk-text-faint)" }}
              >
                {admitLive ? "● 服务端范畴门复核" : "○ 本地判定（离线）"}
              </span>
            </div>
            {admit.admitted ? (
              <div
                data-admit="true"
                style={{
                  fontSize: 12,
                  color: "var(--desk-success)",
                  padding: "9px 12px",
                  borderRadius: "var(--desk-radius)",
                  background: "color-mix(in srgb, var(--desk-success) 12%, transparent)",
                  border: "1px solid var(--desk-success)",
                }}
              >
                ✓ 准入：属信号层（表达式 / 信号契约），可进因子库。
              </div>
            ) : (
              <div
                data-admit="false"
                style={{
                  fontSize: 12,
                  color: "var(--desk-danger)",
                  padding: "9px 12px",
                  borderRadius: "var(--desk-radius)",
                  background: "color-mix(in srgb, var(--desk-danger) 12%, transparent)",
                  border: "1px solid var(--desk-danger)",
                  lineHeight: 1.6,
                }}
              >
                ✕ 拒绝 · {admit.reason}
              </div>
            )}
          </PanelCard>
        )}
      </div>
    </div>
  );
}

export default FactorPureLibsView;
