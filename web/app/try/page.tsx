"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { answerCall, type LiveCall } from "@/lib/call";
import { fmtTime } from "@/lib/format";
import type { Call, CheckoutResult, DemoConfig, Message, RunDetail, TimelineEvent } from "@/lib/types";
import { useStream } from "@/lib/useStream";

type Stage = "form" | "abandon" | "wait" | "ring" | "live" | "result";

const RAIL = ["Abandon the cart", "Your phone rings", "Pay", "Recovered"];
const RAIL_STEP: Record<Stage, number> = { form: 0, abandon: 0, wait: 1, ring: 1, live: 2, result: 3 };

const LABEL: Record<string, (p: Record<string, any>) => string> = {
  "run.started": () => "Journey started",
  "message.sent": (p) => `Message sent (${p.channel})`,
  "wait.started": () => "Waiting before the call",
  "call.dialed": () => "Calling you",
  "call.deferred": () => "Call deferred (outside call window)",
  "call.skipped": (p) => `Call skipped (${p.reason})`,
  "call.retry_scheduled": () => "No answer, will retry",
  "call.completed": (p) => `Call finished: ${p.outcome}`,
  "event.payment_captured": (p) => `PayPal: payment captured $${p.amount}`,
  "run.ended": (p) => `Journey ended: ${p.result}`,
};

const byId = <T extends { id: number }>(list: T[], item: T) =>
  list.some((x) => x.id === item.id) ? list : [...list, item];

