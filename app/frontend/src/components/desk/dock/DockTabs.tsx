import { type ReactNode } from "react";
import { SegmentedControl } from "../primitives";

/**
 * Dock tab 段控（parseConsole.md §P6：6 tab 工作台）。
 * 复用 G1 SegmentedControl，不重造。受控：value + onChange。
 */

export type DockTab =
  | "preview"
  | "schema"
  | "stats"
  | "logs"
  | "history"
  | "lineage";

const TAB_LABELS: { value: DockTab; label: ReactNode }[] = [
  { value: "preview", label: "输出预览" },
  { value: "schema", label: "Schema" },
  { value: "stats", label: "统计" },
  { value: "logs", label: "日志" },
  { value: "history", label: "运行历史" },
  { value: "lineage", label: "血缘溯源" },
];

export interface DockTabsProps {
  value: DockTab;
  onChange: (v: DockTab) => void;
}

export function DockTabs({ value, onChange }: DockTabsProps) {
  return (
    <SegmentedControl
      options={TAB_LABELS}
      value={value}
      onChange={onChange}
      size="sm"
    />
  );
}
