"use client";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Linkified } from "@/components/Linkified";
import { Transcript } from "@/components/Transcript";
import { api } from "@/lib/api";
import { APP_NAME } from "@/lib/brand";
import { answerCall, type LiveCall } from "@/lib/call";
import { fmtTime, timelineLabel } from "@/lib/format";
import type { Call, CheckoutResult, DemoConfig, Message, RunDetail, TimelineEvent } from "@/lib/types";
import { useStream } from "@/lib/useStream";

type Stage = "form" | "abandon" | "wait" | "ring" | "live" | "result";

const RAIL = ["Abandon the cart", "Answer the call", "Pay during the call", "Recovered"];
const RAIL_STEP: Record<Stage, number> = { form: 0, abandon: 0, wait: 1, ring: 1, live: 2, result: 3 };

const byId = <T extends { id: number }>(list: T[], item: T) =>
  list.some((x) => x.id === item.id) ? list : [...list, item];

const card = "rounded-[0.625rem] border border-line bg-panel p-5";
const dark = "box-border rounded-xl bg-ink p-8 text-on-ink";
const btn = "h-11 cursor-pointer rounded-lg bg-ink px-4 font-semibold text-on-ink disabled:opacity-60";
const onDark = "cursor-pointer rounded-lg bg-[#3fc48f] font-bold text-[#06251a] disabled:opacity-60";
const input = "mt-1 h-11 w-full rounded-lg border border-line-strong bg-white px-3 text-base text-ink";

