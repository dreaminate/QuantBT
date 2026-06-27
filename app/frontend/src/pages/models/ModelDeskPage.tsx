import { useState, useEffect } from "react";
import {
  DeskShell,
  DeskTopBar,
  DeskSwitcher,
  SubTabBar,
} from "../../components/desk";
import { JobsDeck, mapBackendJob } from "./desk/JobsDeck";
import { RegistryDeck } from "./desk/RegistryDeck";
import { BuildDeck } from "./desk/BuildDeck";
import { ResearchDeck, type ResearchTab } from "./desk/ResearchDeck";
import { HERO_JOB_ID, EPOCH_TOTAL, type TrainJob } from "./desk/modelMock";
import { fetchJobs } from "./desk/modelApi";
import { ExperimentTrackingPage } from "../workshop/ExperimentTrackingPage";
import { TrainingBenchPage } from "./TrainingBenchPage";

/**
 * Model台（DeskShell data-desk="model" · 蓝 accent）。
 * 四子台单页：作业台 / 模型库注册表 / 构建台 / 研究台（SubTabBar 切换，对齐 DC state.view）。
 * P0：mock 数据 + 可交互 + MOCK 角标；不碰 App.tsx（路由由主控统一接）。
 */

export type ModelView =
  | "jobs"
  | "registry"
  | "build"
  | "research"
  | "experiments"
  | "training";

/** mock 当前操作者（晋级门 self-approve 校验用，对齐后端 creator）。 */
const CREATOR = "dreaminate";
/** hero 实时曲线节拍（DC 360ms）；测试环境关掉计时器避免泄漏。 */
const TICK_MS = 360;

export function ModelDeskPage() {
  const [view, setView] = useState<ModelView>("jobs");

  // ---- 作业台 state ----
  const [selJob, setSelJob] = useState(HERO_JOB_ID);
  const [epoch, setEpoch] = useState(0);
  const [running, setRunning] = useState(true);
  // 真训练队列（GET /api/training/jobs）；空/失败 → JobsDeck 回退 mock + MockBadge（不假绿）。
  const [realJobs, setRealJobs] = useState<TrainJob[] | undefined>(undefined);
  const [published, setPublished] = useState(false);
  const [queueOpen, setQueueOpen] = useState(true);
  const [assistOpen, setAssistOpen] = useState(true);
  const [jobsDraft, setJobsDraft] = useState("");

  // ---- 注册表 / 构建 / 研究 state ----
  const [buildChatOpen, setBuildChatOpen] = useState(true);
  const [paletteOpen, setPaletteOpen] = useState(true);
  const [buildDraft, setBuildDraft] = useState("");
  const [rsChatOpen, setRsChatOpen] = useState(true);
  const [rsTab, setRsTab] = useState<ResearchTab>("formula");
  const [rsDraft, setRsDraft] = useState("");

  // 真训练队列拉取（一次）：成功且非空 → 切真；失败/空 → 保持 undefined 走 mock。
  useEffect(() => {
    let cancelled = false;
    fetchJobs()
      .then((jobs) => {
        if (cancelled || jobs.length === 0) return;
        setRealJobs(jobs.map(mapBackendJob));
      })
      .catch(() => {
        /* 后端未接通：保持 mock + MockBadge，不假绿 */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // hero 实时曲线推进（epoch++ 到顶停 running）。
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      setEpoch((e) => {
        if (e >= EPOCH_TOTAL) {
          setRunning(false);
          return e;
        }
        return e + 1;
      });
    }, TICK_MS);
    return () => clearInterval(t);
  }, [running]);

  const subHint: Record<ModelView, string> = {
    jobs: "训练队列 + 实时曲线 + 算力 + CV folds + 动机文档",
    registry: "dev → staging → production，晋级须审批门",
    build: "draw.io 式图编辑器 · DL 走子进程",
    research: "理论判定 + 论文调研",
    experiments: "实验 / run 血缘谱系 · /api/experiments",
    training: "配置 → 代码预览实时刷新 → 优缺点模型卡 + 训练任务表",
  };

  return (
    <DeskShell
      desk="model"
      topbar={
        <DeskTopBar>
          <DeskSwitcher current="model" />
          <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--desk-text-faint)" }}>
            算力 · 1×A100 80G · 本地
          </span>
        </DeskTopBar>
      }
      center={
        <>
          <SubTabBar<ModelView>
            tabs={[
              { value: "jobs", label: "⊟ 作业台" },
              { value: "registry", label: "▣ 模型库注册表" },
              { value: "build", label: "⌨ 构建台" },
              { value: "research", label: "⚗ 研究台" },
              { value: "experiments", label: "⚯ 实验谱系" },
              { value: "training", label: "⚒ 训练台" },
            ]}
            value={view}
            onChange={setView}
            right={
              <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>{subHint[view]}</span>
            }
          />
          {view === "jobs" && (
            <JobsDeck
              selJob={selJob}
              onSelectJob={setSelJob}
              epoch={epoch}
              running={running}
              published={published}
              onPublish={() => setPublished(true)}
              queueOpen={queueOpen}
              onToggleQueue={() => setQueueOpen((o) => !o)}
              assistOpen={assistOpen}
              onToggleAssist={() => setAssistOpen((o) => !o)}
              draft={jobsDraft}
              onDraftChange={setJobsDraft}
              onSend={() => setJobsDraft("")}
              onAskChip={(q) => setJobsDraft(q)}
              realJobs={realJobs}
            />
          )}
          {view === "registry" && <RegistryDeck creator={CREATOR} />}
          {view === "build" && (
            <BuildDeck
              chatOpen={buildChatOpen}
              onToggleChat={() => setBuildChatOpen((o) => !o)}
              paletteOpen={paletteOpen}
              onTogglePalette={() => setPaletteOpen((o) => !o)}
              draft={buildDraft}
              onDraftChange={setBuildDraft}
              onSend={() => setBuildDraft("")}
            />
          )}
          {view === "research" && (
            <ResearchDeck
              chatOpen={rsChatOpen}
              onToggleChat={() => setRsChatOpen((o) => !o)}
              tab={rsTab}
              onTabChange={setRsTab}
              draft={rsDraft}
              onDraftChange={setRsDraft}
              onSend={() => setRsDraft("")}
              onToBuild={() => setView("build")}
            />
          )}
          {view === "experiments" && (
            <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
              <ExperimentTrackingPage />
            </div>
          )}
          {view === "training" && (
            <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
              <TrainingBenchPage />
            </div>
          )}
        </>
      }
    />
  );
}

export default ModelDeskPage;
