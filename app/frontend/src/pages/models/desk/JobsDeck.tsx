import { useMemo } from "react";
import {
  CollapsiblePanel,
  Pill,
  StatusDot,
  MockBadge,
  AgentChat,
  ChatComposer,
  type AgentBlock,
} from "../../../components/desk";
import {
  JOBS,
  HERO_JOB_ID,
  EPOCH_TOTAL,
  FAMILY_TONE,
  FAMILY_LABEL,
  IO_SPEC,
  COMPUTE,
  CV_FOLDS,
  ASSISTANT_DIAGNOSIS,
  ASSISTANT_CHIPS,
  curveAt,
  type TrainJob,
  type JobStatus,
  type Family,
  type JobDetail,
} from "./modelMock";
import type { BackendJob } from "./modelApi";

/**
 * 作业台（jobs · DC §A 三栏）：训练队列 + dashboard（实时曲线/算力/CV folds/动机文档）+ 训练诊断。
 * P0：mock 数据驱动，全区块挂 MockBadge；曲线由 epoch（受控 props）派生。
 */

const STATUS_TONE: Record<JobStatus, "neutral" | "success" | "danger" | "warning"> = {
  queued: "neutral",
  running: "warning",
  succeeded: "success",
  failed: "danger",
};

const STATUS_COLOR: Record<JobStatus, string> = {
  queued: "var(--desk-text-faint)",
  running: "var(--desk-accent)",
  succeeded: "var(--desk-success)",
  failed: "var(--desk-danger)",
};

const STATUS_LABEL: Record<JobStatus, string> = {
  queued: "排队中",
  running: "训练中",
  succeeded: "已完成",
  failed: "失败",
};

const EMPTY_DETAIL: JobDetail = {
  why: "", data: "", window: "", label: "", design: "", arch: "", hparams: "", sections: [],
};

/** 后端 family 字符串 → desk Family（未知归 code 黄）。 */
function toFamily(f: string): Family {
  return f === "ml" || f === "dl" ? f : "code";
}

/** 后端 detail 富文档（Record<string,unknown>）→ 强类型 JobDetail（缺字段=空，不假绿）。 */
function toDetail(d: Record<string, unknown> | undefined): JobDetail {
  if (!d) return EMPTY_DETAIL;
  const s = (k: string): string => (typeof d[k] === "string" ? (d[k] as string) : "");
  const sections = Array.isArray(d.sections)
    ? (d.sections as unknown[])
        .filter((x): x is [string, string] => Array.isArray(x) && x.length >= 2)
        .map((x) => [String(x[0]), String(x[1])] as [string, string])
    : [];
  return {
    why: s("why"), data: s("data"), window: s("window"), label: s("label"),
    design: s("design"), arch: s("arch"), hparams: s("hparams"), sections,
  };
}

/** 后端 TrainingJob → 作业台 TrainJob 视图模型（真数据接入点）。 */
export function mapBackendJob(j: BackendJob): TrainJob {
  const detail = toDetail(j.detail);
  const ndcgVal = j.metrics?.ndcg ?? j.metrics?.["ndcg@k"];
  return {
    id: j.job_id,
    name: j.name,
    family: toFamily(j.family),
    arch: detail.arch || j.model,
    task: j.task,
    status: j.status,
    elapsed: j.elapsed_seconds != null ? `${j.elapsed_seconds.toFixed(1)}s` : "—",
    ndcg: typeof ndcgVal === "number" ? ndcgVal.toFixed(3) : undefined,
    detail,
  };
}

export interface JobsDeckProps {
  selJob: string;
  onSelectJob: (id: string) => void;
  epoch: number;
  running: boolean;
  published: boolean;
  onPublish: () => void;
  queueOpen: boolean;
  onToggleQueue: () => void;
  assistOpen: boolean;
  onToggleAssist: () => void;
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: () => void;
  onAskChip: (q: string) => void;
  /** 真训练队列（已映射成 TrainJob）；非空 → 用真数据，否则回退 mock JOBS（保留 MockBadge）。 */
  realJobs?: TrainJob[];
}

