"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/Badge";
import { api } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { Run } from "@/lib/types";
import { useStream } from "@/lib/useStream";

export default function RunsPage() {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const load = useCallback(() => {
    api.runs().then((r) => { setRuns(r); setError(null); }).catch((e) => setError(String(e.message)));
  }, []);
  useEffect(load, [load]);

  // run.started / run.ended on the global channel; debounce because the buffer replays on connect.
  useStream("global", ["run.started", "run.ended"], () => {
    clearTimeout(timer.current);
    timer.current = setTimeout(load, 300);
  }, 0);

  return (
    <section>
      <h1 className="mb-4 text-xl font-semibold tracking-tight">Recovery runs</h1>
      {error && <p className="mb-4 rounded-md border border-line bg-panel p-3 text-sm text-rose-600">Can't reach the backend: {error}</p>}
      {runs === null && !error && <p className="text-muted">Loading…</p>}
      {runs?.length === 0 && <p className="text-muted">No runs yet. Abandon a checkout to start one.</p>}
      {runs && runs.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-line bg-panel">
          <table className="w-full text-sm">
            <thead className="border-b border-line text-left text-muted">
              <tr><th className="px-4 py-2 font-medium">Run</th><th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Step</th><th className="px-4 py-2 font-medium">Started</th></tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="border-b border-line last:border-0 hover:bg-black/[.02] dark:hover:bg-white/[.03]">
                  <td className="px-4 py-2"><Link className="font-medium text-accent hover:underline" href={`/runs/${r.id}`}>#{r.id}</Link></td>
                  <td className="px-4 py-2"><Badge>{r.close_reason ?? r.status}</Badge></td>
                  <td className="px-4 py-2 text-muted">{r.cursor ?? "—"}</td>
                  <td className="px-4 py-2 text-muted">{fmtDate(r.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
