import { type ReactNode } from "react";
import { SegmentedControl } from "../primitives";

/**
 * Inspector tab 段控（parseConsole.md §P5：参数 / 端口 / 校验 / 版本血缘）。
 * 复用 G1 SegmentedControl，不重造。受控：value + onChange。
 */

export type InspectorTab = "params" | "ports" | "validate" | "version";

const TAB_LABELS: { value: InspectorTab; label: ReactNode }[] = [
  { value: "params", label: "参数" },
  { value: "ports", label: "端口" },
  { value: "validate", label: "校验" },
  { value: "version", label: "版本/血缘" },
];

export interface InspectorTabsProps {
  value: InspectorTab;
  onChange: (v: InspectorTab) => void;
}

export function InspectorTabs({ value, onChange }: InspectorTabsProps) {
  return (
    <SegmentedControl
      options={TAB_LABELS}
      value={value}
      onChange={onChange}
      size="sm"
    />
  );
}
