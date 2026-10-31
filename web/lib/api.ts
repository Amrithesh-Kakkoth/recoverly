import type { Call, CheckoutInput, CheckoutResult, DemoConfig, Run, RunDetail } from "./types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : `Request failed (${res.status}) — check the backend log`);
  return body as T;
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });

export const api = {
  runs: (limit = 50) => request<Run[]>(`/api/runs?limit=${limit}`),
  run: (id: number) => request<RunDetail>(`/api/runs/${id}`),
  call: (id: string) => request<Call>(`/api/calls/${encodeURIComponent(id)}`),
  demoConfig: () => request<DemoConfig>("/api/demo-config"),
  iceServers: () => request<{ iceServers: RTCIceServer[] }>("/api/ice"),
  checkout: (input: CheckoutInput) => post<CheckoutResult>("/shop/checkout", input),
  answerCall: (callId: string, sdp: string, type: string) =>
    post<{ sdp: string; type: RTCSdpType }>(`/api/calls/${encodeURIComponent(callId)}/offer`, { sdp, type }),
};