export default function TryPage() {
  const [cfg, setCfg] = useState<DemoConfig | null>(null);
  const [stage, setStage] = useState<Stage>("form");
  const [order, setOrder] = useState<CheckoutResult | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [snap, setSnap] = useState<RunDetail | null>(null);
  const [callId, setCallId] = useState<string | null>(null);
  const [call, setCall] = useState<Call | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [countdown, setCountdown] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [gated, setGated] = useState(false);
  const [micOpen, setMicOpen] = useState(true);
  const live = useRef<LiveCall | null>(null);
  const callRef = useRef<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);

  useEffect(() => { api.demoConfig().then(setCfg).catch(() => {}); }, []);

  // Countdown to the abandon timer, shown while the user closes the PayPal popup.
  useEffect(() => {
    if (stage !== "abandon") return;
    const t = setInterval(() => setCountdown((n) => Math.max(0, n - 1)), 1000);
    return () => clearInterval(t);
  }, [stage]);
  useEffect(() => { if (stage === "abandon" && countdown === 0) setStage("wait"); }, [stage, countdown]);

  const hangUp = useCallback(() => { live.current?.hangup(); live.current = null; }, []);
  useEffect(() => hangUp, [hangUp]);

  const endCall = useCallback(() => {
    hangUp();
    setStage((s) => (s === "live" || s === "ring" ? "wait" : s));
  }, [hangUp]);

  const attach = useCallback(async (id: number, family: string) => {
    setRunId(id);
    const s = await api.run(id, family);
    setSnap(s);
    if (s.close_reason) { setResult(s.close_reason); setStage("result"); return; }
    const dialed = [...s.timeline].reverse().find((e) => e.kind === "call.dialed");
    if (dialed && !s.timeline.some((e) => e.kind === "call.completed")) { // call started before we subscribed
      const c = await api.call(String(dialed.payload.call_id), family).catch(() => null);
      if (c?.status === "ringing") ring(String(dialed.payload.call_id));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function ring(id: string) {
    if (callRef.current === id) return;
    callRef.current = id;
    setCallId(id);
    setStage("ring");
    navigator.vibrate?.([200, 100, 200]);
  }

  // 1) wait for the run that belongs to this checkout
  useEffect(() => {
    if (!order || runId !== null) return;
    let found = false;
    const t = setInterval(async () => {
      const { run_id } = await api.runForCheckout(order.family_id).catch(() => ({ run_id: null }));
      if (run_id !== null && !found) { found = true; clearInterval(t); attach(run_id, order.family_id); }
    }, 2000);
    return () => clearInterval(t);
  }, [order, runId, attach]);

  // 2) follow the run, resuming from the snapshot so nothing is missed or duplicated
  useStream(runId !== null ? `run:${runId}` : null, ["timeline", "message", "call.ringing", "call.ended"], (name, d) => {
    if (name === "timeline") {
      setSnap((s) => s && { ...s, timeline: byId<TimelineEvent>(s.timeline, d) });
      if (d.kind === "run.ended") { endCall(); setResult(d.payload.result); setStage("result"); }
    } else if (name === "message") setSnap((s) => s && { ...s, messages: byId<Message>(s.messages, d) });
    else if (name === "call.ringing") ring(d.call_id);
    else if (name === "call.ended") endCall();
  }, snap?.last_event_id, order?.family_id);

  // The transcript has no stream yet, so poll it while the call is live.
  useEffect(() => {
    if (!callId || (stage !== "live" && stage !== "wait" && stage !== "result")) return;
    let alive = true;
    const tick = () => api.call(callId, order?.family_id).then((c) => alive && setCall(c)).catch(() => {});
    tick();
    if (stage !== "live") return () => { alive = false; };
    const t = setInterval(tick, 1000);
    return () => { alive = false; clearInterval(t); };
  }, [callId, stage, order]);

  async function checkout(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true); setError(null);
    try {
      const r = await api.checkout({
        name: String(f.get("name")), phone: String(f.get("phone")), sku: "pro-plan",
        whatsapp_optin: f.get("wa") === "on", call_consent: f.get("consent") === "on",
      });
      setOrder(r); setCountdown(Math.round(r.abandon_after_seconds)); setStage("abandon");
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  async function answer() {
    if (!callId || !audio.current) return;
    setBusy(true); setError(null);
    try {
      live.current = await answerCall(callId, {
        gated, family: order?.family_id, audio: audio.current, onMic: setMicOpen,
        onState: (s) => s === "failed" && setError("Couldn't connect audio. A TURN server may be needed on this network."),
      });
      setStage("live");
    } catch (err) {
      const e = err as Error;
      setError(e.name === "NotAllowedError" ? "Microphone access was blocked. Allow it and try again." : e.message);
    } finally { setBusy(false); }
  }

  const step = RAIL_STEP[stage];
  const won = result === "recovered";

  return (
    <>
      <header className="flex flex-wrap items-center justify-between gap-x-8 gap-y-3 bg-ink px-[clamp(1rem,4vw,3rem)] py-3.5 text-on-ink">
        <span className="text-[1.0625rem] font-bold">{APP_NAME}</span>
        <Link href="/" className="py-2.5 text-[0.9375rem] text-white underline underline-offset-2">Merchant dashboard</Link>
      </header>
      <main className="mx-auto box-border max-w-[84rem] px-[clamp(1rem,4vw,3rem)] pb-12 pt-10">
        <h1 className="mb-6 text-[2.5rem] font-semibold leading-tight tracking-[-0.025em]">Abandon a cart. Get a call.</h1>
        <ol aria-label="Demo progress" className="mb-8 grid grid-cols-[repeat(auto-fit,minmax(10rem,1fr))] gap-2 text-sm">
          {RAIL.map((label, i) => {
            const done = i < step || (stage === "result" && i === 3 && won);
            const current = i === step && !done;
            return (
              <li key={label} aria-current={current ? "step" : undefined}
                className={`border-t-[3px] pt-2.5 ${done ? "border-paypal text-accent-strong" : current ? "border-ink font-semibold" : "border-[#c9d0ca] text-muted"}`}>
                {i + 1} · {i === 3 && stage === "result" && !won ? "Not recovered" : label}
              </li>
            );
          })}
        </ol>

        <div className="flex flex-wrap items-start gap-8">
          <div className="flex min-w-0 flex-[1_1_24rem] flex-col gap-4">
            {stage === "form" && (
              <form onSubmit={checkout} className={card}>
                <h2 className="mb-1 text-xl font-semibold">Start a checkout</h2>
                <label className="mt-3 block text-sm font-medium">Your name
                  <input name="name" required defaultValue="Asha" className={input} /></label>
                <label className="mt-3 block text-sm font-medium">Phone, with country code
                  <input name="phone" type="tel" required defaultValue="+919876543210" pattern="\+[1-9][0-9]{7,14}" className={input} /></label>
                <label className="mt-4 flex gap-2.5 text-sm"><input name="wa" type="checkbox" defaultChecked className="size-[1.125rem]" />Send me WhatsApp reminders</label>
                <label className="mt-2.5 flex gap-2.5 text-sm"><input name="consent" type="checkbox" defaultChecked className="size-[1.125rem]" />I agree to receive an AI voice call about my order</label>
                <button disabled={busy} className={`${btn} mt-5`}>Checkout · Pro plan · $49.00</button>
                {error && <p role="alert" className="mt-2 text-sm text-[#7a3410]">{error}</p>}
              </form>
            )}

            {stage === "abandon" && order && (
              <section className={card}>
                <h2 className="mb-2 text-xl font-semibold">Now abandon the cart</h2>
                <p className="mb-4 text-muted">Open the PayPal checkout, then <b>close it without paying</b>. After {countdown}s the cart counts as abandoned and the recovery journey starts.</p>
                <a href={order.approve_url} target="_blank" rel="noopener" className={`${btn} inline-flex items-center`}>Open PayPal checkout</a>
              </section>
            )}

            {stage === "wait" && (
              <section className={card}>
                <h2 className="mb-1 text-xl font-semibold">Waiting for the journey…</h2>
                <p className="text-muted">{snap?.timeline.some((e) => e.kind === "call.completed")
                  ? "Call finished. Finalising…" : (cfg?.phone_calls ? "Cart abandoned. A WhatsApp nudge goes out first, then your phone rings. Pick up to talk to the agent."
                  : "Cart abandoned. A WhatsApp nudge goes out first, then the agent calls.")}</p>
              </section>
            )}

            {stage === "ring" && (
              <section className={dark}>
                <p className="mb-2 font-mono text-[0.8125rem] text-[#a6b3ac]">Incoming call</p>
                <h2 className="mb-3 text-[2rem] font-semibold leading-tight tracking-[-0.02em]">Your store is calling</h2>
                <p className="mb-6 leading-normal text-on-ink-muted">An AI agent is calling about your unfinished order. Allow the microphone when your browser asks.</p>
                <button onClick={answer} disabled={busy} className={`${onDark} h-14 w-full text-lg`}>Answer</button>
                <label className="mt-4 flex items-start gap-2.5 text-sm leading-snug text-on-ink-muted">
                  <input type="checkbox" checked={gated} onChange={(e) => setGated(e.target.checked)} className="mt-px size-[1.125rem]" />
                  Mute my microphone when I'm not speaking (experimental, cuts speaker echo)
                </label>
                {error && <p role="alert" className="mt-3 text-sm text-[#f2b8a0]">{error}</p>}
              </section>
            )}

            {stage === "live" && (
              <section className={dark}>
                <h2 className="mb-2 flex items-center gap-2.5 text-[2rem] font-semibold tracking-[-0.02em]"><span aria-hidden="true" className="size-2.5 animate-pulse rounded-full bg-[#ff7a59]" />On the call</h2>
                <p className="mb-5 leading-normal text-on-ink-muted">Ask for the payment link, then pay it from the WhatsApp thread. When the payment lands, the agent tells you out loud.</p>
                {gated && <p className="mb-4 text-sm text-on-ink-muted">{micOpen ? "Mic sending" : "Mic idle"}</p>}
                <button onClick={endCall} className="h-11 cursor-pointer rounded-lg border border-[#5a6a62] px-4 font-semibold text-white">Hang up</button>
                {error && <p role="alert" className="mt-3 text-sm text-[#f2b8a0]">{error}</p>}
              </section>
            )}

            {stage === "result" && (
              <section className={dark}>
                <h2 className="text-5xl font-semibold leading-[1.05] tracking-[-0.03em]">{won ? `Recovered $${Number(order?.amount ?? 0)}` : "Not recovered"}</h2>
                <p className="mt-3 leading-normal text-on-ink-muted">{won ? "The payment landed during the call and the journey closed." : "The customer didn't pay this time."}</p>
              </section>
            )}

            {cfg?.buyer && stage !== "form" && stage !== "result" && (
              <section className={card}>
                <h2 className="mb-1 font-semibold">Paying in the PayPal sandbox</h2>
                <p className="mb-2 text-sm text-muted">Log in with this test buyer. Nothing is charged.</p>
                <p className="text-sm">Email <code className="font-mono">{cfg.buyer.email}</code><br />Password <code className="font-mono">{cfg.buyer.password}</code></p>
              </section>
            )}
            {cfg && !cfg.voice_enabled && (
              <p className="rounded-lg bg-[#f6e0d3] p-3 text-sm text-[#5c280c]">Voice isn't configured on this server (no API keys), so the call is simulated and won't ring.</p>
            )}
          </div>

          <div className="flex min-w-0 flex-[999_1_30rem] flex-col gap-6">
            <Feed title="WhatsApp" note="simulated" empty="No messages yet." count={snap?.messages.length ?? 0}>
              <div className="flex flex-col gap-2">
                {snap?.messages.map((m) => (
                  <p key={m.id} className="max-w-[34rem] rounded-[0.625rem] bg-[#eef1ed] px-3.5 py-3 leading-snug"><Linkified text={m.body} /></p>
                ))}
              </div>
            </Feed>
            <Feed title="Call transcript" empty="The conversation appears here once you answer." count={call?.transcript.length ?? 0}>
              {call && <Transcript turns={call.transcript} you="You" />}
            </Feed>
            <section aria-labelledby="timeline-heading" className={card}>
              <h2 id="timeline-heading" className="mb-3.5 text-[1.0625rem] font-semibold">What's happening</h2>
              <ol className="flex flex-col gap-2 text-[0.9375rem]">
                {snap?.timeline.flatMap((e) => {
                  const text = timelineLabel(e.kind, e.payload);
                  return text ? [(
                    <li key={e.id} className="grid grid-cols-[4.75rem_minmax(0,1fr)] gap-3">
                      <time className="font-mono text-[0.8125rem] text-muted">{fmtTime(e.ts)}</time>{text}
                    </li>
                  )] : [];
                })}
                {!snap && <li className="text-muted">Nothing yet.</li>}
              </ol>
            </section>
          </div>
        </div>
        <audio ref={audio} autoPlay playsInline />
      </main>
    </>
  );
}

function Feed({ title, note, empty, count, children }: { title: string; note?: string; empty: string; count: number; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo({ top: ref.current.scrollHeight }); }, [count]);
  return (
    <section className={card}>
      <h2 className="mb-3.5 text-[1.0625rem] font-semibold">{title}{note && <span className="ml-2 text-sm font-normal text-muted">{note}</span>}</h2>
      <div ref={ref} className="max-h-80 overflow-y-auto">
        {count === 0 ? <p className="text-muted">{empty}</p> : children}
      </div>
    </section>
  );
}
