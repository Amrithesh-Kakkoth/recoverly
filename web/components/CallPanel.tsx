"use client";
import { useEffect, useState } from "react";
import { Transcript } from "@/components/Transcript";
import { api } from "@/lib/api";
import type { Call } from "@/lib/types";

export function CallPanel({ callId, refreshKey }: { callId: string; refreshKey: number }) {
  const [call, setCall] = useState<Call | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let live = true;
    const load = () => api.call(callId).then((c) => live && setCall(c)).catch(() => setMissing(true));
    load();
    const t = setInterval(load, 3000); // call transcripts have no stream hookup yet; poll while this page is open
    return () => { live = false; clearInterval(t); };
  }, [callId, refreshKey]);

  if (!call) return missing
    ? <section className="rounded-[0.625rem] border border-line bg-panel p-6 text-muted">No conversation was recorded for this call.</section>
    : null;
  const ms = call.voice_to_voice_ms;
  const median = ms.length ? [...ms].sort((a, b) => a - b)[Math.floor(ms.length / 2)] : null;
  const facts = [
    call.outcome ? `Outcome: ${call.outcome.replaceAll("_", " ")}` : `Status: ${call.status}`,
    median !== null ? `median reply ${(median / 1000).toFixed(1)} s` : null,
  ].filter(Boolean).join(" · ");

  return (
    <section className="rounded-[0.625rem] border border-line bg-panel p-6">
      <div className="mb-5 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <h2 className="text-lg font-semibold">Call transcript</h2>
        <span className="text-sm text-muted">{facts}</span>
      </div>
      {call.summary && <p className="mb-5 text-muted">{call.summary}</p>}
      {call.transcript.length ? <Transcript turns={call.transcript} /> : <p className="text-muted">No conversation yet.</p>}
    </section>
  );
}
