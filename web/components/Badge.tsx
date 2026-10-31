const STYLE: Record<string, [string, string]> = {
  in_call: ["On a call", "bg-ink text-white"],
  running: ["Running", "bg-[#e4e8e3] text-[#2e3a35]"],
  waiting: ["Waiting", "bg-[#e4e8e3] text-[#2e3a35]"],
  recovered: ["Recovered", "bg-[#cfebdd] text-accent-strong"],
  paid: ["Paid", "bg-[#cfebdd] text-accent-strong"],
  lost: ["Lost", "bg-[#f6e0d3] text-[#7a3410]"],
};

export function Badge({ children }: { children: string }) {
  const [label, tone] = STYLE[children.toLowerCase()] ?? [children.replaceAll("_", " "), "bg-[#e4e8e3] text-[#2e3a35]"];
  return <span className={`inline-block rounded-full px-2.5 py-0.5 text-[0.8125rem] font-medium leading-5 ${tone}`}>{label}</span>;
}
