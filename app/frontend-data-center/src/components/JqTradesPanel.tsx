import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getRunTable } from "../api";
import type { RunTableColumn, TableOrder } from "../types";
import { formatInteger } from "../utils";


const TRADES_JQ_ORDER: string[] = [
  "execution_timestamp",
  "symbol",
  "trade_side",
  "quantity",
  "price",
  "turnover",
  "realized_pnl",
  "estimated_fee",
  "delta_weight",
  "execution_model",
  "fee_rate",
  "estimated_slippage",
];


function sortColumnsLikeJq(columns: RunTableColumn[]): RunTableColumn[] {
  const rank = (key: string) => {
    const index = TRADES_JQ_ORDER.indexOf(key);
    return index === -1 ? 1000 : index;
  };
  return [...columns].sort((left, right) => rank(left.key) - rank(right.key) || left.key.localeCompare(right.key));
}


const DEFAULT_KEYS = new Set([
  "execution_timestamp",
  "symbol",
  "trade_side",
  "quantity",
  "price",
  "turnover",
  "realized_pnl",
  "estimated_fee",
]);


function dayPart(ts: string | null | undefined): string {
  if (!ts) return "—";
  return String(ts).slice(0, 10);
}


function timePart(ts: string | null | undefined): string {
  if (!ts) return "—";
  const value = String(ts);
  if (!value.includes("T")) return "—";
  return (value.split("T")[1] ?? "").slice(0, 8) || "—";
}


function formatExecutionTs(ts: string | null | undefined): string {
  if (!ts) return "—";
  const date = new Date(ts);
  if (Number.isNaN(date.getTime())) return String(ts);
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  });
}


function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  const number = Number(value);
  const text = Math.abs(number).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return number < 0 ? `-${text}` : text;
}


