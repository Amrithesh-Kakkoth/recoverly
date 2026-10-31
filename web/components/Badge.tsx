const TONE: Record<string, string> = {
  waiting: "bg-sky-500/15 text-sky-700 dark:text-sky-300",
  in_call: "bg-violet-500/15 text-violet-700 dark:text-violet-300",
  done: "bg-black/5 text-muted dark:bg-white/10",
  running: "bg-amber-500/15 text-amber-700 dark:text-amber-300",
  recovered: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  paid: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
  lost: "bg-rose-500/15 text-rose-700 dark:text-rose-300",
};

export function Badge({ children }: { children: string }) {
  const tone = TONE[children.toLowerCase()] ?? "bg-black/5 text-muted dark:bg-white/10";
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>{children.replace("_", " ")}</span>;
}
