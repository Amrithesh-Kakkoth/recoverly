"use client";
import Link from "next/link";
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
    api.runs().then((r) => { setRuns(r); setError(null); }).catch((e) => setError(e.message));
    api.metrics().then(setMetrics).catch(() => {});
  }, []);
  useEffect(load, [load]);

  // Your runs starting and ending; debounced because the buffer replays on connect.
  useStream("merchant", ["run.started", "run.ended"], () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(load, 300);
  }, 0);

  return (
    <>
      {error && <p role="alert" className="mb-6 text-[#7a3410]">Can't load your runs: {error}</p>}
      {metrics && (
        <section aria-label="Recovery results" className="flex flex-wrap items-end gap-x-14 gap-y-8 border-b border-[#c9d0ca] pb-9">
          <div className="flex-[1_1_20rem]">
            <p className="mb-1 text-[0.9375rem] text-muted">Recovered revenue</p>
            <p className="text-7xl font-semibold leading-none tracking-[-0.04em]">{fmtMoney(metrics.recovered_revenue, metrics.currency)}</p>
            <p className="mt-2 text-[0.9375rem] text-muted">{metrics.recovered} {metrics.recovered === 1 ? "order" : "orders"} brought back</p>
          </div>
          <Stat label="Recovery rate" value={metrics.recovery_rate === null ? "—" : `${Math.round(metrics.recovery_rate * 100)}%`} />
          <Stat label="Median time to pay" value={fmtDuration(metrics.median_seconds_to_pay)} />
          <Stat label="Calls per recovery" value={metrics.calls_per_recovered === null ? "—" : metrics.calls_per_recovered.toFixed(1)} />
        </section>
      )}
      {runs?.length === 0 && (
        <section className="mt-9">
          <h1 className="text-2xl font-semibold tracking-[-0.015em]">No recovery runs yet</h1>
          <p className="mt-2 text-muted">Abandon a test checkout and it will appear here. <Link className="link" href="/try">Try it now</Link></p>
        </section>
      )}
      {runs && runs.length > 0 && <RunsGrid runs={runs} />}
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-32">
      <p className="mb-1 text-sm text-muted">{label}</p>
      <p className="text-[2rem] font-semibold tracking-[-0.02em] tabular-nums">{value}</p>
    </div>
  );
}
