"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CallPanel } from "@/components/CallPanel";
import { Linkified } from "@/components/Linkified";
import { api } from "@/lib/api";
import { channelName, fmtMoney, fmtTime, timelineLabel } from "@/lib/format";
import type { Message, RunDetail, TimelineEvent } from "@/lib/types";
import { useStream } from "@/lib/useStream";

const byId = <T extends { id: number }>(list: T[], item: T) =>
  list.some((x) => x.id === item.id) ? list : [...list, item];

function headline(run: RunDetail): string {
  const amount = run.amount ? fmtMoney(run.amount, run.currency) : "";
  if (run.close_reason === "recovered") return `Recovered ${amount}`.trim();
  if (run.close_reason === "lost") return `Not recovered ${amount}`.trim();
  return run.status === "in_call" ? "On a call now" : "Recovery in progress";
}

export default function RunPage() {
  const id = Number(useParams<{ id: string }>().id);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.run(id).then((r) => { setRun(r); setError(null); }).catch((e) => setError(e.message));
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
    if (name === "timeline" && String(data.kind).startsWith("run.")) load(); // refresh the result
  }, run?.last_event_id);

  if (error) return <p role="alert" className="text-[#7a3410]">Can't load run #{id}: {error}</p>;
  if (!run) return <p className="text-muted">Loading…</p>;

  const calls = run.timeline.filter((e) => e.kind === "call.dialed").map((e) => String(e.payload.call_id));
  const callsDone = run.timeline.filter((e) => e.kind === "call.completed").length;
  const path = [...new Set(run.timeline.filter((e) => e.kind === "step.entered").map((e) => String(e.payload.step)))];
  const events = run.timeline.flatMap((e) => {
    const text = timelineLabel(e.kind, e.payload);
    return text ? [{ id: e.id, ts: e.ts, text }] : [];
  });

  return (
    <>
      <Link href="/" className="link text-[0.9375rem]">All runs</Link>
      <div className="mb-8 mt-3 flex flex-wrap items-end justify-between gap-x-12 gap-y-4">
        <div>
          <h1 className="text-5xl font-semibold leading-[1.05] tracking-[-0.03em]">{headline(run)}</h1>
          <p className="mt-2 text-[1.0625rem] text-muted">{run.customer_name ?? "Customer"} · Run #{run.id}</p>
        </div>
        {path.length > 0 && (
          <ol aria-label="Journey progress" className="flex flex-wrap gap-x-2 gap-y-1 font-mono text-[0.8125rem] text-muted">
            {path.map((step, i) => (
              <li key={step} className={i === path.length - 1 ? "font-medium text-accent-strong" : ""}>{step}{i < path.length - 1 ? " →" : ""}</li>
            ))}
          </ol>
        )}
      </div>
      <div className="flex flex-wrap items-start gap-8">
        <div className="flex min-w-0 flex-[999_1_34rem] flex-col gap-6">
          {calls.map((c) => <CallPanel key={c} callId={c} refreshKey={callsDone} />)}
          {calls.length === 0 && <section className="rounded-[0.625rem] border border-line bg-panel p-6 text-muted">No call has been placed yet.</section>}
        </div>
        <div className="flex min-w-0 flex-[1_1_22rem] flex-col gap-8">
          <section aria-labelledby="timeline-heading">
            <h2 id="timeline-heading" className="mb-3.5 text-lg font-semibold">Timeline</h2>
            <ol className="text-[0.9375rem]">
              {events.map((e) => (
                <li key={e.id} className="grid grid-cols-[4.75rem_minmax(0,1fr)] gap-3 border-t border-line py-2.5">
                  <time className="font-mono text-[0.8125rem] text-muted">{fmtTime(e.ts)}</time>
                  <span>{e.text}</span>
                </li>
              ))}
            </ol>
          </section>
          <section aria-labelledby="inbox-heading">
            <h2 id="inbox-heading" className="mb-3.5 text-lg font-semibold">Messages to the customer</h2>
            <div className="flex flex-col gap-2">
              {run.messages.map((m) => (
                <div key={m.id} className="rounded-[0.625rem] border border-line bg-panel px-4 py-3.5 text-[0.9375rem] leading-normal">
                  <p className="mb-1 text-[0.8125rem] text-muted">{channelName(m.channel)} · simulated in this demo</p>
                  <Linkified text={m.body} />
                </div>
              ))}
              {run.messages.length === 0 && <p className="text-muted">No messages sent.</p>}
            </div>
          </section>
        </div>
      </div>
    </>
  );
}
