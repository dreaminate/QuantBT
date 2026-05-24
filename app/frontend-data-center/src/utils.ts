export function formatPct(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "n/a";
  }
  return `${(value * 100).toFixed(2)}%`;
}


export function formatNumber(value?: number | null, digits = 3) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "n/a";
  }
  return value.toFixed(digits);
}


export function formatDateTime(value?: string | null) {
  if (!value) {
    return "n/a";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleString("en-GB", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  });
}


export function formatInteger(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "n/a";
  }
  return value.toLocaleString("en-US");
}


export function formatFileSize(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(value)) {
    return "n/a";
  }
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}


export function formatCellValue(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") {
    return "n/a";
  }
  if (typeof value === "number") {
    return Math.abs(value) >= 100 ? value.toFixed(2) : value.toFixed(4);
  }
  if (typeof value === "string" && value.includes("T") && value.includes(":")) {
    return formatDateTime(value);
  }
  return value;
}


export function classForNumber(value: unknown) {
  const number = Number(value);
  if (!Number.isFinite(number)) {
    return "";
  }
  if (number > 0) {
    return "positive";
  }
  if (number < 0) {
    return "negative";
  }
  return "";
}


export function readMetric(source: Record<string, unknown>, ...keys: string[]) {
  for (const key of keys) {
    const value = source[key];
    if (value !== undefined && value !== null && value !== "") {
      return value;
    }
  }
  return null;
}
