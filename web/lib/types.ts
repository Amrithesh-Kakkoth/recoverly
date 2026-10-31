// Mirrors the dicts built in backend/app/api/runs.py and calls.py.
export type RunStatus = string;

export interface Run {
  id: number;
  customer_id: string;
  family_id: string;
  status: RunStatus;
  cursor: string | null;
  close_reason: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface TimelineEvent {
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  ts: string | null;
}

export interface Message {
  id: number;
  run_id: number | null;
  channel: string;
  body: string;
  status?: string;
  created_at?: string | null;
}

export interface RunDetail extends Run {
  timeline: TimelineEvent[];
  messages: Message[];
  last_event_id: number;
}

export interface TranscriptTurn {
  role?: string;
  text?: string;
  content?: string;
  [key: string]: unknown;
}

export interface Call {
  id: string;
  status: string;
  transcript: TranscriptTurn[];
  tool_calls: Record<string, unknown>[];
  voice_to_voice_ms: number[];
  outcome?: string | null;
  summary?: string | null;
  overridden_by?: string | null;
}
