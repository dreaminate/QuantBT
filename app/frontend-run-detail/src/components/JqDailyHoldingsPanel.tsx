import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getRunTable } from "../api";
import type { RunTableColumn } from "../types";
import { formatInteger } from "../utils";


const HOLDINGS_JQ_ORDER: string[] = [
  "symbol",
  "quantity",
  "close_price",
  "market_value",
  "pnl",
  "side",
  "row_kind",
  "entry_open",
  "exit_open",
  "timestamp",
  "weight",
  "score",
  "selected_period_return",
  "gross_contribution",
  "funding_contribution",
];


function sortColumnsLikeJq(columns: RunTableColumn[]): RunTableColumn[] {
  const rank = (key: string) => {
    const index = HOLDINGS_JQ_ORDER.indexOf(key);
    return index === -1 ? 1000 + key.charCodeAt(0) : index;
  };
  return [...columns].sort((left, right) => rank(left.key) - rank(right.key) || left.key.localeCompare(right.key));
}


function dayKey(ts: string | number | null | undefined): string {
  if (ts === null || ts === undefined) return "—";
  const value = String(ts);
  return value.length >= 10 ? value.slice(0, 10) : value;
}


function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}


function formatQty(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return `${Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 4 })}股`;
}


const DEFAULT_KEYS = new Set(["symbol", "quantity", "close_price", "market_value", "pnl"]);


