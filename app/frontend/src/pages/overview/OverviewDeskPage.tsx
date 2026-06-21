import { type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import {
  DeskShell,
  DeskSwitcher,
  DeskTopBar,
  SegmentedControl,
  SubTabBar,
} from "../../components/desk";
import { RunsPage } from "../RunsPage";
import { ComparePage } from "../ComparePage";
import { DataPage } from "../DataPage";
import { StrategyIndexPage } from "../StrategyIndexPage";

type View = "runs" | "compare" | "data";
type RunsMode = "table" | "cards";

const TABS: { value: View; label: string }[] = [
  { value: "runs", label: "▦ 回测列表" },
  { value: "compare", label: "⇄ 对比分析" },
  { value: "data", label: "⊞ 数据中心" },
];

const SUB_HINT: Record<View, string> = {
  runs: "全部回测 · 表格 / 卡片两视图 · 选多条进对比",
  compare: "多回测净值 / 回撤 / 代码并排 · 硬指标对齐",
  data: "数据域拉取 / 字段 / 池 / 任务中心",
};

/** 内嵌真后端查看页用的可滚动容器（不重写各页，接受暗背景下的视觉差异）。 */
function Scroll({ children }: { children: ReactNode }) {
  return <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>{children}</div>;
}

/**
 * 总览台容器：把 4 个查看类页面（回测列表 / 策略卡片 / 对比分析 / 数据中心）
 * 聚合进 DeskShell。深链：?view= 选子标签、?mode= 选回测列表的表格/卡片视图、
 * ?run_ids=（多值）驱动内嵌 ComparePage（其自身用 useSearchParams 读 /overview 的 query）。
 * 这些页均真接后端，故不挂 MockBadge。本文件不碰 App.tsx / Shell.tsx / DeskTopBar / theme-cc.css。
 */
export function OverviewDeskPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const view: View = ((): View => {
    const v = searchParams.get("view");
    return v === "compare" || v === "data" ? v : "runs";
  })();
  const runsMode: RunsMode = searchParams.get("mode") === "cards" ? "cards" : "table";

  function setView(next: View): void {
    const params = new URLSearchParams(searchParams);
    params.set("view", next);
    setSearchParams(params, { replace: true });
  }

  function setRunsMode(next: RunsMode): void {
    const params = new URLSearchParams(searchParams);
    params.set("mode", next);
    setSearchParams(params, { replace: true });
  }

  function gotoCompare(ids: string[]): void {
    const params = new URLSearchParams();
    params.set("view", "compare");
    for (const id of ids) params.append("run_ids", id);
    setSearchParams(params);
  }

  const topbar = (
    <DeskTopBar>
      <DeskSwitcher current="overview" />
      <div style={{ flex: 1 }} />
      <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>{SUB_HINT[view]}</span>
    </DeskTopBar>
  );

  let center: ReactNode;
  if (view === "compare") {
    center = (
      <Scroll>
        <ComparePage />
      </Scroll>
    );
  } else if (view === "data") {
    center = (
      <Scroll>
        <DataPage />
      </Scroll>
    );
  } else {
    center = (
      <Scroll>
        {runsMode === "cards" ? <StrategyIndexPage /> : <RunsPage onCompare={gotoCompare} />}
      </Scroll>
    );
  }

  const subRight =
    view === "runs" ? (
      <SegmentedControl
        size="sm"
        value={runsMode}
        onChange={setRunsMode}
        options={[
          { value: "table", label: "表格" },
          { value: "cards", label: "卡片" },
        ]}
      />
    ) : undefined;

  return (
    <DeskShell
      desk="overview"
      topbar={topbar}
      center={
        <>
          <SubTabBar tabs={TABS} value={view} onChange={setView} right={subRight} />
          {center}
        </>
      }
    />
  );
}

export default OverviewDeskPage;