export function JobsDeck(props: JobsDeckProps) {
  const jobs = props.realJobs && props.realJobs.length > 0 ? props.realJobs : JOBS;
  const isLive = jobs !== JOBS;
  const job = jobs.find((j) => j.id === props.selJob) ?? jobs[0];
  const isHero = job.id === HERO_JOB_ID;
  // hero 卡：epoch 推进到顶后视为 succeeded（与 DC 一致）。
  const heroDone = isHero && !props.running;
  const effStatus: JobStatus = heroDone ? "succeeded" : job.status;

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
      <QueuePanel
        open={props.queueOpen}
        onToggle={props.onToggleQueue}
        selJob={props.selJob}
        onSelect={props.onSelectJob}
        running={props.running}
        jobs={jobs}
        isLive={isLive}
      />
      <Dashboard
        job={job}
        status={effStatus}
        epoch={props.epoch}
        running={props.running && isHero}
        published={props.published}
        onPublish={props.onPublish}
      />
      <AssistPanel
        open={props.assistOpen}
        onToggle={props.onToggleAssist}
        draft={props.draft}
        onDraftChange={props.onDraftChange}
        onSend={props.onSend}
        onAskChip={props.onAskChip}
      />
    </div>
  );
}

// --------------------------- 左：训练队列 ---------------------------

