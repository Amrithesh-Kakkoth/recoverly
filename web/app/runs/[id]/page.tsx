"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/Badge";
import { CallPanel } from "@/components/CallPanel";
import { api } from "@/lib/api";
import { fmtTime } from "@/lib/format";
import type { Message, RunDetail, TimelineEvent } from "@/lib/types";
import { useStream } from "@/lib/useStream";

const byId = <T extends { id: number }>(list: T[], item: T) =>
  list.some((x) => x.id === item.id) ? list : [...list, item];

export default function RunPage() {
  const id = Number(useParams<{ id: string }>().id);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.run(id).then((r) => { setRun(r); setError(null); }).catch((e) => setError(String(e.message)));
  }, [id]);
  useEffect(load, [load]);

  // The stream resumes from the snapshot's last_event_id, so nothing is missed or duplicated.
  useStream(`run:${id}`, ["timeline", "message"], (name, data) => {
    setRun((r) => {
      if (!r) return r;
      return name === "timeline"
        ? { ...r, timeline: byId<TimelineEvent>(r.timeline, data) }
        : { ...r, messages: byId<Message>(r.messages, data) };
    });
    if (name === "timeline" && String(data.kind).startsWith("run.")) load(); // refresh status/close_reason
  }, run?.last_event_id);

  if (error) return <p className="text-rose-600">Can't load run #{id}: {error}</p>;
  if (!run) return <p className="text-muted">Loading…</p>;

  const calls = run.timeline.filter((e) => e.kind === "call.dialed").map((e) => String(e.payload.call_id));
  const callsDone = run.timeline.filter((e) => e.kind === "call.completed").length;

  return (
    <section className="space-y-6">
      <div>
        <Link href="/" className="text-sm text-muted hover:underline">← All runs</Link>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-xl font-semibold tracking-tight">Run #{run.id}</h1>
          <Badge>{run.close_reason ?? run.status}</Badge>
          {run.cursor && run.status !== "done" && <span className="text-sm text-muted">at {run.cursor}</span>}
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <Panel title="Timeline">
          <ol className="space-y-3">
            {run.timeline.map((e) => (
              <li key={e.id} className="flex gap-3 text-sm">
                <span className="w-20 shrink-0 text-muted tabular-nums">{fmtTime(e.ts)}</span>
                <div><div className="font-medium">{e.kind}</div>
                  {Object.keys(e.payload).length > 0 && (
                    <div className="text-muted">{Object.entries(e.payload).map(([k, v]) => `${k}: ${String(v)}`).join(" · ")}</div>)}
                </div>
              </li>
            ))}
            {run.timeline.length === 0 && <li className="text-sm text-muted">No events yet.</li>}
          </ol>
        </Panel>

        <Panel title="Customer inbox">
          <ul className="space-y-2">
            {run.messages.map((m) => (
              <li key={m.id} className="rounded-lg bg-emerald-500/10 p-3 text-sm">
                <div className="mb-1 text-xs text-muted">{m.channel}</div>
                <div className="whitespace-pre-wrap break-words">{m.body}</div>
              </li>
            ))}
            {run.messages.length === 0 && <li className="text-sm text-muted">No messages sent.</li>}
          </ul>
        </Panel>
      </div>

      {calls.map((c) => <CallPanel key={c} callId={c} refreshKey={callsDone} />)}
    </section>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-line bg-panel p-4">
      <h2 className="mb-3 text-sm font-semibold text-muted">{title}</h2>
      {children}
    </div>
  );
}