export function JqDailyHoldingsPanel({ runId, available }: { runId: string; available: boolean }) {
  const [groupByDay, setGroupByDay] = useState(true);
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [startTs, setStartTs] = useState("");
  const [endTs, setEndTs] = useState("");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [dayGroupPage, setDayGroupPage] = useState(0);
  const [daysPerPage, setDaysPerPage] = useState(5);

  const query = useQuery({
    queryKey: ["jq-holdings", runId, startTs, endTs, symbolFilter],
    queryFn: () =>
      getRunTable(runId, "positions", {
        limit: 100000,
        offset: 0,
        sort: "execution_timestamp",
        order: "asc",
        start_ts: startTs.trim() || undefined,
        end_ts: endTs.trim() || undefined,
        symbol: symbolFilter.trim() || undefined,
      }),
    enabled: available && Boolean(runId),
  });

  const columns = query.data?.columns ?? [];
  const sortedColumns = useMemo(() => sortColumnsLikeJq(columns), [columns]);
  const rows = query.data?.rows ?? [];

  const mergedVisible = useMemo(() => {
    const next: Record<string, boolean> = {};
    for (const column of columns) {
      if (visible[column.key] !== undefined) next[column.key] = visible[column.key]!;
      else next[column.key] = DEFAULT_KEYS.has(column.key);
    }
    return next;
  }, [columns, visible]);

  const displayCols = sortedColumns.filter((column) => mergedVisible[column.key] && column.key !== "execution_timestamp");

  const grouped = useMemo(() => {
    const map = new Map<string, Array<Record<string, string | number | null>>>();
    for (const row of rows) {
      const key = dayKey(row.execution_timestamp as string);
      const bucket = map.get(key) ?? [];
      bucket.push(row);
      map.set(key, bucket);
    }
    return Array.from(map.entries()).sort((left, right) => left[0].localeCompare(right[0]));
  }, [rows]);

  const groupPageCount = Math.max(1, Math.ceil(grouped.length / daysPerPage) || 1);
  const safePage = Math.min(dayGroupPage, Math.max(0, groupPageCount - 1));
  const pagedGroups = useMemo(() => {
    const start = safePage * daysPerPage;
    return grouped.slice(start, start + daysPerPage);
  }, [grouped, safePage, daysPerPage]);

  useEffect(() => {
    setDayGroupPage(0);
  }, [startTs, endTs, symbolFilter]);

  useEffect(() => {
    const maxPage = Math.max(0, Math.ceil(grouped.length / daysPerPage) - 1);
    setDayGroupPage((current) => (current > maxPage ? maxPage : current));
  }, [grouped.length, daysPerPage]);

  const toggleCol = (key: string) => {
    setVisible((current) => ({ ...current, [key]: !mergedVisible[key] }));
  };

  if (!available) return <p className="muted">暂无持仓明细 artifact。</p>;
  if (query.isLoading) return <p className="muted">加载持仓中...</p>;
  if (query.isError) return <p className="error-text">加载持仓失败。</p>;

  const renderRow = (
    row: Record<string, string | number | null>,
    rowKey: string,
    isCash: boolean,
  ): ReactNode => (
    <tr key={rowKey} className={isCash ? "jq-holdings-cash" : undefined}>
      {displayCols.map((column) => {
        const raw = row[column.key];
        let cell: ReactNode;
        if (column.key === "symbol") {
          cell =
            String(raw ?? "").toUpperCase() === "CASH" || isCash ? (
              <span className="jq-cash-badge-wrap">
                <span className="jq-cash-badge">Cash</span>
              </span>
            ) : (
              String(raw ?? "—")
            );
        } else if (column.dtype === "number") {
          cell = column.key === "quantity" ? formatQty(raw as number) : formatMoney(raw as number);
        } else {
          cell = raw === null || raw === undefined ? "—" : String(raw);
        }
        return (
          <td key={column.key} className="jq-num-cell">
            {cell}
          </td>
        );
      })}
    </tr>
  );

  const dayTotals = (dayRows: Array<Record<string, string | number | null>>) => {
    let marketValue = 0;
    let pnl = 0;
    for (const row of dayRows) {
      const mv = Number(row.market_value ?? 0);
      const pl = Number(row.pnl ?? 0);
      if (Number.isFinite(mv)) marketValue += mv;
      if (Number.isFinite(pl)) pnl += pl;
    }
    return { marketValue, pnl };
  };

  return (
    <div className="jq-panel jq-holdings-panel jq-pixel-table">
      <div className="jq-table-filters jq-table-filters-pixel">
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
        <button type="button" className={groupByDay ? "tab-button active" : "tab-button"} onClick={() => setGroupByDay((value) => !value)}>
          Group by day
        </button>
      </div>

      {!groupByDay ? (
        <div className="table-wrap jq-table-pixel">
          <table className="data-table jq-holdings-table">
            <thead>
              <tr>
                {displayCols.map((column) => (
                  <th key={column.key}>{column.label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => {
                const isCash = String(row.symbol ?? "").toUpperCase() === "CASH" || String(row.row_kind ?? "") === "cash";
                return renderRow(row, `flat-${index}`, isCash);
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="jq-holdings-groups">
          {pagedGroups.map(([date, dayRows]) => {
            const ordered = [...dayRows].sort((left, right) => {
              const leftCash = String(left.symbol ?? "").toUpperCase() === "CASH" ? 1 : 0;
              const rightCash = String(right.symbol ?? "").toUpperCase() === "CASH" ? 1 : 0;
              return leftCash - rightCash || String(left.symbol ?? "").localeCompare(String(right.symbol ?? ""));
            });
            const totals = dayTotals(dayRows);
            return (
              <section key={date} className="jq-holdings-day">
                <div className="jq-holdings-day-title">{date}</div>
                <div className="jq-holdings-summary">
                  <span>市值合计: {formatMoney(totals.marketValue)}</span>
                  <span>盈亏合计: {formatMoney(totals.pnl)}</span>
                </div>
                <div className="table-wrap jq-table-pixel">
                  <table className="data-table jq-holdings-table">
                    <thead>
                      <tr>
                        {displayCols.map((column) => (
                          <th key={column.key}>{column.label}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {ordered.map((row, index) => {
                        const isCash = String(row.symbol ?? "").toUpperCase() === "CASH" || String(row.row_kind ?? "") === "cash";
                        return renderRow(row, `${date}-${index}`, isCash);
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            );
          })}
        </div>
      )}

      <div className="jq-table-footer">
        <div className="muted">
          共 {formatInteger(rows.length)} 行，按日分组 {formatInteger(grouped.length)} 组
        </div>
        {groupByDay ? (
          <div className="actions">
            <label className="jq-inline-select">
              <span className="muted">每页天数</span>
              <select value={daysPerPage} onChange={(event) => setDaysPerPage(Number(event.target.value))}>
                {[3, 5, 10, 20].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="ghost-button" onClick={() => setDayGroupPage((value) => Math.max(0, value - 1))} disabled={safePage <= 0}>
              上一页
            </button>
            <span className="muted">
              {safePage + 1} / {groupPageCount}
            </span>
            <button type="button" className="ghost-button" onClick={() => setDayGroupPage((value) => Math.min(groupPageCount - 1, value + 1))} disabled={safePage >= groupPageCount - 1}>
              下一页
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
