import type { Call, Run, RunDetail } from "./types";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

export const api = {
  runs: (limit = 50) => get<Run[]>(`/api/runs?limit=${limit}`),
  run: (id: number) => get<RunDetail>(`/api/runs/${id}`),
  call: (id: string) => get<Call>(`/api/calls/${encodeURIComponent(id)}`),
};
