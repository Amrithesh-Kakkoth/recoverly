import type { Call, CheckoutInput, CheckoutResult, DemoConfig, Journey, JourneyDefinition, CompileResult, Metrics, Run, RunDetail } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = body.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d?.errors) ? d.errors.join("; ")
      : `Request failed (${res.status}) — check the backend log`);
  }
  return body as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  journeys: () => request<Journey[]>("/api/journeys"),
  compileJourney: (prompt: string) => post<CompileResult>("/api/journeys/compile", { prompt }),
  saveJourney: (definition: JourneyDefinition, journey_id: number | null, source_prompt: string) =>
    post<{ journey_id: number; version_id: number }>("/api/journeys", { definition, journey_id, source_prompt }),
  metrics: () => request<Metrics>("/api/metrics"),
  runs: (limit = 50) => request<Run[]>(`/api/runs?limit=${limit}`),
  run: (id: number) => request<RunDetail>(`/api/runs/${id}`),
  call: (id: string) => request<Call>(`/api/calls/${encodeURIComponent(id)}`),
  demoConfig: () => request<DemoConfig>("/api/demo-config"),
  iceServers: () => request<{ iceServers: RTCIceServer[] }>("/api/ice"),
  checkout: (input: CheckoutInput) => post<CheckoutResult>("/shop/checkout", input),
  answerCall: (callId: string, sdp: string, type: string) =>
    post<{ sdp: string; type: RTCSdpType }>(`/api/calls/${encodeURIComponent(callId)}/offer`, { sdp, type }),
};
