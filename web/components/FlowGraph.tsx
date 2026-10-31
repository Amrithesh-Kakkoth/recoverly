import type { JourneyDefinition, JourneyStep } from "@/lib/types";

const edges = (st: JourneyStep): [string | null, string][] => [
  ...Object.entries(st.next_by_outcome ?? {}).map(([o, t]): [string, string] => [o.replaceAll("_", " "), t]),
  ...(st.next ? [[null, st.next] as [null, string]] : []),
  ...(st.default ? [["otherwise", st.default] as [string, string]] : []),
];

function detail(st: JourneyStep): string {
  if (st.type === "message") return `${st.channel} · ${st.template}`;
  if (st.type === "wait") return `Up to ${st.duration}`;
  if (st.type === "call") return st.objective ?? "";
  return `Closes the run as ${st.result}`;
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
      <div className="flex gap-3 overflow-x-auto pb-2">
        {cols.map((ids, i) => (
          <div key={i} className="flex min-w-[12.5rem] flex-1 flex-col gap-3">
            {ids?.map((id) => {
              const st = journey.steps[id];
              return (
                <div key={id} className={`flex flex-col gap-2 rounded-[0.625rem] border bg-panel p-4 ${id === journey.start ? "border-ink" : "border-line"}`}>
                  <span className="font-mono text-xs capitalize text-muted">{st.type}</span>
                  <span className="text-[1.0625rem] font-semibold">{id}</span>
                  <span className="text-[0.9375rem] leading-snug text-muted">{detail(st)}</span>
                  <ul className="mt-auto pt-2 text-[0.8125rem] text-accent-strong">
                    {edges(st).map(([label, to], k) => <li key={k}>{label ? `${label}: ` : "Next: "}{to}</li>)}
                  </ul>
                </div>
              );
            })}
          </div>
        ))}
      </div>
      {interrupts.length > 0 && <p className="mt-2 text-sm text-muted">From any step: {interrupts.join(" · ")}</p>}
    </div>
  );
}