const card = "rounded-xl border border-line bg-panel p-4";
const btn = "rounded-lg bg-accent px-4 py-2.5 font-semibold text-bg disabled:opacity-50";
const input = "w-full rounded-lg border border-line bg-bg px-3 py-2";

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

  const attach = useCallback(async (id: number) => {
    setRunId(id);
    const s = await api.run(id);
    setSnap(s);
    if (s.close_reason) { setResult(s.close_reason); setStage("result"); return; }
    const dialed = [...s.timeline].reverse().find((e) => e.kind === "call.dialed");
    if (dialed && !s.timeline.some((e) => e.kind === "call.completed")) { // call started before we subscribed
      const c = await api.call(String(dialed.payload.call_id)).catch(() => null);
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

  // 1) wait for the run that belongs to this checkout; since=0 replays the buffer so an early start isn't missed
  useStream(order && runId === null ? "global" : null, ["run.started"], (_n, d) => {
    if (d.payload.family_id === order?.family_id) attach(d.run_id);
  }, 0);

  // 2) follow the run, resuming from the snapshot so nothing is missed or duplicated
  useStream(runId !== null ? `run:${runId}` : null, ["timeline", "message", "call.ringing", "call.ended"], (name, d) => {
    if (name === "timeline") {
      setSnap((s) => s && { ...s, timeline: byId<TimelineEvent>(s.timeline, d) });
      if (d.kind === "run.ended") { endCall(); setResult(d.payload.result); setStage("result"); }
    } else if (name === "message") setSnap((s) => s && { ...s, messages: byId<Message>(s.messages, d) });
    else if (name === "call.ringing") ring(d.call_id);
    else if (name === "call.ended") endCall();
  }, snap?.last_event_id);

  // The transcript has no stream yet, so poll it while the call is live.
  useEffect(() => {
    if (!callId || (stage !== "live" && stage !== "wait" && stage !== "result")) return;
    let alive = true;
    const tick = () => api.call(callId).then((c) => alive && setCall(c)).catch(() => {});
    tick();
    if (stage !== "live") return () => { alive = false; };
    const t = setInterval(tick, 1000);
    return () => { alive = false; clearInterval(t); };
  }, [callId, stage]);

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
        gated, audio: audio.current, onMic: setMicOpen,
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
    <section className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Try the recovery flow</h1>
        <ol className="mt-4 grid grid-cols-4 gap-2">
          {RAIL.map((label, i) => {
            const done = i < step || (stage === "result" && i === 3 && won);
            return (
              <li key={label} className={`rounded-lg border px-3 py-2 text-xs ${done ? "border-transparent bg-accent/15 text-accent"
                : i === step ? "border-accent" : "border-line text-muted"}`}>
                <b className="block uppercase tracking-wide">{i + 1}</b>
                <span className="hidden sm:inline">{i === 3 && stage === "result" && !won ? "Not recovered" : label}</span>
              </li>
            );
          })}
        </ol>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-4">
          {stage === "form" && (
            <form onSubmit={checkout} className={card}>
              <h2 className="mb-2 font-semibold">Start a checkout</h2>
              <label className="mt-3 block text-sm text-muted">Your name
                <input name="name" required defaultValue="Asha" className={`${input} mt-1`} /></label>
              <label className="mt-3 block text-sm text-muted">Phone (E.164)
                <input name="phone" type="tel" required defaultValue="+919876543210" pattern="\+[1-9][0-9]{7,14}" className={`${input} mt-1`} /></label>
              <label className="mt-3 flex gap-2 text-sm"><input name="wa" type="checkbox" defaultChecked />Send me WhatsApp reminders</label>
              <label className="mt-2 flex gap-2 text-sm"><input name="consent" type="checkbox" defaultChecked />I agree to receive an AI voice call about my order</label>
              <button disabled={busy} className={`${btn} mt-4`}>Checkout · Pro plan · $49.00</button>
              {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}
            </form>
          )}

          {stage === "abandon" && order && (
            <div className={card}>
              <h2 className="mb-2 font-semibold">Now abandon the cart</h2>
              <p className="mb-3 text-sm text-muted">Open the PayPal checkout, then <b>close it without paying</b>. After {countdown}s
                the cart counts as abandoned and the recovery journey starts.</p>
              <a href={order.approve_url} target="_blank" rel="noopener" className={`${btn} inline-block`}>Open PayPal checkout</a>
            </div>
          )}

          {stage === "wait" && (
            <div className={card}>
              <h2 className="mb-1 font-semibold">Waiting for the journey…</h2>
              <p className="text-sm text-muted">{snap?.timeline.some((e) => e.kind === "call.completed")
                ? "Call finished. Finalising…" : "Cart abandoned. A WhatsApp nudge goes out first, then the agent calls."}</p>
            </div>
          )}

          {stage === "ring" && (
            <div className={card}>
              <h2 className="mb-1 font-semibold">📞 Incoming call</h2>
              <p className="mb-3 text-sm text-muted">An AI agent is calling about your unfinished order. Allow the microphone when asked.</p>
              <label className="mb-3 flex gap-2 text-sm"><input type="checkbox" checked={gated} onChange={(e) => setGated(e.target.checked)} />
                <span>Mute my microphone when I'm not speaking <span className="text-muted">(experimental, cuts speaker echo)</span></span></label>
              <button onClick={answer} disabled={busy} className={`${btn} w-full py-4 text-lg`}>Answer</button>
              {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}
            </div>
          )}

          {stage === "live" && (
            <div className={card}>
              <h2 className="mb-1 flex items-center gap-2 font-semibold"><span className="size-2 animate-pulse rounded-full bg-rose-500" />On the call</h2>
              <p className="mb-3 text-sm text-muted">Ask for the payment link, then pay it from the thread. When the payment lands the agent will tell you out loud.</p>
              {gated && <p className="mb-3 text-sm text-muted">{micOpen ? "Mic sending" : "Mic idle"}</p>}
              <button onClick={endCall} className="rounded-lg border border-line px-4 py-2 text-accent">Hang up</button>
              {error && <p className="mt-2 text-sm text-rose-600">{error}</p>}
            </div>
          )}

          {stage === "result" && (
            <div className={card}>
              <div className={`rounded-lg p-5 text-center text-2xl font-bold ${won ? "bg-accent/15 text-accent" : "bg-black/5 dark:bg-white/10"}`}>
                {won ? `Recovered $${Number(order?.amount ?? 0)}` : "Not recovered"}</div>
              <p className="mt-2 text-center text-sm text-muted">{won
                ? "The payment landed during the call and the journey closed." : "The customer didn't pay this time."}</p>
            </div>
          )}

          {cfg?.buyer && stage !== "form" && stage !== "result" && (
            <div className={card}>
              <h2 className="mb-1 font-semibold">Paying in the sandbox</h2>
              <p className="mb-2 text-sm text-muted">Log in to PayPal with this test buyer. Nothing is charged.</p>
              <p className="text-sm">Email <code>{cfg.buyer.email}</code><br />Password <code>{cfg.buyer.password}</code></p>
            </div>
          )}
          {cfg && !cfg.voice_enabled && (
            <p className="rounded-lg bg-amber-500/15 p-3 text-sm">Voice isn't configured on this server (no API keys), so the call is simulated and won't ring.</p>
          )}
        </div>

        <div className="space-y-4">
          <Feed title="WhatsApp (simulated)" empty="No messages yet." count={snap?.messages.length ?? 0}>
            {snap?.messages.map((m) => (
              <div key={m.id} className="max-w-[88%] self-start rounded-xl bg-black/5 px-3 py-2 text-sm dark:bg-white/10">
                <small className="block text-xs text-muted">Store · {m.channel}</small><Linkified text={m.body} /></div>
            ))}
          </Feed>
          <Feed title="Call transcript" empty="The call hasn't started." count={call?.transcript.length ?? 0}>
            {call?.transcript.map((t, i) => t.role === "event" ? (
              <div key={i} className="self-center rounded-full bg-violet-500/15 px-3 py-1.5 text-xs font-semibold text-violet-700 dark:text-violet-300">
                ⚡ PayPal · {String(t.text).replace(/^\[PAYPAL EVENT\]\s*/, "")}</div>
            ) : (
              <div key={i} className={`max-w-[88%] rounded-xl px-3 py-2 text-sm ${t.role === "user" ? "self-end bg-accent/15" : "self-start bg-black/5 dark:bg-white/10"}`}>
                <small className="block text-xs text-muted">{t.role === "user" ? "You" : "Agent (AI)"}</small>{String(t.text ?? "")}</div>
            ))}
          </Feed>
          <div className={card}>
            <h2 className="mb-2 text-sm font-semibold text-muted">Timeline</h2>
            <ul className="max-h-52 space-y-1 overflow-y-auto text-sm text-muted">
              {snap?.timeline.filter((e) => LABEL[e.kind]).map((e) => (
                <li key={e.id}><time className="mr-2 text-ink tabular-nums">{fmtTime(e.ts)}</time>{LABEL[e.kind](e.payload)}</li>
              ))}
            </ul>
          </div>
        </div>
      </div>
      <audio ref={audio} autoPlay playsInline />
    </section>
  );
}

function Feed({ title, empty, count, children }: { title: string; empty: string; count: number; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { ref.current?.scrollTo({ top: ref.current.scrollHeight }); }, [count]);
  return (
    <div className={card}>
      <h2 className="mb-2 text-sm font-semibold text-muted">{title}</h2>
      <div ref={ref} className="flex max-h-80 flex-col gap-2 overflow-y-auto">
        {count === 0 ? <span className="text-sm text-muted">{empty}</span> : children}
      </div>
    </div>
  );
}

function Linkified({ text }: { text: string }) {
  return <>{text.split(/(https:\/\/\S+)/g).map((p, i) => /^https:\/\//.test(p)
    ? <a key={i} href={p} target="_blank" rel="noopener" className="text-accent underline">Open payment link</a> : p)}</>;
}
