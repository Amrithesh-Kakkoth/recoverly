"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { RunsGrid } from "@/components/RunsGrid";
import { api } from "@/lib/api";
import { fmtDuration, fmtMoney } from "@/lib/format";
import type { Metrics, Run } from "@/lib/types";
import { useStream } from "@/lib/useStream";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const load = useCallback(() => {
    api.runs().then((r) => { setRuns(r); setError(null); }).catch((e) => setError(String(e.message)));
    api.metrics().then(setMetrics).catch(() => {});
  }, []);
  useEffect(load, [load]);

  // run.started / run.ended on the global channel; debounce because the buffer replays on connect.
  useStream("global", ["run.started", "run.ended"], () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(load, 300);
  }, 0);

  return (
    <section>
      {metrics && (
        <div className="mb-8 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Kpi label="Recovered revenue" value={fmtMoney(metrics.recovered_revenue, metrics.currency)} sub={`${metrics.recovered} orders`} />
          <Kpi label="Recovery rate" value={metrics.recovery_rate === null ? "—" : `${Math.round(metrics.recovery_rate * 100)}%`}
            sub={`${metrics.runs_total - metrics.runs_active} finished runs`} />
          <Kpi label="Median time to pay" value={fmtDuration(metrics.median_seconds_to_pay)} sub="from journey start" />
          <Kpi label="Calls per recovery" value={metrics.calls_per_recovered === null ? "—" : metrics.calls_per_recovered.toFixed(1)}
            sub={`${metrics.calls} calls · ${metrics.runs_active} runs active`} />
        </div>
      )}
      <h1 className="mb-4 text-xl font-semibold tracking-tight">Recovery runs</h1>
      {error && <p className="mb-4 rounded-md border border-line bg-panel p-3 text-sm text-rose-600">Can't reach the backend: {error}</p>}
      {runs === null && !error && <p className="text-muted">Loading…</p>}
      {runs?.length === 0 && <p className="text-muted">No runs yet. Abandon a checkout to start one.</p>}
      {runs && runs.length > 0 && <RunsGrid runs={runs} />}
    </section>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      <div className="mt-1 text-xs text-muted">{sub}</div>
    </div>
  );
}