function formatQty(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 4 })}股`;
}


type TableCol = RunTableColumn | { key: "_jq_date" | "_jq_time"; label: string; dtype: "string" };


function expandTimestampColumns(displayCols: RunTableColumn[]): TableCol[] {
  const out: TableCol[] = [];
  for (const column of displayCols) {
    if (column.key === "execution_timestamp") {
      out.push(
        { key: "_jq_date", label: "日期", dtype: "string" },
        { key: "_jq_time", label: "委托时间", dtype: "string" },
      );
    } else {
      out.push(column);
    }
  }
  return out;
}


export function JqTradesPanel({ runId, available }: { runId: string; available: boolean }) {
  const [groupByDay, setGroupByDay] = useState(true);
  const [order, setOrder] = useState<TableOrder>("desc");
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [pageSize, setPageSize] = useState(100);
  const [offset, setOffset] = useState(0);
  const [startTs, setStartTs] = useState("");
  const [endTs, setEndTs] = useState("");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [groupPage, setGroupPage] = useState(0);
  const [groupDaysPerPage, setGroupDaysPerPage] = useState(5);

  const query = useQuery({
    queryKey: ["jq-trades", runId, order, pageSize, offset, startTs, endTs, symbolFilter],
    queryFn: () =>
      getRunTable(runId, "trades", {
        limit: pageSize,
        offset,
        sort: "execution_timestamp",
        order,
        start_ts: startTs.trim() || undefined,
        end_ts: endTs.trim() || undefined,
        symbol: symbolFilter.trim() || undefined,
      }),
    enabled: available && Boolean(runId),
  });

  const columns = query.data?.columns ?? [];
  const rows = query.data?.rows ?? [];
  const totalRows = query.data?.total_rows ?? 0;
  const sortedColumns = useMemo(() => sortColumnsLikeJq(columns), [columns]);

  const mergedVisible = useMemo(() => {
    const next: Record<string, boolean> = {};
    for (const column of columns) {
      if (visible[column.key] !== undefined) {
        next[column.key] = visible[column.key]!;
      } else {
        next[column.key] = DEFAULT_KEYS.has(column.key);
      }
    }
    return next;
  }, [columns, visible]);

  const displayCols = sortedColumns.filter((column) => mergedVisible[column.key]);
  const tableCols = useMemo(() => expandTimestampColumns(displayCols), [displayCols]);

  const grouped = useMemo(() => {
    const map = new Map<string, Array<Record<string, string | number | null>>>();
    for (const row of rows) {
      const key = dayPart(row.execution_timestamp as string);
      const bucket = map.get(key) ?? [];
      bucket.push(row);
      map.set(key, bucket);
    }
    for (const [, bucket] of map) {
      bucket.sort((left, right) => String(left.execution_timestamp ?? "").localeCompare(String(right.execution_timestamp ?? "")));
    }
    return Array.from(map.entries()).sort((left, right) => right[0].localeCompare(left[0]));
  }, [rows]);

  const groupPageCount = Math.max(1, Math.ceil(grouped.length / groupDaysPerPage) || 1);
  const safeGroupPage = Math.min(groupPage, Math.max(0, groupPageCount - 1));
  const pagedGroups = useMemo(() => {
    const start = safeGroupPage * groupDaysPerPage;
    return grouped.slice(start, start + groupDaysPerPage);
  }, [grouped, safeGroupPage, groupDaysPerPage]);

  useEffect(() => {
    setGroupPage(0);
  }, [offset, pageSize, order, startTs, endTs, symbolFilter, groupByDay]);

  useEffect(() => {
    const maxPage = Math.max(0, Math.ceil(grouped.length / groupDaysPerPage) - 1);
    setGroupPage((current) => (current > maxPage ? maxPage : current));
  }, [grouped.length, groupDaysPerPage]);

  const toggleCol = (key: string) => {
    setVisible((current) => ({ ...current, [key]: !mergedVisible[key] }));
  };

  const renderCell = (
    column: TableCol,
    row: Record<string, string | number | null>,
    mode: "flat" | "grouped",
  ): ReactNode => {
    if (column.key === "_jq_date") return <span className="jq-trade-ts">{dayPart(row.execution_timestamp as string)}</span>;
    if (column.key === "_jq_time") {
      return <span className={`jq-trade-ts ${mode === "grouped" ? "muted" : ""}`}>{timePart(row.execution_timestamp as string)}</span>;
    }
    const raw = row[column.key];
    if (column.key === "execution_timestamp") return <span className="jq-trade-ts">{formatExecutionTs(raw as string)}</span>;
    if (column.key === "quantity") return formatQty(raw as number);
    if (column.key === "turnover" || column.key === "realized_pnl" || column.key === "estimated_fee") return formatMoney(raw as number);
    if ("dtype" in column && column.dtype === "number") return formatMoney(raw as number);
    return raw === null || raw === undefined ? "—" : String(raw);
  };

  if (!available) return <p className="muted">暂无成交明细 artifact。</p>;
  if (query.isLoading) return <p className="muted">加载成交中...</p>;
  if (query.isError) return <p className="error-text">加载成交失败。</p>;

  const startRow = totalRows === 0 ? 0 : offset + 1;
  const endRow = Math.min(offset + rows.length, totalRows);

  return (
    <div className="jq-panel jq-trades-panel jq-pixel-table">
      <div className="jq-table-filters jq-table-filters-pixel jq-trades-filters-row">
        <label className="jq-trades-page-size">
          <span className="muted">行数</span>
          <select
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setOffset(0);
            }}
          >
            {[50, 100, 200, 500].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span className="muted">开始时间</span>
          <input className="jq-filter-input" value={startTs} onChange={(event) => setStartTs(event.target.value)} />
        </label>
        <label>
          <span className="muted">结束时间</span>
          <input className="jq-filter-input" value={endTs} onChange={(event) => setEndTs(event.target.value)} />
        </label>
        <label>
          <span className="muted">标的</span>
          <input className="jq-filter-input" value={symbolFilter} onChange={(event) => setSymbolFilter(event.target.value.toUpperCase())} />
        </label>
      </div>

      <div className="jq-panel-toolbar">
        <div className="jq-col-toggles">
          {sortedColumns.map((column) => (
            <label key={column.key} className="jq-col-toggle">
              <input type="checkbox" checked={mergedVisible[column.key] ?? false} onChange={() => toggleCol(column.key)} />
              {column.label}
            </label>
          ))}
        </div>
        <div className="actions">
          <button type="button" className={groupByDay ? "tab-button active" : "tab-button"} onClick={() => setGroupByDay((value) => !value)}>
            Group by day
          </button>
          <button type="button" className={order === "desc" ? "tab-button active" : "tab-button"} onClick={() => setOrder(order === "desc" ? "asc" : "desc")}>
            {order === "desc" ? "最新在前" : "最旧在前"}
          </button>
        </div>
      </div>

      {!groupByDay ? (
        <div className="table-wrap jq-table-pixel">
          <table className="data-table jq-trades-table">
            <thead>
              <tr>
                {tableCols.map((column) => (
                  <th key={column.key}>{column.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={`flat-${index}`}>
                  {tableCols.map((column) => (
                    <td key={column.key} className={("dtype" in column && column.dtype === "number") || column.key === "quantity" ? "jq-num-cell" : undefined}>
                      {renderCell(column, row, "flat")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="jq-trade-groups">
          {pagedGroups.map(([date, dayRows]) => (
            <section key={date} className="jq-trade-day">
              <div className="jq-trade-day-title">{date}</div>
              <div className="table-wrap jq-table-pixel">
                <table className="data-table jq-trades-table">
                  <thead>
                    <tr>
                      {tableCols.map((column) => (
                        <th key={column.key}>{column.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {dayRows.map((row, index) => (
                      <tr key={`${date}-${index}`}>
                        {tableCols.map((column) => (
                          <td key={column.key} className={("dtype" in column && column.dtype === "number") || column.key === "quantity" ? "jq-num-cell" : undefined}>
                            {renderCell(column, row, "grouped")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      )}

      <div className="jq-table-footer">
        <div className="muted">
          {startRow}-{endRow} / {formatInteger(totalRows)}
        </div>
        <div className="actions">
          {groupByDay ? (
            <>
              <label className="jq-inline-select">
                <span className="muted">每页天数</span>
                <select value={groupDaysPerPage} onChange={(event) => setGroupDaysPerPage(Number(event.target.value))}>
                  {[3, 5, 10, 20].map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <button type="button" className="ghost-button" onClick={() => setGroupPage((value) => Math.max(0, value - 1))} disabled={safeGroupPage <= 0}>
                上一页
              </button>
              <span className="muted">
                {safeGroupPage + 1} / {groupPageCount}
              </span>
              <button type="button" className="ghost-button" onClick={() => setGroupPage((value) => Math.min(groupPageCount - 1, value + 1))} disabled={safeGroupPage >= groupPageCount - 1}>
                下一页
              </button>
            </>
          ) : (
            <>
              <button type="button" className="ghost-button" onClick={() => setOffset((value) => Math.max(0, value - pageSize))} disabled={offset <= 0}>
                上一页
              </button>
              <button type="button" className="ghost-button" onClick={() => setOffset((value) => value + pageSize)} disabled={offset + pageSize >= totalRows}>
                下一页
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
