export const fmtTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";

export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

export const fmtMoney = (amount: string, currency: string | null) =>
  new Intl.NumberFormat([], { style: "currency", currency: currency ?? "USD", currencyDisplay: "narrowSymbol" }).format(Number(amount));

export const fmtDuration = (secs: number | null) =>
  secs === null ? "—" : secs < 60 ? `${Math.round(secs)}s` : secs < 3600 ? `${Math.round(secs / 60)}m` : `${(secs / 3600).toFixed(1)}h`;

export const channelName = (c: string) => (c === "whatsapp" ? "WhatsApp" : c === "web_inbox" ? "Web inbox" : c);

const LABEL: Record<string, (p: Record<string, any>) => string> = {
  "run.started": () => "Journey started",
  "message.sent": (p) => `Message sent (${channelName(p.channel)})`,
  "wait.started": () => "Waiting before the next step",
  "call.dialed": () => "Calling the customer",
  "call.deferred": () => "Call deferred (outside the call window)",
  "call.skipped": (p) => `Call skipped (${p.reason})`,
  "call.retry_scheduled": () => "No answer, will retry",
  "call.completed": (p) => `Call finished: ${String(p.outcome).replaceAll("_", " ")}`,
  "event.payment_captured": (p) => `PayPal captured $${p.amount}, sent into the call`,
  "run.ended": (p) => `Journey ended: ${p.result}`,
};

/** Human wording for a timeline event; null for internal steps the reader doesn't need. */
export const timelineLabel = (kind: string, payload: Record<string, unknown>) => LABEL[kind]?.(payload) ?? null;
