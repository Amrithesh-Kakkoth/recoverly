"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const primary = "h-11 cursor-pointer rounded-lg bg-ink px-4 font-semibold text-on-ink disabled:opacity-60";
const secondary = "h-11 cursor-pointer rounded-lg border border-line-strong bg-white px-4 font-semibold text-ink disabled:opacity-60";

export default function SettingsPage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { api.integrations().then((i) => setConnected(i.slack)).catch((e) => setError(e.message)); }, []);

  async function run(action: () => Promise<void>) {
    setBusy(true); setNotice(null); setError(null);
    try { await action(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  const connect = (e: React.FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.connectSlack(url);
      setConnected(true); setUrl("");
      setNotice("Slack is connected. Send a test message to check the channel.");
    });
  };
  const test = () => run(async () => { await api.testSlack(); setNotice("Test message sent. Check your Slack channel."); });
  const disconnect = () => run(async () => { await api.disconnectSlack(); setConnected(false); setNotice("Slack is disconnected."); });

  return (
    <>
      <h1 className="mb-8 text-[2.5rem] font-semibold leading-tight tracking-[-0.025em]">Settings</h1>
      <section aria-labelledby="slack-heading" className="max-w-[44rem] rounded-[0.625rem] border border-line bg-panel p-6">
        <div className="mb-2 flex flex-wrap items-baseline gap-x-3">
          <h2 id="slack-heading" className="text-2xl font-semibold tracking-[-0.015em]">Slack</h2>
          {connected !== null && <span className="text-sm text-muted">{connected ? "Connected" : "Not connected"}</span>}
        </div>
        <p className="mb-5 text-muted">Get a message in a channel whenever a recovery run ends, with the amount, the customer's name and a link to the run.</p>

        {connected === false && (
          <form onSubmit={connect}>
            <ol className="mb-5 list-decimal space-y-1 pl-5 text-[0.9375rem]">
              <li>Create a Slack app at <a className="link" href="https://api.slack.com/apps" target="_blank" rel="noopener">api.slack.com/apps</a>.</li>
              <li>Turn on <b>Incoming Webhooks</b> and add a webhook to your channel.</li>
              <li>Paste the webhook URL below.</li>
            </ol>
            <label className="flex flex-col gap-1.5 text-sm font-medium">Webhook URL
              <input type="password" required value={url} onChange={(e) => setUrl(e.target.value)} autoComplete="off" spellCheck={false}
                placeholder="https://hooks.slack.com/services/…" className="h-11 rounded-lg border border-line-strong bg-white px-3 text-base font-normal text-ink" />
            </label>
            <button disabled={busy} className={`${primary} mt-4`}>Connect Slack</button>
          </form>
        )}

        {connected === true && (
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={test} disabled={busy} className={primary}>Send a test message</button>
            <button type="button" onClick={disconnect} disabled={busy} className={secondary}>Disconnect</button>
          </div>
        )}

        {notice && <p role="status" className="mt-4 text-accent-strong">{notice}</p>}
        {error && <p role="alert" className="mt-4 text-[#7a3410]">{error}</p>}
      </section>
    </>
  );
}
