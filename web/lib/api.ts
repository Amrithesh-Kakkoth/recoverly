import type { Call, CheckoutInput, CheckoutResult, CompileResult, DemoConfig, Journey, JourneyDefinition, Merchant, Metrics, Run, RunDetail } from "./types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

function message(detail: unknown, status: number): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg.replace(/^Value error, /, "");
  const errors = (detail as { errors?: string[] } | undefined)?.errors;
  return Array.isArray(errors) ? errors.join("; ") : `Request failed (${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(message(body.detail, res.status), res.status);
  return body as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body ?? {}) });

/** Try it visitors have no account: their checkout's family id is what lets them see that one run. */
const asVisitor = (family?: string) => (family ? `?family=${encodeURIComponent(family)}` : "");

export const api = {
  me: () => request<Merchant>("/api/auth/me"),
  signup: (email: string, password: string, store_name: string) => post<Merchant>("/api/auth/signup", { email, password, store_name }),
  login: (email: string, password: string) => post<Merchant>("/api/auth/login", { email, password }),
  logout: () => post<{ ok: boolean }>("/api/auth/logout"),
  journeys: () => request<Journey[]>("/api/journeys"),
  compileJourney: (prompt: string) => post<CompileResult>("/api/journeys/compile", { prompt }),
  saveJourney: (definition: JourneyDefinition, journey_id: number | null, source_prompt: string) =>
    post<{ journey_id: number; version_id: number }>("/api/journeys", { definition, journey_id, source_prompt }),
  metrics: () => request<Metrics>("/api/metrics"),
  runs: (limit = 50) => request<Run[]>(`/api/runs?limit=${limit}`),
  run: (id: number, family?: string) => request<RunDetail>(`/api/runs/${id}${asVisitor(family)}`),
  call: (id: string, family?: string) => request<Call>(`/api/calls/${encodeURIComponent(id)}${asVisitor(family)}`),
  demoConfig: () => request<DemoConfig>("/api/demo-config"),
  iceServers: () => request<{ iceServers: RTCIceServer[] }>("/api/ice"),
  checkout: (input: CheckoutInput) => post<CheckoutResult>("/shop/checkout", input),
  runForCheckout: (family: string) => request<{ run_id: number | null }>(`/shop/runs/${encodeURIComponent(family)}`),
  answerCall: (callId: string, sdp: string, type: string, family?: string) =>
    post<{ sdp: string; type: RTCSdpType }>(`/api/calls/${encodeURIComponent(callId)}/offer${asVisitor(family)}`, { sdp, type }),
};
