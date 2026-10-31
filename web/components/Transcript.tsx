import type { TranscriptTurn } from "@/lib/types";

/** The conversation, with each PayPal event shown at the exact moment it reached the agent. */
export function Transcript({ turns, you = "Customer" }: { turns: TranscriptTurn[]; you?: string }) {
  return (
    <div className="flex flex-col gap-4 leading-normal">
      {turns.map((t, i) => t.role === "event" ? (
        <p key={i} className="rounded-lg bg-paypal px-3.5 py-2.5 font-mono text-sm text-white">
          PayPal · {String(t.text ?? "").replace(/^\[PAYPAL EVENT\]\s*/, "")}
        </p>
      ) : (
        <div key={i} className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3">
          <span className="pt-0.5 text-sm text-muted">{t.role === "user" ? you : "Agent"}</span>
          <span>{String(t.text ?? t.content ?? "")}</span>
        </div>
      ))}
    </div>
  );
}
