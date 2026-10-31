"use client";
import { useEffect, useState } from "react";
import { FlowGraph } from "@/components/FlowGraph";
import { api } from "@/lib/api";
import type { CompileResult, Journey } from "@/lib/types";

const card = "rounded-xl border border-line bg-panel p-4";

export default function JourneysPage() {
  const [active, setActive] = useState<Journey | null>(null);
  const [prompt, setPrompt] = useState("");
  const [draft, setDraft] = useState<CompileResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const load = () => api.journeys().then((j) => setActive(j[0] ?? null)).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function generate() {
    setBusy(true); setError(null); setDraft(null); setSaved(false);
    try { setDraft(await api.compileJourney(prompt)); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  async function save() {
    if (!draft?.definition) return;
    setBusy(true); setError(null);
    try {
      await api.saveJourney(draft.definition, active?.id ?? null, prompt);
      setSaved(true); setDraft(null); setPrompt(""); await load();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <section className="space-y-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Journeys</h1>
        <p className="text-sm text-muted">Describe what should happen after a checkout is abandoned. Runs already in progress keep the version they started on.</p>
      </div>

      {saved && <p className="rounded-md bg-accent/15 p-3 text-sm text-accent">Saved. New runs will use version {active?.version}.</p>}
      {error && <p className="rounded-md border border-line bg-panel p-3 text-sm text-rose-600">{error}</p>}

      <div className={card}>
        <h2 className="mb-2 text-sm font-semibold text-muted">New version from a description</h2>
        <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3}
          placeholder="e.g. Send a WhatsApp reminder, wait 20 minutes, then call once. Offer up to 5% off. If they don't pick up, give up."
          className="w-full rounded-lg border border-line bg-bg px-3 py-2 text-sm" />
        <button onClick={generate} disabled={busy || !prompt.trim()}
          className="mt-2 rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-bg disabled:opacity-50">
          {busy && !draft ? "Generating…" : "Generate journey"}</button>
      </div>

      {draft && (
        <div className={`${card} space-y-4`}>
          <h2 className="text-sm font-semibold text-muted">Draft</h2>
          {draft.definition ? (
            <>
              <Summary lines={draft.summary} />
              <FlowGraph journey={draft.definition} />
              <button onClick={save} disabled={busy} className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-bg disabled:opacity-50">
                Save as new version</button>
            </>
          ) : (
            <div className="text-sm">
              <p className="mb-1 font-medium">Couldn't produce a valid journey. Try rewording:</p>
              <ul className="list-disc pl-5 text-muted">{draft.errors.map((e) => <li key={e}>{e}</li>)}</ul>
            </div>
          )}
        </div>
      )}

      {active && (
        <div className={`${card} space-y-4`}>
          <h2 className="text-sm font-semibold text-muted">Active: {active.name} · v{active.version}</h2>
          {active.source_prompt && <p className="text-sm italic text-muted">“{active.source_prompt}”</p>}
          <Summary lines={active.summary} />
          <FlowGraph journey={active.definition} />
        </div>
      )}
    </section>
  );
}

function Summary({ lines }: { lines: string[] }) {
  return <ol className="list-decimal space-y-1 pl-5 text-sm">{lines.map((l, i) => <li key={i}>{l}</li>)}</ol>;
}
