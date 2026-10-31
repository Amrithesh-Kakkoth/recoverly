import type { JourneyDefinition, JourneyStep } from "@/lib/types";

const edges = (st: JourneyStep): [string | null, string][] => [
  ...Object.entries(st.next_by_outcome ?? {}).map(([o, t]): [string, string] => [o.replace("_", " "), t]),
  ...(st.next ? [[null, st.next] as [null, string]] : []),
  ...(st.default ? [["otherwise", st.default] as [string, string]] : []),
];

function detail(st: JourneyStep): string {
  if (st.type === "message") return `${st.channel} · ${st.template}`;
  if (st.type === "wait") return `up to ${st.duration}`;
  if (st.type === "call") return st.objective ?? "";
  return st.result ?? "";
}

/** Steps laid out in columns by distance from the start; each card lists where it goes next. */
export function FlowGraph({ journey }: { journey: JourneyDefinition }) {
  const depth: Record<string, number> = { [journey.start]: 0 };
  const queue = [journey.start];
  while (queue.length) {
    const id = queue.shift()!;
    for (const [, t] of edges(journey.steps[id] ?? { type: "end" })) {
      if (!(t in depth) && t in journey.steps) { depth[t] = depth[id] + 1; queue.push(t); }
    }
  }
  const cols: string[][] = [];
  for (const id of Object.keys(journey.steps)) (cols[depth[id] ?? 0] ??= []).push(id);
  const interrupts = journey.on_events.map((h) => `${h.event} → ${h.goto}`);

  return (
    <div>
      <div className="flex gap-4 overflow-x-auto pb-2">
        {cols.map((ids, i) => (
          <div key={i} className="flex min-w-48 flex-1 flex-col gap-3">
            {ids?.map((id) => {
              const st = journey.steps[id];
              return (
                <div key={id} className={`rounded-lg border bg-panel p-3 text-sm ${id === journey.start ? "border-accent" : "border-line"}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{id}</span>
                    <span className="text-xs uppercase tracking-wide text-muted">{st.type}</span>
                  </div>
                  <div className="mt-1 text-muted">{detail(st)}</div>
                  <ul className="mt-2 space-y-0.5 text-xs">
                    {edges(st).map(([label, to], k) => (
                      <li key={k} className="text-accent">{label ? `${label} → ` : "→ "}{to}</li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        ))}
      </div>
      {interrupts.length > 0 && <p className="mt-2 text-xs text-muted">From any step: {interrupts.join(" · ")}</p>}
    </div>
  );
}
