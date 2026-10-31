"use client";
import { AllCommunityModule, ModuleRegistry, themeQuartz, type ColDef, type ICellRendererParams } from "ag-grid-community";
import { AgGridReact } from "ag-grid-react";
import Link from "next/link";
import { useMemo, useState } from "react";
import { Badge } from "@/components/Badge";
import { fmtDate } from "@/lib/format";
import type { Run } from "@/lib/types";

ModuleRegistry.registerModules([AllCommunityModule]);

// Colours come from the app's CSS variables, so the grid follows light/dark mode with the rest of the UI.
const theme = themeQuartz.withParams({
  backgroundColor: "var(--panel)",
  foregroundColor: "var(--ink)",
  borderColor: "var(--line)",
  headerBackgroundColor: "var(--panel)",
  headerTextColor: "var(--muted)",
  oddRowBackgroundColor: "transparent",
  accentColor: "var(--accent)",
  fontFamily: "inherit",
  fontSize: 14,
});

const columns: ColDef<Run>[] = [
  { field: "id", headerName: "Run", width: 100, sort: "desc",
    cellRenderer: (p: ICellRendererParams<Run>) => <Link className="font-medium text-accent hover:underline" href={`/runs/${p.value}`}>#{p.value}</Link> },
  { headerName: "Status", valueGetter: (p) => p.data?.close_reason ?? p.data?.status ?? "", width: 150,
    cellRenderer: (p: ICellRendererParams<Run>) => <Badge>{String(p.value)}</Badge> },
  { field: "cursor", headerName: "Step", width: 140, valueFormatter: (p) => p.value ?? "—" },
  { field: "started_at", headerName: "Started", flex: 1, minWidth: 160, valueFormatter: (p) => fmtDate(p.value),
    comparator: (a, b) => Date.parse(a ?? "") - Date.parse(b ?? "") },
  { field: "ended_at", headerName: "Ended", flex: 1, minWidth: 160, valueFormatter: (p) => fmtDate(p.value),
    comparator: (a, b) => Date.parse(a ?? "") - Date.parse(b ?? "") },
];

export function RunsGrid({ runs }: { runs: Run[] }) {
  const [filter, setFilter] = useState("");
  const defaultColDef = useMemo<ColDef>(() => ({ sortable: true, filter: true, resizable: true }), []);

  return (
    <div>
      <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search runs…"
        className="mb-3 w-full max-w-xs rounded-lg border border-line bg-panel px-3 py-1.5 text-sm" />
      <div style={{ height: Math.min(560, 56 + runs.length * 42) }}>
        <AgGridReact<Run> theme={theme} rowData={runs} columnDefs={columns} defaultColDef={defaultColDef}
          quickFilterText={filter} getRowId={(p) => String(p.data.id)} rowHeight={42} />
      </div>
    </div>
  );
}