function QueuePanel({
  open,
  onToggle,
  selJob,
  onSelect,
  running,
  jobs,
  isLive,
}: {
  open: boolean;
  onToggle: () => void;
  selJob: string;
  onSelect: (id: string) => void;
  running: boolean;
  jobs: TrainJob[];
  isLive: boolean;
}) {
  return (
    <CollapsiblePanel open={open} onToggle={onToggle} side="left" width={296} label="训练队列">
      <div
        style={{
          flex: "none",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 14px",
          borderBottom: "1px solid var(--desk-border)",
        }}
      >
        <span style={{ fontSize: 12, color: "var(--desk-text-muted)" }}>训练队列</span>
        <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--desk-text-faint)" }}>
          {jobs.length} 个
        </span>
        {isLive ? (
          <Pill tone="info" title="训练队列来自 GET /api/training/jobs">真实数据</Pill>
        ) : (
          <MockBadge />
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 10 }}>
        {jobs.map((j) => {
          const sel = j.id === selJob;
          const st: JobStatus = j.id === HERO_JOB_ID && !running ? "succeeded" : j.status;
          return (
            <button
              key={j.id}
              onClick={() => onSelect(j.id)}
              data-job-card={j.id}
              aria-pressed={sel}
              style={{
                display: "block",
                width: "100%",
                textAlign: "left",
                marginBottom: 8,
                padding: "9px 11px",
                borderRadius: "var(--desk-radius-lg)",
                cursor: "pointer",
                fontFamily: "inherit",
                background: sel ? "var(--desk-hover)" : "var(--desk-card)",
                border: `1px solid ${sel ? "var(--desk-border-hover)" : "var(--desk-border)"}`,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
                <StatusDot color={STATUS_COLOR[st]} pulse={st === "running"} />
                <span style={{ fontSize: 12.5, color: "var(--desk-text)", fontWeight: 600 }}>
                  {j.name}
                </span>
                <span style={{ marginLeft: "auto" }}>
                  <Pill tone={FAMILY_TONE[j.family]}>{FAMILY_LABEL[j.family]}</Pill>
                </span>
              </div>
              <div style={{ fontSize: 11, color: "var(--desk-text-dim)" }}>
                {j.arch} · {j.task}
              </div>
              <div style={{ fontSize: 10.5, color: STATUS_COLOR[st], marginTop: 2 }}>
                {STATUS_LABEL[st]}
                {j.elapsed !== "—" && j.elapsed !== "live" ? ` · ${j.elapsed}` : ""}
              </div>
            </button>
          );
        })}
      </div>
    </CollapsiblePanel>
  );
}

// --------------------------- 中：dashboard ---------------------------

function Dashboard({
  job,
  status,
  epoch,
  running,
  published,
  onPublish,
}: {
  job: TrainJob;
  status: JobStatus;
  epoch: number;
  running: boolean;
  published: boolean;
  onPublish: () => void;
}) {
  const hasCurves = status === "running" || status === "succeeded";
  return (
    <main style={{ flex: 1, minWidth: 0, overflowY: "auto", background: "var(--desk-canvas)" }}>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "18px 22px" }}>
        {/* header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
          <span style={{ fontSize: 17, fontWeight: 700, color: "var(--desk-text)" }}>
            {job.name}
          </span>
          <Pill tone={FAMILY_TONE[job.family]}>{FAMILY_LABEL[job.family]}</Pill>
          <span style={{ fontSize: 12, color: "var(--desk-text-dim)" }}>{job.arch}</span>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
            <MockBadge />
            <span style={{ fontSize: 11.5, color: STATUS_COLOR[status] }}>
              {STATUS_LABEL[status]}
            </span>
          </div>
        </div>

        {hasCurves ? (
          <>
            <EpochBar epoch={epoch} running={running} />
            <div style={{ display: "flex", gap: 12, marginTop: 14 }}>
              <LossCard epoch={epoch} />
              <NdcgCard epoch={epoch} />
            </div>
            <ComputeCard />
            <CvFoldsCard />
            <MotivationCard job={job} />
            <Actions status={status} published={published} onPublish={onPublish} />
          </>
        ) : (
          <QueuedPlaceholder />
        )}
      </div>
    </main>
  );
}

function EpochBar({ epoch, running }: { epoch: number; running: boolean }) {
  const pct = Math.min(100, (epoch / EPOCH_TOTAL) * 100);
  return (
    <div
      style={{
        background: "var(--desk-card)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius-lg)",
        padding: "11px 14px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 7,
          fontSize: 11.5,
          color: "var(--desk-text-dim)",
        }}
      >
        <span>
          epoch {epoch} / {EPOCH_TOTAL}
        </span>
        <span style={{ marginLeft: "auto", color: running ? "var(--desk-accent)" : "var(--desk-success)" }}>
          {running ? "训练中…" : "已收敛"}
        </span>
      </div>
      <div
        data-epoch-bar
        style={{ height: 7, borderRadius: 4, background: "var(--desk-input)", overflow: "hidden" }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            borderRadius: 4,
            background: "var(--desk-info)",
          }}
        />
      </div>
    </div>
  );
}

/** loss 双线卡（train 实线 accent / val 虚线 info）。SVG 由曲线 mock 派生。 */
function LossCard({ epoch }: { epoch: number }) {
  const { trainPath, valPath } = useMemo(() => {
    const pts: { t: number; v: number }[] = [];
    const upto = Math.max(1, epoch);
    for (let e = 0; e <= upto; e++) {
      const c = curveAt(e);
      pts.push({ t: c.trainLoss, v: c.valLoss });
    }
    const sx = (i: number) => (i / EPOCH_TOTAL) * 300;
    const sy = (val: number) => 110 - (val / 1.2) * 100;
    const toPath = (key: "t" | "v") =>
      pts.map((p, i) => `${i === 0 ? "M" : "L"}${sx(i).toFixed(1)},${sy(p[key]).toFixed(1)}`).join(" ");
    return { trainPath: toPath("t"), valPath: toPath("v") };
  }, [epoch]);

  return (
    <ChartCard title="loss（train 实线 / val 虚线）">
      <svg viewBox="0 0 300 120" width="100%" height="108" preserveAspectRatio="none">
        <path d={trainPath} fill="none" stroke="var(--desk-accent)" strokeWidth={1.8} />
        <path
          d={valPath}
          fill="none"
          stroke="var(--desk-info)"
          strokeWidth={1.6}
          strokeDasharray="3 2"
        />
      </svg>
    </ChartCard>
  );
}

function NdcgCard({ epoch }: { epoch: number }) {
  const { areaPath, linePath, latest } = useMemo(() => {
    const pts: number[] = [];
    const upto = Math.max(1, epoch);
    for (let e = 0; e <= upto; e++) pts.push(curveAt(e).ndcg);
    const sx = (i: number) => (i / EPOCH_TOTAL) * 300;
    const sy = (val: number) => 110 - (val / 0.26) * 100;
    const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${sx(i).toFixed(1)},${sy(p).toFixed(1)}`).join(" ");
    const area = `${line} L${sx(pts.length - 1).toFixed(1)},110 L0,110 Z`;
    return { areaPath: area, linePath: line, latest: pts[pts.length - 1] };
  }, [epoch]);

  return (
    <ChartCard title="val · NDCG@k" big={latest.toFixed(3)}>
      <svg viewBox="0 0 300 120" width="100%" height="108" preserveAspectRatio="none">
        <path d={areaPath} fill="var(--desk-success)" fillOpacity={0.12} stroke="none" />
        <path d={linePath} fill="none" stroke="var(--desk-success)" strokeWidth={1.8} />
      </svg>
    </ChartCard>
  );
}

function ChartCard({
  title,
  big,
  children,
}: {
  title: string;
  big?: string;
  children: React.ReactNode;
}) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        background: "var(--desk-card)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius-lg)",
        padding: "10px 12px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontSize: 11, color: "var(--desk-text-muted)" }}>{title}</span>
        {big && (
          <span
            style={{ marginLeft: "auto", fontSize: 13, fontWeight: 700, color: "var(--desk-success)" }}
          >
            {big}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function ComputeCard() {
  const vramPct = (COMPUTE.vramUsedGb / COMPUTE.vramTotalGb) * 100;
  return (
    <div
      style={{
        marginTop: 14,
        background: "var(--desk-card)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius-lg)",
        padding: "11px 14px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--desk-text-soft)" }}>算力</span>
        <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>{COMPUTE.device}</span>
        <span style={{ marginLeft: "auto" }}>
          <MockBadge />
        </span>
      </div>
      <Bar label="GPU util" value={`${COMPUTE.gpuUtil}%`} pct={COMPUTE.gpuUtil} color="var(--desk-warning)" />
      <Bar
        label={`VRAM ${COMPUTE.vramUsedGb}/${COMPUTE.vramTotalGb}G`}
        value={`${vramPct.toFixed(0)}%`}
        pct={vramPct}
        color="var(--desk-info)"
      />
      <div
        style={{
          display: "flex",
          gap: 18,
          marginTop: 8,
          fontSize: 11,
          color: "var(--desk-text-dim)",
        }}
      >
        <span>
          throughput <span style={{ color: "var(--desk-text-soft)" }}>{COMPUTE.throughput}</span>
        </span>
        <span>
          torch <span style={{ color: "var(--desk-success)" }}>{COMPUTE.subprocess}</span>
        </span>
      </div>
    </div>
  );
}

function Bar({
  label,
  value,
  pct,
  color,
}: {
  label: string;
  value: string;
  pct: number;
  color: string;
}) {
  return (
    <div style={{ marginBottom: 7 }}>
      <div
        style={{
          display: "flex",
          fontSize: 10.5,
          color: "var(--desk-text-muted)",
          marginBottom: 3,
        }}
      >
        <span>{label}</span>
        <span style={{ marginLeft: "auto" }}>{value}</span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: "var(--desk-input)", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${Math.min(100, pct)}%`, background: color, borderRadius: 3 }} />
      </div>
    </div>
  );
}

function CvFoldsCard() {
  return (
    <div
      style={{
        marginTop: 14,
        background: "var(--desk-card)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius-lg)",
        padding: "11px 14px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 9 }}>
        <span style={{ fontSize: 11.5, fontWeight: 600, color: "var(--desk-text-soft)" }}>
          Purged k-fold · embargo 1%
        </span>
        <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>防标签穿越</span>
        <span style={{ marginLeft: "auto" }}>
          <MockBadge />
        </span>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {CV_FOLDS.map((f) => (
          <div
            key={f.label}
            style={{
              flex: 1,
              textAlign: "center",
              padding: "7px 4px",
              borderRadius: "var(--desk-radius-sm)",
              background: "var(--desk-input)",
              border: `1px solid ${
                f.status === "running" ? "var(--desk-warning)" : "var(--desk-border)"
              }`,
            }}
          >
            <div style={{ fontSize: 9.5, color: "var(--desk-text-muted)" }}>{f.label}</div>
            <div
              style={{
                fontSize: 12,
                fontWeight: 600,
                color: f.status === "done" ? "var(--desk-success)" : "var(--desk-text-faint)",
              }}
            >
              {f.ndcg}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function MotivationCard({ job }: { job: TrainJob }) {
  const d = job.detail;
  const meta: [string, string][] = [
    ["数据", d.data],
    ["时间范围", d.window],
    ["标签", d.label],
    ["设计思路", d.design],
    ["架构", d.arch],
    ["超参", d.hparams],
  ];
  return (
    <div
      style={{
        marginTop: 14,
        background: "var(--desk-card)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius-lg)",
        padding: "13px 15px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span style={{ fontSize: 12.5, fontWeight: 600, color: "var(--desk-text)" }}>
          ✎ 动机与设计
        </span>
        <span style={{ marginLeft: "auto" }}>
          <MockBadge />
        </span>
      </div>
      {/* why 引用块（橙左边框） */}
      <div
        style={{
          borderLeft: "3px solid var(--desk-accent)",
          background: "var(--desk-input)",
          padding: "9px 12px",
          borderRadius: "0 var(--desk-radius-sm) var(--desk-radius-sm) 0",
          fontSize: 12,
          lineHeight: 1.65,
          color: "var(--desk-text-soft)",
          marginBottom: 12,
        }}
      >
        {d.why}
      </div>
      {/* 2 列元数据 */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px 16px" }}>
        {meta.map(([k, v]) => (
          <div key={k}>
            <div style={{ fontSize: 10, color: "var(--desk-text-muted)", marginBottom: 1 }}>{k}</div>
            <div style={{ fontSize: 11, color: "var(--desk-text-soft)", lineHeight: 1.5 }}>{v}</div>
          </div>
        ))}
      </div>
      <IoSpecBlock />
      {/* 设计细节逐项 */}
      <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
        {d.sections.map(([h, t]) => (
          <div key={h}>
            <div style={{ fontSize: 11, fontWeight: 600, color: "var(--desk-text-dim)" }}>{h}</div>
            <div style={{ fontSize: 11, color: "var(--desk-text-muted)", lineHeight: 1.55 }}>{t}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** IO 数据规格（单一来源 IO_SPEC，输入青蓝 / 输出绿）。 */
function IoSpecBlock() {
  return (
    <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 8 }}>
      <div
        style={{
          background: "var(--desk-input)",
          border: "1px solid var(--desk-cat-position)",
          borderRadius: "var(--desk-radius-sm)",
          padding: "9px 12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
          <Pill tone="info">输入</Pill>
          <span style={{ fontSize: 11.5, color: "var(--desk-info)" }}>因子矩阵 [N, 28] f32</span>
          <span style={{ marginLeft: "auto", fontSize: 9.5, color: "var(--desk-text-faint)" }}>
            {IO_SPEC.inCount} 字段
          </span>
        </div>
        <div style={{ fontSize: 11, color: "var(--desk-text-soft)" }}>来源：{IO_SPEC.inSrc}</div>
        <div style={{ fontSize: 11, color: "var(--desk-text-muted)" }}>预处理：{IO_SPEC.inPre}</div>
        <div style={{ marginTop: 6, display: "flex", flexDirection: "column", gap: 4 }}>
          {IO_SPEC.inGroups.map((g) => (
            <div key={g.group}>
              <div style={{ fontSize: 9.5, color: "var(--desk-info)" }}>
                {g.group} <span style={{ color: "var(--desk-text-faint)" }}>· {g.type}</span>
              </div>
              <div style={{ fontSize: 10.5, color: "var(--desk-text-dim)", lineHeight: 1.5 }}>
                {g.fields}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div
        style={{
          background: "var(--desk-input)",
          border: "1px solid var(--desk-success)",
          borderRadius: "var(--desk-radius-sm)",
          padding: "9px 12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 5 }}>
          <Pill tone="success">输出</Pill>
          <span style={{ fontSize: 11.5, color: "var(--desk-success)" }}>排序分 [N, 1]</span>
          <span style={{ marginLeft: "auto", fontSize: 9.5, color: "var(--desk-text-faint)" }}>
            {IO_SPEC.outCount} 字段
          </span>
        </div>
        {IO_SPEC.outGroups.map((g) => (
          <div key={g.group} style={{ marginTop: 2 }}>
            <div style={{ fontSize: 9.5, color: "var(--desk-success)" }}>
              {g.group} <span style={{ color: "var(--desk-text-faint)" }}>· {g.type}</span>
            </div>
            <div style={{ fontSize: 10.5, color: "var(--desk-text-dim)", lineHeight: 1.5 }}>
              {g.fields}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function Actions({
  status,
  published,
  onPublish,
}: {
  status: JobStatus;
  published: boolean;
  onPublish: () => void;
}) {
  if (status === "running") {
    return (
      <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
        <button
          style={{
            fontFamily: "inherit",
            fontSize: 12,
            padding: "6px 14px",
            borderRadius: "var(--desk-radius)",
            border: "1px solid var(--desk-warning)",
            background: "transparent",
            color: "var(--desk-warning)",
            cursor: "pointer",
          }}
        >
          ⏸ 暂停训练
        </button>
      </div>
    );
  }
  return (
    <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 12 }}>
      <button
        onClick={onPublish}
        disabled={published}
        style={{
          fontFamily: "inherit",
          fontSize: 12,
          fontWeight: 700,
          padding: "7px 16px",
          borderRadius: "var(--desk-radius)",
          border: "none",
          background: "var(--desk-accent)",
          color: "var(--desk-accent-ink)",
          cursor: published ? "default" : "pointer",
          opacity: published ? 0.6 : 1,
        }}
      >
        {published ? "✓ 已发布到模型库 dev" : "发布到模型库 dev"}
      </button>
      <span style={{ fontSize: 11, color: "var(--desk-info)" }}>查看完整回测详情 ↗</span>
    </div>
  );
}

function QueuedPlaceholder() {
  return (
    <div
      style={{
        marginTop: 40,
        textAlign: "center",
        color: "var(--desk-text-faint)",
        fontSize: 12.5,
      }}
    >
      <div style={{ marginBottom: 8 }}>排队中 — 等待算力空闲后开始训练</div>
      <MockBadge />
    </div>
  );
}

// --------------------------- 右：训练诊断 ---------------------------

function AssistPanel({
  open,
  onToggle,
  draft,
  onDraftChange,
  onSend,
  onAskChip,
}: {
  open: boolean;
  onToggle: () => void;
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: () => void;
  onAskChip: (q: string) => void;
}) {
  const blocks: AgentBlock[] = [
    { id: "diag", type: "say", text: ASSISTANT_DIAGNOSIS },
  ];
  return (
    <CollapsiblePanel open={open} onToggle={onToggle} side="right" width={296} label="训练面板">
      <div
        style={{
          flex: "none",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 14px",
          borderBottom: "1px solid var(--desk-border)",
        }}
      >
        <span style={{ color: "var(--desk-accent)" }}>✦</span>
        <span style={{ fontSize: 12, color: "var(--desk-text-soft)" }}>训练面板</span>
        <span style={{ marginLeft: "auto" }}>
          <MockBadge />
        </span>
      </div>
      <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
        <AgentChat
          blocks={blocks}
          composer={
            <ChatComposer
              draft={draft}
              onDraftChange={onDraftChange}
              onSend={onSend}
              model="claude（mock）"
              permissionMode="ask"
              branch="fullstack"
              placeholder="> 输入训练相关问题…"
            />
          }
          header={
            <div style={{ flex: "none", padding: "8px 13px 0", display: "flex", gap: 6, flexWrap: "wrap" }}>
              {ASSISTANT_CHIPS.map((q) => (
                <button
                  key={q}
                  onClick={() => onAskChip(q)}
                  style={{
                    fontFamily: "inherit",
                    fontSize: 10,
                    padding: "3px 8px",
                    borderRadius: "var(--desk-radius-pill)",
                    border: "1px solid var(--desk-border)",
                    background: "transparent",
                    color: "var(--desk-text-dim)",
                    cursor: "pointer",
                  }}
                >
                  {q}
                </button>
              ))}
            </div>
          }
        />
      </div>
    </CollapsiblePanel>
  );
}
