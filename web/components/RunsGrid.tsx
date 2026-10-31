"use client";
import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef, type ICellRendererParams } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge } from "@/components/Badge";
import { fmtDate, fmtMoney } from "@/lib/format";
import type { Run } from "@/lib/types";

ModuleRegistry.registerModules([AllCommunityModule]);

const theme = themeQuartz.withParams({
  backgroundColor: "var(--panel)",
  foregroundColor: "var(--ink)",
  borderColor: "var(--line)",
  headerBackgroundColor: "var(--panel)",
  headerTextColor: "var(--muted)",
  headerFontWeight: 500,
  oddRowBackgroundColor: "transparent",
  accentColor: "var(--accent)",
  fontFamily: "inherit",
  fontSize: 15,
  wrapperBorderRadius: 10,
});

const columns: ColDef<Run>[] = [
  { field: "id", headerName: "Run", width: 100, sort: "desc",
    cellRenderer: (p: ICellRendererParams<Run>) => <Link className="link font-mono text-sm" href={`/runs/${p.value}`}>#{p.value}</Link> },
  { field: "customer_name", headerName: "Customer", flex: 1, minWidth: 160, valueFormatter: (p) => p.value ?? "—" },
  { headerName: "Status", valueGetter: (p) => p.data?.close_reason ?? p.data?.status ?? "", width: 150,
    cellRenderer: (p: ICellRendererParams<Run>) => <Badge>{String(p.value)}</Badge> },
  { field: "cursor", headerName: "Step", width: 130, cellClass: "text-muted", valueFormatter: (p) => p.value ?? "—" },
  { field: "amount", headerName: "Amount", width: 120, type: "rightAligned", cellClass: "font-mono text-sm",
    comparator: (a, b) => Number(a ?? 0) - Number(b ?? 0),
    valueFormatter: (p) => (p.value ? fmtMoney(p.value, p.data?.currency ?? null) : "—") },
  { field: "started_at", headerName: "Started", flex: 1, minWidth: 160, cellClass: "text-muted", valueFormatter: (p) => fmtDate(p.value),
    comparator: (a, b) => Date.parse(a ?? "") - Date.parse(b ?? "") },
];

export function RunsGrid({ runs }: { runs: Run[] }) {
  const [filter, setFilter] = useState("");
  const defaultColDef = useMemo<ColDef>(() => ({ sortable: true, filter: true, resizable: true }), []);

  return (
    <section aria-labelledby="runs-heading" className="mt-9">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 id="runs-heading" className="text-2xl font-semibold tracking-[-0.015em]">Recovery runs</h1>
        <label className="flex items-center gap-2 text-sm text-muted">Search
          <input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Customer or run"
            className="h-11 w-60 max-w-full rounded-lg border border-line-strong bg-white px-3 text-ink" />
        </label>
      </div>
      <div style={{ height: Math.min(600, 58 + runs.length * 46) }}>
        <AgGridReact<Run> theme={theme} rowData={runs} columnDefs={columns} defaultColDef={defaultColDef}
          quickFilterText={filter} getRowId={(p) => String(p.data.id)} rowHeight={46} />
      </div>
    </section>
  );
}
