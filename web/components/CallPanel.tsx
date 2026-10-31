"use client";
import { useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import { api } from "@/lib/api";
import type { Call } from "@/lib/types";

export function CallPanel({ callId, refreshKey }: { callId: string; refreshKey: number }) {
  const [call, setCall] = useState<Call | null>(null);

  useEffect(() => {
    let live = true;
    const load = () => api.call(callId).then((c) => live && setCall(c)).catch(() => {});
    load();
    const t = setInterval(load, 3000); // call transcripts have no stream hookup yet; poll while this page is open
    return () => { live = false; clearInterval(t); };
  }, [callId, refreshKey]);

  if (!call) return null;
  const ms = call.voice_to_voice_ms;
  const median = ms.length ? [...ms].sort((a, b) => a - b)[Math.floor(ms.length / 2)] : null;

  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold text-muted">Call {callId.slice(0, 8)}</h2>
        <Badge>{call.status}</Badge>
        {call.outcome && <Badge>{call.outcome}</Badge>}
        {median !== null && <span className="text-xs text-muted">median voice-to-voice {Math.round(median)} ms</span>}
      </div>
      {call.summary && <p className="mb-3 text-sm">{call.summary}</p>}
      <ul className="space-y-2 text-sm">
        {call.transcript.map((t, i) => (
          <li key={i}><span className="mr-2 font-medium">{t.role ?? "—"}</span>
            <span className="text-muted">{t.text ?? t.content ?? ""}</span></li>
        ))}
        {call.transcript.length === 0 && <li className="text-muted">No transcript yet.</li>}
      </ul>
    </div>
  );
}
