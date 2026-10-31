"use client";
import { useEffect, useState } from "react";
import { FlowGraph } from "@/components/FlowGraph";
import { api } from "@/lib/api";
import type { CompileResult, Journey } from "@/lib/types";

const card = "rounded-[0.625rem] border border-line bg-panel p-5";
const primary = "h-11 cursor-pointer rounded-lg bg-ink px-4.5 font-semibold text-on-ink disabled:opacity-60";

export default function JourneysPage() {
  const [active, setActive] = useState<Journey | null>(null);
  const [prompt, setPrompt] = useState("");
  const [draft, setDraft] = useState<CompileResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = () => api.journeys().then((j) => setActive(j[0] ?? null)).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function generate(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setError(null); setDraft(null); setSaved(false);
    try { setDraft(await api.compileJourney(prompt)); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  async function save() {
    if (!draft?.definition) return;
    setBusy(true); setError(null);
    try {
      await api.saveJourney(draft.definition, active?.id ?? null, prompt);
      setSaved(true); setDraft(null); setPrompt(""); await load();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <>
      <h1 className="mb-2 text-[2.5rem] font-semibold leading-tight tracking-[-0.025em]">What happens after a cart is abandoned</h1>
      <p className="mb-8 text-[1.0625rem] text-muted">Describe it in plain English. Runs already in progress keep the version they started on.</p>

      <form onSubmit={generate} className={`${card} mb-10`}>
        <label className="flex flex-col gap-2 text-sm font-medium">Describe a new version
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3}
            placeholder="Send a WhatsApp reminder, wait 20 minutes, then call once. Offer up to 5% off. If they don't pick up, give up."
            className="resize-y rounded-lg border border-line-strong p-3 text-base font-normal text-ink" />
        </label>
        <div className="mt-3.5 flex flex-wrap items-center gap-x-4 gap-y-3">
          <button disabled={busy || !prompt.trim()} className={primary}>{busy && !draft ? "Generating…" : "Generate journey"}</button>
          <span className="text-sm text-muted">Discounts are capped at 10%, and calls need the customer's consent.</span>
        </div>
      </form>

      {saved && <p role="status" className="mb-6 text-accent-strong">Saved. New runs will use version {active?.version}.</p>}
      {error && <p role="alert" className="mb-6 text-[#7a3410]">{error}</p>}

      {draft && (
        <section aria-labelledby="draft-heading" className={`${card} mb-10 space-y-4`}>
          <h2 id="draft-heading" className="text-2xl font-semibold tracking-[-0.015em]">Draft</h2>
          {draft.definition ? (
            <>
              <Summary lines={draft.summary} />
              <FlowGraph journey={draft.definition} />
              <button type="button" onClick={save} disabled={busy} className={primary}>Save as new version</button>
            </>
          ) : (
            <div>
              <p className="mb-1 font-medium">Couldn't produce a valid journey. Try rewording:</p>
              <ul className="list-disc pl-5 text-muted">{draft.errors.map((e) => <li key={e}>{e}</li>)}</ul>
            </div>
          )}
        </section>
      )}

      {active && (
        <section aria-labelledby="active-heading" className="space-y-4">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
            <h2 id="active-heading" className="text-2xl font-semibold tracking-[-0.015em]">{active.name}</h2>
            <span className="font-mono text-[0.8125rem] text-muted">active · v{active.version}</span>
          </div>
          {active.source_prompt && <p className="italic text-muted">“{active.source_prompt}”</p>}
          <Summary lines={active.summary} />
          <FlowGraph journey={active.definition} />
        </section>
      )}
    </>
  );
}

function Summary({ lines }: { lines: string[] }) {
  return <ol className="list-decimal space-y-1 pl-5 text-[0.9375rem] text-muted">{lines.map((l, i) => <li key={i}>{l}</li>)}</ol>;
}
