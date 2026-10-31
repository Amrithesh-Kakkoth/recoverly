export const fmtTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";

export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";

export const fmtMoney = (amount: string, currency: string | null) =>
  new Intl.NumberFormat([], { style: "currency", currency: currency ?? "USD" }).format(Number(amount));

export const fmtDuration = (secs: number | null) =>
  secs === null ? "—" : secs < 60 ? `${Math.round(secs)}s` : secs < 3600 ? `${Math.round(secs / 60)}m` : `${(secs / 3600).toFixed(1)}h`;
